## readability-p1

Readability phase 1, merged onto origin/cpp 9a09e59190 by calib/readability-integrate.py.

| Lane | Tip |
|---|---|
| readability-a3 | 3c2e795981 |
| readability-a4 | a15c32d5b1 |
| readability-a5 | ccb8ecd796 |
| readability-a6 | e46d03dc07 |

- Ownership: outside the R7 generated blocks, every changed src/ file equals its owner lane's version (calib/readability-partition.py).
- R7 envelopes: regenerated from the merged mainline methods; the tests/r7shadow_sync.py check passes.
- New src files (add them to calib/readability-partition.py before the next phase): none
- Production binary, built with LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0, compared with the frozen release /home/user/Projects/bins/readability-pre-5c363128/tomokv:

```
IDENTICAL (11167504 bytes after stripping)
```
