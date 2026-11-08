# Same objects and weak-symbol order as the production normal namespace.
# The production entry is tomokv_multidb_main, so linking it does not run it.
LATENCYFIX_TEST ?= tests/latencyfix_counts.cc
LATENCYFIX_OUT ?= $(BUILD_ROOT)/latencyfix-counts
$(LATENCYFIX_OUT): $(LATENCYFIX_TEST) $(OBJ)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. -c $(LATENCYFIX_TEST) -o $(LATENCYFIX_OUT).o
	$(CXX) $(CXXFLAGS) $(OBJ) $(LATENCYFIX_OUT).o -o $@ $(JELIBS) $(LDLIBS) -lm
