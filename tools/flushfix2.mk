# Supplemental serverless range witnesses; no listener or benchmark target.
build/flushfix2-unit: build/tests/flushfix2_unit.o $(CORE_TEST_OBJ) $(DB0_TEST_OBJ)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
build/flushfix2-db0-unit: build/db0/tests/flushfix2_unit.o $(CORE_TEST_OBJ) $(DB0_TEST_OBJ)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
