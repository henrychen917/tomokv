CXX      ?= g++
JEDIR    ?= /home/user/Projects/refs/jemalloc/_install
# jemalloc is optional: without it the tree still builds and runs, using the deterministic portable
# size-class table in alloc.h. Set JE=0 to force that path (useful for A/B-ing the allocator).
JE       ?= 1
ifeq ($(JE),1)
  JEFLAGS := -DTOMO_JEMALLOC -I$(JEDIR)/include
  JELIBS  := $(JEDIR)/lib/libjemalloc.a -ldl
else
  JEFLAGS :=
  JELIBS  :=
endif
CXXFLAGS ?= -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread
LDLIBS   ?= -luring -pthread
SRC      := src/main.cc src/cmd/commands.cc
BIN      := build/tomokv

all: $(BIN)

$(BIN): $(SRC) $(wildcard src/*/*.h) Makefile
	@mkdir -p build
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $(SRC) -o $@ $(JELIBS) $(LDLIBS)

asan: CXXFLAGS += -fsanitize=address,undefined -fno-omit-frame-pointer -O1
asan: BIN := build/tomokv-asan
asan:
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. $(SRC) -o build/tomokv-asan $(LDLIBS)

tsan:
	@mkdir -p build
	$(CXX) -std=c++20 -O1 -g -Wall -Wextra -pthread -fsanitize=thread \
	  -I. $(SRC) -o build/tomokv-tsan -luring -pthread

clean:
	rm -rf build
.PHONY: all asan tsan clean
