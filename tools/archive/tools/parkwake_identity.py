#!/usr/bin/env python3
"""parkwake: linked-body inventory, PRE vs POST, with the gate's strict instruction normalizer.

docs/wave9/identity.py inventories every function group of a linked binary (after COMDAT
selection) through tests/reorder_noop.py with tools/wave12_normalize.py installed; no source-line
immediate, opcode, branch condition, member offset or register is masked. This compares one PRE and
one POST binary group by group and marks the hot groups with that tool's own hot selection.
Identity is a proxy: the instruction scopes (tools/parkwake_counts.py) and the maintainer's merit
run decide. No server or workload.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tests'), str(ROOT / 'docs/wave9')]
import identity  # noqa: E402
from wave12_normalize import install  # noqa: E402

install(identity.audit)
identity.OUT = ROOT / 'build/parkwake/identity'
# Bodies the change edits directly: every park path and loop pass (F1/F11/F12), the executor
# control pass and quiescence (F3/F12), execute()'s Retry arm (F2) and the batches that inline it,
# the namespace watchdog (item 4), the retry-lane consumer (F1) and the control publications (F10).
INTENDED = re.compile(
    r'::(?:r7_)?run_loop<|ExLoopT<(?:true|false)>::run\(|::flip_control_pass\(|::flip_quiesced\(|'
    r'::(?:r7_)?sweep<|::(?:r7_)?fused_pass_impl<|::service_notify_retries\(|::notify_sender_to\(|'
    r'::notify_retries_pending\(|::defer_completion_notice\(|blocking_notify_sender\(|'
    r'ExLoopT<(?:true|false)>::(?:execute|exec_batch|exec_batch_prefetched|execute_resumed)|'
    r'::service_(?:xshard_retries|atomic_deferred|ordered_deferred|multi_retries)<|'
    r'::database_control_pass\(|DatabaseMap::(?:monitor|drain_deadline_start|note_drain_waiting)\(|'
    r'multi_owner_pass_entry_impl<|multi_retry_lane_note_pending\(|'
    r'::lb_control_pass\(|lb_debug_move_client\(|monitor_controllers\(|cfgfix_rebind\(|'
    r'command_client_pause\(|::exclusive\(|multi_exec_io_commands\(|multi_retire\(|'
    r'climon_start_client_command\(|multi_execute_task|::wake_peers_from\(|::idle_timeout_ms\(')


def bodies_text(path, group):
    """objdump text of every body in a group, with RIP-relative displacements and absolute
    addresses masked; symbol names and in-function offsets are kept."""
    out = []
    for body in group:
        start = int(body['address'], 16)
        text = subprocess.check_output(['objdump', '-d', '--no-show-raw-insn', '-w',
                                        f'--start-address={start:#x}',
                                        f'--stop-address={start + body["size"]:#x}', str(path)], text=True)
        lines = []
        for line in text.splitlines():
            m = re.match(r'^\s*[0-9a-f]+:\s+(.*)$', line)
            if not m:
                continue
            ins = re.sub(r'\s*#.*$', '', m[1])
            ins = re.sub(r'-?0x[0-9a-f]+\(%rip\)', 'RIP', ins)
            ins = re.sub(r'\b[0-9a-f]+ <', '<', ins)
            lines.append(ins.strip())
        out.append(lines)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pre', type=Path)
    p.add_argument('post', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    pre, post = identity.inventory(a.pre), identity.inventory(a.post)
    rows = []
    for name in sorted(set(pre['groups']) | set(post['groups'])):
        before, after = pre['groups'].get(name, []), post['groups'].get(name, [])
        if identity.signature(before) == identity.signature(after):
            continue
        hot = bool(identity.GENERAL_HOT.search(name) or identity.HOT.search(name) or
                   re.search(r'::reply_(?:int|bulk|array_header)<|Op::Sink::reserve\(', name) or
                   re.search(r'ExLoopT<.*>::run\(', name) or
                   re.search(r'::(?:flush_ready|parse_and_dispatch|r7_flush_ready|serve)<', name))
        displacement_only = bool(before and after and [b['size'] for b in before] == [b['size'] for b in after]
                                 and bodies_text(a.pre, before) == bodies_text(a.post, after))
        rows.append(dict(name=name, hot=hot, intended=bool(INTENDED.search(name)),
                         displacement_only=displacement_only,
                         pre_sizes=[b['size'] for b in before], post_sizes=[b['size'] for b in after]))
    a.output.mkdir(parents=True, exist_ok=True)
    summary = dict(pre=dict(path=str(a.pre), sha256=pre['sha256'], groups=len(pre['groups'])),
                   post=dict(path=str(a.post), sha256=post['sha256'], groups=len(post['groups'])),
                   changed=len(rows), intended=sum(r['intended'] for r in rows),
                   displacement_only=[r['name'] for r in rows if r['displacement_only']],
                   hot_unintended=[r['name'] for r in rows if r['hot'] and not r['intended']
                                   and not r['displacement_only']],
                   other_unintended=[r['name'] for r in rows if not r['hot'] and not r['intended']
                                     and not r['displacement_only']])
    (a.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (a.output / 'changed-bodies.json').write_text(json.dumps(rows, indent=2) + '\n')
    (a.output / 'changed-bodies.md').write_text('\n'.join([
        '# Linked body differences, PRE vs POST', '',
        'Strict gate normalizer (docs/wave9/identity.py, tools/wave12_normalize.py). Identity is a proxy.', '',
        '| Function group | PRE bytes | POST bytes | Hot | Intended | Data displacement only |',
        '|---|---|---|---|---|---|',
        *[f"| `{r['name']}` | {r['pre_sizes']} | {r['post_sizes']} | {'yes' if r['hot'] else ''} | "
          f"{'yes' if r['intended'] else ''} | {'yes' if r['displacement_only'] else ''} |" for r in rows]]) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if not isinstance(v, list)} |
                     dict(displacement_only=len(summary['displacement_only']),
                          hot_unintended=len(summary['hot_unintended']),
                          other_unintended=len(summary['other_unintended'])), indent=1))
    for name in summary['hot_unintended']:
        print('HOT  ', name[:200])
    for name in summary['other_unintended']:
        print('other', name[:200])


if __name__ == '__main__':
    main()
