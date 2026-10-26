#!/usr/bin/env python3
"""TM4.2: deny DEBUG on the actual gate boot; the entire battery must fail strict."""
import os
from pathlib import Path
import subprocess
import sys
from contextlib import closing
from _lib import Conn

with closing(Conn(sys.argv[1], int(sys.argv[2]))) as admin:
    assert admin.must("ACL", "SETUSER", "default", "-debug") == b"OK"
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("scriptatomic.py")),
                                 sys.argv[1], sys.argv[2]], env=dict(os.environ, TOMO_GATE_STRICT="1"),
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        print(result.stdout, end="")
        assert result.returncode == 1, "DEBUG-denied strict battery incorrectly succeeded"
        assert "VACUOUS cross-owner geometry unavailable under TOMO_GATE_STRICT" in result.stdout
        print("CONTROL FAIL TM4.2: complete DEBUG-denied scriptatomic invocation exits 1")
    finally:
        assert admin.must("ACL", "SETUSER", "default", "+debug") == b"OK"
