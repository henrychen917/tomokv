/*
 * redis-correctness-test.c
 *
 * Correctness tester for a custom Redis-compatible server.
 * Tests GET and SET only.
 *
 * Design:
 *   - 100 clients, each owning 10 keys  ->  1000 keys total
 *     key format: "client_<C>_key_<K>"
 *   - 2 POSIX threads split the 100 clients 50/50
 *   - Each client:
 *       1. SET all 10 keys to unique values
 *       2. GET all 10 keys and verify exact match
 *       3. SET all 10 keys to updated values
 *       4. GET all 10 keys and verify updated values
 *       5. GET a key that was never set  ->  expect NIL
 *
 * Build:
 *   # Ubuntu/Debian: sudo apt install libhiredis-dev
 *   gcc -O2 -Wall -pthread -o redis-correctness-test redis-correctness-test.c \
 *       -lhiredis
 *
 * Usage:
 *   ./redis-correctness-test [host] [port]
 *   ./redis-correctness-test 127.0.0.1 6379
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <pthread.h>
#include <hiredis/hiredis.h>

#define NUM_CLIENTS      1000
#define KEYS_PER_CLIENT   100
#define NUM_THREADS         5

static pthread_mutex_t stats_mutex = PTHREAD_MUTEX_INITIALIZER;
static int total_checks   = 0;
static int total_failures = 0;

static void record_result(int ok) {
    pthread_mutex_lock(&stats_mutex);
    total_checks++;
    if (!ok) total_failures++;
    pthread_mutex_unlock(&stats_mutex);
}

static void fail(const char *fmt, ...) {
    va_list ap;
    pthread_mutex_lock(&stats_mutex);
    total_checks++;
    total_failures++;
    fprintf(stderr, "[FAIL] ");
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fprintf(stderr, "\n");
    pthread_mutex_unlock(&stats_mutex);
}

static redisReply *do_cmd(redisContext *c, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    redisReply *r = redisvCommand(c, fmt, ap);
    va_end(ap);
    if (r == NULL) {
        fprintf(stderr, "FATAL: connection lost: %s\n", c->errstr);
        exit(1);
    }
    return r;
}

static void make_key(char *buf, size_t sz, int cid, int k) {
    snprintf(buf, sz, "client_%d_key_%d", cid, k);
}

static void make_val(char *buf, size_t sz, int cid, int k, int round) {
    snprintf(buf, sz, "val_c%d_k%d_r%d", cid, k, round);
}

static void run_client(redisContext *ctx, int cid) {
    char key[64], val[64], expected[64];
    redisReply *r;

    /* round 1: SET then GET */
    for (int k = 0; k < KEYS_PER_CLIENT; k++) {
        make_key(key, sizeof(key), cid, k);
        make_val(val, sizeof(val), cid, k, 1);
        r = do_cmd(ctx, "SET %s %s", key, val);
        if (r->type != REDIS_REPLY_STATUS || strcmp(r->str, "OK") != 0)
            fail("client %d key %d round 1 SET: got \"%s\"", cid, k,
                 r->type == REDIS_REPLY_STATUS ? r->str : "non-status");
        else
            record_result(1);
        freeReplyObject(r);
    }

    for (int k = 0; k < KEYS_PER_CLIENT; k++) {
        make_key(key, sizeof(key), cid, k);
        make_val(expected, sizeof(expected), cid, k, 1);
        r = do_cmd(ctx, "GET %s", key);
        if (r->type != REDIS_REPLY_STRING)
            fail("client %d key %d round 1 GET: wrong type %d", cid, k, r->type);
        else if (strcmp(r->str, expected) != 0)
            fail("client %d key %d round 1 GET: expected \"%s\" got \"%s\"",
                 cid, k, expected, r->str);
        else
            record_result(1);
        freeReplyObject(r);
    }

    /* round 2: overwrite, verify new values */
    for (int k = 0; k < KEYS_PER_CLIENT; k++) {
        make_key(key, sizeof(key), cid, k);
        make_val(val, sizeof(val), cid, k, 2);
        r = do_cmd(ctx, "SET %s %s", key, val);
        if (r->type != REDIS_REPLY_STATUS || strcmp(r->str, "OK") != 0)
            fail("client %d key %d round 2 SET: got \"%s\"", cid, k,
                 r->type == REDIS_REPLY_STATUS ? r->str : "non-status");
        else
            record_result(1);
        freeReplyObject(r);
    }

    for (int k = 0; k < KEYS_PER_CLIENT; k++) {
        make_key(key, sizeof(key), cid, k);
        make_val(expected, sizeof(expected), cid, k, 2);
        r = do_cmd(ctx, "GET %s", key);
        if (r->type != REDIS_REPLY_STRING)
            fail("client %d key %d round 2 GET: wrong type %d", cid, k, r->type);
        else if (strcmp(r->str, expected) != 0)
            fail("client %d key %d round 2 GET: expected \"%s\" got \"%s\"",
                 cid, k, expected, r->str);
        else
            record_result(1);
        freeReplyObject(r);
    }

    /* round 3: interleaved SET and GET
     * For each key k: SET then immediately GET and verify before moving on.
     * Catches bugs where a write is not visible to the next read on the
     * same connection (buffering, ordering, or state issues). */
    for (int k = 0; k < KEYS_PER_CLIENT; k++) {
        make_key(key, sizeof(key), cid, k);
        make_val(val, sizeof(val), cid, k, 3);

        r = do_cmd(ctx, "SET %s %s", key, val);
        if (r->type != REDIS_REPLY_STATUS || strcmp(r->str, "OK") != 0)
            fail("client %d key %d interleaved SET: got \"%s\"", cid, k,
                 r->type == REDIS_REPLY_STATUS ? r->str : "non-status");
        else
            record_result(1);
        freeReplyObject(r);

        r = do_cmd(ctx, "GET %s", key);
        if (r->type != REDIS_REPLY_STRING)
            fail("client %d key %d interleaved GET: wrong type %d", cid, k, r->type);
        else if (strcmp(r->str, val) != 0)
            fail("client %d key %d interleaved GET: expected \"%s\" got \"%s\"",
                 cid, k, val, r->str);
        else
            record_result(1);
        freeReplyObject(r);
    }

    /* GET a key that was never set -> must return NIL */
    snprintf(key, sizeof(key), "client_%d_never_set", cid);
    r = do_cmd(ctx, "GET %s", key);
    if (r->type != REDIS_REPLY_NIL)
        fail("client %d: GET non-existent key expected NIL got type %d", cid, r->type);
    else
        record_result(1);
    freeReplyObject(r);
}

typedef struct {
    int  thread_id;
    int  client_start;
    int  client_end;
    char host[256];
    int  port;
} ThreadArgs;

static void *thread_func(void *arg) {
    ThreadArgs *ta = (ThreadArgs *)arg;
    for (int cid = ta->client_start; cid < ta->client_end; cid++) {
        redisContext *ctx = redisConnect(ta->host, ta->port);
        if (ctx == NULL || ctx->err) {
            fprintf(stderr, "Thread %d: connect failed for client %d: %s\n",
                    ta->thread_id, cid, ctx ? ctx->errstr : "alloc failure");
            exit(1);
        }
        run_client(ctx, cid);
        redisFree(ctx);
    }
    return NULL;
}

int main(int argc, char **argv) {
    const char *host = argc >= 2 ? argv[1] : "127.0.0.1";
    int         port = argc >= 3 ? atoi(argv[2]) : 6379;

    printf("redis-correctness-test  (GET/SET only)\n");
    printf("  target  : %s:%d\n", host, port);
    printf("  clients : %d   keys/client: %d   total keys: %d\n",
           NUM_CLIENTS, KEYS_PER_CLIENT, NUM_CLIENTS * KEYS_PER_CLIENT);
    printf("  threads : %d\n\n", NUM_THREADS);

    // {
    //     redisContext *c = redisConnect(host, port);
    //     if (!c || c->err) { fprintf(stderr, "Cannot connect\n"); return 1; }
    //     redisReply *r = redisCommand(c, "FLUSHDB");
    //     if (!r || r->type == REDIS_REPLY_ERROR) {
    //         fprintf(stderr, "FLUSHDB failed: %s\n", r ? r->str : "(null)");
    //         return 1;
    //     }
    //     printf("FLUSHDB OK — starting tests...\n\n");
    //     freeReplyObject(r);
    //     redisFree(c);
    // }

    pthread_t  threads[NUM_THREADS];
    ThreadArgs targs[NUM_THREADS];
    int per = NUM_CLIENTS / NUM_THREADS;

    for (int t = 0; t < NUM_THREADS; t++) {
        targs[t].thread_id    = t;
        targs[t].client_start = t * per;
        targs[t].client_end   = (t == NUM_THREADS - 1) ? NUM_CLIENTS : (t + 1) * per;
        strncpy(targs[t].host, host, sizeof(targs[t].host) - 1);
        targs[t].host[sizeof(targs[t].host) - 1] = '\0';
        targs[t].port = port;
        if (pthread_create(&threads[t], NULL, thread_func, &targs[t]) != 0) {
            perror("pthread_create"); return 1;
        }
    }

    for (int t = 0; t < NUM_THREADS; t++)
        pthread_join(threads[t], NULL);

    printf("\n═══════════════════════════════════════\n");
    printf("  Results\n");
    printf("  Total checks : %d\n", total_checks);
    printf("  Passed       : %d\n", total_checks - total_failures);
    printf("  Failed       : %d\n", total_failures);
    printf("  Pass rate    : %.2f%%\n",
           total_checks > 0 ? 100.0*(total_checks-total_failures)/total_checks : 0.0);
    printf("═══════════════════════════════════════\n");

    return total_failures > 0 ? 1 : 0;
}
