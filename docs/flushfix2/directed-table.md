# Directed FLUSH proof

Each row aggregates eight target legs; JSON receipts retain every leg and fresh-state attempt. Counts are correctness observations, not throughput measurements.

| Case | Command | Option | DBs | PRE tears / observations | POST tears / observations | POST fired legs |
|---|---|---|---:|---:|---:|---:|
| flush-only | FLUSHALL | SYNC | 1 | 17779 / 817541 | 0 / 1225095 | 8 |
| flush-only | FLUSHALL | SYNC | 16 | 29500 / 1314509 | 0 / 1203214 | 8 |
| flush-pair | FLUSHALL | SYNC | 1 | 64768 / 1590677 | 0 / 1650528 | 8 |
| flush-pair | FLUSHALL | SYNC | 16 | 51816 / 1491420 | 0 / 1637233 | 8 |
| flush-script | FLUSHALL | SYNC | 1 | 3743 / 1560979 | 0 / 1695663 | 8 |
| flush-script | FLUSHALL | SYNC | 16 | 10184 / 1594709 | 0 / 1679174 | 8 |
| namespace | FLUSHALL | ASYNC | 1 | 3000 / 1178710 | 0 / 1261319 | 8 |
| namespace | FLUSHALL | ASYNC | 16 | 100245 / 859253 | 0 / 1232560 | 8 |
| namespace | FLUSHALL | SYNC | 1 | 9251 / 1050257 | 0 / 1306837 | 8 |
| namespace | FLUSHALL | SYNC | 16 | 43736 / 588382 | 0 / 1162583 | 8 |
| namespace | FLUSHDB | ASYNC | 1 | 36973 / 1149730 | 0 / 1211797 | 8 |
| namespace | FLUSHDB | ASYNC | 16 | 26859 / 880847 | 0 / 911738 | 8 |
| namespace | FLUSHDB | SYNC | 1 | 4516 / 1156103 | 0 / 1334840 | 8 |
| namespace | FLUSHDB | SYNC | 16 | 35935 / 795666 | 0 / 753801 | 8 |
