# blockrace finding (a): deterministic two-offer / no-offer completion schedules. Cold blocking
# witnesses use the production implementation (xshard.cc), without a server. The TOMO_BLOCKING_
# COMPLETION_UNIT hook they drive compiles out of every production build (calib/binary-neutral.sh).
$(BUILD_ROOT)/blockrace-unit: tests/blockrace_unit.cc tests/atomic_survivors_unit.cc $(filter-out $(BUILD_ROOT)/src/main.o $(BUILD_ROOT)/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.h) $(wildcard src/*/*.inc)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(filter-out $(BUILD_ROOT)/src/main.o $(BUILD_ROOT)/src/cmd/xshard.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm

$(BUILD_ROOT)/blockrace-db0-unit: tests/blockrace_unit.cc tests/atomic_survivors_unit.cc $(filter-out $(BUILD_ROOT)/db0/src/main.o $(BUILD_ROOT)/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ)) $(wildcard src/*/*.h) $(wildcard src/*/*.inc)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< $(filter-out $(BUILD_ROOT)/db0/src/main.o $(BUILD_ROOT)/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm

# blockrace finding (b): read-after-Done use-after-free, proven under ASAN. Built against ASAN
# objects in a SEPARATE BUILD_ROOT (build/asan) with JE=0, so ASAN's allocator owns new/delete and
# sees the free of the BlockingState. The TOMO_BLOCKING_UAF_UNIT hook compiles out of production.
$(BUILD_ROOT)/blockrace-uaf-unit: tests/blockrace_uaf_unit.cc tests/atomic_survivors_unit.cc $(filter-out $(BUILD_ROOT)/src/main.o $(BUILD_ROOT)/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.h) $(wildcard src/*/*.inc)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(filter-out $(BUILD_ROOT)/src/main.o $(BUILD_ROOT)/src/cmd/xshard.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm

$(BUILD_ROOT)/blockrace-uaf-db0-unit: tests/blockrace_uaf_unit.cc tests/atomic_survivors_unit.cc $(filter-out $(BUILD_ROOT)/db0/src/main.o $(BUILD_ROOT)/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ)) $(wildcard src/*/*.h) $(wildcard src/*/*.inc)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< $(filter-out $(BUILD_ROOT)/db0/src/main.o $(BUILD_ROOT)/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm
