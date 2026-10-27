# Cold blocking witnesses use the production implementation, without a server.
$(BUILD_ROOT)/blockfix2-unit: tests/blockfix2_unit.cc tests/atomic_survivors_unit.cc $(filter-out $(BUILD_ROOT)/src/main.o $(BUILD_ROOT)/src/cmd/xshard.o,$(OBJ)) $(wildcard src/*/*.h) $(wildcard src/*/*.inc)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(filter-out $(BUILD_ROOT)/src/main.o $(BUILD_ROOT)/src/cmd/xshard.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm
