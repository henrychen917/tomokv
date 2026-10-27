// Serverless allocation census of the actual production sandbox constructors.
// Lua's GC count excludes cjson's malloc-backed persistent encode buffer, so
// report jemalloc's net thread allocation as well. No server or load generator.
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <jemalloc/jemalloc.h>
extern "C" {
#include "third_party/lua/lua.h"
}
namespace tomo { lua_State* script_new_sandbox_state(); }
namespace tomo_db0 { lua_State* script_new_sandbox_state(); }

// PRE's frozen scripting object predates this callback. The registry objects
// are not executed by this constructor-only census; fail loudly if that ever
// changes. POST's real strong definitions override these unreachable stubs.
namespace tomo {
__attribute__((weak)) void script_sync_function_helpers(lua_State*, uint64_t) { std::abort(); }
}
namespace tomo_db0 {
__attribute__((weak)) void script_sync_function_helpers(lua_State*, uint64_t) { std::abort(); }
}

static uint64_t allocated() {
    uint64_t a = 0, d = 0;
    size_t size = sizeof(a);
    assert(mallctl("thread.allocated", &a, &size, nullptr, 0) == 0);
    size = sizeof(d);
    assert(mallctl("thread.deallocated", &d, &size, nullptr, 0) == 0);
    return a - d;
}

int main() {
    setvbuf(stdout, nullptr, _IONBF, 0);
    for (int variant = 0; variant < 2; ++variant) {
        for (int repeat = 0; repeat < 4; ++repeat) {
            const auto before = allocated();
            lua_State* state = variant ? tomo_db0::script_new_sandbox_state()
                                       : tomo::script_new_sandbox_state();
            assert(state);
            const auto constructed = allocated() - before;
            lua_gc(state, LUA_GCCOLLECT, 0);
            const auto retained = allocated() - before;
            const auto lua_bytes = lua_gc(state, LUA_GCCOUNT, 0) * 1024 +
                                   lua_gc(state, LUA_GCCOUNTB, 0);
            lua_close(state);
            const auto remaining = allocated() - before;
            printf("{\"variant\":%d,\"repeat\":%d,\"constructed_bytes\":%llu,"
                   "\"retained_bytes\":%llu,\"lua_gc_bytes\":%d,\"after_close_bytes\":%llu}\n",
                   variant, repeat, (unsigned long long)constructed,
                   (unsigned long long)retained, lua_bytes, (unsigned long long)remaining);
            assert(remaining == 0);
        }
    }
}
