
import streamlit as st

def build_point_block(data):
    return f"""-----------------
포인트 원고(포토샵 작업)
-----------------

1. 동영상

2. 헤드라인  
{data['headline_line1']}  
{data['headline_line2']}

3. (원단컷)
{data['fabric1']}
{data['fabric2']}
{data['fabric3']}

4. (디테일컷)
{data['detail1']}
{data['detail2']}
{data['detail3']}

5. (핵심어필 포인트)
{data['appeal1']}
{data['appeal2']}
{data['appeal3']}
"""


def build_md_block(data):
    return f"""-----------------
MD원고
-----------------

{data['name']}

[이 상품을 초이스한 이유입니다.]
{data['md1']}
{data['md2']}
{data['md3']}

[원단과 두께 체감에 대하여]
{data['fabric1']}
{data['fabric2']}
{data['fabric3']}

[체형과 핏, 사이즈 선택 가이드]
{data['size']}
여유 있는 핏으로 체형 구애 없이 착용 가능합니다.
상체를 자연스럽게 슬림하게 정리해주는 디자인입니다.

[이렇게 입는 날이 많아집니다]
오피스룩으로 단정하게 연출하기 좋습니다.
하객룩, 모임룩으로도 활용 가능합니다.
데일리룩으로도 부담 없이 입기 좋습니다.
"""


def build_text_block():
    return """-----------------
텍스트 소스
-----------------

이런 분께 추천해요
- 다양한 스타일링을 원하는 분
- 체형 커버를 원하는 분
- 관리 쉬운 소재를 원하는 분

FAQ
Q. 사이즈는 어떤가요?
A. FREE 사이즈로 77까지 추천드립니다.

Q. 세탁은 어떻게 하나요?
A. 드라이클리닝 권장드립니다.
"""


def generate(data):
    return build_point_block(data) + "\n\n" + build_text_block() + "\n\n" + build_md_block(data)


st.title("페이지빌더 안정버전")

name = st.text_input("상품명", "비비안 브이넥 타이 블라우스")

if st.button("생성하기"):
    data = {
        "name": name,
        "headline_line1": "여성스러움과 세련미를 동시에,",
        "headline_line2": "타이로 다양한 연출이 가능한 브이넥 블라우스",
        "fabric1": "울·텐셀·레이온·나일론 혼방의 부드러운 텍스처.",
        "fabric2": "은은한 광택감과 고급스러운 표면 질감.",
        "fabric3": "가볍고 자연스럽게 흐르는 실루엣.",
        "detail1": "탈부착 가능한 타이 디테일.",
        "detail2": "볼륨감 있는 소매.",
        "detail3": "앞 절개 라인 포인트.",
        "appeal1": "군살 커버 실루엣.",
        "appeal2": "구김 적은 소재.",
        "appeal3": "다양한 스타일링 활용.",
        "md1": "세련된 무드를 완성하는 블라우스입니다.",
        "md2": "군살 커버에 효과적인 핏입니다.",
        "md3": "다양한 TPO 활용 가능합니다.",
        "size": "FREE 사이즈로 77까지 추천드립니다."
    }

    result = generate(data)
    st.text_area("결과", result, height=600)

    st.download_button("텍스트 다운로드", result, file_name="output.txt")
