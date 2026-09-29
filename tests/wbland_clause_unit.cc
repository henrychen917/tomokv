// Reuse every original clause/read-order witness with a runtime-derived fraction.
#include "src/core/wb_rule.h"
namespace tomo::wb_rule {
template <class C> bool wbland_clause(C& c) {
    State s(-1, true, 0);
    s.pass(0, 0, 1); s.pass(256, 128, 1); s.pass(512, 256, 1);
    return defer(c, s.fraction);
}
}
#define defer wbland_clause
#include "wb_rule_unit.cc"
