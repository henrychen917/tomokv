// serialize.cc -- Redis RDB value encoding for DUMP and RESTORE.
//
// This is deliberately a value codec, not a second persistence format.  DUMP reads an object only
// on its shard owner and converts the type lane's logical snapshot image to an RDB value. RESTORE
// performs the inverse conversion and lets the same type hook rebuild the current representation.
#include "serialize.h"

#include "command.h"
#include "notify.h"
#include "../core/shard.h"
#include "../exec/op.h"
#include "../net/resp.h"
#include "../snapshot/format.h"
#include "../store/kvobj.h"

#include <algorithm>
#include <cerrno>
#include <charconv>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <map>
#include <new>
#include <set>
#include <string>
#include <vector>

namespace tomo {
namespace {

// Redis 7.4 emits RDB version 12 at the end of a DUMP payload and accepts payload versions up to
// its own.  Version zero is accepted too; it is useful to preserve that verifier behavior rather
// than imposing a made-up lower bound.
constexpr uint16_t kRdbVersion = 12;
constexpr size_t kDumpTrailerBytes = 10;  // u16 version + u64 CRC64

enum : uint8_t {
    kRdbString = 0,
    kRdbList = 1,
    kRdbSet = 2,
    kRdbZset = 3,
    kRdbHash = 4,
    kRdbZset2 = 5,
    // Decode-only Redis encodings: RESTORE must accept real Redis DUMP payloads even though this
    // encoder deliberately emits only the plain collection forms above. Do not remove as unused.
    kRdbSetIntset = 11,
    kRdbStream = 15,
    kRdbHashListpack = 16,
    kRdbZsetListpack = 17,
    kRdbListQuicklist2 = 18,
    kRdbStream2 = 19,
    kRdbSetListpack = 20,
    kRdbStream3 = 21,
    // Redis 7.4 hash-field-expiry value types, established from live DUMP payloads. Metadata hashes
    // carry an expiry delta before each ordinary field/value pair; listpackex hashes carry
    // field/value/absolute-expiry triplets inside the listpack.
    kRdbHashMetadata = 24,
    kRdbHashListpackEx = 25,
};

enum : uint8_t {
    // Decode-only Redis string encodings used by RESTORE; the encoder need not produce them.
    kRdbEncInt8 = 0,
    kRdbEncInt16 = 1,
    kRdbEncInt32 = 2,
    kRdbEncLzf = 3,
};

class Reader {
public:
    Reader() = default;
    Reader(const uint8_t* data, size_t size) : cursor_(data), end_(data + size) {}
    explicit Reader(Slice value)
        : Reader(reinterpret_cast<const uint8_t*>(value.p), value.n) {}

    size_t remaining() const { return static_cast<size_t>(end_ - cursor_); }
    bool empty() const { return cursor_ == end_; }

    bool byte(uint8_t& out) {
        if (cursor_ == end_) return false;
        out = *cursor_++;
        return true;
    }

    bool bytes(size_t count, const uint8_t*& out) {
        if (count > remaining()) return false;
        out = cursor_;
        cursor_ += count;
        return true;
    }

    bool skip(size_t count) {
        const uint8_t* ignored = nullptr;
        return bytes(count, ignored);
    }

    bool le16(uint16_t& out) {
        const uint8_t* p = nullptr;
        if (!bytes(2, p)) return false;
        out = static_cast<uint16_t>(p[0]) | (static_cast<uint16_t>(p[1]) << 8);
        return true;
    }

    bool le32(uint32_t& out) {
        const uint8_t* p = nullptr;
        if (!bytes(4, p)) return false;
        out = snapshot_get_u32(p);
        return true;
    }

    bool le64(uint64_t& out) {
        const uint8_t* p = nullptr;
        if (!bytes(8, p)) return false;
        out = snapshot_get_u64(p);
        return true;
    }

    bool be32(uint32_t& out) {
        const uint8_t* p = nullptr;
        if (!bytes(4, p)) return false;
        out = (static_cast<uint32_t>(p[0]) << 24) |
              (static_cast<uint32_t>(p[1]) << 16) |
              (static_cast<uint32_t>(p[2]) << 8) | p[3];
        return true;
    }

    bool be64(uint64_t& out) {
        const uint8_t* p = nullptr;
        if (!bytes(8, p)) return false;
        out = 0;
        for (uint32_t i = 0; i < 8; i++) out = (out << 8) | p[i];
        return true;
    }

private:
    const uint8_t* cursor_ = nullptr;
    const uint8_t* end_ = nullptr;
};

void append_u32(std::vector<uint8_t>& out, uint32_t value) {
    const size_t at = out.size();
    out.resize(at + 4);
    snapshot_put_u32(out.data() + at, value);
}

void append_u64(std::vector<uint8_t>& out, uint64_t value) {
    const size_t at = out.size();
    out.resize(at + 8);
    snapshot_put_u64(out.data() + at, value);
}

bool append_bytes(std::vector<uint8_t>& out, const uint8_t* bytes, size_t length) {
    if (length == 0) return true;
    if (length > std::numeric_limits<size_t>::max() - out.size()) return false;
    out.insert(out.end(), bytes, bytes + length);
    return true;
}

void append_rdb_length(std::vector<uint8_t>& out, uint64_t length) {
    if (length < (1u << 6)) {
        out.push_back(static_cast<uint8_t>(length));
    } else if (length < (1u << 14)) {
        out.push_back(static_cast<uint8_t>(0x40 | (length >> 8)));
        out.push_back(static_cast<uint8_t>(length));
    } else if (length <= UINT32_MAX) {
        out.push_back(0x80);
        out.push_back(static_cast<uint8_t>(length >> 24));
        out.push_back(static_cast<uint8_t>(length >> 16));
        out.push_back(static_cast<uint8_t>(length >> 8));
        out.push_back(static_cast<uint8_t>(length));
    } else {
        out.push_back(0x81);
        for (int shift = 56; shift >= 0; shift -= 8)
            out.push_back(static_cast<uint8_t>(length >> shift));
    }
}

bool append_rdb_string(std::vector<uint8_t>& out, const uint8_t* bytes, size_t length) {
    append_rdb_length(out, length);
    return append_bytes(out, bytes, length);
}

bool append_rdb_string(std::vector<uint8_t>& out, Slice value) {
    return append_rdb_string(out, reinterpret_cast<const uint8_t*>(value.p), value.n);
}

bool read_rdb_length(Reader& reader, uint64_t& length, int& special) {
    uint8_t first = 0;
    if (!reader.byte(first)) return false;
    special = -1;
    switch (first >> 6) {
        case 0:
            length = first & 0x3f;
            return true;
        case 1: {
            uint8_t second = 0;
            if (!reader.byte(second)) return false;
            length = (static_cast<uint64_t>(first & 0x3f) << 8) | second;
            return true;
        }
        case 2: {
            if ((first & 0x3f) == 0) {
                uint32_t value = 0;
                if (!reader.be32(value)) return false;
                length = value;
                return true;
            }
            if ((first & 0x3f) == 1) return reader.be64(length);
            return false;
        }
        case 3:
            length = 0;
            special = first & 0x3f;
            return true;
    }
    return false;
}

bool read_plain_length(Reader& reader, uint64_t& length) {
    int special = -1;
    return read_rdb_length(reader, length, special) && special == -1;
}

// LZF is Marc Lehmann's public-domain format.  Redis stores the compressed and uncompressed
// lengths before this byte stream; literal runs and overlapping back-references are sufficient.
bool lzf_decompress(const uint8_t* input, size_t input_length,
                    uint8_t* output, size_t output_length) {
    const uint8_t* ip = input;
    const uint8_t* input_end = input + input_length;
    uint8_t* op = output;
    uint8_t* output_end = output + output_length;
    while (ip < input_end) {
        const uint32_t control = *ip++;
        if (control < 32) {
            const size_t length = control + 1;
            if (length > static_cast<size_t>(input_end - ip) ||
                length > static_cast<size_t>(output_end - op)) return false;
            std::memcpy(op, ip, length);
            ip += length;
            op += length;
            continue;
        }

        size_t length = control >> 5;
        size_t offset = (control & 0x1f) << 8;
        if (length == 7) {
            if (ip == input_end) return false;
            length += *ip++;
        }
        if (ip == input_end) return false;
        offset += *ip++;
        length += 2;
        if (offset + 1 > static_cast<size_t>(op - output) ||
            length > static_cast<size_t>(output_end - op)) return false;
        uint8_t* reference = op - offset - 1;
        while (length--) *op++ = *reference++;
    }
    return op == output_end;
}

void assign_integer(std::string& out, int64_t value) {
    char text[24];
    const auto converted = std::to_chars(text, text + sizeof(text), value);
    out.assign(text, converted.ptr);
}

bool read_rdb_string(Reader& reader, std::string& out) {
    uint64_t length = 0;
    int special = -1;
    if (!read_rdb_length(reader, length, special)) return false;
    if (special == -1) {
        if (length > reader.remaining() || length > UINT32_MAX) return false;
        const uint8_t* bytes = nullptr;
        if (!reader.bytes(static_cast<size_t>(length), bytes)) return false;
        out.assign(reinterpret_cast<const char*>(bytes), static_cast<size_t>(length));
        return true;
    }

    if (special == kRdbEncInt8) {
        uint8_t value = 0;
        if (!reader.byte(value)) return false;
        assign_integer(out, static_cast<int8_t>(value));
        return true;
    }
    if (special == kRdbEncInt16) {
        uint16_t bits = 0;
        if (!reader.le16(bits)) return false;
        assign_integer(out, static_cast<int16_t>(bits));
        return true;
    }
    if (special == kRdbEncInt32) {
        uint32_t bits = 0;
        if (!reader.le32(bits)) return false;
        assign_integer(out, static_cast<int32_t>(bits));
        return true;
    }
    if (special != kRdbEncLzf) return false;

    uint64_t compressed_length = 0, raw_length = 0;
    if (!read_plain_length(reader, compressed_length) ||
        !read_plain_length(reader, raw_length) ||
        compressed_length > reader.remaining() || raw_length > UINT32_MAX) return false;
    const uint8_t* compressed = nullptr;
    if (!reader.bytes(static_cast<size_t>(compressed_length), compressed)) return false;
    out.resize(static_cast<size_t>(raw_length));
    return lzf_decompress(compressed, static_cast<size_t>(compressed_length),
                          reinterpret_cast<uint8_t*>(out.data()), out.size());
}

constexpr uint64_t kCrc64Polynomial = 0x95ac9329ac4bc9b5ULL;

constexpr uint64_t crc64_table_entry(uint64_t value) {
    for (uint32_t bit = 0; bit < 8; bit++)
        value = (value >> 1) ^ ((value & 1) ? kCrc64Polynomial : 0);
    return value;
}

constexpr auto make_crc64_table() {
    struct Table { uint64_t values[256] = {}; } table;
    for (uint32_t i = 0; i < 256; i++) table.values[i] = crc64_table_entry(i);
    return table;
}

constexpr auto kCrc64Table = make_crc64_table();

uint64_t redis_crc64(const uint8_t* bytes, size_t length) {
    uint64_t crc = 0;
    for (size_t i = 0; i < length; i++)
        crc = kCrc64Table.values[(crc ^ bytes[i]) & 0xff] ^ (crc >> 8);
    return crc;
}

static_assert([] {
    constexpr char input[] = "123456789";
    uint64_t crc = 0;
    for (size_t i = 0; i + 1 < sizeof(input); i++)
        crc = kCrc64Table.values[(crc ^ static_cast<uint8_t>(input[i])) & 0xff] ^ (crc >> 8);
    return crc == 0xe9c6d914c4b8d9caULL;
}(), "Redis/Jones CRC64 test vector");

bool snapshot_image(const KvObj& object, std::vector<uint8_t>& payload, uint8_t& encoding) {
    const SnapshotTypeHooks& hooks = snapshot_type_hooks(static_cast<Type>(object.type));
    SnapshotSaveCursor cursor;
    if (!hooks.begin_save || !hooks.read_save ||
        hooks.begin_save(object, cursor, encoding) != SnapshotHookStatus::Ok ||
        cursor.total > UINT32_MAX) return false;
    payload.resize(static_cast<size_t>(cursor.total));
    while (cursor.offset < cursor.total) {
        size_t written = 0;
        const size_t remaining = static_cast<size_t>(cursor.total - cursor.offset);
        if (hooks.read_save(cursor, payload.data() + cursor.offset, remaining, written) !=
                SnapshotHookStatus::Ok || !written || written > remaining) return false;
    }
    return true;
}

bool native_string(Reader& native, Slice& value) {
    uint32_t length = 0;
    const uint8_t* bytes = nullptr;
    if (!native.le32(length) || !native.bytes(length, bytes)) return false;
    value = Slice(reinterpret_cast<const char*>(bytes), length);
    return true;
}

bool encode_stream(Reader& native, std::vector<uint8_t>& out);

bool encode_rdb_value(const KvObj& object, std::vector<uint8_t>& out) {
    const Type type = static_cast<Type>(object.type);

    std::vector<uint8_t> native_payload;
    uint8_t native_encoding = 0;
    if (!snapshot_image(object, native_payload, native_encoding)) return false;
    Reader native(native_payload.data(), native_payload.size());
    if (type == Type::Stream) return encode_stream(native, out);

    if (type == Type::String) {
        out.push_back(kRdbString);
        if (static_cast<Enc>(native_encoding) == Enc::Int) {
            uint64_t bits = 0;
            if (!native.le64(bits) || !native.empty()) return false;
            char text[24];
            const auto converted = std::to_chars(text, text + sizeof(text),
                                                 static_cast<int64_t>(bits));
            return append_rdb_string(out, reinterpret_cast<const uint8_t*>(text),
                                     static_cast<size_t>(converted.ptr - text));
        }
        if (static_cast<Enc>(native_encoding) != Enc::Raw &&
            static_cast<Enc>(native_encoding) != Enc::Extern) return false;
        return append_rdb_string(out, native_payload.data(), native_payload.size());
    }

    const uint64_t entries = CollectionRef(const_cast<KvObj*>(&object)).entries();

    if (type == Type::Hash && native_encoding == 1) {
        // Native hash encoding 1 appends one absolute i64 deadline (-1 for persistent) to every
        // field/value pair. Redis's metadata RDB type stores the minimum absolute deadline once and
        // a per-entry unsigned delta: zero means persistent, otherwise expire-minimum+1.
        Reader scan(native_payload.data(), native_payload.size());
        int64_t minimum = std::numeric_limits<int64_t>::max();
        for (uint64_t i = 0; i < entries; i++) {
            Slice field, value;
            uint64_t bits = 0;
            int64_t expire = -1;
            if (!native_string(scan, field) || !native_string(scan, value) || !scan.le64(bits))
                return false;
            std::memcpy(&expire, &bits, sizeof(expire));
            if (expire < -1) return false;
            if (expire >= 0) minimum = std::min(minimum, expire);
        }
        if (!scan.empty() || minimum == std::numeric_limits<int64_t>::max()) return false;

        out.push_back(kRdbHashMetadata);
        append_u64(out, static_cast<uint64_t>(minimum));
        append_rdb_length(out, entries);
        for (uint64_t i = 0; i < entries; i++) {
            Slice field, value;
            uint64_t bits = 0;
            int64_t expire = -1;
            if (!native_string(native, field) || !native_string(native, value) ||
                !native.le64(bits)) return false;
            std::memcpy(&expire, &bits, sizeof(expire));
            const uint64_t delta = expire < 0 ? 0
                : static_cast<uint64_t>(expire - minimum) + 1;
            append_rdb_length(out, delta);
            if (!append_rdb_string(out, field) || !append_rdb_string(out, value)) return false;
        }
        return native.empty();
    }
    if (type == Type::Hash && native_encoding != 0) return false;

    out.push_back(type == Type::List ? kRdbList :
                  type == Type::Hash ? kRdbHash :
                  type == Type::Set ? kRdbSet : kRdbZset2);
    append_rdb_length(out, entries);

    if (type == Type::List || type == Type::Set) {
        for (uint64_t i = 0; i < entries; i++) {
            Slice value;
            if (!native_string(native, value) || !append_rdb_string(out, value)) return false;
        }
        return native.empty();
    }
    if (type == Type::Hash) {
        for (uint64_t i = 0; i < entries; i++) {
            Slice field, value;
            if (!native_string(native, field) || !native_string(native, value) ||
                !append_rdb_string(out, field) || !append_rdb_string(out, value)) return false;
        }
        return native.empty();
    }
    if (type == Type::Zset) {
        for (uint64_t i = 0; i < entries; i++) {
            uint64_t score = 0;
            Slice member;
            if (!native.le64(score) || !native_string(native, member) ||
                !append_rdb_string(out, member)) return false;
            append_u64(out, score);
        }
        return native.empty();
    }
    return false;
}

size_t listpack_backlen_size(size_t encoded_length) {
    if (encoded_length <= 127) return 1;
    if (encoded_length <= 16383) return 2;
    if (encoded_length <= 2097151) return 3;
    if (encoded_length <= 268435455) return 4;
    return 5;
}

int64_t sign_extend_24(uint32_t value) {
    if (value & 0x800000) value |= 0xff000000;
    return static_cast<int32_t>(value);
}

bool decode_listpack(const std::string& blob, std::vector<std::string>& values) {
    if (blob.size() < 7 || static_cast<uint8_t>(blob.back()) != 0xff) return false;
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(blob.data());
    if (snapshot_get_u32(bytes) != blob.size()) return false;
    const uint16_t announced = static_cast<uint16_t>(bytes[4]) |
                               (static_cast<uint16_t>(bytes[5]) << 8);
    Reader reader(bytes + 6, blob.size() - 7);
    while (!reader.empty()) {
        const size_t before = reader.remaining();
        uint8_t first = 0;
        if (!reader.byte(first)) return false;
        std::string value;
        if ((first & 0x80) == 0) {
            assign_integer(value, first & 0x7f);
        } else if ((first & 0xc0) == 0x80) {
            const size_t length = first & 0x3f;
            const uint8_t* p = nullptr;
            if (!reader.bytes(length, p)) return false;
            value.assign(reinterpret_cast<const char*>(p), length);
        } else if ((first & 0xe0) == 0xc0) {
            uint8_t low = 0;
            if (!reader.byte(low)) return false;
            uint32_t bits = (static_cast<uint32_t>(first & 0x1f) << 8) | low;
            assign_integer(value, bits >= 4096 ? static_cast<int64_t>(bits) - 8192 : bits);
        } else if ((first & 0xf0) == 0xe0) {
            uint8_t low = 0;
            if (!reader.byte(low)) return false;
            const size_t length = (static_cast<size_t>(first & 0x0f) << 8) | low;
            const uint8_t* p = nullptr;
            if (!reader.bytes(length, p)) return false;
            value.assign(reinterpret_cast<const char*>(p), length);
        } else if (first == 0xf0) {
            uint32_t length = 0;
            const uint8_t* p = nullptr;
            if (!reader.le32(length) || !reader.bytes(length, p)) return false;
            value.assign(reinterpret_cast<const char*>(p), length);
        } else if (first == 0xf1) {
            uint16_t bits = 0;
            if (!reader.le16(bits)) return false;
            assign_integer(value, static_cast<int16_t>(bits));
        } else if (first == 0xf2) {
            const uint8_t* p = nullptr;
            if (!reader.bytes(3, p)) return false;
            assign_integer(value, sign_extend_24(static_cast<uint32_t>(p[0]) |
                                                 (static_cast<uint32_t>(p[1]) << 8) |
                                                 (static_cast<uint32_t>(p[2]) << 16)));
        } else if (first == 0xf3) {
            uint32_t bits = 0;
            if (!reader.le32(bits)) return false;
            assign_integer(value, static_cast<int32_t>(bits));
        } else if (first == 0xf4) {
            uint64_t bits = 0;
            if (!reader.le64(bits)) return false;
            assign_integer(value, static_cast<int64_t>(bits));
        } else {
            return false;
        }

        const size_t encoded_length = before - reader.remaining();
        const size_t backlen_bytes = listpack_backlen_size(encoded_length);
        for (size_t i = 0; i < backlen_bytes; i++) {
            uint8_t actual = 0;
            const uint32_t shift = static_cast<uint32_t>((backlen_bytes - i - 1) * 7);
            const uint8_t wanted = static_cast<uint8_t>(
                ((encoded_length >> shift) & 0x7f) | (i == 0 ? 0 : 0x80));
            if (!reader.byte(actual) || actual != wanted) return false;
        }
        values.push_back(std::move(value));
    }
    return announced == 0xffff || announced == values.size();
}

bool append_native_string(std::vector<uint8_t>& out, const std::string& value) {
    if (value.size() > UINT32_MAX) return false;
    append_u32(out, static_cast<uint32_t>(value.size()));
    return append_bytes(out, reinterpret_cast<const uint8_t*>(value.data()), value.size());
}

bool append_native_hash_entry(std::vector<uint8_t>& out, const std::string& field,
                              const std::string& value, int64_t expire_ms) {
    if (!append_native_string(out, field) || !append_native_string(out, value)) return false;
    append_u64(out, static_cast<uint64_t>(expire_ms));
    return true;
}

bool decode_hash_metadata(Reader& body, std::vector<uint8_t>& out) {
    uint64_t minimum = 0, count = 0;
    if (!body.le64(minimum) || minimum > static_cast<uint64_t>(INT64_MAX) ||
        !read_plain_length(body, count) || count == 0 || count > UINT32_MAX)
        return false;
    for (uint64_t i = 0; i < count; i++) {
        uint64_t delta = 0;
        std::string field, value;
        if (!read_plain_length(body, delta) || !read_rdb_string(body, field) ||
            !read_rdb_string(body, value)) return false;
        int64_t expire_ms = -1;
        if (delta != 0) {
            const uint64_t offset = delta - 1;
            if (offset > static_cast<uint64_t>(INT64_MAX) - minimum) return false;
            expire_ms = static_cast<int64_t>(minimum + offset);
        }
        if (!append_native_hash_entry(out, field, value, expire_ms)) return false;
    }
    return body.empty();
}

bool parse_decimal_u64(const std::string& input, uint64_t& value) {
    if (input.empty()) return false;
    const auto parsed = std::from_chars(input.data(), input.data() + input.size(), value);
    return parsed.ec == std::errc{} && parsed.ptr == input.data() + input.size();
}

// Redis stream listpacks use a big-endian master ID, signed integer deltas,
// and a trailing element count per entry. The native stream image retains the
// logical records and tombstones, not Redis's radix tree or listpack boundaries.
using DumpStreamId = std::pair<uint64_t, uint64_t>;

void append_stream_id(std::vector<uint8_t>& out, DumpStreamId id) {
    for (uint64_t part : {id.first, id.second})
        for (int shift = 56; shift >= 0; shift -= 8)
            out.push_back(static_cast<uint8_t>(part >> shift));
}

bool read_stream_id(Reader& in, DumpStreamId& id) {
    return in.be64(id.first) && in.be64(id.second);
}

void lp_backlen(std::vector<uint8_t>& out, size_t length) {
    const size_t bytes = listpack_backlen_size(length);
    for (size_t i = 0; i < bytes; ++i)
        out.push_back(static_cast<uint8_t>(((length >> ((bytes - i - 1) * 7)) & 127) |
                                          (i ? 128 : 0)));
}

void lp_integer(std::vector<uint8_t>& out, uint64_t bits) {
    if (bits < 128) { out.push_back(static_cast<uint8_t>(bits)); out.push_back(1); }
    else { out.push_back(0xf4); append_u64(out, bits); out.push_back(9); }
}

void lp_string(std::vector<uint8_t>& out, Slice value) {
    out.push_back(0xf0);
    append_u32(out, value.n);
    append_bytes(out, reinterpret_cast<const uint8_t*>(value.p), value.n);
    lp_backlen(out, size_t(value.n) + 5);
}

struct DumpPending {
    std::string consumer;
    uint64_t delivery = 0, count = 0;
    bool assigned = false;
};

bool encode_stream(Reader& native, std::vector<uint8_t>& out) {
    uint32_t version = 0, records = 0;
    uint64_t base_ms = 0, base_seq = 0, last_ms = 0, last_seq = 0;
    uint64_t deleted_ms = 0, deleted_seq = 0, added = 0;
    if (!native.le32(version) || version != 2 || !native.le64(base_ms) ||
        !native.le64(base_seq) || !native.le64(last_ms) || !native.le64(last_seq) ||
        !native.le64(deleted_ms) || !native.le64(deleted_seq) || !native.le64(added) ||
        !native.le32(records) || records > native.remaining() / 21) return false;
    out.push_back(kRdbStream3);
    append_rdb_length(out, records);
    uint64_t length = 0;
    DumpStreamId first{};
    for (uint32_t i = 0; i < records; ++i) {
        DumpStreamId id;
        uint8_t deleted = 0;
        uint32_t fields = 0;
        if (!native.le64(id.first) || !native.le64(id.second) || !native.byte(deleted) ||
            !native.le32(fields) || !fields || fields > native.remaining() / 8) return false;
        std::vector<Slice> names(fields), values(fields);
        for (uint32_t n = 0; n < fields; ++n)
            if (!native_string(native, names[n]) || !native_string(native, values[n])) return false;
        if (!deleted && length++ == 0) first = id;
        std::vector<uint8_t> lp(6, 0);
        lp_integer(lp, !deleted); lp_integer(lp, !!deleted); lp_integer(lp, fields);
        for (Slice name : names) lp_string(lp, name);
        lp_integer(lp, 0); // master terminator
        lp_integer(lp, 2 | !!deleted); // SAMEFIELDS, optional DELETED
        lp_integer(lp, 0); lp_integer(lp, 0);
        for (Slice value : values) lp_string(lp, value);
        lp_integer(lp, fields + uint64_t{3});
        lp.push_back(255);
        if (lp.size() > UINT32_MAX) return false;
        snapshot_put_u32(lp.data(), static_cast<uint32_t>(lp.size()));
        const uint64_t elements = 8 + uint64_t{2} * fields;
        const uint16_t count = static_cast<uint16_t>(std::min(elements, uint64_t{65535}));
        lp[4] = count; lp[5] = count >> 8;
        append_rdb_length(out, 16); append_stream_id(out, id);
        append_rdb_string(out, lp.data(), lp.size());
    }
    for (uint64_t value : {length, last_ms, last_seq, first.first, first.second,
                           deleted_ms, deleted_seq, added}) append_rdb_length(out, value);
    uint32_t groups = 0;
    if (!native.le32(groups) || groups > native.remaining() / 36) return false;
    append_rdb_length(out, groups);
    for (uint32_t g = 0; g < groups; ++g) {
        Slice name;
        uint64_t ms = 0, seq = 0, read = 0;
        uint32_t consumers = 0, pending_count = 0;
        if (!native_string(native, name) || !native.le64(ms) || !native.le64(seq) ||
            !native.le64(read) || !native.le32(consumers) ||
            consumers > native.remaining() / 20) return false;
        append_rdb_string(out, name);
        for (uint64_t value : {ms, seq, read}) append_rdb_length(out, value);
        struct Consumer { Slice name; uint64_t seen, active; std::vector<DumpStreamId> pel; };
        std::vector<Consumer> clients(consumers);
        std::map<std::string, size_t> by_name;
        for (size_t c = 0; c < clients.size(); ++c) {
            auto& client = clients[c];
            if (!native_string(native, client.name) || !native.le64(client.seen) ||
                !native.le64(client.active) ||
                !by_name.emplace(std::string(client.name.p, client.name.n), c).second) return false;
        }
        if (!native.le32(pending_count) || pending_count > native.remaining() / 36) return false;
        append_rdb_length(out, pending_count);
        for (uint32_t p = 0; p < pending_count; ++p) {
            DumpStreamId id;
            Slice consumer;
            uint64_t delivery = 0, deliveries = 0;
            if (!native.le64(id.first) || !native.le64(id.second) ||
                !native_string(native, consumer) || !native.le64(delivery) ||
                !native.le64(deliveries)) return false;
            const auto found = by_name.find(std::string(consumer.p, consumer.n));
            if (found == by_name.end()) return false;
            clients[found->second].pel.push_back(id);
            append_stream_id(out, id); append_u64(out, delivery); append_rdb_length(out, deliveries);
        }
        append_rdb_length(out, consumers);
        for (const auto& client : clients) {
            append_rdb_string(out, client.name);
            append_u64(out, client.seen); append_u64(out, client.active);
            append_rdb_length(out, client.pel.size());
            for (auto id : client.pel) append_stream_id(out, id);
        }
    }
    return native.empty();
}

bool lp_signed(const std::string& value, uint64_t& bits) {
    int64_t integer = 0;
    const auto parsed = std::from_chars(value.data(), value.data() + value.size(), integer);
    if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size()) return false;
    bits = static_cast<uint64_t>(integer);
    return true;
}

bool decode_stream(Reader& body, uint8_t type, std::vector<uint8_t>& out) {
    uint64_t nodes = 0, live = 0;
    uint32_t records = 0;
    DumpStreamId previous{}, first{}, base{}, last{}, deleted{};
    out.resize(64, 0);
    snapshot_put_u32(out.data(), 2);
    if (!read_plain_length(body, nodes) || nodes > body.remaining() / 2) return false;
    std::set<DumpStreamId> masters;
    for (uint64_t n = 0; n < nodes; ++n) {
        std::string key, blob;
        std::vector<std::string> elements;
        DumpStreamId master;
        if (!read_rdb_string(body, key) || key.size() != 16 ||
            !read_rdb_string(body, blob) || !decode_listpack(blob, elements)) return false;
        Reader id_reader(Slice(key.data(), key.size()));
        if (!read_stream_id(id_reader, master) || !masters.insert(master).second ||
            elements.size() < 4) return false;
        size_t at = 0;
        auto integer = [&](uint64_t& value) {
            return at < elements.size() && lp_signed(elements[at++], value);
        };
        uint64_t count = 0, tombstones = 0, master_fields = 0, zero = 0;
        if (!integer(count) || !integer(tombstones) || !integer(master_fields) ||
            master_fields > elements.size() - at) return false;
        const size_t names = at;
        at += master_fields;
        if (!integer(zero) || zero != 0 || count > elements.size() ||
            tombstones > elements.size() || count + tombstones == 0) return false;
        uint64_t observed = 0, removed = 0;
        while (at < elements.size()) {
            const size_t start = at;
            uint64_t flags = 0, ms = 0, seq = 0, fields = master_fields;
            if (!integer(flags) || flags > 3 || !integer(ms) || !integer(seq) ||
                (!(flags & 2) && !integer(fields)) || !fields || fields > UINT32_MAX ||
                fields > (elements.size() - at) / ((flags & 2) ? 1 : 2)) return false;
            // Redis deltas are signed bit patterns with unsigned modular addition;
            // a later millisecond may legitimately have a smaller sequence part.
            DumpStreamId id{master.first + ms, master.second + seq};
            if (id == DumpStreamId{} || (records && id <= previous) || records == UINT32_MAX)
                return false;
            if (!records) base = id;
            previous = id; ++records;
            const bool dead = flags & 1;
            if (dead) ++removed;
            else { if (!live) first = id; ++live; ++observed; }
            append_u64(out, id.first); append_u64(out, id.second);
            out.push_back(dead); append_u32(out, fields);
            for (uint64_t f = 0; f < fields; ++f) {
                const std::string& name = (flags & 2) ? elements[names + f] : elements[at++];
                if (!append_native_string(out, name) ||
                    !append_native_string(out, elements[at++])) return false;
            }
            const size_t expected = at - start;
            uint64_t back = 0;
            if (!integer(back) || back != expected) return false;
        }
        if (observed != count || removed != tombstones) return false;
    }
    uint64_t length = 0, added = 0;
    if (!read_plain_length(body, length) || !read_plain_length(body, last.first) ||
        !read_plain_length(body, last.second) || length != live) return false;
    added = length;
    if (type >= kRdbStream2) {
        DumpStreamId announced;
        if (!read_plain_length(body, announced.first) || !read_plain_length(body, announced.second) ||
            !read_plain_length(body, deleted.first) || !read_plain_length(body, deleted.second) ||
            !read_plain_length(body, added) || announced != first || added < length) return false;
    }
    if ((records && previous > last) || deleted > last) return false;
    const uint64_t metadata[] = {base.first, base.second, last.first, last.second,
                                  deleted.first, deleted.second, added};
    for (size_t i = 0; i < 7; ++i) snapshot_put_u64(out.data() + 4 + 8 * i, metadata[i]);
    snapshot_put_u32(out.data() + 60, records);
    uint64_t groups = 0;
    if (!read_plain_length(body, groups) || groups > UINT32_MAX || groups > body.remaining() / 5)
        return false;
    append_u32(out, groups);
    std::set<std::string> group_names;
    for (uint64_t g = 0; g < groups; ++g) {
        std::string name;
        DumpStreamId id;
        uint64_t read = UINT64_MAX, pending_count = 0, consumers = 0;
        if (!read_rdb_string(body, name) || !group_names.insert(name).second ||
            !read_plain_length(body, id.first) || !read_plain_length(body, id.second)) return false;
        if (type >= kRdbStream2) {
            if (!read_plain_length(body, read)) return false;
        } else {
            if (!added) read = 0;
            else if ((!length && id <= last) || id == last) read = added;
            else if (id <= first && id < last) read = added - length + (id == first);
        }
        if (!append_native_string(out, name)) return false;
        append_u64(out, id.first); append_u64(out, id.second); append_u64(out, read);
        if (!read_plain_length(body, pending_count) || pending_count > UINT32_MAX ||
            pending_count > body.remaining() / 25) return false;
        std::map<DumpStreamId, DumpPending> pel;
        for (uint64_t p = 0; p < pending_count; ++p) {
            DumpStreamId pid;
            DumpPending pending;
            if (!read_stream_id(body, pid) || !body.le64(pending.delivery) ||
                !read_plain_length(body, pending.count) || !pel.emplace(pid, pending).second)
                return false;
        }
        if (!read_plain_length(body, consumers) || consumers > UINT32_MAX ||
            consumers > body.remaining() / (type >= kRdbStream3 ? 18 : 10)) return false;
        append_u32(out, consumers);
        std::set<std::string> consumer_names;
        for (uint64_t c = 0; c < consumers; ++c) {
            uint64_t seen = 0, active = 0, pending = 0;
            if (!read_rdb_string(body, name) || !consumer_names.insert(name).second ||
                !body.le64(seen)) return false;
            active = seen;
            if (type >= kRdbStream3 && !body.le64(active)) return false;
            if (!read_plain_length(body, pending) || pending > body.remaining() / 16 ||
                !append_native_string(out, name)) return false;
            append_u64(out, seen); append_u64(out, active);
            for (uint64_t p = 0; p < pending; ++p) {
                DumpStreamId pid;
                if (!read_stream_id(body, pid)) return false;
                auto entry = pel.find(pid);
                if (entry == pel.end() || entry->second.assigned) return false;
                entry->second.consumer = name;
                entry->second.assigned = true;
            }
        }
        append_u32(out, pending_count);
        for (const auto& [pid, pending] : pel) {
            if (!pending.assigned) return false;
            append_u64(out, pid.first); append_u64(out, pid.second);
            if (!append_native_string(out, pending.consumer)) return false;
            append_u64(out, pending.delivery); append_u64(out, pending.count);
        }
    }
    return body.empty() && out.size() <= UINT32_MAX;
}

bool decode_hash_listpack_ex(Reader& body, std::vector<uint8_t>& out) {
    uint64_t minimum = 0;
    std::string blob;
    std::vector<std::string> values;
    if (!body.le64(minimum) || minimum > static_cast<uint64_t>(INT64_MAX) ||
        !read_rdb_string(body, blob) || !body.empty() || !decode_listpack(blob, values) ||
        values.empty() || values.size() % 3 != 0)
        return false;
    uint64_t observed_minimum = UINT64_MAX;
    for (size_t i = 0; i < values.size(); i += 3) {
        uint64_t encoded_expire = 0;
        if (!parse_decimal_u64(values[i + 2], encoded_expire) ||
            encoded_expire > static_cast<uint64_t>(INT64_MAX)) return false;
        const int64_t expire_ms = encoded_expire == 0 ? -1
                                                       : static_cast<int64_t>(encoded_expire);
        if (encoded_expire != 0) observed_minimum = std::min(observed_minimum, encoded_expire);
        if (!append_native_hash_entry(out, values[i], values[i + 1], expire_ms)) return false;
    }
    // The prefix is the expiry index's minimum. Requiring an exact match rejects a payload whose
    // attention metadata could disagree with its field triplets.
    return observed_minimum != UINT64_MAX && observed_minimum == minimum;
}

bool parse_score(const std::string& input, double& score) {
    if (input.empty() || std::isspace(static_cast<unsigned char>(input[0]))) return false;
    errno = 0;
    char* end = nullptr;
    score = std::strtod(input.c_str(), &end);
    // ERANGE also describes a valid subnormal (for example 5e-324), which Redis can emit in a
    // zset listpack. The serialized spelling came from a stored double; only syntax and NaN are
    // invalid here.
    return end == input.data() + input.size() && !std::isnan(score);
}

bool append_native_zset(std::vector<uint8_t>& out, const std::string& member, double score) {
    if (member.size() > UINT32_MAX || std::isnan(score)) return false;
    uint64_t bits = 0;
    std::memcpy(&bits, &score, sizeof(bits));
    append_u64(out, bits);
    return append_native_string(out, member);
}

struct DecodedValue {
    Type type = Type::String;
    uint8_t encoding = 0;
    std::vector<uint8_t> payload;
};

bool decode_plain_sequence(Reader& body, Type type, uint64_t count,
                           std::vector<uint8_t>& out) {
    if (type == Type::Hash && count > UINT64_MAX / 2) return false;
    const uint64_t strings = type == Type::Hash ? count * 2 : count;
    if (strings > body.remaining()) return false;
    for (uint64_t i = 0; i < strings; i++) {
        std::string value;
        if (!read_rdb_string(body, value) || !append_native_string(out, value)) return false;
    }
    return body.empty();
}

bool decode_binary_zset(Reader& body, uint64_t count, std::vector<uint8_t>& out) {
    if (count > body.remaining() / 9) return false;
    for (uint64_t i = 0; i < count; i++) {
        std::string member;
        uint64_t bits = 0;
        double score = 0;
        if (!read_rdb_string(body, member) || !body.le64(bits)) return false;
        std::memcpy(&score, &bits, sizeof(score));
        if (!append_native_zset(out, member, score)) return false;
    }
    return body.empty();
}

bool read_legacy_double(Reader& body, double& value) {
    uint8_t length = 0;
    if (!body.byte(length)) return false;
    if (length == 253) return false;  // NaN is never a legal sorted-set score.
    if (length == 254) { value = std::numeric_limits<double>::infinity(); return true; }
    if (length == 255) { value = -std::numeric_limits<double>::infinity(); return true; }
    const uint8_t* bytes = nullptr;
    if (!body.bytes(length, bytes)) return false;
    std::string text(reinterpret_cast<const char*>(bytes), length);
    return parse_score(text, value);
}

bool decode_legacy_zset(Reader& body, uint64_t count, std::vector<uint8_t>& out) {
    if (count > body.remaining() / 2) return false;
    for (uint64_t i = 0; i < count; i++) {
        std::string member;
        double score = 0;
        if (!read_rdb_string(body, member) || !read_legacy_double(body, score) ||
            !append_native_zset(out, member, score)) return false;
    }
    return body.empty();
}

bool decode_intset(Reader& body, std::vector<uint8_t>& out) {
    std::string blob;
    if (!read_rdb_string(body, blob) || !body.empty() || blob.size() < 8) return false;
    Reader packed(reinterpret_cast<const uint8_t*>(blob.data()), blob.size());
    uint32_t width = 0, count = 0;
    if (!packed.le32(width) || !packed.le32(count) ||
        (width != 2 && width != 4 && width != 8) ||
        count > packed.remaining() / width || packed.remaining() != uint64_t(count) * width)
        return false;
    for (uint32_t i = 0; i < count; i++) {
        int64_t integer = 0;
        if (width == 2) {
            uint16_t bits = 0;
            if (!packed.le16(bits)) return false;
            integer = static_cast<int16_t>(bits);
        } else if (width == 4) {
            uint32_t bits = 0;
            if (!packed.le32(bits)) return false;
            integer = static_cast<int32_t>(bits);
        } else {
            uint64_t bits = 0;
            if (!packed.le64(bits)) return false;
            integer = static_cast<int64_t>(bits);
        }
        std::string member;
        assign_integer(member, integer);
        if (!append_native_string(out, member)) return false;
    }
    return count != 0 && packed.empty();
}

bool decode_listpack_value(Reader& body, Type type, std::vector<uint8_t>& out) {
    std::string blob;
    std::vector<std::string> values;
    if (!read_rdb_string(body, blob) || !body.empty() || !decode_listpack(blob, values) ||
        values.empty()) return false;
    if (type == Type::Hash && (values.size() & 1)) return false;
    if (type == Type::Zset) {
        if (values.size() & 1) return false;
        for (size_t i = 0; i < values.size(); i += 2) {
            double score = 0;
            if (!parse_score(values[i + 1], score) ||
                !append_native_zset(out, values[i], score)) return false;
        }
        return true;
    }
    for (const std::string& value : values)
        if (!append_native_string(out, value)) return false;
    return true;
}

bool decode_quicklist2(Reader& body, std::vector<uint8_t>& out) {
    uint64_t nodes = 0;
    if (!read_plain_length(body, nodes) || nodes == 0 || nodes > body.remaining() / 2) return false;
    uint64_t elements = 0;
    for (uint64_t i = 0; i < nodes; i++) {
        uint64_t container = 0;
        std::string blob;
        if (!read_plain_length(body, container) || !read_rdb_string(body, blob)) return false;
        if (container == 1) {
            if (!append_native_string(out, blob)) return false;
            elements++;
        } else if (container == 2) {
            std::vector<std::string> values;
            if (!decode_listpack(blob, values) || values.empty()) return false;
            for (const std::string& value : values)
                if (!append_native_string(out, value)) return false;
            elements += values.size();
        } else {
            return false;
        }
        if (elements > UINT32_MAX) return false;
    }
    return elements != 0 && body.empty();
}

bool decode_rdb_value(Slice encoded, DecodedValue& decoded) {
    Reader body(encoded);
    uint8_t rdb_type = 0;
    if (!body.byte(rdb_type)) return false;
    if (rdb_type == kRdbStream || rdb_type == kRdbStream2 || rdb_type == kRdbStream3) {
        decoded.type = Type::Stream;
        decoded.encoding = 2;
        return decode_stream(body, rdb_type, decoded.payload);
    }
    if (rdb_type == kRdbString) {
        std::string value;
        if (!read_rdb_string(body, value) || !body.empty()) return false;
        decoded.type = Type::String;
        decoded.encoding = static_cast<uint8_t>(Enc::Raw);
        decoded.payload.assign(value.begin(), value.end());
        return true;
    }
    if (rdb_type == kRdbHashMetadata) {
        decoded.type = Type::Hash;
        decoded.encoding = 1;
        return decode_hash_metadata(body, decoded.payload);
    }
    if (rdb_type == kRdbHashListpackEx) {
        decoded.type = Type::Hash;
        decoded.encoding = 1;
        return decode_hash_listpack_ex(body, decoded.payload);
    }

    uint64_t count = 0;
    switch (rdb_type) {
        case kRdbList:
        case kRdbSet:
        case kRdbHash:
        case kRdbZset:
        case kRdbZset2:
            if (!read_plain_length(body, count) || count == 0 || count > UINT32_MAX) return false;
            break;
        default:
            break;
    }

    decoded.encoding = 0;
    if (rdb_type == kRdbList) {
        decoded.type = Type::List;
        return decode_plain_sequence(body, decoded.type, count, decoded.payload);
    }
    if (rdb_type == kRdbSet) {
        decoded.type = Type::Set;
        return decode_plain_sequence(body, decoded.type, count, decoded.payload);
    }
    if (rdb_type == kRdbHash) {
        decoded.type = Type::Hash;
        return decode_plain_sequence(body, decoded.type, count, decoded.payload);
    }
    if (rdb_type == kRdbZset2) {
        decoded.type = Type::Zset;
        return decode_binary_zset(body, count, decoded.payload);
    }
    if (rdb_type == kRdbZset) {
        decoded.type = Type::Zset;
        return decode_legacy_zset(body, count, decoded.payload);
    }
    if (rdb_type == kRdbSetIntset) {
        decoded.type = Type::Set;
        return decode_intset(body, decoded.payload);
    }
    if (rdb_type == kRdbHashListpack) {
        decoded.type = Type::Hash;
        return decode_listpack_value(body, decoded.type, decoded.payload);
    }
    if (rdb_type == kRdbZsetListpack) {
        decoded.type = Type::Zset;
        return decode_listpack_value(body, decoded.type, decoded.payload);
    }
    if (rdb_type == kRdbSetListpack) {
        decoded.type = Type::Set;
        return decode_listpack_value(body, decoded.type, decoded.payload);
    }
    if (rdb_type == kRdbListQuicklist2) {
        decoded.type = Type::List;
        return decode_quicklist2(body, decoded.payload);
    }
    return false;
}

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
    output = negative ? (value == uint64_t{INT64_MAX} + 1
                           ? INT64_MIN : -static_cast<int64_t>(value))
                      : static_cast<int64_t>(value);
    return true;
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
        } else if (op.arg(index).eq_icase("idletime") && index + 1 < op.argc() && !freq_seen) {
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
        } else if (op.arg(index).eq_icase("freq") && index + 1 < op.argc() && !idletime_seen) {
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

void reply_dump_payload_error(Op& op) {
    reply_err(op.sink(), "ERR DUMP payload version or checksum are wrong");
}

bool verify_dump_payload(Op& op, Slice envelope, Slice& encoded) {
    if (envelope.n < kDumpTrailerBytes) {
        reply_dump_payload_error(op);
        return false;
    }
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(envelope.p);
    const size_t version_at = envelope.n - kDumpTrailerBytes;
    const uint16_t version = static_cast<uint16_t>(bytes[version_at]) |
                             (static_cast<uint16_t>(bytes[version_at + 1]) << 8);
    const uint64_t expected = snapshot_get_u64(bytes + envelope.n - 8);
    if (version > kRdbVersion || expected != redis_crc64(bytes, envelope.n - 8)) {
        reply_dump_payload_error(op);
        return false;
    }
    encoded = Slice(envelope.p, static_cast<uint32_t>(version_at));
    return true;
}

template <bool kNotify>
void cmd_dump_impl(Shard& shard, Op& op) {
    KvObj* object = shard.store_find_read<kNotify>(op.hash, op.key());
    // Protocol-selected null: reply_nil is the RESP2-only spelling and left DUMP answering "$-1"
    // on a RESP3 connection where every other miss answers "_".
    if (!object) { reply_null(op.sink(), op.resp3()); return; }
    try {
        std::vector<uint8_t> payload;
        if (!encode_rdb_value(*object, payload) ||
            payload.size() > UINT32_MAX - kDumpTrailerBytes) {
            reply_err(op.sink(), "ERR object could not be serialized");
            return;
        }
        payload.push_back(static_cast<uint8_t>(kRdbVersion));
        payload.push_back(static_cast<uint8_t>(kRdbVersion >> 8));
        append_u64(payload, redis_crc64(payload.data(), payload.size()));
        reply_bulk(op.sink(), Slice(reinterpret_cast<const char*>(payload.data()),
                                    static_cast<uint32_t>(payload.size())));
    } catch (const std::bad_alloc&) {
        reply_err(op.sink(), "ERR out of memory");
    }
}

template <bool kNotify>
void cmd_restore_impl(Shard& shard, Op& op) {
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

    Slice encoded;
    if (!verify_dump_payload(op, op.arg(3), encoded)) return;

    int64_t expire_at_ms = -1;
    if (ttl != 0) {
        if (options.absttl) {
            expire_at_ms = ttl;
        } else {
            const uint64_t wrapped = static_cast<uint64_t>(ttl) +
                                     static_cast<uint64_t>(shard.now_ms());
            std::memcpy(&expire_at_ms, &wrapped, sizeof(expire_at_ms));
        }
    }

    try {
        DecodedValue decoded;
        if (!decode_rdb_value(encoded, decoded)) {
            reply_err(op.sink(), "ERR Bad data format");
            return;
        }
        KvObj* restored = nullptr;
        const SnapshotTypeHooks& hooks = snapshot_type_hooks(decoded.type);
        const Slice native(reinterpret_cast<const char*>(decoded.payload.data()),
                           static_cast<uint32_t>(decoded.payload.size()));
        const SnapshotHookStatus loaded = hooks.load
            ? hooks.load(op.key(), decoded.encoding, expire_at_ms, native,
                         shard.type_limits(), restored)
            : SnapshotHookStatus::Corrupt;
        if (loaded != SnapshotHookStatus::Ok || !restored) {
            if (restored) kvobj_free(restored);
            if (loaded == SnapshotHookStatus::Oom)
                reply_err(op.sink(), "ERR out of memory");
            else
                reply_err(op.sink(), "ERR Bad data format");
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
    } catch (const std::bad_alloc&) {
        reply_err(op.sink(), "ERR out of memory");
    }
}

void cmd_dump_notify_body(Shard& shard, Op& op) { cmd_dump_impl<true>(shard, op); }
void cmd_restore_notify_body(Shard& shard, Op& op) { cmd_restore_impl<true>(shard, op); }

}  // namespace

bool encode_function_records(const std::vector<std::string>& sources, std::vector<uint8_t>& out) {
    out.clear();
    for (const auto& code : sources) {
        out.push_back(245); // RDB_OPCODE_FUNCTION2, Redis 7.4
        if (!append_rdb_string(out, reinterpret_cast<const uint8_t*>(code.data()), code.size()))
            return false;
    }
    return out.size() <= UINT32_MAX;
}

bool decode_function_records(Slice payload, std::vector<std::string>& sources) {
    Reader in(payload);
    while (!in.empty()) {
        uint8_t opcode = 0;
        std::string code;
        if (!in.byte(opcode) || opcode != 245 || !read_rdb_string(in, code)) return false;
        sources.push_back(std::move(code));
    }
    return true;
}

void cmd_dump(Shard& shard, Op& op) { cmd_dump_impl<false>(shard, op); }

void cmd_dump_notify(Shard& shard, Op& op) {
    notify_execute_handler(shard, op, cmd_dump_notify_body);
}

void cmd_restore(Shard& shard, Op& op) { cmd_restore_impl<false>(shard, op); }

void cmd_restore_notify(Shard& shard, Op& op) {
    notify_execute_handler(shard, op, cmd_restore_notify_body);
}

}  // namespace tomo
