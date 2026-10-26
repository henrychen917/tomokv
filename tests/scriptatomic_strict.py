#!/usr/bin/env python3
"""TM4.2: whole-battery DEBUG refusal with a live wire and temporary response fixture."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

source_path = Path(__file__).with_name("scriptatomic.py").resolve()
source = source_path.read_text()
marker = "\nconn = Conn()\n"
assert source.count(marker) == 1
# Intercept only DEBUG. ACL -debug would also disable EVAL by the server's
# script-permission policy, making a strict-skip control fail for another reason.
denied = """
_original_cmd = Conn.cmd
def _denied_debug(self, *args):
    if str(args[0]).upper() == 'DEBUG':
        return RespError('ERR fixture: DEBUG disabled')
    return _original_cmd(self, *args)
Conn.cmd = _denied_debug
"""
old_skip = """
def unavailable(detail):
    print('SKIP fixture: original non-strict DEBUG refusal', detail, flush=True)
"""


def require_strict_failure(result):
    assert result.returncode == 1, "DEBUG-denied strict battery incorrectly succeeded"
    assert "VACUOUS cross-owner geometry unavailable under TOMO_GATE_STRICT" in result.stdout
    assert "SCRIPTATOMIC: 1 FAIL (1 vacuous)" in result.stdout, result.stdout


with tempfile.TemporaryDirectory(prefix="scriptatomic-strict-") as directory:
    results = []
    for name, addition in (("headline", denied), ("old-skip", denied + old_skip)):
        fixture = Path(directory) / (name + ".py")
        fixture.write_text(source.replace(marker, "\n" + addition + marker))
        env = dict(os.environ, TOMO_GATE_STRICT="1", PYTHONPATH=str(source_path.parent))
        result = subprocess.run([sys.executable, str(fixture), sys.argv[1], sys.argv[2]],
                                env=env, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=60)
        print(f"-- {name} DEBUG-denied whole invocation exit={result.returncode}")
        print(result.stdout, end="")
        results.append(result)
    require_strict_failure(results[0])
    assert results[1].returncode == 0 and "SCRIPTATOMIC: 0 FAIL (0 vacuous)" in results[1].stdout
    try:
        require_strict_failure(results[1])
    except AssertionError as error:
        print(f"CONTROL FAIL TM4.2: original skip violates strict invocation: {error}")
    else:
        raise AssertionError("old skip control unexpectedly satisfied the strict contract")
