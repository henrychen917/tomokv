#!/usr/bin/env python3
"""Refine the frozen caller inventory with reviewed parser scopes and actions."""
from pathlib import Path
import json
import subprocess

ROOT=Path(__file__).resolve().parents[2]
report=ROOT/'MEASURE-REQUEST-readability-a1.md'
non_source=set('''tests/_iofix.py tests/_lib.py tests/abba_saturation.py tests/aclfix.py tests/aof_frames.py tests/blockfix4_repro/lib/srv.py tests/climonfix4.py tests/datafix1_common.py tests/differ.py tests/differ_gate.sh tests/flipctl.py tests/flipfix5.py tests/hexpire.py tests/lottery_nightly.sh tests/matrix.sh tests/redis_tcl.py tests/rlcache_churn.py tests/scriptatomic.py tests/txnfix4.py tests/txnfix_audit/resp.py tests/wiredump.py'''.split())
review={
 'tests/lottery_nightly.sh':'Added a single-row gate entry for bounded correctness checks; default nightly selection is unchanged.',
 'tests/cfgfix.py':'Retained: parses the pinned Redis 7.4 reference config table; TomoKV edits do not alter that input.',
 'tests/cfgfix2.py':'Canonical stable roles for ELF allocation sites; nonempty inventory remains mandatory.',
 'tests/_serverfix_mutant.py':'Canonical stable roles for HLL symbols; requires both namespace bodies.',
 'tests/perfex_checks.py':'Canonical stable roles for ELF bodies and call operands; exact six/four body counts retained.',
 'tests/storesize_checks.py':'Token anchors and unique function scopes for the cold census instrumentation.',
 'tests/lottery_test_driver.py':'AST edits at stable Python comments; unique calls and nonempty sleep inventory.',
 'tests/scriptatomic_strict.py':'AST insertion at a stable Python bootstrap comment; strict refusal assertions retained.',
 'tests/r7shadow_pad.py':'Shared ELF role canonicalization; nonempty capability inventory and exact opcode checks retained.',
 'tests/r7shadow_noop.py':'Shared ELF/name canonicalization; existing body/clone/instruction controls retained.',
 'tests/exbatch_checks.py':'Shared ELF role canonicalization; exact patch-table and instruction checks retained.',
 'tools/exbatch_artifacts.py':'Shared ELF role canonicalization; numeric patch-table inventory, exact byte checks and nonempty selections retained.',
 'tools/storesize_artifacts.py':'Shared ELF role canonicalization; exactly two route bodies and exact opcode/layout checks retained.',
 'tests/tomo_assert_checks.py':'Stable role names for diagnostic inventory; physical lines validate macro presence; empty-input negative added.',
 'tools/persistfmt_schedule.py':'Token replacements with exact-one guards, including namespace insertion.',
 'tools/source_identity.py':'Existing lexer retained; empty production source inventory now rejected.',
 'tools/assert_map.py':'Existing lexer retained; empty CLI assertion inventory now rejected. Physical lines remain diagnostic output only.',
 'tools/wave14_capture.py':'Exact unique undefined-symbol roles in both namespaces; hook receives current mangled names.',
 'tools/lottery_build.py':'62 checked insertion sites, token replacements, two explicit publication markers; missing/duplicate anchors reject.',
 'tests/r7shadow_sync.py':'Stable function comments, token parity, required nonempty policy inventory; rename-aware regeneration.',
 'tools/reorder_sync.py':'Alias to the same token-based R7 generator; exact unique generated-region markers.',
 'tests/r7shadow_sync_test.py':'Whole-source scratch copy preserves type/callee role bindings; stale-copy and regeneration controls retained.',
 'tools/lbstall_artifacts.py':'Shared ELF name canonicalization for renamed stable roles; byte/relocation comparisons unchanged.',
 'tools/rlfence_artifacts.py':'Stable role translation for selected objdump symbol and disassembly labels; opcode checks unchanged.',
 'tools/ttlstate_proof.py':'LIVE ELF helper imports only. Historical source()/CLI fixed-line proof is not invoked by gate or make; retained with its library.',
 'tools/wave14.py':'LIVE ROOT/sha/save imports only; historical source-editing CLI is not invoked by the gate.',
 'tools/wave10.py':'Retained utility imports/historical receipt orchestration; frozen-reference commands are not replayed by ordinary gate.',
 'tools/wave10_normalize.py':'Instruction/literal parser, not C++ source; its audit uses shared canonical ELF names.',
 'tools/wave11_normalize.py':'Instruction/literal parser, not C++ source; its audit uses shared canonical ELF names.',
 'tools/exec1s_scope.py':'Retained instruction census helper; public main/namespace boundaries and supplied fixture paths, no C++ text patch.',
 'tools/wave13_counts.py':'Retained instruction census helper; public main/namespace boundaries and supplied fixture paths, no C++ text patch.',
 'tools/blockfix2_controls.py':'Live receipt/check paths retained. Six available source-control branches use exact token guards. Historical rename build branch already fails at frozen input; see limitations.',
 'tools/blockfix3_controls.py':'Retained live receipt/check paths; source controls delegate to the reviewed blockfix2 builder.',
 'tools/nullpublish_refreeze.py':'Gate/receipt text matcher; does not inspect production C++. Existing fixture/row tests retained.',
 'tests/nullpublish_refreeze_test.py':'Gate/receipt parser tests; unaffected by production C++ formatting.',
 'tests/gates_test.py':'Gate shell/receipt parser tests; all current source references remain explicit and fixture-checked.',
 'tests/gate.sh':'Existing job/label inventory retained; added source-tool tests inside the existing R7 parity row. No row or EXPECT change.',
}
changed=subprocess.check_output(['git','diff','5c3631281','--name-only','--diff-filter=ACM','--','tools','tests'],cwd=ROOT,text=True).splitlines()
for name in changed:
 if name.startswith('tools/archive/') or not name.endswith('.py') or name in non_source or name in review:continue
 if 'source_tokens' in (ROOT/name).read_text():
  review[name]='Token/role anchors and fail-closed inventory; see the per-tool formatted/rename/negative evidence.'
lines=report.read_text().splitlines();result=[];in_inventory=False
for line in lines:
 if line=='### Inventory':in_inventory=True
 if in_inventory and line.startswith('| `') and ' | ' in line:
  parts=line.split(' | ');name=parts[0].removeprefix('| `').removesuffix('`')
  if len(parts)==4 and not parts[1].startswith('FINISHED-LANE'):
   if name in non_source:
    parts[1]=parts[1].replace('; TEXT-MATCHER','');parts[3]=review.get(name,'Retained protocol/log/fixture reader; no production source matching.')+' |'
   elif name in review:
    if 'TEXT-MATCHER' not in parts[1]:parts[1]+='; TEXT-MATCHER'
    parts[3]=review[name]+' |'
   line=' | '.join(parts)
 result.append(line)
report.write_text('\n'.join(result)+'\n')
(ROOT/'docs/readability-a1/triage-overrides.json').write_text(json.dumps(dict(non_source=sorted(non_source),actions=review),indent=2,sort_keys=True)+'\n')
