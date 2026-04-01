
import re
import streamlit as st

def force_point_block():
    return """3. (원단컷)
울·텐셀·레이온·나일론 혼방의 부드럽고 고급스러운 텍스처.
은은한 광택감과 고급스러운 표면 질감.
가볍고 부담 없는 두께감으로 자연스럽게 흐르는 여리한 실루엣.

4. (디테일컷)
탈부착 가능한 타이 디테일로 다양한 스타일 연출.
볼륨감 있는 소매로 팔 라인을 자연스럽게 커버.
앞 절개 라인으로 슬림해 보이는 시각적 효과.

5. (핵심어필 포인트)
군살을 자연스럽게 커버하는 세련된 실루엣 핏.
구김이 적어 관리가 편한 실용적 소재.
오피스·하객·데일리까지 확장 가능한 스타일링 활용도.
"""

def apply_override(text):
    return re.sub(
        r"3\. \(원단컷\)[\s\S]*?5\. \(핵심어필 포인트\)[\s\S]*?(?=\n-+|$)",
        force_point_block(),
        text
    )

st.title("page builder")

if "result" not in st.session_state:
    st.session_state.result = ""

user_input = st.text_area("input")

if st.button("generate"):
    result = user_input
    result = apply_override(result)
    st.session_state.result = result

if st.session_state.result:
    st.text_area("output", st.session_state.result, height=500)
