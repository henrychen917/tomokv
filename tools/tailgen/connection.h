#pragma once

#include "resp.h"
#include "workload.h"

#include <deque>
#include <sys/socket.h>
#include <unistd.h>
#include <utility>

namespace tailgen {

class File {
public:
    explicit File(int fd = -1) : fd_(fd) {}
    ~File() { if (fd_ >= 0) close(fd_); }
    File(File&& other) noexcept : fd_(std::exchange(other.fd_, -1)) {}
    File& operator=(File&& other) noexcept {
        if (this != &other) { if (fd_ >= 0) close(fd_); fd_ = std::exchange(other.fd_, -1); }
        return *this;
    }
    File(const File&) = delete;
    File& operator=(const File&) = delete;
    int get() const { return fd_; }
private:
    int fd_;
};

struct Request {
    uint64_t sent_ns;
    CommandClass kind;
    bool measured;
};

class Connection {
public:
    explicit Connection(File fd) : fd_(std::move(fd)) {}
    int fd() const { return fd_.get(); }
    size_t outstanding() const { return pending_.size(); }
    size_t queued_bytes() const { return queued_bytes_; }
    bool wants_write() const { return !writes_.empty(); }

    // Timestamp the first send attempt. If the socket is backpressured, its
    // unsent suffix queues without pausing arrivals; this local delay remains
    // in the command's latency. Outstanding includes both queued and sent work.
    void submit(std::string_view command, Request request) {
        pending_.push_back(request);
        const size_t sent = wants_write() ? 0 : send_some(command);
        if (sent != command.size()) {
            writes_.emplace_back(command.substr(sent));
            queued_bytes_ += command.size() - sent;
        }
    }

    void write_ready() {
        if (writes_.empty()) return;
        const size_t sent = send_some(std::string_view(writes_.front()).substr(write_offset_));
        write_offset_ += sent;
        queued_bytes_ -= sent;
        if (write_offset_ == writes_.front().size()) { writes_.pop_front(); write_offset_ = 0; }
    }

    template <class Reply>
    void read_ready(Reply&& reply) {
        char buffer[4096]; // bound work between arrival-deadline checks
        const ssize_t n = recv(fd(), buffer, sizeof buffer, MSG_DONTWAIT);
        if (n < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) return;
            throw std::system_error(errno, std::generic_category(), "recv");
        }
        if (!n) throw std::runtime_error("peer closed connection (outstanding=" + std::to_string(pending_.size()) + ")");
        parser_.feed(std::string_view(buffer, static_cast<size_t>(n)), [&](bool error, std::string_view message) {
            const uint64_t completed = now_ns();
            if (pending_.empty()) throw std::runtime_error("unsolicited RESP reply");
            const Request request = pending_.front();
            pending_.pop_front();
            reply(request, completed, error, message);
        });
    }

private:
    size_t send_some(std::string_view bytes) {
        const ssize_t n = send(fd(), bytes.data(), std::min<size_t>(bytes.size(), 65536), MSG_DONTWAIT | MSG_NOSIGNAL);
        if (n < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) return 0;
            throw std::system_error(errno, std::generic_category(), "send");
        }
        if (!n) throw std::runtime_error("zero-byte send");
        return static_cast<size_t>(n);
    }
    File fd_;
    RespParser parser_;
    std::deque<Request> pending_; // unbounded; --max-outstanding is only an observer
    std::deque<std::string> writes_;
    size_t write_offset_ = 0, queued_bytes_ = 0;
};

} // namespace tailgen
