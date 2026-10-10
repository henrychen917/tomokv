#!/usr/bin/env python3
"""Summarize recorded AOF proof timings; never starts a server."""
import csv
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/aoffix2"


def events(arm, label, event):
    folder = "pre-timings" if arm == "PRE" else "post-timings"
    if arm == "PRE" and label in ("tlswake-2s", "2s-conns-everysec-ratio1to1", "2s-gate-hol"):
        folder = "pre-extra"
    result = []
    for line in (OUT / folder / (label + ".log")).read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("event") == event:
            result.append(row)
    assert result, (arm, label, event)
    return result


def load_range(rows):
    values = [float(row[key]["loadavg"].split()[0]) for row in rows
              for key in ("load_before", "load_after")]
    return f"{min(values):.1f}–{max(values):.1f}"


def latency(row):
    return "/".join(f"{row[k]:.3f}" for k in ("p50", "p99", "max"))


lines = ["### PRE/POST acknowledgement latency", "",
         "Milliseconds, **p50 / p99 / max**. Sequential rows use one connection proven off",
         "the writer. Twelve-connection and default rows report the maximum of each",
         "statistic across all 12 connections, not a pooled percentile. Each connection",
         "has 20 measured SETs after four warmups; sequential rows have 200. Payload is",
         "100 bytes. Both arms use eight target cores; split uses 6:2 and 16 shards.",
         "Defaults preserve the shipped placement, shard count and balancers. The",
         "[per-connection CSV](docs/aoffix2/latency-connections.csv) retains every statistic.", "",
         "Host one-minute load ranges are included in each row. Raw logs also retain",
         "per-target-CPU activity and concurrent process samples. These runs share the",
         "reserved cores with sibling lanes; use them to assess the 50 ms wait, not",
         "as a paper-quality microsecond performance comparison.", "",
         "| Shape | Policy | PRE p50/p99/max ms | POST p50/p99/max ms | PRE load | POST load |",
         "|---|---|---:|---:|---:|---:|"]
connections = []
for shape in ("1s-seq", "2s-seq", "1s-conns", "2s-conns", "defaults", "2s-conns-everysec-ratio1to1"):
    policies = ("everysec",) if "ratio" in shape else ("off", "no", "everysec", "always")
    for policy in policies:
        label = shape if "ratio" in shape else f"{shape}-{policy}"
        data = {}
        for arm in ("PRE", "POST"):
            rows = events(arm, label, "latency_ms")
            assert len(rows) == 1
            per = rows[0]["connections"]
            data[arm] = (latency({k: max(row[k] for row in per) for k in ("p50", "p99", "max")}), load_range(rows))
            for index, row in enumerate(per):
                connections.append(dict(arm=arm, shape=shape, policy=policy, connection=index,
                    **row, load_before=rows[0]["load_before"]["loadavg"],
                    load_after=rows[0]["load_after"]["loadavg"]))
        lines.append(f"| {shape} | {policy} | {data['PRE'][0]} | {data['POST'][0]} | {data['PRE'][1]} | {data['POST'][1]} |")
with (OUT / "latency-connections.csv").open("w") as target:
    writer = csv.DictWriter(target, fieldnames=list(connections[0]))
    writer.writeheader()
    writer.writerows(connections)
lines += ["", "### Snapshot wake and reply head of line", "",
          "BGSAVE seconds for 400,000 keys with 200-byte values, observed by snapshot-file",
          "publication. Unpoked does not poll the server; poked sends PINGs every 1 ms.", "",
          "| Mode | PRE unpoked/poked s | POST unpoked/poked s | PRE load | POST load |",
          "|---|---:|---:|---:|---:|"]
for mode in ("1s", "2s"):
    data = {}
    for arm in ("PRE", "POST"):
        rows = events(arm, f"bgsave-{mode}", "bgsave_seconds")
        assert len(rows) == 2 and {row["poked"] for row in rows} == {False, True}
        data[arm] = ("/".join(f"{next(r['seconds'] for r in rows if r['poked'] == poked):.3f}" for poked in (False, True)), load_range(rows))
    lines.append(f"| {mode} | {data['PRE'][0]} | {data['POST'][0]} | {data['PRE'][1]} | {data['POST'][1]} |")
lines += ["", "For two connections proven on the same nonwriter IO thread, the median PING",
          "latency alone / behind SET (five pairs) was:", ""]
for arm in ("PRE", "POST"):
    rows = events(arm, "2s-gate-hol", "gate_hol_ms")
    per = rows[0]["pairs"]
    medians = "/".join(f"{statistics.median(row[k] for row in per):.3f}" for k in ("alone", "behind"))
    lines.append(f"- {arm}: **{medians} ms**, host load {load_range(rows)}.")
lines += ["", "### TLS report-only check", "",
          "TLS 1.3 GET pipelines, depth 32, eight batches per cell, three fresh boots.",
          "The table shows the median of the three per-boot p50s in milliseconds.",
          "Idle/poked cells use no extra traffic / PING every 1 ms. The complete",
          "[TLS CSV](docs/aoffix2/tls-connections.csv) retains p50/p99/max for every repeat.", "",
          "| Mode | Value | PRE idle/poked p50 ms | POST idle/poked p50 ms | PRE load | POST load |",
          "|---|---:|---:|---:|---:|---:|"]
tls = []
for mode in ("1s", "2s"):
    for size in (1024, 4096, 16384):
        data = {}
        for arm in ("PRE", "POST"):
            rows = [row for row in events(arm, f"tlswake-{mode}", "tlswake_ms") if row["size"] == size]
            assert len(rows) == 6
            data[arm] = ("/".join(f"{statistics.median(r['latency']['p50'] for r in rows if r['poked'] == poked):.3f}" for poked in (False, True)), load_range(rows))
            for row in rows:
                tls.append(dict(arm=arm, mode=mode, size=size, rep=row["rep"], poked=row["poked"],
                                **row["latency"], load_before=row["load_before"]["loadavg"],
                                load_after=row["load_after"]["loadavg"]))
        lines.append(f"| {mode} | {size // 1024} KiB | {data['PRE'][0]} | {data['POST'][0]} | {data['PRE'][1]} | {data['POST'][1]} |")
with (OUT / "tls-connections.csv").open("w") as target:
    writer = csv.DictWriter(target, fieldnames=list(tls[0]))
    writer.writeheader()
    writer.writerows(tls)
(OUT / "timings.md").write_text("\n".join(lines) + "\n")
print(OUT / "timings.md")
