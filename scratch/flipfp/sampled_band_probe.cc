// What a 1-in-100 sampled signature stream does to the band, against a real mix change of ~0.35.
#include <cstdio>
#include <cmath>
#include "src/core/flipctl.h"
using namespace tomo;
// The flip-redesign lane's probe (wt-flipdamp/scratch/sampled_band_probe.cc), verbatim except for
// this constructor shim and the added rows, so it can be pointed at EITHER detector:
//   -DDETECTOR_NOISE_WINDOWS=8 -I<wt-flipdamp>  the redesigned detector (1/sqrt(N) quantum + noise bound)
//   (no define)               -I<wt-flipfp>     this lane's current detector (4/N quantum)
// N is the SAMPLED command count per window, which is what this lane's writer reports.
#ifdef DETECTOR_NOISE_WINDOWS
#define MAKE_DETECTOR(name, typed) FlipShiftDetector name(typed, DETECTOR_NOISE_WINDOWS)
#else
#define MAKE_DETECTOR(name, typed) FlipShiftDetector name(typed)
#endif
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
    MAKE_DETECTOR(d, typed);
    for(int k=0;k<12;k++) d.observe(win(n,0.5));
    d.anchor();
    double at=d.band(); int fires=0, confirmed=0, streak=0; double maxdist=0;
    for(int k=0;k<600;k++){ bool f=d.observe(win(n,0.5)); fires+=f?1:0;
        streak = f ? streak+1 : 0; if (streak>=2) { confirmed++; streak=0; }
        maxdist=std::max(maxdist,d.last_distance()); }
    // the real mix change, measured against the settled band
    MAKE_DETECTOR(d2, typed);
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
    printf("-- the flip lane's original rows --\n");
    run("every command",      13500, -1);
    run("every command typed",13500,  2);
    run("1-in-100 sampled",     100, -1);
    run("1-in-100 typed",       100,  2);
    run("1-in-100 w=1000",     1000, -1);
    // t-flipfp's REAL configuration: W = flip_work_window = 100, so the sampled count per 1 s tick
    // is (commands/s)/100. These are the three rates this lane actually measured on the box.
    printf("-- t-flipfp W=100 at its measured rates (N = sampled commands per tick) --\n");
    run("3.8M/s exhaustive",  38040, -1);   // what PRE's detector sees at that rate
    run("3.8M/s 1-in-100",      380, -1);
    run("3.8M/s 1-in-100 typed",380,  2);
    run("512k/s exhaustive",  51200, -1);
    run("512k/s 1-in-100",      512, -1);
    run("512k/s 1-in-100 typed",512,  2);
    run("6k/s (flipctl row)",  6000, -1);   // the gate row's rate, exhaustive
    run("6k/s 1-in-100",         60, -1);   // ... and sampled: this lane's thinnest real cell
    run("6k/s 1-in-100 typed",   60,  2);
}
