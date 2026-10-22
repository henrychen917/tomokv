#!/usr/bin/env python3
"""Select tested budgets; strict body deltas precede proximity to preserved headroom."""
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'docs/compat2b'
rows=[json.loads(p.read_text()) for d in ('initial','round1','round2')
 for p in (OUT/'trials'/d).glob('*.json') if p.name!='summary.json']
refs={r['object']:r for r in rows if r['tree']=='headline'}
assert len(refs)==29 and all(r['changed']==0 for r in refs.values())
source=(ROOT/'Makefile').read_text(); selected=[]
for obj in sorted(refs):
 choices=[r for r in rows if r['object']==obj and r['tree']=='post']
 initial=next(r for r in choices if 'budget' not in r)
 pattern=r'(\$\(BUILD_ROOT\)/'+re.escape(obj)+r':[^\n]*large-unit-insns=)(\d+)'
 old=int(re.search(pattern,source)[2]); center=old+initial['unit']-refs[obj]['unit']
 score=lambda r:(r['residual_hot'],r['residual'],r['changed'],abs(r.get('budget',old)-center),abs(r.get('budget',old)-old))
 best=min(choices,key=score); new=best.get('budget',old)
 # When the baseline emits the exact same bodies, keep the established budget.
 if score(initial)[:3]==score(best)[:3]:best=initial;new=old
 selected.append(dict(object=obj,old=old,budget=new,unit_growth=initial['unit']-refs[obj]['unit'],
 trials=len(choices),selected_trial=best))
 source=re.sub(pattern,lambda m:m[1]+str(new),source)
comment='# compat2b: 29 reference recompiles and merged compile-only trials select the\n# per-unit budgets in docs/compat2b/selected.json. Preserve headline or compat2\n# hot bodies; composed C1/N3/N4 dispatchers remain explicit merit inputs.\n'
source=source.replace('$(BUILD_ROOT)/src/main.o: override',comment+'$(BUILD_ROOT)/src/main.o: override')
(ROOT/'Makefile').write_text(source);(OUT/'selected.json').write_text(json.dumps(selected,indent=2)+'\n')
for r in selected:
 print(r['object'],r['old'],'->',r['budget'],'hot residual',r['selected_trial']['residual_hot'])
