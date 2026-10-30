#!/usr/bin/env python3
"""Archive completed driver/trace logs with hashes before deleting loose copies."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

DOC = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    assert (DOC / 'jobs/differ-epoll.json').exists(), 'correctness campaigns still running'
    progress = json.loads((DOC / 'readonly-status.json').read_text())
    assert progress == [dict(arm=arm, exit=0) for arm in ('pre', 'c4', 'post')]
    for stem, paths in (('scope', list((DOC / 'scopes').glob('*.log'))),
                        ('development', [*DOC.glob('*.log'), *DOC.glob('jobs/*.log')])):
        target = DOC / (stem + '-logs.tar.gz')
        index_path = DOC / (stem + '-log-index.json')
        index = json.loads(index_path.read_text())
        assert sha(target.read_bytes()) == index['archive_sha256']
        files = {}
        with tarfile.open(target, 'r:gz') as archive:
            for row in index['files']:
                data = archive.extractfile(row['path']).read()
                assert sha(data) == row['sha256']
                files[row['path']] = data
        for path in paths:
            name = str(path.relative_to(DOC))
            data = path.read_bytes()
            assert name not in files or files[name] == data, ('changed archived log', name)
            files[name] = data
        temporary = target.with_suffix('.tmp')
        with temporary.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode='w|') as archive:
                for name, data in sorted(files.items()):
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    info.mode = 0o644
                    archive.addfile(info, io.BytesIO(data))
        temporary.replace(target)
        index = dict(files=[dict(path=name, bytes=len(data), sha256=sha(data))
                            for name, data in sorted(files.items())],
                     archive_sha256=sha(target.read_bytes()))
        index_path.write_text(json.dumps(index, indent=2) + '\n')
        for path in paths:
            assert files[str(path.relative_to(DOC))] == path.read_bytes()
            path.unlink()
        print(stem, len(files), 'archived logs;', len(paths), 'loose copies removed')


if __name__ == '__main__':
    main()
