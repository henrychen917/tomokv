// Correctness-only allocation attribution. Loaded only into a directed test process.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <execinfo.h>
#include <fcntl.h>
#include <new>
#include <unistd.h>

static thread_local bool tracing;
static void trace(char kind, void* pointer, size_t size) {
    if (tracing) return;
    tracing = true;
    const char* path = std::getenv("TOMO_ALLOC_TRACE");
    const char* target = std::getenv("TOMO_ALLOC_BINARY");
    char executable[4096];
    const ssize_t length = readlink("/proc/self/exe", executable, sizeof(executable) - 1);
    if (!path || !target || length < 0) { tracing = false; return; }
    executable[length] = 0;
    if (std::strcmp(executable, target)) { tracing = false; return; }
    char record[2048];
    int used = std::snprintf(record, sizeof(record), "%c %p %zu", kind, pointer, size);
    if (kind == 'N') {
        void* frames[24];
        const int count = backtrace(frames, 24);
        for (int i = 0; i < count; ++i) {
            Dl_info info{};
            if (!dladdr(frames[i], &info) || !info.dli_fname || std::strcmp(info.dli_fname, target)) continue;
            const size_t offset = static_cast<char*>(frames[i]) - static_cast<char*>(info.dli_fbase) - 1;
            used += std::snprintf(record + used, sizeof(record) - used, " %zx", offset);
        }
    }
    record[used++] = '\n';
    const int fd = open(path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0600);
    if (fd >= 0) { (void)write(fd, record, used); close(fd); }
    tracing = false;
}
void* operator new(size_t size) {
    void* value = std::malloc(size ? size : 1);
    if (!value) throw std::bad_alloc();
    trace('N', value, size);
    return value;
}
void* operator new[](size_t size) { return ::operator new(size); }
void operator delete(void* value) noexcept { trace('D', value, 0); std::free(value); }
void operator delete[](void* value) noexcept { ::operator delete(value); }
void operator delete(void* value, size_t) noexcept { ::operator delete(value); }
void operator delete[](void* value, size_t) noexcept { ::operator delete(value); }
