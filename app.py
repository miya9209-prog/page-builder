import base64
import mimetypes
from typing import List, Dict, Any

import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="page-builder", layout="wide")

st.title("PAGE BUILDER")
st.caption("미샵 상세페이지 기획 + 원고 생성기")

st.markdown("""
<style>
.block-container {padding-top: 1.8rem; padding-bottom: 2rem;}
textarea, input {font-size: 15px !important;}
</style>
""", unsafe_allow_html=True)

api_key = st.secrets.get("OPENAI_API_KEY", "")
if not api_key:
    st.warning("OPENAI_API_KEY가 설정되지 않았습니다. Streamlit Cloud Secrets 또는 .streamlit/secrets.toml을 확인해 주세요.")
    st.stop()

client = OpenAI(api_key=api_key)

WRITING_PROMPT = """
당신은 상세페이지 원고 전문 최고의 공감형 라이터입니다.
4050 여성 전문 쇼핑몰 미샵(MISHARP)의 상품 상세페이지를
구매 전 불안 제거, 기대치 명확화, 사이즈·핏 확신 제공을
최우선 목표로 라이팅합니다.

프로젝트 목표
- 사이즈·핏 관련 반품 감소
- 생각보다 ○○했다 유형의 변심 반품 감소
- 결제 후 배송 전 취소 감소
- 고객이 구매 전 입는 장면을 명확히 상상하도록 유도

라이팅 핵심 원칙
1. 두께, 무게감, 핏, 기장, 체감은 애매하게 쓰지 않습니다.
2. 정사이즈/여유핏/슬림핏을 단독으로 쓰지 말고 어떤 체형에 왜 잘 맞는지 설명합니다.
3. 필요시 일부 체형·취향에 맞지 않는 경우도 선택 기준으로 부드럽게 안내합니다.
4. 언제 입는지(TPO)를 구체적으로 씁니다.
5. 스펙 나열이 아니라 체감 언어로 해석합니다.
6. 존칭체를 유지하고 과장하지 않습니다.
7. 텍스트 정보를 기준으로 쓰고, 업로드된 이미지는 핏/실루엣/두께/분위기 판단의 보조 참고로만 활용합니다.
8. 이미지와 텍스트가 충돌하면 텍스트 입력을 우선합니다.

원고 HTML 작성 규칙
- 실제 복사해서 사용할 수 있는 HTML로 작성합니다.
- 상품 본문 원고는 반드시 <div id="subsc"> ... </div> 구조로 작성합니다.
- 소제목은 <strong style="font-weight:700 !important;"> 태그를 사용합니다.
- 줄바꿈은 <br>, 문단 구분은 <br><br> 사용합니다.
- HTML 외 마크다운, 코드펜스, 설명문을 넣지 않습니다.

사이즈 정보 블록 HTML 규칙
- 반드시 <div id="Subtap"> ... </div> 구조로 작성합니다.
- 소재 정보 / 사이즈 정보 / 실측 사이즈 세 블록을 모두 작성합니다.
- 세탁방법, 사이즈 TIP, 길이 TIP, 실측사이즈는 입력값을 반영합니다.
"""

OUTPUT_RULES = """
최종 출력은 반드시 아래 순서와 제목을 그대로 지켜 하나의 텍스트 문서로 작성합니다.

1. 기본 사양

상품명 : 상품명 (컬러)
사이즈 :
소재 :
디테일 팁 :

2. 원고 양식

여기에는 아래 2개의 HTML만 출력합니다.
첫째, <div id="Subtap"> ... </div>
둘째, <div id="subsc"> ... </div>

3. 상품 기획(전체 컨셉)

3-0. 대표 이미지 & 3초훅
구성 : 대표이미지 + 큰 헤드라인 1~2줄 + 서브헤드라인 2~3줄
큰 헤드라인은 고객 페인포인트 기반, 뾰족한 상품 USP 기반의 감성적이고 훅이 강한 문구
서브헤드라인은 헤드라인을 구체적으로 받침하는 문구

3-1. 이런 분께 추천해요

3-2. 상품 핵심 어필 포인트 광고화 3~5가지(핵심특징, 착용효과)

3-3. 디테일 포인트

3-4. 원단 포인트

4. 소재/착용감(특장점 리스팅형식으로)

5. 최하단 사이즈팁 작성

사이즈TIP 작성 규칙
- 아래 4개 체형수치는 고정합니다.
- 아이템에 따라 각 체형별 착용 관련 내용만 변경합니다.
- 실제 고객에게 어필할 수 있게 2~3줄 정도로 작성합니다.

ㅇ55 (90) 160cm 48kg
ㅇ66 (95) 165cm 54kg
ㅇ66반 (95) 164cm 58kg
ㅇ77 (100) 163cm 61kg

중요 삭제 규칙
- 코디제안, 코디컷 가이드, 리뷰포인트, CTA는 절대 출력하지 않습니다.

중요 형식 규칙
- section, ul, li 같은 설명용 HTML 래퍼를 1번, 3번, 4번, 5번에 사용하지 않습니다.
- 1번, 3번, 4번, 5번은 일반 텍스트 문서 형식으로 출력합니다.
- 2번에서만 HTML을 출력합니다.
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
{WRITING_PROMPT}

{OUTPUT_RULES}

입력 데이터
- 상품명: {data['product_name']}
- 거래처 상품명: {data['vendor_name']}
- 컬러: {data['color']}
- 사이즈: {data['size']}
- 소재: {data['material']}
- 디테일특징: {data['detail_tip']}
- 핏/실루엣: {data['fit']}
- 주요 어필 포인트: {data['appeal_points']}
- 타겟: {data['target']}
- 세탁방법: {data['washing']}
- 기타: {data['etc']}

최종 지시
- 위 입력 데이터를 기준으로 작성합니다.
- 1. 기본 사양부터 5. 최하단 사이즈팁 작성까지 정확히 출력합니다.
- 2. 원고 양식에는 HTML 두 덩어리만 출력합니다.
- 1번, 3번, 4번, 5번은 일반 텍스트로 출력합니다.
- 코드펜스, 마크다운 제목, 불필요한 설명문을 넣지 않습니다.
"""

st.subheader("상품정보 입력")

col1, col2 = st.columns(2)

with col1:
    product_name = st.text_input("상품명", placeholder="예: 소프트 웜톤 루즈핏 맨투맨")
    vendor_name = st.text_input("거래처 상품명", placeholder="예: 조이 오버핏 데님 자켓")
    color = st.text_input("컬러", placeholder="예: 베이지, 그레이, 블랙")
    size = st.text_input("사이즈", placeholder="예: FREE / S(55)~XL(88)")
    material = st.text_input("소재", placeholder="예: 면54% 폴리에스터37% 스판9%")
    detail_tip = st.text_input("디테일특징", placeholder="예: 고급스럽게 볼륨감을 주는 소프트 엠보 타입")

with col2:
    fit = st.text_input("핏/실루엣", placeholder="예: 상체 군살을 자연스럽게 커버하는 여유 있는 루즈핏")
    appeal_points = st.text_area("주요 어필 포인트", height=150, placeholder="예: 얼굴빛을 살리는 웜톤 컬러 / 보풀 걱정 적은 원단 / 편안한 착용감 / 데일리 활용도")
    target = st.text_input("타겟", value="4050 여성", placeholder="4050 여성")
    washing = st.text_input("세탁방법", value="드라이클리닝, 단독 울코스 손세탁 권장", placeholder="드라이클리닝, 단독 울코스 손세탁 권장")
    etc = st.text_area("기타", height=100, placeholder="예: 간절기~초겨울 착용 / 이미지 기준 상체가 부해 보이지 않음 / 단독, 이너 모두 활용 가능")

st.subheader("이미지 업로드 (텍스트 기반 + 이미지 보조)")
uploaded_images = st.file_uploader(
    "이미지는 보조 참고용입니다. 텍스트 입력을 우선하고, 이미지는 핏/실루엣/분위기 판단에만 참고합니다.",
    type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True,
)

if uploaded_images:
    preview_cols = st.columns(min(len(uploaded_images), 4))
    for i, img in enumerate(uploaded_images[:4]):
        with preview_cols[i]:
            st.image(img, use_container_width=True, caption=img.name)

with st.expander("현재 적용 중인 출력 규칙 보기", expanded=False):
    st.text_area("출력 규칙", OUTPUT_RULES, height=420, disabled=True)

if st.button("생성하기", type="primary", use_container_width=True):
    if not product_name.strip():
        st.warning("상품명을 입력해 주세요.")
        st.stop()

    data = {
        "product_name": product_name,
        "vendor_name": vendor_name,
        "color": color,
        "size": size,
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

    with st.spinner("형준님 양식대로 출력물을 생성 중입니다..."):
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {
                    "role": "system",
                    "content": "당신은 미샵의 실무 문서 출력기다. 사용자가 준 양식과 순서를 절대 바꾸지 말고, 2번에서만 HTML을 출력한다."
                },
                {
                    "role": "user",
                    "content": user_content
                }
            ],
            temperature=0.25,
        )
        result = response.choices[0].message.content

    st.success("생성이 완료되었습니다.")
    st.text_area("결과", result, height=1100)

    st.download_button(
        "TXT 다운로드",
        data=result,
        file_name=f"{product_name}_page_builder.txt",
        mime="text/plain",
        use_container_width=True,
    )

st.markdown("---")
st.markdown("© made by MISHARP, MIYAWA")
