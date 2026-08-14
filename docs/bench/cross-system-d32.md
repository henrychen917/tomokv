# Cross-system throughput — 32 B values (ops/s)

TomoKV auto (flip on) vs baselines; 8 GB, 300 s cells, flip cost included. **TomoKV leads all 24 cells.**

| pipe | mix | TomoKV | Redis | Dragonfly | ×Redis | ×Dfly | flip land | ipreq |
|---|---|---|---|---|---|---|---|---|
| p1 | GET | **795,896** | 178,890 | 744,734 | 4.45× | 1.07× | io7 | 29,129 |
| p1 | 9:1 mixed | **793,981** | 176,529 | 745,525 | 4.50× | 1.06× | io7 | 29,317 |
| p1 | 1:1 mixed | **787,272** | 169,366 | 751,194 | 4.65× | 1.05× | io7 | 30,155 |
| p1 | SET | **782,957** | 170,830 | 744,581 | 4.58× | 1.05× | io7 | 30,665 |
| p32 | GET | **8,220,006** | 1,899,445 | 4,468,021 | 4.33× | 1.84× | io5 | 5,830 |
| p32 | 9:1 mixed | **8,032,964** | 1,760,592 | 4,344,509 | 4.56× | 1.85× | io5 | 6,078 |
| p32 | 1:1 mixed | **6,053,005** | 1,516,794 | 4,150,234 | 3.99× | 1.46× | io5 | 7,644 |
| p32 | SET | **4,585,260** | 1,369,920 | 3,867,629 | 3.35× | 1.19× | io5 | 9,050 |

See [methodology](methodology.md).
