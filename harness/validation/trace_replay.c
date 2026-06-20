/* thredis-trace-replay — realistic-workload driver for THredis.
 *
 * Three modes (the point: exercise the access PATTERNS that the value-forward
 * gates and the branch-predictor/feedback/SHiP mechanisms need — which uniform
 * memtier cannot produce):
 *   zipf    : Zipfian key popularity (skew) -> hot keys recur -> per-key predictors learn.
 *   phasic  : alternating read-heavy / write-heavy phases -> exercises the write-rate
 *             gate, the predictor's phase adaptation, and the tournament chooser.
 *   file    : replay a CSV trace "op,key[,valsize]" (op = g|get|r read, s|set|w write).
 *             For real Twitter cluster / Meta CacheLib traces on the EPYC box.
 *
 * Synthetic modes (zipf/phasic) write SELF-IDENTIFYING values ("K<id>:" prefix) so a
 * GET that returns a value is checked to encode the requested key -> correctness oracle
 * (catches cross-key/torn replies, e.g. a value-forwarding/predictor bug). file mode
 * does throughput/hit-rate only.
 *
 * Build: gcc -O2 -Wall -pthread -I THredis-opt/deps -o thredis-trace-replay \
 *        thredis-trace-replay.c THredis-opt/deps/hiredis/libhiredis.a
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <pthread.h>
#include <time.h>
#include <stdint.h>
#include <unistd.h>
#include "hiredis/hiredis.h"

static char *g_host = "127.0.0.1";
static int   g_port = 6379;
static int   g_threads = 6;
static int   g_pipe = 32;
static long  g_keyspace = 100000;
static int   g_valsize = 64;
static int   g_ratio_set = 1, g_ratio_get = 9;   /* set:get */
static double g_theta = 0.99;                     /* zipf skew (YCSB default) */
static int   g_seconds = 10;
static int   g_phase_ms = 500;                    /* phasic: phase length */
static const char *g_mode = "zipf";
static const char *g_file = NULL;

static volatile int g_stop = 0;

/* ---- Zipfian generator (YCSB-style, Gray et al.) ---- */
typedef struct { long n; double theta, zetan, alpha, eta, zeta2; } zipf_t;
static double zeta(long n, double theta){ double s=0; for(long i=1;i<=n;i++) s+=1.0/pow((double)i,theta); return s; }
static void zipf_init(zipf_t *z, long n, double theta){
    z->n=n; z->theta=theta; z->zetan=zeta(n,theta); z->zeta2=zeta(2,theta);
    z->alpha=1.0/(1.0-theta);
    z->eta=(1.0-pow(2.0/(double)n,1.0-theta))/(1.0-z->zeta2/z->zetan);
}
static long zipf_next(zipf_t *z, unsigned int *seed){
    double u=(double)rand_r(seed)/RAND_MAX;
    double uz=u*z->zetan;
    if(uz<1.0) return 0;
    if(uz<1.0+pow(0.5,z->theta)) return 1;
    long v=(long)((double)z->n*pow(z->eta*u - z->eta + 1.0, z->alpha));
    if(v<0) v=0; if(v>=z->n) v=z->n-1; return v;
}

typedef struct {
    long ops, gets, sets, hits, miss, errors, corrupt;
} stats_t;

static void mkval(char *buf, int sz, long key){
    int p = snprintf(buf, sz, "K%ld:", key);
    if (p < 0) p = 0; if (p > sz) p = sz;
    for (int i=p;i<sz;i++) buf[i]='x';
}
/* verify a returned value encodes the requested key */
static int valok(const char *s, size_t len, long key){
    char pfx[32]; int p=snprintf(pfx,sizeof(pfx),"K%ld:",key);
    return (len>=(size_t)p && memcmp(s,pfx,p)==0);
}

typedef struct { int id; stats_t st; } worker_t;

static void *worker(void *arg){
    worker_t *w=(worker_t*)arg;
    unsigned int seed = (unsigned int)(time(NULL) ^ (w->id*2654435761u));
    redisContext *c = redisConnect(g_host, g_port);
    if(!c || c->err){ w->st.errors++; if(c) redisFree(c); return NULL; }
    zipf_t z; zipf_init(&z, g_keyspace, g_theta);
    char *val = malloc(g_valsize+1);
    long started = time(NULL);
    int rtot = g_ratio_get + g_ratio_set;

    /* file mode: each thread reads the whole file (simple); interleave by id */
    FILE *tf = NULL; if(strcmp(g_mode,"file")==0){ tf=fopen(g_file,"r"); if(!tf){w->st.errors++; redisFree(c); free(val); return NULL;} }

    while(!g_stop){
        /* issue a pipeline of g_pipe ops */
        long keys[4096]; int isget[4096]; int np=0;
        for(int i=0;i<g_pipe && np<4096;i++){
            long key; int doget;
            if(tf){
                char line[256]; if(!fgets(line,sizeof(line),tf)){ rewind(tf); if(!fgets(line,sizeof(line),tf)) break; }
                char op[16]; long k=0; if(sscanf(line,"%15[^,],%ld",op,&k)<2) continue;
                doget = (op[0]=='g'||op[0]=='r'||op[0]=='G'||op[0]=='R');
                key = k % g_keyspace;
            } else {
                /* phasic: flip ratio by phase; zipf/uniform key pick */
                int writephase=0;
                if(strcmp(g_mode,"phasic")==0){
                    long ms=(long)((time(NULL)-started)*1000);
                    writephase = ((ms / g_phase_ms) & 1);
                }
                if(strcmp(g_mode,"uniform")==0) key = rand_r(&seed) % g_keyspace;
                else key = zipf_next(&z,&seed);
                int roll = rand_r(&seed) % rtot;
                doget = writephase ? (roll >= 7) : (roll >= g_ratio_set); /* writephase: ~70% writes */
            }
            if(doget){ redisAppendCommand(c,"GET %ld",key); }
            else { mkval(val,g_valsize,key); redisAppendCommand(c,"SET %ld %b",key,val,(size_t)g_valsize); }
            keys[np]=key; isget[np]=doget; np++;
        }
        for(int i=0;i<np;i++){
            redisReply *r=NULL;
            if(redisGetReply(c,(void**)&r)!=REDIS_OK || !r){ w->st.errors++; g_stop=1; break; }
            w->st.ops++;
            if(isget[i]){
                w->st.gets++;
                if(r->type==REDIS_REPLY_NIL) w->st.miss++;
                else if(r->type==REDIS_REPLY_STRING){
                    w->st.hits++;
                    if(strcmp(g_mode,"file")!=0 && !valok(r->str,r->len,keys[i])) w->st.corrupt++;
                } else if(r->type==REDIS_REPLY_ERROR){ w->st.errors++; }
            } else { w->st.sets++; if(r->type==REDIS_REPLY_ERROR) w->st.errors++; }
            freeReplyObject(r);
        }
    }
    if(tf) fclose(tf);
    free(val); redisFree(c); return NULL;
}

int main(int argc, char**argv){
    /* args: host port threads pipe keyspace valsize set:get seconds mode [theta|phase_ms|file] */
    if(argc<2){ fprintf(stderr,
        "usage: %s host port threads pipe keyspace valsize set get seconds mode [theta_or_phasems_or_file]\n"
        "  mode = zipf | phasic | uniform | file\n", argv[0]); return 1; }
    int a=1;
    g_host=argv[a++]; g_port=atoi(argv[a++]); g_threads=atoi(argv[a++]); g_pipe=atoi(argv[a++]);
    g_keyspace=atol(argv[a++]); g_valsize=atoi(argv[a++]); g_ratio_set=atoi(argv[a++]); g_ratio_get=atoi(argv[a++]);
    g_seconds=atoi(argv[a++]); g_mode=argv[a++];
    if(a<argc){ if(strcmp(g_mode,"file")==0) g_file=argv[a]; else if(strcmp(g_mode,"phasic")==0) g_phase_ms=atoi(argv[a]); else g_theta=atof(argv[a]); }
    if(g_pipe>4096) g_pipe=4096;

    worker_t *ws=calloc(g_threads,sizeof(worker_t));
    pthread_t *th=calloc(g_threads,sizeof(pthread_t));
    struct timespec t0; clock_gettime(CLOCK_MONOTONIC,&t0);
    for(int i=0;i<g_threads;i++){ ws[i].id=i; pthread_create(&th[i],NULL,worker,&ws[i]); }
    sleep(g_seconds); g_stop=1;
    for(int i=0;i<g_threads;i++) pthread_join(th[i],NULL);
    struct timespec t1; clock_gettime(CLOCK_MONOTONIC,&t1);
    double secs=(t1.tv_sec-t0.tv_sec)+(t1.tv_nsec-t0.tv_nsec)/1e9;

    stats_t tot={0};
    for(int i=0;i<g_threads;i++){ stats_t*s=&ws[i].st;
        tot.ops+=s->ops; tot.gets+=s->gets; tot.sets+=s->sets; tot.hits+=s->hits;
        tot.miss+=s->miss; tot.errors+=s->errors; tot.corrupt+=s->corrupt; }
    double hr = tot.gets? (100.0*tot.hits/tot.gets):0;
    printf("mode=%s keyspace=%ld theta=%.2f ratio=%d:%d pipe=%d threads=%d\n",
        g_mode,g_keyspace,g_theta,g_ratio_set,g_ratio_get,g_pipe,g_threads);
    printf("ops=%ld (%.0f ops/s)  gets=%ld sets=%ld  hit-rate=%.1f%%  miss=%ld  errors=%ld  corrupt=%ld\n",
        tot.ops, tot.ops/secs, tot.gets, tot.sets, hr, tot.miss, tot.errors, tot.corrupt);
    printf("VERDICT: %s\n", (tot.errors==0 && tot.corrupt==0) ? "OK" : "DEFECTS");
    return (tot.errors||tot.corrupt)?2:0;
}
