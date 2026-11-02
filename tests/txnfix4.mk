# Compile the same deterministic capture fixture against either arm's objects.
$(BUILD_ROOT)/txnfix4-hash-unit: tests/txnfix4_hash.cc $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ))
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $^ -o $@ $(JELIBS) $(LDLIBS) -lm
$(BUILD_ROOT)/txnfix4-hash-db0-unit: tests/txnfix4_hash.cc $(filter-out $(BUILD_ROOT)/db0/src/main.o,$(DB0_OBJ)) $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ))
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $^ -o $@ $(JELIBS) $(LDLIBS) -lm
