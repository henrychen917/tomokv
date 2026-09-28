# Standalone serverless lane target; no gate row/count changes.
EXECFIX_SOURCE ?= .
EXECFIX_UNIT ?= build/execfix-unit
$(EXECFIX_UNIT): tests/execfix_unit.cc $(EXECFIX_SOURCE)/src/cmd/xshard.cc $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) $(wildcard $(EXECFIX_SOURCE)/src/*/*.inc) $(wildcard $(EXECFIX_SOURCE)/src/*/*.h)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I$(EXECFIX_SOURCE) -I. $< \
	  $(filter-out build/src/main.o build/src/cmd/xshard.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm

build/execfix-unit-db0: tests/execfix_unit.cc src/cmd/xshard.cc $(filter-out build/db0/src/main.o build/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(CORE_TEST_OBJ) $(wildcard src/*/*.inc) $(wildcard src/*/*.h)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< \
	  $(filter-out build/db0/src/main.o build/db0/src/cmd/xshard.o,$(DB0_OBJ)) $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
