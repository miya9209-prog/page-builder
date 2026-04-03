
import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="Page Builder", layout="wide")

client = OpenAI(api_key=st.secrets.get("OPENAI_API_KEY",""))

PROMPT_RULE = """
추천 문장은 반드시 아래 형태로 작성하세요:
- ~을 찾으시는 분
- ~을 원하시는 분
- ~이 필요하신 분
- ~을 중요하게 생각하시는 분

금지:
- 추천합니다 / 좋습니다 / 가능합니다
- 문장형 표현

모든 문장은 반드시 '분'으로 끝나야 합니다.
"""

def generate(prompt):
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role":"system","content":"4050 여성 의류 MD처럼 작성"},
            {"role":"user","content":PROMPT_RULE + "\n" + prompt}
        ],
        temperature=0.7
    )
    return res.choices[0].message.content

def render_sample():
    data = {
        "recommend":[
            "고급스러운 오피스룩을 찾으시는 4050 여성 분",
            "하객룩으로도 손색없는 세련된 디자인을 원하시는 분",
            "데일리룩으로 활용 가능한 실용적인 아이템을 찾으시는 분",
            "구김 걱정 없이 깔끔한 스타일을 유지하고 싶은 분"
        ]
    }
    html = "<br>".join([f"▪ {x}" for x in data["recommend"]])
    return html

st.title("페이지빌더 최종 안정버전")

if st.button("테스트"):
    html = render_sample()
    st.code(html)
    st.markdown(html, unsafe_allow_html=True)
