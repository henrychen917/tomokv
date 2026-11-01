// Test-only linker wrapper. Pause the rewrite after its library image was copied.
// The release image contains no hook, environment check, or branch.
#include "src/core/server.h"
#include "src/cmd/command.h"
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <unistd.h>
#if TOMO_SINGLE_DATABASE
#define SYMBOL "_ZN8tomo_db022function_snapshot_saveERSt6vectorIhSaIhEERNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE"
#define JOURNAL "_ZN8tomo_db010AofManager23append_function_journalENS_5SliceE"
#else
#define SYMBOL "_ZN4tomo22function_snapshot_saveERSt6vectorIhSaIhEERNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE"
#define JOURNAL "_ZN4tomo10AofManager23append_function_journalENS_5SliceE"
#endif
extern "C" bool real_save(std::vector<uint8_t>&, std::string&) asm("__real_" SYMBOL);
extern "C" bool wrapped_save(std::vector<uint8_t>&, std::string&) asm("__wrap_" SYMBOL);
extern "C" bool wrapped_save(std::vector<uint8_t>& image, std::string& error) {
    const bool result = real_save(image, error);
    const char* path = std::getenv("WAVE14_CAPTURE_HOLD");
    auto* server = tomo::command_server();
    if (result && path && server && server->aof().rewrite_in_progress() && ::access(path, F_OK) == 0) {
        const std::string ready = std::string(path) + ".ready";
        FILE* file = std::fopen(ready.c_str(), "w");
        if (!file) std::abort();
        std::fprintf(file, "%ld\n", static_cast<long>(::gettid()));
        if (std::fclose(file) != 0) std::abort();
        while (::access(path, F_OK) == 0) std::this_thread::yield();
    }
    return result;
}
extern "C" void real_journal(tomo::AofManager*, tomo::Slice) asm("__real_" JOURNAL);
extern "C" void wrapped_journal(tomo::AofManager*, tomo::Slice) asm("__wrap_" JOURNAL);
extern "C" void wrapped_journal(tomo::AofManager* aof, tomo::Slice payload) {
    real_journal(aof, payload);
    const char* path = std::getenv("WAVE14_CAPTURE_HOLD");
    if (path && ::access(path, F_OK) == 0 &&
        ::access((std::string(path) + ".ready").c_str(), F_OK) == 0) {
        FILE* file = std::fopen((std::string(path) + ".journal").c_str(), "w");
        if (!file || std::fclose(file) != 0) std::abort();
    }
}
