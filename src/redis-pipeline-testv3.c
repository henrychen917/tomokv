/*
 * redis-pipeline-testv3.c
 *
 * Multi-threaded, multi-client, pipelined correctness tester covering
 * every command class that bench-workers.sh exercises. Deterministic
 * by construction: each client owns its own keyspace and never touches
 * another client's keys, so concurrency across threads cannot produce
 * race-dependent outcomes.
 *
 * Architecture:
 *   NUM_CLIENTS            total logical clients, partitioned across
 *                          NUM_THREADS POSIX threads. Each thread
 *                          processes its clients serially — new
 *                          connection per client, run all tests,
 *                          disconnect.
 *   KEYS_PER_CLIENT        per-category key count. Per-client keys are
 *                          prefixed <pid>:c<CID>:<category>:<K> so no
 *                          two clients share a key.
 *   PIPELINE_DEPTH         commands queued before each flush. Default
 *                          15 (one below the server's default ring cap
 *                          of 16 — tests the pipeline at close to its
 *                          architectural limit).
 *
 * Tested command classes (per key, per client):
 *   strings   GET/SET/SETNX, STRLEN, APPEND
 *   counters  SET/INCR/INCRBY/DECR/DECRBY/GET (numeric consistency)
 *   bitmap    SETBIT/GETBIT/BITCOUNT (two bits per key, bit K and bit K+128)
 *   hash      HSET/HGET/HLEN/HEXISTS/HSETNX/HDEL
 *   list      RPUSH/LLEN/LINDEX/LPOP/RPOP
 *   set       SADD/SCARD/SISMEMBER/SREM
 *   zset      ZADD/ZCARD/ZSCORE/ZRANK/ZREVRANK/ZINCRBY/ZREM
 *   misc      SET/TYPE/DEL/GET-nil/TYPE-none/PFADD
 *
 * Total commands per client: ~5400 (54 ops/key × 100 keys).
 * Total checks at default scale: ~5.4 M (54 × 100 × NUM_CLIENTS).
 *
 * Every expected reply is pre-computed from the command sequence.
 * There is no wall-clock, no sleep, no timer-based assertion anywhere.
 *
 * Build:
 *   gcc -O2 -Wall -pthread -o redis-pipeline-testv3 redis-pipeline-testv3.c -lhiredis
 *
 * Usage:
 *   ./redis-pipeline-testv3 [host] [port] [pipeline_depth]
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <pthread.h>
#include <unistd.h>
#include <hiredis/hiredis.h>
#define TEST_DELAY_US 200000   /* 200 ms between tests; set 0 to disable */
/* ── tunables ──────────────────────────────────────────────────────────── */
#define NUM_CLIENTS             100
#define KEYS_PER_CLIENT         100
#define NUM_THREADS               4
#define DEFAULT_PIPELINE_DEPTH   16

/* ── shared state ──────────────────────────────────────────────────────── */
static int pipeline_depth = DEFAULT_PIPELINE_DEPTH;
static pid_t run_pid;

static pthread_mutex_t stats_mutex = PTHREAD_MUTEX_INITIALIZER;
static long total_checks = 0;
static long failed_checks = 0;

/* Fail-fast abort flag. Set on first failure by record_fail; every test
 * function checks it at batch boundaries and returns early. volatile is
 * sufficient — we need eventual visibility (next few cycles) to other
 * threads, not strict ordering. Worst case a thread completes one more
 * batch before noticing, which is fine. */
static volatile int abort_flag = 0;

static void record_ok(void)  { pthread_mutex_lock(&stats_mutex); total_checks++; pthread_mutex_unlock(&stats_mutex); }

static int run_named_test(redisContext *c, int cid, int tid,
                          const char *name,
                          void (*fn)(redisContext *, int)) {
    long before_fail, after_fail;

    pthread_mutex_lock(&stats_mutex);
    before_fail = failed_checks;
    pthread_mutex_unlock(&stats_mutex);

    printf("[thread %d client %d] starting %s\n", tid, cid, name);
    fflush(stdout);

    fn(c, cid);

    pthread_mutex_lock(&stats_mutex);
    after_fail = failed_checks;
    pthread_mutex_unlock(&stats_mutex);

    if (after_fail == before_fail) {
        printf("[thread %d client %d] PASS %s\n", tid, cid, name);
        fflush(stdout);
    } else {
        printf("[thread %d client %d] FAIL %s\n", tid, cid, name);
        fflush(stdout);
        return 0;
    }

    if (TEST_DELAY_US > 0 && !abort_flag) {
        usleep(TEST_DELAY_US);
    }
    return 1;
}


static void record_fail(const char *fmt, ...) {
    pthread_mutex_lock(&stats_mutex);
    total_checks++;
    failed_checks++;
    fprintf(stderr, "  \033[31mFAIL\033[0m  ");
    va_list ap; va_start(ap, fmt); vfprintf(stderr, fmt, ap); va_end(ap);
    fputc('\n', stderr);
    fflush(stderr);
    abort_flag = 1;  /* signal all threads to stop at the next boundary */
    pthread_mutex_unlock(&stats_mutex);
}

/* ── reply checkers ────────────────────────────────────────────────────── */
static void expect_status(redisReply *r, const char *want, const char *tag) {
    if (r && r->type == REDIS_REPLY_STATUS && strcmp(r->str, want) == 0) record_ok();
    else record_fail("%s: want status \"%s\", got type=%d str=\"%s\"",
                     tag, want, r ? r->type : -1, (r && r->str) ? r->str : "(null)");
}
static void expect_int(redisReply *r, long long want, const char *tag) {
    if (r && r->type == REDIS_REPLY_INTEGER && r->integer == want) record_ok();
    else record_fail("%s: want int %lld, got type=%d int=%lld",
                     tag, want, r ? r->type : -1, r ? r->integer : -1);
}
static void expect_str(redisReply *r, const char *want, const char *tag) {
    size_t wlen = strlen(want);
    if (r && r->type == REDIS_REPLY_STRING && r->len == wlen && memcmp(r->str, want, wlen) == 0) record_ok();
    else record_fail("%s: want bulk \"%s\", got type=%d str=\"%.*s\"",
                     tag, want, r ? r->type : -1,
                     r ? (int)r->len : 0, (r && r->str) ? r->str : "");
}
static void expect_nil(redisReply *r, const char *tag) {
    if (r && r->type == REDIS_REPLY_NIL) record_ok();
    else record_fail("%s: want nil, got type=%d", tag, r ? r->type : -1);
}

/* ── pipelined batch helper ────────────────────────────────────────────── */

/* Each test function below follows the same pattern:
 *   total_ops = KEYS_PER_CLIENT × cmds_per_key
 *   for idx in [0, total_ops) step pipeline_depth:
 *     queue   min(pipeline_depth, total_ops - idx) commands;
 *     drain   the same number of replies and verify.
 *
 * This keeps at most `pipeline_depth` commands in flight at any time.
 * The verification phase reconstructs (key_index, cmd_index) from the
 * absolute index — both sides use (idx + i) to agree on what was
 * queued. */

#define MIN(a, b) ((a) < (b) ? (a) : (b))

/* Helper to format this client's key: "<pid>:c<cid>:<cat><K>" */
static void fmt_key(char *buf, size_t n, int cid, const char *cat, int k) {
    snprintf(buf, n, "%d:c%d:%s%d", (int)run_pid, cid, cat, k);
}

/* ── test: strings (7 cmds per key) ────────────────────────────────────── */
static void test_strings(redisContext *c, int cid) {
    const int CPK = 7;
    const int total = KEYS_PER_CLIENT * CPK;
    char key[128], expected[128];

    for (int idx = 0; idx < total; ) {
        if (abort_flag) return;
        int chunk = MIN(pipeline_depth, total - idx);

        /* queue phase */
        for (int i = 0; i < chunk; i++) {
            int k = (idx + i) / CPK;
            int op = (idx + i) % CPK;
            fmt_key(key, sizeof(key), cid, "s", k);
            switch (op) {
                case 0: redisAppendCommand(c, "SET %s hello%d", key, k); break;
                case 1: redisAppendCommand(c, "GET %s", key); break;
                case 2: redisAppendCommand(c, "STRLEN %s", key); break;
                case 3: redisAppendCommand(c, "APPEND %s world", key); break;
                case 4: redisAppendCommand(c, "GET %s", key); break;
                case 5: redisAppendCommand(c, "SETNX %s override", key); break;
                case 6: redisAppendCommand(c, "GET %s", key); break;
            }
        }

        /* drain phase */
        for (int i = 0; i < chunk; i++) {
            int k = (idx + i) / CPK;
            int op = (idx + i) % CPK;
            redisReply *r = NULL;
            if (redisGetReply(c, (void **)&r) != REDIS_OK || !r) {
                record_fail("strings drain fd_err=%s", c->errstr);
                continue;
            }
            int hello_len = 5 + snprintf(NULL, 0, "%d", k);  /* "hello" + digits(k) */
            switch (op) {
                case 0: expect_status(r, "OK", "strings SET"); break;
                case 1: snprintf(expected, sizeof(expected), "hello%d", k);
                        expect_str(r, expected, "strings GET1"); break;
                case 2: expect_int(r, hello_len, "strings STRLEN"); break;
                case 3: expect_int(r, hello_len + 5, "strings APPEND"); break;
                case 4: snprintf(expected, sizeof(expected), "hello%dworld", k);
                        expect_str(r, expected, "strings GET2"); break;
                case 5: expect_int(r, 0, "strings SETNX (exists)"); break;
                case 6: snprintf(expected, sizeof(expected), "hello%dworld", k);
                        expect_str(r, expected, "strings GET3"); break;
            }
            freeReplyObject(r);
        }
        idx += chunk;
    }
}

/* ── test: counters (6 cmds per key) ──────────────────────────────────── */
static void test_counters(redisContext *c, int cid) {
    const int CPK = 6;
    const int total = KEYS_PER_CLIENT * CPK;
    char key[128];

    for (int idx = 0; idx < total; ) {
        if (abort_flag) return;
        int chunk = MIN(pipeline_depth, total - idx);
        for (int i = 0; i < chunk; i++) {
            int k = (idx + i) / CPK;
            int op = (idx + i) % CPK;
            fmt_key(key, sizeof(key), cid, "n", k);
            switch (op) {
                case 0: redisAppendCommand(c, "SET %s 10", key); break;
                case 1: redisAppendCommand(c, "INCR %s", key); break;
                case 2: redisAppendCommand(c, "INCRBY %s 5", key); break;
                case 3: redisAppendCommand(c, "DECR %s", key); break;
                case 4: redisAppendCommand(c, "DECRBY %s 3", key); break;
                case 5: redisAppendCommand(c, "GET %s", key); break;
            }
        }
        for (int i = 0; i < chunk; i++) {
            int op = (idx + i) % CPK;
            redisReply *r = NULL;
            if (redisGetReply(c, (void **)&r) != REDIS_OK || !r) {
                record_fail("counters drain err=%s", c->errstr); continue;
            }
            switch (op) {
                case 0: expect_status(r, "OK", "counters SET"); break;
                case 1: expect_int(r, 11, "counters INCR"); break;
                case 2: expect_int(r, 16, "counters INCRBY"); break;
                case 3: expect_int(r, 15, "counters DECR"); break;
                case 4: expect_int(r, 12, "counters DECRBY"); break;
                case 5: expect_str(r, "12", "counters GET"); break;
            }
            freeReplyObject(r);
        }
        idx += chunk;
    }
}

/* ── test: bitmap (6 cmds per key) ────────────────────────────────────── */
/* For each key K we set bits at offset K and (K+128), then verify both are
 * 1 and a third bit at (K+64) is 0. BITCOUNT = 2. Because offsets differ
 * per key, we never have collisions. */
static void test_bitmap(redisContext *c, int cid) {
    const int CPK = 6;
    const int total = KEYS_PER_CLIENT * CPK;
    char key[128];

    for (int idx = 0; idx < total; ) {
        if (abort_flag) return;
        int chunk = MIN(pipeline_depth, total - idx);
        for (int i = 0; i < chunk; i++) {
            int k = (idx + i) / CPK;
            int op = (idx + i) % CPK;
            fmt_key(key, sizeof(key), cid, "b", k);
            int b_set1 = k;
            int b_set2 = k + 128;
            int b_zero = k + 64;
            switch (op) {
                case 0: redisAppendCommand(c, "SETBIT %s %d 1", key, b_set1); break;
                case 1: redisAppendCommand(c, "SETBIT %s %d 1", key, b_set2); break;
                case 2: redisAppendCommand(c, "GETBIT %s %d", key, b_set1); break;
                case 3: redisAppendCommand(c, "GETBIT %s %d", key, b_set2); break;
                case 4: redisAppendCommand(c, "GETBIT %s %d", key, b_zero); break;
                case 5: redisAppendCommand(c, "BITCOUNT %s", key); break;
            }
        }
        for (int i = 0; i < chunk; i++) {
            int op = (idx + i) % CPK;
            redisReply *r = NULL;
            if (redisGetReply(c, (void **)&r) != REDIS_OK || !r) {
                record_fail("bitmap drain err=%s", c->errstr); continue;
            }
            switch (op) {
                case 0: expect_int(r, 0, "bitmap SETBIT1 (prior 0)"); break;
                case 1: expect_int(r, 0, "bitmap SETBIT2 (prior 0)"); break;
                case 2: expect_int(r, 1, "bitmap GETBIT set1"); break;
                case 3: expect_int(r, 1, "bitmap GETBIT set2"); break;
                case 4: expect_int(r, 0, "bitmap GETBIT zero"); break;
                case 5: expect_int(r, 2, "bitmap BITCOUNT"); break;
            }
            freeReplyObject(r);
        }
        idx += chunk;
    }
}

/* ── test: hash (8 cmds per key) ──────────────────────────────────────── */
static void test_hash(redisContext *c, int cid) {
    const int CPK = 8;
    const int total = KEYS_PER_CLIENT * CPK;
    char key[128], expected[128];

    for (int idx = 0; idx < total; ) {
        if (abort_flag) return;
        int chunk = MIN(pipeline_depth, total - idx);
        for (int i = 0; i < chunk; i++) {
            int k = (idx + i) / CPK;
            int op = (idx + i) % CPK;
            fmt_key(key, sizeof(key), cid, "h", k);
            switch (op) {
                case 0: redisAppendCommand(c, "HSET %s f1 a%d f2 b%d", key, k, k); break;
                case 1: redisAppendCommand(c, "HGET %s f1", key); break;
                case 2: redisAppendCommand(c, "HLEN %s", key); break;
                case 3: redisAppendCommand(c, "HEXISTS %s f1", key); break;
                case 4: redisAppendCommand(c, "HSETNX %s f1 override", key); break;
                case 5: redisAppendCommand(c, "HSETNX %s f3 c%d", key, k); break;
                case 6: redisAppendCommand(c, "HDEL %s f1 missing", key); break;
                case 7: redisAppendCommand(c, "HLEN %s", key); break;
            }
        }
        for (int i = 0; i < chunk; i++) {
            int k = (idx + i) / CPK;
            int op = (idx + i) % CPK;
            redisReply *r = NULL;
            if (redisGetReply(c, (void **)&r) != REDIS_OK || !r) {
                record_fail("hash drain err=%s", c->errstr); continue;
            }
            switch (op) {
                case 0: expect_int(r, 2, "hash HSET (2 new)"); break;
                case 1: snprintf(expected, sizeof(expected), "a%d", k);
                        expect_str(r, expected, "hash HGET f1"); break;
                case 2: expect_int(r, 2, "hash HLEN after HSET"); break;
                case 3: expect_int(r, 1, "hash HEXISTS f1"); break;
                case 4: expect_int(r, 0, "hash HSETNX f1 (exists)"); break;
                case 5: expect_int(r, 1, "hash HSETNX f3 (new)"); break;
                case 6: expect_int(r, 1, "hash HDEL (1 of 2)"); break;
                case 7: expect_int(r, 2, "hash HLEN after HDEL"); break;
            }
            freeReplyObject(r);
        }
        idx += chunk;
    }
}

/* ── test: list (7 cmds per key) ──────────────────────────────────────── */
static void test_list(redisContext *c, int cid) {
    const int CPK = 7;
    const int total = KEYS_PER_CLIENT * CPK;
    char key[128], expected[128];

    for (int idx = 0; idx < total; ) {
        if (abort_flag) return;
        int chunk = MIN(pipeline_depth, total - idx);
        for (int i = 0; i < chunk; i++) {
            int k = (idx + i) / CPK;
            int op = (idx + i) % CPK;
            fmt_key(key, sizeof(key), cid, "l", k);
            switch (op) {
                case 0: redisAppendCommand(c, "RPUSH %s a%d b%d c%d", key, k, k, k); break;
                case 1: redisAppendCommand(c, "LLEN %s", key); break;
                case 2: redisAppendCommand(c, "LINDEX %s 0", key); break;
                case 3: redisAppendCommand(c, "LINDEX %s -1", key); break;
                case 4: redisAppendCommand(c, "LPOP %s", key); break;
                case 5: redisAppendCommand(c, "RPOP %s", key); break;
                case 6: redisAppendCommand(c, "LLEN %s", key); break;
            }
        }
        for (int i = 0; i < chunk; i++) {
            int k = (idx + i) / CPK;
            int op = (idx + i) % CPK;
            redisReply *r = NULL;
            if (redisGetReply(c, (void **)&r) != REDIS_OK || !r) {
                record_fail("list drain err=%s", c->errstr); continue;
            }
            switch (op) {
                case 0: expect_int(r, 3, "list RPUSH (3 elems)"); break;
                case 1: expect_int(r, 3, "list LLEN"); break;
                case 2: snprintf(expected, sizeof(expected), "a%d", k);
                        expect_str(r, expected, "list LINDEX 0"); break;
                case 3: snprintf(expected, sizeof(expected), "c%d", k);
                        expect_str(r, expected, "list LINDEX -1"); break;
                case 4: snprintf(expected, sizeof(expected), "a%d", k);
                        expect_str(r, expected, "list LPOP"); break;
                case 5: snprintf(expected, sizeof(expected), "c%d", k);
                        expect_str(r, expected, "list RPOP"); break;
                case 6: expect_int(r, 1, "list LLEN after pops"); break;
            }
            freeReplyObject(r);
        }
        idx += chunk;
    }
}

/* ── test: set (6 cmds per key) ───────────────────────────────────────── */
static void test_set(redisContext *c, int cid) {
    const int CPK = 6;
    const int total = KEYS_PER_CLIENT * CPK;
    char key[128];

    for (int idx = 0; idx < total; ) {
        if (abort_flag) return;
        int chunk = MIN(pipeline_depth, total - idx);
        for (int i = 0; i < chunk; i++) {
            int k = (idx + i) / CPK;
            int op = (idx + i) % CPK;
            fmt_key(key, sizeof(key), cid, "S", k);
            switch (op) {
                case 0: redisAppendCommand(c, "SADD %s a b c", key); break;
                case 1: redisAppendCommand(c, "SADD %s a d", key); break;
                case 2: redisAppendCommand(c, "SCARD %s", key); break;
                case 3: redisAppendCommand(c, "SISMEMBER %s b", key); break;
                case 4: redisAppendCommand(c, "SISMEMBER %s missing", key); break;
                case 5: redisAppendCommand(c, "SREM %s d missing", key); break;
            }
        }
        for (int i = 0; i < chunk; i++) {
            int op = (idx + i) % CPK;
            redisReply *r = NULL;
            if (redisGetReply(c, (void **)&r) != REDIS_OK || !r) {
                record_fail("set drain err=%s", c->errstr); continue;
            }
            switch (op) {
                case 0: expect_int(r, 3, "set SADD 3 new"); break;
                case 1: expect_int(r, 1, "set SADD (a dup, d new)"); break;
                case 2: expect_int(r, 4, "set SCARD"); break;
                case 3: expect_int(r, 1, "set SISMEMBER b"); break;
                case 4: expect_int(r, 0, "set SISMEMBER missing"); break;
                case 5: expect_int(r, 1, "set SREM (1 of 2)"); break;
            }
            freeReplyObject(r);
        }
        idx += chunk;
    }
}

/* ── test: zset (8 cmds per key) ──────────────────────────────────────── */
static void test_zset(redisContext *c, int cid) {
    const int CPK = 8;
    const int total = KEYS_PER_CLIENT * CPK;
    char key[128];

    for (int idx = 0; idx < total; ) {
        if (abort_flag) return;
        int chunk = MIN(pipeline_depth, total - idx);
        for (int i = 0; i < chunk; i++) {
            int k = (idx + i) / CPK;
            int op = (idx + i) % CPK;
            fmt_key(key, sizeof(key), cid, "z", k);
            switch (op) {
                case 0: redisAppendCommand(c, "ZADD %s 1 a 2 b 3 c", key); break;
                case 1: redisAppendCommand(c, "ZCARD %s", key); break;
                case 2: redisAppendCommand(c, "ZSCORE %s b", key); break;
                case 3: redisAppendCommand(c, "ZRANK %s a", key); break;
                case 4: redisAppendCommand(c, "ZREVRANK %s a", key); break;
                case 5: redisAppendCommand(c, "ZINCRBY %s 10 a", key); break;
                case 6: redisAppendCommand(c, "ZSCORE %s a", key); break;
                case 7: redisAppendCommand(c, "ZREM %s b", key); break;
            }
        }
        for (int i = 0; i < chunk; i++) {
            int op = (idx + i) % CPK;
            redisReply *r = NULL;
            if (redisGetReply(c, (void **)&r) != REDIS_OK || !r) {
                record_fail("zset drain err=%s", c->errstr); continue;
            }
            switch (op) {
                case 0: expect_int(r, 3, "zset ZADD 3 new"); break;
                case 1: expect_int(r, 3, "zset ZCARD"); break;
                case 2: expect_str(r, "2", "zset ZSCORE b"); break;
                case 3: expect_int(r, 0, "zset ZRANK a"); break;
                case 4: expect_int(r, 2, "zset ZREVRANK a"); break;
                case 5: expect_str(r, "11", "zset ZINCRBY a +10"); break;
                case 6: expect_str(r, "11", "zset ZSCORE a after ZINCRBY"); break;
                case 7: expect_int(r, 1, "zset ZREM b"); break;
            }
            freeReplyObject(r);
        }
        idx += chunk;
    }
}

/* ── test: pipeline ordering (15 cmds per key, all in one flush) ───────
 *
 * This is the critical correctness test for the fake-client ring's
 * positional ordering invariant. Within a single pipeline batch we
 * issue commands across 7 different sub-keys (s1_K, s2_K, c_K, h_K,
 * z_K, l_K, S_K). Each sub-key hashes independently, so the 15
 * commands in the batch get dispatched across up to 7 different
 * workers, each executing asynchronously.
 *
 * The read-after-write pairs in the batch can only return correct
 * values if:
 *   (a) commands arrive at workers in pipeline order, AND
 *   (b) replies come back to the client in pipeline order.
 *
 * If the ring ever returned replies out of order (e.g., a fast worker's
 * reply was delivered before a slower worker's earlier-positioned
 * reply), hiredis would assign replies to the wrong commands and the
 * assertions here would fail — not occasionally, not under timing
 * pressure, but every single iteration.
 *
 * Same batch every key, so 100 keys per client × 1000 clients =
 * 100,000 independent pipeline batches, each exercising cross-worker
 * ordering on a different set of hash destinations. */
static void test_pipeline_ordering(redisContext *c, int cid) {
    /* enum so CPK is a compile-time constant — required for the
     * `tags[CPK] = { ... }` initializer below. A `const int` here
     * would make tags[] a VLA and C forbids VLA initializers. */
    enum { CPK = 15 };
    char s1[128], s2[128], kc[128], kh[128], kz[128], kl[128], kS[128];

    for (int k = 0; k < KEYS_PER_CLIENT; k++) {
        if (abort_flag) return;
        fmt_key(s1, sizeof(s1), cid, "p:s1:", k);
        fmt_key(s2, sizeof(s2), cid, "p:s2:", k);
        fmt_key(kc, sizeof(kc), cid, "p:c:",  k);
        fmt_key(kh, sizeof(kh), cid, "p:h:",  k);
        fmt_key(kz, sizeof(kz), cid, "p:z:",  k);
        fmt_key(kl, sizeof(kl), cid, "p:l:",  k);
        fmt_key(kS, sizeof(kS), cid, "p:S:",  k);

        /* 15 commands, all queued before first flush. Each read
         * depends on an earlier write in the same batch. */
        redisAppendCommand(c, "SET %s a",      s1);    /* 0 */
        redisAppendCommand(c, "SET %s b",      s2);    /* 1 */
        redisAppendCommand(c, "GET %s",        s1);    /* 2  -> "a" */
        redisAppendCommand(c, "GET %s",        s2);    /* 3  -> "b" */
        redisAppendCommand(c, "INCR %s",       kc);    /* 4  -> 1   */
        redisAppendCommand(c, "INCR %s",       kc);    /* 5  -> 2   */
        redisAppendCommand(c, "GET %s",        kc);    /* 6  -> "2" */
        redisAppendCommand(c, "HSET %s f v",   kh);    /* 7  -> 1   */
        redisAppendCommand(c, "HGET %s f",     kh);    /* 8  -> "v" */
        redisAppendCommand(c, "ZADD %s 5 m",   kz);    /* 9  -> 1   */
        redisAppendCommand(c, "ZSCORE %s m",   kz);    /* 10 -> "5" */
        redisAppendCommand(c, "LPUSH %s x",    kl);    /* 11 -> 1   */
        redisAppendCommand(c, "LLEN %s",       kl);    /* 12 -> 1   */
        redisAppendCommand(c, "SADD %s m",     kS);    /* 13 -> 1   */
        redisAppendCommand(c, "SISMEMBER %s m",kS);    /* 14 -> 1   */

        /* Drain all 15 in order. If the positional ordering invariant
         * holds, every reply lands on its correct position here. If it
         * doesn't, later replies can't compensate — each check is
         * independent and position-locked. */
        redisReply *r = NULL;
        const char *tags[CPK] = {
            "order SET s1", "order SET s2", "order GET s1", "order GET s2",
            "order INCR1", "order INCR2", "order GET c",
            "order HSET", "order HGET",
            "order ZADD", "order ZSCORE",
            "order LPUSH", "order LLEN",
            "order SADD", "order SISMEMBER"
        };
        for (int i = 0; i < CPK; i++) {
            if (redisGetReply(c, (void **)&r) != REDIS_OK || !r) {
                record_fail("ordering drain err=%s", c->errstr);
                continue;
            }
            switch (i) {
                case 0: case 1: expect_status(r, "OK", tags[i]); break;
                case 2: expect_str(r, "a", tags[i]); break;
                case 3: expect_str(r, "b", tags[i]); break;
                case 4: expect_int(r, 1, tags[i]); break;
                case 5: expect_int(r, 2, tags[i]); break;
                case 6: expect_str(r, "2", tags[i]); break;
                case 7: expect_int(r, 1, tags[i]); break;
                case 8: expect_str(r, "v", tags[i]); break;
                case 9: expect_int(r, 1, tags[i]); break;
                case 10: expect_str(r, "5", tags[i]); break;
                case 11: expect_int(r, 1, tags[i]); break;
                case 12: expect_int(r, 1, tags[i]); break;
                case 13: expect_int(r, 1, tags[i]); break;
                case 14: expect_int(r, 1, tags[i]); break;
            }
            freeReplyObject(r);
        }
    }
}

/* ── test: commit-order on single key (sequential writes same key) ─────
 *
 * Canonical "did the server commit in order?" test. For each key K we
 * queue N overwrites followed by a GET, all in one pipeline batch.
 * The GET must return the LAST written value. If any reordering
 * happened — server-side or client-side — we'd see an earlier value
 * in the GET reply. */
#define COMMIT_WRITES_PER_KEY 14  /* 14 SETs + 1 GET = 15, fits pipeline_depth */
static void test_commit_order(redisContext *c, int cid) {
    char key[128];

    for (int k = 0; k < KEYS_PER_CLIENT; k++) {
        if (abort_flag) return;
        fmt_key(key, sizeof(key), cid, "p:co:", k);
        for (int w = 0; w < COMMIT_WRITES_PER_KEY; w++) {
            redisAppendCommand(c, "SET %s ov_%d", key, w);
        }
        redisAppendCommand(c, "GET %s", key);

        /* Drain all N+1 replies in order. */
        for (int w = 0; w < COMMIT_WRITES_PER_KEY; w++) {
            redisReply *r = NULL;
            if (redisGetReply(c, (void **)&r) != REDIS_OK || !r) {
                record_fail("commit SET drain err=%s", c->errstr);
                continue;
            }
            expect_status(r, "OK", "commit SET");
            freeReplyObject(r);
        }
        redisReply *r = NULL;
        if (redisGetReply(c, (void **)&r) != REDIS_OK || !r) {
            record_fail("commit GET drain err=%s", c->errstr);
        } else {
            char expected[64];
            snprintf(expected, sizeof(expected), "ov_%d", COMMIT_WRITES_PER_KEY - 1);
            expect_str(r, expected, "commit GET (last value)");
            freeReplyObject(r);
        }
    }
}

/* ── test: misc (6 cmds per key; SET→TYPE→DEL→GET→TYPE→PFADD) ─────────── */
static void test_misc(redisContext *c, int cid) {
    const int CPK = 6;
    const int total = KEYS_PER_CLIENT * CPK;
    char key[128], pfkey[128];

    for (int idx = 0; idx < total; ) {
        if (abort_flag) return;
        int chunk = MIN(pipeline_depth, total - idx);
        for (int i = 0; i < chunk; i++) {
            int k = (idx + i) / CPK;
            int op = (idx + i) % CPK;
            fmt_key(key, sizeof(key), cid, "m", k);
            fmt_key(pfkey, sizeof(pfkey), cid, "pf", k);
            switch (op) {
                case 0: redisAppendCommand(c, "SET %s value", key); break;
                case 1: redisAppendCommand(c, "TYPE %s", key); break;
                case 2: redisAppendCommand(c, "DEL %s", key); break;
                case 3: redisAppendCommand(c, "GET %s", key); break;
                case 4: redisAppendCommand(c, "TYPE %s", key); break;
                case 5: redisAppendCommand(c, "PFADD %s a b c", pfkey); break;
            }
        }
        for (int i = 0; i < chunk; i++) {
            int op = (idx + i) % CPK;
            redisReply *r = NULL;
            if (redisGetReply(c, (void **)&r) != REDIS_OK || !r) {
                record_fail("misc drain err=%s", c->errstr); continue;
            }
            switch (op) {
                case 0: expect_status(r, "OK", "misc SET"); break;
                case 1: expect_status(r, "string", "misc TYPE string"); break;
                case 2: expect_int(r, 1, "misc DEL (existed)"); break;
                case 3: expect_nil(r, "misc GET after DEL"); break;
                case 4: expect_status(r, "none", "misc TYPE none"); break;
                case 5: expect_int(r, 1, "misc PFADD (state changed)"); break;
            }
            freeReplyObject(r);
        }
        idx += chunk;
    }
}

/* ── thread driver ─────────────────────────────────────────────────────── */
typedef struct {
    int start_cid;
    int end_cid;
    const char *host;
    int port;
    int tid;
} thread_arg_t;

static void *thread_main(void *arg) {
    thread_arg_t *a = arg;
    for (int cid = a->start_cid; cid < a->end_cid; cid++) {
        if (abort_flag) return NULL;

        redisContext *c = redisConnect(a->host, a->port);
        if (!c || c->err) {
            record_fail("thread %d: connect cid=%d failed: %s",
                        a->tid, cid, c ? c->errstr : "alloc");
            if (c) redisFree(c);
            continue;
        }

        if (!run_named_test(c, cid, a->tid, "strings", test_strings))           { redisFree(c); return NULL; }
        if (!run_named_test(c, cid, a->tid, "counters", test_counters))         { redisFree(c); return NULL; }
        if (!run_named_test(c, cid, a->tid, "bitmap", test_bitmap))             { redisFree(c); return NULL; }
        if (!run_named_test(c, cid, a->tid, "hash", test_hash))                 { redisFree(c); return NULL; }
        if (!run_named_test(c, cid, a->tid, "list", test_list))                 { redisFree(c); return NULL; }
        if (!run_named_test(c, cid, a->tid, "set", test_set))                   { redisFree(c); return NULL; }
        if (!run_named_test(c, cid, a->tid, "zset", test_zset))                 { redisFree(c); return NULL; }
        if (!run_named_test(c, cid, a->tid, "misc", test_misc))                 { redisFree(c); return NULL; }
        if (!run_named_test(c, cid, a->tid, "commit-order", test_commit_order)) { redisFree(c); return NULL; }
        if (!run_named_test(c, cid, a->tid, "pipeline-ordering", test_pipeline_ordering)) {
            redisFree(c);
            return NULL;
        }

        redisFree(c);
    }
    return NULL;
}

/* ── entry ─────────────────────────────────────────────────────────────── */
int main(int argc, char **argv) {
    const char *host = (argc > 1) ? argv[1] : "127.0.0.1";
    int port         = (argc > 2) ? atoi(argv[2]) : 6379;
    if (argc > 3) pipeline_depth = atoi(argv[3]);
    if (pipeline_depth <= 0) pipeline_depth = DEFAULT_PIPELINE_DEPTH;

    run_pid = getpid();

    printf("redis-pipeline-testv3\n");
    printf("  target          : %s:%d\n", host, port);
    printf("  clients total   : %d\n", NUM_CLIENTS);
    printf("  threads         : %d\n", NUM_THREADS);
    printf("  keys per client : %d\n", KEYS_PER_CLIENT);
    printf("  pipeline depth  : %d\n", pipeline_depth);
    printf("  key namespace   : %d:c<CID>:<cat>:<K>\n", (int)run_pid);
    printf("  command classes : strings, counters, bitmap, hash, list, set, zset, misc,\n");
    printf("                    pipeline-ordering, commit-order\n");
    printf("\n  (~%ld checks expected at full scale)\n\n",
           (long)(NUM_CLIENTS * KEYS_PER_CLIENT *
                  (7 + 6 + 6 + 8 + 7 + 6 + 8 + 6 + 15 + (COMMIT_WRITES_PER_KEY + 1))));

    pthread_t threads[NUM_THREADS];
    thread_arg_t args[NUM_THREADS];
    int per = NUM_CLIENTS / NUM_THREADS;
    int rem = NUM_CLIENTS % NUM_THREADS;
    int start = 0;
    for (int t = 0; t < NUM_THREADS; t++) {
        int count = per + (t < rem ? 1 : 0);
        args[t].start_cid = start;
        args[t].end_cid   = start + count;
        args[t].host      = host;
        args[t].port      = port;
        args[t].tid       = t;
        start += count;
        if (pthread_create(&threads[t], NULL, thread_main, &args[t]) != 0) {
            fprintf(stderr, "pthread_create failed\n");
            return 2;
        }
    }
    for (int t = 0; t < NUM_THREADS; t++) pthread_join(threads[t], NULL);

    printf("\n═══════════════════════════════════════\n");
    printf("  Results\n");
    printf("  Total checks : %ld\n", total_checks);
    printf("  Passed       : %ld\n", total_checks - failed_checks);
    printf("  Failed       : %ld\n", failed_checks);
    if (abort_flag) {
        printf("  Status       : \033[31mABORTED on first failure\033[0m\n");
    }
    if (total_checks > 0) {
        printf("  Pass rate    : %.4f%%\n",
               100.0 * (double)(total_checks - failed_checks) / (double)total_checks);
    }
    printf("═══════════════════════════════════════\n");

    return failed_checks == 0 ? 0 : 1;
}
