import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="page-builder", layout="wide")

st.title("PAGE BUILDER")
st.caption("미샵 상세페이지 기획 + 원고 생성기 (텍스트 기반 + 이미지 보조)")

api_key = st.secrets.get("OPENAI_API_KEY", "")
if not api_key:
    st.warning("OPENAI_API_KEY가 설정되지 않았습니다.")
    st.stop()

client = OpenAI(api_key=api_key)

def build_prompt(data):
    return f'''
[작성 기준]
- 텍스트 정보를 기준으로 작성
- 이미지는 보조 참고용으로 활용

[출력 양식]
1. 기본 사양
상품명 : {data['name']} ({data['color']})
사이즈 : {data['size']}
소재 : {data['material']}
디테일 팁 : {data['detail']}

2. 상품 기획
3. 소재/착용감
4. 사이즈TIP

[입력 데이터]
핵심 특징: {data['features']}
코디: {data['coordi']}
타겟: {data['target']}
사이즈 추천: {data['size_tip']}
실측 사이즈: {data['size_detail']}
'''

st.subheader("상품 정보 입력")

col1, col2 = st.columns(2)

with col1:
    name = st.text_input("상품명", placeholder="레이 슬리밍 티셔츠")
    material = st.text_input("소재", placeholder="면35% 폴리65%")
    size = st.text_input("사이즈", placeholder="Free / S,M,L")
    target = st.text_input("타겟", value="4050 여성")

with col2:
    color = st.text_input("컬러 옵션", placeholder="블랙, 아이보리")
    features = st.text_area("핵심 특징", placeholder="복부 커버, 신축성")
    detail = st.text_area("디테일 특징", placeholder="꼬임 디테일")
    coordi = st.text_area("코디", placeholder="슬랙스, 데님")

st.subheader("사이즈 정보")
size_tip = st.text_area("사이즈 추천", placeholder="77까지 추천")
size_detail = st.text_area("실측 사이즈", placeholder="어깨60 가슴134")

st.subheader("이미지 업로드 (보조 참고용)")
images = st.file_uploader("이미지", accept_multiple_files=True)

if st.button("생성하기"):
    data = {
        "name": name,
        "color": color,
        "material": material,
        "size": size,
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
