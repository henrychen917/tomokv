#!/usr/bin/env python3
"""Run the landed AT15b proofs, redirecting only their receipt directory."""
from pathlib import Path

source = Path('docs/at15b/prove.py')
text = source.read_text()
anchor = "out = Path('docs/at15b')"
assert text.count(anchor) == 1
Path('docs/storesize5/at15b').mkdir(exist_ok=True)
exec(compile(text.replace(anchor, "out = Path('docs/storesize5/at15b')"), str(source), 'exec'))
