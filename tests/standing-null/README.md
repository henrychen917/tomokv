# Standing null publication

`current.json` selects a tracked publication receipt. The ABBA parser prefers it
to the worktree-local `.gate-history/receipts/baselines/full-null.json`; explicit
`--null-result`, `GATE_ABBA_NULL`, and `GATE_RECEIPT_NULL` still override it.

The content-addressed gzip files preserve the exact promoted null and original
collection bytes. The receipt binds their SHA-256s, the frozen campaign, the
complete instrument manifest, the inventory, and the referenced read-local
proofs. Those proofs are resolved by digest, so another worktree does not need
the campaign's original absolute paths. Matched evidence and its proof files
are also retained beside each gate comparison.

The initial publication is campaign 7, instrument
`3dcdaa497a4f1e2a670342e17daa27bb9c36e9a2cbc633196d134d85b65efb9a`, with
`independent_resolution: PENDING HOLDOUT`. It is historical evidence. Its bytes,
timestamp, 24-hour matching limit, and 46 UNRESOLVED cell classifications have
not changed. A new instrument fingerprint does not inherit its validity.

Publish an already promoted null with `tests/gate_receipt.py publish-standing-null
--null-result PATH --campaign PATH --independent-resolution 'PENDING HOLDOUT'`.
Historical archival additionally needs `--historical 1`. A `PASS` publication
requires `--comparison PATH --holdout-resolution PATH` and revalidates the full
independent holdout, including the published block counts. Historical replays
cannot provide that certification. Commit the resulting tracked files; there
is no gate receipt, automatic commit, push, or timestamp refresh in publication.
