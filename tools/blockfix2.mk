# Cold blocking witnesses use the production implementation, without a server.
$(BUILD_ROOT)/blockfix2-unit: tests/blockfix2_unit.cc tests/atomic_survivors_unit.cc $(filter-out $(BUILD_ROOT)/src/main.o $(BUILD_ROOT)/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.h) $(wildcard src/*/*.inc)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(filter-out $(BUILD_ROOT)/src/main.o $(BUILD_ROOT)/src/cmd/xshard.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm

$(BUILD_ROOT)/blockfix2-db0-unit: tests/blockfix2_unit.cc tests/atomic_survivors_unit.cc $(filter-out $(BUILD_ROOT)/db0/src/main.o $(BUILD_ROOT)/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ)) $(wildcard src/*/*.h) $(wildcard src/*/*.inc)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< $(filter-out $(BUILD_ROOT)/db0/src/main.o $(BUILD_ROOT)/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm
