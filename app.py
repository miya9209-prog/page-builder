import base64
import io
import mimetypes
import re
from typing import List, Dict, Any

import streamlit as st
from openai import OpenAI
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT

st.set_page_config(page_title="PAGE BUILDER", layout="wide")

if "reset_nonce" not in st.session_state:
    st.session_state.reset_nonce = 0
if "naming_result" not in st.session_state:
    st.session_state.naming_result = ""
if "naming_input_value" not in st.session_state:
    st.session_state.naming_input_value = ""

st.markdown("""
<style>
div[data-testid="stButton"] > button { min-height: 42px; }
</style>
""", unsafe_allow_html=True)

st.title("MISHARP PAGE BUILDER")
st.caption("구매전환율 상승을 위한 상세페이지 기획 + 상품 원고 생성기")

api_key = st.secrets.get("OPENAI_API_KEY", "")
if not api_key:
    st.warning("OPENAI_API_KEY가 설정되지 않았습니다. Streamlit Cloud Secrets 또는 .streamlit/secrets.toml을 확인해 주세요.")
    st.stop()

client = OpenAI(api_key=api_key)

FIXED_HTML_HEAD = """<meta http-equiv="X-UA-Compatible" content="IE=edge,chrome=1">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="http://fonts.googleapis.com/css?family=Roboto" rel="stylesheet" type="text/css">
<link href="http://netdna.bootstrapcdn.com/font-awesome/4.3.0/css/font-awesome.min.css" rel="stylesheet" type="text/css">
<link href="/SRC2/cssmtmenu/style.css" rel="stylesheet" type="text/css">
<link href="//spoqa.github.io/spoqa-han-sans/css/SpoqaHanSans-kr.css" rel="stylesheet" type="text/css">
<link href="//misharp.co.kr/subtap.css" rel="stylesheet" type="text/css">"""

NAME_PROMPT = """
너는 4050 여성 패션 쇼핑몰 미샵의 상품 네이밍 전문가다.
- 상품 주요 특징을 반영해 상품명을 20개 제안한다.
- 각 상품명은 공백 포함 최대 18자 이내.
- 반드시 단어와 단어 사이를 자연스럽게 띄어쓴다.
- AI 검색, 키워드 검색 모두 고려한다.
- 디테일/형태/원단/핏 등을 반영한 단어 + 카테고리명을 포함한다.
- 필요하면 세련되고 여성스러운 단어를 앞에 붙여도 된다.
- 번호, 설명, 코드펜스 없이 한 줄에 하나씩 20개만 출력한다.
"""

PRODUCT_COPY_PROMPT = """
당신은 상세페이지 원고 전문 최고의 공감형 라이터입니다.
4050 여성 전문 쇼핑몰 미샵(MISHARP)의 상품 상세페이지를
구매 전 불안 제거, 기대치 명확화, 사이즈·핏 확신 제공을 최우선 목표로 작성합니다.

핵심 원칙
- 텍스트 입력을 우선하고 이미지는 보조 참고만 합니다.
- 동영상 안내 문구는 절대 작성하지 않습니다.
- 실측사이즈 입력 여부와 관계없이 사이즈 팁 4개는 반드시 모두 작성합니다.
- [구매 전 꼭 확인해 주세요] 안에는 세탁 관련 안내 문구를 넣지 않습니다.
- 이번 응답에서는 MD원고(상품 설명 소스) 안의 HTML 중 오직 <div id="subsc"> ... </div> 만 작성합니다.
- meta, link, Subtap은 작성하지 않습니다.

MD원고는 반드시 아래 기존 구조를 그대로 따릅니다.
1. 상품명 하단 소개 3~4줄
2. [쇼핑에 꼭 참고하세요]
3. [이 상품을 초이스한 이유입니다.]
4. [원단과 두께 체감에 대하여]
5. [체형과 핏, 사이즈 선택 가이드]
6. [이렇게 입는 날이 많아집니다]
7. [구매 전 꼭 확인해 주세요]
8. 감성 마무리 문장

중요 규칙
- 각 문장은 한 줄이 너무 길지 않게 20~28자 안팎에서 자연스럽게 <br> 처리합니다.
- 오늘 테스트 출력물처럼 긴 문장을 한 줄에 길게 쓰지 않습니다.
- 기존 스타일처럼 각 소제목을 대괄호 포함 구조화합니다.
- [쇼핑에 꼭 참고하세요] 제목을 반드시 사용합니다.
- [상품 포인트]로 바꾸지 않습니다.
- 소제목은 반드시 <strong style="font-weight:700 !important;">[제목]</strong> 형태만 사용합니다.
- 상품명은 <strong>가 아니라 반드시 <h3> 태그로만 작성합니다.

텍스트 소스 규칙
- "이런 분께 추천해요", "(FAQ) 이 상품, 이게 궁금해요", "미리 입어본 착용 후기(피팅모델/스텝/MD의 리뷰)" 3개 블록 생성
- 각 블록은 제목 아래에 반드시 <h3>구조화된 타이틀</h3>을 한번 더 넣고, 그 아래 중앙정렬 HTML을 작성합니다.
- 중앙정렬에서 보기 좋게 <br> 처리합니다.
- FAQ는 4개를 채웁니다.

사이즈 팁 규칙
- 아래 4개를 모두 작성하고, 각 항목마다 실제 내용 2~3줄을 반드시 채웁니다.
ㅇ55 (90) 160cm 48kg
ㅇ66 (95) 165cm 54kg
ㅇ66반 (95) 164cm 58kg
ㅇ77 (100) 163cm 61kg
"""

OUTPUT_RULES = """
최종 출력은 반드시 아래 순서와 제목을 그대로 지켜 하나의 텍스트 문서로 작성합니다.

상품명 :
컬러 :
사이즈 :
소재 :
소재설명 :
제조국 :

-----------------
포인트 원고(포토샵 작업)
-----------------

1. 동영상

2. 헤드라인

3. (원단컷)

4. (디테일컷)

5. (핵심어필 포인트)

---------------------------------
텍스트 소스
---------------------------------

이런 분께 추천해요
(제목 아래 h3 포함 중앙정렬 HTML 소스)

(FAQ) 이 상품, 이게 궁금해요
(제목 아래 h3 포함 중앙정렬 HTML 소스)

미리 입어본 착용 후기(피팅모델/스텝/MD의 리뷰)
(제목 아래 h3 포함 중앙정렬 HTML 소스)

----------------------------------
MD원고(상품 설명 소스)
----------------------------------
고정 메타/링크 코드
<div id="subsc"> ... </div>
<div id="Subtap"> ... </div>

-----------------
사이즈 팁
-----------------

ㅇ55 (90) 160cm 48kg
ㅇ66 (95) 165cm 54kg
ㅇ66반 (95) 164cm 58kg
ㅇ77 (100) 163cm 61kg
"""

def file_to_content_item(uploaded_file):
    mime = uploaded_file.type or mimetypes.guess_type(uploaded_file.name)[0] or "image/jpeg"
    data = uploaded_file.read()
    b64 = base64.b64encode(data).decode("utf-8")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}

def extract_lines_with_digits(text: str):
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line and re.search(r"\d", line):
            out.append(line)
    return out

def combine_measurements(top_text: str, bottom_text: str, dress_text: str):
    lines = []
    for block in [top_text, bottom_text, dress_text]:
        lines.extend(extract_lines_with_digits(block))
    return lines

def count_colors(color_text: str) -> int:
    if not color_text.strip():
        return 0
    text = color_text.replace(" / ", "\n").replace("/", "\n").replace(",", "\n")
    parts = [re.sub(r"^\s*\d+\s*", "", p).strip() for p in text.splitlines()]
    parts = [p for p in parts if p]
    return len(parts)

def apply_color_count_to_name(product_name: str, color_text: str) -> str:
    count = count_colors(color_text)
    suffix = f"({count} color)" if count > 0 else "(color)"
    name = (product_name or "").strip()
    name = re.sub(r"\(\s*color\s*\)", suffix, name, flags=re.I)
    if re.search(r"\(\s*\d+\s*color\s*\)", name, flags=re.I):
        return name
    if "( color)" in name:
        return name.replace("( color)", f" {suffix}")
    return name

def build_user_prompt(data: Dict[str, str]) -> str:
    return f"""
{PRODUCT_COPY_PROMPT}

{OUTPUT_RULES}

입력 데이터
- 상품명: {data['display_name']}
- 컬러: {data['color']}
- 사이즈: {data['size']}
- 실측사이즈: {" / ".join(data['measurement_lines'])}
- 소재: {data['material']}
- 소재설명: {data['material_desc']}
- 디테일특징: {data['detail_tip']}
- 핏/실루엣: {data['fit']}
- 주요 어필 포인트: {data['appeal_points']}
- 타겟: {data['target']}
- 세탁방법: {data['washing']}
- 기타: {data['etc']}
"""

def format_measurement_lines(lines):
    if not lines:
        return "실측사이즈 정보를 입력해 주세요."
    formatted = []
    for line in lines:
        line = re.sub(r"\s+단위:cm$", "", line).strip()
        line = re.sub(r"\s+L\s+", "<br>L ", line)
        line = re.sub(r"\s+M\s+", "<br>M ", line)
        line = re.sub(r"\s+S\s+", "<br>S ", line)
        line = re.sub(r"\s+XL\s+", "<br>XL ", line)
        line = re.sub(r"\s+", " ", line)
        formatted.append(line)
    return "<br>".join(formatted) + " (단위: cm)"

def build_subtap_html(data: Dict[str, str]):
    material_items = [x.strip() for x in (data["material"] or "").split("+") if x.strip()]
    material_line = " + ".join(material_items) if material_items else "소재 정보 입력 필요"
    if "(건조기사용금지)" not in material_line:
        material_line = f"{material_line} (건조기사용금지)"
    washing = (data["washing"] or "").strip() or "드라이클리닝, 단독 울세탁, 손세탁 권장. 건조기 사용 금지"
    size_tip = (data["size"] or "").strip() or "FREE 사이즈로 77까지 추천드립니다."
    measurement_html = format_measurement_lines(data["measurement_lines"])

    material_desc_lines = [x.strip() for x in (data["material_desc"] or "").splitlines() if x.strip()]
    if not material_desc_lines:
        material_desc_html = "상품 정보를 기준으로 소재 특성을 확인해 주세요.<br>"
    else:
        material_desc_html = "<br>\n\t\t\t\t\t\t\t\t\t".join(material_desc_lines) + "<br>"

    return f"""<div id="Subtap">
\t<div id="header2" role="banner">
\t\t<nav class="nav" role="navigation">
\t\t\t<ul class="nav__list">
\t\t\t\t<li>
\t\t\t\t\t<input id="group-1" type="checkbox" hidden="">
\t\t\t\t\t<label for="group-1" style="border-top-color: rgb(204, 204, 204); border-top-width: 1px; border-top-style: solid;">
\t\t\t\t\t\t<p class="fa fa-angle-right"></p>소재 정보</label>
\t\t\t\t\t<ul class="group-list">
\t\t\t\t\t\t<li>
\t\t\t\t\t\t\t<a href="#">
\t\t\t\t\t\t\t\t<h3>소재 : {material_line}</h3>
\t\t\t\t\t\t\t\t<p>
\t\t\t\t\t\t\t\t\t{material_desc_html}
\t\t\t\t\t\t\t\t</p>
\t\t\t\t\t\t\t\t<h3>세탁방법</h3>
\t\t\t\t\t\t\t\t<p>{washing}</p>
\t\t\t\t\t\t\t</a>
\t\t\t\t\t\t</li>
\t\t\t\t\t</ul>
\t\t\t\t</li>
\t\t\t\t<li>
\t\t\t\t\t<input id="group-2" type="checkbox" hidden="">
\t\t\t\t\t<label for="group-2">
\t\t\t\t\t\t<p class="fa fa-angle-right"></p>사이즈 정보</label>
\t\t\t\t\t<ul class="group-list gray">
\t\t\t\t\t\t<li>
\t\t\t\t\t\t\t<a href="#">
\t\t\t\t\t\t\t\t<h3>사이즈 TIP</h3>
\t\t\t\t\t\t\t\t<p>{size_tip}</p>
\t\t\t\t\t\t\t\t<h3>길이 TIP</h3>
\t\t\t\t\t\t\t\t<p>162-167cm에서는 모델핏을 참고해 주시고,
<br> 다리 길이나 체형에 따라 다르지만,
<br> 160cm이하에서는 모델의 핏보다 조금 길게
<br> 연출됩니다.</p>
\t\t\t\t\t\t\t</a>
\t\t\t\t\t\t</li>
\t\t\t\t\t</ul>
\t\t\t\t</li>
\t\t\t\t<li>
\t\t\t\t\t<input id="group-3" type="checkbox" hidden="">
\t\t\t\t\t<label for="group-3">
\t\t\t\t\t\t<p class="fa fa-angle-right"></p>실측 사이즈</label>
\t\t\t\t\t<ul class="group-list">
\t\t\t\t\t\t<li>
\t\t\t\t\t\t\t<a href="#">
\t\t\t\t\t\t\t\t<p>{measurement_html}</p>
\t\t\t\t\t\t\t</a>
\t\t\t\t\t\t</li>
\t\t\t\t\t</ul>
\t\t\t\t</li>
\t\t\t\t<li>
\t\t\t\t\t<input id="group-5" type="checkbox" hidden="">
\t\t\t\t\t<label for="group-5"><span class="fa fa-angle-right"></span>
\t\t\t\t\t\t<a href="#crema-product-fit-1" style="padding: 0px; box-shadow:none; background:#f7f7f7;">실측사이즈 재는방법</a></label>
\t\t\t\t</li>
\t\t\t</ul>
\t\t</nav>
\t</div>
</div>"""

def extract_subsc_html(result: str, product_name: str):
    m = re.search(r'<div id="subsc">[\s\S]*?</div>', result)
    if m:
        subsc = m.group(0)
    else:
        subsc = f"""<div id="subsc">
  <h3>{product_name or "상품명"}</h3>
  <p>
    본문 내용을 생성하지 못했습니다.
  </p>
</div>"""
    if '<h3>' not in subsc:
        subsc = subsc.replace('<div id="subsc">', f'<div id="subsc">\n  <h3>{product_name or "상품명"}</h3>', 1)
    return subsc

def ensure_text_source_h3(block: str, title: str):
    if "<h3>" in block:
        return block
    if "<div" in block:
        return block.replace("<div", f"<h3>{title}</h3>\n<div", 1)
    return f"{title}\n<h3>{title}</h3>\n<div style=\"text-align:center;\">\n<br>\n</div>"

def extract_block(raw: str, start_title: str, next_titles: list):
    pattern = rf'{re.escape(start_title)}[\s\S]*?(?=' + '|'.join(re.escape(t) for t in next_titles) + r'|$)'
    m = re.search(pattern, raw)
    return m.group(0).strip() if m else start_title

def fallback_size_tips():
    return {
        "ㅇ55 (90) 160cm 48kg": "전체적으로 여유가 느껴지며,\n부담 없이 편안하게 입기 좋은 핏입니다.\n실루엣이 자연스럽게 정리됩니다.",
        "ㅇ66 (95) 165cm 54kg": "가장 안정감 있게 떨어지는 핏으로,\n데일리부터 모임룩까지 활용이 좋습니다.\n라인이 단정하게 정리됩니다.",
        "ㅇ66반 (95) 164cm 58kg": "군살이 신경 쓰이는 부분을 편안하게 감싸주며,\n답답함 없이 입기 좋은 편입니다.\n전체 핏이 자연스럽습니다.",
        "ㅇ77 (100) 163cm 61kg": "체형을 편안하게 커버해 주는 실루엣으로,\n부담 없이 착용하기 좋습니다.\n안정감 있는 핏이 돋보입니다.",
    }

def extract_size_tip_block(raw_result: str, title: str, fallback_map: dict):
    block = extract_block(raw_result, title, ["ㅇ55 (90) 160cm 48kg", "ㅇ66 (95) 165cm 54kg", "ㅇ66반 (95) 164cm 58kg", "ㅇ77 (100) 163cm 61kg"])
    rest = block.replace(title, "").strip()
    if block.strip() == title.strip() or not rest:
        return title + "\n" + fallback_map[title]
    return block

def format_material_desc_for_top(material_desc: str):
    lines = [x.strip() for x in (material_desc or "").splitlines() if x.strip()]
    cleaned = []
    for line in lines:
        line = re.sub(r"(소재)(\s*소재)+", r"\1", line)
        line = re.sub(r"\s+", " ", line).strip()
        cleaned.append(line)
    return cleaned

def assemble_final_output(raw_result: str, source_block: str, data: Dict[str, str]):
    lines = []
    lines.append(f"상품명 : {data['display_name']}")
    lines.append("")
    lines.append(f"컬러 : {data['color']}")
    lines.append(f"사이즈 : {data['size']}")
    material_items = [x.strip() for x in (data["material"] or "").split("+") if x.strip()]
    material_line = " + ".join(material_items) if material_items else data["material"]
    if "(건조기사용금지)" not in material_line:
        material_line = f"{material_line} (건조기사용금지)"
    lines.append(f"소재 : {material_line}")
    lines.append("소재설명 :")
    md_lines = format_material_desc_for_top(data["material_desc"])
    if md_lines:
        for x in md_lines:
            lines.append(f"- {x}")
    else:
        lines.append("-")
    lines.append(f"제조국 : {data['country']}")
    lines.append("")
    lines.append("-----------------")
    lines.append("포인트 원고(포토샵 작업)")
    lines.append("-----------------")
    lines.append("")
    lines.append("1. 동영상")
    lines.append("")
    sec2 = extract_block(raw_result, "2. 헤드라인", ["3. (원단컷)"])
    sec3 = extract_block(raw_result, "3. (원단컷)", ["4. (디테일컷)"])
    sec4 = extract_block(raw_result, "4. (디테일컷)", ["5. (핵심어필 포인트)", "5. (핵심 어필 포인트)"]).replace("5. (핵심 어필 포인트)", "5. (핵심어필 포인트)")
    if "5. (핵심어필 포인트)" in raw_result:
        sec5 = extract_block(raw_result, "5. (핵심어필 포인트)", ["---------------------------------", "텍스트 소스", "이런 분께 추천해요"])
    else:
        sec5 = extract_block(raw_result, "5. (핵심 어필 포인트)", ["---------------------------------", "텍스트 소스", "이런 분께 추천해요"]).replace("5. (핵심 어필 포인트)", "5. (핵심어필 포인트)")
    for sec in [sec2, sec3, sec4, sec5]:
        lines.append(sec)
        lines.append("")
    lines.append("---------------------------------")
    lines.append("텍스트 소스")
    lines.append("---------------------------------")
    lines.append("")
    source_titles = ["이런 분께 추천해요", "(FAQ) 이 상품, 이게 궁금해요", "미리 입어본 착용 후기(피팅모델/스텝/MD의 리뷰)"]
    for i, title in enumerate(source_titles):
        next_titles = source_titles[i+1:] + ["----------------------------------", "MD원고(상품 설명 소스)", "-----------------", "사이즈 팁"]
        block = extract_block(raw_result, title, next_titles)
        block = ensure_text_source_h3(block, title)
        lines.append(block)
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
    fallbacks = fallback_size_tips()
    for title in ["ㅇ55 (90) 160cm 48kg", "ㅇ66 (95) 165cm 54kg", "ㅇ66반 (95) 164cm 58kg", "ㅇ77 (100) 163cm 61kg"]:
        lines.append(extract_size_tip_block(raw_result, title, fallbacks))
        lines.append("")
    return "\n".join(lines).strip()

def result_to_docx_bytes(result_text: str):
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Dotum"
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "돋움")
    style.font.size = Pt(10)

    # 기본 문단 간격 제거
    for style_name in ["Normal"]:
        s = doc.styles[style_name]
        s.paragraph_format.space_before = Pt(0)
        s.paragraph_format.space_after = Pt(0)
        s.paragraph_format.line_spacing = 1.5

    # 기본 빈 문단 제거 성격으로 첫 문단 재사용
    first = True
    for line in result_text.splitlines():
        p = doc.paragraphs[0] if first else doc.add_paragraph()
        first = False
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.5
        p.alignment = WD_PARAGRAPH_ALIGNMENT.LEFT
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

st.markdown("---")
st.subheader("상품 네이밍")
ncol1, ncol2 = st.columns([5, 1], vertical_alignment="bottom")
with ncol1:
    naming_input = st.text_area("상품 주요특징 입력", height=120, placeholder="예: 여리핏, 부드러운 엠보 텍스처, 상체 군살 커버, 루즈핏 맨투맨", key="naming_input_value")
with ncol2:
    if st.button("네이밍 생성", use_container_width=True):
        if naming_input.strip():
            with st.spinner("상품명을 생성 중입니다..."):
                response = client.chat.completions.create(
                    model="gpt-4.1",
                    messages=[{"role": "system", "content": NAME_PROMPT}, {"role": "user", "content": naming_input}],
                    temperature=0.5,
                )
                st.session_state.naming_result = response.choices[0].message.content.strip()
                st.rerun()
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
    color = st.text_input("컬러", placeholder="예: 1 먹 / 2 블랙", key=f"color_{nonce}")
    size = st.text_area("사이즈", height=90, value="FREE 사이즈로 77까지 추천드립니다.", key=f"size_{nonce}")
    material = st.text_input("소재", placeholder="예: 폴리에스터70 + 레이온27 + 스판3", key=f"material_{nonce}")
    material_desc = st.text_area("소재설명", height=110, placeholder="예: 후들후들 가볍고 부드러운 무광의 소재\n예: 비침이나 구김에 강하고 유연한 핏 연출", key=f"material_desc_{nonce}")
    country = st.text_input("제조국", key=f"country_{nonce}")
    top_measure = st.text_area("상의 실측사이즈", height=120, value="어깨단면 / 가슴둘레 / 암홀둘레 / 소매길이 / 소매둘레 / 총장 / 총장(앞) / 총장(뒤)  단위:cm", key=f"top_measure_{nonce}")
    bottom_measure = st.text_area("하의 실측사이즈", height=110, value="F 허리둘레 / 엉덩이둘레 / 허벅지둘레 / 밑단둘레 / 총장 / 밑위 길이  단위:cm\nL 허리둘레 / 엉덩이둘레 / 허벅지둘레 / 밑단둘레 / 총장 / 밑위 길이  단위:cm", key=f"bottom_measure_{nonce}")
    dress_measure = st.text_area("원피스 실측사이즈", height=130, value="어깨단면 / 가슴둘레 / 허리둘레 / 엉덩이둘레 / 암홀둘레 / 소매길이 / 어깨소매길이 / 총장(앞) / 총장(뒤)  단위:cm", key=f"dress_measure_{nonce}")

with right:
    detail_tip = st.text_input("디테일 특징 (예:디자인, 절개라인, 부자재, 스펙상 특징 등)", key=f"detail_tip_{nonce}")
    fit = st.text_input("핏/실루엣 (예:정핏,레귤러핏,오버핏 등/체형커버, 다리길어보이는 등의 특장점)", key=f"fit_{nonce}")
    appeal_points = st.text_area("주요 어필 포인트 (예:고객 문제해결 포인트,원단 구김-탄력-내구성,체형커버,계절성,기능성,코디활용도 등)", height=150, key=f"appeal_points_{nonce}")
    etc = st.text_area("기타 특징 (브랜드퀄리티,백화점납품상품,가격경쟁력,가성비,전문거래처 등)", height=120, key=f"etc_{nonce}")
    target = st.text_input("타겟", value="4050 여성", key=f"target_{nonce}")
    washing = st.text_input("세탁방법", value="드라이클리닝, 단독 울세탁, 손세탁 권장. 건조기 사용 금지", key=f"washing_{nonce}")
    additional_request = st.text_area("추가/수정 요청사항(출력물 확인 후 수정사항 입력)", height=120, key=f"additional_request_{nonce}")

st.subheader("이미지 업로드")
uploaded_images = st.file_uploader("이미지", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True, key=f"uploaded_images_{nonce}")

if st.button("생성하기", type="primary", use_container_width=True, key=f"generate_{nonce}"):
    display_name = apply_color_count_to_name(product_name, color)
    measurement_lines = combine_measurements(top_measure, bottom_measure, dress_measure)
    data = {
        "product_name": product_name,
        "display_name": display_name,
        "color": color,
        "size": size,
        "material": material,
        "material_desc": material_desc,
        "country": country,
        "top_measure": top_measure,
        "bottom_measure": bottom_measure,
        "dress_measure": dress_measure,
        "measurement_lines": measurement_lines,
        "detail_tip": detail_tip,
        "fit": fit,
        "appeal_points": appeal_points,
        "etc": etc,
        "target": target,
        "washing": washing,
    }
    prompt_text = build_user_prompt(data)
    if additional_request.strip():
        prompt_text += "\n\n추가/수정 요청사항\n" + additional_request + "\n"

    user_content: List[Dict[str, Any]] = [{"type": "text", "text": prompt_text}]
    for img in uploaded_images[:5] if uploaded_images else []:
        user_content.append(file_to_content_item(img))

    with st.spinner("출력물을 생성 중입니다..."):
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": "반드시 기존 MD원고 구조([쇼핑에 꼭 참고하세요] 포함)를 유지하고, 문장을 짧게 <br> 처리한다. 텍스트 소스는 각 블록에 h3 제목을 넣는다. 사이즈 팁 4개를 모두 채운다."},
                {"role": "user", "content": user_content}
            ],
            temperature=0.2,
        )
        raw_result = response.choices[0].message.content
        subsc_html = extract_subsc_html(raw_result, display_name)
        subtap_html = build_subtap_html(data)
        source_block = FIXED_HTML_HEAD + "\n\n" + subsc_html + "\n\n" + subtap_html
        result = assemble_final_output(raw_result, source_block, data)

    st.text_area("결과", result, height=1200)
    docx_bytes = result_to_docx_bytes(result)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button("TXT 다운로드", data=result, file_name=f"{(display_name or 'page_builder').replace(' ', '_')}_output.txt", mime="text/plain", use_container_width=True)
    with c2:
        st.download_button("HWP 다운로드", data=docx_bytes, file_name=f"{(display_name or 'page_builder').replace(' ', '_')}_output.hwp", mime="application/x-hwp", use_container_width=True)

st.markdown("---")
st.markdown("© made by MISHARP, MIYAWA. All rights reserved.")
