#!/usr/bin/env python3
"""Run unchanged R7 negative checks after its inventory guard stopped the job.

This is supplemental evidence, not a replacement or a green R7 gate result.
"""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, "tests")
import reorder_noop as audit
import reorder_receipt
import r7shadow_noop

binary = Path("build/tomokv")
out = Path("build/moverfix/reorder-negative-post")
out.mkdir(parents=True, exist_ok=True)
parsed = audit.Binary(binary, out, literal_pools=True)
r7shadow_noop.off_roles(parsed)
reorder_receipt.controls(parsed, out)
Path("docs/moverfix/reorder-negative-post.json").write_text(json.dumps(dict(
    binary=str(binary), sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
    missing_symbol_rejected=True, missing_splitlocal_parser_rejected=True,
    changed_opcode_rejected=True,
    gate_inventory_guard="Still fails 145/146 versus expected 146/146; unchanged."
), indent=2) + "\n")
