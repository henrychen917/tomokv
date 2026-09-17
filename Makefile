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
LDLIBS   += -lssl -lcrypto
# Each measurement arm owns its objects; switching layouts cannot reuse stale objects.
BUILD    ?= build
AUDIT_ARM ?= 5
AUDIT_FLAGS := -DTOMO_CACHE_AUDIT_ARM=$(AUDIT_ARM)
BIN      := $(BUILD)/tomokv
OBJ      := $(SRC:%.cc=$(BUILD)/%.o)

all: $(BIN)
default: all
.PHONY: default

# A changed selector/compiler must invalidate both production and serverless test objects.
# Keeping the timestamp on an identical stamp avoids rebuilding already completed arms.
.PHONY: audit-config-force
$(BUILD)/cache-audit-build-config: audit-config-force
	@mkdir -p $(BUILD)
	@printf '%s\n' '$(AUDIT_ARM)|$(CXX)|$(JE)' > $@.tmp
	@cmp -s $@ $@.tmp && rm $@.tmp || mv $@.tmp $@

$(BIN): $(OBJ)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) $(OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

# The clean string family intentionally excludes the armed instantiations, but its parsed template
# bodies still move GCC just past the default large-unit threshold. 10600 restores the same inlining
# decisions as the base-420b4d492 translation unit; the objdump gate locks cmd_get/cmd_set to base.
$(BUILD)/src/cmd/t_string.o: CXXFLAGS += --param large-unit-insns=10600
# The isolated prebuild TU reuses the string parser text without emitting its public handlers.
$(BUILD)/src/cmd/l4prebuild.o: src/cmd/t_string.cc

# Retiring the reorder pass changes GCC 13's translation-unit inlining budget. These budgets
# retain the parser, command/store bodies and ordinary split/fused IO schedules against v5.
# The complete byte audit records the remaining split read-local writeback/Unix exceptions
# in MEASURE-REQUEST.md; they are not counted as byte-identity passes.
# Compiler code-generation locks only: no runtime option or request-path branch.
$(BUILD)/src/main.o: CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=146170
$(BUILD)/src/core/genthread.o: CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=128880
$(BUILD)/src/core/rl2s.o: CXXFLAGS += --param inline-unit-growth=0 --param large-unit-insns=161750

$(BUILD)/%.o: %.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) $(wildcard third_party/lua/*) Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) $(JEFLAGS) -I. -c $< -o $@

asan: CXXFLAGS += -fsanitize=address,undefined -fno-omit-frame-pointer -O1
asan:
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) -I. $(SRC) -o $(BUILD)/tomokv-asan $(LDLIBS) -lm

tsan:
	@mkdir -p $(BUILD)
	$(CXX) $(AUDIT_FLAGS) -std=c++20 -O1 -g -Wall -Wextra -pthread -fsanitize=thread \
	  -I. $(SRC) -o $(BUILD)/tomokv-tsan $(LDLIBS) -lm

# The armed-write block cache's ownership laws as assertions: the cache and the QSBR retire ring
# are owner-private (one thread, no lock), each cached block is resident exactly once, each class
# list matches its counter, and every shard's retire sink names its CURRENT owner. Debug-only: the
# residency set and the sampled list walk cost far more than the path they guard. DESIGN-P0REPLY.md.
rlcachedbg:
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) $(JEFLAGS) -DTOMO_RL_CACHE_DEBUG -I. $(SRC) \
	  -o $(BUILD)/tomokv-rlcachedbg $(JELIBS) $(LDLIBS) -lm

# NEGATIVE-CONTROL BUILD for the row above: the same assertions with the ownership-edge rebind
# removed, i.e. the pre-fix behaviour. tests/rlcache_churn.py MUST fail against this binary; a
# detector that cannot report failure proves nothing about the runs that pass.
rlcache-nofix:
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) $(JEFLAGS) -DTOMO_RL_CACHE_DEBUG -DTOMO_RL_CACHE_NO_EAGER_ADOPT -I. $(SRC) \
	  -o $(BUILD)/tomokv-rlcache-nofix $(JELIBS) $(LDLIBS) -lm

# NEGATIVE-CONTROL BUILD for the cross-owner script reservation sub-wave. Identical to the release
# build except that ScriptPhase::Pin arms nothing, so tests/xscript.py counterexample MUST fail
# against it. A detector that cannot report failure proves nothing about the runs that pass.
noreserve:
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) $(JEFLAGS) -DTOMO_XSCRIPT_NO_RESERVE -I. $(SRC) \
	  -o $(BUILD)/tomokv-noreserve $(JELIBS) $(LDLIBS) -lm

# Server-less unit binaries: the config parser and the flip controller. `make unit` builds and
# runs both (neither boots a server). tests/gate.sh's parser row is the same program.
$(BUILD)/config-parser-test: tests/config_parser_test.cc $(wildcard src/*/*.h) Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) -I. tests/config_parser_test.cc -o $@
$(BUILD)/flipctl-unit: tests/flipctl_unit.cc src/core/flipctl.cc $(wildcard src/*/*.h) Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) -I. tests/flipctl_unit.cc src/core/flipctl.cc -o $@
# The fused owner's deferred-reclaim ring (QSBR batches) against a per-entry reference model.
$(BUILD)/read-local-ring-unit: tests/read_local_ring_unit.cc $(wildcard src/*/*.h) Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) -I. tests/read_local_ring_unit.cc -o $@
$(BUILD)/read-local-write-ring-unit: tests/read_local_write_ring_unit.cc $(wildcard src/*/*.h) Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) -I. tests/read_local_write_ring_unit.cc -o $@
STORE_REGRESSION_SRC := tests/store_regression.cc src/cmd/t_hash.cc src/cmd/t_hash_ttl.cc
$(BUILD)/store-regression: $(STORE_REGRESSION_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) -ffunction-sections -fdata-sections -DTOMO_STORE_REGRESSION_TEST -I. \
	  $(STORE_REGRESSION_SRC) -Wl,--gc-sections -o $@
$(BUILD)/store-regression-sidecar: $(STORE_REGRESSION_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) -ffunction-sections -fdata-sections -DTOMO_STORE_REGRESSION_TEST \
	  -DTOMO_TTL_DEADLINE_SIDECAR=1 -I. $(STORE_REGRESSION_SRC) -Wl,--gc-sections -o $@
$(BUILD)/store-regression-tsan: $(STORE_REGRESSION_SRC) $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) -O1 -fsanitize=thread -fno-omit-frame-pointer -no-pie \
	  -ffunction-sections -fdata-sections -DTOMO_STORE_REGRESSION_TEST -I. \
	  $(STORE_REGRESSION_SRC) -Wl,--gc-sections -o $@
$(BUILD)/waits-unit: tests/waits_unit.cc $(wildcard src/*/*.h) Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) -I. tests/waits_unit.cc -o $@
$(BUILD)/cache-layout-test: tests/cache_layout_test.cc $(wildcard src/*/*.h) Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) -I. $< -o $@
unit: $(BUILD)/cache-layout-test $(BUILD)/config-parser-test $(BUILD)/flipctl-unit $(BUILD)/read-local-ring-unit $(BUILD)/read-local-write-ring-unit $(BUILD)/waits-unit
	./$(BUILD)/cache-layout-test $(AUDIT_ARM)
	./$(BUILD)/config-parser-test
	./$(BUILD)/flipctl-unit
	./$(BUILD)/read-local-ring-unit
	./$(BUILD)/read-local-write-ring-unit
	./$(BUILD)/waits-unit

# Deterministic core regressions: the test TU instantiates the real executor/IO methods
# with ASAN/UBSAN and test-only interleaving hooks. No server or ring is started.
CORE_TEST_OBJ := $(filter-out $(BUILD)/src/main.o $(BUILD)/src/core/genthread.o,$(OBJ))
$(BUILD)/rehash-waits-unit: tests/rehash_waits_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) Makefile $(BUILD)/cache-audit-build-config
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) $(JEFLAGS) -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

# Whole owner batches and live WATCH blockers; this unit starts no server.
$(BUILD)/overlap-prefetch-unit: tests/overlap_prefetch_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) Makefile $(BUILD)/cache-audit-build-config
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) $(JEFLAGS) -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

$(BUILD)/core-concurrency-unit: tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) $(JEFLAGS) -O1 -fsanitize=address,undefined -fno-omit-frame-pointer \
	  -DTOMO_CORE_CONCURRENCY_TEST -I. $< $(CORE_TEST_OBJ) -o $@ \
	  $(JELIBS) $(LDLIBS) -lm

# Directed owner-phase tests. The test includes xshard.cc to drive the real private phases
# without starting worker threads or opening a listener; all other code is the release objects.
$(BUILD)/atomic-survivors-unit: tests/atomic_survivors_unit.cc src/cmd/xshard.cc $(filter-out $(BUILD)/src/main.o $(BUILD)/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) Makefile $(BUILD)/cache-audit-build-config
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) $(JEFLAGS) -I. tests/atomic_survivors_unit.cc \
	  $(filter-out $(BUILD)/src/main.o $(BUILD)/src/cmd/xshard.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm

# Inspect real record/header allocation arenas on pinned owner threads, including abort cleanup
# and quiesced shard handoff. JE=1 is required; no server or io_uring instance is started.
$(BUILD)/owner-arena-unit: tests/owner_arena_unit.cc src/cmd/xshard.cc $(filter-out $(BUILD)/src/main.o $(BUILD)/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) Makefile $(BUILD)/cache-audit-build-config
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) $(JEFLAGS) -I. $< \
	  $(filter-out $(BUILD)/src/main.o $(BUILD)/src/cmd/xshard.o,$(OBJ)) -o $@ \
	  $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=mallocx -Wl,--wrap=sdallocx

# The fixture needs eight allowed CPUs. Build on the lane's compile CPUs, then invoke this target
# under taskset (for example 112-119) to check both modes with the read-local lane off and armed.
owner-arena-unit: $(BUILD)/owner-arena-unit
	./$(BUILD)/owner-arena-unit 1s read-local-0
	./$(BUILD)/owner-arena-unit 1s read-local-1
	./$(BUILD)/owner-arena-unit 2s read-local-0
	./$(BUILD)/owner-arena-unit 2s read-local-1
.PHONY: owner-arena-unit

# IO-prebuild policy and lifetime regressions, using pinned serverless L4 workers.
# Read the one production boundary at build time. The fixture's separate comparison oracle
# still catches a disabled/inclusive policy; a one-line boundary edit rebuilds both binaries.
L4PREBUILD_TEST_FLAGS := -DTOMO_L4_PREBUILD_TEST_BOUNDARY=$(shell sed -n 's/^\#define TOMO_L4_PREBUILD_THRESHOLD //p' src/cmd/l4prebuild.cc)
$(BUILD)/l4prebuild-unit: tests/l4prebuild_unit.cc tests/owner_arena_unit.cc src/cmd/xshard.cc $(filter-out $(BUILD)/src/main.o $(BUILD)/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) Makefile $(BUILD)/cache-audit-build-config
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) $(JEFLAGS) $(L4PREBUILD_TEST_FLAGS) -I. $< \
	  $(filter-out $(BUILD)/src/main.o $(BUILD)/src/cmd/xshard.o,$(OBJ)) -o $@ \
	  $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=mallocx -Wl,--wrap=sdallocx

# Default POST uses the one compile-time boundary in src/cmd/l4prebuild.cc (512 B).
# Kind A: PRE allocation behaviour in an exact copy of POST's text size/layout. This
# offline target patches only the noipa policy predicate; it never executes the server.
$(BUILD)/tomokv-l4-pad: $(BIN) tools/l4prebuild_artifacts.py tools/lbstall_artifacts.py
	python3 tools/l4prebuild_artifacts.py $< $@ --receipt $@.json

l4prebuild-unit: $(BUILD)/l4prebuild-unit
	./$(BUILD)/l4prebuild-unit 1s read-local-0
	./$(BUILD)/l4prebuild-unit 1s read-local-1
	./$(BUILD)/l4prebuild-unit 2s read-local-0
	./$(BUILD)/l4prebuild-unit 2s read-local-1

# All production objects linked by these serverless tests are instrumented, not just the
# fixture. Invoke builds and tests under taskset on the lane's CPUs (112-127).
L4PREBUILD_TSAN_FLAGS := -std=c++20 -O1 -g -Wall -Wextra -march=native -pthread \
                         -fsanitize=thread -fno-omit-frame-pointer -no-pie
L4PREBUILD_TSAN_COMMON := $(patsubst $(BUILD)/%.o,$(BUILD)/l4prebuild-tsan/%.o,$(filter-out $(BUILD)/src/main.o $(BUILD)/src/cmd/xshard.o,$(OBJ)))
$(BUILD)/l4prebuild-tsan/%.o: %.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(dir $@)
	$(CXX) $(AUDIT_FLAGS) $(L4PREBUILD_TSAN_FLAGS) $(JEFLAGS) -I. -c $< -o $@
$(BUILD)/l4prebuild-tsan/src/cmd/l4prebuild.o: src/cmd/t_string.cc
$(BUILD)/l4prebuild-unit-tsan: tests/l4prebuild_unit.cc tests/owner_arena_unit.cc src/cmd/xshard.cc $(L4PREBUILD_TSAN_COMMON) $(wildcard src/*/*.inc) $(wildcard src/*/*.h) Makefile $(BUILD)/cache-audit-build-config
	$(CXX) $(AUDIT_FLAGS) $(L4PREBUILD_TSAN_FLAGS) $(JEFLAGS) $(L4PREBUILD_TEST_FLAGS) -I. $< \
	  $(L4PREBUILD_TSAN_COMMON) \
	  -o $@ $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=mallocx -Wl,--wrap=sdallocx

l4prebuild-unit-tsan: $(BUILD)/l4prebuild-unit-tsan
	TSAN_OPTIONS=halt_on_error=1:exitcode=66 setarch x86_64 -R ./$(BUILD)/l4prebuild-unit-tsan 1s read-local-0
	TSAN_OPTIONS=halt_on_error=1:exitcode=66 setarch x86_64 -R ./$(BUILD)/l4prebuild-unit-tsan 1s read-local-1
	TSAN_OPTIONS=halt_on_error=1:exitcode=66 setarch x86_64 -R ./$(BUILD)/l4prebuild-unit-tsan 2s read-local-0
	TSAN_OPTIONS=halt_on_error=1:exitcode=66 setarch x86_64 -R ./$(BUILD)/l4prebuild-unit-tsan 2s read-local-1
.PHONY: l4prebuild-unit l4prebuild-unit-tsan

# Load drivers: not part of `all`, kept compiling here so they cannot rot unnoticed.
$(BUILD)/benchtxn: tools/benchtxn.cc Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) -I. tools/benchtxn.cc -o $@
$(BUILD)/broaden-bench: tests/broaden_bench.cc Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) -I. tests/broaden_bench.cc -o $@
tools: $(BUILD)/benchtxn $(BUILD)/broaden-bench $(BUILD)/tailgen

# Standalone smooth open-loop RESP driver; no server libraries or jemalloc.
TAILGEN_HEADERS := $(wildcard tools/tailgen/*.h)
# Only libc/pthread are dynamic dependencies; bundle the compiler/math runtimes.
TAILGEN_LIBS := -static-libstdc++ -static-libgcc -Wl,-Bstatic,-lstdc++,-lm,-Bdynamic -pthread
$(BUILD)/tailgen: tools/tailgen/main.cc $(TAILGEN_HEADERS) Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) -I. $< -o $@ $(TAILGEN_LIBS)
$(BUILD)/tailgen-unit: tests/tailgen_unit.cc $(TAILGEN_HEADERS) Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) -I. $< -o $@ $(TAILGEN_LIBS)
$(BUILD)/tailgen-unit-asan: tests/tailgen_unit.cc $(TAILGEN_HEADERS) Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) -O1 -fsanitize=address,undefined -fno-omit-frame-pointer -I. $< -o $@ -pthread
$(BUILD)/tailgen-unit-tsan: tests/tailgen_unit.cc $(TAILGEN_HEADERS) Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(BUILD)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) -O1 -fsanitize=thread -fno-omit-frame-pointer -no-pie -I. $< -o $@ -pthread
tailgen: $(BUILD)/tailgen
tailgen-unit: $(BUILD)/tailgen-unit
	./$(BUILD)/tailgen-unit
tailgen-unit-asan: $(BUILD)/tailgen-unit-asan
	./$(BUILD)/tailgen-unit-asan
tailgen-unit-tsan: $(BUILD)/tailgen-unit-tsan
	TSAN_OPTIONS=halt_on_error=1:exitcode=66 setarch x86_64 -R ./$(BUILD)/tailgen-unit-tsan
.PHONY: tailgen tailgen-unit tailgen-unit-asan tailgen-unit-tsan

clean:
	rm -rf $(BUILD)
.PHONY: all asan tsan noreserve clean unit tools

# Deterministic networking/command regressions. These TUs include the real private implementations;
# omit their production objects from this serverless binary. No server threads or gate are started.
NETCMD_TEST_SRC := tests/netcmd_unit.cc tests/netcmd_stream_unit.cc tests/netcmd_zset_unit.cc tests/netcmd_config_unit.cc
NETCMD_TEST_OBJ := $(NETCMD_TEST_SRC:tests/%.cc=$(BUILD)/tests/%.o)
NETCMD_LIB_OBJ := $(filter-out $(BUILD)/src/main.o $(BUILD)/src/cmd/xshard.o $(BUILD)/src/cmd/t_stream_groups.o $(BUILD)/src/cmd/t_zset.o $(BUILD)/src/cmd/server_tail.o,$(OBJ))
$(BUILD)/tests/%.o: tests/%.cc tests/netcmd_unit.h $(wildcard src/*/*.h) $(wildcard src/*/*.cc) $(wildcard src/*/*.inc) Makefile $(BUILD)/cache-audit-build-config
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) $(JEFLAGS) -Wno-mismatched-new-delete -I. -c $< -o $@
$(BUILD)/netcmd-unit: $(NETCMD_TEST_OBJ) $(NETCMD_LIB_OBJ)
	$(CXX) $(CXXFLAGS) $(AUDIT_FLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=mkstemp -Wl,--wrap=fopen

# Offline cache-audit artifacts. The exact-layout kind-A PAD pairs with tomokv-layout;
# tomokv keeps the ordinary release link so it can also be compared with mainline.
# L4 stays enabled in every audit arm; tomokv-l4-pad remains its separate policy control.
build/tomokv-pad build/tomokv-layout &: tools/cache_audit_artifacts.py tools/lbstall_artifacts.py $(wildcard src/*/*.h) Makefile
	python3 tools/cache_audit_artifacts.py matched
cache-audit-arms:
	python3 tools/cache_audit_artifacts.py all
cache-audit-negative:
	python3 tests/cache_audit_negative.py
.PHONY: cache-audit-arms cache-audit-negative
