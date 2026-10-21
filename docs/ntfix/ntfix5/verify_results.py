#!/usr/bin/env python3
"""Validate the two real gate-job ledgers, boot reports, and every ntfix leg log."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
LABELS = {
    "close": "TLS silent-peer close after reply (ntfix N2)",
    "preauth": "RESP pre-AUTH limit errors (ntfix N3)",
    "frontier": "RESP query-buffer frontier (ntfix N4)",
}


def main():
    result = {}
    for arm, expected_rc in (("post", 0), ("pre", 1)):
        base = OUT / arm
        assert int((base / "gate.rc").read_text()) == expected_rc
        rows = [line.split("\t") for line in (base / "tls/ledger").read_text().splitlines()]
        assert len(rows) == 20
        failed = {label for verdict, _, label in rows if verdict == "FAIL"}
        assert failed == (set(LABELS.values()) if arm == "pre" else set())
        assert (base / "tls/done").read_text().split() == (
            ["0", "17", "3"] if arm == "pre" else ["0", "20", "0"])
        logs = []
        for source in sorted((base / "tls").glob("gate-tls-srv.*.gz")):
            text = gzip.decompress(source.read_bytes()).decode()
            assert "--ratio is unavailable" not in text
            assert "listening on 127.0.0.1:22800" in text
            assert "listening with TLS on 127.0.0.1:22801" in text
            report = json.loads(next(line.split("shutdown_report ", 1)[1]
                                     for line in text.splitlines() if line.startswith("shutdown_report ")))
            mode = report["thread_mode"]
            engine = "epoll" if report["epoll"]["enabled"] else "uring"
            if mode == "1s":
                assert "read-local=1" in text
            logs.append(dict(file=str(source.relative_to(OUT)), mode=mode, engine=engine,
                             tcp_listener=22800, tls_listener=22801))
        counts = Counter((log["mode"], log["engine"]) for log in logs)
        assert counts == {("2s", "uring"): 6, ("2s", "epoll"): 3,
                          ("1s", "uring"): 3, ("1s", "epoll"): 3}
        legs = []
        for defect in LABELS:
            for mode in ("1s", "2s"):
                for engine in ("uring", "epoll"):
                    path = base / "tls" / f"ntfix-{defect}-{mode}-{engine}.txt"
                    text = path.read_text()
                    assert text and "--ratio is unavailable" not in text
                    passes = arm == "post" or (defect == "close" and engine == "epoll")
                    if passes:
                        if defect == "close":
                            for transport in ("TLS", "TCP"):
                                for case in ("protocol error reply then EOF", "QUIT reply then EOF",
                                             "pipeline then QUIT reply then EOF", "PING remains open"):
                                    assert f"  ok   {transport} {case}" in text
                        else:
                            cases = 23 if defect == "preauth" else 4
                            for tls in (False, True):
                                assert f"PASS ntfix {defect}: {cases} exact cases, tls={tls}" in text
                        witness = "TCP and TLS pass"
                    elif defect == "close":
                        assert "trailing = sock.recv(1)" in text
                        assert "TimeoutError: The read operation timed out" in text
                        witness = "TLS reply completed; waiting for EOF times out"
                    elif defect == "preauth":
                        assert "AssertionError: preauth tls=False: preauth array b'11'" in text
                        assert "invalid multibulk length" in text
                        witness = "TCP returns invalid multibulk length instead of unauthenticated length"
                    else:
                        assert "AssertionError: frontier tls=False: many completed args then over limit:" in text
                        assert "expected silence and open connection; got b''" in text
                        witness = "TCP closes before unconsumed input exceeds its limit"
                    legs.append(dict(defect=defect, mode=mode, engine=engine, passed=passes,
                                     witness=witness, log=str(path.relative_to(OUT))))
        assert "PASS netcap frontier" in (base / "tls/ntfix-frontier-unit.txt").read_text()
        result[arm] = dict(tls_rows=20, tls_pass=20 - len(failed), tls_fail=len(failed),
                           partial_pass=21 - len(failed), partial_fail=len(failed),
                           gate_returncode=expected_rc, boot_logs=logs, legs=legs,
                           post_transport_legs=24 if arm == "post" else None,
                           frontier_unit="current worktree unit; not bound to candidate binary")
    hashes = {}
    for name, binary, expected in (
        ("post", "build/tomokv", "db07cacf524e03f9907ac7c42c1c79b668792c322f9d73e3d127b2d07b18afae"),
        ("pre_bce4eb0aa", "build/ntfix4/headline-src/build/tomokv", "247bb68cf027485c61269762216c73fc81de6cdb968b84c28b44f7ad1da87ca5")):
        digest = hashlib.sha256((ROOT / binary).read_bytes()).hexdigest()
        assert digest == expected
        hashes[name] = dict(path=binary, sha256=digest)
    result["binaries"] = hashes
    gate = (ROOT / "tests/gate.sh").read_text()
    old = subprocess.check_output(["git", "show", "8ae8e65e5:tests/gate.sh"], cwd=ROOT, text=True)
    for line in ("EXPECT_QUICK=669", "EXPECT_FULL=686"):
        assert line in gate and line in old
    result["expect"] = dict(quick=669, full=686, unchanged=True)
    result["source_sha256"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                              for name in ("tests/gate.sh", "tests/gates_test.py", "tests/persistfix.py")}
    (OUT / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print("PASS POST: 20/20 TLS rows, 12 mode/engine logs, 24 TCP/TLS legs; 15/15 boots")
    print("PASS PRE negative control: exactly N2/N3/N4 fail; all 15 boots succeed, including six fused boots")
    print("PASS binary hashes and unchanged EXPECT_QUICK=669 / EXPECT_FULL=686")


if __name__ == "__main__":
    main()
