This combined run executed `tools/ntfix_proof.py` as committed at `d5866243b`,
before the battery boot correction in `6792184d2`. The production binary is
SHA-256 `d6876ec3e8ff9a1d6df911ffac8e0f93cf609c1ecbb82a9014d12780bc280c01`.

All eight unchanged fragment legs pass 4,692 trials each, with no skipped close
cases. All four ordinary RESP compatibility batteries pass. The combined run
as a whole fails: four netcap invocations reject the default client balancing,
and two epoll full TLS batteries fail their default-cipher TLS1.3 gauge assertion.
The exact logs and original boot commands are preserved here.

The gate-profile battery rerun is separate, in `../batteries-gate-profile/`.
It uses NET1's fixed client ownership and DEBUG options, and the full TLS gate's
CBC/TLS1.3 AES-256-GCM settings with `--expect-ktls no`. It does not replace or
retroactively change the default-boot fragment or failure receipts above.
