#!/usr/bin/env python3
"""Inventory the sixteen AT15/AT15b commits by production source identity."""
import json
from pathlib import Path
import subprocess


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


commits = git('rev-list', '--first-parent', '--reverse', 'origin/cpp..657353693').splitlines()
assert len(commits) == 16
rows = []
for commit in commits:
    rows.append(dict(commit=commit, subject=git('show', '-s', '--format=%s', commit),
                     src_tree=git('rev-parse', commit + ':src'),
                     makefile=git('rev-parse', commit + ':Makefile'),
                     lua_tree=git('rev-parse', commit + ':third_party')))
Path('docs/at15c/commit-inventory.json').write_text(json.dumps(rows, indent=2) + '\n')
for row in rows:
    print(row['commit'][:9], row['src_tree'][:12], row['makefile'][:12], row['subject'])
