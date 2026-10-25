# Keep this fixture's build rules separate from production object prerequisites.
include Makefile
build/ctlfix-unit: tests/ctlfix_unit.cc tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) $(wildcard src/*/*.h) $(wildcard tests/*checks.inc)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_CORE_CONCURRENCY_TEST -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
