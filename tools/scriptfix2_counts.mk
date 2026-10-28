# Link both compiled engines in the production weak-symbol order. The fixture
# supplies main; neither production entry point boots a server.
SCRIPT_COUNT_TEST ?= tests/scriptfix2_counts.cc
SCRIPT_COUNT_OUT ?= build/scriptfix2/counts
SCRIPT_COUNT_DB0 ?= 0
SCRIPT_COUNT_FLAGS := -Dmain=__wrap_main
ifeq ($(SCRIPT_COUNT_DB0),1)
SCRIPT_COUNT_FLAGS += -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0
endif
$(SCRIPT_COUNT_OUT): $(SCRIPT_COUNT_TEST) $(DB0_OBJ) $(OBJ)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) $(SCRIPT_COUNT_FLAGS) -I. -c $(SCRIPT_COUNT_TEST) -o $(SCRIPT_COUNT_OUT).o
	$(CXX) $(CXXFLAGS) $(DB0_OBJ) $(OBJ) $(SCRIPT_COUNT_OUT).o -o $@ -Wl,--wrap=main $(JELIBS) $(LDLIBS) -lm
