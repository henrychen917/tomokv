# IO↔EX static split sweep — 32 B (ops/s, bold = best split)

p1 wants IO threads (io7 best, monotonic); p32 GET peaks io5; p32 SET peaks io4 (writes need EX capacity for QSBR reclamation). The auto controller lands io7 @ p1 and io5 @ p32; the io4-for-pure-SET gap (+31% vs io5 static) is a flagged tuning target.

| pipe | op | io1/ex7 | io2/ex6 | io3/ex5 | io4/ex4 | io5/ex3 | io6/ex2 | io7/ex1 |
|---|---|---|---|---|---|---|---|---|
| p1 | GET | 0.18M | 0.32M | 0.46M | 0.60M | 0.71M | 0.79M | **0.80M** |
| p1 | SET | 0.17M | 0.33M | 0.46M | 0.59M | 0.70M | **0.78M** | 0.77M |
| p32 | GET | 2.41M | 4.44M | 6.36M | 7.98M | **8.70M** | 6.70M | 2.37M |
| p32 | SET | 2.19M | 4.11M | 5.78M | **6.18M** | 4.72M | 3.20M | 1.22M |
