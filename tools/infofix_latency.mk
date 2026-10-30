# Same normal-runtime objects as the delivered server; the included tracking
# implementation adds only the test's batch-lock witness counter.
INFOFIX_UNIT ?= $(BUILD_ROOT)/infofix-latency-unit
$(INFOFIX_UNIT): tests/infofix_latency_unit.cc src/cmd/latency_tracking.cc $(filter-out $(BUILD_ROOT)/src/cmd/latency_tracking.o,$(OBJ))
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. -c tests/infofix_latency_unit.cc -o $(INFOFIX_UNIT).o
	$(CXX) $(CXXFLAGS) $(filter-out $(BUILD_ROOT)/src/cmd/latency_tracking.o,$(OBJ)) $(INFOFIX_UNIT).o -o $@ -Wl,--wrap=clock_gettime $(JELIBS) $(LDLIBS) -lm
