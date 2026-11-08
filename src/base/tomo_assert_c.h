// Stable assertion diagnostics for the shared Lua helper C translation units.
// Included by lua_cmsgpack.c, lua_cjson.c and fpconv.c; enabled failures call __assert_fail, while NDEBUG
// omits condition evaluation. This C interface takes explicit ids rather than hashing conditions.
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
