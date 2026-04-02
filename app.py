import base64
import io
import json
import mimetypes
import re
import time
from typing import Any, Dict, List

import streamlit as st
from openai import OpenAI, RateLimitError
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn

st.set_page_config(page_title="PAGE BUILDER", layout="wide")

# -----------------------
# session state
# -----------------------
DEFAULT_STATE = {
    "reset_nonce": 0,
    "naming_result": "",
    "naming_input_value": "",
    "generated_result": "",
    "generated_docx": b"",
    "generated_filename_base": "page_builder",
}
for k, v in DEFAULT_STATE.items():
    if k not in st.session_state:
        st.session_state[k] = v


# -----------------------
# helpers
# -----------------------
def chat_with_retry(client: OpenAI, *, model: str, messages, temperature: float = 0.4, max_retries: int = 2):
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return client.chat.completions.create(model=model, messages=messages, temperature=temperature)
        except RateLimitError as exc:
            last_exc = exc
            if attempt >= max_retries:
                raise
            time.sleep(2 * (attempt + 1))
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries:
                raise
            time.sleep(attempt + 1)
    raise last_exc


def normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def strip_number_prefix(s: str) -> str:
    return re.sub(r"^\s*\d+\s*", "", normalize_space(s))


def split_items(text: str) -> List[str]:
    raw = re.split(r"\n|/|,|·|•|⦁", text or "")
    items = []
    for x in raw:
        s = strip_number_prefix(x).strip("-▪")
        if s and s not in items:
            items.append(s)
    return items


def apply_color_count_to_name(product_name: str, color_text: str) -> str:
    colors = [strip_number_prefix(x) for x in re.split(r"\n|/|,", color_text or "")]
    colors = [c for c in colors if c]
    count = len(colors)
    suffix = f"({count} color)" if count else "(color)"
    name = normalize_space(product_name)
    if re.search(r"\(\s*\d+\s*color\s*\)", name, flags=re.I):
        return name
    if re.search(r"\(\s*color\s*\)", name, flags=re.I):
        return re.sub(r"\(\s*color\s*\)", suffix, name, flags=re.I)
    return f"{name} {suffix}".strip()


def extract_lines_with_digits(text: str) -> List[str]:
    out = []
    for raw in (text or "").splitlines():
        line = normalize_space(raw)
        if line and re.search(r"\d", line):
            out.append(line)
    return out


def combine_measurements(top_text: str, bottom_text: str, dress_text: str) -> List[str]:
    lines: List[str] = []
    for block in [top_text, bottom_text, dress_text]:
        lines.extend(extract_lines_with_digits(block))
    return lines


def format_measurement_lines(lines: List[str]) -> str:
    if not lines:
        return "실측사이즈 정보를 입력해 주세요."
    cleaned = [normalize_space(x).replace(" 단위:cm", "").replace("단위:cm", "") for x in lines]
    return "<br>".join(cleaned) + " (단위: cm)"


def material_desc_lines(material_desc: str) -> List[str]:
    return [normalize_space(x).lstrip("-") for x in (material_desc or "").splitlines() if normalize_space(x)]


def file_to_content_item(uploaded_file):
    mime = uploaded_file.type or mimetypes.guess_type(uploaded_file.name)[0] or "image/jpeg"
    data = uploaded_file.read()
    b64 = base64.b64encode(data).decode("utf-8")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def result_to_docx_bytes(result_text: str) -> bytes:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Dotum"
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "돋움")
    style.font.size = Pt(10)
    style.paragraph_format.line_spacing = 1.5
    for line in result_text.splitlines():
        p = doc.add_paragraph()
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
    st.session_state.naming_result = ""
    st.session_state.naming_input_value = ""
    st.session_state.generated_result = ""
    st.session_state.generated_docx = b""
    st.session_state.generated_filename_base = "page_builder"


FIXED_HTML_HEAD = """<meta http-equiv=\"X-UA-Compatible\" content=\"IE=edge,chrome=1\">\n<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n<link href=\"http://fonts.googleapis.com/css?family=Roboto\" rel=\"stylesheet\" type=\"text/css\">\n<link href=\"http://netdna.bootstrapcdn.com/font-awesome/4.3.0/css/font-awesome.min.css\" rel=\"stylesheet\" type=\"text/css\">\n<link href=\"/SRC2/cssmtmenu/style.css\" rel=\"stylesheet\" type=\"text/css\">\n<link href=\"//spoqa.github.io/spoqa-han-sans/css/SpoqaHanSans-kr.css\" rel=\"stylesheet\" type=\"text/css\">\n<link href=\"//misharp.co.kr/subtap.css\" rel=\"stylesheet\" type=\"text/css\">"""


def build_subtap_html(data: Dict[str, str]) -> str:
    material_line = normalize_space(data.get("material") or "소재 정보 입력 필요")
    if "(건조기사용금지)" not in material_line:
        material_line += " (건조기사용금지)"
    material_html = "\n".join([f"\t\t\t\t\t\t\t\t\t{x}<br>" for x in material_desc_lines(data.get("material_desc") or "")])
    return f'''<div id="Subtap">\n\t<div id="header2" role="banner">\n\t\t<nav class="nav" role="navigation">\n\t\t\t<ul class="nav__list">\n\t\t\t\t<li>\n\t\t\t\t\t<input id="group-1" type="checkbox" hidden="">\n\t\t\t\t\t<label for="group-1" style="border-top-color: rgb(204, 204, 204); border-top-width: 1px; border-top-style: solid;">\n\t\t\t\t\t\t<p class="fa fa-angle-right"></p>소재 정보</label>\n\t\t\t\t\t<ul class="group-list">\n\t\t\t\t\t\t<li>\n\t\t\t\t\t\t\t<a href="#">\n\t\t\t\t\t\t\t\t<h3>소재 : {material_line}</h3>\n\t\t\t\t\t\t\t\t<p>\n{material_html}\n\t\t\t\t\t\t\t\t</p>\n\t\t\t\t\t\t\t\t<h3>세탁방법</h3>\n\t\t\t\t\t\t\t\t<p>{normalize_space(data.get('washing') or '드라이클리닝, 단독 울세탁, 손세탁 권장. 건조기 사용 금지')}</p>\n\t\t\t\t\t\t\t</a>\n\t\t\t\t\t\t</li>\n\t\t\t\t\t</ul>\n\t\t\t\t</li>\n\t\t\t\t<li>\n\t\t\t\t\t<input id="group-2" type="checkbox" hidden="">\n\t\t\t\t\t<label for="group-2"><p class="fa fa-angle-right"></p>사이즈 정보</label>\n\t\t\t\t\t<ul class="group-list gray">\n\t\t\t\t\t\t<li><a href="#">\n\t\t\t\t\t\t\t<h3>사이즈 TIP</h3>\n\t\t\t\t\t\t\t<p>{normalize_space(data.get('size') or 'FREE 사이즈로 77까지 추천드립니다.')}</p>\n\t\t\t\t\t\t\t<h3>길이 TIP</h3>\n\t\t\t\t\t\t\t<p>162-167cm에서는 모델핏을 참고해 주시고,<br> 다리 길이나 체형에 따라 다르지만,<br> 160cm이하에서는 모델의 핏보다 조금 길게<br> 연출됩니다.</p>\n\t\t\t\t\t\t</a></li>\n\t\t\t\t\t</ul>\n\t\t\t\t</li>\n\t\t\t\t<li>\n\t\t\t\t\t<input id="group-3" type="checkbox" hidden="">\n\t\t\t\t\t<label for="group-3"><p class="fa fa-angle-right"></p>실측 사이즈</label>\n\t\t\t\t\t<ul class="group-list"><li><a href="#"><p>{format_measurement_lines(data.get('measurement_lines') or [])}</p></a></li></ul>\n\t\t\t\t</li>\n\t\t\t\t<li>\n\t\t\t\t\t<input id="group-5" type="checkbox" hidden="">\n\t\t\t\t\t<label for="group-5"><span class="fa fa-angle-right"></span><a href="#crema-product-fit-1" style="padding: 0px; box-shadow:none; background:#f7f7f7;">실측사이즈 재는방법</a></label>\n\t\t\t\t</li>\n\t\t\t</ul>\n\t\t</nav>\n\t</div>\n</div>'''


# -------- content generation --------

def _simple_wrap(sentence: str, width: int = 24) -> List[str]:
    words = normalize_space(sentence).split()
    if not words:
        return []
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) <= width:
            cur = f"{cur} {w}".strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _clean_phrase(text: str) -> str:
    t = normalize_space(text)
    t = re.sub(r"[-–—]+", " ", t)
    t = re.sub(r"\s*,\s*", ", ", t)
    return t


def heuristic_copy(data: Dict[str, str]) -> Dict[str, Any]:
    name = data["display_name"]
    fit = _clean_phrase(data.get("fit", ""))
    details = split_items(data.get("detail_tip", ""))
    appeals = split_items(data.get("appeal_points", ""))
    materials = material_desc_lines(data.get("material_desc", ""))
    color = data.get("color", "")
    bright = any(c in color for c in ["아이보리", "화이트", "크림"])

    rec = [
        "▪ 격식 있는 자리에도 단정한 무드를 원하시는 분",
        f"▪ {fit}을 중요하게 보시는 분" if fit else "▪ 군살 부담 없이 편안한 핏을 원하시는 분",
        f"▪ {details[0]} 디테일을 좋아하시는 분" if details else "▪ 기본 아이템도 밋밋하지 않게 입고 싶으신 분",
        "▪ 데님, 스커트, 슬랙스까지 폭넓게 매치할 상의를 찾는 분",
    ]

    reviews = [
        '"피부에 닿는 촉감이 부드러워 오래 입어도 부담이 없었어요."',
        f'"{fit}이라 체형이 한결 정돈돼 보여 만족스러웠어요."' if fit else '"전체 실루엣이 과하지 않아 편하게 입기 좋았어요."',
        f'"{details[0]} 디테일이 은은하게 살아 있어 단독으로도 충분히 멋스러워요."' if details else '"단정하면서도 밋밋하지 않아 손이 자주 가는 타입이에요."',
        '"하루 종일 입어도 비교적 깔끔한 인상이 유지돼 만족도가 높았어요."',
    ]

    shopping = [f"▪ {normalize_space(data.get('size') or 'FREE 사이즈로 77까지 추천드립니다.')}" ]
    if bright:
        shopping.append("▪ 아이보리는 밝은 컬러 특성상 스킨톤 이너와 함께 착용하시면 더욱 안정감 있게 입으실 수 있습니다.")
    if details:
        shopping.append(f"▪ {details[0]} 디테일은 과하지 않아 다양한 하의와 자연스럽게 매치됩니다.")
    else:
        shopping.append("▪ 실측사이즈를 함께 확인하시면 더욱 만족스러운 선택에 도움이 됩니다.")

    faq = [
        ["Q. FREE 사이즈, 77까지 정말 맞나요?", f"A. {normalize_space(data.get('size') or 'FREE 사이즈로 77까지 추천드립니다.')}"],
        ["Q. 원단이 너무 얇거나 힘이 없진 않나요?", f"A. {materials[0] if materials else '부담 없는 두께감으로 데일리하게 활용하기 좋습니다.'}"],
        ["Q. 비침이 심한가요?", "A. 밝은 컬러는 약간의 비침이 있을 수 있어 스킨톤 이너와 함께 착용하시면 더욱 안정감 있게 입으실 수 있습니다." if bright else "A. 비침 부담이 크지 않아 단독으로도 비교적 편하게 활용하기 좋습니다."],
        ["Q. 구김이 많이 가나요?", "A. 구김이 적은 소재 특성상 오랜 시간 비교적 깔끔하게 유지됩니다."],
    ]

    md = {
        "reason": [
            f"기본에 충실한 실루엣에 {details[0]} 디테일이 더해져 단정하면서도 세련된 분위기를 완성합니다." if details else "기본에 충실한 실루엣으로 단정하면서도 세련된 분위기를 완성합니다.",
            f"{fit}이라 체형 부담을 덜어주고 데일리부터 격식 있는 자리까지 폭넓게 활용하기 좋습니다." if fit else "체형 부담을 덜어주는 실루엣으로 데일리부터 격식 있는 자리까지 폭넓게 활용하기 좋습니다.",
            f"{name}은 과하지 않으면서도 고급스러운 인상을 남겨 손이 자주 가는 아이템입니다.",
        ],
        "fabric": materials[:3] if materials else ["부드러운 터치감과 자연스러운 드레이프가 느껴집니다.", "부담 없는 두께감으로 데일리하게 활용하기 좋습니다."],
        "fit": [
            normalize_space(data.get('size') or 'FREE 사이즈로 77까지 추천드립니다.'),
            f"{fit}이 자연스럽게 표현돼 상체 라인이 한결 정돈돼 보입니다." if fit else "전체적으로 여유 있는 실루엣으로 상체 라인을 자연스럽게 정리해줍니다.",
            f"{details[0]} 디테일이 은은한 포인트가 되어 밋밋하지 않게 마무리됩니다." if details else "과하지 않은 디테일로 체형에 구애 없이 단정하게 입기 좋습니다.",
        ],
        "wear": [
            "오피스룩, 모임룩, 데일리룩까지 자연스럽게 이어져 활용도가 높습니다.",
            "슬랙스, 스커트, 데님 등 다양한 하의와 무리 없이 매치됩니다.",
            "단정한 인상이 필요한 날 부담 없이 손이 가는 상의가 되어줍니다.",
        ],
    }

    size_tips = [
        ["ㅇ55 (90) 160cm 48kg", "전체적으로 여유 있게 떨어져 단독으로도 부담 없이 입기 좋고, 실루엣이 과하게 부해 보이지 않습니다."],
        ["ㅇ66 (95) 165cm 54kg", "어깨와 가슴 라인이 답답하지 않게 정리되어 데일리와 오피스룩 모두 활용하기 좋습니다."],
        ["ㅇ66반 (95) 164cm 58kg", "상체 군살이 자연스럽게 커버되고 전체 실루엣이 깔끔하게 정리되는 편입니다."],
        ["ㅇ77 (100) 163cm 61kg", "여유 있는 품으로 체형 구애 없이 편안하게 착용 가능하며 과하게 조이지 않아 안정감 있게 입기 좋습니다."],
    ]

    return {"recommend": rec, "reviews": reviews, "faq": faq, "shopping": shopping, "md": md, "size_tips": size_tips}


def llm_copy(client: OpenAI, data: Dict[str, str], image_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    prompt = f"""
너는 20년차 4050 여성의류 쇼핑몰 미샵의 상세페이지 원고 에디터다.
입력값을 그대로 복붙하지 말고 자연스럽고 설득력 있는 문장으로 재작성해야 한다.
다른 상품 정보를 절대 섞지 말고, 아래 입력값만 사용한다.

반드시 JSON만 출력한다. 코드펜스 금지.
키 구조:
{{
  "recommend": [문장4개],
  "reviews": [후기문장4개],
  "faq": [[질문,답변],[질문,답변],[질문,답변],[질문,답변]],
  "shopping": [문장3개],
  "md": {{
    "reason": [문장3~4개],
    "fabric": [문장3개],
    "fit": [문장3개],
    "wear": [문장3개]
  }},
  "size_tips": [[제목,본문],[제목,본문],[제목,본문],[제목,본문]]
}}

규칙:
- recommend는 '이런 분께 추천해요'용. 각 문장은 자연스럽고 짧게.
- reviews는 실제 착용후기처럼 자연스럽게. 입력키워드를 나열하지 말 것.
- faq는 현재 상품 정보만 반영. 없는 디테일을 만들지 말 것.
- shopping은 실무 안내 3개. 비침/탈부착/실측 등 필요한 점만.
- md.reason/fabric/fit/wear 는 MD원고 4개 소제목용 문장.
- 문장 길이는 너무 길지 않게. 줄바꿈하기 쉬운 길이로.
- 상품명을 반복 남발하지 말 것.
- 디테일 특징/핏/어필 포인트의 키워드를 그대로 복붙하지 말고 자연스러운 설명으로 풀어쓸 것.
- '전체적인 완성도를 높여줍니다' 같은 상투 반복 금지.

입력값:
상품명: {data['display_name']}
컬러: {data['color']}
사이즈: {data['size']}
소재: {data['material']}
소재설명: {' / '.join(material_desc_lines(data['material_desc']))}
디테일 특징: {data['detail_tip']}
핏/실루엣: {data['fit']}
주요 어필 포인트: {data['appeal_points']}
기타 특징: {data['etc']}
타겟: {data['target']}
세탁방법: {data['washing']}
실측사이즈: {' / '.join(data['measurement_lines'])}
추가/수정 요청사항: {data.get('additional_request','')}
"""
    content = [{"type": "text", "text": prompt}] + image_items
    resp = chat_with_retry(
        client,
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": "너는 여성의류 상세페이지 원고를 정확하고 자연스럽게 쓰는 에디터다. 반드시 JSON만 출력한다."},
            {"role": "user", "content": content},
        ],
        temperature=0.45,
        max_retries=2,
    )
    raw = resp.choices[0].message.content.strip()
    raw = re.sub(r"^```json\s*|```$", "", raw, flags=re.S).strip()
    parsed = json.loads(raw)
    return parsed


def safe_list(v, n=None):
    arr = [normalize_space(str(x)) for x in (v or []) if normalize_space(str(x))]
    return arr[:n] if n else arr


def safe_pairs(v, n=4):
    out = []
    for item in (v or []):
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            q, a = normalize_space(str(item[0])), normalize_space(str(item[1]))
            if q and a:
                out.append([q, a])
        if len(out) >= n:
            break
    return out


def line_chunks(sentence: str, width: int = 26) -> List[str]:
    s = normalize_space(sentence)
    if not s:
        return []
    chunks = re.split(r"(?<=[,])\s+|(?<=다\.)\s+|(?<=요\.)\s+|(?<=니다\.)\s+|(?<=며)\s+|(?<=고)\s+", s)
    lines = []
    buf = ""
    for ch in chunks:
        ch = normalize_space(ch)
        if not ch:
            continue
        if not buf:
            buf = ch
        elif len(buf) + len(ch) + 1 <= width:
            buf += " " + ch
        else:
            lines.append(buf)
            buf = ch
    if buf:
        lines.append(buf)
    if len(lines) == 1 and len(lines[0]) > width + 6:
        return _simple_wrap(lines[0], width)
    return lines


def br_join(lines: List[str], indent: str = "\t\t<br> ") -> str:
    out = []
    for s in lines:
        for ln in line_chunks(s):
            out.append(f"{indent}{ln}")
    return "\n".join(out)


def build_text_source_blocks(copy: Dict[str, Any]) -> List[str]:
    rec_lines = [f"▪ {x.lstrip('▪ ').strip()}" for x in safe_list(copy.get("recommend"), 4)]
    reviews = [f'"{x.strip("\"")}"' for x in safe_list(copy.get("reviews"), 4)]
    faq = safe_pairs(copy.get("faq"), 4)
    shopping = [f"▪ {x.lstrip('▪ ').strip()}" for x in safe_list(copy.get("shopping"), 3)]

    blocks = []
    blocks.append('<div style="text-align:center;">\n\t<h3 style="margin-bottom:0;">\n\t\t✓ 이런 분께 추천해요!</h3>\n\t<br>\n\t<p>\n\t\t<span style="font-size:14px; line-height:1.8;">\n' + "<br>\n".join(rec_lines) + '\n</span>\n\t\t<br>\n\t\t<br>\n\t\t<br>\n\t</p>\n</div>')
    blocks.append('<div style="text-align:center;">\n\t<h3 style="margin-bottom:0;">\n\t\t✓ 미리 입어 본 착용후기 (모델/스텝/MD리뷰)</h3>\n\t<br>\n\t<p>\n\t\t<span style="font-size:14px; line-height:1.8;">\n' + "<br>\n".join(reviews) + '\n</span>\n\t\t<br>\n\t\t<br>\n\t\t<br>\n\t</p>\n</div>')

    faq_body = []
    for q, a in faq:
        faq_body.append(q)
        faq_body.append(a)
        faq_body.append("")
    blocks.append('<div style="text-align:center;">\n\t<h3 style="margin-bottom:0;">\n\t\t✓ (FAQ) 이 상품, 이게 궁금해요!</h3>\n\t<br>\n\t<p><span style="font-size:14px; line-height:1.4;">\n' + "<br>\n".join([x for x in faq_body]) + '\n</span>\n\t\t<br>\n\t\t<br>\n\t\t<br>\n\t</p>\n</div>')
    blocks.append('<div style="text-align:center;">\n\t<h3 style="margin-bottom:0;">\n\t\t✓ 쇼핑에 꼭 참고하세요</h3>\n\t<br>\n\t<p>\n\t\t<span style="font-size:14px; line-height:1.8;">\n' + "<br>\n".join(shopping) + '\n</span>\n\t\t<br>\n\t\t<br>\n\t\t<br>\n\t</p>\n</div>')
    return blocks


def build_md_subsc(data: Dict[str, str], copy: Dict[str, Any]) -> str:
    md = copy.get("md", {}) if isinstance(copy.get("md"), dict) else {}
    reason = safe_list(md.get("reason"), 4)
    fabric = safe_list(md.get("fabric"), 3)
    fit = safe_list(md.get("fit"), 3)
    wear = safe_list(md.get("wear"), 3)
    return f'''<div id="subsc">\n<h3>{data['display_name']}</h3>\n\n\t<p>\n\t\t<strong style="font-weight:700 !important;">[이 상품을 초이스한 이유입니다.]</strong>\n{br_join(reason)}\n\t\t<br>\n\t\t<br>\n\t\t<strong style="font-weight:700 !important;">[원단과 두께 체감에 대하여]</strong>\n{br_join(fabric)}\n\t\t<br>\n\t\t<br>\n\t\t<strong style="font-weight:700 !important;">[체형과 핏, 사이즈 선택 가이드]</strong>\n{br_join(fit)}\n\t\t<br>\n\t\t<br>\n\t\t<strong style="font-weight:700 !important;">[이렇게 입는 날이 많아집니다]</strong>\n{br_join(wear)}\n\t\t<br>\n\t\t<br>\n\t</p>\n\n</div>'''


def build_size_tips(copy: Dict[str, Any]) -> List[str]:
    tips = safe_pairs(copy.get("size_tips"), 4)
    default_titles = ["ㅇ55 (90) 160cm 48kg", "ㅇ66 (95) 165cm 54kg", "ㅇ66반 (95) 164cm 58kg", "ㅇ77 (100) 163cm 61kg"]
    lines = []
    for i, title in enumerate(default_titles):
        body = tips[i][1] if i < len(tips) else "체형에 따라 편안하게 착용하실 수 있습니다."
        lines.extend([title, normalize_space(body), ""])
    return lines


def generate_copy(client: OpenAI | None, data: Dict[str, str], images) -> Dict[str, Any]:
    if client:
        try:
            image_items = []
            for img in images or []:
                try:
                    image_items.append(file_to_content_item(img))
                except Exception:
                    pass
            return llm_copy(client, data, image_items)
        except Exception:
            pass
    return heuristic_copy(data)


def assemble_output(data: Dict[str, str], copy: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"상품명 : {data['display_name']}")
    lines.append("")
    lines.append(f"컬러 : {data['color']}")
    lines.append(f"사이즈 : {data['size']}")
    material_line = normalize_space(data['material'])
    if material_line and "(건조기사용금지)" not in material_line:
        material_line += " (건조기사용금지)"
    lines.append(f"소재 : {material_line}")
    lines.append("소재설명 :")
    for m in material_desc_lines(data['material_desc']) or ["-"]:
        lines.append(f"- {m}" if m != "-" else m)
    lines.append(f"제조국 : {data['country']}")
    lines.append("")
    lines.append("")
    lines.append("○ 포인트 코멘트 ")
    lines.append("-")
    lines.append("")
    lines.append("")
    lines.append("---------------------------------")
    lines.append("텍스트 소스")
    lines.append("---------------------------------")
    lines.append("")
    lines.extend(build_text_source_blocks(copy))
    lines.append("")
    lines.append("----------------------------------")
    lines.append("MD원고(상품 설명 소스)")
    lines.append("----------------------------------")
    lines.append(FIXED_HTML_HEAD)
    lines.append("")
    lines.append(build_md_subsc(data, copy))
    lines.append("")
    lines.append(build_subtap_html(data))
    lines.append("")
    lines.append("-----------------")
    lines.append("사이즈 팁")
    lines.append("-----------------")
    lines.append("")
    lines.extend(build_size_tips(copy))
    return "\n".join(lines).strip()


# -----------------------
# UI
# -----------------------
st.markdown('<style>div[data-testid="stButton"] > button { min-height: 42px; }</style>', unsafe_allow_html=True)
st.title("MISHARP PAGE BUILDER")
st.caption("구매전환율 상승을 위한 상세페이지 기획 + 상품 원고 생성기")

api_key = st.secrets.get("OPENAI_API_KEY", "")
client = OpenAI(api_key=api_key) if api_key else None

st.markdown("---")
st.subheader("상품 네이밍")
ncol1, ncol2 = st.columns([5, 1], vertical_alignment="bottom")
with ncol1:
    naming_input = st.text_area("상품 주요특징 입력", height=120, key="naming_input_value")
with ncol2:
    if st.button("네이밍 생성", use_container_width=True):
        if naming_input.strip() and client:
            try:
                response = chat_with_retry(
                    client,
                    model="gpt-4.1",
                    messages=[
                        {"role": "system", "content": "너는 4050 여성 패션 쇼핑몰 미샵의 상품 네이밍 전문가다. 상품명을 20개 제안한다. 한 줄에 하나씩만 출력한다."},
                        {"role": "user", "content": naming_input},
                    ],
                    temperature=0.5,
                    max_retries=2,
                )
                st.session_state.naming_result = response.choices[0].message.content.strip()
                st.rerun()
            except Exception as e:
                st.error(f"네이밍 생성 중 오류가 발생했습니다: {e}")
        elif not client:
            st.warning("OPENAI_API_KEY가 설정되지 않았습니다.")
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
    color = st.text_input("컬러", key=f"color_{nonce}")
    size = st.text_area("사이즈", height=90, value="FREE 사이즈로 77까지 추천드립니다.", key=f"size_{nonce}")
    material = st.text_input("소재", key=f"material_{nonce}")
    material_desc = st.text_area("소재설명", height=110, key=f"material_desc_{nonce}")
    country = st.text_input("제조국", value="한국", key=f"country_{nonce}")
    top_measure = st.text_area("상의 실측사이즈", height=120, value="어깨단면 / 가슴둘레 / 암홀둘레 / 소매길이 / 소매둘레 / 총장 / 총장(앞) / 총장(뒤)  단위:cm", key=f"top_measure_{nonce}")
    bottom_measure = st.text_area("하의 실측사이즈", height=110, value="F 허리둘레 / 엉덩이둘레 / 허벅지둘레 / 밑단둘레 / 총장 / 밑위 길이  단위:cm\nL 허리둘레 / 엉덩이둘레 / 허벅지둘레 / 밑단둘레 / 총장 / 밑위 길이  단위:cm", key=f"bottom_measure_{nonce}")
    dress_measure = st.text_area("원피스 실측사이즈", height=130, value="어깨단면 / 가슴둘레 / 허리둘레 / 엉덩이둘레 / 암홀둘레 / 소매길이 / 어깨소매길이 / 총장(앞) / 총장(뒤)  단위:cm", key=f"dress_measure_{nonce}")
with right:
    detail_tip = st.text_input("디테일 특징 (예:디자인, 절개라인, 부자재, 스펙상 특징 등)", key=f"detail_tip_{nonce}")
    fit = st.text_input("핏/실루엣 (예:정핏,레귤러핏,오버핏 등/체형커버, 다리길어보이는 등의 특장점)", key=f"fit_{nonce}")
    appeal_points = st.text_area("주요 어필 포인트", height=150, key=f"appeal_points_{nonce}")
    etc = st.text_area("기타 특징", height=120, key=f"etc_{nonce}")
    target = st.text_input("타겟", value="4050 여성", key=f"target_{nonce}")
    washing = st.text_input("세탁방법", value="드라이클리닝, 단독 울세탁, 손세탁 권장. 건조기 사용 금지", key=f"washing_{nonce}")
    additional_request = st.text_area("추가/수정 요청사항(출력물 확인 후 수정사항 입력)", height=120, key=f"additional_request_{nonce}")

st.subheader("이미지 업로드")
uploaded_images = st.file_uploader("이미지", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True, key=f"uploaded_images_{nonce}")

if st.button("생성하기", type="primary", use_container_width=True, key=f"generate_{nonce}"):
    display_name = apply_color_count_to_name(product_name, color)
    data = {
        "product_name": product_name,
        "display_name": display_name,
        "color": color,
        "size": normalize_space(size),
        "material": normalize_space(material),
        "material_desc": material_desc,
        "country": normalize_space(country) or "한국",
        "measurement_lines": combine_measurements(top_measure, bottom_measure, dress_measure),
        "detail_tip": detail_tip,
        "fit": fit,
        "appeal_points": appeal_points,
        "etc": etc,
        "target": target,
        "washing": washing,
        "additional_request": additional_request,
    }
    copy = generate_copy(client, data, uploaded_images)
    result = assemble_output(data, copy).replace("&nbsp;", "")
    st.session_state.generated_result = result
    st.session_state.generated_docx = result_to_docx_bytes(result)
    st.session_state.generated_filename_base = (display_name or "page_builder").replace(" ", "_")

if st.session_state.generated_result:
    st.text_area("결과", st.session_state.generated_result, height=1200)
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("TXT 다운로드", data=st.session_state.generated_result, file_name=f"{st.session_state.generated_filename_base}_output.txt", mime="text/plain", use_container_width=True)
    with c2:
        st.download_button("HWP 다운로드", data=st.session_state.generated_docx, file_name=f"{st.session_state.generated_filename_base}_output.hwp", mime="application/x-hwp", use_container_width=True)

st.markdown("---")
st.markdown("© made by MISHARP, MIYAWA. All rights reserved.")
