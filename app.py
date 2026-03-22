import base64
import mimetypes
from typing import List, Dict, Any

import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="page-builder", layout="wide")

if "reset_nonce" not in st.session_state:
    st.session_state.reset_nonce = 0

st.title("PAGE BUILDER")
st.caption("미샵 상세페이지 기획 + 원고 생성기")

st.markdown("""
<style>
.block-container {padding-top: 1.8rem; padding-bottom: 2rem;}
textarea, input {font-size: 15px !important;}
.field-label {
    font-size: 0.95rem;
    font-weight: 600;
    margin-bottom: 0.2rem;
}
.field-label .hint {
    font-weight: 500;
    color: #666;
    font-size: 0.9rem;
    margin-left: 4px;
}
.tight-row {
    display:flex;
    align-items:end;
    gap:8px;
}
</style>
""", unsafe_allow_html=True)

api_key = st.secrets.get("OPENAI_API_KEY", "")
if not api_key:
    st.warning("OPENAI_API_KEY가 설정되지 않았습니다. Streamlit Cloud Secrets 또는 .streamlit/secrets.toml을 확인해 주세요.")
    st.stop()

client = OpenAI(api_key=api_key)

PRODUCT_COPY_PROMPT = """
🧩 프로젝트 목적
당신은 상세페이지 원고 전문 최고의 공감형 라이터입니다. 
4050 여성 전문 쇼핑몰 미샵(MISHARP)의 상품 상세페이지를
“구매 전 불안 제거 → 기대치 명확화 → 사이즈·핏 확신 제공”을
최우선 목표로 라이팅한다.

본 프로젝트의 1차 KPI는 감성 만족이 아니라
반품·취소율 감소이다.

ChatGPT는 상품 원문, 이미지, 스펙 정보가 주어졌을 때
미샵의 브랜드 톤앤매너를 유지하면서도
고객이 반품·취소를 고민하게 되는 지점을
상세페이지 문장 안에서 사전에 차단해야 한다.

🎯 프로젝트 목표
- 사이즈·핏 관련 반품 감소
- “생각보다 ○○했다” 유형의 변심 반품 감소
- 결제 후 배송 전 취소 감소
- 고객이 구매 전 ‘입는 장면’을 명확히 상상하도록 유도

🧠 라이팅 핵심 원칙 (절대 준수)
1. 기대치 명확화
   - 두께, 무게감, 핏, 기장, 체감은 애매하게 표현하지 않는다.
   - 반드시 비교 기준 또는 착용 기준을 함께 제시한다.

2. 사이즈 불안 제거
   - “정사이즈 / 여유핏 / 슬림핏”을 단독으로 사용하지 않는다.
   - 어떤 체형에, 어떤 이유로 잘 맞는지를 함께 설명한다.

3. 반품, 취소를 줄이기 위한 전략적 비추천 허용
   - 일부 체형·취향에 맞지 않는 경우를 솔직하게 언급하되
     부정이 아닌 ‘선택 기준’으로 표현한다.

4. TPO 고정
   - “언제 입지?”라는 고민이 남지 않도록
     활용 상황을 구체적으로 제시한다.

5. 스펙 나열 금지
   - 모든 수치는 ‘체감 언어’로 해석해서 설명한다.

6. 전체 글자 수 : 글자 700자를 넘지 않는다.

7. 체형별 핏 가이드: "복부 비만형 / 하체 튼실형 / 어깨가 좁은 체형" 다리 짧은 체형/상체튼실형 등 고민별로 이 옷이 왜 좋은지 설명합니다.

8. 고객이 할 만한 질문에 대한 답변이 되는 글 삽입

🪄 공통 작성 구조 규칙

① 상품명 하단 구매 확신 스니펫 (2줄)
- 감성 요약 + 실제 착용 가치
- 어떤 날, 어떤 상황에 적합한 옷인지 명확히 제시

중요! 설명글은 한줄에 30자 정도에서 <br> 처리
정확히 30자가 아니고, 읽을 때 문맥이 매끄럽도록 30자 정도선에서 <br>처리

중요! 작성된 상세설명글은 한꺼번에 통째로 복사해 사용할 수 있도록 해줄 것.

② 상단 30초 판단 요약 (3줄)
- 아래 항목 중 최소 3개 이상 반드시 포함
- 소제목 : [쇼핑에 꼭 참고하세요]
  · 핏 성향 (여유 / 정사이즈 / 슬림)
  · 체형 커버 핵심 포인트
  · 두께/보온/시원함/부드러움 등 체감 기준
  · 추천 4050 TPO
  · 특히 잘 맞는 체형 유형

③ 상세 본문 (반품·취소 방지형 5섹션)

[이 상품을 초이스한 이유입니다.]
- 고객의 일상 상황 공감으로 시작
- 왜 이 옷이 지금 필요한지 명확히 설명

[원단과 두께 체감에 대하여]
- 촉감 설명 + 실제 체감 두께
- 이너 기준(얇은 티 / 니트 / 맨투맨 가능 여부)
- 계절 체감 반드시 포함

[체형과 핏, 사이즈 선택 가이드]
- 잘 맞는 체형과 이유를 명확히 제시
- 필요 시 비추천 체형도 부드럽게 언급

[이렇게 입는 날이 많아집니다]
- 출근 / 모임 / 여행 / 일상 중
  최소 3가지 TPO 제시

[구매 전 꼭 확인해 주세요]
- 오해 가능 포인트를 사전에 안내
- 단점이 아닌 ‘선택 기준’ 형태로 제시

④ 감성 마무리 문장
- ‘자주 입게 되는 장면’을 떠올리게 마무리
- 선택에 대한 심리적 확신 제공

🧱 HTML 작성 규칙
- 전체는 아래 구조로 작성한다.

<div id="subsc">
  <h3>상품명</h3>
  <p>
    본문 내용
  </p>
</div>

- 상품명은 h3 태그 단독 사용
- 본문은 p 태그 내부 작성
- 소제목은 <strong style="font-weight:700 !important;"> 태그로 감싸고 대괄호 유지
- 줄바꿈은 <br>, 문단 구분은 <br><br> 사용
- HTML 외 마크다운, 특수기호 사용 금지

🧠 상품군 자동 미세 튜닝 적용 규칙
ChatGPT는 입력된 상품 정보를 기반으로
아래 상품군 중 하나를 자동 판별하고
해당 항목을 반드시 반영한다.

[아우터]
- 무게 체감, 이너 허용 범위, 활동성 필수 설명
- 어깨·팔·상체 커버 포인트 명확화
- 기장에 따른 체감 차이 언급

[티셔츠]
- 비침 여부, 단독/이너용 구분 필수
- 상복부·팔뚝 체감 설명
- 세탁 후 변형 가능성 기준 제시

[팬츠]
- 허리 타입, 착용 시 편안함 필수
- 하복부·힙·허벅지 커버 포인트 명확화
- 키 기준 기장 체감 포함

[니트]
- 두께 단계, 레이어드 가능 여부 필수
- 까슬거림·부해 보임 여부 명확화
- 적합 시즌 명시

[블라우스/셔츠]
- 구김·비침·레이어드 활용 설명
- 상체 볼륨·팔 라인 체감 명확화
- 출근·모임 활용 적합도 제시

[원피스/스커트]
- 허리선 위치, 하복부·힙 체감 필수
- 키에 따른 길이 체감 명확화
- 단독 착용 및 아우터 매칭 제안 포함

🖼️ 이미지 활용 기준 (반품 방지 목적)
- 정면 전신 컷: 기본 실루엣 판단용
- 옆/뒤 컷: 체형 커버 판단용
- 원단 확대 컷: 두께·촉감 기대치 고정용
- TPO 착용 컷: 변심 반품 방지용
- 사이즈 비교컷(55/66/77): 사이즈 불안 제거용

이미지는 감성용이 아니라
‘판단 기준 제공용’으로 활용한다.

🎨 문체 & 톤앤매너
- 존칭체 유지
- 과장·모호한 표현 금지
- “~한 편입니다 / ~느껴질 수 있습니다”는
  반드시 기준과 함께 사용

📌 최종 목표
이 상세페이지를 본 고객이
“받아보면 어떨까?”가 아니라
“이 정도면 나한테 맞겠다”라고
스스로 판단하게 만드는 것이다.
"""

OUTPUT_RULES = """
최종 출력은 반드시 아래 순서와 제목을 그대로 지켜 하나의 텍스트 문서로 작성합니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
기본사양
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

상품명 : 상품명 (컬러)
사이즈 :
소재 :
디테일 팁 :

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
원고 양식
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

여기에는 아래 순서로 HTML 두 덩어리만 출력합니다.
첫째, <div id="subsc"> ... </div>
둘째, <div id="Subtap"> ... </div>

중요한 순서 규칙
- 상품설명 HTML이 먼저 나온다.
- 그다음 소재정보 → 사이즈정보 → 실측사이즈 → 실측사이즈 재는방법 순서의 Subtap HTML이 나온다.
- 상품설명 HTML은 사용자가 제공한 상품설명 작성 프롬프트를 그대로 따른다.
- 출력 형식은 사용자가 제시한 HTML 양식 스타일에 맞춘다.

Subtap HTML 작성 규칙
- 아래와 같은 구조와 순서를 유지한다.
<div id="Subtap">
  <div id="header2" role="banner">
    <nav class="nav" role="navigation">
      <ul class="nav__list">
        <li>소재 정보</li>
        <li>사이즈 정보</li>
        <li>실측 사이즈</li>
        <li>실측사이즈 재는방법</li>
      </ul>
    </nav>
  </div>
</div>

- 소재 정보에는 <h3>소재 : ...</h3> 와 설명, 세탁방법을 넣는다.
- 사이즈 정보에는 사이즈 TIP, 길이 TIP을 넣는다.
- 실측 사이즈에는 입력된 실측 사이즈를 정리해 넣는다.
- 실측사이즈 재는방법 링크 항목도 포함한다.
- 가능하면 사용자가 예시로 준 마크업 스타일에 가깝게 작성한다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
상품 기획(전체 컨셉)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

3-0. 대표 이미지 & 3초훅
대표이미지: (상단 이미지 참고)
큰 헤드라인:
서브헤드라인:

3-1. 이런 분께 추천해요

3-2. 상품 핵심 어필 포인트 광고화 3~5가지(핵심특징, 착용효과)

3-3. 디테일 포인트

3-4. 원단 포인트

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
소재/착용감(특장점 리스팅형식으로)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
최하단 사이즈팁 작성
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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
- 1번, 3번, 4번, 5번은 일반 텍스트 문서 형식으로 출력합니다.
- 2번에서만 HTML을 출력합니다.
- HTML 외에는 코드펜스, 마크다운, 설명문을 넣지 않습니다.
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

최종 지시
- 위 입력 데이터를 기준으로 작성합니다.
- 섹션 제목은 반드시 아래위 긴 한 줄 구분선과 함께 출력합니다.
- 2. 원고 양식에서는 반드시 subsc HTML 먼저, Subtap HTML 나중 순서로 출력합니다.
- 상품설명 부분은 위 상품설명 작성 프롬프트를 그대로 적용합니다.
- 1번, 상품 기획, 소재/착용감, 최하단 사이즈팁은 일반 텍스트로 출력합니다.
- HTML 외에는 코드펜스, 마크다운, 불필요한 설명을 넣지 않습니다.
"""

st.subheader("상품정보 입력")
title_col1, title_col2, title_col3 = st.columns([2.2, 0.7, 7.1])

with title_col2:
    if st.button("초기화", use_container_width=True):
        st.session_state.reset_nonce += 1
        st.rerun()

nonce = st.session_state.reset_nonce

col1, col2 = st.columns(2)

with col1:
    product_name = st.text_input("상품명", placeholder="예: 소프트 웜톤 루즈핏 맨투맨", key=f"product_name_{nonce}")
    vendor_name = st.text_input("거래처 상품명", placeholder="예: 조이 오버핏 데님 자켓", key=f"vendor_name_{nonce}")
    color = st.text_input("컬러", placeholder="예: 베이지, 그레이, 블랙", key=f"color_{nonce}")
    size = st.text_input("사이즈", placeholder="예: FREE / S(55)~XL(88)", key=f"size_{nonce}")
    measurement = st.text_input("실측사이즈", placeholder="예: 가슴둘레146 / 어깨-소매79.5 / 소매단26.5 / 총길이78", key=f"measurement_{nonce}")
    material = st.text_input("소재", placeholder="예: 면80+나일론20", key=f"material_{nonce}")

    st.markdown('<div class="field-label">디테일 특징<span class="hint">(예:디자인, 절개라인, 부자재, 스펙상 특징 등)</span></div>', unsafe_allow_html=True)
    detail_tip = st.text_input("", placeholder="예: 가슴 절개라인이 더해진 와이드 오버핏", key=f"detail_tip_{nonce}", label_visibility="collapsed")

with col2:
    st.markdown('<div class="field-label">핏/실루엣 <span class="hint">(예:정핏,레귤러핏,오버핏 등/체형커버, 다리길어보이는 등의 특장점)</span></div>', unsafe_allow_html=True)
    fit = st.text_input("", placeholder="예: 상체 군살을 자연스럽게 커버하는 여유 있는 오버핏", key=f"fit_{nonce}", label_visibility="collapsed")

    st.markdown('<div class="field-label">주요 어필 포인트<span class="hint">(예:원단 구김, 체형커버, 계절성, 코디 활용도 등)</span></div>', unsafe_allow_html=True)
    appeal_points = st.text_area("", height=150, placeholder="예: 구김에 강함 / 체형 구애 없는 오버핏 / 절개 디테일 / 간절기 활용도", key=f"appeal_points_{nonce}", label_visibility="collapsed")

    target = st.text_input("타겟", value="4050 여성", placeholder="4050 여성", key=f"target_{nonce}")
    washing = st.text_input("세탁방법", value="드라이클리닝, 단독 울코스 손세탁 권장", placeholder="드라이클리닝, 단독 울코스 손세탁 권장", key=f"washing_{nonce}")

    st.markdown('<div class="field-label">기타<span class="hint">(가격 경쟁력, 가성비 등)</span></div>', unsafe_allow_html=True)
    etc = st.text_area("", height=130, placeholder="예: free사이즈 77까지 추천 / 162-167cm 모델핏 참고 / 가격 경쟁력 우수", key=f"etc_{nonce}", label_visibility="collapsed")

st.subheader("이미지 업로드 (텍스트 기반 + 이미지 보조)")
uploaded_images = st.file_uploader(
    "이미지는 보조 참고용입니다. 텍스트 입력을 우선하고, 이미지는 핏/실루엣/분위기 판단에만 참고합니다.",
    type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True,
    key=f"uploaded_images_{nonce}"
)

if uploaded_images:
    preview_cols = st.columns(min(len(uploaded_images), 4))
    for i, img in enumerate(uploaded_images[:4]):
        with preview_cols[i]:
            st.image(img, use_container_width=True, caption=img.name)

with st.expander("현재 적용 중인 출력 규칙 보기", expanded=False):
    st.text_area("출력 규칙", OUTPUT_RULES, height=560, disabled=True)

if st.button("생성하기", type="primary", use_container_width=True, key=f"generate_{nonce}"):
    if not product_name.strip():
        st.warning("상품명을 입력해 주세요.")
        st.stop()

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

    with st.spinner("수정 요청 반영 출력물을 생성 중입니다..."):
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {
                    "role": "system",
                    "content": "당신은 미샵의 실무 문서 출력기다. 사용자가 준 순서와 양식을 절대 바꾸지 말고, 2번에서는 subsc HTML을 먼저, Subtap HTML을 나중에 출력한다. 섹션 제목은 반드시 아래위 긴 한 줄 구분선으로 감싸서 출력한다. 상품설명 HTML은 사용자가 준 상품설명 프롬프트를 반드시 따른다."
                },
                {
                    "role": "user",
                    "content": user_content
                }
            ],
            temperature=0.2,
        )
        result = response.choices[0].message.content

    st.success("생성이 완료되었습니다.")
    st.text_area("결과", result, height=1100, key=f"result_{nonce}")

    st.download_button(
        "TXT 다운로드",
        data=result,
        file_name=f"{product_name}_page_builder.txt",
        mime="text/plain",
        use_container_width=True,
        key=f"download_{nonce}"
    )

st.markdown("---")
st.markdown("© made by MISHARP, MIYAWA")
