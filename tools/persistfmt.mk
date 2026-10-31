# Build-only scheduling twin, using the selected arm's production objects.
# Pass PERSISTFMT_OBJECTS and PERSISTFMT_AOF for the unmodified PRE arm.
PERSISTFMT_OBJECTS ?= build
PERSISTFMT_AOF ?= src/persist/aof.cc
PERSISTFMT_SCHEDULE ?= build/persistfmt/scheduled
$(PERSISTFMT_SCHEDULE)/aof.cc: tools/persistfmt_schedule.py $(PERSISTFMT_AOF)
	python3 tools/persistfmt_schedule.py $(PERSISTFMT_AOF) $@
$(PERSISTFMT_SCHEDULE)/aof.o: $(PERSISTFMT_SCHEDULE)/aof.cc
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Isrc/persist -I. -c $< -o $@
$(PERSISTFMT_SCHEDULE)/db0-aof.o: $(PERSISTFMT_SCHEDULE)/aof.cc
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -Isrc/persist -I. -c $< -o $@
PERSISTFMT_LINK = $(filter-out $(BUILD_ROOT)/src/persist/aof.o $(BUILD_ROOT)/db0/src/persist/aof.o,$(DB0_OBJ) $(DB0_SERVER_ONLY_OBJ) $(OBJ) $(SERVER_ONLY_OBJ))
$(PERSISTFMT_SCHEDULE)/tomokv: $(PERSISTFMT_SCHEDULE)/aof.o $(PERSISTFMT_SCHEDULE)/db0-aof.o $(patsubst $(BUILD_ROOT)/%,$(PERSISTFMT_OBJECTS)/%,$(PERSISTFMT_LINK))
	$(CXX) $(CXXFLAGS) $^ -o $@ -Wl,--wrap=main $(JELIBS) $(LDLIBS) -lm
