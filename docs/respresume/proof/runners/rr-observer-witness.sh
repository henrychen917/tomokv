#!/bin/bash
# Lane respresume (build/ only): fragment corpus against the POST observer, then its counters.
cd /home/user/Projects/cx-respresume/tests
python3 respresume.py fragment 127.0.0.1 25420 --oracle-port 25421 | tail -1
/home/user/Projects/redis74/src/redis-cli -p 25420 INFO stats | grep -E '^(perfio|rr)_'
