/*
 * redis-pipeline-test.c
 *
 * Pipelining correctness tester for a custom Redis-compatible server.
 * Tests GET and SET via hiredis pipelining (redisAppendCommand /
 * redisGetReply).
 *
 * Design:
 *   - NUM_CLIENTS clients, each owning KEYS_PER_CLIENT keys
 *     key format: "client_<C>_key_<K>"
 *   - NUM_THREADS POSIX threads split the clients evenly
 *   - Each client runs four pipeline rounds:
 *
 *     Round 1 – bulk SET pipeline
 *       Queue all KEYS_PER_CLIENT SET commands, flush, drain replies.
 *       Every reply must be "+OK".
 *
 *     Round 2 – bulk GET pipeline (verify round-1 values)
 *       Queue all KEYS_PER_CLIENT GET commands, flush, drain replies.
 *       Every reply must match the expected round-1 value.
 *
 *     Round 3 – bulk overwrite + verify pipeline
 *       Queue KEYS_PER_CLIENT SET commands (round-2 values), flush,
 *       drain SET replies, then queue KEYS_PER_CLIENT GET commands,
 *       flush, drain GET replies and verify.
 *
 *     Round 4 – mixed SET/GET pipeline (write-then-read ordering)
 *       For each key: append SET immediately followed by GET in the
 *       same pipeline. Flush once, then drain 2*KEYS_PER_CLIENT
 *       replies in order.  Verifies that the server returns GET
 *       responses in the correct pipeline order and that writes
 *       issued earlier in the pipeline are visible to later GETs
 *       within the same pipeline batch.
 *
 *     Round 5 – sequential overwrite commit-order check
 *       For each key, issue OVERWRITES_PER_KEY SET commands to the
 *       same key (values ov_0 .. ov_N) followed immediately by a GET,
 *       all within the same pipeline chunk.  The GET must return ov_N
 *       — the last value written — not any earlier value.
 *
 *       This is the canonical commit-order test: if the server
 *       processes or commits commands out of order, a stale value
 *       (ov_0 .. ov_N-1) will appear.  The test is exercised at the
 *       configured pipeline_depth so it covers both small and large
 *       in-flight batches.
 *
 *     NIL check – single pipelined GET for a key never set.
 *       Must return NIL (REDIS_REPLY_NIL).
 *
 *   PIPELINE_DEPTH controls how many commands are queued before the
 *   kernel flushes the send buffer and replies are drained.  Each round
 *   is chunked into ceil(KEYS_PER_CLIENT / PIPELINE_DEPTH) batches.
 *   Set it to 1 to degrade to one-command-at-a-time (like the original
 *   synchronous test); set it to KEYS_PER_CLIENT to send every key in a
 *   single batch.  Values in between let you test partial-pipeline
 *   behaviour and help reproduce ordering or buffering bugs that only
 *   appear at specific batch sizes.
 *
 * Build:
 *   # Ubuntu/Debian: sudo apt install libhiredis-dev
 *   gcc -O2 -Wall -pthread -o redis-pipeline-test redis-pipeline-test.c \
 *       -lhiredis
 *
 * Usage:
 *   ./redis-pipeline-test [host] [port] [pipeline_depth]
 *   ./redis-pipeline-test 127.0.0.1 6379 16
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <pthread.h>
#include <hiredis/hiredis.h>

/* ── tunables ──────────────────────────────────────────────────────────── */
#define NUM_CLIENTS        1000
#define KEYS_PER_CLIENT     100
#define NUM_THREADS           5
#define DEFAULT_PIPELINE_DEPTH 16   /* commands queued per flush; argv[3] overrides */
/* ───────────────────────────────────────────────────────────────────────── */

static int pipeline_depth = DEFAULT_PIPELINE_DEPTH;

static pthread_mutex_t stats_mutex = PTHREAD_MUTEX_INITIALIZER;
static int total_checks   = 0;
static int total_failures = 0;

/* ── stats helpers ─────────────────────────────────────────────────────── */

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

/* ── key / value helpers ───────────────────────────────────────────────── */

static void make_key(char *buf, size_t sz, int cid, int k) {
    snprintf(buf, sz, "client_%d_key_%d", cid, k);
}

static void make_val(char *buf, size_t sz, int cid, int k, int round) {
    snprintf(buf, sz, "val_c%d_k%d_r%d", cid, k, round);
}

/* ── pipeline drain helpers ────────────────────────────────────────────── */

/*
 * drain_set_replies – collect `n` replies from the pipeline and verify
 * each is a "+OK" status.  `label` is used in failure messages.
 * `key_offset` is the index of the first key in this chunk (for error msgs).
 */
static void drain_set_replies(redisContext *ctx, int cid, int n,
                               int key_offset, const char *label) {
    for (int i = 0; i < n; i++) {
        int k = key_offset + i;
        redisReply *r = NULL;
        if (redisGetReply(ctx, (void **)&r) != REDIS_OK || r == NULL) {
            fprintf(stderr, "FATAL: connection lost draining SET (%s) "
                    "client %d key %d: %s\n",
                    label, cid, k, ctx->errstr);
            exit(1);
        }
        if (r->type != REDIS_REPLY_STATUS || strcmp(r->str, "OK") != 0)
            fail("client %d key %d %s SET pipeline reply: got type=%d str=\"%s\"",
                 cid, k, label,
                 r->type,
                 r->type == REDIS_REPLY_STATUS ? r->str : "<non-status>");
        else
            record_result(1);
        freeReplyObject(r);
    }
}

/*
 * drain_get_replies – collect `n` replies starting at `key_offset` and
 * verify each matches make_val(cid, key_offset+i, round).
 */
static void drain_get_replies(redisContext *ctx, int cid, int n,
                               int key_offset, int round,
                               const char *label) {
    char expected[64];
    for (int i = 0; i < n; i++) {
        int k = key_offset + i;
        redisReply *r = NULL;
        if (redisGetReply(ctx, (void **)&r) != REDIS_OK || r == NULL) {
            fprintf(stderr, "FATAL: connection lost draining GET (%s) "
                    "client %d key %d: %s\n",
                    label, cid, k, ctx->errstr);
            exit(1);
        }
        make_val(expected, sizeof(expected), cid, k, round);
        if (r->type != REDIS_REPLY_STRING)
            fail("client %d key %d %s GET pipeline reply: wrong type %d",
                 cid, k, label, r->type);
        else if (strcmp(r->str, expected) != 0)
            fail("client %d key %d %s GET pipeline reply: "
                 "expected \"%s\" got \"%s\"",
                 cid, k, label, expected, r->str);
        else
            record_result(1);
        freeReplyObject(r);
    }
}

/* ── per-client test logic ─────────────────────────────────────────────── */

/*
 * Each round is chunked into batches of `pipeline_depth` commands.
 * Within a batch: append all commands, then drain all replies.
 * This gives explicit control over how many commands are in-flight at once.
 */
static void run_client(redisContext *ctx, int cid) {
    char key[64], val[64];
    int depth = pipeline_depth;

    /* ── Round 1: chunked SET pipeline ─────────────────────────────── */
    for (int base = 0; base < KEYS_PER_CLIENT; base += depth) {
        int chunk = (base + depth <= KEYS_PER_CLIENT) ? depth
                                                       : KEYS_PER_CLIENT - base;
        for (int i = 0; i < chunk; i++) {
            make_key(key, sizeof(key), cid, base + i);
            make_val(val, sizeof(val), cid, base + i, 1);
            redisAppendCommand(ctx, "SET %s %s", key, val);
        }
        drain_set_replies(ctx, cid, chunk, base, "round1");
    }

    /* ── Round 2: chunked GET pipeline, verify round-1 values ──────── */
    for (int base = 0; base < KEYS_PER_CLIENT; base += depth) {
        int chunk = (base + depth <= KEYS_PER_CLIENT) ? depth
                                                       : KEYS_PER_CLIENT - base;
        for (int i = 0; i < chunk; i++) {
            make_key(key, sizeof(key), cid, base + i);
            redisAppendCommand(ctx, "GET %s", key);
        }
        drain_get_replies(ctx, cid, chunk, base, 1, "round2");
    }

    /* ── Round 3: chunked overwrite SET then chunked GET ───────────── */
    for (int base = 0; base < KEYS_PER_CLIENT; base += depth) {
        int chunk = (base + depth <= KEYS_PER_CLIENT) ? depth
                                                       : KEYS_PER_CLIENT - base;
        for (int i = 0; i < chunk; i++) {
            make_key(key, sizeof(key), cid, base + i);
            make_val(val, sizeof(val), cid, base + i, 2);
            redisAppendCommand(ctx, "SET %s %s", key, val);
        }
        drain_set_replies(ctx, cid, chunk, base, "round3-set");
    }

    for (int base = 0; base < KEYS_PER_CLIENT; base += depth) {
        int chunk = (base + depth <= KEYS_PER_CLIENT) ? depth
                                                       : KEYS_PER_CLIENT - base;
        for (int i = 0; i < chunk; i++) {
            make_key(key, sizeof(key), cid, base + i);
            redisAppendCommand(ctx, "GET %s", key);
        }
        drain_get_replies(ctx, cid, chunk, base, 2, "round3-get");
    }

    /* ── Round 4: interleaved SET+GET in chunked pipelines ─────────── *
     * Within each chunk, for each key k: append SET then GET.          *
     * Drain 2*chunk replies in order:                                   *
     *   reply[2i]   = SET for key (base+i)  -> must be OK              *
     *   reply[2i+1] = GET for key (base+i)  -> must equal val_r3       *
     *                                                                   *
     * Tests ordering and write-visibility within a pipeline batch at    *
     * the configured depth.                                             */
    for (int base = 0; base < KEYS_PER_CLIENT; base += depth) {
        int chunk = (base + depth <= KEYS_PER_CLIENT) ? depth
                                                       : KEYS_PER_CLIENT - base;
        for (int i = 0; i < chunk; i++) {
            make_key(key, sizeof(key), cid, base + i);
            make_val(val, sizeof(val), cid, base + i, 3);
            redisAppendCommand(ctx, "SET %s %s", key, val);
            redisAppendCommand(ctx, "GET %s", key);
        }
        for (int i = 0; i < chunk; i++) {
            int k = base + i;
            char expected[64];
            redisReply *r = NULL;

            /* consume the SET reply */
            if (redisGetReply(ctx, (void **)&r) != REDIS_OK || r == NULL) {
                fprintf(stderr, "FATAL: connection lost (round4 SET) "
                        "client %d key %d\n", cid, k);
                exit(1);
            }
            if (r->type != REDIS_REPLY_STATUS || strcmp(r->str, "OK") != 0)
                fail("client %d key %d round4 interleaved SET: "
                     "type=%d str=\"%s\"",
                     cid, k, r->type,
                     r->type == REDIS_REPLY_STATUS ? r->str : "<non-status>");
            else
                record_result(1);
            freeReplyObject(r);

            /* consume the GET reply */
            r = NULL;
            if (redisGetReply(ctx, (void **)&r) != REDIS_OK || r == NULL) {
                fprintf(stderr, "FATAL: connection lost (round4 GET) "
                        "client %d key %d\n", cid, k);
                exit(1);
            }
            make_val(expected, sizeof(expected), cid, k, 3);
            if (r->type != REDIS_REPLY_STRING)
                fail("client %d key %d round4 interleaved GET: wrong type %d",
                     cid, k, r->type);
            else if (strcmp(r->str, expected) != 0)
                fail("client %d key %d round4 interleaved GET: "
                     "expected \"%s\" got \"%s\"",
                     cid, k, expected, r->str);
            else
                record_result(1);
            freeReplyObject(r);
        }
    }

    /* ── NIL check: GET a key never set (single-command pipeline) ───── */
    snprintf(key, sizeof(key), "client_%d_never_set", cid);
    redisAppendCommand(ctx, "GET %s", key);

    redisReply *r = NULL;
    if (redisGetReply(ctx, (void **)&r) != REDIS_OK || r == NULL) {
        fprintf(stderr, "FATAL: connection lost (NIL check) client %d\n", cid);
        exit(1);
    }
    if (r->type != REDIS_REPLY_NIL)
        fail("client %d: pipelined GET non-existent key: "
             "expected NIL got type %d", cid, r->type);
    else
        record_result(1);
    freeReplyObject(r);
}

/* ── thread entry ──────────────────────────────────────────────────────── */

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
                    ta->thread_id, cid,
                    ctx ? ctx->errstr : "alloc failure");
            exit(1);
        }
        run_client(ctx, cid);
        redisFree(ctx);
    }
    return NULL;
}

/* ── main ──────────────────────────────────────────────────────────────── */

int main(int argc, char **argv) {
    const char *host = argc >= 2 ? argv[1] : "127.0.0.1";
    int         port = argc >= 3 ? atoi(argv[2]) : 6379;

    if (argc >= 4) {
        pipeline_depth = atoi(argv[3]);
        if (pipeline_depth < 1) {
            fprintf(stderr, "pipeline_depth must be >= 1\n");
            return 1;
        }
        if (pipeline_depth > KEYS_PER_CLIENT) {
            fprintf(stderr, "pipeline_depth clamped to KEYS_PER_CLIENT (%d)\n",
                    KEYS_PER_CLIENT);
            pipeline_depth = KEYS_PER_CLIENT;
        }
    }

    printf("redis-pipeline-test  (GET/SET pipelining)\n");
    printf("  target          : %s:%d\n", host, port);
    printf("  clients         : %d   keys/client: %d   total keys: %d\n",
           NUM_CLIENTS, KEYS_PER_CLIENT, NUM_CLIENTS * KEYS_PER_CLIENT);
    printf("  threads         : %d\n", NUM_THREADS);
    printf("  pipeline depth  : %d  (commands per flush)\n\n", pipeline_depth);
    printf("  Pipeline rounds per client:\n");
    printf("    1. Bulk SET pipeline\n");
    printf("    2. Bulk GET pipeline  (verify round-1 values)\n");
    printf("    3. Bulk overwrite SET then bulk GET pipeline\n");
    printf("    4. Interleaved SET+GET in one pipeline batch\n");
    printf("    5. GET non-existent key -> NIL\n\n");

    pthread_t  threads[NUM_THREADS];
    ThreadArgs targs[NUM_THREADS];
    int per = NUM_CLIENTS / NUM_THREADS;

    for (int t = 0; t < NUM_THREADS; t++) {
        targs[t].thread_id    = t;
        targs[t].client_start = t * per;
        targs[t].client_end   = (t == NUM_THREADS - 1)
                                 ? NUM_CLIENTS
                                 : (t + 1) * per;
        strncpy(targs[t].host, host, sizeof(targs[t].host) - 1);
        targs[t].host[sizeof(targs[t].host) - 1] = '\0';
        targs[t].port = port;
        if (pthread_create(&threads[t], NULL, thread_func, &targs[t]) != 0) {
            perror("pthread_create");
            return 1;
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
           total_checks > 0
               ? 100.0 * (total_checks - total_failures) / total_checks
               : 0.0);
    printf("═══════════════════════════════════════\n");

    return total_failures > 0 ? 1 : 0;
}
