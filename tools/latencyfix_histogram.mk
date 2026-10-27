# Only the numeric oracle witness links Redis's independently vendored HDR library.
# Production uses TomoKV's own implementation and does not link any Redis code.
HDR_DIR ?= /home/user/Projects/redis/deps/hdr_histogram
build/latencyfix-histogram-unit: tests/latencyfix_histogram_unit.cc src/cmd/latency_tracking.cc $(filter-out build/src/main.o build/src/cmd/latency_tracking.o,$(OBJ))
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. -I$(HDR_DIR) $< $(filter-out build/src/main.o build/src/cmd/latency_tracking.o,$(OBJ)) $(HDR_DIR)/hdr_histogram.o -o $@ $(JELIBS) $(LDLIBS) -lm
