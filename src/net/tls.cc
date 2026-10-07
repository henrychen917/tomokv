#include "tls.h"

#include <algorithm>
#include <atomic>
#include <cctype>
#include <climits>
#include <cstring>
#include <fcntl.h>
#include <linux/tls.h>
#include <sstream>
#include <sys/socket.h>

#include <openssl/bio.h>
#include <openssl/crypto.h>
#include <openssl/err.h>
#include <openssl/evp.h>
#include <openssl/kdf.h>

#include "../core/config.h"

namespace tomo {
namespace {

#ifndef SOL_TLS
#define SOL_TLS 282
#endif

std::atomic<uint64_t> rx_declined_13{0}, tx_rekeys{0};

bool eq_icase(const std::string& value, const char* wanted) {
    const size_t n = std::strlen(wanted);
    if (value.size() != n) return false;
    for (size_t i = 0; i < n; i++)
        if (std::tolower(static_cast<unsigned char>(value[i])) !=
            std::tolower(static_cast<unsigned char>(wanted[i]))) return false;
    return true;
}

bool configure_protocols(SSL_CTX* ctx, const char* configured, std::string& error) {
    // Redis's empty value means the safe default: TLS 1.2 and TLS 1.3.
    uint32_t enabled = 0;
    if (!configured || !*configured) {
        enabled = (1u << 2) | (1u << 3);
    } else {
        std::istringstream words(configured);
        std::string word;
        while (words >> word) {
            if (eq_icase(word, "TLSv1")) enabled |= 1u << 0;
            else if (eq_icase(word, "TLSv1.1")) enabled |= 1u << 1;
            else if (eq_icase(word, "TLSv1.2")) enabled |= 1u << 2;
            else if (eq_icase(word, "TLSv1.3")) enabled |= 1u << 3;
            else {
                error = "Invalid tls-protocols value '" + word + "'";
                return false;
            }
        }
        if (!enabled) {
            error = "tls-protocols must enable at least one protocol";
            return false;
        }
    }

    static constexpr int versions[] = {
        TLS1_VERSION, TLS1_1_VERSION, TLS1_2_VERSION, TLS1_3_VERSION
    };
    uint32_t first = 0, last = 3;
    while (!(enabled & (1u << first))) first++;
    while (!(enabled & (1u << last))) last--;
    if (!SSL_CTX_set_min_proto_version(ctx, versions[first]) ||
        !SSL_CTX_set_max_proto_version(ctx, versions[last])) {
        error = "Failed to apply tls-protocols min/max versions";
        return false;
    }

    // min/max is the modern API; NO_* bits preserve Redis's exact non-contiguous-list semantics.
    uint64_t disabled = 0;
    if (!(enabled & (1u << 0))) disabled |= SSL_OP_NO_TLSv1;
    if (!(enabled & (1u << 1))) disabled |= SSL_OP_NO_TLSv1_1;
    if (!(enabled & (1u << 2))) disabled |= SSL_OP_NO_TLSv1_2;
    if (!(enabled & (1u << 3))) disabled |= SSL_OP_NO_TLSv1_3;
    SSL_CTX_set_options(ctx, disabled);
    return true;
}

std::string openssl_error(const char* prefix) {
    unsigned long code = ERR_get_error();
    if (!code) return std::string(prefix);
    char detail[256];
    ERR_error_string_n(code, detail, sizeof(detail));
    return std::string(prefix) + ": " + detail;
}

int hex_nibble(char value) {
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    if (value >= 'A' && value <= 'F') return value - 'A' + 10;
    return -1;
}

bool hkdf_expand_label(const EVP_MD* md, const unsigned char* secret, int secret_len,
                       const char* label, unsigned char* out, size_t out_len) {
    static constexpr char prefix[] = "tls13 ";
    const size_t label_len = std::strlen(label);
    if (out_len > UINT16_MAX || sizeof(prefix) - 1 + label_len > UINT8_MAX) return false;
    unsigned char info[64];
    size_t pos = 0;
    info[pos++] = static_cast<unsigned char>(out_len >> 8);
    info[pos++] = static_cast<unsigned char>(out_len);
    info[pos++] = static_cast<unsigned char>(sizeof(prefix) - 1 + label_len);
    std::memcpy(info + pos, prefix, sizeof(prefix) - 1);
    pos += sizeof(prefix) - 1;
    std::memcpy(info + pos, label, label_len);
    pos += label_len;
    info[pos++] = 0;  // empty context

    EVP_PKEY_CTX* ctx = EVP_PKEY_CTX_new_id(EVP_PKEY_HKDF, nullptr);
    if (!ctx) return false;
    size_t derived = out_len;
    const bool ok = EVP_PKEY_derive_init(ctx) > 0 &&
                    EVP_PKEY_CTX_set_hkdf_mode(ctx, EVP_PKEY_HKDEF_MODE_EXPAND_ONLY) > 0 &&
                    EVP_PKEY_CTX_set_hkdf_md(ctx, md) > 0 &&
                    EVP_PKEY_CTX_set1_hkdf_key(ctx, secret, secret_len) > 0 &&
                    EVP_PKEY_CTX_add1_hkdf_info(ctx, info, static_cast<int>(pos)) > 0 &&
                    EVP_PKEY_derive(ctx, out, &derived) > 0 && derived == out_len;
    EVP_PKEY_CTX_free(ctx);
    OPENSSL_cleanse(info, sizeof(info));
    return ok;
}

// A KeyUpdate starts a new record sequence at zero. OpenSSL invokes the keylog callback after
// flushing its old-key KeyUpdate and before writing any new-key application data.
template <class Crypto>
bool install_tx_key(int fd, uint16_t cipher, const EVP_MD* md,
                    const unsigned char* secret, int secret_len, unsigned char* key) {
    Crypto crypto{};
    unsigned char iv[sizeof(crypto.salt) + sizeof(crypto.iv)];
    crypto.info.version = TLS_1_3_VERSION;
    crypto.info.cipher_type = cipher;
    const bool derived = hkdf_expand_label(md, secret, secret_len, "key", key, sizeof(crypto.key)) &&
                         hkdf_expand_label(md, secret, secret_len, "iv", iv, sizeof(iv));
    if (derived) {
        std::memcpy(crypto.key, key, sizeof(crypto.key));
        std::memcpy(crypto.salt, iv, sizeof(crypto.salt));
        std::memcpy(crypto.iv, iv + sizeof(crypto.salt), sizeof(crypto.iv));
    }
    const bool installed = derived &&
        ::setsockopt(fd, SOL_TLS, TLS_TX, &crypto, sizeof(crypto)) == 0;
    OPENSSL_cleanse(iv, sizeof(iv));
    OPENSSL_cleanse(&crypto, sizeof(crypto));
    return installed;
}

}  // namespace

uint64_t tls_ktls_rx_declined_13() { return rx_declined_13.load(std::memory_order_relaxed); }
uint64_t tls_ktls_tx_rekeys() { return tx_rekeys.load(std::memory_order_relaxed); }

std::unique_ptr<TlsContext> TlsContext::create(const Config& cfg, std::string& error) {
    error.clear();
    ERR_clear_error();
    SSL_CTX* raw = SSL_CTX_new(TLS_server_method());
    if (!raw) {
        error = openssl_error("Failed to create TLS context");
        return nullptr;
    }
    std::unique_ptr<TlsContext> out(new TlsContext(raw));

    SSL_CTX_set_options(raw, SSL_OP_NO_COMPRESSION | SSL_OP_NO_RENEGOTIATION |
                             SSL_OP_ENABLE_KTLS);
    if (cfg.tls_prefer_server_ciphers)
        SSL_CTX_set_options(raw, SSL_OP_CIPHER_SERVER_PREFERENCE);
    SSL_CTX_set_session_cache_mode(raw, SSL_SESS_CACHE_OFF);
    SSL_CTX_set_dh_auto(raw, 1);
    SSL_CTX_set_keylog_callback(raw, TlsConn::keylog_callback);

    if (!configure_protocols(raw, cfg.tls_protocols, error)) return nullptr;
    // Prefer the kernel/AES-NI-fast choices by default. Explicit Redis cipher knobs replace these
    // defaults exactly; they are also the compatibility escape hatch for other cipher suites.
    const char* tls12_ciphers = cfg.tls_ciphers && *cfg.tls_ciphers
        ? cfg.tls_ciphers
        : "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256";
    if (!SSL_CTX_set_cipher_list(raw, tls12_ciphers)) {
        error = openssl_error("Failed to configure tls-ciphers");
        return nullptr;
    }
    const char* tls13_ciphers = cfg.tls_ciphersuites && *cfg.tls_ciphersuites
        ? cfg.tls_ciphersuites
        : "TLS_AES_128_GCM_SHA256";
    if (!SSL_CTX_set_ciphersuites(raw, tls13_ciphers)) {
        error = openssl_error("Failed to configure tls-ciphersuites");
        return nullptr;
    }
    if (SSL_CTX_use_certificate_chain_file(raw, cfg.tls_cert_file) != 1) {
        error = openssl_error("Failed to load tls-cert-file");
        return nullptr;
    }
    if (SSL_CTX_use_PrivateKey_file(raw, cfg.tls_key_file, SSL_FILETYPE_PEM) != 1) {
        error = openssl_error("Failed to load tls-key-file");
        return nullptr;
    }
    if (SSL_CTX_check_private_key(raw) != 1) {
        error = openssl_error("tls-key-file does not match tls-cert-file");
        return nullptr;
    }
    const char* ca_file = cfg.tls_ca_cert_file && *cfg.tls_ca_cert_file
        ? cfg.tls_ca_cert_file : nullptr;
    const char* ca_dir = cfg.tls_ca_cert_dir && *cfg.tls_ca_cert_dir
        ? cfg.tls_ca_cert_dir : nullptr;
    if ((ca_file || ca_dir) && SSL_CTX_load_verify_locations(raw, ca_file, ca_dir) != 1) {
        error = openssl_error("Failed to load TLS CA certificates");
        return nullptr;
    }
    return out;
}

TlsContext::~TlsContext() {
    if (ctx_) SSL_CTX_free(ctx_);
}

TlsConn::~TlsConn() {
    OPENSSL_cleanse(traffic_key_.data(), traffic_key_.size());
    if (ssl_) SSL_free(ssl_);
    if (external_bio_) BIO_free(external_bio_);
}

void TlsConn::keylog_callback(const SSL* ssl, const char* line) {
    // OpenSSL 3.2+ owns kTLS re-keying in its record layer. The older record layer changes only
    // its userspace TX key. RX remains in OpenSSL, but a requested update also changes TX.
#if OPENSSL_VERSION_NUMBER < 0x30200000L
    auto* self = static_cast<TlsConn*>(SSL_get_app_data(const_cast<SSL*>(ssl)));
    static constexpr char label[] = "SERVER_TRAFFIC_SECRET_N ";
    if (!self || !line || self->tx_rekey_failed_ ||
        std::strncmp(line, label, sizeof(label) - 1) != 0 ||
        !BIO_get_ktls_send(SSL_get_wbio(ssl))) return;
    const char* secret = std::strrchr(line, ' ');
    if (!secret || !self->install_tls13_tx(secret + 1)) {
        // A keylog callback cannot return an SSL error. Shut down the fd BEFORE SSL_write can
        // send application data under a stale key, then surface the failure through the engine.
        self->tx_rekey_failed_ = true;
        self->last_error_ = "TLS 1.3 kTLS TX re-key failed (kernel TLS_TX re-key support required)";
        self->state_ = State::Failed;
        (void)::shutdown(self->socket_fd_, SHUT_RDWR);
    } else tx_rekeys.fetch_add(1, std::memory_order_relaxed);
#else
    (void)ssl; (void)line;
#endif
}

bool TlsConn::install_tls13_tx(const char* secret_hex) {
    if (SSL_version(ssl_) != TLS1_3_VERSION) return false;
    const SSL_CIPHER* cipher = SSL_get_current_cipher(ssl_);
    const EVP_MD* md = SSL_CIPHER_get_handshake_digest(cipher);
    const int secret_len = md ? EVP_MD_get_size(md) : 0;
    unsigned char secret[EVP_MAX_MD_SIZE]{};
    if (secret_len <= 0 || secret_len > static_cast<int>(sizeof(secret)) ||
        std::strlen(secret_hex) != static_cast<size_t>(secret_len) * 2) return false;
    bool valid = true;
    for (int i = 0; i < secret_len; ++i) {
        const int hi = hex_nibble(secret_hex[i * 2]), lo = hex_nibble(secret_hex[i * 2 + 1]);
        if (hi < 0 || lo < 0) { valid = false; break; }
        secret[i] = static_cast<unsigned char>((hi << 4) | lo);
    }
    bool installed = false;
    if (valid) {
        switch (SSL_CIPHER_get_protocol_id(cipher)) {
        case 0x1301:  // TLS_AES_128_GCM_SHA256
            installed = install_tx_key<tls12_crypto_info_aes_gcm_128>(socket_fd_,
                TLS_CIPHER_AES_GCM_128, md, secret, secret_len, traffic_key_.data()); break;
        case 0x1302:  // TLS_AES_256_GCM_SHA384
            installed = install_tx_key<tls12_crypto_info_aes_gcm_256>(socket_fd_,
                TLS_CIPHER_AES_GCM_256, md, secret, secret_len, traffic_key_.data()); break;
        case 0x1303:  // TLS_CHACHA20_POLY1305_SHA256
            installed = install_tx_key<tls12_crypto_info_chacha20_poly1305>(socket_fd_,
                TLS_CIPHER_CHACHA20_POLY1305, md, secret, secret_len, traffic_key_.data()); break;
        case 0x1304:  // TLS_AES_128_CCM_SHA256 (CCM_8 is not kTLS eligible)
            installed = install_tx_key<tls12_crypto_info_aes_ccm_128>(socket_fd_,
                TLS_CIPHER_AES_CCM_128, md, secret, secret_len, traffic_key_.data()); break;
        }
    }
    OPENSSL_cleanse(secret, sizeof(secret));
    OPENSSL_cleanse(traffic_key_.data(), traffic_key_.size());
    return installed;
}

bool TlsConn::install_memory_bio(std::string& error) {
    BIO* internal = nullptr;
    BIO* external = nullptr;
    if (BIO_new_bio_pair(&internal, kBioBytes, &external, kBioBytes) != 1) {
        error = openssl_error("Failed to create TLS BIO pair");
        return false;
    }
    // rbio and wbio intentionally name the same internal endpoint. SSL owns both references.
    if (BIO_up_ref(internal) != 1) {
        BIO_free(internal);
        BIO_free(external);
        error = openssl_error("Failed to retain TLS internal BIO");
        return false;
    }
    SSL_set0_rbio(ssl_, internal);
    SSL_set0_wbio(ssl_, internal);
    external_bio_ = external;
    return true;
}

void TlsConn::restore_socket_flags() {
    if (socket_fd_ >= 0 && saved_socket_flags_ >= 0)
        (void)::fcntl(socket_fd_, F_SETFL, saved_socket_flags_);
    saved_socket_flags_ = -1;
}

bool TlsConn::init(const TlsContext& context, TlsAuthClients auth, int fd,
                   std::string& error) {
    ERR_clear_error();
    ssl_ = SSL_new(context.native());
    if (!ssl_) {
        error = openssl_error("Failed to create TLS connection");
        return false;
    }
    SSL_set_app_data(ssl_, this);

    socket_fd_ = fd;
    fd_handshake_ = true;
    saved_socket_flags_ = ::fcntl(fd, F_GETFL, 0);
    if (saved_socket_flags_ < 0 ||
        ::fcntl(fd, F_SETFL, saved_socket_flags_ | O_NONBLOCK) != 0 ||
        SSL_set_fd(ssl_, fd) != 1) {
        error = openssl_error("Failed to attach non-blocking TLS socket");
        restore_socket_flags();
        return false;
    }
    SSL_set_mode(ssl_, SSL_MODE_ENABLE_PARTIAL_WRITE |
                        SSL_MODE_ACCEPT_MOVING_WRITE_BUFFER |
                        SSL_MODE_RELEASE_BUFFERS);
    int verify = SSL_VERIFY_NONE;
    if (auth == TlsAuthClients::Yes)
        verify = SSL_VERIFY_PEER | SSL_VERIFY_FAIL_IF_NO_PEER_CERT;
    else if (auth == TlsAuthClients::Optional)
        verify = SSL_VERIFY_PEER;
    SSL_set_verify(ssl_, verify, nullptr);
    SSL_set_accept_state(ssl_);
    state_ = State::Handshaking;
    error.clear();
    return true;
}

void TlsConn::record_error(const char* operation, int ssl_error) {
    char prefix[128];
    std::snprintf(prefix, sizeof(prefix), "%s failed (SSL error %d)", operation, ssl_error);
    last_error_ = openssl_error(prefix);
}

TlsOp TlsConn::funnel(int result, const char* operation) {
    const int error = SSL_get_error(ssl_, result);
    if (error == SSL_ERROR_WANT_READ) return wanted_ = TlsOp::WantRead;
    if (error == SSL_ERROR_WANT_WRITE) return wanted_ = TlsOp::WantWrite;
    if (error == SSL_ERROR_ZERO_RETURN) return TlsOp::GracefulEof;
    record_error(operation, error);
    state_ = State::Failed;
    return TlsOp::Error;
}

TlsOp TlsConn::handshake() {
    ERR_clear_error();
    const int result = SSL_accept(ssl_);
    if (result == 1) {
        // A socket BIO is unbuffered. SSL_accept has emitted its final flight (including TLS 1.3
        // session tickets) before returning success. A zero-length SSL_write_ex completes any
        // provider-delayed post-handshake ticket work while OpenSSL still owns the record layer;
        // the explicit BIO flush then rejects a future buffered BIO substitution.
        size_t ticket_bytes = 0;
        const char empty = 0;
        const int ticket_result = SSL_write_ex(ssl_, &empty, 0, &ticket_bytes);
        if (ticket_result != 1) return funnel(ticket_result, "TLS ticket flush");
        BIO* wbio = SSL_get_wbio(ssl_);
        BIO* rbio = SSL_get_rbio(ssl_);
        const bool ktls_send = BIO_get_ktls_send(wbio);
        const bool ktls_recv = BIO_get_ktls_recv(rbio);
        const bool tls13 = SSL_version(ssl_) == TLS1_3_VERSION;
        // NET2: never install RX from CLIENT_TRAFFIC_SECRET_0 or give TLS 1.3 records to raw
        // recv. OpenSSL must consume KeyUpdate/control records and keep its RX secrets current.
        // If a newer OpenSSL installed RX itself, retain its socket BIO and record layer too.
        if (BIO_flush(wbio) == 1 && !tls13 && ktls_send && ktls_recv) {
            restore_socket_flags();
            wanted_ = TlsOp::Progress;
            ktls_engaged_ = true;
            state_ = State::Ktls;
            return TlsOp::Progress;
        }

        // Once either TLS_TX or TLS_RX is configured it cannot be removed from a live socket.
        // Keep OpenSSL on its fd BIO so it owns the direction the kernel did not offload; swapping
        // to a memory BIO here would feed ciphertext into TLS_TX and double-encrypt it.
        if (ktls_send || ktls_recv) {
            wanted_ = TlsOp::Progress;
            state_ = State::SocketUserspace;
            if (tls13) rx_declined_13.fetch_add(1, std::memory_order_relaxed);
            return TlsOp::Progress;
        }

        std::string error;
        if (!install_memory_bio(error)) {
            restore_socket_flags();
            last_error_ = error;
            state_ = State::Failed;
            return TlsOp::Error;
        }
        restore_socket_flags();
        wanted_ = TlsOp::Progress;
        state_ = State::MemoryUserspace;
        if (tls13) rx_declined_13.fetch_add(1, std::memory_order_relaxed);
        return TlsOp::Progress;
    }
    return funnel(result, "TLS handshake");
}

TlsIoResult TlsConn::read_plain(char* dst, size_t capacity) {
    if (tx_rekey_failed_) return {TlsOp::Error, 0};
    const int offer = static_cast<int>(std::min(capacity, static_cast<size_t>(INT_MAX)));
    ERR_clear_error();
    const int result = SSL_read(ssl_, dst, offer);
    if (tx_rekey_failed_) return {TlsOp::Error, 0};
    if (result > 0) {
        wanted_ = TlsOp::Progress;
        return {TlsOp::Progress, static_cast<uint32_t>(result)};
    }
    return {funnel(result, "TLS read"), 0};
}

TlsIoResult TlsConn::write_plain(const char* src, size_t length) {
    if (tx_rekey_failed_) return {TlsOp::Error, 0};
    if (pending_plain_len_) {
        src = pending_plain_ptr_;
        length = pending_plain_len_;
    }
    const int offer = static_cast<int>(std::min(length, static_cast<size_t>(INT_MAX)));
    ERR_clear_error();
    const int result = SSL_write(ssl_, src, offer);
    if (tx_rekey_failed_) return {TlsOp::Error, 0};
    if (result > 0) {
        wanted_ = TlsOp::Progress;
        pending_plain_ptr_ = nullptr;
        pending_plain_len_ = 0;
        return {TlsOp::Progress, static_cast<uint32_t>(result)};
    }
    const TlsOp op = funnel(result, "TLS write");
    if (op == TlsOp::WantRead || op == TlsOp::WantWrite) {
        pending_plain_ptr_ = src;
        pending_plain_len_ = static_cast<uint32_t>(offer);
    }
    return {op, 0};
}

TlsOp TlsConn::shutdown() {
    shutdown_started_ = true;
    ERR_clear_error();
    const int result = SSL_shutdown(ssl_);
    if (result >= 0) return TlsOp::Progress;  // 0 means close_notify emitted, peer reply pending.
    return funnel(result, "TLS shutdown");
}

int TlsConn::reserve_input(char*& dst, size_t cap) {
    dst = nullptr;
    if (!external_bio_ || reserved_input_) return -1;
    char* raw = nullptr;
    const int contiguous = BIO_nwrite0(external_bio_, &raw);
    if (contiguous <= 0) return contiguous;
    const size_t offered = std::min(static_cast<size_t>(contiguous), cap);
    reserved_input_ = raw;
    reserved_input_cap_ = static_cast<uint32_t>(offered);
    dst = raw;
    return static_cast<int>(offered);
}

bool TlsConn::commit_input(size_t bytes) {
    if (!external_bio_ || !reserved_input_ || bytes > reserved_input_cap_ || bytes > INT_MAX)
        return false;
    char* committed = nullptr;
    const int result = BIO_nwrite(external_bio_, &committed, static_cast<int>(bytes));
    const bool ok = result == static_cast<int>(bytes) && committed == reserved_input_;
    reserved_input_ = nullptr;
    reserved_input_cap_ = 0;
    return ok;
}

void TlsConn::abandon_input() {
    reserved_input_ = nullptr;
    reserved_input_cap_ = 0;
}

int TlsConn::peek_output(const char*& src) const {
    if (!external_bio_) { src = nullptr; return 0; }
    char* raw = nullptr;
    const int result = BIO_nread0(external_bio_, &raw);
    src = result > 0 ? raw : nullptr;
    return result;
}

bool TlsConn::consume_output(size_t bytes) {
    if (!external_bio_ || bytes > INT_MAX) return false;
    char* consumed = nullptr;
    const int result = BIO_nread(external_bio_, &consumed, static_cast<int>(bytes));
    return result == static_cast<int>(bytes);
}

bool TlsConn::output_pending() const {
    return external_bio_ && BIO_ctrl_pending(external_bio_) != 0;
}

bool TlsConn::input_pending() const {
    if (!external_bio_) return false;
    if (SSL_pending(ssl_) > 0) return true;
    return BIO_ctrl_get_write_guarantee(external_bio_) < kBioBytes;
}

}  // namespace tomo
