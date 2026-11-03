# Final production-linked command counts

PRE is 9d6ab5526; POST is the bcbe1650fd production source. Finite serverless
owner/scatter command scopes, not network throughput or end-to-end parse counts.
The same fixture and single-step counter exclude library and fixture callees.
Both production namespaces are linked with production COMDAT precedence.
All 80 cells add zero instructions (delta <= 0); these are not a rate claim.

| Namespace | Command | Mode | Batch | Atomic | PRE instructions | POST instructions | Delta |
|---|---|---|---:|---:|---:|---:|---:|
| normal | GET | 1s | 1 | 0 | 936 | 936 | +0 |
| normal | GET | 1s | 1 | 1 | 936 | 936 | +0 |
| normal | GET | 1s | 32 | 0 | 18482 | 18482 | +0 |
| normal | GET | 1s | 32 | 1 | 18482 | 18482 | +0 |
| normal | GET | 2s | 1 | 0 | 1556 | 1556 | +0 |
| normal | GET | 2s | 1 | 1 | 1556 | 1556 | +0 |
| normal | GET | 2s | 32 | 0 | 18327 | 18327 | +0 |
| normal | GET | 2s | 32 | 1 | 18327 | 18327 | +0 |
| normal | SET | 1s | 1 | 0 | 1027 | 1027 | +0 |
| normal | SET | 1s | 1 | 1 | 1027 | 1027 | +0 |
| normal | SET | 1s | 32 | 0 | 21394 | 21394 | +0 |
| normal | SET | 1s | 32 | 1 | 21394 | 21394 | +0 |
| normal | SET | 2s | 1 | 0 | 1647 | 1647 | +0 |
| normal | SET | 2s | 1 | 1 | 1647 | 1647 | +0 |
| normal | SET | 2s | 32 | 0 | 21239 | 21239 | +0 |
| normal | SET | 2s | 32 | 1 | 21239 | 21239 | +0 |
| normal | INCR | 1s | 1 | 0 | 1484 | 1484 | +0 |
| normal | INCR | 1s | 1 | 1 | 1484 | 1484 | +0 |
| normal | INCR | 1s | 32 | 0 | 36547 | 36547 | +0 |
| normal | INCR | 1s | 32 | 1 | 36547 | 36547 | +0 |
| normal | INCR | 2s | 1 | 0 | 2104 | 2104 | +0 |
| normal | INCR | 2s | 1 | 1 | 2104 | 2104 | +0 |
| normal | INCR | 2s | 32 | 0 | 36392 | 36392 | +0 |
| normal | INCR | 2s | 32 | 1 | 36392 | 36392 | +0 |
| normal | MGET | 1s | 1 | 0 | 10105 | 10104 | -1 |
| normal | MGET | 1s | 1 | 1 | 10125 | 10124 | -1 |
| normal | MGET | 1s | 32 | 0 | 322182 | 322150 | -32 |
| normal | MGET | 1s | 32 | 1 | 322822 | 322790 | -32 |
| normal | MGET | 2s | 1 | 0 | 10105 | 10104 | -1 |
| normal | MGET | 2s | 1 | 1 | 10125 | 10124 | -1 |
| normal | MGET | 2s | 32 | 0 | 322182 | 322150 | -32 |
| normal | MGET | 2s | 32 | 1 | 322822 | 322790 | -32 |
| normal | MSET | 1s | 1 | 0 | 10561 | 10560 | -1 |
| normal | MSET | 1s | 1 | 1 | 16916 | 16916 | +0 |
| normal | MSET | 1s | 32 | 0 | 337797 | 337765 | -32 |
| normal | MSET | 1s | 32 | 1 | 959774 | 959774 | +0 |
| normal | MSET | 2s | 1 | 0 | 10379 | 10378 | -1 |
| normal | MSET | 2s | 1 | 1 | 16584 | 16584 | +0 |
| normal | MSET | 2s | 32 | 0 | 331973 | 331941 | -32 |
| normal | MSET | 2s | 32 | 1 | 949150 | 949150 | +0 |
| db0 | GET | 1s | 1 | 0 | 783 | 783 | +0 |
| db0 | GET | 1s | 1 | 1 | 783 | 783 | +0 |
| db0 | GET | 1s | 32 | 0 | 17585 | 17585 | +0 |
| db0 | GET | 1s | 32 | 1 | 17585 | 17585 | +0 |
| db0 | GET | 2s | 1 | 0 | 1016 | 1016 | +0 |
| db0 | GET | 2s | 1 | 1 | 1016 | 1016 | +0 |
| db0 | GET | 2s | 32 | 0 | 17043 | 17043 | +0 |
| db0 | GET | 2s | 32 | 1 | 17043 | 17043 | +0 |
| db0 | SET | 1s | 1 | 0 | 894 | 894 | +0 |
| db0 | SET | 1s | 1 | 1 | 894 | 894 | +0 |
| db0 | SET | 1s | 32 | 0 | 21137 | 21137 | +0 |
| db0 | SET | 1s | 32 | 1 | 21137 | 21137 | +0 |
| db0 | SET | 2s | 1 | 0 | 1127 | 1127 | +0 |
| db0 | SET | 2s | 1 | 1 | 1127 | 1127 | +0 |
| db0 | SET | 2s | 32 | 0 | 20595 | 20595 | +0 |
| db0 | SET | 2s | 32 | 1 | 20595 | 20595 | +0 |
| db0 | INCR | 1s | 1 | 0 | 1244 | 1244 | +0 |
| db0 | INCR | 1s | 1 | 1 | 1244 | 1244 | +0 |
| db0 | INCR | 1s | 32 | 0 | 32866 | 32866 | +0 |
| db0 | INCR | 1s | 32 | 1 | 32866 | 32866 | +0 |
| db0 | INCR | 2s | 1 | 0 | 1477 | 1477 | +0 |
| db0 | INCR | 2s | 1 | 1 | 1477 | 1477 | +0 |
| db0 | INCR | 2s | 32 | 0 | 32324 | 32324 | +0 |
| db0 | INCR | 2s | 32 | 1 | 32324 | 32324 | +0 |
| db0 | MGET | 1s | 1 | 0 | 9977 | 9968 | -9 |
| db0 | MGET | 1s | 1 | 1 | 9995 | 9985 | -10 |
| db0 | MGET | 1s | 32 | 0 | 318086 | 317860 | -226 |
| db0 | MGET | 1s | 32 | 1 | 318662 | 318404 | -258 |
| db0 | MGET | 2s | 1 | 0 | 9977 | 9968 | -9 |
| db0 | MGET | 2s | 1 | 1 | 9995 | 9985 | -10 |
| db0 | MGET | 2s | 32 | 0 | 318086 | 317860 | -226 |
| db0 | MGET | 2s | 32 | 1 | 318662 | 318404 | -258 |
| db0 | MSET | 1s | 1 | 0 | 10680 | 10668 | -12 |
| db0 | MSET | 1s | 1 | 1 | 16301 | 16184 | -117 |
| db0 | MSET | 1s | 32 | 0 | 341605 | 341221 | -384 |
| db0 | MSET | 1s | 32 | 1 | 895454 | 891710 | -3744 |
| db0 | MSET | 2s | 1 | 0 | 10490 | 10478 | -12 |
| db0 | MSET | 2s | 1 | 1 | 15955 | 15838 | -117 |
| db0 | MSET | 2s | 32 | 0 | 335525 | 335141 | -384 |
| db0 | MSET | 2s | 32 | 1 | 884382 | 880638 | -3744 |

Final production source bcbe1650fd; POST d443b95831da51c41d8095a529d4e1d3db8ec3fd7dd802c1a3ef34926c47fd21.
All 80 deltas are non-positive (maximum 0, minimum -3744). No rate claim.
