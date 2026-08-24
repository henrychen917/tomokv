// kvobj.h — one key-value pair in ONE allocation.
//
// Layout, contiguous, in this order:
//
//   [ hdr 8B ][ klen_ext u32? ][ expire_at i64? ][ key bytes ][ value: inline bytes | void* | i64 ]
//
// Three rules drive this, all of them measured on the fork rather than assumed:
//
//  1. ALLOCATION COUNT is the lever (a bespoke size-class pool was built and deleted; the measured
//     win was fewer allocations, not cleverer ones). So key and value live in the same block as the
//     header, and small values never allocate separately. Embedding was worth +27% on SET.
//  2. NO REFCOUNT. Redis's robj refcount is a cross-thread hazard in a sharded server and its
//     traffic is a shared-line write. A KvObj is owned outright by one shard: copy or move, never
//     share. There is no shared-integer cache either.
//  3. NOTHING STORED THAT THE TABLE ALREADY HAS. FlatStore's slot carries a 15-bit tag, so no hash
//     is kept here. No LRU/LFU field unless eviction is compiled in.
//
// BUDGET (this is a test, not an aspiration — see bench/kvobj_footprint):
//   16-byte key + 64-byte value, no TTL  ->  target < 85 B all-in.
//   Today: 8 + 16 + 64 = 88 B before the allocator's size class. Getting under the bar needs the
//   varint header noted at TODO(density); doing it before the data path works would be premature.
#pragma once
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <new>
#include "../base/slice.h"
#include "../base/alloc.h"
#include "../net/resp.h"
#include "typeval.h"

namespace tomo {

enum class Type : uint8_t { String = 0, Hash = 1, List = 2, Set = 3, Zset = 4 };

enum class Enc : uint8_t {
    Raw    = 0,   // value bytes inline in this block
    Int    = 1,   // value IS an int64 held in the block; no bytes, no allocation
    Extern = 2,   // value lives in a separate block; the slot holds a void*
    // collection encodings land here later: FlatArray (compact) / Table (scalable) / BTree / Deque.
    // Promotion between them is on ELEMENT COUNT, never on total bytes — a byte-bounded compact
    // form is what made hash writes O(n) in the fork and had to be deleted.
};

struct KvObjFlags {
    static constexpr uint8_t HasTtl = 1u << 0;
    static constexpr uint8_t KeyExt = 1u << 1;   // klen did not fit in 8 bits; u32 follows the hdr
    // Re-headering a collection moves this ownership bit to the replacement before FlatStore
    // retires the old header. Both headers briefly name the pointer; exactly one may destroy it.
    static constexpr uint8_t OwnsExtern = 1u << 2;
};

// Header is exactly 8 bytes. Fields are ordered so the hot ones (type/enc/flags) share one word.
struct KvObj {
    uint8_t  type;      // Type
    uint8_t  enc;       // Enc
    uint8_t  flags;     // KvObjFlags
    uint8_t  klen8;     // key length when < 255; 255 means "see the u32 after the header"
    uint32_t vlen;      // inline value length, or external length when Enc::Extern

    // ---- layout arithmetic -------------------------------------------------------------------
    // Everything after the header is optional and positional, so all offsets are computed rather
    // than stored. Kept in one place: get these wrong and every accessor is wrong together.
    uint32_t klen_ext_bytes() const { return (flags & KvObjFlags::KeyExt) ? 4u : 0u; }
    uint32_t ttl_bytes()      const { return (flags & KvObjFlags::HasTtl) ? 8u : 0u; }

    char*       tail()       { return reinterpret_cast<char*>(this) + sizeof(KvObj); }
    const char* tail() const { return reinterpret_cast<const char*>(this) + sizeof(KvObj); }

    uint32_t klen() const {
        if (flags & KvObjFlags::KeyExt) {
            uint32_t k;
            std::memcpy(&k, tail(), 4);
            return k;
        }
        return klen8;
    }

    char*       key_ptr()       { return tail() + klen_ext_bytes() + ttl_bytes(); }
    const char* key_ptr() const { return tail() + klen_ext_bytes() + ttl_bytes(); }
    Slice       key()     const { return Slice(key_ptr(), klen()); }

    char*       val_ptr()       { return key_ptr() + klen(); }
    const char* val_ptr() const { return key_ptr() + klen(); }

    int64_t expire_at_ms() const {
        if (!(flags & KvObjFlags::HasTtl)) return -1;
        int64_t t;
        std::memcpy(&t, tail() + klen_ext_bytes(), 8);
        return t;
    }
    void set_expire_at_ms(int64_t t) {
        // Only valid when the object was built with HasTtl — the slot must already exist.
        std::memcpy(tail() + klen_ext_bytes(), &t, 8);
    }

    // ---- value access ------------------------------------------------------------------------
    Slice str_value() const {
        if (static_cast<Enc>(enc) == Enc::Extern) {
            void* p;
            std::memcpy(&p, val_ptr(), sizeof(void*));
            return Slice(static_cast<const char*>(p), vlen);
        }
        return Slice(val_ptr(), vlen);   // Enc::Raw
    }
    int64_t int_value() const {
        int64_t v;
        std::memcpy(&v, val_ptr(), 8);
        return v;
    }
    void set_int_value(int64_t v) { std::memcpy(val_ptr(), &v, 8); }

    void* external_ptr() const {
        void* p;
        std::memcpy(&p, val_ptr(), sizeof(void*));
        return p;
    }
    void set_external_ptr(void* p) { std::memcpy(val_ptr(), &p, sizeof(void*)); }

    bool is_int() const { return static_cast<Enc>(enc) == Enc::Int; }
    bool is_type(Type t) const { return static_cast<Type>(type) == t; }
};

static_assert(sizeof(KvObj) == 8, "KvObj header must stay 8 bytes");

// ---- construction ----------------------------------------------------------------------------
// Values at or below this live in the same block as the key. 192 was validated on the fork, but
// against Redis's allocation shape rather than this one, so it is a starting point to re-measure —
// it trades RSS against SET throughput.
inline constexpr uint32_t kEmbedThreshold = 192;

inline size_t kvobj_alloc_size(uint32_t klen, uint32_t vlen, bool has_ttl, Enc enc) {
    size_t n = sizeof(KvObj);
    if (klen >= 255) n += 4;
    if (has_ttl)     n += 8;
    n += klen;
    switch (enc) {
        case Enc::Int:    n += 8; break;
        case Enc::Extern: n += sizeof(void*); break;
        case Enc::Raw:    n += vlen; break;
    }
    return n;
}

// Builds a String KvObj. `val` is copied when it fits the embed threshold, otherwise a second block
// holds it and this one keeps the pointer. Returns nullptr on OOM rather than throwing: the worker
// loop reports an error reply instead of unwinding.
inline KvObj* kvobj_new_string(Slice key, Slice val, int64_t expire_at_ms = -1) {
    const bool  has_ttl = expire_at_ms >= 0;
    const Enc   enc     = (val.n <= kEmbedThreshold) ? Enc::Raw : Enc::Extern;
    // Request the CLASS-ROUNDED size explicitly. try_overwrite writes up to good_size(request),
    // which is only within the allocation if the allocation asked for it: on jemalloc the class
    // rounds up anyway (zero cost), on an exact allocator (ASAN, glibc) requesting the raw size
    // made that write a heap overflow -- a 3-byte corruption the gate's RYOW-under-ASAN caught.
    const size_t n      = good_size(kvobj_alloc_size(key.n, val.n, has_ttl, enc));

    void* mem = alloc_raw(n);
    if (!mem) return nullptr;

    auto* o  = static_cast<KvObj*>(mem);
    o->type  = static_cast<uint8_t>(Type::String);
    o->enc   = static_cast<uint8_t>(enc);
    o->flags = static_cast<uint8_t>((has_ttl ? KvObjFlags::HasTtl : 0) |
                                    (key.n >= 255 ? KvObjFlags::KeyExt : 0) |
                                    (enc == Enc::Extern ? KvObjFlags::OwnsExtern : 0));
    o->klen8 = static_cast<uint8_t>(key.n >= 255 ? 255 : key.n);
    o->vlen  = val.n;

    if (key.n >= 255) { uint32_t k = key.n; std::memcpy(o->tail(), &k, 4); }
    if (has_ttl)      { o->set_expire_at_ms(expire_at_ms); }

    std::memcpy(o->key_ptr(), key.p, key.n);

    if (enc == Enc::Raw) {
        std::memcpy(o->val_ptr(), val.p, val.n);
    } else {
        void* ext = alloc_raw(good_size(val.n));   // same contract as the main block
        if (!ext) { free_sized(mem, n); return nullptr; }
        std::memcpy(ext, val.p, val.n);
        std::memcpy(o->val_ptr(), &ext, sizeof(void*));
    }
    return o;
}

inline KvObj* kvobj_new_int(Slice key, int64_t value, int64_t expire_at_ms = -1) {
    const bool has_ttl = expire_at_ms >= 0;
    const size_t n = good_size(kvobj_alloc_size(key.n, 0, has_ttl, Enc::Int));
    void* mem = alloc_raw(n);
    if (!mem) return nullptr;

    auto* o = static_cast<KvObj*>(mem);
    o->type = static_cast<uint8_t>(Type::String);
    o->enc = static_cast<uint8_t>(Enc::Int);
    o->flags = static_cast<uint8_t>((has_ttl ? KvObjFlags::HasTtl : 0) |
                                    (key.n >= 255 ? KvObjFlags::KeyExt : 0));
    o->klen8 = static_cast<uint8_t>(key.n >= 255 ? 255 : key.n);
    o->vlen = 0;
    if (key.n >= 255) { uint32_t k = key.n; std::memcpy(o->tail(), &k, 4); }
    if (has_ttl) o->set_expire_at_ms(expire_at_ms);
    std::memcpy(o->key_ptr(), key.p, key.n);
    o->set_int_value(value);
    return o;
}

inline KvObj* kvobj_new_typeval(Slice key, Type type, void* value, uint32_t value_size,
                                int64_t expire_at_ms = -1, bool owns = true) {
    if (type == Type::String || !value) return nullptr;
    const bool has_ttl = expire_at_ms >= 0;
    const size_t n = good_size(kvobj_alloc_size(key.n, value_size, has_ttl, Enc::Extern));
    void* mem = alloc_raw(n);
    if (!mem) return nullptr;

    auto* o = static_cast<KvObj*>(mem);
    o->type = static_cast<uint8_t>(type);
    o->enc = static_cast<uint8_t>(Enc::Extern);
    o->flags = static_cast<uint8_t>((has_ttl ? KvObjFlags::HasTtl : 0) |
                                    (key.n >= 255 ? KvObjFlags::KeyExt : 0) |
                                    (owns ? KvObjFlags::OwnsExtern : 0));
    o->klen8 = static_cast<uint8_t>(key.n >= 255 ? 255 : key.n);
    o->vlen = value_size;
    if (key.n >= 255) { uint32_t k = key.n; std::memcpy(o->tail(), &k, 4); }
    if (has_ttl) o->set_expire_at_ms(expire_at_ms);
    std::memcpy(o->key_ptr(), key.p, key.n);
    o->set_external_ptr(value);
    return o;
}

inline KvObj* kvobj_new_hash(Slice key, HashVal* value, int64_t expire_at_ms = -1) {
    return kvobj_new_typeval(key, Type::Hash, value, sizeof(*value), expire_at_ms);
}
inline KvObj* kvobj_new_list(Slice key, ListVal* value, int64_t expire_at_ms = -1) {
    return kvobj_new_typeval(key, Type::List, value, sizeof(*value), expire_at_ms);
}
inline KvObj* kvobj_new_set(Slice key, SetVal* value, int64_t expire_at_ms = -1) {
    return kvobj_new_typeval(key, Type::Set, value, sizeof(*value), expire_at_ms);
}
inline KvObj* kvobj_new_zset(Slice key, ZsetVal* value, int64_t expire_at_ms = -1) {
    return kvobj_new_typeval(key, Type::Zset, value, sizeof(*value), expire_at_ms);
}

// Creates the replacement header needed when HasTtl changes the positional layout. Strings are
// copied because their bytes may be borrowed by a zero-copy send. Collections are single-owner and
// move their external ownership in FlatStore::rewrite_expire().
inline KvObj* kvobj_reheader(KvObj* src, int64_t expire_at_ms) {
    const Type type = static_cast<Type>(src->type);
    if (type == Type::String) {
        if (src->is_int()) return kvobj_new_int(src->key(), src->int_value(), expire_at_ms);
        return kvobj_new_string(src->key(), src->str_value(), expire_at_ms);
    }
    return kvobj_new_typeval(src->key(), type, src->external_ptr(), src->vlen,
                             expire_at_ms, false);
}

// What this object ASKED the allocator for. Used to free it (sized free) and as the basis for its
// capacity. Recomputed rather than stored: a size field would cost every key 4 bytes to save a
// multiply, and the computation is a pure function of the header.
inline size_t kvobj_request_size(const KvObj* o) {
    return kvobj_alloc_size(o->klen(), o->vlen, (o->flags & KvObjFlags::HasTtl) != 0,
                            static_cast<Enc>(o->enc));
}

// What the allocator actually handed back. The slack between request and class is already paid for,
// and exposing it is what lets a SET whose value grew by a few bytes still avoid allocating.
inline size_t kvobj_capacity(const KvObj* o) { return good_size(kvobj_request_size(o)); }

// Real footprint, for the store's resident estimate: the size CLASS, not the request, plus any
// external value block.
inline size_t kvobj_size(const KvObj* o) {
    size_t n = kvobj_capacity(o);
    if (static_cast<Enc>(o->enc) != Enc::Extern) return n;
    switch (static_cast<Type>(o->type)) {
        case Type::String: n += good_size(o->vlen); break;
        case Type::Hash:
            n += static_cast<HashVal*>(o->external_ptr())->allocation_bytes() +
                 sizeof(HashVal) - sizeof(CompactValue);
            break;
        case Type::List:
            n += static_cast<ListVal*>(o->external_ptr())->allocation_bytes() +
                 sizeof(ListVal) - sizeof(CompactValue);
            break;
        case Type::Set:
            n += static_cast<SetVal*>(o->external_ptr())->allocation_bytes() +
                 sizeof(SetVal) - sizeof(CompactValue);
            break;
        case Type::Zset:
            n += static_cast<ZsetVal*>(o->external_ptr())->allocation_bytes() +
                 sizeof(ZsetVal) - sizeof(CompactValue);
            break;
    }
    return n;
}

inline void kvobj_free(KvObj* o) {
    if (!o) return;
    const size_t n = good_size(kvobj_request_size(o));   // compute BEFORE the value block is released
    if (static_cast<Enc>(o->enc) == Enc::Extern && (o->flags & KvObjFlags::OwnsExtern)) {
        void* ext = o->external_ptr();
        switch (static_cast<Type>(o->type)) {
            case Type::String: free_sized(ext, good_size(o->vlen)); break;
            case Type::Hash: delete static_cast<HashVal*>(ext); break;
            case Type::List: delete static_cast<ListVal*>(ext); break;
            case Type::Set:  delete static_cast<SetVal*>(ext); break;
            case Type::Zset: delete static_cast<ZsetVal*>(ext); break;
        }
    }
    // Sized free: ordinary free() has to look up how big the block was; we already know.
    free_sized(o, n);
}

template <typename Sink>
inline bool obj_type_check(const KvObj* o, Type wanted, Sink&& sink) {
    if (!o || static_cast<Type>(o->type) == wanted) return true;
    reply_wrongtype(sink);
    return false;
}

}  // namespace tomo
