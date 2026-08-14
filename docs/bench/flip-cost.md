# The cost of automatic tuning (flip convergence)

Auto cells boot balanced io4/ex4, zero warmup; convergence happens inside the 300 s measured window. Static-best ≈ auto at p1 within ~1%.

| pipe | mix | converge | overall ops/s | post-converge | cost |
|---|---|---|---|---|---|
| p1 | SET | 15 s | 782,957 | 783,522 | 0.1% |
| p1 | 9:1 mixed | 10 s | 793,981 | 794,143 | 0.0% |
| p32 | GET | 115 s | 8,220,006 | 8,550,790 | 3.9% |
| p32 | 9:1 mixed | 15 s | 8,032,964 | 8,121,854 | 1.1% |
| p32 | 1:1 mixed | 14 s | 6,053,005 | 6,125,079 | 1.2% |
