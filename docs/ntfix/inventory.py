#!/usr/bin/env python3
"""Annotate, without modifying, the unmodified identity tools' full inventory."""
from collections import Counter
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/ntfix/ntfix2/identity"


def reason(name):
    if "resp_preauth_error(" in name:
        return "N3: new cold error classifier using the existing strict length decoder"
    if "parse_and_dispatch<" in name:
        return "N3 error-exit call and N4 inlined limit accounting; associated compiler inlining/codegen"
    if "IoLoop::epoll_recv(" in name:
        return "N1 received-byte add and N4 inlined receive cap/check; associated compiler codegen"
    if any(x in name for x in ("Client::query_buffer_pos(", "Client::query_buffer_exceeded(",
                               "Client::read_space(")):
        return "N4: saved completed-prefix frontier in the query check/receive cap"
    if any(x in name for x in ("IoLoop::arm_recv<", "IoLoop::drive_tls<",
                               "IoLoop::query_buffer_exceeded(", "IoLoop::on_cqe")):
        return "N4 receive cap/check compiled into caller; associated compiler inlining/codegen"
    if "WbEngine::pump_tls<" in name:
        return "N2 close wakeup (uring) or epoll ciphertext-output accounting; associated compiler codegen"
    if any(x in name for x in ("WbEngine::pump_epoll(", "WbEngine::write_legacy_epoll(",
                               "WbEngine::submit_tls_cipher<")):
        return "Epoll output-byte accounting found by the required N1 INFO differential"
    return "Function source unedited; compiler inlining/codegen after changed network headers"


def main():
    rows = json.loads((OUT / "full/changed-bodies.json").read_text())
    rows = [dict(r, reason=reason(r["name"])) for r in rows]
    (OUT / "changed-bodies-with-reasons.json").write_text(json.dumps(rows, indent=2) + "\n")
    summary = json.loads((OUT / "full/summary.json").read_text())
    hot = {(r["object"], r["symbol"]) for r in summary["changed_hot"]}
    for filename, selected in (("changed-bodies.md", rows),
                               ("changed-hot-bodies.md",
                                [r for r in rows if (r["object"], r["symbol"]) in hot])):
        lines = ["# PRE 567d3b8e3 versus final ntfix2", "",
                 "Unmodified `ccfix_audit.py` canonical bytes and resolved relocation targets.",
                 "Zero means a body was not emitted in that arm. Source attribution does not",
                 "waive any difference or imply a performance verdict.", "",
                 "| Object | Function | PRE bytes | POST bytes | Why changed |",
                 "|---|---|---:|---:|---|"]
        for r in selected:
            lines.append(f"| `{r['object']}` | `{r['name']}` | {r['pre_size']} | "
                         f"{r['post_size']} | {r['reason']} |")
        (OUT / filename).write_text("\n".join(lines) + "\n")
    print(json.dumps(dict(changed=len(rows), changed_hot=len(hot),
                          reasons=dict(Counter(r["reason"] for r in rows))), indent=2))


if __name__ == "__main__":
    main()
