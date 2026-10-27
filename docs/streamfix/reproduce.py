"""Replay the assigned harness5 transcripts; no throughput measurements."""
import argparse, hashlib, importlib.util, json
from pathlib import Path
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("h5repro", ROOT / "docs/harness5/repro_tcl.py")
h5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h5)
ROOTS = ["STREAM-TRIM-APPROX-LIMIT", "XREAD-PLUS-LAST", "XRANGE-EXCLUSIVE-SENTINEL",
         "STREAM-GROUP-ID-DASH", "XAUTOCLAIM-COUNT-RANGE", "DUMP-STREAM-REFUSED",
         "RESTORE-IDLETIME-FREQ-IGNORED", "OBJECT-IDLETIME-ZERO", "MPOP-ARG-ERROR-TEXT"]
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--expect-pre", action="store_true")
    a = p.parse_args()
    a.binary = a.binary.resolve()
    oracle = Path("/home/user/Projects/redis74/src/redis-server")
    cases = json.loads((ROOT / "docs/harness5/redis-tcl-repros.json").read_text())["cases"]
    out = dict(binary_sha256=h5.hashlib.sha256(a.binary.read_bytes()).hexdigest(),
               redis_sha256=h5.hashlib.sha256(oracle.read_bytes()).hexdigest(), cases={})
    for root in ROOTS:
        key, case = next((k,v) for k,v in cases.items() if k.endswith(root))
        original = dict(steps=case["steps"], server_args=case.get("server_args", []))
        options = SimpleNamespace(port=20600, cores="96-103", ratio="6:2")
        results = {"redis": h5.play(original, "redis", oracle, options,
                    ROOT / "build/streamfix/repro" / a.output.stem / root / "redis")}
        for engine in ("uring", "epoll"):
            target_case = dict(original, server_args=original["server_args"] + ["--net-io", engine])
            for mode in ("2s", "1s"):
                results[engine + "-" + mode] = h5.play(target_case, mode, a.binary, options,
                    ROOT / "build/streamfix/repro" / a.output.stem / root / (engine + "-" + mode))
        replies = lambda result: [x["reply"] for x in result["transcript"] if "reply" in x]
        verdict = {k: "SAME" if replies(v) == replies(results["redis"]) else "DIFFERENT"
                   for k,v in results.items() if k != "redis"}
        out["cases"][root] = dict(results=results, verdict=verdict)
        a.output.write_text(json.dumps(out, indent=2) + "\n")
        print(root, verdict, flush=True)
        if a.expect_pre: assert set(verdict.values()) == {"DIFFERENT"}, root
if __name__ == "__main__": main()
