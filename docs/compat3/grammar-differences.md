# Additional stream option differences (inventory only)

508 fresh-state probes per mode; 137 parser outcome differences in each mode. Full replies are retained in [1s.json](grammar/1s.json) and [2s.json](grammar/2s.json). The comparison below covers acceptance and exact error replies, not data semantics or timing fields. No listed difference was fixed in this lane.

Coverage: 22 numeric options × 19 boundary/lexical inputs; four stream-ID options × 17 inputs; 22 duplicate-option probes. Each probe resets the database, adds three explicit IDs, creates the group and populates its PEL. Geometry: 16 shards; split 6:2 or eight fused threads; atomic 0, uring, databases 1. Oracle CPU 104/port 25891; server CPUs 96–103/port 25890; client CPUs 105–111.

Redis parser anchors: `/home/user/Projects/redis/src/util.c:439` (`string2ll`), `object.c:867` (`getLongLongFromObjectOrReply`), and `t_stream.c`: 918/943/956 (trim MAXLEN/MINID/LIMIT), 2124 (range COUNT), 2195/2199 (read BLOCK/COUNT), 2610 (ENTRIESREAD), 2769/2777 (XSETID), 2918/2930 (XPENDING), 3159/3193/3199/3204/3209 (XCLAIM), 3369 (XAUTOCLAIM), 3683 (XINFO FULL COUNT). This is a bounded inventory of the complete numeric-option families, not an exhaustive grammar proof.

| Option or repeated command | Inputs | Redis 7.4.10 | TomoKV |
|---|---|---|---|
| XADD LIMIT | '-9223372036854775809', '-0', '00', '01', '+1', ' 1', '1 ', '1\x00', '1.0', '', '9223372036854775808', '18446744073709551615' | ERR value is not an integer or out of range | ERR syntax error |
| XTRIM LIMIT | '-9223372036854775809', '-0', '00', '01', '+1', ' 1', '1 ', '1\x00', '1.0', '', '9223372036854775808', '18446744073709551615' | ERR value is not an integer or out of range | ERR syntax error |
| XREAD COUNT | '-9223372036854775808', '-2', '-1' | accepted | ERR value is not an integer or out of range |
| XREAD COUNT | '00', '01', '9223372036854775808', '18446744073709551615' | ERR value is not an integer or out of range | accepted |
| XREAD BLOCK | '-9223372036854775808', '-2', '-1' | ERR timeout is negative | ERR timeout is not an integer or out of range |
| XREAD BLOCK | '00', '01' | ERR timeout is not an integer or out of range | accepted |
| XREAD BLOCK | '9223372036854775808', '18446744073709551615' | ERR timeout is not an integer or out of range | ERR timeout is out of range |
| XREADGROUP COUNT | '-9223372036854775808', '-2', '-1' | accepted | ERR value is not an integer or out of range |
| XREADGROUP COUNT | '00', '01', '9223372036854775808', '18446744073709551615' | ERR value is not an integer or out of range | accepted |
| XREADGROUP BLOCK | '-9223372036854775808', '-2', '-1' | ERR timeout is negative | ERR timeout is not an integer or out of range |
| XREADGROUP BLOCK | '00', '01', '9223372036854775808', '18446744073709551615' | ERR timeout is not an integer or out of range | accepted |
| XREADGROUP BLOCK | '9223372036854775807' | ERR timeout is out of range | accepted |
| XPENDING IDLE | '-9223372036854775808', '-2', '-1' | accepted | ERR value is not an integer or out of range |
| XPENDING IDLE | '00', '01', '9223372036854775808', '18446744073709551615' | ERR value is not an integer or out of range | accepted |
| XPENDING COUNT | '-0', '00', '01' | ERR value is not an integer or out of range | accepted |
| XCLAIM IDLE | '-9223372036854775808', '-2', '-1' | accepted | ERR Invalid IDLE option argument for XCLAIM |
| XCLAIM IDLE | '00', '01', '9223372036854775808', '18446744073709551615' | ERR Invalid IDLE option argument for XCLAIM | accepted |
| XCLAIM TIME | '-9223372036854775808', '-2', '-1' | accepted | ERR Invalid TIME option argument for XCLAIM |
| XCLAIM TIME | '00', '01', '9223372036854775808', '18446744073709551615' | ERR Invalid TIME option argument for XCLAIM | accepted |
| XCLAIM RETRYCOUNT | '-9223372036854775808', '-2', '-1' | accepted | ERR Invalid RETRYCOUNT option argument for XCLAIM |
| XCLAIM RETRYCOUNT | '00', '01', '9223372036854775808', '18446744073709551615' | ERR Invalid RETRYCOUNT option argument for XCLAIM | accepted |
| XAUTOCLAIM COUNT | '01', '9223372036854775807', '9223372036854775808', '18446744073709551615' | ERR COUNT must be > 0 | accepted |
| XINFO FULL COUNT | '-9223372036854775809', '-0', '+1', ' 1', '1 ', '1\x00', '1.0', '' | ERR value is not an integer or out of range | ERR syntax error |
| XINFO FULL COUNT | '-9223372036854775808', '-2', '-1' | accepted | ERR syntax error |
| XINFO FULL COUNT | '00', '01', '9223372036854775808', '18446744073709551615' | ERR value is not an integer or out of range | accepted |
| XADD MINID | '+0', '1-+1', '1\x00' | accepted | ERR Invalid stream ID specified as stream command argument |
| XTRIM MINID | '+0', '1-+1', '1\x00' | accepted | ERR Invalid stream ID specified as stream command argument |
| XCLAIM LASTID | '+0', '1-+1', '1\x00' | accepted | ERR Invalid stream ID specified as stream command argument |
| XSETID MAXDELETEDID | '+0', '1-+1', '1\x00' | accepted | ERR Invalid stream ID specified as stream command argument |
| XADD s MAXLEN 10 MAXLEN 2 4-0 f v | '0' | ERR syntax error, MAXLEN and MINID options at the same time are not compatible | ERR syntax error |
| XTRIM s MAXLEN 10 MAXLEN 2 | '1' | ERR syntax error, MAXLEN and MINID options at the same time are not compatible | ERR syntax error |
| XRANGE s - + COUNT 1 COUNT 2 | '2' | accepted | ERR wrong number of arguments for 'xrange' command |
| XREAD COUNT 1 COUNT 2 STREAMS s 0 | '3' | accepted | ERR syntax error |
| XREAD BLOCK 0 BLOCK 1 STREAMS s 0 | '4' | accepted | ERR syntax error |
| XREADGROUP GROUP g c COUNT 1 COUNT 2 STREAMS s 0 | '5' | accepted | ERR syntax error |
| XREADGROUP GROUP g c BLOCK 0 BLOCK 1 STREAMS s 0 | '6' | accepted | ERR syntax error |
| XCLAIM s g c2 0 1-0 IDLE 0 IDLE 1 JUSTID | '7' | accepted | ERR syntax error |
| XCLAIM s g c2 0 1-0 TIME 0 TIME 1 JUSTID | '8' | accepted | ERR syntax error |
| XCLAIM s g c2 0 1-0 RETRYCOUNT 1 RETRYCOUNT 2 JUSTID | '9' | accepted | ERR syntax error |
| XAUTOCLAIM s g c2 0 0 COUNT 1 COUNT 2 JUSTID | '10' | accepted | ERR wrong number of arguments for 'xautoclaim' command |
| XGROUP CREATE s g2 0 ENTRIESREAD 1 ENTRIESREAD 2 | '11' | ERR unknown subcommand or wrong number of arguments for 'CREATE'. Try XGROUP HELP. | ERR syntax error |
| XGROUP SETID s g 0 ENTRIESREAD 1 ENTRIESREAD 2 | '12' | ERR unknown subcommand or wrong number of arguments for 'SETID'. Try XGROUP HELP. | ERR syntax error |
| XSETID s 3-0 ENTRIESADDED 4 ENTRIESADDED 5 | '13' | accepted | ERR syntax error |
| XINFO STREAM s FULL COUNT 1 COUNT 2 | '14' | ERR unknown subcommand or wrong number of arguments for 'STREAM'. Try XINFO HELP. | ERR syntax error |
| XADD s NOMKSTREAM NOMKSTREAM 4-0 f v | '15' | accepted | ERR syntax error |
| XGROUP CREATE s g2 0 MKSTREAM MKSTREAM | '16' | accepted | ERR syntax error |
| XCLAIM s g c2 0 1-0 FORCE FORCE JUSTID | '17' | accepted | ERR syntax error |
| XCLAIM s g c2 0 1-0 JUSTID JUSTID | '18' | accepted | ERR syntax error |
| XAUTOCLAIM s g c2 0 0 JUSTID JUSTID | '19' | accepted | ERR syntax error |
| XREADGROUP GROUP g c NOACK NOACK STREAMS s 0 | '20' | accepted | ERR syntax error |
| XREADGROUP GROUP g c GROUP g c STREAMS s 0 | '21' | accepted | ERR syntax error |
