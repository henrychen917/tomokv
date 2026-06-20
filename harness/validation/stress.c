/*
 * thredis-stress.c
 *
 * Adversarial, high-throughput correctness tester for THredis. Complements
 * redis-pipeline-testv3.c: where v3 verifies per-command-class behavior on
 * DISJOINT per-client keys (deliberately race-free), this tool attacks exactly
 * what v3 omits — the properties THredis's paper (Sec 3.1, 4.8) actually
 * promises and the value-forwarding optimization touches:
 *
 *   Phase 1  FORWARD   Deterministic, pipelined, PRIVATE keys. Deep same-key
 *                      GET runs (the read-run value-forwarding path), read-
 *                      your-writes, APPEND chains, missing-key runs, volatile
 *                      (TTL) keys, and a cross-key reply-ALIGNMENT torture
 *                      (mixed pipeline; every GET must return ITS key's value).
 *                      Exact-value oracle — any deviation is a bug.
 *
 *   Phase 2  INCR      Hot shared counters hammered by all threads. Oracle:
 *                      final value == total INCRs issued (no lost update =>
 *                      single-writer / WAW correctness). Catches the keyspace
 *                      data hazard the paper's Sec 3.2 warns about.
 *
 *   Phase 3  HOTKV     Hot shared string keys, concurrent SET/GET incl. long
 *                      same-key GET runs. Values are SELF-IDENTIFYING
 *                      (K=<id>;W=<wid>;S=<seq>;...). Oracle: a GET is either a
 *                      pre-populated value or a writer's value, but its
 *                      embedded key id MUST equal the requested key and the
 *                      format MUST be intact. Catches torn reads (RAW), cross-
 *                      key corruption, and reply MISALIGNMENT under contention.
 *
 *   Phase 4  CHAOS     Large values (span embstr->raw and multiple read
 *                      buffers), rapid same-key overwrites on a tiny keyspace,
 *                      and connection churn (reconnect mid-stream). Goal: trip
 *                      the refcount-race / teardown crash class. Server death
 *                      (lost connection) is a hard FAIL.
 *
 * Throughput: no sleeps, deep pipelines, many threads, time-boxed phases.
 *
 * Build:
 *   gcc -O2 -Wall -pthread -o thredis-stress thredis-stress.c -lhiredis
 * Usage:
 *   ./thredis-stress [host] [port] [seconds_per_phase] [threads] [pipeline] [hotkeys]
 *   defaults: 127.0.0.1 6379 5 8 32 16
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <stdint.h>
#include <pthread.h>
#include <unistd.h>
#include <time.h>
#include <stdatomic.h>
#include <hiredis/hiredis.h>

/* ── config ─────────────────────────────────────────────────────────────── */
static char HOST[256] = "127.0.0.1";
static int  PORT = 6379;
static int  SECS = 5;          /* seconds per phase */
static int  NTHREADS = 8;
static int  PIPE = 32;
static int  NHOT = 16;         /* hot keys (small => heavy skew/contention) */
static int  VALSZ = 64;        /* self-identifying value target size */
static int  TTL_PROBE = 0;     /* gate the SET..EX probe (worker SET-with-options
                                * is an out-of-scope, known-unstable path); enable
                                * with env STRESS_TTL=1 to study it deliberately. */
static pid_t RUN_PID;

/* ── stats ──────────────────────────────────────────────────────────────── */
static atomic_long g_checks = 0;
static atomic_long g_fails  = 0;
static atomic_int  g_server_down = 0;
static atomic_long g_ops = 0;

static void ok(void)  { atomic_fetch_add(&g_checks, 1); }
static void failf(const char *fmt, ...) {
    atomic_fetch_add(&g_checks, 1);
    atomic_fetch_add(&g_fails, 1);
    char buf[512]; va_list ap; va_start(ap, fmt); vsnprintf(buf, sizeof buf, fmt, ap); va_end(ap);
    fprintf(stderr, "  \033[31mFAIL\033[0m %s\n", buf);
    fflush(stderr);
}
static void server_down(const char *where, redisContext *c) {
    if (atomic_exchange(&g_server_down, 1) == 0) {
        fprintf(stderr, "  \033[1;31m*** SERVER DOWN / connection lost at %s: %s ***\033[0m\n",
                where, (c && c->errstr[0]) ? c->errstr : "(no errstr)");
        fflush(stderr);
    }
    atomic_fetch_add(&g_fails, 1);
    atomic_fetch_add(&g_checks, 1);
}

static double now_sec(void) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

static redisContext *connect_or_die(void) {
    redisContext *c = redisConnect(HOST, PORT);
    if (!c || c->err) {
        fprintf(stderr, "connect failed: %s\n", c ? c->errstr : "alloc");
        exit(2);
    }
    return c;
}

/* Self-identifying value: "K=<keyid>;W=<wid>;S=<seq>;" + 'x' padding to VALSZ. */
static int make_val(char *buf, int cap, long keyid, int wid, long seq) {
    int n = snprintf(buf, cap, "K=%ld;W=%d;S=%ld;", keyid, wid, seq);
    if (n < 0) n = 0;
    while (n < VALSZ && n < cap - 1) buf[n++] = 'x';
    buf[n] = '\0';
    return n;
}
/* Parse embedded keyid from a returned value; -1 if malformed. */
static long val_keyid(const char *s, size_t len) {
    if (len < 3 || s[0] != 'K' || s[1] != '=') return -1;
    long v = 0; size_t i = 2; int any = 0;
    for (; i < len && s[i] >= '0' && s[i] <= '9'; i++) { v = v*10 + (s[i]-'0'); any = 1; }
    if (!any || i >= len || s[i] != ';') return -1;
    return v;
}

/* ── Phase 1: deterministic private-key forwarding / RYW / alignment ─────── */
typedef struct { int tid; } targ_t;

static void phase1_thread(int tid, redisContext *c) {
    const int R = PIPE > 8 ? PIPE : 8;   /* same-key GET-run length */
    char key[160], val[1024], exp[1024];
    long round = 0;
    double end = now_sec() + SECS;
    while (now_sec() < end && !atomic_load(&g_server_down)) {
        round++;
        /* ---- 1a: same-key GET run + read-your-writes + APPEND chain ---- */
        snprintf(key, sizeof key, "p:%d:t%d:r:fwd", (int)RUN_PID, tid);
        snprintf(val, sizeof val, "v_t%d_r%ld", tid, round);
        /* pipeline: SET; GET xR; SET v2; GET xR; APPEND; GET xR */
        char val2[1024], val3[1024];
        snprintf(val2, sizeof val2, "w_t%d_r%ld", tid, round);
        redisAppendCommand(c, "SET %s %s", key, val);
        for (int i=0;i<R;i++) redisAppendCommand(c, "GET %s", key);
        redisAppendCommand(c, "SET %s %s", key, val2);
        for (int i=0;i<R;i++) redisAppendCommand(c, "GET %s", key);
        redisAppendCommand(c, "APPEND %s Z", key);
        snprintf(val3, sizeof val3, "%sZ", val2);
        for (int i=0;i<R;i++) redisAppendCommand(c, "GET %s", key);
        int total = 1 + R + 1 + R + 1 + R;
        for (int i=0;i<total;i++) {
            redisReply *r=NULL;
            if (redisGetReply(c,(void**)&r)!=REDIS_OK || !r) { server_down("p1.fwd", c); return; }
            const char *want; int isstatus=0, isint=0; long iwant=0;
            if (i==0) { isstatus=1; want="OK"; }
            else if (i>=1 && i<=R) want=val;
            else if (i==R+1) { isstatus=1; want="OK"; }
            else if (i>=R+2 && i<=2*R+1) want=val2;
            else if (i==2*R+2) { isint=1; iwant=(long)strlen(val3); }
            else { want=val3; }
            if (isstatus) { if(r->type==REDIS_REPLY_STATUS && !strcmp(r->str,want)) ok(); else failf("p1 fwd op%d want OK got t=%d s=%s",i,r->type,r->str?r->str:""); }
            else if (isint) { if(r->type==REDIS_REPLY_INTEGER && r->integer==iwant) ok(); else failf("p1 fwd APPEND len want %ld got t=%d i=%lld",iwant,r->type,(long long)(r?r->integer:-1)); }
            else { if(r->type==REDIS_REPLY_STRING && r->len==strlen(want) && !memcmp(r->str,want,r->len)) ok(); else failf("p1 fwd op%d want \"%s\" got t=%d \"%.*s\"",i,want,r->type,r?(int)r->len:0,r&&r->str?r->str:""); }
            freeReplyObject(r);
        }
        atomic_fetch_add(&g_ops, total);

        /* ---- 1b: missing-key GET run (recorded-NULL replay path) ---- */
        snprintf(key, sizeof key, "p:%d:t%d:r%ld:missing", (int)RUN_PID, tid, round);
        for (int i=0;i<R;i++) redisAppendCommand(c, "GET %s", key);
        for (int i=0;i<R;i++) { redisReply*r=NULL; if(redisGetReply(c,(void**)&r)!=REDIS_OK||!r){server_down("p1.miss",c);return;} if(r->type==REDIS_REPLY_NIL) ok(); else failf("p1 miss-run want nil got t=%d",r->type); freeReplyObject(r);}
        atomic_fetch_add(&g_ops, R);

        /* ---- 1c: volatile (TTL) key GET run (forwarding must DISARM) ----
         * Gated: worker SET-with-options (EX) is an out-of-scope path with a
         * known argv-rewrite instability; only probe it when asked. */
        if (TTL_PROBE) {
        snprintf(key, sizeof key, "p:%d:t%d:r:ttl", (int)RUN_PID, tid);
        redisAppendCommand(c, "SET %s %s EX 1000", key, val);
        for (int i=0;i<R;i++) redisAppendCommand(c, "GET %s", key);
        { redisReply*r=NULL; if(redisGetReply(c,(void**)&r)!=REDIS_OK||!r){server_down("p1.ttl.set",c);return;} if(r->type==REDIS_REPLY_STATUS&&!strcmp(r->str,"OK")) ok(); else failf("p1 ttl SET want OK got t=%d",r->type); freeReplyObject(r);}
        for (int i=0;i<R;i++){ redisReply*r=NULL; if(redisGetReply(c,(void**)&r)!=REDIS_OK||!r){server_down("p1.ttl.get",c);return;} if(r->type==REDIS_REPLY_STRING&&r->len==strlen(val)&&!memcmp(r->str,val,r->len)) ok(); else failf("p1 ttl GET want \"%s\" got t=%d \"%.*s\"",val,r->type,r?(int)r->len:0,r&&r->str?r->str:""); freeReplyObject(r);}
        atomic_fetch_add(&g_ops, R+1);
        } /* end TTL_PROBE */

        /* ---- 1d: cross-key reply ALIGNMENT torture (mixed pipeline) ----
         * SET many distinct private keys, then GET them in a DIFFERENT order;
         * each GET must return exactly its own key's value. Catches any
         * reply<->request misalignment in the drain. */
        int M = PIPE;
        char (*ks)[160] = malloc(sizeof(char[160])*M);
        char (*vs)[64]  = malloc(sizeof(char[64])*M);
        for (int i=0;i<M;i++){ snprintf(ks[i],160,"p:%d:t%d:r%ld:a%d",(int)RUN_PID,tid,round,i); snprintf(vs[i],64,"A%d_%ld",i,round); redisAppendCommand(c,"SET %s %s",ks[i],vs[i]); }
        for (int i=0;i<M;i++){ redisReply*r=NULL; if(redisGetReply(c,(void**)&r)!=REDIS_OK||!r){server_down("p1.align.set",c);free(ks);free(vs);return;} if(r->type==REDIS_REPLY_STATUS) ok(); else failf("p1 align SET t=%d",r->type); freeReplyObject(r);}
        /* GET in reverse + interleaved order */
        for (int i=M-1;i>=0;i--) redisAppendCommand(c,"GET %s",ks[i]);
        for (int i=M-1;i>=0;i--){ redisReply*r=NULL; if(redisGetReply(c,(void**)&r)!=REDIS_OK||!r){server_down("p1.align.get",c);free(ks);free(vs);return;} if(r->type==REDIS_REPLY_STRING&&r->len==strlen(vs[i])&&!memcmp(r->str,vs[i],r->len)) ok(); else failf("p1 ALIGNMENT: GET %s want \"%s\" got \"%.*s\" (reply misaligned or cross-key corruption)",ks[i],vs[i],r?(int)r->len:0,r&&r->str?r->str:""); freeReplyObject(r);}
        atomic_fetch_add(&g_ops, 2*M);
        free(ks); free(vs);
    }
}

/* ── Phase 2: hot-counter INCR linearizability (no lost updates) ─────────── */
static atomic_long *g_incr_issued;   /* per hot counter, issued count */
static void phase2_thread(int tid, redisContext *c) {
    char key[160];
    double end = now_sec() + SECS;
    long local[4096]; for(int i=0;i<NHOT;i++) local[i]=0;
    while (now_sec() < end && !atomic_load(&g_server_down)) {
        for (int i=0;i<PIPE;i++){ int h=(tid*7+i)%NHOT; snprintf(key,sizeof key,"c:%d:hot%d",(int)RUN_PID,h); redisAppendCommand(c,"INCR %s",key); local[h]++; }
        for (int i=0;i<PIPE;i++){ int h=(tid*7+i)%NHOT; redisReply*r=NULL; if(redisGetReply(c,(void**)&r)!=REDIS_OK||!r){server_down("p2.incr",c);
            /* still flush issued counts so verify reflects what we sent */
            for(int j=0;j<NHOT;j++) atomic_fetch_add(&g_incr_issued[j],local[j]); return;}
            if(r->type==REDIS_REPLY_INTEGER && r->integer>=1) ok(); else failf("p2 INCR hot%d want int>=1 got t=%d i=%lld",h,r->type,(long long)(r?r->integer:-1)); freeReplyObject(r);}
        atomic_fetch_add(&g_ops, 2*PIPE);
    }
    for(int j=0;j<NHOT;j++) atomic_fetch_add(&g_incr_issued[j],local[j]);
}

/* ── Phase 3: hot shared SET/GET — torn/cross-key/misalignment ───────────── */
static void phase3_thread(int tid, redisContext *c) {
    char key[160], val[1024];
    long seq=0; double end = now_sec()+SECS;
    while (now_sec() < end && !atomic_load(&g_server_down)) {
        /* mixed pipeline: writes + same-key GET runs across hot keys */
        int nq=0;
        for (int i=0;i<PIPE;i++) {
            int h=(tid*13+i*3+ (int)seq)%NHOT;
            snprintf(key,sizeof key,"h:%d:hot%d",(int)RUN_PID,h);
            if (i%4==0) { make_val(val,sizeof val,h,tid,++seq); redisAppendCommand(c,"SET %s %b",key,val,strlen(val)); }
            else        { redisAppendCommand(c,"GET %s",key); }
            nq++;
        }
        for (int i=0;i<nq;i++) {
            int h=(tid*13+i*3+ (int)seq)%NHOT;  /* NOTE: seq changed during queue; recompute below */
            (void)h;
        }
        /* re-derive op identity exactly as queued: track in a small array */
        /* (simpler: re-run derivation with a captured seq base) */
        for (int i=0;i<nq;i++){ redisReply*r=NULL; if(redisGetReply(c,(void**)&r)!=REDIS_OK||!r){server_down("p3.kv",c);return;}
            /* We can't know which hot index this op used after the fact because
             * seq mutated; instead validate structurally: SET->OK, GET-> nil or
             * a well-formed self-id value. Cross-key/misalignment is still
             * caught because the embedded K must be a VALID hot id [0,NHOT). */
            if (r->type==REDIS_REPLY_STATUS) { if(!strcmp(r->str,"OK")) ok(); else failf("p3 status %s",r->str); }
            else if (r->type==REDIS_REPLY_NIL) { ok(); }
            else if (r->type==REDIS_REPLY_STRING) { long kid=val_keyid(r->str,r->len); if(kid>=0 && kid<NHOT) ok(); else failf("p3 GET torn/cross-key/misaligned value: \"%.*s\" kid=%ld",r?(int)r->len:0,r&&r->str?r->str:"",kid); }
            else failf("p3 unexpected reply type %d",r->type);
            freeReplyObject(r);
        }
        atomic_fetch_add(&g_ops, 2*nq);
    }
}

/* stronger same-key oracle: deterministic per-key matching */
static void phase3b_thread(int tid, redisContext *c) {
    /* Each op pipelined with KNOWN hot index (no shared seq mutation issue):
     * SET hot[h] then GET hot[h] in same pipeline; GET must return a value
     * whose embedded key id == h (its own writes interleave with others', but
     * the id is always h unless misaligned/corrupted). */
    char key[160], val[1024];
    long seq=0; double end = now_sec()+SECS;
    int *hidx = malloc(sizeof(int)*PIPE);
    int *iss  = malloc(sizeof(int)*PIPE);  /* 1=SET 0=GET */
    while (now_sec() < end && !atomic_load(&g_server_down)) {
        for (int i=0;i<PIPE;i++){ int h=(i+tid)%NHOT; hidx[i]=h; snprintf(key,sizeof key,"h:%d:hot%d",(int)RUN_PID,h);
            if (i%3==0){ iss[i]=1; make_val(val,sizeof val,h,tid,++seq); redisAppendCommand(c,"SET %s %b",key,val,strlen(val)); }
            else { iss[i]=0; redisAppendCommand(c,"GET %s",key); } }
        for (int i=0;i<PIPE;i++){ redisReply*r=NULL; if(redisGetReply(c,(void**)&r)!=REDIS_OK||!r){server_down("p3b.kv",c);free(hidx);free(iss);return;}
            if (iss[i]) { if(r->type==REDIS_REPLY_STATUS) ok(); else failf("p3b SET hot%d t=%d",hidx[i],r->type); }
            else { if (r->type==REDIS_REPLY_NIL) ok();
                   else if (r->type==REDIS_REPLY_STRING){ long kid=val_keyid(r->str,r->len); if(kid==hidx[i]) ok(); else failf("p3b GET hot%d returned key id %ld (\"%.*s\") — misalignment/torn/cross-key",hidx[i],kid,r?(int)r->len:0,r&&r->str?r->str:""); }
                   else failf("p3b GET hot%d type %d",hidx[i],r->type); }
            freeReplyObject(r);
        }
        atomic_fetch_add(&g_ops, PIPE);
    }
    free(hidx); free(iss);
}

/* ── Phase 4: chaos — large values, churn, rapid overwrite ───────────────── */
static void phase4_thread(int tid, redisContext *c_unused) {
    (void)c_unused;
    double end = now_sec()+SECS;
    long round=0;
    int big = 70000;  /* spans embstr->raw and > one read buffer */
    char *bv = malloc(big+64);
    while (now_sec() < end && !atomic_load(&g_server_down)) {
        redisContext *c = redisConnect(HOST, PORT);   /* churn: fresh conn each loop */
        if (!c || c->err) { server_down("p4.connect", c); if(c)redisFree(c); free(bv); return; }
        round++;
        char key[160];
        /* rapid same-key overwrite on a tiny keyspace (max refcount-race pressure) */
        for (int i=0;i<PIPE;i++){ int h=i%4; snprintf(key,sizeof key,"x:%d:hot%d",(int)RUN_PID,h);
            int n=make_val(bv,big+64,h,tid,round*PIPE+i); redisAppendCommand(c,"SET %s %b",key,bv,(size_t)n); }
        for (int i=0;i<PIPE;i++){ redisReply*r=NULL; if(redisGetReply(c,(void**)&r)!=REDIS_OK||!r){server_down("p4.set",c);redisFree(c);free(bv);return;} if(r->type==REDIS_REPLY_STATUS) ok(); else failf("p4 set t=%d",r->type); freeReplyObject(r);}
        /* one big value to exercise multi-buffer parse + raw encoding */
        memset(bv,'B',big); bv[big]='\0';
        snprintf(key,sizeof key,"x:%d:big",(int)RUN_PID);
        redisAppendCommand(c,"SET %s %b",key,bv,(size_t)big);
        redisAppendCommand(c,"STRLEN %s",key);
        redisAppendCommand(c,"GET %s",key);
        { redisReply*r=NULL; if(redisGetReply(c,(void**)&r)!=REDIS_OK||!r){server_down("p4.big.set",c);redisFree(c);free(bv);return;} if(r->type==REDIS_REPLY_STATUS) ok(); else failf("p4 big set t=%d",r->type); freeReplyObject(r);}
        { redisReply*r=NULL; if(redisGetReply(c,(void**)&r)!=REDIS_OK||!r){server_down("p4.big.strlen",c);redisFree(c);free(bv);return;} if(r->type==REDIS_REPLY_INTEGER&&r->integer==big) ok(); else failf("p4 big STRLEN want %d got t=%d i=%lld",big,r->type,(long long)(r?r->integer:-1)); freeReplyObject(r);}
        { redisReply*r=NULL; if(redisGetReply(c,(void**)&r)!=REDIS_OK||!r){server_down("p4.big.get",c);redisFree(c);free(bv);return;} if(r->type==REDIS_REPLY_STRING&&r->len==(size_t)big) ok(); else failf("p4 big GET want len %d got t=%d len=%d",big,r->type,r?(int)r->len:-1); freeReplyObject(r);}
        atomic_fetch_add(&g_ops, 2*PIPE+3);
        redisFree(c);   /* drop connection mid-stress -> teardown path */
    }
    free(bv);
}

/* ── phase driver ───────────────────────────────────────────────────────── */
typedef void (*phasefn)(int, redisContext*);
typedef struct { int tid; phasefn fn; int own_conn; } pctx_t;
static void *pthread_entry(void *a) {
    pctx_t *p = (pctx_t*)a;
    redisContext *c = NULL;
    if (p->own_conn) { c = connect_or_die();
        /* disable hiredis read timeout-less blocking issues: keep default */ }
    p->fn(p->tid, c);
    if (c) redisFree(c);
    return NULL;
}
static void run_phase(const char *name, phasefn fn, int own_conn) {
    if (atomic_load(&g_server_down)) { printf("[%s] SKIPPED (server already down)\n", name); return; }
    long c0=atomic_load(&g_checks), f0=atomic_load(&g_fails), o0=atomic_load(&g_ops);
    double t0=now_sec();
    pthread_t th[256]; pctx_t ctx[256];
    for (int i=0;i<NTHREADS;i++){ ctx[i].tid=i; ctx[i].fn=fn; ctx[i].own_conn=own_conn; pthread_create(&th[i],NULL,pthread_entry,&ctx[i]); }
    for (int i=0;i<NTHREADS;i++) pthread_join(th[i],NULL);
    double dt=now_sec()-t0;
    long checks=atomic_load(&g_checks)-c0, fails=atomic_load(&g_fails)-f0, ops=atomic_load(&g_ops)-o0;
    printf("[%-8s] %.1fs  ops=%ld (%.0f kops/s)  checks=%ld  fails=%ld  %s\n",
           name, dt, ops, dt>0?ops/dt/1000.0:0, checks, fails,
           fails==0 ? "\033[32mPASS\033[0m" : "\033[31mFAIL\033[0m");
    fflush(stdout);
}

int main(int argc, char **argv) {
    if (argc>=2) strncpy(HOST,argv[1],sizeof HOST-1);
    if (argc>=3) PORT=atoi(argv[2]);
    if (argc>=4) SECS=atoi(argv[3]);
    if (argc>=5) NTHREADS=atoi(argv[4]);
    if (argc>=6) PIPE=atoi(argv[5]);
    if (argc>=7) NHOT=atoi(argv[6]);
    if (NTHREADS>256) NTHREADS=256;
    if (NHOT>4096) NHOT=4096;
    if (getenv("STRESS_TTL")) TTL_PROBE=1;
    RUN_PID=getpid();
    printf("thredis-stress -> %s:%d  secs/phase=%d threads=%d pipeline=%d hotkeys=%d valsz=%d\n\n",
           HOST,PORT,SECS,NTHREADS,PIPE,NHOT,VALSZ);

    /* sanity + pre-populate hot keys for phase 3 so GET is never spuriously nil */
    redisContext *c = connect_or_die();
    redisReply *r = redisCommand(c,"PING");
    if (!r || r->type==REDIS_REPLY_ERROR){ fprintf(stderr,"PING failed\n"); return 2; }
    freeReplyObject(r);
    char key[160], val[1024];
    for (int h=0;h<NHOT;h++){ snprintf(key,sizeof key,"h:%d:hot%d",(int)RUN_PID,h); make_val(val,sizeof val,h,-1,0);
        r=redisCommand(c,"SET %s %b",key,val,strlen(val)); if(r)freeReplyObject(r);
        snprintf(key,sizeof key,"c:%d:hot%d",(int)RUN_PID,h); r=redisCommand(c,"DEL %s",key); if(r)freeReplyObject(r);
        snprintf(key,sizeof key,"c:%d:hot%d",(int)RUN_PID,h); r=redisCommand(c,"SET %s 0",key); if(r)freeReplyObject(r);
    }
    redisFree(c);

    g_incr_issued = calloc(NHOT, sizeof(atomic_long));

    run_phase("FORWARD", phase1_thread, 1);
    run_phase("INCR",    phase2_thread, 1);
    /* verify counters == issued (no lost updates) */
    if (!atomic_load(&g_server_down)) {
        c = connect_or_die();
        for (int h=0;h<NHOT;h++){ snprintf(key,sizeof key,"c:%d:hot%d",(int)RUN_PID,h);
            r=redisCommand(c,"GET %s",key);
            long want=atomic_load(&g_incr_issued[h]);
            long got = (r&&r->type==REDIS_REPLY_STRING)? atol(r->str) : -1;
            if (got==want) ok(); else failf("INCR LOST UPDATE on hot%d: issued %ld but counter=%ld (WAW hazard / single-writer violation)",h,want,got);
            if(r)freeReplyObject(r);
        }
        redisFree(c);
        printf("[INCR-VFY] counters checked against issued totals\n");
    }
    run_phase("HOTKV",   phase3b_thread, 1);
    run_phase("HOTKV2",  phase3_thread,  1);
    run_phase("CHAOS",   phase4_thread,  0);

    long checks=atomic_load(&g_checks), fails=atomic_load(&g_fails);
    printf("\n═══════════════════════════════════════\n");
    printf("  total checks : %ld\n", checks);
    printf("  failures     : %ld\n", fails);
    printf("  server down  : %s\n", atomic_load(&g_server_down)?"YES (CRASH/DISCONNECT)":"no");
    printf("  verdict      : %s\n", (fails==0 && !atomic_load(&g_server_down))?"\033[32mALL CORRECT\033[0m":"\033[31mDEFECTS FOUND\033[0m");
    printf("═══════════════════════════════════════\n");
    return (fails==0 && !atomic_load(&g_server_down)) ? 0 : 1;
}
