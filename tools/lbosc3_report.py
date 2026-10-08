#!/usr/bin/env python3
"""Read-only pooled lbosc3 judge. Scores telemetry, never the harness PASS flag."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics
import tempfile
import unittest

import lb_episodes as episodes

ARMS = ("PRE", "PAD-A", "POST")
MODES = ("1s", "2s")


def mean(xs):
    return statistics.mean(xs)


def quantities(path, config):
    row = json.loads(path.read_text())
    if row.get("episode") != "key-skew" or row.get("probe"):
        return None
    episodes.require(row.get("measurement_valid"), "invalid measurement/accounting")
    samples = [json.loads(line) for line in path.with_name("telemetry.jsonl").read_text().splitlines() if line]
    tracked = episodes.owner_tracking(samples)
    # Compare observed owner changes to the independent completed-move counter.
    # A poll that misses a cycle cannot contribute a zero to the pooled verdict.
    counter_moves = samples[-1]["info"][episodes.KEY] - samples[0]["info"][episodes.KEY]
    episodes.require(tracked["shard_moves"] == counter_moves, "owner tracking missed a completed move")
    stimulus = row["stimulus_t"]
    end = stimulus + config["max_converge"] + episodes.DECISION_SECONDS + config["suffix"]
    before = [s for s in samples if s["t"] <= end - episodes.DECISION_SECONDS]
    tail = [s for s in samples if end - episodes.DECISION_SECONDS < s["t"] <= end]
    episodes.require(before and tail and end - tail[-1]["t"] <= .5, "missing fixed endpoint window")
    first, last = before[-1], tail[-1]
    # The cheap planner signal is visits per tick, averaged over three ticks.
    # Derive a conservative absolute band from real visits in that same interval.
    owners = {str(s["owner"]) for s in last["signals"]["shards"].values()}
    total = 0
    for sid, shard in last["signals"]["shards"].items():
        old = first["signals"]["shards"].get(sid)
        episodes.require(old is not None and shard["ops"] >= old["ops"], "missing/reset shard visits")
        total += shard["ops"] - old["ops"]
    mean_owner = total / (last["t"] - first["t"]) / len(owners)
    episodes.require(mean_owner > 0, "unarmed endpoint visits")
    band_pct = episodes.sampling_floor(len(owners))
    last_move = None
    for old, sample in zip(samples, samples[1:]):
        if stimulus <= sample["t"] <= end and episodes.shard_owners(old) != episodes.shard_owners(sample):
            last_move = sample["t"] - stimulus
    rate, p99 = row["rate"], row["p99"]
    episodes.require(all(math.isfinite(v) and v > 0 for v in (rate, p99)), "missing rate/p99")
    return dict(arm=row["arm"], mode=row["mode"], round=row["round"], path=str(path),
                moves=tracked["shard_moves"], returns=tracked["returns"], exchanges=tracked["exchanges"],
                last_move_s=last_move or 0.0,
                end_spread=mean(float(s["info"][episodes.SPREADS[0]]) for s in tail),
                band_floor=mean_owner * band_pct / 100, band_floor_pct=band_pct,
                measured_band_pct=mean(float(s["info"].get(episodes.PREFIX + "damping_band_pct", 0)) for s in tail),
                rate=rate, p99=p99)


def judge(rows, invalid=()):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["mode"], row["arm"])].append(row)
    summary, failures, pending, accuracy = {}, [], list(invalid), []
    for mode in MODES:
        summary[mode] = {}
        rounds = []
        for arm in ARMS:
            values = groups[mode, arm]
            ids = [r["round"] for r in values]
            if len(values) < 6 or len(ids) != len(set(ids)):
                pending.append(f"{mode} {arm}: need >=6 distinct complete rounds, have {len(values)}")
            rounds.append(set(ids))
            if not values:
                summary[mode][arm] = {"n": 0}
                continue
            summary[mode][arm] = dict(n=len(values),
                **{k: sum(r[k] for r in values) for k in ("moves", "returns", "exchanges")},
                **{k: mean(r[k] for r in values) for k in ("last_move_s", "end_spread", "band_floor", "rate", "p99")},
                max_last_move_s=max(r["last_move_s"] for r in values),
                max_end_spread=max(r["end_spread"] for r in values))
        if rounds[0] != rounds[1] or rounds[0] != rounds[2]:
            pending.append(f"{mode}: arm round sets differ")
        if any(summary[mode][a]["n"] < 6 for a in ARMS):
            continue
        post = summary[mode]["POST"]
        for arm in ("PRE", "PAD-A"):
            control = summary[mode][arm]
            if post["moves"] >= control["moves"]:
                failures.append(f"{mode}: pooled moves {post['moves']} >= {arm} {control['moves']}")
            for metric, sign in (("rate", -1), ("p99", 1)):
                delta = 100 * (post[metric] / control[metric] - 1)
                post[f"{metric}_delta_vs_{arm}"] = delta
                if sign * delta > 2:
                    failures.append(f"{mode}: {metric} vs {arm} {delta:+.3f}% exceeds box band")
        twin = summary[mode]["PAD-A"]
        # Use the twin's sampling floor as a LOWER BOUND on its true jitter band.
        # This is stricter than 1.5 times that band's actual (possibly wider) value.
        loss = post["end_spread"] - twin["end_spread"]
        post.update(accuracy_loss=loss, accuracy_allowance=1.5 * twin["band_floor"],
                    accuracy_loss_bands=loss / twin["band_floor"])
        if loss > post["accuracy_allowance"]:
            accuracy.append(f"{mode}: accuracy loss {loss:.3f} > 1.5-band allowance {post['accuracy_allowance']:.3f}")
    # Missing evidence is never converted into a loss or gain by dropping rounds.
    verdict = "UNTUNED" if pending else "SHELVE" if failures else "UNTUNED" if accuracy else "EPISODES PASS; mainline null and gate pending"
    return dict(verdict=verdict, summary=summary, failures=failures, pending=pending + accuracy, rows=rows,
                accuracy_rule="mean POST end spread - mean PAD-A end spread <= 1.5 * mean PAD-A sampling-floor band; max endpoints reported",
                band_method="sampling_floor(owners) times per-owner visits/second in endpoint's last 3 seconds; a conservative lower bound on the admission band",
                box_band_pct=2.0)


def report(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    config = manifest["config"]
    rows, invalid = [], []
    for path in sorted(directory.glob("key-skew-*-r*/run.json")):
        try:
            row = quantities(path, config)
            if row is not None: rows.append(row)
        except (KeyError, ValueError, OSError) as error:
            invalid.append(f"{path}: {error}")
    result = judge(rows, invalid)
    result["manifest"] = str(directory / "manifest.json")
    result["arms"] = manifest.get("arms")
    return result


def display(result):
    print(result["verdict"])
    print("\n| Mode | Arm | n | Moves | Returns | Exchanges | Last move mean/max s | End spread mean/max | Rate | p99 ms |")
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for mode in MODES:
        for arm in ARMS:
            r = result["summary"][mode][arm]
            if not r["n"]:
                print(f"| {mode} | {arm} | 0 | NA | NA | NA | NA | NA | NA | NA |")
                continue
            print(f"| {mode} | {arm} | {r['n']} | {r['moves']} | {r['returns']} | {r['exchanges']} | "
                  f"{r['last_move_s']:.3f}/{r['max_last_move_s']:.3f} | {r['end_spread']:.3f}/{r['max_end_spread']:.3f} | "
                  f"{r['rate']:.1f} | {r['p99']:.3f} |")
        post = result["summary"][mode]["POST"]
        if "accuracy_loss" in post:
            print(f"\n{mode}: measured mean accuracy loss {post['accuracy_loss']:.3f} visits/tick "
                  f"({post['accuracy_loss_bands']:.3f} bands), allowance {post['accuracy_allowance']:.3f}.\n")
    for why in result["failures"] + result["pending"]: print("- " + why)


class SelfTest(unittest.TestCase):
    def test_raw_owner_maps_and_fixed_endpoint_override_pass_flag(self):
        parent = Path(__file__).resolve().parents[1] / "build"
        parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            path = Path(temporary) / "run.json"
            path.write_text(json.dumps(dict(episode="key-skew", mode="1s", arm="POST", round=1,
                                           status="FAIL", measurement_valid=True, stimulus_t=2,
                                           rate=400, p99=1)))
            samples = []
            for i in range(91):
                moved = i >= 30
                owners = (1, 0, 0, 1) if moved else (0, 1, 0, 1)
                samples.append(dict(t=i / 10,
                    info={episodes.KEY: 2 * moved, episodes.SPREADS[0]: 20},
                    signals={"shards": {str(sid): {"owner": owner, "ops": 10 * i}
                                          for sid, owner in enumerate(owners)}}))
            telemetry = path.with_name("telemetry.jsonl")
            def save(): telemetry.write_text("".join(json.dumps(s) + "\n" for s in samples))
            save()
            result = quantities(path, dict(max_converge=3, suffix=1))
            self.assertEqual((result["moves"], result["returns"], result["exchanges"]), (2, 0, 1))
            self.assertEqual((result["last_move_s"], result["end_spread"]), (1, 20))
            self.assertAlmostEqual(result["band_floor"], 2 * episodes.sampling_floor(2))
            samples[-1]["info"][episodes.KEY] += 2
            save()
            with self.assertRaisesRegex(ValueError, "missed a completed move"):
                quantities(path, dict(max_converge=3, suffix=1))

    def rows(self):
        return [dict(mode=m, arm=a, round=i, moves=1 if a == "POST" else 2,
                     returns=0, exchanges=0, last_move_s=3, end_spread=15 if a == "POST" else 10,
                     band_floor=4, rate=100, p99=1)
                for m in MODES for a in ARMS for i in range(1, 7)]

    def test_pooled_mean_bound_and_strict_twin(self):
        rows = self.rows()
        self.assertTrue(judge(rows)["verdict"].startswith("EPISODES PASS"))
        for r in rows:
            if r["arm"] == "PAD-A": r["moves"] = 1
        self.assertEqual(judge(rows)["verdict"], "SHELVE")

    def test_incomplete_accuracy_and_perf_cannot_pass(self):
        self.assertEqual(judge(self.rows()[:-1])["verdict"], "UNTUNED")
        rows = self.rows()
        for r in rows:
            if r["arm"] == "POST": r["end_spread"] = 17
        self.assertEqual(judge(rows)["verdict"], "UNTUNED")
        rows = self.rows()
        rows[0]["round"] = rows[1]["round"]
        self.assertEqual(judge(rows)["verdict"], "UNTUNED")
        rows = self.rows()
        for r in rows:
            if r["arm"] == "POST": r["p99"] = 1.021
        self.assertEqual(judge(rows)["verdict"], "SHELVE")
        rows = self.rows()
        for r in rows:
            if r["arm"] == "POST": r["rate"] = 97.9
        self.assertEqual(judge(rows)["verdict"], "SHELVE")
        self.assertEqual(judge(self.rows(), ["telemetry gap"])["verdict"], "UNTUNED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(0 if unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(SelfTest)).wasSuccessful() else 1)
    if args.directory is None:
        parser.error("directory required")
    result = report(args.directory)
    display(result)
    if args.json: args.json.write_text(json.dumps(result, indent=2) + "\n")
    raise SystemExit(0 if result["verdict"].startswith("EPISODES PASS") else 1)
