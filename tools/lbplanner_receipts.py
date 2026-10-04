#!/usr/bin/env python3
"""Serverless instruction/load and layout receipts; no clocks, perf events or live server."""
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from lbstall_artifacts import Elf
from rlfence_artifacts import tables

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/lbplanner'
OUT.mkdir(parents=True, exist_ok=True)


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n')


def layout():
    script = ROOT / 'build/lbplanner-layout.gdb'
    script.write_text('''set pagination off
python
import gdb,json
expected = dict(Op=336,Client=1984,ThreadCtx=1408,Shard=1440,FlatStore=944,AtomicEntry=144,Config=624)
expected['Rob<64>'] = 192
rows = {}
for ns in ('tomo','tomo_db0'):
    sizes = {name:int(gdb.lookup_type(ns+'::'+name).sizeof) for name in expected}
    assert sizes == expected, (ns,sizes)
    fields = {}
    for name in ('Server','IoLoop'):
        t = gdb.lookup_type(ns+'::'+name)
        fields[name] = dict(size=int(t.sizeof), offsets={f.name:int(f.bitpos)//8 for f in t.fields() if hasattr(f,'bitpos')})
    rows[ns] = dict(locked=sizes, fields=fields)
print('LAYOUT='+json.dumps(rows))
end
''')
    rows = {}
    for arm, binary in [('PRE', ROOT / 'build/lbplanner-pre/tomokv'), ('POST', ROOT / 'build/tomokv')]:
        result = subprocess.run(['gdb', '-nx', '-q', '-batch', str(binary), '-x', str(script)],
                                capture_output=True, text=True, check=True)
        (OUT / f'{arm}-layout.log').write_text(result.stdout + result.stderr)
        rows[arm] = json.loads(next(line[7:] for line in result.stdout.splitlines() if line.startswith('LAYOUT=')))
        tables(Elf(binary), OUT, arm)
    launch_script = ROOT / 'build/lbplanner-launch-layout.gdb'
    rows['LAUNCH'] = {}
    for ns, suffix in [('tomo', ''), ('tomo_db0', '-db0')]:
        launch_script.write_text(script.read_text().replace("for ns in ('tomo','tomo_db0'):",
                                                          f"for ns in ({ns!r},):"))
        result = subprocess.run(['gdb', '-nx', '-q', '-batch',
                                 str(ROOT / f'build/lbplanner-launch-layout{suffix}.o'), '-x', str(launch_script)],
                                capture_output=True, text=True, check=True)
        (OUT / f'LAUNCH-{ns}-layout.log').write_text(result.stdout + result.stderr)
        data = json.loads(next(line[7:] for line in result.stdout.splitlines() if line.startswith('LAYOUT=')))
        rows['LAUNCH'][ns] = data[ns]
        # Exact equality: the fix introduces no member, size, or offset change.
        assert data[ns] == rows['POST'][ns], ('launch/POST layout changed', ns)
    differences = []
    for ns in rows['PRE']:
        before, after = rows['PRE'][ns], rows['POST'][ns]
        assert before['locked'] == after['locked']
        for kind in ('Server', 'IoLoop'):
            if before['fields'][kind]['size'] != after['fields'][kind]['size']:
                differences.append(dict(namespace=ns, type=kind, member='sizeof',
                    before=before['fields'][kind]['size'], after=after['fields'][kind]['size']))
            for name, offset in before['fields'][kind]['offsets'].items():
                new_name = 'lb_pause_id_' if name == 'lb_controller_beat_ms_' else name
                actual = after['fields'][kind]['offsets'].get(new_name)
                if actual != offset:
                    differences.append(dict(namespace=ns, type=kind, member=name, before=offset, after=actual))
    write('layout.json', rows)
    write('layout-comparison.json', dict(launch_revision='6c9cb4b85', launch_post_exact=True,
          historical_pre_post_existing_offsets_and_sizes_equal=not differences,
          historical_pre_post_differences=differences, all_eight_locked_sizes_equal=True))
    for arm in ('PRE', 'POST'):
        for kind in ('functions', 'sections'):
            path = OUT / f'{arm}-{kind}.tsv'
            with gzip.GzipFile(filename=str(path)+'.gz', mode='wb', mtime=0) as f:
                f.write(path.read_bytes())
            path.unlink()
    return rows


def costs(rows):
    tracer = ROOT / 'build/lbplanner-trace'
    stage = rows['POST']['tomo']['fields']['Server']['offsets']['lb_stage_']
    pause = rows['POST']['tomo']['fields']['IoLoop']['offsets']['lb_pause_id_']
    results = []
    for arm, negative in [('PRE', False), ('POST', False), ('POST', True), ('PAD-A', False)]:
        binary = (ROOT / dict(PRE='build/lbplanner-pre-pass', POST='build/lbplanner-unit', **{'PAD-A': 'build/lbplanner-unit-pad'})[arm]).resolve()
        elf = Elf(binary)
        sec = elf.sections[elf.names.index('.text')]
        asm = subprocess.check_output(['objdump', '-dw', str(binary)], text=True)
        instructions = {}
        for line in asm.splitlines():
            match = re.match(r'\s*([0-9a-f]+):\s+(?:[0-9a-f]{2} )+\s*(.*)', line)
            if match:
                instructions[int(match[1],16)] = match[2]
        symbol = 'lbplanner_io_pass' + ('_negative' if negative else '')
        address = elf.functions()[symbol]['value']
        for count in (1, 32, 4096):
            command = [str(tracer), str(binary), ('n' if negative else 'p' if arm == 'PAD-A' else '')+str(count),
                       f'{address:x}', f'{sec[3]:x}', f'{sec[5]:x}', str(int(elf.kind==3))]
            result = subprocess.run(command, text=True, capture_output=True, timeout=60, check=True)
            lines = result.stdout.splitlines()
            trace = json.loads(next(line[6:] for line in lines if line.startswith('TRACE=')))
            sites = json.loads(next(line[6:] for line in lines if line.startswith('SITES=')))
            executed = [dict(address=address, visits=visits, instruction=instructions[int(address,16)])
                        for address, visits in sites.items()]
            # Only instructions actually retired with the production stage pinned Idle.
            # Reads have the offset in the source operand; stores are excluded explicitly.
            def loads(offset):
                pat = re.compile(r'^mov\w*\s+(?:0x)?'+f'{offset:x}'+r'\(%[a-z0-9]+\),%')
                return [x for x in executed if pat.search(x['instruction'])]
            shared, local = loads(stage), loads(pause)
            nshared = sum(x['visits'] for x in shared)
            expected_shared = count + 1 if arm in ('PRE', 'PAD-A') else count + 2 if negative else 2
            assert nshared == expected_shared, (symbol,count,nshared,shared)
            if arm == "POST":
                assert sum(x["visits"] for x in local) == count, ("one private gate load per connection",count,local)
            results.append(dict(arm=arm, negative=negative, connections=count, trace=trace,
                                stage_loads=nshared, cache_loads=sum(x['visits'] for x in local),
                                load_sites=shared+local, executed=executed))
    write('instructions.json', dict(stage='Idle', stage_offset=stage, pause_offset=pause,
        scope='Real pass-start snapshot, repeated production inline parse gate, then control tail; no parser/network/command execution.',
        positive='exactly two shared stage loads independent of connection count: pass start and control tail',
        negative='reintroduced per-connection stage load rejected at every count', rows=results))
    print('PASS pinned IO pass: two shared stage loads at 1/32/4096 connections; extra-load controls detected')


def source():
    pre = subprocess.check_output(['git','show','cd02ecbab:src/core/server.h'],text=True,cwd=ROOT)
    post = (ROOT/'src/core/lbplanner.cc').read_text().split('// These PRE bodies are comparison material')[0]
    # Exact policy blocks, excluding only indentation and the separately audited hosting/hand-off.
    def block(text,start,end):
        return re.sub(r'\s+', ' ', text[text.index(start):text.index(end,text.index(start))]).strip()
    anchors = [('auto spread =', 'std::vector<LbShardMove> shard_plan;'),
               ('const double band = lb_policy_->key_jitter.band', 'for (uint32_t step'),
               ('WeightedLbMoveChoice choice;', 'shard_after = spread(loads, executors);'),
               ('LbClientMove client_plan;', 'std::lock_guard<std::mutex> transition_lock(shape_transition_mu_);')]
    proofs = []
    for start,end in anchors:
        a,b = block(pre,start,end), block(post,start,end)
        if start.startswith('const double band'):
            b = b.replace(' const uint32_t move_cap = lb_policy_->move_cap(nshards());', '')
        assert a == b, ('admission/search changed',start)
        proofs.append(dict(start=start,end=end,sha256=hashlib.sha256(a.encode()).hexdigest()))
    assert post.count('const uint32_t move_cap = lb_policy_->move_cap(nshards());') == 1
    assert 'step < move_cap;' in post and 'step < lb_policy_' not in post
    for file in ('src/core/io_loop.h','src/core/reorder.cc'):
        text = (ROOT/file).read_text()
        assert 'lb_controller_tick(' not in text and 'srv_->lb_should_pause(' not in text
        assert 'lb_parse_paused([&] { return c->id(); })' in text
        assert text.count('lb_pass_begin(); // one shared pause snapshot before any connection parsing') == 1
        assert text.index('lb_pass_begin(); // one shared pause snapshot') < text.index('on_cqe<', text.index('lb_pass_begin(); //'))
    for file in ('src/main.cc','src/core/genthread.cc','src/core/rl2s.cc','src/core/reorder.cc'):
        assert 'srv.monitor_controllers();' in (ROOT/file).read_text(), file
    assert 'now_ms >= next_lb_ms' in post and 'flip_now_ms >= next_flip_ms' in post
    assert 'next_flip_ms = now_ns() / 1000000 + flipctl_wait_ms();' in post
    weighted = (ROOT/'src/core/weighted_lb.h').read_bytes()
    assert weighted == subprocess.check_output(['git','show','cd02ecbab:src/core/weighted_lb.h'],cwd=ROOT)
    from lbplanner_pad import body
    io = (ROOT/'src/core/io_loop.h').read_text()
    begin, tail = body(io, 'lb_pass_begin'), body(io, 'lb_control_pass')
    for block in (begin, tail):
        assert block.index('lb_client_read()') < block.index('lb_client_move()')
    assert tail.count('lb_drain_pass_expired(') == 1
    assert tail.index('client_transfer_ready(') < tail.index('lb_drain_pass_expired(')
    consume = body(post, 'lb_consume_plan')
    assert consume.index('plan.client_readers.load(std::memory_order_seq_cst)') < consume.index('lb_client_move_ =')
    assert 'lb_stage_.store(LbStage::PlanReady, std::memory_order_seq_cst);' in post
    write('source.json', dict(policy_blocks=proofs, weighted_lb_sha256=hashlib.sha256(weighted).hexdigest(),
        io_has_no_planner_calls=True, all_four_boot_paths_monitor=True, move_cap_once=True,
        pause_snapshot_before_dispatch=True, drain_budget_after_readiness=True,
        client_record_lifetime='SC reader scope only in ClientDrain; PlanReady consumer defers reuse without waiting'))
    print('PASS unchanged admission/search policy blocks, monitor boot wiring and hoisted cap')


def pad_status():
    from lbplanner_pad import plan, verify
    post, pad = ROOT/'build/tomokv', ROOT/'build/tomokv-lbplanner-pad'
    expected = plan(post)
    verify(post, pad, expected, independent=False)
    proof = json.loads((ROOT/'build/lbplanner-pad-proof/proof.json').read_text())
    assert proof['post']['binary_sha256'] == hashlib.sha256(post.read_bytes()).hexdigest()
    assert proof['pad']['binary_sha256'] == hashlib.sha256(pad.read_bytes()).hexdigest()
    write('pad-status.json', dict(required_kind=expected['kind'], valid_pad_a_built=True,
        proof='pad-a/proof.json', behavior='PRE IO-hosted gather/search and cron, live parse stage, repeated cap reads',
        layout='Complete function/section tables equal; every other byte identical.',
        performance='NOT MEASURED: mainline owns the three-regime ABBA and full gate.'))
    print('PASS PAD-A identity, source closure and all approved retargets; mainline performance remains unmeasured')


if __name__ == '__main__':
    source()
    rows = layout()
    costs(rows)
    pad_status()
