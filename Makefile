CXX      ?= g++
JEDIR    ?= /home/user/Projects/refs/jemalloc/_install
# jemalloc is optional: without it the tree still builds and runs, using the deterministic portable
# size-class table in alloc.h. Set JE=0 to force that path (useful for A/B-ing the allocator).
JE       ?= 1
ifeq ($(JE),1)
  # Prefer the system package; fall back to the copy built from refs/.
  ifneq ($(wildcard /usr/include/jemalloc/jemalloc.h),)
    JEFLAGS := -DTOMO_JEMALLOC
    JELIBS  := -ljemalloc
  else
    JEFLAGS := -DTOMO_JEMALLOC -I$(JEDIR)/include
    JELIBS  := $(JEDIR)/lib/libjemalloc.a -ldl
  endif
else
  JEFLAGS :=
  JELIBS  :=
endif
CXXFLAGS ?= -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread
LDLIBS   ?= -luring -pthread
SRC      := src/main.cc src/net/tls.cc src/cmd/commands.cc src/cmd/glob.cc src/cmd/xshard.cc src/cmd/acl.cc src/cmd/hll.cc src/cmd/t_server.cc src/cmd/t_string.cc src/cmd/t_string_notify.cc src/cmd/t_hash.cc src/cmd/t_hash_ttl.cc \
            src/cmd/t_list.cc src/cmd/t_set.cc src/cmd/t_zset.cc src/cmd/t_zset_ops.cc src/cmd/geo.cc src/cmd/t_stream.cc src/cmd/t_stream_groups.cc src/cmd/scripting.cc src/cmd/functions.cc src/cmd/serialize.cc src/snapshot/snapshot.cc src/persist/aof.cc
SRC      += src/cmd/climon.cc src/cmd/tracking.cc
SRC      += src/cmd/server_tail.cc src/cmd/slowlog.cc src/cmd/lcs.cc src/cmd/info_stats.cc
SRC      += src/cmd/lbsignals.cc
SRC      += src/core/flipctl.cc
SRC      += src/core/genthread.cc
SRC      += src/core/rl2s.cc
SRC      += src/core/lbstall.cc
SRC      += src/core/lbplanner.cc
SRC      += src/cmd/l4prebuild.cc
SRC      += src/cmd/cmdgap.cc
SRC      += src/cmd/pfdebug.cc
SRC      += src/cmd/cmdmeta.cc
SRC      += src/cmd/t_sort.cc
SRC      += src/cmd/multidb.cc
SRC      += src/cmd/storesize.cc
SRC      += src/cmd/multi_admin.cc
# Preserve mainline weak-symbol selection; isolated R7 bodies link last.
SRC      += src/core/reorder.cc
SRC      += src/cmd/geo_store.cc
# Cold DEBUG observer links after existing objects to preserve weak-symbol selection.
SRC      += src/persist/aof_frame_debug.cc
SRC      += src/cmd/aclkeys.cc
# Keep the armed-only witness parser after ordinary objects (weak-symbol selection).
SRC      += src/cmd/blocking_debug.cc
SRC      += src/cmd/objectpread.cc src/cmd/hexpread.cc
SRC      += src/cmd/autharity.cc
SRC      += src/core/fliplisten.cc
SRC      += src/core/shutdown.cc
SRC      += src/cmd/latency_tracking.cc
# The entry wrapper belongs only to server links using --wrap=main.
SERVER_ONLY_SRC := src/core/version.cc
LDLIBS   += -lssl -lcrypto
BUILD_ROOT ?= build
BIN      := $(BUILD_ROOT)/tomokv
OBJ      := $(SRC:%.cc=$(BUILD_ROOT)/%.o)
# Redis 7.4's permissively licensed helpers share the existing Lua VM between
# the two database variants. Compile as C, including the caller's sanitizer flags.
LUA_HELPER_SRC := $(addprefix third_party/lua/helpers/,lua_cjson.c lua_cmsgpack.c lua_bit.c lua_struct.c strbuf.c fpconv.c)
OBJ      += $(LUA_HELPER_SRC:%.c=$(BUILD_ROOT)/%.o)
DB0_OBJ  := $(SRC:%.cc=$(BUILD_ROOT)/db0/%.o)
SERVER_ONLY_OBJ := $(SERVER_ONLY_SRC:%.cc=$(BUILD_ROOT)/%.o)
DB0_SERVER_ONLY_OBJ := $(SERVER_ONLY_SRC:%.cc=$(BUILD_ROOT)/db0/%.o)

ASSERT_MAP := $(BUILD_ROOT)/tomokv.asserts.tsv
ASSERT_SOURCES := $(shell find src third_party/lua/helpers -type f \( -name '*.h' -o -name '*.cc' -o -name '*.inc' -o -name '*.c' -o -name '*.def' \))

ASSERT_DIRS := $(shell find src third_party/lua/helpers -type d)

all: $(BIN) $(ASSERT_MAP)

# The source map is a build artifact: duplicate ids or a Python/C++ hash mismatch
# fail make all. Its mtime also participates in make -q freshness checks.
$(ASSERT_MAP): tools/assert_map.py $(ASSERT_SOURCES) $(ASSERT_DIRS) Makefile
	python3 tools/assert_map.py --output $@ --cxx "$(CXX)"


# Wave 7: compile-only per-unit trials in docs/wave7/budgets and
# docs/wave7/budgets-dispatch preserve headline or lane POST hot bodies where
# changes compose. The second sweep scores dispatch call sites, not just changed
# group counts. Residuals and command-scope counts remain explicit merit inputs.

# Opt-in lottery observation arm. Production sources and default objects remain
# untouched; the copied tree adds only DEBUG-armed counters, never pause points.
build/lottery/tomokv: tools/lottery_build.py tools/assert_map.py tests/lottery_hooks.h $(SRC) $(SERVER_ONLY_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	python3 tools/lottery_build.py build/lottery/source
	$(MAKE) -C build/lottery/source BUILD_ROOT=$(abspath build/lottery/objects) all
	cp build/lottery/objects/tomokv $@

build/lottery/tomokv-asan: build/lottery/tomokv
	$(MAKE) -C build/lottery/source BUILD_ROOT=$(abspath build/lottery/asan) JE=0 CXXFLAGS='$(CXXFLAGS) -fsanitize=address,undefined -fno-omit-frame-pointer -O1' all
	cp build/lottery/asan/tomokv $@

# NT4.2: no server/listener; frozen PRE can compile the same witness with
# -DTOMO_RESPRESUME_PRE and its source root first on the include path.
build/respresume-unit: tests/respresume_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -I. $< -o $@

# AOF ordering schedule control: production contains no fragment-parking hook.
build/aoforder-scheduled: tools/aoforder_schedule.py $(BIN)
	python3 tools/aoforder_schedule.py --objects build --output build/aoforder/scheduled
	cp build/aoforder/scheduled/tomokv $@

# SV4.10: the DEBUG parser and pre-store hook exist only in this copied test
# tree. Default production objects never contain a hook, branch or test state.
build/racefix-climon: tools/racefix_build.py tools/assert_map.py tests/racefix_hook.h $(SRC) $(SERVER_ONLY_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	python3 tools/racefix_build.py build/racefix-climon-source
	$(MAKE) -C build/racefix-climon-source BUILD_ROOT=$(abspath build/racefix-climon-objects) all
	cp build/racefix-climon-objects/tomokv $@

# Optional teardown-only diagnostics; no code or storage in normal binaries.
.PHONY: connreset-trace
connreset-trace:
	$(MAKE) BUILD_ROOT=build/connreset/trace CXXFLAGS='$(CXXFLAGS) -DTOMO_CONNRESET_TRACE' all

# PS1/PS2/PS14 schedules call the actual AOF implementation without starting a
# listener or ring. Controls are throwaway source copies with one fix removed.
PERSISTFIX_CONTROLS := old-ack old-close no-refusal
PERSISTFIX_CORE = $(filter-out build/src/main.o build/src/persist/aof.o,$(OBJ))
build/persistfix/aof-test.o: src/persist/aof.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_PERSISTFIX_TEST -I. -c $< -o $@
build/persistfix/unit.o: tests/persistfix_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_PERSISTFIX_TEST -I. -c $< -o $@
build/persistfix-unit: build/persistfix/unit.o build/persistfix/aof-test.o $(PERSISTFIX_CORE)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
build/persistfix-controls/%/aof.cc: tools/persistfix_controls.py src/persist/aof.cc Makefile
	@mkdir -p $(dir $@)
	python3 tools/persistfix_controls.py $* $@
build/persistfix-controls/%/aof.o: build/persistfix-controls/%/aof.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_PERSISTFIX_TEST -Isrc/persist -I. -c build/persistfix-controls/$*/aof.cc -o $@
build/persistfix-controls/%/db0-aof.o: build/persistfix-controls/%/aof.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -DTOMO_PERSISTFIX_TEST -Isrc/persist -I. -c $< -o $@
build/persistfix-controls/%/unit: build/persistfix-controls/%/aof.o build/persistfix/unit.o $(PERSISTFIX_CORE)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
.PHONY: persistfix-units
persistfix-units: build/persistfix-units
build/persistfix-units: build/persistfix-unit $(foreach arm,$(PERSISTFIX_CONTROLS),build/persistfix-controls/$(arm)/unit)
	@mkdir -p $(dir $@)
	@touch $@
.SECONDARY: $(foreach arm,$(PERSISTFIX_CONTROLS),build/persistfix-controls/$(arm)/aof.o)
.SECONDARY: $(foreach arm,$(PERSISTFIX_CONTROLS),build/persistfix-controls/$(arm)/aof.cc)
build/persistfix-controls/%/tomokv: build/persistfix-controls/%/aof.o build/persistfix-controls/%/db0-aof.o $(filter-out build/src/persist/aof.o,$(OBJ)) $(filter-out build/db0/src/persist/aof.o,$(DB0_OBJ))
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
.PHONY: persistfix-live-controls
persistfix-live-controls: build/persistfix-controls/old-ack/tomokv build/persistfix-controls/old-close/tomokv

$(BIN): $(OBJ) $(SERVER_ONLY_OBJ) $(DB0_OBJ) $(DB0_SERVER_ONLY_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(DB0_OBJ) $(DB0_SERVER_ONLY_OBJ) $(OBJ) $(SERVER_ONLY_OBJ) -o $@ -Wl,--wrap=main $(JELIBS) $(LDLIBS) -lm

# SV6 adds only a cold metadata lookup; retain all unrelated climon bodies.
# wave1b (seven correctness lanes + climon fix ec0317384): IPA unit 22058 -> 22490 (src) and
# 22015 -> 22447 (db0). Compile-only scans 25743-26300 / 25670-26300 with per-body attribution
# (docs/wave1b/identity/budget-trials): at every clean value the only non-lane changes are the
# climon fix's drain and the three helper copies its two changed callers now inline; fewest changed
# bodies at 26145 (= 26146) / 26220.
# compat3: compile-only PRE/POST IPA re-derivation and body-scored neighbour trials
# are retained in docs/compat3/budgets. Residual parser/TLS spillover remains a merit input.
# wave4 integration: 102 compile-only IPA trials across all 29 pinned units;
# 85 distinct object bodies judged with the gate linked-instruction normalizer
# against headline and the four frozen lane POSTs. See docs/wave4/budgets/selected.json.
# Preserve established budgets on tied body scores; composed residuals remain merit inputs.
$(BUILD_ROOT)/src/cmd/climon.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=26265
$(BUILD_ROOT)/db0/src/cmd/climon.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=26780

# The clean string family intentionally excludes the armed instantiations, but its parsed template
# bodies still move GCC just past the default large-unit threshold. 10600 restores the same inlining
# decisions as the base-420b4d492 translation unit; the objdump gate locks cmd_get/cmd_set to base.
$(BUILD_ROOT)/src/cmd/t_string.o: override CXXFLAGS += --param large-unit-insns=10600
$(BUILD_ROOT)/db0/src/cmd/t_string.o: override CXXFLAGS += --param large-unit-insns=10600
# Armed handlers include the same implementation; incremental builds must see its edits.
$(BUILD_ROOT)/src/cmd/t_string_notify.o $(BUILD_ROOT)/db0/src/cmd/t_string_notify.o: src/cmd/t_string.cc
# ACLKEYS4's physical namespace argument changes only blocking list publication.
# Keep every other list body identical; tools/aclkeys4_audit.py checks all bodies.
$(BUILD_ROOT)/src/cmd/t_list.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=25608
# PS5/PS7 add cold CONFIG/INFO/finalization code. Retain PRE's inlining decisions
# for every ordinary command and storage body; tools/psfix_artifacts.py audits both variants.
# wave1b: IPA unit +58 in both namespaces (racefix/authfix); scans 31297-31400 / 31629-31760: no
# unattributed body and fewest changed bodies at 31330 / 31725.
# rlresize: see the budget note above $(BUILD_ROOT)/src/main.o.
# wave2: see the re-derivation note above $(BUILD_ROOT)/src/main.o (31379 kept, db0 31776).
# wave3: see the re-derivation note above $(BUILD_ROOT)/src/main.o (31388 / db0 31787).
$(BUILD_ROOT)/src/cmd/t_server.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=32703
# SV7/SV9 keep new INFO formatting cold; infofields_artifacts.py checks every ordinary body.
# CC18/PS5/PS7/SV9 composition: preserve every unrelated server-command body.
# txnorder2: compile-only trials retained in docs/txnorder2/budgets; remaining spillover is explicit.
# perfex2: the two cold inline sample resets need 31737 to retain every ordinary
# body from the merged perfex POST. Complete-body trials: docs/perfex2/budgets.py.
# rlresize: see the budget note above $(BUILD_ROOT)/src/main.o.
$(BUILD_ROOT)/db0/src/cmd/t_server.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=33448 --param max-inline-insns-auto=16
# PS4 AOF recovery adds cold code. Preserve 5146b78ee storage helper bodies
# in both namespaces; the aoffix2 hot-body audit checks these compiler budgets.
# rlresize: see the budget note above $(BUILD_ROOT)/src/main.o.
# wave2: see the re-derivation note above $(BUILD_ROOT)/src/main.o (src 34437 kept, db0 34840).
# aoforder: the cold ticket/stable-order helpers add IPA size. These budgets retain
# every ordinary hot body in both namespaces; docs/aoforder records the comparison.
# wave3: see the re-derivation note above $(BUILD_ROOT)/src/main.o (37179 / db0 37578).
$(BUILD_ROOT)/src/persist/aof.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=37173
$(BUILD_ROOT)/db0/src/persist/aof.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=39024
# SV9 publishes save status only on cold completion/abort edges.
# wave1b: savefix's capture cancellation grows both units by 130; scans 14584-14760 / 14457-14620:
# FlatStore::insert stays PRE and every changed body is savefix's at 14718 (= 14720); db0 fewest at 14562.
# txnfix2: preserve PRE's ordinary store bodies after the cold unit-intent cleanup addition.
$(BUILD_ROOT)/src/snapshot/snapshot.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=15191
$(BUILD_ROOT)/db0/src/snapshot/snapshot.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=14612
# CD6/CD13 add cold scan/replacement work. Preserve GCC 13's ordinary set/zset bodies in
# both database namespaces; tests/cdfix_checks.py audits every emitted function against PRE.
# These are compile-time inlining budgets, with no runtime option or request-path branch.
# datafix1: compact SPOP, survivor rebuilding and RAND parsing add 1688/1670
# initial IPA instructions in the ordinary/db0 units.
# Bounded scans in docs/datafix1/budgets restore all ordinary storage hot bodies;
# the chosen budgets also minimize unrelated set-body changes among those trials.
$(BUILD_ROOT)/src/cmd/t_set.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=26451
# The live intset limit adds cold collection code; retain the ordinary FlatStore body.
$(BUILD_ROOT)/db0/src/cmd/t_set.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=26651
$(BUILD_ROOT)/src/cmd/t_zset.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=33447
$(BUILD_ROOT)/db0/src/cmd/t_zset.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=33229
# CD7/CD13's cold GEO text needs its own budget. The audit still reports the three
# remaining GEO-helper differences; these settings do not claim that strict check passes.
$(BUILD_ROOT)/src/cmd/geo.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=14410
$(BUILD_ROOT)/db0/src/cmd/geo.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=16462
# The parent EXECABORT store adds four IPA instructions. Keep PRE's namespaced
# xshard inlining decisions outside MULTI; docs/gt13split/audit_bodies.py checks
# every function, including ordinary xshard_plain_prepare and cold clones.
# CD13b adds owner-side GEO metadata calls; +51/+53 retains ordinary command/notify bodies
# in both namespaces. tests/cd13b_audit.py checks every emitted body and linker selection.
# ACLKEYS3's held registration and final-task wake preserve every outside-path
# xshard body at these budgets, including both blocked queue specializations.
# aclfix's pre-execution wake check grows both units by 30 insns (+29/+30 here); the
# remaining non-blocking deltas are listed in docs/aclfix/identity.
# flipfix's FLIP/fingerprint code adds 8 insns here (+24 on its own branch). wave1b: merged unit
# +73/+73; scans 127820-127950 / 126421-126500: every changed body lane-identical or a lane
# composite, fewest at 127880 (127878-127882) / 126482 (126480-126485).
# txnorder2: compile-only trials retained in docs/txnorder2/budgets; remaining spillover is explicit.
# rlresize: see the budget note above $(BUILD_ROOT)/src/main.o.
# wave2: see the re-derivation note above $(BUILD_ROOT)/src/main.o (src 127924 kept, db0 126566).
# wave3: see the re-derivation note above $(BUILD_ROOT)/src/main.o (128012 / db0 126680).
# publishfix: the publisher adds 14 IPA instructions per namespace. Compile-only
# trials (docs/publishfix/identity/budgets) retain all command/hot bodies and reduce
# unrelated changes to normalize_multi_blocking_pop plus its cold fragment at
# 128042; db0 has no unrelated changes at 126710. Remaining spillover is reported.
# moverfix: compile-only per-unit re-derivation restores all selected hot bodies;
# 128550 / 127250 leave 77 explicitly inventoried xshard bodies for merit review.
# See docs/moverfix/identity-budgets and identity-tuned/README.md.
# notifyorder: physical-record routing/salvage, overwrite expiry observation and
# opaque sink callbacks grow IPA by 390/395 instructions. Per-unit dumps and trials
# (docs/notifyorder/budgets-callback) retain the audited command bodies at 128432/127105.
# Remaining cold spillover is enumerated for merit review, not treated as identity.
# wave4 merge (provisional, additive lane deltas over 128042/126710): compat2 +76/+68,
# moverfix +508/+540, notifyorder +390/+395; the wave-4 budget commit re-derives both.
# notifycompat: source-accurate IPA deltas are +2531/+2526. Bounded per-unit
# trials (docs/notifycompat/budgets-final) reduce unrelated compiler spillover;
# db0 prepare and shared execution deltas remain inventoried for merit review.
# Wave 8: 58 IPA surveys and 103 compile-only trials across all 29 pinned units.
# Selected budgets and full reference scores: docs/wave8/budgets/selected.json.
# wave8b: compile-only re-derivation of every affected pinned IO/scatter unit;
# Final trials/scores: docs/wave8b/budgets-exact/selected.json, including
# exact callback starts and WAIT slices. Identity is a proxy; merit is pending.
# Instruction scopes and the maintainer merit still decide, not body identity.
$(BUILD_ROOT)/src/cmd/xshard.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=148585
# AT15's cold EXEC routing must not perturb ordinary DB0 dispatch/store helpers.
# perfex2: compensate the inline cold clear reset; every other emitted body is PRE-identical.
$(BUILD_ROOT)/db0/src/cmd/xshard.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=147391
# ACL key extraction is isolated from the IO templates. Keep the merged baseline's
# ordinary dispatch/command bodies; docs/aclkeys records the remaining cold ACL deltas.
# aclfix grows the unit by 749/765 insns (+739/+750 here): the shared reply helpers this
# object provides to the link stay identical; docs/aclfix/identity lists the cold ACL deltas.
# flipfix adds 8 insns (+8/+24 on its own branch). wave1b: merged unit +802/+818 (aclfix + authfix
# + flipfix); scans 35360-35500 / 35300-35420: only the two weak-copy differences every value shows
# (no vector<Client*>::push_back copy; flipfix's close_client) at 35369 (35367-35370) / 35324 (= 35326).
$(BUILD_ROOT)/src/cmd/acl.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=35758
$(BUILD_ROOT)/db0/src/cmd/acl.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=35705
# The isolated prebuild TU reuses the string parser text without emitting its public handlers.
$(BUILD_ROOT)/src/cmd/l4prebuild.o: src/cmd/t_string.cc

# Retiring the reorder pass changes GCC 13's translation-unit inlining budget. These budgets
# retain the parser, command/store bodies and ordinary split/fused IO schedules against v5.
# The complete byte audit records the remaining split read-local writeback/Unix exceptions
# in MEASURE-REQUEST.md; they are not counted as byte-identity passes.
# R7's cold role selectors shift two budgets slightly. tests/reorder_noop.py locks
# all 169 current off-path bodies, including O1 pipeline passes and O6 prefetch.
# Compiler code-generation locks only: no runtime option or request-path branch.
# Round-3 direct split entries retain the split owner's timer inline, ordinary IO
# deque outline and split read-local epoch outlines at these compiler budgets.
# Reorder cleanup removes cold parser/controller code. Keep each database variant's
# original FIFO inlining decisions; r7shadow_noop audits all 336 surviving bodies.
# The cold topology demotion and relaxed cache gauge perturb the fused TU's budget.
# rltopo_artifacts.py checks the PRE point-read/parser/scheduler bodies byte for byte.
# Pin the single-database R7 TU's compiler budget as well: its source is unchanged,
# and both surviving parser bodies must retain their PRE instructions.
# Encoding setup and LBOSC3 change the boot parser and policy initialization in these two
# TUs. Preserve PRE's ordinary parser/TLS/writeback bodies; lbstall_artifacts checks
# both complete hot inventories. No override changes in unaffected TUs.
# wave1b (seven correctness lanes on 1ba80bd4e): merged IPA units main +925/+909, genthread
# +643/+643, rl2s +654/+654, db0 reorder +675. Compile-only scans with per-body attribution and
# call-structure additivity (docs/wave1b/identity/budget-trials): main.o and db0 rl2s.o emit one
# object across every scanned value (same-headroom values used); src rl2s 162300 (clean from
# 162265, fewest non-additive dispatch call counts); genthread 129420 / 129640 (flipfix's own
# values left unattributed hot bodies once savefix/clientfix/racefix share these TUs); db0 reorder
# 148258 (148256-148261: no unattributed hot body, the ordinary TLS serve lambda back to PRE).
# perfio IO4.19: the cold epoll DEL adds 8 IPA instructions. +12 at rl2s (src) and
# genthread (db0) preserves every ordinary hot body; docs/perfio/inline-probe.json.
# rlresize (armed atomic growth reserves its resize record; FLUSH's replacement table is bounded by
# a prepared snapshot): IPA units +7 where the atomic preflight is emitted (main, genthread, rl2s,
# reorder), +37 where clear() is (t_server, aof), +44 in xshard. Compile-only scans against
# 991d48f65 (docs/rlresize/identity/budget-trials): main.o and db0 rl2s.o emit one object across
# every scanned value and keep their budgets; each changed value is the scanned one with no changed
# hot body and the fewest other changes. Remaining bodies are cold/growth paths, listed in
# MEASURE-REQUEST-rlresize.md: GCC now outlines prepare_resize_retirement in genthread/reorder, so
# maybe_start_shrink and snapshot_control_pass call it instead of inlining it.
# wave2 (perfio + perfex/perfex2 + rlresize + dbdefault on 991d48f65; lottery has no production
# change): merged IPA units vs 991d48f65 t_server +37/+51, aof +37/+44, xshard +44/+51, main +6/+51,
# genthread -2/+43, rl2s -3/+42, reorder -2/+43 (src/db0). Compile-only scans with per-body
# attribution against 991d48f65 and each lane tip's own default build (docs/wave2/identity/
# budget-trials, 3 rounds): no selected hot body may differ from 991d48f65 except perfex's own
# executor bodies (drain_tasks*, ExLoopT run), which must equal perfex's; then fewest unattributed
# and lane-differing bodies, fewest changed bodies, nearest the headroom-preserving value. main.o x2
# and db0 rl2s.o emit one object at every scanned value and keep their budgets; src rl2s 162305
# (162305-162306; perfio/rlresize/provisional values left 1-2 dispatch bodies changed); genthread
# 129447 (129447-129448) / 129704 (129704-129706; every other db0 value kept perfex's own dispatch
# drift or an unattributed body); db0 reorder 148358 (148357-148360: perfex's serve-lambda drift
# gone); t_server 31379 / 31776; aof 34437 / 34840 (db0 make_room_for differs from 991d48f65 only
# in register allocation at every clean value); xshard 127924 / 126566 (fewest bodies: rlresize's
# cold prepare_commands drift back to 991d48f65).
# wave3 (respresume + rlfix + mkfix2 A/B + aoforder + hexpread, lanes on 991d48f65, merged on
# f821104a9): merged IPA units vs f821104a9 genthread +388/+386, rl2s +454/+452, reorder +454/+441,
# main +204/+204, aof +1662/+1656, xshard +79/+79, t_server +23/+23 (src/db0). Compile-only scans
# (docs/wave3/identity/budget-trials, 3 rounds) classify every emitted body against f821104a9,
# 991d48f65 and each lane tip's own default build: no selected hot body may differ from f821104a9
# unless it equals the build of the lane that changed it (respresume+mkfix2 dispatcher composites
# excepted, being each lane's own change); then fewest unattributed and lane-differing bodies,
# fewest changed bodies, nearest the headroom-preserving value (f821104a9 budget + unit growth),
# off a plateau edge. main.o x2 and db0 rl2s.o emit identical bodies at their old value and at
# that centre: kept. src genthread 129975 (129975-129976 fewest; one D at every value: wave2's
# atomic_prepare_capacity_read_local, same size and call targets as f821104a9) / db0 130179
# (130178-130181); src rl2s 162716 (clean 162672-162720); db0 reorder 148772 (148769-148774) with
# rlfix's max-inline-insns-auto=14 (keeps f821104a9's r7_fused_sweep_impl); src reorder.o gains
# its first override: GCC's default limit is 1.4 x the running minimal unit (final 105268 at
# f821104a9, -fdump-ipa-inline), i.e. 147375 + 454 = 147829 preserves f821104a9's headroom; the
# default allowed 181 more insns, which inlined Rob::quiesced into drive_tls and
# flush_xshard_commits into the R7 sweep; 147794 (147792-147795) is clean; aof 37179 (37177-37182)
# / db0 37578 (37576-37580; one D at every value: aoforder's record_post_image_impl no longer
# inlines Slice::key_eq in the merged unit); xshard 128012 / db0 126680; t_server 31388 / 31787.
# ntfix4 composition on bce4eb0aa: initial IPA units grow by 127 (main),
# 142 (genthread), 172 (rl2s/reorder). Eight reference and 56 merged compile-only
# trials retain the main/rl2s budgets and select genthread 130084/130316,
# reorder 147950/148944. All selected hot bodies outside the 20 composed
# dispatchers equal headline or ntfix3; every remaining delta is retained in
# docs/ntfix/ntfix4/identity. Scans and selection: docs/ntfix/ntfix4/selected.json.
# compat2b: 29 reference recompiles and merged compile-only trials select the
# per-unit budgets in docs/compat2b/selected.json. Preserve headline or compat2
# hot bodies; composed C1/N3/N4 dispatchers remain explicit merit inputs.
$(BUILD_ROOT)/src/main.o: override CXXFLAGS += -DTOMO_DUAL_DATABASE --param inline-unit-growth=0 --param large-unit-insns=147838
# txnorder2: compile-only trials retained in docs/txnorder2/budgets; remaining spillover is explicit.
# RL4.3/RL4.4 add only cold miss/delete work. Preserve the PRE hot-body inlining
# choices; docs/rlfix records the complete byte inventory and compile-only trials.
# clockcut: adding the post-dequeue refresh grows each IO IPA unit by 23.
# Compile-only per-unit trials (docs/clockcut/budget-selected.json) reduce unrelated
# body spillover; the remaining differences are reported for merit review.
# wave4 merge (provisional, additive lane deltas over 8656f9fa9): genthread compat2 +29 and
# clockcut +128; rl2s clockcut +256. The wave-4 budget commit re-derives these values.
$(BUILD_ROOT)/src/core/genthread.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=131218
$(BUILD_ROOT)/src/core/rl2s.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=164621
# wave3: see the note above $(BUILD_ROOT)/src/main.o (first override of this object).
# wave3 R7 round (7fa5cb0e0 regenerates rlfix's RL4.4 into the R7 envelope): units +82 / +80
# (src / db0). Compile-only scans 147770-147970 / 148760-148949 (docs/wave3/identity/
# budget-trials-r7) against the pre-regeneration cx-wave3 objects: no selected hot body may change;
# then fewest changed bodies. src 147778 (147776-147779) and db0 148779 (148777-148780) change only
# r7_ReadLocalDemotionPlan::prepare, its new read_local_commands_overlap .part.0 clone and
# discarded COMDAT copies (the non-R7 demotion plan and FlatStore helpers; genthread.o's are linked).
$(BUILD_ROOT)/src/core/reorder.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=149103
# CC18/ST3 composition: smallest current hot-body delta; ccfix4 retains the search.
$(BUILD_ROOT)/db0/src/main.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=146080 --param max-inline-insns-auto=18
# RL1: retain the measured ALT spelling and its fused GET placement controls.
# docs/rlfence2/alt.patch and MEASURE-REQUEST-rlfence3.md record the byte proofs.
# txnorder2: compile-only trials retained in docs/txnorder2/budgets; remaining spillover is explicit.
# wave4 merge (provisional, additive lane deltas over 8656f9fa9): db0 genthread compat2 +27
# and clockcut +64; db0 reorder compat2 +39 and clockcut +128. Re-derived by the budget commit.
$(BUILD_ROOT)/db0/src/core/genthread.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=132012 -Wa,--defsym,tomo_rlfence_text_pad=16
$(BUILD_ROOT)/db0/src/core/rl2s.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=167496
# Keep PRE's first (rather than second) tombstone-compaction call inlined in the
# R7 fused sweep; the cold miss body otherwise changes GCC's tied call ordering.
$(BUILD_ROOT)/db0/src/core/reorder.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=150092 --param max-inline-insns-auto=14
$(BUILD_ROOT)/db0/src/cmd/l4prebuild.o: src/cmd/t_string.cc

# Separate C++ namespaces prevent accidental cross-variant inline/COMDAT binding.
# The only shared code is third-party Lua; all database state is variant-private.
$(BUILD_ROOT)/third_party/lua/helpers/%.o: third_party/lua/helpers/%.c $(wildcard third_party/lua/*.h) $(wildcard third_party/lua/helpers/*.h) src/base/tomo_assert_c.h Makefile
	@mkdir -p $(dir $@)
	$(CC) $(filter-out -std=c++20,$(CXXFLAGS)) -std=c11 -DENABLE_CJSON_GLOBAL -Ithird_party/lua -c $< -o $@

$(BUILD_ROOT)/db0/%.o: %.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) $(wildcard third_party/lua/*) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. -c $< -o $@

$(BUILD_ROOT)/%.o: %.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) $(wildcard third_party/lua/*) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. -c $< -o $@

asan:
	$(MAKE) BUILD_ROOT=build/asan JE=0 CXXFLAGS='$(CXXFLAGS) -fsanitize=address,undefined -fno-omit-frame-pointer -O1' all
	cp build/asan/tomokv build/tomokv-asan

tsan:
	$(MAKE) BUILD_ROOT=build/tsan JE=0 CXXFLAGS='-std=c++20 -O1 -g -Wall -Wextra -pthread -fsanitize=thread' all
	cp build/tsan/tomokv build/tomokv-tsan

# The armed-write block cache's ownership laws as assertions: the cache and the QSBR retire ring
# are owner-private (one thread, no lock), each cached block is resident exactly once, each class
# list matches its counter, and every shard's retire sink names its CURRENT owner. Debug-only: the
# residency set and the sampled list walk cost far more than the path they guard. DESIGN-P0REPLY.md.
rlcachedbg:
	$(MAKE) BUILD_ROOT=build/rlcachedbg CXXFLAGS='$(CXXFLAGS) -DTOMO_RL_CACHE_DEBUG' all
	cp build/rlcachedbg/tomokv build/tomokv-rlcachedbg

# NEGATIVE-CONTROL BUILD for the row above: the same assertions with the ownership-edge rebind
# removed, i.e. the pre-fix behaviour. tests/rlcache_churn.py MUST fail against this binary; a
# detector that cannot report failure proves nothing about the runs that pass.
rlcache-nofix:
	$(MAKE) BUILD_ROOT=build/rlcache-nofix CXXFLAGS='$(CXXFLAGS) -DTOMO_RL_CACHE_DEBUG -DTOMO_RL_CACHE_NO_EAGER_ADOPT' all
	cp build/rlcache-nofix/tomokv build/tomokv-rlcache-nofix

# NEGATIVE-CONTROL BUILD for the cross-owner script reservation sub-wave. Identical to the release
# build except that ScriptPhase::Pin arms nothing, so tests/xscript.py counterexample MUST fail
# against it. A detector that cannot report failure proves nothing about the runs that pass.
noreserve:
	$(MAKE) BUILD_ROOT=build/noreserve CXXFLAGS='$(CXXFLAGS) -DTOMO_XSCRIPT_NO_RESERVE' all
	cp build/noreserve/tomokv build/tomokv-noreserve

# Server-less unit binaries: the config parser and the flip controller. `make unit` builds and
# runs both (neither boots a server). tests/gate.sh's parser row is the same program.
# Live NET2 witness: connects only to a maintainer/gate-owned TLS listener.
build/ktls-keyupdate: tests/ktls_keyupdate.cc Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. $< -o $@ -lssl -lcrypto

build/ktls-keyupdate-unit: tests/ktls_keyupdate_unit.cc src/net/tls.cc src/net/tls.h src/core/config.h Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -I. tests/ktls_keyupdate_unit.cc src/net/tls.cc -o $@ \
	  -Wl,--wrap=BIO_ctrl -Wl,--wrap=setsockopt -lssl -lcrypto
build/splitlocal-unit.cc: tests/splitlocal_checks.py tests/r7shadow_sync.py tools/reorder_sync.py src/core/io_loop.h src/core/reorder.cc src/core/genthread_pipeline.h
	@mkdir -p $(dir $@)
	python3 tests/splitlocal_checks.py emit $@
build/splitlocal-unit: build/splitlocal-unit.cc Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $< -o $@
build/config-parser-test: tests/config_parser_test.cc tests/boot_support_checks.inc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/config_parser_test.cc -o $@
build/climon-mask-unit: tests/climon_mask_unit.cc src/core/climon_mask.h Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. $< -o $@
build/climon-mask-old-unit: tests/climon_mask_unit.cc src/core/climon_mask.h Makefile
	@mkdir -p build/climon-mask-old/src/core
	sed 's/return io >> 6;/return 0;/' src/core/climon_mask.h > build/climon-mask-old/src/core/climon_mask.h
	$(CXX) $(CXXFLAGS) -Ibuild/climon-mask-old -I. $< -o $@

build/flipctl-unit: tests/flipctl_unit.cc tests/signalacct_checks.h src/core/flipctl.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/flipctl_unit.cc src/core/flipctl.cc -o $@
# The fused owner's deferred-reclaim ring (QSBR batches) against a per-entry reference model.
build/read-local-ring-unit: tests/read_local_ring_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/read_local_ring_unit.cc -o $@
build/read-local-write-ring-unit: tests/read_local_write_ring_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/read_local_write_ring_unit.cc -o $@
build/rlfence-unit: tests/rlfence_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/rlfence_unit.cc -o $@
STORE_REGRESSION_SRC := tests/store_regression.cc src/cmd/t_hash.cc src/cmd/t_hash_ttl.cc src/cmd/hexpread.cc src/cmd/storesize.cc
build/store-regression: $(STORE_REGRESSION_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -ffunction-sections -fdata-sections -DTOMO_STORE_REGRESSION_TEST -I. \
	  $(STORE_REGRESSION_SRC) -Wl,--gc-sections -o $@
build/store-regression-tsan: $(STORE_REGRESSION_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -O1 -fsanitize=thread -fno-omit-frame-pointer -no-pie \
	  -ffunction-sections -fdata-sections -DTOMO_STORE_REGRESSION_TEST -I. \
	  $(STORE_REGRESSION_SRC) -Wl,--gc-sections -o $@
build/waits-unit: tests/waits_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/waits_unit.cc -o $@
unit: build/reorder-unit build/r7shadow-unit build/config-parser-test build/flipctl-unit build/read-local-ring-unit build/read-local-write-ring-unit build/rlfence-unit build/waits-unit
	./build/reorder-unit
	./build/r7shadow-unit
	./build/config-parser-test
	./build/flipctl-unit
	./build/read-local-ring-unit
	./build/read-local-write-ring-unit
	./build/rlfence-unit
	./build/waits-unit

# Deterministic core regressions: the test TU instantiates the real executor/IO methods
# with ASAN/UBSAN and test-only interleaving hooks. No server or ring is started.
CORE_TEST_OBJ := $(filter-out build/src/main.o,$(OBJ))
build/tomo-assert-fail: tests/tomo_assert_fail.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

ASSERT_LINT_JOBS ?= 1
.PHONY: source-identity-check
source-identity-check:
	python3 tools/source_identity.py --cxx "$(CXX)" --cc "$(CC)" --flags "$(CXXFLAGS) $(JEFLAGS)" --jobs $(ASSERT_LINT_JOBS) --sources $(SRC) $(SERVER_ONLY_SRC) --c-sources $(LUA_HELPER_SRC)

build/rlfix3-info-unit: build/tests/rlfix3_info_unit.o $(CORE_TEST_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=clock_gettime,--wrap=getpid,--wrap=getrandom,--wrap=realpath,--wrap=mallctl,--wrap=time
build/expire-notify-unit: tests/expire_notify_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
build/ktls-lifetime-unit: tests/ktls_lifetime_unit.cc tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
build/respresume-migration: tests/respresume_migration.cc tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
build/encodingfix-unit: build/tests/encodingfix_unit.o $(CORE_TEST_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
DB0_TEST_OBJ := $(filter-out build/db0/src/main.o,$(DB0_OBJ))
build/rlfix3-info-db0-unit: build/db0/tests/rlfix3_info_unit.o $(DB0_TEST_OBJ) $(CORE_TEST_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=clock_gettime,--wrap=getpid,--wrap=getrandom,--wrap=realpath,--wrap=mallctl,--wrap=time
# ACL range audit and real permission checks; never starts the server.
$(BUILD_ROOT)/aclkeys-unit: tests/aclkeys_unit.cc $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ))
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $^ -o $@ $(JELIBS) $(LDLIBS) -lm
# Directed blocked-XREAD schedule using production bodies; no listener or worker.
$(BUILD_ROOT)/aclkeys-wake-unit: tests/aclkeys_wake_unit.cc $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ))
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $^ -o $@ $(JELIBS) $(LDLIBS) -lm
$(BUILD_ROOT)/aclkeys-wake-db0-unit: tests/aclkeys_wake_unit.cc $(filter-out $(BUILD_ROOT)/db0/src/main.o,$(DB0_OBJ)) $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ))
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $^ -o $@ $(JELIBS) $(LDLIBS) -lm
# ST2 cost witness: only the two cold census walks are instrumented. The fixture
# dispatches real commands and counts work; it never boots a listener or workers.
STORESIZE_CORE_OBJ := $(filter-out build/src/cmd/xshard.o build/src/cmd/multidb.o build/db0/src/cmd/xshard.o build/db0/src/cmd/multidb.o,$(CORE_TEST_OBJ) $(DB0_TEST_OBJ))
build/storesize/multidb.cc: tests/storesize_checks.py src/cmd/multidb.cc
	@mkdir -p $(dir $@)
	python3 $< src/cmd/multidb.cc $@
build/storesize/multidb.o: build/storesize/multidb.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Isrc/cmd -I. -c $< -o $@
build/storesize/db0-multidb.o: build/storesize/multidb.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -Isrc/cmd -I. -c $< -o $@
build/storesize-unit: build/tests/storesize_unit.o build/db0/tests/storesize_unit.o build/storesize/multidb.o build/storesize/db0-multidb.o $(STORESIZE_CORE_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
# AT15: production transaction routing, no listener or worker threads.
build/at15-unit: build/tests/at15_unit.o $(CORE_TEST_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
build/at15-db0-unit: build/db0/tests/at15_unit.o $(DB0_TEST_OBJ) $(CORE_TEST_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
# EXECABORT/WATCH: same serverless witness linked against real production bodies.
build/execabort-watch-unit: build/tests/execabort_watch_unit.o $(CORE_TEST_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
build/execabort-watch-db0-unit: build/db0/tests/execabort_watch_unit.o $(DB0_TEST_OBJ) $(CORE_TEST_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
# EX1/EX3/EX6 use production objects without opening a listener or IO ring.
build/exbatch-unit: build/tests/exbatch_unit.o $(CORE_TEST_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
build/exbatch-db0-unit: build/db0/tests/exbatch_unit.o $(DB0_TEST_OBJ) $(CORE_TEST_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
# Lane-only frozen baseline fixture; PRE/source and PRE/build come from cd02ecbab.
# The ordinary gate never depends on this artifact.
build/exbatch/PRE/unit.o: tests/exbatch_unit.cc Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Wno-mismatched-new-delete -Ibuild/exbatch/PRE/source -I. -c $< -o $@
build/exbatch/PRE/unit: build/exbatch/PRE/unit.o $(patsubst build/%,build/exbatch/PRE/build/%,$(CORE_TEST_OBJ))
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
# ST1/ST10 serverless proofs. PRE objects are kept by the lane before editing;
# the control target substitutes just the two command objects in both images.
FLUSHFIX_UNIT_OBJ := build/tests/flushfix_unit.o build/db0/tests/flushfix_unit.o
FLUSHFIX_COMMAND_OBJ := build/src/cmd/t_server.o build/src/cmd/multidb.o build/db0/src/cmd/t_server.o build/db0/src/cmd/multidb.o
build/flushfix-unit: $(FLUSHFIX_UNIT_OBJ) $(DB0_TEST_OBJ) $(CORE_TEST_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
build/flushfix-pre-unit: $(FLUSHFIX_UNIT_OBJ) $(filter-out $(FLUSHFIX_COMMAND_OBJ),$(DB0_TEST_OBJ) $(CORE_TEST_OBJ)) $(addprefix build/flushfix/pre/,$(patsubst build/%,%,$(FLUSHFIX_COMMAND_OBJ)))
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
build/flushfix/pre-source/.emitted: tests/flushfix_checks.py
	@mkdir -p $(dir $@)
	python3 tests/flushfix_checks.py emit-pre build/flushfix/pre-source
build/flushfix/pre/src/cmd/%.o: build/flushfix/pre-source/.emitted
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. -c build/flushfix/pre-source/src/cmd/$*.cc -o $@
build/flushfix/pre/db0/src/cmd/%.o: build/flushfix/pre-source/.emitted
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. -c build/flushfix/pre-source/src/cmd/$*.cc -o $@
build/kvobj-header-unit: tests/kvobj_header_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< -o $@ $(JELIBS)
build/kvobj-header-db0-unit: tests/kvobj_header_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< -o $@ $(JELIBS)
FLUSHFIX_HEADER_SITES := raw int string typeval embedded reheader
build/flushfix-header-controls/%/unit: tests/kvobj_header_unit.cc tests/flushfix_checks.py $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p build/flushfix-header-controls/$*/source
	python3 tests/flushfix_checks.py emit-header $* build/flushfix-header-controls/$*/source
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Ibuild/flushfix-header-controls/$*/source -I. $< -o $@ $(JELIBS)
build/flushfix-units: build/flushfix-unit build/kvobj-header-unit build/kvobj-header-db0-unit $(addprefix build/flushfix-header-controls/,$(addsuffix /unit,$(FLUSHFIX_HEADER_SITES)))
	@mkdir -p $(dir $@)
	@touch $@
# Link-only witnesses: no allocation/metadata counters enter production objects.
MDBSTAMP_WRAP := -Wl,--wrap=_ZN4tomo24command_metadata_resolveERNS_2OpEj \
  -Wl,--wrap=_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE \
  -Wl,--wrap=malloc -Wl,--wrap=calloc -Wl,--wrap=realloc \
  -Wl,--wrap=aligned_alloc -Wl,--wrap=posix_memalign
build/tests/multidb_unit.o: src/cmd/xshard.cc tests/sortstore_checks.inc
build/tests/multidb_unit.o build/db0/tests/multidb_db0_unit.o build/rehash-waits-unit: tests/probeadapter_checks.h
build/multidb-unit: build/tests/multidb_unit.o build/tests/mdbstamp_checks.o build/db0/tests/multidb_db0_unit.o $(DB0_TEST_OBJ) $(filter-out build/src/cmd/xshard.o,$(CORE_TEST_OBJ))
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm $(MDBSTAMP_WRAP)
# The existing multidb row also owns the deterministic reclamation checks.
# Every map/reader/loop implementation object is instrumented, not just the driver.
MDBQSBR_SRC := $(filter-out src/main.cc,$(SRC))
MDBQSBR_ASAN_OBJ := $(MDBQSBR_SRC:%.cc=build/mdbqsbr-asan/%.o)
MDBQSBR_TSAN_OBJ := $(MDBQSBR_SRC:%.cc=build/mdbqsbr-tsan/%.o)
MDBQSBR_ASAN_OBJ += $(LUA_HELPER_SRC:%.c=build/mdbqsbr-asan/%.o)
MDBQSBR_TSAN_OBJ += $(LUA_HELPER_SRC:%.c=build/mdbqsbr-tsan/%.o)
MDBQSBR_FLAGS := -std=c++20 -O1 -g -Wall -Wextra -march=native -pthread \
  -fno-omit-frame-pointer -no-pie -DTOMO_MDBQSBR_TEST -DTOMO_CORE_CONCURRENCY_TEST -I.
MDBQSBR_WRAP := -Wl,--wrap=_ZN4tomo11AofProducer19record_database_mapEPKh
build/mdbqsbr-asan/%.o: %.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(MDBQSBR_FLAGS) -fsanitize=address,undefined -c $< -o $@
build/mdbqsbr-tsan/%.o: %.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(MDBQSBR_FLAGS) -fsanitize=thread -c $< -o $@
build/mdbqsbr-asan/third_party/lua/helpers/%.o: third_party/lua/helpers/%.c $(wildcard third_party/lua/*.h) $(wildcard third_party/lua/helpers/*.h) src/base/tomo_assert_c.h Makefile
	@mkdir -p $(dir $@)
	$(CC) $(filter-out -std=c++20,$(MDBQSBR_FLAGS)) -std=c11 -DENABLE_CJSON_GLOBAL -Ithird_party/lua -fsanitize=address,undefined -c $< -o $@
build/mdbqsbr-tsan/third_party/lua/helpers/%.o: third_party/lua/helpers/%.c $(wildcard third_party/lua/*.h) $(wildcard third_party/lua/helpers/*.h) src/base/tomo_assert_c.h Makefile
	@mkdir -p $(dir $@)
	$(CC) $(filter-out -std=c++20,$(MDBQSBR_FLAGS)) -std=c11 -DENABLE_CJSON_GLOBAL -Ithird_party/lua -fsanitize=thread -c $< -o $@
build/mdbqsbr-asan/src/cmd/l4prebuild.o build/mdbqsbr-tsan/src/cmd/l4prebuild.o: src/cmd/t_string.cc
build/mdbqsbr-unit: build/mdbqsbr-asan/tests/mdbqsbr_unit.o $(MDBQSBR_ASAN_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(MDBQSBR_FLAGS) -fsanitize=address,undefined $^ -o $@ $(LDLIBS) -lm $(MDBQSBR_WRAP)
build/mdbqsbr-unit-tsan: build/mdbqsbr-tsan/tests/mdbqsbr_unit.o $(MDBQSBR_TSAN_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(MDBQSBR_FLAGS) -fsanitize=thread $^ -o $@ $(LDLIBS) -lm $(MDBQSBR_WRAP)
build/core-concurrency-mdbqsbr-asan: build/mdbqsbr-asan/tests/core_concurrency_unit.o $(MDBQSBR_ASAN_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(MDBQSBR_FLAGS) -fsanitize=address,undefined $^ -o $@ $(LDLIBS) -lm
build/rltopo-unit: build/mdbqsbr-asan/tests/rltopo_unit.o $(MDBQSBR_ASAN_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(MDBQSBR_FLAGS) -fsanitize=address,undefined $^ -o $@ $(LDLIBS) -lm
build/core-concurrency-mdbqsbr-tsan: build/mdbqsbr-tsan/tests/core_concurrency_unit.o $(MDBQSBR_TSAN_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(MDBQSBR_FLAGS) -fsanitize=thread $^ -o $@ $(LDLIBS) -lm
build/multidb-unit: | build/mdbqsbr-unit
# Real-boot wake proof twins, never measurement arms. Both extend only the idle
# wait beyond the client's derived deadline; the negative removes database wakes.
# Keep flags consistent in every implementation TU (including inline Ring code).
.PHONY: mdbqsbr-live-arms
mdbqsbr-live-arms:
	$(MAKE) BUILD_ROOT=build/mdbqsbr2-park CXXFLAGS='$(CXXFLAGS) -DTOMO_MDBQSBR_LIVE_PARK' all
	$(MAKE) BUILD_ROOT=build/mdbqsbr2-no-wake CXXFLAGS='$(CXXFLAGS) -DTOMO_MDBQSBR_LIVE_PARK -DTOMO_MDBQSBR_NO_WAKE' all

build/multidb-boundary-unit: tests/multidb_boundary_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
build/multidb-cost-unit: tests/multidb_cost_unit.cc $(CORE_TEST_OBJ) $(DB0_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< $(DB0_TEST_OBJ) $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
build/multidb-cost-unit-multi: tests/multidb_cost_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_COST_NAMESPACED=1 -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
build/tomokv-multidb2-pad: build/tomokv tools/multidb2_artifacts.py tools/lbstall_artifacts.py
	@mkdir -p $(dir $@)
	python3 tools/multidb2_artifacts.py $< $@ > build/multidb2-pad.json
build/tomokv-multidb-pad: build/tomokv tools/multidb_artifacts.py tools/lbstall_artifacts.py
	@mkdir -p $(dir $@)
	python3 tools/multidb_artifacts.py $< $@ > build/multidb-pad.json
build/rehash-waits-unit: tests/rehash_waits_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

# Whole owner batches and live WATCH blockers; this unit starts no server.
build/owner-prefetch-unit: tests/owner_prefetch_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

build/core-concurrency-unit: build/core-concurrency-mdbqsbr-asan
	@mkdir -p $(dir $@)
	cp $< $@

# Directed owner-phase tests. The test includes xshard.cc to drive the real private phases
# without starting worker threads or opening a listener; all other code is the release objects.
# Keep ALL COMDAT copies of the hook-bearing inline publisher identical. Never
# link these objects into a production server or mix them with release objects.
PUBLISHFIX_OBJ := $(patsubst %.cc,$(BUILD_ROOT)/publishfix-unit-objects/%.o,$(filter-out src/main.cc,$(SRC)))
# Helpers contain no TOMO_PUBLISHFIX_TEST code; use the same C objects as release.
PUBLISHFIX_OBJ += $(LUA_HELPER_SRC:%.c=$(BUILD_ROOT)/%.o)
$(BUILD_ROOT)/publishfix-unit-objects/src/cmd/l4prebuild.o: src/cmd/t_string.cc
$(BUILD_ROOT)/publishfix-unit-objects/%.o: %.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_PUBLISHFIX_TEST -I. -c $< -o $@
$(BUILD_ROOT)/publishfix-unit: tests/publishfix_unit.cc $(PUBLISHFIX_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_PUBLISHFIX_TEST -I. $< $(PUBLISHFIX_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

build/atomic-survivors-unit: tests/atomiccollapse_checks.inc tests/atomic_plain_checks.inc tests/txnorder_checks.inc
build/atomic-survivors-unit: tests/atomic_survivors_unit.cc src/cmd/xshard.cc $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. tests/atomic_survivors_unit.cc \
	  $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm

# Deterministic A' schedules and WATCH windows use the production owner code.
build/txnorder-wake-unit: tests/txnorder_wake_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< -o $@ $(JELIBS) $(LDLIBS)

TXNORDER_UNIT_DEPS := tests/atomic_survivors_unit.cc tests/atomiccollapse_checks.inc tests/atomic_plain_checks.inc tests/txnorder_checks.inc $(wildcard src/*/*.inc) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
build/txnorder-episodes: tests/txnorder_episodes.cc $(TXNORDER_UNIT_DEPS) $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ))
	$(CXX) $(filter-out -O3,$(CXXFLAGS)) -O0 $(JEFLAGS) -I. $< $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm
build/txnorder-episodes-debug: tests/txnorder_episodes.cc $(TXNORDER_UNIT_DEPS) $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ))
	$(CXX) $(filter-out -O3,$(CXXFLAGS)) -O0 $(JEFLAGS) -DTOMO_TXNORDER_DEBUG -I. $< $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm
build/txnorder-watch-unit: tests/txnorder_watch_unit.cc $(TXNORDER_UNIT_DEPS) $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ))
	$(CXX) $(filter-out -O3,$(CXXFLAGS)) -O0 $(JEFLAGS) -I. $< $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm

build/txnorder-watch-db0-unit: tests/txnorder_watch_unit.cc $(TXNORDER_UNIT_DEPS) $(filter-out build/db0/src/main.o build/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out build/src/main.o,$(OBJ))
	$(CXX) $(filter-out -O3,$(CXXFLAGS)) -O0 $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< $(filter-out build/db0/src/main.o build/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out build/src/main.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm

# Wound publication and allocation-failure owner turns, both namespaces.
# Pause seams exist only in the copied fixture source, never in release objects.
build/woundfix-windows/stamp: tools/woundfix_windows.py $(wildcard src/*/*.cc) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	python3 tools/woundfix_windows.py build/woundfix-windows
build/txnorder-wound-unit: tests/txnorder_wound_window.cc $(TXNORDER_UNIT_DEPS) build/woundfix-windows/stamp $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ))
	$(CXX) $(filter-out -O3,$(CXXFLAGS)) -O0 $(JEFLAGS) -Ibuild/woundfix-windows -I. $< $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm
build/txnorder-wound-db0-unit: tests/txnorder_wound_window.cc $(TXNORDER_UNIT_DEPS) build/woundfix-windows/stamp $(filter-out build/db0/src/main.o build/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out build/src/main.o,$(OBJ))
	$(CXX) $(filter-out -O3,$(CXXFLAGS)) -O0 $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -Ibuild/woundfix-windows -I. $< $(filter-out build/db0/src/main.o build/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out build/src/main.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm

build/txnorder-retry-unit: tests/txnorder_retry_unit.cc $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< -o $@ $(JELIBS) $(LDLIBS)

# execindex uses independent frozen linear owner code in both physical namespaces.
build/txnorder-index-unit: tests/txnorder_index_unit.cc tests/txnorder_linear_oracle.inc $(TXNORDER_UNIT_DEPS) $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ))
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_TXN_ORACLE -DTOMO_TXNORDER_DEBUG -I. $< $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm
build/txnorder-index-db0-unit: tests/txnorder_index_unit.cc tests/txnorder_linear_oracle.inc $(TXNORDER_UNIT_DEPS) $(filter-out build/db0/src/main.o build/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out build/src/main.o,$(OBJ))
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_TXN_ORACLE -DTOMO_TXNORDER_DEBUG -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< $(filter-out build/db0/src/main.o build/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out build/src/main.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm

# Inspect real record/header allocation arenas on pinned owner threads, including abort cleanup
# and quiesced shard handoff. JE=1 is required; no server or io_uring instance is started.
build/owner-arena-unit: tests/owner_arena_unit.cc tests/at_recycle_checks.inc src/cmd/xshard.cc $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< \
	  $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) -o $@ \
	  $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=mallocx -Wl,--wrap=sdallocx

# The fixture needs eight allowed CPUs. Build on the lane's compile CPUs, then invoke this target
# under taskset (for example 112-119) to check both modes with the read-local lane off and armed.
owner-arena-unit: build/owner-arena-unit
	./build/owner-arena-unit 1s read-local-0
	./build/owner-arena-unit 1s read-local-1
	./build/owner-arena-unit 2s read-local-0
	./build/owner-arena-unit 2s read-local-1
.PHONY: owner-arena-unit

# IO-prebuild policy and lifetime regressions, using pinned serverless L4 workers.
# Read the one production boundary at build time. The fixture's separate comparison oracle
# still catches a disabled/inclusive policy; a one-line boundary edit rebuilds both binaries.
L4PREBUILD_TEST_FLAGS := -DTOMO_L4_PREBUILD_TEST_BOUNDARY=$(shell sed -n 's/^\#define TOMO_L4_PREBUILD_THRESHOLD //p' src/cmd/l4prebuild.cc)
build/l4prebuild-unit: tests/l4prebuild_unit.cc tests/owner_arena_unit.cc src/cmd/xshard.cc $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) $(L4PREBUILD_TEST_FLAGS) -I. $< \
	  $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) -o $@ \
	  $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=mallocx -Wl,--wrap=sdallocx

# R7 kind A: mainline FIFO behavior in an exact copy of POST text and layout.
# The offline patch disables only the boot capability; L4 prebuild stays enabled.
build/tomokv-pad: $(BIN) tests/r7shadow_pad.py tools/lbstall_artifacts.py
	@mkdir -p $(dir $@)
	python3 tests/r7shadow_pad.py $< $@ --scope fifo --receipt $@.json

l4prebuild-unit: build/l4prebuild-unit
	./build/l4prebuild-unit 1s read-local-0
	./build/l4prebuild-unit 1s read-local-1
	./build/l4prebuild-unit 2s read-local-0
	./build/l4prebuild-unit 2s read-local-1

# All production objects linked by these serverless tests are instrumented, not just the
# fixture. Invoke builds and tests under taskset on the lane's CPUs (112-127).
L4PREBUILD_TSAN_FLAGS := -std=c++20 -O1 -g -Wall -Wextra -march=native -pthread \
                         -fsanitize=thread -fno-omit-frame-pointer -no-pie
L4PREBUILD_TSAN_COMMON := $(patsubst build/%.o,build/l4prebuild-tsan/%.o,$(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)))
build/l4prebuild-tsan/%.o: %.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(L4PREBUILD_TSAN_FLAGS) $(JEFLAGS) -I. -c $< -o $@
build/l4prebuild-tsan/src/cmd/l4prebuild.o: src/cmd/t_string.cc
build/l4prebuild-unit-tsan: tests/l4prebuild_unit.cc tests/owner_arena_unit.cc src/cmd/xshard.cc $(L4PREBUILD_TSAN_COMMON) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(L4PREBUILD_TSAN_FLAGS) $(JEFLAGS) $(L4PREBUILD_TEST_FLAGS) -I. $< \
	  $(L4PREBUILD_TSAN_COMMON) \
	  -o $@ $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=mallocx -Wl,--wrap=sdallocx

l4prebuild-unit-tsan: build/l4prebuild-unit-tsan
	TSAN_OPTIONS=halt_on_error=1:exitcode=66 setarch x86_64 -R ./build/l4prebuild-unit-tsan 1s read-local-0
	TSAN_OPTIONS=halt_on_error=1:exitcode=66 setarch x86_64 -R ./build/l4prebuild-unit-tsan 1s read-local-1
	TSAN_OPTIONS=halt_on_error=1:exitcode=66 setarch x86_64 -R ./build/l4prebuild-unit-tsan 2s read-local-0
	TSAN_OPTIONS=halt_on_error=1:exitcode=66 setarch x86_64 -R ./build/l4prebuild-unit-tsan 2s read-local-1
.PHONY: l4prebuild-unit l4prebuild-unit-tsan
build/l4prebuild-unit build/l4prebuild-unit-tsan: tests/at_recycle_checks.inc

# Load drivers: not part of `all`, kept compiling here so they cannot rot unnoticed.
build/benchtxn: tools/benchtxn.cc Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tools/benchtxn.cc -o $@
build/broaden-bench: tests/broaden_bench.cc Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/broaden_bench.cc -o $@
tools: build/benchtxn build/broaden-bench build/tailgen

# Standalone smooth open-loop RESP driver; no server libraries or jemalloc.
TAILGEN_HEADERS := $(wildcard tools/tailgen/*.h)
# Only libc/pthread are dynamic dependencies; bundle the compiler/math runtimes.
TAILGEN_LIBS := -static-libstdc++ -static-libgcc -Wl,-Bstatic,-lstdc++,-lm,-Bdynamic -pthread
build/tailgen: tools/tailgen/main.cc $(TAILGEN_HEADERS) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. $< -o $@ $(TAILGEN_LIBS)
build/tailgen-unit: tests/tailgen_unit.cc $(TAILGEN_HEADERS) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. $< -o $@ $(TAILGEN_LIBS)
build/tailgen-unit-asan: tests/tailgen_unit.cc $(TAILGEN_HEADERS) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -O1 -fsanitize=address,undefined -fno-omit-frame-pointer -I. $< -o $@ -pthread
build/tailgen-unit-tsan: tests/tailgen_unit.cc $(TAILGEN_HEADERS) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -O1 -fsanitize=thread -fno-omit-frame-pointer -no-pie -I. $< -o $@ -pthread
tailgen: build/tailgen
tailgen-unit: build/tailgen-unit
	./build/tailgen-unit
tailgen-unit-asan: build/tailgen-unit-asan
	./build/tailgen-unit-asan
tailgen-unit-tsan: build/tailgen-unit-tsan
	TSAN_OPTIONS=halt_on_error=1:exitcode=66 setarch x86_64 -R ./build/tailgen-unit-tsan
.PHONY: tailgen tailgen-unit tailgen-unit-asan tailgen-unit-tsan

clean:
	rm -rf build
.PHONY: all asan tsan noreserve clean unit tools

# Deterministic networking/command regressions. These TUs include the real private implementations;
# omit their production objects from this serverless binary. No server threads or gate are started.
NETCMD_TEST_SRC := tests/netcmd_unit.cc tests/netcmd_stream_unit.cc tests/netcmd_zset_unit.cc tests/netcmd_config_unit.cc
NETCMD_TEST_OBJ := $(NETCMD_TEST_SRC:tests/%.cc=build/tests/%.o)
build/tests/netcmd_unit.o build/db0/tests/netcmd_unit.o: tests/tlsserve_checks.inc tests/hexpire_oom_checks.inc tests/notify_order_checks.inc
NETCMD_LIB_OBJ := $(filter-out build/src/main.o build/src/cmd/xshard.o build/src/cmd/t_stream_groups.o build/src/cmd/t_zset.o build/src/cmd/server_tail.o,$(OBJ))
build/tests/%.o: tests/%.cc tests/netcmd_unit.h $(wildcard src/*/*.h) $(wildcard src/core/*.inc) $(filter-out $(SERVER_ONLY_SRC),$(wildcard src/*/*.cc)) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Wno-mismatched-new-delete -I. -c $< -o $@
build/netcmd-unit: $(NETCMD_TEST_OBJ) $(NETCMD_LIB_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=mkstemp -Wl,--wrap=fopen

# The same direct-call regressions against the databases=1 runtime selected at boot.
NETCMD_DB0_TEST_OBJ := $(NETCMD_TEST_SRC:tests/%.cc=build/db0/tests/%.o)
build/db0/tests/%.o: tests/%.cc tests/netcmd_unit.h $(wildcard src/*/*.h) $(wildcard src/core/*.inc) $(filter-out $(SERVER_ONLY_SRC),$(wildcard src/*/*.cc)) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Wno-mismatched-new-delete -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. -c $< -o $@
# Lua's C runtime is emitted only by the namespaced scripting object; the second library
# supplies that shared runtime, as in multidb-unit, without crossing database state.
build/netcmd-unit-db0: $(NETCMD_DB0_TEST_OBJ) $(patsubst build/%,build/db0/%,$(NETCMD_LIB_OBJ)) $(CORE_TEST_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=mkstemp -Wl,--wrap=fopen

# R7 uses real Clients/ROB slots, without a listener or worker loop.
# The 128-task queue cases retain their historical name after the unused
# production pipeline preset was removed. Keep that alias confined to tests.
build/reorder-unit build/reorder-unit-asan build/r7shadow-unit build/r7shadow-unit-asan: override CXXFLAGS += -DkGenthreadPipelineExBatchOps=128
build/reorderscan-unit: tests/reorderscan_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. $< -o $@
build/reorderscan-unit-asan: tests/reorderscan_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -O1 -fsanitize=address,undefined -fno-omit-frame-pointer -I. $< -o $@

build/reorder-unit: tests/reorder_unit.cc tests/reorder_batch_fixture.h $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -I. $< -o $@
build/reorder-unit-asan: tests/reorder_unit.cc tests/reorder_batch_fixture.h $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -O1 -fsanitize=address,undefined -fno-omit-frame-pointer -I. $< -o $@

build/reorder-engagement-unit: tests/reorder_engagement_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
build/reorder-engagement-unit-db0: tests/reorder_engagement_unit.cc $(DB0_TEST_OBJ) $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< \
	  $(DB0_TEST_OBJ) $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

# Serverless R7 receipts, also independent gate rows. The FIFO twin is kind A:
# candidate text size/layout with the cold capability disabled, never a server.
.PHONY: reorder-checks
reorder-checks: $(BIN) build/reorder-engagement-unit build/reorder-engagement-unit-db0
	@mkdir -p build/reorder-checks/multi build/reorder-checks/db0 build/reorder-checks/identity
	python3 tests/r7shadow_sync.py
	python3 tests/r7shadow_sync_test.py
	python3 tests/reorder_receipt.py build/reorder-engagement-unit build/reorder-checks/multi --engagement
	python3 tests/reorder_receipt.py build/reorder-engagement-unit-db0 build/reorder-checks/db0 --engagement
	python3 tests/reorder_receipt.py $(BIN) build/reorder-checks/identity

# Test-only path counters in every R7 envelope plus a complete C++ allocation trace.
# The release objects/binary have no instrumentation; neither unit starts a server.
build/r7shadow3/reorder-witness.o: src/core/reorder.cc tests/r7shadow_witness.h $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_R7_WITNESS -include tests/r7shadow_witness.h -I. -c $< -o $@
build/r7shadow-split-unit: tests/r7shadow_split_unit.cc tests/reorder_engagement_unit.cc tests/r7shadow_witness.h build/r7shadow3/reorder-witness.o $(filter-out build/src/core/reorder.o,$(CORE_TEST_OBJ)) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_R7_WITNESS -DTOMO_R7_WITNESS_MAIN -Wno-mismatched-new-delete \
	  -include tests/r7shadow_witness.h -I. $< build/r7shadow3/reorder-witness.o \
	  $(filter-out build/src/core/reorder.o,$(CORE_TEST_OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm
build/r7shadow3/reorder-witness-db0.o: src/core/reorder.cc tests/r7shadow_witness.h $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 \
	  -DTOMO_R7_WITNESS -include tests/r7shadow_witness.h -I. -c $< -o $@
build/r7shadow-split-unit-db0: tests/r7shadow_split_unit.cc tests/reorder_engagement_unit.cc tests/r7shadow_witness.h build/r7shadow3/reorder-witness-db0.o $(filter-out build/db0/src/core/reorder.o,$(DB0_TEST_OBJ)) $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 \
	  -DTOMO_R7_WITNESS -DTOMO_R7_WITNESS_MAIN -Wno-mismatched-new-delete \
	  -include tests/r7shadow_witness.h -I. $< build/r7shadow3/reorder-witness-db0.o \
	  $(filter-out build/db0/src/core/reorder.o,$(DB0_TEST_OBJ)) $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

build/r7shadow-unit: tests/r7shadow_unit.cc tests/reorder_batch_fixture.h $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -I. $< -o $@
build/r7shadow-unit-asan: tests/r7shadow_unit.cc tests/reorder_batch_fixture.h $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -O1 -fsanitize=address,undefined -fno-omit-frame-pointer -I. $< -o $@

# Instructions only, no rate/timing benchmark and no server. Run on compile CPUs.
build/r7shadow-instr: tests/r7shadow_instr.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -I. $< -o $@

# Existing route row owns IO accounting/model/physical-placement proofs.
build/mdbqsbr-asan/tests/core_concurrency_unit.o build/mdbqsbr-tsan/tests/core_concurrency_unit.o: tests/signalacct_core_checks.inc tests/flip_close_checks.inc tests/flipsettle_checks.inc tests/flipreport_checks.inc tests/flipfix_checks.inc tests/slowlog_completion_checks.inc tests/wave5_dispatch_checks.inc
# Fast serverless lane entry; the gate uses its existing fully instrumented route row.
build/signalacct-core-unit: tests/core_concurrency_unit.cc tests/signalacct_core_checks.inc tests/flip_close_checks.inc tests/flipsettle_checks.inc tests/flipreport_checks.inc tests/flipfix_checks.inc tests/slowlog_completion_checks.inc tests/wave5_dispatch_checks.inc $(CORE_TEST_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_CORE_CONCURRENCY_TEST -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

# Measured fused writeback rule, serverless production-path witnesses. Clause
# mutants live only in build/ header overlays; no selector enters production.
WB_RULE_POLICY_CONTROLS := scatter-exit fastpath staged-clause staged-source submitted done-bytes spill direct borrow crlf no-sum floor whole hole marker code relaxed pre-read walk-tail
WB_RULE_PHASE_CONTROLS := budget rotation head pin capture visit dead work split-policy split-local split-budget split-ex parse split-aof
WB_RULE_CONTROL_DEPS := tests/wb_rule_checks.py tests/wb_rule_unit.cc tests/wb_rule_phase_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
WB_RULE_WRAP := -Wl,--wrap=io_uring_submit -Wl,--wrap=io_uring_submit_and_get_events
build/wb-rule-unit: tests/wb_rule_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< -o $@ $(JELIBS)
build/wb-rule-db0-unit: tests/wb_rule_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< -o $@ $(JELIBS)
build/wb-rule-phase-unit: build/tests/wb_rule_phase_unit.o $(CORE_TEST_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm $(WB_RULE_WRAP)
build/wb-rule-db0-phase-unit: build/db0/tests/wb_rule_phase_unit.o $(DB0_TEST_OBJ) $(CORE_TEST_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm $(WB_RULE_WRAP)
$(addprefix build/wb-rule-controls/,$(addsuffix /unit,$(WB_RULE_POLICY_CONTROLS))): build/wb-rule-controls/%/unit: $(WB_RULE_CONTROL_DEPS)
	@mkdir -p build/wb-rule-controls/$*/source
	python3 tests/wb_rule_checks.py emit $* build/wb-rule-controls/$*/source
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Ibuild/wb-rule-controls/$*/source -I. tests/wb_rule_unit.cc -o $@ $(JELIBS)
$(addprefix build/wb-rule-controls/,$(addsuffix /unit,$(WB_RULE_PHASE_CONTROLS))): build/wb-rule-controls/%/unit: $(WB_RULE_CONTROL_DEPS) $(CORE_TEST_OBJ)
	@mkdir -p build/wb-rule-controls/$*/source
	python3 tests/wb_rule_checks.py emit $* build/wb-rule-controls/$*/source
	$(CXX) $(CXXFLAGS) -O0 -g0 $(JEFLAGS) -Ibuild/wb-rule-controls/$*/source -I. tests/wb_rule_phase_unit.cc $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm $(WB_RULE_WRAP)
.PHONY: wb-rule-units
wb-rule-units: build/wb-rule-units
build/wb-rule-units: build/wb-rule-unit build/wb-rule-db0-unit build/wb-rule-phase-unit build/wb-rule-db0-phase-unit $(addprefix build/wb-rule-controls/,$(addsuffix /unit,$(WB_RULE_POLICY_CONTROLS) $(WB_RULE_PHASE_CONTROLS)))
	@mkdir -p $(dir $@)
	@touch $@

# Completion witnesses and clause-deletion controls share the existing wbland rows.
WB_RULE_COMPLETION_CONTROLS := small-early small-late visits-early visits-late serve-reset knob-small-ignored knob-unbounded-ignored knob-unbounded-wrap
WB_RULE_COMPLETION_DEPS := tests/wb_rule_completion_unit.cc tests/wb_rule_checks.py $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
WB_RULE_COMPLETION_UNITS := build/wb-rule-completion-unit build/wb-rule-db0-completion-unit $(foreach name,$(WB_RULE_COMPLETION_CONTROLS),build/wb-rule-completion-controls/$(name)/unit build/wb-rule-completion-controls/$(name)/db0-unit)
build/wb-rule-completion-unit: $(WB_RULE_COMPLETION_DEPS)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< -o $@ $(JELIBS)
build/wb-rule-db0-completion-unit: $(WB_RULE_COMPLETION_DEPS)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< -o $@ $(JELIBS)
$(addprefix build/wb-rule-completion-controls/,$(addsuffix /source/.emitted,$(WB_RULE_COMPLETION_CONTROLS))): build/wb-rule-completion-controls/%/source/.emitted: $(WB_RULE_COMPLETION_DEPS)
	@mkdir -p $(dir $@)
	python3 tests/wb_rule_checks.py emit $* build/wb-rule-completion-controls/$*/source
	@touch $@
build/wb-rule-completion-controls/%/unit: build/wb-rule-completion-controls/%/source/.emitted $(WB_RULE_COMPLETION_DEPS)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Ibuild/wb-rule-completion-controls/$*/source -I. tests/wb_rule_completion_unit.cc -o $@ $(JELIBS)
build/wb-rule-completion-controls/%/db0-unit: build/wb-rule-completion-controls/%/source/.emitted $(WB_RULE_COMPLETION_DEPS)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -Ibuild/wb-rule-completion-controls/$*/source -I. tests/wb_rule_completion_unit.cc -o $@ $(JELIBS)

# Fixed writeback policies: all fixtures are serverless; gate owns execution.
WBLAND_CONTROLS := flushall half empty byte-limit
build/wbland-unit: tests/wbland_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< -o $@ $(JELIBS)
build/wbland-db0-unit: tests/wbland_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< -o $@ $(JELIBS)
build/wbland-clause-unit: tests/wbland_clause_unit.cc tests/wb_rule_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< -o $@ $(JELIBS)
build/wbland-db0-clause-unit: tests/wbland_clause_unit.cc tests/wb_rule_unit.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< -o $@ $(JELIBS)
$(addprefix build/wbland-controls/,$(addsuffix /unit,$(WBLAND_CONTROLS))): build/wbland-controls/%/unit: tests/wbland_checks.py tests/wbland_unit.cc $(WB_RULE_CONTROL_DEPS)
	@mkdir -p build/wbland-controls/$*/source
	python3 tests/wbland_checks.py emit $* build/wbland-controls/$*/source
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Ibuild/wbland-controls/$*/source -I. tests/wbland_unit.cc -o $@ $(JELIBS)
$(addprefix build/wbland-clause-controls/,$(addsuffix /unit,$(WB_RULE_POLICY_CONTROLS))): build/wbland-clause-controls/%/unit: tests/wbland_clause_unit.cc $(WB_RULE_CONTROL_DEPS)
	@mkdir -p build/wbland-clause-controls/$*/source
	python3 tests/wb_rule_checks.py emit $* build/wbland-clause-controls/$*/source
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Ibuild/wbland-clause-controls/$*/source -I. tests/wbland_clause_unit.cc -o $@ $(JELIBS)
.PHONY: wbland-units
wbland-units: build/wbland-units
build/wbland-units: $(WB_RULE_COMPLETION_UNITS) build/wbland-unit build/wbland-db0-unit build/wbland-clause-unit build/wbland-db0-clause-unit build/wb-rule-units $(addprefix build/wbland-controls/,$(addsuffix /unit,$(WBLAND_CONTROLS))) $(addprefix build/wbland-clause-controls/,$(addsuffix /unit,$(WB_RULE_POLICY_CONTROLS)))
	@mkdir -p $(dir $@)
	@touch $@

# cleanup-lanefull extends the existing core route row; no new gate emission.
build/mdbqsbr-asan/tests/core_concurrency_unit.o build/mdbqsbr-tsan/tests/core_concurrency_unit.o build/signalacct-core-unit: tests/lanefull_checks.inc
# Fast direct-call db0 variant; both database implementations retain their existing object flags.
build/lanefull-db0-unit: tests/core_concurrency_unit.cc tests/lanefull_checks.inc $(DB0_TEST_OBJ) $(CORE_TEST_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_CORE_CONCURRENCY_TEST -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< $(DB0_TEST_OBJ) $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

# SV2: production control flow; replace only the disk writer in the serverless witness.
SHUTDOWN_WRAP := -Wl,--wrap=_ZN4tomo15SnapshotManager5startERNS_6ServerERNS_9ThreadCtxERNS_4RingEbRNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEEPNS_10AofManagerEPKcSH_b -Wl,--wrap=clock_gettime
SHUTDOWN_UNIT_OBJ = $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ))
$(BUILD_ROOT)/tests/shutdown_unit.o: tests/shutdown_client_checks.inc

$(BUILD_ROOT)/shutdown-unit: $(BUILD_ROOT)/tests/shutdown_unit.o $(SHUTDOWN_UNIT_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm $(SHUTDOWN_WRAP)
# Shutdown/SAVE supervisor schedules; no listener or worker loop is started.
$(BUILD_ROOT)/shutsave-unit: $(BUILD_ROOT)/tests/shutsave_unit.o $(SHUTDOWN_UNIT_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=clock_gettime -Wl,--wrap=fdatasync
# NET1 bounds, linear scan, and actual deferred client reclamation; no server is started.
build/netcap-unit: build/tests/netcap_unit.o $(CORE_TEST_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=free

# CT1-CT3 serverless handoff; the planner object is production code, no live loops.
LBPLANNER_WRAP := -Wl,--wrap=pthread_mutex_trylock -Wl,--wrap=pthread_mutex_lock
build/lbplanner-unit: tests/lbplanner_unit.cc tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_CORE_CONCURRENCY_TEST -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm $(LBPLANNER_WRAP)
build/lbplanner-unit-tsan: tests/lbplanner_unit.cc tests/core_concurrency_unit.cc $(MDBQSBR_TSAN_OBJ) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(MDBQSBR_FLAGS) -fsanitize=thread $< $(MDBQSBR_TSAN_OBJ) -o $@ $(LDLIBS) -lm $(LBPLANNER_WRAP)

LBPLANNER_CONTROLS := no-publish stale-flip stale-lb duplicate copy-on-io record-reuse
LBPLANNER_TIMING_CONTROLS := timing-lock timing-late-pause timing-budget
build/lbplanner-controls/%/source/src/core/io_loop.h: tools/lbplanner_controls.py $(SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc)
	@mkdir -p $(dir $@)
	python3 tools/lbplanner_controls.py $* $@
$(foreach arm,$(LBPLANNER_TIMING_CONTROLS),build/lbplanner-controls/$(arm)/unit): build/lbplanner-controls/%/unit: build/lbplanner-controls/%/source/src/core/io_loop.h tests/lbplanner_unit.cc tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_CORE_CONCURRENCY_TEST -Ibuild/lbplanner-controls/$*/source -I. tests/lbplanner_unit.cc $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm $(LBPLANNER_WRAP)
build/lbplanner-controls/%/lbplanner.cc: tools/lbplanner_controls.py src/core/lbplanner.cc
	@mkdir -p $(dir $@)
	python3 tools/lbplanner_controls.py $* $@
build/lbplanner-controls/%/lbplanner.o: build/lbplanner-controls/%/lbplanner.cc $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -iquote src/core -I. -c $< -o $@
build/lbplanner-controls/%/unit: build/lbplanner-controls/%/lbplanner.o tests/lbplanner_unit.cc tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_CORE_CONCURRENCY_TEST -I. tests/lbplanner_unit.cc $< $(filter-out build/src/core/lbplanner.o,$(CORE_TEST_OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm $(LBPLANNER_WRAP)
build/lbplanner-unit-pad: build/lbplanner-unit tools/lbplanner_pad.py tools/rlfence_artifacts.py tools/lbstall_artifacts.py
	@mkdir -p $(dir $@) build/lbplanner-unit-pad-proof
	python3 tools/lbplanner_pad.py $< $@ build/lbplanner-unit-pad-proof > build/lbplanner-unit-pad.log
build/tomokv-lbplanner-pad: build/tomokv tools/lbplanner_pad.py tools/rlfence_artifacts.py tools/lbstall_artifacts.py
	@mkdir -p $(dir $@) build/lbplanner-pad-proof
	python3 tools/lbplanner_pad.py $< $@ build/lbplanner-pad-proof > build/lbplanner-pad.log
build/lbosc3-unit-pad: build/lbplanner-unit tools/lbosc3_pad.py
	@mkdir -p build/lbosc3/unit-pad-proof
	python3 tools/lbosc3_pad.py $< $@ build/lbosc3/unit-pad-proof > build/lbosc3/unit-pad.log
build/lbplanner-units: build/lbplanner-unit build/lbplanner-unit-pad build/lbosc3-unit-pad $(foreach arm,$(LBPLANNER_CONTROLS) $(LBPLANNER_TIMING_CONTROLS),build/lbplanner-controls/$(arm)/unit)
	@mkdir -p $(dir $@)
	@touch $@
.SECONDARY: $(foreach arm,$(LBPLANNER_CONTROLS),build/lbplanner-controls/$(arm)/lbplanner.cc build/lbplanner-controls/$(arm)/lbplanner.o)

build/lbplanner-trace: tools/lbplanner_trace.cc Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $< -o $@

# D2 deterministic owner-turn controls, same fixture against either source arm.
$(BUILD_ROOT)/moverfix-unit: tests/moverfix_unit.cc src/cmd/xshard.cc $(filter-out $(BUILD_ROOT)/src/main.o $(BUILD_ROOT)/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(filter-out $(BUILD_ROOT)/src/main.o $(BUILD_ROOT)/src/cmd/xshard.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm
$(BUILD_ROOT)/moverfix-db0-unit: tests/moverfix_unit.cc src/cmd/xshard.cc $(filter-out $(BUILD_ROOT)/db0/src/main.o $(BUILD_ROOT)/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) $(wildcard src/core/*.inc) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< $(filter-out $(BUILD_ROOT)/db0/src/main.o $(BUILD_ROOT)/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm
