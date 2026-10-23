# Invoke with: taskset -c 80-95 make -j16 -f Makefile -f docs/prefetch/counts.mk prefetch-counts
# These fixtures deliberately use ordinary release code, with no test hooks.
PREFETCH_PRE_OBJ := $(patsubst build/%,build/prefetch/pre-objects/%,$(CORE_TEST_OBJ))
PREFETCH_PRE_DB0_OBJ := $(patsubst build/%,build/prefetch/pre-objects/%,$(filter-out build/db0/src/main.o,$(DB0_OBJ)))
.PHONY: prefetch-counts
prefetch-counts: build/prefetch/counts-pre build/prefetch/counts-post build/prefetch/counts-pre-db0 build/prefetch/counts-post-db0
build/prefetch/counts-pre: docs/prefetch/batch_counts.cc $(PREFETCH_PRE_OBJ)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -Ibuild/prefetch/pre-source $< $(PREFETCH_PRE_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
build/prefetch/counts-post: docs/prefetch/batch_counts.cc $(CORE_TEST_OBJ)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
build/prefetch/counts-pre-db0: docs/prefetch/batch_counts.cc $(PREFETCH_PRE_DB0_OBJ) $(PREFETCH_PRE_OBJ)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -Ibuild/prefetch/pre-source $< $(PREFETCH_PRE_DB0_OBJ) $(PREFETCH_PRE_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
build/prefetch/counts-post-db0: docs/prefetch/batch_counts.cc $(DB0_TEST_OBJ) $(CORE_TEST_OBJ)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. $< $(DB0_TEST_OBJ) $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
