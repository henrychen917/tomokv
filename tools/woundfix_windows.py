#!/usr/bin/env python3
"""Copy-only owner-turn pause seams. Release sources/binaries get no hook.

The exact anchors fail closed if a publication site changes. Each pause runs
another owner's bounded fixture turn synchronously; no threads or timing delay.
"""
import argparse
from pathlib import Path
import shutil


def main():
    p = argparse.ArgumentParser()
    p.add_argument("destination", type=Path)
    p.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    a = p.parse_args()
    root = a.source.resolve()
    dest = a.destination
    shutil.copytree(root / "src", dest / "src", dirs_exist_ok=True)
    multi = dest / "src/cmd/multi.inc"
    group = dest / "src/cmd/txn_group.inc"
    def insert(path, anchor, addition):
        text = path.read_text()
        assert text.count(anchor) == 1, (path, anchor, text.count(anchor))
        path.write_text(text.replace(anchor, anchor + addition))
    insert(multi, "std::memory_order_acq_rel)) return false;\n    uint64_t zero = 0;",
           "\n    ::woundfix_pause(1, holder.token);")
    # The phase hook is before the epoch CAS; the local zero initialization is
    # intentionally allowed (it publishes nothing). The following hook observes
    # the other half of cancellation, between the epoch and aborted stores.
    insert(group, "std::memory_order_acq_rel)) {\n            uint64_t zero = 0;",
           "\n            ::woundfix_pause(2, &state);")
    insert(multi, "std::memory_order_acq_rel)) {\n                state.backoff.store(true, std::memory_order_relaxed);",
           "\n                ::woundfix_pause(3, &state);")
    # Epoch-to-aborted seams are anchored within their function, not a global
    # substitution over unrelated abort paths.
    for path, begin, end, store, site in [
        (multi, "bool txn_wound(", "\n}\n}", "holder.aborted->store(true, std::memory_order_release);", 4),
        (group, "bool txn_group_ready(", "\nvoid txn_group_cancel(", "state.aborted.store(true, std::memory_order_release);", 5),
    ]:
        text = path.read_text(); lo = text.index(begin); hi = text.index(end, lo)
        body = text[lo:hi]
        # In txn_group_ready the first aborted store belongs to blind restart.
        at = body.index(store)
        body = body[:at] + f"::woundfix_pause({site}, " + ("holder.token" if site == 4 else "&state") + ");\n" + body[at:]
        path.write_text(text[:lo] + body + text[hi:])
    # EXEC's blind publication uses multi_cancel_decision on PRE. POST's local
    # helper may move its store into execute_watch_phase; choose exactly one.
    text = multi.read_text()
    lo = text.index("bool execute_watch_phase("); hi = text.index("\nvoid finalize_reservations(", lo)
    body = text[lo:hi]
    if "multi_cancel_decision(state.decision, shard.id(), TxnCounter::BlindRestarts);" in body:
        lo = text.index("uint64_t multi_cancel_decision("); hi = text.index("\n}\n}", lo)
        body = text[lo:hi]
        store = "decision.aborted.store(true, std::memory_order_release);"
        hook = "::woundfix_pause(6, decision.owner);\n        "
    else:
        store = "state.decision.aborted.store(true, std::memory_order_release);"
        hook = "::woundfix_pause(6, &state);\n                "
    at = body.index(store)
    body = body[:at] + hook + body[at:]
    multi.write_text(text[:lo] + body + text[hi:])
    (dest / "stamp").write_text("six copy-only publication seams\n")


if __name__ == "__main__":
    main()
