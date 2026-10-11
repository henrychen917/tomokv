// Execute only an allocation-free complete-frame parser body copied from the
// production ELF. No main/server entry, listener, thread or load generator runs.
// GDB single-steps the copied instructions; leaving the body except by RET fails.
#include "src/exec/op.h"
#include <elf.h>
#include <sys/mman.h>
#include <fstream>
#include <vector>
#include <string>
#include <cstdio>

void* trace_entry;
void* trace_end;
extern "C" __attribute__((noinline)) void trace_ready() { asm volatile(""); }
int main(int argc, char** argv) {
    if (argc != 7) return 2;
    std::ifstream f(argv[1], std::ios::binary);
    Elf64_Ehdr eh{}; f.read(reinterpret_cast<char*>(&eh), sizeof(eh));
    const auto address = std::stoull(argv[2], nullptr, 0), size = std::stoull(argv[3]);
    uint64_t extent = 0;
    std::vector<Elf64_Phdr> loads;
    for (uint32_t i = 0; i < eh.e_phnum; ++i) {
        Elf64_Phdr ph{}; f.seekg(eh.e_phoff + i * eh.e_phentsize);
        f.read(reinterpret_cast<char*>(&ph), sizeof(ph));
        if (ph.p_type == PT_LOAD) {
            loads.push_back(ph);
            extent = std::max(extent, ph.p_vaddr + ph.p_memsz);
        }
    }
    if (address + size > extent) return 3;
    void* mapping = mmap(nullptr, extent, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (mapping == MAP_FAILED) return 4;
    // Preserve relative addresses/alignment of read-only constants used by the
    // limited parser. Dynamic relocations are deliberately NOT executed: the
    // traced complete path must make no external call or global-state access.
    for (const auto& ph : loads) {
        f.seekg(ph.p_offset); f.read(static_cast<char*>(mapping) + ph.p_vaddr, ph.p_filesz);
        if (!f) return 5;
    }
    if (mprotect(mapping, extent, PROT_READ | PROT_EXEC)) return 5;
    trace_entry = static_cast<char*>(mapping) + address;
    trace_end = static_cast<char*>(trace_entry) + size;
    std::string frame = std::string(argv[6]) == "GET" ? "*2\r\n$3\r\nGET\r\n$1\r\nk\r\n"
        : "*3\r\n$3\r\nSET\r\n$1\r\nk\r\n$1\r\nv\r\n";
    tomo::Op op; uint32_t pos = 0; const char* err = nullptr;
    alignas(8) char frontier[32]{};
    const bool limited = std::stoi(argv[4]), post = std::stoi(argv[5]);
    trace_ready();
    int result;
    if (!limited && post) {
        using Fn = int (*)(const char*, uint32_t, uint32_t&, tomo::Op&, const char**, void*);
        result = reinterpret_cast<Fn>(trace_entry)(frame.data(), frame.size(), pos, op, &err, frontier);
    } else {
        using Fn = int (*)(const char*, uint32_t, uint32_t&, tomo::Op&, const char**, uint64_t, uint64_t, void*);
        result = reinterpret_cast<Fn>(trace_entry)(frame.data(), frame.size(), pos, op, &err, 10, 16384, frontier);
    }
    if (result != 0 || pos != frame.size() || op.argc() != (std::string(argv[6]) == "GET" ? 2 : 3)) return 6;
    std::puts("validated complete frame");
}
