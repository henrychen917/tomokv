#!/usr/bin/env python3
"""Repair comment-only R7 parity, rebuild, and prove the frozen runtime unchanged."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/eoffix'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def elf(path):
    data = path.read_bytes()
    header = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
    assert header[0][:6] == b'\x7fELF\x02\x01', 'requires ELF64 little endian'
    assert header[2] == 62 and header[9] == 56 and header[11] == 64
    program = [struct.unpack_from('<IIQQQQQQ', data, header[5] + i * 56)
               for i in range(header[10])]
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, header[6] + i * 64)
                for i in range(header[12])]
    strings = sections[header[13]]
    names = data[strings[4]:strings[4] + strings[5]]
    named = {names[s[0]:names.index(b'\0', s[0])].decode(): s for s in sections}
    return data, header, program, named


def runtime_identity(before, after):
    left, lh, lp, ls = elf(before)
    right, rh, rp, rs = elf(after)
    # The section table follows debug data, so its offset can move. Every other
    # ELF header field and all program headers must remain byte-for-byte equal.
    assert lh[:6] + lh[7:] == rh[:6] + rh[7:]
    assert lp == rp, 'program segment layout changed'
    allocated = {name for name, s in ls.items() if s[2] & 2}
    assert allocated == {name for name, s in rs.items() if s[2] & 2}
    rows = []
    ignored = [(40, 48, 'ELF section-table offset')]
    for name in sorted(allocated):
        a, b = ls[name], rs[name]
        assert a[1:] == b[1:], ('allocated section metadata changed', name)
        ad = b'' if a[1] == 8 else left[a[4]:a[4] + a[5]]
        bd = b'' if b[1] == 8 else right[b[4]:b[4] + b[5]]
        if name == '.note.gnu.build-id':
            namesz, descsz, kind = struct.unpack_from('<III', ad)
            start = 12 + ((namesz + 3) & ~3)
            assert kind == 3 and ad[12:12 + namesz] == b'GNU\0'
            assert ad[:start] == bd[:start] and ad[start + descsz:] == bd[start + descsz:]
            ignored.append((a[4] + start, a[4] + start + descsz, 'GNU build-id descriptor'))
        else:
            assert ad == bd, ('allocated section bytes changed', name)
        rows.append(dict(section=name, address=a[3], size=a[5],
                         before_sha256=digest(ad), after_sha256=digest(bd)))
    segments = []
    for p in lp:
        if p[0] != 1:
            continue
        offset, length = p[2], p[5]
        a = bytearray(left[offset:offset + length])
        b = bytearray(right[offset:offset + length])
        for start, end, _ in ignored:
            lo, hi = max(start, offset), min(end, offset + length)
            if lo < hi:
                a[lo - offset:hi - offset] = b'\0' * (hi - lo)
                b[lo - offset:hi - offset] = b'\0' * (hi - lo)
        assert a == b, ('PT_LOAD bytes changed', offset)
        segments.append(dict(offset=offset, bytes=length, normalized_sha256=digest(a)))
    return dict(equivalent=True, before=str(before.relative_to(ROOT)),
                after=str(after.relative_to(ROOT)), before_sha256=digest(left),
                after_sha256=digest(right), allocated_sections=rows,
                load_segments=segments, excluded_metadata=ignored,
                meaning='Identical instructions, allocated data, relocations, addresses and segment layout. '
                        'Only non-runtime debug metadata, GNU build-id and the section-table offset may differ.')


def identity_controls(binary):
    runtime_identity(binary, binary)
    _, _, _, sections = elf(binary)
    rows = []
    with tempfile.TemporaryDirectory(prefix='identity-control-', dir=ROOT/'build/eoffix') as temp:
        altered = Path(temp) / 'altered'
        shutil.copy2(binary, altered)
        for name in ('.text', '.rodata', '.data'):
            offset = sections[name][4]
            with altered.open('r+b') as stream:
                stream.seek(offset)
                original = stream.read(1)
                stream.seek(offset)
                stream.write(bytes([original[0] ^ 1]))
            try:
                runtime_identity(binary, altered)
            except AssertionError as error:
                assert error.args == (('allocated section bytes changed', name),), error
                rows.append(dict(section=name, rejected=True, reason=str(error)))
            else:
                raise AssertionError(('altered runtime was accepted', name))
            with altered.open('r+b') as stream:
                stream.seek(offset)
                stream.write(original)
    return rows


def main():
    assert os.sched_getaffinity(0) <= set(range(8))
    receipt = DOC / 'source-sync-identity.json'
    assert not receipt.exists()
    manifest = DOC / 'source-files-final.json'
    identity = json.loads(manifest.read_text())
    for row in identity['production_files']:
        assert digest((ROOT / row['path']).read_bytes()) == row['sha256']
    path = ROOT / 'src/core/reorder.cc'
    old = path.read_text()
    needle = '            const bool eof = res == 0 && !c->is_tls() && !c->closing();'
    comments = ('            // Rollback normally re-arms reception. EOF already released the\n'
                '            // original kernel pin; hold admission across that rollback.\n')
    assert old.count(needle) == 1
    shutil.copy2(manifest, DOC / 'source-files-final-before-comment-sync.json')
    subprocess.run(['python3', 'tests/r7shadow_sync.py', '--write'], cwd=ROOT, check=True)
    assert path.read_text() == old.replace(needle, comments + needle), 'change exceeds two comments'
    builds = []
    for index, row in enumerate(json.loads((DOC / 'complete-build.json').read_text())):
        started = time.monotonic()
        with (DOC / f'comment-sync-build-{index}.log').open('w') as log:
            code = subprocess.run(row['command'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT).returncode
        builds.append(dict(command=row['command'], exit_code=code, seconds=time.monotonic() - started))
        (DOC / 'comment-sync-build.json').write_text(json.dumps(builds, indent=2) + '\n')
        assert code == 0, ('comment synchronization build failed', index)
    arms = {row['arm']: row for row in json.loads((DOC / 'arms-final.json').read_text())}
    proof = runtime_identity(ROOT / arms['POST']['path'], ROOT / 'build/tomokv')
    assert proof['before_sha256'] == arms['POST']['sha256']
    proof['negative_controls'] = identity_controls(ROOT / arms['POST']['path'])
    refreshed = ROOT / 'build/eoffix/post-comment-sync/tomokv'
    refreshed.parent.mkdir(exist_ok=True)
    assert not refreshed.exists()
    shutil.copy2(ROOT / 'build/tomokv', refreshed)
    proof.update(source='src/core/reorder.cc', source_before_sha256=digest(old.encode()),
                 source_after_sha256=digest(path.read_bytes()), added_comments=comments.splitlines(),
                 rebuilt_copy=str(refreshed.relative_to(ROOT)))
    receipt.write_text(json.dumps(proof, indent=2) + '\n')
    for row in identity['production_files']:
        now = digest((ROOT / row['path']).read_bytes())
        if row['path'] != 'src/core/reorder.cc':
            assert now == row['sha256']
        row['sha256'] = now
    manifest.write_text(json.dumps(identity, indent=2) + '\n')
    print('Comment-only R7 parity repaired. Rebuilt production runtime equals the frozen POST.')


if __name__ == '__main__':
    main()
