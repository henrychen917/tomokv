CXX      ?= g++
CXXFLAGS ?= -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread
LDLIBS   ?= -luring -pthread
SRC      := src/main.cc src/cmd/commands.cc
BIN      := build/tomokv

all: $(BIN)

$(BIN): $(SRC) $(wildcard src/*/*.h)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -I. $(SRC) -o $@ $(LDLIBS)

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
