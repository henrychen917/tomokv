# Test-only target; keep the production Makefile and its freshness unchanged.
$(BUILD_ROOT)/list-namespace-unit: tests/list_namespace_unit.cc $(filter-out $(BUILD_ROOT)/src/main.o,$(OBJ))
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $^ -o $@ -Wl,--wrap=_ZN4tomo20blocking_publish_keyERNS_5ShardEmPKcjh $(JELIBS) $(LDLIBS) -lm
