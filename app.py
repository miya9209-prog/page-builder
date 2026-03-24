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

st.set_page_config(page_title="PAGE BUILDER", layout="wide")

if "reset_nonce" not in st.session_state:
    st.session_state.reset_nonce = 0

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

PRODUCT_COPY_PROMPT = """
당신은 상세페이지 원고 전문 최고의 공감형 라이터입니다.
4050 여성 전문 쇼핑몰 미샵(MISHARP)의 상품 상세페이지를
구매 전 불안 제거, 기대치 명확화, 사이즈·핏 확신 제공을 최우선 목표로 작성합니다.

핵심 원칙
- 텍스트 입력을 우선하고 이미지는 보조 참고만 합니다.
- [쇼핑에 꼭 참고하세요] 대신 [상품 포인트]를 사용합니다.
- 동영상 안내 문구는 절대 작성하지 않습니다.
- 실측사이즈 입력 여부와 관계없이 사이즈 팁 4개는 반드시 모두 작성합니다.

이번 응답에서는 "원고 양식" 안의 HTML 중 오직 <div id="subsc"> ... </div> 만 작성합니다.
<meta>, <link>, <div id="Subtap"> 는 작성하지 않습니다.

상품설명 HTML 규칙
<div id="subsc">
  <h3>상품명</h3>
  <p>
    본문 내용
  </p>
</div>

반드시 지킬 것
1. <div id="subsc"> 바로 다음 줄은 반드시 <h3>상품명</h3> 이어야 합니다.
2. 상품명은 <strong>로 쓰지 말고 반드시 <h3> 태그로만 씁니다.
3. 그 아래 <p> 안에 본문을 넣습니다.
4. 소제목은 <strong style="font-weight:700 !important;"> 태그를 사용합니다.
5. 줄바꿈은 <br>, 문단 구분은 <br><br> 사용합니다.
6. HTML 외 마크다운, 코드펜스 사용 금지입니다.
"""

OUTPUT_RULES = """
최종 출력은 반드시 아래 순서와 제목을 그대로 지켜 하나의 텍스트 문서로 작성합니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
기본사양
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

상품명 : 상품명 (컬러)
사이즈 :
소재 :
디테일 팁 :

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
원고 양식
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

원고 양식에는 아래 순서로만 출력합니다.
1. 고정 메타/링크 코드
2. <div id="subsc"> ... </div>
3. <div id="Subtap"> ... </div>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
포인트 코멘트
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

0. 동영상

1. 헤드라인

2. (원단컷)
- 원단관련 내용 리스팅형식으로

3. (디테일컷)
- 디테일 관련 내용 리스팅형식으로

4. 이런 분께 추천해요

5. (핵심 어필 포인트)
- 상품 usp 와 고객 니즈반영한 감성 문구 + 광고화 핵심 어필포인트 리스팅

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
하단 상세 원단컷 설명(나열식으로 변경)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 기존 대로 리스팅형

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사이즈 팁
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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

def build_user_prompt(data: Dict[str, str]) -> str:
    return f"""
{PRODUCT_COPY_PROMPT}

{OUTPUT_RULES}

입력 데이터
- 상품명: {data['product_name']}
- 거래처 상품명: {data['vendor_name']}
- 컬러: {data['color']}
- 사이즈: {data['size']}
- 실측사이즈: {data['measurement']}
- 소재: {data['material']}
- 디테일특징: {data['detail_tip']}
- 핏/실루엣: {data['fit']}
- 주요 어필 포인트: {data['appeal_points']}
- 타겟: {data['target']}
- 세탁방법: {data['washing']}
- 기타: {data['etc']}
"""

def build_subtap_html(data: Dict[str, str]) -> str:
    material = (data["material"] or "").strip() or "소재 정보 입력 필요"
    washing = (data["washing"] or "").strip() or "드라이클리닝, 단독 울코스 손세탁 권장"
    size_tip = (data["size"] or "").strip() or "상품 정보를 기준으로 추천 사이즈를 확인해 주세요."
    length_tip = """162-167cm에서는 모델핏을 참고해 주시고,
<br> 다리 길이나 체형에 따라 다르지만,
<br> 160cm이하에서는 모델의 핏보다 조금 길게
<br> 연출됩니다."""
    measurement = (data["measurement"] or "").strip() or "실측사이즈 정보를 입력해 주세요."

    material_desc = f"{material} 소재로 제작되었습니다."

    return f"""<div id="Subtap">
	<div id="header2" role="banner">
		<nav class="nav" role="navigation">

			<ul class="nav__list">
				<li>
					<input id="group-1" type="checkbox" hidden="">
					<label for="group-1" style="border-top-color: rgb(204, 204, 204); border-top-width: 1px; border-top-style: solid;">

						<p class="fa fa-angle-right"></p>소재 정보</label>

					<ul class="group-list">
						<li>
							<a href="#">

								<h3>소재 : {material}</h3>

								<p>
									{material_desc}
									<br>
								</p>

								<h3>세탁방법</h3>

								<p>{washing}</p>
							</a>
						</li>
					</ul>
				</li>

				<li>
					<input id="group-2" type="checkbox" hidden="">
					<label for="group-2">

						<p class="fa fa-angle-right"></p>사이즈 정보</label>

					<ul class="group-list gray">
						<li>
							<a href="#">

								<h3>사이즈 TIP</h3>

								<p>
									{size_tip}
								</p>

								<h3>길이 TIP</h3>

								<p>
									{length_tip}
								</p>
							</a>
						</li>
					</ul>
				</li>

				<li>
					<input id="group-3" type="checkbox" hidden="">
					<label for="group-3">

						<p class="fa fa-angle-right"></p>실측 사이즈</label>

					<ul class="group-list">
						<li>
							<a href="#">

								<p>{measurement}</p>

							</a>
						</li>
					</ul>
				</li>

				<li>
					<input id="group-5" type="checkbox" hidden="">
					<label for="group-5"><span class="fa fa-angle-right"></span>
						<a href="#crema-product-fit-1" style="padding: 0px; box-shadow:none; background:#f7f7f7;">실측사이즈 재는방법</a></label>
				</li>
			</ul>
		</nav>
	</div>
</div>"""

def extract_subsc_html(result: str, product_name: str) -> str:
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

def replace_source_section(result: str, source_block: str) -> str:
    pattern = r'━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n원고 양식\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[\s\S]*?━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n포인트 코멘트'
    replacement = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "원고 양식\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{source_block}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "포인트 코멘트"
    )
    if re.search(pattern, result):
        return re.sub(pattern, replacement, result, count=1)
    return result + "\n\n" + source_block

def result_to_docx_bytes(result_text: str) -> bytes:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Malgun Gothic"
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
    style.font.size = Pt(10.5)
    for line in result_text.splitlines():
        p = doc.add_paragraph()
        run = p.add_run(line)
        run.font.name = "Malgun Gothic"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
        run.font.size = Pt(10.5)
    bio = io.BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio.getvalue()

h1, h2 = st.columns([2.2, 1.0])
with h1:
    st.subheader("상품정보 입력")
with h2:
    st.write("")
    if st.button("초기화", use_container_width=True):
        st.session_state.reset_nonce += 1
        st.rerun()

nonce = st.session_state.reset_nonce
left, right = st.columns(2)

with left:
    product_name = st.text_input("상품명", placeholder="예: 소프트 웜톤 루즈핏 맨투맨", key=f"product_name_{nonce}")
    vendor_name = st.text_input("거래처 상품명", placeholder="예: 조이 오버핏 데님 자켓", key=f"vendor_name_{nonce}")
    color = st.text_input("컬러", placeholder="예: 베이지, 그레이, 블랙", key=f"color_{nonce}")
    size = st.text_input("사이즈", placeholder="예: FREE / S(55)~XL(88)", key=f"size_{nonce}")
    measurement = st.text_input("실측사이즈", placeholder="예: 가슴둘레146 / 어깨-소매79.5 / 소매단26.5 / 총길이78", key=f"measurement_{nonce}")
    material = st.text_input("소재", placeholder="예: 면80+나일론20", key=f"material_{nonce}")
    detail_tip = st.text_input("디테일 특징 (예:디자인, 절개라인, 부자재, 스펙상 특징 등)", key=f"detail_tip_{nonce}")

with right:
    fit = st.text_input("핏/실루엣 (예:정핏,레귤러핏,오버핏 등/체형커버, 다리길어보이는 등의 특장점)", key=f"fit_{nonce}")
    appeal_points = st.text_area("주요 어필 포인트 (예:고객 문제해결 포인트,원단 구김-탄력-내구성,체형커버,계절성,기능성,코디활용도 등)", height=150, key=f"appeal_points_{nonce}")
    target = st.text_input("타겟", value="4050 여성", key=f"target_{nonce}")
    washing = st.text_input("세탁방법", value="드라이클리닝, 단독 울코스 손세탁 권장", key=f"washing_{nonce}")
    etc = st.text_area("기타 (브랜드퀄리티,백화점납품상품,가격경쟁력,가성비,전문거래처 등)", height=130, key=f"etc_{nonce}")

st.subheader("이미지 업로드")
uploaded_images = st.file_uploader("이미지", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True, key=f"uploaded_images_{nonce}")

if st.button("생성하기", type="primary", use_container_width=True, key=f"generate_{nonce}"):
    data = {
        "product_name": product_name,
        "vendor_name": vendor_name,
        "color": color,
        "size": size,
        "measurement": measurement,
        "material": material,
        "detail_tip": detail_tip,
        "fit": fit,
        "appeal_points": appeal_points,
        "target": target,
        "washing": washing,
        "etc": etc,
    }

    prompt_text = build_user_prompt(data)
    user_content: List[Dict[str, Any]] = [{"type": "text", "text": prompt_text}]
    for img in uploaded_images[:5] if uploaded_images else []:
        user_content.append(file_to_content_item(img))

    with st.spinner("출력물을 생성 중입니다..."):
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": "subsc만 정확히 작성하고, 포인트 코멘트와 사이즈 팁은 채운다. 동영상 문구는 쓰지 않는다."},
                {"role": "user", "content": user_content}
            ],
            temperature=0.2,
        )
        raw_result = response.choices[0].message.content
        subsc_html = extract_subsc_html(raw_result, product_name)
        subtap_html = build_subtap_html(data)
        source_block = FIXED_HTML_HEAD + "\n\n" + subsc_html + "\n\n" + subtap_html
        result = replace_source_section(raw_result, source_block)

    st.text_area("결과", result, height=1100)
    docx_bytes = result_to_docx_bytes(result)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button("TXT 다운로드", data=result, file_name=f"{product_name or 'page_builder'}_output.txt", mime="text/plain", use_container_width=True)
    with c2:
        st.download_button("한글 호환 DOCX 다운로드", data=docx_bytes, file_name=f"{product_name or 'page_builder'}_output.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)

st.markdown("---")
st.markdown("© made by MISHARP, MIYAWA. All rights reserved.")
