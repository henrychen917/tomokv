#!/usr/bin/env python3
"""Build a kind-A fingerprint control without executing a server.

The control restores PRE's boot-atomic classification in POST's exact ELF layout.
It is a PRE behaviour twin only for well-formed workloads: S4's empty-collection
guards stay enabled. Never use this measurement arm as the correctness candidate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from lbstall_artifacts import Elf


def twin(reference, candidate, output):
    old, new = Elf(reference), Elf(candidate)
    assert old.kind != 1 and new.kind != 1, 'expected linked ELF executables'
    assert Path(output).resolve() not in (Path(reference).resolve(), Path(candidate).resolve())
    symbols = [s for n, s in new.functions().items() if 'flip_fingerprint_note_sampled' in n]
    assert 1 <= len(symbols) <= 2, 'expected the namespaced and/or db0 fingerprint body'
    # PRE: mov cfg.atomic(%rcx),%ecx; test %ecx,%ecx; je ...
    boot_load = re.compile(rb'\x8b\x89(.{4})\x85\xc9\x74', re.S)
    # POST: mov atomic_activity(%rax),%rax; mov spec.flags(%r8),%edx; test %rax,%rax; js ...
    live_load = re.compile(rb'\x48\x8b\x80(.{4})\x41\x8b\x50\x10\x48\x85\xc0\x78', re.S)
    data = bytearray(new.data)
    patches = []
    for symbol in symbols:
        before = old.functions()[symbol['name']]
        boot, = boot_load.finditer(old.body(before))
        live, = live_load.finditer(new.body(symbol))
        # Read the boot uint32 into eax (zero extending rax), retain the spec.flags
        # load and test, and change js to jne. The one-byte NOP keeps every address.
        replacement = b'\x8b\x80' + boot.group(1) + b'\x90' + live.group()[7:-1] + b'\x75'
        assert len(replacement) == len(live.group()) == 15
        section = new.sections[symbol['sec']]
        at = section[4] + symbol['value'] - section[3] + live.start()
        assert data[at:at + len(replacement)] == live.group()
        data[at:at + len(replacement)] = replacement
        patches.append(dict(symbol=symbol['name'], offset=at, before=live.group().hex(),
                            after=replacement.hex(), boot_offset=int.from_bytes(boot.group(1), 'little'),
                            live_offset=int.from_bytes(live.group(1), 'little')))
    changed = [i for i, (a, b) in enumerate(zip(new.data, data)) if a != b]
    assert changed and all(any(p['offset'] <= i < p['offset'] + 15 for p in patches) for i in changed)
    Path(output).write_bytes(data)
    Path(output).chmod(Path(candidate).stat().st_mode)
    pad = Elf(output)
    assert pad.sections == new.sections and pad.symbols == new.symbols
    return dict(kind='A: behaviour twin', scope='well-formed benchmark data; S4 guards retained',
                control='PRE boot-atomic fingerprint classification in the exact POST text/layout',
                reference=str(reference), candidate=str(candidate), output=str(output),
                reference_sha256=hashlib.sha256(old.data).hexdigest(),
                candidate_sha256=hashlib.sha256(new.data).hexdigest(),
                output_sha256=hashlib.sha256(data).hexdigest(),
                bytes_changed=len(changed), all_other_bytes_equal=True, patches=patches)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference')
    parser.add_argument('candidate')
    parser.add_argument('output')
    args = parser.parse_args()
    print(json.dumps(twin(args.reference, args.candidate, args.output), indent=2))
