# Multi-key — MGET/MSET, 8 keys per command (commands/s)

TomoKV wins unpipelined multi-key (+10–21%); Dragonfly's batched executor wins pipelined multi-key (~13%) — a marked optimization target. MGET-8 at p1 = 5.6× the per-key rate of single GET (implicit pipelining).

| pipe | mix | TomoKV | Dragonfly | Redis | ×Dfly |
|---|---|---|---|---|---|
| p1 | GET | **548,947** | 497,732 | 143,018 | 1.10× |
| p1 | SET | **537,099** | 443,821 | 117,083 | 1.21× |
| p1 | 9:1 mixed | **529,292** | 484,653 | 137,921 | 1.09× |
| p1 | 1:1 mixed | **545,986** | 456,121 | 127,615 | 1.20× |
| p32 | GET | **708,812** | 811,690 | 389,090 | 0.87× |
| p32 | SET | **560,006** | 635,599 | 279,048 | 0.88× |
| p32 | 9:1 mixed | **689,717** | 780,475 | 361,060 | 0.88× |
| p32 | 1:1 mixed | **668,959** | 681,473 | 301,340 | 0.98× |
