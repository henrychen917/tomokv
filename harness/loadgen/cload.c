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
 *   ./cload -p 7800 -t 8 -P 32 -d 10 -c mixed -r 0.5 -s 1 -w -1 -W 8 -n 1000000 -v 64
 *
 * -w -1 spreads across all workers (uniform). -c mixed uses -r as the SET fraction (0.1 => 1:9).
 * The command/key stream is deterministic for a fixed option set and seed. Output is key=value so
 * benchmark coordinators can join it with an externally attached `perf stat` window.
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
#include <errno.h>
#include <sys/time.h>
#include <ctype.h>
#include <limits.h>

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
static char  g_host[64]="127.0.0.1", g_variant[64]="unspecified", g_start_gate[PATH_MAX]="";
static int   g_port=7800, g_threads=8, g_pipe=64, g_W=8, g_target=-1, g_io_timeout=5;
static double g_dur=10.0;
static long  g_keyspace=1000000; static int g_valsize=64; static double g_setfrac=0.0;
enum {C_GET,C_SET,C_BITCOUNT,C_MIXED,C_MGET,C_MSET}; static int g_cmd=C_GET;
static int g_mkeys=8;   /* keys per multi-key (MGET/MSET) command */
static int g_session=0; /* per-client locality: each connection (thread) uses its OWN keyspace ("c<tid>_<n>")
                         * — models pub/sub publishers / session apps; tests the client-aware predictor. */
static unsigned g_seed=1;
static unsigned g_set_threshold=0;
static long long g_hop_ns=-1;
static _Atomic int g_stop=0;
static _Atomic long long g_issued=0, g_completed=0, g_scored=0;
static _Atomic long long g_connect_errors=0, g_io_errors=0, g_server_errors=0, g_thread_errors=0;
static uint64_t g_deadline_ns=0;
static size_t g_output_capacity=0;
static pthread_mutex_t g_gate_mu=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_gate_cv=PTHREAD_COND_INITIALIZER;
static int g_ready=0, g_go=0;

static uint64_t monotonic_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC,&ts);
    return (uint64_t)ts.tv_sec*1000000000ULL+(uint64_t)ts.tv_nsec;
}

static void gate_ready_and_wait(void) {
    pthread_mutex_lock(&g_gate_mu);
    g_ready++;
    pthread_cond_broadcast(&g_gate_cv);
    while(!g_go) pthread_cond_wait(&g_gate_cv,&g_gate_mu);
    pthread_mutex_unlock(&g_gate_mu);
}

static const char *command_name(void) {
    static const char *names[]={"get","set","bitcount","mixed","mget","mset"};
    return names[g_cmd];
}

/* Key names are at most 47 bytes. Leave generous RESP framing headroom per key and reject
 * configurations whose complete pipeline would not fit the single send buffer. */
static int set_output_capacity(void) {
    uint64_t per_command=128;
    if(g_cmd==C_SET||g_cmd==C_MIXED) per_command+=(uint64_t)g_valsize;
    else if(g_cmd==C_MGET) per_command+=(uint64_t)g_mkeys*128;
    else if(g_cmd==C_MSET) per_command+=(uint64_t)g_mkeys*((uint64_t)g_valsize+128);
    uint64_t total=per_command*(uint64_t)g_pipe+1;
    if(total>512ULL*1024*1024||total>(uint64_t)INT_MAX) return 0;
    g_output_capacity=(size_t)total;
    return 1;
}

/* build a per-thread pool of keys that hash to g_target (or any key if target<0).
 * session mode: keys are namespaced by thread id ("c<tid>_<n>") so each connection has its OWN set. */
static char**build_pool(int *out_n,int tid){
    int cap = (g_target<0)? 4096 : 8192, n=0;
    char**pool=malloc(sizeof(char*)*cap);
    if(!pool){*out_n=0;return NULL;}
    long i=0, search_limit=g_keyspace<40000000L?g_keyspace:40000000L;
    while(n<cap&&i<search_limit){
        char buf[48]; int len = g_session ? snprintf(buf,sizeof buf,"c%d_%ld",tid,i)
                                           : snprintf(buf,sizeof buf,"k%ld",i); i++;
        if(g_target>=0 && key_worker(buf,g_W)!=g_target) continue;
        pool[n]=malloc(len+1);
        if(!pool[n]){for(int j=0;j<n;j++)free(pool[j]);free(pool);*out_n=0;return NULL;}
        memcpy(pool[n],buf,len+1); n++;
    }
    *out_n=n; return pool;
}

static int connect_srv(void){
    int fd=socket(AF_INET,SOCK_STREAM,0); if(fd<0)return -1;
    int one=1; setsockopt(fd,IPPROTO_TCP,TCP_NODELAY,&one,sizeof one);
    struct timeval tv={.tv_sec=g_io_timeout,.tv_usec=0};
    setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&tv,sizeof tv);
    setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&tv,sizeof tv);
    struct sockaddr_in a={0}; a.sin_family=AF_INET; a.sin_port=htons(g_port);
    if(inet_pton(AF_INET,g_host,&a.sin_addr)!=1){close(fd);return -1;}
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
    if(t=='*'){
        if(rline(r,&v))return -1;
        for(long i=0;i<v;i++){int rc=read_reply(r);if(rc)return rc;}
        return 0;
    }
    if(t=='-') return rline(r,&v)?-1:1; /* valid RESP error reply */
    if(t=='+'||t==':') return rline(r,&v);
    return -1;
}

static void*worker(void*arg){
    int tid=(int)(intptr_t)arg; int fd=connect_srv();
    if(fd<0){
        __atomic_fetch_add(&g_connect_errors,1,__ATOMIC_RELAXED);
        __atomic_store_n(&g_stop,1,__ATOMIC_RELEASE);
        gate_ready_and_wait();
        return 0;
    }
    int np=0; char**pool=build_pool(&np,tid);
    char*val=malloc(g_valsize>1?g_valsize:1);
    struct rdr r={.fd=fd};
    char*ob=malloc(g_output_capacity); unsigned ki=0;
    unsigned rng=g_seed^(0x9e3779b9u*(unsigned)(tid+1));
    if(!pool||np<=0||!val||!ob){
        __atomic_fetch_add(&g_thread_errors,1,__ATOMIC_RELAXED);
        __atomic_store_n(&g_stop,1,__ATOMIC_RELEASE);
        gate_ready_and_wait();
        if(pool){for(int i=0;i<np;i++)free(pool[i]);free(pool);}
        free(val); free(ob);
        close(fd);
        return 0;
    }
    memset(val,'x',g_valsize>1?g_valsize:1);
    if(getenv("CLOAD_DEBUG")) fprintf(stderr,"[dbg] connected fd=%d np=%d firstkey=%s\n",fd,np,pool[0]);
    gate_ready_and_wait();
    while(!__atomic_load_n(&g_stop,__ATOMIC_ACQUIRE)&&monotonic_ns()<g_deadline_ns){
        int olen=0;
        for(int i=0;i<g_pipe;i++){
            const char*k=pool[ki++ % np];
            if(g_cmd==C_MGET){
                olen+=sprintf(ob+olen,"*%d\r\n$4\r\nMGET\r\n",g_mkeys+1);
                for(int j=0;j<g_mkeys;j++){const char*mk=pool[ki++ % np];olen+=sprintf(ob+olen,"$%zu\r\n%s\r\n",strlen(mk),mk);}
                continue;
            }
            if(g_cmd==C_MSET){
                olen+=sprintf(ob+olen,"*%d\r\n$4\r\nMSET\r\n",2*g_mkeys+1);
                for(int j=0;j<g_mkeys;j++){const char*mk=pool[ki++ % np];olen+=sprintf(ob+olen,"$%zu\r\n%s\r\n$%d\r\n",strlen(mk),mk,g_valsize);memcpy(ob+olen,val,g_valsize);olen+=g_valsize;olen+=sprintf(ob+olen,"\r\n");}
                continue;
            }
            int isset = (g_cmd==C_SET) ||
                (g_cmd==C_MIXED && ((rng=rng*1103515245u+12345u)>>8)<g_set_threshold);
            if(isset)
                olen+=sprintf(ob+olen,"*3\r\n$3\r\nSET\r\n$%zu\r\n%s\r\n$%d\r\n",strlen(k),k,g_valsize),
                memcpy(ob+olen,val,g_valsize), olen+=g_valsize, olen+=sprintf(ob+olen,"\r\n");
            else if(g_cmd==C_BITCOUNT)
                olen+=sprintf(ob+olen,"*2\r\n$8\r\nBITCOUNT\r\n$%zu\r\n%s\r\n",strlen(k),k);
            else
                olen+=sprintf(ob+olen,"*2\r\n$3\r\nGET\r\n$%zu\r\n%s\r\n",strlen(k),k);
        }
        int off=0;
        while(off<olen){
            int w=send(fd,ob+off,olen-off,MSG_NOSIGNAL);
            if(w<=0){
                __atomic_fetch_add(&g_io_errors,1,__ATOMIC_RELAXED);
                __atomic_store_n(&g_stop,1,__ATOMIC_RELEASE);
                break;
            }
            off+=w;
        }
        if(off!=olen) break;
        __atomic_fetch_add(&g_issued,g_pipe,__ATOMIC_RELAXED);
        if(__atomic_load_n(&g_completed,__ATOMIC_RELAXED)==0 && getenv("CLOAD_DEBUG"))
            fprintf(stderr,"[dbg] sent olen=%d off=%d\n",olen,off);
        int done=0;
        for(int i=0;i<g_pipe;i++){
            int rc=read_reply(&r);
            if(rc<0){
                if(__atomic_load_n(&g_completed,__ATOMIC_RELAXED)==0&&getenv("CLOAD_DEBUG"))
                    fprintf(stderr,"[dbg] read_reply failed at i=%d\n",i);
                __atomic_fetch_add(&g_io_errors,1,__ATOMIC_RELAXED);
                __atomic_store_n(&g_stop,1,__ATOMIC_RELEASE);
                break;
            }
            done++;
            if(rc>0){
                __atomic_fetch_add(&g_server_errors,1,__ATOMIC_RELAXED);
                __atomic_store_n(&g_stop,1,__ATOMIC_RELEASE);
                break;
            }
        }
        __atomic_fetch_add(&g_completed,done,__ATOMIC_RELAXED);
        if(monotonic_ns()<=g_deadline_ns)
            __atomic_fetch_add(&g_scored,done,__ATOMIC_RELAXED);
        if(done!=g_pipe) break;
    }
    for(int i=0;i<np;i++) free(pool[i]);
    free(pool); free(val); free(ob); close(fd); return 0;
}

static void usage(FILE *out,const char *prog) {
    fprintf(out,
        "usage: %s [-h host] [-p port] [-t threads] [-P pipeline] [-d seconds]\n"
        "          [-c get|set|bitcount|mixed|mget|mset] [-r set_fraction]\n"
        "          [-w target_worker] [-W workers] [-n key_search_limit] [-v value_bytes]\n"
        "          [-k multi_keys] [-S] [-s seed] [-T io_timeout_seconds]\n"
        "          [-G start_gate_file] [-H simulated_hop_ns] [-V variant]\n",prog);
}

static const char *option_value(int argc,char **argv,int *index) {
    if(*index+1>=argc){
        fprintf(stderr,"missing value for %s\n",argv[*index]);
        usage(stderr,argv[0]);
        exit(2);
    }
    return argv[++*index];
}

static int safe_label(const char *s) {
    if(!*s)return 0;
    for(;*s;s++) if(!(isalnum((unsigned char)*s)||*s=='_'||*s=='-'||*s=='.')) return 0;
    return 1;
}

int main(int argc,char**argv){
    for(int i=1;i<argc;i++){
        if(!strcmp(argv[i],"--help")){usage(stdout,argv[0]);return 0;}
        else if(!strcmp(argv[i],"-h"))snprintf(g_host,sizeof g_host,"%s",option_value(argc,argv,&i));
        else if(!strcmp(argv[i],"-p"))g_port=atoi(option_value(argc,argv,&i));
        else if(!strcmp(argv[i],"-t"))g_threads=atoi(option_value(argc,argv,&i));
        else if(!strcmp(argv[i],"-P"))g_pipe=atoi(option_value(argc,argv,&i));
        else if(!strcmp(argv[i],"-d"))g_dur=strtod(option_value(argc,argv,&i),NULL);
        else if(!strcmp(argv[i],"-w"))g_target=atoi(option_value(argc,argv,&i));
        else if(!strcmp(argv[i],"-W"))g_W=atoi(option_value(argc,argv,&i));
        else if(!strcmp(argv[i],"-n"))g_keyspace=atol(option_value(argc,argv,&i));
        else if(!strcmp(argv[i],"-v"))g_valsize=atoi(option_value(argc,argv,&i));
        else if(!strcmp(argv[i],"-r"))g_setfrac=strtod(option_value(argc,argv,&i),NULL);
        else if(!strcmp(argv[i],"-k"))g_mkeys=atoi(option_value(argc,argv,&i));
        else if(!strcmp(argv[i],"-s"))g_seed=(unsigned)strtoul(option_value(argc,argv,&i),NULL,0);
        else if(!strcmp(argv[i],"-T"))g_io_timeout=atoi(option_value(argc,argv,&i));
        else if(!strcmp(argv[i],"-G")){
            const char *gate=option_value(argc,argv,&i);
            if(snprintf(g_start_gate,sizeof g_start_gate,"%s",gate)>=(int)sizeof g_start_gate){
                fprintf(stderr,"start gate path is too long\n");return 2;
            }
        }
        else if(!strcmp(argv[i],"-H"))g_hop_ns=strtoll(option_value(argc,argv,&i),NULL,0);
        else if(!strcmp(argv[i],"-V"))snprintf(g_variant,sizeof g_variant,"%s",option_value(argc,argv,&i));
        else if(!strcmp(argv[i],"-S"))g_session=1;
        else if(!strcmp(argv[i],"-c")){
            const char*c=option_value(argc,argv,&i);
            if(!strcmp(c,"get"))g_cmd=C_GET;
            else if(!strcmp(c,"set"))g_cmd=C_SET;
            else if(!strcmp(c,"bitcount"))g_cmd=C_BITCOUNT;
            else if(!strcmp(c,"mixed"))g_cmd=C_MIXED;
            else if(!strcmp(c,"mget"))g_cmd=C_MGET;
            else if(!strcmp(c,"mset"))g_cmd=C_MSET;
            else {fprintf(stderr,"unknown command mode: %s\n",c);return 2;}
        } else {fprintf(stderr,"unknown option: %s\n",argv[i]);usage(stderr,argv[0]);return 2;}
    }
    if(g_port<=0||g_port>65535||g_threads<=0||g_threads>1024||g_pipe<=0||g_pipe>4096||
       g_dur<=0||g_dur!=g_dur||g_dur>86400||g_W<=0||g_target>=g_W||g_target<-1||
       g_keyspace<=0||g_valsize<0||g_setfrac!=g_setfrac||g_setfrac<0||g_setfrac>1||
       g_mkeys<=0||g_mkeys>4096||g_io_timeout<=0||g_hop_ns<-1||
       !safe_label(g_variant)||!set_output_capacity()){
        fprintf(stderr,"invalid option value\n");usage(stderr,argv[0]);return 2;
    }
    g_set_threshold=g_setfrac>=1.0?(1u<<24):(unsigned)(g_setfrac*(double)(1u<<24));

    pthread_t th[1024]; int created=0;
    for(int i=0;i<g_threads;i++){
        if(pthread_create(&th[created],0,worker,(void*)(intptr_t)i)==0) created++;
        else __atomic_fetch_add(&g_thread_errors,1,__ATOMIC_RELAXED);
    }

    pthread_mutex_lock(&g_gate_mu);
    while(g_ready<created) pthread_cond_wait(&g_gate_cv,&g_gate_mu);
    uint64_t duration_ns=(uint64_t)(g_dur*1000000000.0);
    long long setup_errors=__atomic_load_n(&g_connect_errors,__ATOMIC_RELAXED)+
                           __atomic_load_n(&g_thread_errors,__ATOMIC_RELAXED);
    printf("CLOAD_READY variant=%s hop_ns=%lld seed=%u deterministic=yes gate=%s requested_threads=%d ready_threads=%d setup_errors=%lld\n",
           g_variant,g_hop_ns,g_seed,*g_start_gate?"enabled":"disabled",g_threads,g_ready,setup_errors);
    fflush(stdout);
    if(*g_start_gate){
        uint64_t gate_deadline=monotonic_ns()+60000000000ULL;
        while(access(g_start_gate,F_OK)!=0&&monotonic_ns()<gate_deadline){
            struct timespec pause={.tv_sec=0,.tv_nsec=100000};
            nanosleep(&pause,NULL);
        }
        if(access(g_start_gate,F_OK)!=0){
            __atomic_fetch_add(&g_thread_errors,1,__ATOMIC_RELAXED);
            __atomic_store_n(&g_stop,1,__ATOMIC_RELEASE);
            setup_errors++;
        }
    }
    uint64_t start_ns=monotonic_ns();
    g_deadline_ns=start_ns+duration_ns;
    g_go=1;
    pthread_cond_broadcast(&g_gate_cv);
    pthread_mutex_unlock(&g_gate_mu);

    if(setup_errors==0){
        struct timespec until={.tv_sec=(time_t)(g_deadline_ns/1000000000ULL),
                               .tv_nsec=(long)(g_deadline_ns%1000000000ULL)};
        while(clock_nanosleep(CLOCK_MONOTONIC,TIMER_ABSTIME,&until,NULL)==EINTR){}
    }
    __atomic_store_n(&g_stop,1,__ATOMIC_RELEASE);
    for(int i=0;i<created;i++) pthread_join(th[i],0);
    uint64_t end_ns=monotonic_ns();

    long long issued=__atomic_load_n(&g_issued,__ATOMIC_RELAXED);
    long long completed=__atomic_load_n(&g_completed,__ATOMIC_RELAXED);
    long long scored=__atomic_load_n(&g_scored,__ATOMIC_RELAXED);
    long long connect_errors=__atomic_load_n(&g_connect_errors,__ATOMIC_RELAXED);
    long long io_errors=__atomic_load_n(&g_io_errors,__ATOMIC_RELAXED);
    long long server_errors=__atomic_load_n(&g_server_errors,__ATOMIC_RELAXED);
    long long thread_errors=__atomic_load_n(&g_thread_errors,__ATOMIC_RELAXED);
    long long errors=connect_errors+io_errors+server_errors+thread_errors;
    long long outstanding=issued-completed;
    uint64_t elapsed_ns=end_ns-start_ns;
    uint64_t drain_ns=elapsed_ns>duration_ns?elapsed_ns-duration_ns:0;
    double ops_per_sec=(double)scored/g_dur;
    int healthy=errors==0&&outstanding==0&&scored>0&&created==g_threads;
    printf("CLOAD_RESULT variant=%s hop_ns=%lld seed=%u command=%s set_fraction=%.6f duration_ns=%llu elapsed_ns=%llu drain_ns=%llu host=%s port=%d threads=%d pipeline=%d target_worker=%d workers=%d key_search_limit=%ld value_bytes=%d session=%s scored_ops=%lld issued=%lld completed=%lld outstanding=%lld ops_per_sec=%.3f\n",
           g_variant,g_hop_ns,g_seed,command_name(),
           g_setfrac,
           (unsigned long long)duration_ns,(unsigned long long)elapsed_ns,(unsigned long long)drain_ns,
           g_host,g_port,g_threads,g_pipe,g_target,g_W,g_keyspace,g_valsize,g_session?"yes":"no",
           scored,issued,completed,outstanding,ops_per_sec);
    printf("CLOAD_HEALTH healthy=%s errors=%lld connect_errors=%lld io_errors=%lld server_errors=%lld thread_errors=%lld outstanding=%lld\n",
           healthy?"yes":"no",errors,connect_errors,io_errors,server_errors,thread_errors,outstanding);
    return healthy?0:1;
}
