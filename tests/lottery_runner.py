#!/usr/bin/env python3
"""Repeat a gate row on fresh state until K witnessed attempts, or a wall cap.

This is an opt-in correctness campaign, never a landing-gate receipt. A hit is
an attempt with *all* required witnesses, not a number of events in one attempt.
Failures on misses are failures too. Incomplete evidence is never a hit.
"""
import argparse
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HITS = 20  # Owner policy; docs/lottery/constants-ledger.md, LOTTERY-K.


def upper_bound(hits, failures=0, confidence=.95):
    """One-sided exact Clopper-Pearson binomial upper bound; no-hit = unknown.

    Fixed K successful observations selected by a mechanism witness, independent
    of the correctness oracle. A time-capped sample is descriptive only. This
    is NOT a bound on missed windows, all workloads, or correlated executions.
    """
    if not 0 <= failures <= hits or not 0 < confidence < 1:
        raise ValueError('invalid binomial inputs')
    if hits == 0:
        return None
    if failures == hits:
        return 1.0
    if failures == 0:
        return -math.expm1(math.log1p(-confidence) / hits)
    # Invert Pr[X <= failures] = 1-confidence in log space.
    def cdf(p):
        terms = [math.lgamma(hits + 1) - math.lgamma(i + 1) -
                 math.lgamma(hits - i + 1) + i * math.log(p) +
                 (hits - i) * math.log1p(-p) for i in range(failures + 1)]
        peak = max(terms)
        return math.exp(peak) * sum(math.exp(x - peak) for x in terms)
    lo, hi = 0.0, 1.0
    for _ in range(64):
        mid = (lo + hi) / 2
        if cdf(mid) > 1 - confidence:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def registry():
    rows = json.loads((ROOT / 'tests/lottery_rows.json').read_text())
    if len(rows) != 58 or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('class-B occurrence inventory changed; review registry')
    return rows


@dataclass
class Tally:
    required: tuple
    goal: int = DEFAULT_HITS
    attempts: int = 0
    hits: int = 0
    failures: int = 0
    hit_failures: int = 0
    errors: int = 0
    incomplete: int = 0
    witness_attempts: dict = field(default_factory=dict)

    def add(self, receipt):
        self.attempts += 1
        counters = receipt.get('counters', {})
        valid = (receipt.get('evidence_complete') is True and
                 isinstance(counters, dict) and all(
                     type(counters.get(k)) is int and counters[k] >= 0
                     for k in self.required))
        complete = receipt.get('completed') is True
        hit = valid and complete and all(counters[k] > 0 for k in self.required)
        if valid:
            for k in self.required:
                self.witness_attempts[k] = self.witness_attempts.get(k, 0) + (counters[k] > 0)
        self.incomplete += not complete
        self.errors += receipt.get('error') is not None or (complete and not valid)
        failed = receipt.get('passed') is False and complete
        self.failures += failed
        self.hits += hit
        self.hit_failures += hit and failed
        return hit

    def result(self, seconds):
        verdict = ('ERROR' if self.errors else 'FAIL' if self.failures else
                   'PASS' if self.hits >= self.goal else 'INSUFFICIENT')
        rate = self.hits / self.attempts if self.attempts else None
        return dict(verdict=verdict, attempts=self.attempts, hits=self.hits,
                    failures=self.failures, hit_failures=self.hit_failures,
                    errors=self.errors, incomplete=self.incomplete,
                    hit_rate=rate, target_hits=self.goal, seconds=seconds,
                    upper_95=upper_bound(self.hits, self.hit_failures),
                    bound_assumption='independent, stationary witnessed attempts; per row',
                    bound_fixed_k=verdict == 'PASS',
                    estimated_attempts_for_k=(self.goal / rate if rate else None),
                    estimated_seconds_for_k=(self.goal * seconds / self.hits
                                             if self.hits else None),
                    witness_attempts=self.witness_attempts)


def repeat(attempt, required, goal, cap, clock=time.monotonic, publish=lambda *args: None):
    if goal < 1 or not math.isfinite(cap) or cap <= 0 or not required:
        raise ValueError('positive K/cap and nonempty witness list required')
    tally = Tally(tuple(required), goal)
    start = clock()
    while tally.hits < goal and clock() - start < cap:
        receipt = attempt(tally.attempts + 1, max(0, cap - (clock() - start)))
        hit = tally.add(receipt)
        publish(receipt, hit, tally.result(clock() - start))
        if tally.failures or tally.errors or not receipt.get('completed'):
            break
    return tally.result(clock() - start)


def run_child(argv, log, timeout):
    """Own the complete attempt process group, including listeners and clients."""
    with Path(log).open('w') as stream:
        child = subprocess.Popen(argv, stdout=stream, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        timed_out = False
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            # Also clean grandchildren left by an unexpectedly exited attempt driver.
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
        return child.returncode, timed_out


def campaign(row, args, directory):
    directory.mkdir(parents=True, exist_ok=False)

    def attempt(index, remaining):
        attempt_dir = directory / f'attempt-{index:04d}'
        attempt_dir.mkdir()
        nonce = uuid.uuid4().hex
        argv = [sys.executable, str(ROOT / 'tests/lottery_attempt.py'),
                '--row', row['id'], '--output', str(attempt_dir), '--nonce', nonce,
                '--binary', str(args.binary.resolve()), '--port', str(args.port),
                '--server-cpus', args.server_cpus, '--client-cpus', args.client_cpus]
        rc, expired = run_child(argv, attempt_dir / 'attempt.log', remaining)
        path = attempt_dir / 'receipt.json'
        if expired:
            return dict(completed=False, passed=False, evidence_complete=False,
                        counters={}, reason='wall cap expired', nonce=nonce)
        if not path.exists():
            return dict(completed=True, passed=False, evidence_complete=False,
                        counters={}, error=f'no receipt; child exit {rc}')
        try:
            receipt = json.loads(path.read_text())
            if receipt['nonce'] != nonce or receipt['row'] != row['id']:
                raise ValueError('stale/wrong-row receipt')
            if rc != 0 and receipt.get('passed'):
                raise ValueError(f'green receipt but child exit {rc}')
            return receipt
        except (ValueError, KeyError) as exc:
            return dict(completed=True, passed=False, counters={}, error=str(exc))

    def publish(receipt, hit, summary):
        with (directory / 'attempts.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(receipt=receipt, hit=hit, summary=summary)) + '\n')
        write_json(directory / 'result.json', dict(row=row, **summary))

    result = dict(row=row, **repeat(attempt, row['requires'], args.hits, args.cap,
                                    publish=publish))
    write_json(directory / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('row', nargs='?', help='stable inventory ordinal or exact row name')
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--all', action='store_true', help='opt-in nightly campaign')
    parser.add_argument('--hits', type=int, default=DEFAULT_HITS)
    parser.add_argument('--cap', type=float, default=600, help='wall seconds per row, including boots')
    parser.add_argument('--binary', type=Path, default=ROOT / 'build/lottery/tomokv')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/lottery/nightly')
    parser.add_argument('--server-cpus', default='112-119')
    parser.add_argument('--client-cpus', default='120-127')
    parser.add_argument('--port', type=int, default=25300)
    args = parser.parse_args()
    rows = registry()
    if args.list:
        for r in rows:
            print(f"{r['id']:>3}  {r['name']}  ({', '.join(r['requires'])})")
        return 0
    if not args.all:
        rows = [r for r in rows if args.row in (r['id'], r['name'])]
    if not rows or (args.all and args.row):
        parser.error('select one named row or --all')
    if args.hits < 1 or not math.isfinite(args.cap) or args.cap <= 0:
        parser.error('--hits and --cap must be positive')
    from _gate_process import cpus
    server, client = set(cpus(args.server_cpus)), set(cpus(args.client_cpus))
    if server & client or not server | client <= set(range(112, 128)) or len(server) != 8:
        parser.error('use 8 server CPUs and disjoint client CPUs, all within 112-127')
    if not 25300 <= args.port <= 25397:
        parser.error('three consecutive ports must be within 25300-25399')
    os.sched_setaffinity(0, server | client)
    results = []
    for row in rows:
        result = campaign(row, args, args.output.resolve() / row['id'])
        results.append(result)
        print(f"{row['id']} {result['verdict']}: attempts={result['attempts']} "
              f"hits={result['hits']} hit_rate={result['hit_rate']} "
              f"upper95={result['upper_95']}", flush=True)
        write_json(args.output / 'results.json', results)
    return int(any(r['verdict'] != 'PASS' for r in results))


if __name__ == '__main__':
    sys.exit(main())
