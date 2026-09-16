// Compile the alternate SET handlers in their own TU. Reuse the original private option
// parser/helpers without emitting the registry or exported string-family entry points.
#pragma GCC diagnostic ignored "-Wunused-function"
#define TOMO_STRING_NOTIFY_TU 1
#define TOMO_L4_PREBUILD_TU 1
#include "t_string.cc"

namespace tomo {
// The only size policy is this compile-time boundary (strictly greater, like kEmbedThreshold).
#ifndef TOMO_L4_PREBUILD_THRESHOLD
#define TOMO_L4_PREBUILD_THRESHOLD 192
#endif
static_assert(TOMO_L4_PREBUILD_THRESHOLD >= kEmbedThreshold);

namespace {
// Reuse the existing sidecar lane; never a borrowed reply. The handler detaches before any
// notification can claim that lane. IO cleans refused posts; the owner cleans admission/prepare
// errors before publishing Done, so every completed ordinary Op retains the original WB shape.
constexpr int32_t kPrebuiltSetMarker = -6;

struct PrebuiltSetValue {
    KvObj* object;
    explicit PrebuiltSetValue(Op& op)
        : object(reinterpret_cast<KvObj*>(const_cast<char*>(op.zc_ptr))) {
        if (!object || op.zc_shard != kPrebuiltSetMarker) std::abort();
        op.detach_scatter_state();
    }
    ~PrebuiltSetValue() { if (object) kvobj_free(object); }

    // KEEPTTL needs the owner's current object. Transfer the external payload to a new HEADER
    // only when its physical TTL reservation differs; never copy the value on the owner.
    bool deadline(int64_t expire, bool reserve) {
        const bool ttl = reserve || expire >= 0;
        if (object->has_ttl_slot() != ttl) {
            const Slice key = object->key();
            const size_t capacity = good_size(kvobj_alloc_size(key.n, object->vlen, ttl, Enc::Extern));
            auto* replacement = static_cast<KvObj*>(alloc_raw(capacity));
            if (!replacement) return false;
            replacement->type = object->type;
            replacement->enc = object->enc;
            replacement->flags = static_cast<uint8_t>(
                (object->flags & ~KvObjFlags::HasTtl) | (ttl ? KvObjFlags::HasTtl : 0));
            replacement->klen8 = object->klen8;
            replacement->init_nonraw_length(object->vlen);
            if (key.n >= 255) std::memcpy(replacement->tail(), &key.n, 4);
            if (ttl) replacement->set_expire_at_ms(expire);
            if (key.n) bytes_copy(replacement->key_ptr(), key.p, key.n);
            replacement->set_external_ptr(object->external_ptr());
            object->flags &= static_cast<uint8_t>(~KvObjFlags::OwnsExtern);
            kvobj_free(object);
            object = replacement;
        } else if (ttl) {
            object->set_expire_at_ms(expire);
        }
        return true;
    }
    template <bool Notify>
    StoreResult install(Shard& sh, uint64_t hash) {
        KvObj* value = object;
        object = nullptr;
        if constexpr (Notify) return map_insert_notify(sh, hash, value);
        return map_insert(sh.store(), hash, value);
    }
};

template <bool notify>
void cmd_set_prebuilt(Shard& sh, Op& op) {
    PrebuiltSetValue value(op);
    NotifyExecutionScope notifications(sh, op, notify);
    if (op.argc() == 3) {
        const StoreResult result = value.install<notify>(sh, op.hash);
        if (result != StoreResult::Stored) { reply_store_error(op, result); return; }
        if constexpr (notify) notify_record(sh, op, NOTIFY_STRING, NotifyEventId::Set, op.key());
        reply_ok(op.sink());
        return;
    }
    SetOptions options;
    if (!parse_set_options(sh, op, options)) return;
    KvObj* old = sh.store_find<notify>(op.hash, op.key());
    if (options.get) {
        auto sink = op.sink();
        if (!obj_type_check(old, Type::String, sink)) return;
        reply_string_bulk(op, old);
    }
    if ((options.nx && old) || (options.xx && !old)) {
        if (!options.get) reply_null(op.sink(), op.resp3());
        return;
    }
    int64_t expire = options.expire_at_ms;
    const bool reserve = options.keep_ttl && old && old->has_ttl_slot();
    if (options.keep_ttl && old) expire = sh.store().deadline(op.hash, old);
    if (expire >= 0 && expire <= sh.now_ms()) {
        if (old) sh.store_erase<notify>(op.hash, op.key());
        else if constexpr (notify)
            notify_record(sh, op, NOTIFY_GENERIC, NotifyEventId::Del, op.key());
        if (!options.get) reply_ok(op.sink());
        return;
    }
    const StoreResult result = value.deadline(expire, reserve)
        ? value.install<notify>(sh, op.hash) : StoreResult::Oom;
    if (result != StoreResult::Stored) { reply_store_error(op, result, options.get); return; }
    if constexpr (notify) {
        notify_record(sh, op, NOTIFY_STRING, NotifyEventId::Set, op.key());
        if (options.expire_kind != ExpireKind::None)
            notify_record(sh, op, NOTIFY_GENERIC, NotifyEventId::Expire, op.key());
    }
    if (!options.get) reply_ok(op.sink());
}
} // namespace

const CommandSpec* l4prebuild_notify_spec() {
    static const CommandSpec spec = [] {
        CommandSpec copy = *command_notify_variant(g_hot_command_specs.set);
        copy.handler = cmd_set_prebuilt<true>;
        return copy;
    }();
    return &spec;
}
// The kind-A control patches only this predicate to false in a COPY of POST. noipa prevents
// cloning/constant propagation, so both arms have identical text sizes and symbol addresses.
__attribute__((noipa)) bool l4prebuild_policy(uint32_t bytes) {
    return bytes > TOMO_L4_PREBUILD_THRESHOLD;
}

void l4prebuild_prepare_set(Op& op) {
    if (!l4prebuild_policy(op.arg(2).n)) return;
    // Best effort: an allocation failure leaves the exact original handler and OOM/option
    // precedence on the owner, including SET NX/XX that need not write at all.
    KvObj* value = kvobj_new_string(op.key(), op.arg(2));
    if (!value) return;
    static const CommandSpec clean = [] {
        CommandSpec copy = *g_hot_command_specs.set;
        copy.handler = cmd_set_prebuilt<false>;
        return copy;
    }();
    op.spec = (op.spec->flags & CmdFlags::NotifySelected) ? l4prebuild_notify_spec() : &clean;
    op.zc_ptr = reinterpret_cast<const char*>(value);
    op.zc_len = 0;
    op.zc_shard = kPrebuiltSetMarker;
}

void l4prebuild_discard_set(Op& op) {
    if (op.zc_shard != kPrebuiltSetMarker) return;
    PrebuiltSetValue unused(op);
}

} // namespace tomo
