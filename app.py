import base64
import time
from openai import RateLimitError
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


def chat_with_retry(*, model: str, messages, temperature: float = 0.2, max_retries: int = 2):
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
            time.sleep(1 * (attempt + 1))
    raise last_exc

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
1. 상품명 바로 아래 소개 문장은 작성하지 않습니다.
2. [이 상품을 초이스한 이유입니다.]
3. [원단과 두께 체감에 대하여]
4. [체형과 핏, 사이즈 선택 가이드]
5. [이렇게 입는 날이 많아집니다]
6. [구매 전 꼭 확인해 주세요]
7. 감성 마무리 문장

중요 규칙
- 각 문장은 한 줄이 너무 길지 않게 20~28자 안팎에서 자연스럽게 <br> 처리합니다.
- 오늘 테스트 출력물처럼 긴 문장을 한 줄에 길게 쓰지 않습니다.
- 기존 스타일처럼 각 소제목을 대괄호 포함 구조화합니다.
- MD원고 안에는 [쇼핑에 꼭 참고하세요] 섹션을 넣지 않습니다.
- [상품 포인트]로 바꾸지 않습니다.
- 소제목은 반드시 <strong style="font-weight:700 !important;">[제목]</strong> 형태만 사용합니다.
- 상품명은 <strong>가 아니라 반드시 <h3> 태그로만 작성합니다.

텍스트 소스 규칙
- 순서는 반드시 "✓ 이런 분께 추천해요!" → "✓ 미리 입어 본 착용후기 (모델/스텝/MD리뷰)" → "✓ (FAQ) 이 상품, 이게 궁금해요!" → "✓쇼핑에 꼭 참고하세요" 순서로 작성합니다.
- 각 블록은 중복 제목 없이 <div style="text-align:center;"> 안에 <h3 style="margin-bottom:0;"> 제목 한 번만 사용합니다.
- 추천/후기/쇼핑에 꼭 참고하세요 블록의 본문은 <p><span style="font-size:14px; line-height:1.8;"> ... </span></p> 구조를 사용합니다.
- FAQ 블록의 본문은 <p><span style="font-size:14px; line-height:1.4;"> ... </span></p> 구조를 사용합니다.
- 추천 블록은 각 줄 앞에 ▪ 또는 ⦁를 붙인 실무용 문장으로 작성합니다.
- 착용후기 블록은 각 문장을 따옴표로 감싸고, 문장이 두 줄이 되면 둘째 줄은  또는  로 들여맞춤합니다.
- FAQ는 반드시 4개를 작성하되, 상품 정보와 직접 관련된 질문만 작성합니다. 상품과 무관한 질문은 금지합니다.
- A 문장이 줄바꿈될 때는  또는  로 들여맞춤합니다.

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

이런 분께 추천해요!
(h3 제목 + ⦁ 리스트)

미리 입어 본 착용후기 (모델/스텝/MD리뷰)
(h3 제목 + 따옴표 후기)

(FAQ) 이 상품, 이게 궁금해요!
(h3 제목 + Q/A 4개)

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
- 소재설명 참고메모: {data['material_desc']}
- 디테일특징: {data['detail_tip']}
- 핏/실루엣: {data['fit']}
- 주요 어필 포인트: {data['appeal_points']}
- 타겟: {data['target']}
- 세탁방법: {data['washing']}
- 기타: {data['etc']}

중요 추가 지시
- 상단의 "소재설명 :" 항목은 입력자가 적은 문구를 그대로 복붙하지 않습니다.
- 입력된 소재설명 참고메모를 바탕으로, AI가 자연스럽고 전문적인 문장으로 다시 정리해 2~4개의 리스팅 문장으로 작성합니다.
- 3. (원단컷), 4. (디테일컷), 5. (핵심어필 포인트)는 모두 한 줄씩 끊어지는 리스팅형으로 작성합니다.
- 포인트 원고 문장은 설명형 종결문보다 명사형에 가까운 짧고 구체적인 실무용 카피를 우선합니다.
- 예: "고밀도 면 100%로 탄탄하게 제작되었습니다." 보다 "고밀도 면 100%의 탄탄한 조직감." 같은 형식을 우선합니다.
- 예: "다잉 염색과 워싱 가공으로 색감이 깊고 고급스럽습니다." 보다 "다잉 염색과 워싱 가공으로 깊고 부드러운 색감." 같은 형식을 우선합니다.
- 최하단 사이즈 팁은 한 체형당 한 문장을 엔터로 쪼개지 말고, 문장 흐름이 이어지도록 작성합니다.
- 문장 끝 표현이 반복되지 않게 하고, 쇼핑몰 실무자가 바로 쓸 수 있는 설명문으로 다듬습니다.
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



def strip_leading_intro_from_subsc(subsc: str) -> str:
    pattern = r'(<h3>.*?</h3>)\s*<p>\s*.*?(?=<strong style="font-weight:700 !important;">\[이 상품을 초이스한 이유입니다\.\]</strong>)'
    return re.sub(pattern, r'\1\n\t<p>\n\t\t', subsc, flags=re.S)


def remove_shopping_block_from_subsc(subsc: str):
    pattern = r'<strong style="font-weight:700 !important;">\[쇼핑에 꼭 참고하세요\]</strong>\s*(.*?)\s*(?=<strong style="font-weight:700 !important;">\[이 상품을 초이스한 이유입니다\.\]</strong>)'
    m = re.search(pattern, subsc, flags=re.S)
    shopping_lines = []
    if m:
        block = m.group(1)
        shopping_lines = [x.strip() for x in re.split(r'<br\s*/?>', block) if x.strip()]
        subsc = subsc[:m.start()] + subsc[m.end():]
    return subsc, shopping_lines


def ensure_subsc_paragraph_wrapper(subsc: str) -> str:
    if '<p>' not in subsc:
        subsc = subsc.replace('</h3>', '</h3>\n\t<p>', 1)
        subsc = subsc.replace('</div>', '\n\t</p>\n</div>')
    return subsc


def normalize_md_subsc_html(subsc: str):
    subsc = ensure_subsc_paragraph_wrapper(subsc)
    subsc = strip_leading_intro_from_subsc(subsc)
    subsc, shopping_lines = remove_shopping_block_from_subsc(subsc)
    return subsc, shopping_lines


def _dedupe_keep_order(lines: list[str]) -> list[str]:
    seen = set()
    out = []
    for line in lines:
        norm = normalize_phrase(line)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _point_quality_upgrade(line: str) -> str:
    s = normalize_phrase(line)
    if not s:
        return ''
    s = re.sub(r'<br\s*/?>', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip(' .')
    s = s.replace('타이이', '타이').replace('소매이', '소매').replace('오피스이', '오피스').replace('하객이', '하객')
    s = s.replace('전체적인 완성도를 높여줍니다', '').replace('돋보여', '')
    s = re.sub(r'\s+', ' ', s).strip(' .')
    if not s:
        return ''
    rules = [
        (r'울|텐셀|레이온|나일론|혼방|텍스처|촉감|소재', '울·텐셀·레이온·나일론 혼방의 부드럽고 고급스러운 텍스처.'),
        (r'광택|표면', '은은한 광택감과 고급스러운 표면 질감.'),
        (r'구김|관리', '구김이 적어 관리가 편한 실용적 소재.'),
        (r'두께|여리|실루엣', '가볍고 부담 없는 두께감으로 자연스럽게 흐르는 여리한 실루엣.'),
        (r'타이', '탈부착 가능한 타이 디테일로 다양한 스타일 연출.'),
        (r'브이넥', '브이넥 디자인으로 목선이 길어 보이는 효과.'),
        (r'소매', '볼륨감 있는 소매로 팔 라인을 자연스럽게 커버.'),
        (r'절개', '앞 절개 라인으로 슬림해 보이는 시각적 효과.'),
        (r'군살|커버|핏', '군살을 자연스럽게 커버하는 세련된 실루엣 핏.'),
        (r'오피스|하객|데일리|활용', '오피스·하객·데일리까지 확장 가능한 스타일링 활용도.'),
    ]
    for patt, repl in rules:
        if re.search(patt, s):
            return repl
    return s + '.' if not s.endswith('.') else s


def sentence_to_point_phrase(text: str) -> str:
    return _point_quality_upgrade(text)


def build_relevant_faqs(data: Dict[str, str]) -> list[tuple[str, str]]:
    faqs = []
    size = normalize_phrase(data.get('size') or 'FREE 사이즈로 77까지 여유 있게 착용 가능합니다.')
    if size:
        faqs.append(('사이즈는 어떻게 보면 될까요?', size if re.search(r'[.!?]$', size) else size + '.'))
    detail = normalize_phrase(data.get('detail_tip') or '')
    material_lines = format_material_desc_for_top(data.get('material_desc') or '')
    color = normalize_phrase(data.get('color') or '')
    washing = normalize_phrase((data.get('washing') or '드라이클리닝, 단독 울세탁, 손세탁을 권장합니다. 건조기 사용은 피해주세요.').replace(' 권장. ', '을 권장합니다. '))

    if '타이' in detail or '스트랩' in detail or '탈부착' in detail:
        faqs.append(('스카프 스트랩은 탈부착이 가능한가요?', '네, 탈부착이 가능해 타이 없이도 깔끔하게 연출하실 수 있습니다.'))
    if any(x in color for x in ['아이보리', '크림', '화이트', '베이지']):
        faqs.append(('밝은 컬러는 비침이 심한 편인가요?', '밝은 컬러는 약간의 비침이 있을 수 있어 스킨톤 이너와 함께 착용하시면 더욱 안정감 있게 입으실 수 있습니다.'))
    elif material_lines:
        ans = material_lines[0]
        faqs.append(('원단 느낌은 어떤 편인가요?', ans if re.search(r'[.!?]$', ans) else ans + '.'))
    if material_lines and any(x in ' '.join(material_lines) for x in ['구김', '링클']):
        faqs.append(('구김이 많이 가는 편인가요?', '구김이 적은 혼용 소재라 오랜 시간 비교적 깔끔한 상태로 입기 좋습니다.'))
    else:
        faqs.append(('세탁과 관리가 까다롭지 않나요?', washing if re.search(r'[.!?]$', washing) else washing + '.'))
    if len(faqs) < 4:
        fit = normalize_phrase(data.get('fit') or '')
        if fit:
            faqs.append(('핏감은 어떤 편인가요?', f'{fit}으로 체형을 자연스럽게 커버하며 부담 없이 입기 좋습니다.'))
        elif any(x in detail for x in ['버튼', '롤업', '파이핑']):
            faqs.append(('디테일 포인트는 어떤 점이 매력적인가요?', '소매 버튼과 파이핑 같은 디테일이 더해져 심플한 룩도 한층 더 정돈되고 세련돼 보입니다.'))
    out = []
    seen = set()
    for q, a in faqs:
        if q and a and (q, a) not in seen:
            seen.add((q, a))
            out.append((q, a))
    return out[:4]


def build_shopping_block(lines_in: list[str], data: Dict[str, str]) -> str:
    lines = []
    src = [normalize_phrase(x) for x in lines_in if normalize_phrase(x)]
    if not src:
        size = normalize_phrase(data.get('size') or '')
        if size:
            lines.append(f'▪ {size}')
        color = normalize_phrase(data.get('color') or '')
        if any(x in color for x in ['아이보리', '크림', '화이트']):
            lines.append('▪ 아이보리는 밝은 컬러 특성상 스킨톤 이너와 함께 착용하시면 더욱 안정감 있게 입으실 수 있습니다.')
        detail = normalize_phrase(data.get('detail_tip') or '')
        if '타이' in detail or '스트랩' in detail or '탈부착' in detail:
            lines.append('▪ 스카프 스트랩은 탈부착이 가능해 취향에 따라 자유롭게 연출하실 수 있습니다.')
    else:
        for idx, s in enumerate(src):
            if idx == 0 and not s.startswith(('▪', '⦁')):
                s = '▪ ' + s
            lines.append(s)
    body = '<br>\n'.join(lines)
    return '<div style="text-align:center;">\n\t<h3 style="margin-bottom:0;">\n\t\t✓쇼핑에 꼭 참고하세요</h3>\n\t<br>\n\t<p><span style="font-size:14px; line-height:1.8;">\n' + body + '\n</span>\n\t\t<br>\n\t\t<br>\n\t\t<br>\n\t</p>\n</div>'

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
    block = (block or '').strip()
    if not block:
        return f'<h3 style="margin-bottom:0;">\n{title}</h3>\n'
    block = re.sub(r'^.*?<h3[^>]*>', '<h3 style="margin-bottom:0;">\n', block, count=1, flags=re.S)
    if '<h3' not in block:
        block = f'<h3 style="margin-bottom:0;">\n{title}</h3>\n' + block
    block = re.sub(r'</h3>\s*<div[^>]*>', '</h3>\n', block, flags=re.S)
    block = block.replace('</div>', '').strip()
    return block

def extract_block(raw: str, start_title: str, next_titles: list):
    pattern = rf'{re.escape(start_title)}[\s\S]*?(?=' + '|'.join(re.escape(t) for t in next_titles) + r'|$)'
    m = re.search(pattern, raw)
    return m.group(0).strip() if m else start_title

def fallback_size_tips():
    return {
        "ㅇ55 (90) 160cm 48kg": "전체적으로 여유가 느껴지며 부담 없이 편안하게 입기 좋은 핏입니다. 실루엣이 자연스럽게 정리됩니다.",
        "ㅇ66 (95) 165cm 54kg": "가장 안정감 있게 떨어지는 핏으로 데일리부터 모임룩까지 활용이 좋습니다. 라인이 단정하게 정리됩니다.",
        "ㅇ66반 (95) 164cm 58kg": "군살이 신경 쓰이는 부분을 편안하게 감싸주며 답답함 없이 입기 좋은 편입니다. 전체 핏이 자연스럽습니다.",
        "ㅇ77 (100) 163cm 61kg": "체형을 편안하게 커버해 주는 실루엣으로 부담 없이 착용하기 좋습니다. 안정감 있는 핏이 돋보입니다.",
    }

def extract_size_tip_block(raw_result: str, title: str, fallback_map: dict):
    block = extract_block(raw_result, title, ["ㅇ55 (90) 160cm 48kg", "ㅇ66 (95) 165cm 54kg", "ㅇ66반 (95) 164cm 58kg", "ㅇ77 (100) 163cm 61kg"])
    rest = block.replace(title, '').replace('<br>', ' ').strip()
    rest = re.sub(r'\s+', ' ', rest)
    if block.strip() == title.strip() or not rest:
        rest = fallback_map[title]
    return title + "\n" + rest

def format_material_desc_for_top(material_desc: str):
    lines = [x.strip() for x in (material_desc or '').splitlines() if x.strip()]
    cleaned = []
    for line in lines:
        line = re.sub(r'(소재)(\s*소재)+', r'\1', line)
        line = re.sub(r'\s+', ' ', line).strip()
        cleaned.append(line)
    return cleaned


def normalize_phrase(phrase: str) -> str:
    p = re.sub(r'^[\-•⦁\s]+', '', (phrase or '').strip())
    p = p.strip(' ,/;')
    if not p:
        return ''
    p = re.sub(r'\s+', ' ', p)
    return p


def split_phrases(text: str):
    if not text:
        return []
    temp = text.replace(' / ', '\n').replace('/', '\n').replace('·', '\n').replace('•', '\n').replace('⦁', '\n')
    temp = temp.replace(', ', '\n').replace(',', '\n')
    parts = [normalize_phrase(x) for x in temp.splitlines()]
    return [x for x in parts if x]


def phrase_to_sentence(phrase: str) -> str:
    p = normalize_phrase(phrase)
    if not p:
        return ''
    if re.search(r'[.!?다요]$', p):
        return p
    rules = [
        (r'체형\s*커버', '체형을 자연스럽게 커버해 부담을 덜어줍니다.'),
        (r'심플한\s*라인', '심플한 라인이 전체 실루엣을 더 깔끔하게 정리해 줍니다.'),
        (r'유러?피안\s*무드', '유러피안 무드가 은은하게 살아 있어 세련된 분위기를 완성합니다.'),
        (r'황금\s*단추', '황금 단추 디테일이 밋밋함 없이 고급스러운 포인트가 됩니다.'),
        (r'카라\s*디테일', '카라 디테일이 얼굴선을 더 단정하고 정돈돼 보이게 해줍니다.'),
        (r'원단\s*구김\s*없', '구김이 적은 원단이라 하루 종일 깔끔한 인상을 유지하기 좋습니다.'),
        (r'탄력', '탄력이 좋아 움직임이 많은 날에도 편안하게 입기 좋습니다.'),
        (r'편안함', '편안한 착용감으로 데일리 아이템으로 손이 자주 갑니다.'),
        (r'탄탄한\s*면\s*소재', '탄탄한 면 소재가 핏을 안정감 있게 잡아줍니다.'),
        (r'내구성', '내구성이 좋아 오래 입어도 흐트러짐이 적습니다.'),
    ]
    for pattern, repl in rules:
        if re.search(pattern, p):
            return repl
    if p.endswith('핏'):
        return f'{p}으로 입었을 때 전체 라인이 더 깔끔하게 정리됩니다.'
    if p.endswith('디테일'):
        return f'{p}이 세련된 포인트가 되어 완성도를 높여줍니다.'
    if p.endswith('소재'):
        return f'{p}로 편안하면서도 안정감 있는 착용감을 느끼실 수 있습니다.'
    return f'{p}이 돋보여 전체적인 완성도를 높여줍니다.'


def format_point_block(title: str, content_lines: list[str]) -> str:
    lines = [title]
    for line in content_lines:
        line = normalize_phrase(line)
        if line:
            lines.append(line)
    return '\n'.join(lines)


def build_point_fallbacks(data: Dict[str, str]):
    material_lines = format_material_desc_for_top(data.get('material_desc') or '')
    detail_phrases = split_phrases(data.get('detail_tip') or '')
    appeal_phrases = split_phrases(data.get('appeal_points') or '')

    headline = '2. 헤드라인\n'

    fabric_src = material_lines[:4] if material_lines else ['혼방 소재', '은은한 광택', '가벼운 두께감']
    fabric_lines = _dedupe_keep_order([_point_quality_upgrade(x) for x in fabric_src])[:3]
    fabric = format_point_block('3. (원단컷)', fabric_lines)

    detail_seed = detail_phrases or ['브이넥', '타이 디테일', '소매']
    detail_lines = _dedupe_keep_order([_point_quality_upgrade(x) for x in detail_seed])[:3]
    detail_block = format_point_block('4. (디테일컷)', detail_lines)

    appeal_seed = appeal_phrases or [data.get('fit') or '군살 커버 핏', '오피스 하객 데일리 활용']
    appeal_lines = _dedupe_keep_order([_point_quality_upgrade(x) for x in appeal_seed])[:3]
    appeal_block = format_point_block('5. (핵심어필 포인트)', appeal_lines)
    return {
        '2. 헤드라인': headline,
        '3. (원단컷)': fabric,
        '4. (디테일컷)': detail_block,
        '5. (핵심어필 포인트)': appeal_block,
    }


def get_block_body(block: str, title: str) -> str:
    return re.sub(r'^' + re.escape(title) + r'\s*', '', (block or '').strip())


def normalize_fabric_lines(block_body: str, data: Dict[str, str]) -> list[str]:
    parts = [normalize_phrase(x) for x in re.split(r'<br\s*/?>|\n+', block_body) if normalize_phrase(x)]
    if len(parts) < 2:
        parts = format_material_desc_for_top(data.get('material_desc') or '')
    return _dedupe_keep_order([_point_quality_upgrade(p) for p in parts])[:3]


def normalize_detail_or_appeal_lines(block_body: str, input_text: str, fallback_lines: list[str]) -> list[str]:
    phrases = [normalize_phrase(x) for x in re.split(r'<br\s*/?>|\n+|/|,', block_body) if normalize_phrase(x)]
    if len(phrases) <= 1:
        phrases = split_phrases(input_text) or phrases
    if not phrases:
        phrases = fallback_lines
    lines = _dedupe_keep_order([_point_quality_upgrade(x) for x in phrases])
    if not lines:
        lines = _dedupe_keep_order([_point_quality_upgrade(x) for x in fallback_lines])
    return lines[:3]


def extract_text_source_section(raw_result: str) -> str:
    m = re.search(r'---------------------------------\s*텍스트 소스\s*---------------------------------([\s\S]*?)----------------------------------\s*MD원고', raw_result)
    return m.group(1).strip() if m else raw_result


def build_recommend_block(section: str, data: Dict[str, str]) -> str:
    fit = normalize_phrase(data.get('fit') or '')
    detail = normalize_phrase(data.get('detail_tip') or '')
    bullets = [
        '▪ 격식 있는 자리에도 여성스러운 무드를 원하시는 분',
        '▪ 브이넥으로 얼굴이 갸름해 보이는 느낌을 선호하시는 분' if ('브이넥' in detail or '브이' in detail) else (f'▪ 체형을 자연스럽게 커버하는 {fit}을 선호하시는 분' if fit else '▪ 체형을 자연스럽게 커버하는 핏을 선호하시는 분'),
        '▪ 데님, 스커트, 슬랙스 등 다양한 스타일링을 원하시는 분',
        '▪ 고급스럽고 부드러운 텍스처를 좋아하시는 분',
    ]
    body = '\n'.join([x + '<br>' for x in bullets[:4]])
    return '<div style="text-align:center;">\n\t<h3 style="margin-bottom:0;">\n\t\t✓ 이런 분께 추천해요!</h3>\n\t<br>\n\t<p>\n\t\t<span style="font-size:14px; line-height:1.8;">\n' + body + '\n</span>\n\t\t<br>\n\t\t<br>\n\t\t<br>\n\t</p>\n</div>'


def indent_multiline_quote(text: str) -> str:
    parts = [normalize_phrase(x) for x in re.split(r'(?<=[.!?])\s+|\n+', text) if normalize_phrase(x)]
    if not parts:
        return '"편안한 착용감으로 데일리하게 입기 좋았어요."<br>'
    if len(parts) == 1:
        return f'"{parts[0]}"<br>'
    first = parts[0]
    rest = ' '.join(parts[1:])
    return f'"{first}<br>\n{rest}"<br>'


def build_review_block(section: str, data: Dict[str, str]) -> str:
    title = '미리 입어본 착용 후기(피팅모델/스텝/MD의 리뷰)'
    body = extract_block(section, title, ['(FAQ) 이 상품, 이게 궁금해요!', '(FAQ) 이 상품, 이게 궁금해요'])
    body = body.replace(title, '').strip()
    quotes = re.findall(r'["“](.*?)["”]', body, flags=re.S)
    if not quotes:
        lines = [x for x in split_phrases(body) if not x.startswith('Q.') and not x.startswith('A.')]
        quotes = lines[:4]
    if len(quotes) < 3:
        quotes = [
            '피부에 닿는 촉감이 정말 부드러워요.',
            '여유로운 핏이라 체형에 큰 구애 없이 편하게 입었어요.',
            '디테일이 은은하게 포인트 되어 단독으로도 충분히 멋스럽습니다.',
            '구김이 적어 하루 종일 깔끔하게 입기 좋아 만족도가 높았어요.',
        ]
    rendered = [indent_multiline_quote(q) for q in quotes[:4]]
    body_html = '\n'.join(rendered)
    return '<div style="text-align:center;">\n\t<h3 style="margin-bottom:0;">\n\t\t✓ 미리 입어 본 착용후기 (모델/스텝/MD리뷰)</h3>\n\t<br>\n\t<p>\n\t\t<span style="font-size:14px; line-height:1.8;">\n' + body_html + '\n</span>\n\t\t<br>\n\t\t<br>\n\t\t<br>\n\t</p>\n</div>'


def wrap_answer_lines(answer: str) -> str:
    answer = normalize_phrase(answer)
    if not answer:
        return ''
    if len(answer) <= 34:
        return answer + '<br>'
    split_at = max(answer.rfind(' ', 0, 30), answer.rfind(' ', 0, 34))
    if split_at == -1:
        parts = re.split(r'(?<=[.!?])\s+|,\s*', answer)
        parts = [normalize_phrase(x) for x in parts if normalize_phrase(x)]
        if len(parts) <= 1:
            return answer + '<br>'
        first = parts[0]
        rest = ' '.join(parts[1:])
    else:
        first = answer[:split_at].rstrip()
        rest = answer[split_at + 1:].lstrip()
    return first + '<br>\n' + rest + '<br>'


def build_faq_block(section: str, data: Dict[str, str]) -> str:
    body = extract_block(section, '(FAQ) 이 상품, 이게 궁금해요', [])
    body = re.sub(r'^\(FAQ\) 이 상품, 이게 궁금해요!?', '', body).strip()
    pairs = re.findall(r'Q\.\s*(.*?)\s*A\.\s*(.*?)(?=(?:Q\.|$))', body, flags=re.S)
    faqs = []
    for q, a in pairs:
        q = normalize_phrase(q)
        a = normalize_phrase(a)
        if q and a:
            faqs.append((q, a))
    if len(faqs) < 4:
        faqs = build_relevant_faqs(data)
    rendered = ['<div style="text-align:center;">', '\t<h3 style="margin-bottom:0;">', '\t\t✓ (FAQ) 이 상품, 이게 궁금해요!</h3>', '\t<br>', '\t<p><span style="font-size:14px; line-height:1.4;">']
    for q, a in faqs[:4]:
        rendered.append(f'Q. {q}<br>')
        rendered.append(f'A. {wrap_answer_lines(a)}')
        rendered.append('<br>')
    rendered.extend(['</span>', '\t\t<br>', '\t\t<br>', '\t\t<br>', '\t</p>', '</div>'])
    return '\n'.join(rendered)


def assemble_final_output(raw_result: str, source_block: str, data: Dict[str, str]):
    lines = []
    lines.append(f"상품명 : {data['display_name']}")
    lines.append('')
    lines.append(f"컬러 : {data['color']}")
    lines.append(f"사이즈 : {data['size']}")
    material_items = [x.strip() for x in (data['material'] or '').split('+') if x.strip()]
    material_line = ' + '.join(material_items) if material_items else data['material']
    if '(건조기사용금지)' not in material_line:
        material_line = f'{material_line} (건조기사용금지)'
    lines.append(f'소재 : {material_line}')
    lines.append('소재설명 :')
    md_lines = format_material_desc_for_top(data['material_desc'])
    if md_lines:
        for x in md_lines:
            lines.append(f'- {x}')
    else:
        lines.append('-')
    lines.append(f"제조국 : {data['country']}")
    lines.append('')
    lines.append('-----------------')
    lines.append('포인트 원고(포토샵 작업)')
    lines.append('-----------------')
    lines.append('')
    lines.append('1. 동영상')
    lines.append('')

    point_fallbacks = build_point_fallbacks(data)
    sec2 = extract_block(raw_result, '2. 헤드라인', ['3. (원단컷)'])
    sec3 = extract_block(raw_result, '3. (원단컷)', ['4. (디테일컷)'])
    sec4 = extract_block(raw_result, '4. (디테일컷)', ['5. (핵심어필 포인트)', '5. (핵심 어필 포인트)']).replace('5. (핵심 어필 포인트)', '5. (핵심어필 포인트)')
    if '5. (핵심어필 포인트)' in raw_result:
        sec5 = extract_block(raw_result, '5. (핵심어필 포인트)', ['---------------------------------', '텍스트 소스', '이런 분께 추천해요'])
    else:
        sec5 = extract_block(raw_result, '5. (핵심 어필 포인트)', ['---------------------------------', '텍스트 소스', '이런 분께 추천해요']).replace('5. (핵심 어필 포인트)', '5. (핵심어필 포인트)')

    if not get_block_body(sec2, '2. 헤드라인').strip():
        sec2 = point_fallbacks['2. 헤드라인']
    sec3 = format_point_block('3. (원단컷)', normalize_fabric_lines(get_block_body(sec3, '3. (원단컷)'), data))
    sec4 = format_point_block('4. (디테일컷)', normalize_detail_or_appeal_lines(get_block_body(sec4, '4. (디테일컷)'), data.get('detail_tip') or '', ['입었을 때 더 정돈돼 보이는 디테일이 살아 있습니다.', '작은 차이가 전체 분위기를 더 세련되게 완성합니다.']))
    sec5 = format_point_block('5. (핵심어필 포인트)', normalize_detail_or_appeal_lines(get_block_body(sec5, '5. (핵심어필 포인트)'), data.get('appeal_points') or data.get('fit') or '', ['체형 부담을 덜어 주는 실용적인 매력이 있습니다.', '매일 손이 가는 편안한 아이템입니다.']))

    for sec in [sec2, sec3, sec4, sec5]:
        lines.append(sec)
        lines.append('')
    lines.append('---------------------------------')
    lines.append('텍스트 소스')
    lines.append('---------------------------------')
    lines.append('')
    section = extract_text_source_section(raw_result)
    lines.append(build_recommend_block(section, data))
    lines.append('')
    lines.append(build_review_block(section, data))
    lines.append('')
    lines.append(build_faq_block(section, data))
    lines.append('')
    lines.append(build_shopping_block([], data))
    lines.append('')
    lines.append('----------------------------------')
    lines.append('MD원고(상품 설명 소스)')
    lines.append('----------------------------------')
    lines.append(source_block)
    lines.append('')
    lines.append('-----------------')
    lines.append('사이즈 팁')
    lines.append('-----------------')
    lines.append('')
    fallbacks = fallback_size_tips()
    for title in ['ㅇ55 (90) 160cm 48kg', 'ㅇ66 (95) 165cm 54kg', 'ㅇ66반 (95) 164cm 58kg', 'ㅇ77 (100) 163cm 61kg']:
        lines.append(extract_size_tip_block(raw_result, title, fallbacks))
        lines.append('')
    return '\n'.join(lines).strip()

def rewrite_material_desc(data: Dict[str, str]) -> str:
    memo = (data.get("material_desc") or "").strip()
    material = (data.get("material") or "").strip()
    if not memo and not material:
        return ""
    prompt = f"""
너는 여성의류 쇼핑몰 상세페이지의 소재설명 전문 에디터다.

입력 정보
- 소재: {material}
- 참고메모: {memo}

규칙
- 참고메모를 그대로 복붙하지 말고 자연스럽고 전문적인 설명으로 다시 쓴다.
- 2~4개의 짧은 리스팅 문장으로 작성한다.
- 문장 끝 표현 반복을 줄인다.
- 과장 없이 실무자가 바로 상세페이지에 넣을 수 있게 쓴다.
- 결과는 문장만 줄바꿈으로 출력한다. 번호, 기호, 설명 금지.
"""
    try:
        response = chat_with_retry(
            model="gpt-4.1",
            messages=[{"role":"system","content":"사용자가 입력한 추가/수정 요청사항은 최우선으로 반드시 반영해야 한다."},
                {"role": "system", "content": "너는 소재설명 정리 전문가다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_retries=1,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return memo

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

st.markdown("---")
st.subheader("상품 네이밍")
ncol1, ncol2 = st.columns([5, 1], vertical_alignment="bottom")
with ncol1:
    naming_input = st.text_area("상품 주요특징 입력", height=120, placeholder="예: 여리핏, 부드러운 엠보 텍스처, 상체 군살 커버, 루즈핏 맨투맨", key="naming_input_value")
with ncol2:
    if st.button("네이밍 생성", use_container_width=True):
        if naming_input.strip():
            with st.spinner("상품명을 생성 중입니다..."):
                try:
                    response = chat_with_retry(
                        model="gpt-4.1",
                        messages=[{"role":"system","content":"사용자가 입력한 추가/수정 요청사항은 최우선으로 반드시 반영해야 한다."},{"role": "system", "content": NAME_PROMPT}, {"role": "user", "content": naming_input}],
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
    data["material_desc"] = rewrite_material_desc(data)
    prompt_text = build_user_prompt(data)
    if additional_request.strip():
        prompt_text += "\n\n추가/수정 요청사항\n" + additional_request + "\n"

    user_content: List[Dict[str, Any]] = [{"type": "text", "text": prompt_text}]
    for img in uploaded_images[:5] if uploaded_images else []:
        user_content.append(file_to_content_item(img))

    with st.spinner("출력물을 생성 중입니다..."):
        try:
            response = chat_with_retry(
                model="gpt-4.1",
                messages=[{"role":"system","content":"사용자가 입력한 추가/수정 요청사항은 최우선으로 반드시 반영해야 한다."},
                    {"role": "system", "content": "MD원고에서는 상품명 아래 소개 문장과 [쇼핑에 꼭 참고하세요] 섹션을 넣지 않는다. 문장은 짧게 <br> 처리한다. 텍스트 소스는 4개 블록(추천/후기/FAQ/쇼핑에 꼭 참고하세요)으로 작성한다. FAQ는 상품 정보와 직접 관련된 질문만 만든다. 사이즈 팁 4개를 모두 채운다. 추가/수정 요청사항이 있으면 반드시 100% 반영한다. 무시하지 않는다."},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.2,
                max_retries=2,
            )
            raw_result = response.choices[0].message.content
            subsc_html = extract_subsc_html(raw_result, display_name)
            subsc_html, shopping_lines = normalize_md_subsc_html(subsc_html)
            subtap_html = build_subtap_html(data)
            source_block = FIXED_HTML_HEAD + "\n\n" + subsc_html + "\n\n" + subtap_html
            result = assemble_final_output(raw_result, source_block, data)
            result = result.replace(build_shopping_block([], data), build_shopping_block(shopping_lines, data))
        except RateLimitError:
            st.error("현재 OpenAI 요청이 일시적으로 몰려 원고 생성을 완료하지 못했습니다. 결괏값 품질을 유지하기 위해 자동 대체문구는 넣지 않았습니다. 잠시 후 다시 시도해 주세요.")
            st.stop()
        except Exception as e:
            st.error(f"원고 생성 중 오류가 발생했습니다: {e}")
            st.stop()

    st.text_area("결과", result, height=1200)
    docx_bytes = result_to_docx_bytes(result)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button("TXT 다운로드", data=result, file_name=f"{(display_name or 'page_builder').replace(' ', '_')}_output.txt", mime="text/plain", use_container_width=True)
    with c2:
        st.download_button("HWP 다운로드", data=docx_bytes, file_name=f"{(display_name or 'page_builder').replace(' ', '_')}_output.hwp", mime="application/x-hwp", use_container_width=True)

st.markdown("---")
st.markdown("© made by MISHARP, MIYAWA. All rights reserved.")
