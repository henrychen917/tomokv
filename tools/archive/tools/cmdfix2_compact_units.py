#!/usr/bin/env python3
"""Compress only unit-binary debug sections; assert every loaded section is unchanged."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]


def loaded(path):
    elf = Elf(path)
    data = path.read_bytes()
    return {name: (s[1], s[2], s[3], s[5], hashlib.sha256(data[s[4]:s[4]+s[5]]).hexdigest()
                   if s[1] != 8 else None)
            for name, s in zip(elf.names, elf.sections) if s[2] & 2}


def compact(path):
    try: before = path.stat()
    except FileNotFoundError: return None
    if before.st_size < 20_000_000 or time.time() - before.st_mtime < 30:
        return None
    with path.open('rb') as f: header = f.read(18)
    if header[:4] != b'\x7fELF' or int.from_bytes(header[16:18], 'little') not in (1, 2, 3):
        return None
    temporary = path.with_name(path.name + '.cmdfix2-debug.tmp')
    sections = loaded(path)
    subprocess.run(['objcopy', '--compress-debug-sections=zlib', str(path), str(temporary)], check=True)
    assert loaded(temporary) == sections, path
    after = path.stat()
    if (before.st_ino, before.st_mtime_ns, before.st_size) != (after.st_ino, after.st_mtime_ns, after.st_size):
        temporary.unlink(); return None
    result = dict(path=str(path.relative_to(ROOT)), before_bytes=before.st_size,
                  after_bytes=temporary.stat().st_size, loaded_sections_identical=True,
                  sha256=hashlib.sha256(temporary.read_bytes()).hexdigest())
    os.utime(temporary, ns=(before.st_atime_ns, before.st_mtime_ns))
    temporary.replace(path)
    print(path.name, result['before_bytes'], result['after_bytes'], flush=True)
    return result


if __name__ == '__main__':
    assert os.sched_getaffinity(0) <= set(range(100, 112))
    output = ROOT / 'docs/cmdfix2/unit-debug-compression.json'
    rows = json.loads(output.read_text()) if output.exists() else []
    paths = [p for p in (ROOT/'build').rglob('*') if p.is_file() and not p.is_symlink()
             and p != ROOT/'build/tomokv' and not p.name.endswith('.tmp')
             and not p.relative_to(ROOT/'build').parts[0].startswith('gate-run.')
             and p.relative_to(ROOT/'build').parts[0] not in ('cmdfix2', 'src', 'db0', 'third_party')]
    prior = {r['path']: r for r in rows}
    paths = [p for p in paths if (str(p.relative_to(ROOT)) not in prior or
             p.stat().st_size != prior[str(p.relative_to(ROOT))]['after_bytes'] or
             hashlib.sha256(p.read_bytes()).hexdigest() != prior[str(p.relative_to(ROOT))]['sha256'])]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(compact, p) for p in paths]):
            result = future.result()
            if result:
                rows.append(result)
                output.write_text(json.dumps(rows, indent=2) + '\n')
    output.write_text(json.dumps(rows, indent=2) + '\n')
