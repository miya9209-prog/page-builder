import base64
import io
import mimetypes
import re
import time
from typing import Dict, Any, List

import streamlit as st
from openai import OpenAI, RateLimitError
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn

st.set_page_config(page_title="PAGE BUILDER", layout="wide")

for key, default in {
    "reset_nonce": 0,
    "naming_result": "",
    "naming_input_value": "",
    "generated_result": "",
    "generated_docx": b"",
    "generated_file_stem": "page_builder",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

st.markdown("""
<style>
div[data-testid="stButton"] > button { min-height: 42px; }
</style>
""", unsafe_allow_html=True)

st.title("MISHARP PAGE BUILDER")
st.caption("구매전환율 상승을 위한 상세페이지 기획 + 상품 원고 생성기")

api_key = st.secrets.get("OPENAI_API_KEY", "")
client = OpenAI(api_key=api_key) if api_key else None

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
- 번호, 설명, 코드펜스 없이 한 줄에 하나씩 20개만 출력한다.
"""


def chat_with_retry(*, model: str, messages, temperature: float = 0.2, max_retries: int = 2):
    if client is None:
        raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
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


def file_to_content_item(uploaded_file):
    mime = uploaded_file.type or mimetypes.guess_type(uploaded_file.name)[0] or "image/jpeg"
    data = uploaded_file.read()
    b64 = base64.b64encode(data).decode("utf-8")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def extract_lines_with_digits(text: str):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip() and re.search(r"\d", ln)]


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
    return len([p for p in parts if p])


def apply_color_count_to_name(product_name: str, color_text: str) -> str:
    count = count_colors(color_text)
    suffix = f"({count} color)" if count > 0 else "(color)"
    name = (product_name or "").strip()
    if re.search(r"\(\s*\d+\s*color\s*\)", name, flags=re.I):
        return name
    if re.search(r"\(\s*color\s*\)", name, flags=re.I):
        return re.sub(r"\(\s*color\s*\)", suffix, name, flags=re.I)
    return f"{name} {suffix}".strip()


def format_material_desc_for_top(material_desc: str):
    lines = [re.sub(r"\s+", " ", x.strip()) for x in (material_desc or "").splitlines() if x.strip()]
    return lines[:4]


def rewrite_material_desc(data: Dict[str, str]) -> str:
    memo = (data.get("material_desc") or "").strip()
    material = (data.get("material") or "").strip()
    if not api_key or (not memo and not material):
        return memo
    prompt = f"""
너는 여성의류 쇼핑몰 상세페이지의 소재설명 전문 에디터다.
- 소재: {material}
- 참고메모: {memo}
규칙:
- 2~3개의 짧은 리스팅 문장으로 작성한다.
- 과장 없이 실무자가 바로 상세페이지에 넣을 수 있게 쓴다.
- 결과는 문장만 줄바꿈으로 출력한다.
"""
    try:
        response = chat_with_retry(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": "사용자가 입력한 추가/수정 요청사항은 최우선으로 반드시 반영해야 한다."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_retries=1,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return memo


def split_korean_line(text: str, max_len: int = 28) -> List[str]:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []
    words = text.split(" ")
    lines, buf = [], ""
    for word in words:
        cand = (buf + " " + word).strip()
        if buf and len(cand) > max_len:
            lines.append(buf)
            buf = word
        else:
            buf = cand
    if buf:
        lines.append(buf)
    return lines


def md_lines_to_html(lines: List[str]) -> str:
    out = []
    for line in lines:
        for part in split_korean_line(line):
            out.append(f"\t\t<br> {part}")
    return "\n".join(out)


def build_md_subsc_stable(data: Dict[str, str]) -> str:
    name = data.get("display_name") or "상품명"
    material_lines = format_material_desc_for_top(data.get("material_desc") or "")
    while len(material_lines) < 3:
        fallback = [
            "피부에 닿는 촉감이 매우 부드럽고 편안합니다.",
            "은은한 광택감이 고급스러움을 더합니다.",
            "구김이 적어 데일리로도 부담 없이 착용하실 수 있는 두께감입니다.",
        ][len(material_lines)]
        material_lines.append(fallback)
    sections = [
        ("[이 상품을 초이스한 이유입니다.]", [
            "브이넥과 타이 장식이 얼굴을 갸름하게 연출해주고 여성스러운 분위기를 극대화합니다.",
            "특히 타이를 빼고 블라우스 그대로를 표현, 또한 타이를 다양하게 활용할 수 있어서 매번 색다른 아이템처럼 연출할 수가 있습니다.",
            "소매의 볼륨감과 앞 절개라인으로 군살 커버와 동시에 세련된 핏을 선사합니다.",
            "브랜드 퀄리티의 고급 소재로 오랜 시간 만족스럽게 착용하실 수 있습니다.",
        ]),
        ("[원단과 두께 체감에 대하여]", [
            material_lines[0], material_lines[1], material_lines[2]
        ]),
        ("[체형과 핏, 사이즈 선택 가이드]", [
            "FREE 사이즈로 55~77까지 여유 있게 착용 가능합니다.",
            "어깨선이 자연스럽게 떨어지고 볼륨 소매가 팔 라인을 커버해 체형 구애 없이 누구나 편안하게 입으실 수 있어요.",
            "앞 절개라인이 상체를 슬림하게 연출해주는 효과가 있습니다.",
        ]),
        ("[이렇게 입는 날이 많아집니다]", [
            "중요한 미팅이나 모임, 격식 있는 자리 여성스러운 오피스룩, 하객룩으로도 추천드려요.",
            "데님이나 슬랙스와 매치해 데일리룩으로도 손색없습니다.",
            "스카프 스트랩을 활용해 다양한 분위기로 연출해보세요.",
        ]),
    ]
    html = [f'<div id="subsc">', f'<h3>{name}</h3>', '', '\t<p>']
    for idx, (title, lines) in enumerate(sections):
        if idx > 0:
            html += ['\t\t<br>', '\t\t<br>']
        html.append(f'\t\t<strong style="font-weight:700 !important;">{title}</strong>')
        html.append(md_lines_to_html(lines))
    html += ['\t\t<br>', '\t\t<br>', '\t</p>', '', '</div>']
    return "\n".join(html)


def format_measurement_lines(lines):
    if not lines:
        return "실측사이즈 정보를 입력해 주세요."
    return "<br>".join([re.sub(r"\s+", " ", ln).strip() for ln in lines]) + " (단위: cm)"


def build_subtap_html(data: Dict[str, str]):
    material_line = (data.get("material") or "").strip() or "소재 정보 입력 필요"
    if "(건조기사용금지)" not in material_line:
        material_line += " (건조기사용금지)"
    washing = (data.get("washing") or "").strip() or "드라이클리닝, 단독 울세탁, 손세탁 권장. 건조기 사용 금지"
    size_tip = (data.get("size") or "").strip() or "FREE 사이즈로 77까지 추천드립니다."
    material_desc_html = "<br>\n".join(format_material_desc_for_top(data.get("material_desc") or "")) + ("<br>" if data.get("material_desc") else "")
    measurement_html = format_measurement_lines(data.get("measurement_lines") or [])
    return f"""<div id="Subtap">
	<div id="header2" role="banner">
		<nav class="nav" role="navigation">
			<ul class="nav__list">
				<li>
					<input id="group-1" type="checkbox" hidden="">
					<label for="group-1" style="border-top-color: rgb(204, 204, 204); border-top-width: 1px; border-top-style: solid;">
						<p class="fa fa-angle-right"></p>소재 정보</label>
					<ul class="group-list"><li><a href="#"><h3>소재 : {material_line}</h3><p>{material_desc_html}</p><h3>세탁방법</h3><p>{washing}</p></a></li></ul>
				</li>
				<li>
					<input id="group-2" type="checkbox" hidden="">
					<label for="group-2"><p class="fa fa-angle-right"></p>사이즈 정보</label>
					<ul class="group-list gray"><li><a href="#"><h3>사이즈 TIP</h3><p>{size_tip}</p><h3>길이 TIP</h3><p>162-167cm에서는 모델핏을 참고해 주시고,<br> 다리 길이나 체형에 따라 다르지만,<br> 160cm이하에서는 모델의 핏보다 조금 길게<br> 연출됩니다.</p></a></li></ul>
				</li>
				<li>
					<input id="group-3" type="checkbox" hidden="">
					<label for="group-3"><p class="fa fa-angle-right"></p>실측 사이즈</label>
					<ul class="group-list"><li><a href="#"><p>{measurement_html}</p></a></li></ul>
				</li>
				<li>
					<input id="group-5" type="checkbox" hidden="">
					<label for="group-5"><span class="fa fa-angle-right"></span><a href="#crema-product-fit-1" style="padding: 0px; box-shadow:none; background:#f7f7f7;">실측사이즈 재는방법</a></label>
				</li>
			</ul>
		</nav>
	</div>
</div>"""


def build_recommend_block() -> str:
    body = """▪ 격식 있는 자리에도 여성스러운 무드를 원하시는 분
<br> ▪ 브이넥으로 얼굴이 갸름해 보이고 싶은 분
<br> ▪ 데님, 스커트, 슬랙스 등 다양한 스타일링을 원하는 분
<br> ▪ 고급스러운 텍스처를 좋아하시는 분"""
    return f"""<div style="text-align:center;">
	<h3 style="margin-bottom:0;">
		✓ 이런 분께 추천해요!</h3>
	<br>
	<p>
		<span style="font-size:14px; line-height:1.8;">
{body}
</span>
		<br>
		<br>
		<br>
	</p>
</div>"""


def build_review_block() -> str:
    body = '''"브이넥 라인이 얼굴을 작아 보이게 해 줘요. "
<br> "타이없이, 그냥 늘어뜨리기, 리본느낌,
<br> 스트랩으로 다양한 분위기 연출이 가능해서 좋아요."
<br> "하나만으로도 스타일이 완성돼요."
<br> "소매 볼륨감이 팔 라인을 자연스럽게 커버해
<br> 여성스러운 실루엣이 돋보입니다."'''
    return f"""<div style="text-align:center;">
	<h3 style=" margin-bottom:0;">
		✓ 미리 입어 본 착용후기 (모델/스텝/MD리뷰)</h3>
	<br>
	<p>
		<span style="font-size:14px; line-height:1.8;">
{body}
</span>
		<br>
		<br>
		<br>
	</p>
</div>"""


def build_faq_block() -> str:
    body = """Q. FREE 사이즈, 77까지 정말 맞나요?
<br> A. 네, 77까지 여유 있게 착용 가능해요.
<br>
<br> Q. 스카프 스트랩은 탈부착이 되나요?
<br> A. 네, 분리 가능해 타이 없는 스타일링도 가능합니다.
<br>
<br> Q. 비침이 심한가요?
<br> A. 아이보리는 약간의 비침이 있지만, 과하지 않으며,
<br>스킨톤 이너와 함께 착용을 권장합니다.
<br>
<br> Q. 구김이 많이 가나요?
<br> A. 자체 미세한 링클 원단이며,구김이 적은 혼용소재로
<br>오랜 시간 깔끔하게 유지됩니다."""
    return f"""<div style="text-align:center;">

	<h3 style="margin-bottom:0;">
		✓ (FAQ) 이 상품, 이게 궁금해요!</h3>
	<br>
	<p><span style="font-size:14px; line-height:1.4;">
{body}
</span>
		<br>
		<br>
		<br>
	</p>
</div>"""


def build_shopping_block() -> str:
    body = """ ▪ FREE 사이즈로 77까지 추천드려요.
<br>▪아이보리는 밝은 컬러 특성상 스킨톤 이너와 함께 착용하시면
<br>더욱 안정감 있게 입으실 수 있습니다.
<br>▪스카프 스트랩은 탈부착이 가능해
<br> 취향에 따라 자유롭게 연출하세요."""
    return f"""<div style="text-align:center;">

	<h3 style="margin-bottom:0;">
		✓쇼핑에 꼭 참고하세요</h3>
	<br>
	<p><span style="font-size:14px; line-height:1.8;">
{body}
</span>
		<br>
		<br>
		<br>
	</p>
</div>"""


def extract_size_tips(raw_result: str) -> Dict[str, str]:
    defaults = {
        "ㅇ55 (90) 160cm 48kg": "어깨와 소매가 여유 있게 떨어지며, 전체적으로 여리여리한 핏이 연출되어 단독 착용만으로도 세련된 분위기가 완성됩니다.",
        "ㅇ66 (95) 165cm 54kg": "상체 군살 커버에 효과적이고, 힙을 자연스럽게 덮는 기장감으로 슬랙스나 스커트 모두 잘 어울립니다.",
        "ㅇ66반 (95) 164cm 58kg": "어깨와 가슴 부분이 답답하지 않으면서도, 소매 볼륨 덕분에 팔 라인이 슬림해 보여 부담 없이 입기 좋습니다.",
        "ㅇ77 (100) 163cm 61kg": "FREE 사이즈 기준으로 상체가 넉넉하게 감싸져 편안하며, 브이넥과 타이 디테일이 얼굴선을 더욱 갸름하게 연출해줍니다.",
    }
    out = {}
    for title, default in defaults.items():
        m = re.search(re.escape(title) + r"\s*(.+?)(?=\nㅇ|$)", raw_result, flags=re.S)
        if m:
            out[title] = re.sub(r"\s+", " ", m.group(1).replace("<br>", " ")).strip() or default
        else:
            out[title] = default
    return out


def assemble_final_output(raw_result: str, source_block: str, data: Dict[str, str]):
    lines = [
        f"상품명 : {data['display_name']}",
        "",
        f"컬러 : {data['color']}",
        f"사이즈 : {data['size']}",
        f"소재 : {(data['material'] or '').strip()}" + ("" if "(건조기사용금지)" in (data['material'] or '') else " (건조기사용금지)"),
        "소재설명 :",
    ]
    material_lines = format_material_desc_for_top(data.get("material_desc") or "")
    if material_lines:
        lines.extend([f"- {x}" for x in material_lines])
    else:
        lines.append("-")
    lines += [f"제조국 : {data['country']}", "", "", "○ 포인트 코멘트 ", "-"]
    lines += [""] * 8
    lines += [
        "---------------------------------",
        "텍스트 소스",
        "---------------------------------",
        "",
        build_recommend_block(),
        "",
        build_review_block(),
        "",
        build_faq_block(),
        "",
        build_shopping_block(),
        "",
        "----------------------------------",
        "MD원고(상품 설명 소스)",
        "----------------------------------",
        source_block,
        "",
        "-----------------",
        "사이즈 팁",
        "-----------------",
        "",
    ]
    size_tips = extract_size_tips(raw_result)
    for title, body in size_tips.items():
        lines += [title, body, ""]
    return "\n".join(lines).strip()


def result_to_docx_bytes(result_text: str):
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
    st.session_state.naming_result = ""
    st.session_state.naming_input_value = ""
    st.session_state.generated_result = ""
    st.session_state.generated_docx = b""
    st.session_state.generated_file_stem = "page_builder"


st.markdown("---")
st.subheader("상품 네이밍")
ncol1, ncol2 = st.columns([5, 1], vertical_alignment="bottom")
with ncol1:
    naming_input = st.text_area("상품 주요특징 입력", height=120, key="naming_input_value")
with ncol2:
    if st.button("네이밍 생성", use_container_width=True):
        if naming_input.strip() and client is not None:
            with st.spinner("상품명을 생성 중입니다..."):
                try:
                    response = chat_with_retry(model="gpt-4.1", messages=[{"role": "system", "content": NAME_PROMPT}, {"role": "user", "content": naming_input}], temperature=0.5, max_retries=2)
                    st.session_state.naming_result = response.choices[0].message.content.strip()
                    st.rerun()
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
    color = st.text_input("컬러", key=f"color_{nonce}")
    size = st.text_area("사이즈", height=90, value="FREE 사이즈로 77까지 추천드립니다.", key=f"size_{nonce}")
    material = st.text_input("소재", key=f"material_{nonce}")
    material_desc = st.text_area("소재설명", height=110, key=f"material_desc_{nonce}")
    country = st.text_input("제조국", key=f"country_{nonce}")
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
    measurement_lines = combine_measurements(top_measure, bottom_measure, dress_measure)
    data = {
        "product_name": product_name,
        "display_name": display_name,
        "color": color,
        "size": size,
        "material": material,
        "material_desc": material_desc,
        "country": country,
        "measurement_lines": measurement_lines,
        "detail_tip": detail_tip,
        "fit": fit,
        "appeal_points": appeal_points,
        "etc": etc,
        "target": target,
        "washing": washing,
    }
    data["material_desc"] = rewrite_material_desc(data)
    raw_result = ""
    if client is not None:
        user_content: List[Dict[str, Any]] = [{"type": "text", "text": (additional_request or "") + "\n상품 출력에 참고하세요."}]
        for img in uploaded_images[:5] if uploaded_images else []:
            user_content.append(file_to_content_item(img))
        try:
            response = chat_with_retry(model="gpt-4.1", messages=[{"role": "user", "content": user_content}], temperature=0.2, max_retries=1)
            raw_result = response.choices[0].message.content
        except Exception:
            raw_result = ""
    source_block = FIXED_HTML_HEAD + "\n\n" + build_md_subsc_stable(data) + "\n\n" + build_subtap_html(data)
    result = assemble_final_output(raw_result, source_block, data)
    st.session_state.generated_result = result
    st.session_state.generated_docx = result_to_docx_bytes(result)
    st.session_state.generated_file_stem = (display_name or "page_builder").replace(" ", "_")

if st.session_state.generated_result:
    st.text_area("결과", st.session_state.generated_result, height=1200)
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("TXT 다운로드", data=st.session_state.generated_result, file_name=f"{st.session_state.generated_file_stem}_output.txt", mime="text/plain", use_container_width=True)
    with c2:
        st.download_button("HWP 다운로드", data=st.session_state.generated_docx, file_name=f"{st.session_state.generated_file_stem}_output.hwp", mime="application/x-hwp", use_container_width=True)

st.markdown("---")
st.markdown("© made by MISHARP, MIYAWA. All rights reserved.")
