/* thredis-mkey-oracle-v7 — cross-shard MGET correctness oracle for THredis v7.
 *
 * v7 implements cross-shard MGET only (MSET/DEL/EXISTS deferred). The original
 * thredis-mkey-oracle POPULATES with MSET — which, without cross-shard MSET, runs inline
 * on the IO thread's (empty) db instead of the worker shards, so cross-shard MGET would
 * read nothing and the oracle would falsely report corruption.
 *
 * This version populates with SINGLE-KEY SET (which IS worker-dispatched, so each key lands
 * in its owning shard via the same xxh64 hash MGET's subs use), then exercises cross-shard
 * MGET REASSEMBLY: key "mk:<id>" -> value "v<id>"; MGET a random multi-key set whose keys
 * deliberately span shards; verify position i of the reply is EXACTLY key i's value. Any
 * mismatch = reorder / cross-key / lost-subreply bug. Also mixes set+unset keys (an id >=
 * keyspace is never written) to verify nils land in the right positions. Multi-threaded,
 * pipelined; run under churn / ASAN / flag toggle.
 *
 * Build: gcc -O2 -Wall -pthread -I THredis-opt-v7/deps -o thredis-mkey-oracle-v7 \
 *        thredis-mkey-oracle-v7.c THredis-opt-v7/deps/hiredis/libhiredis.a
 * Run:   ./thredis-mkey-oracle-v7 127.0.0.1 6379 <threads> <nkeys/cmd> <secs> <keyspace>
 *        (set `config set thredis-opt-cross-shard yes` first)
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <time.h>
#include <unistd.h>
#include "hiredis/hiredis.h"

static char *g_host="127.0.0.1"; static int g_port=6379;
static int g_threads=6, g_nkeys=8, g_secs=10; long g_keyspace=20000;
static volatile int g_stop=0, g_ready=0;
typedef struct { long mget, checked, corrupt, errors, badnil; } st_t;

/* Populate [0,keyspace) with SET mk:<id> v<id> (single-key => worker-dispatched => correct
 * shard). Pipelined for speed. Returns 0 on success. */
static int populate(void){
    redisContext *c=redisConnect(g_host,g_port); if(!c||c->err){ if(c)redisFree(c); return -1; }
    char k[32], v[32];
    const int BATCH=1000;
    for(long base=0; base<g_keyspace; base+=BATCH){
        long hi = base+BATCH < g_keyspace ? base+BATCH : g_keyspace;
        for(long id=base; id<hi; id++){
            snprintf(k,sizeof(k),"mk:%ld",id); snprintf(v,sizeof(v),"v%ld",id);
            redisAppendCommand(c,"SET %s %s",k,v);
        }
        for(long id=base; id<hi; id++){ redisReply *r=NULL;
            if(redisGetReply(c,(void**)&r)!=REDIS_OK || !r){ redisFree(c); return -2; }
            freeReplyObject(r);
        }
    }
    redisFree(c); return 0;
}

static void *worker(void *arg){
    st_t *s=(st_t*)arg; unsigned int seed=(unsigned int)(time(NULL)^(long)pthread_self());
    redisContext *c=redisConnect(g_host,g_port); if(!c||c->err){ s->errors++; if(c)redisFree(c); return NULL; }
    char keys[256][32]; char vals[256][32];
    const char *argv[260]; size_t argl[260];
    while(!g_ready && !g_stop) usleep(1000);
    while(!g_stop){
        int n=g_nkeys;
        /* pick n random keys spanning the keyspace (=> span shards) */
        for(int i=0;i<n;i++){ long id=rand_r(&seed)%g_keyspace;
            snprintf(keys[i],sizeof(keys[i]),"mk:%ld",id);
            snprintf(vals[i],sizeof(vals[i]),"v%ld",id); }
        /* MGET same keys -> verify position i == vals[i] (all were pre-SET) */
        argv[0]="MGET"; argl[0]=4; for(int i=0;i<n;i++){ argv[1+i]=keys[i]; argl[1+i]=strlen(keys[i]); }
        redisReply *r=redisCommandArgv(c,1+n,argv,argl); s->mget++;
        if(!r){ s->errors++; g_stop=1; break; }
        if(r->type==REDIS_REPLY_ERROR){ s->errors++; }
        else if(r->type!=REDIS_REPLY_ARRAY || (int)r->elements!=n){ s->corrupt++; }
        else { for(int i=0;i<n;i++){ s->checked++;
                redisReply *e=r->element[i];
                if(e->type==REDIS_REPLY_STRING){ if(strcmp(e->str,vals[i])!=0) s->corrupt++; }
                else { s->corrupt++; } /* pre-SET key must exist as a string */ } }
        freeReplyObject(r);
        /* mixed: MGET set key + GUARANTEED-absent key (id >= keyspace) + set key; check nil pos */
        char absent[32]; snprintf(absent,sizeof(absent),"mk:%ld",g_keyspace + 1 + (rand_r(&seed)%100000));
        argv[0]="MGET"; argl[0]=4; argv[1]=keys[0]; argl[1]=strlen(keys[0]);
        argv[2]=absent; argl[2]=strlen(absent); argv[3]=keys[1]; argl[3]=strlen(keys[1]);
        r=redisCommandArgv(c,4,argv,argl);
        if(r && r->type==REDIS_REPLY_ARRAY && r->elements==3){ s->checked+=3;
            if(!(r->element[0]->type==REDIS_REPLY_STRING && strcmp(r->element[0]->str,vals[0])==0)) s->corrupt++;
            if(r->element[1]->type!=REDIS_REPLY_NIL) s->badnil++;
            if(!(r->element[2]->type==REDIS_REPLY_STRING && strcmp(r->element[2]->str,vals[1])==0)) s->corrupt++;
        } else if(r){ s->corrupt++; }
        if(r) freeReplyObject(r);
        /* single-key MGET (n==1) edge case occasionally */
        if((rand_r(&seed)&7)==0){
            argv[0]="MGET"; argl[0]=4; argv[1]=keys[0]; argl[1]=strlen(keys[0]);
            r=redisCommandArgv(c,2,argv,argl);
            if(r && r->type==REDIS_REPLY_ARRAY && r->elements==1){ s->checked++;
                redisReply *e=r->element[0];
                if(!(e->type==REDIS_REPLY_STRING && strcmp(e->str,vals[0])==0)) s->corrupt++;
            } else if(r){ s->corrupt++; }
            if(r) freeReplyObject(r);
        }
    }
    redisFree(c); return NULL;
}

int main(int argc,char**argv){
    if(argc>1)g_host=argv[1]; if(argc>2)g_port=atoi(argv[2]); if(argc>3)g_threads=atoi(argv[3]);
    if(argc>4)g_nkeys=atoi(argv[4]); if(argc>5)g_secs=atoi(argv[5]); if(argc>6)g_keyspace=atol(argv[6]);
    if(g_nkeys>256)g_nkeys=256; if(g_nkeys<1)g_nkeys=1;
    printf("populating %ld keys via single-key SET ...\n",g_keyspace); fflush(stdout);
    if(populate()!=0){ printf("POPULATE FAILED (server up? cross-shard ok? )\n"); return 3; }
    st_t *s=calloc(g_threads,sizeof(st_t)); pthread_t *t=calloc(g_threads,sizeof(pthread_t));
    for(int i=0;i<g_threads;i++) pthread_create(&t[i],NULL,worker,&s[i]);
    g_ready=1;
    sleep(g_secs); g_stop=1;
    for(int i=0;i<g_threads;i++) pthread_join(t[i],NULL);
    st_t T={0}; for(int i=0;i<g_threads;i++){ T.mget+=s[i].mget;T.checked+=s[i].checked;
        T.corrupt+=s[i].corrupt;T.errors+=s[i].errors;T.badnil+=s[i].badnil; }
    printf("nkeys/cmd=%d threads=%d keyspace=%ld\n",g_nkeys,g_threads,g_keyspace);
    printf("MGET=%ld positions-checked=%ld  CORRUPT=%ld  bad-nil=%ld  errors=%ld\n",
        T.mget,T.checked,T.corrupt,T.badnil,T.errors);
    printf("VERDICT: %s\n",(T.corrupt==0 && T.badnil==0 && T.errors==0)?"OK":"DEFECTS");
    return (T.corrupt||T.badnil||T.errors)?2:0;
}
