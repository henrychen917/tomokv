// Survey-only RESP2 client. No production headers or link dependencies.
// Script: primary(0/1), validator, request bytes, expected bytes; length framed.
// Timed load uses epoll per pinned worker, exact drain, no reconnect or dropped deadlines.
#include <arpa/inet.h>
#include <netinet/tcp.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <sys/resource.h>
#include <sys/prctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <sched.h>
#include <algorithm>
#include <array>
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
#include <string_view>
#include <thread>
#include <vector>

using Clock = std::chrono::steady_clock;
using u64 = uint64_t;
static u64 ns() { return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count(); }
static void need(bool yes, std::string_view msg) { if (!yes) throw std::runtime_error(std::string(msg)); }
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
struct Op { bool primary; std::string rule, request, expect; Reply expected; std::vector<size_t> key_offsets; };
static std::vector<size_t> key_offsets(const std::string& s) {
    std::vector<size_t> offsets;
    for(const char* prefix:{"sv:","sw:","ss:","s0:","s1:","s2:","s3:","s4:","s5:","s6:","s7:"}) {
        std::string mark=std::string(prefix)+"000000000000";size_t p=0;
        while((p=s.find(mark,p))!=std::string::npos){offsets.push_back(p+3);p+=15;}
    }
    return offsets;
}
static bool equal(const Reply& a, const Reply& b) {
    if(a.kind!=b.kind || a.nil!=b.nil || a.array.size()!=b.array.size()) return false;
    if(a.kind!='*' && a.text!=b.text) return false;
    for(size_t i=0;i<a.array.size();i++) if(!equal(a.array[i],b.array[i])) return false;
    return true;
}
static void check(const Op& op, const Reply& r) {
    if(r.kind=='-')throw std::runtime_error("server error: "+r.text);
    if(op.rule=="exact") {
        if(!equal(r,op.expected))throw std::runtime_error("unexpected reply: "+canon(r).substr(0,180));
    }
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
        need(parse(o.expect,p,o.expected) && p==b,"bad expected response");
        o.key_offsets=key_offsets(o.request);out.push_back(std::move(o));
    }
    need(!out.empty(),"empty script"); return out;
}
// Every placeholder has the same width as the deterministic key. ss: is a stream.
static std::string keywire(std::string s, u64 key) {
    char digits[13]; snprintf(digits,sizeof digits,"%012llu",(unsigned long long)(100000000000ull+key));
    for(size_t p:key_offsets(s))s.replace(p,12,digits);
    return s;
}
// HDR-style 3 significant decimal digits: 2048 sub-buckets, 1 ns floor.
// Upper equivalent value has <0.1% relative error; exact max also retained.
static u64 bucket(u64 n) { int shift=std::max(0,int(std::bit_width(n))-11); return (n>>shift<<shift)|((u64(1)<<shift)-1); }
static size_t hist_index(u64 n) { int shift=std::max(0,int(std::bit_width(n))-11);return shift*1024+(n>>shift); }
static u64 hist_edge(size_t i) { int shift=std::max(0,int(i/1024)-1);return (u64(i-shift*1024)<<shift)|((u64(1)<<shift)-1); }
struct Hist {
    // Same HDR-equivalent buckets as before, without three tree lookups and
    // per-bucket allocation on the reply path. Covers the full uint64 range.
    std::vector<u64> bins=std::vector<u64>(55*1024);u64 max=0,n=0;
    void add(u64 x){bins[hist_index(x)]++;max=std::max(max,x);n++;}
};
struct Pending { size_t op; u64 scheduled,sent,key; };
struct SendStamp { u64 byte; Pending* pending; };
struct Conn {
    int fd=-1; u64 id=0,cycle=0,seedkey=0,completed=0;
    std::string input,output; size_t offset=0; std::deque<Pending> pending;
    u64 queued=0,written=0; bool write_wait=false;
    std::deque<SendStamp> unsent;
    ~Conn(){if(fd>=0)close(fd);}
};
struct Options {
    int port=0,connections=0,threads=0,pipeline=1; u64 keys=0,count=0;
    double seconds=0,rate=0,timeout=60; std::string script,out,raw,ready,go; std::vector<int> cpus;
};
static int first_conn(int wid,const Options& o){return u64(o.connections)*wid/o.threads;}
struct alignas(64) Result {
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
    for(size_t i=0;i<h.bins.size();i++)if(h.bins[i]){if(!first)f<<",";first=false;f<<"["<<hist_edge(i)<<","<<h.bins[i]<<"]";}
    f<<"]}";
}
static u64 deadline(const Conn& c,const Options& o,u64 start,u64 primary_ops) {
    return start+u64((c.cycle*o.connections+c.id)*double(primary_ops)*1e9/o.rate);
}
static void enqueue(Conn& c,const std::vector<Op>& ops,u64 scheduled,u64 key,Result& res) {
    char digits[13];snprintf(digits,sizeof digits,"%012llu",(unsigned long long)(100000000000ull+key));
    for(size_t j=0;j<ops.size();j++) {
        c.pending.push_back({j,scheduled,0,key});
        c.unsent.push_back({c.queued,&c.pending.back()});
        size_t begin=c.output.size();c.output+=ops[j].request;
        for(size_t p:ops[j].key_offsets)memcpy(c.output.data()+begin+p,digits,12);
        c.queued+=ops[j].request.size();res.scheduled+=ops[j].primary;
    }
    c.cycle++;
}
static void flush(Conn& c,int ep) {
    while(c.offset<c.output.size()) {
        u64 attempted=ns();
        ssize_t w=send(c.fd,c.output.data()+c.offset,c.output.size()-c.offset,MSG_NOSIGNAL);
        if(w<0&&(errno==EAGAIN||errno==EWOULDBLOCK))break;
        if(w<0&&errno==EINTR)continue;
        need(w>0,"send failed");c.offset+=w;c.written+=w;
        // Stamp only commands whose first byte was accepted, including partial
        // sends. An EAGAIN/EPOLLOUT wait is send lag, not an early 'sent' sample.
        while(!c.unsent.empty()&&c.unsent.front().byte<c.written) {
            c.unsent.front().pending->sent=attempted;c.unsent.pop_front();
        }
    }
    bool blocked=c.offset<c.output.size();
    if(!blocked){c.output.clear();c.offset=0;}
    if(blocked!=c.write_wait) {
        epoll_event e{};e.events=EPOLLIN|(blocked?uint32_t(EPOLLOUT):0);e.data.ptr=&c;
        need(epoll_ctl(ep,EPOLL_CTL_MOD,c.fd,&e)==0,"epoll mod");c.write_wait=blocked;
    }
}
static void worker(int wid,const Options& o,const std::vector<Op>& ops,std::barrier<>& ready,
                   std::atomic<u64>& epoch,std::atomic<bool>& abort,Result& res) {
    int ep=-1; bool joined=false;
    std::ofstream raw;std::vector<std::array<u64,4>> observations;size_t observed=0;
    try {
        cpu_set_t cpu;CPU_ZERO(&cpu);CPU_SET(o.cpus[wid%o.cpus.size()],&cpu);
        need(sched_setaffinity(0,sizeof cpu,&cpu)==0,"worker pinning");
        need(prctl(PR_SET_TIMERSLACK,1ul)==0,"timer slack");
        ep=epoll_create1(0);need(ep>=0,"epoll_create");
        std::vector<std::unique_ptr<Conn>> clients;
        for(int i=first_conn(wid,o);i<first_conn(wid+1,o);i++){
            auto c=std::make_unique<Conn>();c->id=i;c->seedkey=i;c->fd=dial(o.port);
            epoll_event e{};e.events=EPOLLIN;e.data.ptr=c.get();need(epoll_ctl(ep,EPOLL_CTL_ADD,c->fd,&e)==0,"epoll add");clients.push_back(std::move(c));
        }
        u64 primary_ops=std::count_if(ops.begin(),ops.end(),[](const Op& x){return x.primary;});
        u64 target=o.rate?u64(std::ceil(o.rate*o.seconds/primary_ops)):0;
        if(!o.raw.empty()) {
            need(o.rate>0,"raw observations require fixed load");
            raw.open(o.raw+"."+std::to_string(wid)+".bin",std::ios::binary);need(bool(raw),"raw open");
            u64 cycles=target/o.connections*clients.size();
            for(const auto& c:clients)cycles+=c->id<target%o.connections;
            // Pre-touch the exact, finite observation allocation before ready.
            // Storage stalls must not hold the paced worker off its deadlines.
            observations.resize(cycles*primary_ops);
        }
        res.perop.resize(ops.size());
        joined=true; ready.arrive_and_wait();
        while(!epoch.load()&&!abort.load()) std::this_thread::sleep_for(std::chrono::milliseconds(1));
        if(abort.load())throw std::runtime_error("peer worker failed");
        u64 start=epoch.load(),end=start+u64(o.seconds*1e9);
        std::this_thread::sleep_until(Clock::time_point(std::chrono::nanoseconds(start)));
        double cpu0=threadcpu();
        std::vector<epoll_event> events(std::max(1,int(clients.size())));
        size_t next=0;
        auto pace=[&] {
            // Bound catch-up work so a backlog cannot starve socket progress.
            for(int batch=0;batch<64;batch++) {
                Conn& c=*clients[next];
                if(c.cycle*o.connections+c.id>=target)break;
                u64 scheduled=deadline(c,o,start,primary_ops);
                if(ns()<scheduled)break;
                enqueue(c,ops,scheduled,(c.id+c.cycle*o.connections)%o.keys,res);
                flush(c,ep);next=(next+1)%clients.size();
            }
        };
        while(!abort.load()) {
            u64 now=ns();need(now<=end+u64(o.timeout*1e9),"client drain timeout");bool live=false;
            u64 wake=now+1000000;
            if(o.rate) {
                // Contiguous IDs give each worker a short run of due deadlines
                // per round instead of waking all workers for interleaved slots.
                // Global spacing and per-connection key order stay unchanged.
                pace();
                const Conn& c=*clients[next];
                if(c.cycle*o.connections+c.id<target){live=true;wake=std::min(wake,deadline(c,o,start,primary_ops));}
            }
            for(auto& ptr:clients){Conn& c=*ptr;
                if(!c.pending.empty()||c.offset<c.output.size()){live=true;continue;}
                if(o.rate)continue;
                for(int batch=0;batch<o.pipeline;batch++) {
                    bool more=o.count?c.seedkey<o.count:now<end;
                    if(!more)break;
                    live=true;
                    u64 key=o.count?c.seedkey:(c.id+c.cycle*o.connections)%o.keys;
                    enqueue(c,ops,now,key,res);c.seedkey+=o.connections;
                }
                if(!c.output.empty())flush(c,ep);
            }
            if(!live)break;
            now=ns();u64 wait=wake>now?wake-now:0;
            timespec timeout{time_t(wait/1000000000),long(wait%1000000000)};
            int n=epoll_pwait2(ep,events.data(),events.size(),&timeout,nullptr);
            need(n>=0||errno==EINTR,"epoll wait");
            for(int i=0;i<n;i++){
                auto& c=*static_cast<Conn*>(events[i].data.ptr);
                need(!(events[i].events&(EPOLLERR|EPOLLHUP)),"socket closed/error");
                if(events[i].events&EPOLLOUT)flush(c,ep);
                if(events[i].events&EPOLLIN){
                    char buf[65536];for(int reads=0;reads<16;reads++){ssize_t got=recv(c.fd,buf,sizeof buf,0);
                        if(got<0&&(errno==EAGAIN||errno==EWOULDBLOCK))break;
                        if(got<0&&errno==EINTR)continue;
                        need(got>0,"recv failed/EOF");c.input.append(buf,got);
                    }
                    size_t p=0;for(;;){size_t old=p;Reply reply;if(!parse(c.input,p,reply)){p=old;break;}
                        need(!c.pending.empty(),"unsolicited reply");auto pending=c.pending.front();c.pending.pop_front();
                        need(pending.sent>0,"reply before send");
                        const auto& op=ops[pending.op];
                        if(op.expect.find("ss:000000000000")!=std::string::npos) {
                            Op concrete=op;concrete.expect=keywire(op.expect,pending.key);
                            size_t pos=0;need(parse(concrete.expect,pos,concrete.expected),"stream expectation");check(concrete,reply);
                        }else check(op,reply);
                        u64 done=ns();res.completed++;res.perop[pending.op]++;c.completed++;
                        if(op.primary){res.primary++;res.within+=done<=end;
                            u64 lag=pending.sent>pending.scheduled?pending.sent-pending.scheduled:0;
                            res.rtt.add(done-pending.sent);res.response.add(done-pending.scheduled);res.lag.add(lag);res.maxlag=std::max(res.maxlag,lag);
                            if(raw.is_open()) {
                                need(observed<observations.size(),"too many raw observations");
                                observations[observed++]={c.id,pending.scheduled-start,pending.sent-start,done-start};
                            }
                        }
                        // A ready set can contain many milliseconds of replies.
                        // Service due sends during parsing, not just after the
                        // entire epoll batch, without dropping any observation.
                        if(o.rate&&res.completed%32==0)pace();
                    }c.input.erase(0,p);
                }
            }
        }
        need(!abort.load(),"peer worker failed");
        for(auto& c:clients){need(c->pending.empty()&&c->input.empty()&&c->unsent.empty()&&c->offset==c->output.size(),"undrained connection");need(c->completed>0,"inactive connection");res.cycles+=c->cycle;}
        res.finish=ns();res.cpu=threadcpu()-cpu0;
    }catch(const std::exception& e){res.error=e.what();abort=true;if(!joined)ready.arrive_and_drop();}
    if(raw.is_open()) {
        // Retain every completed observation, including a failed run's prefix.
        raw.write(reinterpret_cast<const char*>(observations.data()),observed*sizeof(observations[0]));
        raw.close();
        if(!raw){res.error+=" raw write/close failed";abort=true;}
    }
    if(ep>=0)close(ep);
}
static void selftest(){
    Reply r;size_t p=0;need(!parse("$3\r\nxy",p,r)&&p==0,"partial bulk");
    need(parse("*2\r\n:1\r\n$1\r\nx\r\n",p,r)&&r.array.size()==2,"nested reply");
    Op op{true,"exact","",":1\r\n",{}, {}};p=0;need(parse(op.expect,p,op.expected),"fixture");check(op,op.expected);
    auto bad=op.expected;bad.text="2";bool rejected=false;try{check(op,bad);}catch(...){rejected=true;}need(rejected,"bad reply accepted");
    for(u64 n:{0ull,1ull,1024ull,2048ull,1000000ull,100000000000ull})need(bucket(n)>=n&&bucket(n)-n<=std::max<u64>(1,n/1000),"hist precision");
    for(size_t i=0;i<55*1024;i++)need(hist_index(hist_edge(i))==i&&bucket(hist_edge(i))==hist_edge(i),"hist bucket roundtrip");
    for(int bit=0;bit<64;bit++)for(u64 n:{(u64(1)<<bit)-1,u64(1)<<bit,(u64(1)<<bit)+1})
        need(hist_edge(hist_index(n))==bucket(n),"hist boundary equivalence");
    need(keywire("sv:000000000000 sw:000000000000",42)=="sv:100000000042 sw:100000000042","key substitution");
    // Uneven worker/connection division must cover every global deadline once.
    Options o;o.connections=512;o.threads=80;o.rate=100000;
    std::vector<int> seen(1500);
    for(int wid=0;wid<o.threads;wid++) {
        std::vector<std::unique_ptr<Conn>> clients;
        for(int id=first_conn(wid,o);id<first_conn(wid+1,o);id++){auto c=std::make_unique<Conn>();c->id=id;clients.push_back(std::move(c));}
        size_t next=0;u64 last=0;
        for(;;) {
            Conn& c=*clients[next];u64 global=c.cycle*o.connections+c.id;
            if(global>=seen.size())break;
            u64 due=deadline(c,o,1,1);need(due>=last,"deadline order");last=due;
            seen[global]++;c.cycle++;next=(next+1)%clients.size();
        }
    }
    need(std::all_of(seen.begin(),seen.end(),[](int n){return n==1;}),"lost/duplicated deadline");
    // Withhold replies and force EAGAIN: subsequent cycles must still enqueue,
    // and their send timestamps must remain unset until bytes actually move.
    int sockets[2];need(socketpair(AF_UNIX,SOCK_STREAM|SOCK_NONBLOCK,0,sockets)==0,"test socketpair");
    Conn c,peer;c.fd=sockets[0];peer.fd=sockets[1];int small=4096;
    need(setsockopt(c.fd,SOL_SOCKET,SO_SNDBUF,&small,sizeof small)==0,"test send buffer");
    int ep=epoll_create1(0);need(ep>=0,"test epoll");epoll_event event{};event.events=EPOLLIN;event.data.ptr=&c;
    need(epoll_ctl(ep,EPOLL_CTL_ADD,c.fd,&event)==0,"test epoll add");
    Result res;Op large=op;
    large.request="sv:000000000000 sw:000000000000";large.key_offsets=key_offsets(large.request);
    Conn keyed;enqueue(keyed,{large},1,42,res);
    need(keyed.output==keywire(large.request,42),"prepared key substitution");
    large.request.assign(65536,'x');large.key_offsets.clear();
    enqueue(c,{large},ns(),0,res);flush(c,ep);
    need(c.write_wait&&c.pending.front().sent>0,"partial send witness");
    enqueue(c,{large},ns(),1,res);flush(c,ep);
    need(c.cycle==2&&c.pending.size()==2&&c.pending.back().sent==0,"EAGAIN/send gating");
    u64 resumed=ns();char buf[65536];
    for(int tries=0;c.write_wait&&tries<1000;tries++) {
        while(recv(peer.fd,buf,sizeof buf,0)>0){}
        flush(c,ep);
    }
    need(!c.write_wait&&c.unsent.empty()&&c.pending.back().sent>=resumed,"delayed send stamp");
    close(ep);
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
