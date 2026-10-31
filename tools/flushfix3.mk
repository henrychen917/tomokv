# The unit includes the cold source to inspect its private collision index.
# All other methods bind to the matching production objects in link order.
build/tests/flushfix3_unit.o build/db0/tests/flushfix3_unit.o: src/store/flush.cc
build/flushfix3-unit: build/tests/flushfix3_unit.o $(filter-out build/src/store/flush.o,$(CORE_TEST_OBJ)) $(DB0_TEST_OBJ)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
build/flushfix3-db0-unit: build/db0/tests/flushfix3_unit.o $(CORE_TEST_OBJ) $(filter-out build/db0/src/store/flush.o,$(DB0_TEST_OBJ))
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
