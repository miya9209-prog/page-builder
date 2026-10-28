"""로컬 무API 회귀 테스트: 상품 정보 반영, 문법, 원고 품질 게이트, 출력 형식."""
import ast
import io
import json
import re
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from quality_engine import (
    TIP_PROFILES, check_quality, normalize_generated_strict,
    natural_wrap, check_structure,
)


def app_functions():
    source = (HERE / 'app.py').read_text(encoding='utf-8')
    source_ast = ast.parse(source)
    keep = {'build_generation_prompt', 'generate_structured_copy', 'render_subsc_html',
            'render_text_source', 'build_subtap_html', 'assemble_final_output',
            'result_to_docx_bytes', 'add_blue_divider', 'format_material_line',
            'format_measurement_lines', 'extract_json', 'clean_line'}
    code = ast.Module(body=[n for n in source_ast.body if isinstance(n, ast.FunctionDef) and n.name in keep], type_ignores=[])
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt
    from quality_engine import fact_report
    namespace = dict(json=json, io=io, re=re, TIP_PROFILES=TIP_PROFILES,
                     fact_report=fact_report, check_quality=check_quality,
                     normalize_generated_strict=normalize_generated_strict,
                     natural_wrap=natural_wrap, Document=Document, OxmlElement=OxmlElement, qn=qn, Pt=Pt,
                     RateLimitError=RuntimeError, DIVIDER_MARKER="────────────────────────────────────────",
                     FIXED_HTML_HEAD='<meta charset="UTF-8">')
    exec(compile(code, str(HERE / 'app.py'), 'exec'), namespace)
    return namespace


def product(category='블라우스'):
    if category == '블라우스':
        return dict(display_name='비비안 브이넥 타이 블라우스 (3 color)', color='아이보리 / 연그레이 / 블랙',
                    size='FREE 77까지', material='텐셀 45% 레이온 37%',
                    material_desc_raw='부드러운 터치감, 은은한 광택', detail_tip='탈부착 타이, 소매 핀턱',
                    fit='팔뚝 군살 커버, 복부 여유핏', appeal_points='하객룩, 구김 적음', etc='',
                    target='4050 여성', washing='드라이클리닝 권장, 건조기 사용 금지',
                    measurement_lines=['어깨단면37 / 가슴둘레106 / 총장63.5'], country='한국')
    if category == '슬랙스':
        return dict(display_name='매그 S 639 부츠컷 슬랙스', color='네이비 / 블랙', size='S M L',
                    material='폴리에스터 95%, 스판 5%', material_desc_raw='텐션이 높고 복원력 좋음',
                    detail_tip='부츠컷, 허리 밴딩', fit='허벅지 여유, 다리선 슬림',
                    appeal_points='오피스룩, 구김 적음', etc='', target='4050 여성',
                    washing='찬물 손세탁 권장', measurement_lines=['S 허리둘레 66 / 총장 96'], country='한국')
    return dict(display_name='하이넥 스트링 야상', color='카키', size='FREE 77까지', material='코튼 100%',
                material_desc_raw='피치 가공 표면', detail_tip='하이넥, 밑단 스트링',
                fit='여유로운 어깨, 힙 덮는 기장', appeal_points='간절기 아우터, 여행', etc='',
                target='4050 여성', washing='단독 세탁', measurement_lines=['어깨단면 55 / 총장 70'], country='한국')


def draft_for(data):
    source = ' '.join(str(data[k]) for k in ('detail_tip', 'fit', 'appeal_points', 'material', 'material_desc_raw'))
    md_templates = {
      "choice": [
        f"{data['display_name']}의 가장 중요한 특징은 {data['detail_tip']}이라는 디테일입니다. 이런 구성이 필요한 장면을 명확하게 설명할 수 있습니다.",
        f"{data['appeal_points']}이라는 고객의 불편을 기준으로 해당 상품의 선택 이유를 구체적으로 살펴볼 수 있습니다. 단순한 광고 문구를 피합니다.",
        "실측과 상세 소재 설명을 먼저 확인하고, 평소 선호하는 옷과 비교하여 자신에게 적합한지를 판단하는 편이 좋습니다. 상품의 실제 정보가 선택 기준입니다."
      ],
      "fabric": [
        f"소재 구성은 {data['material']}이며 원단 설명에는 {data['material_desc_raw']}이라고 나와 있습니다. 이 정보를 바탕으로 감촉과 표면 특성을 이해할 수 있습니다.",
        "두께와 질감은 착용 계절을 가늠하는 중요한 기준이지만, 입력되지 않은 온도 적합성이나 기능을 확정적으로 안내하지 않습니다.",
        "관리 안내도 확인된 세탁법을 우선해야 하므로, 고객이 케어라벨 정보를 확인하도록 설명하는 것이 중요합니다."
      ],
      "fit": [
        f"핏에서 확인할 사항은 {data['fit']}으로 정리됩니다. 취향과 체형에 따라 같은 사이즈라도 느낌이 달라질 수 있습니다.",
        f"사이즈는 {data['size']}입니다. 평소 자주 입는 상품의 실측과 비교하면 원하는 실루엣을 이해하는 데 도움이 됩니다.",
        "착용 시 답답함과 움직임의 여유는 개인차가 있으므로, 정확한 사이즈 선택은 표기된 치수와 체형을 함께 고려해야 합니다."
      ],
      "occasion": [
        f"활용 장면은 {data['appeal_points']}을 참고하는 것이 좋습니다. 실제 디테일인 {data['detail_tip']}에 따라 코디 분위기가 달라집니다.",
        "평소 즐겨 입는 하의와 아우터를 함께 고려하면 활용도를 판단할 수 있고, 특별한 날에만 입게 되는 옷인지도 구분할 수 있습니다.",
        "자주 입는 색상과 계절감을 비교하여 조합을 선택하면 여러 상황에 맞춰 활용할 수 있으므로, 자신의 옷장 속 기본 아이템을 떠올려 보는 것이 좋습니다."
      ]
    }
    return {'material_desc_lines': [f'{source}로 이해할 수 있습니다.', f'{source}를 참고해 선택합니다.', f'{source}가 상품의 주요 특징입니다.'],
      'recommend_lines': [f'{data["detail_tip"]}을 찾는 분', f'{data["fit"]}을 원하는 분', '착용할 때의 편안함을 원하는 분', '관리의 편리함을 중요하게 생각하시는 분'],
      'review_lines': ['실측과 소재를 비교해 보기 좋은 상품이에요.', '평소 착용하는 옷과 비교하여 선택할 수 있어요.', '소재 정보와 핏을 함께 확인해보세요.', '상세 사이즈표가 선택에 도움이 됩니다.'],
      'faqs': [{'q': 'Q. 소재가 무엇인가요?', 'a': 'A. ' + str(data['material'])}, {'q': 'Q. 디테일은 어떤가요?', 'a': 'A. ' + str(data['detail_tip'])}, {'q': 'Q. 사이즈는 어떤가요?', 'a': 'A. ' + str(data['size'])}, {'q': 'Q. 세탁법은요?', 'a': 'A. ' + str(data['washing'])}],
      'md_sections': md_templates,
      'size_tips': {x: [f'{TIP_PROFILES[x]} 기준에서 실측과 기존 옷을 비교해 주세요.', f'{TIP_PROFILES[x]}은 개인차를 고려해 선택하세요.'] for x in TIP_PROFILES}}


class RepoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = app_functions()

    def test_unchanged_ui_and_downloads(self):
        s = (HERE/'app.py').read_text(encoding='utf-8')
        for piece in ['st.title("MISHARP PAGE BUILDER")', 'TXT 다운로드', 'HWP 다운로드',
                      'generated_result', 'generated_docx', 'DIVIDER_MARKER', 'ㅇ55 (90) 160cm 50kg']:
            self.assertIn(piece, s)
        self.assertNotIn('✓쇼핑에 꼭 참고하세요</h3>', s)

    def test_prompt_has_specific_product_facts(self):
        for category in ['블라우스', '슬랙스', '야상']:
            d=product(category)
            prompt=self.f['build_generation_prompt'](d, '사실 근거로 설명')
            for field in ('display_name','detail_tip','fit','appeal_points','material'):
                self.assertIn(str(d[field]), prompt)
            self.assertIn('입력된 한 상품', prompt)

    def test_generic_fallback_disallowed(self):
        d=product('블라우스')
        draft=draft_for(d)
        draft['recommend_lines'] = draft['recommend_lines'][:1]
        issues=check_quality(draft,d)
        self.assertTrue(any('recommend_lines' in s for s in issues))
        with self.assertRaises(ValueError):
            normalize_generated_strict(draft)

    def test_no_cross_product_text(self):
        for category in ['블라우스','슬랙스','야상']:
            d=product(category)
            result=normalize_generated_strict(draft_for(d))
            assembled=self.f['assemble_final_output'](d,result)
            self.assertIn(d['display_name'],assembled)
            for term in ('비비안', '매그', '야상'):
                if term not in d['display_name']:
                    self.assertNotIn(term, assembled)
            self.assertEqual(assembled.count('────────────────────────────────────────'), 1)
            self.assertNotIn('✓쇼핑에 꼭 참고하세요', assembled)
            self.assertNotIn('[구매 전 꼭 확인해 주세요]', assembled)
            for label in ('ㅇ55 (90) 160cm 50kg', 'ㅇ66 (95) 162cm 55kg', 'ㅇ66반 (95) 163cm 59kg','ㅇ77 (100) 161cm 62kg'):
                self.assertIn(label, assembled)

    def test_hwp_blue_line_and_txt_line(self):
        d=product()
        result=normalize_generated_strict(draft_for(d))
        assembled=self.f['assemble_final_output'](d,result)
        b=self.f['result_to_docx_bytes'](assembled)
        self.assertGreater(len(b),1000)
        # HWP 다운로드는 현재 레포가 내부적으로 생성하는 Word 호환 바이너리임 (기존 동작 유지)
        from docx import Document
        doc=Document(io.BytesIO(b))
        borders=[]
        for p in doc.paragraphs:
            pPr=p._p.pPr
            if pPr is not None and pPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pBdr') is not None:
                borders.append(p)
        self.assertEqual(len(borders),1)
        line=borders[0]._p.xml
        self.assertIn('2F6DF6', line)
        pos=next(i for i,p in enumerate(doc.paragraphs) if p._p.xml == borders[0]._p.xml)
        self.assertEqual([p.text for p in doc.paragraphs[pos-2:pos]],['',''])
        self.assertEqual([p.text for p in doc.paragraphs[pos+1:pos+3]],['',''])

    def test_content_gate_and_wrapping(self):
        d=product()
        draft=draft_for(d)
        self.assertFalse(check_quality(draft,d), check_quality(draft,d))
        self.assertTrue(all(len(x)<=24 for x in natural_wrap('이 원단은 은은하게 흐르는 질감이 자연스럽게 표현되어 체형에 따라 서로 다른 착용감이 느껴질 수 있습니다.',24)))

    def test_engine_draft_and_revision_integration_mock(self):
        d=product()
        initial=draft_for(d)
        incomplete=dict(initial, recommend_lines=initial['recommend_lines'][:1])
        calls=[]
        def fake_chat_with_retry(**kwargs):
            calls.append(kwargs)
            contents = json.dumps(incomplete if len(calls)==1 else initial, ensure_ascii=False)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=contents))])
        self.f['chat_with_retry']=fake_chat_with_retry
        self.f['file_to_content_item']=lambda image: None
        result=self.f['generate_structured_copy'](d,'',[])
        self.assertEqual(len(calls),2)
        self.assertEqual(len(result['recommend_lines']),4)
        self.assertIn('탈부착', str(calls[0]['messages']))
        self.assertIn('recommend_lines', str(calls[1]['messages']))


if __name__ == '__main__':
    unittest.main()
