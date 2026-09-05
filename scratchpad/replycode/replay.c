// Deterministic pipelined replay client. Sends a fixed, pre-built command stream at a fixed
// pipeline depth and drains every reply byte. The op count is EXACT (it is the replay length),
// so instructions/op needs no rate estimate.
//
// usage: replay <port> <cell> <keylen> <nops> [seedops]
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <errno.h>

static char* bp;
static void raw(const char* s, int n){ memcpy(bp, s, n); bp += n; }
static void hdr(char c, long v){ bp += sprintf(bp, "%c%ld\r\n", c, v); }
static void arg(const char* s, int n){ hdr('$', n); raw(s, n); raw("\r\n", 2); }

static void mkkey(char* k, int keylen, long i){
    // "k:<i>" then padded with 'a' to exactly keylen
    int n = sprintf(k, "k:%ld", i);
    while (n < keylen) k[n++] = 'a';
    k[keylen] = 0;
}

int main(int argc, char** argv){
    if (argc < 5){ fprintf(stderr, "usage: replay port cell keylen nops [seed]\n"); return 2; }
    int port = atoi(argv[1]);
    const char* cell = argv[2];
    int keylen = atoi(argv[3]);
    long nops = atol(argv[4]);
    long seed = argc > 5 ? atol(argv[5]) : 0;
    if (keylen < 6) keylen = 6;

    int fd = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in sa; memset(&sa, 0, sizeof sa);
    sa.sin_family = AF_INET; sa.sin_port = htons(port);
    sa.sin_addr.s_addr = inet_addr("127.0.0.1");
    if (connect(fd, (struct sockaddr*)&sa, sizeof sa) < 0){ perror("connect"); return 1; }
    int one = 1; setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);

    const int DEPTH = (argc > 6) ? atoi(argv[6]) : 32;
    // Build one batch of DEPTH commands, reused. Key varies per op via a rebuild each batch.
    char* buf = malloc(1 << 20);
    char* rbuf = malloc(1 << 20);
    char key[256], val[64];
    memset(val, 'v', sizeof val); val[32] = 0;   // 32-byte value

    long sent = 0, inflight = 0, done = 0, ki = seed;
    int st = 0, need = 0;

    // Non-blocking socket + a credit window. WINDOW is the number of commands allowed to be
    // outstanding; we top it up before every read, so the server always has a queue.
    int fl = fcntl(fd, F_GETFL, 0); fcntl(fd, F_SETFL, fl | O_NONBLOCK);
    const int WINDOW = DEPTH;
    char* wp = buf; char* wend = buf;          // pending unsent bytes

    while (done < nops){
        // 1. refill the window
        while (wp == wend && inflight < WINDOW && sent < nops){
            bp = buf;
            int batch = 0;
            while (batch < DEPTH && inflight + batch < WINDOW && sent < nops){
                mkkey(key, keylen, ki);
                if (!strcmp(cell, "set_over"))      { ki = seed + (ki + 1 - seed) % 1000; hdr('*',3); arg("SET",3); arg(key,keylen); arg(val,32); }
                else if (!strcmp(cell, "set_new"))  { ki++;                                hdr('*',3); arg("SET",3); arg(key,keylen); arg(val,32); }
                else if (!strcmp(cell, "del"))      { ki++;                                hdr('*',2); arg("DEL",3); arg(key,keylen); }
                else if (!strcmp(cell, "get_hit"))  { ki = seed + (ki + 1 - seed) % 1000; hdr('*',2); arg("GET",3); arg(key,keylen); }
                else if (!strcmp(cell, "get_miss")) { ki++;                                hdr('*',2); arg("GET",3); arg(key,keylen); }
                else if (!strcmp(cell, "incr"))     { ki = seed + (ki + 1 - seed) % 1000; hdr('*',2); arg("INCR",4); arg(key,keylen); }
                else if (!strcmp(cell, "mset8"))    {
                    hdr('*', 17); arg("MSET",4);
                    for (int j = 0; j < 8; j++){ mkkey(key, keylen, seed + ((ki + j) % 1000)); arg(key,keylen); arg(val,32); }
                    ki = seed + (ki + 8 - seed) % 1000;
                }
                else if (!strcmp(cell, "del8"))     {
                    hdr('*', 9); arg("DEL",3);
                    for (int j = 0; j < 8; j++){ mkkey(key, keylen, ki + j); arg(key,keylen); }
                    ki += 8;
                }
                else if (!strcmp(cell, "ping"))     {                                      hdr('*',1); arg("PING",4); }
                else if (!strcmp(cell, "mix"))      {   /* 1:1 GET/SET on a hot 1000-key window */
                    long k = seed + ((ki + 1 - seed) % 1000); ki = k;
                    mkkey(key, keylen, k);
                    if (sent & 1) { hdr('*',3); arg("SET",3); arg(key,keylen); arg(val,32); }
                    else          { hdr('*',2); arg("GET",3); arg(key,keylen); }
                }
                else { fprintf(stderr, "unknown cell %s\n", cell); return 2; }
                batch++; sent++;
            }
            wp = buf; wend = bp; inflight += batch;
        }
        // 2. push whatever is pending
        while (wp < wend){
            ssize_t w = write(fd, wp, wend - wp);
            if (w > 0){ wp += w; continue; }
            if (w < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) break;
            perror("write"); return 1;
        }
        // 3. drain replies
        ssize_t r = read(fd, rbuf, 1 << 20);
        if (r < 0){
            if (errno == EAGAIN || errno == EWOULDBLOCK){ if (wp < wend) continue; continue; }
            perror("read"); return 1;
        }
        if (r == 0){ fprintf(stderr, "eof\n"); return 1; }
        for (ssize_t i = 0; i < r; i++){
            char c = rbuf[i];
            if (st == 0){ if (c == '$'){ st = 1; need = 0; } else st = 2; }
            else if (st == 1){ if (c == '\r') st = 3; else if (c == '-') need = -1; else if (need >= 0) need = need * 10 + (c - '0'); }
            else if (st == 3){ if (need < 0){ st = 0; inflight--; done++; } else st = 4; }
            else if (st == 4){ if (need > 0) need--; else if (c == '\n'){ st = 0; inflight--; done++; } }
            else if (st == 2){ if (c == '\n'){ st = 0; inflight--; done++; } }
        }
    }
    printf("done=%ld\n", done);
    close(fd);
    return 0;
}
