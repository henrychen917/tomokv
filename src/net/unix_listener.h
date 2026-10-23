// Late-bound AF_UNIX listener ownership.
//
// Persistence is loaded before open() is called.  The object owns both an untransferred fd and,
// after a successful bind, the filesystem pathname; transferring the fd to IoLoop deliberately
// does not transfer pathname cleanup.  That gives every boot-error and normal-exit edge one unlink
// owner without exposing a listener while shard state is still loading.
#pragma once

#include <cerrno>
#include <cstdint>
#include <cstring>
#include <string>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

namespace tomo {

class LateUnixListener {
public:
    explicit LateUnixListener(const char* path) : path_(path) {}
    LateUnixListener(const LateUnixListener&) = delete;
    LateUnixListener& operator=(const LateUnixListener&) = delete;

    ~LateUnixListener() {
        if (fd_ >= 0) ::close(fd_);
        if (owns_path_) (void)::unlink(path_);
    }

    bool configured() const { return path_ && *path_; }
    bool bound() const { return owns_path_; }
    int fd() const { return fd_; }

    // May be called exactly once, after persistence load and before any IoLoop activates.
    bool open(uint32_t backlog, std::string& error, uint16_t permissions) {
        if (!configured()) return true;
        if (fd_ >= 0 || owns_path_) {
            error = "unix listener was opened more than once";
            return false;
        }

        sockaddr_un address{};
        address.sun_family = AF_UNIX;
        const size_t path_length = std::strlen(path_);
        if (path_length >= sizeof(address.sun_path)) {
            error = "unixsocket path is too long";
            return false;
        }
        std::memcpy(address.sun_path, path_, path_length + 1);

        // Redis 7.4 unix.c unconditionally removes the pathname before binding. This
        // includes regular files, symlinks and live listeners; unlink errors surface at bind.
        (void)::unlink(path_);

        fd_ = ::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
        if (fd_ < 0) {
            error = std::string("socket unixsocket: ") + std::strerror(errno);
            return false;
        }
        if (::bind(fd_, reinterpret_cast<const sockaddr*>(&address), sizeof(address)) != 0) {
            error = std::string("bind unixsocket: ") + std::strerror(errno);
            ::close(fd_);
            fd_ = -1;
            return false;
        }
        owns_path_ = true;
        // Redis mode 0 leaves the process umask in charge. Apply an explicit mode before
        // listening; the existing pathname/fd owner also cleans up a chmod failure.
        if (permissions && ::chmod(path_, static_cast<mode_t>(permissions)) != 0) {
            error = std::string("chmod unixsocket: ") + std::strerror(errno);
            return false;
        }
        if (::listen(fd_, static_cast<int>(backlog)) != 0) {
            error = std::string("listen unixsocket: ") + std::strerror(errno);
            ::close(fd_);
            fd_ = -1;
            (void)::unlink(path_);
            owns_path_ = false;
            return false;
        }
        return true;
    }

    // Call only after IoLoop::attach_listener() has accepted fd().
    int release_fd() {
        const int result = fd_;
        fd_ = -1;
        return result;
    }

private:
    const char* path_ = nullptr;
    int fd_ = -1;
    bool owns_path_ = false;
};

}  // namespace tomo
