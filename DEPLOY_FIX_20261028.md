# 페이지빌더 Streamlit ImportError 수정 (2026-10-28)

## 문제

Streamlit Cloud 실행 시 `app.py`의 `from quality_engine import (... apply_grounded_safety, validate_required_inputs)` 지점에서 `ImportError`가 발생했습니다.

## 원인 및 조치

- 이전 개선본에는 두 함수가 없고 V5 품질 모듈에 새로 추가되어, GitHub에서 `app.py`만 바뀌거나 이전 `quality_engine.py`가 남으면 시작할 수 없습니다.
- 이번 패키지는 **V5의 동일한 quality_engine 코드가 `app.py`에 포함**되어, Streamlit 앱 실행이 외부 품질 모듈 버전에 의존하지 않도록 변경했습니다.
- `quality_engine.py`는 독립 테스트 및 유지보수용으로 그대로 포함했습니다.
- 원고 생성 로직/프롬프트/화면/다운로드/사이즈팁은 V5에서 변경하지 않았습니다.

## GitHub 반영

**중요:** ZIP 자체를 GitHub에 파일 하나로 올리지 마세요. ZIP의 `page-builder-main` 폴더 **안에 있는 파일들을 레포 루트(`/app.py`가 위치한 곳)**에 복사·커밋해야 합니다. `app.py`만 교체해도 이번 ImportError는 재발하지 않도록 수정되어 있으나, 전체 레포 내용을 함께 업데이트하는 것이 권장됩니다.

Streamlit Cloud `Manage app` → `Reboot app`으로 재시작하고, 에러 없이 입력 폼이 표시되는지 확인해 주세요.

## 검증

- 기존 회귀 테스트 34개 + 배포 초기 구동 테스트
- Python 구문/독립 품질 모듈 전체 함수 일치/ZIP 무결성
- 실제 Streamlit Cloud 및 OpenAI API 라이브 호출은 로컬에서 확인하지 않았습니다.
