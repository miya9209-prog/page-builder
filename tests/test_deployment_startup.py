"""Smoke test: app starts even if quality_engine installed/deployed is old."""
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / 'app.py'

class StreamlitStop(Exception):
    """Emulate st.stop on missing API key, after app initialization."""


class SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)
    def __setattr__(self, name, value):
        self[name] = value


class DeploymentSmokeTest(unittest.TestCase):
    def test_cold_start_without_quality_engine_dependency(self):
        st = types.ModuleType('streamlit')
        st.session_state = SessionState()
        st.secrets = {}  # Missing key intentionally stops before first API call.
        st.set_page_config = lambda *a, **kw: None
        st.markdown = lambda *a, **kw: None
        st.title = lambda *a, **kw: None
        st.caption = lambda *a, **kw: None
        st.warning = lambda *a, **kw: None
        st.stop = lambda: (_ for _ in ()).throw(StreamlitStop())

        # An intentionally incompatible old quality_engine must not affect startup.
        old_engine = types.ModuleType('quality_engine')
        old_engine.TIP_PROFILES = {'55': 'old-version'}
        openai = types.ModuleType('openai')
        openai.OpenAI = lambda *a, **kw: None
        openai.RateLimitError = type('RateLimitError', (Exception,), {})
        with patch.dict(sys.modules, {'streamlit': st, 'quality_engine': old_engine, 'openai': openai}):
            with self.assertRaises(StreamlitStop):
                runpy.run_path(str(APP), run_name='__main__')
        self.assertIn('generated_result', st.session_state)
        self.assertIn('generated_docx', st.session_state)

if __name__ == '__main__':
    unittest.main()
