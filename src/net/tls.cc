#include "tls.h"

#include <algorithm>
#include <cctype>
#include <climits>
#include <cstring>
#include <sstream>

#include <openssl/bio.h>
#include <openssl/err.h>

#include "../core/config.h"

namespace tomo {
namespace {

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

}  // namespace

std::unique_ptr<TlsContext> TlsContext::create(const Config& cfg, std::string& error) {
    error.clear();
    ERR_clear_error();
    SSL_CTX* raw = SSL_CTX_new(TLS_server_method());
    if (!raw) {
        error = openssl_error("Failed to create TLS context");
        return nullptr;
    }
    std::unique_ptr<TlsContext> out(new TlsContext(raw));

    SSL_CTX_set_options(raw, SSL_OP_NO_COMPRESSION | SSL_OP_NO_RENEGOTIATION);
    if (cfg.tls_prefer_server_ciphers)
        SSL_CTX_set_options(raw, SSL_OP_CIPHER_SERVER_PREFERENCE);
    SSL_CTX_set_session_cache_mode(raw, SSL_SESS_CACHE_OFF);
    SSL_CTX_set_dh_auto(raw, 1);

    if (!configure_protocols(raw, cfg.tls_protocols, error)) return nullptr;
    if (cfg.tls_ciphers && *cfg.tls_ciphers &&
        !SSL_CTX_set_cipher_list(raw, cfg.tls_ciphers)) {
        error = openssl_error("Failed to configure tls-ciphers");
        return nullptr;
    }
    if (cfg.tls_ciphersuites && *cfg.tls_ciphersuites &&
        !SSL_CTX_set_ciphersuites(raw, cfg.tls_ciphersuites)) {
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
    if (ssl_) SSL_free(ssl_);
    if (external_bio_) BIO_free(external_bio_);
}

bool TlsConn::init(const TlsContext& context, TlsAuthClients auth, std::string& error) {
    ERR_clear_error();
    ssl_ = SSL_new(context.native());
    if (!ssl_) {
        error = openssl_error("Failed to create TLS connection");
        return false;
    }

    BIO* internal = nullptr;
    if (BIO_new_bio_pair(&internal, kBioBytes, &external_bio_, kBioBytes) != 1) {
        error = openssl_error("Failed to create TLS BIO pair");
        return false;
    }
    // rbio and wbio intentionally name the same internal endpoint. SSL owns both references.
    if (BIO_up_ref(internal) != 1) {
        BIO_free(internal);
        error = openssl_error("Failed to retain TLS internal BIO");
        return false;
    }
    SSL_set0_rbio(ssl_, internal);
    SSL_set0_wbio(ssl_, internal);
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
    if (error == SSL_ERROR_WANT_READ) return TlsOp::WantRead;
    if (error == SSL_ERROR_WANT_WRITE) return TlsOp::WantWrite;
    if (error == SSL_ERROR_ZERO_RETURN) return TlsOp::GracefulEof;
    record_error(operation, error);
    state_ = State::Failed;
    return TlsOp::Error;
}

TlsOp TlsConn::handshake() {
    ERR_clear_error();
    const int result = SSL_accept(ssl_);
    if (result == 1) {
        state_ = State::Connected;
        return TlsOp::Progress;
    }
    return funnel(result, "TLS handshake");
}

TlsIoResult TlsConn::read_plain(char* dst, size_t capacity) {
    const int offer = static_cast<int>(std::min(capacity, static_cast<size_t>(INT_MAX)));
    ERR_clear_error();
    const int result = SSL_read(ssl_, dst, offer);
    if (result > 0) return {TlsOp::Progress, static_cast<uint32_t>(result)};
    return {funnel(result, "TLS read"), 0};
}

TlsIoResult TlsConn::write_plain(const char* src, size_t length) {
    if (pending_plain_len_) {
        src = pending_plain_ptr_;
        length = pending_plain_len_;
    }
    const int offer = static_cast<int>(std::min(length, static_cast<size_t>(INT_MAX)));
    ERR_clear_error();
    const int result = SSL_write(ssl_, src, offer);
    if (result > 0) {
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
    if (reserved_input_) return -1;
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
    if (!reserved_input_ || bytes > reserved_input_cap_ || bytes > INT_MAX) return false;
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
    char* raw = nullptr;
    const int result = BIO_nread0(external_bio_, &raw);
    src = result > 0 ? raw : nullptr;
    return result;
}

bool TlsConn::consume_output(size_t bytes) {
    if (bytes > INT_MAX) return false;
    char* consumed = nullptr;
    const int result = BIO_nread(external_bio_, &consumed, static_cast<int>(bytes));
    return result == static_cast<int>(bytes);
}

bool TlsConn::output_pending() const {
    return BIO_ctrl_pending(external_bio_) != 0;
}

bool TlsConn::input_pending() const {
    if (SSL_pending(ssl_) > 0) return true;
    return BIO_ctrl_get_write_guarantee(external_bio_) < kBioBytes;
}

}  // namespace tomo
