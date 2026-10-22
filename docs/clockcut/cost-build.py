#!/usr/bin/env python3
"""Expose only ExLoopT's private section in an uncommitted test header copy."""
from pathlib import Path
import subprocess
root=Path(__file__).resolve().parents[2]
header=(root/'src/core/ex_loop.h').read_text()
prefix,body=header.split('class ExLoopT {',1)
assert body.count('\nprivate:')==1
copy=prefix+'class ExLoopT {'+body.replace('\nprivate:', '\npublic:',1)
(root/'build/clockcut/clock-access.h').write_text(copy)
subprocess.run(['g++','-std=c++20','-O2','-g','-Wall','-Wextra','-march=native','-pthread',
 '-DTOMO_JEMALLOC','-ffunction-sections','-fdata-sections','-Ibuild/clockcut','-iquote','src/core','-I.',
 'docs/clockcut/cost.cc','-Wl,--gc-sections','-ljemalloc','-luring','-lssl','-lcrypto',
 '-o','build/clockcut/cost'],cwd=root,check=True)
