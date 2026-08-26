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
SRC      := src/main.cc src/cmd/commands.cc src/cmd/xshard.cc src/cmd/acl.cc src/cmd/hll.cc src/cmd/t_server.cc src/cmd/t_string.cc src/cmd/t_string_notify.cc src/cmd/t_hash.cc \
            src/cmd/t_list.cc src/cmd/t_set.cc src/cmd/t_zset.cc src/cmd/scripting.cc src/snapshot/snapshot.cc src/persist/aof.cc
BIN      := build/tomokv
OBJ      := $(SRC:%.cc=build/%.o)

all: $(BIN)

$(BIN): $(OBJ)
	$(CXX) $(CXXFLAGS) $(OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm

# The clean string family intentionally excludes the armed instantiations, but its parsed template
# bodies still move GCC just past the default large-unit threshold. 10400 restores the same inlining
# decisions as the base-b5 translation unit; the objdump gate locks store_string/cmd_set to base.
build/src/cmd/t_string.o: CXXFLAGS += --param large-unit-insns=10400

build/%.o: %.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) $(wildcard third_party/lua/*) Makefile
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. -c $< -o $@

asan: CXXFLAGS += -fsanitize=address,undefined -fno-omit-frame-pointer -O1
asan: BIN := build/tomokv-asan
asan:
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. $(SRC) -o build/tomokv-asan $(LDLIBS) -lm

tsan:
	@mkdir -p build
	$(CXX) -std=c++20 -O1 -g -Wall -Wextra -pthread -fsanitize=thread \
	  -I. $(SRC) -o build/tomokv-tsan -luring -pthread -lm

clean:
	rm -rf build
.PHONY: all asan tsan clean
