#!/usr/bin/env python3
"""Run the stock literal inventory, admitting absence of its three retired hot names.

The full function union, section bytes and address/size tables are unchanged.
Absent historical names report null, never equality with a present body.
"""
import gzip
import inspect
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import rlfence_artifacts as stock
source=inspect.getsource(stock.identity)
needle='            symbol = inv[(name, 0)]'
assert source.count(needle)==1
source=source.replace(needle,'            if (name, 0) not in inv: return None\n'+needle)
scope=vars(stock).copy()
exec(source,scope)
out=ROOT/'build/clockcut/identity-linked'
scope['identity'](ROOT/'build/clockcut/pre/tomokv',ROOT/'build/tomokv',out)
for path in out.iterdir():
    if path.is_file():
        with gzip.open(ROOT/'docs/clockcut'/('linked-'+path.name+'.gz'),'wb') as f:
            f.write(path.read_bytes())
