// Deterministic RESP replay driver for the read-local interleave lane.
//
// One request stream, two connection layouts. Both arms emit the BYTE-IDENTICAL sequence of
// commands over the identical key sequence at the identical delivered read fraction; the only
// difference is whether reads and writes share one socket ("mix") or use two ("sep"). That is
// exactly the box comparison this lane exists to close.
//
//   replay <port> <shape> <keylen> <ops> <pipeline> <readpct> [valuelen] [keyring]
//
// shapes: mix   interleaved: reads and writes on ONE connection
//         sep   separated:   reads on connection A, writes on connection B
//         warm  populate every key of the ring (not measured)
//
// The read/write decision is error-diffused (Bresenham), so the reads are spread as evenly as the
// fraction allows and consecutive-write runs stay at their minimum: the cost under study is binary
// in "does this connection carry writes at all", not in run length (measured, see the lane brief).
// Read keys come from the LOW half of the ring, write keys from the HIGH half, so the two key sets
// are disjoint and a correct server serves every read locally.
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <stdint.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <time.h>

static void make_key(char *out, int keylen, unsigned i) {
    int n = snprintf(out, 64, "k%010u", i);
    for (; n < keylen; n++) out[n] = 'a' + (char)((i + (unsigned)n) % 26);
    out[keylen] = '\0';
}

static double now_s(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + 1e-9 * (double)t.tv_nsec;
}

static int dial(int port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in sa; memset(&sa, 0, sizeof sa);
    sa.sin_family = AF_INET; sa.sin_port = htons((uint16_t)port);
    sa.sin_addr.s_addr = inet_addr("127.0.0.1");
    if (connect(fd, (struct sockaddr *)&sa, sizeof sa) != 0) { perror("connect"); exit(1); }
    int one = 1; setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    return fd;
}

static size_t cap;
static char *inbuf;

// Drain until `need` reply lines have arrived on fd. Every RESP line this workload can produce
// ends in '\n', so counting newlines frames the batch exactly.
static void drain_lines(int fd, long need) {
    long got = 0;
    while (got < need) {
        ssize_t r = read(fd, inbuf, cap);
        if (r <= 0) { perror("read"); exit(1); }
        for (ssize_t i = 0; i < r; i++) if (inbuf[i] == '\n') got++;
    }
}

static void flush_out(int fd, const char *buf, size_t n) {
    size_t sent = 0;
    while (sent < n) {
        ssize_t w = write(fd, buf + sent, n - sent);
        if (w <= 0) { perror("write"); exit(1); }
        sent += (size_t)w;
    }
}

int main(int argc, char **argv) {
    if (argc < 7) {
        fprintf(stderr, "usage: replay port shape keylen ops pipeline readpct [vlen] [ring]\n");
        return 2;
    }
    int port = atoi(argv[1]);
    const char *shape = argv[2];
    int keylen = atoi(argv[3]);
    long ops = atol(argv[4]);
    int pipeline = atoi(argv[5]);
    int readpct = atoi(argv[6]);
    int vlen = argc > 7 ? atoi(argv[7]) : 32;
    unsigned ring = argc > 8 ? (unsigned)atoi(argv[8]) : 4096;
    if (keylen < 12 || keylen > 60) { fprintf(stderr, "keylen 12..60\n"); return 2; }
    if (readpct < 0 || readpct > 100) { fprintf(stderr, "readpct 0..100\n"); return 2; }
    if (ring < 4 || (ring & 1)) { fprintf(stderr, "ring even and >=4\n"); return 2; }

    char *value = malloc((size_t)vlen + 1);
    for (int i = 0; i < vlen; i++) value[i] = 'v';
    value[vlen] = '\0';

    int is_warm = !strcmp(shape, "warm");
    int is_sep  = !strcmp(shape, "sep");
    int is_mix  = !strcmp(shape, "mix");
    if (!is_warm && !is_sep && !is_mix) { fprintf(stderr, "bad shape\n"); return 2; }

    cap = 1u << 22;
    inbuf = malloc(cap);
    char *out_r = malloc(cap), *out_w = malloc(cap);
    char keybuf[64];

    int fd_r = dial(port);
    int fd_w = is_sep ? dial(port) : fd_r;

    if (is_warm) {
        // Populate the whole ring over one connection, 64 deep.
        for (unsigned i = 0; i < ring; ) {
            size_t n = 0; long lines = 0; int b = 0;
            for (; b < 64 && i < ring; b++, i++) {
                make_key(keybuf, keylen, i);
                n += (size_t)snprintf(out_w + n, cap - n,
                        "*3\r\n$3\r\nSET\r\n$%d\r\n%s\r\n$%d\r\n%s\r\n",
                        keylen, keybuf, vlen, value);
                lines++;
            }
            flush_out(fd_w, out_w, n);
            drain_lines(fd_w, lines);
        }
        close(fd_r);
        printf("warmed %u\n", ring);
        return 0;
    }

    long done = 0;
    unsigned kr = 0, kw = 0;
    long acc = 0;                       // Bresenham accumulator for the read fraction
    long reads = 0, writes = 0;
    double t0 = now_s();
    while (done < ops) {
        int batch = (int)(ops - done); if (batch > pipeline) batch = pipeline;
        size_t nr = 0, nw = 0;
        long lines_r = 0, lines_w = 0;
        for (int b = 0; b < batch; b++, done++) {
            acc += readpct;
            int is_read = 0;
            if (acc >= 100) { acc -= 100; is_read = 1; }
            if (is_read) {
                make_key(keybuf, keylen, kr % (ring / 2));
                kr++;
                // mix: one stream buffer (out_r) carries both kinds in emission order.
                nr += (size_t)snprintf(out_r + nr, cap - nr,
                        "*2\r\n$3\r\nGET\r\n$%d\r\n%s\r\n", keylen, keybuf);
                lines_r += 2;                       // $len + payload
                reads++;
            } else {
                make_key(keybuf, keylen, ring / 2 + (kw % (ring / 2)));
                kw++;
                if (is_sep) {
                    nw += (size_t)snprintf(out_w + nw, cap - nw,
                            "*3\r\n$3\r\nSET\r\n$%d\r\n%s\r\n$%d\r\n%s\r\n",
                            keylen, keybuf, vlen, value);
                    lines_w += 1;                   // +OK
                } else {
                    nr += (size_t)snprintf(out_r + nr, cap - nr,
                            "*3\r\n$3\r\nSET\r\n$%d\r\n%s\r\n$%d\r\n%s\r\n",
                            keylen, keybuf, vlen, value);
                    lines_r += 1;                   // +OK
                }
                writes++;
            }
        }
        if (is_sep) {
            if (nw) flush_out(fd_w, out_w, nw);
            if (nr) flush_out(fd_r, out_r, nr);
            if (lines_w) drain_lines(fd_w, lines_w);
            if (lines_r) drain_lines(fd_r, lines_r);
        } else {
            if (nr) flush_out(fd_r, out_r, nr);
            if (lines_r) drain_lines(fd_r, lines_r);
        }
    }
    double dt = now_s() - t0;
    fprintf(stdout, "%ld %.4f %.0f reads=%ld writes=%ld\n",
            done, dt, dt > 0 ? (double)done / dt : 0.0, reads, writes);
    close(fd_r);
    if (is_sep) close(fd_w);
    return 0;
}
