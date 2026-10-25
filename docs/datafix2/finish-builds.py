#!/usr/bin/env python3
"""Final lean-build/freshness proof after all correctness processes have ended."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/datafix2"
for filename in ("campaign-state.json", "campaign-watch-state.json"):
    state = json.loads((DOC / filename).read_text())
    assert state.get("active") is None and state.get("completed") == state.get("planned"), filename
assert (DOC / "campaign-reruns-results.json").exists(), "snapshot repeat still pending"
paths = [ROOT / "build" / name for name in ("tomokv-pre", "tomokv", "tomokv-pad-a")]
paths.append(ROOT / "build/pre-objects/build/tomokv")
def hashes():
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
before = hashes()
if not (DOC / "lean-build-first.json").exists():
    shutil.copyfile(DOC / "lean-build.json", DOC / "lean-build-first.json")
with (DOC / "lean-build-final.log").open("w") as log:
    subprocess.run(["taskset", "-c", "96-111", "python3", str(DOC / "lean-build.py")], cwd=ROOT,
                   stdout=log, stderr=subprocess.STDOUT, check=True)
shutil.copyfile(DOC / "lean-build.json", DOC / "lean-build-final.json")
results = []
for prefix, source in (("post-handoff-", None), ("pre-handoff-", ROOT / "build/pre-objects")):
    argv = ["taskset", "-c", "96-111", "python3", str(DOC / "build-units.py"), "--prefix", prefix]
    if source:
        argv += ["--source-root", str(source)]
    with (DOC / (prefix + "build.log")).open("w") as log:
        rc = subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT).returncode
    result = json.loads((DOC / (prefix + "unit-build.json")).read_text())
    assert rc == 0 and result["build_returncode"] == 0 and all(row["returncode"] == 0 for row in result["checks"]), prefix
    results.append(dict(prefix=prefix, checks=len(result["checks"]), returncode=rc))
after = hashes()
assert before == after, "merit or baseline server executable changed"
(DOC / "handoff-build-proof.json").write_text(json.dumps(dict(before=before, after=after,
    unchanged=True, freshness=results), indent=2) + "\n")
print("Merit arms and baseline copy unchanged; both arms pass all final build/freshness checks.")
