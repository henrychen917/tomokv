#!/usr/bin/env python3
"""Rootcompat PAD-A exact-image pair; builds only, never starts a workload."""
from pathlib import Path
from exec1s_pad import build

root = Path(__file__).resolve().parents[1]
if __name__ == '__main__':
    out = root / 'build/rootcompat'
    out.mkdir(parents=True, exist_ok=True)
    build(out / 'pre-source', root, out, root / 'docs/rootcompat/pad-a.json')
