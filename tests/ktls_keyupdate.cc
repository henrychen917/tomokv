// NET2 live witness. Connects to a fresh, maintainer/gate-owned TLS listener; starts no server.
// tx: TLS 1.3 userspace RX + kernel TX, both KeyUpdate types and repeated requested updates.
// userspace: negotiate a 512-byte maximum fragment, which makes OpenSSL decline kernel TX.
#include <openssl/ssl.h>
#include <openssl/err.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <thread>
#include <chrono>

void require(bool value, const char* reason) {
    if (!value) {
        std::fprintf(stderr, "FAIL: %s\n", reason);
        ERR_print_errors_fp(stderr);
        std::exit(1);
    }
}
std::string read_exact(SSL* ssl, size_t size) {
    std::string result(size, '\0'); size_t done = 0;
    while (done < size) {
        const int n = SSL_read(ssl, result.data() + done, size - done);
        require(n > 0, "TLS read failed after a legal KeyUpdate"); done += n;
    }
    return result;
}
std::string read_line(SSL* ssl) {
    std::string line;
    while (!line.ends_with("\r\n")) {
        require(line.size() < 4096, "bounded RESP line");
        line += read_exact(ssl, 1);
    }
    return line;
}
void send(SSL* ssl, const std::string& request) {
    size_t done = 0;
    while (done < request.size()) {
        const int n = SSL_write(ssl, request.data() + done, request.size() - done);
        require(n > 0, "TLS write failed"); done += n;
    }
}
std::string stats(SSL* ssl) {
    send(ssl, "INFO STATS\r\n");
    const auto header = read_line(ssl);
    require(header[0] == '$', "INFO bulk reply");
    const auto size = std::stoull(header.substr(1));
    require(size < 1024 * 1024, "bounded INFO bulk reply");
    return read_exact(ssl, size + 2);
}
uint64_t counter(const std::string& info, const char* name) {
    const std::string prefix = std::string("\r\n") + name + ":";
    const size_t pos = info.find(prefix);
    require(pos != std::string::npos, (std::string("missing INFO counter: ") + name).c_str());
    return std::stoull(info.substr(pos + prefix.size()));
}
int main(int argc, char** argv) {
    require(argc == 4, "usage: ktls-keyupdate HOST PORT tx|userspace");
    const std::string arm = argv[3];
    require(arm == "tx" || arm == "userspace", "known transport arm");
    SSL_CTX* ctx = SSL_CTX_new(TLS_client_method()); require(ctx, "client context");
    require(SSL_CTX_set_min_proto_version(ctx, TLS1_3_VERSION) == 1 &&
            SSL_CTX_set_max_proto_version(ctx, TLS1_3_VERSION) == 1, "TLS1.3 selected");
    require(SSL_CTX_set_ciphersuites(ctx, "TLS_AES_128_GCM_SHA256") == 1, "TLS1.3 cipher selected");
    if (arm == "userspace")
        require(SSL_CTX_set_tlsext_max_fragment_length(ctx, TLSEXT_max_fragment_length_512) == 1,
                "request userspace-only record size");
    const int fd = socket(AF_INET, SOCK_STREAM, 0); require(fd >= 0, "client socket");
    timeval timeout{5, 0};
    require(setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) == 0 &&
            setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) == 0, "socket deadlines");
    sockaddr_in address{}; address.sin_family = AF_INET; address.sin_port = htons(std::atoi(argv[2]));
    require(inet_pton(AF_INET, argv[1], &address.sin_addr) == 1, "numeric host address");
    require(connect(fd, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0, "connect");
    SSL* ssl = SSL_new(ctx); require(ssl && SSL_set_fd(ssl, fd) == 1 && SSL_connect(ssl) == 1, "TLS handshake");
    require(SSL_version(ssl) == TLS1_3_VERSION, "negotiated TLS 1.3");
    if (arm == "userspace")
        require(SSL_SESSION_get_max_fragment_length(SSL_get_session(ssl)) == TLSEXT_max_fragment_length_512,
                "peer acknowledged userspace-only record size");
    auto info = stats(ssl);
    // Prior gate clients can still be crossing the deferred-free fence. This is bounded arming,
    // never a skip: no update is sent until this connection is the sole TLS connection.
    for (unsigned i = 0; i < 50 && counter(info, "tls_current_connections") != 1; ++i) {
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
        info = stats(ssl);
    }
    require(counter(info, "tls_current_connections") == 1, "sole TLS connection arms the witness");
    require(counter(info, "tls_ktls_active") == 0, "TLS13_RX_DECLINED: no raw kTLS receive path");
    require(counter(info, "tls_ktls_rx_declined_13") > 0, "TLS13_RX_DECLINED counter fired");
    const auto rekeys = counter(info, "tls_ktls_tx_rekeys");
    std::printf("armed: TLS1.3 %s; RX retained by OpenSSL\n", arm.c_str()); std::fflush(stdout);
    unsigned requested = 0;
    for (int update : {SSL_KEY_UPDATE_NOT_REQUESTED, SSL_KEY_UPDATE_REQUESTED,
                       SSL_KEY_UPDATE_REQUESTED, SSL_KEY_UPDATE_NOT_REQUESTED}) {
        require(SSL_key_update(ssl, update) == 1 && SSL_do_handshake(ssl) == 1,
                "legal KeyUpdate sent");
        send(ssl, "PING\r\nECHO keyupdate-byte-receipt\r\n");
        require(read_line(ssl) == "+PONG\r\n", "PING survives KeyUpdate");
        require(read_line(ssl) == "$22\r\n" && read_exact(ssl, 24) == "keyupdate-byte-receipt\r\n",
                "pipelined ECHO preserves bytes and reply order after KeyUpdate");
        requested += update == SSL_KEY_UPDATE_REQUESTED;
        const auto now = counter(stats(ssl), "tls_ktls_tx_rekeys");
        require(now == rekeys + (arm == "tx" ? requested : 0),
                "TLS13_TX_REKEY: requested updates prove the exact TX arm, never skip");
    }
    SSL_free(ssl); SSL_CTX_free(ctx); close(fd);
    std::printf("ok: NET2 live KeyUpdate %s\n", arm.c_str());
}
