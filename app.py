import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="page-builder", layout="wide")

st.title("PAGE BUILDER")
st.caption("미샵 전환형 상세페이지 기획 + HTML 원고 통합 생성기")

api_key = st.secrets.get("OPENAI_API_KEY", "")
if not api_key:
    st.warning("OPENAI_API_KEY가 설정되지 않았습니다.")
    st.stop()

client = OpenAI(api_key=api_key)

def build_prompt(data):
    return f"""
상품명: {data['name']}
컬러 옵션: {data['color']}
소재: {data['material']}
핏: {data['fit']}
특징: {data['features']}
디테일: {data['detail']}
코디: {data['coordi']}
타겟: {data['target']}

사이즈 추천: {data['size_tip']}
실측 사이즈: {data['size_detail']}

미샵 스타일 기획 + HTML 생성
"""

st.subheader("상품 정보 입력")

col1, col2 = st.columns(2)

with col1:
    name = st.text_input("상품명")
    material = st.text_input("소재")
    fit = st.text_input("핏")

with col2:
    color = st.text_input("컬러 옵션")
    target = st.text_input("타겟")

features = st.text_area("핵심 특징")
detail = st.text_area("디테일 특징")
coordi = st.text_area("코디")

st.subheader("사이즈 정보")
size_tip = st.text_area("사이즈 추천")
size_detail = st.text_area("실측 사이즈")

if st.button("생성하기"):
    data = {
        "name": name,
        "color": color,
        "material": material,
        "fit": fit,
        "features": features,
        "detail": detail,
        "coordi": coordi,
        "target": target,
        "size_tip": size_tip,
        "size_detail": size_detail
    }

    prompt = build_prompt(data)

    res = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role":"system","content":"미샵 상세페이지 전문가"},
            {"role":"user","content":prompt}
        ]
    )

    result = res.choices[0].message.content

    st.text_area("결과", result, height=900)
    st.download_button("다운로드", result, file_name="page_builder.txt")

# 🔥 화면 최하단 카피라이트
st.markdown("---")
st.markdown("© made by MISHARP, MIYAWA")
