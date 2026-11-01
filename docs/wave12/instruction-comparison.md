# Command-scope instruction census

Serverless production command activation and completion. Native namespace instructions; Lua companion includes executable VM instructions. Fixture, shared-library bodies, network, io_uring syscalls and idle scheduler work are outside this census. No rates, cycles/op or IPC were measured.

Counts are instructions per complete activation (batch columns are totals).

| Namespace | Command | Mode | Batch/children | Atomic | PRE | POST | Delta |
|---|---|---|---:|---:|---:|---:|---:|
| normal | EVAL-single | 1s | 1 | 0 | 8914 | 8915 | 1 |
| normal | EVAL-single | 1s | 1 | 1 | 8914 | 8915 | 1 |
| normal | EVAL-single | 2s | 1 | 0 | 9453 | 9454 | 1 |
| normal | EVAL-single | 2s | 1 | 1 | 9453 | 9454 | 1 |
| normal | EVAL-single-header | 1s | 1 | 0 | 6341 | 6342 | 1 |
| normal | EVAL-single-header | 1s | 1 | 1 | 6341 | 6342 | 1 |
| normal | EVAL-single-header | 2s | 1 | 0 | 6880 | 6881 | 1 |
| normal | EVAL-single-header | 2s | 1 | 1 | 6880 | 6881 | 1 |
| normal | EVAL-cross | 1s | 1 | 0 | 35148 | 35173 | 25 |
| normal | EVAL-cross | 1s | 1 | 1 | 35146 | 35171 | 25 |
| normal | EVAL-cross | 2s | 1 | 0 | 35167 | 35187 | 20 |
| normal | EVAL-cross | 2s | 1 | 1 | 35165 | 35185 | 20 |
| normal | EVAL-cross-header | 1s | 1 | 0 | 24148 | 24158 | 10 |
| normal | EVAL-cross-header | 1s | 1 | 1 | 24146 | 24156 | 10 |
| normal | EVAL-cross-header | 2s | 1 | 0 | 24175 | 24180 | 5 |
| normal | EVAL-cross-header | 2s | 1 | 1 | 24173 | 24178 | 5 |
| normal | EVALSHA-single | 1s | 1 | 0 | 8765 | 8766 | 1 |
| normal | EVALSHA-single | 1s | 1 | 1 | 8765 | 8766 | 1 |
| normal | EVALSHA-single | 2s | 1 | 0 | 9304 | 9305 | 1 |
| normal | EVALSHA-single | 2s | 1 | 1 | 9304 | 9305 | 1 |
| normal | EVALSHA-single-header | 1s | 1 | 0 | 6192 | 6193 | 1 |
| normal | EVALSHA-single-header | 1s | 1 | 1 | 6192 | 6193 | 1 |
| normal | EVALSHA-single-header | 2s | 1 | 0 | 6731 | 6732 | 1 |
| normal | EVALSHA-single-header | 2s | 1 | 1 | 6731 | 6732 | 1 |
| normal | EVALSHA-cross | 1s | 1 | 0 | 35063 | 35088 | 25 |
| normal | EVALSHA-cross | 1s | 1 | 1 | 35061 | 35086 | 25 |
| normal | EVALSHA-cross | 2s | 1 | 0 | 35082 | 35102 | 20 |
| normal | EVALSHA-cross | 2s | 1 | 1 | 35080 | 35100 | 20 |
| normal | EVALSHA-cross-header | 1s | 1 | 0 | 24063 | 24073 | 10 |
| normal | EVALSHA-cross-header | 1s | 1 | 1 | 24061 | 24071 | 10 |
| normal | EVALSHA-cross-header | 2s | 1 | 0 | 24090 | 24095 | 5 |
| normal | EVALSHA-cross-header | 2s | 1 | 1 | 24088 | 24093 | 5 |
| normal | FCALL-single | 1s | 1 | 0 | 8546 | 8547 | 1 |
| normal | FCALL-single | 1s | 1 | 1 | 8546 | 8547 | 1 |
| normal | FCALL-single | 2s | 1 | 0 | 9085 | 9086 | 1 |
| normal | FCALL-single | 2s | 1 | 1 | 9085 | 9086 | 1 |
| normal | FCALL-single-header | 1s | 1 | 0 | 5892 | 5893 | 1 |
| normal | FCALL-single-header | 1s | 1 | 1 | 5892 | 5893 | 1 |
| normal | FCALL-single-header | 2s | 1 | 0 | 6431 | 6432 | 1 |
| normal | FCALL-single-header | 2s | 1 | 1 | 6431 | 6432 | 1 |
| normal | FCALL-cross | 1s | 1 | 0 | 34914 | 34939 | 25 |
| normal | FCALL-cross | 1s | 1 | 1 | 34912 | 34937 | 25 |
| normal | FCALL-cross | 2s | 1 | 0 | 34933 | 34953 | 20 |
| normal | FCALL-cross | 2s | 1 | 1 | 34931 | 34951 | 20 |
| normal | FCALL-cross-header | 1s | 1 | 0 | 23829 | 23839 | 10 |
| normal | FCALL-cross-header | 1s | 1 | 1 | 23827 | 23837 | 10 |
| normal | FCALL-cross-header | 2s | 1 | 0 | 23856 | 23861 | 5 |
| normal | FCALL-cross-header | 2s | 1 | 1 | 23854 | 23859 | 5 |
| normal | GET | 1s | 1 | 0 | 936 | 936 | 0 |
| normal | GET | 1s | 1 | 1 | 936 | 936 | 0 |
| normal | GET | 1s | 32 | 0 | 18482 | 18482 | 0 |
| normal | GET | 1s | 32 | 1 | 18482 | 18482 | 0 |
| normal | GET | 2s | 1 | 0 | 1556 | 1556 | 0 |
| normal | GET | 2s | 1 | 1 | 1556 | 1556 | 0 |
| normal | GET | 2s | 32 | 0 | 18327 | 18327 | 0 |
| normal | GET | 2s | 32 | 1 | 18327 | 18327 | 0 |
| normal | SET | 1s | 1 | 0 | 1060 | 1060 | 0 |
| normal | SET | 1s | 1 | 1 | 1060 | 1060 | 0 |
| normal | SET | 1s | 32 | 0 | 22450 | 22450 | 0 |
| normal | SET | 1s | 32 | 1 | 22450 | 22450 | 0 |
| normal | SET | 2s | 1 | 0 | 1680 | 1680 | 0 |
| normal | SET | 2s | 1 | 1 | 1680 | 1680 | 0 |
| normal | SET | 2s | 32 | 0 | 22295 | 22295 | 0 |
| normal | SET | 2s | 32 | 1 | 22295 | 22295 | 0 |
| normal | INCR | 1s | 1 | 0 | 1511 | 1511 | 0 |
| normal | INCR | 1s | 1 | 1 | 1511 | 1511 | 0 |
| normal | INCR | 1s | 32 | 0 | 37411 | 37411 | 0 |
| normal | INCR | 1s | 32 | 1 | 37411 | 37411 | 0 |
| normal | INCR | 2s | 1 | 0 | 2131 | 2131 | 0 |
| normal | INCR | 2s | 1 | 1 | 2131 | 2131 | 0 |
| normal | INCR | 2s | 32 | 0 | 37256 | 37256 | 0 |
| normal | INCR | 2s | 32 | 1 | 37256 | 37256 | 0 |
| normal | MGET | 1s | 1 | 0 | 10159 | 10147 | -12 |
| normal | MGET | 1s | 1 | 1 | 10177 | 10171 | -6 |
| normal | MGET | 1s | 32 | 0 | 323910 | 323526 | -384 |
| normal | MGET | 1s | 32 | 1 | 324486 | 324294 | -192 |
| normal | MGET | 2s | 1 | 0 | 10159 | 10147 | -12 |
| normal | MGET | 2s | 1 | 1 | 10177 | 10171 | -6 |
| normal | MGET | 2s | 32 | 0 | 323910 | 323526 | -384 |
| normal | MGET | 2s | 32 | 1 | 324486 | 324294 | -192 |
| normal | MSET | 1s | 1 | 0 | 10779 | 10680 | -99 |
| normal | MSET | 1s | 1 | 1 | 16956 | 16947 | -9 |
| normal | MSET | 1s | 32 | 0 | 344773 | 341605 | -3168 |
| normal | MSET | 1s | 32 | 1 | 960806 | 960766 | -40 |
| normal | MSET | 2s | 1 | 0 | 10597 | 10498 | -99 |
| normal | MSET | 2s | 1 | 1 | 16624 | 16615 | -9 |
| normal | MSET | 2s | 32 | 0 | 338949 | 335781 | -3168 |
| normal | MSET | 2s | 32 | 1 | 950182 | 950142 | -40 |
| normal | EXEC-same | 1s | 1 | 0 | 23337 | 23290 | -47 |
| normal | EXEC-same | 1s | 1 | 1 | 23337 | 23290 | -47 |
| normal | EXEC-same | 1s | 2 | 0 | 28644 | 28605 | -39 |
| normal | EXEC-same | 1s | 2 | 1 | 28644 | 28605 | -39 |
| normal | EXEC-same | 1s | 4 | 0 | 39161 | 39138 | -23 |
| normal | EXEC-same | 1s | 4 | 1 | 39161 | 39138 | -23 |
| normal | EXEC-same | 2s | 1 | 0 | 23292 | 23245 | -47 |
| normal | EXEC-same | 2s | 1 | 1 | 23292 | 23245 | -47 |
| normal | EXEC-same | 2s | 2 | 0 | 28584 | 28545 | -39 |
| normal | EXEC-same | 2s | 2 | 1 | 28584 | 28545 | -39 |
| normal | EXEC-same | 2s | 4 | 0 | 39071 | 39048 | -23 |
| normal | EXEC-same | 2s | 4 | 1 | 39071 | 39048 | -23 |
| normal | EXEC-cross | 1s | 1 | 0 | 23337 | 23290 | -47 |
| normal | EXEC-cross | 1s | 1 | 1 | 23337 | 23290 | -47 |
| normal | EXEC-cross | 1s | 2 | 0 | 33567 | 33515 | -52 |
| normal | EXEC-cross | 1s | 2 | 1 | 33567 | 33515 | -52 |
| normal | EXEC-cross | 1s | 4 | 0 | 53823 | 53767 | -56 |
| normal | EXEC-cross | 1s | 4 | 1 | 53823 | 53767 | -56 |
| normal | EXEC-cross | 2s | 1 | 0 | 23292 | 23245 | -47 |
| normal | EXEC-cross | 2s | 1 | 1 | 23292 | 23245 | -47 |
| normal | EXEC-cross | 2s | 2 | 0 | 33417 | 33365 | -52 |
| normal | EXEC-cross | 2s | 2 | 1 | 33417 | 33365 | -52 |
| normal | EXEC-cross | 2s | 4 | 0 | 53325 | 53269 | -56 |
| normal | EXEC-cross | 2s | 4 | 1 | 53325 | 53269 | -56 |
| normal | READLOCAL-GET | 1s | 1 | 1 | 2433 | 2433 | 0 |
| normal | READLOCAL-GET | 1s | 32 | 1 | 49236 | 49236 | 0 |
| normal | FLUSHALL-empty | 1s | 1 | 0 | 163698 | 200975 | 37277 |
| normal | FLUSHALL-empty | 1s | 1 | 1 | 163728 | 200975 | 37247 |
| normal | FLUSHALL-empty | 2s | 1 | 0 | 163698 | 200605 | 36907 |
| normal | FLUSHALL-empty | 2s | 1 | 1 | 163728 | 200605 | 36877 |
| normal | FLUSHALL-small | 1s | 1 | 0 | 164530 | 201807 | 37277 |
| normal | FLUSHALL-small | 1s | 1 | 1 | 164560 | 201807 | 37247 |
| normal | FLUSHALL-small | 2s | 1 | 0 | 164530 | 201437 | 36907 |
| normal | FLUSHALL-small | 2s | 1 | 1 | 164560 | 201437 | 36877 |
| db0 | EVAL-single | 1s | 1 | 0 | 8318 | 8149 | -169 |
| db0 | EVAL-single | 1s | 1 | 1 | 8318 | 8149 | -169 |
| db0 | EVAL-single | 2s | 1 | 0 | 8539 | 8370 | -169 |
| db0 | EVAL-single | 2s | 1 | 1 | 8539 | 8370 | -169 |
| db0 | EVAL-single-header | 1s | 1 | 0 | 5881 | 5802 | -79 |
| db0 | EVAL-single-header | 1s | 1 | 1 | 5881 | 5802 | -79 |
| db0 | EVAL-single-header | 2s | 1 | 0 | 6102 | 6023 | -79 |
| db0 | EVAL-single-header | 2s | 1 | 1 | 6102 | 6023 | -79 |
| db0 | EVAL-cross | 1s | 1 | 0 | 32425 | 32093 | -332 |
| db0 | EVAL-cross | 1s | 1 | 1 | 32423 | 32091 | -332 |
| db0 | EVAL-cross | 2s | 1 | 0 | 32444 | 32111 | -333 |
| db0 | EVAL-cross | 2s | 1 | 1 | 32442 | 32109 | -333 |
| db0 | EVAL-cross-header | 1s | 1 | 0 | 21629 | 21491 | -138 |
| db0 | EVAL-cross-header | 1s | 1 | 1 | 21627 | 21489 | -138 |
| db0 | EVAL-cross-header | 2s | 1 | 0 | 21656 | 21517 | -139 |
| db0 | EVAL-cross-header | 2s | 1 | 1 | 21654 | 21515 | -139 |
| db0 | EVALSHA-single | 1s | 1 | 0 | 8179 | 8010 | -169 |
| db0 | EVALSHA-single | 1s | 1 | 1 | 8179 | 8010 | -169 |
| db0 | EVALSHA-single | 2s | 1 | 0 | 8400 | 8231 | -169 |
| db0 | EVALSHA-single | 2s | 1 | 1 | 8400 | 8231 | -169 |
| db0 | EVALSHA-single-header | 1s | 1 | 0 | 5742 | 5663 | -79 |
| db0 | EVALSHA-single-header | 1s | 1 | 1 | 5742 | 5663 | -79 |
| db0 | EVALSHA-single-header | 2s | 1 | 0 | 5963 | 5884 | -79 |
| db0 | EVALSHA-single-header | 2s | 1 | 1 | 5963 | 5884 | -79 |
| db0 | EVALSHA-cross | 1s | 1 | 0 | 32345 | 32013 | -332 |
| db0 | EVALSHA-cross | 1s | 1 | 1 | 32343 | 32011 | -332 |
| db0 | EVALSHA-cross | 2s | 1 | 0 | 32364 | 32031 | -333 |
| db0 | EVALSHA-cross | 2s | 1 | 1 | 32362 | 32029 | -333 |
| db0 | EVALSHA-cross-header | 1s | 1 | 0 | 21549 | 21411 | -138 |
| db0 | EVALSHA-cross-header | 1s | 1 | 1 | 21547 | 21409 | -138 |
| db0 | EVALSHA-cross-header | 2s | 1 | 0 | 21576 | 21437 | -139 |
| db0 | EVALSHA-cross-header | 2s | 1 | 1 | 21574 | 21435 | -139 |
| db0 | FCALL-single | 1s | 1 | 0 | 8042 | 7873 | -169 |
| db0 | FCALL-single | 1s | 1 | 1 | 8042 | 7873 | -169 |
| db0 | FCALL-single | 2s | 1 | 0 | 8263 | 8094 | -169 |
| db0 | FCALL-single | 2s | 1 | 1 | 8263 | 8094 | -169 |
| db0 | FCALL-single-header | 1s | 1 | 0 | 5533 | 5454 | -79 |
| db0 | FCALL-single-header | 1s | 1 | 1 | 5533 | 5454 | -79 |
| db0 | FCALL-single-header | 2s | 1 | 0 | 5754 | 5675 | -79 |
| db0 | FCALL-single-header | 2s | 1 | 1 | 5754 | 5675 | -79 |
| db0 | FCALL-cross | 1s | 1 | 0 | 32278 | 31946 | -332 |
| db0 | FCALL-cross | 1s | 1 | 1 | 32276 | 31944 | -332 |
| db0 | FCALL-cross | 2s | 1 | 0 | 32297 | 31964 | -333 |
| db0 | FCALL-cross | 2s | 1 | 1 | 32295 | 31962 | -333 |
| db0 | FCALL-cross-header | 1s | 1 | 0 | 21406 | 21268 | -138 |
| db0 | FCALL-cross-header | 1s | 1 | 1 | 21404 | 21266 | -138 |
| db0 | FCALL-cross-header | 2s | 1 | 0 | 21433 | 21294 | -139 |
| db0 | FCALL-cross-header | 2s | 1 | 1 | 21431 | 21292 | -139 |
| db0 | GET | 1s | 1 | 0 | 818 | 783 | -35 |
| db0 | GET | 1s | 1 | 1 | 818 | 783 | -35 |
| db0 | GET | 1s | 32 | 0 | 18705 | 17585 | -1120 |
| db0 | GET | 1s | 32 | 1 | 18705 | 17585 | -1120 |
| db0 | GET | 2s | 1 | 0 | 1051 | 1016 | -35 |
| db0 | GET | 2s | 1 | 1 | 1051 | 1016 | -35 |
| db0 | GET | 2s | 32 | 0 | 18163 | 17043 | -1120 |
| db0 | GET | 2s | 32 | 1 | 18163 | 17043 | -1120 |
| db0 | SET | 1s | 1 | 0 | 926 | 926 | 0 |
| db0 | SET | 1s | 1 | 1 | 926 | 926 | 0 |
| db0 | SET | 1s | 32 | 0 | 22161 | 22161 | 0 |
| db0 | SET | 1s | 32 | 1 | 22161 | 22161 | 0 |
| db0 | SET | 2s | 1 | 0 | 1159 | 1159 | 0 |
| db0 | SET | 2s | 1 | 1 | 1159 | 1159 | 0 |
| db0 | SET | 2s | 32 | 0 | 21619 | 21619 | 0 |
| db0 | SET | 2s | 32 | 1 | 21619 | 21619 | 0 |
| db0 | INCR | 1s | 1 | 0 | 1308 | 1269 | -39 |
| db0 | INCR | 1s | 1 | 1 | 1308 | 1269 | -39 |
| db0 | INCR | 1s | 32 | 0 | 34914 | 33666 | -1248 |
| db0 | INCR | 1s | 32 | 1 | 34914 | 33666 | -1248 |
| db0 | INCR | 2s | 1 | 0 | 1541 | 1502 | -39 |
| db0 | INCR | 2s | 1 | 1 | 1541 | 1502 | -39 |
| db0 | INCR | 2s | 32 | 0 | 34372 | 33124 | -1248 |
| db0 | INCR | 2s | 32 | 1 | 34372 | 33124 | -1248 |
| db0 | MGET | 1s | 1 | 0 | 10308 | 9964 | -344 |
| db0 | MGET | 1s | 1 | 1 | 10325 | 9990 | -335 |
| db0 | MGET | 1s | 32 | 0 | 328678 | 317670 | -11008 |
| db0 | MGET | 1s | 32 | 1 | 329222 | 318502 | -10720 |
| db0 | MGET | 2s | 1 | 0 | 10308 | 9964 | -344 |
| db0 | MGET | 2s | 1 | 1 | 10325 | 9990 | -335 |
| db0 | MGET | 2s | 32 | 0 | 328678 | 317670 | -11008 |
| db0 | MGET | 2s | 32 | 1 | 329222 | 318502 | -10720 |
| db0 | MSET | 1s | 1 | 0 | 11018 | 10748 | -270 |
| db0 | MSET | 1s | 1 | 1 | 16415 | 16306 | -109 |
| db0 | MSET | 1s | 32 | 0 | 352421 | 343781 | -8640 |
| db0 | MSET | 1s | 32 | 1 | 951926 | 897102 | -54824 |
| db0 | MSET | 2s | 1 | 0 | 10828 | 10566 | -262 |
| db0 | MSET | 2s | 1 | 1 | 16075 | 15974 | -101 |
| db0 | MSET | 2s | 32 | 0 | 346341 | 337957 | -8384 |
| db0 | MSET | 2s | 32 | 1 | 941046 | 886478 | -54568 |
| db0 | EXEC-same | 1s | 1 | 0 | 22142 | 22025 | -117 |
| db0 | EXEC-same | 1s | 1 | 1 | 22142 | 22025 | -117 |
| db0 | EXEC-same | 1s | 2 | 0 | 27174 | 26990 | -184 |
| db0 | EXEC-same | 1s | 2 | 1 | 27174 | 26990 | -184 |
| db0 | EXEC-same | 1s | 4 | 0 | 37134 | 36812 | -322 |
| db0 | EXEC-same | 1s | 4 | 1 | 37134 | 36812 | -322 |
| db0 | EXEC-same | 2s | 1 | 0 | 22097 | 21979 | -118 |
| db0 | EXEC-same | 2s | 1 | 1 | 22097 | 21979 | -118 |
| db0 | EXEC-same | 2s | 2 | 0 | 27114 | 26928 | -186 |
| db0 | EXEC-same | 2s | 2 | 1 | 27114 | 26928 | -186 |
| db0 | EXEC-same | 2s | 4 | 0 | 37044 | 36718 | -326 |
| db0 | EXEC-same | 2s | 4 | 1 | 37044 | 36718 | -326 |
| db0 | EXEC-cross | 1s | 1 | 0 | 22142 | 22025 | -117 |
| db0 | EXEC-cross | 1s | 1 | 1 | 22142 | 22025 | -117 |
| db0 | EXEC-cross | 1s | 2 | 0 | 31877 | 31707 | -170 |
| db0 | EXEC-cross | 1s | 2 | 1 | 31877 | 31707 | -170 |
| db0 | EXEC-cross | 1s | 4 | 0 | 51130 | 50824 | -306 |
| db0 | EXEC-cross | 1s | 4 | 1 | 51130 | 50824 | -306 |
| db0 | EXEC-cross | 2s | 1 | 0 | 22097 | 21979 | -118 |
| db0 | EXEC-cross | 2s | 1 | 1 | 22097 | 21979 | -118 |
| db0 | EXEC-cross | 2s | 2 | 0 | 31727 | 31555 | -172 |
| db0 | EXEC-cross | 2s | 2 | 1 | 31727 | 31555 | -172 |
| db0 | EXEC-cross | 2s | 4 | 0 | 50632 | 50322 | -310 |
| db0 | EXEC-cross | 2s | 4 | 1 | 50632 | 50322 | -310 |
| db0 | READLOCAL-GET | 1s | 1 | 1 | 2345 | 2345 | 0 |
| db0 | READLOCAL-GET | 1s | 32 | 1 | 45954 | 45954 | 0 |
| db0 | FLUSHALL-empty | 1s | 1 | 0 | 129915 | 167677 | 37762 |
| db0 | FLUSHALL-empty | 1s | 1 | 1 | 129945 | 167677 | 37732 |
| db0 | FLUSHALL-empty | 2s | 1 | 0 | 129915 | 167307 | 37392 |
| db0 | FLUSHALL-empty | 2s | 1 | 1 | 129945 | 167307 | 37362 |
| db0 | FLUSHALL-small | 1s | 1 | 0 | 130475 | 168237 | 37762 |
| db0 | FLUSHALL-small | 1s | 1 | 1 | 130505 | 168237 | 37732 |
| db0 | FLUSHALL-small | 2s | 1 | 0 | 130475 | 167867 | 37392 |
| db0 | FLUSHALL-small | 2s | 1 | 1 | 130505 | 167867 | 37362 |

## Scriptfix3 reference

Wave11 retained scriptfix3 receipts and production bindings; same tracer source, warm script activation and GC fixture semantics. These reference counts were not rerun in wave12.

| Domain | Namespace | Command | Delta min | Delta max |
|---|---|---|---:|---:|
| scriptfix3_native | db0 | EVAL-cross | -349 | -348 |
| scriptfix3_native | db0 | EVAL-cross-header | -143 | -142 |
| scriptfix3_native | db0 | EVAL-single | -185 | -185 |
| scriptfix3_native | db0 | EVAL-single-header | -83 | -83 |
| scriptfix3_native | db0 | EVALSHA-cross | -345 | -344 |
| scriptfix3_native | db0 | EVALSHA-cross-header | -139 | -138 |
| scriptfix3_native | db0 | EVALSHA-single | -181 | -181 |
| scriptfix3_native | db0 | EVALSHA-single-header | -79 | -79 |
| scriptfix3_native | db0 | FCALL-cross | -351 | -350 |
| scriptfix3_native | db0 | FCALL-cross-header | -157 | -156 |
| scriptfix3_native | db0 | FCALL-single | -187 | -187 |
| scriptfix3_native | db0 | FCALL-single-header | -97 | -97 |
| scriptfix3_native | normal | EVAL-cross | -19 | -14 |
| scriptfix3_native | normal | EVAL-cross-header | -10 | -5 |
| scriptfix3_native | normal | EVAL-single | -38 | -38 |
| scriptfix3_native | normal | EVAL-single-header | -14 | -14 |
| scriptfix3_native | normal | EVALSHA-cross | -15 | -10 |
| scriptfix3_native | normal | EVALSHA-cross-header | -6 | -1 |
| scriptfix3_native | normal | EVALSHA-single | -34 | -34 |
| scriptfix3_native | normal | EVALSHA-single-header | -10 | -10 |
| scriptfix3_native | normal | FCALL-cross | -1 | 4 |
| scriptfix3_native | normal | FCALL-cross-header | -14 | -9 |
| scriptfix3_native | normal | FCALL-single | -20 | -20 |
| scriptfix3_native | normal | FCALL-single-header | -18 | -18 |
| scriptfix3_lua | db0 | EVAL-cross | -655 | -651 |
| scriptfix3_lua | db0 | EVAL-cross-header | -258 | -254 |
| scriptfix3_lua | db0 | EVAL-single | -492 | -492 |
| scriptfix3_lua | db0 | EVAL-single-header | -199 | -194 |
| scriptfix3_lua | db0 | EVALSHA-cross | -651 | -646 |
| scriptfix3_lua | db0 | EVALSHA-cross-header | -255 | -249 |
| scriptfix3_lua | db0 | EVALSHA-single | -488 | -488 |
| scriptfix3_lua | db0 | EVALSHA-single-header | -195 | -190 |
| scriptfix3_lua | db0 | FCALL-cross | -351 | -350 |
| scriptfix3_lua | db0 | FCALL-cross-header | -169 | -156 |
| scriptfix3_lua | db0 | FCALL-single | -199 | -182 |
| scriptfix3_lua | db0 | FCALL-single-header | -109 | -85 |
| scriptfix3_lua | normal | EVAL-cross | -356 | -351 |
| scriptfix3_lua | normal | EVAL-cross-header | -215 | -210 |
| scriptfix3_lua | normal | EVAL-single | -380 | -375 |
| scriptfix3_lua | normal | EVAL-single-header | -219 | -219 |
| scriptfix3_lua | normal | EVALSHA-cross | -352 | -347 |
| scriptfix3_lua | normal | EVALSHA-cross-header | -211 | -206 |
| scriptfix3_lua | normal | EVALSHA-single | -376 | -371 |
| scriptfix3_lua | normal | EVALSHA-single-header | -215 | -215 |
| scriptfix3_lua | normal | FCALL-cross | -1 | 11 |
| scriptfix3_lua | normal | FCALL-cross-header | -14 | 3 |
| scriptfix3_lua | normal | FCALL-single | -32 | -20 |
| scriptfix3_lua | normal | FCALL-single-header | -30 | -13 |
