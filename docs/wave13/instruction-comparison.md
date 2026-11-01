# Command-scope instruction census

Serverless production command activation and completion. Native namespace instructions; Lua companion includes executable VM instructions. Fixture, shared-library bodies, network, io_uring syscalls and idle scheduler work are outside this census. No rates, cycles/op or IPC were measured.

Counts are instructions per complete activation (batch columns are totals).

| Namespace | Command | Mode | Batch/children | Atomic | PRE | POST | Delta |
|---|---|---|---:|---:|---:|---:|---:|
| normal | EVAL-single | 1s | 1 | 0 | 8915 | 8916 | 1 |
| normal | EVAL-single | 1s | 1 | 1 | 8915 | 8916 | 1 |
| normal | EVAL-single | 2s | 1 | 0 | 9454 | 9455 | 1 |
| normal | EVAL-single | 2s | 1 | 1 | 9454 | 9455 | 1 |
| normal | EVAL-single-header | 1s | 1 | 0 | 6342 | 6343 | 1 |
| normal | EVAL-single-header | 1s | 1 | 1 | 6342 | 6343 | 1 |
| normal | EVAL-single-header | 2s | 1 | 0 | 6881 | 6882 | 1 |
| normal | EVAL-single-header | 2s | 1 | 1 | 6881 | 6882 | 1 |
| normal | EVAL-cross | 1s | 1 | 0 | 35173 | 35174 | 1 |
| normal | EVAL-cross | 1s | 1 | 1 | 35171 | 35172 | 1 |
| normal | EVAL-cross | 2s | 1 | 0 | 35187 | 35188 | 1 |
| normal | EVAL-cross | 2s | 1 | 1 | 35185 | 35186 | 1 |
| normal | EVAL-cross-header | 1s | 1 | 0 | 24158 | 24159 | 1 |
| normal | EVAL-cross-header | 1s | 1 | 1 | 24156 | 24157 | 1 |
| normal | EVAL-cross-header | 2s | 1 | 0 | 24180 | 24181 | 1 |
| normal | EVAL-cross-header | 2s | 1 | 1 | 24178 | 24179 | 1 |
| normal | EVALSHA-single | 1s | 1 | 0 | 8766 | 8767 | 1 |
| normal | EVALSHA-single | 1s | 1 | 1 | 8766 | 8767 | 1 |
| normal | EVALSHA-single | 2s | 1 | 0 | 9305 | 9306 | 1 |
| normal | EVALSHA-single | 2s | 1 | 1 | 9305 | 9306 | 1 |
| normal | EVALSHA-single-header | 1s | 1 | 0 | 6193 | 6194 | 1 |
| normal | EVALSHA-single-header | 1s | 1 | 1 | 6193 | 6194 | 1 |
| normal | EVALSHA-single-header | 2s | 1 | 0 | 6732 | 6733 | 1 |
| normal | EVALSHA-single-header | 2s | 1 | 1 | 6732 | 6733 | 1 |
| normal | EVALSHA-cross | 1s | 1 | 0 | 35088 | 35089 | 1 |
| normal | EVALSHA-cross | 1s | 1 | 1 | 35086 | 35087 | 1 |
| normal | EVALSHA-cross | 2s | 1 | 0 | 35102 | 35103 | 1 |
| normal | EVALSHA-cross | 2s | 1 | 1 | 35100 | 35101 | 1 |
| normal | EVALSHA-cross-header | 1s | 1 | 0 | 24073 | 24074 | 1 |
| normal | EVALSHA-cross-header | 1s | 1 | 1 | 24071 | 24072 | 1 |
| normal | EVALSHA-cross-header | 2s | 1 | 0 | 24095 | 24096 | 1 |
| normal | EVALSHA-cross-header | 2s | 1 | 1 | 24093 | 24094 | 1 |
| normal | FCALL-single | 1s | 1 | 0 | 8547 | 8549 | 2 |
| normal | FCALL-single | 1s | 1 | 1 | 8547 | 8549 | 2 |
| normal | FCALL-single | 2s | 1 | 0 | 9086 | 9088 | 2 |
| normal | FCALL-single | 2s | 1 | 1 | 9086 | 9088 | 2 |
| normal | FCALL-single-header | 1s | 1 | 0 | 5893 | 5895 | 2 |
| normal | FCALL-single-header | 1s | 1 | 1 | 5893 | 5895 | 2 |
| normal | FCALL-single-header | 2s | 1 | 0 | 6432 | 6434 | 2 |
| normal | FCALL-single-header | 2s | 1 | 1 | 6432 | 6434 | 2 |
| normal | FCALL-cross | 1s | 1 | 0 | 34939 | 34941 | 2 |
| normal | FCALL-cross | 1s | 1 | 1 | 34937 | 34939 | 2 |
| normal | FCALL-cross | 2s | 1 | 0 | 34953 | 34955 | 2 |
| normal | FCALL-cross | 2s | 1 | 1 | 34951 | 34953 | 2 |
| normal | FCALL-cross-header | 1s | 1 | 0 | 23839 | 23841 | 2 |
| normal | FCALL-cross-header | 1s | 1 | 1 | 23837 | 23839 | 2 |
| normal | FCALL-cross-header | 2s | 1 | 0 | 23861 | 23863 | 2 |
| normal | FCALL-cross-header | 2s | 1 | 1 | 23859 | 23861 | 2 |
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
| normal | MGET | 1s | 1 | 0 | 10147 | 10147 | 0 |
| normal | MGET | 1s | 1 | 1 | 10171 | 10167 | -4 |
| normal | MGET | 1s | 32 | 0 | 323526 | 323526 | 0 |
| normal | MGET | 1s | 32 | 1 | 324294 | 324166 | -128 |
| normal | MGET | 2s | 1 | 0 | 10147 | 10147 | 0 |
| normal | MGET | 2s | 1 | 1 | 10171 | 10167 | -4 |
| normal | MGET | 2s | 32 | 0 | 323526 | 323526 | 0 |
| normal | MGET | 2s | 32 | 1 | 324294 | 324166 | -128 |
| normal | MSET | 1s | 1 | 0 | 10680 | 10682 | 2 |
| normal | MSET | 1s | 1 | 1 | 16947 | 16947 | 0 |
| normal | MSET | 1s | 32 | 0 | 341605 | 341669 | 64 |
| normal | MSET | 1s | 32 | 1 | 960766 | 960766 | 0 |
| normal | MSET | 2s | 1 | 0 | 10498 | 10500 | 2 |
| normal | MSET | 2s | 1 | 1 | 16615 | 16615 | 0 |
| normal | MSET | 2s | 32 | 0 | 335781 | 335845 | 64 |
| normal | MSET | 2s | 32 | 1 | 950142 | 950142 | 0 |
| normal | EXEC-same | 1s | 1 | 0 | 23290 | 23291 | 1 |
| normal | EXEC-same | 1s | 1 | 1 | 23290 | 23291 | 1 |
| normal | EXEC-same | 1s | 2 | 0 | 28605 | 28605 | 0 |
| normal | EXEC-same | 1s | 2 | 1 | 28605 | 28605 | 0 |
| normal | EXEC-same | 1s | 4 | 0 | 39138 | 39136 | -2 |
| normal | EXEC-same | 1s | 4 | 1 | 39138 | 39136 | -2 |
| normal | EXEC-same | 2s | 1 | 0 | 23245 | 23246 | 1 |
| normal | EXEC-same | 2s | 1 | 1 | 23245 | 23246 | 1 |
| normal | EXEC-same | 2s | 2 | 0 | 28545 | 28545 | 0 |
| normal | EXEC-same | 2s | 2 | 1 | 28545 | 28545 | 0 |
| normal | EXEC-same | 2s | 4 | 0 | 39048 | 39046 | -2 |
| normal | EXEC-same | 2s | 4 | 1 | 39048 | 39046 | -2 |
| normal | EXEC-cross | 1s | 1 | 0 | 23290 | 23291 | 1 |
| normal | EXEC-cross | 1s | 1 | 1 | 23290 | 23291 | 1 |
| normal | EXEC-cross | 1s | 2 | 0 | 33515 | 33515 | 0 |
| normal | EXEC-cross | 1s | 2 | 1 | 33515 | 33515 | 0 |
| normal | EXEC-cross | 1s | 4 | 0 | 53767 | 53765 | -2 |
| normal | EXEC-cross | 1s | 4 | 1 | 53767 | 53765 | -2 |
| normal | EXEC-cross | 2s | 1 | 0 | 23245 | 23246 | 1 |
| normal | EXEC-cross | 2s | 1 | 1 | 23245 | 23246 | 1 |
| normal | EXEC-cross | 2s | 2 | 0 | 33365 | 33365 | 0 |
| normal | EXEC-cross | 2s | 2 | 1 | 33365 | 33365 | 0 |
| normal | EXEC-cross | 2s | 4 | 0 | 53269 | 53267 | -2 |
| normal | EXEC-cross | 2s | 4 | 1 | 53269 | 53267 | -2 |
| normal | READLOCAL-GET | 1s | 1 | 1 | 2433 | 2433 | 0 |
| normal | READLOCAL-GET | 1s | 32 | 1 | 49236 | 49236 | 0 |
| normal | FLUSHALL-empty | 1s | 1 | 0 | 200975 | 200976 | 1 |
| normal | FLUSHALL-empty | 1s | 1 | 1 | 200975 | 200976 | 1 |
| normal | FLUSHALL-empty | 2s | 1 | 0 | 200605 | 200606 | 1 |
| normal | FLUSHALL-empty | 2s | 1 | 1 | 200605 | 200606 | 1 |
| normal | FLUSHALL-small | 1s | 1 | 0 | 201807 | 201808 | 1 |
| normal | FLUSHALL-small | 1s | 1 | 1 | 201807 | 201808 | 1 |
| normal | FLUSHALL-small | 2s | 1 | 0 | 201437 | 201438 | 1 |
| normal | FLUSHALL-small | 2s | 1 | 1 | 201437 | 201438 | 1 |
| db0 | EVAL-single | 1s | 1 | 0 | 8149 | 8150 | 1 |
| db0 | EVAL-single | 1s | 1 | 1 | 8149 | 8150 | 1 |
| db0 | EVAL-single | 2s | 1 | 0 | 8370 | 8371 | 1 |
| db0 | EVAL-single | 2s | 1 | 1 | 8370 | 8371 | 1 |
| db0 | EVAL-single-header | 1s | 1 | 0 | 5802 | 5803 | 1 |
| db0 | EVAL-single-header | 1s | 1 | 1 | 5802 | 5803 | 1 |
| db0 | EVAL-single-header | 2s | 1 | 0 | 6023 | 6024 | 1 |
| db0 | EVAL-single-header | 2s | 1 | 1 | 6023 | 6024 | 1 |
| db0 | EVAL-cross | 1s | 1 | 0 | 32093 | 32098 | 5 |
| db0 | EVAL-cross | 1s | 1 | 1 | 32091 | 32096 | 5 |
| db0 | EVAL-cross | 2s | 1 | 0 | 32111 | 32112 | 1 |
| db0 | EVAL-cross | 2s | 1 | 1 | 32109 | 32110 | 1 |
| db0 | EVAL-cross-header | 1s | 1 | 0 | 21491 | 21496 | 5 |
| db0 | EVAL-cross-header | 1s | 1 | 1 | 21489 | 21494 | 5 |
| db0 | EVAL-cross-header | 2s | 1 | 0 | 21517 | 21518 | 1 |
| db0 | EVAL-cross-header | 2s | 1 | 1 | 21515 | 21516 | 1 |
| db0 | EVALSHA-single | 1s | 1 | 0 | 8010 | 8011 | 1 |
| db0 | EVALSHA-single | 1s | 1 | 1 | 8010 | 8011 | 1 |
| db0 | EVALSHA-single | 2s | 1 | 0 | 8231 | 8232 | 1 |
| db0 | EVALSHA-single | 2s | 1 | 1 | 8231 | 8232 | 1 |
| db0 | EVALSHA-single-header | 1s | 1 | 0 | 5663 | 5664 | 1 |
| db0 | EVALSHA-single-header | 1s | 1 | 1 | 5663 | 5664 | 1 |
| db0 | EVALSHA-single-header | 2s | 1 | 0 | 5884 | 5885 | 1 |
| db0 | EVALSHA-single-header | 2s | 1 | 1 | 5884 | 5885 | 1 |
| db0 | EVALSHA-cross | 1s | 1 | 0 | 32013 | 32018 | 5 |
| db0 | EVALSHA-cross | 1s | 1 | 1 | 32011 | 32016 | 5 |
| db0 | EVALSHA-cross | 2s | 1 | 0 | 32031 | 32032 | 1 |
| db0 | EVALSHA-cross | 2s | 1 | 1 | 32029 | 32030 | 1 |
| db0 | EVALSHA-cross-header | 1s | 1 | 0 | 21411 | 21416 | 5 |
| db0 | EVALSHA-cross-header | 1s | 1 | 1 | 21409 | 21414 | 5 |
| db0 | EVALSHA-cross-header | 2s | 1 | 0 | 21437 | 21438 | 1 |
| db0 | EVALSHA-cross-header | 2s | 1 | 1 | 21435 | 21436 | 1 |
| db0 | FCALL-single | 1s | 1 | 0 | 7873 | 7875 | 2 |
| db0 | FCALL-single | 1s | 1 | 1 | 7873 | 7875 | 2 |
| db0 | FCALL-single | 2s | 1 | 0 | 8094 | 8096 | 2 |
| db0 | FCALL-single | 2s | 1 | 1 | 8094 | 8096 | 2 |
| db0 | FCALL-single-header | 1s | 1 | 0 | 5454 | 5456 | 2 |
| db0 | FCALL-single-header | 1s | 1 | 1 | 5454 | 5456 | 2 |
| db0 | FCALL-single-header | 2s | 1 | 0 | 5675 | 5677 | 2 |
| db0 | FCALL-single-header | 2s | 1 | 1 | 5675 | 5677 | 2 |
| db0 | FCALL-cross | 1s | 1 | 0 | 31946 | 31952 | 6 |
| db0 | FCALL-cross | 1s | 1 | 1 | 31944 | 31950 | 6 |
| db0 | FCALL-cross | 2s | 1 | 0 | 31964 | 31966 | 2 |
| db0 | FCALL-cross | 2s | 1 | 1 | 31962 | 31964 | 2 |
| db0 | FCALL-cross-header | 1s | 1 | 0 | 21268 | 21274 | 6 |
| db0 | FCALL-cross-header | 1s | 1 | 1 | 21266 | 21272 | 6 |
| db0 | FCALL-cross-header | 2s | 1 | 0 | 21294 | 21296 | 2 |
| db0 | FCALL-cross-header | 2s | 1 | 1 | 21292 | 21294 | 2 |
| db0 | GET | 1s | 1 | 0 | 783 | 783 | 0 |
| db0 | GET | 1s | 1 | 1 | 783 | 783 | 0 |
| db0 | GET | 1s | 32 | 0 | 17585 | 17585 | 0 |
| db0 | GET | 1s | 32 | 1 | 17585 | 17585 | 0 |
| db0 | GET | 2s | 1 | 0 | 1016 | 1016 | 0 |
| db0 | GET | 2s | 1 | 1 | 1016 | 1016 | 0 |
| db0 | GET | 2s | 32 | 0 | 17043 | 17043 | 0 |
| db0 | GET | 2s | 32 | 1 | 17043 | 17043 | 0 |
| db0 | SET | 1s | 1 | 0 | 926 | 926 | 0 |
| db0 | SET | 1s | 1 | 1 | 926 | 926 | 0 |
| db0 | SET | 1s | 32 | 0 | 22161 | 22161 | 0 |
| db0 | SET | 1s | 32 | 1 | 22161 | 22161 | 0 |
| db0 | SET | 2s | 1 | 0 | 1159 | 1159 | 0 |
| db0 | SET | 2s | 1 | 1 | 1159 | 1159 | 0 |
| db0 | SET | 2s | 32 | 0 | 21619 | 21619 | 0 |
| db0 | SET | 2s | 32 | 1 | 21619 | 21619 | 0 |
| db0 | INCR | 1s | 1 | 0 | 1269 | 1269 | 0 |
| db0 | INCR | 1s | 1 | 1 | 1269 | 1269 | 0 |
| db0 | INCR | 1s | 32 | 0 | 33666 | 33666 | 0 |
| db0 | INCR | 1s | 32 | 1 | 33666 | 33666 | 0 |
| db0 | INCR | 2s | 1 | 0 | 1502 | 1502 | 0 |
| db0 | INCR | 2s | 1 | 1 | 1502 | 1502 | 0 |
| db0 | INCR | 2s | 32 | 0 | 33124 | 33124 | 0 |
| db0 | INCR | 2s | 32 | 1 | 33124 | 33124 | 0 |
| db0 | MGET | 1s | 1 | 0 | 9964 | 9961 | -3 |
| db0 | MGET | 1s | 1 | 1 | 9990 | 9981 | -9 |
| db0 | MGET | 1s | 32 | 0 | 317670 | 317574 | -96 |
| db0 | MGET | 1s | 32 | 1 | 318502 | 318214 | -288 |
| db0 | MGET | 2s | 1 | 0 | 9964 | 9961 | -3 |
| db0 | MGET | 2s | 1 | 1 | 9990 | 9981 | -9 |
| db0 | MGET | 2s | 32 | 0 | 317670 | 317574 | -96 |
| db0 | MGET | 2s | 32 | 1 | 318502 | 318214 | -288 |
| db0 | MSET | 1s | 1 | 0 | 10748 | 10747 | -1 |
| db0 | MSET | 1s | 1 | 1 | 16306 | 16295 | -11 |
| db0 | MSET | 1s | 32 | 0 | 343781 | 343749 | -32 |
| db0 | MSET | 1s | 32 | 1 | 897102 | 896750 | -352 |
| db0 | MSET | 2s | 1 | 0 | 10566 | 10565 | -1 |
| db0 | MSET | 2s | 1 | 1 | 15974 | 15963 | -11 |
| db0 | MSET | 2s | 32 | 0 | 337957 | 337925 | -32 |
| db0 | MSET | 2s | 32 | 1 | 886478 | 886126 | -352 |
| db0 | EXEC-same | 1s | 1 | 0 | 22025 | 22025 | 0 |
| db0 | EXEC-same | 1s | 1 | 1 | 22025 | 22025 | 0 |
| db0 | EXEC-same | 1s | 2 | 0 | 26990 | 26988 | -2 |
| db0 | EXEC-same | 1s | 2 | 1 | 26990 | 26988 | -2 |
| db0 | EXEC-same | 1s | 4 | 0 | 36812 | 36806 | -6 |
| db0 | EXEC-same | 1s | 4 | 1 | 36812 | 36806 | -6 |
| db0 | EXEC-same | 2s | 1 | 0 | 21979 | 21979 | 0 |
| db0 | EXEC-same | 2s | 1 | 1 | 21979 | 21979 | 0 |
| db0 | EXEC-same | 2s | 2 | 0 | 26928 | 26926 | -2 |
| db0 | EXEC-same | 2s | 2 | 1 | 26928 | 26926 | -2 |
| db0 | EXEC-same | 2s | 4 | 0 | 36718 | 36712 | -6 |
| db0 | EXEC-same | 2s | 4 | 1 | 36718 | 36712 | -6 |
| db0 | EXEC-cross | 1s | 1 | 0 | 22025 | 22025 | 0 |
| db0 | EXEC-cross | 1s | 1 | 1 | 22025 | 22025 | 0 |
| db0 | EXEC-cross | 1s | 2 | 0 | 31707 | 31705 | -2 |
| db0 | EXEC-cross | 1s | 2 | 1 | 31707 | 31705 | -2 |
| db0 | EXEC-cross | 1s | 4 | 0 | 50824 | 50818 | -6 |
| db0 | EXEC-cross | 1s | 4 | 1 | 50824 | 50818 | -6 |
| db0 | EXEC-cross | 2s | 1 | 0 | 21979 | 21979 | 0 |
| db0 | EXEC-cross | 2s | 1 | 1 | 21979 | 21979 | 0 |
| db0 | EXEC-cross | 2s | 2 | 0 | 31555 | 31553 | -2 |
| db0 | EXEC-cross | 2s | 2 | 1 | 31555 | 31553 | -2 |
| db0 | EXEC-cross | 2s | 4 | 0 | 50322 | 50316 | -6 |
| db0 | EXEC-cross | 2s | 4 | 1 | 50322 | 50316 | -6 |
| db0 | READLOCAL-GET | 1s | 1 | 1 | 2345 | 2345 | 0 |
| db0 | READLOCAL-GET | 1s | 32 | 1 | 45954 | 45954 | 0 |
| db0 | FLUSHALL-empty | 1s | 1 | 0 | 167677 | 167677 | 0 |
| db0 | FLUSHALL-empty | 1s | 1 | 1 | 167677 | 167677 | 0 |
| db0 | FLUSHALL-empty | 2s | 1 | 0 | 167307 | 167307 | 0 |
| db0 | FLUSHALL-empty | 2s | 1 | 1 | 167307 | 167307 | 0 |
| db0 | FLUSHALL-small | 1s | 1 | 0 | 168237 | 168237 | 0 |
| db0 | FLUSHALL-small | 1s | 1 | 1 | 168237 | 168237 | 0 |
| db0 | FLUSHALL-small | 2s | 1 | 0 | 167867 | 167867 | 0 |
| db0 | FLUSHALL-small | 2s | 1 | 1 | 167867 | 167867 | 0 |

## Summary by namespace and domain

| Domain | Namespace | Command | Delta min | Delta max |
|---|---|---|---:|---:|
| headline_native | db0 | EVAL-cross | 1 | 5 |
| headline_native | db0 | EVAL-cross-header | 1 | 5 |
| headline_native | db0 | EVAL-single | 1 | 1 |
| headline_native | db0 | EVAL-single-header | 1 | 1 |
| headline_native | db0 | EVALSHA-cross | 1 | 5 |
| headline_native | db0 | EVALSHA-cross-header | 1 | 5 |
| headline_native | db0 | EVALSHA-single | 1 | 1 |
| headline_native | db0 | EVALSHA-single-header | 1 | 1 |
| headline_native | db0 | EXEC-cross | -6 | 0 |
| headline_native | db0 | EXEC-same | -6 | 0 |
| headline_native | db0 | FCALL-cross | 2 | 6 |
| headline_native | db0 | FCALL-cross-header | 2 | 6 |
| headline_native | db0 | FCALL-single | 2 | 2 |
| headline_native | db0 | FCALL-single-header | 2 | 2 |
| headline_native | db0 | FLUSHALL-empty | 0 | 0 |
| headline_native | db0 | FLUSHALL-small | 0 | 0 |
| headline_native | db0 | GET | 0 | 0 |
| headline_native | db0 | INCR | 0 | 0 |
| headline_native | db0 | MGET | -288 | -3 |
| headline_native | db0 | MSET | -352 | -1 |
| headline_native | db0 | READLOCAL-GET | 0 | 0 |
| headline_native | db0 | SET | 0 | 0 |
| headline_native | normal | EVAL-cross | 1 | 1 |
| headline_native | normal | EVAL-cross-header | 1 | 1 |
| headline_native | normal | EVAL-single | 1 | 1 |
| headline_native | normal | EVAL-single-header | 1 | 1 |
| headline_native | normal | EVALSHA-cross | 1 | 1 |
| headline_native | normal | EVALSHA-cross-header | 1 | 1 |
| headline_native | normal | EVALSHA-single | 1 | 1 |
| headline_native | normal | EVALSHA-single-header | 1 | 1 |
| headline_native | normal | EXEC-cross | -2 | 1 |
| headline_native | normal | EXEC-same | -2 | 1 |
| headline_native | normal | FCALL-cross | 2 | 2 |
| headline_native | normal | FCALL-cross-header | 2 | 2 |
| headline_native | normal | FCALL-single | 2 | 2 |
| headline_native | normal | FCALL-single-header | 2 | 2 |
| headline_native | normal | FLUSHALL-empty | 1 | 1 |
| headline_native | normal | FLUSHALL-small | 1 | 1 |
| headline_native | normal | GET | 0 | 0 |
| headline_native | normal | INCR | 0 | 0 |
| headline_native | normal | MGET | -128 | 0 |
| headline_native | normal | MSET | 0 | 64 |
| headline_native | normal | READLOCAL-GET | 0 | 0 |
| headline_native | normal | SET | 0 | 0 |
| headline_lua | db0 | EVAL-cross | -4 | 6 |
| headline_lua | db0 | EVAL-cross-header | 0 | 5 |
| headline_lua | db0 | EVAL-single | -4 | 1 |
| headline_lua | db0 | EVAL-single-header | -4 | 6 |
| headline_lua | db0 | EVALSHA-cross | 0 | 6 |
| headline_lua | db0 | EVALSHA-cross-header | 1 | 10 |
| headline_lua | db0 | EVALSHA-single | -4 | 6 |
| headline_lua | db0 | EVALSHA-single-header | -4 | 6 |
| headline_lua | db0 | FCALL-cross | 2 | 18 |
| headline_lua | db0 | FCALL-cross-header | 2 | 6 |
| headline_lua | db0 | FCALL-single | -10 | 2 |
| headline_lua | db0 | FCALL-single-header | 2 | 7 |
| headline_lua | normal | EVAL-cross | -4 | 1 |
| headline_lua | normal | EVAL-cross-header | -4 | 1 |
| headline_lua | normal | EVAL-single | -4 | 6 |
| headline_lua | normal | EVAL-single-header | 1 | 6 |
| headline_lua | normal | EVALSHA-cross | -4 | 6 |
| headline_lua | normal | EVALSHA-cross-header | -4 | 1 |
| headline_lua | normal | EVALSHA-single | 1 | 1 |
| headline_lua | normal | EVALSHA-single-header | -4 | 6 |
| headline_lua | normal | FCALL-cross | 2 | 14 |
| headline_lua | normal | FCALL-cross-header | -10 | 14 |
| headline_lua | normal | FCALL-single | -10 | 7 |
| headline_lua | normal | FCALL-single-header | -10 | 2 |
