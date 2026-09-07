// What a 1-in-100 sampled signature stream does to the band, against a real mix change of ~0.35.
#include <cstdio>
#include <cmath>
#include "src/core/flipctl.h"
using namespace tomo;
static uint64_t st = 88172645463325252ull;
static double u(){ st^=st<<13; st^=st>>7; st^=st<<17; return (double)(st>>11)/9007199254740992.0; }
static uint32_t binom(uint32_t n,double p){ uint32_t k=0; for(uint32_t i=0;i<n;i++) if(u()<p) k++; return k; }
static FlipFingerprintWindow win(uint32_t n,double p){       // n SAMPLED commands, p = read share
    FlipFingerprintWindow s; uint32_t r=binom(n,p), w=n-r;
    s.pass_depth={n,0,0,0};
    s.command_class[(size_t)FlipFingerprintClass::Read]=r;
    s.command_class[(size_t)FlipFingerprintClass::Write]=w;
    s.commands=n; s.value_bytes=(uint64_t)w*32; s.closed_windows=1; return s;
}
static FlipFingerprintWindow mixchange(uint32_t n){          // the positive phase: multi-key traffic
    FlipFingerprintWindow s; s.pass_depth={0,n/10,n-n/10,0};
    s.command_class[(size_t)FlipFingerprintClass::MultiRead]=n*8/10;
    s.command_class[(size_t)FlipFingerprintClass::MultiWrite]=n*2/10;
    s.commands=n; s.multikey_ops=n; s.multikey_keys=(uint64_t)n*8;
    s.value_bytes=(uint64_t)(n*2/10)*8*64; s.closed_windows=1; return s;
}
static void run(const char* tag, uint32_t n, int32_t typed){
    FlipShiftDetector d(typed, 8);
    for(int k=0;k<12;k++) d.observe(win(n,0.5));
    d.anchor();
    double at=d.band(); int fires=0, confirmed=0, streak=0; double maxdist=0;
    for(int k=0;k<600;k++){ bool f=d.observe(win(n,0.5)); fires+=f?1:0;
        streak = f ? streak+1 : 0; if (streak>=2) { confirmed++; streak=0; }
        maxdist=std::max(maxdist,d.last_distance()); }
    // the real mix change, measured against the settled band
    FlipShiftDetector d2(typed, 8);
    for(int k=0;k<12;k++) d2.observe(win(n,0.5));
    d2.anchor();
    for(int k=0;k<40;k++) d2.observe(win(n,0.5));
    double band_before=d2.band();
    bool fired = d2.observe(mixchange(n));
    double chg=d2.last_distance();
    printf("%-22s N=%5u typed=%3d | band %.4f | quiet maxdist %.4f fires %3d/600 CONFIRMED(2-consec) %d | change %.4f fired=%d margin %.1fx\n",
           tag,n,typed,band_before,maxdist,fires,confirmed,chg,fired?1:0, band_before>0?chg/band_before:0.0);
}
int main(){
    run("every command",      13500, -1);
    run("every command typed",13500,  2);
    run("1-in-100 sampled",     100, -1);
    run("1-in-100 typed",       100,  2);
    run("1-in-100 w=1000",     1000, -1);
}
