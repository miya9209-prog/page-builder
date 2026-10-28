import base64
import io
import json
import mimetypes
import re
import time
from typing import Any, Dict, List

import streamlit as st
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from openai import OpenAI, RateLimitError

from quality_engine import (TIP_PROFILES, fact_report, check_quality,
                            normalize_generated_strict, natural_wrap)

st.set_page_config(page_title="PAGE BUILDER", layout="wide")

# ─────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────
for key, default in [
    ("reset_nonce", 0),
    ("naming_result", ""),
    ("naming_input_value", ""),
    ("generated_result", ""),
    ("generated_docx", b""),
    ("generated_file_stem", "page_builder"),
]:
    if key not in st.session_state:
        st.session_state[key] = default

st.markdown(
    "<style>div[data-testid='stButton'] > button { min-height: 42px; }</style>",
    unsafe_allow_html=True,
)

st.title("MISHARP PAGE BUILDER")
st.caption("구매전환율 상승을 위한 상세페이지 기획 + 상품 원고 생성기")

api_key = st.secrets.get("OPENAI_API_KEY", "")
if not api_key:
    st.warning("OPENAI_API_KEY가 설정되지 않았습니다. Streamlit Cloud Secrets 또는 .streamlit/secrets.toml을 확인해 주세요.")
    st.stop()

client = OpenAI(api_key=api_key)

# ─────────────────────────────────────────────
# 고정 HTML 헤더
# ─────────────────────────────────────────────
FIXED_HTML_HEAD = (
    '<meta http-equiv="X-UA-Compatible" content="IE=edge,chrome=1">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    '<link href="http://fonts.googleapis.com/css?family=Roboto" rel="stylesheet" type="text/css">\n'
    '<link href="http://netdna.bootstrapcdn.com/font-awesome/4.3.0/css/font-awesome.min.css" rel="stylesheet" type="text/css">\n'
    '<link href="/SRC2/cssmtmenu/style.css" rel="stylesheet" type="text/css">\n'
    '<link href="//spoqa.github.io/spoqa-han-sans/css/SpoqaHanSans-kr.css" rel="stylesheet" type="text/css">\n'
    '<link href="//misharp.co.kr/subtap.css" rel="stylesheet" type="text/css">'
)


DIVIDER_MARKER = "────────────────────────────────────────"

def add_blue_divider(doc):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "12")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "2F6DF6")
    pBdr.append(bottom)
    pPr.append(pBdr)
    run = p.add_run(" ")
    run.font.name = "Dotum"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "돋움")
    run.font.size = Pt(10)

NAME_PROMPT = (
    "너는 4050 여성 패션 쇼핑몰 미샵의 상품 네이밍 전문가다.\n"
    "- 상품 주요 특징을 반영해 상품명을 20개 제안한다.\n"
    "- 각 상품명은 공백 포함 최대 18자 이내.\n"
    "- 반드시 단어와 단어 사이를 자연스럽게 띄어쓴다.\n"
    "- AI 검색, 키워드 검색 모두 고려한다.\n"
    "- 디테일/형태/원단/핏 등을 반영한 단어 + 카테고리명을 포함한다.\n"
    "- 필요하면 세련되고 여성스러운 단어를 앞에 붙여도 된다.\n"
    "- 번호, 설명, 코드펜스 없이 한 줄에 하나씩 20개만 출력한다."
)


# ─────────────────────────────────────────────
# 유틸 함수
# ─────────────────────────────────────────────
def chat_with_retry(*, model, messages, temperature=0.3, max_retries=2):
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return client.chat.completions.create(
                model=model, messages=messages, temperature=temperature
            )
        except RateLimitError as exc:
            last_exc = exc
            if attempt >= max_retries:
                raise
            time.sleep(2 * (attempt + 1))
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries:
                raise
            time.sleep(1 * (attempt + 1))
    raise last_exc


def file_to_content_item(uploaded_file):
    mime = uploaded_file.type or mimetypes.guess_type(uploaded_file.name)[0] or "image/jpeg"
    b64 = base64.b64encode(uploaded_file.read()).decode("utf-8")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def extract_lines_with_digits(text):
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line and re.search(r"\d", line):
            out.append(line)
    return out


def combine_measurements(top, bottom, dress):
    lines = []
    for block in [top, bottom, dress]:
        lines.extend(extract_lines_with_digits(block))
    return lines


def count_colors(color_text):
    if not color_text.strip():
        return 0
    # 슬래시·쉼표로 먼저 분리
    text = color_text.replace(" / ", "\n").replace("/", "\n").replace(",", "\n")
    result = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # "1 블랙 2 네이비 3 베이지" 처럼 숫자가 구분자인 경우 각각 분리
        sub = re.split(r"(?=\s*\d+\s+[가-힣a-zA-Z])", line)
        for s in sub:
            s = re.sub(r"^\s*\d+\s*", "", s).strip()
            if s:
                result.append(s)
    return len(result) if result else 0


def apply_color_count_to_name(product_name, color_text):
    count = count_colors(color_text)
    suffix = f"({count} color)" if count > 0 else "(color)"
    name = (product_name or "").strip()
    name = re.sub(r"\(\s*\d+\s*color\s*\)", suffix, name, flags=re.I)
    name = re.sub(r"\(\s*color\s*\)", suffix, name, flags=re.I)
    return name


def clean_line(line):
    line = (line or "").strip()
    line = re.sub(r"^[\-\u2022\u25aa\u29bf\s]+", "", line)
    line = re.sub(r"\s+", " ", line).strip()
    # ",." 중복 패턴 정리
    line = re.sub(r",\.+", ".", line)
    return line


def ensure_period(line):
    """마침표로 끝나게 보장. 쉼표/쉼표+마침표로 끝나는 경우도 정리."""
    line = clean_line(line)
    if not line:
        return ""
    # 쉼표+마침표 중복 제거: ",." → "."
    line = re.sub(r",\.+$", ".", line)
    # 쉼표로만 끝나는 경우: 쉼표 제거 후 마침표
    if line.endswith(","):
        line = line[:-1].rstrip()
    if re.search(r"[.!?\u2026]$", line):
        return line
    return line + "."


def format_measurement_lines(lines):
    if not lines:
        return "실측사이즈 정보를 입력해 주세요."
    formatted = []
    for line in lines:
        line = re.sub(r"\s+단위:cm$", "", line).strip()
        for label in ["XL", "L", "M", "S", "F"]:
            line = re.sub(rf"\s+{label}\s+", f"<br>{label} ", line)
        line = re.sub(r"\s+", " ", line)
        formatted.append(line)
    return "<br>".join(formatted) + " (단위: cm)"


def format_material_line(material):
    mat = (material or "").strip()
    return mat



def result_to_docx_bytes(result_text):
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Dotum"
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "돋움")
    style.font.size = Pt(10)
    style.paragraph_format.space_before = Pt(0)
    style.paragraph_format.space_after = Pt(0)
    style.paragraph_format.line_spacing = 1.5

    def add_plain_paragraph(text=""):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.5
        run = p.add_run(text)
        run.font.name = "Dotum"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "돋움")
        run.font.size = Pt(10)
        return p

    for line in result_text.splitlines():
        if line.strip() == DIVIDER_MARKER:
            add_plain_paragraph("")
            add_plain_paragraph("")
            add_blue_divider(doc)
            add_plain_paragraph("")
            add_plain_paragraph("")
            continue
        add_plain_paragraph(line)

    bio = io.BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio.getvalue()

def reset_all():
    st.session_state.reset_nonce += 1
    st.session_state.naming_result = ""
    st.session_state.naming_input_value = ""
    st.session_state.generated_result = ""
    st.session_state.generated_docx = b""
    st.session_state.generated_file_stem = "page_builder"


# ─────────────────────────────────────────────
# JSON 파싱
# ─────────────────────────────────────────────
def extract_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("JSON 응답을 찾지 못했습니다.")
    return json.loads(m.group(0))


# ─────────────────────────────────────────────
# 프롬프트 빌더
# ─────────────────────────────────────────────
def build_generation_prompt(data, additional_request):
    """상품 근거 중심 초안. 분량을 강제로 줄여 정보가 누락되지 않도록 한다."""
    fields = {
        "상품명": data.get("display_name", ""),
        "컬러": data.get("color", ""),
        "사이즈": data.get("size", ""),
        "소재": data.get("material", ""),
        "소재설명": data.get("material_desc_raw", ""),
        "디테일 특징": data.get("detail_tip", ""),
        "핏·실루엣": data.get("fit", ""),
        "주요 어필 포인트": data.get("appeal_points", ""),
        "기타 특징": data.get("etc", ""),
        "타겟": data.get("target", ""),
        "세탁방법": data.get("washing", ""),
        "실측사이즈": data.get("measurement_lines", []),
        "추가 요청": additional_request or "없음",
    }
    raw = json.dumps(fields, ensure_ascii=False, indent=2)
    profiles = "; ".join(TIP_PROFILES.values())
    return f"""당신은 미샵(MISHARP)의 4050 여성 패션 상세페이지를 작성하는 전문 MD 카피라이터입니다.
이번 작업은 문장 수 채우기가 아니라, 입력된 한 상품의 구매 이유를 고객이 이해하도록 정확하고 풍부하게 설명하는 것입니다.

[이번 상품에 대해 확인된 입력값]
{raw}

[상품 고유 정보를 빠뜨리지 않기 위한 체크리스트]
{fact_report(data, additional_request)}

[작성 순서]
1. 입력에서 증명되는 상품 특징/소재/장점/주의사항을 머릿속에 정리하세요.
2. 겉보기에 그럴듯한 일반론 대신 '어떤 디테일이 고객의 어떤 불편을 해소하는지' 근거를 연결하세요.
3. 입력된 디테일, 핏, 주요 어필 포인트를 MD원고에 골고루 배치하세요. 특정 내용만 반복하거나 누락하지 마세요.
4. 고객이 실제로 궁금해할 사이즈·소재·관리·코디 질문을 구체적으로 다루세요.
5. 불확실한 내용을 지어내지 마세요. 사진에 없거나 입력되지 않은 소재 비율, 제조 방식, 안감, 비침 없음, 건조기 가능, 제작사, 실제 착용 후기 등을 단정하면 안 됩니다.
6. 실측 숫자와 혼용률이 입력됐다면 정확히 유지하세요. 입력에 없는 실측 수치를 쓰지 마세요.
7. 다른 상품에서 가져온 내용, 템플릿용 고정 상품 문구, 근거 없는 장점은 절대 넣지 마세요.
8. 입력 문장을 그대로 복사하지 말고, 그 의미를 유지하며 자연스럽게 재구성하세요.

[문장 품질]
- MD원고는 4개 소제목, 각 영역에 해당하는 풍부하고 구체적인 문단 3~5개로 작성합니다. 영역별 본문은 공백 포함 115~220자 정도를 목표로 합니다.
- 이 단계에서 한 줄 20~24자에 억지로 맞추지 마세요. 출력 함수가 자연스럽게 줄바꿈합니다. 의미와 문장 흐름이 우선입니다.
- 각 영역의 문장은 전개가 자연스럽고 반복 없이 구체적이어야 합니다. '다양한 활용이 가능합니다' 같은 빈 문구로 채우지 마세요.
- choice: 다른 상품과의 차이·선택 이유. fabric: 실제 혼용 소재/촉감/두께 (입력 근거 있을 때만). fit: 체형, 사이즈, 실측. occasion: 구체적인 코디와 착용 장면.
- 추천문장 4개는 모두 자연스러운 '~분'으로 끝납니다. '분께', '추천합니다', '권해드립니다', '입니다 분' 금지. 각기 다른 구매 니즈를 제시하세요.
- review_lines 4개는 입을 때 확인할 포인트를 자연스러운 친근한 톤으로 작성하세요. 실제 직원/모델이 직접 착용했다는 근거가 없으면 가짜 경험담이나 인용을 꾸며내지 마세요.
- FAQ 4개는 입력 상품에 맞는 현실적인 구매 장애 요인과 근거 있는 답변으로 작성하세요. 모르면 모른다고 하거나 실측 확인을 안내하세요.
- 소재설명 3문장은 소재·조직·특성을 가급적 구체적으로 설명하되 확인되지 않은 기능은 주장하지 마세요.
- 사이즈팁: {profiles}. 각 사이즈별로 이 수치가 가리키는 체형 차이와 상품의 실제 핏 정보를 고려한 2문장. 특정 체형에 무조건 잘 맞는다거나 극적인 커버 효과를 확정하지 마세요. 입력 실측이 부족하면 개인차/실측 확인을 안내하세요.
- '쇼핑에 꼭 참고하세요', '[구매 전 꼭 확인해 주세요]', 마무리 인사 등은 작성·출력하지 않습니다.

[JSON 형식 — 코드펜스/설명 없이 객체 하나만]
{{
 "material_desc_lines": ["충분히 구체적인 완결 문장 1", "완결 문장 2", "완결 문장 3"],
 "recommend_lines": ["고유 장점을 찾으시는 분", "특징을 원하는 분", "착용감을 중요하게 생각하시는 분", "실용성을 찾으시는 분"],
 "review_lines": ["근거 있는 관찰 포인트 1", "2", "3", "4"],
 "faqs": [{{"q":"Q. 실제 구매 질문 1", "a":"A. 입력을 근거로 한 답변 1"}}, {{"q":"Q. 실제 구매 질문 2", "a":"A. 답변 2"}}, {{"q":"Q. 실제 구매 질문 3", "a":"A. 답변 3"}}, {{"q":"Q. 실제 구매 질문 4", "a":"A. 답변 4"}}],
 "md_sections": {{"choice":["정보가 풍부한 문단 1", "문단 2", "문단 3"], "fabric":["문단 1", "문단 2", "문단 3"], "fit":["문단 1", "문단 2", "문단 3"], "occasion":["문단 1", "문단 2", "문단 3"]}},
 "size_tips": {{"55":["문장 1", "문장 2"], "66":["문장 1", "문장 2"], "66half":["문장 1", "문장 2"], "77":["문장 1", "문장 2"]}}
}}
"""


# ─────────────────────────────────────────────
# LLM 생성
# ─────────────────────────────────────────────
def generate_structured_copy(data, additional_request, uploaded_images):
    """초안 생성 후 상품정보 충실도 재검토. 부실 원고를 범용 문장으로 메우지 않음."""
    prompt = build_generation_prompt(data, additional_request)
    user_content = [{"type": "text", "text": prompt}]
    for img in (uploaded_images[:5] if uploaded_images else []):
        user_content.append(file_to_content_item(img))

    messages = [
        {"role": "system", "content": "확인된 상품 정보만으로 한국어 커머스 카피를 작성하세요. JSON 객체만 반환하세요. 근거 없는 정보는 절대 추측하지 않습니다."},
        {"role": "user", "content": user_content},
    ]
    first = chat_with_retry(model="gpt-4o", messages=messages, temperature=0.45, max_retries=2)
    raw = extract_json(first.choices[0].message.content)
    issues = check_quality(raw, data, additional_request)

    # 수정 포인트가 없더라도 한 번 MD 편집 검수를 수행해 형식만 맞춘 싱거운 원고를 걸러낸다.
    editor_instructions = (
        "다음 상품에 대한 초안을 실무자가 바로 사용할 수준으로 꼼꼼히 편집하세요. "
        "반드시 원래 JSON의 동일한 키/개수를 유지하세요. "
        "구체적 디테일·소재·핏·어필 포인트가 누락된 곳을 보강하고, 반복되는 범용 표현과 과장·허위 경험담을 제거하세요. "
        "특히 md_sections 4개 영역 각각 3~5개 문단, 내용 총 115자 이상이 되게 작성하세요. "
        "리스트 문장과 사이즈팁의 정확성도 확인하세요. "
        "모르는 사실은 만들지 말고 입력값만 사용하세요. JSON 객체만 답하세요."
    )
    if issues:
        editor_instructions += "\n[실제 검사에서 발견된 문제]\n" + "\n".join("- " + x for x in issues)
    audit = [
        {"role": "system", "content": editor_instructions},
        {"role": "user", "content": "[이 상품 입력 정보]\n" + prompt + "\n[검토·개선할 초안 JSON]\n" + json.dumps(raw, ensure_ascii=False)},
    ]
    try:
        revised_result = chat_with_retry(model="gpt-4o", messages=audit, temperature=0.25, max_retries=1)
        revised = extract_json(revised_result.choices[0].message.content)
        revised_issues = check_quality(revised, data, additional_request)
        if not revised_issues:
            return revised
        # 검수 모델이 더 나쁜 답을 냈다면 원본이 유효할 때는 원본을 사용한다.
        if not issues:
            return raw
        raise ValueError("작성 품질 검증 미통과: " + " / ".join(revised_issues[:5]))
    except RateLimitError:
        if not issues:
            return raw
        raise
    except (ValueError, json.JSONDecodeError) as exc:
        if not issues:
            return raw
        raise ValueError("원고 재검토에도 미흡한 항목이 남아 있습니다. " + str(exc)) from exc


# ─────────────────────────────────────────────
# 폴백 데이터
# ─────────────────────────────────────────────
def fallback_structured(data):
    product = data.get("display_name") or "상품"
    size = clean_line(data.get("size") or "FREE 사이즈로 77까지 추천드립니다.")
    material_desc_raw = data.get("material_desc_raw") or ""
    raw_lines = [x.strip() for x in material_desc_raw.replace("\r", "").split("\n") if x.strip()]
    material_lines = [ensure_period(clean_line(x)) for x in raw_lines[:3]]
    if not material_lines:
        material_lines = [
            "부드러운 터치감으로 피부에 닿는 느낌이 편안한 소재입니다.",
            "표면감이 차분하게 정리되어 데일리로 활용하기 좋습니다.",
            "관리 부담이 크지 않아 손이 자주 가는 아이템입니다.",
        ]

    return {
        "material_desc_lines": material_lines,
        "recommend_lines": [
            "출근룩부터 모임룩까지 단정하게 입을 아이템을 찾으시는 분",
            "상체 라인을 부담 없이 정리해 주는 편안한 핏을 원하시는 분",
            "소재감이 주는 고급스러운 분위기를 중요하게 생각하시는 분",
            "데님, 슬랙스, 스커트와 두루 잘 어울리는 상의를 찾으시는 분",
        ],
        "review_lines": [
            "입었을 때 전체 실루엣이 차분하게 정리돼서 손이 자주 가요.",
            "촉감이 부담스럽지 않아 하루 종일 입어도 편안한 느낌이에요.",
            "격식 있는 자리에도 과하지 않게 잘 어울려 활용도가 높아요.",
            "구김 부담이 크지 않아 바쁜 날에도 깔끔하게 입기 좋았어요.",
        ],
        "faqs": [
            {"q": "Q. 가슴이 있는 77 체형도 답답하지 않게 착용할 수 있을까요?", "a": "A. " + size + " 기준으로 안내드리며, 여유 있게 착용하실 수 있도록 설계되어 있습니다. 실측사이즈를 함께 확인하시면 더 정확합니다."},
            {"q": "Q. 밝은 컬러는 비침이 심한 편인가요?", "a": "A. 밝은 컬러 계열은 약간의 비침이 있을 수 있어 스킨톤 이너와 함께 착용하시면 더 안정감 있게 입으실 수 있습니다."},
            {"q": "Q. 하루 종일 입으면 구김이 많이 남는 편인가요?", "a": "A. 소재 특성상 비교적 구김이 적어 출근룩이나 모임룩으로도 부담 없이 입기 좋은 편입니다."},
            {"q": "Q. 세탁은 어떻게 하면 좋을까요?", "a": "A. " + ensure_period(clean_line(data.get("washing") or "드라이클리닝, 단독 울세탁, 손세탁 권장. 건조기 사용 금지"))},
        ],
        "shopping_lines": [
            size,
            "밝은 컬러 계열은 스킨톤 이너와 함께 착용하시면 더 안정감 있게 연출하실 수 있습니다.",
            "실측사이즈를 함께 확인하시면 원하는 핏으로 선택하시기 더 수월합니다.",
        ],
        "md_sections": {
            "choice": [
                product + "은 과하지 않으면서도 차분하고 세련된 인상을 만들어 줍니다.",
                "기본에 가까운 디자인일수록 소재와 핏의 차이가 크게 드러나는데, 이 아이템은 그 균형감이 특히 좋습니다.",
                "체형을 부드럽게 감싸주는 실루엣이 안정감 있게 느껴집니다.",
                "데일리와 격식을 오가는 장면에서 활용도가 높아 추천드리기 좋습니다.",
            ],
            "fabric": material_lines + ["두께감 또한 과하게 무겁지 않아 계절감에 맞춰 손쉽게 매치하기 좋습니다."],
            "fit": [
                size + " 기준으로 안내드리며, 전체적으로 답답하지 않게 착용하기 좋은 편입니다.",
                "어깨선과 품이 과하게 붙지 않아 상체 라인이 비교적 편안해 보입니다.",
                "실루엣이 과하게 흐트러지지 않아 단정한 분위기를 유지하기 좋습니다.",
                "실측사이즈를 함께 확인하시면 원하는 핏으로 선택하시기 더 수월합니다.",
            ],
            "occasion": [
                "출근룩처럼 단정함이 필요한 날에도 무리 없이 입기 좋습니다.",
                "모임이나 식사 자리처럼 차려입은 느낌이 필요한 순간에도 자연스럽게 어울립니다.",
                "데님, 슬랙스, 스커트와 두루 매치하기 쉬워 코디 폭이 넓습니다.",
                "아우터 안에 받쳐 입거나 단독으로 연출해도 분위기가 흐트러지지 않습니다.",
            ],
            "purchase_note": [],
            "ending": [],
        },
        "size_tips": {
            "55": [
                "여유 있는 핏으로 루즈하지 않게 자연스럽게 떨어져 단정한 실루엣을 연출합니다.",
                "소매와 어깨선이 부드럽게 정리되어 슬림한 체형에도 밋밋하지 않게 어울립니다.",
            ],
            "66": [
                "품과 실루엣에 적당한 여유가 있어 편안하게 착용하기 좋습니다.",
                "힙을 덮는 기장과 안정감 있는 핏으로 체형 커버 효과를 자연스럽게 느끼실 수 있습니다.",
            ],
            "66half": [
                "상체를 편안하게 감싸주어 답답함 없이 착용하기 좋습니다.",
                "어깨와 팔 라인이 자연스럽게 정리되어 군살을 부드럽게 커버해 줍니다.",
            ],
            "77": [
                "상체에 여유가 필요한 체형도 편안하게 입을 수 있을 만큼 넉넉한 핏입니다.",
                "가슴과 어깨가 있는 체형도 부해 보이지 않게 정돈된 실루엣으로 연출됩니다.",
            ],
        },
    }


# ─────────────────────────────────────────────
# 추천 문장 정규화 (핵심 안전장치)
# ─────────────────────────────────────────────
def normalize_recommend_line(x):
    """
    추천 문장이 반드시 '분'으로 끝나도록 보장.
    이중 '분' 방지, 금지 서술형 제거.
    """
    x = clean_line(x)
    # 마침표 제거
    x = x.rstrip(".")
    # 이미 '분'으로 끝나면 그대로
    if x.endswith("분"):
        return x
    # 금지 서술형 어미 제거
    x = re.sub(r"(추천합니다|권해드립니다|적합합니다|잘 어울립니다|좋습니다|만족하실)$", "", x).strip()
    x = x.rstrip(".")
    if x.endswith("분"):
        return x
    return x + " 분"


def normalize_review_line(x):
    """후기 문장에서 따옴표 제거 (렌더 단계에서 붙임)."""
    x = clean_line(x)
    # 다양한 따옴표 제거
    x = x.replace('"', "").replace("\u201c", "").replace("\u201d", "").strip()
    return x


def normalize_faq(faq_raw, fallback):
    out = []
    for item in (faq_raw if isinstance(faq_raw, list) else []):
        if not isinstance(item, dict):
            continue
        q = clean_line(item.get("q", ""))
        a = clean_line(item.get("a", ""))
        if not q or not a:
            continue
        # Q./A. 중복 제거 후 정규화
        q = re.sub(r"^Q\.\s*Q\.", "Q.", q.strip())
        a = re.sub(r"^A\.\s*A\.", "A.", a.strip())
        if not q.startswith("Q."):
            q = "Q. " + q.lstrip("Q.").strip()
        if not a.startswith("A."):
            a = "A. " + a.lstrip("A.").strip()
        out.append({"q": q, "a": a})
        if len(out) >= 4:
            break
    for fb in fallback:
        if len(out) >= 4:
            break
        if all(fb["q"] != x["q"] for x in out):
            out.append(fb)
    return out[:4]


def safe_lines(raw, count, fallback):
    """일반 필드용: LLM 결과가 count보다 부족하면 폴백으로 보충."""
    items = [clean_line(x) for x in (raw if isinstance(raw, list) else []) if clean_line(x)]
    if len(items) < count:
        for fb in fallback:
            c = clean_line(fb)
            if c and c not in items:
                items.append(c)
            if len(items) >= count:
                break
    return items[:count]


def safe_md_lines(raw, fallback):
    """MD원고 전용: LLM이 생성한 줄만 사용. 아예 없을 때만 폴백 전체 사용. 폴백 혼합 없음."""
    def fix_md_line(x):
        x = clean_line(x)
        # 쉼표로 끝나는 줄: 쉼표 제거 (다음 줄과 이어지는 연결줄은 마침표 없이 그대로)
        if x.endswith(","):
            x = x[:-1].rstrip()
        # ",." 중복 패턴 제거
        x = re.sub(r",\.+$", ".", x)
        return x

    items = [fix_md_line(x) for x in (raw if isinstance(raw, list) else []) if clean_line(x)]
    items = [x for x in items if x]  # 빈 줄 제거
    if not items:
        return [clean_line(x) for x in fallback if clean_line(x)]
    return items


def normalize_generated(result, data):
    fb = fallback_structured(data)

    material_desc_lines = [ensure_period(x) for x in safe_lines(result.get("material_desc_lines"), 3, fb["material_desc_lines"])]
    recommend_lines = [normalize_recommend_line(x) for x in safe_lines(result.get("recommend_lines"), 4, fb["recommend_lines"])]
    review_lines = [normalize_review_line(x) for x in safe_lines(result.get("review_lines"), 4, fb["review_lines"])]
    faqs = normalize_faq(result.get("faqs"), fb["faqs"])
    shopping_lines = [ensure_period(x) for x in safe_lines(result.get("shopping_lines"), 3, fb["shopping_lines"])]

    md_raw = result.get("md_sections") if isinstance(result.get("md_sections"), dict) else {}
    md_sections = {
        # safe_md_lines: LLM 생성 줄만 사용, 쉼표 끝 정리 포함. ensure_period 미적용(연결줄 보존)
        "choice":   safe_md_lines(md_raw.get("choice"),   fb["md_sections"]["choice"]),
        "fabric":   safe_md_lines(md_raw.get("fabric"),   fb["md_sections"]["fabric"]),
        "fit":      safe_md_lines(md_raw.get("fit"),      fb["md_sections"]["fit"]),
        "occasion": safe_md_lines(md_raw.get("occasion"), fb["md_sections"]["occasion"]),
        "purchase_note": [],
        "ending": [],
    }

    tips_raw = result.get("size_tips") if isinstance(result.get("size_tips"), dict) else {}

    def normalize_tip(val, fallback_val):
        """size_tips 값이 문자열이든 배열이든 2개 문장 리스트로 정규화."""
        if isinstance(val, list) and val:
            lines = [ensure_period(clean_line(x)) for x in val if clean_line(x)]
            if not lines:
                lines = fallback_val if isinstance(fallback_val, list) else [ensure_period(fallback_val)]
            return lines[:2] if len(lines) >= 2 else lines
        if isinstance(val, str) and val.strip():
            # 문자열이면 마침표 기준으로 분리 시도
            parts = re.split(r"\.\s+", ensure_period(clean_line(val)))
            parts = [p.strip() for p in parts if p.strip()]
            parts = [p if p.endswith(".") else p + "." for p in parts]
            return parts[:2] if len(parts) >= 2 else parts
        # 폴백
        if isinstance(fallback_val, list):
            return fallback_val
        return [ensure_period(fallback_val)]

    size_tips = {
        "55":     normalize_tip(tips_raw.get("55"),     fb["size_tips"]["55"]),
        "66":     normalize_tip(tips_raw.get("66"),     fb["size_tips"]["66"]),
        "66half": normalize_tip(tips_raw.get("66half"), fb["size_tips"]["66half"]),
        "77":     normalize_tip(tips_raw.get("77"),     fb["size_tips"]["77"]),
    }

    return {
        "material_desc_lines": material_desc_lines,
        "recommend_lines": recommend_lines,
        "review_lines": review_lines,
        "faqs": faqs,
        "shopping_lines": shopping_lines,
        "md_sections": md_sections,
        "size_tips": size_tips,
    }


# ─────────────────────────────────────────────
# HTML 렌더링
# ─────────────────────────────────────────────

def render_text_source(structured):
    rec_lines = ''.join([f"▪ {x}<br>\n" for x in structured['recommend_lines']])
    review_lines = ''.join([f'"{x}"<br>\n' for x in structured['review_lines']])

    faq_parts = []
    for idx, faq in enumerate(structured['faqs']):
        q = re.sub(r"^(?:Q\.\s*)+", "", faq['q']).strip()
        a = re.sub(r"^(?:A\.\s*)+", "", faq['a']).strip()
        faq_parts.append(f"Q. {q}<br>\n")
        faq_parts.append(f"A. {a}<br>\n")
        if idx < len(structured['faqs']) - 1:
            faq_parts.append("<br>\n")
    faq_lines = "".join(faq_parts)

    return (
        '<div style="text-align:center;">\n'
        '<h3 style="margin-bottom:0;">\n'
        "✓ 이런 분께 추천해요!</h3>\n"
        "<br>\n"
        '<p><span style="font-size:14px; line-height:1.8;">\n'
        + rec_lines
        + "</span></p></div>\n"
        "<br><br><br><br>\n\n"
        '<div style="text-align:center;">\n'
        '<h3 style="margin-bottom:0;">\n'
        "✓ 미리 입어 본 착용후기 (모델/스텝/MD리뷰)</h3>\n"
        "<br>\n"
        '<p><span style="font-size:14px; line-height:1.8;">\n'
        + review_lines
        + "</span></p></div>\n"
        "<br><br><br>\n\n"
        + DIVIDER_MARKER + "\n\n"
        '<div style="text-align:center;">\n'
        '<h3 style="margin-bottom:0;">\n'
        "✓ (FAQ) 이 상품, 이게 궁금해요!</h3>\n"
        "<br>\n"
        '<p><span style="font-size:14px; line-height:1.4;">\n'
        + faq_lines
        + "</span></p></div>\n"
        "<br><br><br><br>"
    )

def render_subsc_html(data, structured):
    """MD원고 — 4개 소제목만. purchase_note/ending 절대 포함 안 함."""
    md = structured["md_sections"]

    def join_md(lines):
        return "".join(part + "<br>\n" for x in lines for part in natural_wrap(x, max_chars=24))

    return (
        '<div id="subsc">\n'
        "<h3>" + data["display_name"] + "</h3>\n"
        "<p>\n"
        '<strong style="font-weight:700 !important;">[이 상품을 초이스한 이유입니다.]</strong><br>\n'
        + join_md(md["choice"])
        + "<br>\n"
        '<strong style="font-weight:700 !important;">[원단과 두께 체감에 대하여]</strong><br>\n'
        + join_md(md["fabric"])
        + "<br>\n"
        '<strong style="font-weight:700 !important;">[체형과 핏, 사이즈 선택 가이드]</strong><br>\n'
        + join_md(md["fit"])
        + "<br>\n"
        '<strong style="font-weight:700 !important;">[이렇게 입는 날이 많아집니다]</strong><br>\n'
        + join_md(md["occasion"])
        + "\n</p></div>"
    )


def build_subtap_html(data, material_desc_lines):
    material_line = format_material_line(data["material"])
    washing = (data["washing"] or "").strip() or "상품 케어라벨의 세탁 안내를 확인해 주세요."
    size_tip = (data["size"] or "").strip() or "FREE 사이즈로 77까지 추천드립니다."
    measurement_html = format_measurement_lines(data["measurement_lines"])
    desc_html = "<br>\n\t\t\t\t\t\t\t\t\t".join(material_desc_lines) + "<br>"

    return (
        '<div id="Subtap">\n'
        '\t<div id="header2" role="banner">\n'
        '\t\t<nav class="nav" role="navigation">\n'
        '\t\t\t<ul class="nav__list">\n'
        "\t\t\t\t<li>\n"
        '\t\t\t\t\t<input id="group-1" type="checkbox" hidden="">\n'
        '\t\t\t\t\t<label for="group-1" style="border-top-color: rgb(204, 204, 204); border-top-width: 1px; border-top-style: solid;">\n'
        '\t\t\t\t\t\t<p class="fa fa-angle-right"></p>소재 정보</label>\n'
        '\t\t\t\t\t<ul class="group-list">\n'
        "\t\t\t\t\t\t<li>\n"
        '\t\t\t\t\t\t\t<a href="#">\n'
        "\t\t\t\t\t\t\t\t<h3>소재 : " + material_line + "</h3>\n"
        "\t\t\t\t\t\t\t\t<p>\n"
        "\t\t\t\t\t\t\t\t\t" + desc_html + "\n"
        "\t\t\t\t\t\t\t\t</p>\n"
        "\t\t\t\t\t\t\t\t<h3>세탁방법</h3>\n"
        "\t\t\t\t\t\t\t\t<p>" + washing + "</p>\n"
        "\t\t\t\t\t\t\t</a>\n"
        "\t\t\t\t\t\t</li>\n"
        "\t\t\t\t\t</ul>\n"
        "\t\t\t\t</li>\n"
        "\t\t\t\t<li>\n"
        '\t\t\t\t\t<input id="group-2" type="checkbox" hidden="">\n'
        '\t\t\t\t\t<label for="group-2">\n'
        '\t\t\t\t\t\t<p class="fa fa-angle-right"></p>사이즈 정보</label>\n'
        '\t\t\t\t\t<ul class="group-list gray">\n'
        "\t\t\t\t\t\t<li>\n"
        '\t\t\t\t\t\t\t<a href="#">\n'
        "\t\t\t\t\t\t\t\t<h3>사이즈 TIP</h3>\n"
        "\t\t\t\t\t\t\t\t<p>" + size_tip + "</p>\n"
        "\t\t\t\t\t\t\t\t<h3>길이 TIP</h3>\n"
        "\t\t\t\t\t\t\t\t<p>실제 기장감은 키와 체형에 따라 달라집니다.\n"
        "<br> 입력된 상품의 총장 및 실측사이즈를 참고해 주세요.</p>\n"
        "\t\t\t\t\t\t\t</a>\n"
        "\t\t\t\t\t\t</li>\n"
        "\t\t\t\t\t</ul>\n"
        "\t\t\t\t</li>\n"
        "\t\t\t\t<li>\n"
        '\t\t\t\t\t<input id="group-3" type="checkbox" hidden="">\n'
        '\t\t\t\t\t<label for="group-3">\n'
        '\t\t\t\t\t\t<p class="fa fa-angle-right"></p>실측 사이즈</label>\n'
        '\t\t\t\t\t<ul class="group-list">\n'
        "\t\t\t\t\t\t<li>\n"
        '\t\t\t\t\t\t\t<a href="#">\n'
        "\t\t\t\t\t\t\t\t<p>" + measurement_html + "</p>\n"
        "\t\t\t\t\t\t\t</a>\n"
        "\t\t\t\t\t\t</li>\n"
        "\t\t\t\t\t</ul>\n"
        "\t\t\t\t</li>\n"
        "\t\t\t\t<li>\n"
        '\t\t\t\t\t<input id="group-5" type="checkbox" hidden="">\n'
        '\t\t\t\t\t<label for="group-5"><span class="fa fa-angle-right"></span>\n'
        '\t\t\t\t\t\t<a href="#crema-product-fit-1" style="padding: 0px; box-shadow:none; background:#f7f7f7;">실측사이즈 재는방법</a></label>\n'
        "\t\t\t\t</li>\n"
        "\t\t\t</ul>\n"
        "\t\t</nav>\n"
        "\t</div>\n"
        "</div>"
    )


def assemble_final_output(data, structured):
    material_line = format_material_line(data["material"])
    text_source = render_text_source(structured)
    subsc_html = render_subsc_html(data, structured)
    subtap_html = build_subtap_html(data, structured["material_desc_lines"])
    source_block = FIXED_HTML_HEAD + "\n\n" + subsc_html + "\n\n" + subtap_html

    # 소재설명: 단락 형태 (리스트 아님)
    material_desc_paragraph = " ".join(structured["material_desc_lines"])

    lines = []
    lines.append("상품명 : " + data["display_name"])
    lines.append("")
    lines.append("컬러 : " + data["color"])
    lines.append("사이즈 : " + data["size"])
    lines.append("소재 : " + material_line)
    lines.append("소재설명 : " + material_desc_paragraph)
    lines.append("제조국 : " + data["country"])
    lines.append("")
    lines.append("○ 포인트 코멘트")
    lines.append("-")
    # 포인트 코멘트 빈 줄 9개
    for _ in range(9):
        lines.append("")
    lines.append("-")
    lines.append("")
    lines.append("---------------------------------")
    lines.append("텍스트 소스")
    lines.append("---------------------------------")
    lines.append("")
    lines.append(text_source)
    lines.append("")
    lines.append("----------------------------------")
    lines.append("MD원고(상품 설명 소스)")
    lines.append("----------------------------------")
    lines.append(source_block)
    lines.append("")
    lines.append("-----------------")
    lines.append("사이즈 팁")
    lines.append("-----------------")
    lines.append("")
    lines.append("ㅇ55 (90) 160cm 50kg")
    for s in structured["size_tips"]["55"]:
        lines.append(s)
    lines.append("")
    lines.append("ㅇ66 (95) 162cm 55kg")
    for s in structured["size_tips"]["66"]:
        lines.append(s)
    lines.append("")
    lines.append("ㅇ66반 (95) 163cm 59kg")
    for s in structured["size_tips"]["66half"]:
        lines.append(s)
    lines.append("")
    lines.append("ㅇ77 (100) 161cm 62kg")
    for s in structured["size_tips"]["77"]:
        lines.append(s)
    return "\n".join(lines).strip()


# ─────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────
st.markdown("---")
st.subheader("상품 네이밍")
ncol1, ncol2 = st.columns([5, 1], vertical_alignment="bottom")
with ncol1:
    naming_input = st.text_area(
        "상품 주요특징 입력",
        height=120,
        placeholder="예: 여리핏, 부드러운 엠보 텍스처, 상체 군살 커버, 루즈핏 맨투맨",
        key="naming_input_value",
    )
with ncol2:
    if st.button("네이밍 생성", use_container_width=True):
        if naming_input.strip():
            with st.spinner("상품명을 생성 중입니다..."):
                try:
                    response = chat_with_retry(
                        model="gpt-4o",
                        messages=[
                            {"role": "system", "content": NAME_PROMPT},
                            {"role": "user", "content": naming_input},
                        ],
                        temperature=0.5,
                        max_retries=2,
                    )
                    st.session_state.naming_result = response.choices[0].message.content.strip()
                    st.rerun()
                except RateLimitError:
                    st.error("현재 OpenAI 요청이 일시적으로 몰려 네이밍 생성을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.")
                except Exception as e:
                    st.error(f"네이밍 생성 중 오류가 발생했습니다: {e}")
        else:
            st.warning("상품 주요특징을 입력해 주세요.")

st.text_area("상품 네이밍 제안 20개", value=st.session_state.naming_result, height=250)
st.markdown("---")

h1, h2 = st.columns([2.2, 1.0], vertical_alignment="bottom")
with h1:
    st.subheader("상품정보 입력")
with h2:
    st.button("초기화", use_container_width=True, on_click=reset_all)

nonce = st.session_state.reset_nonce
left, right = st.columns(2)

with left:
    product_name = st.text_input("상품명", value="( color)", key=f"product_name_{nonce}")
    color = st.text_input("컬러", placeholder="예: 1 아이보리 2 연그레이 3 블랙", key=f"color_{nonce}")
    size = st.text_area("사이즈", height=90, value="FREE 사이즈로 77까지 추천드립니다.", key=f"size_{nonce}")
    material = st.text_input("소재", placeholder="예: 울6 텐셀45 레이온37 나일론12", key=f"material_{nonce}")
    material_desc = st.text_area(
        "소재설명",
        height=110,
        placeholder="예: 부드러운 촉감, 은은한 광택, 구김 적음, 여리한 실루엣",
        key=f"material_desc_{nonce}",
    )
    country = st.text_input("제조국", key=f"country_{nonce}")
    top_measure = st.text_area(
        "상의 실측사이즈",
        height=120,
        value="어깨단면 / 가슴둘레 / 암홀둘레 / 소매길이 / 소매둘레 / 총장 / 총장(앞) / 총장(뒤)  단위:cm",
        key=f"top_measure_{nonce}",
    )
    bottom_measure = st.text_area(
        "하의 실측사이즈",
        height=110,
        value="F 허리둘레 / 엉덩이둘레 / 허벅지둘레 / 밑단둘레 / 총장 / 밑위 길이  단위:cm\nL 허리둘레 / 엉덩이둘레 / 허벅지둘레 / 밑단둘레 / 총장 / 밑위 길이  단위:cm",
        key=f"bottom_measure_{nonce}",
    )
    dress_measure = st.text_area(
        "원피스 실측사이즈",
        height=130,
        value="어깨단면 / 가슴둘레 / 허리둘레 / 엉덩이둘레 / 암홀둘레 / 소매길이 / 어깨소매길이 / 총장(앞) / 총장(뒤)  단위:cm",
        key=f"dress_measure_{nonce}",
    )

with right:
    detail_tip = st.text_input("디테일 특징", placeholder="예: 브이넥, 타이 탈부착, 앞 절개라인, 소매 볼륨", key=f"detail_tip_{nonce}")
    fit = st.text_input("핏/실루엣", placeholder="예: 군살커버, 세련된 핏, 여리한 실루엣", key=f"fit_{nonce}")
    appeal_points = st.text_area(
        "주요 어필 포인트",
        height=150,
        placeholder="예: 구김 적음, 체형커버, 오피스룩, 하객룩, 데일리룩",
        key=f"appeal_points_{nonce}",
    )
    etc = st.text_area(
        "기타 특징",
        height=120,
        placeholder="예: 브랜드 퀄리티 고급소재",
        key=f"etc_{nonce}",
    )
    target = st.text_input("타겟", value="4050 여성", key=f"target_{nonce}")
    washing = st.text_input(
        "세탁방법",
        value="드라이클리닝, 단독 울세탁, 손세탁 권장. 건조기 사용 금지",
        key=f"washing_{nonce}",
    )
    additional_request = st.text_area(
        "추가/수정 요청사항 (출력물 확인 후 수정사항 입력)",
        height=120,
        key=f"additional_request_{nonce}",
    )

st.subheader("이미지 업로드")
uploaded_images = st.file_uploader(
    "이미지",
    type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True,
    key=f"uploaded_images_{nonce}",
)

if st.button("생성하기", type="primary", use_container_width=True, key=f"generate_{nonce}"):
    display_name = apply_color_count_to_name(product_name, color)
    measurement_lines = combine_measurements(top_measure, bottom_measure, dress_measure)
    data = {
        "product_name": product_name,
        "display_name": display_name,
        "color": color,
        "size": size,
        "material": material,
        "material_desc_raw": material_desc,
        "country": country,
        "measurement_lines": measurement_lines,
        "detail_tip": detail_tip,
        "fit": fit,
        "appeal_points": appeal_points,
        "etc": etc,
        "target": target,
        "washing": washing,
    }

    with st.spinner("출력물을 생성 중입니다..."):
        try:
            structured_raw = generate_structured_copy(data, additional_request, uploaded_images)
            structured = normalize_generated_strict(structured_raw)
            result = assemble_final_output(data, structured)
        except RateLimitError:
            st.error("현재 OpenAI 요청이 일시적으로 몰려 원고 생성을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.")
            st.stop()
        except Exception as e:
            st.error(f"원고 생성 중 오류가 발생했습니다: {e}")
            st.stop()

    # 세션에 저장 — TXT/HWP 버튼이 다운로드 후에도 사라지지 않음
    st.session_state.generated_result = result
    st.session_state.generated_docx = result_to_docx_bytes(result)
    st.session_state.generated_file_stem = (display_name or "page_builder").replace(" ", "_")

# ─── 결과 표시 (세션 기반) ───
if st.session_state.generated_result:
    st.text_area("결과", st.session_state.generated_result, height=1200)
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "TXT 다운로드",
            data=st.session_state.generated_result,
            file_name=st.session_state.generated_file_stem + "_output.txt",
            mime="text/plain",
            use_container_width=True,
        )
    with c2:
        st.download_button(
            "HWP 다운로드",
            data=st.session_state.generated_docx,
            file_name=st.session_state.generated_file_stem + "_output.hwp",
            mime="application/x-hwp",
            use_container_width=True,
        )

st.markdown("---")
st.markdown("© made by MISHARP, MIYAWA. All rights reserved.")
