"""Serverless argv census. Geometry below is historical DATA, never executed."""
import gzip, hashlib, json, os, subprocess, sys
from pathlib import Path
ROOT = Path(os.getenv("HARNESS5_ARGV_ROOT", str(Path(__file__).resolve().parents[2])))
sys.path.insert(0, str(ROOT / "tests"))
import abbagate as abba
import gateprod

def snapshot():
    args = gateprod.parse_abba(["--candidate", "/DRY-RUN/candidate", "--reference-binary", "/DRY-RUN/reference",
        "--server-cores", "0-31", "--load-cores", "32-111", "--server-smt", "", "--load-smt", "",
        "--port", "45800", "--memtier", "/DRY-RUN/memtier"])
    args.port = 45800
    runner = abba.Runner(args, Path("/DRY-RUN/output"), {"A": args.reference_binary, "B": args.candidate}, None)
    paths = subprocess.check_output(["git", "ls-files", "*cells*.txt"],
                                    cwd=Path(__file__).resolve().parents[2], text=True).splitlines()
    result = {}
    from functools import lru_cache
    abba.measured_ratio = lru_cache(None)(abba.measured_ratio)
    for name in paths:
        try: cells = abba.read_cells(ROOT / name)
        except ValueError as error:
            result[name] = {"refused": str(error).replace(str(ROOT), "<ROOT>")}; continue
        rows = []
        for cell in cells:
            try: gateprod.knobs(cell)
            except abba.KnobNotAccepted as error:
                rows.append(dict(cell=abba.cell_receipt(cell), refused=str(error))); continue
            rungs = sorted(set([cell.instances or 1] + [n for n in abba.LADDER if n <= min(24, cell.conns)]))
            plans = []
            for n in rungs:
                layout = abba.load_layout(runner.load_cpus, n, cell.conns, cell.dbs)
                arms = {}
                for arm in "AB":
                    folder = Path("/DRY-RUN/output") / cell.id / f"n{n}-{arm}"
                    arms[arm] = dict(server=gateprod.server_argv(runner, cell, arm, folder),
                        loads=[runner.memtier(part, cell=cell) + abba.workload_arguments(cell) +
                          [f"--pipeline={cell.depth}", f"--test-time={abba.WARMUP+abba.WINDOW+abba.TAIL}",
                           "--json-out-file=" + str(folder / ("load-%d.json" % i))] + abba.client_arguments(cell.client_flags)
                          for i, part in enumerate(layout)])
                plans.append(dict(instances=n, layout=layout, arms=arms))
            rows.append(dict(cell=abba.cell_receipt(cell), plans=plans))
        result[name] = rows
    return result

if __name__ == "__main__":
    raw = json.dumps(snapshot(), sort_keys=True, separators=(",", ":")).encode()
    Path(sys.argv[1]).write_bytes(gzip.compress(raw, mtime=0))
    print(hashlib.sha256(raw).hexdigest(), "uncompressed bytes", len(raw))
