Model: equal-rate hot/cold SET cohorts; ratio = 100 * owners * (max(load)-min(load))/sum(load).
Three-band margin applies to total demand. Hot-only ratios are shown to expose the cold-cohort dilution.

1s: owners [0, 1, 2, 3, 4, 5, 6, 7], 64 shards; band 7.216114583%; 3 bands 21.648343748%.

| HOTMAX | Hot keys per owner | Hot-only % | Total % | Total / band | Recorded-rate % | Recorded-rate + seed-cold % | Improves with one shard |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 4 | 1,0,0,1,1,0,1,0 | 200.0000 | 100.0000 | 13.8579 | 99.9864 | 100.4881 | no |
| 8 | 1,0,0,2,3,0,1,1 | 300.0000 | 150.0000 | 20.7868 | 149.9796 | 150.2357 | yes |
| 16 | 5,1,1,2,3,1,1,2 | 200.0000 | 100.0000 | 13.8579 | 99.9864 | 100.3329 | yes |
| 32 | 8,4,3,5,5,2,2,3 | 150.0000 | 75.0000 | 10.3934 | 74.9898 | 75.0002 | yes |
| 64 | 12,10,8,9,8,5,7,5 | 87.5000 | 43.7500 | 6.0628 | 43.7441 | 43.8201 | yes |
| 128 | 20,21,15,14,16,12,17,13 | 56.2500 | 28.1250 | 3.8975 | 28.1212 | 28.1468 | yes |
| 256 | 35,32,36,29,31,28,37,28 | 28.1250 | 14.0625 | 1.9488 | 14.0606 | 14.2879 | yes |

Largest HOTMAX with >=3 bands: 128; recorded hot fraction 0.499932072.

2s: owners [4, 5, 6, 7], 32 shards; band 6.085137720%; 3 bands 18.255413159%.

| HOTMAX | Hot keys per owner | Hot-only % | Total % | Total / band | Recorded-rate % | Recorded-rate + seed-cold % | Improves with one shard |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 4 | 1,0,1,2 | 200.0000 | 100.0000 | 16.4335 | 99.5075 | 99.4709 | yes |
| 8 | 1,3,2,2 | 100.0000 | 50.0000 | 8.2167 | 49.7537 | 49.9616 | yes |
| 16 | 4,4,4,4 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.2231 | no |
| 32 | 10,6,6,10 | 50.0000 | 25.0000 | 4.1084 | 24.8769 | 24.8395 | no |
| 64 | 20,14,15,15 | 37.5000 | 18.7500 | 3.0813 | 18.6577 | 18.4466 | yes |
| 128 | 36,33,29,30 | 21.8750 | 10.9375 | 1.7974 | 10.8836 | 10.6577 | yes |
| 256 | 65,65,65,61 | 6.2500 | 3.1250 | 0.5135 | 3.1096 | 3.1583 | no |

Largest HOTMAX with >=3 bands: 64; recorded hot fraction 0.497537447.

Predeclare 2s HOTMAX=64. 1s HOTMAX=256 arms but does NOT retain the declared three-band margin once cold traffic is counted; the largest model-compliant 1s value is 128. No favourable round selection or automatic stimulus change.
