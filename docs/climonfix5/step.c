// Finite serverless x86-64 instruction counter. No perf events or rate measurement.
// The parent owns its traced child; no attach to any existing process.
#include <sys/ptrace.h>
#include <sys/user.h>
#include <sys/wait.h>
#include <sys/prctl.h>
#include <unistd.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

typedef struct { unsigned long pc; unsigned len, kind, fn; } Insn;
static pid_t child;
static void fail(const char *s) { perror(s); if(child>0)kill(child,SIGKILL); exit(1); }
static long peek(unsigned long a) { errno=0;long v=ptrace(PTRACE_PEEKDATA,child,a,0);if(errno)fail("peek");return v; }
static void poke(unsigned long a,long v) { if(ptrace(PTRACE_POKEDATA,child,a,v))fail("poke"); }
static void stopped(void) { int s;if(waitpid(child,&s,0)!=child)fail("wait");if(!WIFSTOPPED(s)||WSTOPSIG(s)!=SIGTRAP){fprintf(stderr,"unexpected child status %x\n",s);fail("stop");} }
static struct user_regs_struct regs(void) { struct user_regs_struct r;if(ptrace(PTRACE_GETREGS,child,0,&r))fail("regs");return r; }
static void putregs(struct user_regs_struct *r) { if(ptrace(PTRACE_SETREGS,child,0,r))fail("setregs"); }
static void resume(int how) { if(ptrace(how,child,0,0))fail("resume");stopped(); }
static void until(unsigned long address) {
    long old=peek(address);poke(address,(old&~255L)|0xcc);
    resume(PTRACE_CONT);
    struct user_regs_struct r=regs();
    if(r.rip!=address+1)fail("breakpoint not reached");
    poke(address,old);r.rip=address;putregs(&r);
}
static Insn *at(Insn *a,size_t n,unsigned long pc) {
    size_t lo=0,hi=n;while(lo<hi){size_t mid=(lo+hi)/2;if(a[mid].pc<pc)lo=mid+1;else hi=mid;}
    return lo<n&&a[lo].pc==pc?&a[lo]:NULL;
}
int main(int argc,char **argv) {
    if(argc<5)return 2;
    FILE *f=fopen(argv[1],"r");if(!f)fail("plan");
    unsigned long begin,end;size_t n;unsigned nf;
    if(fscanf(f,"%lx %lx %zu %u",&begin,&end,&n,&nf)!=4)fail("header");
    Insn *ins=calloc(n,sizeof(*ins));uint64_t *counts=calloc(nf+1,sizeof(*counts));uint64_t *pc_counts=calloc(n,sizeof(*pc_counts));
    for(size_t i=0;i<n;i++)if(fscanf(f,"%lx %u %u %u",&ins[i].pc,&ins[i].len,&ins[i].kind,&ins[i].fn)!=4)fail("instruction");
    fclose(f);
    child=fork();if(child<0)fail("fork");
    if(!child){prctl(PR_SET_PDEATHSIG,SIGKILL);if(ptrace(PTRACE_TRACEME,0,0,0))_exit(125);execv(argv[3],argv+3);_exit(126);}
    stopped();ptrace(PTRACE_SETOPTIONS,child,0,PTRACE_O_EXITKILL);
    char path[64],line[4096];snprintf(path,sizeof(path),"/proc/%d/maps",child);
    f=fopen(path,"r");if(!f)fail("maps");
    unsigned long base=0;
    // The first mapping of the executable has file offset zero. Fixtures are PIE.
    while(fgets(line,sizeof(line),f))if(strstr(line,argv[3])){unsigned long offset;char perm[8];if(sscanf(line,"%lx-%*x %7s %lx",&base,perm,&offset)!=3||offset)fail("base");break;}
    fclose(f);if(!base)fail("missing executable map");
    until(base+begin);
    uint64_t steps=0,clocks=0,excluded=0;unsigned long previous=0;
    for(;steps<10000000;steps++) {
        struct user_regs_struct r=regs();if(r.rip==base+end)break;
        Insn *i=at(ins,n,r.rip-base);
        if(!i) {
            // A production wrapper can tail-jump through a PLT entry.
            unsigned long ret=(unsigned long)peek(r.rsp);
            if(!at(ins,n,ret-base)){fprintf(stderr,"external %llx prev %lx rsp %lx %lx %lx\n",r.rip-base,previous,ret-base,peek(r.rsp+8)-base,peek(r.rsp+16)-base);fail("unplanned external return");}
            excluded++;until(ret);continue;
        }
        previous=i->pc;
        if(i->fn){counts[i->fn]++;pc_counts[i-ins]++;}
        if(i->kind==2) {
            // Same deterministic clock as the established GDB fixture.
            poke(r.rsi,1000);poke(r.rsi+8,++clocks*1000);r.rax=0;r.rip+=i->len;putregs(&r);
        } else if(i->kind==1) {
            unsigned long ret=r.rip+i->len;resume(PTRACE_SINGLESTEP);
            struct user_regs_struct target=regs();Insn *callee=at(ins,n,target.rip-base);
            if(target.rip!=base+end && (!callee)){if(i->fn)excluded++;until(ret);}
        } else resume(PTRACE_SINGLESTEP);
    }
    if(steps==10000000)fail("trace bound");
    if(ptrace(PTRACE_CONT,child,0,0))fail("finish");
    int status;
    if(waitpid(child,&status,0)!=child||!WIFEXITED(status)||WEXITSTATUS(status))fail("fixture exact-data check");
    child=0;
    f=fopen(argv[2],"w");if(!f)fail("output");
    fprintf(f,"{\"steps\":%lu,\"clock_calls\":%lu,\"excluded_calls\":%lu,\"counts\":[",steps,clocks,excluded);
    for(unsigned j=0;j<=nf;j++)fprintf(f,"%s%lu",j?",":"",counts[j]);
    fprintf(f,"],\"pc_counts\":[");int first=1;for(size_t j=0;j<n;j++)if(pc_counts[j]){fprintf(f,"%s[%lu,%lu]",first?"":",",ins[j].pc,pc_counts[j]);first=0;}fprintf(f,"]}\n");fclose(f);
    return 0;
}
