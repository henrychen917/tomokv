#!/bin/bash
# Lane respresume (build/ only): witnesses run against an already booted server on 25420.
cd /home/user/Projects/cx-respresume/tests
python3 respresume.py fragment 127.0.0.1 25420 --oracle-port 25421 | tail -1
python3 respresume.py cpu 127.0.0.1 25420 --pid "$RR_TOMO_PID" --cpu-limit 999 | tail -1
python3 respresume.py neighbour 127.0.0.1 25420 --median-ms 999 | tail -1
