// Reuse the existing real production parser fixtures without editing them.
#include "reorderscan_witness.h"
#define main inherited_reorder_engagement_main
#include "reorder_engagement_unit.cc"
#undef main

int main(int argc, char** argv) {
    using T = tomo::CoreConcurrencyTest;
    using namespace r7_scan_witness;
    T::require(argc == 2 && (std::string(argv[1]) == "pre" || std::string(argv[1]) == "post"),
               "expected PRE or POST witness arm");
    const bool post = std::string(argv[1]) == "post";
    T::require(tomo::command_registry_init(false), "command registry");
    constructions = visits = 0;
    for (uint32_t overlap : {0u, 1u}) {
        T::io_dispatch_membership<false, true>(tomo::ThreadMode::Fused, overlap, 1);
        T::io_dispatch_membership<true>(tomo::ThreadMode::Fused, overlap, 1);
    }
    // Four fresh clients, one incomplete and one successful SET pass each.
    T::require(constructions == (post ? 0 : 8), "RO2 no-Long production construction count");
    std::printf("PASS RO2 production: 8 no-Long passes, %llu constructions, %llu visits\n",
                (unsigned long long)constructions, (unsigned long long)visits);
    constructions = visits = 0;
    T::shadow_foreign_passes();
    T::require(constructions > 0 && visits > 0, "Long production positive control never armed");
    std::printf("PASS RO2 production Long control: %llu constructions, %llu visits\n",
                (unsigned long long)constructions, (unsigned long long)visits);
    constructions = visits = 0;
    T::shadow_demotions(tomo::ThreadMode::Fused);
    T::require(visits > 0, "production demotion did not visit its older prefix");
    std::printf("PASS RO1 production demotion fixture: %llu slot visits (including parser)\n",
                (unsigned long long)visits);
}
