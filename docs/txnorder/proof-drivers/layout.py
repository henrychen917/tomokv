#!/usr/bin/env python3
"""Inspect DWARF and TLS without starting either binary."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from lbstall_artifacts import Elf

LOCKS = dict(Op=336, Client=1984, ThreadCtx=1408, Shard=1440,
             FlatStore=944, AtomicEntry=144, Config=624)
LOCKS["Rob<64>"] = 192
LOCKS["ScatterState"] = 896
LOCKS["Shard::WatchReservation"] = 88
LOCKS["AtomicScriptIntent"] = 32
LOCKS["AtomicPendingState"] = 1352
TYPES = list(LOCKS) + ["Server", "MultiDecision", "MultiRetryLane", "MultiRetryNode",
                      "TxnGroupAttempt", "TxnOwnerCounters", "UnitRef"]
out = ROOT / "docs/txnorder/layout"
out.mkdir(parents=True, exist_ok=True)
arms = {}
for arm, binary in [("pre", ROOT / "build/txnorder/pre/tomokv"), ("post", ROOT / "build/tomokv")]:
    data = out / (arm + ".json")
    script = out / (arm + ".gdb")
    script.write_text("set pagination off\nset auto-load off\npython\n" +
                     "import gdb,json\nrows={}\n" +
                     "for ns in ('tomo','tomo_db0'):\n" +
                     " for name in " + repr(TYPES) + ":\n" +
                     "  t=gdb.lookup_type(ns+'::'+name)\n" +
                     "  fields={f.name:dict(bitpos=int(f.bitpos),size=int(f.type.sizeof)) for f in t.fields() if hasattr(f,'bitpos')}\n" +
                     "  rows[ns+'::'+name]=dict(size=int(t.sizeof),fields=fields)\n" +
                     "json.dump(rows,open(" + repr(str(data)) + ",'w'),indent=2)\nend\n")
    command = ["taskset", "-c", "48-63", "gdb", "-nx", "-batch", "-x", str(script), str(binary)]
    with (out / (arm + ".log")).open("w") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    rows = json.loads(data.read_text())
    for ns in ("tomo", "tomo_db0"):
        for name, size in LOCKS.items():
            assert rows[ns + "::" + name]["size"] == size, (arm, ns, name)
    elf = Elf(binary)
    tls = {s["name"]:dict(offset=s["value"], size=s["size"]) for s in elf.symbols
           if s["info"] & 15 == 6 and s["size"]}
    arms[arm] = dict(command=command, types=rows, tls=tls)
for ns in ("tomo", "tomo_db0"):
    for name in LOCKS:
        if name == "Shard::WatchReservation":
            continue  # three kind/mode bytes deliberately replace old padding
        assert arms["pre"]["types"][ns + "::" + name] == arms["post"]["types"][ns + "::" + name], name
assert arms["pre"]["tls"] == arms["post"]["tls"], "TLS layout changed"
(out / "result.json").write_text(json.dumps(dict(locked_sizes_and_existing_offsets_equal=True,
    reservation_size=88, tls_equal=True, arms=arms), indent=2) + "\n")
print("Locked layouts and TLS match; cold unit/Server layouts are inventoried.")
