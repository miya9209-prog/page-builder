import base64
import io
import json
import mimetypes
import re
import time
from typing import Any, Dict, List

import streamlit as st
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt
from openai import OpenAI, RateLimitError

st.set_page_config(page_title="PAGE BUILDER", layout="wide")

# Session state
if "reset_nonce" not in st.session_state:
    st.session_state.reset_nonce = 0
if "naming_result" not in st.session_state:
    st.session_state.naming_result = ""
if "naming_input_value" not in st.session_state:
    st.session_state.naming_input_value = ""
if "generated_result" not in st.session_state:
    st.session_state.generated_result = ""
if "generated_docx" not in st.session_state:
    st.session_state.generated_docx = b""
if "generated_file_stem" not in st.session_state:
    st.session_state.generated_file_stem = "page_builder"

st.markdown("<style>div[data-testid='stButton'] > button { min-height: 42px; }</style>", unsafe_allow_html=True)
st.title("MISHARP PAGE BUILDER")
st.caption("구매전환율 상승을 위한 상세페이지 기획 + 상품 원고 생성기")

api_key = st.secrets.get("OPENAI_API_KEY", "")
if not api_key:
    st.warning("OPENAI_API_KEY가 설정되지 않았습니다.")
    st.stop()

client = OpenAI(api_key=api_key)

FIXED_HTML_HEAD = (
    '<meta http-equiv="X-UA-Compatible" content="IE=edge,chrome=1">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    '<link href="http://fonts.googleapis.com/css?family=Roboto" rel="stylesheet" type="text/css">\n'
    '<link href="http://netdna.bootstrapcdn.com/font-awesome/4.3.0/css/font-awesome.min.css" rel="stylesheet" type="text/css">\n'
    '<link href="/SRC2/cssmtmenu/style.css" rel="stylesheet" type="text/css">\n'
    '<link href="//spoqa.github.io/spoqa-han-sans/css/SpoqaHanSans-kr.css" rel="stylesheet" type="text/css">\n'
    '<link href="//misharp.co.kr/subtab.css" rel="stylesheet" type="text/css">'
)

NAME_PROMPT = """너는 4050 여성 패션 쇼핑몰 미샵의 상품 네이밍 전문가다.
- 상품 주요 특징을 반영해 상품명을 20개 제안한다.
- 각 상품명은 공백 포함 최대 18자 이내.
- 반드시 단어와 단어 사이를 자연스럽게 띄어쓴다.
- AI 검색, 키워드 검색 모두 고려한다.
- 디테일/형태/원단/핏 등을 반영한 단어 + 카테고리명을 포함한다.
- 필요하면 세련되고 여성스러운 단어를 앞에 붙여도 된다.
- 번호, 설명, 코드펜스 없이 한 줄에 하나씩 20개만 출력한다."""


def chat_with_retry(*, model, messages, temperature=0.3, max_retries=2):
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return client.chat.completions.create(model=model, messages=messages, temperature=temperature)
        except RateLimitError as exc:
            last_exc = exc
            if attempt >= max_retries: raise
            time.sleep(2 * (attempt + 1))
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries: raise
            time.sleep(1 * (attempt + 1))
    raise last_exc


def file_to_content_item(uploaded_file):
    mime = uploaded_file.type or mimetypes.guess_type(uploaded_file.name)[0] or "image/jpeg"
    data = uploaded_file.read()
    b64 = base64.b64encode(data).decode("utf-8")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def extract_lines_with_digits(text):
    return [l.strip() for l in (text or "").splitlines() if l.strip() and re.search(r"\d", l)]


def combine_measurements(top, bottom, dress):
    lines = []
    for block in [top, bottom, dress]:
        lines.extend(extract_lines_with_digits(block))
    return lines


def count_colors(color_text):
    if not color_text.strip(): return 0
    text = color_text.replace(" / ", "\n").replace("/", "\n").replace(",", "\n")
    parts = [re.sub(r"^\s*\d+\s*", "", p).strip() for p in text.splitlines()]
    return len([p for p in parts if p])


def apply_color_count_to_name(product_name, color_text):
    count = count_colors(color_text)
    suffix = f"({count} color)" if count > 0 else "(color)"
    name = (product_name or "").strip()
    name = re.sub(r"\(\s*color\s*\)", suffix, name, flags=re.I)
    if re.search(r"\(\s*\d+\s*color\s*\)", name, flags=re.I): return name
    if "( color)" in name: return name.replace("( color)", f" {suffix}")
    return name


def normalize_space(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def clean_line(line):
    line = re.sub(r"^[\-\u2022\u25aa\u29bf\s]+", "", (line or "").strip())
    return re.sub(r"\s+", " ", line).strip()


def ensure_sentence(line, ending="."):
    line = clean_line(line)
    if not line: return ""
    return line if re.search(r"[.!?\u2026]$", line) else line + ending


def normalize_list(items, count, quote=False):
    out, seen = [], set()
    for item in items:
        item = clean_line(item).replace('"', "").strip()
        if not item: continue
        key = re.sub(r"\s+", "", item)
        if key in seen: continue
        seen.add(key)
        out.append(item)
        if len(out) >= count: break
    return [f'"{x}"' for x in out] if quote else out


def normalize_multiline_text(text):
    if not text: return []
    return [clean_line(p) for p in text.replace("\r", "\n").split("\n") if clean_line(p)]


def format_measurement_lines(lines):
    if not lines: return "실측사이즈 정보를 입력해 주세요."
    formatted = []
    for line in lines:
        line = re.sub(r"\s+단위:cm$", "", line).strip()
        for sz in ["L", "M", "S", "XL"]:
            line = re.sub(rf"\s+{sz}\s+", f"<br>{sz} ", line)
        line = re.sub(r"\s+", " ", line)
        formatted.append(line)
    return "<br>".join(formatted) + " (단위: cm)"


def result_to_docx_bytes(result_text):
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Dotum"
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "돋움")
    style.font.size = Pt(10)
    style.paragraph_format.space_before = Pt(0)
    style.paragraph_format.space_after = Pt(0)
    style.paragraph_format.line_spacing = 1.5
    for line in result_text.splitlines():
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.5
        run = p.add_run(line)
        run.font.name = "Dotum"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "돋움")
        run.font.size = Pt(10)
    bio = io.BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio.getvalue()


def reset_all():
    st.session_state.reset_nonce += 1
    for key in ["naming_result", "naming_input_value", "generated_result"]:
        st.session_state[key] = ""
    st.session_state.generated_docx = b""
    st.session_state.generated_file_stem = "page_builder"


def build_generation_prompt(data, additional_request):
    return f"""
너는 10년 이상 4050 여성 패션몰 미샵 상세페이지를 써 온 최고 수준의 한국어 커머스 카피라이터다.
단순 요약이 아니라, 실제 고객이 망설이는 이유를 먼저 해소하고 구매를 돕는 고급 원고를 작성한다.

[핵심 원칙]
1) 입력 문구를 그대로 복붙하지 말고 반드시 자연스럽고 매력적인 문장으로 재작성한다.
2) 없는 디테일은 절대 만들지 않는다. 타이/스카프/포켓/단추/절개/비침/스트랩 등은 입력 근거가 있을 때만 언급한다.
3) SEO/AEO/GEO 최적화: 상품명·카테고리·소재명·핏 키워드·활용 장면·고객 니즈 표현을 자연스럽게 모든 텍스트에 녹인다.
4) 결과는 반드시 JSON만 출력한다. 코드펜스(```) 및 설명문 금지.

[FAQ 작성 필수 규칙 ★ 가장 중요 ★]
- FAQ 4개는 반드시 실제 고객이 구매 망설일 때 드는 구체적·심화 질문이어야 한다.
- 절대 금지 유형: "사이즈가 어떻게 되나요?", "소재가 어떻게 되나요?", "FREE 사이즈인가요?" 같은 단순·기계적 질문
- 반드시 이런 유형으로: 체형 고민(가슴·뱃살·팔뚝·어깨), TPO(결혼식 하객·오피스·모임), 비침·구김·세탁 실전, 코디 고민
- 좋은 FAQ 예시: "Q. 가슴이 좀 있는 77인데 어깨랑 가슴 쪽이 당기지 않을까요?", "Q. 결혼식 하객룩으로 너무 캐주얼해 보이지 않을까요?", "Q. 아이보리 컬러인데 속이 많이 비칠까요?", "Q. 팔뚝이 굵은 편인데 소매가 꽉 끼거나 짧지 않을까요?"
- 4개 질문이 모두 서로 다른 고민 영역을 다뤄야 한다.

[입력 데이터]
- 상품명: {data['display_name']}
- 컬러: {data['color']}
- 사이즈: {data['size']}
- 소재: {data['material']}
- 소재설명 참고메모: {data['material_desc_raw']}
- 디테일 특징: {data['detail_tip']}
- 핏/실루엣: {data['fit']}
- 주요 어필 포인트: {data['appeal_points']}
- 기타 특징: {data['etc']}
- 타겟: {data['target']}
- 세탁방법: {data['washing']}
- 실측사이즈: {' / '.join(data['measurement_lines']) if data['measurement_lines'] else '정보 없음'}
- 추가/수정 요청사항: {additional_request or '없음'}

[JSON 스키마 - 이 형식 그대로만 출력]
{{
  "material_desc_lines": ["문장1", "문장2", "문장3"],
  "recommend_lines": ["문장1", "문장2", "문장3", "문장4"],
  "review_lines": ["문장1", "문장2", "문장3", "문장4"],
  "faqs": [
    {{"q": "Q. 구체적 pain point 질문", "a": "A. 상세 답변"}},
    {{"q": "Q. 구체적 pain point 질문", "a": "A. 상세 답변"}},
    {{"q": "Q. 구체적 pain point 질문", "a": "A. 상세 답변"}},
    {{"q": "Q. 구체적 pain point 질문", "a": "A. 상세 답변"}}
  ],
  "shopping_lines": ["문장1", "문장2", "문장3"],
  "md_sections": {{
    "choice": ["문장1", "문장2", "문장3", "문장4"],
    "fabric": ["문장1", "문장2", "문장3", "문장4"],
    "fit": ["문장1", "문장2", "문장3", "문장4"],
    "occasion": ["문장1", "문장2", "문장3", "문장4"],
    "ending": ["문장1", "문장2", "문장3"]
  }},
  "size_tips": {{
    "55": "55 체형(160cm 48kg) 착용감 한 문장",
    "66": "66 체형(165cm 54kg) 착용감 한 문장",
    "66half": "66반 체형(164cm 58kg) 착용감 한 문장",
    "77": "77 체형(163cm 61kg) 착용감 한 문장"
  }}
}}

[각 섹션 세부 기준]
- material_desc_lines: 소재명 키워드 포함, 촉감·광택·계절감·관리 포인트 3줄.
- recommend_lines: "~하시는 분" 마무리. 체형고민·TPO·코디·소재취향 구체적 4줄.
- review_lines: 미샵 스텝/MD가 직접 입고 말할 법한 생생한 후기 4줄. 따옴표 없이 작성(자동 추가됨). 착용감·체형·활용성 구체 언급.
- faqs: 위 필수 규칙 반드시 준수. 4개 모두 다른 고민 영역. 답변은 실용적이고 구체적으로.
- shopping_lines: 사이즈 권장/컬러 주의/탈부착 여부 등 실용 체크 3줄.
- md_sections.choice: 왜 이 상품이어야 하는지 설득형 4줄.
- md_sections.fabric: 소재명+혼방 기반 질감·광택·두께감 4줄.
- md_sections.fit: 체형별 핏 설명, 사이즈 선택 가이드 4줄. 구체적 체형 언급.
- md_sections.occasion: 출근·모임·하객·데이트 등 구체적 TPO와 코디 4줄.
- md_sections.ending: 감성 과장 없이 미샵 톤으로 자연스러운 3줄.
- size_tips: 각 체형 실제 착용감 한 문장. 여유감·커버감·실루엣 구체 표현.
"""


def extract_json(text):
    text = re.sub(r"^```(?:json)?", "", (text or "").strip()).strip()
    text = re.sub(r"```$", "", text).strip()
    if text.startswith("{") and text.endswith("}"): return json.loads(text)
    m = re.search(r"\{[\s\S]*\}", text)
    if not m: raise ValueError("JSON 응답을 찾지 못했습니다.")
    return json.loads(m.group(0))


def smart_faq_defaults(data):
    size = clean_line(data.get("size") or "FREE 사이즈로 77까지 추천드립니다.")
    product = data.get("display_name") or "상품"
    color = data.get("color") or ""
    detail = normalize_space(data.get("detail_tip") or "")
    fit = normalize_space(data.get("fit") or "")
    bright = any(k in color for k in ["아이보리", "화이트", "크림"])
    has_detachable = bool(re.search(r"탈부착|분리", detail))

    faq = [
        {
            "q": "Q. 가슴이 좀 있는 77인데 어깨나 가슴 쪽이 당기거나 답답하지 않을까요?",
            "a": (f"A. {fit} 특성이 있어 체형을 편안하게 감싸주는 편이에요. " if fit else "A. ") +
                 f"{size} 기준으로 여유 있게 재단되어 있어 가슴이 있는 77 체형도 답답하지 않게 착용하실 수 있어요. 실측사이즈의 가슴둘레와 암홀 수치를 함께 확인해 보시길 권해드립니다."
        },
        {
            "q": "Q. 결혼식 하객룩으로 입어도 될까요? 너무 캐주얼해 보이지 않을까요?",
            "a": f"A. {product}은 은은한 광택과 정제된 실루엣 덕분에 격식 있는 자리에서도 충분히 우아하게 연출하실 수 있어요. 슬랙스나 스커트와 매치하시면 하객룩으로도 손색없이 품격 있는 스타일이 완성됩니다."
        },
        {
            "q": "Q. 아이보리 컬러인데 속이 많이 비쳐서 이너를 꼭 챙겨 입어야 하나요?" if bright else "Q. 하루 종일 활동하면 구김이 심하게 남는 편인가요?",
            "a": "A. 밝은 컬러 특성상 약간의 비침이 있을 수 있어요. 스킨톤이나 베이지 계열 이너를 함께 착용하시면 훨씬 안정감 있고 깔끔하게 입으실 수 있습니다." if bright else "A. 혼방 소재 특성상 구김 회복력이 비교적 좋은 편이라 오랜 시간 착용해도 깔끔한 상태를 유지하기 좋아요. 출근 후 저녁 약속까지 이어지는 바쁜 날에도 부담 없이 활용하시기 좋습니다."
        },
        {
            "q": "Q. 스카프 스트랩을 빼고 심플하게 입을 수도 있나요?" if has_detachable else "Q. 팔뚝이 굵은 편인데 소매가 꽉 끼거나 너무 짧지 않을까요?",
            "a": "A. 네, 스트랩은 탈부착이 가능해 타이 없이 깔끔한 브이넥 블라우스로도 입을 수 있어요. 상황에 맞게 자유롭게 스타일링해 보세요." if has_detachable else "A. 실측사이즈의 소매둘레와 소매길이 수치를 함께 확인해 보시면 정확한 판단에 도움이 돼요. 여유 있게 재단된 편이라 팔뚝 부담 없이 착용하시는 분들이 많습니다."
        },
    ]
    return faq


def fallback_structured(data):
    product = data.get("display_name") or "상품"
    size = clean_line(data.get("size") or "FREE 사이즈로 77까지 추천드립니다.")
    material_lines = normalize_multiline_text(data.get("material_desc_raw") or "")[:3]
    if not material_lines:
        material_lines = [
            "부드러운 터치감으로 피부에 닿는 느낌이 편안한 소재입니다.",
            "표면감이 차분하게 정리되어 데일리로 활용하기 좋습니다.",
            "관리 부담이 크지 않아 손이 자주 가는 아이템입니다.",
        ]
    else:
        material_lines = [ensure_sentence(x) for x in material_lines]

    fit_text = normalize_space(data.get("fit") or "")
    detail_text = normalize_space(data.get("detail_tip") or "")
    etc_text = normalize_space(data.get("etc") or "")

    return {
        "material_desc_lines": material_lines,
        "recommend_lines": [
            "격식 있는 자리에도 여성스럽고 단정한 스타일을 원하시는 분",
            "상체 라인을 부담 없이 정리해 주는 여유로운 핏을 선호하시는 분",
            "소재감이 주는 고급스러운 무드를 중요하게 생각하시는 분",
            "데님, 슬랙스, 스커트 모두 두루 어울리는 활용도 높은 상의를 찾으시는 분",
        ],
        "review_lines": [
            "입었을 때 전체 실루엣이 자연스럽게 정리돼서 하루 종일 손이 가요.",
            "촉감이 부담스럽지 않고 피부에 닿는 느낌이 부드러워 오래 입어도 편안해요.",
            "격식 있는 자리에도 과하지 않게 잘 어울려 활용도가 정말 높아요.",
            "구김 부담이 크지 않아 바쁜 날 출근룩으로도 깔끔하게 입기 좋았어요.",
        ],
        "faqs": smart_faq_defaults(data),
        "shopping_lines": [
            f"{size}",
            "밝은 컬러 계열은 스킨톤 이너와 함께 착용하시면 더 안정감 있게 연출하실 수 있습니다.",
            "실측사이즈를 함께 확인하시면 원하는 핏으로 선택하시기 더 좋습니다.",
        ],
        "md_sections": {
            "choice": [
                f"{product}은 과하게 꾸민 느낌 없이도 차분하고 세련된 인상을 완성해 줍니다.",
                "브이넥 라인과 탈부착 타이 디테일이 얼굴 라인을 갸름하게 잡아주는 효과가 있어요." if detail_text else "기본에 가까운 디자인일수록 소재와 핏의 차이가 크게 느껴지는데, 이 아이템은 그 균형감이 특히 좋습니다.",
                fit_text + " 장점이 자연스럽게 살아 있어 부담 없이 손이 갑니다." if fit_text else "체형을 부드럽게 감싸주는 실루엣이 안정감 있게 느껴집니다.",
                etc_text + " 장점까지 더해져 소장 만족도를 높여줍니다." if etc_text else "데일리와 격식을 오가는 다양한 자리에서 활용도가 높아 추천드리기 좋습니다.",
            ],
            "fabric": material_lines + ["두께감도 과하게 무겁지 않아 봄, 가을, 간절기에 활용도 높게 매치하시기 좋습니다."],
            "fit": [
                f"{size} 기준으로 안내드리며, 전체적으로 답답하지 않게 착용하시기 좋은 편입니다.",
                fit_text + " 장점이 자연스럽게 드러나 체형 고민을 덜어줍니다." if fit_text else "어깨선과 품이 과하게 조이지 않아 상체 라인이 비교적 편안해 보입니다.",
                "브이넥 라인과 앞 절개 디테일이 슬림하고 세련된 인상을 연출해 줍니다." if detail_text else "실루엣이 흐트러지지 않아 단정한 분위기를 유지하기 좋습니다.",
                "실측사이즈를 함께 확인하시면 원하는 핏으로 선택하시기 더 수월합니다.",
            ],
            "occasion": [
                "오피스룩처럼 단정함이 필요한 날에도 무리 없이 품격 있게 입기 좋습니다.",
                "하객룩, 모임, 식사 자리처럼 차려입은 느낌이 필요한 순간에도 자연스럽게 어울립니다.",
                "데님, 슬랙스, 스커트와 두루 매치하기 쉬워 코디 폭이 넓습니다.",
                "아우터 안에 받쳐 입거나 단독으로 연출해도 분위기가 흐트러지지 않습니다.",
            ],
            "ending": [
                "기본 아이템일수록 오래 입기 좋은 밸런스가 중요합니다.",
                f"{product}은 그런 기준에 잘 맞는 데일리 상의로 추천드릴 만합니다.",
                "한 벌만으로도 차분하고 세련된 분위기를 완성해 보세요.",
            ],
        },
        "size_tips": {
            "55": "전체적으로 여유 있는 느낌으로 떨어져 단독 착용 시에도 부담 없이 활용하시기 좋습니다.",
            "66": "품과 실루엣이 가장 안정감 있게 정리되어 데일리부터 모임룩까지 자연스럽게 이어집니다.",
            "66half": "상체를 비교적 편안하게 감싸 주는 편이라 체형 고민을 덜고 입기 좋습니다.",
            "77": "답답하게 조이지 않고 여유 있게 착용 가능한 편으로 실측 확인 후 선택하시면 만족도가 높습니다.",
        },
    }


def generate_structured_copy(data, additional_request, uploaded_images):
    prompt = build_generation_prompt(data, additional_request)
    user_content = [{"type": "text", "text": prompt}]
    for img in (uploaded_images[:5] if uploaded_images else []):
        user_content.append(file_to_content_item(img))
    response = chat_with_retry(
        model="gpt-4.1",
        messages=[
            {
                "role": "system",
                "content": (
                    "사용자 추가/수정 요청사항 최우선 반영. "
                    "반드시 JSON만 출력. 코드펜스·설명문 금지. "
                    "없는 디테일 절대 추정 금지. "
                    "FAQ는 반드시 구체적 pain point 기반 질문만. 단순·기계적 질문 절대 금지. "
                    "SEO/AEO/GEO 키워드 자연스럽게 녹일 것."
                )
            },
            {"role": "user", "content": user_content},
        ],
        temperature=0.6,
        max_retries=2,
    )
    return extract_json(response.choices[0].message.content)


def safe_lines(value, count, fallback, quote=False):
    items = value if isinstance(value, list) else []
    normalized = normalize_list(items, count)
    if len(normalized) < count:
        for item in fallback:
            c = clean_line(item)
            if c and c not in normalized:
                normalized.append(c)
            if len(normalized) >= count: break
    normalized = normalized[:count]
    if quote:
        return [f'"{x.replace(chr(34), "").strip()}"' for x in normalized]
    return normalized


def safe_faqs(value, fallback):
    out = []
    for item in (value if isinstance(value, list) else []):
        if not isinstance(item, dict): continue
        q = clean_line(item.get("q", ""))
        a = clean_line(item.get("a", ""))
        if not q or not a: continue
        if not q.startswith("Q."): q = "Q. " + q
        if not a.startswith("A."): a = "A. " + a
        out.append({"q": q, "a": a})
        if len(out) >= 4: break
    for item in fallback:
        if len(out) >= 4: break
        if all(item["q"] != x["q"] for x in out):
            out.append(item)
    return out[:4]


def normalize_generated(result, data):
    fallback = fallback_structured(data)
    md_raw = result.get("md_sections") if isinstance(result.get("md_sections"), dict) else {}
    tips_raw = result.get("size_tips") if isinstance(result.get("size_tips"), dict) else {}
    return {
        "material_desc_lines": [ensure_sentence(x) for x in safe_lines(result.get("material_desc_lines"), 3, fallback["material_desc_lines"])],
        "recommend_lines": [ensure_sentence(x) for x in safe_lines(result.get("recommend_lines"), 4, fallback["recommend_lines"])],
        "review_lines": safe_lines(result.get("review_lines"), 4, fallback["review_lines"]),
        "faqs": safe_faqs(result.get("faqs"), fallback["faqs"]),
        "shopping_lines": [ensure_sentence(x) for x in safe_lines(result.get("shopping_lines"), 3, fallback["shopping_lines"])],
        "md_sections": {
            k: [ensure_sentence(x) for x in safe_lines(md_raw.get(k), 4 if k != "ending" else 3, fallback["md_sections"][k])]
            for k in ["choice", "fabric", "fit", "occasion", "ending"]
        },
        "size_tips": {
            sz: ensure_sentence(tips_raw.get(sz, fallback["size_tips"][sz]))
            for sz in ["55", "66", "66half", "77"]
        },
    }


def build_subtap_html(data, material_desc_lines):
    mat = " + ".join(x.strip() for x in (data["material"] or "").split("+") if x.strip()) or "소재 정보 입력 필요"
    if "(건조기사용금지)" not in mat:
        mat = f"{mat} (건조기사용금지)"
    washing = (data["washing"] or "").strip() or "드라이클리닝, 단독 울세탁, 손세탁 권장. 건조기 사용 금지"
    size_tip = (data["size"] or "").strip() or "FREE 사이즈로 77까지 추천드립니다."
    measurement_html = format_measurement_lines(data["measurement_lines"])
    desc_html = "<br>\n\t\t\t\t\t\t\t\t\t".join(material_desc_lines) + "<br>"
    return (
        '<div id="Subtap">\n'
        '\t<div id="header2" role="banner">\n'
        '\t\t<nav class="nav" role="navigation">\n'
        '\t\t\t<ul class="nav__list">\n'
        '\t\t\t\t<li>\n'
        '\t\t\t\t\t<input id="group-1" type="checkbox" hidden="">\n'
        '\t\t\t\t\t<label for="group-1" style="border-top-color: rgb(204, 204, 204); border-top-width: 1px; border-top-style: solid;">\n'
        '\t\t\t\t\t\t<p class="fa fa-angle-right"></p>소재 정보</label>\n'
        '\t\t\t\t\t<ul class="group-list">\n'
        '\t\t\t\t\t\t<li>\n'
        '\t\t\t\t\t\t\t<a href="#">\n'
        f'\t\t\t\t\t\t\t\t<h3>소재 : {mat}</h3>\n'
        '\t\t\t\t\t\t\t\t<p>\n'
        f'\t\t\t\t\t\t\t\t\t{desc_html}\n'
        '\t\t\t\t\t\t\t\t</p>\n'
        '\t\t\t\t\t\t\t\t<h3>세탁방법</h3>\n'
        f'\t\t\t\t\t\t\t\t<p>{washing}</p>\n'
        '\t\t\t\t\t\t\t</a>\n'
        '\t\t\t\t\t\t</li>\n'
        '\t\t\t\t\t</ul>\n'
        '\t\t\t\t</li>\n'
        '\t\t\t\t<li>\n'
        '\t\t\t\t\t<input id="group-2" type="checkbox" hidden="">\n'
        '\t\t\t\t\t<label for="group-2">\n'
        '\t\t\t\t\t\t<p class="fa fa-angle-right"></p>사이즈 정보</label>\n'
        '\t\t\t\t\t<ul class="group-list gray">\n'
        '\t\t\t\t\t\t<li>\n'
        '\t\t\t\t\t\t\t<a href="#">\n'
        '\t\t\t\t\t\t\t\t<h3>사이즈 TIP</h3>\n'
        f'\t\t\t\t\t\t\t\t<p>{size_tip}</p>\n'
        '\t\t\t\t\t\t\t\t<h3>길이 TIP</h3>\n'
        '\t\t\t\t\t\t\t\t<p>162-167cm에서는 모델핏을 참고해 주시고,\n'
        '<br> 다리 길이나 체형에 따라 다르지만,\n'
        '<br> 160cm이하에서는 모델의 핏보다 조금 길게\n'
        '<br> 연출됩니다.</p>\n'
        '\t\t\t\t\t\t\t</a>\n'
        '\t\t\t\t\t\t</li>\n'
        '\t\t\t\t\t</ul>\n'
        '\t\t\t\t</li>\n'
        '\t\t\t\t<li>\n'
        '\t\t\t\t\t<input id="group-3" type="checkbox" hidden="">\n'
        '\t\t\t\t\t<label for="group-3">\n'
        '\t\t\t\t\t\t<p class="fa fa-angle-right"></p>실측 사이즈</label>\n'
        '\t\t\t\t\t<ul class="group-list">\n'
        '\t\t\t\t\t\t<li>\n'
        '\t\t\t\t\t\t\t<a href="#">\n'
        f'\t\t\t\t\t\t\t\t<p>{measurement_html}</p>\n'
        '\t\t\t\t\t\t\t</a>\n'
        '\t\t\t\t\t\t</li>\n'
        '\t\t\t\t\t</ul>\n'
        '\t\t\t\t</li>\n'
        '\t\t\t\t<li>\n'
        '\t\t\t\t\t<input id="group-5" type="checkbox" hidden="">\n'
        '\t\t\t\t\t<label for="group-5"><span class="fa fa-angle-right"></span>\n'
        '\t\t\t\t\t\t<a href="#crema-product-fit-1" style="padding: 0px; box-shadow:none; background:#f7f7f7;">실측사이즈 재는방법</a></label>\n'
        '\t\t\t\t</li>\n'
        '\t\t\t</ul>\n'
        '\t\t</nav>\n'
        '\t</div>\n'
        '</div>'
    )


def render_text_source(structured):
    # 추천 - 확정 샘플 형식 완전 일치
    rec = ''.join([f'▪ {x}<br>\n' for x in structured['recommend_lines']])
    # 착용후기 - 따옴표 자동 추가
    rev = ''.join([f'"{x.strip(chr(34))}"<br>\n' for x in structured['review_lines']])
    # FAQ
    faq_lines = []
    for i, faq in enumerate(structured['faqs']):
        faq_lines.append(f"{faq['q']}<br>\n")
        faq_lines.append(f"{faq['a']}<br>\n")
        if i < len(structured['faqs']) - 1:
            faq_lines.append("<br>\n")
    # 쇼핑참고 - 마지막 줄 <br> 없음
    shop = structured['shopping_lines']
    shopping = ''.join([f'▪ {x}<br>\n' for x in shop[:-1]]) + f'▪ {shop[-1]}' if len(shop) >= 2 else ''.join([f'▪ {x}<br>\n' for x in shop])

    return (
        '<div style="text-align:center;">\n'
        '<h3 style="margin-bottom:0;">\n'
        '✓ 이런 분께 추천해요!</h3>\n'
        '<br>\n'
        '<p><span style="font-size:14px; line-height:1.8;">\n'
        f'{rec}'
        '</span></p></div>\n'
        '<br><br><br><br>\n\n'
        '<div style="text-align:center;">\n'
        '<h3 style="margin-bottom:0;">\n'
        '✓ 미리 입어 본 착용후기 (모델/스텝/MD리뷰)</h3>\n'
        '<br>\n'
        '<p><span style="font-size:14px; line-height:1.8;">\n'
        f'{rev}'
        '</span></p></div>\n'
        '<br><br><br>\n\n'
        '<div style="text-align:center;">\n'
        '<h3 style="margin-bottom:0;">\n'
        '✓ (FAQ) 이 상품, 이게 궁금해요!</h3>\n'
        '<br>\n'
        '<p><span style="font-size:14px; line-height:1.4;">\n'
        f'{"".join(faq_lines)}'
        '</span></p></div>\n'
        '<br><br><br><br>\n\n'
        '<div style="text-align:center;">\n'
        '<h3 style="margin-bottom:0;">\n'
        '✓쇼핑에 꼭 참고하세요</h3>\n'
        '<br>\n'
        '<p><span style="font-size:14px; line-height:1.8;">\n'
        f'{shopping}\n'
        '</span></p></div>\n'
        '<br><br><br>'
    )


def render_subsc_html(data, structured):
    md = structured['md_sections']
    def jl(lines): return ''.join([f'{x}<br>\n' for x in lines])
    # 확정 샘플 기준: [구매 전 꼭 확인해 주세요] 섹션 없음, 마무리 3줄만
    return (
        '<div id="subsc">\n'
        f'<h3>{data["display_name"]}</h3>\n'
        '<p>\n'
        '<strong style="font-weight:700 !important;">[이 상품을 초이스한 이유입니다.]</strong><br>\n'
        f'{jl(md["choice"])}'
        '<br>\n'
        '<strong style="font-weight:700 !important;">[원단과 두께 체감에 대하여]</strong><br>\n'
        f'{jl(md["fabric"])}'
        '<br>\n'
        '<strong style="font-weight:700 !important;">[체형과 핏, 사이즈 선택 가이드]</strong><br>\n'
        f'{jl(md["fit"])}'
        '<br>\n'
        '<strong style="font-weight:700 !important;">[이렇게 입는 날이 많아집니다]</strong><br>\n'
        f'{jl(md["occasion"])}'
        '<br>\n'
        f'{jl(md["ending"])}\n'
        '</p></div>'
    )


def assemble_final_output(data, structured):
    mat_items = [x.strip() for x in (data['material'] or '').split('+') if x.strip()]
    mat_line = ' + '.join(mat_items) if mat_items else data['material']
    if '(건조기사용금지)' not in mat_line:
        mat_line = f'{mat_line} (건조기사용금지)'

    text_source = render_text_source(structured)
    subsc_html = render_subsc_html(data, structured)
    subtap_html = build_subtap_html(data, structured['material_desc_lines'])
    source_block = FIXED_HTML_HEAD + '\n\n' + subsc_html + '\n\n' + subtap_html

    lines = [
        f"상품명 : {data['display_name']}", '',
        f"컬러 : {data['color']}",
        f"사이즈 : {data['size']}",
        f"소재 : {mat_line}",
        '소재설명 :',
    ]
    for x in structured['material_desc_lines']:
        lines.append(f'- {x}')
    lines += [
        f"제조국 : {data['country']}", '',
        '-----------------', '포인트 원고(포토샵 작업)', '-----------------',
    ]
    lines.extend([''] * 11)
    lines += [
        '---------------------------------', '텍스트 소스', '---------------------------------', '',
        text_source, '',
        '----------------------------------', 'MD원고(상품 설명 소스)', '----------------------------------',
        source_block, '',
        '-----------------', '사이즈 팁', '-----------------', '',
        'ㅇ55 (90) 160cm 48kg', structured['size_tips']['55'], '',
        'ㅇ66 (95) 165cm 54kg', structured['size_tips']['66'], '',
        'ㅇ66반 (95) 164cm 58kg', structured['size_tips']['66half'], '',
        'ㅇ77 (100) 163cm 61kg', structured['size_tips']['77'],
    ]
    return '\n'.join(lines).strip()


# ─────────────────────────────────────
# UI
# ─────────────────────────────────────
st.markdown("---")
st.subheader("상품 네이밍")
ncol1, ncol2 = st.columns([5, 1], vertical_alignment="bottom")
with ncol1:
    naming_input = st.text_area("상품 주요특징 입력", height=120,
        placeholder="예: 여리핏, 부드러운 엠보 텍스처, 상체 군살 커버, 루즈핏 맨투맨",
        key="naming_input_value")
with ncol2:
    if st.button("네이밍 생성", use_container_width=True):
        if naming_input.strip():
            with st.spinner("상품명을 생성 중입니다..."):
                try:
                    resp = chat_with_retry(model="gpt-4.1",
                        messages=[{"role": "system", "content": NAME_PROMPT}, {"role": "user", "content": naming_input}],
                        temperature=0.5, max_retries=2)
                    st.session_state.naming_result = resp.choices[0].message.content.strip()
                    st.rerun()
                except RateLimitError:
                    st.error("현재 OpenAI 요청이 몰려 있습니다. 잠시 후 다시 시도해 주세요.")
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
    product_name  = st.text_input("상품명", value="( color)", key=f"product_name_{nonce}")
    color         = st.text_input("컬러", placeholder="예: 1 먹 / 2 블랙", key=f"color_{nonce}")
    size          = st.text_area("사이즈", height=90, value="FREE 사이즈로 77까지 추천드립니다.", key=f"size_{nonce}")
    material      = st.text_input("소재", placeholder="예: 폴리에스터70 + 레이온27 + 스판3", key=f"material_{nonce}")
    material_desc = st.text_area("소재설명", height=110,
        placeholder="예: 후들후들 가볍고 부드러운 무광의 소재\n예: 비침이나 구김에 강하고 유연한 핏 연출",
        key=f"material_desc_{nonce}")
    country       = st.text_input("제조국", key=f"country_{nonce}")
    top_measure   = st.text_area("상의 실측사이즈", height=120,
        value="어깨단면 / 가슴둘레 / 암홀둘레 / 소매길이 / 소매둘레 / 총장 / 총장(앞) / 총장(뒤)  단위:cm",
        key=f"top_measure_{nonce}")
    bottom_measure = st.text_area("하의 실측사이즈", height=110,
        value="F 허리둘레 / 엉덩이둘레 / 허벅지둘레 / 밑단둘레 / 총장 / 밑위 길이  단위:cm\nL 허리둘레 / 엉덩이둘레 / 허벅지둘레 / 밑단둘레 / 총장 / 밑위 길이  단위:cm",
        key=f"bottom_measure_{nonce}")
    dress_measure  = st.text_area("원피스 실측사이즈", height=130,
        value="어깨단면 / 가슴둘레 / 허리둘레 / 엉덩이둘레 / 암홀둘레 / 소매길이 / 어깨소매길이 / 총장(앞) / 총장(뒤)  단위:cm",
        key=f"dress_measure_{nonce}")

with right:
    detail_tip       = st.text_input("디테일 특징 (예:디자인, 절개라인, 부자재, 스펙상 특징 등)", key=f"detail_tip_{nonce}")
    fit              = st.text_input("핏/실루엣 (예:정핏,레귤러핏,오버핏 등/체형커버, 다리길어보이는 등의 특장점)", key=f"fit_{nonce}")
    appeal_points    = st.text_area("주요 어필 포인트 (예:고객 문제해결 포인트,원단 구김-탄력-내구성,체형커버,계절성,기능성,코디활용도 등)", height=150, key=f"appeal_points_{nonce}")
    etc              = st.text_area("기타 특징 (브랜드퀄리티,백화점납품상품,가격경쟁력,가성비,전문거래처 등)", height=120, key=f"etc_{nonce}")
    target           = st.text_input("타겟", value="4050 여성", key=f"target_{nonce}")
    washing          = st.text_input("세탁방법", value="드라이클리닝, 단독 울세탁, 손세탁 권장. 건조기 사용 금지", key=f"washing_{nonce}")
    additional_request = st.text_area("추가/수정 요청사항(출력물 확인 후 수정사항 입력)", height=120, key=f"additional_request_{nonce}")

st.subheader("이미지 업로드")
uploaded_images = st.file_uploader("이미지", type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True, key=f"uploaded_images_{nonce}")

if st.button("생성하기", type="primary", use_container_width=True, key=f"generate_{nonce}"):
    display_name = apply_color_count_to_name(product_name, color)
    measurement_lines = combine_measurements(top_measure, bottom_measure, dress_measure)
    data = {
        "product_name": product_name, "display_name": display_name,
        "color": color, "size": size, "material": material,
        "material_desc_raw": material_desc, "country": country,
        "measurement_lines": measurement_lines, "detail_tip": detail_tip,
        "fit": fit, "appeal_points": appeal_points, "etc": etc,
        "target": target, "washing": washing,
    }
    with st.spinner("출력물을 생성 중입니다..."):
        try:
            structured_raw = generate_structured_copy(data, additional_request, uploaded_images)
            structured = normalize_generated(structured_raw, data)
            result = assemble_final_output(data, structured)
        except RateLimitError:
            st.error("현재 OpenAI 요청이 몰려 있습니다. 잠시 후 다시 시도해 주세요.")
            st.stop()
        except Exception as e:
            st.error(f"원고 생성 중 오류가 발생했습니다: {e}")
            st.stop()
    st.session_state.generated_result = result
    st.session_state.generated_docx = result_to_docx_bytes(result)
    st.session_state.generated_file_stem = (display_name or "page_builder").replace(" ", "_")

if st.session_state.generated_result:
    st.text_area("결과", st.session_state.generated_result, height=1200)
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("TXT 다운로드", data=st.session_state.generated_result,
            file_name=f"{st.session_state.generated_file_stem}_output.txt",
            mime="text/plain", use_container_width=True)
    with c2:
        st.download_button("HWP 다운로드", data=st.session_state.generated_docx,
            file_name=f"{st.session_state.generated_file_stem}_output.hwp",
            mime="application/x-hwp", use_container_width=True)

st.markdown("---")
st.markdown("© made by MISHARP, MIYAWA. All rights reserved.")
