// NET2: real OpenSSL handshakes/KeyUpdates over an AF_UNIX socketpair, no listener or server.
// Link wrappers affect only TomoKV's offload observations/setsockopt, not libssl internals.
// Thus the promotion decision sees an available kernel without requiring root or kTLS.
#include "src/net/tls.h"
#include "src/core/config.h"
#include <openssl/err.h>
#include <openssl/kdf.h>
#include <openssl/core_names.h>
#include <csignal>
#include <vector>
#include <linux/tls.h>
#include <sys/socket.h>
#include <unistd.h>
#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

using namespace tomo;
namespace {
struct SslAccess { using Type = SSL* TlsConn::*; friend Type member(SslAccess); };
template <SslAccess::Type P> struct SslMember {
    friend SslAccess::Type member(SslAccess) { return P; }
};
template struct SslMember<&TlsConn::ssl_>;
BIO* observed_bio = nullptr;
bool fake_tx = false, fake_rx = false;
unsigned rx_installs = 0, tx_installs = 0;
bool reject_tx = false;
std::vector<std::vector<unsigned char>> installed_keys;
std::vector<std::string> peer_secrets;
void peer_keylog(const SSL*, const char* line) {
    if (std::strncmp(line, "SERVER_TRAFFIC_SECRET_N ", 24) == 0)
        peer_secrets.emplace_back(std::strrchr(line, ' ') + 1);
}
std::string current_case;
void require(bool okay, const char* assertion) {
    if (okay) return;
    std::fprintf(stderr, "FAIL %s: %s\n", current_case.c_str(), assertion);
    ERR_print_errors_fp(stderr);
    std::exit(1);
}
struct Fixture {
    std::unique_ptr<TlsContext> context;
    TlsConn server;
    SSL_CTX* client_context = nullptr;
    SSL* client = nullptr;
    int fds[2]{-1, -1};
    Fixture(const std::string& dir, int version, bool attempt, bool tx, bool rx,
            const char* suite = "TLS_AES_128_GCM_SHA256", bool small_fragment = false) {
        fake_tx = tx; fake_rx = rx; rx_installs = tx_installs = 0;
        installed_keys.clear(); peer_secrets.clear();
        Config cfg;
        const auto cert = dir + "/server.crt", key = dir + "/server.key";
        cfg.tls_cert_file = cert.c_str(); cfg.tls_key_file = key.c_str();
        cfg.tls_ciphersuites = suite;
        cfg.tls_protocols = version == TLS1_3_VERSION ? "TLSv1.3" : "TLSv1.2";
        std::string error;
        context = TlsContext::create(cfg, error);
        require(context != nullptr, error.c_str());
        require(socketpair(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK, 0, fds) == 0,
                "local socketpair");
        require(server.init(*context, TlsAuthClients::No, fds[0], attempt, error), error.c_str());
        observed_bio = SSL_get_wbio(server.*member(SslAccess{}));
        client_context = SSL_CTX_new(TLS_client_method());
        require(client_context && SSL_CTX_set_min_proto_version(client_context, version) == 1 &&
                SSL_CTX_set_max_proto_version(client_context, version) == 1, "client protocol");
        require(SSL_CTX_set_ciphersuites(client_context, suite) == 1,
                "client cipher");
        if (small_fragment)
            require(SSL_CTX_set_tlsext_max_fragment_length(client_context, TLSEXT_max_fragment_length_512) == 1,
                    "request pure userspace live arm's maximum fragment length");
        SSL_CTX_set_keylog_callback(client_context, peer_keylog);
        client = SSL_new(client_context);
        require(client && SSL_set_fd(client, fds[1]) == 1, "client socket BIO");
        bool client_done = false;
        for (unsigned i = 0; i < 1000 && (!client_done || server.handshaking()); ++i) {
            if (!client_done) {
                ERR_clear_error();
                const int n = SSL_connect(client);
                if (n == 1) client_done = true;
                else want(n, "client handshake");
            }
            pump();
            if (server.handshaking()) {
                const auto op = server.handshake();
                require(op == TlsOp::Progress || op == TlsOp::WantRead || op == TlsOp::WantWrite,
                        server.last_error().c_str());
            }
            pump();
        }
        require(client_done && server.connected(), "bounded handshake completed");
        require(SSL_version(client) == version, "negotiated requested version");
        if (small_fragment)
            require(SSL_SESSION_get_max_fragment_length(SSL_get_session(client)) == TLSEXT_max_fragment_length_512 &&
                    SSL_SESSION_get_max_fragment_length(SSL_get_session(server.*member(SslAccess{}))) == TLSEXT_max_fragment_length_512,
                    "both peers agree on userspace-only fragment size");
    }
    ~Fixture() {
        observed_bio = nullptr;
        SSL_free(client); SSL_CTX_free(client_context);
        close(fds[0]); close(fds[1]);
    }
    void want(int n, const char* message) {
        const int error = SSL_get_error(client, n);
        require(error == SSL_ERROR_WANT_READ || error == SSL_ERROR_WANT_WRITE, message);
    }
    void pump() {
        if (!server.memory_bio()) return;
        const char* src = nullptr;
        int pending = server.peek_output(src);
        if (pending > 0) {
            const int n = ::send(fds[0], src, pending, MSG_NOSIGNAL);
            if (n > 0) require(server.consume_output(n), "ciphertext output accounting");
            else require(errno == EAGAIN || errno == EWOULDBLOCK, "ciphertext send");
        }
        char* dst = nullptr;
        const int space = server.reserve_input(dst, TlsConn::kBioBytes);
        if (space > 0) {
            const int n = ::recv(fds[0], dst, space, 0);
            if (n > 0) require(server.commit_input(n), "ciphertext input accounting");
            else {
                server.abandon_input();
                require(n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK), "ciphertext recv");
            }
        }
    }
    void exchange() {
        static const std::string request = "*1\r\n$4\r\nPING\r\n";
        static const std::string response = "+PONG\r\n";
        size_t sent = 0, replied = 0;
        std::string got_request, got_reply;
        for (unsigned i = 0; i < 1000 && got_reply.size() < response.size(); ++i) {
            char bytes[1024];
            if (sent < request.size()) {
                ERR_clear_error();
                const int n = SSL_write(client, request.data() + sent, request.size() - sent);
                if (n > 0) sent += n; else want(n, "client request write");
            }
            pump();
            if (got_request.size() < request.size()) {
                const auto read = server.read_plain(bytes, sizeof(bytes));
                if (read.op == TlsOp::Progress) got_request.append(bytes, read.bytes);
                else require(read.op == TlsOp::WantRead || read.op == TlsOp::WantWrite,
                             server.last_error().c_str());
            }
            if (got_request.size() >= request.size()) {
                require(got_request == request, "KeyUpdate control bytes never reach RESP");
                if (replied < response.size()) {
                    const auto write = server.write_plain(response.data() + replied,
                                                          response.size() - replied);
                    if (write.op == TlsOp::Progress) replied += write.bytes;
                    else require(write.op == TlsOp::WantRead || write.op == TlsOp::WantWrite,
                                 server.last_error().c_str());
                }
            }
            pump();
            ERR_clear_error();
            const int n = SSL_read(client, bytes, sizeof(bytes));
            if (n > 0) got_reply.append(bytes, n); else want(n, "client response read");
        }
        require(got_reply == response, "PING survives KeyUpdate");
    }
    void updates() {
        exchange();
        for (int request : {SSL_KEY_UPDATE_NOT_REQUESTED, SSL_KEY_UPDATE_REQUESTED,
                            SSL_KEY_UPDATE_REQUESTED, SSL_KEY_UPDATE_NOT_REQUESTED}) {
            require(SSL_key_update(client, request) == 1, "schedule legal KeyUpdate");
            // Coalesce the update and the first new-key application record.
            exchange();
        }
        require(server.connected(), "connection remains usable after repeated KeyUpdates");
    }
};
}  // namespace
extern "C" long __real_BIO_ctrl(BIO*, int, long, void*);
extern "C" long __wrap_BIO_ctrl(BIO* bio, int command, long value, void* ptr) {
    if (bio == observed_bio) {
        if (command == BIO_CTRL_GET_KTLS_SEND) return fake_tx;
        if (command == BIO_CTRL_GET_KTLS_RECV) return fake_rx;
    }
    return __real_BIO_ctrl(bio, command, value, ptr);
}
extern "C" int __wrap_setsockopt(int, int level, int option, const void* value, socklen_t length) {
    require(level == SOL_TLS, "only kTLS setsockopt is intercepted");
    if (option == TLS_RX) ++rx_installs;
    else if (option == TLS_TX) {
        ++tx_installs;
        installed_keys.emplace_back(static_cast<const unsigned char*>(value),
                                    static_cast<const unsigned char*>(value) + length);
        if (reject_tx) { errno = EBUSY; return -1; }
    }
    else require(false, "unexpected kTLS option");
    return 0;
}
// Compare the kernel key/IV to the secrets learned by the *peer*, deriving with the separate
// OpenSSL TLS13-KDF API. This catches wrong direction/hash/label, stale keys and nonzero sequences.
template <class Crypto>
void check_keys(uint16_t cipher, const char* digest) {
    require(installed_keys.size() == 2 && peer_secrets.size() == 2, "two peer-confirmed TX re-keys");
    for (size_t i = 0; i < installed_keys.size(); ++i) {
        require(installed_keys[i].size() == sizeof(Crypto), "kernel cipher structure size");
        Crypto crypto;
        std::memcpy(&crypto, installed_keys[i].data(), sizeof(crypto));
        require(crypto.info.version == TLS_1_3_VERSION && crypto.info.cipher_type == cipher,
                "kernel protocol and cipher");
        unsigned char secret[64]{}, key[32]{}, iv[12]{};
        const auto& hex = peer_secrets[i];
        for (size_t j = 0; j < hex.size() / 2; ++j)
            secret[j] = static_cast<unsigned char>(std::stoul(hex.substr(j * 2, 2), nullptr, 16));
        for (bool make_iv : {false, true}) {
            EVP_KDF* kdf = EVP_KDF_fetch(nullptr, "TLS13-KDF", nullptr);
            require(kdf != nullptr, "independent TLS13 KDF");
            EVP_KDF_CTX* context = EVP_KDF_CTX_new(kdf);
            EVP_KDF_free(kdf);
            int mode = EVP_KDF_HKDF_MODE_EXPAND_ONLY;
            auto* label = const_cast<char*>(make_iv ? "iv" : "key");
            char prefix[] = "tls13 ";
            OSSL_PARAM params[]{
                OSSL_PARAM_construct_int(OSSL_KDF_PARAM_MODE, &mode),
                OSSL_PARAM_construct_utf8_string(OSSL_KDF_PARAM_DIGEST, const_cast<char*>(digest), 0),
                OSSL_PARAM_construct_octet_string(OSSL_KDF_PARAM_KEY, secret, hex.size() / 2),
                OSSL_PARAM_construct_octet_string(OSSL_KDF_PARAM_PREFIX, prefix, sizeof(prefix) - 1),
                OSSL_PARAM_construct_octet_string(OSSL_KDF_PARAM_LABEL, label, std::strlen(label)),
                OSSL_PARAM_construct_end()};
            require(context && EVP_KDF_derive(context, make_iv ? iv : key,
                    make_iv ? sizeof(iv) : sizeof(crypto.key), params) == 1, "derive peer key/IV");
            EVP_KDF_CTX_free(context);
        }
        require(std::memcmp(crypto.key, key, sizeof(crypto.key)) == 0 &&
                std::memcmp(crypto.salt, iv, sizeof(crypto.salt)) == 0 &&
                std::memcmp(crypto.iv, iv + sizeof(crypto.salt), sizeof(crypto.iv)) == 0,
                "TLS13_TX_REKEY_MATERIAL: kernel key/IV match the peer");
        for (auto byte : crypto.rec_seq) require(byte == 0, "new key starts at sequence zero");
        OPENSSL_cleanse(secret, sizeof(secret)); OPENSSL_cleanse(key, sizeof(key));
        OPENSSL_cleanse(iv, sizeof(iv)); OPENSSL_cleanse(&crypto, sizeof(crypto));
    }
    require(installed_keys[0] != installed_keys[1], "repeated KeyUpdates install distinct keys");
}
int main(int argc, char** argv) {
    std::signal(SIGPIPE, SIG_IGN);
    require(argc == 3, "usage: ktls-keyupdate-unit CERT_DIR rx-policy|tls12|userspace|tx-rekey|tx-failure");
    current_case = argv[2];
    if (current_case == "rx-policy") {
        for (bool native_rx : {false, true}) {
            Fixture f(argv[1], TLS1_3_VERSION, true, true, native_rx);
            require(rx_installs == 0, "TLS13_RX_DECLINED: no initial-secret TLS_RX install");
            require(f.server.socket_userspace() && !f.server.ktls(),
                    "TLS13_RX_DECLINED: OpenSSL retains control-record ownership");
            f.updates();
        }
    } else if (current_case == "tx-rekey") {
        for (auto suite : {"TLS_AES_128_GCM_SHA256", "TLS_AES_256_GCM_SHA384",
                           "TLS_CHACHA20_POLY1305_SHA256", "TLS_AES_128_CCM_SHA256"}) {
            Fixture f(argv[1], TLS1_3_VERSION, true, true, false, suite);
            f.updates();
            require(tx_installs == 2, "TLS13_TX_REKEY: both requested updates reinstall TX");
            switch (SSL_CIPHER_get_protocol_id(SSL_get_current_cipher(f.client))) {
            case 0x1301: check_keys<tls12_crypto_info_aes_gcm_128>(TLS_CIPHER_AES_GCM_128, "SHA256"); break;
            case 0x1302: check_keys<tls12_crypto_info_aes_gcm_256>(TLS_CIPHER_AES_GCM_256, "SHA384"); break;
            case 0x1303: check_keys<tls12_crypto_info_chacha20_poly1305>(TLS_CIPHER_CHACHA20_POLY1305, "SHA256"); break;
            case 0x1304: check_keys<tls12_crypto_info_aes_ccm_128>(TLS_CIPHER_AES_CCM_128, "SHA256"); break;
            default: require(false, "known re-key cipher");
            }
        }
    } else if (current_case == "tx-failure") {
        Fixture f(argv[1], TLS1_3_VERSION, true, true, false);
        f.exchange();
        reject_tx = true;
        require(SSL_key_update(f.client, SSL_KEY_UPDATE_REQUESTED) == 1 &&
                SSL_do_handshake(f.client) == 1, "request update before rejected TX install");
        char bytes[128];
        (void)f.server.read_plain(bytes, sizeof(bytes));
        const auto write = f.server.write_plain("+PONG\r\n", 7);
        require(tx_installs == 1 && f.server.failed() && write.op == TlsOp::Error && write.bytes == 0,
                "TLS13_TX_REKEY_FAILURE: reject application writes after failed key install");
        require(f.server.last_error().find("kTLS TX re-key failed") != std::string::npos,
                "failed re-key has a diagnostic");
    } else if (current_case == "tls12") {
        Fixture f(argv[1], TLS1_2_VERSION, true, true, true);
        require(f.server.ktls() && f.server.was_ktls(), "TLS12_KTLS: both directions retained");
        require(rx_installs == 0, "TLS12_KTLS: no manual key install");
    } else if (current_case == "userspace") {
        for (bool attempt : {false, true}) {
            Fixture f(argv[1], TLS1_3_VERSION, attempt, false, false, "TLS_AES_128_GCM_SHA256", attempt);
            require(f.server.memory_userspace(), "userspace fallback stays on the BIO pair");
            f.updates();
            require(rx_installs == 0 && tx_installs == 0, "userspace never installs kernel keys");
        }
    } else require(false, "unknown case");
    std::printf("ok: NET2 %s (TlsConn=%zu)\n", current_case.c_str(), sizeof(TlsConn));
}
