#!/usr/bin/env python3
"""Use the unchanged at15b PAD-A builder with only at15c output paths."""
from pathlib import Path

original = Path('docs/at15b/build_pad.py')
source = original.read_text()
source = source.replace("post = Path('build/at15b-post')", "post = Path('build/at15c-post')")
source = source.replace("pad = Path('build/at15b-pad-a')", "pad = Path('build/at15c-pad-a')")
source = source.replace("Path('build/at15b-padding.S')", "Path('build/at15c-padding.S')")
source = source.replace("Path('docs/at15b/", "Path('docs/at15c/")
exec(compile(source, str(original), 'exec'))
