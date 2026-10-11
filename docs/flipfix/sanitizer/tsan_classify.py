#!/usr/bin/env python3
"""Classify ThreadSanitizer reports in a server log. Each report is keyed by the first in-project
frame of its two access stacks, then put in one class:
  diagnostic  - an accessor is a LoopSignals/INFO diagnostic counter reader or writer (the lbsignals
                owner decision; pre-existing on PRE),
  flip        - otherwise, the top two frames of an access name FLIP plan/close/readiness/placement/
                fingerprint/inbox code,
  other       - anything else.
Usage: tsan_classify.py <log> [<log> ...]   (one JSON object per log)"""
import collections, json, re, sys
DIAG = re.compile(r'lb_fold_signals|IoTenure<.*>::account|total_commands|info_stats_tick|'
                  r'sample_role_demand|lbsignals_capture|command_calls|MaskedSpscArray<.*>::diagnostics|'
                  r'FlipController::start_maneuver')   # start_maneuver reads LoopSignals (flipctl.cc:655)
FLIP = re.compile(r'flip_|FlipFingerprint|pubsub_disconnect_ready|set_runtime_role|client_transfer|'
                  r'sample_fingerprint|publish_sampled_pass|finish_parse_pass|published_since|'
                  r'flag_pending_io_inbound|Placement|placement|remove_client|reap_dead')
FRAME = re.compile(r'^\s+#\d+ (.*)$')
def frames(block):
    out = []
    for line in block.splitlines():
        m = FRAME.match(line)
        if not m: continue
        rest = re.sub(r' \((?:BuildId|[^()]*\+0x)[^()]*\)', '', m[1])  # drop (module+off) (BuildId: ..)
        out.append(rest.rsplit(' ', 1)[0] if ' ' in rest else rest)   # drop FILE:LINE / <null>
    return out
def project(fs):
    return [f for f in fs if 'tomo' in f or f.startswith('main')]
for path in sys.argv[1:]:
    text = open(path, errors='replace').read()
    blocks = text.split('WARNING: ThreadSanitizer:')[1:]
    groups, cls = collections.Counter(), {}
    for b in blocks:
        b = b.split('==================')[0]
        kind = b.split('\n', 1)[0].strip().split(' (pid')[0]
        stacks = re.split(r'\n\s*\n', b)[:2]          # the two accesses only
        accessors = [(project(frames(st)) or [''])[0] for st in stacks]
        sig = f'{kind} :: ' + ' <-> '.join(sorted(a[:100] for a in accessors))   # unordered pair
        if any(DIAG.search(a) for a in accessors): c = 'diagnostic'
        elif any(FLIP.search(n) for st in stacks for n in frames(st)[:2]): c = 'flip'
        else: c = 'other'
        groups[sig] += 1
        cls[sig] = c
    counts = collections.Counter()
    for sig, n in groups.items(): counts[cls[sig]] += n
    print(json.dumps(dict(log=path, reports=len(blocks), classes=counts,
                          groups=[[c, n, g] for g, n in groups.most_common() for c in [cls[g]]]), indent=1))
