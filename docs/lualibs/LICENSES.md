# Lua helper licenses and provenance

These third-party libraries are imported from the Redis 7.4.10 distribution,
local checkout `/home/user/Projects/redis`, commit
`f103d127b9747965e28f20615ef790332661fc68`, directory `deps/lua/src/`.
Their own permissive licenses, rather than the Redis server license, apply.
The complete copyright, permission and warranty notices remain in the files.
Upstream source: https://github.com/redis/redis/tree/f103d127b9747965e28f20615ef790332661fc68/deps/lua/src

| File under `third_party/lua/helpers/` | License | Copyright / origin |
|---|---|---|
| lua_cjson.c | MIT | Mark Pulford, 2010–2012; Lua CJSON 2.1.0, Redis distribution |
| lua_cmsgpack.c | MIT | Salvatore Sanfilippo, 2012; lua-cmsgpack, Redis distribution |
| lua_bit.c | MIT | Mike Pall, 2008–2012; Lua BitOp, Redis distribution |
| lua_struct.c | MIT | Lua.org, PUC-Rio, 2010–2018; Lua struct, Redis distribution |
| strbuf.c | MIT | Mark Pulford, 2010–2012; Lua CJSON buffer |
| strbuf.h | MIT | Mark Pulford, 2010–2012; Lua CJSON buffer declarations |
| fpconv.c | MIT | Mark Pulford, 2011–2012; Lua CJSON floating-point conversion |
| fpconv.h | MIT (associated fpconv.c notice) | Lua CJSON floating-point declarations; upstream header has no separate notice |

Local changes: `lua_cjson.c` drops the Solaris-only Redis server header include
(the header has a different license and is **not imported**); platform `math.h`
provides the needed operations on this Linux target. `fpconv.c` makes its locale
cache C11 thread-local, preventing concurrent initialization/read races between
executor Lua states. It costs one byte of TLS per OS thread. All other helper
files are byte-identical to the origin. Redis uses libc fpconv, and this build
uses the same backend and the same default options and limits.

`redis.sha1hex` is independently wired to TomoKV's existing SHA-1 implementation
in `src/cmd/scripting.cc`; no code or notices from Redis's `script_lua.c` or its
SHA implementation are copied. Redis's callable contract was used as the oracle.
The existing Lua VM and its MIT notice in `third_party/lua` are unchanged.

## Original file SHA-256s

- `lua_cjson.c`: `20bcf34ee652800d41d769847022315d2e04beffb5c3070b8321f0e7f69d0054`
- `lua_cmsgpack.c`: `0d2fd82fb47fc247a0e6f0a287f5429e81b7eb6735665e8d851bfb109961640d`
- `lua_bit.c`: `78e10247b33d0db026cbe906d19b4bd3636840f195a63e93ce08c5dee9fb578a`
- `lua_struct.c`: `57bc18e91a747a846ba76c070d9213452283c0ed9e652861ee7fabf87d590878`
- `strbuf.c`: `46f386f1640d436a1fe03b4150e6be5751114e9f5de007ef231774e06ac95ebd`
- `strbuf.h`: `830ab40b6da9ae6aa2d53452720be83b1e1ff7f02899739a1b1b288e15182362`
- `fpconv.c`: `29f80d82e6356f2110eb2721cdcaad4dd49f80463774334d747ffd882c4c05df`
- `fpconv.h`: `61cb0f044e1dfccfcda0908b9330da250d386454e95acda4bf78b2188fc64070`
