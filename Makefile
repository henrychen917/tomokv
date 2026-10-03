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
SRC      += src/cmd/l4prebuild.cc
SRC      += src/cmd/cmdgap.cc
SRC      += src/cmd/pfdebug.cc
SRC      += src/cmd/cmdmeta.cc
SRC      += src/cmd/t_sort.cc
SRC      += src/cmd/multidb.cc
# Preserve mainline weak-symbol selection; isolated R7 bodies link last.
SRC      += src/core/reorder.cc
LDLIBS   += -lssl -lcrypto
BUILD_ROOT ?= build
BIN      := $(BUILD_ROOT)/tomokv
OBJ      := $(SRC:%.cc=$(BUILD_ROOT)/%.o)
DB0_OBJ  := $(SRC:%.cc=$(BUILD_ROOT)/db0/%.o)

all: $(BIN)

# PS1/PS2/PS14 schedules call the actual AOF implementation without starting a
# listener or ring. Controls are throwaway source copies with one fix removed.
PERSISTFIX_CONTROLS := old-ack old-close no-refusal
PERSISTFIX_CORE = $(filter-out build/src/main.o build/src/persist/aof.o,$(OBJ))
build/persistfix/aof-test.o: src/persist/aof.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_PERSISTFIX_TEST -I. -c $< -o $@
build/persistfix/unit.o: tests/persistfix_unit.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_PERSISTFIX_TEST -I. -c $< -o $@
build/persistfix-unit: build/persistfix/unit.o build/persistfix/aof-test.o $(PERSISTFIX_CORE)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
build/persistfix-controls/%/aof.cc: tools/persistfix_controls.py src/persist/aof.cc Makefile
	python3 tools/persistfix_controls.py $* $@
build/persistfix-controls/%/aof.o: build/persistfix-controls/%/aof.cc $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_PERSISTFIX_TEST -Isrc/persist -I. -c build/persistfix-controls/$*/aof.cc -o $@
build/persistfix-controls/%/db0-aof.o: build/persistfix-controls/%/aof.cc $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -DTOMO_PERSISTFIX_TEST -Isrc/persist -I. -c $< -o $@
build/persistfix-controls/%/unit: build/persistfix-controls/%/aof.o build/persistfix/unit.o $(PERSISTFIX_CORE)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
.PHONY: persistfix-units
persistfix-units: build/persistfix-units
build/persistfix-units: build/persistfix-unit $(foreach arm,$(PERSISTFIX_CONTROLS),build/persistfix-controls/$(arm)/unit)
	@touch $@
.SECONDARY: $(foreach arm,$(PERSISTFIX_CONTROLS),build/persistfix-controls/$(arm)/aof.o)
.SECONDARY: $(foreach arm,$(PERSISTFIX_CONTROLS),build/persistfix-controls/$(arm)/aof.cc)
build/persistfix-controls/%/tomokv: build/persistfix-controls/%/aof.o build/persistfix-controls/%/db0-aof.o $(filter-out build/src/persist/aof.o,$(OBJ)) $(filter-out build/db0/src/persist/aof.o,$(DB0_OBJ))
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
.PHONY: persistfix-live-controls
persistfix-live-controls: build/persistfix-controls/old-ack/tomokv build/persistfix-controls/old-close/tomokv

$(BIN): $(OBJ) $(DB0_OBJ)
	$(CXX) $(CXXFLAGS) $(DB0_OBJ) $(OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

# The clean string family intentionally excludes the armed instantiations, but its parsed template
# bodies still move GCC just past the default large-unit threshold. 10600 restores the same inlining
# decisions as the base-420b4d492 translation unit; the objdump gate locks cmd_get/cmd_set to base.
$(BUILD_ROOT)/src/cmd/t_string.o: override CXXFLAGS += --param large-unit-insns=10600
$(BUILD_ROOT)/db0/src/cmd/t_string.o: override CXXFLAGS += --param large-unit-insns=10600
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
$(BUILD_ROOT)/src/main.o: override CXXFLAGS += -DTOMO_DUAL_DATABASE --param inline-unit-growth=0 --param large-unit-insns=146400
$(BUILD_ROOT)/src/core/genthread.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=128865
$(BUILD_ROOT)/src/core/rl2s.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=161715
$(BUILD_ROOT)/db0/src/main.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=146214
$(BUILD_ROOT)/db0/src/core/genthread.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=128880
$(BUILD_ROOT)/db0/src/core/rl2s.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=161715
$(BUILD_ROOT)/db0/src/core/reorder.o: override CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=147380
$(BUILD_ROOT)/db0/src/cmd/l4prebuild.o: src/cmd/t_string.cc

# Separate C++ namespaces prevent accidental cross-variant inline/COMDAT binding.
# The only shared code is third-party Lua; all database state is variant-private.
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
	$(CXX) $(CXXFLAGS) -I. tests/ktls_keyupdate_unit.cc src/net/tls.cc -o $@ \
	  -Wl,--wrap=BIO_ctrl -Wl,--wrap=setsockopt -lssl -lcrypto
build/splitlocal-unit.cc: tests/splitlocal_checks.py tests/r7shadow_sync.py tools/reorder_sync.py src/core/io_loop.h src/core/reorder.cc src/core/genthread_pipeline.h
	python3 tests/splitlocal_checks.py emit $@
build/splitlocal-unit: build/splitlocal-unit.cc Makefile
	$(CXX) $(CXXFLAGS) $< -o $@
build/config-parser-test: tests/config_parser_test.cc tests/boot_support_checks.inc $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/config_parser_test.cc -o $@
build/flipctl-unit: tests/flipctl_unit.cc tests/signalacct_checks.h src/core/flipctl.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/flipctl_unit.cc src/core/flipctl.cc -o $@
# The fused owner's deferred-reclaim ring (QSBR batches) against a per-entry reference model.
build/read-local-ring-unit: tests/read_local_ring_unit.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/read_local_ring_unit.cc -o $@
build/read-local-write-ring-unit: tests/read_local_write_ring_unit.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/read_local_write_ring_unit.cc -o $@
STORE_REGRESSION_SRC := tests/store_regression.cc src/cmd/t_hash.cc src/cmd/t_hash_ttl.cc
build/store-regression: $(STORE_REGRESSION_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -ffunction-sections -fdata-sections -DTOMO_STORE_REGRESSION_TEST -I. \
	  $(STORE_REGRESSION_SRC) -Wl,--gc-sections -o $@
build/store-regression-sidecar: $(STORE_REGRESSION_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -ffunction-sections -fdata-sections -DTOMO_STORE_REGRESSION_TEST \
	  -DTOMO_TTL_DEADLINE_SIDECAR=1 -I. $(STORE_REGRESSION_SRC) -Wl,--gc-sections -o $@
build/store-regression-tsan: $(STORE_REGRESSION_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -O1 -fsanitize=thread -fno-omit-frame-pointer -no-pie \
	  -ffunction-sections -fdata-sections -DTOMO_STORE_REGRESSION_TEST -I. \
	  $(STORE_REGRESSION_SRC) -Wl,--gc-sections -o $@
build/waits-unit: tests/waits_unit.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. tests/waits_unit.cc -o $@
unit: build/reorder-unit build/r7shadow-unit build/config-parser-test build/flipctl-unit build/read-local-ring-unit build/read-local-write-ring-unit build/waits-unit
	./build/reorder-unit
	./build/r7shadow-unit
	./build/config-parser-test
	./build/flipctl-unit
	./build/read-local-ring-unit
	./build/read-local-write-ring-unit
	./build/waits-unit

# Deterministic core regressions: the test TU instantiates the real executor/IO methods
# with ASAN/UBSAN and test-only interleaving hooks. No server or ring is started.
CORE_TEST_OBJ := $(filter-out build/src/main.o,$(OBJ))
DB0_TEST_OBJ := $(filter-out build/db0/src/main.o,$(DB0_OBJ))
# ST1/ST10 serverless proofs. PRE objects are kept by the lane before editing;
# the control target substitutes just the two command objects in both images.
FLUSHFIX_UNIT_OBJ := build/tests/flushfix_unit.o build/db0/tests/flushfix_unit.o
FLUSHFIX_COMMAND_OBJ := build/src/cmd/t_server.o build/src/cmd/multidb.o build/db0/src/cmd/t_server.o build/db0/src/cmd/multidb.o
build/flushfix-unit: $(FLUSHFIX_UNIT_OBJ) $(DB0_TEST_OBJ) $(CORE_TEST_OBJ)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
build/flushfix-pre-unit: $(FLUSHFIX_UNIT_OBJ) $(filter-out $(FLUSHFIX_COMMAND_OBJ),$(DB0_TEST_OBJ) $(CORE_TEST_OBJ)) $(addprefix build/flushfix/pre/,$(patsubst build/%,%,$(FLUSHFIX_COMMAND_OBJ)))
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
build/flushfix/pre-source/.emitted: tests/flushfix_checks.py
	python3 tests/flushfix_checks.py emit-pre build/flushfix/pre-source
build/flushfix/pre/src/cmd/%.o: build/flushfix/pre-source/.emitted
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. -c build/flushfix/pre-source/src/cmd/$*.cc -o $@
build/flushfix/pre/db0/src/cmd/%.o: build/flushfix/pre-source/.emitted
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. -c build/flushfix/pre-source/src/cmd/$*.cc -o $@
build/kvobj-header-unit: tests/kvobj_header_unit.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< -o $@ $(JELIBS)
build/kvobj-header-db0-unit: tests/kvobj_header_unit.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< -o $@ $(JELIBS)
FLUSHFIX_HEADER_SITES := raw int string typeval embedded reheader
build/flushfix-header-controls/%/unit: tests/kvobj_header_unit.cc tests/flushfix_checks.py $(wildcard src/*/*.h) Makefile
	python3 tests/flushfix_checks.py emit-header $* build/flushfix-header-controls/$*/source
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Ibuild/flushfix-header-controls/$*/source -I. $< -o $@ $(JELIBS)
build/flushfix-units: build/flushfix-unit build/kvobj-header-unit build/kvobj-header-db0-unit $(addprefix build/flushfix-header-controls/,$(addsuffix /unit,$(FLUSHFIX_HEADER_SITES)))
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
MDBQSBR_FLAGS := -std=c++20 -O1 -g -Wall -Wextra -march=native -pthread \
  -fno-omit-frame-pointer -no-pie -DTOMO_MDBQSBR_TEST -DTOMO_CORE_CONCURRENCY_TEST -I.
MDBQSBR_WRAP := -Wl,--wrap=_ZN4tomo11AofProducer19record_database_mapEPKh
build/mdbqsbr-asan/%.o: %.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(MDBQSBR_FLAGS) -fsanitize=address,undefined -c $< -o $@
build/mdbqsbr-tsan/%.o: %.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(MDBQSBR_FLAGS) -fsanitize=thread -c $< -o $@
build/mdbqsbr-asan/src/cmd/l4prebuild.o build/mdbqsbr-tsan/src/cmd/l4prebuild.o: src/cmd/t_string.cc
build/mdbqsbr-unit: build/mdbqsbr-asan/tests/mdbqsbr_unit.o $(MDBQSBR_ASAN_OBJ)
	$(CXX) $(MDBQSBR_FLAGS) -fsanitize=address,undefined $^ -o $@ $(LDLIBS) -lm $(MDBQSBR_WRAP)
build/mdbqsbr-unit-tsan: build/mdbqsbr-tsan/tests/mdbqsbr_unit.o $(MDBQSBR_TSAN_OBJ)
	$(CXX) $(MDBQSBR_FLAGS) -fsanitize=thread $^ -o $@ $(LDLIBS) -lm $(MDBQSBR_WRAP)
build/core-concurrency-mdbqsbr-asan: build/mdbqsbr-asan/tests/core_concurrency_unit.o $(MDBQSBR_ASAN_OBJ)
	$(CXX) $(MDBQSBR_FLAGS) -fsanitize=address,undefined $^ -o $@ $(LDLIBS) -lm
build/rltopo-unit: build/mdbqsbr-asan/tests/rltopo_unit.o $(MDBQSBR_ASAN_OBJ)
	$(CXX) $(MDBQSBR_FLAGS) -fsanitize=address,undefined $^ -o $@ $(LDLIBS) -lm
build/core-concurrency-mdbqsbr-tsan: build/mdbqsbr-tsan/tests/core_concurrency_unit.o $(MDBQSBR_TSAN_OBJ)
	$(CXX) $(MDBQSBR_FLAGS) -fsanitize=thread $^ -o $@ $(LDLIBS) -lm
build/multidb-unit: | build/mdbqsbr-unit
# Real-boot wake proof twins, never measurement arms. Both extend only the idle
# wait beyond the client's derived deadline; the negative removes database wakes.
# Keep flags consistent in every implementation TU (including inline Ring code).
.PHONY: mdbqsbr-live-arms
mdbqsbr-live-arms:
	$(MAKE) BUILD_ROOT=build/mdbqsbr2-park CXXFLAGS='$(CXXFLAGS) -DTOMO_MDBQSBR_LIVE_PARK' all
	$(MAKE) BUILD_ROOT=build/mdbqsbr2-no-wake CXXFLAGS='$(CXXFLAGS) -DTOMO_MDBQSBR_LIVE_PARK -DTOMO_MDBQSBR_NO_WAKE' all

build/multidb-boundary-unit: tests/multidb_boundary_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
build/multidb-cost-unit: tests/multidb_cost_unit.cc $(CORE_TEST_OBJ) $(DB0_TEST_OBJ) $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< $(DB0_TEST_OBJ) $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
build/multidb-cost-unit-multi: tests/multidb_cost_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_COST_NAMESPACED=1 -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
build/tomokv-multidb2-pad: build/tomokv tools/multidb2_artifacts.py tools/lbstall_artifacts.py
	python3 tools/multidb2_artifacts.py $< $@ > build/multidb2-pad.json
build/tomokv-multidb-pad: build/tomokv tools/multidb_artifacts.py tools/lbstall_artifacts.py
	python3 tools/multidb_artifacts.py $< $@ > build/multidb-pad.json
build/rehash-waits-unit: tests/rehash_waits_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

# Whole owner batches and live WATCH blockers; this unit starts no server.
build/overlap-prefetch-unit: tests/overlap_prefetch_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

build/core-concurrency-unit: build/core-concurrency-mdbqsbr-asan
	cp $< $@

# Directed owner-phase tests. The test includes xshard.cc to drive the real private phases
# without starting worker threads or opening a listener; all other code is the release objects.
build/atomic-survivors-unit: tests/atomiccollapse_checks.inc tests/atomic_plain_checks.inc
build/atomic-survivors-unit: tests/atomic_survivors_unit.cc src/cmd/xshard.cc $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. tests/atomic_survivors_unit.cc \
	  $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm

# Inspect real record/header allocation arenas on pinned owner threads, including abort cleanup
# and quiesced shard handoff. JE=1 is required; no server or io_uring instance is started.
build/owner-arena-unit: tests/owner_arena_unit.cc tests/at_recycle_checks.inc src/cmd/xshard.cc $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) Makefile
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
build/l4prebuild-unit: tests/l4prebuild_unit.cc tests/owner_arena_unit.cc src/cmd/xshard.cc $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) $(L4PREBUILD_TEST_FLAGS) -I. $< \
	  $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) -o $@ \
	  $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=mallocx -Wl,--wrap=sdallocx

# R7 kind A: mainline FIFO behavior in an exact copy of POST text and layout.
# The offline patch disables only the boot capability; L4 prebuild stays enabled.
build/tomokv-pad: $(BIN) tests/r7shadow_pad.py tools/lbstall_artifacts.py
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
build/l4prebuild-unit-tsan: tests/l4prebuild_unit.cc tests/owner_arena_unit.cc src/cmd/xshard.cc $(L4PREBUILD_TSAN_COMMON) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) Makefile
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
build/tests/netcmd_unit.o build/db0/tests/netcmd_unit.o: tests/tlsserve_checks.inc tests/hexpire_oom_checks.inc
NETCMD_LIB_OBJ := $(filter-out build/src/main.o build/src/cmd/xshard.o build/src/cmd/t_stream_groups.o build/src/cmd/t_zset.o build/src/cmd/server_tail.o,$(OBJ))
build/tests/%.o: tests/%.cc tests/netcmd_unit.h $(wildcard src/*/*.h) $(wildcard src/*/*.cc) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Wno-mismatched-new-delete -I. -c $< -o $@
build/netcmd-unit: $(NETCMD_TEST_OBJ) $(NETCMD_LIB_OBJ)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=mkstemp -Wl,--wrap=fopen

# The same direct-call regressions against the databases=1 runtime selected at boot.
NETCMD_DB0_TEST_OBJ := $(NETCMD_TEST_SRC:tests/%.cc=build/db0/tests/%.o)
build/db0/tests/%.o: tests/%.cc tests/netcmd_unit.h $(wildcard src/*/*.h) $(wildcard src/*/*.cc) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Wno-mismatched-new-delete -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. -c $< -o $@
# Lua's C runtime is emitted only by the namespaced scripting object; the second library
# supplies that shared runtime, as in multidb-unit, without crossing database state.
build/netcmd-unit-db0: $(NETCMD_DB0_TEST_OBJ) $(patsubst build/%,build/db0/%,$(NETCMD_LIB_OBJ)) $(CORE_TEST_OBJ)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=mkstemp -Wl,--wrap=fopen

# R7 uses real Clients/ROB slots, without a listener or worker loop.
build/reorder-unit: tests/reorder_unit.cc $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) -I. $< -o $@
build/reorder-unit-asan: tests/reorder_unit.cc $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) -O1 -fsanitize=address,undefined -fno-omit-frame-pointer -I. $< -o $@

build/reorder-engagement-unit: tests/reorder_engagement_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
build/reorder-engagement-unit-db0: tests/reorder_engagement_unit.cc $(DB0_TEST_OBJ) $(CORE_TEST_OBJ) $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< \
	  $(DB0_TEST_OBJ) $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

# Test-only path counters in every R7 envelope plus a complete C++ allocation trace.
# The release objects/binary have no instrumentation; neither unit starts a server.
build/r7shadow3/reorder-witness.o: src/core/reorder.cc tests/r7shadow_witness.h $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_R7_WITNESS -include tests/r7shadow_witness.h -I. -c $< -o $@
build/r7shadow-split-unit: tests/r7shadow_split_unit.cc tests/reorder_engagement_unit.cc tests/r7shadow_witness.h build/r7shadow3/reorder-witness.o $(filter-out build/src/core/reorder.o,$(CORE_TEST_OBJ)) $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_R7_WITNESS -DTOMO_R7_WITNESS_MAIN -Wno-mismatched-new-delete \
	  -include tests/r7shadow_witness.h -I. $< build/r7shadow3/reorder-witness.o \
	  $(filter-out build/src/core/reorder.o,$(CORE_TEST_OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm
build/r7shadow3/reorder-witness-db0.o: src/core/reorder.cc tests/r7shadow_witness.h $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 \
	  -DTOMO_R7_WITNESS -include tests/r7shadow_witness.h -I. -c $< -o $@
build/r7shadow-split-unit-db0: tests/r7shadow_split_unit.cc tests/reorder_engagement_unit.cc tests/r7shadow_witness.h build/r7shadow3/reorder-witness-db0.o $(filter-out build/db0/src/core/reorder.o,$(DB0_TEST_OBJ)) $(CORE_TEST_OBJ) $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 \
	  -DTOMO_R7_WITNESS -DTOMO_R7_WITNESS_MAIN -Wno-mismatched-new-delete \
	  -include tests/r7shadow_witness.h -I. $< build/r7shadow3/reorder-witness-db0.o \
	  $(filter-out build/db0/src/core/reorder.o,$(DB0_TEST_OBJ)) $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

build/r7shadow-unit: tests/r7shadow_unit.cc $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) -I. $< -o $@
build/r7shadow-unit-asan: tests/r7shadow_unit.cc $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) -O1 -fsanitize=address,undefined -fno-omit-frame-pointer -I. $< -o $@

# Instructions only, no rate/timing benchmark and no server. Run on compile CPUs.
build/r7shadow-instr: tests/r7shadow_instr.cc $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) -I. $< -o $@

# Existing route row owns IO accounting/model/physical-placement proofs.
build/mdbqsbr-asan/tests/core_concurrency_unit.o build/mdbqsbr-tsan/tests/core_concurrency_unit.o: tests/signalacct_core_checks.inc tests/flip_close_checks.inc tests/flipsettle_checks.inc tests/flipreport_checks.inc
# Fast serverless lane entry; the gate uses its existing fully instrumented route row.
build/signalacct-core-unit: tests/core_concurrency_unit.cc tests/signalacct_core_checks.inc tests/flip_close_checks.inc tests/flipsettle_checks.inc tests/flipreport_checks.inc $(CORE_TEST_OBJ)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_CORE_CONCURRENCY_TEST -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

# Measured fused writeback rule, serverless production-path witnesses. Clause
# mutants live only in build/ header overlays; no selector enters production.
WB_RULE_POLICY_CONTROLS := scatter-exit fastpath staged-clause staged-source submitted done-bytes spill direct borrow crlf no-sum floor whole hole marker code relaxed pre-read walk-tail
WB_RULE_PHASE_CONTROLS := budget rotation head pin capture visit dead work split-policy split-local split-budget split-ex parse split-aof gather-policy gather-rotation gather-head gather-pin gather-capture gather-visit gather-dead gather-work gather-chunks gather-aof
WB_RULE_CONTROL_DEPS := tests/wb_rule_checks.py tests/wb_rule_unit.cc tests/wb_rule_phase_unit.cc $(wildcard src/*/*.h) Makefile
WB_RULE_WRAP := -Wl,--wrap=io_uring_submit -Wl,--wrap=io_uring_submit_and_get_events
build/wb-rule-unit: tests/wb_rule_unit.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< -o $@ $(JELIBS)
build/wb-rule-db0-unit: tests/wb_rule_unit.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< -o $@ $(JELIBS)
build/wb-rule-phase-unit: build/tests/wb_rule_phase_unit.o $(CORE_TEST_OBJ)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm $(WB_RULE_WRAP)
build/wb-rule-db0-phase-unit: build/db0/tests/wb_rule_phase_unit.o $(DB0_TEST_OBJ) $(CORE_TEST_OBJ)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm $(WB_RULE_WRAP)
$(addprefix build/wb-rule-controls/,$(addsuffix /unit,$(WB_RULE_POLICY_CONTROLS))): build/wb-rule-controls/%/unit: $(WB_RULE_CONTROL_DEPS)
	python3 tests/wb_rule_checks.py emit $* build/wb-rule-controls/$*/source
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Ibuild/wb-rule-controls/$*/source -I. tests/wb_rule_unit.cc -o $@ $(JELIBS)
$(addprefix build/wb-rule-controls/,$(addsuffix /unit,$(WB_RULE_PHASE_CONTROLS))): build/wb-rule-controls/%/unit: $(WB_RULE_CONTROL_DEPS) $(CORE_TEST_OBJ)
	python3 tests/wb_rule_checks.py emit $* build/wb-rule-controls/$*/source
	$(CXX) $(CXXFLAGS) -O0 -g0 $(JEFLAGS) -Ibuild/wb-rule-controls/$*/source -I. tests/wb_rule_phase_unit.cc $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm $(WB_RULE_WRAP)
.PHONY: wb-rule-units
wb-rule-units: build/wb-rule-units
build/wb-rule-units: build/wb-rule-unit build/wb-rule-db0-unit build/wb-rule-phase-unit build/wb-rule-db0-phase-unit $(addprefix build/wb-rule-controls/,$(addsuffix /unit,$(WB_RULE_POLICY_CONTROLS) $(WB_RULE_PHASE_CONTROLS)))
	@touch $@

# Completion witnesses and clause-deletion controls share the existing wbland rows.
WB_RULE_COMPLETION_CONTROLS := small-early small-late visits-early visits-late gather-reset serve-reset
WB_RULE_COMPLETION_DEPS := tests/wb_rule_completion_unit.cc tests/wb_rule_checks.py $(wildcard src/*/*.h) Makefile
WB_RULE_COMPLETION_UNITS := build/wb-rule-completion-unit build/wb-rule-db0-completion-unit $(foreach name,$(WB_RULE_COMPLETION_CONTROLS),build/wb-rule-completion-controls/$(name)/unit build/wb-rule-completion-controls/$(name)/db0-unit)
build/wb-rule-completion-unit: $(WB_RULE_COMPLETION_DEPS)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< -o $@ $(JELIBS)
build/wb-rule-db0-completion-unit: $(WB_RULE_COMPLETION_DEPS)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< -o $@ $(JELIBS)
$(addprefix build/wb-rule-completion-controls/,$(addsuffix /source/.emitted,$(WB_RULE_COMPLETION_CONTROLS))): build/wb-rule-completion-controls/%/source/.emitted: $(WB_RULE_COMPLETION_DEPS)
	python3 tests/wb_rule_checks.py emit $* build/wb-rule-completion-controls/$*/source
	@touch $@
build/wb-rule-completion-controls/%/unit: build/wb-rule-completion-controls/%/source/.emitted $(WB_RULE_COMPLETION_DEPS)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Ibuild/wb-rule-completion-controls/$*/source -I. tests/wb_rule_completion_unit.cc -o $@ $(JELIBS)
build/wb-rule-completion-controls/%/db0-unit: build/wb-rule-completion-controls/%/source/.emitted $(WB_RULE_COMPLETION_DEPS)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -Ibuild/wb-rule-completion-controls/$*/source -I. tests/wb_rule_completion_unit.cc -o $@ $(JELIBS)

# Fixed writeback policies: all fixtures are serverless; gate owns execution.
WBLAND_CONTROLS := flushall half empty byte-limit
build/wbland-unit: tests/wbland_unit.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< -o $@ $(JELIBS)
build/wbland-db0-unit: tests/wbland_unit.cc $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< -o $@ $(JELIBS)
build/wbland-clause-unit: tests/wbland_clause_unit.cc tests/wb_rule_unit.cc $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< -o $@ $(JELIBS)
build/wbland-db0-clause-unit: tests/wbland_clause_unit.cc tests/wb_rule_unit.cc $(wildcard src/*/*.h) Makefile
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< -o $@ $(JELIBS)
$(addprefix build/wbland-controls/,$(addsuffix /unit,$(WBLAND_CONTROLS))): build/wbland-controls/%/unit: tests/wbland_checks.py tests/wbland_unit.cc $(WB_RULE_CONTROL_DEPS)
	python3 tests/wbland_checks.py emit $* build/wbland-controls/$*/source
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Ibuild/wbland-controls/$*/source -I. tests/wbland_unit.cc -o $@ $(JELIBS)
$(addprefix build/wbland-clause-controls/,$(addsuffix /unit,$(WB_RULE_POLICY_CONTROLS))): build/wbland-clause-controls/%/unit: tests/wbland_clause_unit.cc $(WB_RULE_CONTROL_DEPS)
	python3 tests/wb_rule_checks.py emit $* build/wbland-clause-controls/$*/source
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Ibuild/wbland-clause-controls/$*/source -I. tests/wbland_clause_unit.cc -o $@ $(JELIBS)
.PHONY: wbland-units
wbland-units: build/wbland-units
build/wbland-units: $(WB_RULE_COMPLETION_UNITS) build/wbland-unit build/wbland-db0-unit build/wbland-clause-unit build/wbland-db0-clause-unit build/wb-rule-units $(addprefix build/wbland-controls/,$(addsuffix /unit,$(WBLAND_CONTROLS))) $(addprefix build/wbland-clause-controls/,$(addsuffix /unit,$(WB_RULE_POLICY_CONTROLS)))
	@touch $@

# cleanup-lanefull extends the existing core route row; no new gate emission.
build/mdbqsbr-asan/tests/core_concurrency_unit.o build/mdbqsbr-tsan/tests/core_concurrency_unit.o build/signalacct-core-unit: tests/lanefull_checks.inc
# Fast direct-call db0 variant; both database implementations retain their existing object flags.
build/lanefull-db0-unit: tests/core_concurrency_unit.cc tests/lanefull_checks.inc $(DB0_TEST_OBJ) $(CORE_TEST_OBJ)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_CORE_CONCURRENCY_TEST -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< $(DB0_TEST_OBJ) $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

# NET1 bounds, linear scan, and actual deferred client reclamation; no server is started.
build/netcap-unit: build/tests/netcap_unit.o $(CORE_TEST_OBJ)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=free
