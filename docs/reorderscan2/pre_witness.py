from pathlib import Path
import shutil
import subprocess
root = Path.cwd()
out = root / 'build/reorderscan2-evidence/pre-witness'
source = out / 'source'
shutil.copytree(root / 'build/reorderscan-pre2-source/src', source / 'src', dirs_exist_ok=True)
header = source / 'src/core/reorder.h'
s = header.read_text()
needle = 'explicit ShadowDispatch(Client& client, uint64_t before = UINT64_MAX) {\n        TOMO_R7_PATH();'
assert s.count(needle) == 1
s = s.replace(needle, needle + '\n        TOMO_R7_SCAN_CONSTRUCT();')
needle = 'for (uint64_t end = std::min(before, rob.dispatch_id()); end > first;) {'
assert s.count(needle) == 1
s = s.replace(needle, needle + '\n            TOMO_R7_SCAN_VISIT();')
header.write_text(s)
flags = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native', '-pthread',
         '-DTOMO_JEMALLOC', '-include', 'tests/reorderscan_witness.h', '-I' + str(source), '-I.']
objects = sorted((root / 'build/reorderscan-pre2/src').rglob('*.o'))
objects = [str(p) for p in objects if p.name not in ('main.o', 'reorder.o')]
with (out / 'build.log').open('w') as log:
    subprocess.run(flags + ['-c', str(source / 'src/core/reorder.cc'), '-o', str(out / 'reorder.o')], stdout=log, stderr=subprocess.STDOUT, check=True)
    subprocess.run(flags + ['tests/reorderscan_paths.cc', str(out / 'reorder.o')] + objects + ['-o', str(out / 'paths'), '-ljemalloc', '-luring', '-lssl', '-lcrypto', '-lm'], stdout=log, stderr=subprocess.STDOUT, check=True)
for arm, expected in [('pre', 0), ('post', 1)]:
    result = subprocess.run([str(out / 'paths'), arm], text=True, capture_output=True)
    (out / (arm + '.log')).write_text(result.stdout + result.stderr)
    assert result.returncode == expected, result
    if arm == 'post':
        assert 'RO2 no-Long production construction count' in result.stderr
    print('PASS PRE2 production witness expected=' + arm, flush=True)
