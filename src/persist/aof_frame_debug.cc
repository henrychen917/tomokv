// Status publication only while DEBUG AOF-REWRITE-PAUSE is explicitly armed.
#include <cstdint>
#include <cstdio>
#include <string>
#include <fcntl.h>
#include <unistd.h>

namespace tomo {
__attribute__((cold)) void aof_debug_frame_cleanup(const std::string& directory) noexcept try {
    (void)::unlink((directory + "/debug-aof-frame-state").c_str());
} catch (...) {} // Best effort, like the existing stage-marker cleanup.

__attribute__((cold)) bool aof_debug_frame_state(const std::string& directory,
        uint32_t writer, uint64_t pending, uint64_t posted) noexcept try {
    const std::string path = directory + "/debug-aof-frame-state";
    const std::string temporary = path + ".tmp";
    char text[80];
    const int size = std::snprintf(text, sizeof(text), "%u %llu %llu\n", writer,
        static_cast<unsigned long long>(pending), static_cast<unsigned long long>(posted));
    const int fd = ::open(temporary.c_str(), O_CREAT | O_TRUNC | O_WRONLY | O_CLOEXEC, 0600);
    if (fd < 0) return false;
    const bool written = ::write(fd, text, static_cast<size_t>(size)) == size;
    const bool closed = ::close(fd) == 0;
    if (written && closed && ::rename(temporary.c_str(), path.c_str()) == 0) return true;
    (void)::unlink(temporary.c_str());
    return false;
} catch (...) { return false; } // An unpublishable observation is never a witness.
}  // namespace tomo
