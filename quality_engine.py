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
    }
    result = {}
    for label, blocks in fields.items():
        vals = []
        for b in blocks:
            for fact in split_facts(b, 8):
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
            if not isinstance(lines, list) or len([x for x in lines if compact(x)]) < 3:
                problems.append(f"md_sections.{field}: 정보가 담긴 문장/단락 3개 이상 필요합니다.")
            elif sum(len(compact(x)) for x in lines) < 115:
                problems.append(f"md_sections.{field}: 설명이 지나치게 짧습니다.")
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
    # 누락된 사실만 잡기 위한 보수적인 신호: 3글자 이상 핵심 토큰을 하나도 사용하지 않은 입력 묶음
    facts = input_facts(data, additional_request)
    for group in ("디테일", "핏·체형", "구매 포인트", "소재·촉감"):
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
