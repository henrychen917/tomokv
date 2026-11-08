#!/usr/bin/env python3
"""Prepare disposable source-format/rename fixtures; never build or boot."""
from pathlib import Path
import shutil,subprocess,sys,json
root=Path(__file__).resolve().parents[2];work=root/'build/readability-a1'
sys.path.insert(0,str(root/'tools'));import source_tokens as cpp
clang=work/'python/clang_format/data/bin/clang-format'
assert 'version 18.1.8' in subprocess.check_output([str(clang),'--version'],text=True)
settings='BasedOnStyle: Google\nColumnLimit: 100\nSortIncludes: Never\nBreakStringLiterals: false\nInsertBraces: false\nQualifierAlignment: Leave\n'
for shape in ('current','formatted','renamed'):
 target=work/shape
 for folder in ('src','tests','tools','third_party'):
  if (target/folder).exists():shutil.rmtree(target/folder)
  shutil.copytree(root/folder,target/folder,ignore=shutil.ignore_patterns('archive','__pycache__'))
 shutil.copy2(root/'Makefile',target/'Makefile')
 for document in ('docs/CONFIGURATION.md','docs/wave8/helper-assert-pins.json'):
  (target/document).parent.mkdir(parents=True,exist_ok=True)
  shutil.copy2(root/document,target/document)
 (target/'.clang-format').write_text(settings)
 paths=sorted(p for p in (target/'src').rglob('*') if p.suffix in ('.cc','.h','.inc'))
 if shape!='current':
  subprocess.run([str(clang),'-i',*[str(p) for p in paths]],check=True)
 if shape=='renamed':
  names={old:'a1_role_'+old for p in paths for old in cpp.bindings(p.read_text())}
  for p in paths:p.write_text(cpp.rename(p.read_text(),names))
  (work/'rename-map.json').write_text(json.dumps(names,indent=2)+'\n')
 for folder in ('build/proof','build/flushfix3/work-reference'):
  if (target/folder).exists():shutil.rmtree(target/folder)
 print(shape,len(paths),flush=True)
