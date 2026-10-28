import base64
import io
import json
import mimetypes
import re
import time
from typing import Any, Dict, List

import streamlit as st
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from openai import OpenAI, RateLimitError

# V5 startup compatibility: keep the editorial engine in this script so a stale
# quality_engine.py left on Streamlit Cloud cannot prevent the app from starting.
# The separate quality_engine.py is retained for offline tests and maintenance.
# Both copies originate from the same V5 module in this release.
# === EMBEDDED QUALITY ENGINE BEGIN ===
"""상품별 원고 검증·편집 모듈. Streamlit/외부 API 호출 없음."""
import re
from typing import Any, Dict, List

MD_KEYS = ("choice", "fabric", "fit", "occasion")
TIP_KEYS = ("55", "66", "66half", "77")
TIP_PROFILES = {"55": "55(90), 160cm 50kg", "66": "66(95), 162cm 55kg", "66half": "66반(95), 163cm 59kg", "77": "77(100), 161cm 62kg"}

# 의미 없는 조사·범용 어휘보다는 원단/구조/핏 등의 구체적 어휘를 먼저 확인한다.
STOPWORDS = {"그리고", "하지만", "때문에", "제품", "상품", "여성", "정도", "스타일", "예쁘게", "다양한", "편안하게", "느낌", "입을", "만들어", "있도록", "데일리", "좋은", "좋아", "필요한", "활용", "추천", "가능", "예시", "입력", "없음", "바로", "매우", "정말", "외출", "일상", "단정하게", "구체적으로"}
DANGEROUS_REVIEW_PATTERNS = ("직접 입어보니", "실제로 입어보니", "모델이 직접", "직원이 직접", "스텝이 착용해보니")
GENERIC_SNIPPETS = (
    "다양한 하의와", "다양한 스타일링", "활용도가 높", "누구나 편안", "어떤 체형", "다양한 상황에", "활용할 수 있습니다",
)


def compact(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def split_facts(value: Any, maximum: int = 5) -> List[str]:
    """입력의 개별 포인트를 모아 원고에 반영해야 할 근거 목록을 만든다."""
    value = str(value or "")
    parts = re.split(r"[\n;；•▪]+|\s*/\s*|(?<=[가-힣])\s*,\s*", value)
    facts = []
    for part in parts:
        part = re.sub(r"^[-*\d.)\s]+", "", part).strip(" .，")
        if len(part) >= 2 and part not in facts and part not in ("없음", "입력 없음"):
            facts.append(part[:160])
    return facts[:maximum]


def input_facts(data: Dict[str, Any], additional_request: str = "") -> Dict[str, List[str]]:
    fields = {
        "소재·촉감": [data.get("material", ""), data.get("material_desc_raw", "")],
        "디테일": [data.get("detail_tip", "")],
        "핏·체형": [data.get("fit", "")],
        "구매 포인트": [data.get("appeal_points", ""), data.get("etc", "")],
        "사이즈·컬러": [data.get("size", ""), data.get("color", "")],
        "세탁·주의": [data.get("washing", "")],
        "사진에서 확인된 외관": data.get("visual_details", []),
    }
    result = {}
    for label, blocks in fields.items():
        vals = []
        for b in blocks:
            for fact in (list(b) if isinstance(b,list) else split_facts(b, 8)):
                if fact not in vals:
                    vals.append(fact)
        if vals:
            result[label] = vals[:7]
    # 이미지에서만 보이는 항목은 반드시 이미지에서 확인 가능한 경우에만 반영해야 한다.
    if compact(additional_request):
        result["추가 요청"] = split_facts(additional_request, 6)
    return result


def fact_report(data: Dict[str, Any], additional_request: str = "") -> str:
    facts = input_facts(data, additional_request)
    return "\n".join("- " + name + ": " + " / ".join(values) for name, values in facts.items())


def meaningful_terms(text: str) -> List[str]:
    text = compact(text)
    terms = re.findall(r"[A-Za-z][A-Za-z0-9+%-]{2,}|\d+(?:\.\d+)?(?:cm|kg|%|호)|[가-힣]{2,}", text)
    result = []
    for tok in terms:
        if tok in STOPWORDS or tok.isdigit():
            continue
        # 활용형 조사 일부 제거. 실제 원고에서 동의어로 다르게 표현하는 건 재작성 단계가 판단한다.
        tok = re.sub(r"(으로|에서|에게|까지|에도|보다|마다|하고|이며|인데|있는|없는|하기|하며|하고|되어|하여)$", "", tok)
        if len(tok) >= 2 and tok not in result:
            result.append(tok)
    return result


def content_string(draft: Dict[str, Any]) -> str:
    # 입력을 베껴 넣을 수 있는 소재/사이즈 데이터는 제외하고 AI 작성 블록만 검사한다.
    chunks = []
    for key in ("recommend_lines", "review_lines"):
        chunks.extend(x for x in draft.get(key, []) if isinstance(x, str))
    for f in draft.get("faqs", []):
        if isinstance(f, dict):
            chunks.extend([str(f.get("q", "")), str(f.get("a", ""))])
    md = draft.get("md_sections", {})
    if isinstance(md, dict):
        for key in MD_KEYS:
            chunks.extend(x for x in md.get(key, []) if isinstance(x, str))
    return " ".join(chunks)


def check_structure(draft: Any) -> List[str]:
    if not isinstance(draft, dict):
        return ["JSON 객체 형식이 아닙니다."]
    problems = []
    for field, minimum in (("material_desc_lines", 3), ("recommend_lines", 4), ("review_lines", 4)):
        val = draft.get(field)
        if not isinstance(val, list) or len([x for x in val if compact(x)]) < minimum:
            problems.append(f"{field}: 내용 {minimum}개가 필요합니다.")
    rec = draft.get("recommend_lines", [])
    if isinstance(rec, list):
        for i, line in enumerate(rec[:4], 1):
            s = compact(line).rstrip(".。 ")
            if not s.endswith("분") or re.search(r"추천합니다|추천드립니다|권해드립니다|적합합니다|잘 어울립니다|분께|분에게|입니다\s*분", s):
                problems.append(f"추천 {i}번: '~분'으로 자연스럽게 끝나야 합니다.")
    faq = draft.get("faqs")
    if not isinstance(faq, list) or len([f for f in faq if isinstance(f, dict) and compact(f.get("q")) and compact(f.get("a"))]) < 4:
        problems.append("faqs: 실질적인 질문과 답변이 4개 필요합니다.")
    md = draft.get("md_sections")
    if not isinstance(md, dict):
        problems.append("md_sections: 4개 원고 영역이 필요합니다.")
    else:
        for field in MD_KEYS:
            lines = md.get(field)
            # 출력 가능 여부와 문장 풍부함은 별도 판단한다. 사진만으로 확인되거나
            # 디테일/핏 입력이 적은 상품에 115자 하한을 강제하면 허위 설명을 유도한다.
            if not isinstance(lines, list) or not any(compact(x) for x in lines):
                problems.append(f"md_sections.{field}: 본문이 비어 있습니다.")
    tips = draft.get("size_tips")
    if not isinstance(tips, dict):
        problems.append("size_tips: 4개 체형 프로필이 필요합니다.")
    else:
        for field in TIP_KEYS:
            x = tips.get(field)
            if not isinstance(x, list) or len([s for s in x if compact(s)]) < 2:
                problems.append(f"size_tips.{field}: 2개 문장이 필요합니다.")
    return problems


def check_quality(draft: Dict[str, Any], data: Dict[str, Any], additional_request: str = "") -> List[str]:
    issues = check_structure(draft)
    if not isinstance(draft, dict):
        return issues
    content = content_string(draft)
    # '더 자세히 쓰면 좋은가?'는 보완 권고만 하고 다운로드를 막지 않는다.
    # 분량만 늘리기 위해 입력되지 않은 특징을 만들어내는 일을 방지한다.
    md = draft.get("md_sections")
    if isinstance(md, dict):
        for field in MD_KEYS:
            lines = md.get(field)
            if isinstance(lines, list):
                valid = [compact(x) for x in lines if compact(x)]
                if valid and len(valid) < 2:
                    issues.append(f"md_sections.{field}: 설명을 더 보완하면 좋습니다.")
    # 누락된 사실만 잡기 위한 보수적인 신호: 3글자 이상 핵심 토큰을 하나도 사용하지 않은 입력 묶음
    facts = input_facts(data, additional_request)
    for group in ("디테일", "핏·체형", "구매 포인트", "소재·촉감", "사진에서 확인된 외관"):
        if group not in facts:
            continue
        terms = []
        for fact in facts[group]:
            for tok in meaningful_terms(fact):
                if len(tok) >= 3 and tok not in terms:
                    terms.append(tok)
        # 숫자도 포함하지만 흔한 단어만 주어진 경우 강제하지 않는다.
        if terms and not any(tok in content for tok in terms):
            issues.append(f"{group}: 입력한 핵심 정보가 생성 원고에서 확인되지 않습니다. 입력: {' / '.join(facts[group][:3])}")
    for term in DANGEROUS_REVIEW_PATTERNS:
        if term in " ".join(draft.get("review_lines", [])) and "실제착용" not in compact(additional_request):
            issues.append("실제 착용 근거 없이 직원·모델이 입어본 것처럼 단정했습니다.")
            break
    # 입력의 근거 없이 사양을 확정하거나, 서로 다른 체형에 동일한 설명을 반복하지 않는다.
    input_context = " ".join(str(v) for v in data.values()) + " " + compact(additional_request)
    for unsupported in ("방수", "항균", "자체 제작", "자체제작", "절대 비치지", "비침이 전혀 없", "건조기 사용 가능"):
        if unsupported in content and unsupported not in input_context:
            issues.append(f"입력 근거 없이 '{unsupported}'이라는 표현이 사용됐습니다.")
    tips = draft.get("size_tips", {})
    if isinstance(tips, dict) and all(isinstance(tips.get(k), list) for k in TIP_KEYS):
        signatures = [" ".join(compact(x) for x in tips[k]) for k in TIP_KEYS]
        if len(set(signatures)) <= 2:
            issues.append("55/66/66반/77 사이즈팁이 동일하거나 과도하게 반복됩니다. 체형별 차이를 반영하세요.")
    md = draft.get("md_sections") or {}
    md_text = " ".join(" ".join(md.get(k, [])) for k in MD_KEYS if isinstance(md.get(k), list))
    if any(md_text.count(fragment) > 2 for fragment in GENERIC_SNIPPETS):
        issues.append("MD원고에 범용 문구가 반복됩니다. 상품 고유 근거를 더 사용하세요.")
    return list(dict.fromkeys(issues))


def normalize_recommend(s: str) -> str:
    s = re.sub(r"^\s*[▪•-]\s*", "", compact(s)).rstrip(".。 ")
    if not s.endswith("분"):
        raise ValueError("추천 문장의 형식이 틀립니다: " + s)
    return s


def normalize_generated_strict(result: Dict[str, Any]) -> Dict[str, Any]:
    """범용 폴백을 끼워 넣지 않는다. 유효하지 않으면 재생성 요청."""
    issues = check_structure(result)
    if issues:
        raise ValueError("\n".join(issues))
    def clean_list(xs, n):
        return [compact(x).strip('"“”') for x in xs[:n]]
    faqs = []
    for f in result["faqs"][:4]:
        q = re.sub(r"^(?:Q\.\s*)+", "", compact(f["q"]), flags=re.I)
        a = re.sub(r"^(?:A\.\s*)+", "", compact(f["a"]), flags=re.I)
        faqs.append({"q": "Q. " + q, "a": "A. " + a})
    md = {k: [compact(x) for x in result["md_sections"][k] if compact(x)] for k in MD_KEYS}
    md["purchase_note"] = []
    md["ending"] = []
    size_tips = {k: clean_list(result["size_tips"][k], 2) for k in TIP_KEYS}
    return {
        "material_desc_lines": clean_list(result["material_desc_lines"], 3),
        "recommend_lines": [normalize_recommend(x) for x in result["recommend_lines"][:4]],
        "review_lines": [compact(x).strip('"“”') for x in result["review_lines"][:4]],
        "faqs": faqs,
        "md_sections": md,
        "size_tips": size_tips,
    }


def natural_wrap(text: str, max_chars: int = 24) -> List[str]:
    """원고 내용을 삭제하지 않고 공백 위치에서만 끊는다. HTML 문법은 건드리지 않는다."""
    lines = []
    for paragraph in str(text or "").split("\n"):
        words = paragraph.split()
        current = ""
        for word in words:
            new = word if not current else current + " " + word
            if current and len(new) > max_chars:
                lines.append(current)
                current = word
            else:
                current = new
        if current:
            lines.append(current)
    return lines


# ── Editorial QA: the previous release checked length and broad term presence,
# but missed factual-color mismatches, repetitive FAQ, unfounded testimonials and
# exaggerated material claims observed in real MISHARP outputs.
KNOWN_COLORS = (
    "아이보리", "오프화이트", "화이트", "블랙", "차콜", "베이지", "네이비", "그레이",
    "카키", "브라운", "크림", "핑크", "블루", "레드", "퍼플", "민트", "그린",
    "버건디", "와인", "옐로우", "오트밀", "연그레이", "진그레이", "멜란지", "코랄",
)
BASIC_FAQ_PATTERNS = (
    r"^(?:소재|원단)(?:가|는|는요|는 무엇인가요|는 어떤가요|가 뭔가요)",
    r"^사이즈(?:가|는|는요|가 어떻게 되나요|는 어떻게 되나요)",
    r"^컬러(?:가|는|옵션|는요)",
    r"^색상(?:이|은|종류)",
    r"^(?:어떤|무슨) 소재",
)


def editorial_issues(draft: Dict[str, Any], data: Dict[str, Any], additional_request: str = "") -> List[str]:
    """Warnings intended for a targeted LLM revision, not a hard download gate."""
    if not isinstance(draft, dict):
        return ["원고 JSON이 아닙니다."]
    issues = []
    content = content_string(draft)
    # Colors that appear in generated claims must be present in entered color
    # or product name. Do not compare against background examples in prompts.
    allowed = compact(data.get('color', '')) + ' ' + compact(data.get('display_name', ''))
    unsupported_colors = sorted({c for c in KNOWN_COLORS if c in content and c not in allowed
                                 and not any(c in other for other in KNOWN_COLORS if other in allowed)})
    if unsupported_colors:
        issues.append('입력되지 않은 상품 색상 언급: ' + ', '.join(unsupported_colors))

    full_input = ' '.join(compact(v) for v in data.values()) + ' ' + compact(additional_request)
    if re.search(r"털\s*빠짐(?:이)?\s*거의\s*없|털\s*빠짐(?:이)?\s*적", full_input):
        if re.search(r"털\s*빠짐\s*(?:이\s*)?(?:전혀\s*)?없는|털\s*빠짐\s*제로|털\s*빠짐\s*없습니다", content):
            issues.append("'털 빠짐이 거의 없음'을 '털 빠짐 전혀 없음'으로 과장했습니다.")
    if '폴리에스터' in full_input and re.search(r"(?:양털|울)(?:\s*100%|\s*소재|\s*특유의)", content):
        # '양털 같은 질감'은 허용하지만 폴리에스터를 실제 양털로 오인시키는 표현은 금지.
        if not re.search(r"(?:양털|울)\s*(?:같|처럼|을\s*닮|을\s*연상)", content):
            issues.append('합성섬유를 실제 양털/울 소재처럼 오인시키는 표현이 있습니다.')
    review = draft.get('review_lines', [])
    if isinstance(review,list):
        reviewtext=' '.join(map(compact, review))
        if re.search(r"(?:입어\s*보니|입었더니|만져\s*보니|저는\s*|제가\s*|착용했는데|입고\s*나가니)", reviewtext) and not re.search(r"실제\s*(?:착용|후기)|모델\s*피드백", full_input):
            issues.append('실제 후기 근거 없이 1인칭 착용 경험을 꾸몄습니다.')

    faqs=draft.get('faqs',[])
    if isinstance(faqs,list):
        basic = 0
        questions=[]
        for faq in faqs[:4]:
            if not isinstance(faq,dict): continue
            q = re.sub(r"^Q\.\s*",'',compact(faq.get('q','')),flags=re.I)
            questions.append(q)
            if any(re.search(pat,q) for pat in BASIC_FAQ_PATTERNS): basic += 1
        if basic >= 2:
            issues.append('FAQ가 기본정보 재진술에 치우쳤습니다. 실제 구매 망설임을 다루세요.')
        if len(set(questions)) < len(questions):
            issues.append('FAQ 질문이 중복됩니다.')

    md=draft.get('md_sections',{})
    if isinstance(md,dict):
        sections={key:' '.join(map(compact,md.get(key,[]))) if isinstance(md.get(key),list) else '' for key in MD_KEYS}
        choice=sections['choice']
        # Don't repeat composition, sizes and colors as the main selling point.
        material=compact(data.get('material',''))
        if (choice.count('사이즈') + choice.count('컬러') + choice.count('폴리에스터') >= 3
                and not any(x in choice for x in ('걱정', '고민', '찾으', '불편', '마음', '포인트', '선택', '좋은 이유'))):
            issues.append('선택 이유가 상품 기본정보 나열에 치우쳤습니다. 고객 고민과 구매 가치를 연결하세요.')
        # Repetition across MD section roles: exact product phrases rather than common connectors.
        for feature in ('털 빠짐', '폴리에스터 100', 'FREE 사이즈', '가슴둘레 116', '베이지와 차콜', '편안한 착용감'):
            if sum(feature in s for s in sections.values()) >= 3:
                issues.append(f"MD원고 영역 사이에 '{feature}' 설명이 반복됩니다.")
        measure=' '.join(str(x) for x in data.get('measurement_lines', []))
        # A jacket with a stated 58cm total length should not be described as hip-covering.
        if re.search(r'(?:총길이|총장)\s*[:=]?\s*(?:5[0-9])(?:\D|$)',measure) and '힙을 덮' in content:
            issues.append('입력된 짧은 총장만으로 힙을 덮는다고 단정했습니다.')

    tips=draft.get('size_tips',{})
    if isinstance(tips,dict):
        tiptext=' '.join(str(v) for v in tips.values())
        if any(x in tiptext for x in ('드라마틱한', '무조건', '누구나', '완벽한 체형', '활동성이 좋습니다')):
            issues.append('실제 착용 근거 없는 사이즈팁의 과장·확정 표현이 있습니다.')
    # 검증용 실제 자켓 출력물에서 관찰된 취약점: 선택 이유가 상품명/스펙으로 시작하고
    # 핵심 고민을 다루지 않는 문제. '구매 고민' 문구 자체를 억지로 추가시키지는 않는다.
    if isinstance(md, dict):
        choice = sections.get('choice', '')
        if choice:
            product_name = compact(data.get('display_name', ''))
            starts_with_catalogue = bool(product_name and choice.startswith(product_name))
            solves_worry = bool(re.search(r'걱정|고민|찾으|망설|불편|부담|신경\s*쓰|원하', choice))
            if starts_with_catalogue and not solves_worry:
                issues.append('선택 이유가 상품명으로 시작하는 스펙 나열입니다. 고객 고민과 확인된 해결 가치를 연결하세요.')
            if ('폴리에스터' in choice and ('사이즈' in choice or '컬러' in choice)) and not solves_worry:
                issues.append('선택 이유에 소재·사이즈·컬러를 한꺼번에 나열했습니다. 구매 가치부터 제시하세요.')
            # 비슷한 소재 사실을 두 영역에서 장황하게 반복하는 경우
            fabric = sections.get('fabric','')
            matching_features = ('털 빠짐', '폴리에스터', '포근한 질감', '부드러운 촉감')
            repeated = [x for x in matching_features if x in choice and x in fabric]
            if len(repeated) >= 2:
                issues.append('선택 이유와 소재 설명이 같은 특징을 반복합니다. 선택 이유는 고객 편익, 소재는 근거 중심으로 분리하세요.')
        fit_text = sections.get('fit','')
        measurements = ' '.join(str(v) for v in data.get('measurement_lines', []))
        chest = re.search(r'(?:가슴\s*둘레)\s*[:=]?\s*(\d{2,3})', measurements)
        if chest and re.search(r'자켓|점퍼|코트|블라우스|셔츠', compact(data.get('display_name', ''))):
            if ('여유' in fit_text or '체형' in fit_text or '품' in fit_text) and not re.search(r'가슴\s*둘레\s*[:=]?\s*' + chest.group(1), fit_text):
                issues.append(f'상체 품을 설명하면서 핵심 가슴둘레 {chest.group(1)}cm 실측이 빠졌습니다. 핏 설명에 검토하세요.')

    # 입력에 없는 착용·기능 효과가 재작성 원고에서 확정되지 않도록 본문과 사이즈팁 전체 검사.
    input_fit = compact(data.get('fit','')) + ' ' + compact(data.get('detail_tip',''))
    tips = draft.get('size_tips', {})
    tip_text = ' '.join(' '.join(str(x) for x in v) for v in tips.values() if isinstance(v,list)) if isinstance(tips,dict) else ''
    prose = content + ' ' + tip_text
    if re.search(r'힙(?:을|까지|라인)?\s*(?:살짝\s*)?덮(?:는|어주는|어줍니다|습니다)', prose) and not re.search(r'힙(?:을|까지|라인)?\s*(?:살짝\s*)?덮', input_fit):
        issues.append('실측 총장만으로 힙을 덮는다고 단정했습니다. 실제 핏 근거가 없으면 삭제하세요.')
    if re.search(r'보온성(?:이)?\s*(?:뛰어나|뛰어난|우수|탁월)', prose) and not re.search(r'보온성(?:이)?\s*(?:뛰어나|뛰어난|우수|탁월)', ' '.join(compact(v) for v in data.values())):
        issues.append('입력 근거 없이 보온성이 뛰어나다고 단정했습니다.')
    if re.search(r'이너.{0,14}(?:불편함이 없|답답하지 않|충분히 들어가|여유롭게 입)', tip_text) and not re.search(r'이너|레이어드|겹쳐\s*입', input_fit):
        issues.append('실제 레이어드 착용 근거 없이 이너 착용 여유를 보장하는 사이즈팁입니다.')
    if re.search(r'(?:총장|총길이)\s*\d{2,3}\s*cm.{0,10}적당', prose):
        issues.append('총장 숫자만으로 길이가 적당하다고 확정했습니다. 평소 옷 실측과 비교하도록 안내하세요.')

    # '착용 전 체크 포인트'가 실제 체크 방법 없이 단순 상품 스펙만 재진술하는 경우.
    review = draft.get('review_lines',[])
    if isinstance(review,list) and review:
        actions = sum(bool(re.search(r'확인|비교|살펴|체크|참고|고르|선택|보세요|따져|느껴질', compact(x))) for x in review)
        if actions < 2:
            issues.append('착용 전 체크 포인트가 스펙 재진술에 그칩니다. 고객이 실제 확인할 방법을 2개 이상 안내하세요.')

    # FAQ에서 질문에 직접 답하지 않고 '실측 참고'로 회피하는 사례.
    faqs=draft.get('faqs',[])
    if isinstance(faqs,list):
        for f in faqs[:4]:
            if not isinstance(f,dict):
                continue
            q=compact(f.get('q','')); ans=compact(f.get('a',''))
            if re.search(r'부해\s*보|날씬해\s*보|뚱뚱해\s*보',q):
                # 핵심 우려에 대한 조건부 설명 없이 막연한 '다양한 체형/실측 참고'만 답하는 경우
                if re.search(r'실측\s*사이즈를?\s*참고.{0,15}다양한\s*체형에\s*적합',ans) or (re.search(r'실측\s*사이즈를?\s*참고|다양한\s*체형에\s*적합',ans) and not re.search(r'볼륨|부피|핏|실루엣|체형\s*차이|착용\s*위치',ans)):
                    issues.append('부해 보이는지에 관한 FAQ 답변이 모호합니다. 확인된 원단 볼륨과 체형별 개인차를 구분해 직접 답하세요.')
            if len(ans) < 27:
                issues.append('FAQ 답변이 지나치게 짧습니다. 질문에 직접 답하고 상품 근거 또는 확인할 조건을 추가하세요.')
                break

    # New real-output regressions: unsupported 'not hip covering', overclaim of shedding,
    # and country handling are warnings rather than a blocking download gate.
    if re.search(r'힙을\s*(?:살짝\s*)?덮지\s*않는', prose) and not re.search(r'힙.{0,7}(?:덮|가리|커버)', input_fit):
        issues.append('총장 수치만으로 힙을 덮지 않는다고 단정했습니다.')
    if re.search(r'(?:총장|총길이)\s*\d{2,3}\s*cm\s*로\s*다양한\s*체형', prose):
        issues.append('총장 수치만으로 다양한 체형에 잘 맞는다고 단정했습니다.')
    if re.search(r'털\s*빠짐\s*걱정\s*없는', content) and re.search(r'털\s*빠짐.{0,8}거의\s*없', full_input):
        issues.append('털 빠짐이 거의 없음을 걱정 없는 것으로 과장했습니다.')
    if not compact(data.get('country','')):
        issues.append('제조국 입력값이 비어 있습니다. 제품 라벨에서 확인해 입력해야 합니다.')
    if not data.get('visual_details') and ('립니트' in compact(data.get('display_name','')) and '립니트' not in content):
        issues.append('상품명에 있는 립니트의 구체적인 위치·형태가 확인되지 않았습니다. 사진이나 상세 입력에서 확인해 주세요.')
    # Prevent altered measurement numbers, a source of preventable returns.
    issues.extend(numeric_measurement_issues(draft, data))
    return list(dict.fromkeys(issues))


def score_editorial(draft: Dict[str, Any], data: Dict[str, Any], additional_request: str = "") -> tuple:
    """Prioritize actual product accuracy and useful FAQ over raw paragraph length."""
    structural=check_structure(draft)
    content=content_string(draft) if isinstance(draft,dict) else ''
    # Keep automatic selection conservative; a revision should improve real issues.
    major=editorial_issues(draft, data, additional_request)
    coverage=check_quality(draft,data,additional_request)
    return (len(structural),len(major),len(coverage),-len(set(meaningful_terms(content))))


def soften_unverified_claims(draft: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """Only safe, deterministic softening; never invent a new product feature."""
    import copy
    out=copy.deepcopy(draft)
    input_text=' '.join(compact(v) for v in data.values())
    if not re.search(r"털\s*빠짐(?:이)?\s*(?:거의\s*없|적)",input_text):
        return out
    def soften(s):
        s=re.sub(r"털\s*빠짐\s*(?:이\s*)?(?:전혀\s*)?없는",'털 빠짐이 거의 없는',s)
        s=re.sub(r"털\s*빠짐\s*(?:이\s*)?없습니다",'털 빠짐이 거의 없습니다',s)
        return s
    for key in ('recommend_lines','review_lines','material_desc_lines'):
        if isinstance(out.get(key),list):
            out[key]=[soften(s) if isinstance(s,str) else s for s in out[key]]
    if isinstance(out.get('faqs'),list):
        for f in out['faqs']:
            if isinstance(f,dict):
                for k in ('q','a'):
                    if isinstance(f.get(k),str): f[k]=soften(f[k])
    if isinstance(out.get('md_sections'),dict):
        for key,val in out['md_sections'].items():
            if isinstance(val,list): out['md_sections'][key]=[soften(s) if isinstance(s,str) else s for s in val]
    if isinstance(out.get('size_tips'),dict):
        for key,val in out['size_tips'].items():
            if isinstance(val,list): out['size_tips'][key]=[soften(s) if isinstance(s,str) else s for s in val]
    return out


def purchase_motive(data: Dict[str, Any]) -> str:
    """Suggest a customer decision angle only from stated product facts.

    This is not a generated sales claim: it gives the model one grounded worry
    to resolve, rather than allowing the model to simply recite specifications.
    """
    detail = compact(data.get('detail_tip', ''))
    fit = compact(data.get('fit', ''))
    benefits = compact(data.get('appeal_points', ''))
    fabric = compact(data.get('material_desc_raw', ''))
    photo_details = data.get('visual_details', [])
    if isinstance(photo_details, list) and photo_details:
        return '사진에서 관찰된 디자인 포인트: ' + ' / '.join(map(str, photo_details[:3])) + ' — 고객에게 보이는 실제 차이 중심으로 설명하되 원단·착용 효과 추정 금지'
    haystack = ' '.join((detail, fit, benefits, fabric))
    candidates = [
        (r'털\s*빠짐(?:이)?\s*(?:거의\s*없|적)', '보송한 소재를 고를 때 털 빠짐을 걱정하는 고객', '털 빠짐이 거의 없다는 입력 근거를 과장 없이 설명'),
        (r'구김\s*(?:적|없|걱정)|링클프리', '하루 동안 옷의 구김이 신경 쓰이는 고객', '입력에 확인된 구김 관련 소재 특성을 구체적으로 설명'),
        (r'비침\s*(?:없|적)|비침\s*제로', '밝은 색 옷의 비침이 걱정인 고객', '입력된 비침 특성만 근거로 설명'),
        (r'복부|팔뚝|군살|체형\s*커버', '상체 또는 복부 라인이 신경 쓰이는 고객', '실제 확인된 핏·여유분·디테일을 연결하되 효과를 보장하지 않기'),
        (r'허리\s*밴딩|밴딩', '허리 압박과 장시간 착용이 신경 쓰이는 고객', '허리 밴딩의 구체적인 구조를 설명하고 착용감은 확정하지 않기'),
        (r'스트레치|텐션|신축|스판', '움직일 때 원단의 유연함을 중요하게 보는 고객', '입력된 신축성 근거를 설명하고 활동성을 무조건 보장하지 않기'),
        (r'탈부착|타이|배색|절개|립니트', '기본 옷에 차별화된 디테일을 원하는 고객', '실제로 확인된 디테일이 코디에 주는 차이 중심으로 설명'),
    ]
    for pat,worry,evidence in candidates:
        if re.search(pat,haystack):
            return f'고객 고민: {worry} / 입증할 가치: {evidence}'
    for value in (detail, benefits, fit, fabric):
        if value:
            return f'선택 이유 후보: 입력값 「{value[:100]}」의 실제 차별점이 누구에게 필요한지 설명. 근거 없는 효과 추가 금지'
    return '상품 고유의 판매 포인트 입력이 부족함: 이름·소재만으로 효과를 추정하지 말고 실제 확인되는 사실만 간결히 설명'


def build_editorial_brief(data: Dict[str, Any]) -> str:
    """Specific editorial allocation; no cross-product sales claims."""
    name=compact(data.get('display_name',''))
    detail=compact(data.get('detail_tip',''))
    fit=compact(data.get('fit',''))
    benefits=compact(data.get('appeal_points',''))
    material=compact(data.get('material_desc_raw',''))
    measurement=' / '.join(str(v) for v in data.get('measurement_lines',[]))
    known='; '.join(x for x in (detail,fit,benefits) if x)
    gaps = []
    if not detail: gaps.append('디테일 특징: 미입력 — 사진에서 보이지 않으면 장식·넥·여밈 방식 추정 금지')
    if not fit: gaps.append('핏·실루엣: 미입력 — 사진/실측 근거 없이 체형 커버 효과 확정 금지')
    if not benefits: gaps.append('주요 어필 포인트: 미입력 — 구매 편익은 확인된 소재·구조를 토대로만 설명')
    return '\n'.join([
        f'상품: {name}',
        '이번 상품의 최우선 구매 동기: ' + purchase_motive(data),
        f'확인된 디테일/핏/포인트: {known or "명시 입력 없음"}',
        '사진에서 관찰된 외관 (직원 확인 필요): ' + ' / '.join(map(str,data.get('visual_details', []))),
        f'확인된 원단 특징: {material or "미입력"}',
        f'실측: {measurement or "미입력"}',
        '섹션 역할 배분:',
        '1) choice: 제품 외관의 고유 디테일이 확인됐다면 가장 먼저 활용. 고객 고민은 하나만 자연스럽게 연결하되 가장 큰 고민이라고 일반화 금지. 소재 성분·컬러·사이즈 나열 금지',
        '2) fabric: 혼용률·촉감·질감·관리 주의. 두께/보온성은 직접 확인된 경우만. 의류 소재와 색상 혼동 금지',
        '3) fit: 확인된 실측, 사이즈 표기, 형태/핏. 숫자만으로 착용감을 보증하지 않기. 총장으로 힙커버를 단정하지 않기',
        '4) occasion: 상품의 형태·색상에 근거한 구체적인 코디 2~3가지와 TPO. 상품 특징 요약 반복 금지',
        'FAQ: 단순 색상·소재·사이즈를 묻는 기본정보 질문보다 부해 보임/77체형·이너 여유/구김·관리/실제 코디 등 구매 불안을 다루되 답변은 조건부·근거 중심',
        '추천문장: 다른 니즈 네 가지. 실측/촉감/관리/스타일 등 근거 있는 특징을 고객 문제와 연결',
        '착용 체크 포인트: 실제 후기 근거가 없으면 1인칭 경험담 대신 확인해야 할 실용 포인트 4개',
        '체형팁: 55/66/66반/77별 실측 비교 시 참고사항만; 모델 실착 근거 없이 활동성·힙덮음·슬림효과 단정 금지',
        '입력 정보 부족: ' + ('; '.join(gaps) if gaps else '상세 입력값 사용 가능'),
    ])


# ── Output-time grounded claims filter. This runs even if the LLM reviewer fails.
def validate_required_inputs(data: Dict[str, Any]) -> List[str]:
    """Block silently incomplete output, never invent manufacturing origin."""
    missing = []
    for key, label in (("display_name", "상품명"), ("country", "제조국")):
        if not compact(data.get(key)):
            missing.append(label)
    return missing


def safe_measurement(data: Dict[str, Any], labels: tuple) -> str:
    text = ' '.join(map(str, data.get('measurement_lines', [])))
    for label in labels:
        match = re.search(re.escape(label) + r'\s*[:：]?\s*(\d{2,3}(?:\.\d+)?)', text)
        if match:
            return match.group(1)
    return ''


def apply_grounded_safety(draft: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """Only rewrite provably unsupported assertions, keeping the editorial copy otherwise intact."""
    import copy
    out = copy.deepcopy(draft)
    evidence = ' '.join(str(data.get(k, '')) for k in ('fit', 'detail_tip', 'appeal_points', 'etc', 'material_desc_raw'))
    length = safe_measurement(data, ('총장','총길이'))
    chest = safe_measurement(data, ('가슴둘레',))
    hip_evidence = bool(re.search(r'힙.{0,7}(?:덮|가리|커버)', evidence))
    unverified_fit = not bool(re.search(r'실착|착용 테스트|모델 착용|착용 후기', evidence))

    def correct(text):
        text = str(text)
        # Restrict this adjustment to input claiming minimal shedding.
        if re.search(r'털\s*빠짐.{0,8}(거의\s*없|적)', evidence):
            text = re.sub(r'털\s*빠짐\s*걱정\s*없는', '털 빠짐이 거의 없는', text)
            text = re.sub(r'털\s*빠짐이?\s*전혀\s*없습니다', '털 빠짐이 거의 없습니다', text)
            text = re.sub(r'털\s*빠짐이?\s*전혀\s*없는', '털 빠짐이 거의 없는', text)
        if not hip_evidence:
            text = re.sub(r'(?:총장|총길이)\s*\d+(?:\.\d+)?\s*cm\s*로\s*힙을\s*(?:살짝\s*)?(?:덮(?:는|지\s*않는|습니다|어주는)|가려주는)[^.]*\.',
                          '총장은 평소 입으시는 옷의 실측과 비교해 주세요.', text)
            text = re.sub(r'힙을\s*(?:살짝\s*)?덮(?:는|지\s*않는|습니다)[^.]*\.',
                          '실제 기장 위치는 체형과 착용 방식에 따라 달라집니다.', text)
        # A numerical length/shoulder value alone does not establish suitability.
        text = re.sub(r'(?:총장|총길이)\s*\d+(?:\.\d+)?\s*cm\s*로\s*다양한\s*체형에\s*잘\s*맞습니다\.',
                      '총장은 평소 입으시는 옷의 실측과 비교해 주세요.', text)
        text = re.sub(r'(?:소매\s*길이|어깨단면)\s*\d+(?:\.\d+)?\s*cm\s*로\s*적당한\s*길이[^.]*\.',
                      '소매와 어깨 실측을 평소 착용하는 옷과 비교해 주세요.', text)
        if unverified_fit:
            text = re.sub(r'이너.{0,18}(?:불편함이\s*없|답답하지\s*않)[^.]*\.',
                          '겹쳐 입으실 경우 가슴·암홀 실측을 비교해 주세요.', text)
            text = re.sub(r'(?:활동성이\s*좋습니다|어떤\s*체형에도\s*잘\s*맞습니다|다양한\s*체형에\s*잘\s*맞습니다)\.',
                          '착용감은 체형에 따라 달라질 수 있어 실측 확인을 권합니다.', text)
        return text

    for key in ('material_desc_lines', 'recommend_lines', 'review_lines'):
        if isinstance(out.get(key), list): out[key] = [correct(s) for s in out[key]]
    if isinstance(out.get('faqs'), list):
        for faq in out['faqs']:
            if isinstance(faq,dict):
                for key in ('q','a'):
                    if isinstance(faq.get(key),str): faq[key] = correct(faq[key])
    if isinstance(out.get('md_sections'), dict):
        for key in MD_KEYS:
            if isinstance(out['md_sections'].get(key),list):
                out['md_sections'][key] = [correct(s) for s in out['md_sections'][key]]
    if isinstance(out.get('size_tips'), dict):
        for key in TIP_KEYS:
            if isinstance(out['size_tips'].get(key),list):
                out['size_tips'][key] = [correct(s) for s in out['size_tips'][key]]
    return out


def numeric_measurement_issues(draft: Dict[str, Any], data: Dict[str, Any]) -> List[str]:
    """Compare printed dimension numbers against actual inputs; handles multiple listed sizes."""
    raw = ' '.join(str(v) for v in data.get('measurement_lines', []))
    text = content_string(draft)
    tips = draft.get('size_tips', {})
    if isinstance(tips, dict):
        text += ' ' + ' '.join(' '.join(map(str, x)) for x in tips.values() if isinstance(x,list))
    warnings=[]
    groups = [('총장','총길이'), ('가슴둘레',), ('어깨단면',), ('암홀둘레',),
              ('소매길이',), ('소매단둘레',), ('허리둘레',), ('엉덩이둘레',)]
    for labels in groups:
        pattern = r'(?:' + '|'.join(re.escape(t) for t in labels) + r')\s*[:：=]?\s*(\d{2,3}(?:\.\d+)?)\s*(?:cm)?'
        expected = {float(v) for v in re.findall(pattern,raw)}
        actual = {float(v) for v in re.findall(pattern,text)}
        # An empty input does not license the model to invent a dimension.
        if actual and not expected:
            warnings.append(f'{labels[0]}: 입력되지 않은 실측 수치가 원고에 나타납니다.')
        elif expected and actual - expected:
            warnings.append(f'{labels[0]}: 원고 실측 {sorted(actual-expected)}가 입력값 {sorted(expected)}과 다릅니다.')
    return warnings
# === EMBEDDED QUALITY ENGINE END ===

st.set_page_config(page_title="PAGE BUILDER", layout="wide")

# ─────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────
for key, default in [
    ("reset_nonce", 0),
    ("naming_result", ""),
    ("naming_input_value", ""),
    ("generated_result", ""),
    ("generated_docx", b""),
    ("generated_file_stem", "page_builder"),
    ("generated_issues", []),
    ("generated_visual_details", []),
]:
    if key not in st.session_state:
        st.session_state[key] = default

st.markdown(
    "<style>div[data-testid='stButton'] > button { min-height: 42px; }</style>",
    unsafe_allow_html=True,
)

st.title("MISHARP PAGE BUILDER")
st.caption("구매전환율 상승을 위한 상세페이지 기획 + 상품 원고 생성기")

api_key = st.secrets.get("OPENAI_API_KEY", "")
if not api_key:
    st.warning("OPENAI_API_KEY가 설정되지 않았습니다. Streamlit Cloud Secrets 또는 .streamlit/secrets.toml을 확인해 주세요.")
    st.stop()

client = OpenAI(api_key=api_key)

# ─────────────────────────────────────────────
# 고정 HTML 헤더
# ─────────────────────────────────────────────
FIXED_HTML_HEAD = (
    '<meta http-equiv="X-UA-Compatible" content="IE=edge,chrome=1">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    '<link href="http://fonts.googleapis.com/css?family=Roboto" rel="stylesheet" type="text/css">\n'
    '<link href="http://netdna.bootstrapcdn.com/font-awesome/4.3.0/css/font-awesome.min.css" rel="stylesheet" type="text/css">\n'
    '<link href="/SRC2/cssmtmenu/style.css" rel="stylesheet" type="text/css">\n'
    '<link href="//spoqa.github.io/spoqa-han-sans/css/SpoqaHanSans-kr.css" rel="stylesheet" type="text/css">\n'
    '<link href="//misharp.co.kr/subtap.css" rel="stylesheet" type="text/css">'
)


DIVIDER_MARKER = "────────────────────────────────────────"

def add_blue_divider(doc):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "12")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "2F6DF6")
    pBdr.append(bottom)
    pPr.append(pBdr)
    run = p.add_run(" ")
    run.font.name = "Dotum"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "돋움")
    run.font.size = Pt(10)

NAME_PROMPT = (
    "너는 4050 여성 패션 쇼핑몰 미샵의 상품 네이밍 전문가다.\n"
    "- 상품 주요 특징을 반영해 상품명을 20개 제안한다.\n"
    "- 각 상품명은 공백 포함 최대 18자 이내.\n"
    "- 반드시 단어와 단어 사이를 자연스럽게 띄어쓴다.\n"
    "- AI 검색, 키워드 검색 모두 고려한다.\n"
    "- 디테일/형태/원단/핏 등을 반영한 단어 + 카테고리명을 포함한다.\n"
    "- 필요하면 세련되고 여성스러운 단어를 앞에 붙여도 된다.\n"
    "- 번호, 설명, 코드펜스 없이 한 줄에 하나씩 20개만 출력한다."
)


# ─────────────────────────────────────────────
# 유틸 함수
# ─────────────────────────────────────────────
def chat_with_retry(*, model, messages, temperature=0.3, max_retries=2):
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return client.chat.completions.create(
                model=model, messages=messages, temperature=temperature
            )
        except RateLimitError as exc:
            last_exc = exc
            if attempt >= max_retries:
                raise
            time.sleep(2 * (attempt + 1))
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries:
                raise
            time.sleep(1 * (attempt + 1))
    raise last_exc


def file_to_content_item(uploaded_file):
    mime = uploaded_file.type or mimetypes.guess_type(uploaded_file.name)[0] or "image/jpeg"
    b64 = base64.b64encode(uploaded_file.read()).decode("utf-8")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def extract_lines_with_digits(text):
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line and re.search(r"\d", line):
            out.append(line)
    return out


def combine_measurements(top, bottom, dress):
    lines = []
    for block in [top, bottom, dress]:
        lines.extend(extract_lines_with_digits(block))
    return lines


def count_colors(color_text):
    if not color_text.strip():
        return 0
    # 슬래시·쉼표로 먼저 분리
    text = color_text.replace(" / ", "\n").replace("/", "\n").replace(",", "\n")
    result = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # "1 블랙 2 네이비 3 베이지" 처럼 숫자가 구분자인 경우 각각 분리
        sub = re.split(r"(?=\s*\d+\s+[가-힣a-zA-Z])", line)
        for s in sub:
            s = re.sub(r"^\s*\d+\s*", "", s).strip()
            if s:
                result.append(s)
    return len(result) if result else 0


def apply_color_count_to_name(product_name, color_text):
    count = count_colors(color_text)
    suffix = f"({count} color)" if count > 0 else "(color)"
    name = (product_name or "").strip()
    name = re.sub(r"\(\s*\d+\s*color\s*\)", suffix, name, flags=re.I)
    name = re.sub(r"\(\s*color\s*\)", suffix, name, flags=re.I)
    return name


def clean_line(line):
    line = (line or "").strip()
    line = re.sub(r"^[\-\u2022\u25aa\u29bf\s]+", "", line)
    line = re.sub(r"\s+", " ", line).strip()
    # ",." 중복 패턴 정리
    line = re.sub(r",\.+", ".", line)
    return line


def ensure_period(line):
    """마침표로 끝나게 보장. 쉼표/쉼표+마침표로 끝나는 경우도 정리."""
    line = clean_line(line)
    if not line:
        return ""
    # 쉼표+마침표 중복 제거: ",." → "."
    line = re.sub(r",\.+$", ".", line)
    # 쉼표로만 끝나는 경우: 쉼표 제거 후 마침표
    if line.endswith(","):
        line = line[:-1].rstrip()
    if re.search(r"[.!?\u2026]$", line):
        return line
    return line + "."


def format_measurement_lines(lines):
    if not lines:
        return "실측사이즈 정보를 입력해 주세요."
    formatted = []
    for line in lines:
        line = re.sub(r"\s+단위:cm$", "", line).strip()
        for label in ["XL", "L", "M", "S", "F"]:
            line = re.sub(rf"\s+{label}\s+", f"<br>{label} ", line)
        line = re.sub(r"\s+", " ", line)
        formatted.append(line)
    return "<br>".join(formatted) + " (단위: cm)"


def format_material_line(material):
    mat = (material or "").strip()
    return mat



def result_to_docx_bytes(result_text):
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Dotum"
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "돋움")
    style.font.size = Pt(10)
    style.paragraph_format.space_before = Pt(0)
    style.paragraph_format.space_after = Pt(0)
    style.paragraph_format.line_spacing = 1.5

    def add_plain_paragraph(text=""):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.5
        run = p.add_run(text)
        run.font.name = "Dotum"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "돋움")
        run.font.size = Pt(10)
        return p

    for line in result_text.splitlines():
        if line.strip() == DIVIDER_MARKER:
            add_plain_paragraph("")
            add_plain_paragraph("")
            add_blue_divider(doc)
            add_plain_paragraph("")
            add_plain_paragraph("")
            continue
        add_plain_paragraph(line)

    bio = io.BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio.getvalue()

def reset_all():
    st.session_state.reset_nonce += 1
    st.session_state.naming_result = ""
    st.session_state.naming_input_value = ""
    st.session_state.generated_result = ""
    st.session_state.generated_docx = b""
    st.session_state.generated_file_stem = "page_builder"
    st.session_state.generated_issues = []
    st.session_state.generated_visual_details = []


# ─────────────────────────────────────────────
# JSON 파싱
# ─────────────────────────────────────────────
def extract_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("JSON 응답을 찾지 못했습니다.")
    return json.loads(m.group(0))



def extract_visual_evidence(data, image_items):
    """Optional photo-only inspection. Never turn an image inference into a fabric/fit guarantee.

    On API failure leave visual evidence empty; the regular generation path still works.
    """
    if not image_items or not all(isinstance(x, dict) and x.get("type") == "image_url" for x in image_items):
        return []
    task = (
        "이 상품 사진에서 눈으로 확실하게 확인되는 디자인 요소만 최대 6개 관찰하세요. "
        "예: 넥 형태, 카라, 여밈, 단추, 소매 끝, 밑단, 포켓, 배색, 절개, 립 조직이 위치한 부분. "
        "상품 이름에 나온 특징이어도 실제 사진으로 확인할 수 없다면 쓰지 마세요. "
        "실루엣/길이는 뒷모습과 전체 착장 사진이 있을 때만 제한적으로 묘사하세요. "
        "촉감·소재 혼용률·신축성·보온성·털빠짐·제조국·치수·착용의 편안함은 사진으로 판단하지 마세요. "
        "사진의 색은 조명 차이가 있으므로 입력된 컬러명을 대체하지 마세요. "
        "반드시 {\"visible_details\": [\"확인된 외관 특징\"]} JSON으로만 답하세요. "
        "불명확하면 빈 배열을 반환하세요."
    )
    try:
        resp = chat_with_retry(
            model="gpt-4o", temperature=0.1, max_retries=0,
            messages=[{"role":"system", "content":task},
                      {"role":"user", "content":[{"type":"text", "text":"제품명: " + str(data.get('display_name',''))}] + image_items}],
        )
        obj = extract_json(resp.choices[0].message.content)
        values = obj.get('visible_details', []) if isinstance(obj, dict) else []
        if not isinstance(values, list):
            return []
        forbidden = ("입어", "착용감", "편안", "보온", "촉감", "털 빠짐", "방수", "신축", "스판", "폴리에스터", "면100", "제조국")
        details = []
        for value in values[:6]:
            detail = re.sub(r"\s+", " ", str(value or '')).strip().strip('-•')
            if 3 <= len(detail) <= 65 and not any(term in detail for term in forbidden) and detail not in details:
                details.append(detail)
        return details
    except Exception:
        return []

# ─────────────────────────────────────────────
# 프롬프트 빌더
# ─────────────────────────────────────────────
def build_generation_prompt(data, additional_request):
    """상품 근거 중심 초안. 분량을 강제로 줄여 정보가 누락되지 않도록 한다."""
    fields = {
        "상품명": data.get("display_name", ""),
        "컬러": data.get("color", ""),
        "제조국": data.get("country", ""),
        "사진으로 확인된 디자인 특징(직원 확인 권장)": data.get("visual_details", []),
        "사이즈": data.get("size", ""),
        "소재": data.get("material", ""),
        "소재설명": data.get("material_desc_raw", ""),
        "디테일 특징": data.get("detail_tip", ""),
        "핏·실루엣": data.get("fit", ""),
        "주요 어필 포인트": data.get("appeal_points", ""),
        "기타 특징": data.get("etc", ""),
        "타겟": data.get("target", ""),
        "세탁방법": data.get("washing", ""),
        "실측사이즈": data.get("measurement_lines", []),
        "추가 요청": additional_request or "없음",
    }
    raw = json.dumps(fields, ensure_ascii=False, indent=2)
    profiles = "; ".join(TIP_PROFILES.values())
    return f"""당신은 미샵(MISHARP)의 4050 여성 패션 상세페이지를 작성하는 전문 MD 카피라이터입니다.
이번 작업은 문장 수 채우기가 아니라, 입력된 한 상품의 구매 이유를 고객이 이해하도록 정확하고 풍부하게 설명하는 것입니다. 사진의 시각 특징은 사진 관찰에 의한 참고이며 실제 제품을 본 직원의 확인이 우선합니다.

[이번 상품에 대해 확인된 입력값]
{raw}

[상품 고유 정보를 빠뜨리지 않기 위한 체크리스트]
{fact_report(data, additional_request)}

[이 상품만의 편집 설계도]
{build_editorial_brief(data)}

[반드시 지켜야 할 MD 편집 원칙]
- 첫 번째 소제목은 상품명·소재·컬러·FREE사이즈를 열거하며 시작하지 마세요. 고객이 구매 전에 느끼는 한 가지 고민을 고르고, 확인된 상품 장점이 어떻게 그 고민을 덜어 줄지 설명하세요. 고객 고민을 끼워 맞추거나 없는 장점을 만들지 마세요.
- 사진에서 확인된 디자인 특징은 상품의 차별점을 설명할 때 우선 검토하세요. 제품명에 '립니트'가 있어도 위치·형태가 사진으로 확인되지 않았다면 추정하지 마세요. 사진에서 확실한 외관 특징과 텍스트로 확인된 사실을 구분하세요.
- 확인된 디자인 차별점이 있으면 그것을 선택 이유에 한 번 구체적으로 설명하고, 원단/핏/코디 섹션에서 같은 말을 재진술하지 마세요. 첫 섹션에 사용한 근거를 두 번째 섹션에서 장황하게 반복하지 마세요. 1절은 고객의 선택 이유, 2절은 실제 질감·소재 특성, 3절은 가슴둘레·어깨·총장 등 유용한 실측, 4절은 고객 옷장 속 구체적인 코디입니다.
- 자켓·상의에서 상체 여유나 부해 보임을 다룰 때 입력에 가슴둘레 수치가 있으면 해당 숫자를 우선 활용하되, 입었을 때 날씬함·편안함은 실착 근거 없이 보장하지 마세요.
- 58cm 등 총장 숫자만으로 힙을 덮거나 덮지 않는다고 결론 내리지 마세요. 총장과 체형별 위치는 착장 근거가 없으면 확정할 수 없습니다. '실측 총장을 평소 자켓과 비교하세요'가 안전합니다.
- 사이즈팁 4개는 동일한 '여유롭다/편안하다' 표현을 바꾸어 반복하지 마세요. 55~77 각각 판단할 실측 위치와 체형 차이를 다르게 알려주고 실제 모델 실착 경험은 지어내지 마세요.
- FAQ는 '부해 보일까요?'라고 물으면 원단 볼륨·핏과 개인차를 정직하게 답하세요. '실측을 참고하면 적합합니다'만 쓰지 마세요. 질문에 먼저 답하고 근거/조건을 설명하세요.
- '착용 전 체크 포인트'는 스펙 재진술이 아닙니다. 최소 2개는 실제로 비교·확인할 행동을 설명하세요. 후기를 꾸미지 마세요.
- 정보를 늘리기 위해 같은 말을 반복하지 말고, 확인되지 않은 착용·보온·관리 효과를 약속하지 마세요. '거의 없음'을 '걱정 없음'으로 과장하지 마세요. 제조국은 입력값만 쓰며 미입력 시 지어내지 마세요.

[작성 순서]
1. 입력에서 증명되는 상품 특징/소재/장점/주의사항을 머릿속에 정리하세요.
2. 겉보기에 그럴듯한 일반론 대신 '어떤 디테일이 고객의 어떤 불편을 해소하는지' 근거를 연결하세요.
3. 입력된 디테일, 핏, 주요 어필 포인트를 MD원고에 골고루 배치하세요. 특정 내용만 반복하거나 누락하지 마세요.
4. 고객이 실제로 궁금해할 사이즈·소재·관리·코디 질문을 구체적으로 다루세요.
5. 불확실한 내용을 지어내지 마세요. 사진에 없거나 입력되지 않은 소재 비율, 제조 방식, 안감, 비침 없음, 건조기 가능, 제작사, 실제 착용 후기 등을 단정하면 안 됩니다.
6. 실측 숫자와 혼용률이 입력됐다면 정확히 유지하세요. 입력에 없는 실측 수치를 쓰지 마세요.
7. 다른 상품에서 가져온 내용, 템플릿용 고정 상품 문구, 근거 없는 장점은 절대 넣지 마세요.
8. 입력 문장을 그대로 복사하지 말고, 그 의미를 유지하며 자연스럽게 재구성하세요.

[문장 품질]
- MD원고는 4개 소제목으로 작성합니다. 각 영역에 역할이 겹치지 않는 2~4개 문단을 쓰되, 입력·사진으로 확인된 정보가 적으면 짧아도 정확하게 작성합니다. 글자 수를 채우려고 사실을 만들거나 빈말을 반복하지 마세요.
- 이 단계에서 한 줄 20~24자에 억지로 맞추지 마세요. 출력 함수가 자연스럽게 줄바꿈합니다. 의미와 문장 흐름이 우선입니다.
- 각 영역의 문장은 전개가 자연스럽고 반복 없이 구체적이어야 합니다. '다양한 활용이 가능합니다' 같은 빈 문구로 채우지 마세요.
- choice: 고객의 실제 고민부터 시작해 상품 고유의 근거 있는 해결 가치를 소개합니다. 성분/컬러/사이즈 정보 나열로 채우지 마세요. fabric: 실제 혼용 소재/촉감/두께 (입력 근거 있을 때만). fit: 체형, 사이즈, 실측. occasion: 구체적인 코디와 착용 장면. 핏·디테일·어필포인트 칸이 비어 있으면 실측과 사진에서 확인되는 사실만 사용하고, 정보를 지어내거나 115자를 강제로 채우지 마세요.
- 추천문장 4개는 모두 자연스러운 '~분'으로 끝납니다. '분께', '추천합니다', '권해드립니다', '입니다 분' 금지. 각기 다른 구매 니즈를 제시하세요.
- review_lines 4개는 MD/모델이 실물 착용 시 확인할 점을 고객도 이해하기 쉬운 자연스러운 문장으로 작성하세요. 현재 입력에 실제 착용후기가 없으면 '입어보니/입었더니/저는/제가/정말 마음에 들어요' 등 고객이나 직원의 가짜 실착 인용을 절대 쓰지 마세요.
- FAQ 4개는 '소재가 무엇인가요/사이즈가 어떻게 되나요/색상은 무엇인가요' 같은 상품 기본정보 복사형 질문을 피하고, 실제 망설임 4종을 구체적으로 다루세요. 부해 보일지, 기존 옷과 맞을지, 관리가 번거로울지, 코디가 쉬울지 같은 불안을 이 상품의 실측·소재·특징으로 답하세요. 확인할 수 없는 답변은 조건부로 안내하세요.
- 소재설명 3문장은 소재·조직·특성을 구체적으로 설명하되 확인되지 않은 기능은 주장하지 마세요. '털 빠짐이 거의 없음'은 '털 빠짐 전혀 없음'으로 과장하지 마세요. 폴리에스터 뽀글이를 실제 울/양털 원료로 오인시키지 마세요. 입력되지 않은 다른 컬러를 언급하지 마세요.
- 사이즈팁: {profiles}. 각 사이즈별로 이 수치가 가리키는 체형 차이와 상품의 실제 핏 정보를 고려한 2문장. 특정 체형에 무조건 잘 맞는다거나 극적인 커버 효과를 확정하지 마세요. 입력 실측이 부족하면 개인차/실측 확인을 안내하세요.
- '쇼핑에 꼭 참고하세요', '[구매 전 꼭 확인해 주세요]', 마무리 인사 등은 작성·출력하지 않습니다.

[JSON 형식 — 코드펜스/설명 없이 객체 하나만]
{{
 "material_desc_lines": ["충분히 구체적인 완결 문장 1", "완결 문장 2", "완결 문장 3"],
 "recommend_lines": ["고유 장점을 찾으시는 분", "특징을 원하는 분", "착용감을 중요하게 생각하시는 분", "실용성을 찾으시는 분"],
 "review_lines": ["근거 있는 관찰 포인트 1", "2", "3", "4"],
 "faqs": [{{"q":"Q. 실제 구매 질문 1", "a":"A. 입력을 근거로 한 답변 1"}}, {{"q":"Q. 실제 구매 질문 2", "a":"A. 답변 2"}}, {{"q":"Q. 실제 구매 질문 3", "a":"A. 답변 3"}}, {{"q":"Q. 실제 구매 질문 4", "a":"A. 답변 4"}}],
 "md_sections": {{"choice":["정보가 풍부한 문단 1", "문단 2", "문단 3"], "fabric":["문단 1", "문단 2", "문단 3"], "fit":["문단 1", "문단 2", "문단 3"], "occasion":["문단 1", "문단 2", "문단 3"]}},
 "size_tips": {{"55":["문장 1", "문장 2"], "66":["문장 1", "문장 2"], "66half":["문장 1", "문장 2"], "77":["문장 1", "문장 2"]}}
}}
"""


# ─────────────────────────────────────────────
# LLM 생성
# ─────────────────────────────────────────────
def generate_structured_copy(data, additional_request, uploaded_images):
    """원고 생성 → 사실 기반 편집 검수. 분량 부족만으로 정상 원고를 폐기하지 않는다.

    필수 JSON 구조가 깨진 경우에는 한 번만 구체적으로 보완 요청한다.
    원본이 완전하면 검수 API 실패나 검수 결과의 역행에도 원고 출력 가능.
    """
    image_items = [file_to_content_item(img) for img in (uploaded_images[:5] if uploaded_images else [])]
    # Observe product-visible details once before drafting, rather than repeatedly
    # asking the writer to guess what the photos show.
    data["visual_details"] = extract_visual_evidence(data, image_items)
    prompt = build_generation_prompt(data, additional_request)
    initial_content = [{"type": "text", "text": prompt}] + image_items
    messages = [
        {"role": "system", "content": "확인된 상품 정보만으로 한국어 커머스 카피를 작성하세요. JSON 객체만 반환하세요. 근거 없는 정보는 절대 추측하지 않습니다."},
        {"role": "user", "content": initial_content},
    ]
    first = chat_with_retry(model="gpt-4o", messages=messages, temperature=0.45, max_retries=2)
    raw = extract_json(first.choices[0].message.content)
    original_issues = check_quality(raw, data, additional_request)

    editor_instructions = (
        "다음 상품에 대한 초안을 실무자가 바로 사용할 수준으로 꼼꼼히 편집하세요. "
        "반드시 동일한 JSON 키와 필요한 개수(추천/후기/FAQ 각 4, 사이즈팁 4체형)를 유지하세요. "
        "소재, 실측, 상품 고유 특징의 누락을 확인하고 범용 표현이나 근거 없는 내용을 고치세요. "
        "md_sections의 4개 영역은 근거가 충분한 만큼 자연스럽고 구체적으로 서술하세요. "
        "입력되지 않은 디테일/핏 정보가 있더라도 글자 수를 채우려고 만들어 내지 마세요. "
        "사진에서 확인 가능한 형태/구조만 단정하세요. "
        "형식보다 입력정보 반영과 자연스러운 문장이 중요합니다. JSON 객체만 답하세요."
    )
    editorial_findings = editorial_issues(raw, data, additional_request)
    editor_instructions += (
        " 첫 선택 이유는 상품 스펙을 다시 나열하지 말고 고객의 고민과 선택 가치를 연결하세요. "
        "소재·핏·코디 각 섹션의 내용을 중복하지 말고 역할별로 배분하세요. "
        "FAQ는 단순 정보조회형을 줄이고 실제 구매 망설임을 확인된 사실로 해결하세요. "
        "근거 없는 개인 착용 경험·절대 표현·존재하지 않는 컬러는 제거하세요. "
        "소재가 폴리에스터라면 양털/울 원료로 오인되게 쓰지 마세요. "
        "실제 착용 데이터 없는 사이즈팁의 무조건적 핏 보장·체형 효과는 금지합니다. "
        "특히 선택 이유가 상품명과 소재 소개로만 시작하지 않는지, 자켓의 가슴둘레 실측이 핏 설명에 반영되는지, "
        "FAQ가 질문에 직접 답하는지, 착용 전 체크포인트가 실제 확인 행동인지 확인하고 고치세요. "
        "총장으로 힙을 덮는다고 단정하거나 이너 착용 편안함·뛰어난 보온성을 지어내지 마세요. "
    )
    if original_issues or editorial_findings:
        editor_instructions += "\n[실제 검사에서 발견된 문제]\n" + "\n".join("- " + x for x in original_issues + editorial_findings)
    review_text = (
        "[이 상품 입력 정보]\n" + prompt
        + "\n[검토·개선할 초안 JSON]\n" + json.dumps(raw, ensure_ascii=False)
    )
    # 첫 생성의 이미지를 재사용해, 입력란이 빈 상품에서도 2차 편집이 사진 근거를 잃지 않게 한다.
    review_content = ([{"type": "text", "text": review_text}] + image_items) if image_items else review_text
    audit = [
        {"role": "system", "content": editor_instructions},
        {"role": "user", "content": review_content},
    ]
    candidates = [raw]
    try:
        revised_result = chat_with_retry(model="gpt-4o", messages=audit, temperature=0.25, max_retries=1)
        candidates.append(extract_json(revised_result.choices[0].message.content))
    except Exception:
        # 원본에 모든 필수 영역이 있으면 편집 호출 문제만으로 다운로드를 차단하지 않는다.
        if not check_structure(raw):
            return apply_grounded_safety(soften_unverified_claims(raw, data), data)
        raise

    def rank(candidate):
        return score_editorial(candidate, data, additional_request)

    complete = [candidate for candidate in candidates if not check_structure(candidate)]
    if complete:
        # 1차 평가에서 남은 명백한 품질 문제는 한 번만 지목하여 재편집한다.
        best = min(reversed(complete), key=rank)
        remaining = editorial_issues(best, data, additional_request)
        if remaining:
            repair_prompt = (
                "[실제 상품 원고 오류 수정 — 원고 전체를 완성된 JSON으로 반환]\n"
                "현재 문장을 길게 늘리지 말고 아래 지적 사항을 실질적으로 고치세요. "
                "고객의 선택 이유, 핵심 실측, 구체적인 FAQ 답변을 우선하고, "
                "입력되지 않은 옷의 형태·착용 경험·기능은 지어내지 마세요. "
                "기존 JSON 키, 추천 4개/체크포인트 4개/FAQ 4개/사이즈팁 각 2개를 유지하세요.\n"
                + "\n".join("- " + x for x in remaining)
                + "\n[현재 원고]\n" + json.dumps(best, ensure_ascii=False)
                + "\n[원상품 근거]\n" + prompt
            )
            repair_messages = ([{"type": "text", "text": repair_prompt}] + image_items) if image_items else repair_prompt
            try:
                repaired = chat_with_retry(
                    model="gpt-4o",
                    messages=[{"role": "system", "content": "상품 근거만을 사용하는 한국어 MD 교열자. 반드시 완전한 JSON 객체만 반환."},
                              {"role": "user", "content": repair_messages}],
                    temperature=0.2, max_retries=1,
                )
                new_draft = extract_json(repaired.choices[0].message.content)
                if not check_structure(new_draft) and rank(new_draft) < rank(best):
                    best = new_draft
            except Exception:
                pass  # 최소한 출력 가능한 정상 초안은 유지한다.
        return apply_grounded_safety(soften_unverified_claims(best, data), data)

    # 첫 생성/검수 모두 일부 필수 필드를 누락한 경우에만 표적 복구 1회.
    best = min(reversed(candidates), key=rank)
    missing = check_structure(best)
    repair_text = (
        "다음 상품의 JSON 원고에는 출력에 필수인 영역이 누락되었습니다. "
        "가능한 다른 본문은 보존하고 지적된 필드만 해당 상품 입력 근거로 보완하세요. "
        "빈 템플릿이나 타 상품 공통 문구로 채우지 마세요. 근거 없는 사실은 쓰지 마세요. "
        "반드시 모든 키가 있는 JSON 객체만 반환하세요.\n"
        "[복구할 필드]\n" + "\n".join(missing)
        + "\n[실제 입력]\n" + prompt
        + "\n[기존 원고 JSON]\n" + json.dumps(best, ensure_ascii=False)
    )
    repair_content = ([{"type": "text", "text": repair_text}] + image_items) if image_items else repair_text
    fixed_result = chat_with_retry(
        model="gpt-4o",
        messages=[{"role": "system", "content": "필수 누락 필드만 보완하되 사실을 지어내지 않는 한국어 MD 편집자. JSON만 반환."},
                  {"role": "user", "content": repair_content}],
        temperature=0.2, max_retries=1,
    )
    fixed = extract_json(fixed_result.choices[0].message.content)
    if not check_structure(fixed):
        return apply_grounded_safety(soften_unverified_claims(fixed, data), data)
    raise ValueError("필수 원고 항목이 누락되어 출력할 수 없습니다: " + " / ".join(check_structure(fixed)[:4]))


# ─────────────────────────────────────────────
# 폴백 데이터
# ─────────────────────────────────────────────
def fallback_structured(data):
    product = data.get("display_name") or "상품"
    size = clean_line(data.get("size") or "FREE 사이즈로 77까지 추천드립니다.")
    material_desc_raw = data.get("material_desc_raw") or ""
    raw_lines = [x.strip() for x in material_desc_raw.replace("\r", "").split("\n") if x.strip()]
    material_lines = [ensure_period(clean_line(x)) for x in raw_lines[:3]]
    if not material_lines:
        material_lines = [
            "부드러운 터치감으로 피부에 닿는 느낌이 편안한 소재입니다.",
            "표면감이 차분하게 정리되어 데일리로 활용하기 좋습니다.",
            "관리 부담이 크지 않아 손이 자주 가는 아이템입니다.",
        ]

    return {
        "material_desc_lines": material_lines,
        "recommend_lines": [
            "출근룩부터 모임룩까지 단정하게 입을 아이템을 찾으시는 분",
            "상체 라인을 부담 없이 정리해 주는 편안한 핏을 원하시는 분",
            "소재감이 주는 고급스러운 분위기를 중요하게 생각하시는 분",
            "데님, 슬랙스, 스커트와 두루 잘 어울리는 상의를 찾으시는 분",
        ],
        "review_lines": [
            "입었을 때 전체 실루엣이 차분하게 정리돼서 손이 자주 가요.",
            "촉감이 부담스럽지 않아 하루 종일 입어도 편안한 느낌이에요.",
            "격식 있는 자리에도 과하지 않게 잘 어울려 활용도가 높아요.",
            "구김 부담이 크지 않아 바쁜 날에도 깔끔하게 입기 좋았어요.",
        ],
        "faqs": [
            {"q": "Q. 가슴이 있는 77 체형도 답답하지 않게 착용할 수 있을까요?", "a": "A. " + size + " 기준으로 안내드리며, 여유 있게 착용하실 수 있도록 설계되어 있습니다. 실측사이즈를 함께 확인하시면 더 정확합니다."},
            {"q": "Q. 밝은 컬러는 비침이 심한 편인가요?", "a": "A. 밝은 컬러 계열은 약간의 비침이 있을 수 있어 스킨톤 이너와 함께 착용하시면 더 안정감 있게 입으실 수 있습니다."},
            {"q": "Q. 하루 종일 입으면 구김이 많이 남는 편인가요?", "a": "A. 소재 특성상 비교적 구김이 적어 출근룩이나 모임룩으로도 부담 없이 입기 좋은 편입니다."},
            {"q": "Q. 세탁은 어떻게 하면 좋을까요?", "a": "A. " + ensure_period(clean_line(data.get("washing") or "드라이클리닝, 단독 울세탁, 손세탁 권장. 건조기 사용 금지"))},
        ],
        "shopping_lines": [
            size,
            "밝은 컬러 계열은 스킨톤 이너와 함께 착용하시면 더 안정감 있게 연출하실 수 있습니다.",
            "실측사이즈를 함께 확인하시면 원하는 핏으로 선택하시기 더 수월합니다.",
        ],
        "md_sections": {
            "choice": [
                product + "은 과하지 않으면서도 차분하고 세련된 인상을 만들어 줍니다.",
                "기본에 가까운 디자인일수록 소재와 핏의 차이가 크게 드러나는데, 이 아이템은 그 균형감이 특히 좋습니다.",
                "체형을 부드럽게 감싸주는 실루엣이 안정감 있게 느껴집니다.",
                "데일리와 격식을 오가는 장면에서 활용도가 높아 추천드리기 좋습니다.",
            ],
            "fabric": material_lines + ["두께감 또한 과하게 무겁지 않아 계절감에 맞춰 손쉽게 매치하기 좋습니다."],
            "fit": [
                size + " 기준으로 안내드리며, 전체적으로 답답하지 않게 착용하기 좋은 편입니다.",
                "어깨선과 품이 과하게 붙지 않아 상체 라인이 비교적 편안해 보입니다.",
                "실루엣이 과하게 흐트러지지 않아 단정한 분위기를 유지하기 좋습니다.",
                "실측사이즈를 함께 확인하시면 원하는 핏으로 선택하시기 더 수월합니다.",
            ],
            "occasion": [
                "출근룩처럼 단정함이 필요한 날에도 무리 없이 입기 좋습니다.",
                "모임이나 식사 자리처럼 차려입은 느낌이 필요한 순간에도 자연스럽게 어울립니다.",
                "데님, 슬랙스, 스커트와 두루 매치하기 쉬워 코디 폭이 넓습니다.",
                "아우터 안에 받쳐 입거나 단독으로 연출해도 분위기가 흐트러지지 않습니다.",
            ],
            "purchase_note": [],
            "ending": [],
        },
        "size_tips": {
            "55": [
                "여유 있는 핏으로 루즈하지 않게 자연스럽게 떨어져 단정한 실루엣을 연출합니다.",
                "소매와 어깨선이 부드럽게 정리되어 슬림한 체형에도 밋밋하지 않게 어울립니다.",
            ],
            "66": [
                "품과 실루엣에 적당한 여유가 있어 편안하게 착용하기 좋습니다.",
                "힙을 덮는 기장과 안정감 있는 핏으로 체형 커버 효과를 자연스럽게 느끼실 수 있습니다.",
            ],
            "66half": [
                "상체를 편안하게 감싸주어 답답함 없이 착용하기 좋습니다.",
                "어깨와 팔 라인이 자연스럽게 정리되어 군살을 부드럽게 커버해 줍니다.",
            ],
            "77": [
                "상체에 여유가 필요한 체형도 편안하게 입을 수 있을 만큼 넉넉한 핏입니다.",
                "가슴과 어깨가 있는 체형도 부해 보이지 않게 정돈된 실루엣으로 연출됩니다.",
            ],
        },
    }


# ─────────────────────────────────────────────
# 추천 문장 정규화 (핵심 안전장치)
# ─────────────────────────────────────────────
def normalize_recommend_line(x):
    """
    추천 문장이 반드시 '분'으로 끝나도록 보장.
    이중 '분' 방지, 금지 서술형 제거.
    """
    x = clean_line(x)
    # 마침표 제거
    x = x.rstrip(".")
    # 이미 '분'으로 끝나면 그대로
    if x.endswith("분"):
        return x
    # 금지 서술형 어미 제거
    x = re.sub(r"(추천합니다|권해드립니다|적합합니다|잘 어울립니다|좋습니다|만족하실)$", "", x).strip()
    x = x.rstrip(".")
    if x.endswith("분"):
        return x
    return x + " 분"


def normalize_review_line(x):
    """후기 문장에서 따옴표 제거 (렌더 단계에서 붙임)."""
    x = clean_line(x)
    # 다양한 따옴표 제거
    x = x.replace('"', "").replace("\u201c", "").replace("\u201d", "").strip()
    return x


def normalize_faq(faq_raw, fallback):
    out = []
    for item in (faq_raw if isinstance(faq_raw, list) else []):
        if not isinstance(item, dict):
            continue
        q = clean_line(item.get("q", ""))
        a = clean_line(item.get("a", ""))
        if not q or not a:
            continue
        # Q./A. 중복 제거 후 정규화
        q = re.sub(r"^Q\.\s*Q\.", "Q.", q.strip())
        a = re.sub(r"^A\.\s*A\.", "A.", a.strip())
        if not q.startswith("Q."):
            q = "Q. " + q.lstrip("Q.").strip()
        if not a.startswith("A."):
            a = "A. " + a.lstrip("A.").strip()
        out.append({"q": q, "a": a})
        if len(out) >= 4:
            break
    for fb in fallback:
        if len(out) >= 4:
            break
        if all(fb["q"] != x["q"] for x in out):
            out.append(fb)
    return out[:4]


def safe_lines(raw, count, fallback):
    """일반 필드용: LLM 결과가 count보다 부족하면 폴백으로 보충."""
    items = [clean_line(x) for x in (raw if isinstance(raw, list) else []) if clean_line(x)]
    if len(items) < count:
        for fb in fallback:
            c = clean_line(fb)
            if c and c not in items:
                items.append(c)
            if len(items) >= count:
                break
    return items[:count]


def safe_md_lines(raw, fallback):
    """MD원고 전용: LLM이 생성한 줄만 사용. 아예 없을 때만 폴백 전체 사용. 폴백 혼합 없음."""
    def fix_md_line(x):
        x = clean_line(x)
        # 쉼표로 끝나는 줄: 쉼표 제거 (다음 줄과 이어지는 연결줄은 마침표 없이 그대로)
        if x.endswith(","):
            x = x[:-1].rstrip()
        # ",." 중복 패턴 제거
        x = re.sub(r",\.+$", ".", x)
        return x

    items = [fix_md_line(x) for x in (raw if isinstance(raw, list) else []) if clean_line(x)]
    items = [x for x in items if x]  # 빈 줄 제거
    if not items:
        return [clean_line(x) for x in fallback if clean_line(x)]
    return items


def normalize_generated(result, data):
    fb = fallback_structured(data)

    material_desc_lines = [ensure_period(x) for x in safe_lines(result.get("material_desc_lines"), 3, fb["material_desc_lines"])]
    recommend_lines = [normalize_recommend_line(x) for x in safe_lines(result.get("recommend_lines"), 4, fb["recommend_lines"])]
    review_lines = [normalize_review_line(x) for x in safe_lines(result.get("review_lines"), 4, fb["review_lines"])]
    faqs = normalize_faq(result.get("faqs"), fb["faqs"])
    shopping_lines = [ensure_period(x) for x in safe_lines(result.get("shopping_lines"), 3, fb["shopping_lines"])]

    md_raw = result.get("md_sections") if isinstance(result.get("md_sections"), dict) else {}
    md_sections = {
        # safe_md_lines: LLM 생성 줄만 사용, 쉼표 끝 정리 포함. ensure_period 미적용(연결줄 보존)
        "choice":   safe_md_lines(md_raw.get("choice"),   fb["md_sections"]["choice"]),
        "fabric":   safe_md_lines(md_raw.get("fabric"),   fb["md_sections"]["fabric"]),
        "fit":      safe_md_lines(md_raw.get("fit"),      fb["md_sections"]["fit"]),
        "occasion": safe_md_lines(md_raw.get("occasion"), fb["md_sections"]["occasion"]),
        "purchase_note": [],
        "ending": [],
    }

    tips_raw = result.get("size_tips") if isinstance(result.get("size_tips"), dict) else {}

    def normalize_tip(val, fallback_val):
        """size_tips 값이 문자열이든 배열이든 2개 문장 리스트로 정규화."""
        if isinstance(val, list) and val:
            lines = [ensure_period(clean_line(x)) for x in val if clean_line(x)]
            if not lines:
                lines = fallback_val if isinstance(fallback_val, list) else [ensure_period(fallback_val)]
            return lines[:2] if len(lines) >= 2 else lines
        if isinstance(val, str) and val.strip():
            # 문자열이면 마침표 기준으로 분리 시도
            parts = re.split(r"\.\s+", ensure_period(clean_line(val)))
            parts = [p.strip() for p in parts if p.strip()]
            parts = [p if p.endswith(".") else p + "." for p in parts]
            return parts[:2] if len(parts) >= 2 else parts
        # 폴백
        if isinstance(fallback_val, list):
            return fallback_val
        return [ensure_period(fallback_val)]

    size_tips = {
        "55":     normalize_tip(tips_raw.get("55"),     fb["size_tips"]["55"]),
        "66":     normalize_tip(tips_raw.get("66"),     fb["size_tips"]["66"]),
        "66half": normalize_tip(tips_raw.get("66half"), fb["size_tips"]["66half"]),
        "77":     normalize_tip(tips_raw.get("77"),     fb["size_tips"]["77"]),
    }

    return {
        "material_desc_lines": material_desc_lines,
        "recommend_lines": recommend_lines,
        "review_lines": review_lines,
        "faqs": faqs,
        "shopping_lines": shopping_lines,
        "md_sections": md_sections,
        "size_tips": size_tips,
    }


# ─────────────────────────────────────────────
# HTML 렌더링
# ─────────────────────────────────────────────

def render_text_source(structured):
    rec_lines = ''.join([f"▪ {x}<br>\n" for x in structured['recommend_lines']])
    review_lines = ''.join([f'{x}<br>\n' for x in structured['review_lines']])

    faq_parts = []
    for idx, faq in enumerate(structured['faqs']):
        q = re.sub(r"^(?:Q\.\s*)+", "", faq['q']).strip()
        a = re.sub(r"^(?:A\.\s*)+", "", faq['a']).strip()
        faq_parts.append(f"Q. {q}<br>\n")
        faq_parts.append(f"A. {a}<br>\n")
        if idx < len(structured['faqs']) - 1:
            faq_parts.append("<br>\n")
    faq_lines = "".join(faq_parts)

    return (
        '<div style="text-align:center;">\n'
        '<h3 style="margin-bottom:0;">\n'
        "✓ 이런 분께 추천해요!</h3>\n"
        "<br>\n"
        '<p><span style="font-size:14px; line-height:1.8;">\n'
        + rec_lines
        + "</span></p></div>\n"
        "<br><br><br><br>\n\n"
        '<div style="text-align:center;">\n'
        '<h3 style="margin-bottom:0;">\n'
        "✓ 착용 전 체크 포인트 (모델/스텝/MD 참고)</h3>\n"
        "<br>\n"
        '<p><span style="font-size:14px; line-height:1.8;">\n'
        + review_lines
        + "</span></p></div>\n"
        "<br><br><br>\n\n"
        + DIVIDER_MARKER + "\n\n"
        '<div style="text-align:center;">\n'
        '<h3 style="margin-bottom:0;">\n'
        "✓ (FAQ) 이 상품, 이게 궁금해요!</h3>\n"
        "<br>\n"
        '<p><span style="font-size:14px; line-height:1.4;">\n'
        + faq_lines
        + "</span></p></div>\n"
        "<br><br><br><br>"
    )

def render_subsc_html(data, structured):
    """MD원고 — 4개 소제목만. purchase_note/ending 절대 포함 안 함."""
    md = structured["md_sections"]

    def join_md(lines):
        return "".join(part + "<br>\n" for x in lines for part in natural_wrap(x, max_chars=24))

    return (
        '<div id="subsc">\n'
        "<h3>" + data["display_name"] + "</h3>\n"
        "<p>\n"
        '<strong style="font-weight:700 !important;">[이 상품을 초이스한 이유입니다.]</strong><br>\n'
        + join_md(md["choice"])
        + "<br>\n"
        '<strong style="font-weight:700 !important;">[원단과 두께 체감에 대하여]</strong><br>\n'
        + join_md(md["fabric"])
        + "<br>\n"
        '<strong style="font-weight:700 !important;">[체형과 핏, 사이즈 선택 가이드]</strong><br>\n'
        + join_md(md["fit"])
        + "<br>\n"
        '<strong style="font-weight:700 !important;">[이렇게 입는 날이 많아집니다]</strong><br>\n'
        + join_md(md["occasion"])
        + "\n</p></div>"
    )


def build_subtap_html(data, material_desc_lines):
    material_line = format_material_line(data["material"])
    washing = (data["washing"] or "").strip() or "상품 케어라벨의 세탁 안내를 확인해 주세요."
    size_tip = (data["size"] or "").strip() or "FREE 사이즈로 77까지 추천드립니다."
    measurement_html = format_measurement_lines(data["measurement_lines"])
    desc_html = "<br>\n\t\t\t\t\t\t\t\t\t".join(material_desc_lines) + "<br>"

    return (
        '<div id="Subtap">\n'
        '\t<div id="header2" role="banner">\n'
        '\t\t<nav class="nav" role="navigation">\n'
        '\t\t\t<ul class="nav__list">\n'
        "\t\t\t\t<li>\n"
        '\t\t\t\t\t<input id="group-1" type="checkbox" hidden="">\n'
        '\t\t\t\t\t<label for="group-1" style="border-top-color: rgb(204, 204, 204); border-top-width: 1px; border-top-style: solid;">\n'
        '\t\t\t\t\t\t<p class="fa fa-angle-right"></p>소재 정보</label>\n'
        '\t\t\t\t\t<ul class="group-list">\n'
        "\t\t\t\t\t\t<li>\n"
        '\t\t\t\t\t\t\t<a href="#">\n'
        "\t\t\t\t\t\t\t\t<h3>소재 : " + material_line + "</h3>\n"
        "\t\t\t\t\t\t\t\t<p>\n"
        "\t\t\t\t\t\t\t\t\t" + desc_html + "\n"
        "\t\t\t\t\t\t\t\t</p>\n"
        "\t\t\t\t\t\t\t\t<h3>세탁방법</h3>\n"
        "\t\t\t\t\t\t\t\t<p>" + washing + "</p>\n"
        "\t\t\t\t\t\t\t</a>\n"
        "\t\t\t\t\t\t</li>\n"
        "\t\t\t\t\t</ul>\n"
        "\t\t\t\t</li>\n"
        "\t\t\t\t<li>\n"
        '\t\t\t\t\t<input id="group-2" type="checkbox" hidden="">\n'
        '\t\t\t\t\t<label for="group-2">\n'
        '\t\t\t\t\t\t<p class="fa fa-angle-right"></p>사이즈 정보</label>\n'
        '\t\t\t\t\t<ul class="group-list gray">\n'
        "\t\t\t\t\t\t<li>\n"
        '\t\t\t\t\t\t\t<a href="#">\n'
        "\t\t\t\t\t\t\t\t<h3>사이즈 TIP</h3>\n"
        "\t\t\t\t\t\t\t\t<p>" + size_tip + "</p>\n"
        "\t\t\t\t\t\t\t\t<h3>길이 TIP</h3>\n"
        "\t\t\t\t\t\t\t\t<p>실제 기장감은 키와 체형에 따라 달라집니다.\n"
        "<br> 입력된 상품의 총장 및 실측사이즈를 참고해 주세요.</p>\n"
        "\t\t\t\t\t\t\t</a>\n"
        "\t\t\t\t\t\t</li>\n"
        "\t\t\t\t\t</ul>\n"
        "\t\t\t\t</li>\n"
        "\t\t\t\t<li>\n"
        '\t\t\t\t\t<input id="group-3" type="checkbox" hidden="">\n'
        '\t\t\t\t\t<label for="group-3">\n'
        '\t\t\t\t\t\t<p class="fa fa-angle-right"></p>실측 사이즈</label>\n'
        '\t\t\t\t\t<ul class="group-list">\n'
        "\t\t\t\t\t\t<li>\n"
        '\t\t\t\t\t\t\t<a href="#">\n'
        "\t\t\t\t\t\t\t\t<p>" + measurement_html + "</p>\n"
        "\t\t\t\t\t\t\t</a>\n"
        "\t\t\t\t\t\t</li>\n"
        "\t\t\t\t\t</ul>\n"
        "\t\t\t\t</li>\n"
        "\t\t\t\t<li>\n"
        '\t\t\t\t\t<input id="group-5" type="checkbox" hidden="">\n'
        '\t\t\t\t\t<label for="group-5"><span class="fa fa-angle-right"></span>\n'
        '\t\t\t\t\t\t<a href="#crema-product-fit-1" style="padding: 0px; box-shadow:none; background:#f7f7f7;">실측사이즈 재는방법</a></label>\n'
        "\t\t\t\t</li>\n"
        "\t\t\t</ul>\n"
        "\t\t</nav>\n"
        "\t</div>\n"
        "</div>"
    )


def assemble_final_output(data, structured):
    material_line = format_material_line(data["material"])
    text_source = render_text_source(structured)
    subsc_html = render_subsc_html(data, structured)
    subtap_html = build_subtap_html(data, structured["material_desc_lines"])
    source_block = FIXED_HTML_HEAD + "\n\n" + subsc_html + "\n\n" + subtap_html

    # 소재설명: 단락 형태 (리스트 아님)
    material_desc_paragraph = " ".join(structured["material_desc_lines"])

    lines = []
    lines.append("상품명 : " + data["display_name"])
    lines.append("")
    lines.append("컬러 : " + data["color"])
    lines.append("사이즈 : " + data["size"])
    lines.append("소재 : " + material_line)
    lines.append("소재설명 : " + material_desc_paragraph)
    lines.append("제조국 : " + (data.get("country", "").strip() or "미입력 (확인 필요)"))
    lines.append("")
    lines.append("○ 포인트 코멘트")
    lines.append("-")
    # 포인트 코멘트 빈 줄 9개
    for _ in range(9):
        lines.append("")
    lines.append("-")
    lines.append("")
    lines.append("---------------------------------")
    lines.append("텍스트 소스")
    lines.append("---------------------------------")
    lines.append("")
    lines.append(text_source)
    lines.append("")
    lines.append("----------------------------------")
    lines.append("MD원고(상품 설명 소스)")
    lines.append("----------------------------------")
    lines.append(source_block)
    lines.append("")
    lines.append("-----------------")
    lines.append("사이즈 팁")
    lines.append("-----------------")
    lines.append("")
    lines.append("ㅇ55 (90) 160cm 50kg")
    for s in structured["size_tips"]["55"]:
        lines.append(s)
    lines.append("")
    lines.append("ㅇ66 (95) 162cm 55kg")
    for s in structured["size_tips"]["66"]:
        lines.append(s)
    lines.append("")
    lines.append("ㅇ66반 (95) 163cm 59kg")
    for s in structured["size_tips"]["66half"]:
        lines.append(s)
    lines.append("")
    lines.append("ㅇ77 (100) 161cm 62kg")
    for s in structured["size_tips"]["77"]:
        lines.append(s)
    return "\n".join(lines).strip()


# ─────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────
st.markdown("---")
st.subheader("상품 네이밍")
ncol1, ncol2 = st.columns([5, 1], vertical_alignment="bottom")
with ncol1:
    naming_input = st.text_area(
        "상품 주요특징 입력",
        height=120,
        placeholder="예: 여리핏, 부드러운 엠보 텍스처, 상체 군살 커버, 루즈핏 맨투맨",
        key="naming_input_value",
    )
with ncol2:
    if st.button("네이밍 생성", use_container_width=True):
        if naming_input.strip():
            with st.spinner("상품명을 생성 중입니다..."):
                try:
                    response = chat_with_retry(
                        model="gpt-4o",
                        messages=[
                            {"role": "system", "content": NAME_PROMPT},
                            {"role": "user", "content": naming_input},
                        ],
                        temperature=0.5,
                        max_retries=2,
                    )
                    st.session_state.naming_result = response.choices[0].message.content.strip()
                    st.rerun()
                except RateLimitError:
                    st.error("현재 OpenAI 요청이 일시적으로 몰려 네이밍 생성을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.")
                except Exception as e:
                    st.error(f"네이밍 생성 중 오류가 발생했습니다: {e}")
        else:
            st.warning("상품 주요특징을 입력해 주세요.")

st.text_area("상품 네이밍 제안 20개", value=st.session_state.naming_result, height=250)
st.markdown("---")

h1, h2 = st.columns([2.2, 1.0], vertical_alignment="bottom")
with h1:
    st.subheader("상품정보 입력")
with h2:
    st.button("초기화", use_container_width=True, on_click=reset_all)

nonce = st.session_state.reset_nonce
left, right = st.columns(2)

with left:
    product_name = st.text_input("상품명", value="( color)", key=f"product_name_{nonce}")
    color = st.text_input("컬러", placeholder="예: 1 아이보리 2 연그레이 3 블랙", key=f"color_{nonce}")
    size = st.text_area("사이즈", height=90, value="FREE 사이즈로 77까지 추천드립니다.", key=f"size_{nonce}")
    material = st.text_input("소재", placeholder="예: 울6 텐셀45 레이온37 나일론12", key=f"material_{nonce}")
    material_desc = st.text_area(
        "소재설명",
        height=110,
        placeholder="예: 부드러운 촉감, 은은한 광택, 구김 적음, 여리한 실루엣",
        key=f"material_desc_{nonce}",
    )
    country = st.text_input("제조국", key=f"country_{nonce}")
    top_measure = st.text_area(
        "상의 실측사이즈",
        height=120,
        value="어깨단면 / 가슴둘레 / 암홀둘레 / 소매길이 / 소매둘레 / 총장 / 총장(앞) / 총장(뒤)  단위:cm",
        key=f"top_measure_{nonce}",
    )
    bottom_measure = st.text_area(
        "하의 실측사이즈",
        height=110,
        value="F 허리둘레 / 엉덩이둘레 / 허벅지둘레 / 밑단둘레 / 총장 / 밑위 길이  단위:cm\nL 허리둘레 / 엉덩이둘레 / 허벅지둘레 / 밑단둘레 / 총장 / 밑위 길이  단위:cm",
        key=f"bottom_measure_{nonce}",
    )
    dress_measure = st.text_area(
        "원피스 실측사이즈",
        height=130,
        value="어깨단면 / 가슴둘레 / 허리둘레 / 엉덩이둘레 / 암홀둘레 / 소매길이 / 어깨소매길이 / 총장(앞) / 총장(뒤)  단위:cm",
        key=f"dress_measure_{nonce}",
    )

with right:
    detail_tip = st.text_input("디테일 특징", placeholder="예: 브이넥, 타이 탈부착, 앞 절개라인, 소매 볼륨", key=f"detail_tip_{nonce}")
    fit = st.text_input("핏/실루엣", placeholder="예: 군살커버, 세련된 핏, 여리한 실루엣", key=f"fit_{nonce}")
    appeal_points = st.text_area(
        "주요 어필 포인트",
        height=150,
        placeholder="예: 구김 적음, 체형커버, 오피스룩, 하객룩, 데일리룩",
        key=f"appeal_points_{nonce}",
    )
    etc = st.text_area(
        "기타 특징",
        height=120,
        placeholder="예: 브랜드 퀄리티 고급소재",
        key=f"etc_{nonce}",
    )
    target = st.text_input("타겟", value="4050 여성", key=f"target_{nonce}")
    washing = st.text_input(
        "세탁방법",
        value="드라이클리닝, 단독 울세탁, 손세탁 권장. 건조기 사용 금지",
        key=f"washing_{nonce}",
    )
    additional_request = st.text_area(
        "추가/수정 요청사항 (출력물 확인 후 수정사항 입력)",
        height=120,
        key=f"additional_request_{nonce}",
    )

st.subheader("이미지 업로드")
uploaded_images = st.file_uploader(
    "이미지",
    type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True,
    key=f"uploaded_images_{nonce}",
)

if st.button("생성하기", type="primary", use_container_width=True, key=f"generate_{nonce}"):
    display_name = apply_color_count_to_name(product_name, color)
    measurement_lines = combine_measurements(top_measure, bottom_measure, dress_measure)
    data = {
        "product_name": product_name,
        "display_name": display_name,
        "color": color,
        "size": size,
        "material": material,
        "material_desc_raw": material_desc,
        "country": country,
        "measurement_lines": measurement_lines,
        "detail_tip": detail_tip,
        "fit": fit,
        "appeal_points": appeal_points,
        "etc": etc,
        "target": target,
        "washing": washing,
    }

    missing_fields = validate_required_inputs(data)
    if missing_fields:
        st.error("원고 생성을 위해 필수 정보를 입력해 주세요: " + ", ".join(missing_fields))
        st.stop()

    with st.spinner("출력물을 생성 중입니다..."):
        try:
            structured_raw = generate_structured_copy(data, additional_request, uploaded_images)
            structured = normalize_generated_strict(structured_raw)
            result = assemble_final_output(data, structured)
        except RateLimitError:
            st.error("현재 OpenAI 요청이 일시적으로 몰려 원고 생성을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.")
            st.stop()
        except Exception as e:
            st.error(f"원고 생성 중 오류가 발생했습니다: {e}")
            st.stop()

    # 세션에 저장 — TXT/HWP 버튼이 다운로드 후에도 사라지지 않음
    st.session_state.generated_result = result
    st.session_state.generated_docx = result_to_docx_bytes(result)
    st.session_state.generated_issues = editorial_issues(structured, data, additional_request)
    st.session_state.generated_visual_details = data.get("visual_details", [])
    st.session_state.generated_file_stem = (display_name or "page_builder").replace(" ", "_")

# ─── 결과 표시 (세션 기반) ───
if st.session_state.generated_result:
    if st.session_state.generated_visual_details:
        with st.expander("사진에서 확인된 디자인 특징 (원고 사용 전 직원 확인)", expanded=False):
            for detail in st.session_state.generated_visual_details:
                st.write("• " + detail)
    if st.session_state.generated_issues:
        with st.expander("원고 사실확인 필요 항목 (출력은 가능합니다)", expanded=False):
            for issue in st.session_state.generated_issues:
                st.write("• " + issue)
    st.text_area("결과", st.session_state.generated_result, height=1200)
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "TXT 다운로드",
            data=st.session_state.generated_result,
            file_name=st.session_state.generated_file_stem + "_output.txt",
            mime="text/plain",
            use_container_width=True,
        )
    with c2:
        st.download_button(
            "HWP 다운로드",
            data=st.session_state.generated_docx,
            file_name=st.session_state.generated_file_stem + "_output.hwp",
            mime="application/x-hwp",
            use_container_width=True,
        )

st.markdown("---")
st.markdown("© made by MISHARP, MIYAWA. All rights reserved.")
