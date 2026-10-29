// Bounded named-production instruction census. No sockets, PMU, or rate measurement.
// Library calls are skipped exactly as in the wave10 census's GDB reference tracer.
#include <sys/ptrace.h>
#include <sys/user.h>
#include <sys/wait.h>
#include <unistd.h>
#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
static void need(bool ok,const char* s){if(!ok)throw std::runtime_error(s);}
static unsigned long peek(pid_t p,unsigned long at){errno=0;auto v=ptrace(PTRACE_PEEKTEXT,p,at,nullptr);need(!errno,"peek");return v;}
static void stop(pid_t p){int s;need(waitpid(p,&s,0)==p,"wait");need(WIFSTOPPED(s)&&WSTOPSIG(s)==SIGTRAP,"instruction trap / fixture assertion");}
static void request(pid_t p,enum __ptrace_request op){need(ptrace(op,p,nullptr,nullptr)==0,"ptrace request");stop(p);}
static user_regs_struct regs(pid_t p){user_regs_struct r{};need(ptrace(PTRACE_GETREGS,p,nullptr,&r)==0,"get regs");return r;}
static void setregs(pid_t p,user_regs_struct& r){need(ptrace(PTRACE_SETREGS,p,nullptr,&r)==0,"set regs");}
static void to(pid_t p,unsigned long at){auto word=peek(p,at);need(ptrace(PTRACE_POKETEXT,p,at,(word&~255ul)|0xcc)==0,"set breakpoint");request(p,PTRACE_CONT);auto r=regs(p);need(r.rip==at+1,"breakpoint reached");need(ptrace(PTRACE_POKETEXT,p,at,word)==0,"restore breakpoint");r.rip=at;setregs(p,r);}
struct Range{unsigned long lo,hi;};
int main(int argc,char** argv){
 if(argc<7)return 2;
 pid_t child=-1;
 try{
  const std::string path=argv[1];
  auto begin=std::stoul(argv[3],nullptr,16),end=std::stoul(argv[4],nullptr,16),clock=std::stoul(argv[5],nullptr,16);
  std::vector<Range> ranges;std::ifstream in(argv[2]);Range x;while(in>>std::hex>>x.lo>>x.hi)ranges.push_back(x);
  std::sort(ranges.begin(),ranges.end(),[](auto a,auto b){return a.lo<b.lo||(a.lo==b.lo&&a.hi<b.hi);});
  std::vector<char*> args{argv[1]};for(int i=6;i<argc;i++)args.push_back(argv[i]);args.push_back(nullptr);
  child=fork();need(child>=0,"fork");
  if(!child){need(ptrace(PTRACE_TRACEME,0,nullptr,nullptr)==0,"traceme");execv(path.c_str(),args.data());_exit(127);}
  stop(child);unsigned long base=0;std::ifstream maps("/proc/"+std::to_string(child)+"/maps");std::string line;bool found=false;
  while(std::getline(maps,line)){unsigned long lo,hi,off;char perms[8];if(std::sscanf(line.c_str(),"%lx-%lx %7s %lx",&lo,&hi,perms,&off)==4&&off==0&&line.find(path)!=std::string::npos){base=lo;found=true;break;}}
  need(found,"PIE mapping");begin+=base;end+=base;clock+=base;
  auto included=[&](unsigned long pc){pc-=base;auto it=std::upper_bound(ranges.begin(),ranges.end(),pc,[](auto at,auto r){return at<r.lo;});return it!=ranges.begin()&&pc<(--it)->hi;};
  to(child,begin);auto r=regs(child);std::map<unsigned long,unsigned long> sites,raw,encoding;unsigned long steps=0,clocks=0,excluded=0,last=~0ul;bool last_rep=false;
  while(r.rip!=end){
   need(++steps<5000000,"bounded trace exhausted");auto pc=r.rip;
   auto [it,added]=encoding.try_emplace(pc,0);if(added)it->second=peek(child,pc);
   unsigned long bits=it->second;unsigned op=0,modrm=0;bool rep=false;
   for(unsigned i=0;i<8;i++){op=(bits>>(i*8))&255;modrm=i<7?(bits>>((i+1)*8))&255:0;
    if(op==0xf2||op==0xf3){rep=true;continue;}
    if((op>=0x40&&op<=0x4f)||op==0x66||op==0x67||op==0x26||op==0x2e||op==0x36||op==0x3e||op==0x64||op==0x65)continue;
    break;
   }
   if(included(pc)){++raw[pc-base];if(pc!=last||!last_rep)++sites[pc-base];}
   last=pc;last_rep=rep&&((op>=0xa4&&op<=0xa7)||(op>=0xaa&&op<=0xaf));
   const bool call=op==0xe8||(op==0xff&&((modrm>>3)&7)==2);
   request(child,PTRACE_SINGLESTEP);r=regs(child);
   if(call&&r.rip!=end&&!included(r.rip)){
    if(r.rip==clock){long time[2]={1000,static_cast<long>(++clocks*1000)};
     need(ptrace(PTRACE_POKEDATA,child,r.rsi,time[0])==0&&ptrace(PTRACE_POKEDATA,child,r.rsi+8,time[1])==0,"fixed clock");
     r.rip=peek(child,r.rsp);r.rsp+=8;r.rax=0;setregs(child,r);
    }else{++excluded;to(child,peek(child,r.rsp));r=regs(child);}
   }
  }
  need(!sites.empty(),"production scope fired");
  need(ptrace(PTRACE_DETACH,child,nullptr,nullptr)==0,"detach");int status;need(waitpid(child,&status,0)==child,"final wait");child=-1;need(WIFEXITED(status)&&WEXITSTATUS(status)==0,"exact fixture result");
  std::printf("TRACE={\"steps\":%lu,\"clock_calls\":%lu,\"excluded_calls\":%lu,\"sites\":{",steps,clocks,excluded);bool first=true;
  for(auto [pc,n]:sites){std::printf("%s\"%lx\":%lu",first?"":",",pc,n);first=false;}
  std::printf("},\"raw_sites\":{");first=true;for(auto [pc,n]:raw){std::printf("%s\"%lx\":%lu",first?"":",",pc,n);first=false;}
  std::puts("}}");
 }catch(const std::exception& e){if(child>0){kill(child,SIGKILL);waitpid(child,nullptr,0);}std::fprintf(stderr,"FAIL trace: %s\n",e.what());return 1;}
}
