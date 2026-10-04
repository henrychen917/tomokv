#!/usr/bin/env python3
"""Mainline-only LB convergence episodes; --self-test and --dry-run start nothing.

PRE probes must admit key movement before a key-skew matrix can run. Key episodes
require a stationary key suffix; client episodes score spread improvement.
See MEASURE-REQUEST-lbplanner-bench4.md for the comparison and replay rules.
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
TICKS, STAGE = PREFIX + "ticks", PREFIX + "stage"
KEY, CLIENT, GATHERS = (PREFIX + n for n in ("bucket_moves", "client_moves", "bucket_gathers"))
SPREADS = tuple(PREFIX + n + "_spread_current" for n in
                ("bucket_weight", "bucket_bytes", "client_weight"))
REFUSALS = tuple(PREFIX + n for n in (
    "no_candidate", "hysteresis_refused", "cooldown_refused", "transition_refused",
    "capacity_refused", "client_refused", "hot_bucket_refused"))
STALL = {short: "tomokv_lbstall_" + name for short, name in (
    ("exec", "executor"), ("proto", "protocol"), ("passl", "pass_limit"),
    ("dest", "destination"), ("pipe", "pipeline"), ("defout", "deferred_output"),
    ("cstate", "client_state"), ("invalid", "invalid_client"))}
PENDING = "tomokv_lbstall_pending_ns_max"
COUNTERS = (TICKS, KEY, CLIENT, GATHERS, PREFIX + "bucket_cross_domain_moves",
            PREFIX + "client_cross_domain_moves", *REFUSALS, *STALL.values())
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
        for key in FIELDS:
            value = float(result[key]) if "spread" in key else int(result[key])
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


def geometry(sample, mode, requested_shards=None):
    snap = sample["signals"]
    roles = Counter(r["role"] for r in snap["threads"].values())
    require(snap["derived"]["thread_mode"] == mode,
            f"expected thread-mode={mode}, observed {snap['derived']['thread_mode']}; observed {roles!r}")
    valid = (roles == {"fused": 16} if mode == "1s" else
             len(snap["threads"]) == roles["io"] + roles["ex"] == 16 and roles["io"] >= 2)
    expected = "16 fused threads" if mode == "1s" else "16 IO + EX threads with at least 2 IO"
    require(valid, f"expected {expected} on cores 0-15; observed {roles!r}")
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
                      decision_client_moves=final_moves[CLIENT], decision_start_t=window[0]["t"])
        require(movements[KEY] == 0,
                f"balanced key_moves={movements[KEY]}, limit=0 (placement changed)")
        if episode == "client-skew":
            require(final_moves[CLIENT] == 0,
                    f"balanced final decision client_moves={final_moves[CLIENT]}, limit=0 "
                    f"(earlier={result['baseline_earlier_client_moves']})")
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
        reason = f"own {episode} baseline stationary; baseline_client_moves={movements[CLIENT]}"
    except ValueError as error:
        reason = str(error)
    return dict(result, reason=reason + "; " + summary)


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
            "attempts": total[PREFIX + "client_refused"] + total[CLIENT],
            # A high-water mark is not additive: subtracting two maxima would
            # mislabel a difference as a duration. Retain both endpoints.
            "pending_ms": final["info"][PENDING] / 1e6,
            "pending_ms_before": anchor["info"][PENDING] / 1e6,
            "pending_scope": "server lifetime high-water at post-stimulus endpoint"}


def spread_progress(before, after, rows, stimulus, primary, move):
    """Fixed windows and 5% record improvements, independent of the candidate arm."""
    def mean(window):
        require(bool(window), "missing spread window")
        return sum(s["info"][primary] for s in window) / len(window)
    final = after[-1]
    base = mean([s for s in before if s["t"] > stimulus - DECISION_SECONDS])
    peak = max(s["info"][primary] for s in after if s["t"] <= stimulus + 6)
    end = mean([s for s in after if s["t"] > final["t"] - DECISION_SECONDS])
    previous = mean([s for s in after if
                     final["t"] - 2 * DECISION_SECONDS < s["t"] <= final["t"] - DECISION_SECONDS])
    # Only start recording improvements after the fixed peak window. The
    # pre-step values in its first polls must not become a spurious low record.
    level, last_improvement = peak, None
    for row in [*rows, final]:
        if row["t"] < stimulus + 6:
            continue
        value = mean([s for s in after if row["t"] - DECISION_SECONDS < s["t"] <= row["t"]])
        if value < level and value <= .95 * level:
            level, last_improvement = value, row
    reduction = 1 - end / peak if peak else None
    improved = reduction is not None and reduction >= .05
    return {"spread_base": base, "spread_peak": peak, "spread_end": end,
            "spread_min": min(s["info"][primary] for s in after), "reduction": reduction,
            "spread_previous": previous, "spread_improved": improved,
            "still_converging": improved and end < previous and end <= level,
            "last_improvement_t": last_improvement["t"] if last_improvement else None,
            "last_improvement_level": level,
            "thrash_moves": final["info"][move] -
                (last_improvement or before[-1])["info"][move],
            "spread_method": "base/end: final 3s sample means; peak: first 6s max; min: all post-stimulus polls; "
                             "5% records: 3s means at closed ticks after peak window; falling: end < preceding 3s mean and <= last record"}


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
              **spread_progress(before, after, rows, stimulus, primary, move)}
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
            return dict(result, reason=f"no 5% spread improvement: reduction={result['reduction']}, "
                        f"limit>=0.05; thrash_moves={result['thrash_moves']}")
        if result["thrash_moves"] and not result["still_converging"]:
            return dict(result, reason=f"spread stopped falling: thrash_moves={result['thrash_moves']}, limit=0")
    if result["t_converge"] > max_seconds and not (episode == "client-skew" and result["still_converging"]):
        return dict(result, reason=f"t_converge={result['t_converge']:g}, limit<={max_seconds:g}")
    if episode == "client-skew" and result["still_converging"]:
        # Successful balancing need not leave a 30s quiet tail. Retain Idle
        # evidence over the final decision window while reporting the last move.
        for row in decision_window(after)[1:]:
            if row["info"][STAGE] != 0:
                return dict(result, reason=f"final decision {STAGE}={row['info'][STAGE]}, limit=0")
        return dict(result, status="PASS", reason="still converging: spread falling at the fixed endpoint")
    if result["suffix_ticks"] < DECISION_TICKS:
        return dict(result, reason=f"suffix_ticks={result['suffix_ticks']}, limit>={DECISION_TICKS}")
    # Current spreads are refreshed at controller ticks, not at move completion.
    # Use the first closed beat strictly after the last move's tick; never
    # hunt for a later favourable spread or skip an active plan to re-arm it.
    level = next((s for s in rows if s["info"][TICKS] > last_move["info"][TICKS]), None)
    if level is None:
        return dict(result, reason="post-move closed beats=0, limit>=1")
    result.update(suffix_start_t=level["t"], suffix_seconds=final["t"] - level["t"],
                  suffix_ticks=final["info"][TICKS] - level["info"][TICKS])
    if result["suffix_seconds"] < suffix_seconds or result["suffix_ticks"] < DECISION_TICKS:
        return dict(result, reason=f"suffix_seconds={result['suffix_seconds']:g}, limit>={suffix_seconds:g}; "
                    f"suffix_ticks={result['suffix_ticks']}, limit>={DECISION_TICKS}")
    width = criterion["upper"][primary] - criterion["lower"][primary]
    limit = level["info"][primary] + width
    result.update(post_last_move_level=level["info"][primary], post_last_move_level_t=level["t"],
                  primary=primary, rebound_limit=limit, pre_envelope_width=width)
    for row in after:
        if row["info"][TICKS] < level["info"][TICKS]:
            continue
        if row["info"][primary] > limit:
            return dict(result, reason=f"post-move rebound: {primary}={row['info'][primary]:g}, limit={limit:g} at t={row['t']:.6f}")
        if row["info"][STAGE] != 0:
            return dict(result, reason=f"stationary suffix {STAGE}={row['info'][STAGE]}, limit=0 at t={row['t']:.6f}")
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
        self.thread.join(timeout=5)
        require(not self.thread.is_alive(), "sampler did not stop")
        require(self.error is None, "sampler failed: " + str(self.error))


@contextmanager
def sampled_episode(sampler, result):
    """Classify the episode and join its observer inside the server lifetime."""
    try:
        sampler.thread.start()
        yield
    except Exception as error:
        result.update(status="FAIL", reason=str(error), measurement_valid=False)
    finally:
        try:
            sampler.close()
        except Exception as error:
            result["sampler_error"] = str(error)
            if result["status"] != "FAIL" or not result.get("reason"):
                result.update(status="FAIL", reason=str(error))
            result["measurement_valid"] = False


def server_command(args, arm, mode, directory):
    # Match calib/lb-stationary.sh: the default split uses all 16 allowed CPUs.
    # --ratio specifies whole-server counts, not a ratio scaled to CPU affinity.
    argv = ["taskset", "-c", SERVER_CORES, str(ROOT / arm_table(args)[arm][0]),
            "--bind", "127.0.0.1", "--port", str(args.port), "--thread-mode", mode,
            "--key-lb", "1", "--client-lb", "1", "--flip-auto", "0",
            "--enable-debug-command", "yes", "--save", "", "--appendonly", "no",
            "--dir", str(directory), "--dbfilename", "seed.tomo"]
    if args.shards is not None:
        argv += ["--shards", str(args.shards)]
    return argv


def load_command(args, directory, label, low, high, duration=None, populate=False, owners=None):
    argv = ["taskset", "-c", LOAD_CORES, args.memtier, "-s", "127.0.0.1", "-p", str(args.port),
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
        owners = geometry(sample, mode, args.shards)
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
        row += f"hotmax={fmt(result.get('hotmax'))} shards={fmt(result.get('shards'))} "
        row += " ".join(f"{k}={fmt(result.get('deltas', {}).get(PREFIX + k))}" for k in
                        ("hysteresis_refused", "no_candidate", "hot_bucket_refused"))
    else:
        row = f"LBPLANNER-EPISODE {episode} {mode} {arm} r{result['round']} "
        row += " ".join(f"{k}={fmt(result.get(k))}" for k in (
            "t_converge", "key_moves", "client_moves", "gathers", "suffix_moves", "rate", "p99",
            "coord_busy", "shards", "hotmax", "envelope_return_t"))
    stall = result.get("stall") or {}
    row += " stall=" + ",".join(f"{k}:{fmt(stall.get(k))}" for k in STALL if k != "invalid")
    row += f" pending_ms={fmt(result.get('pending_ms'))} attempts={fmt(result.get('attempts'))}"
    row += f" baseline_client_moves={fmt(result.get('baseline_client_moves'))}"
    row += f" suffix_other={fmt(result.get('suffix_other_moves'))}"
    row += " spread=" + ",".join(f"{k}:{fmt(result.get('spread_' + k))}" for k in ("base", "peak", "end", "min"))
    reduction = result.get("reduction")
    row += f" reduction={fmt(100 * reduction) + '%' if reduction is not None else 'NA'}"
    row += f" thrash_moves={fmt(result.get('thrash_moves'))}"
    if result.get("still_converging"):
        row += " (still converging)"
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
              "status": "FAIL", "sampling_interval": INTERVAL, "commands": []}
    sampler = None
    try:
        with boot(args, arm, mode, directory, seed) as (conn, children, owners, identity):
            result["identity"] = identity
            result["shards"] = identity["shards"]
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
                                        args.warm + args.baseline + 3, owners=owners)
                    result["commands"].append(argv)
                    processes.append(children.start(argv, directory / (label + ".log"), directory))
                baseline_end = wait_loads(processes, sampler, args.warm + args.baseline + 63)
                result["baseline"] = {"start": baseline_start, "end": baseline_end,
                                      "owners": owner_evidence(directory, ("baseline-a", "baseline-b"), [owners, owners])}
                # Trim both connection setup and generator teardown. The last three seconds are
                # guard time, not calibration evidence. No candidate run refits PRE limits.
                balanced = [s for s in sampler.samples if
                            baseline_start + args.warm <= s["t"] <= baseline_start + args.warm + args.baseline]
                baseline_kind = ("client-skew" if args.episodes == "client-skew" else "key-skew") if calibration else episode
                own_baseline = baseline_stationarity(balanced, None if calibration else criterion["shard_owners"], baseline_kind)
                result["baseline_stationarity"] = own_baseline
                for field in ("baseline_client_moves", "baseline_key_moves", "baseline_earlier_client_moves"):
                    result[field] = own_baseline.get(field)
                require(own_baseline["status"] == "PASS", own_baseline["reason"])
                if calibration:
                    result["criterion"] = envelope(balanced, baseline_kind)
                    result["status"] = "PASS"
                else:
                    result["baseline_in_envelope_fraction"] = sum(inside(s, criterion) for s in balanced) / len(balanced)
                    diagnostic = diagnostic_envelope(criterion, own_baseline["spread_maxima"])
                    result["diagnostic_envelope"] = diagnostic
                    command_before = parse_info(conn.must("INFO", "COMMANDSTATS"), False)
                    stimulus = time.monotonic()
                    result["stimulus_t"] = stimulus
                    result["baseline_to_stimulus_gap"] = stimulus - baseline_end
                    processes = []
                    post_owners = [owners, owners[:2] if episode == "client-skew" else owners]
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
            result["measurement_valid"] = False
        else:
            result.update(status="FAIL", reason=str(error), measurement_valid=False)
    finally:
        if probe:
            result["convergence_status"] = result["status"]
            result["convergence_reason"] = result.get("reason")
            result["status"], result["reason"] = probe_verdict(result)
        summary = result.get("baseline_stationarity", {}).get("summary", "")
        if summary and summary not in result.get("reason", ""):
            result["reason"] = result.get("reason", "complete") + "; " + summary
        directory.mkdir(parents=True, exist_ok=True)
        save_json(directory / "run.json", result)
    if not calibration:
        row = episode_row(result)
        print(row, flush=True)
        print(f"{name}: {result['status']} {result.get('reason', '')}", flush=True)
        with (args.output / "rows.txt").open("a") as stream:
            stream.write(row + "\n")
    return result


def schedule(episodes="both"):
    for episode in (("key-skew", "client-skew") if episodes == "both" else (episodes,)):
        for mode in ("1s", "2s"):
            for number in range(1, 4):
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


def assess(results, episodes="both"):
    checks = []
    expected = list(schedule(episodes))
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
        reasons, mix, spread_comparison = [], {}, None
        if set(paired) != set(ARMS) or any(r["status"] != "PASS" for r in paired.values()):
            reasons.append("PRE, PAD-A or POST episode missing or did not establish its kind's convergence")
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
        checks.append({"episode": post["episode"], "mode": post["mode"], "round": post["round"],
                       "status": "FAIL" if reasons else "PASS", "reasons": reasons, "actuator_mix": mix,
                       "spread_comparison": spread_comparison})
    return {"status": "PASS" if complete and all(c["status"] == "PASS" for c in checks)
            and all(r["status"] == "PASS" for r in results) else "FAIL", "checks": checks,
            "schedule_complete": complete,
            "rule": "key-skew: POST's last required move is no slower than PRE, with no more required moves, other-kind moves or suffix_other moves; "
                    "client-skew: POST spread_end <= paired PRE spread_end + the range of valid PRE spread_end rounds in the same mode; "
                    "completed moves, thrash_moves and t_converge are reported, continued spread improvement is balancing; "
                    "both: no aggregate/cohort rate or p99 loss, PRE/PAD-A actuator mix within binomial counting noise, PassLimit == PRE exactly; every paired round must pass",
            "actuator_noise": {"method": "two-sided exact conditional binomial (Fisher), Bonferroni over scheduled comparisons",
                               "family_alpha": .05, "comparison_alpha": alpha},
            "pad_kind": "A: PRE behaviour with candidate text size/layout; diagnostic control, no placement claim without mainline null",
            "rate_tail_tolerance": "none; no arm-dependent or invented noise allowance"}


def dry_run(args):
    def command(argv):
        print(shlex.join(argv))
    print("# DRY RUN: no processes, sockets or output files are created")
    for arm, (path, sha) in arm_table(args).items():
        print(f"# SHA256 REQUIRED {arm} {sha} {ROOT / path}")
    print("# ARMS RECEIPT " + json.dumps(arms_receipt(args), sort_keys=True))
    jobs = list(schedule(args.episodes))
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
        print("# Owner placeholders expand to comma-separated sorted DEBUG LBSIGNALS IO/fused IDs; EX IDs are excluded")
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
    jobs = list(schedule(args.episodes))
    modes = len({mode for _, mode, _, _ in jobs})
    probes = modes if args.episodes in ("key-skew", "both") else 0
    observations = len(jobs) + probes
    return ((modes + observations) * (args.warm + args.baseline + 3) +
            observations * (args.max_converge + DECISION_SECONDS + args.suffix + 3))


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--self-test", action="store_true")
    action.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "build/lbplanner-episodes")
    parser.add_argument("--memtier", default="memtier_benchmark")
    parser.add_argument("--port", type=int, default=7931)
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
    args.output = args.output.resolve()
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
    require(set(range(0, 16)) | set(range(64, 96)) <= os.sched_getaffinity(0), "required server/load CPUs unavailable")
    os.sched_setaffinity(0, range(64, 96))
    args.output.mkdir(parents=True)
    (args.output / "owner-select.c").write_text(SELECTOR_C)
    compile_argv = ["cc", "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror", "-o",
                    str(args.output / "owner-select.so"), str(args.output / "owner-select.c"), "-ldl"]
    with (args.output / "owner-select-build.log").open("wb") as log:
        subprocess.run(compile_argv, check=True, stdout=log, stderr=subprocess.STDOUT)
    jobs = list(schedule(args.episodes))
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
    report = assess(results, args.episodes)
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
        self.assertIn(SPREADS[0] + "=1.2", baseline["reason"])

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

    def test_paired_client_spread_uses_pre_round_range_not_move_count(self):
        results = [dict(arm=a, mode=m, episode=e, round=r, status="PASS", t_converge=4,
                        key_moves=0, client_moves=3, total_moves=3, suffix_moves=0, suffix_other_moves=0,
                        spread_end=100 + r, rate=100, p99=1, stall={k: 0 for k in STALL},
                        attempts=30, pass_limit=0) for a, m, e, r in schedule("client-skew")]
        post = results[2]
        post.update(client_moves=20, total_moves=20, t_converge=210, spread_end=103)
        report = assess(results, "client-skew")
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["checks"][0]["spread_comparison"]["PRE_width"], 2)
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
        sampler.close.assert_called_once()
        # A live sampling failure still invalidates an otherwise passing run.
        result = {"status": "PASS", "measurement_valid": True}
        sampler.close.side_effect = ValueError("sampler failed: live failure")
        with sampled_episode(sampler, result):
            pass
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["reason"], "sampler failed: live failure")
        self.assertFalse(result["measurement_valid"])

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
            "LBPLANNER-EPISODE key-skew 1s PRE probe UNARMED hotmax=2000 shards=128 "
            "hysteresis_refused=0 no_candidate=0 hot_bucket_refused=0"))
        result["measurement_valid"] = False
        self.assertEqual(probe_verdict(result)[0], "FAIL")
        result.update(measurement_valid=True, deltas={KEY: 1})
        self.assertEqual(probe_verdict(result)[0], "PASS")

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
        last["info"][PREFIX + "client_refused"] = 30
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
