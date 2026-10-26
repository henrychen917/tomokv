#!/usr/bin/env python3
"""Strict R7-off witness, with linkage/caller proof for armed-only local clones.

The original audit compared pre-R7 mainline against R7 (169 bodies). Comparing
R7 itself also sees two R7 ThreadCtx callbacks and two TU-local parser clones in
reorder.cc. Prove their armed-only provenance; keep the original byte normalizer
and every off-path occurrence, register, branch, immediate and layout operand.
"""
import argparse
import bisect
from collections import Counter
import json
from itertools import product
from pathlib import Path
import re
import sys

import reorder_noop as audit
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from lbstall_artifacts import Elf


def off_roles(binary):
    elf = Elf(binary.path)
    owner, locals_ = '', set()
    for symbol in elf.symbols:
        if symbol['info'] & 15 == 4:
            owner = symbol['name']
        elif symbol['info'] & 15 == 2 and symbol['info'] >> 4 == 0 and owner == 'reorder.cc':
            locals_.add(symbol['value'])
    functions = {f['addr']: (name, f) for name, bodies in binary.groups.items() for f in bodies}
    starts = sorted(functions)
    callers = {a: set() for a in starts}
    for at, (_, asm) in binary.instructions.items():
        index = bisect.bisect_right(starts, at) - 1
        if index < 0: continue
        source = starts[index]
        if at >= source + functions[source][1]['size']: continue
        for ref in audit.REFERENCE.finditer(asm):
            target = int(ref[1], 16)
            if target in callers and target != source: callers[target].add(source)

    def armed(name):
        return '::r7_' in name or '_reordered(' in name

    def prove_local(at, visited):
        name = functions[at][0]
        if armed(name): return
        if at in visited: return
        if at not in locals_:
            raise AssertionError('excluded clone reachable from a non-R7 entry: ' + name)
        visited.add(at)
        for caller in callers[at]: prove_local(caller, visited)

    removed = []
    for name, bodies in list(binary.groups.items()):
        keep = []
        for body in bodies:
            if not audit.category(name):
                keep.append(body)
                continue
            reason = None
            ancestors = set()
            if armed(name): reason = 'explicit R7 specialization'
            elif body['addr'] in locals_:
                prove_local(body['addr'], ancestors)
                reason = 'STB_LOCAL in reorder.cc; all incoming paths local or armed'
            if reason:
                if audit.category(name):
                    removed.append(dict(name=name, address=hex(body['addr']), reason=reason,
                                        local_ancestors=[functions[x][0] for x in sorted(ancestors)]))
            else: keep.append(body)
        if keep: binary.groups[name] = keep
        else: del binary.groups[name]
    return removed


def splitlocal_inventory(binary, namespaces, *, overlap_removed=False, fliplisten=False, latencyfix=False):
    """Require the extra physical parser bodies per runtime after splitlocal.

    Forwarding SplitLocal emits two parsers and four ordinary-parser clones.
    Their eight out-of-line closures become six after overlap removal.
    Historical inventories remain usable for frozen inputs.
    """
    for namespace in namespaces:
        for no_borrow in ('false', 'true'):
            parser = audit.canonical(f'{namespace}::IoLoop::parse_and_dispatch'
                                     f'<{no_borrow}, 32u, false, true>({namespace}::Client*)')
            direct = f'{namespace}::IoLoop::DispatchResult {parser}'
            family = {name for name in binary.groups if parser in name and audit.category(name)}
            conflicts = {name for name in family if name.startswith(
                f'{namespace}::Rob<64u>::read_local_owner_conflicts_before<')}
            fillers = {name for name in family if name.startswith(
                f'auto {parser}::{{lambda(auto:1&&)#1}}::operator()<')}
            ordinary = audit.canonical(f'{namespace}::IoLoop::DispatchResult {namespace}::IoLoop::'
                                       f'parse_and_dispatch<{no_borrow}, 32u, false, false>({namespace}::Client*)')
            clones = {ordinary + ' [clone .isra.0]' + suffix for suffix in ('', ' [clone .cold]')}
            conflict_count = 2 if overlap_removed else 3
            if latencyfix and namespace == "tomo": conflict_count += 1
            assert (len(conflicts) == conflict_count and len(fillers) == 1 and
                    family == {direct} | conflicts | fillers and
                    all(len(binary.groups.get(name, ())) == 1 for name in family) and
                    all(len(binary.groups.get(name, ())) ==
                        (2 if fliplisten and no_borrow == 'true' else 1) for name in clones)), \
                f'missing split-local parser bodies: {namespace}, NoBorrow={no_borrow}'


def fliplisten_inventory(binary, namespaces):
    """Six additional physical parser bodies per runtime from fliplisten.cc.

    Keep every instruction comparison; require each exact new closure and each
    extra clone. This is the isolated fliplisten POST's +6/+6 inventory, not a
    tolerance for arbitrary compiler drift in the integration.
    """
    normal = {'auto tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)::{lambda(auto:1&&)#1}::operator()<tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)::{lambda()#2}::operator()() const::{lambda(tomo::Op const&)#1}>(tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)::{lambda()#2}::operator()() const::{lambda(tomo::Op const&)#1}&&) const': 1,
 'auto tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)::{lambda(auto:1&&)#1}::operator()<tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)::{lambda(tomo::Op const&)#1}>(tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)::{lambda(tomo::Op const&)#1}&&) const': 1,
 'tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]': 3,
 'tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] [clone .cold]': 3,
 'tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*) [clone .isra.0]': 2,
 'tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*) [clone .isra.0] [clone .cold]': 2}
    for namespace in namespaces:
        expected = {name.replace('tomo::', namespace + '::'): count
                    for name, count in normal.items()}
        for name, count in expected.items():
            assert len(binary.groups.get(name, ())) == count, \
                f'missing fliplisten parser body: {namespace}: {name}'


def execfair_inventory(binary, namespaces):
    """Exactly three owner-local promotion callback bodies per runtime.

    They are ordinary execute callbacks, not armed R7-only bodies. Keep each
    physical body in the strict byte comparison and reject a missing clone.
    """
    for namespace in namespaces:
        expected = {
            f'{namespace}::ExLoopT<{fused}>::execute<false, {no_evict}>'
            f'({namespace}::Task const&)::{{lambda(void*, {namespace}::Task const&)#1}}'
            f'::_FUN(void*, {namespace}::Task const&)'
            for fused, no_evict in (('false', 'false'), ('true', 'false'), ('true', 'true'))
        }
        found = {name for name in binary.groups
                 if name.startswith(namespace + '::ExLoopT<') and '::execute<' in name
                 and '::{lambda(void*, ' + namespace + '::Task const&)#1}::_FUN(' in name}
        assert found == expected and all(len(binary.groups[name]) == 1 for name in expected), \
            f'missing execfair promotion callback: {namespace}: expected={expected}, found={found}'


def notifycompat_inventory(binary):
    """NO-A7 replaces one normal scan by two unique-key bodies: net +1/0.

    The DB0 hot/cold pair already exists on the headline. Require all four
    physical bodies, and the disappearance of the superseded normal scan.
    """
    normal = 'void tomo::FlatStore::atomic_for_each_unique_key<tomo::FlatStore::atomic_for_each_side_key<tomo::xshard_execute(tomo::Task const&, tomo::Shard&, tomo::Op&, unsigned int)::{lambda(tomo::Slice)#1}>(unsigned long, tomo::xshard_execute(tomo::Task const&, tomo::Shard&, tomo::Op&, unsigned int)::{lambda(tomo::Slice)#1}&&)::{lambda(unsigned long, tomo::Slice)#1}>(tomo::xshard_execute(tomo::Task const&, tomo::Shard&, tomo::Op&, unsigned int)::{lambda(tomo::Slice)#1}&&) [clone .isra.0]'
    expected = {normal.replace('tomo::', namespace + '::') + suffix
                for namespace in ('tomo', 'tomo_db0')
                for suffix in ('', ' [clone .cold]')}
    found = {name for name in binary.groups if 'FlatStore::atomic_for_each_unique_key<' in name
             and 'xshard_execute(' in name and audit.category(name)}
    retired = {name for name in binary.groups if 'tomo::FlatStore::scan<' in name
               and 'tomo::xshard_execute(' in name and audit.category(name)}
    assert found == expected and all(len(binary.groups[name]) == 1 for name in expected) and not retired, \
        f'missing notifycompat scatter scan: expected={expected}, found={found}'
    return expected


def latencyfix_inventory(binary):
    """Require all 312 inherited bodies plus 14 newly outlined bodies by exact name.

    The manifest also pins physical clone counts. No historical body is removed,
    and compare() still checks every opcode, operand and literal in all 326.
    """
    path = Path(__file__).resolve().parents[1] / 'docs/latencyfix/reorder-inventory.json'
    expected = json.loads(path.read_text())
    actual = {name: len(bodies) for name, bodies in binary.groups.items() if audit.category(name)}
    assert actual == expected, 'latencyfix named inventory differs'
    return Counter({'tomo': 164, 'tomo_db0': 162})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pre')
    parser.add_argument('post')
    parser.add_argument('output')
    parser.add_argument('--inventory', choices=('r7', 'wbrule', 'splitlocal', 'overlapaxe', 'wave5', 'execfair', 'wave6', 'latencyfix'), default='r7',
                        help='wbrule/splitlocal retain historical inventories; overlapaxe requires the surviving bodies')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    audit.self_test()
    pre = audit.Binary(args.pre, out, literal_pools=True)
    post = audit.Binary(args.post, out, literal_pools=True)
    excluded = {'pre': off_roles(pre), 'post': off_roles(post)}
    rows = audit.compare(pre, post, out)
    # The boot-selected db0 runtime duplicates the historical 168-body inventory;
    # the old single-runtime audit had 169. Later inventory deltas are explicit.
    expected = {'tomo': 168, 'tomo_db0': 168} if any(
        'tomo_db0::' in row['name'] for row in rows) else {'tomo': 169}
    if args.inventory in ('wbrule', 'splitlocal', 'overlapaxe', 'wave5', 'execfair', 'wave6'):
        assert set(expected) == {'tomo', 'tomo_db0'}, 'wbrule requires both database runtimes'
        # wbrule carries SplitLocal through flush_ready. These sixteen additional
        # instantiations per runtime keep physical 2s writeback separate from 1s.
        # Require each exact name and retain ALL old and new byte comparisons.
        for namespace in expected:
            added = {'unsigned int ' + namespace + '::IoLoop::flush_ready<' +
                     ', '.join((tls, ep, 'true', unix, sweep, 'true')) + '>()'
                     for tls, ep, unix, sweep in product(('false', 'true'), repeat=4)}
            for binary in (pre, post):
                found = {name for name in binary.groups if name in added}
                assert found == added, f'missing physical split-local WB bodies: {added - found}'
            expected[namespace] += len(added)
    if args.inventory in ('splitlocal', 'overlapaxe', 'wave5', 'execfair', 'wave6'):
        for binary in (pre, post):
            splitlocal_inventory(binary, expected, overlap_removed=args.inventory in ('overlapaxe', 'wave5', 'execfair', 'wave6'),
                                 fliplisten=args.inventory in ('wave5', 'execfair', 'wave6'))
        for namespace in expected:
            expected[namespace] += 14
    if args.inventory in ('overlapaxe', 'wave5', 'execfair', 'wave6'):
        # 198 -> 147 physical bodies per runtime: -32 IO envelopes, -14 parser
        # bodies/closures, -4 retired WB helpers, -1 scheduler body. The renamed
        # fused owner prefetch remains in the audit; only split prefetch is gone.
        for namespace in expected:
            expected[namespace] -= 51
            # perfex: ExLoopT<false>::exec_batch<false, 32ul> is inlined into drain_tasks once the
            # task batch needs no zero-fill, so one split scheduler body per runtime is gone (147 -> 146).
            expected[namespace] -= 1
            owner = f'{namespace}::ExLoopT<true>::prefetch_owner_batch({namespace}::Task const*, unsigned int)'
            for binary in (pre, post):
                assert len(binary.groups.get(owner, ())) == 1, f'missing owner prefetch body: {namespace}'
            # clockcut: the post-dequeue command-clock refresh grows the split executor's
            # exec_batch_prefetched, which GCC now keeps out of line (146 -> 147 per runtime).
            expected[namespace] += 1
            batch = (f'void {namespace}::ExLoopT<false>::exec_batch_prefetched<false>'
                     f'({namespace}::Task const*, unsigned int)')
            for binary in (pre, post):
                assert len(binary.groups.get(batch, ())) == 1, f'missing split batch body: {namespace}'
        # moverfix: normal xshard.o inlines the xshard_execute KEYS/RANDOMKEY
        # atomic_for_each_unique_key<atomic_for_each_side_key<...>> .isra.0
        # body and its cold fragment into xshard_execute (-2), but emits its
        # FlatStore::scan<...> .constprop.0 clone (+1): 146 -> 145. DB0 keeps
        # the two unique-key bodies and inlines scan (146). Budget-only trials
        # retaining those helper bodies change other hot bodies; retain POST.
        # See docs/moverfix2/README.md for symbols, IPA decisions and trials.
        # wave4: both edits compose additively: normal 146+1-1 = 146, DB0 146+1 = 147.
        expected['tomo'] -= 1
    if args.inventory in ('wave5', 'execfair', 'wave6'):
        # All seven frozen lane links are inventoried in docs/wave5/r7-inventory.
        # Only fliplisten adds bodies: headline 146/147 + 6/6 = merged 152/153.
        for binary in (pre, post): fliplisten_inventory(binary, expected)
        for namespace in expected: expected[namespace] += 6
    if args.inventory in ('execfair', 'wave6'):
        for binary in (pre, post): execfair_inventory(binary, expected)
        for namespace in expected: expected[namespace] += 3
    if args.inventory == 'wave6':
        for binary in (pre, post): notifycompat_inventory(binary)
        # Headline 152/153 + execfair 3/3 + notifycompat 1/0 = 156/156.
        # Wave 7 retains 156/156: rlfix3/ctlfix/blockfix/persistfix2/atomfix5
        # add no entries; datafix2's older-base normal scan is the same +1
        # already included by notifycompat. Never count that overlap twice.
        expected['tomo'] += 1
    if args.inventory == 'latencyfix':
        for binary in (pre, post): expected = latencyfix_inventory(binary)
    counts = Counter('tomo_db0' if 'tomo_db0::' in row['name'] else 'tomo' for row in rows)
    assert counts == expected, f'off-path inventory changed: {counts}, expected {expected}'
    def inventory(binary):
        return {name: len(bodies) for name, bodies in binary.groups.items() if audit.category(name)}
    assert inventory(pre) == inventory(post), 'off-path symbols/clone counts changed'
    passed = all(row['equal'] for row in rows)
    result = dict(pre=str(pre.path), post=str(post.path), pre_sha256=pre.sha256,
                  post_sha256=post.sha256, literal_pools=True, excluded_armed=excluded,
                  expected_bodies=expected, inventory=args.inventory, rows=rows, strict_noop=passed)
    (out / 'audit.json').write_text(json.dumps(result, indent=2) + '\n')
    for row in rows:
        if not row['equal']: print('DIFF', row['diff'], row['name'])
    print(f'strict_noop={passed}: {sum(r["equal"] for r in rows)}/{len(rows)} identical bodies')
    raise SystemExit(0 if passed else 1)
