# txnfix4 CD5.3: the serverless capture fixture linked against either arm's own objects.
# Test-only targets; the production Makefile and its freshness are unchanged. A frozen source
# tree passes TXNFIX4_HASH_SOURCE so the fixture text stays the lane's while headers and objects
# stay the arm's.
TXNFIX4_HASH_SOURCE ?= tests/txnfix4_hash.cc

$(BUILD_ROOT)/txnfix4-hash-unit: $(TXNFIX4_HASH_SOURCE) $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ)) $(wildcard src/*/*.h) $(wildcard src/*/*.inc)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm

$(BUILD_ROOT)/txnfix4-hash-db0-unit: $(TXNFIX4_HASH_SOURCE) $(filter-out $(BUILD_ROOT)/db0/src/main.o,$(DB0_OBJ)) $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ)) $(wildcard src/*/*.h) $(wildcard src/*/*.inc)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< $(filter-out $(BUILD_ROOT)/db0/src/main.o,$(DB0_OBJ)) $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ)) -o $@ $(JELIBS) $(LDLIBS) -lm
