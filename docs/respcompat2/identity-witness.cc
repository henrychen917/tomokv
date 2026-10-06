#include "src/net/resp.h"
#include <cstdio>
#include <cstring>
int main() {
    const char* labels[] = {"canonical", "zero-first array", "zero-first bulk", "later zero digit"};
    const char* frames[] = {"*1\r\n$4\r\nPING\r\n", "*01\r\n$4\r\nPING\r\n", "*1\r\n$04\r\nPING\r\n", "*1\r\n$10\r\n0123456789\r\n"};
    for (unsigned i = 0; i != 4; ++i) {
        tomo::Op op; uint32_t pos = 0; const char* err = nullptr;
        auto result = tomo::resp_parse(frames[i], std::strlen(frames[i]), pos, op, &err);
        std::printf("%s: result=%d pos=%u argc=%u error=%s\n", labels[i], int(result), pos, op.argc(), err ? err : "none");
    }
}
