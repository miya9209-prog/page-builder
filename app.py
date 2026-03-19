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
"""

st.subheader("상품 정보 입력")

col1, col2 = st.columns(2)

with col1:
    name = st.text_input("상품명", placeholder="예: 레이 슬리밍 티셔츠")
    material = st.text_input("소재", placeholder="예: 면35% 폴리65%")
    fit = st.text_input("핏", placeholder="예: 허리라인 강조 슬림핏")

with col2:
    color = st.text_input("컬러 옵션", placeholder="예: 블랙, 아이보리, 베이지")
    target = st.text_input("타겟", value="4050 여성")

features = st.text_area("핵심 특징", placeholder="예: 복부 커버, 허리 들뜸 방지, 신축성 우수")
detail = st.text_area("디테일 특징", placeholder="예: 꼬임 디테일, 인밴딩, 라글란 소매")
coordi = st.text_area("코디", placeholder="예: 슬랙스 / 데님 / 스커트")

st.subheader("사이즈 정보")

size_tip = st.text_area("사이즈 추천", placeholder="예: free사이즈로 77까지 추천드립니다.")
size_detail = st.text_area("실측 사이즈", placeholder="예: 어깨60 / 가슴134 / 총장67")

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

st.markdown("---")
st.markdown("© made by MISHARP, MIYAWA")
