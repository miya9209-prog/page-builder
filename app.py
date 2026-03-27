# FIXED VERSION (string error resolved)

def build_prompt_text(existing_text=""):
    lines = [
        "- 입력칸 문구를 그대로 복붙하지 말고 쇼핑몰용 문장으로 재작성",
        "- 문장은 끊기지 않고 자연스럽게 이어지도록 작성",
        "- 빈 섹션 없이 모든 항목 채우기"
    ]
    return existing_text + "\n" + "\n".join(lines)
