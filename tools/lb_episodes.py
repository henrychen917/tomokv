#!/usr/bin/env python3
"""Mainline-only LB convergence episodes; --self-test and --dry-run start nothing.

PRE probes must admit key movement before a key-skew matrix can run. Key episodes
require a stationary key suffix; client episodes score spread improvement.
See MEASURE-REQUEST-bench5.md for the comparison and read-only --replay rules.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from _lib import Conn  # noqa: E402
from abba_workloads import (command_histogram, memtier_workload_counts, percentile,
                            require_workload_accounting)  # noqa: E402

PREFIX = "tomokv_keylb_"
CLIENT_PREFIX = "tomokv_clientlb_"
TICKS, STAGE = PREFIX + "ticks", PREFIX + "stage"
KEY, GATHERS = (PREFIX + n for n in ("bucket_moves", "bucket_gathers"))
CLIENT = CLIENT_PREFIX + "moves"
SPREADS = (PREFIX + "bucket_weight_spread_current", PREFIX + "bucket_bytes_spread_current",
           CLIENT_PREFIX + "weight_spread_current")
REFUSALS = tuple(PREFIX + n for n in (
    "no_candidate", "hysteresis_refused", "cooldown_refused", "transition_refused",
    "capacity_refused", "hot_bucket_refused")) + (CLIENT_PREFIX + "refused",)
HISTORY_COUNTERS = tuple(PREFIX + n for n in (
    "reversal_refused", "recent_move_refused", "owner_pair_refused", "history_escapes"))
OWNER_METRICS = ("shard_moves", "returns", "exchanges", "distinct_shards")
STALL = {short: "tomokv_lbstall_" + name for short, name in (
    ("exec", "executor"), ("proto", "protocol"), ("passl", "pass_limit"),
    ("dest", "destination"), ("pipe", "pipeline"), ("defout", "deferred_output"),
    ("cstate", "client_state"), ("invalid", "invalid_client"))}
PENDING = "tomokv_lbstall_pending_ns_max"
COUNTERS = (TICKS, KEY, CLIENT, GATHERS, PREFIX + "bucket_cross_domain_moves",
            CLIENT_PREFIX + "cross_domain_moves", *REFUSALS, *STALL.values())
FIELDS = (STAGE, PENDING, *COUNTERS, *SPREADS,
          *(n.replace("current", edge) for n in SPREADS for edge in ("before", "after")))
ARMS = {
    "PRE": ("build/lbplanner-pre/tomokv", "33f07418205817e93d5d759d4cab78480f77c5aa9fa51618dc89aa3e3828f8a2"),
    "PAD-A": ("build/tomokv-lbplanner-pad", "bdda99b8c96438cfa60637279c886827cc1a6d78370a5c9a5053e73a79d634c8"),
    "POST": ("build/tomokv", "571fa4ab3e81f1d231941be82f22950644e0ed437a85d50d6111e5545354e0f1"),
}
INTERVAL = .1
DECISION_TICKS, DECISION_SECONDS = 3, 3.0  # frozen arms' LbAutotune, not a fitted threshold
KEYS, CONNECTIONS, PIPELINE, DATA_SIZE = 500000, 128, 128, 64
SERVER_CORES, LOAD_CORES = "0-15", "64-95"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def bind_arms(receipt):
    if receipt is None:
        return dict(ARMS), {"path": None, "sha256": None, "source": "frozen ARMS table"}
    path = receipt.resolve()
    raw = path.read_bytes()
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"duplicate arm receipt field: {key}")
            result[key] = value
        return result
    data = json.loads(raw, object_pairs_hook=unique)
    require(isinstance(data, dict) and set(data) == set(ARMS),
            "arms receipt must bind exactly PRE, PAD-A and POST")
    table = {}
    for arm, entry in data.items():
        require(isinstance(entry, dict) and set(entry) == {"path", "sha256"},
                f"{arm} receipt must contain path and sha256")
        name, sha = entry["path"], entry["sha256"]
        require(isinstance(name, str) and name and isinstance(sha, str) and len(sha) == 64
                and all(c in "0123456789abcdef" for c in sha), f"invalid {arm} path/SHA256 receipt")
        binary = Path(name)
        table[arm] = (str((path.parent / binary).resolve()), sha)
    return table, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "source": "--arms"}


def arm_table(args):
    return getattr(args, "arm_table", ARMS)


def arms_receipt(args):
    return getattr(args, "arms_receipt", {"path": None, "sha256": None, "source": "frozen ARMS table"})


def verify_arms(args, only=None):
    receipt = arms_receipt(args)
    if receipt["path"]:
        require(digest(receipt["path"]) == receipt["sha256"], "arms receipt changed after binding")
    for arm, (relative, expected) in arm_table(args).items():
        if only is not None and arm != only:
            continue
        path = ROOT / relative
        require(path.is_file() and os.access(path, os.X_OK) and digest(path) == expected,
                f"{arm} binary differs from " + ("explicit arms" if receipt["path"] else "frozen lbplanner") +
                " receipt; do not silently rebind SHA")


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def parse_info(raw, mandatory=True):
    require(isinstance(raw, bytes), "INFO must return a bulk string")
    result = {}
    for line in raw.decode().splitlines():
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        require(sep and key not in result, "malformed/duplicate INFO field: " + line)
        result[key] = value
    if mandatory:
        require(all(k in result for k in FIELDS),
                "INFO LB missing mandatory fields: " + ", ".join(k for k in FIELDS if k not in result))
        require(result.get(PREFIX + "enabled") == result.get("tomokv_clientlb_enabled") == "1",
                "both balancers must be enabled")
        optional = (PREFIX + "damping_band_pct", PREFIX + "damping_fire_pct", PREFIX + "damping_ticks")
        for key in (*FIELDS, *(k for k in (*HISTORY_COUNTERS, *optional) if k in result)):
            value = float(result[key]) if "spread" in key or key.endswith("_pct") else int(result[key])
            require(math.isfinite(value) and value >= 0, "invalid INFO value: " + key)
            result[key] = value
    return result


def parse_signals(raw):
    require(isinstance(raw, bytes), "LBSIGNALS must return a bulk string")
    result = {"threads": {}, "shards": {}, "raw": raw.decode()}
    for line in raw.decode().splitlines():
        v = line.split()
        if not v:
            continue
        if v[0] == "lbver":
            require(len(v) == 4 and v[:3] == ["lbver", "1", "stamp_ns"], "bad LB schema")
            result["stamp_ns"] = int(v[3])
        elif v[0] == "thread":
            require(len(v) >= 23 and v[2] in ("fused", "io", "ex"), "bad LB thread row")
            tid = int(v[1])
            require(tid not in result["threads"], "duplicate LB thread")
            row = dict(zip(("domain", "clients", "iterations", "ops", "busy_ns", "idle_ns",
                            "cpu_ns"), map(int, v[3:10])))
            require(all(n >= 0 for n in row.values()), "negative LB thread counter")
            result["threads"][tid] = dict(row, role=v[2])
        elif v[0] == "shard":
            require(len(v) == 9, "bad LB shard row")
            sid = int(v[1])
            require(sid not in result["shards"], "duplicate LB shard")
            result["shards"][sid] = dict(zip(
                ("owner", "domain", "ops", "foreign_ops", "migrations", "size", "obj_bytes"),
                map(int, v[2:])))
        elif v[0] == "derived":
            require(len(v) % 2 == 1, "bad LB derived row")
            result["derived"] = dict(zip(v[1::2], v[2::2]))
    require(result.get("stamp_ns", 0) > 0 and result["threads"] and result["shards"]
            and "derived" in result, "incomplete LBSIGNALS")
    require(all(r["owner"] in result["threads"] for r in result["shards"].values()),
            "shard references absent owner")
    return result


def geometry(sample, mode, requested_shards=None, threads=16):
    snap = sample["signals"]
    roles = Counter(r["role"] for r in snap["threads"].values())
    require(snap["derived"]["thread_mode"] == mode,
            f"expected thread-mode={mode}, observed {snap['derived']['thread_mode']}; observed {roles!r}")
    valid = (roles == {"fused": threads} if mode == "1s" else
             len(snap["threads"]) == roles["io"] + roles["ex"] == threads and roles["io"] >= 2)
    expected = f"{threads} fused threads" if mode == "1s" else f"{threads} IO + EX threads with at least 2 IO"
    require(valid, f"expected {expected} on requested server CPUs; observed {roles!r}")
    count = len(snap["shards"])
    require(count > 0 and set(snap["shards"]) == set(range(count)),
            f"shard IDs must cover 0..{count - 1}; observed {sorted(snap['shards'])}")
    require(requested_shards is None or count == requested_shards,
            f"shards={count}, requested limit={requested_shards}")
    require(all(snap["threads"][row["owner"]]["role"] in ("ex", "fused")
                for row in snap["shards"].values()), "shard owner must be an executor/fused thread")
    return sorted(tid for tid, row in snap["threads"].items() if row["role"] in ("io", "fused"))


def delta(before, after):
    result = {key: after["info"][key] - before["info"][key] for key in COUNTERS}
    for key, value in result.items():
        require(value >= 0, f"LB counter reset: {key} delta={value}, limit>=0")
    require(after["info"][PENDING] >= before["info"][PENDING],
            f"{PENDING}={after['info'][PENDING]}, limit>={before['info'][PENDING]} (reset)")
    result["total_moves"] = result[KEY] + result[CLIENT]
    return result


def beats(samples):
    """Last observation of each *closed* beat avoids treating 10 polls as 10 decisions."""
    result, previous = [], None
    for sample in samples:
        if previous:
            change = sample["info"][TICKS] - previous["info"][TICKS]
            require(change in (0, 1), f"{TICKS} delta={change}, limit=0 or 1 (missed beat or reset)")
            delta(previous, sample)
            gap = sample["t"] - previous["t"]
            require(0 < gap <= .5, f"telemetry gap={gap:g}s, limit=0<gap<=0.5s")
            if change:
                result.append(previous)
        previous = sample
    return result


def shard_owners(sample):
    return {str(sid): row["owner"] for sid, row in sample["signals"]["shards"].items()}


def owner_tracking(samples):
    """Observed transitions over the whole capture, including warmup/guards.

    A return includes any previously visited owner, not just the last source.
    One exchange is one unordered owner pair with both directions in one poll
    interval, irrespective of how many shards travelled in either direction.
    Moves between polls are unobservable; never infer them from INFO counters.
    """
    require(bool(samples), "owner tracking: missing telemetry")
    previous = shard_owners(samples[0])
    require(bool(previous), "owner tracking: empty shard map")
    seen = {sid: {owner} for sid, owner in previous.items()}
    touched, moves, returns, exchanges = set(), 0, 0, 0
    for old, sample in zip(samples, samples[1:]):
        gap = sample["t"] - old["t"]
        require(0 < gap <= .5, f"owner tracking: telemetry gap={gap:g}s, limit=0<gap<=0.5s")
        current = shard_owners(sample)
        require(current.keys() == previous.keys(), "owner tracking: shard map changed or is incomplete")
        edges = set()
        for sid, owner in current.items():
            if owner == previous[sid]:
                continue
            moves += 1
            returns += owner in seen[sid]
            seen[sid].add(owner)
            touched.add(sid)
            edges.add((previous[sid], owner))
        exchanges += sum(a < b and (b, a) in edges for a, b in edges)
        previous = current
    return {"shard_moves": moves, "returns": returns, "exchanges": exchanges,
            "distinct_shards": len(touched),
            "owner_tracking": {"start_t": samples[0]["t"], "end_t": samples[-1]["t"],
                               "samples": len(samples), "shard_ids": sorted(touched, key=int),
                               "scope": "entire captured episode, including warmup and guards; observed transitions only"}}


def history_deltas(samples):
    """Optional lbosc2 counters: absence is NA, never zero or a summed refusal."""
    result = {}
    for key in HISTORY_COUNTERS:
        values = [int(s["info"][key]) for s in samples if key in s["info"]]
        require(all(v >= 0 for v in values), f"invalid INFO value: {key}")
        require(all(b >= a for a, b in zip(values, values[1:])), f"LB counter reset: {key}")
        result[key] = values[-1] - values[0] if values and len(values) == len(samples) else None
    # reversal_refused is the aggregate admission refusal, not the sum of the
    # potentially overlapping recent-move and owner-pair reason counters.
    return {"history_counters": result, "refused": result[HISTORY_COUNTERS[0]],
            "escapes": result[HISTORY_COUNTERS[-1]]}


def spread_maxima(samples):
    return {key: max(s["info"][key] for s in samples) for key in SPREADS} if samples else {}


def decision_window(samples):
    """Include the observation preceding the final three seconds AND ticks."""
    last = samples[-1]
    start = next(i for i, s in enumerate(samples) if
                 last["t"] - s["t"] <= DECISION_SECONDS or
                 last["info"][TICKS] - s["info"][TICKS] <= DECISION_TICKS)
    return samples[max(0, start - 1):]


def baseline_stationarity(samples, placement=None, episode="key-skew"):
    """Stationarity belongs to the required controller; placement stays fixed."""
    maxima = spread_maxima(samples)
    summary = "balanced maxima (reported only): " + ", ".join(f"{k}={v:g}" for k, v in maxima.items())
    result = {"status": "FAIL", "spread_maxima": maxima, "summary": summary}
    try:
        rows = beats(samples)
        require(len(rows) >= 3 * DECISION_TICKS,
                f"balanced closed_beats={len(rows)}, limit>={3 * DECISION_TICKS}")
        duration = samples[-1]["t"] - samples[0]["t"]
        require(duration >= 3 * DECISION_SECONDS,
                f"balanced seconds={duration:g}, limit>={3 * DECISION_SECONDS:g}")
        movements = delta(samples[0], samples[-1])
        window = decision_window(samples)
        final_moves = delta(window[0], window[-1])
        result.update(deltas=movements, baseline_key_moves=movements[KEY],
                      baseline_client_moves=movements[CLIENT],
                      baseline_earlier_client_moves=movements[CLIENT] - final_moves[CLIENT],
                      decision_client_moves=final_moves[CLIENT],
                      baseline_decision_client_moves=final_moves[CLIENT], decision_start_t=window[0]["t"])
        require(movements[KEY] == 0,
                f"balanced key_moves={movements[KEY]}, limit=0 (placement changed)")
        if episode == "client-skew":
            require(final_moves[CLIENT] <= 1,
                    f"balanced final decision client_moves={final_moves[CLIENT]}, limit<=1 "
                    f"(earlier={result['baseline_earlier_client_moves']})")
            if final_moves[CLIENT]:
                # A nominal 60s sample window spans 59.9s at 100ms polling.
                # Keep the same 500ms maximum endpoint gap as convergence.
                require(duration >= 60 - .5,
                        f"one-move baseline seconds={duration:g}, limit>=59.5 (60s window)")
                for row in samples:
                    if samples[-1]["info"][TICKS] - row["info"][TICKS] < 3 * DECISION_TICKS:
                        require(row["info"][STAGE] == 0,
                                f"balanced last 9 ticks {STAGE}={row['info'][STAGE]}, limit=0 at t={row['t']:.6f}")
        last = samples[-1]
        for row in window[1:]:  # preceding observation brackets moves; it is outside the window
            require(row["info"][STAGE] == 0,
                    f"balanced {STAGE}={row['info'][STAGE]}, limit=0 at t={row['t']:.6f}")
        if placement is not None:
            observed = shard_owners(last)
            for sid in sorted(set(placement) | set(observed), key=int):
                require(observed.get(sid) == placement.get(sid),
                        f"balanced shard_owners[{sid}]={observed.get(sid)}, limit={placement.get(sid)} (PRE)")
        result.update(status="PASS", beats=len(rows), seconds=duration)
        reason = (f"own {episode} baseline stationary; baseline_client_moves={movements[CLIENT]}; "
                  f"baseline_decision_client_moves={final_moves[CLIENT]}")
    except ValueError as error:
        reason = str(error)
    return dict(result, reason=reason)


def sampling_floor(owners):
    # weighted_lb.h LbAutotune::sampling_floor, in percent, 4096 samples/owner.
    count = max(owners, 2)
    pairs = count * (count - 1) / 2
    return 200 * math.sqrt(2 / 4096 * (1 + .5 * math.log(pairs)))


def envelope(samples, episode="key-skew"):
    baseline = baseline_stationarity(samples, episode=episode)
    require(baseline["status"] == "PASS", "PRE " + baseline["reason"])
    first, last = samples[0], samples[-1]
    for tid, old in first["signals"]["threads"].items():
        count = last["signals"]["threads"][tid]["ops"] - old["ops"]
        require(count > 0, f"PRE owner[{tid}].ops delta={count}, limit>0")
    roles = Counter(r["role"] for r in last["signals"]["threads"].values())
    writers, clients = roles["ex"] + roles["fused"], roles["io"] + roles["fused"]
    return {"upper": baseline["spread_maxima"], "lower": {key: 0 for key in SPREADS},
            "beats": baseline["beats"], "shard_owners": shard_owners(last),
            "shards": len(last["signals"]["shards"]),
            "first_tick": first["info"][TICKS], "last_tick": last["info"][TICKS],
            "release_band": {k: .8 * sampling_floor(clients if k == SPREADS[2] else writers) / 100
                             for k in SPREADS},
            "release_band_source": "0.8 * sampling_floor: minimum Schmitt release band; learned jitter is not exported",
            "sustain_seconds": DECISION_SECONDS, "sustain_ticks": DECISION_TICKS,
            "source": "PRE balanced baseline; all 100 ms sample maxima; never widened using an arm"}


def diagnostic_envelope(criterion, own_maxima):
    # This run-local margin is ONLY a diagnostic. It cannot widen the frozen
    # PRE width used to reject a post-move rebound, or fit any comparison rule.
    return {"upper": {k: max(criterion["upper"][k] * (1 + criterion["release_band"][k]),
                             own_maxima[k]) for k in SPREADS},
            "source": "max(PRE maximum * (1 + minimum release band), own baseline maximum); diagnostic only"}


def inside(sample, criterion):
    return (sample["info"][STAGE] == 0 and
            all(sample["info"][k] <= limit for k, limit in criterion["upper"].items()))


def actuator_mix(anchor, final, total):
    return {"stall": {short: total[key] for short, key in STALL.items()},
            "pass_limit": total[STALL["passl"]],
            "attempts": total[CLIENT_PREFIX + "refused"] + total[CLIENT],
            # A high-water mark is not additive: subtracting two maxima would
            # mislabel a difference as a duration. Retain both endpoints.
            "pending_ms": final["info"][PENDING] / 1e6,
            "pending_ms_before": anchor["info"][PENDING] / 1e6,
            "pending_scope": "server lifetime high-water at post-stimulus endpoint"}


def spread_progress(before, after, rows, stimulus, end_t, primary, move, suffix_seconds):
    """Fixed windows and 5% record improvements, independent of the candidate arm."""
    def mean(window):
        require(bool(window), "missing spread window")
        return sum(s["info"][primary] for s in window) / len(window)
    final = after[-1]
    base = before[-1]["info"][primary]
    peak = max(s["info"][primary] for s in after if s["t"] <= stimulus + 6)
    end = mean([s for s in after if s["t"] > end_t - DECISION_SECONDS])
    previous = mean([s for s in after if
                     end_t - 2 * DECISION_SECONDS < s["t"] <= end_t - DECISION_SECONDS])
    # Only start recording improvements after the fixed peak window. The
    # pre-step values in its first polls must not become a spurious low record.
    level, last_improvement = peak, None
    for row in [*rows, final]:
        if row["t"] < stimulus + 6:
            continue
        value = mean([s for s in after if row["t"] - DECISION_SECONDS < s["t"] <= row["t"]])
        if value < level and value <= .95 * level:
            level, last_improvement = value, row
    # Disjoint three-second decision windows charge each move exactly once.
    # Compare their trailing 3s means with the running best, and accumulate
    # non-improving moves: a later record can never forgive an earlier window.
    # The first two windows use the fixed peak reference without lowering it
    # during the rising edge; subsequent windows update the best even for a
    # sub-5% improvement. Retain the old last-milestone quantity separately.
    best, previous_poll, thrash = peak, before[-1], 0
    windows = []
    for number in range(1, math.ceil((end_t - stimulus) / DECISION_SECONDS) + 1):
        stop = min(stimulus + number * DECISION_SECONDS, end_t)
        window = [s for s in after if stop - DECISION_SECONDS < s["t"] <= stop]
        value = mean(window)
        current = window[-1]
        count = current["info"][move] - previous_poll["info"][move]
        improved_window = value < best and value <= .95 * best
        if not improved_window:
            thrash += count
        windows.append({"end_t": stop, "mean": value, "best_before": best,
                        "required_moves": count, "improved": improved_window,
                        "thrash_moves": 0 if improved_window else count})
        if stop >= stimulus + 6:
            best = min(best, value)
        previous_poll = current
    reduction = 1 - end / peak if peak else None
    improved = reduction is not None and reduction > 0
    # A single noisy three-second endpoint difference is not a trend. Fit
    # closed controller beats in the already-declared suffix window instead.
    tail = [s for s in rows if end_t - s["t"] <= suffix_seconds]
    slope = None
    if len(tail) >= DECISION_TICKS:
        x = [s["t"] - final["t"] for s in tail]
        y = [s["info"][primary] for s in tail]
        mx, my = sum(x) / len(x), sum(y) / len(y)
        slope = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sum((a - mx) ** 2 for a in x)
    return {"spread_base": base, "spread_peak": peak, "spread_end": end,
            "spread_min": min(s["info"][primary] for s in after), "reduction": reduction,
            "spread_previous": previous, "spread_improved": improved,
            "spread_tail_slope": slope, "spread_tail_seconds": suffix_seconds,
            "still_converging": improved and slope is not None and slope < 0,
            "last_improvement_t": last_improvement["t"] if last_improvement else None,
            "last_improvement_level": level,
            "thrash_moves": thrash, "thrash_windows": windows,
            "milestone_moves": final["info"][move] -
                (last_improvement or before[-1])["info"][move],
            "spread_method": "base: last pre-stimulus poll; end: fixed endpoint's last 3s mean; peak: first 6s max; min: all post-stimulus polls; "
                             "thrash: cumulative moves in disjoint 3s windows whose trailing mean is not >=5% below the running best; "
                             "first 6s use the peak reference, then best=min(best,mean); partial final window uses a trailing 3s mean; "
                             "milestone_moves: moves after last 5% closed-tick record; falling: negative closed-beat slope over --suffix, "
                             "positive reduction and a required move in that window"}


def suffix_rebound(result, after, level, criterion, primary):
    width = criterion["upper"][primary] - criterion["lower"][primary]
    limit = level["info"][primary] + width
    result.update(post_last_move_level=level["info"][primary], post_last_move_level_t=level["t"],
                  primary=primary, rebound_limit=limit, pre_envelope_width=width)
    for row in after:
        if row["info"][TICKS] < level["info"][TICKS]:
            continue
        if row["info"][primary] > limit:
            return f"post-move rebound: {primary}={row['info'][primary]:g}, limit={limit:g} at t={row['t']:.6f}"
        if row["info"][STAGE] != 0:
            return f"stationary suffix {STAGE}={row['info'][STAGE]}, limit=0 at t={row['t']:.6f}"
    return None


def convergence(samples, stimulus, end, criterion, episode, max_seconds, suffix_seconds,
                diagnostic=None):
    samples = [s for s in samples if s["t"] <= end]
    rows = beats(samples)
    before = [s for s in samples if s["t"] <= stimulus]
    after = [s for s in samples if stimulus < s["t"] <= end]
    require(before and after, "episode has no bracketing samples")
    anchor, final = before[-1], after[-1]
    require(stimulus - anchor["t"] <= .5,
            f"stimulus telemetry gap={stimulus - anchor['t']:g}s, limit<=0.5s")
    require(end - final["t"] <= .5,
            f"endpoint telemetry gap={end - final['t']:g}s, limit<=0.5s")
    rows = [s for s in rows if stimulus < s["t"] <= final["t"]]
    primary = SPREADS[0] if episode == "key-skew" else SPREADS[2]
    move = KEY if episode == "key-skew" else CLIENT
    other = CLIENT if episode == "key-skew" else KEY
    excursion = next((s for s in after if s["info"][primary] > criterion["upper"][primary]), None)
    total = delta(anchor, final)
    result = {"status": "FAIL", "t_converge": None, "deltas": total,
              "key_moves": total[KEY], "client_moves": total[CLIENT],
              "total_moves": total["total_moves"], "gathers": total[GATHERS],
              "suffix_moves": None, "suffix_other_moves": None, "suffix_deltas": None,
              "envelope_return_t": None,
              "anchor_t": anchor["t"], "end_t": final["t"],
              "excursion_t": excursion["t"] if excursion else None,
              **actuator_mix(anchor, final, total),
              **history_deltas([anchor, *after]),
              **spread_progress(before, after, rows, stimulus, end, primary, move, suffix_seconds)}
    if total[move] == 0 or (episode == "key-skew" and total[GATHERS] == 0):
        return dict(result, reason=f"unarmed: {move} delta={total[move]}, limit>0; "
                    f"{GATHERS} delta={total[GATHERS]} (key-skew limit>0)")
    previous, last_move = anchor, None
    for row in after:
        if row["info"][move] > previous["info"][move]:
            last_move = row
            result["last_move_interval"] = [previous["t"], row["t"]]
        previous = row
    result["t_converge"] = last_move["t"] - stimulus
    result["last_move_t"] = last_move["t"]
    suffix = delta(last_move, final)
    result.update(suffix_deltas=suffix, suffix_moves=suffix[move], suffix_other_moves=suffix[other],
                  suffix_seconds=final["t"] - last_move["t"],
                  suffix_ticks=final["info"][TICKS] - last_move["info"][TICKS])
    result["still_converging"] = (episode == "client-skew" and result["still_converging"] and
                                  result["suffix_seconds"] <= suffix_seconds)
    # Keep envelope return as a final sustained-return diagnostic, never a gate.
    diagnostic = diagnostic or criterion
    streak = None
    for row in after:
        if row["t"] < last_move["t"] or not inside(row, diagnostic):
            streak = None
        elif streak is None:
            streak = row
    if (streak and final["t"] - streak["t"] >= DECISION_SECONDS and
            final["info"][TICKS] - streak["info"][TICKS] >= DECISION_TICKS):
        result["envelope_return_t"] = streak["t"] - stimulus
    result["envelope_excess"] = {k: {"value": final["info"][k], "limit": limit}
                                 for k, limit in diagnostic["upper"].items() if final["info"][k] > limit}
    if episode == "client-skew":
        # Key movement changes the placement during a client-only suffix.
        if suffix[KEY]:
            return dict(result, reason=f"key moves during client suffix: key_moves={suffix[KEY]}, limit=0")
        if not result["spread_improved"]:
            return dict(result, reason=f"no spread improvement: reduction={result['reduction']}, "
                        f"limit>0; thrash_moves={result['thrash_moves']}")
        if result["thrash_moves"] and not result["still_converging"]:
            return dict(result, reason=f"spread stopped falling: thrash_moves={result['thrash_moves']}, limit=0")
    if result["t_converge"] > max_seconds and not (episode == "client-skew" and result["still_converging"]):
        return dict(result, reason=f"t_converge={result['t_converge']:g}, limit<={max_seconds:g}")
    # Current spreads are refreshed at controller ticks, not at move completion.
    # Use the first closed beat strictly after the last move's tick; never
    # hunt for a later favourable spread or skip an active plan to re-arm it.
    level = next((s for s in rows if s["info"][TICKS] > last_move["info"][TICKS]), None)
    if episode == "client-skew" and result["still_converging"]:
        # Successful balancing need not leave a 30s quiet tail. Retain Idle
        # evidence over the final decision window while reporting the last move.
        for row in decision_window(after)[1:]:
            if row["info"][STAGE] != 0:
                return dict(result, reason=f"final decision {STAGE}={row['info'][STAGE]}, limit=0")
        # A last-moment successful move may have no refreshed closed beat yet.
        # Once that level is observed, subsequent samples retain the PRE-width
        # rebound check even though the stationary suffix may be incomplete.
        if level is not None:
            reason = suffix_rebound(result, [s for s in after if s["t"] >= level["t"]],
                                    level, criterion, primary)
            if reason:
                return dict(result, reason=reason)
        return dict(result, status="PASS", reason="still converging: spread falling at the fixed endpoint")
    if result["suffix_ticks"] < DECISION_TICKS:
        return dict(result, reason=f"suffix_ticks={result['suffix_ticks']}, limit>={DECISION_TICKS}")
    if level is None:
        return dict(result, reason="post-move closed beats=0, limit>=1")
    result.update(suffix_start_t=level["t"], suffix_seconds=final["t"] - level["t"],
                  suffix_ticks=final["info"][TICKS] - level["info"][TICKS])
    if result["suffix_seconds"] < suffix_seconds or result["suffix_ticks"] < DECISION_TICKS:
        return dict(result, reason=f"suffix_seconds={result['suffix_seconds']:g}, limit>={suffix_seconds:g}; "
                    f"suffix_ticks={result['suffix_ticks']}, limit>={DECISION_TICKS}")
    reason = suffix_rebound(result, after, level, criterion, primary)
    if reason:
        return dict(result, reason=reason)
    return dict(result, status="PASS", reason="last required move followed by a complete quiescent suffix")


def occupancy(samples, start, end, coordinator):
    rows = [s for s in samples if start <= s["t"] <= end]
    require(len(rows) >= 2, "missing occupancy window")
    first, last = rows[0]["signals"], rows[-1]["signals"]
    result = {}
    for tid, old in first["threads"].items():
        new = last["threads"][tid]
        counters = {key: new[key] - old[key] for key in ("busy_ns", "idle_ns", "cpu_ns", "ops")}
        require(all(n >= 0 for n in counters.values()), "thread counters reset")
        denom = counters["busy_ns"] + counters["idle_ns"]
        require(denom > 0, "thread occupancy not observed")
        result[tid] = dict(counters, busy_pct=100 * counters["busy_ns"] / denom, role=new["role"])
    return {"threads": result, "coordinator": coordinator, "coord_busy": result[coordinator]["busy_pct"]}


def metrics(documents, before, after, expected_seconds, hot_pipeline=PIPELINE):
    require(len(documents) == 2, f"loader documents={len(documents)}, limit=2")
    hist, rate, per_loader, accounting = Counter(), 0, [], []
    cell = SimpleNamespace(op="SET", depth=PIPELINE, conns=CONNECTIONS)
    for document, depth in zip(documents, (PIPELINE, hot_pipeline)):
        cohort = SimpleNamespace(op="SET", depth=depth, conns=CONNECTIONS // 2)
        stats = document["ALL STATS"]
        total = stats["Totals"]
        require("Connection Errors" in total, "memtier lacks connection-error evidence")
        require(all(float(total.get(k, 0)) == 0 for k in
                    ("Errors", "Errors/sec", "Connection Errors", "Connection Errors/sec")),
                "memtier reports errors")
        require(str(stats["Runtime"].get("Interrupted", "false")).lower() == "false",
                "memtier interrupted")
        value = float(total["Ops/sec"])
        require(math.isfinite(value) and value > 0, "invalid memtier rate")
        runtime = stats["Runtime"]
        require(runtime["Time unit"] == "MILLISECONDS" and
                float(runtime["Total duration"]) >= (expected_seconds - 1) * 1000,
                "memtier ended before the requested fixed episode duration")
        # The gate's audited finite Count/HDR bound is 64 connections * cohort depth
        # replies. It is legal ONLY alongside exact server SET calls == drained HDR counts.
        evidence = memtier_workload_counts(cohort, document, CONNECTIONS // 2)
        bins = command_histogram(document, "SET", count_bound=evidence["outstanding_bound"])
        accounting.append(evidence)
        hist.update(bins)
        rate += value
        per_loader.append({"rate": value, "p99": percentile(bins, 99), "count": sum(bins.values()),
                           "runtime": runtime, "pipeline": depth})
    return {"rate": rate, "p99": percentile(hist, 99), "loaders": per_loader,
            "accounting": require_workload_accounting(cell, before, after, accounting),
            "p99_method": "merged SET HDR counts; microseconds converted to milliseconds"}


# Connect-only LD_PRELOAD helper: select real TCP sockets with the read-only owner hook.
# No send/recv interposition, forwarding process, server mutation or steady-path work.
# A new socket replaces a rejected one on the SAME descriptor before memtier uses it.
SELECTOR_C = r'''
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/tcp.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>
static _Atomic unsigned sequence;
static void fail(const char *why) { dprintf(2, "lb-owner-selector: %s\n", why); _exit(91); }
int connect(int fd, const struct sockaddr *address, socklen_t length) {
    int (*real_connect)(int, const struct sockaddr *, socklen_t) = dlsym(RTLD_NEXT, "connect");
    const char *port = getenv("LB_EPISODE_PORT"), *owners = getenv("LB_EPISODE_OWNERS");
    if (!real_connect) fail("dlsym connect");
    if (!port || !owners || address->sa_family != AF_INET ||
        ntohs(((const struct sockaddr_in *)address)->sin_port) != atoi(port))
        return real_connect(fd, address, length);
    unsigned ids[128], n = 0;
    char *copy = strdup(owners), *save = NULL;
    if (!copy) fail("strdup");
    for (char *p = strtok_r(copy, ",", &save); p; p = strtok_r(NULL, ",", &save)) {
        if (n == 128) fail("too many owners");
        ids[n++] = strtoul(p, NULL, 10);
    }
    free(copy);
    if (!n) fail("empty owner list");
    unsigned index = atomic_fetch_add(&sequence, 1), wanted = ids[index % n];
    int flags = fcntl(fd, F_GETFL), descriptor_flags = fcntl(fd, F_GETFD);
    if (flags < 0 || descriptor_flags < 0) fail("fcntl");
    for (unsigned attempt = 0; attempt < 512; ++attempt) {
        if (attempt) {
            int replacement = socket(AF_INET, SOCK_STREAM, 0);
            if (replacement < 0 || dup2(replacement, fd) < 0) fail("replace socket");
            close(replacement);
        }
        struct timeval timeout = {.tv_sec = 2};
        int yes = 1;
        if (fcntl(fd, F_SETFL, flags & ~O_NONBLOCK) < 0 ||
            setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) ||
            setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) ||
            setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &yes, sizeof(yes))) fail("socket setup");
        if (real_connect(fd, address, length)) fail("connect");
        const char request[] = "*2\r\n$5\r\nDEBUG\r\n$9\r\nIO-THREAD\r\n";
        size_t sent = 0;
        while (sent < sizeof(request)-1) {
            ssize_t count = send(fd, request+sent, sizeof(request)-1-sent, MSG_NOSIGNAL);
            if (count <= 0) fail("owner query send");
            sent += (size_t)count;
        }
        char reply[64]; size_t used = 0;
        while (used < sizeof(reply)-1) {
            if (recv(fd, reply+used, 1, 0) != 1) fail("owner query receive");
            if (reply[used++] == '\n') break;
        }
        reply[used] = 0;
        unsigned owner; char extra;
        if (sscanf(reply, ":%u\r\n%c", &owner, &extra) != 1 || used < 4 ||
            reply[used-2] != '\r' || reply[used-1] != '\n') fail("bad owner reply");
        if (owner != wanted) continue;
        timeout.tv_sec = 0;
        if (setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) ||
            setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) ||
            fcntl(fd, F_SETFL, flags) < 0 || fcntl(fd, F_SETFD, descriptor_flags) < 0)
            fail("restore socket");
        const char *path = getenv("LB_EPISODE_LOG");
        int logfd = path ? open(path, O_WRONLY|O_APPEND|O_CREAT|O_CLOEXEC, 0600) : -1;
        if (logfd < 0) fail("owner log open");
        struct timespec stamp; clock_gettime(CLOCK_MONOTONIC, &stamp);
        char line[256]; int size = snprintf(line, sizeof(line),
            "{\"index\":%u,\"owner\":%u,\"attempts\":%u,\"t\":%ld.%09ld}\n",
            index, owner, attempt+1, stamp.tv_sec, stamp.tv_nsec);
        if (write(logfd, line, (size_t)size) != size) fail("owner log write");
        close(logfd);
        return 0;
    }
    fail("owner never armed after 512 fresh connections");
    return -1;
}
'''


class Children:
    def __init__(self):
        self.processes = []

    def start(self, argv, log, cwd, env=None):
        print("COMMAND " + shlex.join(argv), flush=True)
        with log.open("wb") as stream:
            proc = subprocess.Popen(argv, stdout=stream, stderr=subprocess.STDOUT,
                                    cwd=cwd, env=env, start_new_session=True)
        self.processes.append(proc)
        return proc

    def close(self):
        for proc in reversed(self.processes):
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=10)


def cpu_ticks(path):
    # /proc comm may contain spaces or parentheses; field 3 follows the LAST ')'.
    fields = path.read_text().rsplit(")", 1)[1].split()
    return int(fields[11]) + int(fields[12])  # fields 14 + 15


class Sampler:
    def __init__(self, port, path, pid):
        self.port, self.path, self.pid = port, path, pid
        self.samples, self.error = [], None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        conn = None
        try:
            conn = Conn("127.0.0.1", self.port, timeout=2)
            with self.path.open("w") as stream:
                deadline = time.monotonic()
                while not self.stop.is_set():
                    started = time.monotonic()
                    row = {"t": started, "info": parse_info(conn.must("INFO", "LB")),
                           "signals": parse_signals(conn.must("DEBUG", "LBSIGNALS"))}
                    row["process_cpu_ticks"] = cpu_ticks(Path(f"/proc/{self.pid}/stat"))
                    row["monitor_cpu_ticks"] = cpu_ticks(Path(f"/proc/{self.pid}/task/{self.pid}/stat"))
                    row["capture_seconds"] = time.monotonic() - started
                    self.samples.append(row)
                    stream.write(json.dumps(row, allow_nan=False) + "\n")
                    stream.flush()
                    deadline += INTERVAL
                    self.stop.wait(max(0, deadline - time.monotonic()))
        except Exception as error:
            self.error = str(error)
        finally:
            if conn:
                conn.close()

    def close(self):
        self.stop.set()
        # Conn has a two-second socket timeout. Complete the join even on a
        # slow final capture; returning with a live observer races teardown.
        self.thread.join()
        require(self.error is None, "sampler failed: " + str(self.error))


def episode_failure(result, error, source):
    """Keep the first failure exact; later failures are structured diagnostics."""
    message = str(error)
    if result["status"] == "FAIL" and result.get("reason"):
        result.setdefault("diagnostics", []).append({"source": source, "message": message})
    else:
        result["reason"] = message
    result.update(status="FAIL", measurement_valid=False)


@contextmanager
def sampled_episode(sampler, result):
    """Classify the episode and join its observer inside the server lifetime."""
    try:
        sampler.thread.start()
        yield
    except Exception as error:
        episode_failure(result, error, "episode")
    finally:
        try:
            sampler.close()
        except Exception as error:
            result["sampler_error"] = str(error)
            episode_failure(result, error, "sampler")


def server_command(args, arm, mode, directory):
    # Match calib/lb-stationary.sh: the default split uses all 16 allowed CPUs.
    # --ratio specifies whole-server counts, not a ratio scaled to CPU affinity.
    argv = ["taskset", "-c", getattr(args, "server_cores", SERVER_CORES), str(ROOT / arm_table(args)[arm][0]),
            "--bind", "127.0.0.1", "--port", str(args.port), "--thread-mode", mode,
            "--key-lb", "1", "--client-lb", "1", "--flip-auto", "0",
            "--enable-debug-command", "yes", "--save", "", "--appendonly", "no",
            "--dir", str(directory), "--dbfilename", "seed.tomo"]
    if args.shards is not None:
        argv += ["--shards", str(args.shards)]
    return argv


def load_command(args, directory, label, low, high, duration=None, populate=False, owners=None):
    argv = ["taskset", "-c", getattr(args, "load_cores", LOAD_CORES), args.memtier, "-s", "127.0.0.1", "-p", str(args.port),
            "--protocol=redis", "-t", "8" if populate else "4", "-c", "4" if populate else "16",
            "--ratio=1:0", "--key-pattern=" + ("P:P" if populate else "R:R"),
            f"--key-minimum={low}", f"--key-maximum={high}", "--key-prefix=memtier-",
            "-d", str(DATA_SIZE), "--hide-histogram",
            "--json-out-file=" + str(directory / (label + ".json"))]
    if populate:
        argv += ["-n", str(KEYS // 32)]
    else:
        depth = getattr(args, "hot_pipeline", PIPELINE) if label == "hot" else PIPELINE
        argv += [f"--pipeline={depth}", "--test-time=" + str(duration)]
        if args.rate_per_client:
            argv += [f"--rate-limiting={args.rate_per_client}"]
    if owners is not None:
        argv = ["env", "LD_PRELOAD=" + str(args.output / "owner-select.so"),
                "LB_EPISODE_PORT=" + str(args.port),
                "LB_EPISODE_OWNERS=" + ",".join(map(str, owners)),
                "LB_EPISODE_LOG=" + str(directory / (label + ".owners.jsonl")), *argv]
    return argv


@contextmanager
def boot(args, arm, mode, directory, seed=None):
    verify_arms(args, arm)
    directory.mkdir(parents=True, exist_ok=False)
    if seed:
        shutil.copyfile(seed, directory / "seed.tomo")
        require(digest(directory / "seed.tomo") == digest(seed), "snapshot copy mismatch")
    # Bind without SO_REUSEPORT: never share with or kill another measurement's listener.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", args.port))
    children, conn = Children(), None
    try:
        proc = children.start(server_command(args, arm, mode, directory), directory / "server.log", directory)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            require(proc.poll() is None, "server exited during boot")
            try:
                conn = Conn("127.0.0.1", args.port, timeout=2)
                identity = parse_info(conn.must("INFO", "SERVER"), False)
                require(int(identity["process_id"]) == proc.pid, "server PID does not match owned child")
                break
            except (OSError, EOFError):
                if conn:
                    conn.close()
                    conn = None
                time.sleep(.1)
        require(conn is not None, "server boot timeout")
        sample = {"signals": parse_signals(conn.must("DEBUG", "LBSIGNALS"))}
        owners = geometry(sample, mode, args.shards, len(cpu_set(getattr(args, "server_cores", SERVER_CORES))))
        observed = len(sample["signals"]["shards"])
        require(int(identity["shards"]) == observed,
                f"INFO shards={identity['shards']}, DEBUG LBSIGNALS limit={observed}")
        identity["shards"] = observed
        parse_info(conn.must("INFO", "LB"))
        yield conn, children, owners, identity
    finally:
        if conn:
            conn.close()
        children.close()


def wait_loads(processes, sampler=None, timeout=600):
    deadline = time.monotonic() + timeout
    while any(p.poll() is None for p in processes):
        require(time.monotonic() < deadline, "load timeout")
        require(all(p.poll() in (None, 0) for p in processes), "memtier failed; inspect loader log")
        if sampler:
            require(sampler.error is None, "telemetry failed: " + str(sampler.error))
        time.sleep(.05)
    require(all(p.returncode == 0 for p in processes), "memtier failed; inspect loader log")
    return time.monotonic()


def key_mapping(conn, hotmax, shards):
    result = []
    for start in range(1, hotmax + 1, 128):
        keys = ["memtier-" + str(i) for i in range(start, min(hotmax + 1, start + 128))]
        rows = conn.must("DEBUG", "SHARDS", *keys)
        require(isinstance(rows, list) and len(rows) == len(keys), "bad physical key map")
        result.extend([key, int(row[0])] for key, row in zip(keys, rows))
    require(all(0 <= sid < shards for _, sid in result),
            f"DEBUG SHARDS hot-key ID outside limit=[0,{shards})")
    return result


def prepare_seed(args, mode):
    # Default shard counts differ by mode. A snapshot and its physical key map
    # are shared across every arm/probe/round *within* the observed geometry.
    directory = args.output / ("seed-" + mode)
    with boot(args, "PRE", mode, directory) as (conn, children, owners, identity):
        argv = load_command(args, directory, "populate", 1, KEYS, populate=True)
        proc = children.start(argv, directory / "populate.log", directory)
        wait_loads([proc])
        require(conn.must("DBSIZE") == KEYS, "population did not produce exactly 500000 keys")
        mapping = key_mapping(conn, args.hotmax, identity["shards"])
        require(conn.must("SAVE") == b"OK", "seed SAVE failed")
    path = directory / "seed.tomo"
    record = {"sha256": digest(path), "path": str(path), "hot_keys": mapping,
              "population_command": argv, "identity": identity, "mode": mode,
              "shards": identity["shards"], "arms_receipt": arms_receipt(args)}
    save_json(directory / "manifest.json", record)
    return path, record


def owner_evidence(directory, labels, expected):
    result = {}
    for label, targets in zip(labels, expected):
        rows = [json.loads(line) for line in (directory / (label + ".owners.jsonl")).read_text().splitlines()]
        require(len(rows) == 64 and {r["index"] for r in rows} == set(range(64)),
                "loader did not arm exactly 64 selected connections (or reconnected)")
        require(all(r["owner"] == targets[r["index"] % len(targets)] for r in rows),
                "connection selector did not produce requested owners")
        result[label] = rows
    return result


def cohort_owners(owners, episode):
    """Explicit connection-index -> owner plans, independent of boot accept order."""
    owners = sorted(owners)
    require(owners and len(owners) == len(set(owners)), "invalid boot IO owner list")
    balanced = [owners[i % len(owners)] for i in range(CONNECTIONS // 2)]
    hot = owners[:2] if episode == "client-skew" else owners
    return {"baseline-a": list(balanced), "baseline-b": list(balanced),
            "cold": list(balanced), "hot": [hot[i % len(hot)] for i in range(CONNECTIONS // 2)]}


def probe_verdict(result):
    if not result.get("measurement_valid"):
        return "FAIL", result.get("reason", "probe lacks valid telemetry/accounting")
    count = result["deltas"][KEY]
    if count == 0:
        return "REFUSED", f"UNARMED: {KEY} delta={count}, limit>0; key-skew matrix refused"
    return "PASS", f"ARMED: {KEY} delta={count}, limit>0; convergence scored separately in the matrix"


def episode_row(result):
    def fmt(value):
        return "NA" if value is None else f"{value:.6f}" if isinstance(value, float) else str(value)
    episode, mode, arm = (result[k] for k in ("episode", "mode", "arm"))
    if result.get("probe"):
        state = "UNARMED" if result["status"] == "REFUSED" else "ARMED" if result["status"] == "PASS" else "FAIL"
        row = f"LBPLANNER-EPISODE {episode} {mode} {arm} probe {state} "
        row += f"hotmax={fmt(result.get('hotmax'))} shard_count={fmt(result.get('shards'))} "
        row += " ".join(f"{k}={fmt(result.get('deltas', {}).get(PREFIX + k))}" for k in
                        ("hysteresis_refused", "no_candidate", "hot_bucket_refused"))
    else:
        row = f"LBPLANNER-EPISODE {episode} {mode} {arm} r{result['round']} "
        row += " ".join(f"{'shard_count' if k == 'shards' else k}={fmt(result.get(k))}" for k in (
            "t_converge", "key_moves", "client_moves", "gathers", "suffix_moves", "rate", "p99",
            "coord_busy", "shards", "hotmax", "envelope_return_t"))
    stall = result.get("stall") or {}
    row += " stall=" + ",".join(f"{k}:{fmt(stall.get(k))}" for k in STALL if k != "invalid")
    row += f" pending_ms={fmt(result.get('pending_ms'))} attempts={fmt(result.get('attempts'))}"
    row += f" baseline_client_moves={fmt(result.get('baseline_client_moves'))}"
    row += f" baseline_decision_client_moves={fmt(result.get('baseline_decision_client_moves'))}"
    row += f" suffix_other={fmt(result.get('suffix_other_moves'))}"
    row += " spread=" + ",".join(f"{k}:{fmt(result.get('spread_' + k))}" for k in ("base", "peak", "end", "min"))
    reduction = result.get("reduction")
    row += f" reduction={fmt(100 * reduction) + '%' if reduction is not None else 'NA'}"
    row += f" thrash_moves={fmt(result.get('thrash_moves'))}"
    if result.get("still_converging"):
        row += " (still converging)"
    row += " " + " ".join(f"{label}={fmt(result.get(key))}" for label, key in
                            zip(("moves", "returns", "exchanges", "shards"), OWNER_METRICS))
    if episode == "key-skew":
        row += f" refused={fmt(result.get('refused'))} escapes={fmt(result.get('escapes'))}"
    return row


def run_episode(args, arm, mode, episode, round_no, seed, seed_record, criterion=None, probe=False):
    calibration = episode == "balanced"
    name = f"{episode}-{mode}-{arm}-" + ("probe" if probe else f"r{round_no}")
    directory = args.output / name
    result = {"name": name, "arm": arm, "mode": mode, "episode": episode, "round": round_no,
              "binary": str(ROOT / arm_table(args)[arm][0]), "sha256": arm_table(args)[arm][1],
              "arms_receipt": arms_receipt(args), "shards": None, "hotmax": args.hotmax,
              "requested_shards": args.shards, "hot_pipeline": args.hot_pipeline,
              "probe": probe, "measurement_valid": False,
              "stall": None, "pending_ms": None, "attempts": None, "pass_limit": None,
              "seed_sha256": seed_record["sha256"], "criterion": criterion,
              "status": "FAIL", "sampling_interval": INTERVAL, "commands": [], "diagnostics": []}
    sampler = None
    try:
        with boot(args, arm, mode, directory, seed) as (conn, children, owners, identity):
            result["identity"] = identity
            result["shards"] = identity["shards"]
            placement = cohort_owners(owners, episode)
            result["cohort_owners"] = placement
            result["cohort_owners_method"] = "requested connection index -> sorted boot IO owners, round robin; actual placements in baseline.owners and owners"
            require(identity["shards"] == seed_record["shards"],
                    f"shards={identity['shards']}, seed limit={seed_record['shards']}")
            require(key_mapping(conn, args.hotmax, identity["shards"]) == seed_record["hot_keys"],
                    "physical key map changed from this mode's SHA-bound seed")
            sampler = Sampler(args.port, directory / "telemetry.jsonl", int(identity["process_id"]))
            with sampled_episode(sampler, result):
                baseline_start = time.monotonic()
                processes = []
                for label in ("baseline-a", "baseline-b"):
                    argv = load_command(args, directory, label, 1, KEYS,
                                        args.warm + args.baseline + 3, owners=placement[label])
                    result["commands"].append(argv)
                    processes.append(children.start(argv, directory / (label + ".log"), directory))
                baseline_end = wait_loads(processes, sampler, args.warm + args.baseline + 63)
                result["baseline"] = {"start": baseline_start, "end": baseline_end,
                                      "owners": owner_evidence(directory, ("baseline-a", "baseline-b"),
                                                               [placement[k] for k in ("baseline-a", "baseline-b")])}
                # Trim both connection setup and generator teardown. The last three seconds are
                # guard time, not calibration evidence. No candidate run refits PRE limits.
                balanced = [s for s in sampler.samples if
                            baseline_start + args.warm <= s["t"] <= baseline_start + args.warm + args.baseline]
                baseline_kind = ("client-skew" if args.episodes == "client-skew" else "key-skew") if calibration else episode
                own_baseline = baseline_stationarity(balanced, None if calibration else criterion["shard_owners"], baseline_kind)
                result["baseline_stationarity"] = own_baseline
                for field in ("baseline_client_moves", "baseline_key_moves", "baseline_earlier_client_moves",
                              "baseline_decision_client_moves"):
                    result[field] = own_baseline.get(field)
                require(own_baseline["status"] == "PASS", own_baseline["reason"])
                if calibration:
                    result["criterion"] = envelope(balanced, baseline_kind)
                    result.update(status="PASS", reason=own_baseline["reason"])
                else:
                    result["baseline_in_envelope_fraction"] = sum(inside(s, criterion) for s in balanced) / len(balanced)
                    diagnostic = diagnostic_envelope(criterion, own_baseline["spread_maxima"])
                    result["diagnostic_envelope"] = diagnostic
                    command_before = parse_info(conn.must("INFO", "COMMANDSTATS"), False)
                    stimulus = time.monotonic()
                    result["stimulus_t"] = stimulus
                    result["baseline_to_stimulus_gap"] = stimulus - baseline_end
                    processes = []
                    post_owners = [placement[k] for k in ("cold", "hot")]
                    ranges = [(args.hotmax + 1, KEYS), (1, args.hotmax)] if episode == "key-skew" else [(1, KEYS)] * 2
                    duration = args.max_converge + DECISION_SECONDS + args.suffix + 3
                    for label, targets, (low, high) in zip(("cold", "hot"), post_owners, ranges):
                        argv = load_command(args, directory, label, low, high, int(duration), owners=targets)
                        result["commands"].append(argv)
                        processes.append(children.start(argv, directory / (label + ".log"), directory))
                    finish = wait_loads(processes, sampler, duration + 60)
                    command_after = parse_info(conn.must("INFO", "COMMANDSTATS"), False)
                    # Fixed common window, ending before either load's requested test-time.
                    end = stimulus + duration - 3
                    result["loads_finished_t"] = finish
                    result["owners"] = owner_evidence(directory, ("cold", "hot"), post_owners)
                    result["stimulus_ready_t"] = max(r["t"] for rows in result["owners"].values() for r in rows)
                    require(result["stimulus_ready_t"] - stimulus < DECISION_SECONDS,
                            "connection burst took a full decision window; stimulus is not a step")
                    result.update(convergence(sampler.samples, stimulus, end, criterion, episode,
                                              args.max_converge, args.suffix, diagnostic))
                    result.update(metrics([json.loads((directory / (label + ".json")).read_text())
                                           for label in ("cold", "hot")], command_before, command_after,
                                          duration, args.hot_pipeline))
                    result["occupancy"] = occupancy(sampler.samples, stimulus, end, owners[0])
                    result["coord_busy"] = result["occupancy"]["coord_busy"]
                    result["coordinator_latency"] = None
                    result["coordinator_latency_reason"] = "memtier aggregate histograms do not identify connection owners after migration"
                    cpu_rows = [s for s in sampler.samples if stimulus <= s["t"] <= end]
                    result["cpu"] = {key + "_delta": cpu_rows[-1][key] - cpu_rows[0][key]
                                     for key in ("process_cpu_ticks", "monitor_cpu_ticks")}
                    result["cpu"]["clock_ticks_per_second"] = os.sysconf("SC_CLK_TCK")
                    result["measurement_valid"] = True
    except Exception as error:
        if result["status"] == "FAIL" and result.get("reason"):
            result["teardown_error"] = str(error)
        episode_failure(result, error, "teardown")
    finally:
        # A rejected baseline never starts the stimulus. Missing owner evidence
        # there is not a second finding, nor may it alter the baseline's cause.
        if sampler is not None and result.get("baseline_stationarity", {}).get("status") == "PASS":
            try:
                result.update(owner_tracking(sampler.samples))
            except ValueError as error:
                result["owner_tracking_error"] = str(error)
                result["owner_tracking"] = {"status": "FAIL", "reason": str(error)}
                episode_failure(result, error, "owner_tracking")
        if probe:
            result["convergence_status"] = result["status"]
            result["convergence_reason"] = result.get("reason")
            result["status"], result["reason"] = probe_verdict(result)
        summary = result.get("baseline_stationarity", {}).get("summary", "")
        if summary:
            result["diagnostics"].append({"source": "baseline_stationarity", "message": summary})
        directory.mkdir(parents=True, exist_ok=True)
        save_json(directory / "run.json", result)
    if not calibration:
        row = episode_row(result)
        print(row, flush=True)
        print(f"{name}: {result['status']} {result.get('reason', '')}", flush=True)
        with (args.output / "rows.txt").open("a") as stream:
            stream.write(row + "\n")
    return result


def schedule(episodes="both", rounds=3):
    for episode in (("key-skew", "client-skew") if episodes == "both" else (episodes,)):
        for mode in ("1s", "2s"):
            for number in range(1, rounds + 1):
                order = ("PRE", "PAD-A", "POST") if number % 2 else ("POST", "PAD-A", "PRE")
                for arm in order:
                    yield arm, mode, episode, number


def binomial_mix_pvalue(x, n, y, m):
    """Exact equality test for two binomial proportions, conditional on x+y.

    This is the two-sided Fisher test, including probabilities no greater than
    the observed table. No Gaussian approximation at rare/zero refusals.
    """
    require(0 <= x <= n and 0 <= y <= m,
            f"stall counts={x}/{n},{y}/{m}, limit=0<=count<=attempts")
    if n == m == 0:
        return 1.0
    if n == 0 or m == 0:
        return None  # no evidence about one of the actuator distributions
    def choose(a, b):
        return math.lgamma(a + 1) - math.lgamma(b + 1) - math.lgamma(a - b + 1)
    successes = x + y
    common = choose(n + m, successes)
    def log_probability(k):
        return choose(n, k) + choose(m, successes - k) - common
    observed = log_probability(x)
    return min(1.0, sum(math.exp(p) for k in range(max(0, successes - m), min(n, successes) + 1)
                        if (p := log_probability(k)) <= observed + 1e-10))


def compare_actuators(post, reference, alpha):
    reasons, evidence = [], {}
    label = reference["arm"]
    for short in STALL:
        x, y = post["stall"][short], reference["stall"][short]
        n, m = post["attempts"], reference["attempts"]
        try:
            probability = binomial_mix_pvalue(x, n, y, m)
        except ValueError as error:
            reasons.append(str(error))
            probability = None
        evidence[short] = {"POST": x, label: y, "POST_attempts": n, "reference_attempts": m,
                           "pvalue": probability, "alpha": alpha}
        if probability is None or probability < alpha:
            reasons.append(f"POST stall.{short}={x}/{n}, {label}={y}/{m}, "
                           f"binomial p={probability}, limit>={alpha:g}")
    if label == "PRE" and post["pass_limit"] != reference["pass_limit"]:
        reasons.append(f"POST pass_limit={post['pass_limit']}, limit={reference['pass_limit']} (PRE exact)")
    return reasons, evidence


def assess(results, episodes="both", rounds=3):
    def admissible(result):
        # Client PRE/PAD may stall on refusals. Their measured end spread is
        # still a control: demanding that it improve would again reject a
        # candidate precisely when it balances better than those controls.
        return (result.get("measurement_valid", result["status"] == "PASS") and
                (result["status"] == "PASS" or
                 (result["episode"] == "client-skew" and result["arm"] != "POST")))
    checks = []
    expected = list(schedule(episodes, rounds))
    identities = [(r["arm"], r["mode"], r["episode"], r["round"]) for r in results]
    complete = Counter(identities) == Counter(expected)
    # 95% family confidence over all predeclared arm/reason comparisons. This
    # allowance derives only from attempt counts and schedule size, never an arm.
    alpha = .05 / (len(expected) // 3 * 2 * len(STALL))
    pre_spreads = {}
    for pre in results:
        if (pre["arm"] == "PRE" and pre["episode"] == "client-skew" and
                pre.get("measurement_valid", True) and pre.get("spread_end") is not None):
            pre_spreads.setdefault(pre["mode"], {})[pre["round"]] = pre["spread_end"]
    for post in (r for r in results if r["arm"] == "POST"):
        paired = {r["arm"]: r for r in results if all(r[k] == post[k] for k in ("episode", "mode", "round"))}
        pre = paired.get("PRE")
        reasons, mix, spread_comparison, owner_comparison = [], {}, None, {}
        if set(paired) != set(ARMS) or any(not admissible(r) for r in paired.values()):
            reasons.append("PRE, PAD-A or POST missing, lacks valid evidence, or failed required convergence checks")
        else:
            if post["episode"] == "client-skew":
                rounds = pre_spreads.get(post["mode"], {})
                require(bool(rounds), "missing PRE spread endpoints")
                width = max(rounds.values()) - min(rounds.values())
                limit = pre["spread_end"] + width
                spread_comparison = {"POST": post["spread_end"], "PRE": pre["spread_end"],
                                     "PRE_rounds": rounds, "PRE_width": width, "limit": limit}
                if post["spread_end"] > limit:
                    reasons.append(f"POST spread_end={post['spread_end']}, limit<={limit} "
                                   f"(paired PRE + PRE round range {width})")
                compared = ("p99",)  # completed moves and last-move time are evidence, not costs
            else:
                compared = ("t_converge", "key_moves", "client_moves", "suffix_moves", "suffix_other_moves", "p99")
            for key in compared:
                if post[key] > pre[key]:
                    reasons.append(f"POST {key}={post[key]}, limit<={pre[key]} (PRE)")
            if post["rate"] < pre["rate"]:
                reasons.append(f"POST rate={post['rate']}, limit>={pre['rate']} (PRE)")
            # A merged rate/quantile must not hide a loss on the hot or cold cohort.
            for index, (pre_load, post_load) in enumerate(zip(pre.get("loaders", []), post.get("loaders", []))):
                for key, valid in (("rate", post_load["rate"] >= pre_load["rate"]),
                                   ("p99", post_load["p99"] <= pre_load["p99"])):
                    if not valid:
                        reasons.append(f"POST loader[{index}].{key}={post_load[key]}, "
                                       f"limit{'>' if key == 'rate' else '<'}={pre_load[key]} (PRE)")
        # Retain comparisons even when convergence failed, provided the endpoint
        # counters exist. This keeps the actuator failure visible in report.json.
        missing_mix = [arm for arm in ARMS if arm in paired and paired[arm].get("stall") is None]
        if missing_mix:
            reasons.append("actuator evidence missing for " + ", ".join(missing_mix) + "; limit=all arms")
        if post.get("stall") is not None:
            for control in ("PRE", "PAD-A"):
                if control not in paired or paired[control].get("stall") is None:
                    continue
                failures, mix[control] = compare_actuators(post, paired[control], alpha)
                reasons.extend(failures)
        # Cycles can be the cause of a convergence failure. Preserve their
        # paired evidence even on failed traces, just as for actuator counters.
        for control in ("PRE", "PAD-A"):
            if control not in paired:
                continue
            owner_comparison[control] = {}
            for key in OWNER_METRICS:
                value, limit = post.get(key), paired[control].get(key)
                owner_comparison[control][key] = {"POST": value, control: limit}
                if value is None or limit is None:
                    reasons.append(f"owner evidence missing: {key} POST={value}, {control}={limit}")
                elif value > limit:
                    reasons.append(f"POST {key}={value}, limit<={limit} ({control})")
        checks.append({"episode": post["episode"], "mode": post["mode"], "round": post["round"],
                       "status": "FAIL" if reasons else "PASS", "reasons": reasons, "actuator_mix": mix,
                       "spread_comparison": spread_comparison, "owner_comparison": owner_comparison})
    return {"status": "PASS" if complete and all(c["status"] == "PASS" for c in checks)
            and all(admissible(r) for r in results) else "FAIL", "checks": checks,
            "schedule_complete": complete,
            "rule": "key-skew: POST's last required move is no slower than PRE, with no more required moves, other-kind moves or suffix_other moves; "
                    "client-skew: POST spread_end <= paired PRE spread_end + the range of valid PRE spread_end rounds in the same mode; "
                    "completed moves, thrash_moves and t_converge are reported, continued spread improvement is balancing; "
                    "client controls need valid measurements, POST must improve without stalled-spread thrash; "
                    "both: POST observed shard_moves, returns, exchanges and distinct_shards <= PRE and <= PAD-A; "
                    "no aggregate/cohort rate or p99 loss, PRE/PAD-A actuator mix within binomial counting noise, PassLimit == PRE exactly; every paired round must pass",
            "actuator_noise": {"method": "two-sided exact conditional binomial (Fisher), Bonferroni over scheduled comparisons",
                               "family_alpha": .05, "comparison_alpha": alpha},
            "pad_kind": "A: PRE behaviour with candidate text size/layout; diagnostic control, no placement claim without mainline null",
            "rate_tail_tolerance": "none; no arm-dependent or invented noise allowance"}


def replay_episode(path, config, criteria):
    """Recompute from saved telemetry without refitting PRE or trusting old scores."""
    saved = json.loads(path.read_text())
    # Copy only identity, placement receipts and workload measurements. In
    # particular, missing telemetry must never print yesterday's thrash count
    # as though it had been recomputed under today's rules.
    fields = ("name", "episode", "mode", "arm", "round", "probe", "hotmax", "shards",
              "hot_pipeline", "binary", "sha256", "arms_receipt", "seed_sha256",
              "requested_shards", "baseline", "stimulus_t", "owners", "cohort_owners",
              "rate", "p99", "loaders", "accounting", "p99_method", "coord_busy")
    result = {k: saved[k] for k in fields if k in saved}
    result.update(status="NA", measurement_valid=False, diagnostics=[],
                  replay={"saved_status": saved.get("status"), "saved_reason": saved.get("reason"),
                          "saved_measurement_valid": saved.get("measurement_valid", False),
                          "measurement_source": "saved run.json rate/HDR/accounting; no new measurement",
                          "missing": []})
    if result["episode"] != "balanced" and result.get("stimulus_t") is None:
        result["replay"]["missing"].append("post-stimulus evidence (no saved stimulus_t)")
    telemetry = path.with_name("telemetry.jsonl")
    if not telemetry.is_file():
        result["replay"]["missing"].append(str(telemetry))
        return dict(result, reason="missing telemetry.jsonl; current rules cannot be scored")
    errors = []
    try:
        with telemetry.open() as stream:
            samples = [json.loads(line) for line in stream]
        result.update(owner_tracking(samples))
    except (ValueError, KeyError, TypeError, OSError) as error:
        return dict(result, status="FAIL", reason="invalid telemetry: " + str(error))
    calibration = result["episode"] == "balanced"
    kind = ("client-skew" if config.get("episodes") == "client-skew" else "key-skew") if calibration else result["episode"]
    criterion = saved.get("criterion") or criteria.get(result["mode"])
    result["criterion"] = criterion  # never re-fit a newly admissible calibration
    needed = ("warm", "baseline") if calibration or result.get("stimulus_t") is None else (
        "warm", "baseline", "max_converge", "suffix")
    missing_config = [k for k in needed if k not in config]
    if missing_config:
        result["replay"]["missing"].append("manifest.json config: " + ", ".join(missing_config))
        return dict(result, reason="missing saved configuration: " + ", ".join(missing_config))
    if not calibration and criterion is None:
        result["replay"]["missing"].append("frozen PRE criterion (run.json or criteria.json)")
        return dict(result, reason="missing frozen PRE criterion; refusing to refit from another baseline")
    try:
        start = saved["baseline"]["start"] + config["warm"]
        stop = start + config["baseline"]
        balanced = [s for s in samples if start <= s["t"] <= stop]
        require(balanced and balanced[0]["t"] - start <= .5 and stop - balanced[-1]["t"] <= .5,
                "missing baseline endpoint coverage (limit<=0.5s)")
        baseline = baseline_stationarity(balanced, None if calibration else criterion["shard_owners"], kind)
        result["baseline_stationarity"] = baseline
        for key in ("baseline_client_moves", "baseline_key_moves", "baseline_earlier_client_moves",
                    "baseline_decision_client_moves"):
            result[key] = baseline.get(key)
        if baseline["status"] != "PASS":
            errors.append(baseline["reason"])
        if calibration:
            return dict(result, status=baseline["status"], reason=baseline["reason"])
        if result.get("stimulus_t") is None:
            message = "no saved stimulus; baseline=" + baseline["status"]
            if errors:
                result["diagnostics"].append({"source": "replay", "message": message})
            return dict(result, status="FAIL" if errors else "NA",
                        reason=errors[0] if errors else message)
        stimulus = result["stimulus_t"]
        end = stimulus + config["max_converge"] + DECISION_SECONDS + config["suffix"]
        diagnostic = diagnostic_envelope(criterion, baseline["spread_maxima"])
        result["diagnostic_envelope"] = diagnostic
        result.update(convergence(samples, stimulus, end, criterion, kind,
                                  config["max_converge"], config["suffix"], diagnostic))
        # Old convergence FAIL with valid accounting can be rescored. An old
        # telemetry/accounting/teardown failure cannot silently become valid.
        if not saved.get("measurement_valid") or any(saved.get(k) is None for k in
                                                      ("accounting", "rate", "p99", "loaders")):
            errors.append("saved workload measurement lacks valid accounting/telemetry evidence")
        result["measurement_valid"] = not errors
        if errors:
            result["diagnostics"].extend({"source": "replay", "message": message}
                                         for message in [*errors[1:], result["reason"]])
            result.update(status="FAIL", reason=errors[0])
    except (ValueError, KeyError, TypeError) as error:
        if errors:
            result.update(status="FAIL", reason=errors[0])
        episode_failure(result, "replay scoring failed: " + str(error), "replay")
    if result.get("probe"):
        result["convergence_status"], result["convergence_reason"] = result["status"], result["reason"]
        result["status"], result["reason"] = probe_verdict(result)
    return result


def replay(directory):
    """Read-only campaign, episode, or archive collection replay; never boots."""
    directory = directory.resolve()
    require(directory.is_dir(), "replay directory missing: " + str(directory))
    paths = sorted(directory.rglob("run.json"))
    require(bool(paths), "replay has no run.json files: " + str(directory))
    campaigns = {}
    for path in paths:
        campaign = path.parent.parent
        if campaign not in campaigns:
            metadata = {}
            for name in ("manifest", "criteria"):
                source = campaign / (name + ".json")
                metadata[name] = json.loads(source.read_text()) if source.is_file() else {}
            campaigns[campaign] = dict(metadata, results=[])
        data = campaigns[campaign]
        result = replay_episode(path, data["manifest"].get("config", {}), data["criteria"])
        data["results"].append(result)
        if result["episode"] != "balanced":
            print(episode_row(result))
        baseline = result.get("baseline_stationarity", {}).get("status", "NA")
        print(f"LBPLANNER-REPLAY {path.parent.name} {result['status']} baseline={baseline} "
              f"saved={result['replay']['saved_status']}: {result['reason']}")
        for missing in result["replay"]["missing"]:
            print(f"LBPLANNER-REPLAY-MISSING {path.parent.name}: {missing}")
    reports = []
    for campaign, data in campaigns.items():
        results = [r for r in data["results"] if r["episode"] != "balanced" and not r.get("probe")]
        kinds = {r["episode"] for r in results}
        episodes = data["manifest"].get("config", {}).get("episodes") or (
            next(iter(kinds)) if len(kinds) == 1 else "both")
        present = {(r["arm"], r["mode"], r["episode"], r["round"]) for r in results}
        rounds = data["manifest"].get("config", {}).get("rounds", 3)
        missing = [f"{e}-{m}-{a}-r{n}/run.json" for a, m, e, n in schedule(episodes, rounds)
                   if (a, m, e, n) not in present]
        for name in missing:
            print(f"LBPLANNER-REPLAY-MISSING {campaign / name}")
        report = assess(results, episodes, rounds)
        for check in report["checks"]:
            print(f"LBPLANNER-REPLAY-PAIR {check['episode']} {check['mode']} r{check['round']} "
                  f"{check['status']}: " + ("; ".join(check["reasons"]) or "all paired rules passed"))
        print(f"LBPLANNER-REPLAY-VERDICT {campaign} {report['status']} "
              f"schedule_complete={report['schedule_complete']}; saved rate/HDR, current telemetry rules")
        reports.append({"directory": str(campaign), "results": data["results"], "report": report,
                        "missing_runs": missing})
    return {"status": "PASS" if all(r["report"]["status"] == "PASS" for r in reports) else "FAIL",
            "campaigns": reports}


def dry_run(args):
    def command(argv):
        print(shlex.join(argv))
    print("# DRY RUN: no processes, sockets or output files are created")
    for arm, (path, sha) in arm_table(args).items():
        print(f"# SHA256 REQUIRED {arm} {sha} {ROOT / path}")
    print("# ARMS RECEIPT " + json.dumps(arms_receipt(args), sort_keys=True))
    jobs = list(schedule(args.episodes, args.rounds))
    modes = sorted({mode for _, mode, _, _ in jobs})
    probes = args.episodes in ("key-skew", "both")
    def job(arm, mode, episode, number, probe=False):
        directory = args.output / (f"{episode}-{mode}-{arm}-" + ("probe" if probe else f"r{number}"))
        owners = ["<boot-io-owners>"]
        if episode == "balanced" and number > 1:
            print("# CONDITIONAL: only if preceding calibration failed to arm; fresh snapshot/server, bounded to 3")
        print(f"# {directory.name}: copy seed-{mode}; verify SHA/key map/shards/actual owner IDs")
        command(server_command(args, arm, mode, directory))
        print("# RESP: INFO SERVER (owned PID); DEBUG SHARDS; INFO LB + DEBUG LBSIGNALS every 100 ms")
        print("# Selector RESP per connection attempt: DEBUG IO-THREAD (<=512 fresh sockets); actual IO IDs come from boot")
        print("# Owner placeholders expand to 64 round-robin slots over sorted DEBUG LBSIGNALS IO/fused IDs; EX IDs are excluded")
        for label in ("baseline-a", "baseline-b"):
            command(load_command(args, directory, label, 1, KEYS, args.warm + args.baseline + 3, owners=owners))
        if episode != "balanced":
            print("# RESP: INFO COMMANDSTATS before/after both complete post-stimulus generators")
            ranges = [(args.hotmax + 1, KEYS), (1, args.hotmax)] if episode == "key-skew" else [(1, KEYS)] * 2
            for label, (low, high) in zip(("cold", "hot"), ranges):
                targets = ["<first-two-boot-io-owners>"] if episode == "client-skew" and label == "hot" else owners
                command(load_command(args, directory, label, low, high,
                                     int(args.max_converge + DECISION_SECONDS + args.suffix + 3), owners=targets))
        print("# stop sampler; SIGTERM owned server process group; wait (SIGKILL only on timeout)")
    if probes:
        print("# ADMISSIBILITY PROBES FIRST (preview): live prerequisites are the seed/calibration commands below")
        for mode in modes:
            job("PRE", mode, "key-skew", 0, probe=True)
        print("# Any valid probe with bucket_moves delta=0: receipt UNARMED, verdict REFUSED, exit 3 BEFORE the matrix")
    print("# PREREQUISITES: compile selector, prepare each mode's seed, calibrate PRE")
    command(["cc", "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror", "-o",
             str(args.output / "owner-select.so"), str(args.output / "owner-select.c"), "-ldl"])
    for mode in modes:
        seed = args.output / ("seed-" + mode)
        command(server_command(args, "PRE", mode, seed))
        command(load_command(args, seed, "populate", 1, KEYS, populate=True))
        print(f"# RESP 127.0.0.1:{args.port}: INFO SERVER, INFO LB, DEBUG LBSIGNALS, DBSIZE;")
        print(f"# DEBUG SHARDS memtier-1 ... memtier-{args.hotmax} in batches of 128; SAVE")
        for attempt in range(1, 4):
            job("PRE", mode, "balanced", attempt)
    print("# SCORED MATRIX (only after every requested key probe is ARMED)")
    for arm, mode, episode, number in jobs:
        job(arm, mode, episode, number)
    print(f"# nominal load time {wall_seconds(args) / 60:.1f} minutes + population/boot/SAVE/connection setup")


def wall_seconds(args):
    jobs = list(schedule(args.episodes, args.rounds))
    modes = len({mode for _, mode, _, _ in jobs})
    probes = modes if args.episodes in ("key-skew", "both") else 0
    observations = len(jobs) + probes
    return ((modes + observations) * (args.warm + args.baseline + 3) +
            observations * (args.max_converge + DECISION_SECONDS + args.suffix + 3))


def cpu_set(text):
    result = set()
    for entry in text.split(","):
        parts = entry.split("-")
        require(1 <= len(parts) <= 2 and all(p.isdecimal() for p in parts), "invalid CPU list: " + text)
        first, last = int(parts[0]), int(parts[-1])
        require(first <= last, "reversed CPU range: " + text)
        result.update(range(first, last + 1))
    require(bool(result), "empty CPU list")
    return result


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--self-test", action="store_true")
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--replay", type=Path, metavar="RUNDIR",
                        help="read-only rescore of saved run.json/telemetry.jsonl; uses saved configuration and frozen PRE criteria")
    parser.add_argument("--output", type=Path, default=ROOT / "build/lbplanner-episodes")
    parser.add_argument("--memtier", default="memtier_benchmark")
    parser.add_argument("--port", type=int, default=7931)
    parser.add_argument("--rounds", type=int, default=3, help="rounds per arm and mode; lbosc3 requires at least 6")
    parser.add_argument("--server-cores", default=SERVER_CORES)
    parser.add_argument("--load-cores", default=LOAD_CORES)
    parser.add_argument("--hotmax", type=int, default=int(os.environ.get("HOTMAX", "2000")))
    parser.add_argument("--hot-pipeline", type=int, default=PIPELINE,
                        help="hot stimulus cohort depth; cold and balanced cohorts stay at 128")
    parser.add_argument("--shards", type=int, default=None,
                        help="omit by default: use and record the server's observed default shard count")
    parser.add_argument("--episodes", choices=("key-skew", "client-skew", "both"), default="both")
    parser.add_argument("--arms", type=Path, help="explicit PRE/PAD-A/POST path+sha256 JSON receipt")
    parser.add_argument("--warm", type=int, default=30)
    parser.add_argument("--baseline", type=int, default=60)
    parser.add_argument("--max-converge", type=int, default=180)
    parser.add_argument("--suffix", type=int, default=30)
    parser.add_argument("--rate-per-client", type=int, default=0,
                        help="0: stationary driver's closed loop; positive: same fixed memtier cap for every arm")
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    if args.self_test:
        return 0 if unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SelfTest)).wasSuccessful() else 1
    if args.replay is not None:
        return 0 if replay(args.replay)["status"] == "PASS" else 1
    args.output = args.output.resolve()
    require(args.rounds > 0, "--rounds must be positive")
    server_cpus, load_cpus = cpu_set(args.server_cores), cpu_set(args.load_cores)
    require(not server_cpus & load_cpus, "server/load CPUs must be disjoint")
    require(args.warm >= 30 and args.baseline >= 12, "keep warm >=30 s and baseline >=12 s")
    require(args.max_converge >= DECISION_SECONDS and args.suffix >= DECISION_SECONDS,
            "convergence and suffix must each cover a decision window")
    require(1 <= args.hotmax < KEYS and 0 < args.port < 65536 and args.rate_per_client >= 0, "invalid workload argument")
    require(args.shards is None or args.shards > 0, "--shards must be positive or omitted")
    require(args.hot_pipeline > 0, "--hot-pipeline must be positive")
    args.arm_table, args.arms_receipt = bind_arms(args.arms)
    if args.dry_run:
        dry_run(args)
        return 0
    require(not args.output.exists(), "output must be new; never overwrite or cherry-pick prior trials")
    require("LD_PRELOAD" not in os.environ, "unset inherited LD_PRELOAD before a matched measurement")
    verify_arms(args)
    memtier = shutil.which(args.memtier)
    require(memtier is not None, "memtier executable missing")
    args.memtier = str(Path(memtier).resolve())
    require(server_cpus | load_cpus <= os.sched_getaffinity(0), "required server/load CPUs unavailable")
    os.sched_setaffinity(0, load_cpus)
    args.output.mkdir(parents=True)
    (args.output / "owner-select.c").write_text(SELECTOR_C)
    compile_argv = ["cc", "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror", "-o",
                    str(args.output / "owner-select.so"), str(args.output / "owner-select.c"), "-ldl"]
    with (args.output / "owner-select-build.log").open("wb") as log:
        subprocess.run(compile_argv, check=True, stdout=log, stderr=subprocess.STDOUT)
    jobs = list(schedule(args.episodes, args.rounds))
    modes = sorted({mode for _, mode, _, _ in jobs})
    manifest = {"arms": arm_table(args), "arms_receipt": arms_receipt(args),
                "identity": {"shards": {}, "arms_receipt": arms_receipt(args)},
                "pad_kind": "A: PRE behaviour with POST text size/layout",
                "config": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                "schedule": jobs, "memtier_sha256": digest(args.memtier),
                "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in
                                  (Path(__file__).resolve(), ROOT / "tests/_lib.py", ROOT / "tests/abba_workloads.py")},
                "selector_sha256": digest(args.output / "owner-select.so"),
                "expected_load_seconds": wall_seconds(args), "started_unix": time.time()}
    save_json(args.output / "manifest.json", manifest)
    seeds, criteria = {}, {}
    for mode in modes:
        seed, seed_record = prepare_seed(args, mode)
        seeds[mode] = (seed, seed_record)
        manifest["identity"]["shards"][mode] = seed_record["shards"]
        manifest.setdefault("seeds", {})[mode] = seed_record
        save_json(args.output / "manifest.json", manifest)
        for attempt in range(1, 4):
            calibration = run_episode(args, "PRE", mode, "balanced", attempt, seed, seed_record)
            if calibration["status"] == "PASS":
                break
            print(f"PRE balanced {mode} fresh-state attempt {attempt}/3: {calibration.get('reason')}", flush=True)
        require(calibration["status"] == "PASS", f"PRE balanced {mode} never armed after 3 fresh-state attempts: {calibration.get('reason')}")
        criteria[mode] = calibration["criterion"]
    save_json(args.output / "criteria.json", criteria)
    probes = []
    if args.episodes in ("key-skew", "both"):
        for mode in modes:
            seed, seed_record = seeds[mode]
            probes.append(run_episode(args, "PRE", mode, "key-skew", 0, seed, seed_record,
                                      criteria[mode], probe=True))
            save_json(args.output / "probes.json", probes)
        if any(r["status"] != "PASS" for r in probes):
            refused = any(r["status"] == "REFUSED" for r in probes)
            report = {"status": "REFUSED" if refused else "FAIL", "probes": probes,
                      "rule": "every requested PRE key-skew probe must admit a key move; no automatic stimulus changes"}
            save_json(args.output / "report.json", report)
            save_json(args.output / "results.json", [])
            print("LBPLANNER-VERDICT " + report["status"] + ": " + report["rule"])
            return 3 if refused else 1
    results = []
    for arm, mode, episode, number in jobs:
        seed, seed_record = seeds[mode]
        results.append(run_episode(args, arm, mode, episode, number, seed, seed_record, criteria[mode]))
        save_json(args.output / "results.json", results)
    report = assess(results, args.episodes, args.rounds)
    save_json(args.output / "report.json", report)
    print("LBPLANNER-VERDICT " + report["status"] + ": " + report["rule"])
    return 0 if report["status"] == "PASS" else 1


class SelfTest(unittest.TestCase):
    @staticmethod
    def sample(t, spread=1, key=0, client=0, gathers=0):
        info = {name: 0 for name in FIELDS}
        info.update({TICKS: int(t), KEY: key, CLIENT: client, GATHERS: gathers,
                     **{k: spread for k in SPREADS}})
        return {"t": t, "info": info, "signals": {"shards": {0: {"owner": 0}}, "threads": {0: {
            "role": "fused", "busy_ns": int(t * 800), "idle_ns": int(t * 200),
            "cpu_ns": int(t * 900), "ops": int(t * 100)}}}}

    def trace(self, end=40, moving=True, excursion=True):
        return [self.sample(i / 10, 10 if excursion and 150 <= i < 180 else 1,
                            int(moving and i >= 180), int(moving and i >= 180),
                            int(moving and i >= 170)) for i in range(end * 10 + 1)]

    def criterion(self):
        return envelope(self.trace()[:130])

    def test_converges_and_counts_separately(self):
        for episode in ("key-skew", "client-skew"):
            result = convergence(self.trace(), 14, 40, self.criterion(), episode, 20, 3)
            self.assertEqual(result["status"], "PASS")
            self.assertAlmostEqual(result["t_converge"], 4)
            self.assertEqual((result["key_moves"], result["client_moves"], result["total_moves"]), (1, 1, 2))
            self.assertEqual(result["suffix_moves"], 0)

    def test_unarmed_and_no_move_fail(self):
        result = convergence(self.trace(moving=False), 14, 40, self.criterion(), "key-skew", 20, 3)
        self.assertEqual(result["status"], "FAIL")
        self.assertIsNone(result["t_converge"])
        # The move itself witnesses engagement; a baseline-max excursion is no gate.
        result = convergence(self.trace(excursion=False), 14, 40, self.criterion(), "key-skew", 20, 3)
        self.assertEqual(result["status"], "PASS")

    def test_suffix_other_moves_reported_and_truncation_fails(self):
        trace = self.trace()
        for s in trace:
            if s["t"] >= 30:
                s["info"][CLIENT] += 1
        result = convergence(trace, 14, 40, self.criterion(), "key-skew", 20, 3)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual((result["suffix_moves"], result["suffix_other_moves"]), (0, 1))
        self.assertIn(" suffix_other=1", episode_row(dict(result, episode="key-skew", mode="1s", arm="PRE", round=1)))
        self.assertEqual(convergence(trace, 14, 24, self.criterion(), "key-skew", 20, 10)["status"], "FAIL")
        trace = self.trace()
        for s in trace:
            if s["t"] >= 30:
                s["info"][KEY] += 1
        result = convergence(trace, 14, 40, self.criterion(), "client-skew", 20, 3)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["suffix_other_moves"], 1)
        self.assertIn("key moves during client suffix", result["reason"])

    def test_later_rebound_fails_without_restarting_clock(self):
        trace = self.trace()
        for s in trace:
            if 25 <= s["t"] < 30:
                s["info"][SPREADS[0]] = 10
        result = convergence(trace, 14, 40, self.criterion(), "key-skew", 20, 3)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(SPREADS[0] + "=10, limit=2", result["reason"])
        self.assertAlmostEqual(result["t_converge"], 4)
        trace = self.trace()
        for s in trace:
            if s["t"] >= 30:
                s["info"][STAGE] = 5
        self.assertEqual(convergence(trace, 14, 40, self.criterion(), "key-skew", 20, 3)["status"], "FAIL")

    def test_duplicate_ticks_and_reset(self):
        trace = self.trace()
        self.assertEqual(len(beats(trace)), 40)
        trace[22]["info"][TICKS] = 0
        with self.assertRaises(ValueError):
            beats(trace)
        with self.assertRaises(ValueError):
            envelope(self.trace()[:30])
        with self.assertRaises(ValueError):
            beats(self.trace()[::20])

    def test_envelope_frozen_and_baseline_motion_refused(self):
        criterion = self.criterion()
        trace = self.trace()
        for s in trace:
            if s["t"] >= 18:
                s["info"][SPREADS[0]] = 2
        result = convergence(trace, 14, 40, criterion, "key-skew", 20, 3)
        self.assertEqual(result["status"], "PASS")
        self.assertIsNone(result["envelope_return_t"])
        self.assertIn("envelope_return_t=NA", episode_row(dict(result, episode="key-skew", mode="1s", arm="PRE", round=1)))
        self.assertEqual(criterion["upper"][SPREADS[0]], 1)
        with self.assertRaises(ValueError):
            envelope(self.trace()[150:300])

    def test_info_parsing(self):
        raw = b"# LB\r\ntomokv_keylb_enabled:1\r\ntomokv_clientlb_enabled:1\r\n" + b"".join(
            f"{k}:1\r\n".encode() for k in FIELDS)
        self.assertEqual(parse_info(raw)[KEY], 1)
        for broken in (raw.replace((KEY + ":1\r\n").encode(), b""), raw + b"tomokv_keylb_ticks:1\r\n",
                       raw.replace((SPREADS[0] + ":1").encode(), (SPREADS[0] + ":nan").encode())):
            with self.assertRaises(ValueError):
                parse_info(broken)

    def test_signals_parsing_and_coordinator(self):
        raw = ("lbver 1 stamp_ns 42\nthread 0 fused " + " ".join(["0"] * 20) +
               "\nshard 0 0 0 100 0 0 4 256\nderived thread_mode 1s client_threads 1\n").encode()
        self.assertEqual(parse_signals(raw)["shards"][0]["ops"], 100)
        with self.assertRaises(ValueError):
            parse_signals(raw.replace(b"lbver 1", b"lbver 2"))
        self.assertEqual(occupancy(self.trace(), 1, 10, 0)["coord_busy"], 80)

    @staticmethod
    def topology_sample(roles, mode="2s", shards=16):
        rows = ["lbver 1 stamp_ns 42"]
        rows += [f"thread {tid} {role} " + " ".join(["0"] * 20) for tid, role in roles]
        writers = [tid for tid, role in roles if role in ("ex", "fused")]
        rows += [f"shard {sid} {writers[sid % len(writers)]} 0 100 0 0 4 256" for sid in range(shards)]
        rows += [f"derived thread_mode {mode} client_threads {sum(r != 'ex' for _, r in roles)}"]
        return {"signals": parse_signals(("\n".join(rows) + "\n").encode())}

    def test_failed_split_topology_from_saved_server_log(self):
        # Exact startup rows from build/lbplanner-episodes-mainline-01/
        # balanced-2s-PRE-r1/server.log. DEBUG LBSIGNALS names ifid's role "io".
        # Keep the excerpt inline so self-test needs no local measurement files.
        saved_rows = """  thread t0: role=ifid cpu=0 L3=0 shards=0
  thread t1: role=ifid cpu=1 L3=0 shards=0
  thread t2: role=ifid cpu=2 L3=0 shards=0
  thread t3: role=ex cpu=3 L3=0 shards=8
  thread t4: role=ifid cpu=8 L3=1 shards=0
  thread t5: role=ifid cpu=9 L3=1 shards=0
  thread t6: role=ifid cpu=10 L3=1 shards=0
  thread t7: role=ex cpu=11 L3=1 shards=8"""
        roles = [(int(v[1][1:-1]), "io" if v[2] == "role=ifid" else "ex")
                 for v in map(str.split, saved_rows.splitlines())]
        sample = self.topology_sample(roles)
        threads = sample["signals"]["threads"]
        self.assertEqual([tid for tid, row in threads.items() if row["role"] == "io"],
                         [0, 1, 2, 4, 5, 6])
        with self.assertRaises(ValueError) as failure:
            geometry(sample, "2s")
        self.assertIn("observed Counter({'io': 6, 'ex': 2})", str(failure.exception))

    def test_split_topology_and_selector_exclude_ex_owners(self):
        args = SimpleNamespace(output=Path("/unused"), port=7931,
                               memtier="memtier_benchmark", rate_per_client=0)
        # Two interleaved domains; accept both the default 8:8 and other valid splits.
        for expected in ([0, 1, 2, 3, 8, 9, 10, 11], [0, 1, 2, 8, 9, 10], [1, 9]):
            with self.subTest(io_owners=expected):
                sample = self.topology_sample([(tid, "io" if tid in expected else "ex")
                                               for tid in reversed(range(16))])
                owners = geometry(sample, "2s")
                self.assertEqual(owners, expected)
                for targets in (owners, owners[:2]):
                    argv = load_command(args, args.output, "hot", 1, KEYS, 216, owners=targets)
                    selected = next(v for v in argv if v.startswith("LB_EPISODE_OWNERS="))
                    ids = list(map(int, selected.partition("=")[2].split(",")))
                    self.assertEqual(ids, targets)
                    self.assertTrue(all(sample["signals"]["threads"][tid]["role"] == "io" for tid in ids))

    def test_geometry_rejects_wrong_counts_or_roles(self):
        self.assertEqual(geometry(self.topology_sample([(t, "fused") for t in range(16)], "1s"), "1s"),
                         list(range(16)))
        for mode, roles in (
                ("1s", [(t, "fused") for t in range(15)]),
                ("2s", [(t, "io" if t == 0 else "ex") for t in range(16)]),
                ("2s", [(t, "io" if t < 8 else "ex") for t in range(17)]),
                ("2s", [(t, "fused" if t == 0 else "io" if t < 8 else "ex") for t in range(16)])):
            with self.subTest(mode=mode, roles=roles), self.assertRaisesRegex(ValueError, "observed Counter"):
                geometry(self.topology_sample(roles, mode), mode)

    def test_orders_and_sha_pins(self):
        jobs = list(schedule())
        self.assertEqual(len(jobs), 36)
        self.assertEqual([j[0] for j in jobs[:9]], ["PRE", "PAD-A", "POST", "POST", "PAD-A", "PRE", "PRE", "PAD-A", "POST"])
        self.assertTrue(all(len(sha) == 64 for _, sha in ARMS.values()))

    @staticmethod
    def document(count, upper_us, reported=None):
        import base64
        import struct
        import zlib
        payload = bytearray()
        for signed in (-upper_us, count):
            number = (signed << 1) ^ (signed >> 63)
            while number >= 128:
                payload.append((number & 127) | 128)
                number >>= 7
            payload.append(number)
        body = struct.pack(">IIiiQQd", 0x1c849303, len(payload), 0, 3, 1, 1000000, 1.0) + payload
        compressed = zlib.compress(body)
        encoded = base64.b64encode(struct.pack(">II", 0x1c849304, len(compressed)) + compressed).decode()
        count_field = count if reported is None else reported
        return {"ALL STATS": {
            "Runtime": {"Interrupted": "false", "Total duration": 3000, "Time unit": "MILLISECONDS"},
            "Sets": {"Count": count_field, "Percentile Latencies": {"p99.90": upper_us / 1000,
                      "Histogram log format": {"Compressed Histogram": encoded}}},
            "Totals": {"Count": count_field, "Ops/sec": 100, "Connection Errors": 0}}}

    def test_merged_hdr_and_exact_server_accounting(self):
        documents = [self.document(9900, 1000, reported=9901), self.document(100, 2000)]
        before, after = {"cmdstat_set": "calls=50"}, {"cmdstat_set": "calls=10050"}
        result = metrics(documents, before, after, 3)
        self.assertEqual(result["rate"], 200)
        self.assertEqual(result["p99"], 1)  # never the average of cohort p99s (1.5)
        with self.assertRaises(RuntimeError):
            metrics(documents, before, {"cmdstat_set": "calls=10051"}, 3)
        documents[0]["ALL STATS"]["Totals"]["Connection Errors"] = 1
        with self.assertRaises(ValueError):
            metrics(documents, before, after, 3)

    def test_truncated_and_mismatched_metrics_fail(self):
        docs = [self.document(100, 1000), self.document(100, 1000)]
        before, after = {"cmdstat_set": "calls=0"}, {"cmdstat_set": "calls=200"}
        with self.assertRaises(ValueError):
            metrics(docs, before, after, 30)
        docs[0]["ALL STATS"]["Sets"]["Count"] += 10000
        docs[0]["ALL STATS"]["Totals"]["Count"] += 10000
        with self.assertRaises(RuntimeError):
            metrics(docs, before, after, 3)

    def test_dry_run_never_starts_processes_or_sockets(self):
        from contextlib import redirect_stdout
        import io
        from unittest.mock import patch
        args = argument_parser().parse_args(["--output", "/nonexistent/lb-episodes"])
        output = io.StringIO()
        with patch.object(subprocess, "Popen", side_effect=AssertionError("spawned process")), \
                patch.object(socket, "socket", side_effect=AssertionError("opened socket")), \
                patch.object(Path, "mkdir", side_effect=AssertionError("created directory")), \
                redirect_stdout(output):
            dry_run(args)
        commands = [shlex.split(line) for line in output.getvalue().splitlines() if not line.startswith("#")]
        servers = [argv for argv in commands if "--thread-mode" in argv]
        self.assertEqual(len(servers), 46)  # two probes, two seeds, up to six calibrations, 36 scored
        self.assertTrue(all("probe" in argv[argv.index("--dir") + 1] for argv in servers[:2]))
        self.assertEqual({argv[argv.index("--thread-mode") + 1] for argv in servers}, {"1s", "2s"})
        for argv in servers:
            self.assertNotIn("--ratio", argv)
            self.assertEqual(argv[:3], ["taskset", "-c", "0-15"])
            self.assertNotIn("--shards", argv)
        self.assertIn("LB_EPISODE_OWNERS=<boot-io-owners>", output.getvalue())
        self.assertIn("LB_EPISODE_OWNERS=<first-two-boot-io-owners>", output.getvalue())
        self.assertIn("198.8 minutes", output.getvalue())

    def test_comparison_cannot_hide_one_bad_metric(self):
        results = [dict(arm=a, mode=m, episode=e, round=r, status="PASS", t_converge=4,
                        key_moves=2, client_moves=3, total_moves=5, suffix_moves=0, suffix_other_moves=0,
                        shard_moves=2, returns=0, exchanges=0, distinct_shards=2,
                        spread_end=100, rate=100, p99=1,
                        stall={k: 0 for k in STALL}, attempts=3, pass_limit=0)
                   for a, m, e, r in schedule()]
        self.assertEqual(assess(results)["status"], "PASS")
        results[2]["client_moves"] += 1
        results[2]["key_moves"] -= 1
        self.assertEqual(assess(results)["status"], "FAIL")

    def test_own_quiet_baseline_above_pre_maxima_passes(self):
        criterion = self.criterion()
        samples = [self.sample(i / 10, spread=1.2) for i in range(130)]
        baseline = baseline_stationarity(samples, criterion["shard_owners"])
        self.assertEqual(baseline["status"], "PASS")
        self.assertTrue(all(v == 1.2 for v in baseline["spread_maxima"].values()))
        diagnostic = diagnostic_envelope(criterion, baseline["spread_maxima"])
        self.assertEqual(diagnostic["upper"][SPREADS[0]], 1.2)
        self.assertEqual(criterion["upper"][SPREADS[0]], 1)
        self.assertIn(SPREADS[0] + "=1.2", baseline["summary"])
        self.assertNotIn("balanced maxima", baseline["reason"])

    def test_baseline_raw_samples_and_last_window(self):
        samples = [self.sample(i / 10) for i in range(130)]
        samples[112]["info"][SPREADS[2]] = 1.5  # not a closed-beat endpoint
        criterion = envelope(samples)
        self.assertEqual(criterion["upper"][SPREADS[2]], 1.5)
        self.assertTrue(all(inside(s, criterion) for s in samples))
        samples[112]["info"][STAGE] = 5
        result = baseline_stationarity(samples)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(STAGE + "=5, limit=0", result["reason"])
        samples[112]["info"][STAGE] = 0
        for s in samples[1:]:
            s["info"][KEY] = 1  # movement before the first closed beat still fails
        self.assertEqual(baseline_stationarity(samples)["status"], "FAIL")
        self.assertEqual(baseline_stationarity(self.trace()[:130], {"0": 1})["status"], "FAIL")

    def test_baseline_controller_specific_moves(self):
        for move_t in (1, 10):
            samples = [self.sample(i / 10, client=int(i / 10 >= move_t)) for i in range(130)]
            key = baseline_stationarity(samples, episode="key-skew")
            client = baseline_stationarity(samples, episode="client-skew")
            self.assertEqual(key["status"], "PASS")
            self.assertEqual(key["baseline_client_moves"], 1)
            self.assertEqual(client["status"], "PASS" if move_t == 1 else "FAIL")
            self.assertEqual(client["baseline_earlier_client_moves"], int(move_t == 1))
            self.assertEqual(client["decision_client_moves"], int(move_t == 10))
        # Include a counter change on the first in-window observation.
        samples = [self.sample(i / 10, client=int(i >= 90)) for i in range(130)]
        self.assertEqual(baseline_stationarity(samples, episode="client-skew")["status"], "FAIL")
        samples = [self.sample(i / 10, key=int(i >= 10)) for i in range(130)]
        for kind in ("key-skew", "client-skew"):
            result = baseline_stationarity(samples, episode=kind)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["baseline_key_moves"], 1)

    def test_client_spread_falling_with_late_moves_passes_but_flat_thrashes(self):
        for falling in (True, False):
            trace = [self.sample(i / 10, spread=100 if i <= 140 else
                                 (200 - max(0, i / 10 - 20) * 3 if falling else 200),
                                 client=max(0, (i - 170) // 30)) for i in range(401)]
            result = convergence(trace, 14, 40, self.criterion(), "client-skew", 20, 3)
            self.assertGreater(result["t_converge"], 20)
            self.assertEqual(result["spread_base"], 100)
            self.assertEqual(result["spread_peak"], 200)
            self.assertEqual(result["status"], "PASS" if falling else "FAIL")
            self.assertEqual(result["still_converging"], falling)
            if falling:
                self.assertIn("still converging", result["reason"])
                self.assertLess(result["spread_end"], result["spread_previous"])
                self.assertGreater(result["reduction"], .05)
            else:
                self.assertEqual(result["thrash_moves"], result["client_moves"])
                self.assertGreater(result["thrash_moves"], 0)
                self.assertEqual(result["reduction"], 0)

    def test_client_moves_after_spread_plateau_fail(self):
        trace = [self.sample(i / 10, spread=100 if i <= 140 else
                             200 - min(10, max(0, i / 10 - 20)) * 5,
                             client=max(0, (i - 170) // 30)) for i in range(501)]
        result = convergence(trace, 14, 50, self.criterion(), "client-skew", 40, 3)
        self.assertEqual(result["status"], "FAIL")
        self.assertGreater(result["reduction"], .05)
        self.assertGreater(result["thrash_moves"], 0)
        self.assertIn("spread stopped falling", result["reason"])

    def test_client_tail_trend_survives_endpoint_noise(self):
        trace = [self.sample(i / 10, spread=100 if i <= 140 else
                             200 - max(0, i / 10 - 20) * 3 + (12 if i >= 370 else 0),
                             client=max(0, (i - 170) // 30)) for i in range(401)]
        result = convergence(trace, 14, 40, self.criterion(), "client-skew", 20, 10)
        self.assertGreater(result["spread_end"], result["spread_previous"])
        self.assertLess(result["spread_tail_slope"], 0)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["still_converging"])
        trace[-1]["info"][SPREADS[2]] += 20
        result = convergence(trace, 14, 40, self.criterion(), "client-skew", 20, 10)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("post-move rebound", result["reason"])

    def test_spread_windows_and_zero_peak(self):
        trace = self.trace(moving=False, excursion=False)
        for s in trace:
            s["info"][SPREADS[0]] = 7 if s["t"] == 14 else 10 if 14 < s["t"] <= 20 else 2
            if s["t"] == 20.1:
                s["info"][SPREADS[0]] = 50  # outside the fixed peak window
            if 37 < s["t"] <= 40:
                s["info"][SPREADS[0]] = 5
        result = convergence(trace, 14, 40, self.criterion(), "key-skew", 20, 3)
        self.assertEqual([result['spread_' + k] for k in ('base', 'peak', 'end', 'min')], [7, 10, 5, 2])
        self.assertEqual(result["reduction"], .5)
        for s in trace:
            s["info"][SPREADS[0]] = 0
        result = convergence(trace, 14, 40, self.criterion(), "key-skew", 20, 3)
        self.assertIsNone(result["reduction"])
        json.dumps(result, allow_nan=False)

    def test_cumulative_thrash_survives_late_drop(self):
        trace = [self.sample(i / 10, spread=10 if i <= 140 else 200 if i < 440 else 80,
                             key=sum(i >= t for t in (180, 240, 270, 330, 420)), gathers=int(i >= 170))
                 for i in range(601)]
        result = convergence(trace, 14, 60, self.criterion(), "key-skew", 40, 3)
        self.assertEqual(result["milestone_moves"], 0)  # old definition erased all five moves
        self.assertEqual(result["thrash_moves"], 5)
        self.assertEqual(sum(w["required_moves"] for w in result["thrash_windows"]), result["key_moves"])
        early = convergence(trace, 14, 44, self.criterion(), "key-skew", 40, 3)
        self.assertEqual(early["thrash_moves"], result["thrash_moves"])
        for sample in trace:
            sample["info"][CLIENT], sample["info"][KEY] = sample["info"][KEY], 0
        client = convergence(trace, 14, 60, self.criterion(), "client-skew", 40, 3)
        self.assertEqual(client["thrash_moves"], 5)
        self.assertEqual(client["status"], "FAIL")
        self.assertIn("spread stopped falling", client["reason"])

    def test_thrash_uses_running_best_and_counts_windows_once(self):
        trace = [self.sample(i / 10, spread=100 if i <= 140 else
                             200 if i <= 200 else 190 if i <= 230 else 185,
                             key=int(i >= 220) + int(i >= 250), gathers=int(i >= 170))
                 for i in range(261)]
        result = convergence(trace, 14, 26, self.criterion(), "key-skew", 40, 3)
        self.assertEqual(result["thrash_moves"], 1)  # 200 -> 190 passes exactly 5%; 190 -> 185 does not
        self.assertEqual(sum(w["required_moves"] for w in result["thrash_windows"]), 2)
        trace.extend(self.sample(i / 10, spread=185, key=3, gathers=1) for i in range(261, 271))
        result = convergence(trace, 14, 27, self.criterion(), "key-skew", 40, 3)
        self.assertEqual(result["thrash_moves"], 2)  # partial final window is charged, once

    def test_owner_tracking_three_cycle_and_exchange(self):
        samples = [self.sample(i / 10) for i in range(5)]
        for sample, owner in zip(samples, (0, 1, 2, 0, 1)):
            sample["signals"]["shards"][0]["owner"] = owner
        result = owner_tracking(samples)
        self.assertEqual([result[k] for k in OWNER_METRICS], [4, 2, 0, 1])
        # Two shards in each direction count as one exchange of this owner pair.
        samples = [self.sample(i / 10) for i in range(3)]
        for sample, owners in zip(samples, ((0, 0, 1, 1), (1, 1, 0, 0), (0, 0, 1, 1))):
            sample["signals"]["shards"] = {str(i): {"owner": owner} for i, owner in enumerate(owners)}
        result = owner_tracking(samples)
        self.assertEqual([result[k] for k in OWNER_METRICS], [8, 4, 2, 4])
        samples[-1]["signals"]["shards"].pop("0")
        with self.assertRaisesRegex(ValueError, "shard map"):
            owner_tracking(samples)

    def test_owner_tracking_requires_same_sample_window_for_exchange(self):
        samples = [self.sample(i / 10) for i in range(3)]
        for sample, owners in zip(samples, ((0, 1), (1, 1), (1, 0))):
            sample["signals"]["shards"] = {i: {"owner": owner} for i, owner in enumerate(owners)}
        self.assertEqual(owner_tracking(samples)["exchanges"], 0)
        samples[-1]["t"] = 2
        with self.assertRaisesRegex(ValueError, "telemetry gap"):
            owner_tracking(samples)
        with self.assertRaisesRegex(ValueError, "missing telemetry"):
            owner_tracking([])

    def test_client_baseline_one_final_move_requires_full_idle_window(self):
        samples = [self.sample(i / 10, client=int(i >= 570)) for i in range(601)]
        result = baseline_stationarity(samples, episode="client-skew")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["baseline_decision_client_moves"], 1)
        self.assertEqual(result["baseline_earlier_client_moves"], 0)
        row = episode_row(dict(result, episode="client-skew", mode="2s", arm="POST", round=1))
        self.assertIn(" baseline_decision_client_moves=1 ", row)
        # An active plan outside the final 3s but inside the last nine ticks fails.
        samples[540]["info"][STAGE] = 1
        self.assertEqual(baseline_stationarity(samples, episode="client-skew")["status"], "FAIL")
        samples[540]["info"][STAGE] = 0
        samples[-1]["info"][CLIENT] = 2
        self.assertEqual(baseline_stationarity(samples, episode="client-skew")["status"], "FAIL")
        samples[-1]["info"][CLIENT] = 1
        samples[-1]["info"][KEY] = 1
        self.assertEqual(baseline_stationarity(samples, episode="client-skew")["status"], "FAIL")
        samples[-1]["info"][KEY] = 0
        self.assertEqual(baseline_stationarity(samples[100:], episode="client-skew")["status"], "FAIL")

    def test_optional_history_counters_absence_deltas_and_reset(self):
        samples = self.trace()
        self.assertEqual(history_deltas(samples)["refused"], None)
        for s in samples:
            for index, key in enumerate(HISTORY_COUNTERS):
                s["info"][key] = str(10 + index * int(s["t"]))  # old samplers saved optional fields as strings
        result = convergence(samples, 14, 40, self.criterion(), "key-skew", 20, 3)
        self.assertEqual(list(result["history_counters"].values()), [0, 26, 52, 78])
        self.assertEqual((result["refused"], result["escapes"]), (0, 78))
        row = episode_row(dict(result, episode="key-skew", mode="1s", arm="POST", round=1))
        self.assertTrue(row.endswith(" refused=0 escapes=78"))
        del samples[200]["info"][HISTORY_COUNTERS[1]]
        self.assertIsNone(history_deltas(samples)["history_counters"][HISTORY_COUNTERS[1]])
        samples[-1]["info"][HISTORY_COUNTERS[0]] = 0
        with self.assertRaisesRegex(ValueError, "counter reset"):
            history_deltas(samples)
        raw = b"tomokv_keylb_enabled:1\ntomokv_clientlb_enabled:1\n" + b"".join(
            f"{k}:1\n".encode() for k in (*FIELDS, *HISTORY_COUNTERS))
        self.assertEqual(parse_info(raw)[HISTORY_COUNTERS[0]], 1)
        with self.assertRaises(ValueError):
            parse_info(raw.replace((HISTORY_COUNTERS[0] + ":1").encode(), (HISTORY_COUNTERS[0] + ":-1").encode()))

    def test_balanced_cohort_placement_is_explicit_and_verified(self):
        import tempfile
        owners = [0, 1, 2, 3, 8, 9, 10, 11]
        plan = cohort_owners(list(reversed(owners)), "client-skew")
        self.assertEqual(plan["baseline-a"], owners * 8)
        self.assertEqual(plan["baseline-b"], plan["cold"])
        self.assertEqual(plan["hot"], [0, 1] * 32)
        with tempfile.TemporaryDirectory(prefix=".lb-episodes-", dir=ROOT / "tests") as temp:
            directory = Path(temp)
            args = argument_parser().parse_args(["--output", temp])
            for label, targets in plan.items():
                argv = load_command(args, directory, label, 1, KEYS, 93, owners=targets)
                self.assertIn("LB_EPISODE_OWNERS=" + ",".join(map(str, targets)), argv)
                self.assertIn("LD_PRELOAD=" + str(directory / "owner-select.so"), argv)
                path = directory / (label + ".owners.jsonl")
                path.write_text("".join(json.dumps({"index": i, "owner": owner}) + "\n"
                                        for i, owner in reversed(list(enumerate(targets)))))
            self.assertEqual(set(owner_evidence(directory, plan, list(plan.values()))), set(plan))
            path.write_text(path.read_text().replace('"owner": 0', '"owner": 8', 1))
            with self.assertRaisesRegex(ValueError, "requested owners"):
                owner_evidence(directory, plan, list(plan.values()))

    def test_owner_comparison_requires_both_controls_and_every_metric(self):
        results = [dict(arm=a, mode=m, episode=e, round=r, status="PASS", t_converge=4,
                        key_moves=2, client_moves=3, suffix_moves=0, suffix_other_moves=0,
                        shard_moves=2, returns=1, exchanges=1, distinct_shards=2,
                        spread_end=100, rate=100, p99=1, stall={k: 0 for k in STALL},
                        attempts=3, pass_limit=0) for a, m, e, r in schedule()]
        self.assertEqual(assess(results)["status"], "PASS")
        for control in (results[0], results[1], results[18], results[19]):
            for metric in OWNER_METRICS:
                with self.subTest(control=control["arm"], metric=metric):
                    control[metric] -= 1
                    report = assess(results)
                    self.assertEqual(report["status"], "FAIL")
                    check = next(c for c in report["checks"] if all(c[k] == control[k]
                                 for k in ("episode", "mode", "round")))
                    self.assertTrue(any(metric in reason and control["arm"] in reason
                                        for reason in check["reasons"]))
                    control[metric] += 1
        del results[0]["returns"]
        self.assertEqual(assess(results)["status"], "FAIL")

    def replay_fixture(self, directory):
        config = {"episodes": "key-skew", "warm": 0, "baseline": 12, "max_converge": 20, "suffix": 3}
        criterion = self.criterion()
        save_json(directory / "manifest.json", {"config": config})
        save_json(directory / "criteria.json", {m: criterion for m in ("1s", "2s")})
        samples = self.trace(end=42)
        for s in samples:
            s["signals"]["shards"][0]["owner"] = int(18 <= s["t"] < 41)
        saved = {"status": "FAIL", "reason": "old scoring", "measurement_valid": True,
                 "baseline": {"start": 0, "end": 13}, "stimulus_t": 14,
                 "criterion": criterion, "thrash_moves": 999, "shards": 1,
                 "rate": 200, "p99": 1, "coord_busy": 80,
                 "loaders": [{"rate": 100, "p99": 1}] * 2,
                 "accounting": {"commands": {"SET": {"server_calls": 200, "completed_hdr_count": 200,
                                                       "memtier_count": 200}}}}
        telemetry = "".join(json.dumps(s) + "\n" for s in samples)
        for arm, mode, episode, number in schedule("key-skew"):
            name = f"{episode}-{mode}-{arm}-r{number}"
            run = directory / name
            run.mkdir()
            save_json(run / "run.json", dict(saved, name=name, arm=arm, mode=mode, episode=episode, round=number))
            (run / "telemetry.jsonl").write_text(telemetry)
        return config, criterion

    def test_replay_is_read_only_and_needs_no_live_tools(self):
        from contextlib import redirect_stdout
        import io
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(prefix=".lb-episodes-", dir=ROOT / "tests") as temp:
            directory = Path(temp)
            self.replay_fixture(directory)
            before = {str(p): (digest(p), p.stat().st_mtime_ns) for p in directory.rglob("*") if p.is_file()}
            output = io.StringIO()
            with patch.object(subprocess, "Popen", side_effect=AssertionError("spawned process")), \
                    patch.object(subprocess, "run", side_effect=AssertionError("ran process")), \
                    patch.object(socket, "socket", side_effect=AssertionError("opened socket")), \
                    patch.object(Path, "write_text", side_effect=AssertionError("wrote file")), \
                    patch.object(Path, "write_bytes", side_effect=AssertionError("wrote file")), \
                    patch.object(Path, "mkdir", side_effect=AssertionError("created directory")), \
                    patch(__name__ + ".bind_arms", side_effect=AssertionError("bound live arms")), \
                    patch(__name__ + ".save_json", side_effect=AssertionError("saved output")), \
                    patch.object(os, "sched_setaffinity", side_effect=AssertionError("changed affinity")), \
                    redirect_stdout(output):
                code = main(["--replay", str(directory), "--arms", "/missing/arms.json", "--output", "/unused"])
            self.assertEqual(code, 0)
            self.assertEqual(before, {str(p): (digest(p), p.stat().st_mtime_ns)
                                      for p in directory.rglob("*") if p.is_file()})
            rows = [r for r in output.getvalue().splitlines() if r.startswith("LBPLANNER-EPISODE ")]
            self.assertEqual(len(rows), 18)
            self.assertTrue(all("thrash_moves=0 " in r and " moves=2 returns=1 exchanges=0 shards=1" in r for r in rows))
            self.assertTrue(all(" refused=NA escapes=NA" in r for r in rows))

    def test_replay_missing_telemetry_clears_old_scores_and_reports_missing_runs(self):
        from contextlib import redirect_stdout
        import io
        import tempfile
        with tempfile.TemporaryDirectory(prefix=".lb-episodes-", dir=ROOT / "tests") as temp:
            directory = Path(temp)
            config, criterion = self.replay_fixture(directory)
            run = directory / "key-skew-1s-POST-r1"
            (run / "telemetry.jsonl").unlink()
            result = replay_episode(run / "run.json", config, {"1s": criterion})
            self.assertEqual(result["status"], "NA")
            self.assertFalse(result["measurement_valid"])
            self.assertNotIn("thrash_moves", result)
            self.assertIn("thrash_moves=NA", episode_row(result))
            output = io.StringIO()
            with redirect_stdout(output):
                report = replay(run)  # a single episode also works, without inventing its missing pairs
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("missing telemetry.jsonl", output.getvalue())
            self.assertIn("key-skew-1s-PRE-r1/run.json", output.getvalue())

    def test_replay_uses_saved_frozen_criterion_and_valid_accounting(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix=".lb-episodes-", dir=ROOT / "tests") as temp:
            directory = Path(temp)
            config, criterion = self.replay_fixture(directory)
            path = directory / "key-skew-1s-POST-r1" / "run.json"
            saved = json.loads(path.read_text())
            saved["measurement_valid"] = False
            save_json(path, saved)
            result = replay_episode(path, config, {})
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["reason"], "saved workload measurement lacks valid accounting/telemetry evidence")
            self.assertEqual(result["diagnostics"], [{"source": "replay", "message":
                "last required move followed by a complete quiescent suffix"}])
            saved["measurement_valid"] = True
            save_json(path, saved)
            samples = [json.loads(s) for s in path.with_name("telemetry.jsonl").read_text().splitlines()]
            samples[390]["info"][SPREADS[0]] = 5
            path.with_name("telemetry.jsonl").write_text("".join(json.dumps(s) + "\n" for s in samples))
            wide = dict(criterion, upper={k: 1000 for k in SPREADS})
            result = replay_episode(path, config, {"1s": wide})
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("post-move rebound", result["reason"])
            self.assertEqual(result["criterion"]["upper"][SPREADS[0]], 1)
            result = replay_episode(path, {}, {})
            self.assertEqual(result["status"], "NA")
            self.assertIn("missing saved configuration", result["reason"])
            self.assertEqual(result["shard_moves"], 2)  # owner evidence survives missing scoring metadata
            saved["measurement_valid"] = False
            save_json(path, saved)
            result = replay_episode(path, config, {})
            self.assertEqual(result["reason"], "saved workload measurement lacks valid accounting/telemetry evidence")
            self.assertIn("post-move rebound", result["diagnostics"][0]["message"])

    def test_replay_newly_admissible_baseline_cannot_invent_stimulus(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix=".lb-episodes-", dir=ROOT / "tests") as temp:
            directory = Path(temp)
            path = directory / "run.json"
            samples = [self.sample(i / 10, client=int(i >= 570)) for i in range(601)]
            save_json(path, {"episode": "client-skew", "mode": "2s", "arm": "POST", "round": 1,
                             "status": "FAIL", "baseline": {"start": 0}, "criterion": self.criterion()})
            path.with_name("telemetry.jsonl").write_text("".join(json.dumps(s) + "\n" for s in samples))
            result = replay_episode(path, {"episodes": "client-skew", "warm": 0, "baseline": 60}, {})
            self.assertEqual(result["status"], "NA")
            self.assertEqual(result["baseline_stationarity"]["status"], "PASS")
            self.assertEqual(result["baseline_decision_client_moves"], 1)
            self.assertIn("no saved stimulus", result["reason"])
            self.assertNotIn("t_converge", result)
            self.assertFalse(result["measurement_valid"])
            for sample in samples[500:]:
                sample["info"][KEY] = 1
            path.with_name("telemetry.jsonl").write_text("".join(json.dumps(s) + "\n" for s in samples))
            result = replay_episode(path, {"episodes": "client-skew", "warm": 0, "baseline": 60}, {})
            self.assertEqual(result["reason"], "balanced key_moves=1, limit=0 (placement changed)")
            self.assertEqual(result["diagnostics"], [{"source": "replay", "message": "no saved stimulus; baseline=FAIL"}])

    def test_paired_client_spread_uses_pre_round_range_not_move_count(self):
        results = [dict(arm=a, mode=m, episode=e, round=r, status="PASS", t_converge=4,
                        key_moves=0, client_moves=3, total_moves=3, suffix_moves=0, suffix_other_moves=0,
                        shard_moves=0, returns=0, exchanges=0, distinct_shards=0,
                        spread_end=100 + r, rate=100, p99=1, stall={k: 0 for k in STALL},
                        attempts=30, pass_limit=0) for a, m, e, r in schedule("client-skew")]
        post = results[2]
        post.update(client_moves=20, total_moves=20, t_converge=210, spread_end=103)
        report = assess(results, "client-skew")
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["checks"][0]["spread_comparison"]["PRE_width"], 2)
        for control in results:
            if control["arm"] != "POST":
                control.update(status="FAIL", measurement_valid=True, reason="no spread improvement")
        self.assertEqual(assess(results, "client-skew")["status"], "PASS")
        results[0]["measurement_valid"] = False
        self.assertEqual(assess(results, "client-skew")["status"], "FAIL")
        results[0]["measurement_valid"] = True
        post["spread_end"] = 103.01
        self.assertEqual(assess(results, "client-skew")["status"], "FAIL")
        post["spread_end"] = 90
        post["p99"] = 1.01
        self.assertEqual(assess(results, "client-skew")["status"], "FAIL")

    def test_sampler_joins_before_teardown_and_preserves_primary_failure(self):
        from unittest.mock import Mock
        events = []
        result = {"status": "FAIL", "measurement_valid": False}
        sampler = Mock()
        def close():
            events.append("join")
            self.assertEqual(result["reason"], "balanced key_moves=1, limit=0")
            raise ValueError("sampler failed: Connection reset by peer")
        sampler.close.side_effect = close
        @contextmanager
        def server_lifetime():
            try:
                yield
            finally:
                events.append("teardown")
        with server_lifetime():
            with sampled_episode(sampler, result):
                raise ValueError("balanced key_moves=1, limit=0")
        self.assertEqual(events, ["join", "teardown"])
        self.assertEqual(result["reason"], "balanced key_moves=1, limit=0")
        self.assertIn("Connection reset", result["sampler_error"])
        self.assertEqual(result["diagnostics"], [{"source": "sampler", "message":
            "sampler failed: Connection reset by peer"}])
        sampler.close.assert_called_once()
        # A live sampling failure still invalidates an otherwise passing run.
        result = {"status": "PASS", "measurement_valid": True}
        sampler.close.side_effect = ValueError("sampler failed: live failure")
        with sampled_episode(sampler, result):
            pass
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["reason"], "sampler failed: live failure")
        self.assertFalse(result["measurement_valid"])
        # A workload/accounting error after a convergence rejection is also
        # secondary, even when closing the sampler fails independently.
        result = {"status": "FAIL", "reason": "convergence rejected", "measurement_valid": True}
        with sampled_episode(sampler, result):
            raise ValueError("accounting failed")
        self.assertEqual(result["reason"], "convergence rejected")
        self.assertEqual(result["diagnostics"], [
            {"source": "episode", "message": "accounting failed"},
            {"source": "sampler", "message": "sampler failed: live failure"}])
        self.assertFalse(result["measurement_valid"])

    def test_run_episode_missing_owners_preserves_primary_failure(self):
        from contextlib import redirect_stdout
        import io
        import tempfile
        from unittest.mock import Mock, patch
        cases = ((False, None, None), (False, "monitor failed", "teardown failed"),
                 (True, None, None), (True, "monitor failed", "teardown failed"))
        for baseline_pass, monitor_error, teardown_error in cases:
            with self.subTest(baseline_pass=baseline_pass, monitor_error=monitor_error), \
                    tempfile.TemporaryDirectory(prefix=".lb-episodes-", dir=ROOT / "tests") as temp:
                sampler = Mock(samples=[])
                if monitor_error:
                    sampler.close.side_effect = ValueError(monitor_error)
                @contextmanager
                def fake_boot(*args):
                    yield Mock(), Mock(), [0], {"shards": 1, "process_id": 123}
                    if teardown_error:
                        raise ValueError(teardown_error)
                baseline = {"status": "PASS" if baseline_pass else "FAIL",
                            "reason": "baseline stationary" if baseline_pass else
                                      "balanced total_moves=1, limit=0 (key=0, client=1)",
                            "summary": "balanced maxima (reported only): test summary"}
                args = argument_parser().parse_args(["--output", temp])
                with patch(__name__ + ".boot", side_effect=fake_boot), \
                        patch(__name__ + ".Sampler", return_value=sampler), \
                        patch(__name__ + ".key_mapping", return_value=[]), \
                        patch(__name__ + ".wait_loads", return_value=1), \
                        patch(__name__ + ".owner_evidence", return_value={}), \
                        patch(__name__ + ".baseline_stationarity", return_value=baseline), \
                        patch(__name__ + ".envelope", return_value={}), \
                        patch(__name__ + ".owner_tracking", wraps=owner_tracking) as tracking, \
                        patch.object(subprocess, "Popen", side_effect=AssertionError("started process")), \
                        patch.object(socket, "socket", side_effect=AssertionError("opened socket")), \
                        redirect_stdout(io.StringIO()):
                    result = run_episode(args, "PRE", "2s", "balanced", 1, None,
                                         {"sha256": "test", "shards": 1, "hot_keys": []})
                missing = "owner tracking: missing telemetry"
                primary = baseline["reason"] if not baseline_pass else monitor_error or missing
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(result["reason"], primary)
                self.assertFalse(result["measurement_valid"])
                diagnostics = []
                if monitor_error and not baseline_pass:
                    diagnostics.append({"source": "sampler", "message": monitor_error})
                if teardown_error:
                    diagnostics.append({"source": "teardown", "message": teardown_error})
                if baseline_pass:
                    tracking.assert_called_once_with([])
                    self.assertEqual(result["owner_tracking"], {"status": "FAIL", "reason": missing})
                    if monitor_error:
                        diagnostics.append({"source": "owner_tracking", "message": missing})
                else:
                    tracking.assert_not_called()
                    self.assertNotIn("owner_tracking", result)
                    self.assertNotIn("owner_tracking_error", result)
                diagnostics.append({"source": "baseline_stationarity", "message": baseline["summary"]})
                self.assertEqual(result["diagnostics"], diagnostics)
                saved = json.loads((args.output / result["name"] / "run.json").read_text())
                self.assertEqual(saved["reason"], primary)
                self.assertEqual(saved["diagnostics"], diagnostics)

    def test_run_episode_baseline_failure_stops_sampler_inside_boot(self):
        from contextlib import redirect_stdout
        import io
        import tempfile
        from unittest.mock import Mock, patch
        events = []
        sampler = Mock()
        sampler.samples = [self.sample(i / 10, key=int(i >= 500)) for i in range(932)]
        sampler.close.side_effect = lambda: events.append("join")
        @contextmanager
        def fake_boot(*args, **kwargs):
            try:
                yield Mock(), Mock(), [0], {"shards": 1, "process_id": 123}
            finally:
                events.append("teardown")
                self.assertEqual(events, ["join", "teardown"])
        with tempfile.TemporaryDirectory(prefix=".lb-episodes-", dir=ROOT / "tests") as temp:
            args = argument_parser().parse_args(["--output", temp])
            with patch(__name__ + ".boot", side_effect=fake_boot), \
                    patch(__name__ + ".Sampler", return_value=sampler), \
                    patch(__name__ + ".key_mapping", return_value=[]), \
                    patch(__name__ + ".wait_loads", return_value=93), \
                    patch(__name__ + ".owner_evidence", return_value={}), \
                    patch.object(time, "monotonic", return_value=0), \
                    patch.object(subprocess, "Popen", side_effect=AssertionError("started process")), \
                    patch.object(socket, "socket", side_effect=AssertionError("opened socket")), \
                    redirect_stdout(io.StringIO()):
                result = run_episode(args, "PRE", "1s", "key-skew", 1, None,
                                     {"sha256": "test", "shards": 1, "hot_keys": []}, self.criterion())
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["reason"], "balanced key_moves=1, limit=0 (placement changed)")
            self.assertNotIn("owner_tracking", result)
            self.assertEqual(result["diagnostics"], [{"source": "baseline_stationarity", "message":
                result["baseline_stationarity"]["summary"]}])
            self.assertFalse(result["measurement_valid"])
            self.assertEqual(events, ["join", "teardown"])
            saved = json.loads((args.output / result["name"] / "run.json").read_text())
            self.assertEqual(saved["cohort_owners"]["baseline-a"], [0] * 64)
            self.assertEqual(saved["cohort_owners"]["baseline-b"], [0] * 64)
            self.assertTrue(all("LB_EPISODE_OWNERS=" + ",".join(["0"] * 64) in argv
                                for argv in saved["commands"]))

    def test_last_required_move_and_three_real_ticks(self):
        trace = self.trace()
        for s in trace:
            if s["t"] >= 35:
                s["info"][KEY] += 1
        result = convergence(trace, 14, 40, self.criterion(), "key-skew", 30, 3)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["t_converge"], 21)
        self.assertEqual(convergence(trace, 14, 40, self.criterion(), "key-skew", 20, 3)["status"], "FAIL")
        self.assertEqual(convergence(trace, 14, 40, self.criterion(), "key-skew", 30, 6)["status"], "FAIL")
        for s in trace:
            if s["t"] >= 35:
                s["info"][TICKS] = 35  # many raw polls cannot supply three decision ticks
        result = convergence(trace, 14, 40, self.criterion(), "key-skew", 30, 3)
        self.assertIn("suffix_ticks=0, limit>=3", result["reason"])

    def test_missing_endpoint_or_first_post_move_plan_cannot_pass(self):
        with self.assertRaisesRegex(ValueError, "endpoint telemetry gap=10s, limit<=0.5s"):
            convergence(self.trace(), 14, 50, self.criterion(), "key-skew", 20, 3)
        trace = self.trace()
        for s in trace:
            if 19 <= s["t"] < 20:
                s["info"][STAGE] = 5
        result = convergence(trace, 14, 40, self.criterion(), "key-skew", 20, 3)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(STAGE + "=5, limit=0", result["reason"])

    def test_unarmed_probe_refuses_and_receipts_counters(self):
        result = convergence(self.trace(moving=False), 14, 40, self.criterion(), "key-skew", 20, 3)
        result.update(measurement_valid=True, probe=True, episode="key-skew", mode="1s", arm="PRE",
                      hotmax=2000, shards=128)
        result["status"], result["reason"] = probe_verdict(result)
        self.assertEqual(result["status"], "REFUSED")
        self.assertTrue(episode_row(result).startswith(
            "LBPLANNER-EPISODE key-skew 1s PRE probe UNARMED hotmax=2000 shard_count=128 "
            "hysteresis_refused=0 no_candidate=0 hot_bucket_refused=0"))
        result["measurement_valid"] = False
        self.assertEqual(probe_verdict(result)[0], "FAIL")
        result.update(measurement_valid=True, deltas={KEY: 1})
        self.assertEqual(probe_verdict(result)[0], "PASS")

    def test_damping_campaign_geometry_and_six_rounds(self):
        args = argument_parser().parse_args(["--episodes", "key-skew", "--rounds", "6",
                                            "--server-cores", "112-119", "--load-cores", "120-127"])
        self.assertEqual(len(list(schedule(args.episodes, args.rounds))), 36)
        self.assertEqual(server_command(args, "PRE", "1s", args.output)[2], "112-119")
        command = load_command(args, args.output, "hot", 1, 256, 20, owners=[0])
        self.assertEqual(command[command.index("taskset") + 2], "120-127")
        sample = self.topology_sample([(t, "fused") for t in range(8)], "1s")
        self.assertEqual(geometry(sample, "1s", threads=8), list(range(8)))
        with self.assertRaises(ValueError): geometry(sample, "1s", threads=16)
        self.assertEqual(cpu_set("112-115,118,119"), {112, 113, 114, 115, 118, 119})
        for bad in ("", "3-1", "-1", "1-2-3", "x"):
            with self.assertRaises(ValueError): cpu_set(bad)
        self.assertGreater(wall_seconds(args), wall_seconds(argument_parser().parse_args(["--episodes", "key-skew"])))

    def test_shards_schedule_depth_and_wall_time(self):
        args = argument_parser().parse_args(["--episodes", "key-skew", "--shards", "128", "--hot-pipeline", "4"])
        self.assertEqual(args.baseline, 60)
        self.assertEqual(len(list(schedule(args.episodes))), 18)
        self.assertEqual(wall_seconds(args), 6366)
        args.episodes = "client-skew"
        self.assertEqual(wall_seconds(args), 5748)
        self.assertEqual(server_command(args, "PRE", "1s", args.output)[-2:], ["--shards", "128"])
        for label in ("hot", "cold", "baseline-a", "baseline-b"):
            argv = load_command(args, args.output, label, 1, KEYS, 216)
            self.assertIn("--pipeline=" + ("4" if label == "hot" else "128"), argv)
        sample = self.topology_sample([(t, "fused") for t in range(16)], "1s", shards=128)
        self.assertEqual(geometry(sample, "1s"), list(range(16)))
        with self.assertRaisesRegex(ValueError, "shards=128, requested limit=16"):
            geometry(sample, "1s", 16)
        del sample["signals"]["shards"][30]
        with self.assertRaisesRegex(ValueError, "shard IDs"):
            geometry(sample, "1s")

    def test_actuator_deltas_and_max_are_not_confused(self):
        first, last = self.sample(0), self.sample(4, client=2)
        for i, field in enumerate(STALL.values()):
            first["info"][field], last["info"][field] = 10, 10 + i
        first["info"][PENDING], last["info"][PENDING] = 1000000, 2500000
        last["info"][CLIENT_PREFIX + "refused"] = 30
        mix = actuator_mix(first, last, delta(first, last))
        self.assertEqual(mix["pending_ms"], 2.5)
        self.assertEqual(mix["pending_ms_before"], 1)
        self.assertEqual(mix["attempts"], 32)
        self.assertEqual(mix["pass_limit"], 2)
        self.assertEqual(mix["stall"]["exec"], 0)

    def test_binomial_mix_and_exact_pass_limit(self):
        pre = {"arm": "PRE", "stall": {k: 0 for k in STALL}, "attempts": 71, "pass_limit": 0}
        post = {"arm": "POST", "stall": dict(pre["stall"]), "attempts": 71, "pass_limit": 0}
        pre["stall"].update(exec=39, proto=30)
        post["stall"].update(exec=38, proto=31)
        self.assertEqual(compare_actuators(post, pre, .0005)[0], [])
        post["stall"].update(exec=2, proto=56, passl=13)
        post["pass_limit"] = 13
        failures, _ = compare_actuators(post, pre, .0005)
        self.assertTrue(any("stall.exec" in s for s in failures))
        self.assertTrue(any("pass_limit=13, limit=0" in s for s in failures))
        post["stall"] = dict(pre["stall"], passl=1)
        post["pass_limit"] = 1
        self.assertTrue(any("pass_limit=1, limit=0" in s for s in compare_actuators(post, pre, .0005)[0]))
        self.assertAlmostEqual(binomial_mix_pvalue(1, 10, 11, 14), .0027594561852200836)
        self.assertEqual(binomial_mix_pvalue(0, 0, 0, 0), 1)
        self.assertIsNone(binomial_mix_pvalue(0, 0, 0, 2))
        with self.assertRaises(ValueError):
            binomial_mix_pvalue(3, 2, 0, 2)

    def test_hot_pipeline_accounting_uses_its_own_bound(self):
        docs = [self.document(10000, 1000), self.document(10000, 1000, reported=10000 + 257)]
        before, after = {"cmdstat_set": "calls=0"}, {"cmdstat_set": "calls=20000"}
        with self.assertRaises(RuntimeError):
            metrics(docs, before, after, 3, hot_pipeline=4)
        docs[1] = self.document(10000, 1000, reported=10000 + 256)
        result = metrics(docs, before, after, 3, hot_pipeline=4)
        self.assertEqual(result["accounting"]["count_outstanding_bound"], 64 * (128 + 4))

    def test_128_shard_topology_from_saved_server_log(self):
        # Exact startup excerpt from cx-lbplanner/build/c4kw-build_tomokv/
        # s4kg/n8-2-B/server.log. Its 32-thread topology is NOT an episode
        # geometry; its 128-shard map must nevertheless parse without a cap.
        saved = """tomokv-cpp: 32 threads (16 io + 16 ex), 128 shard(s), thread-mode=2s, overlap=1, io_uring, alloc=jemalloc, reorder=0, read-local=0
  thread t0: role=ifid cpu=0 L3=0 shards=0
  thread t1: role=ifid cpu=1 L3=0 shards=0
  thread t2: role=ifid cpu=2 L3=0 shards=0
  thread t3: role=ifid cpu=3 L3=0 shards=0
  thread t4: role=ex cpu=4 L3=0 shards=8
  thread t5: role=ex cpu=5 L3=0 shards=8
  thread t6: role=ex cpu=6 L3=0 shards=8
  thread t7: role=ex cpu=7 L3=0 shards=8
  thread t8: role=ifid cpu=8 L3=1 shards=0
  thread t9: role=ifid cpu=9 L3=1 shards=0
  thread t10: role=ifid cpu=10 L3=1 shards=0
  thread t11: role=ifid cpu=11 L3=1 shards=0
  thread t12: role=ex cpu=12 L3=1 shards=8
  thread t13: role=ex cpu=13 L3=1 shards=8
  thread t14: role=ex cpu=14 L3=1 shards=8
  thread t15: role=ex cpu=15 L3=1 shards=8
  thread t16: role=ifid cpu=16 L3=2 shards=0
  thread t17: role=ifid cpu=17 L3=2 shards=0
  thread t18: role=ifid cpu=18 L3=2 shards=0
  thread t19: role=ifid cpu=19 L3=2 shards=0
  thread t20: role=ex cpu=20 L3=2 shards=8
  thread t21: role=ex cpu=21 L3=2 shards=8
  thread t22: role=ex cpu=22 L3=2 shards=8
  thread t23: role=ex cpu=23 L3=2 shards=8
  thread t24: role=ifid cpu=24 L3=3 shards=0
  thread t25: role=ifid cpu=25 L3=3 shards=0
  thread t26: role=ifid cpu=26 L3=3 shards=0
  thread t27: role=ifid cpu=27 L3=3 shards=0
  thread t28: role=ex cpu=28 L3=3 shards=8
  thread t29: role=ex cpu=29 L3=3 shards=8
  thread t30: role=ex cpu=30 L3=3 shards=8
  thread t31: role=ex cpu=31 L3=3 shards=8"""
        header, *lines = saved.splitlines()
        count = int(header.partition(" shard(s)")[0].rsplit(",", 1)[1])
        roles = [(int(v[1][1:-1]), "io" if v[2] == "role=ifid" else "ex")
                 for v in map(str.split, lines)]
        sample = self.topology_sample(roles, shards=count)
        self.assertEqual(len(sample["signals"]["shards"]), 128)
        self.assertEqual(set(sample["signals"]["shards"]), set(range(128)))
        owners = Counter(row["owner"] for row in sample["signals"]["shards"].values())
        self.assertTrue(all(owners[int(v[1][1:-1])] == int(v[5].partition("=")[2])
                            for v in map(str.split, lines)))
        with self.assertRaisesRegex(ValueError, "observed Counter"):
            geometry(sample, "2s")

    def test_explicit_arms_receipt_binds_paths_hashes_and_itself(self):
        import tempfile
        frozen, identity = bind_arms(None)
        self.assertEqual(frozen, ARMS)
        self.assertIsNone(identity["path"])
        with tempfile.TemporaryDirectory(prefix=".lb-episodes-", dir=ROOT / "tests") as temp:
            directory = Path(temp)
            entries = {}
            for arm in ARMS:
                binary = directory / arm
                binary.write_text(arm)
                binary.chmod(0o700)
                entries[arm] = {"path": arm, "sha256": digest(binary)}
            receipt = directory / "arms.json"
            save_json(receipt, entries)
            args = argument_parser().parse_args([])
            args.arm_table, args.arms_receipt = bind_arms(receipt)
            self.assertEqual(args.arms_receipt, {"path": str(receipt), "sha256": digest(receipt), "source": "--arms"})
            verify_arms(args)
            self.assertEqual(server_command(args, "POST", "1s", directory)[3], str(directory / "POST"))
            (directory / "POST").write_text("changed")
            with self.assertRaisesRegex(ValueError, "POST binary differs from explicit arms receipt"):
                verify_arms(args)
            (directory / "POST").write_text("POST")
            receipt.write_text(receipt.read_text() + "\n")
            with self.assertRaisesRegex(ValueError, "arms receipt changed"):
                verify_arms(args)
            for broken in ({"PRE": entries["PRE"]}, dict(entries, POST={"path": "POST", "sha256": "bad"})):
                save_json(receipt, broken)
                with self.assertRaises(ValueError):
                    bind_arms(receipt)
            receipt.write_text('{"PRE": {}, "PRE": {}}')
            with self.assertRaisesRegex(ValueError, "duplicate"):
                bind_arms(receipt)
        self.assertEqual(frozen, ARMS)  # replacement never mutates the frozen table

    def test_filtered_dry_run_has_no_unrequested_matrix_or_probes(self):
        from contextlib import redirect_stdout
        import io
        for episode, expected_servers in (("key-skew", 28), ("client-skew", 26)):
            args = argument_parser().parse_args(["--episodes", episode, "--hot-pipeline", "4"])
            output = io.StringIO()
            with redirect_stdout(output):
                dry_run(args)
            commands = [shlex.split(s) for s in output.getvalue().splitlines() if not s.startswith("#")]
            servers = [a for a in commands if "--thread-mode" in a]
            self.assertEqual(len(servers), expected_servers)
            paths = [a[a.index("--dir") + 1] for a in servers]
            other = "client-skew" if episode == "key-skew" else "key-skew"
            self.assertTrue(all(other not in path for path in paths))
            self.assertEqual(sum(path.endswith("-probe") for path in paths), 2 if episode == "key-skew" else 0)

    def test_refused_probe_stops_matrix_with_exit_three(self):
        from contextlib import redirect_stdout
        import io
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(prefix=".lb-episodes-", dir=ROOT / "tests") as temp:
            output = Path(temp) / "campaign"
            def fake_compile(argv, **kwargs):
                (output / "owner-select.so").write_bytes(b"not a shared object")
            def seed(args, mode):
                return output / ("seed-" + mode), {"shards": 128 if mode == "1s" else 64}
            jobs = []
            def episode(args, arm, mode, kind, number, *rest, **kwargs):
                jobs.append((kind, kwargs.get("probe", False)))
                return {"status": "REFUSED", "reason": "UNARMED"} if kwargs.get("probe") else {
                    "status": "PASS", "criterion": {"shards": 128 if mode == "1s" else 64}}
            with patch(__name__ + ".verify_arms"), patch(__name__ + ".prepare_seed", side_effect=seed), \
                    patch(__name__ + ".run_episode", side_effect=episode), \
                    patch.object(shutil, "which", return_value=__file__), \
                    patch.object(os, "sched_getaffinity", return_value=set(range(112))), \
                    patch.object(os, "sched_setaffinity"), \
                    patch.object(subprocess, "run", side_effect=fake_compile), \
                    patch.object(subprocess, "Popen", side_effect=AssertionError("started process")), \
                    patch.object(socket, "socket", side_effect=AssertionError("opened socket")), \
                    redirect_stdout(io.StringIO()):
                code = main(["--episodes", "key-skew", "--output", str(output)])
            self.assertEqual(code, 3)
            self.assertEqual(jobs, [("balanced", False)] * 2 + [("key-skew", True)] * 2)
            self.assertEqual(json.loads((output / "results.json").read_text()), [])
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["identity"]["shards"], {"1s": 128, "2s": 64})
            self.assertEqual(json.loads((output / "report.json").read_text())["status"], "REFUSED")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print("LBPLANNER-ERROR " + str(error), file=sys.stderr)
        sys.exit(1)
