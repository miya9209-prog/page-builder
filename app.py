import base64
import io
import mimetypes
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
<link href="http://netdna.bootstrapcdn.com/font-awesome/4.3.0/css/font-awesome.min.css" rel="stylesheet">
<link href="/SRC2/cssmtmenu/style.css" rel="stylesheet" type="text/css">
<link href="//spoqa.github.io/spoqa-han-sans/css/SpoqaHanSans-kr.css" rel="stylesheet" type="text/css">
<link href="//misharp.co.kr/subtap.css" rel="stylesheet" type="text/css">"""

PRODUCT_COPY_PROMPT = """
당신은 상세페이지 원고 전문 최고의 공감형 라이터입니다.
4050 여성 전문 쇼핑몰 미샵(MISHARP)의 상품 상세페이지를
구매 전 불안 제거, 기대치 명확화, 사이즈·핏 확신 제공을 최우선 목표로 작성합니다.

중요:
- 텍스트 입력을 우선하고 이미지는 보조 참고만 합니다.
- [쇼핑에 꼭 참고하세요] 대신 [상품 포인트]를 사용합니다.
- 상품설명 HTML은 반드시 아래 구조를 지킵니다.

<div id="subsc">
  <h3>상품명</h3>
  <p>
    본문 내용
  </p>
</div>

반드시 지킬 것:
1. <div id="subsc"> 바로 다음 줄은 반드시 <h3>상품명</h3> 이어야 한다.
2. 상품명은 <strong>로 쓰지 말고 반드시 <h3> 태그로만 쓴다.
3. 그 아래 <p> 안에 본문을 넣는다.
4. 소제목은 <strong style="font-weight:700 !important;"> 태그를 사용한다.
5. 줄바꿈은 <br>, 문단 구분은 <br><br> 사용한다.
6. HTML 외 마크다운, 코드펜스 사용 금지.
"""

OUTPUT_RULES = f"""
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
1. 아래 고정 코드
{FIXED_HTML_HEAD}

2. <div id="subsc"> ... </div>
3. <div id="Subtap"> ... </div>

중요:
- 원고 양식 최상단 첫 줄은 반드시 <meta http-equiv="X-UA-Compatible" content="IE=edge,chrome=1"> 로 시작해야 한다.
- 그 아래 나머지 meta/link 코드가 그대로 이어져야 한다.
- 그 다음에 <div id="subsc"> 가 와야 한다.
- 마지막에 <div id="Subtap"> 가 와야 한다.

Subtap HTML 작성 규칙
- 소재 정보에는 소재 설명 + 세탁방법
- 사이즈 정보에는 사이즈 TIP + 길이 TIP
- 실측 사이즈에는 입력된 실측사이즈
- 실측사이즈 재는방법 링크 포함

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
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{b64}"}
    }

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

def force_fixed_html_order(result: str) -> str:
    # normalize subsc start if model omitted h3
    if '<div id="subsc">' in result:
        start = result.find('<div id="subsc">')
        end = result.find('</div>', start)
        if end != -1:
            subsc_block = result[start:end+6]
            if '<h3>' not in subsc_block:
                product_name = st.session_state.get("last_product_name", "상품명")
                subsc_block_fixed = subsc_block.replace('<div id="subsc">', f'<div id="subsc">\n  <h3>{product_name}</h3>', 1)
                result = result.replace(subsc_block, subsc_block_fixed, 1)

    # always prepend fixed head immediately before first subsc block
    if '<div id="subsc">' in result:
        start = result.find('<div id="subsc">')
        # remove existing duplicated head blocks first
        result_wo_head = result.replace(FIXED_HTML_HEAD, '').strip()
        start = result_wo_head.find('<div id="subsc">')
        result_wo_head = result_wo_head[:start] + FIXED_HTML_HEAD + "\n\n" + result_wo_head[start:]
        return result_wo_head
    return FIXED_HTML_HEAD + "\n\n" + result

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
    product_name = st.text_input("상품명", key=f"product_name_{nonce}")
    vendor_name = st.text_input("거래처 상품명", key=f"vendor_name_{nonce}")
    color = st.text_input("컬러", key=f"color_{nonce}")
    size = st.text_input("사이즈", key=f"size_{nonce}")
    measurement = st.text_input("실측사이즈", key=f"measurement_{nonce}")
    material = st.text_input("소재", key=f"material_{nonce}")
    detail_tip = st.text_input("디테일 특징", key=f"detail_tip_{nonce}")

with right:
    fit = st.text_input("핏/실루엣", key=f"fit_{nonce}")
    appeal_points = st.text_area("주요 어필 포인트", height=150, key=f"appeal_points_{nonce}")
    target = st.text_input("타겟", value="4050 여성", key=f"target_{nonce}")
    washing = st.text_input("세탁방법", value="드라이클리닝, 단독 울코스 손세탁 권장", key=f"washing_{nonce}")
    etc = st.text_area("기타", height=130, key=f"etc_{nonce}")

st.subheader("이미지 업로드")
uploaded_images = st.file_uploader("", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True, key=f"uploaded_images_{nonce}")

if st.button("생성하기", type="primary", use_container_width=True, key=f"generate_{nonce}"):
    st.session_state["last_product_name"] = product_name or "상품명"

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
                {"role": "system", "content": "당신은 미샵의 실무 문서 출력기다. 반드시 고정 메타/링크 코드를 최상단에 넣고, subsc는 h3 상품명으로 시작하게 한다."},
                {"role": "user", "content": user_content}
            ],
            temperature=0.2,
        )
        result = force_fixed_html_order(response.choices[0].message.content)

    st.text_area("결과", result, height=1100)
    docx_bytes = result_to_docx_bytes(result)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button("TXT 다운로드", data=result, file_name=f"{product_name or 'page_builder'}_output.txt", mime="text/plain", use_container_width=True)
    with c2:
        st.download_button("한글 호환 DOCX 다운로드", data=docx_bytes, file_name=f"{product_name or 'page_builder'}_output.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)

st.markdown("---")
st.markdown("© made by MISHARP, MIYAWA. All rights reserved.")
