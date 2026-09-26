#!/usr/bin/env python3
"""Read the final schema-1 shutdown report; clean also requires IO tenure conservation.

LOG present|clean|get PATH|io [--edges]. IO wall is independently sampled, not
busy+idle. Nanosecond accounting must be exact; the allowed outer residual is
fixed BEFORE a run to the measured endpoint bracket width, never a percentage.
"""
import json
import sys


def fail(message):
    raise SystemExit("shutdown report: " + message)


def load_report(path):
    with open(path, "rb") as stream:
        lines = stream.read().splitlines()
    if not lines:
        fail("empty log")
    prefix = b"shutdown_report "
    if not lines[-1].startswith(prefix):
        fail("last line is not shutdown_report: %r" % lines[-1][:160])
    try:
        report = json.loads(lines[-1][len(prefix):])
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        fail("invalid JSON: %s" % error)
    if report.get("schema") != 1:
        fail("unsupported schema %r" % report.get("schema"))
    return report


def require_io_conservation(report, edges=False):
    rows = report.get("threads", [])
    if not rows:
        fail("IO tenure evidence: no thread rows")
    count, mixed = 0, False
    fired = dict.fromkeys(("did_submit", "sweep_submit", "park", "role_exit"), 0)
    seen = set()
    for row in rows:
        tid = row.get("tid")
        if type(tid) is not int or tid in seen:
            fail("IO tenure evidence: invalid/duplicate tid")
        seen.add(tid)
        tenures = row.get("io_tenures")
        if not isinstance(tenures, list):
            fail("t%s: missing independent IO tenure row" % tid)
        if row.get("role") in ("io", "fused") and not tenures:
            fail("t%s: IO role never entered an accounted tenure" % tid)
        prior_exit, busy, idle = 0, 0, 0
        for n, t in enumerate(tenures):
            label = "t%s/IO%d" % (tid, n)
            fields = ("entry_ns", "begin_ns", "end_ns", "exit_ns", "busy_ns", "idle_ns",
                      "did_submit", "sweep_submit", "park")
            if any(type(t.get(k)) is not int or t[k] < 0 or t[k] >= 2**64 for k in fields):
                fail(label + ": missing/invalid cut or counter")
            if any(type(t.get(k)) is not bool for k in ("role_exit", "stopped")):
                fail(label + ": missing exit reason")
            if not (prior_exit <= t["entry_ns"] <= t["begin_ns"] <= t["end_ns"] <= t["exit_ns"]):
                fail(label + ": non-monotonic/overlapping tenure endpoints")
            if not (t["role_exit"] or t["stopped"]):
                fail(label + ": neither role exit nor shutdown fired")
            wall = t["exit_ns"] - t["entry_ns"]
            uncertainty = t["begin_ns"] - t["entry_ns"] + t["exit_ns"] - t["end_ns"]
            accounted = t["busy_ns"] + t["idle_ns"]
            if accounted != t["end_ns"] - t["begin_ns"]:
                fail(label + ": completed interval is not exact (busy+idle=%d inner_wall=%d)" %
                     (accounted, t["end_ns"] - t["begin_ns"]))
            if abs(wall - accounted) > uncertainty or wall - accounted != uncertainty:
                fail(label + ": independent wall residual exceeds endpoint uncertainty")
            count += 1
            busy += t["busy_ns"]
            idle += t["idle_ns"]
            prior_exit = t["exit_ns"]
            for key in fired:
                fired[key] += t[key]
        if busy > row.get("busy_ns", -1) or idle > row.get("idle_ns", -1):
            fail("t%s: role-separated IO totals exceed lifetime counters" % tid)
        mixed |= len(tenures) > 1 and any(t["role_exit"] for t in tenures[:-1])
    if not count:
        fail("no completed IO tenure; unentered window")
    required = ("did_submit", "sweep_submit", "park") + (("role_exit",) if report.get("thread_mode") == "2s" else ())
    if edges and (not all(fired[k] for k in required) or
                  (report.get("thread_mode") == "2s" and not mixed)):
        fail("required did-submit/sweep-submit/park/IO->EX->IO window never opened: %r mixed=%s" %
             (fired, mixed))
    return dict(tenures=count, fired=fired, mixed=mixed)


def main():
    if len(sys.argv) < 3:
        fail("usage: LOG present|clean|get PATH|io [--edges]")
    path, action = sys.argv[1:3]
    report = load_report(path)
    if action == "present":
        return
    if action in ("clean", "io"):
        require_io_conservation(report, edges="--edges" in sys.argv[3:])
        if action == "clean":
            stuck = report.get("stuck", {})
            wanted = ("live_conns", "rob_not_quiesced", "unsent_bytes_pending")
            dirty = {name: stuck.get(name) for name in wanted if stuck.get(name) != 0}
            if dirty:
                fail("dirty shutdown: %r" % dirty)
        return
    if action != "get" or len(sys.argv) != 4:
        fail("usage: LOG present|clean|get PATH|io [--edges]")
    value = report
    for component in sys.argv[3].split("."):
        if not isinstance(value, dict) or component not in value:
            fail("missing field %s" % sys.argv[3])
        value = value[component]
    if isinstance(value, bool):
        print("1" if value else "0")
    elif isinstance(value, (int, float, str)):
        print(value)
    else:
        fail("field %s is not scalar" % sys.argv[3])


if __name__ == "__main__":
    main()
