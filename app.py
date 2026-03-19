import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="page-builder", layout="wide")

st.title("PAGE BUILDER")
st.caption("미샵 전환형 상세페이지 기획 + HTML 원고 통합 생성기")

api_key = st.secrets.get("OPENAI_API_KEY", "")
if not api_key:
    st.warning("OPENAI_API_KEY가 설정되지 않았습니다. Streamlit Cloud의 Secrets 또는 .streamlit/secrets.toml을 확인해 주세요.")
    st.stop()

client = OpenAI(api_key=api_key)

DEFAULT_PROMPT = """
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

7. 체형별 핏 가이드: "복부 비만형 / 하체 튼실형 / 어깨가 좁은 체형 / 다리 짧은 체형 / 상체튼실형" 등 고민별로 이 옷이 왜 좋은지 설명한다.

8. 고객이 할 만한 질문에 대한 답변이 되는 글 삽입

🪄 공통 작성 구조 규칙
① 상품명 하단 구매 확신 스니펫 (2줄)
- 감성 요약 + 실제 착용 가치
- 어떤 날, 어떤 상황에 적합한 옷인지 명확히 제시
- 설명글은 한줄에 30자 정도에서 <br> 처리
- 정확히 30자가 아니고, 읽을 때 문맥이 매끄럽도록 30자 정도선에서 <br> 처리

② 상단 30초 판단 요약 (3줄)
- 소제목 : [쇼핑에 꼭 참고하세요]
- 아래 항목 중 최소 3개 이상 반드시 포함
  · 핏 성향 (여유 / 정사이즈 / 슬림)
  · 체형 커버 핵심 포인트
  · 두께·보온 체감 기준
  · 추천 TPO
  · 특히 잘 맞는 체형 유형

③ 상세 본문 (반품·취소 방지형 5섹션)
[이 상품을 초이스한 이유입니다.]
[원단과 두께 체감에 대하여]
[체형과 핏, 사이즈 선택 가이드]
[이렇게 입는 날이 많아집니다]
[구매 전 꼭 확인해 주세요]

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
입력된 상품 정보를 기반으로 아래 상품군 중 하나를 자동 판별하고 반드시 반영한다.

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
- “~한 편입니다 / ~느껴질 수 있습니다”는 반드시 기준과 함께 사용

📌 최종 목표
이 상세페이지를 본 고객이
“받아보면 어떨까?”가 아니라
“이 정도면 나한테 맞겠다”라고
스스로 판단하게 만드는 것이다.

[최종 출력 형식 - 반드시 아래 순서대로 한 개의 텍스트 문서로 출력]
1. 상품 포지셔닝
2. 섹션1 : 대표이미지 / 3초 훅
3. 섹션2 : 이런 분께 추천
4. 섹션3 : 핵심특징 광고화
5. 섹션4 : 착용 효과
6. 섹션5 : 소재 / 착용감
7. 섹션6 : 디테일
8. 섹션7 : 코디 제안
9. 섹션8 : 코디컷 가이드
10. 섹션9 : 리뷰 포인트
11. 섹션10 : CTA
12. 미샵 HTML 원고
13. 사이즈 정보 블록 HTML

[섹션 출력 규칙]
- 섹션1~10은 포토샵 디자인 작업자가 바로 배치할 수 있도록 짧고 명확한 문장 위주로 작성
- 섹션6 디테일은 입력된 디테일 특징을 기반으로 작성
- 섹션8 코디컷 가이드는 LOOK 01~03 형식으로 작성
- 섹션9 리뷰 포인트는 실제 고객 후기처럼 짧게 작성
- 섹션10 CTA는 구매 결정을 밀어주는 2문장으로 작성

[사이즈 정보 블록 HTML 작성 규칙]
- 아래 구조를 반드시 사용한다.
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

- 소재 정보에는 입력 소재와 세탁방법을 반영한다.
- 사이즈 정보에는 입력된 사이즈 추천, 길이 TIP을 반영한다.
- 실측 사이즈에는 입력된 실측값을 그대로 정리한다.
- HTML 외 설명 문장은 추가하지 않는다.

[중요]
- 최종 출력은 한 개의 텍스트 문서처럼 이어서 작성한다.
- HTML 원고와 사이즈 정보 블록 HTML은 실제 복사 사용 가능 수준으로 완성해서 출력한다.
"""

def generate_prompt(user_inputs: dict) -> str:
    return f"""{DEFAULT_PROMPT}

[입력 데이터]
상품명: {user_inputs['product_name']}
카테고리: {user_inputs['category']}
소재: {user_inputs['material']}
세탁방법: {user_inputs['washing']}
핏: {user_inputs['fit']}
핵심 특징: {user_inputs['features']}
디테일 특징: {user_inputs['detail_features']}
추천 코디: {user_inputs['coordi']}
타겟 고객: {user_inputs['target']}
대표 이미지 분위기: {user_inputs['mood']}
사이즈 추천: {user_inputs['size_tip']}
길이 TIP: {user_inputs['length_tip']}
실측 사이즈: {user_inputs['size_detail']}
추가 참고사항: {user_inputs['extra_notes']}
"""

st.subheader("상품 정보 입력")
col1, col2 = st.columns(2)

with col1:
    product_name = st.text_input("상품명")
    category = st.text_input("카테고리")
    material = st.text_input("소재")
    washing = st.text_input("세탁방법", value="드라이크리닝/손세탁 권장")
    fit = st.text_input("핏")
    target = st.text_input("타겟 고객", value="4050 여성")

with col2:
    features = st.text_area("핵심 특징", height=140, placeholder="예: 복부 커버, 허리 들뜸 방지, 탄력 좋은 원단")
    detail_features = st.text_area("디테일 특징", height=140, placeholder="예: 인밴딩, 꼬임 디테일, 라글란 소매")
    coordi = st.text_area("추천 코디", height=100, placeholder="예: 슬랙스 / 스커트 / 데님")
    mood = st.text_input("대표 이미지 분위기", value="단정, 우아, 슬림")
    extra_notes = st.text_area("추가 참고사항", height=100, placeholder="예: 비침 적음, 간절기용, 160cm 이하 길이 참고 필요")

st.subheader("사이즈 정보 입력")
col3, col4 = st.columns(2)
with col3:
    size_tip = st.text_area("사이즈 추천", height=120, placeholder="예: free사이즈로 77까지 추천드립니다.")
    length_tip = st.text_area("길이 TIP", height=120, placeholder="예: 162~167cm는 모델핏, 160cm 이하는 조금 더 길게 느껴질 수 있습니다.")
with col4:
    size_detail = st.text_area("실측 사이즈", height=120, placeholder="예: 어깨단면60 / 가슴둘레134 / 암홀둘레52 / 소매길이49.5 / 총길이67")

with st.expander("사용 중인 원고 프롬프트 보기", expanded=False):
    st.text_area("프롬프트", DEFAULT_PROMPT, height=500, disabled=True)

if st.button("상품 기획 생성하기", type="primary", use_container_width=True):
    if not product_name.strip():
        st.warning("상품명을 입력해 주세요.")
        st.stop()

    payload = {
        "product_name": product_name,
        "category": category,
        "material": material,
        "washing": washing,
        "fit": fit,
        "features": features,
        "detail_features": detail_features,
        "coordi": coordi,
        "target": target,
        "mood": mood,
        "size_tip": size_tip,
        "length_tip": length_tip,
        "size_detail": size_detail,
        "extra_notes": extra_notes,
    }

    prompt = generate_prompt(payload)

    with st.spinner("미샵 스타일 기획서와 HTML 원고를 생성 중입니다..."):
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": "당신은 4050 여성 패션 상세페이지 전환 최적화 전문가이며, 미샵의 톤앤매너를 지키는 실무형 카피라이터입니다."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
        )
        result = response.choices[0].message.content

    st.success("생성이 완료되었습니다.")
    st.subheader("생성 결과")
    st.text_area("통합 결과 텍스트", result, height=900)

    st.download_button(
        "TXT 한 파일로 다운로드",
        data=result,
        file_name=f"{product_name}_page_builder_output.txt",
        mime="text/plain",
        use_container_width=True,
    )
