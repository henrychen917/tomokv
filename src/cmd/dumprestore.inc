// DUMP / RESTORE -- TomoKV's deliberately self-compatible value envelope.
// The payload bytes are emitted and consumed only by SnapshotTypeHooks; this file adds framing,
// validation, TTL grammar, and insertion, not a second per-type serializer.

namespace tomo {
namespace {

bool restore_parse_i64(Slice input, int64_t& output) {
    if (input.n == 0 || input.n >= 32) return false;
    uint32_t position = 0;
    bool negative = false;
    if (input.p[position] == '-') {
        negative = true;
        if (++position == input.n) return false;
    }
    if (input.p[position] == '0') {
        if (negative || position + 1 != input.n) return false;
        output = 0;
        return true;
    }
    if (input.p[position] < '1' || input.p[position] > '9') return false;
    uint64_t value = 0;
    const uint64_t limit = negative ? uint64_t{INT64_MAX} + 1 : uint64_t{INT64_MAX};
    for (; position < input.n; position++) {
        const unsigned char byte = static_cast<unsigned char>(input.p[position]);
        if (byte < '0' || byte > '9') return false;
        const uint32_t digit = byte - '0';
        if (value > (limit - digit) / 10) return false;
        value = value * 10 + digit;
    }
    if (negative) {
        output = value == uint64_t{INT64_MAX} + 1
            ? INT64_MIN : -static_cast<int64_t>(value);
    } else {
        output = static_cast<int64_t>(value);
    }
    return true;
}

inline constexpr uint8_t kDumpMagic[8] = {'T', 'O', 'M', 'O', 'D', 'M', 'P', 0};
inline constexpr uint16_t kDumpVersion = 0x8001;
inline constexpr size_t kDumpHeaderBytes = 12;  // magic + u16 version + u8 type + u8 encoding
inline constexpr size_t kDumpChecksumBytes = 8;

uint64_t dump_rotl64(uint64_t value, uint32_t shift) {
    return (value << shift) | (value >> (64 - shift));
}

uint64_t dump_read_u64(const uint8_t* bytes) {
    uint64_t value = 0;
    std::memcpy(&value, bytes, sizeof(value));
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
    value = __builtin_bswap64(value);
#endif
    return value;
}

uint32_t dump_read_u32(const uint8_t* bytes) {
    uint32_t value = 0;
    std::memcpy(&value, bytes, sizeof(value));
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
    value = __builtin_bswap32(value);
#endif
    return value;
}

// XXH64, seed 0. The checksum covers exactly the SnapshotTypeHooks payload bytes.
uint64_t dump_xxh64(const uint8_t* bytes, size_t length) {
    constexpr uint64_t p1 = 11400714785074694791ULL;
    constexpr uint64_t p2 = 14029467366897019727ULL;
    constexpr uint64_t p3 = 1609587929392839161ULL;
    constexpr uint64_t p4 = 9650029242287828579ULL;
    constexpr uint64_t p5 = 2870177450012600261ULL;
    auto round = [=](uint64_t accumulator, uint64_t lane) {
        accumulator += lane * p2;
        accumulator = dump_rotl64(accumulator, 31);
        return accumulator * p1;
    };
    const uint8_t* cursor = bytes;
    const uint8_t* end = bytes + length;
    uint64_t hash = 0;
    if (length >= 32) {
        uint64_t v1 = p1 + p2, v2 = p2, v3 = 0, v4 = 0 - p1;
        const uint8_t* limit = end - 32;
        do {
            v1 = round(v1, dump_read_u64(cursor)); cursor += 8;
            v2 = round(v2, dump_read_u64(cursor)); cursor += 8;
            v3 = round(v3, dump_read_u64(cursor)); cursor += 8;
            v4 = round(v4, dump_read_u64(cursor)); cursor += 8;
        } while (cursor <= limit);
        hash = dump_rotl64(v1, 1) + dump_rotl64(v2, 7) +
               dump_rotl64(v3, 12) + dump_rotl64(v4, 18);
        const uint64_t lanes[] = {v1, v2, v3, v4};
        for (uint64_t lane : lanes) {
            hash ^= round(0, lane);
            hash = hash * p1 + p4;
        }
    } else {
        hash = p5;
    }
    hash += length;
    while (cursor + 8 <= end) {
        const uint64_t lane = round(0, dump_read_u64(cursor));
        hash ^= lane;
        hash = dump_rotl64(hash, 27) * p1 + p4;
        cursor += 8;
    }
    if (cursor + 4 <= end) {
        hash ^= static_cast<uint64_t>(dump_read_u32(cursor)) * p1;
        hash = dump_rotl64(hash, 23) * p2 + p3;
        cursor += 4;
    }
    while (cursor < end) {
        hash ^= static_cast<uint64_t>(*cursor++) * p5;
        hash = dump_rotl64(hash, 11) * p1;
    }
    hash ^= hash >> 33; hash *= p2;
    hash ^= hash >> 29; hash *= p3;
    return hash ^ (hash >> 32);
}

void reply_dump_payload_error(Op& op) {
    reply_err(op.sink(), "ERR DUMP payload version or checksum are wrong");
}

template <bool kNotify>
void cmd_dump(Shard& shard, Op& op) {
    KvObj* object = shard.store_find<kNotify>(op.hash, op.key());
    if (!object) { reply_nil(op.sink()); return; }
    const Type type = static_cast<Type>(object->type);
    const SnapshotTypeHooks& hooks = snapshot_type_hooks(type);
    SnapshotSaveCursor cursor;
    uint8_t encoding = 0;
    if (!hooks.begin_save || !hooks.read_save ||
        hooks.begin_save(*object, cursor, encoding) != SnapshotHookStatus::Ok ||
        cursor.total > UINT32_MAX - kDumpHeaderBytes - kDumpChecksumBytes) {
        reply_err(op.sink(), "ERR object could not be serialized");
        return;
    }

    std::string envelope;
    try {
        envelope.resize(kDumpHeaderBytes + static_cast<size_t>(cursor.total) +
                        kDumpChecksumBytes);
    } catch (const std::bad_alloc&) {
        reply_err(op.sink(), "ERR out of memory");
        return;
    }
    uint8_t* bytes = reinterpret_cast<uint8_t*>(envelope.data());
    std::memcpy(bytes, kDumpMagic, sizeof(kDumpMagic));
    bytes[8] = static_cast<uint8_t>(kDumpVersion);
    bytes[9] = static_cast<uint8_t>(kDumpVersion >> 8);
    bytes[10] = static_cast<uint8_t>(type);
    bytes[11] = encoding;
    while (cursor.offset < cursor.total) {
        size_t written = 0;
        const size_t remaining = static_cast<size_t>(cursor.total - cursor.offset);
        if (hooks.read_save(cursor, bytes + kDumpHeaderBytes + cursor.offset,
                            remaining, written) != SnapshotHookStatus::Ok || !written ||
            written > remaining) {
            reply_err(op.sink(), "ERR object could not be serialized");
            return;
        }
    }
    const uint8_t* payload = bytes + kDumpHeaderBytes;
    snapshot_put_u64(bytes + kDumpHeaderBytes + cursor.total,
                     dump_xxh64(payload, static_cast<size_t>(cursor.total)));
    reply_bulk(op.sink(), Slice(envelope.data(), static_cast<uint32_t>(envelope.size())));
}

struct RestoreOptions {
    bool replace = false;
    bool absttl = false;
};

bool parse_restore_options(Op& op, RestoreOptions& options) {
    bool idletime_seen = false;
    bool freq_seen = false;
    for (uint32_t index = 4; index < op.argc(); index++) {
        if (op.arg(index).eq_icase("replace")) {
            options.replace = true;
        } else if (op.arg(index).eq_icase("absttl")) {
            options.absttl = true;
        } else if (op.arg(index).eq_icase("idletime") && index + 1 < op.argc() &&
                   !freq_seen) {
            int64_t seconds = 0;
            if (!restore_parse_i64(op.arg(++index), seconds)) {
                reply_err(op.sink(), "ERR value is not an integer or out of range");
                return false;
            }
            if (seconds < 0) {
                reply_err(op.sink(), "ERR Invalid IDLETIME value, must be >= 0");
                return false;
            }
            idletime_seen = true;
        } else if (op.arg(index).eq_icase("freq") && index + 1 < op.argc() &&
                   !idletime_seen) {
            int64_t frequency = 0;
            if (!restore_parse_i64(op.arg(++index), frequency)) {
                reply_err(op.sink(), "ERR value is not an integer or out of range");
                return false;
            }
            if (frequency < 0 || frequency > 255) {
                reply_err(op.sink(), "ERR Invalid FREQ value, must be >= 0 and <= 255");
                return false;
            }
            freq_seen = true;
        } else {
            reply_syntax(op.sink());
            return false;
        }
    }
    return true;
}

bool decode_dump_envelope(Op& op, Slice envelope, Type& type, uint8_t& encoding,
                          Slice& payload) {
    if (envelope.n < kDumpHeaderBytes + kDumpChecksumBytes) {
        reply_dump_payload_error(op);
        return false;
    }
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(envelope.p);
    const uint16_t version = static_cast<uint16_t>(bytes[8]) |
                             (static_cast<uint16_t>(bytes[9]) << 8);
    const uint8_t raw_type = bytes[10];
    const size_t payload_length = envelope.n - kDumpHeaderBytes - kDumpChecksumBytes;
    const uint8_t* payload_bytes = bytes + kDumpHeaderBytes;
    const uint64_t expected = snapshot_get_u64(payload_bytes + payload_length);
    if (std::memcmp(bytes, kDumpMagic, sizeof(kDumpMagic)) != 0 ||
        version != kDumpVersion || raw_type > static_cast<uint8_t>(Type::Stream) ||
        expected != dump_xxh64(payload_bytes, payload_length)) {
        reply_dump_payload_error(op);
        return false;
    }
    type = static_cast<Type>(raw_type);
    encoding = bytes[11];
    payload = Slice(reinterpret_cast<const char*>(payload_bytes),
                    static_cast<uint32_t>(payload_length));
    return true;
}

template <bool kNotify>
void cmd_restore(Shard& shard, Op& op) {
    RestoreOptions options;
    if (!parse_restore_options(op, options)) return;

    KvObj* existing = shard.store_find<kNotify>(op.hash, op.key());
    if (existing && !options.replace) {
        reply_err(op.sink(), "BUSYKEY Target key name already exists.");
        return;
    }

    int64_t ttl = 0;
    if (!restore_parse_i64(op.arg(2), ttl)) {
        reply_err(op.sink(), "ERR value is not an integer or out of range");
        return;
    }
    if (ttl < 0) {
        reply_err(op.sink(), "ERR Invalid TTL value, must be >= 0");
        return;
    }

    Type type = Type::String;
    uint8_t encoding = 0;
    Slice payload;
    if (!decode_dump_envelope(op, op.arg(3), type, encoding, payload)) return;

    int64_t expire_at_ms = -1;
    if (ttl != 0) {
        if (options.absttl) {
            expire_at_ms = ttl;
        } else {
            // Redis performs this addition in mstime_t. Preserve its observed two's-complement
            // wrap at INT64_MAX: a wrapped deadline is already expired and takes the OK/no-key
            // path below.
            const uint64_t wrapped = static_cast<uint64_t>(ttl) +
                                     static_cast<uint64_t>(shard.now_ms());
            std::memcpy(&expire_at_ms, &wrapped, sizeof(expire_at_ms));
        }
    }

    KvObj* restored = nullptr;
    const SnapshotTypeHooks& hooks = snapshot_type_hooks(type);
    const SnapshotHookStatus loaded = hooks.load
        ? hooks.load(op.key(), encoding, expire_at_ms, payload, shard.type_limits(), restored)
        : SnapshotHookStatus::Corrupt;
    if (loaded != SnapshotHookStatus::Ok || !restored) {
        if (restored) kvobj_free(restored);
        if (loaded == SnapshotHookStatus::Oom) reply_err(op.sink(), "ERR out of memory");
        else reply_err(op.sink(), "ERR Bad data format");
        return;
    }

    if (ttl != 0 && expire_at_ms <= shard.now_ms()) {
        kvobj_free(restored);
        if (options.replace && existing) shard.store_erase<kNotify>(op.hash, op.key());
        reply_ok(op.sink());
        return;
    }

    const FlatStore::InsertResult inserted = shard.store_insert<kNotify>(op.hash, restored);
    if (inserted != FlatStore::InsertResult::Inserted) {
        kvobj_free(restored);
        if (inserted == FlatStore::InsertResult::MaxmemoryOom) reply_maxmemory_oom(op);
        else reply_err(op.sink(), "ERR keyspace insert failed");
        return;
    }
    shard.store().note_loaded_object(op.hash, restored);
    if constexpr (kNotify)
        notify_record(shard, op, NOTIFY_GENERIC, NotifyEventId::Restore, op.key());
    reply_ok(op.sink());
}

void cmd_dump_notify_body(Shard& shard, Op& op) { cmd_dump<true>(shard, op); }
void cmd_restore_notify_body(Shard& shard, Op& op) { cmd_restore<true>(shard, op); }

}  // namespace

void cmd_dump(Shard& shard, Op& op) { cmd_dump<false>(shard, op); }

void cmd_dump_notify(Shard& shard, Op& op) {
    notify_execute_handler(shard, op, cmd_dump_notify_body);
}

void cmd_restore(Shard& shard, Op& op) { cmd_restore<false>(shard, op); }

void cmd_restore_notify(Shard& shard, Op& op) {
    notify_execute_handler(shard, op, cmd_restore_notify_body);
}

}  // namespace tomo
