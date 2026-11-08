## readability-p2

Readability phase 2, merged onto origin/cpp 7595a6705a by calib/readability-integrate.py.

| Lane | Tip |
|---|---|
| readability-a7 | 9be4ac18d6 |
| readability-a8 | e89a4b2e2d |
| readability-a9 | b88b5ddee2 |
| readability-a10 | 8af5ba5782 |
| readability-p1fix | 3549d7c966 |

- Ownership: outside the R7 generated blocks, every changed src/ file equals its owner lane's version (calib/readability-partition.py).
- R7 envelopes: regenerated from the merged mainline methods; the tests/r7shadow_sync.py check passes.
- New src files (add them to calib/readability-partition.py before the next phase): src/core/placement_impl.h (readability-a7), src/store/flatstore_impl.h (readability-a8)
- Production binary, built with LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0, compared with the frozen release /home/user/Projects/bins/readability-pre-5c363128/tomokv:

```
IDENTICAL (11167504 bytes after stripping)
```
