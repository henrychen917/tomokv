// Deterministic single-connection RESP replay driver for instructions/op measurement.
//
// One connection, fixed pipeline depth, a fixed key ring, an exactly-known operation count. The
// server is measured with perf; this program only guarantees that arm A and arm B receive the
// byte-identical request stream in the identical order.
//
//   replay <port> <shape> <keylen> <ops> <pipeline> [valuelen] [keyring]
//
// shapes: get_hit  GET over pre-populated keys
//         get_miss GET over keys never written (disjoint prefix)
//         set_over SET over pre-populated keys, same value length (overwrite in place)
//         mixed11  GET k, SET k alternating on the SAME key, 1:1
//         mixed11x GET k, SET k+ring/2 alternating: 1:1 with DISJOINT read and write key sets,
//                  which is what an independent-key 1:1 load generator produces
//         warm     SET every key once (population; not measured)
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <time.h>

static char keybuf[64];

// Key i of the ring, padded to `keylen` with a deterministic filler. `miss` shifts the namespace
// so a miss shape can never collide with a populated key of the same length.
static void make_key(char *out, int keylen, unsigned i, int miss) {
    int n = snprintf(out, 64, "%c%010u", miss ? 'm' : 'k', i);
    for (; n < keylen; n++) out[n] = 'a' + (char)((i + (unsigned)n) % 26);
    out[keylen] = '\0';
}

static double now_s(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + 1e-9 * (double)t.tv_nsec;
}

int main(int argc, char **argv) {
    if (argc < 6) { fprintf(stderr, "usage: replay port shape keylen ops pipeline [vlen] [ring]\n"); return 2; }
    int port = atoi(argv[1]);
    const char *shape = argv[2];
    int keylen = atoi(argv[3]);
    long ops = atol(argv[4]);
    int pipeline = atoi(argv[5]);
    int vlen = argc > 6 ? atoi(argv[6]) : 32;
    unsigned ring = argc > 7 ? (unsigned)atoi(argv[7]) : 4096;
    if (keylen < 12 || keylen > 60) { fprintf(stderr, "keylen 12..60\n"); return 2; }

    char *value = malloc((size_t)vlen + 1);
    for (int i = 0; i < vlen; i++) value[i] = 'v';
    value[vlen] = '\0';

    int fd = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in sa; memset(&sa, 0, sizeof sa);
    sa.sin_family = AF_INET; sa.sin_port = htons((uint16_t)port);
    sa.sin_addr.s_addr = inet_addr("127.0.0.1");
    if (connect(fd, (struct sockaddr *)&sa, sizeof sa) != 0) { perror("connect"); return 1; }
    int one = 1; setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);

    size_t cap = 1u << 22;
    char *out = malloc(cap), *in = malloc(cap);
    int is_warm  = !strcmp(shape, "warm");
    int is_get   = !strcmp(shape, "get_hit") || !strcmp(shape, "get_miss");
    int is_miss  = !strcmp(shape, "get_miss");
    int is_set   = !strcmp(shape, "set_over") || is_warm;
    int is_mixed = !strcmp(shape, "mixed11") || !strcmp(shape, "mixed11x");
    int mixed_disjoint = !strcmp(shape, "mixed11x");
    if (!is_get && !is_set && !is_mixed) { fprintf(stderr, "bad shape\n"); return 2; }
    if (is_warm) { ops = ring; pipeline = 64; }

    long done = 0; unsigned k = 0; long replies_expected = 0;
    double t0 = now_s();
    while (done < ops) {
        int batch = (int)(ops - done); if (batch > pipeline) batch = pipeline;
        size_t n = 0;
        long need_lines = 0;
        for (int b = 0; b < batch; b++, done++) {
            int set = is_set || (is_mixed && (done & 1));
            make_key(keybuf, keylen,
                     (k + (unsigned)(mixed_disjoint && set ? ring / 2 : 0)) % ring, is_miss);
            if (!is_mixed || (done & 1)) k++;          // mixed: GET then SET on the same key
            if (set) {
                n += (size_t)snprintf(out + n, cap - n,
                        "*3\r\n$3\r\nSET\r\n$%d\r\n%s\r\n$%d\r\n%s\r\n", keylen, keybuf, vlen, value);
                need_lines += 1;                       // +OK
            } else {
                n += (size_t)snprintf(out + n, cap - n,
                        "*2\r\n$3\r\nGET\r\n$%d\r\n%s\r\n", keylen, keybuf);
                need_lines += is_miss ? 1 : 2;         // $-1 | $len + payload
            }
        }
        size_t sent = 0;
        while (sent < n) {
            ssize_t w = write(fd, out + sent, n - sent);
            if (w <= 0) { perror("write"); return 1; }
            sent += (size_t)w;
        }
        replies_expected += batch;
        // Read until this batch's replies have all arrived: count terminating CRLFs of top-level
        // replies is fragile, so instead track bytes of a known-shape reply stream by scanning
        // for the exact number of '\n' that a batch produces (every RESP line ends in one).
        long got = 0;
        while (got < need_lines) {
            ssize_t r = read(fd, in, cap);
            if (r <= 0) { perror("read"); return 1; }
            for (ssize_t i = 0; i < r; i++) if (in[i] == '\n') got++;
        }
        if (got != need_lines) { fprintf(stderr, "reply framing drift %ld/%ld\n", got, need_lines); return 1; }
    }
    double dt = now_s() - t0;
    fprintf(stdout, "%ld %.4f %.0f\n", done, dt, dt > 0 ? (double)done / dt : 0.0);
    close(fd);
    return 0;
}
