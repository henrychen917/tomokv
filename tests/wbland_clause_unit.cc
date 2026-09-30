// Reuse every REF clause/read-order witness with a runtime policy read.
#include "src/core/wb_rule.h"
namespace tomo::wb_rule {
template <class C> bool wbland_clause(C& c) {
    volatile int policy = 1;
    return defer(c, policy);
}
}
#define defer wbland_clause
#include "wb_rule_unit.cc"
