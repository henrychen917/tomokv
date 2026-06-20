/* cload — fast, worker-targeting load generator for THredis.
 *
 * Raw-socket RESP + deep pipelining + N threads => saturates the server (unlike the Python
 * generators, which become client-bound ~1.5M ops/s). Targets ONE worker's keys via an embedded
 * bit-exact copy of THredis's seedless xxh64 (server.c), so you can create controlled worker-skew
 * and actually measure the worker-bound regime where load-balancing matters.
 *
 *   gcc -O3 -o cload cload.c -lpthread
 *   ./cload -p 7800 -t 8 -P 64 -d 10 -c get -w 2 -W 8 -n 300000      # GET, keys on worker 2 of 8
 *   ./cload -p 7800 -t 8 -P 64 -d 10 -c bitcount -w 2 -W 8 -n 20000  # worker-CPU-heavy
 *   ./cload -p 7800 -t 8 -P 32 -d 10 -c mixed -r 0.5 -w -1 -W 8 -n 1000000 -v 64   # 1:1, all workers
 *
 * -w -1 spreads across all workers (uniform). -c mixed uses -r as the SET fraction (0.1 => 1:9).
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <pthread.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <time.h>

/* ---- xxh64 (seedless), byte-identical to THredis server.c ---- */
#define P1 0x9E3779B185EBCA87ULL
#define P2 0xC2B2AE3D27D4EB4FULL
#define P3 0x165667B19E3779F9ULL
#define P4 0x85EBCA77C2B2AE63ULL
#define P5 0x27D4EB2F165667C5ULL
static inline uint64_t rotl(uint64_t x,int r){return (x<<r)|(x>>(64-r));}
static inline uint64_t rd64(const uint8_t*p){uint64_t v;memcpy(&v,p,8);return v;}
static inline uint32_t rd32(const uint8_t*p){uint32_t v;memcpy(&v,p,4);return v;}
static inline uint64_t round_(uint64_t a,uint64_t in){a+=in*P2;a=rotl(a,31);a*=P1;return a;}
static inline uint64_t merge_(uint64_t a,uint64_t v){v=round_(0,v);a^=v;a=a*P1+P4;return a;}
static uint64_t xxh64(const void*in,size_t len){
    const uint8_t*p=in,*end=p+len; uint64_t h;
    if(len>=32){uint64_t v1=P1+P2,v2=P2,v3=0,v4=0-P1;
        do{v1=round_(v1,rd64(p));p+=8;v2=round_(v2,rd64(p));p+=8;
           v3=round_(v3,rd64(p));p+=8;v4=round_(v4,rd64(p));p+=8;}while(p+32<=end);
        h=rotl(v1,1)+rotl(v2,7)+rotl(v3,12)+rotl(v4,18);
        h=merge_(h,v1);h=merge_(h,v2);h=merge_(h,v3);h=merge_(h,v4);
    } else h=P5;
    h+=(uint64_t)len;
    while(p+8<=end){h^=round_(0,rd64(p));h=rotl(h,27)*P1+P4;p+=8;}
    if(p+4<=end){h^=(uint64_t)rd32(p)*P1;h=rotl(h,23)*P2+P3;p+=4;}
    while(p<end){h^=(*p)*P5;h=rotl(h,11)*P1;p++;}
    h^=h>>33;h*=P2;h^=h>>29;h*=P3;h^=h>>32;return h;
}
#define BUCKETS 4096
static int key_worker(const char*k,int W){ return (int)((xxh64(k,strlen(k))&(BUCKETS-1)) * W / BUCKETS); }

/* ---- config ---- */
static char  g_host[64]="127.0.0.1";
static int   g_port=7800, g_threads=8, g_pipe=64, g_dur=10, g_W=8, g_target=-1;
static long  g_keyspace=1000000; static int g_valsize=64; static double g_setfrac=0.0;
enum {C_GET,C_SET,C_BITCOUNT,C_MIXED}; static int g_cmd=C_GET;
static volatile int g_stop=0;
static _Atomic long long g_ops=0;

/* build a per-thread pool of keys that hash to g_target (or any key if target<0) */
static char**build_pool(int *out_n){
    int cap = (g_target<0)? 4096 : 8192, n=0;
    char**pool=malloc(sizeof(char*)*cap);
    long i=0;
    while(n<cap){
        char buf[32]; int len=snprintf(buf,sizeof buf,"k%ld",i); i++;
        if(g_target>=0 && key_worker(buf,g_W)!=g_target) continue;
        pool[n]=malloc(len+1); memcpy(pool[n],buf,len+1); n++;
        if(i>40000000L) break;
    }
    *out_n=n; return pool;
}

static int connect_srv(void){
    int fd=socket(AF_INET,SOCK_STREAM,0); if(fd<0)return -1;
    int one=1; setsockopt(fd,IPPROTO_TCP,TCP_NODELAY,&one,sizeof one);
    struct sockaddr_in a={0}; a.sin_family=AF_INET; a.sin_port=htons(g_port);
    inet_pton(AF_INET,g_host,&a.sin_addr);
    if(connect(fd,(struct sockaddr*)&a,sizeof a)<0){close(fd);return -1;}
    return fd;
}

/* minimal pipelined RESP reply consumer: parse exactly `count` top-level replies from fd */
struct rdr{int fd; unsigned char buf[1<<16]; int pos,end;};
static int rfill(struct rdr*r){ if(r->pos<r->end)return 1; r->pos=0; r->end=recv(r->fd,r->buf,sizeof r->buf,0); return r->end>0; }
static int rbyte(struct rdr*r){ if(!rfill(r))return -1; return r->buf[r->pos++]; }
static int rline(struct rdr*r,long*val){ /* read until \n, parse leading int into *val */
    long v=0,sign=1; int seen=0,first=1;
    for(;;){int c=rbyte(r); if(c<0)return -1; if(c=='\r')continue; if(c=='\n')break;
        if(first&&c=='-'){sign=-1;first=0;continue;} first=0;
        if(c>='0'&&c<='9'){v=v*10+(c-'0');seen=1;} }
    if(val)*val=seen?sign*v:0; return 0;
}
static int rskip(struct rdr*r,long n){ /* consume n+2 bytes (bulk body+crlf) */
    n+=2; while(n>0){ if(r->pos>=r->end && !rfill(r))return -1; int avail=r->end-r->pos; int take=avail<n?avail:(int)n; r->pos+=take; n-=take; } return 0;
}
static int read_reply(struct rdr*r){
    int t=rbyte(r); if(t<0)return -1; long v;
    if(t=='$'){ if(rline(r,&v))return -1; if(v>=0) return rskip(r,v); return 0; }
    if(t=='*'){ if(rline(r,&v))return -1; for(long i=0;i<v;i++) if(read_reply(r))return -1; return 0; }
    return rline(r,&v); /* +, -, : */
}

static void*worker(void*arg){
    (void)arg; int fd=connect_srv(); if(fd<0){fprintf(stderr,"connect failed\n");return 0;}
    int np; char**pool=build_pool(&np);
    if(getenv("CLOAD_DEBUG")) fprintf(stderr,"[dbg] connected fd=%d np=%d firstkey=%s\n",fd,np,np?pool[0]:"NONE");
    char*val=malloc(g_valsize>1?g_valsize:1); memset(val,'x',g_valsize>1?g_valsize:1);
    struct rdr r={.fd=fd};
    char*ob=malloc(1<<20); long ops=0; unsigned ki=0; unsigned rng=(unsigned)(uintptr_t)pool;
    while(!g_stop){
        int olen=0;
        for(int i=0;i<g_pipe;i++){
            const char*k=pool[ki++ % np];
            int isset = (g_cmd==C_SET) || (g_cmd==C_MIXED && ((rng=rng*1103515245u+12345u)>>8)*1.0/(1u<<24) < g_setfrac);
            if(isset)
                olen+=sprintf(ob+olen,"*3\r\n$3\r\nSET\r\n$%zu\r\n%s\r\n$%d\r\n",strlen(k),k,g_valsize),
                memcpy(ob+olen,val,g_valsize), olen+=g_valsize, olen+=sprintf(ob+olen,"\r\n");
            else if(g_cmd==C_BITCOUNT)
                olen+=sprintf(ob+olen,"*2\r\n$8\r\nBITCOUNT\r\n$%zu\r\n%s\r\n",strlen(k),k);
            else
                olen+=sprintf(ob+olen,"*2\r\n$3\r\nGET\r\n$%zu\r\n%s\r\n",strlen(k),k);
        }
        int off=0; while(off<olen){int w=send(fd,ob+off,olen-off,0); if(w<=0){g_stop=1;break;} off+=w;}
        if(ops==0 && getenv("CLOAD_DEBUG")) fprintf(stderr,"[dbg] sent olen=%d off=%d\n",olen,off);
        for(int i=0;i<g_pipe;i++){ if(read_reply(&r)){if(ops==0&&getenv("CLOAD_DEBUG"))fprintf(stderr,"[dbg] read_reply failed at i=%d\n",i);g_stop=1;break;} }
        ops+=g_pipe;
    }
    __atomic_fetch_add(&g_ops,ops,__ATOMIC_RELAXED); close(fd); return 0;
}

int main(int argc,char**argv){
    for(int i=1;i<argc-1;i++){
        if(!strcmp(argv[i],"-h"))strncpy(g_host,argv[++i],63);
        else if(!strcmp(argv[i],"-p"))g_port=atoi(argv[++i]);
        else if(!strcmp(argv[i],"-t"))g_threads=atoi(argv[++i]);
        else if(!strcmp(argv[i],"-P"))g_pipe=atoi(argv[++i]);
        else if(!strcmp(argv[i],"-d"))g_dur=atoi(argv[++i]);
        else if(!strcmp(argv[i],"-w"))g_target=atoi(argv[++i]);
        else if(!strcmp(argv[i],"-W"))g_W=atoi(argv[++i]);
        else if(!strcmp(argv[i],"-n"))g_keyspace=atol(argv[++i]);
        else if(!strcmp(argv[i],"-v"))g_valsize=atoi(argv[++i]);
        else if(!strcmp(argv[i],"-r"))g_setfrac=atof(argv[++i]);
        else if(!strcmp(argv[i],"-c")){const char*c=argv[++i];
            g_cmd = !strcmp(c,"set")?C_SET : !strcmp(c,"bitcount")?C_BITCOUNT : !strcmp(c,"mixed")?C_MIXED : C_GET;}
    }
    pthread_t th[1024];
    struct timespec t0,t1; clock_gettime(CLOCK_MONOTONIC,&t0);
    for(int i=0;i<g_threads;i++) pthread_create(&th[i],0,worker,0);
    struct timespec ts={g_dur,0}; nanosleep(&ts,0); g_stop=1;
    for(int i=0;i<g_threads;i++) pthread_join(th[i],0);
    clock_gettime(CLOCK_MONOTONIC,&t1);
    double sec=(t1.tv_sec-t0.tv_sec)+(t1.tv_nsec-t0.tv_nsec)/1e9;
    long long ops=__atomic_load_n(&g_ops,__ATOMIC_RELAXED);
    printf("%lld ops in %.1fs = %.0f ops/sec (%d threads, pipeline %d, cmd %d, worker %d/%d)\n",
           ops,sec,ops/sec,g_threads,g_pipe,g_cmd,g_target,g_W);
    return 0;
}
