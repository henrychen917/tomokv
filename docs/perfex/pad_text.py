#!/usr/bin/env python3
"""Build PAD kind B: candidate behavior, padding restores PRE .text byte size.

No production source or object is changed. This controls total text size only;
it does not claim to restore every PRE function's address or instruction layout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from lbstall_artifacts import Elf


def text_size(path):
    elf = Elf(path)
    return elf.sections[elf.names.index(".text")][5]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pre", type=Path, default=ROOT / "build/perfex/pre/tomokv")
    p.add_argument("--post", type=Path, default=ROOT / "build/tomokv")
    a = p.parse_args()
    assert a.post.resolve() == ROOT / "build/tomokv", "builder uses the default POST objects"
    subprocess.run(["make", "-q", "all"], cwd=ROOT, check=True)
    pre, post = text_size(a.pre), text_size(a.post)
    delta = pre - post
    if delta <= 256:
        raise SystemExit(f"PAD B requires a candidate shrink exceeding a few hundred bytes; delta={delta}")
    out = ROOT / "build/perfex/pad-b"
    out.mkdir(parents=True, exist_ok=True)
    assembly = out / "padding.s"
    obj = out / "padding.o"
    binary = out / "tomokv"
    assembly.write_text('.section .text\n.globl tomo_perfex_pad_b\ntomo_perfex_pad_b:\n'
                        f'.space {delta},0x90\n.section .note.GNU-stack,"",@progbits\n')
    compile_cmd = ["cc", "-c", str(assembly), "-o", str(obj)]
    subprocess.run(compile_cmd, check=True)
    dry = subprocess.check_output(["make", "-n", "-W", "build/src/main.o", "all"], cwd=ROOT, text=True)
    links = [shlex.split(line) for line in dry.splitlines() if " -o build/tomokv " in line]
    assert len(links) == 1, "could not identify the ordinary Makefile link"
    link = links[0]
    at = link.index("-o")
    assert Path(link[at + 1]) == Path("build/tomokv")
    link[at + 1] = str(binary)
    link.insert(at, str(obj))
    subprocess.run(link, cwd=ROOT, check=True)
    assert text_size(binary) == pre, "padding failed to restore PRE text size"
    report = dict(kind="B", definition="candidate behavior plus padding restoring PRE .text size",
                  pre_text=pre, post_text=post, pad_text=text_size(binary), padding_bytes=delta,
                  binary=str(binary), sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                  compile=compile_cmd, link=link,
                  limitation="Controls total .text byte size, not every PRE body address/layout")
    (ROOT / "docs/perfex/pad-b.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("compile", "link")}))


if __name__ == "__main__":
    main()
