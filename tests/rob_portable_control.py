#!/usr/bin/env python3
"""NT4.17 portable ROB: compile a throwaway missing-fence-clear control."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="rob-portable-control-") as temporary:
    work = Path(temporary)
    shutil.copytree(root / "src", work / "src")
    header = work / "src/net/rob.h"
    text = header.read_text()
    old = "if (bits & read_local_slot_bit(local_mget_fence_id_)) local_mget_fence_id_ = UINT64_MAX;"
    assert text.count(old) == 1, "portable control seam changed"
    header.write_text(text.replace(old, "/* throwaway: retain stale completed MGET fence */"))
    source = work / "control.cc"
    source.write_text('#ifdef __BMI__\n#error portable control unexpectedly enables BMI\n#endif\n'
                      + '#include "' + str(root / "tests/rlfence_unit.cc") + '"\n')
    binary = work / "unit"
    subprocess.run([os.environ.get("CXX", "g++"), "-std=c++20", "-O2", "-pthread",
                    "-mno-bmi", "-mno-bmi2", "-I" + str(work), "-I" + str(root),
                    str(source), "-o", str(binary)], check=True, timeout=90)
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    print(result.stdout, end="")
    print(result.stderr, end="")
    assert result.returncode == 1 and "clear the covered MGET fence before retirement" in result.stderr, result
    print("CONTROL FAIL NT4.17: portable completion retained a stale MGET fence")
