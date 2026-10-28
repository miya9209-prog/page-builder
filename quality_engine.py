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
        f'상품: {name}',f'확인된 디테일/핏/포인트: {known or "명시 입력 없음"}',
        f'확인된 원단 특징: {material or "미입력"}',
        f'실측: {measurement or "미입력"}',
        '섹션 역할 배분:',
        '1) choice: 고객이 겪는 구체적인 구매 고민 → 해당 상품의 확인된 특징 → 선택할 이유. 소재 성분·컬러·사이즈 나열 금지',
        '2) fabric: 혼용률·촉감·질감·관리 주의. 두께/보온성은 직접 확인된 경우만. 의류 소재와 색상 혼동 금지',
        '3) fit: 확인된 실측, 사이즈 표기, 형태/핏. 숫자만으로 착용감을 보증하지 않기. 총장으로 힙커버를 단정하지 않기',
        '4) occasion: 상품의 형태·색상에 근거한 구체적인 코디 2~3가지와 TPO. 상품 특징 요약 반복 금지',
        'FAQ: 단순 색상·소재·사이즈를 묻는 기본정보 질문보다 부해 보임/77체형·이너 여유/구김·관리/실제 코디 등 구매 불안을 다루되 답변은 조건부·근거 중심',
        '추천문장: 다른 니즈 네 가지. 실측/촉감/관리/스타일 등 근거 있는 특징을 고객 문제와 연결',
        '착용 체크 포인트: 실제 후기 근거가 없으면 1인칭 경험담 대신 확인해야 할 실용 포인트 4개',
        '체형팁: 55/66/66반/77별 실측 비교 시 참고사항만; 모델 실착 근거 없이 활동성·힙덮음·슬림효과 단정 금지',
        '입력 정보 부족: ' + ('; '.join(gaps) if gaps else '상세 입력값 사용 가능'),
    ])
