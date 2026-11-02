// Production APPEND with linker-only copy/allocation spies. No server or timer.
#define main encodingfix_fixture_main
#include "encodingfix_unit.cc"
#undef main

static bool observing = false;
static size_t large_copies = 0;
static size_t scratch_allocations = 0;
static constexpr size_t length = 1 << 20;
extern "C" void* __real_malloc(size_t);
extern "C" void* __real_memcpy(void*, const void*, size_t);
extern "C" void* __wrap_malloc(size_t n) {
    if (observing && n == length + 1) ++scratch_allocations;
    return __real_malloc(n);
}
extern "C" void* __wrap_memcpy(void* to, const void* from, size_t n) {
    if (observing && n >= length) large_copies += n;
    return __real_memcpy(to, from, n);
}
int main() {
    check(tomo::command_registry_init(false), "command registry");
    tomo::NetcmdRegression fixture(1);
    const std::string old(length, 'x');
    check(fixture.run({"SET", "append", old}) == "+OK\r\n", "seed large string");
    observing = true;
    const auto reply = fixture.run({"APPEND", "append", "y"});
    observing = false;
    check(reply == ":1048577\r\n", "append length");
    check(fixture.run({"GET", "append"}) == bulk(old + 'y'), "append bytes");
    std::printf("large_copied_bytes=%zu scratch_allocations=%zu\n", large_copies, scratch_allocations);
    check(large_copies >= length, "large-copy witness fired");
    check(large_copies <= length + 1 && scratch_allocations == 0,
          "APPEND must copy the old value once without a merged scratch allocation");
}
