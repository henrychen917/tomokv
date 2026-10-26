"""Revert ONE harness5 repair (or all) in a scratch checkout, keeping every new test.

Usage: revert_fixes.py ROOT {cg46a,cg46b,cg47,cg48,all}
Each hunk is an exact string replacement of the repaired HEAD text by the base
(3700b51d7) text; a missing hunk is a hard error so a red run cannot be vacuous.
"""
import sys
from pathlib import Path

HUNKS = {
 'cg46a': [  # optional workload axes rejected by the floor/ceiling DATA validators
  ('tests/gate_measurements.py',
   '''                and type(floor["instances"]) is int and floor["instances"] > 0 and
                floor["status"] in ("calibrated", "historical-unverified"),
                f"{ident}: invalid load-floor fields")
        validate_shape(floor["shape"])
''',
   '''                and type(floor["instances"]) is int and floor["instances"] > 0 and
                set(floor["shape"]) in (set(SHAPE), set(SHAPE) | {"data_bytes"}) and
                type(floor["shape"].get("data_bytes", 64)) is int and
                floor["shape"].get("data_bytes", 64) > 0 and
                floor["status"] in ("calibrated", "historical-unverified"),
                f"{ident}: invalid load-floor fields")
'''),
  ('tests/abba_ceiling.py',
   'from gate_measurements import require, provenance, validate_shape, AXES',
   'from gate_measurements import require, provenance, SHAPE, AXES'),
  ('tests/abba_ceiling.py',
   '''    validate_shape(plan["shape"])
    require(set(plan["geometry"]) == set(AXES), "invalid ceiling-only geometry")
''',
   '''    require(set(plan["shape"]) in (set(SHAPE), set(SHAPE) | {"data_bytes"}) and
            set(plan["geometry"]) == set(AXES), "invalid ceiling-only shape/geometry")
'''),
 ],
 'cg46b': [  # freeze/current-campaign/promotion hard-coded to the headline inventory
  ('tests/gate_receipt.py',
   'require(campaign["inventory"] == inventory(root, root / campaign["inventory"]["path"]),',
   'require(campaign["inventory"] == inventory(root, root / "tests/headline_cells.txt"),'),
  ('tests/gate_receipt.py',
   'inv = inventory(root, getattr(args, "cells", None) or root / "tests/headline_cells.txt")',
   'inv = inventory(root, root / "tests/headline_cells.txt")'),
  ('tests/gate_receipt.py',
   '''    name = "epoll-null.json" if campaign["inventory"]["path"] == "tests/netio_cells.txt" else "full-null.json"
    path = directory / "baselines" / name
''',
   '''    path = directory / "baselines/full-null.json"
'''),
 ],
 'cg47': [  # a promoted full null is matched by full-campaign validation of the comparison
  ('tests/abba_evidence.py',
   'validate_campaign_evidence(comparison, full=comparison.get("run_kind") == "null-holdout")',
   'validate_campaign_evidence(comparison)'),
 ],
 'cg48': [  # the receipt keeps only the headline report/null of the two-pass product
  ('tests/gate_receipt.py',
   '''    from gate_product_evidence import read_product, validate_product
    product = read_product(args.product_result)
    validate_product(root, product, state, report, control, candidate, ended)
''', ''),
  ('tests/gate_receipt.py',
   '"observations": observed, "abba": report, "null": control, "product": product}',
   '"observations": observed, "abba": report, "null": control}'),
  ('tests/gate_receipt.py',
   '''    from gate_product_evidence import validate_product
    validate_product(root, evidence.get("product"), state, evidence["abba"], evidence["null"],
                     binary, completed["finished_at"])
''', ''),
 ],
}


def main():
    root, variant = Path(sys.argv[1]), sys.argv[2]
    for name in (HUNKS if variant == 'all' else [variant]):
        for relative, new, old in HUNKS[name]:
            path = root / relative
            text = path.read_text()
            if text.count(new) != 1:
                raise SystemExit(f'{name}: repaired hunk not found exactly once in {relative}')
            path.write_text(text.replace(new, old, 1))
            print(f'reverted {name}: {relative}')


if __name__ == '__main__':
    main()
