/* thredis-mkey-oracle — cross-shard multi-key correctness oracle for THredis v7.
 *
 * Validates MGET/MSET scatter-gather REASSEMBLY: writes self-identifying values
 * (key "mk:<id>" -> value "v<id>"), then MGETs a random multi-key set whose keys
 * deliberately span shards, and verifies position i of the reply is EXACTLY key i's
 * value. Any mismatch = reorder / cross-key / lost-subreply bug (the failure modes
 * cross-shard reassembly is prone to). Also mixes set+unset keys to verify nils land
 * in the right positions. Multi-threaded, pipelined, runs under churn/ASAN.
 *
 * Build: gcc -O2 -Wall -pthread -I THredis-opt-v6/deps -o thredis-mkey-oracle \
 *        thredis-mkey-oracle.c THredis-opt-v6/deps/hiredis/libhiredis.a
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
static volatile int g_stop=0;
typedef struct { long mset, mget, checked, corrupt, errors, badnil; } st_t;

static void *worker(void *arg){
    st_t *s=(st_t*)arg; unsigned int seed=(unsigned int)(time(NULL)^(long)pthread_self());
    redisContext *c=redisConnect(g_host,g_port); if(!c||c->err){ s->errors++; if(c)redisFree(c); return NULL; }
    char keys[256][32]; char vals[256][32]; long ids[256];
    const char *argv[260]; size_t argl[260];
    while(!g_stop){
        int n=g_nkeys;
        /* pick n random keys spanning the keyspace (=> span shards) */
        for(int i=0;i<n;i++){ long id=rand_r(&seed)%g_keyspace; ids[i]=id;
            snprintf(keys[i],sizeof(keys[i]),"mk:%ld",id);
            snprintf(vals[i],sizeof(vals[i]),"v%ld",id); }
        /* MSET k1 v1 ... */
        argv[0]="MSET"; argl[0]=4; int a=1;
        for(int i=0;i<n;i++){ argv[a]=keys[i]; argl[a]=strlen(keys[i]); a++; argv[a]=vals[i]; argl[a]=strlen(vals[i]); a++; }
        redisReply *r=redisCommandArgv(c,a,argv,argl); s->mset++;
        if(!r){ s->errors++; g_stop=1; break; }
        if(r->type==REDIS_REPLY_ERROR) s->errors++;
        freeReplyObject(r);
        /* MGET same keys -> verify position i == vals[i] */
        argv[0]="MGET"; argl[0]=4; for(int i=0;i<n;i++){ argv[1+i]=keys[i]; argl[1+i]=strlen(keys[i]); }
        r=redisCommandArgv(c,1+n,argv,argl); s->mget++;
        if(!r){ s->errors++; g_stop=1; break; }
        if(r->type==REDIS_REPLY_ERROR){ s->errors++; }
        else if(r->type!=REDIS_REPLY_ARRAY || (int)r->elements!=n){ s->corrupt++; }
        else { for(int i=0;i<n;i++){ s->checked++;
                redisReply *e=r->element[i];
                if(e->type==REDIS_REPLY_STRING){ if(strcmp(e->str,vals[i])!=0) s->corrupt++; }
                else if(e->type==REDIS_REPLY_NIL){ s->corrupt++; } /* we just MSET it -> must exist */
                else s->corrupt++; } }
        freeReplyObject(r);
        /* mixed: MGET a set key + an unset key, verify nil position */
        char unset[32]; snprintf(unset,sizeof(unset),"absent:%u",rand_r(&seed));
        argv[0]="MGET"; argl[0]=4; argv[1]=keys[0]; argl[1]=strlen(keys[0]);
        argv[2]=unset; argl[2]=strlen(unset); argv[3]=keys[1]; argl[3]=strlen(keys[1]);
        r=redisCommandArgv(c,4,argv,argl);
        if(r && r->type==REDIS_REPLY_ARRAY && r->elements==3){ s->checked+=3;
            if(!(r->element[0]->type==REDIS_REPLY_STRING && strcmp(r->element[0]->str,vals[0])==0)) s->corrupt++;
            if(r->element[1]->type!=REDIS_REPLY_NIL) s->badnil++;
            if(!(r->element[2]->type==REDIS_REPLY_STRING && strcmp(r->element[2]->str,vals[1])==0)) s->corrupt++;
        } else if(r){ s->corrupt++; }
        if(r) freeReplyObject(r);
    }
    redisFree(c); return NULL;
}

int main(int argc,char**argv){
    if(argc>1)g_host=argv[1]; if(argc>2)g_port=atoi(argv[2]); if(argc>3)g_threads=atoi(argv[3]);
    if(argc>4)g_nkeys=atoi(argv[4]); if(argc>5)g_secs=atoi(argv[5]); if(argc>6)g_keyspace=atol(argv[6]);
    if(g_nkeys>256)g_nkeys=256;
    st_t *s=calloc(g_threads,sizeof(st_t)); pthread_t *t=calloc(g_threads,sizeof(pthread_t));
    for(int i=0;i<g_threads;i++) pthread_create(&t[i],NULL,worker,&s[i]);
    sleep(g_secs); g_stop=1;
    for(int i=0;i<g_threads;i++) pthread_join(t[i],NULL);
    st_t T={0}; for(int i=0;i<g_threads;i++){ T.mset+=s[i].mset;T.mget+=s[i].mget;T.checked+=s[i].checked;
        T.corrupt+=s[i].corrupt;T.errors+=s[i].errors;T.badnil+=s[i].badnil; }
    printf("nkeys/cmd=%d threads=%d keyspace=%ld\n",g_nkeys,g_threads,g_keyspace);
    printf("MSET=%ld MGET=%ld positions-checked=%ld  CORRUPT=%ld  bad-nil=%ld  errors=%ld\n",
        T.mset,T.mget,T.checked,T.corrupt,T.badnil,T.errors);
    printf("VERDICT: %s\n",(T.corrupt==0 && T.badnil==0 && T.errors==0)?"OK":"DEFECTS");
    return (T.corrupt||T.badnil||T.errors)?2:0;
}
