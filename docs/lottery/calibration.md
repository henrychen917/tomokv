| Row | Name | Witness | Verdict | Attempts | Hits | Hit rate | s/attempt | Attempts for K=20 | Minutes for K=20 | K within 10 min? |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 122 | idle loop ceiling (LBSIGNALS, 1s) | W10.idle | PASS | 20 | 20 | 100% | 1.2 | 20 | 0.4 | yes |
| 126 | atomic torn/window battery | W2.fanout | INSUFFICIENT | 4 | 4 | 100% | 37.7 | 20 | 12.6 | NO (attempt length) |
| 128 | atomic owner-local hazard battery | W2.pin_flush, W2.ryow | PASS | 20 | 20 | 100% | 5.6 | 20 | 1.9 | yes |
| 130 | s6 battery (atomic 0) | W3 | INSUFFICIENT | 15 | 15 | 100% | 8.2 | 20 | 2.7 | yes |
| 131 | multi_exec battery (atomic 0) | W16 | PASS | 20 | 20 | 100% | 2.5 | 20 | 0.8 | yes |
| 132 | blocking battery (atomic 0) | W1, W5.timeout | PASS | 20 | 20 | 100% | 1.7 | 20 | 0.6 | yes |
| 139 | limits battery (atomic 0) | W5.idle, W5.soft, W5.exempt | INSUFFICIENT | 8 | 8 | 100% | 15.2 | 20 | 5.1 | yes |
| 149 | servertail battery (atomic 0) | W1 | PASS | 20 | 20 | 100% | 2.8 | 20 | 0.9 | yes |
| 159 | expwide battery (atomic 0) | W4 | INSUFFICIENT | 2 | 0 | 0 (95% < 78%) | 67.8 | - | - | NO (rate; limiting W4) - W4 held command expiry cut |
| 164 | s6 battery (atomic 1) | W3 | PASS | 20 | 20 | 100% | 5.5 | 20 | 1.8 | yes |
| 165 | multi_exec battery (atomic 1) | W16 | PASS | 20 | 20 | 100% | 2.6 | 20 | 0.9 | yes |
| 166 | blocking battery (atomic 1) | W1, W5.timeout | PASS | 20 | 20 | 100% | 1.7 | 20 | 0.6 | yes |
| 173 | limits battery (atomic 1) | W5.idle, W5.soft, W5.exempt | INSUFFICIENT | 8 | 8 | 100% | 15.1 | 20 | 5.0 | yes |
| 183 | servertail battery (atomic 1) | W1 | PASS | 20 | 20 | 100% | 3.2 | 20 | 1.1 | yes |
| 193 | expwide battery (atomic 1) | W4 | INSUFFICIENT | 3 | 0 | 0 (95% < 63%) | 53.7 | - | - | NO (rate; limiting W4) - W4 held command expiry cut |
| 199 | fused s6 battery (atomic 0) | W3 | INSUFFICIENT | 17 | 17 | 100% | 7.2 | 20 | 2.4 | yes |
| 200 | fused multi_exec battery (atomic 0) | W16 | PASS | 21 | 20 | 95% | 2.9 | 21 | 1.0 | yes |
| 203 | fused spinprobe battery (atomic 0) | W10 | PASS | 20 | 20 | 100% | 2.5 | 20 | 0.8 | yes |
| 206 | fused s6 battery (atomic 1) | W3 | PASS | 20 | 20 | 100% | 6.0 | 20 | 2.0 | yes |
| 207 | fused multi_exec battery (atomic 1) | W16 | PASS | 21 | 20 | 95% | 2.6 | 21 | 0.9 | yes |
| 210 | fused spinprobe battery (atomic 1) | W10 | PASS | 20 | 20 | 100% | 2.4 | 20 | 0.8 | yes |
| 213 | fused+armed s6 battery (atomic 0) | W3 | PASS | 20 | 20 | 100% | 2.1 | 20 | 0.7 | yes |
| 214 | fused+armed multi_exec battery (atomic 0) | W16 | PASS | 20 | 20 | 100% | 2.4 | 20 | 0.8 | yes |
| 215 | fused+armed blocking battery (atomic 0) | W1, W5.timeout | PASS | 20 | 20 | 100% | 1.6 | 20 | 0.5 | yes |
| 222 | fused+armed limits battery (atomic 0) | W5.idle, W5.soft, W5.exempt | INSUFFICIENT | 8 | 8 | 100% | 15.0 | 20 | 5.0 | yes |
| 232 | fused+armed servertail battery (atomic 0) | W1 | PASS | 21 | 20 | 95% | 2.7 | 21 | 1.0 | yes |
| 242 | fused+armed expwide battery (atomic 0) | W4 | INSUFFICIENT | 3 | 0 | 0 (95% < 63%) | 43.2 | - | - | NO (rate; limiting W4) - W4 held command expiry cut |
| 248 | fused+armed s6 battery (atomic 1) | W3 | INSUFFICIENT | 10 | 10 | 100% | 12.0 | 20 | 4.0 | yes |
| 249 | fused+armed multi_exec battery (atomic 1) | W16 | PASS | 21 | 20 | 95% | 2.8 | 21 | 1.0 | yes |
| 250 | fused+armed blocking battery (atomic 1) | W1, W5.timeout | PASS | 20 | 20 | 100% | 1.8 | 20 | 0.6 | yes |
| 257 | fused+armed limits battery (atomic 1) | W5.idle, W5.soft, W5.exempt | INSUFFICIENT | 8 | 8 | 100% | 15.0 | 20 | 5.0 | yes |
| 267 | fused+armed servertail battery (atomic 1) | W1 | PASS | 21 | 20 | 95% | 3.1 | 21 | 1.1 | yes |
| 277 | fused+armed expwide battery (atomic 1) | W4 | INSUFFICIENT | 3 | 0 | 0 (95% < 63%) | 44.4 | - | - | NO (rate; limiting W4) - W4 held command expiry cut |
| 300 | slowlog battery (atomic 0) | W1 | PASS | 20 | 20 | 100% | 1.8 | 20 | 0.6 | yes |
| 303 | execatomic battery (atomic 0) | W2.fanout | INSUFFICIENT | 6 | 6 | 100% | 22.3 | 20 | 7.4 | yes |
| 304 | execiso battery (atomic 0) | W2.fanout | INSUFFICIENT | 8 | 8 | 100% | 16.5 | 20 | 5.5 | yes |
| 310 | xmove battery (atomic 0) | W6.left, W6.right | FAIL | 6 | 5 | 83% | 1.7 | 24 | 0.7 | yes |
| 314 | slowlog battery (atomic 1) | W1 | PASS | 20 | 20 | 100% | 2.1 | 20 | 0.7 | yes |
| 317 | execatomic battery (atomic 1) | W2.fanout | INSUFFICIENT | 6 | 6 | 100% | 20.4 | 20 | 6.8 | yes |
| 318 | execiso battery (atomic 1) | W2.fanout | INSUFFICIENT | 9 | 9 | 100% | 14.0 | 20 | 4.7 | yes |
| 324 | xmove battery (atomic 1) | W6.left, W6.right | INSUFFICIENT | 102 | 0 | 0 (95% < 3%) | 1.2 | - | - | NO (rate; limiting W6.left) - W6 LMOVE phase-one hold |
| 339 | DEBUG toggle/reload battery | W7.progress, W7.cancel | PASS | 20 | 20 | 100% | 1.7 | 20 | 0.6 | yes |
| 341 | snapshot concurrent cut (epoll) | W8 | PASS | 20 | 20 | 100% | 3.6 | 20 | 1.2 | yes |
| 342 | snapshot cut reload (epoll) | W8 | PASS | 20 | 20 | 100% | 2.4 | 20 | 0.8 | yes |
| 343 | snapshot never tears a cross-shard MSET group (epoll, atomic 1) | W9 | INSUFFICIENT | 18 | 18 | 100% | 7.0 | 20 | 2.3 | yes |
| 344 | snapshot never tears a MULTI/EXEC group (epoll, default atomic 0) | W9 | INSUFFICIENT | 13 | 11 | 85% | 9.4 | 24 | 3.7 | yes |
| 349 | snapshot concurrent cut (uring) | W8 | PASS | 20 | 20 | 100% | 2.3 | 20 | 0.8 | yes |
| 350 | snapshot cut reload (uring) | W8 | PASS | 20 | 20 | 100% | 1.5 | 20 | 0.5 | yes |
| 351 | snapshot never tears a cross-shard MSET group (uring, atomic 1) | W9 | INSUFFICIENT | 17 | 17 | 100% | 7.1 | 20 | 2.4 | yes |
| 352 | snapshot never tears a MULTI/EXEC group (uring, default atomic 0) | W9 | INSUFFICIENT | 13 | 10 | 77% | 9.3 | 26 | 4.0 | yes |
| 357 | MULTI feature battery | W16 | PASS | 21 | 20 | 95% | 2.7 | 21 | 0.9 | yes |
| 358 | blocking feature battery | W1, W5.timeout | PASS | 20 | 20 | 100% | 1.8 | 20 | 0.6 | yes |
| 366 | partial-frame conn parks (no io spin) | W10 | PASS | 20 | 20 | 100% | 2.4 | 20 | 0.8 | yes |
| 368 | FLIP applies under saturated load | W11 | INSUFFICIENT | 20 | 18 | 90% | 6.3 | 23 | 2.4 | yes |
| 443 | TLS pipeline/torn-record/coexistence battery | W12.handshake, W12.record, W12.parser | INSUFFICIENT | 8 | 0 | 0 (95% < 31%) | 16.2 | - | - | NO (rate; limiting W12.handshake) - W12 per-connection TLS stage hold |
| 503 | atomic torn/window under ASAN | W2.fanout | INSUFFICIENT | 4 | 4 | 100% | 34.9 | 20 | 11.6 | NO (attempt length) |
| 515 | Redis 7.4 differential matrix | W3, W13, W14, W15 | INSUFFICIENT | 1 | 1 | 100% | 846.2 | 20 | 282.1 | NO (attempt length) |
| 516 | Redis 7.4 differential matrix (armed fused + read-local) | W3, W13, W14, W15 | INSUFFICIENT | 1 | 1 | 100% | 786.2 | 20 | 262.1 | NO (attempt length) |
