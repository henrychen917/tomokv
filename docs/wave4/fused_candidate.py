#!/usr/bin/python3
"""Supplemental gate boots in 1s, using the same POST.

The existing gate jobs default to split. This launcher changes only that boot
geometry for their supplemental mode proof; batteries and assertions are intact.
"""
import os
from pathlib import Path
import sys

args=[]
index=1
while index<len(sys.argv):
    arg=sys.argv[index]
    if arg in ('--ratio','--thread-mode','--read-local'):
        index+=2
        continue
    if any(arg.startswith(key+'=') for key in ('--ratio','--thread-mode','--read-local')):
        index+=1
        continue
    args.append(arg)
    index+=1
binary=Path(__file__).resolve().parents[2]/'build/tomokv'
read_local=os.environ.get('WAVE4_READ_LOCAL','1')
if read_local not in ('0','1'):
    raise SystemExit('WAVE4_READ_LOCAL must be 0 or 1')
os.execv(binary,[str(binary),*args,'--thread-mode','1s','--read-local',read_local])
