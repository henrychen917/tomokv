#!/usr/bin/python3
"""Throwaway shim mutants, used only through the real gate job's compiler call."""
import os
import subprocess
import sys
source=sys.stdin.buffer.read()
assert b'TOMO_NTNEW4_CLOCK' in source, 'this wrapper accepts only the clock shim'
control=os.environ['CLOCKCUT_SHIM_CONTROL']
if control=='no-freeze':
    # Both wall-clock reads (clock_gettime and gettimeofday) lose the frozen value.
    needle=b'__atomic_load_n(&page->frozen_ms, __ATOMIC_ACQUIRE)'
    assert source.count(needle)==2
    source=source.replace(needle,b'0')
elif control=='no-stall':
    needle=b'if (gen > consumed &&'
    assert source.count(needle)==1
    source=source.replace(needle,b'if (0 && gen > consumed &&')
else: raise ValueError(control)
sys.exit(subprocess.run(['/usr/bin/cc',*sys.argv[1:]],input=source).returncode)
