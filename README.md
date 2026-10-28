# MISHARP PAGE BUILDER

Streamlit 기반 상세페이지 카피 생성기. 원고 초안, 검수, TXT 및 문서 다운로드를 지원합니다.

## 실행
```bash
pip install -r requirements.txt
streamlit run app.py
```

Streamlit Secrets에서 `OPENAI_API_KEY`를 설정해야 합니다.

## 테스트
```bash
python -m unittest discover -s tests -v
```

변경 상세 및 기존 출력 호환성 주의사항은 `VALUE_EDITOR_UPDATE_20261028.md` 참조.
