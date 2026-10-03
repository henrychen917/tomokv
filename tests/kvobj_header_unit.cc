// ST10: keep the six db0 code-generation-sensitive builders honest without changing them.
#include "src/store/kvobj.h"
#include <cstdio>
#include <cstdlib>
#include <string>

using namespace tomo;

static void require(bool ok, const char* site, const char* claim) {
    if (!ok) {
        std::fprintf(stderr, "FAIL header %s: %s\n", site, claim);
        std::exit(1);
    }
}

static void compare(const char* site, KvObj* object, Slice key, Type type, Enc enc,
                    uint32_t length, bool ttl, uint8_t flags, int64_t deadline) {
    require(object, site, "allocation");
    alignas(KvObj) unsigned char storage[sizeof(KvObj) + sizeof(uint32_t)]{};
    auto* expected = reinterpret_cast<KvObj*>(storage);
    kvobj_init_header(expected, key, uint8_t(type), uint8_t(enc), length, ttl, flags);
    // Compare BEFORE decoding: a wrong KeyExt bit must fail here, not hide behind a
    // decoder which repeats the same mistake (or an out-of-bounds payload access).
    require(std::memcmp(object, expected, sizeof(KvObj)) == 0, site,
            "8-byte header equals kvobj_init_header");
    if (key.identity() >= 255)
        require(std::memcmp(object->tail(), expected->tail(), sizeof(uint32_t)) == 0,
                site, "extended key length equals kvobj_init_header");
    require(object->key().key_eq(key), site, "key bytes and namespace round trip");
    require(object->has_ttl_slot() == ttl && object->expire_at_ms() == deadline,
            site, "TTL slot and deadline round trip");
}

static void release(KvObj* object) {
    // External collection fixtures below borrow a dummy payload. Avoid the type
    // destructor; only the external STRING fixture owns an allocation here.
    if (object->type == uint8_t(Type::String) && object->encoding() == Enc::Extern)
        free_sized(object->external_ptr(), good_size(object->vlen));
    free_sized(object, kvobj_capacity(object));
}

int main(int argc, char** argv) {
    const std::string selected = argc == 2 ? argv[1] : "all";
    unsigned checked = 0;
    auto wants = [&](const char* site) { return selected == "all" || selected == site; };
    for (uint32_t db : {0u, 1u, 15u, 255u}) {
        if (kSingleDatabase && db) continue;
        for (uint32_t n : {0u, 1u, 254u, 255u, 256u, 307u}) {
            std::string bytes(n, '\0');
            if (n) bytes.back() = 'k';
            const Slice key(bytes.data(), n, db);
            for (unsigned variant = 0; variant < 3; ++variant) {
                const bool reserved = variant == 1;
                const int64_t deadline = variant == 2 ? 123456 : -1;
                const bool ttl = reserved || deadline >= 0;
                if (wants("raw")) {
                    const Slice value("raw", 3);
                    void* mem = alloc_raw(good_size(kvobj_alloc_size(key.identity(), value.n, ttl, Enc::Raw)));
                    auto* o = kvobj_init_raw_string(mem, key, value, deadline, reserved);
                    compare("raw", o, key, Type::String, Enc::Raw, value.n, ttl, 0, deadline);
                    release(o); ++checked;
                }
                if (wants("int")) {
                    void* mem = alloc_raw(good_size(kvobj_alloc_size(key.identity(), 0, ttl, Enc::Int)));
                    auto* o = kvobj_init_int(mem, key, 42, deadline, reserved);
                    compare("int", o, key, Type::String, Enc::Int, 0, ttl, 0, deadline);
                    release(o); ++checked;
                }
                if (wants("string")) {
                    const std::string value(kEmbedThreshold + 1, 'v');
                    auto* o = kvobj_new_string(key, Slice(value), deadline, reserved);
                    compare("string", o, key, Type::String, Enc::Extern, value.size(), ttl,
                            KvObjFlags::OwnsExtern, deadline);
                    release(o); ++checked;
                }
                for (Type type : {Type::Hash, Type::List, Type::Set, Type::Zset}) {
                    if (wants("typeval")) for (bool owns : {false, true}) {
                        uint64_t payload = 0;
                        auto* o = kvobj_new_typeval(key, type, &payload, sizeof(payload),
                                                   deadline, owns, reserved);
                        compare("typeval", o, key, type, Enc::Extern, sizeof(payload), ttl,
                                owns ? KvObjFlags::OwnsExtern : 0, deadline);
                        release(o); ++checked;
                    }
                    Compact compact;
                    require(compact.append(Slice("entry", 5)), "fixture", "compact payload");
                    const uint32_t length = sizeof(EmbeddedCompact) + compact.encoded_bytes();
                    if (wants("embedded")) {
                        auto* o = kvobj_new_embedded_typeval(key, type, compact, 7, 9,
                                                            deadline, reserved);
                        compare("embedded", o, key, type, Enc::Compact, length, ttl, 0, deadline);
                        release(o); ++checked;
                    }
                    if (wants("reheader")) {
                        auto* source = kvobj_new_embedded_typeval(key, type, compact, 7, 9,
                                                                 deadline, reserved);
                        require(source, "reheader", "source allocation");
                        for (int64_t next : {int64_t(-1), int64_t(654321)}) {
                            auto* o = kvobj_reheader(source, next);
                            compare("reheader", o, key, type, Enc::Compact, length,
                                    ttl || next >= 0, 0, next);
                            release(o); ++checked;
                        }
                        release(source);
                    }
                }
            }
        }
    }
    require(checked != 0, "selection", "at least one builder exercised");
    std::printf("PASS header %s: %u comparisons (%s)\n", selected.c_str(), checked,
                kSingleDatabase ? "db0" : "multi");
}
