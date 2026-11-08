// Single-pass instruction audit of a serverless witness; no clock/perf events.
// Count actual user instructions through the named policy boundary using ptrace.
#include <sys/ptrace.h>
#include <sys/user.h>
#include <sys/wait.h>
#include <unistd.h>
#include <cstdio>
#include <cstdlib>
#include <cerrno>
#include <cstring>
#include <fstream>
#include <string>
#include <stdexcept>

static void check(bool ok,const char* what) {if(!ok)throw std::runtime_error(what);}
static long peek(pid_t p,unsigned long address){errno=0;long v=ptrace(PTRACE_PEEKTEXT,p,address,nullptr);check(!errno,"peek");return v;}
static void wait_stop(pid_t p){int status=0;check(waitpid(p,&status,0)==p,"wait");check(WIFSTOPPED(status)&&WSTOPSIG(status)==SIGTRAP,"expected instruction trap");}
int main(int argc,char** argv){
    if(argc!=7){std::fprintf(stderr,"usage: trace WITNESS CASE SYMBOL TEXT_START TEXT_SIZE PIE\n");return 2;}
    pid_t child=-1;
    try{
        const unsigned long offset=std::stoul(argv[3],nullptr,16),text_start=std::stoul(argv[4],nullptr,16),text_size=std::stoul(argv[5],nullptr,16);
        const bool pie=std::stoi(argv[6]);
        child=fork();check(child>=0,"fork");
        if(child==0){check(ptrace(PTRACE_TRACEME,0,nullptr,nullptr)==0,"traceme");execl(argv[1],argv[1],argv[2],nullptr);_exit(127);}
        wait_stop(child);unsigned long base=0;
        if(pie){std::ifstream maps("/proc/"+std::to_string(child)+"/maps");std::string line;bool found=false;
            while(std::getline(maps,line)){unsigned long lo,hi,off;char permissions[8];
                if(std::sscanf(line.c_str(),"%lx-%lx %7s %lx",&lo,&hi,permissions,&off)==4 && off==0 && line.find(argv[1])!=std::string::npos){base=lo;found=true;break;}}
            check(found,"PIE mapping");}
        const unsigned long start=base+offset;const long word=peek(child,start);
        check(ptrace(PTRACE_POKETEXT,child,start,(word&~0xffL)|0xcc)==0,"breakpoint");
        check(ptrace(PTRACE_CONT,child,nullptr,nullptr)==0,"continue");wait_stop(child);
        user_regs_struct regs{};check(ptrace(PTRACE_GETREGS,child,nullptr,&regs)==0,"registers");check(regs.rip==start+1,"named boundary reached");
        check(ptrace(PTRACE_POKETEXT,child,start,word)==0,"restore instruction");regs.rip=start;
        check(ptrace(PTRACE_SETREGS,child,nullptr,&regs)==0,"rewind");const unsigned long target=peek(child,regs.rsp);
        unsigned long count=0,local=0;
        while(regs.rip!=target){check(count<5000000,"instruction bound");++count;
            if(regs.rip>=base+text_start && regs.rip<base+text_start+text_size)++local;
            check(ptrace(PTRACE_SINGLESTEP,child,nullptr,nullptr)==0,"step");wait_stop(child);
            check(ptrace(PTRACE_GETREGS,child,nullptr,&regs)==0,"registers");}
        check(ptrace(PTRACE_DETACH,child,nullptr,nullptr)==0,"detach");int status=0;check(waitpid(child,&status,0)==child,"exit wait");child=-1;
        check(WIFEXITED(status)&&WEXITSTATUS(status)==0,"witness success");
        std::printf("TRACE={\"instructions\":%lu,\"executable_instructions\":%lu,\"library_instructions\":%lu}\n",count,local,count-local);
    }catch(const std::exception& e){if(child>0){kill(child,SIGKILL);waitpid(child,nullptr,0);}std::fprintf(stderr,"FAIL instruction audit: %s\n",e.what());return 1;}
}
