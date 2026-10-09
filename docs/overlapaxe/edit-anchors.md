# Removal/edit anchors

Every modified source/test/harness/document hunk is indexed below. PRE coordinates refer to `6b50f447fcc5be467e9314d7c602b688755957b9`; POST coordinates refer to the final lane tree. The complete original feature matches are in inventory.md and references-before.txt.gz. Cell count details are separate.


## GATES.md

- `@@ -16,3 +16,3 @@ No pattern kill, other worktree edit, full gate, or automatic reference replacem`
- `@@ -45,3 +45,2 @@ Assertions require:`
- `@@ -74 +73 @@ implementation. No rejection is marked expected, skipped, or passed by these row`
- `@@ -224 +223 @@ invoke `tests/gate.sh` or run the full gate.`

## Makefile

- `@@ -434 +434 @@ build/rehash-waits-unit: tests/rehash_waits_unit.cc $(CORE_TEST_OBJ) $(wildcard`
- `@@ -654 +654 @@ WB_RULE_POLICY_CONTROLS := scatter-exit fastpath staged-clause staged-source sub`
- `@@ -684 +684 @@ build/wb-rule-units: build/wb-rule-unit build/wb-rule-db0-unit build/wb-rule-pha`

## README.md

- `@@ -123 +123 @@ Important defaults, before any overrides:`

## docs/ARCHITECTURE.md

- `@@ -32 +32 @@ whose IO threads remain shard-less (`src/main.cc:325`, `src/core/rl2s.cc:97`,`
- `@@ -35 +35 @@ whose IO threads remain shard-less (`src/main.cc:325`, `src/core/rl2s.cc:97`,`

## docs/CONFIGURATION.md

- `@@ -50 +49,0 @@ the allowed CPU set and complete SMT sibling units (`src/core/placement.h:73`).`
- `@@ -54,2 +53,2 @@ the allowed CPU set and complete SMT sibling units (`src/core/placement.h:73`).`
- `@@ -68 +67 @@ to the valueless `--no-pin`. A later `pin yes` does not undo an earlier `pin no``
- `@@ -297 +295,0 @@ shards 16`
- `@@ -319 +317 @@ From another terminal: `redis-cli -p 6399 PING`,`

## docs/FINDINGS.md

- `@@ -19 +19 @@ These are the five contradicted claims identified by the cmd-server audit`
- `@@ -64 +64 @@ Read-local has complete runtimes in both modes (`src/main.cc:325`,`

## src/cmd/t_server.cc

- `@@ -338,2 +337,0 @@ void init_config(const Config& cfg) {`
- `@@ -2103 +2101 @@ void cmd_info(Shard&, Op& op) {`
- `@@ -2109,2 +2106,0 @@ void cmd_info(Shard&, Op& op) {`
- `@@ -2155,2 +2151 @@ void cmd_info(Shard&, Op& op) {`

## src/core/boot_support.h

- `@@ -26 +26 @@ void print_boot_presentation(ServerState& srv, std::FILE* out = stdout) {`
- `@@ -28 +28 @@ void print_boot_presentation(ServerState& srv, std::FILE* out = stdout) {`
- `@@ -32 +32 @@ void print_boot_presentation(ServerState& srv, std::FILE* out = stdout) {`
- `@@ -34 +34 @@ void print_boot_presentation(ServerState& srv, std::FILE* out = stdout) {`
- `@@ -39 +39 @@ void print_boot_presentation(ServerState& srv, std::FILE* out = stdout) {`
- `@@ -41 +41 @@ void print_boot_presentation(ServerState& srv, std::FILE* out = stdout) {`

## src/core/config.h

- `@@ -354,5 +354 @@ struct Config {`
- `@@ -840,6 +835,0 @@ inline int parse_config_args(const std::vector<const char*>& args, Config& cfg,`
- `@@ -1151 +1141 @@ inline int parse_config_args(const std::vector<const char*>& args, Config& cfg,`
- `@@ -1153 +1142,0 @@ inline int parse_config_args(const std::vector<const char*>& args, Config& cfg,`
- `@@ -1240,4 +1228,0 @@ inline int validate_config(const Config& cfg) {`

## src/core/ex_loop.h

- `@@ -2230,8 +2230,4 @@ private:`
- `@@ -2249 +2245 @@ private:`
- `@@ -2252,3 +2248,3 @@ private:`
- `@@ -2305,2 +2301,2 @@ private:`

## src/core/genthread.cc

- `@@ -2 +2 @@`
- `@@ -44,2 +44 @@ void IoLoop::run_fused() {`
- `@@ -48,2 +47,2 @@ void IoLoop::run_fused() {`
- `@@ -51,2 +50,2 @@ void IoLoop::run_fused() {`
- `@@ -57,2 +56,2 @@ void IoLoop::run_fused() {`
- `@@ -60,2 +59,2 @@ void IoLoop::run_fused() {`
- `@@ -64,4 +63,2 @@ void IoLoop::run_fused() {`

## src/core/genthread_pipeline.h

- `@@ -8 +8 @@ namespace tomo {`

## src/core/io_loop.h

- `@@ -29 +28,0 @@`
- `@@ -409 +407,0 @@ public:`
- `@@ -415,2 +413,2 @@ public:`
- `@@ -418,2 +416,2 @@ public:`
- `@@ -424,2 +422,2 @@ public:`
- `@@ -427,2 +425,2 @@ public:`
- `@@ -434,2 +432 @@ public:`
- `@@ -504,2 +501 @@ private:`
- `@@ -507,3 +502,0 @@ private:`
- `@@ -513 +505,0 @@ private:`
- `@@ -529,4 +520,0 @@ private:`
- `@@ -570,4 +557,0 @@ private:`
- `@@ -609 +593 @@ private:`
- `@@ -614 +598 @@ private:`
- `@@ -617 +601 @@ private:`
- `@@ -638,6 +622 @@ private:`
- `@@ -677,8 +656 @@ private:`
- `@@ -699,5 +671 @@ private:`
- `@@ -705,8 +673 @@ private:`
- `@@ -738 +699 @@ private:`
- `@@ -744 +705 @@ private:`
- `@@ -902 +863 @@ private:`
- `@@ -910 +871 @@ private:`
- `@@ -925 +886 @@ private:`
- `@@ -986 +947 @@ private:`
- `@@ -996 +957 @@ private:`
- `@@ -999 +960 @@ private:`
- `@@ -1003 +964 @@ private:`
- `@@ -1103 +1064 @@ private:`
- `@@ -1105 +1066 @@ private:`
- `@@ -1110 +1071 @@ private:`
- `@@ -1112 +1073 @@ private:`
- `@@ -1114 +1075 @@ private:`
- `@@ -1119 +1080 @@ private:`
- `@@ -1144 +1105 @@ private:`
- `@@ -1146 +1107 @@ private:`
- `@@ -1148 +1109 @@ private:`
- `@@ -1150 +1111 @@ private:`
- `@@ -1154 +1115 @@ private:`
- `@@ -1159 +1120 @@ private:`
- `@@ -1162 +1123 @@ private:`
- `@@ -1164 +1125 @@ private:`
- `@@ -1167 +1128 @@ private:`
- `@@ -1260 +1221 @@ private:`
- `@@ -1280 +1241 @@ private:`
- `@@ -1287 +1248 @@ private:`
- `@@ -1302 +1263 @@ private:`
- `@@ -1309 +1270 @@ private:`
- `@@ -1367 +1328 @@ private:`
- `@@ -1372 +1333 @@ private:`
- `@@ -2277 +2238 @@ private:`
- `@@ -2328 +2289 @@ private:`
- `@@ -2331 +2292 @@ private:`
- `@@ -2333 +2294 @@ private:`
- `@@ -2354 +2315 @@ private:`
- `@@ -2391 +2352 @@ private:`
- `@@ -2406 +2367 @@ private:`
- `@@ -2437 +2398 @@ private:`
- `@@ -2445 +2406 @@ private:`
- `@@ -2457 +2418 @@ private:`
- `@@ -2487 +2448 @@ private:`
- `@@ -2499 +2460 @@ private:`
- `@@ -2502 +2463 @@ private:`
- `@@ -2510 +2471 @@ private:`
- `@@ -2516 +2477 @@ private:`
- `@@ -2523 +2484 @@ private:`
- `@@ -2531 +2492 @@ private:`
- `@@ -2535 +2496 @@ private:`
- `@@ -2555 +2516 @@ private:`
- `@@ -3063 +3024 @@ private:`
- `@@ -3066 +3027 @@ private:`
- `@@ -3069 +3030 @@ private:`
- `@@ -3141 +3101,0 @@ private:`
- `@@ -3160,2 +3120,2 @@ private:`
- `@@ -4038 +3998 @@ ordinary_shard_ready:`
- `@@ -4041,2 +4001 @@ ordinary_shard_ready:`
- `@@ -4207,25 +4165,0 @@ ordinary_shard_ready:`
- `@@ -4292,408 +4225,0 @@ ordinary_shard_ready:`
- `@@ -4828 +4354 @@ ordinary_shard_ready:`
- `@@ -4831 +4357 @@ ordinary_shard_ready:`
- `@@ -4834 +4360 @@ ordinary_shard_ready:`
- `@@ -4841 +4367 @@ ordinary_shard_ready:`
- `@@ -4844 +4370 @@ ordinary_shard_ready:`
- `@@ -4847 +4373 @@ ordinary_shard_ready:`
- `@@ -5354 +4880 @@ ordinary_shard_ready:`
- `@@ -5356,2 +4882 @@ ordinary_shard_ready:`
- `@@ -5527,2 +5052 @@ public:`
- `@@ -5535 +5059 @@ public:`
- `@@ -5537 +5061 @@ public:`
- `@@ -5539 +5063 @@ public:`
- `@@ -5541 +5065 @@ public:`
- `@@ -5543 +5067 @@ public:`
- `@@ -5545 +5069 @@ public:`
- `@@ -5547,5 +5071 @@ public:`
- `@@ -5553 +5073 @@ public:`
- `@@ -5555 +5075 @@ public:`
- `@@ -5557 +5077 @@ public:`
- `@@ -5559 +5079 @@ public:`
- `@@ -5561 +5081 @@ public:`

## src/core/iopipe_pipeline.h

- `@@ -1,111 +0,0 @@`

## src/core/orthog.h

- `@@ -25,2 +24,0 @@ struct ReorderResult {`
- `@@ -28,2 +26 @@ struct alignas(64) ModeScheduleStats {`
- `@@ -34 +31 @@ struct alignas(64) ModeScheduleStats {`
- `@@ -43,5 +39,0 @@ struct alignas(64) ModeScheduleStats {`
- `@@ -57,2 +48,0 @@ static_assert(sizeof(ModeScheduleStats) == 64);`
- `@@ -63 +52,0 @@ static_assert(offsetof(ModeScheduleStats, reorder_max_batch) == 40);`
- `@@ -69,11 +57,0 @@ inline void append_mode_schedule_info(std::string& body, const ModeScheduleStats`
- `@@ -81,5 +59,2 @@ inline void append_mode_schedule_info(std::string& body, const ModeScheduleStats`

## src/core/reorder.cc

- `@@ -67 +67 @@ uint32_t ExLoopT<Fused>::r7_drain_tasks_impl(bool unmasked) {`
- `@@ -727,2 +727 @@ uint32_t ExLoopT<Fused>::r7_sweep() {`
- `@@ -731,3 +729,0 @@ void IoLoop::r7_run_loop() {`
- `@@ -746 +741,0 @@ void IoLoop::r7_run_loop() {`
- `@@ -762,4 +756,0 @@ void IoLoop::r7_run_loop() {`
- `@@ -803,4 +793,0 @@ void IoLoop::r7_run_loop() {`
- `@@ -842 +829 @@ void IoLoop::r7_run_loop() {`
- `@@ -847 +834 @@ void IoLoop::r7_run_loop() {`
- `@@ -850 +837 @@ void IoLoop::r7_run_loop() {`
- `@@ -871,6 +858 @@ void IoLoop::r7_run_loop() {`
- `@@ -910,8 +892 @@ void IoLoop::r7_run_loop() {`
- `@@ -932,5 +907 @@ void IoLoop::r7_run_loop() {`
- `@@ -938,8 +909 @@ void IoLoop::r7_run_loop() {`
- `@@ -971 +935 @@ void IoLoop::r7_run_loop() {`
- `@@ -977 +941 @@ void IoLoop::r7_run_loop() {`
- `@@ -1187 +1151 @@ uint32_t IoLoop::r7_flush_ready() {`
- `@@ -1190 +1154 @@ uint32_t IoLoop::r7_flush_ready() {`
- `@@ -1193 +1157 @@ uint32_t IoLoop::r7_flush_ready() {`
- `@@ -1200 +1164 @@ uint32_t IoLoop::r7_flush_ready() {`
- `@@ -1203 +1167 @@ uint32_t IoLoop::r7_flush_ready() {`
- `@@ -1206 +1170 @@ uint32_t IoLoop::r7_flush_ready() {`
- `@@ -1296 +1260 @@ uint32_t IoLoop::r7_flush_ready() {`
- `@@ -1355 +1319 @@ void IoLoop::r7_admit_fd(int fd, UrKind kind) {`
- `@@ -1360 +1324 @@ void IoLoop::r7_admit_fd(int fd, UrKind kind) {`
- `@@ -1364 +1328 @@ void IoLoop::r7_admit_fd(int fd, UrKind kind) {`
- `@@ -1416 +1380 @@ void IoLoop::r7_adopt_client(Client* c, bool unix_socket, bool tls_socket) {`
- `@@ -1419 +1383 @@ void IoLoop::r7_adopt_client(Client* c, bool unix_socket, bool tls_socket) {`
- `@@ -1421 +1385 @@ void IoLoop::r7_adopt_client(Client* c, bool unix_socket, bool tls_socket) {`
- `@@ -1430 +1394 @@ void IoLoop::r7_adopt_client(Client* c, bool unix_socket, bool tls_socket) {`
- `@@ -1439 +1403 @@ void IoLoop::r7_arm_tls_recv(Client* c) {`
- `@@ -1454 +1418 @@ void IoLoop::r7_arm_tls_recv(Client* c) {`
- `@@ -1478 +1442 @@ void IoLoop::r7_arm_tls_recv(Client* c) {`
- `@@ -1510 +1474 @@ bool IoLoop::r7_drive_tls(Client* c) {`
- `@@ -1518 +1482 @@ bool IoLoop::r7_drive_tls(Client* c) {`
- `@@ -1530 +1494 @@ bool IoLoop::r7_drive_tls(Client* c) {`
- `@@ -1560 +1524 @@ bool IoLoop::r7_drive_tls(Client* c) {`
- `@@ -1572 +1536 @@ bool IoLoop::r7_drive_tls(Client* c) {`
- `@@ -1575 +1539 @@ bool IoLoop::r7_drive_tls(Client* c) {`
- `@@ -1583 +1547 @@ bool IoLoop::r7_drive_tls(Client* c) {`
- `@@ -1589 +1553 @@ bool IoLoop::r7_drive_tls(Client* c) {`
- `@@ -1596 +1560 @@ bool IoLoop::r7_drive_tls(Client* c) {`
- `@@ -1612 +1576 @@ uint32_t IoLoop::r7_epoll_accept(UrKind kind) {`
- `@@ -1616 +1580 @@ uint32_t IoLoop::r7_epoll_accept(UrKind kind) {`
- `@@ -1627 +1591 @@ uint32_t IoLoop::r7_epoll_pass(int timeout_ms) {`
- `@@ -1630 +1594 @@ uint32_t IoLoop::r7_epoll_pass(int timeout_ms) {`
- `@@ -1634 +1598 @@ uint32_t IoLoop::r7_epoll_pass(int timeout_ms) {`
- `@@ -1699,165 +1663 @@ uint32_t IoLoop::r7_epoll_pass(int timeout_ms) {`
- `@@ -1884 +1684 @@ void IoLoop::r7_on_accept(io_uring_cqe* cqe, UrKind kind) {`
- `@@ -1888 +1688 @@ void IoLoop::r7_on_accept(io_uring_cqe* cqe, UrKind kind) {`
- `@@ -1891 +1691 @@ void IoLoop::r7_on_cqe(io_uring_cqe* cqe) {`
- `@@ -1896 +1696 @@ void IoLoop::r7_on_cqe(io_uring_cqe* cqe) {`
- `@@ -1898 +1698 @@ void IoLoop::r7_on_cqe(io_uring_cqe* cqe) {`
- `@@ -1900 +1700 @@ void IoLoop::r7_on_cqe(io_uring_cqe* cqe) {`
- `@@ -1905 +1705 @@ void IoLoop::r7_on_cqe(io_uring_cqe* cqe) {`
- `@@ -1930 +1730 @@ void IoLoop::r7_on_cqe(io_uring_cqe* cqe) {`
- `@@ -1932 +1732 @@ void IoLoop::r7_on_cqe(io_uring_cqe* cqe) {`
- `@@ -1934 +1734 @@ void IoLoop::r7_on_cqe(io_uring_cqe* cqe) {`
- `@@ -1936 +1736 @@ void IoLoop::r7_on_cqe(io_uring_cqe* cqe) {`
- `@@ -1940 +1740 @@ void IoLoop::r7_on_cqe(io_uring_cqe* cqe) {`
- `@@ -1945 +1745 @@ void IoLoop::r7_on_cqe(io_uring_cqe* cqe) {`
- `@@ -1948 +1748 @@ void IoLoop::r7_on_cqe(io_uring_cqe* cqe) {`
- `@@ -1950 +1750 @@ void IoLoop::r7_on_cqe(io_uring_cqe* cqe) {`
- `@@ -1953 +1753 @@ void IoLoop::r7_on_cqe(io_uring_cqe* cqe) {`
- `@@ -1976 +1776 @@ void IoLoop::r7_on_cqe(io_uring_cqe* cqe) {`
- `@@ -2014 +1814 @@ void IoLoop::r7_on_recv(Client* c, int res) {`
- `@@ -2029 +1829 @@ void IoLoop::r7_on_recv(Client* c, int res) {`
- `@@ -2050 +1850 @@ void IoLoop::r7_on_tls_recv(Client* c, int res) {`
- `@@ -2054 +1854 @@ void IoLoop::r7_on_tls_recv(Client* c, int res) {`
- `@@ -2063 +1863 @@ void IoLoop::r7_on_tls_socket_poll(Client* c, int res, TlsOp wanted) {`
- `@@ -2067 +1867 @@ void IoLoop::r7_on_tls_socket_poll(Client* c, int res, TlsOp wanted) {`
- `@@ -2072 +1872 @@ IoLoop::DispatchResult IoLoop::r7_parse_and_dispatch(Client* c) {`
- `@@ -2079 +1879 @@ IoLoop::DispatchResult IoLoop::r7_parse_and_dispatch(Client* c) {`
- `@@ -2082 +1882 @@ IoLoop::DispatchResult IoLoop::r7_parse_and_dispatch(Client* c) {`
- `@@ -2154 +1953,0 @@ IoLoop::DispatchResult IoLoop::r7_parse_and_dispatch(Client* c) {`
- `@@ -2173,2 +1972,2 @@ IoLoop::DispatchResult IoLoop::r7_parse_and_dispatch(Client* c) {`
- `@@ -3068 +2867 @@ ordinary_shard_ready:`
- `@@ -3071,2 +2870 @@ ordinary_shard_ready:`
- `@@ -3107,2 +2905 @@ void IoLoop::run_fused_reordered() {`
- `@@ -3111,2 +2908,2 @@ void IoLoop::run_fused_reordered() {`
- `@@ -3114,2 +2911,2 @@ void IoLoop::run_fused_reordered() {`
- `@@ -3120,2 +2917,2 @@ void IoLoop::run_fused_reordered() {`
- `@@ -3123,2 +2920,2 @@ void IoLoop::run_fused_reordered() {`
- `@@ -3127,4 +2924,2 @@ void IoLoop::run_fused_reordered() {`

## src/core/rl2s.cc

- `@@ -76 +76 @@ void IoLoop::run_split_read_local_baseline() {`
- `@@ -79,2 +79,2 @@ void IoLoop::run_split_read_local_baseline() {`
- `@@ -82,2 +82,2 @@ void IoLoop::run_split_read_local_baseline() {`
- `@@ -86,2 +86,2 @@ void IoLoop::run_split_read_local_baseline() {`
- `@@ -89,2 +89,2 @@ void IoLoop::run_split_read_local_baseline() {`
- `@@ -93,2 +93 @@ void IoLoop::run_split_read_local_baseline() {`

## src/core/server.h

- `@@ -402 +402 @@ public:`

## src/core/wb_rule.h

- `@@ -131,22 +130,0 @@ struct Phase2 {`

## src/net/wb.h

- `@@ -754,2 +753,0 @@ private:`

## tests/abba_experiments.py

- `@@ -230,2 +230,2 @@ def prime_snapshot(args, fixture, output, cell):`

## tests/abba_saturation_controls.py

- `@@ -349 +349 @@ def idle(args):`

## tests/abbagate.py

- `@@ -1420,20 +1420,3 @@ def accepted(binary, name, value):`
- `@@ -1443 +1426,14 @@ class NotComparable(RuntimeError):`
- `@@ -1447,3 +1443,6 @@ def knob_plan(cell, support):`
- `@@ -1453 +1452 @@ def knob_plan(cell, support):`
- `@@ -1456,21 +1455,4 @@ def knob_plan(cell, support):`
- `@@ -1478 +1460,3 @@ def knob_plan(cell, support):`
- `@@ -1886,0 +1871 @@ class Runner:`
- `@@ -2468,2 +2453 @@ def main(args, *, diagnostic_monitor=None, diagnostic_profile=0,`
- `@@ -3130 +3114 @@ def self_test():`
- `@@ -3133 +3117 @@ def self_test():`
- `@@ -3144 +3128 @@ def self_test():`
- `@@ -3157 +3141 @@ def self_test():`
- `@@ -3905 +3889 @@ def self_test():`
- `@@ -4078,15 +4062,22 @@ def self_test():`
- `@@ -4093,0 +4085,8 @@ def self_test():`
- `@@ -4217,2 +4216,2 @@ def self_test():`
- `@@ -4220,5 +4219,5 @@ def self_test():`
- `@@ -4770,2 +4769,2 @@ def self_test():`

## tests/boot_support_checks.inc

- `@@ -64 +63,0 @@ void presentation() {`
- `@@ -74 +72,0 @@ void presentation() {`
- `@@ -93 +91 @@ void presentation() {`
- `@@ -115 +113 @@ void presentation() {`

## tests/bplus.py

- `@@ -5 +5 @@ Boot requirement:`
- `@@ -541,2 +540,0 @@ def main():`

## tests/config_parser_test.cc

- `@@ -114 +114 @@ void documented_example() {`
- `@@ -401,10 +400,0 @@ int main() {`
- `@@ -412,6 +402,3 @@ int main() {`
- `@@ -422,2 +409 @@ int main() {`
- `@@ -425,15 +411,6 @@ int main() {`
- `@@ -441,13 +418,9 @@ int main() {`
- `@@ -455,2 +428 @@ int main() {`
- `@@ -461 +433 @@ int main() {`
- `@@ -483 +455 @@ int main() {`
- `@@ -488 +460 @@ int main() {`
- `@@ -496,2 +467,0 @@ int main() {`
- `@@ -502 +471,0 @@ int main() {`
- `@@ -505,2 +474,2 @@ int main() {`
- `@@ -508,2 +477,2 @@ int main() {`

## tests/feature_gate.py

- `@@ -30,3 +30,3 @@ MODES = ('1s', '2s')`
- `@@ -43 +43 @@ def refuses_boot(cell):`
- `@@ -51,2 +51,2 @@ def config(cell, cpu_list, ratio):`
- `@@ -54,2 +54,2 @@ def config(cell, cpu_list, ratio):`
- `@@ -61 +61 @@ def config(cell, cpu_list, ratio):`
- `@@ -83 +83 @@ def inventory(cpu_list, ratio):`
- `@@ -158,4 +158,3 @@ def check_activity(before, after, knobs, nthreads, cross_owner):`
- `@@ -165 +164 @@ def check_activity(before, after, knobs, nthreads, cross_owner):`
- `@@ -167,11 +165,0 @@ def check_activity(before, after, knobs, nthreads, cross_owner):`

## tests/gate.sh

- `@@ -284,2 +284,4 @@ python3 tests/gate_history.py prepare --history "$ROW_HISTORY" "${HISTORY_ARGS[@`
- `@@ -1034,2 +1036,2 @@ plan_jobs(){`
- `@@ -1445 +1447 @@ job_wb_rule_units(){`
- `@@ -1848 +1850 @@ for WAIT_MODE in split fused; do`
- `@@ -1851 +1853 @@ for WAIT_MODE in split fused; do`
- `@@ -1931,2 +1933 @@ local AT=${1##*-}`
- `@@ -1935 +1936 @@ local AT=${1##*-}`
- `@@ -3361 +3362 @@ collect_job tls`
- `@@ -3369,2 +3370,2 @@ for FM in 1s 2s; do`
- `@@ -3397 +3398 @@ if [ -f "$RUN_DIR/unit-ready/tailgen" ] &&`

## tests/gateprod.py

- `@@ -34,2 +34,3 @@ IDS = tuple(f"h{i:02}" for i in range(1, 33))`
- `@@ -72,0 +74,2 @@ def knobs(cell):`
- `@@ -74 +77 @@ def knobs(cell):`
- `@@ -303 +306 @@ def self_test():`

## tests/gates_test.py

- `@@ -32 +32 @@ def feature_evidence():`
- `@@ -34 +34 @@ def feature_evidence():`
- `@@ -38 +38 @@ def feature_evidence():`
- `@@ -41 +40,0 @@ def feature_evidence():`
- `@@ -52 +51 @@ def perf_evidence():`
- `@@ -70 +69 @@ class FeatureFailures(unittest.TestCase):`
- `@@ -109 +108 @@ class FeatureFailures(unittest.TestCase):`
- `@@ -115 +114 @@ class FeatureFailures(unittest.TestCase):`
- `@@ -117,10 +115,0 @@ class FeatureFailures(unittest.TestCase):`
- `@@ -128,8 +117,4 @@ class FeatureFailures(unittest.TestCase):`
- `@@ -137 +122 @@ class FeatureFailures(unittest.TestCase):`
- `@@ -139,11 +124 @@ class FeatureFailures(unittest.TestCase):`
- `@@ -150,0 +126,6 @@ class FeatureFailures(unittest.TestCase):`
- `@@ -157,6 +137,0 @@ class FeatureFailures(unittest.TestCase):`
- `@@ -181 +156 @@ class FeatureFailures(unittest.TestCase):`

## tests/knobs.py

- `@@ -20 +20 @@ retired = (`
- `@@ -67 +67 @@ try:`
- `@@ -72 +72 @@ try:`
- `@@ -91 +91 @@ try:`

## tests/lanefull_checks.inc

- `@@ -46 +46 @@`

## tests/legacy_reorder_witness.py

- `@@ -250 +250 @@ def translated_knobs(binary, mode, reorder, read_local=0):`
- `@@ -649 +649 @@ def self_test():`

## tests/load_calibration.py

- `@@ -189 +189 @@ def main(args):`

## tests/mode_equivalence.py

- `@@ -4 +4 @@`
- `@@ -41,2 +41,2 @@ ROOT = Path(__file__).resolve().parents[1]`
- `@@ -153,3 +153,3 @@ def configuration(cell):`
- `@@ -179 +179 @@ def self_test():`
- `@@ -257 +257 @@ def main(argv=None):`
- `@@ -318 +318 @@ def main(argv=None):`

## tests/mode_lane.py

- `@@ -2 +2 @@`
- `@@ -4,3 +4,3 @@`
- `@@ -37 +37 @@ def main():`
- `@@ -40,2 +40,2 @@ def main():`
- `@@ -49 +49 @@ def main():`
- `@@ -53,4 +53,4 @@ def main():`
- `@@ -58,2 +58 @@ def main():`
- `@@ -62 +61 @@ def main():`
- `@@ -69 +68 @@ def main():`
- `@@ -127 +126 @@ def main():`
- `@@ -129 +128 @@ def main():`

## tests/multidb_boundary_unit.cc

- `@@ -46 +46 @@ struct CoreConcurrencyTest {`

## tests/netcmd_config_unit.cc

- `@@ -24,0 +25,6 @@ void knob_matrix() {`
- `@@ -204,0 +211 @@ void test_config_rewrite() {`

## tests/netcmd_unit.cc

- `@@ -396,0 +397,3 @@ struct NetcmdRegression {`
- `@@ -402,0 +406,3 @@ struct NetcmdRegression {`
- `@@ -421,4 +427 @@ struct NetcmdRegression {`
- `@@ -429,4 +432,2 @@ struct NetcmdRegression {`
- `@@ -435,11 +436,5 @@ struct NetcmdRegression {`
- `@@ -455 +449,0 @@ struct NetcmdRegression {`
- `@@ -458 +451,0 @@ struct NetcmdRegression {`
- `@@ -774,0 +768 @@ int main(int argc, char** argv) {`

## tests/orthog.py

- `@@ -4 +4 @@`
- `@@ -39 +39 @@ def main():`
- `@@ -50 +49,0 @@ def main():`
- `@@ -62,2 +61,2 @@ def main():`
- `@@ -65 +63,0 @@ def main():`
- `@@ -67 +65 @@ def main():`
- `@@ -153,6 +150,0 @@ def main():`
- `@@ -162 +154 @@ def main():`
- `@@ -174,13 +166,3 @@ def main():`
- `@@ -190 +172 @@ def main():`
- `@@ -195,4 +177,3 @@ def main():`

## tests/owner_prefetch_unit.cc

- `@@ -11,0 +12,2 @@`
- `@@ -18 +20 @@ struct CoreConcurrencyTest {`
- `@@ -31 +33 @@ struct CoreConcurrencyTest {`
- `@@ -51,2 +53,2 @@ struct CoreConcurrencyTest {`
- `@@ -59,5 +61,7 @@ struct CoreConcurrencyTest {`
- `@@ -69,3 +73,3 @@ struct CoreConcurrencyTest {`
- `@@ -74,2 +78,4 @@ struct CoreConcurrencyTest {`
- `@@ -80 +86 @@ struct CoreConcurrencyTest {`
- `@@ -105,4 +111 @@ struct CoreConcurrencyTest {`
- `@@ -110,2 +112,0 @@ struct CoreConcurrencyTest {`
- `@@ -113,11 +114,2 @@ struct CoreConcurrencyTest {`
- `@@ -128 +120 @@ struct CoreConcurrencyTest {`
- `@@ -130,2 +122,2 @@ struct CoreConcurrencyTest {`
- `@@ -134 +126 @@ struct CoreConcurrencyTest {`
- `@@ -141,2 +133,2 @@ struct CoreConcurrencyTest {`
- `@@ -222,2 +214,3 @@ int main() {`
- `@@ -228,2 +221,2 @@ int main() {`

## tests/perf_gate.py

- `@@ -75 +75 @@ def machine(args):`
- `@@ -110 +110 @@ def summarize_window(before, after, cell, keymax):`

## tests/r7shadow_split_unit.cc

- `@@ -10 +10 @@ template <bool ReadLocal>`
- `@@ -13,3 +13,3 @@ void split(int32_t requested, uint32_t overlap, const std::string& leak) {`
- `@@ -35,6 +35 @@ void split(int32_t requested, uint32_t overlap, const std::string& leak) {`
- `@@ -64,2 +59,2 @@ int main(int argc, char** argv) {`
- `@@ -71 +66 @@ int main(int argc, char** argv) {`
- `@@ -74,4 +69,3 @@ int main(int argc, char** argv) {`

## tests/r7shadow_split_witness.py

- `@@ -46,17 +46,16 @@ def main():`

## tests/r7shadow_sync.py

- `@@ -19 +19 @@ IO = ('run_loop', 'sweep', 'flush_ready', 'admit_fd', 'adopt_client',`
- `@@ -52 +52 @@ def removal_inventory(root):`
- `@@ -141 +141 @@ def envelopes():`

## tests/read_local_lane.py

- `@@ -6 +6 @@ Usage: read_local_lane.py HOST PORT`

## tests/reorder_engagement_unit.cc

- `@@ -35 +35 @@ struct CoreConcurrencyTest {`
- `@@ -57 +56,0 @@ struct CoreConcurrencyTest {`
- `@@ -88 +87 @@ struct CoreConcurrencyTest {`
- `@@ -100 +99 @@ struct CoreConcurrencyTest {`
- `@@ -134,20 +132,0 @@ struct CoreConcurrencyTest {`
- `@@ -162 +141 @@ struct CoreConcurrencyTest {`
- `@@ -165 +144 @@ struct CoreConcurrencyTest {`
- `@@ -187 +165,0 @@ struct CoreConcurrencyTest {`
- `@@ -222,2 +199,0 @@ struct CoreConcurrencyTest {`
- `@@ -229 +205 @@ struct CoreConcurrencyTest {`
- `@@ -231 +207 @@ struct CoreConcurrencyTest {`
- `@@ -238,2 +214,2 @@ struct CoreConcurrencyTest {`
- `@@ -252,2 +228,2 @@ struct CoreConcurrencyTest {`
- `@@ -297,2 +273,2 @@ struct CoreConcurrencyTest {`
- `@@ -303 +279 @@ struct CoreConcurrencyTest {`
- `@@ -306 +282 @@ struct CoreConcurrencyTest {`
- `@@ -308,2 +284,2 @@ struct CoreConcurrencyTest {`
- `@@ -314,2 +290,2 @@ struct CoreConcurrencyTest {`
- `@@ -346,2 +322,2 @@ struct CoreConcurrencyTest {`
- `@@ -381,2 +357,2 @@ struct CoreConcurrencyTest {`
- `@@ -386 +362 @@ struct CoreConcurrencyTest {`
- `@@ -468 +444 @@ struct CoreConcurrencyTest {`
- `@@ -520 +496 @@ struct CoreConcurrencyTest {`
- `@@ -542 +518 @@ struct CoreConcurrencyTest {`
- `@@ -554 +530 @@ struct CoreConcurrencyTest {`
- `@@ -601 +577 @@ int main(int argc, char** argv) {`
- `@@ -603,2 +579,2 @@ int main(int argc, char** argv) {`
- `@@ -606 +582 @@ int main(int argc, char** argv) {`
- `@@ -609 +585 @@ int main(int argc, char** argv) {`
- `@@ -611,4 +587,4 @@ int main(int argc, char** argv) {`

## tests/reorder_flip.py

- `@@ -6 +6 @@ workload and acceptance oracle. Explicitly record both switches: the original`
- `@@ -53,2 +53 @@ def check_settings(settings, args, pid):`
- `@@ -69 +67,0 @@ def main():`
- `@@ -103,2 +100,0 @@ def main():`

## tests/reorder_scope.py

- `@@ -163 +163 @@ inline std::string metadata(const Config& cfg, const Op* op, const char* path,`

## tests/reordertrim.py

- `@@ -204,19 +204,19 @@ def boot(args):`

## tests/resizefix.py

- `@@ -202 +202 @@ def main():`

## tests/rl2s.py

- `@@ -6 +6 @@ Run against a maintainer-started, otherwise idle server:`

## tests/signalacct_live.py

- `@@ -124 +124 @@ def attempt(args, index):`
- `@@ -196 +195,0 @@ def main():`

## tests/signalacct_live_test.py

- `@@ -17 +17 @@ class Driver(unittest.TestCase):`
- `@@ -73 +73 @@ class Driver(unittest.TestCase):`

## tests/splitlocal_checks.py

- `@@ -30 +30 @@ def emit(root, output):`
- `@@ -46 +46 @@ def emit(root, output):`
- `@@ -48 +48 @@ def emit(root, output):`
- `@@ -57,2 +57 @@ def emit(root, output):`
- `@@ -61 +60 @@ def emit(root, output):`
- `@@ -68 +67 @@ def emit(root, output):`
- `@@ -70 +69 @@ def emit(root, output):`
- `@@ -77,3 +76,2 @@ def emit(root, output):`
- `@@ -94 +92 @@ def check(binary, output):`
- `@@ -96,2 +94,2 @@ def check(binary, output):`

## tests/splitlocal_live.py

- `@@ -72 +72 @@ def instrument(pre, post, output):`
- `@@ -79 +78,0 @@ def probe(host, port, mode, overlap, database, output):`
- `@@ -106 +105 @@ def probe(host, port, mode, overlap, database, output):`
- `@@ -127 +126 @@ if __name__ == '__main__':`
- `@@ -131 +130 @@ if __name__ == '__main__':`

## tests/tailgen_stall.py

- `@@ -44 +44 @@ def run(args):`
- `@@ -147 +147 @@ boot_fused(){`

## tests/ttlcell_test.py

- `@@ -96 +96 @@ def suite(abba):`

## tests/wb_rule_2s_cost.cc

- `@@ -9 +8,0 @@`
- `@@ -13,17 +11,0 @@ void tomo::multi_session_destroy(MultiSession* p) { if (p) std::abort(); }`
- `@@ -39 +20,0 @@ int main(int argc, char** argv) {`
- `@@ -42 +22,0 @@ int main(int argc, char** argv) {`
- `@@ -54 +34 @@ int main(int argc, char** argv) {`
- `@@ -57 +37 @@ int main(int argc, char** argv) {`

## tests/wb_rule_checks.py

- `@@ -27 +26,0 @@ MUTANTS = {`
- `@@ -63,10 +61,0 @@ MUTANTS = {`
- `@@ -124 +113 @@ def check(group, build, controls=True):`
- `@@ -132 +121 @@ def check(group, build, controls=True):`
- `@@ -152 +141 @@ if __name__ == "__main__":`

## tests/wb_rule_completion_unit.cc

- `@@ -125,2 +124,0 @@ struct Loop {`
- `@@ -128,7 +126,3 @@ static bool visit(Loop& loop) {`
- `@@ -217 +211 @@ int main(int argc, char** argv) {`
- `@@ -220 +214 @@ int main(int argc, char** argv) {`

## tests/wb_rule_phase_unit.cc

- `@@ -18 +17,0 @@ static unsigned submissions = 0, submitted_sends = 0;`
- `@@ -99 +98 @@ struct CoreConcurrencyTest {`
- `@@ -182,4 +180,0 @@ struct CoreConcurrencyTest {`
- `@@ -489,4 +484 @@ struct CoreConcurrencyTest {`

## tests/wbland_checks.py

- `@@ -27 +26,0 @@ SERVE = 'wb_rule::Phase2::serve<HasTls, kEp, IoLoop, Fused>(*this)'`
- `@@ -43,16 +41,0 @@ SERVE_GUARD = '''`
- `@@ -86 +68,0 @@ PLUMBING = (`
- `@@ -88,3 +69,0 @@ PLUMBING = (`
- `@@ -98 +76,0 @@ R7_PLUMBING = (`
- `@@ -177,3 +155 @@ def envelope(path, expected_calls, plumbing, guarded):`
- `@@ -215 +191 @@ def source():`
- `@@ -234 +210 @@ SOURCE_CONTROLS = {`
- `@@ -310 +286 @@ def check(group, build, proofs=None):`
- `@@ -314 +290 @@ def check(group, build, proofs=None):`
- `@@ -334,3 +310,3 @@ def check(group, build, proofs=None):`

## tomokv.conf

- `@@ -117,6 +116,0 @@`

## tools/boot_support_controls.py

- `@@ -33 +32,0 @@ def main():`

## tools/exbatch_directed.py

- `@@ -403 +403 @@ def inventory():`
- `@@ -1141 +1141 @@ def run_sample(cell, arm, identities, folder, q, guard=None):`
- `@@ -2288 +2288 @@ def self_test():`

## tools/iopass_validate.py

- `@@ -39 +39 @@ py('persistfix_checks.py')`

## tools/signalacct_artifacts.py

- `@@ -131 +131 @@ def prepare_witness():`

## tools/wb_rule_2s_artifacts.py

- `@@ -21 +21 @@ STUDY = BUILD / 'wbrule2s34-src'`
- `@@ -175 +175 @@ def costs():`
- `@@ -186 +186 @@ def costs():`
