// Survey-only RESP2 client. No production headers or link dependencies.
// Script: primary(0/1), validator, request bytes, expected bytes; length framed.
// Timed load uses epoll per pinned worker, exact drain, no reconnect or dropped deadlines.
#include <arpa/inet.h>
#include <netinet/tcp.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <sys/resource.h>
#include <fcntl.h>
#include <unistd.h>
#include <sched.h>
#include <algorithm>
#include <atomic>
#include <barrier>
#include <bit>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <deque>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

using Clock = std::chrono::steady_clock;
using u64 = uint64_t;
static u64 ns() { return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count(); }
static void need(bool yes, const std::string& msg) { if (!yes) throw std::runtime_error(msg); }
struct Reply { char kind=0; std::string text; std::vector<Reply> array; bool nil=false; };
// Returns false for a partial frame. Position is advanced only on a complete frame.
static bool parse(const std::string& s, size_t& pos, Reply& r, int depth=0) {
    need(depth<16, "RESP nesting overflow");
    size_t p=pos, end=s.find("\r\n",p);
    if (end==std::string::npos) return false;
    need(end>p, "empty RESP header");
    r.kind=s[p]; r.text=s.substr(p+1,end-p-1); r.array.clear(); r.nil=false; p=end+2;
    if (r.kind==':' || r.kind=='$' || r.kind=='*') {
        size_t used=0; long long n=std::stoll(r.text,&used);
        need(used==r.text.size(), "bad RESP number");
        if(r.kind!=':') {
            need(n>=-1 && n<=256*1024*1024, "bad RESP length");
            r.nil=n==-1;
            if(n>=0 && r.kind=='$') {
                if(s.size()-p<size_t(n)+2) return false;
                need(s.compare(p+n,2,"\r\n")==0,"bad bulk ending");
                r.text=s.substr(p,n); p+=n+2;
            } else if(n>=0) {
                need(n<=1000000, "too many RESP elements");
                for(long long i=0;i<n;i++) { Reply v; if(!parse(s,p,v,depth+1)) return false; r.array.push_back(std::move(v)); }
            }
        }
    } else need(r.kind=='+' || r.kind=='-', "unsupported RESP tag");
    pos=p; return true;
}
static std::string canon(const Reply& r) {
    std::string s(1,r.kind); s+=r.nil?"nil":r.text;
    for(const auto& c:r.array) s+="["+canon(c)+"]";
    return s;
}
struct Op { bool primary; std::string rule, request, expect; Reply expected; };
static bool equal(const Reply& a, const Reply& b) {
    if(a.kind!=b.kind || a.nil!=b.nil || a.array.size()!=b.array.size()) return false;
    if(a.kind!='*' && a.text!=b.text) return false;
    for(size_t i=0;i<a.array.size();i++) if(!equal(a.array[i],b.array[i])) return false;
    return true;
}
static void check(const Op& op, const Reply& r) {
    need(r.kind!='-',"server error: "+r.text);
    if(op.rule=="exact") need(equal(r,op.expected),"unexpected reply: "+canon(r).substr(0,180));
    else if(op.rule=="positive") need(r.kind==':' && std::stoll(r.text)>0,"expected positive integer");
    else if(op.rule=="nonnegative") need(r.kind==':' && std::stoll(r.text)>=0,"expected nonnegative integer");
    else if(op.rule=="number") {
        size_t used=0; double v=std::stod(r.text,&used);
        need(r.kind=='$' && !r.nil && used==r.text.size() && std::isfinite(v),"expected finite bulk number");
    } else if(op.rule=="unordered" || op.rule=="pairs") {
        need(r.kind=='*' && !r.nil && r.array.size()==op.expected.array.size(),"bad unordered reply shape");
        auto keys=[&](const Reply& value) {
            std::vector<std::string> out; size_t stride=op.rule=="pairs"?2:1;
            need(value.array.size()%stride==0,"odd hash reply");
            for(size_t i=0;i<value.array.size();i+=stride)
                out.push_back(canon(value.array[i])+(stride==2?"="+canon(value.array[i+1]):""));
            std::sort(out.begin(),out.end()); return out;
        };
        need(keys(r)==keys(op.expected),"wrong unordered values");
    } else throw std::runtime_error("unknown validator "+op.rule);
}
static std::vector<Op> script(const std::string& path) {
    std::ifstream f(path,std::ios::binary); need(bool(f),"missing script");
    size_t count; f>>count; f.get(); std::vector<Op> out;
    for(size_t i=0;i<count;i++) {
        Op o; size_t a,b; f>>o.primary>>o.rule>>a>>b; need(f.get()=='\n',"script header");
        o.request.resize(a); o.expect.resize(b); f.read(o.request.data(),a); f.read(o.expect.data(),b);
        need(bool(f),"truncated script"); size_t p=0;
        need(parse(o.expect,p,o.expected) && p==b,"bad expected response"); out.push_back(std::move(o));
    }
    need(!out.empty(),"empty script"); return out;
}
// Every placeholder has the same width as the deterministic key. ss: is a stream.
static std::string keywire(std::string s, u64 key) {
    char digits[13]; snprintf(digits,sizeof digits,"%012llu",(unsigned long long)key);
    for(const char* prefix:{"sv:","sw:","ss:","s0:","s1:","s2:","s3:","s4:","s5:","s6:","s7:"}) {
        std::string mark=std::string(prefix)+"000000000000"; size_t p=0;
        while((p=s.find(mark,p))!=std::string::npos) { s.replace(p+3,12,digits); p+=15; }
    }
    return s;
}
// HDR-style 3 significant decimal digits: 2048 sub-buckets, 1 ns floor.
// Upper equivalent value has <0.1% relative error; exact max also retained.
static u64 bucket(u64 n) { int shift=std::max(0,int(std::bit_width(n))-11); return (n>>shift<<shift)|((u64(1)<<shift)-1); }
struct Hist { std::map<u64,u64> bins; u64 max=0,n=0; void add(u64 x){bins[bucket(x)]++;max=std::max(max,x);n++;} };
struct Pending { size_t op; u64 scheduled,sent,key; };
struct Conn {
    int fd=-1; u64 id=0,cycle=0,seedkey=0,completed=0;
    std::string input,output; size_t offset=0; std::deque<Pending> pending;
    ~Conn(){if(fd>=0)close(fd);}
};
struct Options {
    int port=0,connections=0,threads=0,pipeline=1; u64 keys=0,count=0;
    double seconds=0,rate=0,timeout=60; std::string script,out,raw,ready,go; std::vector<int> cpus;
};
struct Result {
    u64 completed=0,primary=0,cycles=0,finish=0,within=0,scheduled=0,maxlag=0;
    double cpu=0; Hist rtt,response,lag; std::vector<u64> perop; std::string error;
};
static int dial(int port) {
    int fd=socket(AF_INET,SOCK_STREAM,0); need(fd>=0,"socket");
    sockaddr_in a{};a.sin_family=AF_INET;a.sin_port=htons(port);a.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    if(connect(fd,(sockaddr*)&a,sizeof a)) {close(fd);throw std::runtime_error("connect: "+std::string(strerror(errno)));}
    int yes=1; setsockopt(fd,IPPROTO_TCP,TCP_NODELAY,&yes,sizeof yes);
    need(fcntl(fd,F_SETFL,O_NONBLOCK)==0,"fcntl"); return fd;
}
static double threadcpu(){timespec t{};clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t);return t.tv_sec+t.tv_nsec/1e9;}
static void histjson(std::ostream& f,const Hist& h){
    f<<"{\"n\":"<<h.n<<",\"max\":"<<h.max<<",\"bins\":[";bool first=true;
    for(auto [edge,count]:h.bins){if(!first)f<<",";first=false;f<<"["<<edge<<","<<count<<"]";}f<<"]}";
}
static void worker(int wid,const Options& o,const std::vector<Op>& ops,std::barrier<>& ready,
                   std::atomic<u64>& epoch,std::atomic<bool>& abort,Result& res) {
    int ep=-1; bool joined=false;
    try {
        cpu_set_t cpu;CPU_ZERO(&cpu);CPU_SET(o.cpus[wid%o.cpus.size()],&cpu);
        need(sched_setaffinity(0,sizeof cpu,&cpu)==0,"worker pinning");
        ep=epoll_create1(0);need(ep>=0,"epoll_create");
        std::vector<std::unique_ptr<Conn>> clients;
        for(int i=wid;i<o.connections;i+=o.threads){
            auto c=std::make_unique<Conn>();c->id=i;c->seedkey=i;c->fd=dial(o.port);
            epoll_event e{};e.events=EPOLLIN;e.data.ptr=c.get();need(epoll_ctl(ep,EPOLL_CTL_ADD,c->fd,&e)==0,"epoll add");clients.push_back(std::move(c));
        }
        std::ofstream raw;
        if(!o.raw.empty()){raw.open(o.raw+"."+std::to_string(wid)+".bin",std::ios::binary);need(bool(raw),"raw open");}
        res.perop.resize(ops.size());
        joined=true; ready.arrive_and_wait();
        while(!epoch.load()&&!abort.load()) std::this_thread::sleep_for(std::chrono::milliseconds(1));
        if(abort.load())throw std::runtime_error("peer worker failed");
        u64 start=epoch.load(),end=start+u64(o.seconds*1e9);double cpu0=threadcpu();
        u64 primary_ops=std::count_if(ops.begin(),ops.end(),[](const Op& x){return x.primary;});
        u64 target=o.rate?u64(std::ceil(o.rate*o.seconds/primary_ops)):0;
        std::vector<epoll_event> events(std::max(1,int(clients.size())));
        while(!abort.load()) {
            u64 now=ns();need(now<=end+u64(o.timeout*1e9),"client drain timeout");bool live=false;
            for(auto& ptr:clients){Conn& c=*ptr;
                if(!c.pending.empty()||c.offset<c.output.size()){live=true;continue;}
                c.output.clear();c.offset=0;
                for(int batch=0;batch<o.pipeline;batch++) {
                    u64 global=c.cycle*o.connections+c.id;
                    u64 scheduled=o.rate?start+u64(global*double(primary_ops)*1e9/o.rate):now;
                    bool more=o.count?c.seedkey<o.count:(o.rate?global<target:now<end);
                    if(!more)break;
                    live=true;if(now<start || (o.rate&&now<scheduled))break;
                    u64 key=o.count?c.seedkey:(c.id+c.cycle*o.connections)%o.keys;
                    for(size_t j=0;j<ops.size();j++) {
                        c.output+=keywire(ops[j].request,key);
                        c.pending.push_back({j,scheduled,now,key});res.scheduled+=ops[j].primary;
                    }
                    c.cycle++;c.seedkey+=o.connections;
                    if(o.rate)break; // pacing emits each due cycle separately, never batches deadlines
                }
                if(!c.output.empty()) {
                    // Timestamp immediately before the first send attempt. EPOLLOUT waits are included.
                    for(auto& p:c.pending)p.sent=ns();
                    epoll_event e{};e.events=EPOLLIN|EPOLLOUT;e.data.ptr=&c;
                    need(epoll_ctl(ep,EPOLL_CTL_MOD,c.fd,&e)==0,"epoll mod");
                }
            }
            if(!live)break;
            int n=epoll_wait(ep,events.data(),events.size(),o.rate?0:1);
            need(n>=0||errno==EINTR,"epoll wait");
            for(int i=0;i<n;i++){
                auto& c=*static_cast<Conn*>(events[i].data.ptr);
                need(!(events[i].events&(EPOLLERR|EPOLLHUP)),"socket closed/error");
                if(events[i].events&EPOLLOUT){
                    while(c.offset<c.output.size()){
                        ssize_t w=send(c.fd,c.output.data()+c.offset,c.output.size()-c.offset,MSG_NOSIGNAL);
                        if(w<0&&(errno==EAGAIN||errno==EWOULDBLOCK))break;
                        if(w<0&&errno==EINTR)continue;
                        need(w>0,"send failed");c.offset+=w;
                    }
                    if(c.offset==c.output.size()){epoll_event e{};e.events=EPOLLIN;e.data.ptr=&c;need(epoll_ctl(ep,EPOLL_CTL_MOD,c.fd,&e)==0,"epoll mod read");}
                }
                if(events[i].events&EPOLLIN){
                    char buf[65536];for(;;){ssize_t got=recv(c.fd,buf,sizeof buf,0);
                        if(got<0&&(errno==EAGAIN||errno==EWOULDBLOCK))break;
                        if(got<0&&errno==EINTR)continue;
                        need(got>0,"recv failed/EOF");c.input.append(buf,got);
                    }
                    size_t p=0;for(;;){size_t old=p;Reply reply;if(!parse(c.input,p,reply)){p=old;break;}
                        need(!c.pending.empty(),"unsolicited reply");auto pending=c.pending.front();c.pending.pop_front();
                        const auto& op=ops[pending.op];
                        if(op.expect.find("ss:000000000000")!=std::string::npos) {
                            Op concrete=op;concrete.expect=keywire(op.expect,pending.key);
                            size_t pos=0;need(parse(concrete.expect,pos,concrete.expected),"stream expectation");check(concrete,reply);
                        }else check(op,reply);
                        u64 done=ns();res.completed++;res.perop[pending.op]++;c.completed++;
                        if(op.primary){res.primary++;res.within+=done<=end;
                            u64 lag=pending.sent>pending.scheduled?pending.sent-pending.scheduled:0;
                            res.rtt.add(done-pending.sent);res.response.add(done-pending.scheduled);res.lag.add(lag);res.maxlag=std::max(res.maxlag,lag);
                            if(raw){u64 row[]={c.id,pending.scheduled-start,pending.sent-start,done-start};raw.write((char*)row,sizeof row);need(bool(raw),"raw write");}
                        }
                    }c.input.erase(0,p);
                }
            }
            if(now<start)std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        need(!abort.load(),"peer worker failed");
        for(auto& c:clients){need(c->pending.empty()&&c->input.empty()&&c->offset==c->output.size(),"undrained connection");need(c->completed>0,"inactive connection");res.cycles+=c->cycle;}
        res.finish=ns();res.cpu=threadcpu()-cpu0;
    }catch(const std::exception& e){res.error=e.what();abort=true;if(!joined)ready.arrive_and_drop();}
    if(ep>=0)close(ep);
}
static void selftest(){
    Reply r;size_t p=0;need(!parse("$3\r\nxy",p,r)&&p==0,"partial bulk");
    need(parse("*2\r\n:1\r\n$1\r\nx\r\n",p,r)&&r.array.size()==2,"nested reply");
    Op op{true,"exact","",":1\r\n",{}};p=0;need(parse(op.expect,p,op.expected),"fixture");check(op,op.expected);
    auto bad=op.expected;bad.text="2";bool rejected=false;try{check(op,bad);}catch(...){rejected=true;}need(rejected,"bad reply accepted");
    for(u64 n:{0ull,1ull,1024ull,2048ull,1000000ull,100000000000ull})need(bucket(n)>=n&&bucket(n)-n<=std::max<u64>(1,n/1000),"hist precision");
    need(keywire("sv:000000000000 sw:000000000000",42)=="sv:000000000042 sw:000000000042","key substitution");
    std::cout<<"survey-client selftest: PASS\n";
}
int main(int argc,char**argv){
    try {
        if(argc==2&&std::string(argv[1])=="--selftest"){selftest();return 0;}
        std::map<std::string,std::string> a;for(int i=1;i<argc;i+=2){need(i+1<argc,"missing argument");a[argv[i]]=argv[i+1];}
        Options o;o.port=std::stoi(a.at("--port"));o.connections=std::stoi(a.at("--connections"));o.threads=std::stoi(a.at("--threads"));
        o.pipeline=std::stoi(a.at("--pipeline"));o.keys=std::stoull(a.at("--keys"));o.seconds=std::stod(a.at("--seconds"));
        o.script=a.at("--script");o.out=a.at("--out");o.count=a.count("--count")?std::stoull(a["--count"]):0;
        o.rate=a.count("--rate")?std::stod(a["--rate"]):0;o.raw=a.count("--raw")?a["--raw"]:"";
        o.ready=a.at("--ready");o.go=a.at("--go");o.timeout=std::stod(a.at("--timeout"));
        std::string cs=a.at("--cpus");size_t pos=0;while(pos<cs.size()){size_t comma=cs.find(',',pos);o.cpus.push_back(std::stoi(cs.substr(pos,comma-pos)));if(comma==std::string::npos)break;pos=comma+1;}
        need(o.port>0&&o.port<32768&&o.connections>0&&o.threads>0&&o.threads<=o.connections&&o.keys>0&&o.seconds>0&&o.pipeline>0&&o.rate>=0,"invalid options");
        auto ops=script(o.script);std::atomic<u64> epoch=0;std::atomic<bool> abort=false;std::barrier ready(o.threads+1);
        std::vector<Result> results(o.threads);std::vector<std::thread> threads;
        for(int i=0;i<o.threads;i++)threads.emplace_back(worker,i,std::cref(o),std::cref(ops),std::ref(ready),std::ref(epoch),std::ref(abort),std::ref(results[i]));
        ready.arrive_and_wait();
        if(!abort.load()){
            std::ofstream(o.ready)<<"ready\n";u64 deadline=ns()+u64(o.timeout*1e9);
            while(access(o.go.c_str(),F_OK)!=0&&!abort.load()&&ns()<deadline)std::this_thread::sleep_for(std::chrono::milliseconds(1));
            if(access(o.go.c_str(),F_OK)!=0)abort=true;else epoch=ns()+100000000;
        }
        for(auto& t:threads)t.join();
        std::ofstream f(o.out);need(bool(f),"result open");f<<"{\"epoch_ns\":"<<epoch.load()<<",\"workers\":[";
        for(size_t i=0;i<results.size();i++){
            auto&r=results[i];if(i)f<<",";
            f<<"{\"completed\":"<<r.completed<<",\"primary\":"<<r.primary<<",\"cycles\":"<<r.cycles<<",\"finish_ns\":"<<r.finish<<",\"within\":"<<r.within<<",\"scheduled\":"<<r.scheduled<<",\"cpu_seconds\":"<<r.cpu<<",\"counts\":[";
            for(size_t j=0;j<r.perop.size();j++){if(j)f<<",";f<<r.perop[j];}
            f<<"],\"rtt\":";histjson(f,r.rtt);f<<",\"response\":";histjson(f,r.response);f<<",\"lag\":";histjson(f,r.lag);f<<"}";
            if(!r.error.empty())std::cerr<<"worker "<<i<<": "<<r.error<<"\n";
        }
        f<<"],\"valid\":"<<(abort.load()?"false":"true")<<"}\n";
        return abort.load()?1:0;
    }catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}
}
