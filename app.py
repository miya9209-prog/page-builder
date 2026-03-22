import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="page-builder", layout="wide")

st.title("PAGE BUILDER (최종 양식 적용)")
st.caption("미샵 상세페이지 기획 + 원고 생성기")

api_key = st.secrets.get("OPENAI_API_KEY", "")
if not api_key:
    st.warning("OPENAI_API_KEY가 설정되지 않았습니다.")
    st.stop()

client = OpenAI(api_key=api_key)

def build_prompt(data):
    return f'''
[출력물 양식]

1. 기본 사양

상품명 : {data['product_name']} ({data['color']})
사이즈 : {data['size']}
소재 : {data['material']}
디테일 팁 : {data['detail']}

2. 원고 양식
- 입력된 프롬프트 기준 HTML 원고 생성

3. 상품 기획(전체 컨셉)

3-0. 대표 이미지 & 3초훅
3-1. 이런 분께 추천해요
3-2. 상품 핵심 어필 포인트 광고화
3-3. 디테일 포인트
3-4. 원단 포인트

4. 소재/착용감

5. 최하단 사이즈팁 작성

[입력 데이터]
거래처 상품명: {data['vendor_name']}
핏: {data['fit']}
어필포인트: {data['features']}
기타: {data['etc']}
'''

st.subheader("상품 정보 입력")

col1, col2 = st.columns(2)

with col1:
    product_name = st.text_input("상품명")
    vendor_name = st.text_input("거래처 상품명")
    color = st.text_input("컬러")
    size = st.text_input("사이즈")
    material = st.text_input("소재")

with col2:
    detail = st.text_input("디테일 특징")
    fit = st.text_input("핏/실루엣")
    features = st.text_area("주요 어필 포인트")
    etc = st.text_area("기타")

st.markdown("타겟: 4050 여성 (고정)")
st.markdown("세탁방법: 드라이클리닝, 단독 울코스 손세탁 권장 (고정)")

if st.button("생성하기"):
    data = {
        "product_name": product_name,
        "vendor_name": vendor_name,
        "color": color,
        "size": size,
        "material": material,
        "detail": detail,
        "fit": fit,
        "features": features,
        "etc": etc
    }

    res = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role":"system","content":"양식 반드시 준수"},
            {"role":"user","content":build_prompt(data)}
        ]
    )

    result = res.choices[0].message.content

    st.text_area("결과", result, height=900)
    st.download_button("다운로드", result, file_name="page_builder.txt")

st.markdown("---")
st.markdown("© made by MISHARP, MIYAWA")
