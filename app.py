import base64
import io
import mimetypes
from typing import List, Dict, Any

import streamlit as st
from openai import OpenAI
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn

st.set_page_config(page_title="PAGE BUILDER", layout="wide")

if "reset_nonce" not in st.session_state:
    st.session_state.reset_nonce = 0

st.title("MISHARP 상품문구 생성기")
st.caption("미샵 상세페이지 기획 + 원고 생성기")

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

본 프로젝트의 1차 KPI는 감성 만족이 아니라 반품·취소율 감소이다.

🎯 프로젝트 목표
- 사이즈·핏 관련 반품 감소
- “생각보다 ○○했다” 유형의 변심 반품 감소
- 결제 후 배송 전 취소 감소
- 고객이 구매 전 ‘입는 장면’을 명확히 상상하도록 유도

🧠 라이팅 핵심 원칙
1. 두께, 무게감, 핏, 기장, 체감은 애매하게 쓰지 않는다.
2. 정사이즈 / 여유핏 / 슬림핏을 단독 사용하지 않고 어떤 체형에 왜 잘 맞는지 설명한다.
3. 필요 시 일부 체형·취향에 맞지 않는 경우를 선택 기준으로 부드럽게 안내한다.
4. 언제 입는지(TPO)를 구체적으로 쓴다.
5. 스펙은 체감 언어로 해석한다.
6. 전체 본문은 700자를 넘기지 않는다.
7. 텍스트 정보를 기준으로 쓰고, 업로드 이미지는 핏/실루엣/두께/분위기 판단의 보조 참고로만 활용한다.
8. 이미지와 텍스트가 충돌하면 텍스트 입력을 우선한다.

🪄 공통 작성 구조 규칙
① 상품명 하단  2줄
② 상단 30초 판단 요약 3줄
- 소제목 : [상품 포인트]

③ 상세 본문 5섹션
[이 상품을 초이스한 이유입니다.]
[원단과 두께 체감에 대하여]
[체형과 핏, 사이즈 선택 가이드]
[이렇게 입는 날이 많아집니다]
[구매 전 꼭 확인해 주세요]

④ 감성 마무리 문장

🧱 HTML 작성 규칙
- 상품설명은 반드시 <div id="subsc"> ... </div> 구조로 작성
- 소제목은 <strong style="font-weight:700 !important;"> 태그 사용
- 줄바꿈은 <br>, 문단 구분은 <br><br> 사용
- HTML 외 마크다운, 코드펜스 사용 금지
"""

OUTPUT_RULES = """
최종 출력은 반드시 아래 순서와 제목을 그대로 지켜 하나의 텍스트 문서로 작성합니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
기본사양
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

상품명 : 상품명 (컬러)
사이즈 :
소재 :
디테일 팁 :

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
원고 양식
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

여기에는 아래 순서로 HTML 두 덩어리만 출력합니다.
첫째, <div id="subsc"> ... </div>
둘째, <div id="Subtap"> ... </div>

중요한 순서 규칙
- 상품설명 HTML이 먼저 나온다.
- 그다음 소재정보 → 사이즈정보 → 실측사이즈 → 실측사이즈 재는방법 순서의 Subtap HTML이 나온다.
- 상품설명 HTML은 사용자가 제공한 상품설명 작성 프롬프트를 그대로 따른다.
- 출력 형식은 사용자가 제시한 HTML 양식 스타일에 맞춘다.

Subtap HTML 작성 규칙
- 소재 정보에는 <h3>소재 : ...</h3> 와 설명, 세탁방법을 넣는다.
- 사이즈 정보에는 사이즈 TIP, 길이 TIP을 넣는다.
- 실측 사이즈에는 입력된 실측 사이즈를 정리해 넣는다.
- 실측사이즈 재는방법 링크 항목도 포함한다.
- 사용 예시 스타일에 가깝게 작성한다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
포인트 코멘트
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

0. 동영상

(비워둠)

1. 헤드라인

2. (원단컷)
- 원단관련 내용 리스팅형식으로

3. (디테일컷)
- 디테일 관련 내용 리스팅형식으로

4. 이런 분께 추천해요
- 기존대로

5. (핵심 어필 포인트)
- 상품 usp 와 고객 니즈반영한 감성 문구 + 광고화 핵심 어필포인트 리스팅

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
하단 상세 원단컷 설명(나열식으로 변경)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 기존 대로 리스팅형

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사이즈 팁
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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
- 포인트 코멘트는 반드시 0,1,2,3,4,5 순서를 지킵니다.
- [쇼핑에 꼭 참고하세요] 대신 [상품 포인트]를 사용합니다.
- HTML 외에는 코드펜스, 마크다운, 불필요한 설명을 넣지 않습니다.
"""

def result_to_docx_bytes(result_text: str) -> bytes:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Malgun Gothic"
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
    style.font.size = Pt(10.5)

    for line in result_text.splitlines():
        p = doc.add_paragraph()
        run = p.add_run(line)
        run.font.name = "Malgun Gothic"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
        run.font.size = Pt(10.5)

    bio = io.BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio.getvalue()

# Header row
h1, h2, h3 = st.columns([2.2, 1.0, 8.8])
with h1:
    st.subheader("상품정보 입력")
with h2:
    st.write("")
    if st.button("초기화", use_container_width=True):
        st.session_state.reset_nonce += 1
        st.rerun()

nonce = st.session_state.reset_nonce

left, right = st.columns(2)

with left:
    product_name = st.text_input("상품명", placeholder="예: 소프트 웜톤 루즈핏 맨투맨", key=f"product_name_{nonce}")
    vendor_name = st.text_input("거래처 상품명", placeholder="예: 조이 오버핏 데님 자켓", key=f"vendor_name_{nonce}")
    color = st.text_input("컬러", placeholder="예: 베이지, 그레이, 블랙", key=f"color_{nonce}")
    size = st.text_input("사이즈", placeholder="예: FREE / S(55)~XL(88)", key=f"size_{nonce}")
    measurement = st.text_input("실측사이즈", placeholder="예: 가슴둘레146 / 어깨-소매79.5 / 소매단26.5 / 총길이78", key=f"measurement_{nonce}")
    material = st.text_input("소재", placeholder="예: 면80+나일론20", key=f"material_{nonce}")
    detail_tip = st.text_input(
        "디테일 특징 (예:디자인, 절개라인, 부자재, 스펙상 특징 등)",
        placeholder="예: 가슴 절개라인이 더해진 와이드 오버핏",
        key=f"detail_tip_{nonce}"
    )

with right:
    fit = st.text_input(
        "핏/실루엣 (예:정핏,레귤러핏,오버핏 등/체형커버, 다리길어보이는 등의 특장점)",
        placeholder="예: 상체 군살을 자연스럽게 커버하는 여유 있는 오버핏",
        key=f"fit_{nonce}"
    )
    appeal_points = st.text_area(
        "주요 어필 포인트 (예:원단 구김, 체형커버, 계절성, 코디 활용도 등)",
        height=150,
        placeholder="예: 구김에 강함 / 체형 구애 없는 오버핏 / 절개 디테일 / 간절기 활용도",
        key=f"appeal_points_{nonce}"
    )
    target = st.text_input("타겟", value="4050 여성", placeholder="4050 여성", key=f"target_{nonce}")
    washing = st.text_input("세탁방법", value="드라이클리닝, 단독 울코스 손세탁 권장", placeholder="드라이클리닝, 단독 울코스 손세탁 권장", key=f"washing_{nonce}")
    etc = st.text_area(
        "기타 (가격 경쟁력, 가성비 등)",
        height=130,
        placeholder="예: free사이즈 77까지 추천 / 162-167cm 모델핏 참고 / 가격 경쟁력 우수",
        key=f"etc_{nonce}"
    )

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
    st.text_area("출력 규칙", OUTPUT_RULES, height=480, disabled=True)

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

    with st.spinner("출력물을 생성 중입니다..."):
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {
                    "role": "system",
                    "content": "당신은 미샵의 실무 문서 출력기다. 사용자가 준 순서와 양식을 절대 바꾸지 말고, 2번에서는 subsc HTML을 먼저, Subtap HTML을 나중에 출력한다. 섹션 제목은 반드시 아래위 긴 한 줄 구분선으로 감싸서 출력한다. 포인트 코멘트는 0,1,2,3,4,5 순서를 지킨다. [상품 포인트] 제목을 사용한다."
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

    docx_bytes = result_to_docx_bytes(result)

    d1, d2 = st.columns(2)
    with d1:
        st.download_button(
            "TXT 다운로드",
            data=result,
            file_name=f"{product_name}_page_builder.txt",
            mime="text/plain",
            use_container_width=True,
            key=f"download_txt_{nonce}"
        )
    with d2:
        st.download_button(
            "한글 호환 DOCX 다운로드",
            data=docx_bytes,
            file_name=f"{product_name}_page_builder.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
            key=f"download_docx_{nonce}"
        )

st.markdown("---")
st.markdown("© made by MISHARP, MIYAWA")
