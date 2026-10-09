// Serverless entry integration witness: forwarding must preserve argv and rc.
#include <cstdio>

int main(int argc, char** argv) {
    std::printf("forwarded argc=%d", argc);
    for (int i = 1; i < argc; ++i) std::printf(" [%s]", argv[i]);
    std::putchar('\n');
    return 23;
}
