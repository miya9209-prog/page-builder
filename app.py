import base64
import mimetypes
from typing import List, Dict, Any

import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="page-builder", layout="wide")

st.title("PAGE BUILDER")
st.caption("미샵 상세페이지 기획 + HTML 원고 생성기")

st.markdown("""
<style>
.block-container {padding-top: 2rem; padding-bottom: 2rem;}
textarea, input {font-size: 15px !important;}
.small-note {color:#666; font-size:13px;}
</style>
""", unsafe_allow_html=True)

api_key = st.secrets.get("OPENAI_API_KEY", "")
if not api_key:
    st.warning("OPENAI_API_KEY가 설정되지 않았습니다. Streamlit Cloud Secrets 또는 .streamlit/secrets.toml을 확인해 주세요.")
    st.stop()

client = OpenAI(api_key=api_key)

OUTPUT_SCHEMA = """
[출력물 양식 - 반드시 이 순서와 제목을 그대로 사용]

1. 기본 사양

상품명 : 상품명 (컬러)
사이즈 :
소재 :
디테일 팁 :

2. 원고 양식

아래 HTML 블록을 실제 복사해서 사용할 수 있는 완성형으로 출력한다.
반드시 아래 구조를 유지한다.

<div id="Subtap">
  <div id="header2" role="banner">
    <nav class="nav" role="navigation">
      <ul class="nav__list">
        <li>
          <input id="group-1" type="checkbox" hidden="">
          <label for="group-1"><p class="fa fa-angle-right"></p>소재 정보</label>
          <ul class="group-list">
            <li><a href="#"><h3>소재 : ...</h3><p>...</p><h3>세탁방법</h3><p>...</p></a></li>
          </ul>
        </li>
        <li>
          <input id="group-2" type="checkbox" hidden="">
          <label for="group-2"><p class="fa fa-angle-right"></p>사이즈 정보</label>
          <ul class="group-list gray">
            <li><a href="#"><h3>사이즈 TIP</h3><p>...</p><h3>길이 TIP</h3><p>...</p></a></li>
          </ul>
        </li>
        <li>
          <input id="group-3" type="checkbox" hidden="">
          <label for="group-3"><p class="fa fa-angle-right"></p>실측 사이즈</label>
          <ul class="group-list">
            <li><a href="#"><p>...</p></a></li>
          </ul>
        </li>
      </ul>
    </nav>
  </div>
</div>

추가로 아래 본문 HTML도 실제 복붙 가능한 완성형으로 반드시 출력한다.

<div id="subsc">
  <h3>상품명</h3>
  <p>
    상품명 하단 구매 확신 스니펫 2줄<br><br>
    <strong style="font-weight:700 !important;">[쇼핑에 꼭 참고하세요]</strong><br>
    3줄 요약<br><br>
    <strong style="font-weight:700 !important;">[이 상품을 초이스한 이유입니다.]</strong><br>
    ...<br><br>
    <strong style="font-weight:700 !important;">[원단과 두께 체감에 대하여]</strong><br>
    ...<br><br>
    <strong style="font-weight:700 !important;">[체형과 핏, 사이즈 선택 가이드]</strong><br>
    ...<br><br>
    <strong style="font-weight:700 !important;">[이렇게 입는 날이 많아집니다]</strong><br>
    ...<br><br>
    <strong style="font-weight:700 !important;">[구매 전 꼭 확인해 주세요]</strong><br>
    ...<br><br>
    감성 마무리 문장
  </p>
</div>

3. 상품 기획(전체 컨셉)

3-0. 대표 이미지 & 3초훅
- 구성 : 대표이미지 + 큰 헤드라인 1~2줄 + 서브헤드라인 2~3줄
- 큰 헤드라인은 고객 페인포인트 기반, 뾰족한 상품 USP 기반, 감성적이고 훅이 강한 문구
- 서브헤드라인은 헤드라인을 구체적으로 받침하는 문구

3-1. 이런 분께 추천해요

3-2. 상품 핵심 어필 포인트 광고화 3~5가지(핵심특징, 착용효과)

3-3. 디테일 포인트

3-4. 원단 포인트

3-5. 디테일

4. 소재/착용감(특장점 리스팅형식으로)

5. 최하단 사이즈팁 작성

아래 4개 체형은 고정이며, 아이템에 맞게 문장만 바꾼다.

ㅇ55 (90) 160cm 48kg
ㅇ66 (95) 165cm 54kg
ㅇ66반 (95) 164cm 58kg
ㅇ77 (100) 163cm 61kg

[중요 삭제 규칙]
- 코디제안, 코디컷 가이드, 리뷰포인트, CTA는 절대 출력하지 않는다.

[중요 작성 규칙]
- 텍스트 입력을 기준으로 작성하고, 업로드된 이미지는 핏/실루엣/두께/분위기 판단의 보조 참고로만 활용한다.
- 출력물은 반드시 위 양식 그대로 작성한다.
- 항목 제목을 바꾸거나 순서를 바꾸지 않는다.
- HTML 블록은 실제 복사 사용 가능 수준으로 작성한다.
- 존칭체 유지
- 과장 금지
- 반품/취소 방지형 문장 구조 적용
"""

WRITING_RULES = """
[미샵 원고 프롬프트 핵심]
- 4050 여성 전문 쇼핑몰 미샵(MISHARP)의 톤앤매너를 유지한다.
- 목표는 감성 만족보다 반품/취소율 감소다.
- 두께, 무게감, 핏, 기장, 체감은 애매하게 쓰지 않는다.
- “정사이즈 / 여유핏 / 슬림핏”을 단독 사용하지 않고 어떤 체형에 왜 잘 맞는지 설명한다.
- 필요 시 비추천 체형/취향을 부드럽게 선택 기준으로 언급한다.
- TPO를 구체적으로 쓴다.
- 모든 수치는 체감 언어로 해석한다.
- 전체 본문은 장황하지 않게, 실무에서 바로 쓸 수 있게 정리한다.
- 줄바꿈은 HTML 본문에서 <br>, 문단 구분은 <br><br> 로 처리한다.
- 이미지가 있더라도 텍스트 입력과 충돌하면 텍스트 입력을 우선한다.
"""

def file_to_content_item(uploaded_file):
    mime = uploaded_file.type or mimetypes.guess_type(uploaded_file.name)[0] or "image/jpeg"
    data = uploaded_file.read()
    b64 = base64.b64encode(data).decode("utf-8")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{b64}"}
    }

def build_text_prompt(data: Dict[str, str]) -> str:
    return f"""
{OUTPUT_SCHEMA}

{WRITING_RULES}

[입력 데이터]
상품명: {data['product_name']}
컬러 옵션: {data['color_options']}
사이즈: {data['size_names']}
소재: {data['material']}
세탁방법: {data['washing']}
디테일 팁: {data['detail_tip']}
핏/실루엣: {data['fit']}
핵심 특징: {data['features']}
디테일 특징: {data['detail_features']}
소재/착용감 참고: {data['fabric_notes']}
사이즈 추천: {data['size_tip']}
길이 TIP: {data['length_tip']}
실측 사이즈: {data['size_detail']}
타겟 고객: {data['target']}
추가 참고사항: {data['extra_notes']}

[최종 지시]
- 위 입력 데이터를 우선해서 작성한다.
- 업로드 이미지가 있다면 핏, 실루엣, 원단 분위기 판단만 보조 참고한다.
- 출력 시작부터 끝까지 한 개의 텍스트 문서처럼 작성한다.
- "1. 기본 사양"부터 시작해서 "5. 최하단 사이즈팁 작성"으로 끝낸다.
"""

st.subheader("상품 정보 입력")
col1, col2 = st.columns(2)

with col1:
    product_name = st.text_input("상품명", placeholder="예: 레이 슬리밍 티셔츠")
    color_options = st.text_input("컬러 옵션", placeholder="예: 블랙, 아이보리, 베이지")
    size_names = st.text_input("사이즈", placeholder="예: Free / S, M, L / S(55)~XL(88)")
    material = st.text_input("소재", placeholder="예: 폴리에스테르 98%, 폴리우레탄 2%")
    washing = st.text_input("세탁방법", placeholder="예: 드라이크리닝 또는 손세탁 권장")
    detail_tip = st.text_input("디테일 팁", placeholder="예: 복부를 안정감 있게 감싸고 허리 들뜸을 줄여주는 설계")

with col2:
    fit = st.text_input("핏 / 실루엣", placeholder="예: 허리와 복부를 안정감 있게 잡아주는 세미슬림 핏")
    features = st.text_area("핵심 특징", height=120, placeholder="예: 복부 커버, 허리 들뜸 방지, 탄력 좋은 소재, 하체 라인 정돈")
    detail_features = st.text_area("디테일 특징", height=120, placeholder="예: 인밴딩, 꼬임 디테일, 절개선, 라글란 소매")
    fabric_notes = st.text_area("소재/착용감 참고", height=120, placeholder="예: 간절기~가을까지 입기 좋은 두께감, 맨살에 닿아도 부담 적은 촉감")
    target = st.text_input("타겟 고객", value="4050 여성")
    extra_notes = st.text_area("추가 참고사항", height=80, placeholder="예: 이미지 기준 허벅지 군살 부각 적음 / 160cm 이하 길이 참고 필요")

st.subheader("사이즈 정보 입력")
col3, col4 = st.columns(2)
with col3:
    size_tip = st.text_area("사이즈 TIP", height=120, placeholder="예: S(55)~XL(88)까지, 복부와 허리를 안정적으로 감싸는 핏입니다.")
    length_tip = st.text_area("길이 TIP", height=120, placeholder="예: 3가지 기장으로 체형과 키에 맞게 선택 가능하며 키가 작아도 수선 부담이 적습니다.")
with col4:
    size_detail = st.text_area("실측 사이즈", height=120, placeholder="예: 사이즈\t허리둘레\t엉덩이둘레\t허벅지둘레\t밑단둘레\t총장\t밑위길이 ...")

st.subheader("이미지 업로드 (보조 참고용)")
uploaded_images = st.file_uploader(
    "상품 이미지를 올려주세요. 텍스트 입력을 우선하고, 이미지는 핏/실루엣/분위기 판단 보조용으로만 참고합니다.",
    type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True,
)

if uploaded_images:
    preview_cols = st.columns(min(len(uploaded_images), 4))
    for i, img in enumerate(uploaded_images[:4]):
        with preview_cols[i]:
            st.image(img, use_container_width=True, caption=img.name)

with st.expander("현재 적용 중인 출력 구조 보기", expanded=False):
    st.text_area("출력 구조", OUTPUT_SCHEMA, height=500, disabled=True)

if st.button("상품 기획 생성하기", type="primary", use_container_width=True):
    if not product_name.strip():
        st.warning("상품명을 입력해 주세요.")
        st.stop()

    data = {
        "product_name": product_name,
        "color_options": color_options,
        "size_names": size_names,
        "material": material,
        "washing": washing,
        "detail_tip": detail_tip,
        "fit": fit,
        "features": features,
        "detail_features": detail_features,
        "fabric_notes": fabric_notes,
        "size_tip": size_tip,
        "length_tip": length_tip,
        "size_detail": size_detail,
        "target": target,
        "extra_notes": extra_notes,
    }

    text_prompt = build_text_prompt(data)

    user_content: List[Dict[str, Any]] = [{"type": "text", "text": text_prompt}]
    for img in uploaded_images[:5] if uploaded_images else []:
        user_content.append(file_to_content_item(img))

    with st.spinner("형준님 양식에 맞춰 기획서와 HTML 원고를 생성 중입니다..."):
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {
                    "role": "system",
                    "content": "당신은 미샵의 상세페이지 실무 문서를 만드는 전문가다. 형식을 무조건 지키고, 텍스트 입력 우선 원칙을 지켜라."
                },
                {
                    "role": "user",
                    "content": user_content
                }
            ],
            temperature=0.35,
        )
        result = response.choices[0].message.content

    st.success("생성이 완료되었습니다.")
    st.subheader("생성 결과")
    st.text_area("통합 결과 텍스트", result, height=1000)

    st.download_button(
        "TXT 한 파일로 다운로드",
        data=result,
        file_name=f"{product_name}_page_builder_output.txt",
        mime="text/plain",
        use_container_width=True,
    )

st.markdown("---")
st.markdown("© made by MISHARP, MIYAWA")
