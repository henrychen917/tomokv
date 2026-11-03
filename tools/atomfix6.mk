# Fully instrumented production owners for the held-park schedule. Reuse the
# gate's ASAN objects; the source/header dependencies remain Makefile-owned.
build/atomfix6-park-asan: tests/atomfix6_park_unit.cc $(MDBQSBR_ASAN_OBJ) tools/atomfix6.mk
	$(CXX) $(MDBQSBR_FLAGS) -fsanitize=address,undefined $< $(MDBQSBR_ASAN_OBJ) -Wl,--compress-debug-sections=zlib -o $@ $(LDLIBS) -lm
