// tls.h — handshake and userspace-fallback TLS engine.
//
// A kTLS attempt starts with a non-blocking socket BIO so OpenSSL can install the kernel record
// layer.  Once both directions engage, the SSL object becomes a cold lifetime holder and ordinary
// io_uring recv/send owns application data.  Forced fallback uses the original BIO-pair engine;
// automatic fallback uses it when neither direction engaged and retains the socket BIO when a
// direction is already irreversible, preserving a valid userspace transport in either case.
#pragma once

#include <cstddef>
#include <cstdint>
#include <array>
#include <memory>
#include <string>

#include <openssl/ssl.h>

namespace tomo {

struct Config;
enum class TlsAuthClients : uint8_t;

enum class TlsOp : int8_t {
    Progress = 1,
    WantRead = -1,
    WantWrite = -2,
    GracefulEof = -3,
    Error = -4,
};

struct TlsIoResult {
    TlsOp op = TlsOp::Error;
    uint32_t bytes = 0;  // plaintext bytes only
};

class TlsContext {
public:
    static std::unique_ptr<TlsContext> create(const Config& cfg, std::string& error);
    ~TlsContext();
    TlsContext(const TlsContext&) = delete;
    TlsContext& operator=(const TlsContext&) = delete;

    SSL_CTX* native() const { return ctx_; }

private:
    explicit TlsContext(SSL_CTX* ctx) : ctx_(ctx) {}
    SSL_CTX* ctx_ = nullptr;
};

class TlsConn {
public:
    static constexpr int kBioBytes = 64 * 1024;

    TlsConn() = default;
    ~TlsConn();
    TlsConn(const TlsConn&) = delete;
    TlsConn& operator=(const TlsConn&) = delete;

    bool init(const TlsContext& context, TlsAuthClients auth, int fd, bool try_ktls,
              std::string& error);

    bool handshaking() const { return state_ == State::Handshaking; }
    bool connected() const { return userspace() || ktls(); }
    bool userspace() const { return memory_userspace() || socket_userspace(); }
    bool memory_userspace() const { return state_ == State::MemoryUserspace; }
    bool socket_userspace() const { return state_ == State::SocketUserspace; }
    bool memory_bio() const { return external_bio_ != nullptr; }
    bool ktls() const { return state_ == State::Ktls; }
    bool was_ktls() const { return ktls_engaged_; }
    bool fd_handshake() const { return fd_handshake_; }
    bool failed() const { return state_ == State::Failed; }
    bool shutdown_started() const { return shutdown_started_; }

    TlsOp handshake();
    TlsIoResult read_plain(char* dst, size_t capacity);
    TlsIoResult write_plain(const char* src, size_t length);
    TlsOp shutdown();

    // Ciphertext ingress. reserve_input() does not advance the BIO; the recv CQE's byte count is
    // the only value commit_input() accepts. abandon_input() is used on a failed/EOF socket recv.
    int reserve_input(char*& dst, size_t cap);
    bool commit_input(size_t bytes);
    void abandon_input();

    // Ciphertext egress. peek_output() does not advance the BIO; only a positive send CQE is fed to
    // consume_output(). Consequently ciphertext byte counts can never touch plaintext cursors.
    int peek_output(const char*& src) const;
    bool consume_output(size_t bytes);
    bool output_pending() const;
    // True while the engine can make input progress without another socket recv.  Keeping the
    // connection active (and not pinning a fresh BIO_nwrite0 reservation) is what lets ROB
    // backpressure drain a pipeline already buffered inside OpenSSL.
    bool input_pending() const;

    bool has_pinned_plain() const { return pending_plain_len_ != 0; }
    void pinned_plain(const char*& src, size_t& length) const {
        src = pending_plain_ptr_;
        length = pending_plain_len_;
    }

    const std::string& last_error() const { return last_error_; }
    TlsOp wanted() const { return wanted_; }
    bool poll_armed(TlsOp wanted) const {
        return wanted == TlsOp::WantWrite ? write_poll_armed_ : read_poll_armed_;
    }
    void set_poll_armed(TlsOp wanted, bool armed) {
        if (wanted == TlsOp::WantWrite) write_poll_armed_ = armed;
        else read_poll_armed_ = armed;
    }
    bool any_poll_armed() const { return read_poll_armed_ || write_poll_armed_; }

private:
    friend class TlsContext;
    enum class State : uint8_t { Handshaking, MemoryUserspace, SocketUserspace, Ktls, Failed };
    static void keylog_callback(const SSL* ssl, const char* line);
    bool install_tls13_rx();
    bool install_memory_bio(std::string& error);
    void restore_socket_flags();
    TlsOp funnel(int result, const char* operation);
    void record_error(const char* operation, int ssl_error);

    SSL* ssl_ = nullptr;
    BIO* external_bio_ = nullptr;
    State state_ = State::Handshaking;
    char* reserved_input_ = nullptr;
    uint32_t reserved_input_cap_ = 0;
    const char* pending_plain_ptr_ = nullptr;
    uint32_t pending_plain_len_ = 0;
    int socket_fd_ = -1;
    int saved_socket_flags_ = -1;
    bool fd_handshake_ = false;
    bool ktls_engaged_ = false;
    bool read_poll_armed_ = false;
    bool write_poll_armed_ = false;
    bool shutdown_started_ = false;
    bool has_client_traffic_secret_ = false;
    TlsOp wanted_ = TlsOp::Progress;
    std::array<unsigned char, 32> client_traffic_secret_{};
    std::string last_error_;
};

}  // namespace tomo
