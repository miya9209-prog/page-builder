import base64
import io
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
for k, v in {
    "reset_nonce": 0,
    "naming_result": "",
    "naming_input_value": "",
    "generated_result": "",
    "generated_docx": b"",
    "generated_filename_base": "page_builder",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v


# -----------------------
# helpers
# -----------------------
def chat_with_retry(client: OpenAI, *, model: str, messages, temperature: float = 0.2, max_retries: int = 2):
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
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
            time.sleep(attempt + 1)
    raise last_exc


def normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def split_items(text: str) -> List[str]:
    raw = re.split(r"\n|/|,|·|•|⦁", text or "")
    items = []
    for x in raw:
        s = normalize_space(x).strip("-▪")
        if s and s not in items:
            items.append(s)
    return items


def ensure_sentence(s: str, end: str = "습니다.") -> str:
    s = normalize_space(s)
    if not s:
        return ""
    if re.search(r"[.!?]$|니다$|요$|됩니다$|좋습니다$|어울립니다$|가능합니다$", s):
        return s
    return s + end


def apply_color_count_to_name(product_name: str, color_text: str) -> str:
    colors = [re.sub(r"^\d+\s*", "", normalize_space(x)) for x in re.split(r"\n|/|,", color_text or "")]
    colors = [c for c in colors if c]
    count = len(colors)
    name = normalize_space(product_name)
    suffix = f"({count} color)" if count else "(color)"
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
    return "<br>".join([normalize_space(x).replace(" 단위:cm", "").replace("단위:cm", "") for x in lines]) + " (단위: cm)"


def material_desc_lines(material_desc: str) -> List[str]:
    return [normalize_space(x) for x in (material_desc or "").splitlines() if normalize_space(x)]


def rewrite_material_desc(client: OpenAI, data: Dict[str, str]) -> str:
    memo = normalize_space(data.get("material_desc") or "")
    if not memo:
        return ""
    prompt = f"""
너는 여성의류 쇼핑몰 상세페이지의 소재설명 전문 에디터다.

입력 정보
- 소재: {data.get('material','')}
- 참고메모: {memo}

규칙
- 참고메모를 그대로 복붙하지 말고 자연스럽고 전문적인 설명으로 다시 쓴다.
- 3~4개의 짧은 리스팅 문장으로 작성한다.
- 문장 끝 표현 반복을 줄인다.
- 결과는 문장만 줄바꿈으로 출력한다.
"""
    try:
        r = chat_with_retry(
            client,
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": "너는 여성의류 소재 설명을 자연스럽게 정리하는 전문가다."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_retries=1,
        )
        return r.choices[0].message.content.strip()
    except Exception:
        return memo


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
    material_html = "<br>\n".join(material_desc_lines(data.get("material_desc") or "")) or "상품 정보를 기준으로 소재 특성을 확인해 주세요.<br>"
    return f'''<div id="Subtap">\n\t<div id="header2" role="banner">\n\t\t<nav class="nav" role="navigation">\n\t\t\t<ul class="nav__list">\n\t\t\t\t<li>\n\t\t\t\t\t<input id="group-1" type="checkbox" hidden="">\n\t\t\t\t\t<label for="group-1" style="border-top-color: rgb(204, 204, 204); border-top-width: 1px; border-top-style: solid;">\n\t\t\t\t\t\t<p class="fa fa-angle-right"></p>소재 정보</label>\n\t\t\t\t\t<ul class="group-list">\n\t\t\t\t\t\t<li>\n\t\t\t\t\t\t\t<a href="#">\n\t\t\t\t\t\t\t\t<h3>소재 : {material_line}</h3>\n\t\t\t\t\t\t\t\t<p>{material_html}<br></p>\n\t\t\t\t\t\t\t\t<h3>세탁방법</h3>\n\t\t\t\t\t\t\t\t<p>{normalize_space(data.get('washing') or '드라이클리닝, 단독 울세탁, 손세탁 권장. 건조기 사용 금지')}</p>\n\t\t\t\t\t\t\t</a>\n\t\t\t\t\t\t</li>\n\t\t\t\t\t</ul>\n\t\t\t\t</li>\n\t\t\t\t<li>\n\t\t\t\t\t<input id="group-2" type="checkbox" hidden="">\n\t\t\t\t\t<label for="group-2"><p class="fa fa-angle-right"></p>사이즈 정보</label>\n\t\t\t\t\t<ul class="group-list gray">\n\t\t\t\t\t\t<li><a href="#">\n\t\t\t\t\t\t\t<h3>사이즈 TIP</h3>\n\t\t\t\t\t\t\t<p>{normalize_space(data.get('size') or 'FREE 사이즈로 77까지 추천드립니다.')}</p>\n\t\t\t\t\t\t\t<h3>길이 TIP</h3>\n\t\t\t\t\t\t\t<p>162-167cm에서는 모델핏을 참고해 주시고,<br> 다리 길이나 체형에 따라 다르지만,<br> 160cm이하에서는 모델의 핏보다 조금 길게<br> 연출됩니다.</p>\n\t\t\t\t\t\t</a></li>\n\t\t\t\t\t</ul>\n\t\t\t\t</li>\n\t\t\t\t<li>\n\t\t\t\t\t<input id="group-3" type="checkbox" hidden="">\n\t\t\t\t\t<label for="group-3"><p class="fa fa-angle-right"></p>실측 사이즈</label>\n\t\t\t\t\t<ul class="group-list"><li><a href="#"><p>{format_measurement_lines(data.get('measurement_lines') or [])}</p></a></li></ul>\n\t\t\t\t</li>\n\t\t\t\t<li>\n\t\t\t\t\t<input id="group-5" type="checkbox" hidden="">\n\t\t\t\t\t<label for="group-5"><span class="fa fa-angle-right"></span><a href="#crema-product-fit-1" style="padding: 0px; box-shadow:none; background:#f7f7f7;">실측사이즈 재는방법</a></label>\n\t\t\t\t</li>\n\t\t\t</ul>\n\t\t</nav>\n\t</div>\n</div>'''


def build_md_subsc(data: Dict[str, str]) -> str:
    name = data.get("display_name") or "상품명"
    fit = normalize_space(data.get("fit") or "")
    detail_items = split_items(data.get("detail_tip") or "")
    appeal_items = split_items(data.get("appeal_points") or "")
    mat = material_desc_lines(data.get("material_desc") or "")

    reason_lines = []
    if detail_items:
        reason_lines.append(ensure_sentence(f"{detail_items[0]} 포인트가 세련된 분위기를 더해줍니다"))
    if fit:
        reason_lines.append(ensure_sentence(f"{fit}으로 체형 부담을 덜고 편안하게 입기 좋습니다"))
    reason_lines.append(ensure_sentence(f"{name}은 데일리부터 격식 있는 자리까지 폭넓게 활용하기 좋습니다"))

    fabric_lines = mat[:3] if mat else ["부드럽고 편안한 착용감을 느끼실 수 있습니다.", "부담 없는 두께감으로 데일리하게 활용하기 좋습니다."]

    fit_lines = [ensure_sentence((data.get("size") or "FREE 사이즈로 77까지 추천드립니다.").replace("추천드립니다.", "추천드리며 여유 있게 착용 가능합니다."))]
    if fit:
        fit_lines.append(ensure_sentence(f"{fit}으로 자연스럽게 떨어지는 실루엣이 돋보입니다"))
    if detail_items:
        fit_lines.append(ensure_sentence(f"{detail_items[0]} 디테일이 전체 라인을 더욱 정돈돼 보이게 합니다"))

    wear_lines = ["오피스룩, 모임룩, 데일리룩까지 자연스럽게 이어집니다."]
    if appeal_items:
        wear_lines.append(ensure_sentence(f"{appeal_items[0]}이 필요한 날 손이 자주 가는 아이템입니다"))
    wear_lines.append("다양한 하의와 무리 없이 매치되어 활용도가 높습니다.")

    def br_lines(lines: List[str]) -> str:
        return "\n".join([f"\t\t<br> {x}" for x in lines if normalize_space(x)])

    return f'''<div id="subsc">\n<h3>{name}</h3>\n\n\t<p>\n\t\t<strong style="font-weight:700 !important;">[이 상품을 초이스한 이유입니다.]</strong>\n{br_lines(reason_lines)}\n\t\t<br>\n\t\t<br>\n\t\t<strong style="font-weight:700 !important;">[원단과 두께 체감에 대하여]</strong>\n{br_lines(fabric_lines)}\n\t\t<br>\n\t\t<br>\n\t\t<strong style="font-weight:700 !important;">[체형과 핏, 사이즈 선택 가이드]</strong>\n{br_lines(fit_lines)}\n\t\t<br>\n\t\t<br>\n\t\t<strong style="font-weight:700 !important;">[이렇게 입는 날이 많아집니다]</strong>\n{br_lines(wear_lines)}\n\t\t<br>\n\t\t<br>\n\t</p>\n\n</div>'''


def build_text_source_blocks(data: Dict[str, str]) -> List[str]:
    name = data.get("display_name") or "상품"
    fit = normalize_space(data.get("fit") or "")
    detail = normalize_space(data.get("detail_tip") or "")
    appeal = split_items(data.get("appeal_points") or "")
    mat = material_desc_lines(data.get("material_desc") or "")

    bullets = []
    if fit:
        bullets.append(f"▪ {fit}을 선호하시는 분")
    if detail:
        bullets.append(f"▪ {detail} 포인트를 좋아하시는 분")
    if appeal:
        bullets.append(f"▪ {appeal[0]}이 필요한 분")
    bullets += [
        f"▪ {name}처럼 데일리와 모임룩 모두 활용할 아이템을 찾는 분",
        "▪ 구김 부담이 적고 관리가 편한 옷을 찾는 분",
        "▪ 다양한 하의와 자연스럽게 매치되는 상의를 원하시는 분",
    ]
    rec_lines = []
    for b in bullets:
        if b not in rec_lines:
            rec_lines.append(b)
        if len(rec_lines) >= 4:
            break

    reviews = []
    if mat:
        reviews.append(f'"{mat[0].rstrip(".")} 정말 만족스러웠어요."')
    if fit:
        reviews.append(f'"{fit} 느낌이 과하지 않아 편하게 입기 좋았어요."')
    if detail:
        reviews.append(f'"{detail} 포인트가 은은하게 살아 있어 단독으로도 충분히 멋스러워요."')
    reviews.append('"하루 종일 입어도 비교적 깔끔한 인상이 유지돼 만족도가 높았어요."')
    reviews = reviews[:4]

    bright = '아이보리' in (data.get('color') or '') or '화이트' in (data.get('color') or '')
    has_tie = '타이' in detail or '스트랩' in detail
    faq = [
        ("Q. FREE 사이즈, 77까지 정말 맞나요?", f"A. {normalize_space(data.get('size') or 'FREE 사이즈로 77까지 추천드립니다.')}"),
        ("Q. 스카프 스트랩은 탈부착이 되나요?" if has_tie else "Q. 디테일 포인트가 과하지 않나요?", "A. 네, 탈부착이 가능해 취향에 따라 다양하게 연출하실 수 있습니다." if has_tie else "A. 은은하게 포인트가 살아 있어 부담 없이 다양한 자리에 활용하기 좋습니다."),
        ("Q. 비침이 심한가요?", "A. 밝은 컬러는 약간의 비침이 있을 수 있어 스킨톤 이너와 함께 착용하시면 더욱 안정감 있게 입으실 수 있습니다." if bright else "A. 비침 부담이 크지 않아 데일리하게 활용하기 좋습니다."),
        ("Q. 구김이 많이 가나요?", "A. 구김이 적은 소재 특성상 오랜 시간 비교적 깔끔하게 유지됩니다."),
    ]
    shopping = [f"▪ {normalize_space(data.get('size') or 'FREE 사이즈로 77까지 추천드립니다.')}" ]
    if bright:
        shopping.append("▪ 아이보리는 밝은 컬러 특성상 스킨톤 이너와 함께 착용하시면 더욱 안정감 있게 입으실 수 있습니다.")
    if has_tie:
        shopping.append("▪ 스카프 스트랩은 탈부착이 가능해 취향에 따라 자유롭게 연출하세요.")
    else:
        shopping.append("▪ 실측사이즈를 함께 확인하시면 더욱 만족스러운 선택에 도움이 됩니다.")

    blocks = []
    blocks.append('<div style="text-align:center;">\n\t<h3 style="margin-bottom:0;">\n\t\t✓ 이런 분께 추천해요!</h3>\n\t<br>\n\t<p>\n\t\t<span style="font-size:14px; line-height:1.8;">\n' + "<br>\n".join(rec_lines) + '\n</span>\n\t\t<br>\n\t\t<br>\n\t\t<br>\n\t</p>\n</div>')
    blocks.append('<div style="text-align:center;">\n\t<h3 style="margin-bottom:0;">\n\t\t✓ 미리 입어 본 착용후기 (모델/스텝/MD리뷰)</h3>\n\t<br>\n\t<p>\n\t\t<span style="font-size:14px; line-height:1.8;">\n' + "<br>\n".join(reviews) + '\n</span>\n\t\t<br>\n\t\t<br>\n\t\t<br>\n\t</p>\n</div>')
    faq_body = []
    for q, a in faq:
        faq_body.extend([q, a, '<br>'])
    blocks.append('<div style="text-align:center;">\n\t<h3 style="margin-bottom:0;">\n\t\t✓ (FAQ) 이 상품, 이게 궁금해요!</h3>\n\t<br>\n\t<p><span style="font-size:14px; line-height:1.4;">\n' + "<br>\n".join(faq_body) + '\n</span>\n\t\t<br>\n\t\t<br>\n\t\t<br>\n\t</p>\n</div>')
    blocks.append('<div style="text-align:center;">\n\t<h3 style="margin-bottom:0;">\n\t\t✓ 쇼핑에 꼭 참고하세요</h3>\n\t<br>\n\t<p>\n\t\t<span style="font-size:14px; line-height:1.8;">\n' + "<br>\n".join(shopping) + '\n</span>\n\t\t<br>\n\t\t<br>\n\t\t<br>\n\t</p>\n</div>')
    return blocks


def build_size_tips(data: Dict[str, str]) -> List[str]:
    fit = normalize_space(data.get("fit") or "여유 있는 핏")
    tips = {
        "ㅇ55 (90) 160cm 48kg": f"{fit}으로 전체적으로 부담 없이 떨어져 단독으로도 편하게 입기 좋습니다.",
        "ㅇ66 (95) 165cm 54kg": "어깨와 가슴 라인이 답답하지 않고 자연스럽게 정리되어 데일리하게 활용하기 좋습니다.",
        "ㅇ66반 (95) 164cm 58kg": "군살 커버가 자연스럽고 전체 실루엣이 깔끔하게 정리되는 편입니다.",
        "ㅇ77 (100) 163cm 61kg": "여유 있는 품으로 체형 구애 없이 편안하게 착용 가능합니다.",
    }
    lines = []
    for title, body in tips.items():
        lines.append(title)
        lines.append(body)
        lines.append("")
    return lines


def assemble_output(data: Dict[str, str]) -> str:
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
        if m == "-":
            lines.append(m)
        else:
            lines.append(f"- {m}")
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
    lines.extend(build_text_source_blocks(data))
    lines.append("")
    lines.append("----------------------------------")
    lines.append("MD원고(상품 설명 소스)")
    lines.append("----------------------------------")
    lines.append(FIXED_HTML_HEAD)
    lines.append("")
    lines.append(build_md_subsc(data))
    lines.append("")
    lines.append(build_subtap_html(data))
    lines.append("")
    lines.append("-----------------")
    lines.append("사이즈 팁")
    lines.append("-----------------")
    lines.append("")
    lines.extend(build_size_tips(data))
    return "\n".join(lines).strip()


# -----------------------
# UI
# -----------------------
st.markdown("<style>div[data-testid='stButton'] > button { min-height: 42px; }</style>", unsafe_allow_html=True)
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
    }
    if client:
        data["material_desc"] = rewrite_material_desc(client, data)
    else:
        data["material_desc"] = material_desc
    if additional_request.strip():
        # reflect explicit request minimally in text source / md via concatenation to detail/appeal
        data["appeal_points"] = (data["appeal_points"] + "\n" + additional_request).strip()
    result = assemble_output(data).replace("&nbsp;", "")
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
