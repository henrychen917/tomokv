# Keep production weak-symbol order; replace only the instrumented histogram
# object and the program entry. EXEC/scatter/storage remain production objects.
$(BUILD_ROOT)/wave8b-original-main.o: $(BUILD_ROOT)/db0/src/main.o
	objcopy --redefine-sym main=wave8b_original_main $< $@

WAVE8B_LINK = $(BUILD_ROOT)/wave8b-original-main.o $(filter-out $(BUILD_ROOT)/db0/src/main.o,$(DB0_OBJ)) $(DB0_SERVER_ONLY_OBJ) $(OBJ) $(SERVER_ONLY_OBJ)
WAVE8B_DEPS = tests/wave8b_latency_unit.cc tests/wave8b_scope.cc src/cmd/latency_tracking.cc tools/wave8b.mk $(WAVE8B_LINK)
$(BUILD_ROOT)/wave8b-latency-unit: $(WAVE8B_DEPS)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. -c $< -o $@.o
	$(CXX) $(CXXFLAGS) $(filter-out $(BUILD_ROOT)/src/cmd/latency_tracking.o,$(WAVE8B_LINK)) $@.o -o $@ -Wl,--wrap=main $(JELIBS) $(LDLIBS) -lm

$(BUILD_ROOT)/wave8b-latency-db0-unit: $(WAVE8B_DEPS)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. -c $< -o $@.o
	$(CXX) $(CXXFLAGS) $(filter-out $(BUILD_ROOT)/db0/src/cmd/latency_tracking.o,$(WAVE8B_LINK)) $@.o -o $@ -Wl,--wrap=main $(JELIBS) $(LDLIBS) -lm
