#!/usr/bin/env python3
"""Build/run only serverless cron units, including two failing mechanism controls."""
from pathlib import Path
import resource
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/infofields/units'
OUT.mkdir(parents=True, exist_ok=True)
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
source = (ROOT / 'src/cmd/info_stats.cc').read_text()
source = source.replace('#include "info_stats.h"', '#include "src/cmd/info_stats.h"')
source = source.replace('#include "../core/server.h"', '#include "src/core/server.h"')
test = (ROOT / 'tests/infofields_unit.cc').read_text().replace('#include "../src/cmd/info_stats.cc"', '')
controls = {
    'production': source,
    'eight-slots': source.replace('kSampleWindow = 16;', 'kSampleWindow = 8;'),
    'no-cron-peak': source.replace('    g_info_stats.memory_peak = std::max(g_info_stats.memory_peak, memory);', '', 1),
}
assert len(set(controls.values())) == len(controls)
for label, implementation in controls.items():
    unit = OUT / (label + '.cc')
    binary = OUT / label
    unit.write_text(implementation + '\n' + test)
    subprocess.run(['taskset', '-c', '0-15', 'g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra',
                    '-pthread', '-ffunction-sections', '-fdata-sections', '-I.', str(unit),
                    '-Wl,--gc-sections', '-o', str(binary)], cwd=ROOT, check=True)
    result = subprocess.run([str(binary)], cwd=ROOT, text=True, capture_output=True)
    assert (result.returncode == 0) == (label == 'production'), (label, result.returncode, result.stderr)
    print(label, 'PASS' if result.returncode == 0 else 'REJECTED', 'exit', result.returncode, flush=True)
