"""Expose the shared source lexer to directly executed test scripts."""
from pathlib import Path
import importlib.util
import sys

_path = Path(__file__).resolve().parents[1] / 'tools/source_tokens.py'
_spec = importlib.util.spec_from_file_location('_tomo_source_tokens', _path)
_module = importlib.util.module_from_spec(_spec)
sys.modules.setdefault(_spec.name, _module)
_spec.loader.exec_module(_module)
globals().update({name: value for name, value in vars(_module).items() if not name.startswith('_')})
