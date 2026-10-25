# The production_units gate job invokes this supplement. The witness includes
# production owner code; it opens no listener or worker. Bind both outputs so a
# fresh checkout or a missing receipt rebuilds the exact witness/server pair.
$(BUILD_ROOT)/blockfix-cost $(BIN).blockfix-cost.sha256 &: tests/blockfix_cost.cc src/cmd/xshard.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc) $(wildcard src/core/*.inc) tools/blockfix_cost.mk $(BIN) $(filter-out $(BUILD_ROOT)/src/main.o $(BUILD_ROOT)/src/cmd/xshard.o,$(OBJ))
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(filter-out $(BUILD_ROOT)/src/main.o $(BUILD_ROOT)/src/cmd/xshard.o,$(OBJ)) -o $(BUILD_ROOT)/blockfix-cost $(JELIBS) $(LDLIBS) -lm
	sha256sum $(abspath $(BIN)) $(abspath $(BUILD_ROOT)/blockfix-cost) > $(BIN).blockfix-cost.sha256
