#!/usr/bin/env python3
"""Link the current RL4.15 witness with frozen PRE objects in both namespaces."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
pre = root / "build/pre-source"
out = root / "build/rlfix3"
out.mkdir(exist_ok=True)
for image in ("multi", "db0"):
    variables = "$(DB0_TEST_OBJ) $(CORE_TEST_OBJ)" if image == "db0" else "$(CORE_TEST_OBJ)"
    objects = subprocess.check_output(["make", "-s", "--eval",
        "rlfix3-objects:;@echo " + variables, "rlfix3-objects"], cwd=pre, text=True).split()
    flags = ["-DTOMO_SINGLE_DATABASE=1", "-Dtomo=tomo_db0"] if image == "db0" else []
    cmd = ["g++", "-std=c++20", "-O2", "-g", "-march=native", "-pthread", "-DTOMO_JEMALLOC",
           *flags, "-I" + str(pre), str(root / "tests/rlfix3_info_unit.cc"),
           *(str(pre / name) for name in objects), "-ljemalloc", "-luring", "-lssl", "-lcrypto", "-lm",
           "-Wl,--wrap=clock_gettime,--wrap=getpid,--wrap=getrandom,--wrap=realpath,--wrap=mallctl,--wrap=time",
           "-o", str(out / ("info-pre-" + image))]
    with (out / ("unit-pre-" + image + ".log")).open("w") as log:
        subprocess.run(cmd, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
    print("Built", image, "PRE witness", flush=True)
