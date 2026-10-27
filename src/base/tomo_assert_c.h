// Stable assertion diagnostics for the shared Lua helper C translation units.
// C sites pin their generated ids explicitly; assert_map.py checks uniqueness
// and records their physical locations in the same map as the C++ sites.
#pragma once
#include <assert.h>

#ifdef NDEBUG
#define TOMO_ASSERT_ID(cond, id) ((void)0)
#else
#define TOMO_ASSERT_ID(cond, id) \
    ((cond) ? (void)0 : __assert_fail("see tomokv.asserts", "tomokv", (id), "site"))
#endif
