// cmdmeta.cc -- cold command/subcommand metadata and COMMAND key-intent extraction.
#include "cmdmeta.h"

#include "acl_categories_generated.h"
#include "command.h"
#include "../exec/op.h"
#include "../net/resp.h"

#include <algorithm>
#include <cstring>
#include <limits>
#include <new>
#include <string>
#include <vector>

namespace tomo {

namespace {

enum class BeginType : uint8_t { Index, Keyword, Unknown };
enum class FindType : uint8_t { Range, Keynum, Unknown };

struct GeneratedKeySpec {
    const char* notes;
    uint16_t flags;
    BeginType begin_type;
    int16_t begin_index;
    const char* keyword;
    int16_t startfrom;
    FindType find_type;
    int16_t lastkey;
    int16_t keystep;
    int16_t limit;
    int16_t keynumidx;
    int16_t firstkey;
};

}  // namespace

struct CommandMetadata {
    const char* name;
    int16_t arity;
    uint64_t flags;
    int16_t first_key;
    int16_t last_key;
    int16_t key_step;
    uint64_t categories;
    uint16_t tips_offset;
    uint8_t tip_count;
    uint16_t key_specs_offset;
    uint8_t key_spec_count;
};

namespace {

#include "cmdmeta_generated.inc"

std::vector<const CommandMetadata*> g_metadata_by_id;

bool ascii_equal_icase(Slice value, const char* literal) {
    const size_t length = std::strlen(literal);
    if (value.n != length) return false;
    for (size_t index = 0; index < length; index++) {
        unsigned char left = static_cast<unsigned char>(value.p[index]);
        unsigned char right = static_cast<unsigned char>(literal[index]);
        if (left >= 'A' && left <= 'Z') left = static_cast<unsigned char>(left + ('a' - 'A'));
        if (right >= 'A' && right <= 'Z') right = static_cast<unsigned char>(right + ('a' - 'A'));
        if (left != right) return false;
    }
    return true;
}

bool ascii_equal_icase(Slice left, Slice right) {
    if (left.n != right.n) return false;
    for (uint32_t index = 0; index < left.n; index++) {
        unsigned char a = static_cast<unsigned char>(left.p[index]);
        unsigned char b = static_cast<unsigned char>(right.p[index]);
        if (a >= 'A' && a <= 'Z') a = static_cast<unsigned char>(a + ('a' - 'A'));
        if (b >= 'A' && b <= 'Z') b = static_cast<unsigned char>(b + ('a' - 'A'));
        if (a != b) return false;
    }
    return true;
}

uint16_t key_flag(const char* name) {
    for (uint32_t index = 0; index < sizeof(kGeneratedKeyFlagNames) /
                                      sizeof(kGeneratedKeyFlagNames[0]); index++)
        if (!std::strcmp(kGeneratedKeyFlagNames[index], name))
            return static_cast<uint16_t>(uint16_t{1} << index);
    return 0;
}

bool parse_nonnegative(Slice value, uint64_t& out, bool& canonical) {
    if (!value.n) return false;
    uint32_t start = 0;
    if (value.p[0] == '+') start = 1;
    if (start == value.n) return false;
    canonical = start == 0 && (value.n == 1 || value.p[0] != '0');
    uint64_t parsed = 0;
    for (uint32_t index = start; index < value.n; index++) {
        const char byte = value.p[index];
        if (byte < '0' || byte > '9') return false;
        const uint64_t digit = static_cast<uint64_t>(byte - '0');
        if (parsed > (std::numeric_limits<uint64_t>::max() - digit) / 10) return false;
        parsed = parsed * 10 + digit;
    }
    out = parsed;
    return true;
}

bool metadata_has_prefix(const CommandMetadata& candidate, const CommandMetadata& parent) {
    const size_t parent_length = std::strlen(parent.name);
    return !std::strncmp(candidate.name, parent.name, parent_length) &&
           candidate.name[parent_length] == '|';
}

void reply_string_set(Op::Sink& sink, uint64_t mask, const char* const* names,
                      uint32_t count, bool resp3) {
    reply_set_header(sink, static_cast<uint64_t>(__builtin_popcountll(mask)), resp3);
    for (uint32_t index = 0; index < count; index++) {
        if (!(mask & (uint64_t{1} << index))) continue;
        reply_simple(sink, names[index]);
    }
}

void reply_key_spec(Op::Sink& sink, const GeneratedKeySpec& spec, bool resp3) {
    reply_map_header(sink, spec.notes ? 4 : 3, resp3);
    if (spec.notes) {
        reply_bulk(sink, Slice("notes", 5));
        reply_bulk(sink, Slice(spec.notes, std::strlen(spec.notes)));
    }
    reply_bulk(sink, Slice("flags", 5));
    reply_string_set(sink, spec.flags, kGeneratedKeyFlagNames,
                     sizeof(kGeneratedKeyFlagNames) / sizeof(kGeneratedKeyFlagNames[0]), resp3);

    reply_bulk(sink, Slice("begin_search", 12));
    reply_map_header(sink, 2, resp3);
    reply_bulk(sink, Slice("type", 4));
    const char* begin_type = spec.begin_type == BeginType::Index ? "index" :
                             spec.begin_type == BeginType::Keyword ? "keyword" : "unknown";
    reply_bulk(sink, Slice(begin_type, std::strlen(begin_type)));
    reply_bulk(sink, Slice("spec", 4));
    if (spec.begin_type == BeginType::Index) {
        reply_map_header(sink, 1, resp3);
        reply_bulk(sink, Slice("index", 5)); reply_int(sink, spec.begin_index);
    } else if (spec.begin_type == BeginType::Keyword) {
        reply_map_header(sink, 2, resp3);
        reply_bulk(sink, Slice("keyword", 7));
        reply_bulk(sink, Slice(spec.keyword, std::strlen(spec.keyword)));
        reply_bulk(sink, Slice("startfrom", 9)); reply_int(sink, spec.startfrom);
    } else {
        reply_map_header(sink, 0, resp3);
    }

    reply_bulk(sink, Slice("find_keys", 9));
    reply_map_header(sink, 2, resp3);
    reply_bulk(sink, Slice("type", 4));
    const char* find_type = spec.find_type == FindType::Range ? "range" :
                            spec.find_type == FindType::Keynum ? "keynum" : "unknown";
    reply_bulk(sink, Slice(find_type, std::strlen(find_type)));
    reply_bulk(sink, Slice("spec", 4));
    if (spec.find_type == FindType::Range) {
        reply_map_header(sink, 3, resp3);
        reply_bulk(sink, Slice("lastkey", 7)); reply_int(sink, spec.lastkey);
        reply_bulk(sink, Slice("keystep", 7)); reply_int(sink, spec.keystep);
        reply_bulk(sink, Slice("limit", 5)); reply_int(sink, spec.limit);
    } else if (spec.find_type == FindType::Keynum) {
        reply_map_header(sink, 3, resp3);
        reply_bulk(sink, Slice("keynumidx", 9)); reply_int(sink, spec.keynumidx);
        reply_bulk(sink, Slice("firstkey", 8)); reply_int(sink, spec.firstkey);
        reply_bulk(sink, Slice("keystep", 7)); reply_int(sink, spec.keystep);
    } else {
        reply_map_header(sink, 0, resp3);
    }
}

uint32_t child_count(const CommandMetadata& parent) {
    uint32_t count = 0;
    for (const CommandMetadata& metadata : kGeneratedMetadata)
        if (metadata_has_prefix(metadata, parent)) count++;
    return count;
}

void reply_info_row(Op& op, const CommandMetadata& metadata) {
    auto sink = op.sink();
    reply_array_header(sink, 10);
    reply_bulk(sink, Slice(metadata.name, std::strlen(metadata.name)));
    reply_int(sink, metadata.arity);
    reply_string_set(sink, metadata.flags, kGeneratedCommandFlagNames,
                     sizeof(kGeneratedCommandFlagNames) /
                         sizeof(kGeneratedCommandFlagNames[0]), op.resp3());
    reply_int(sink, metadata.first_key);
    reply_int(sink, metadata.last_key);
    reply_int(sink, metadata.key_step);

    reply_set_header(sink, static_cast<uint64_t>(__builtin_popcountll(metadata.categories)),
                     op.resp3());
    for (uint32_t index = 0; index < kAclCategoryCount; index++) {
        if (!(metadata.categories & (uint64_t{1} << index))) continue;
        std::string name = "@";
        name += kAclCategories[index].name;
        reply_simple(sink, name.c_str());
    }

    reply_set_header(sink, metadata.tip_count, op.resp3());
    for (uint32_t index = 0; index < metadata.tip_count; index++) {
        const char* tip = kGeneratedTipRefs[metadata.tips_offset + index];
        reply_bulk(sink, Slice(tip, std::strlen(tip)));
    }

    reply_set_header(sink, metadata.key_spec_count, op.resp3());
    for (uint32_t index = 0; index < metadata.key_spec_count; index++) {
        const uint8_t spec = kGeneratedKeySpecRefs[metadata.key_specs_offset + index];
        reply_key_spec(sink, kGeneratedKeySpecs[spec], op.resp3());
    }

    const uint32_t children = child_count(metadata);
    if (children) {
        // Redis keeps populated subcommands as an array even in RESP3. Empty collections use the
        // protocol-native empty set, like the other metadata-set fields.
        reply_array_header(sink, children);
        for (const CommandMetadata& child : kGeneratedMetadata)
            if (metadata_has_prefix(child, metadata)) reply_info_row(op, child);
    } else {
        reply_set_header(sink, 0, op.resp3());
    }
}

}  // namespace

bool command_metadata_init(const CommandSpec* specs, size_t count) {
    try {
        g_metadata_by_id.assign(count, nullptr);
    } catch (const std::bad_alloc&) {
        return false;
    }
    for (size_t index = 0; index < count; index++) {
        const CommandMetadata* metadata = command_metadata_lookup(
            Slice(specs[index].name, static_cast<uint32_t>(std::strlen(specs[index].name))));
        if (!metadata || command_metadata_is_subcommand(*metadata)) return false;
        g_metadata_by_id[specs[index].id] = metadata;
    }
    return true;
}

const CommandMetadata* command_metadata_for(const CommandSpec& spec) {
    return spec.id < g_metadata_by_id.size() ? g_metadata_by_id[spec.id] : nullptr;
}

const CommandMetadata* command_metadata_lookup(Slice name) {
    for (const CommandMetadata& metadata : kGeneratedMetadata)
        if (ascii_equal_icase(name, metadata.name)) return &metadata;
    return nullptr;
}

const CommandMetadata* command_metadata_resolve(Op& op, uint32_t command_argument) {
    if (command_argument >= op.argc()) return nullptr;
    const CommandMetadata* parent = command_metadata_lookup(op.arg(command_argument));
    if (command_argument + 1 < op.argc()) {
        std::string qualified(op.arg(command_argument).p, op.arg(command_argument).n);
        qualified.push_back('|');
        qualified.append(op.arg(command_argument + 1).p, op.arg(command_argument + 1).n);
        if (const CommandMetadata* subcommand = command_metadata_lookup(
                Slice(qualified.data(), static_cast<uint32_t>(qualified.size()))))
            return subcommand;
        // A known container with an unrecognised first argument is not the broad parent for key
        // extraction. Redis reports Invalid command specified for that full command.
        if (parent && child_count(*parent)) return nullptr;
    }
    return parent;
}

uint32_t command_metadata_size() {
    return sizeof(kGeneratedMetadata) / sizeof(kGeneratedMetadata[0]);
}

const CommandMetadata* command_metadata_at(uint32_t index) {
    return index < command_metadata_size() ? &kGeneratedMetadata[index] : nullptr;
}

Slice command_metadata_name(const CommandMetadata& metadata) {
    return Slice(metadata.name, static_cast<uint32_t>(std::strlen(metadata.name)));
}

int16_t command_metadata_arity(const CommandMetadata& metadata) { return metadata.arity; }
uint64_t command_metadata_categories(const CommandMetadata& metadata) {
    return metadata.categories;
}
bool command_metadata_is_subcommand(const CommandMetadata& metadata) {
    return std::strchr(metadata.name, '|') != nullptr;
}
bool command_metadata_arity_ok(const CommandMetadata& metadata, uint32_t argc) {
    return metadata.arity > 0 ? argc == static_cast<uint32_t>(metadata.arity)
                              : argc >= static_cast<uint32_t>(-metadata.arity);
}

void command_metadata_reply_info(Op& op, const CommandMetadata* metadata) {
    auto sink = op.sink();
    if (!metadata) { reply_null(sink, op.resp3()); return; }
    reply_info_row(op, *metadata);
}

CommandMetadataKeysResult command_metadata_collect_keys(
    Op& op, uint32_t command_argument, const CommandMetadata& metadata,
    std::vector<CommandKeyMetadata>& keys) {
    const Slice name = command_metadata_name(metadata);
    const uint32_t command_argc = op.argc() - command_argument;
    const uint16_t ro_access = key_flag("RO") | key_flag("access");
    const uint16_t ow_update = key_flag("OW") | key_flag("update");

    // SORT's BY/GET and STORE key names are described as unknown searches in Redis metadata.
    // Its concrete COMMAND GETKEYS* extraction is nonetheless deterministic from this argv.
    if (ascii_equal_icase(name, "sort") || ascii_equal_icase(name, "sort_ro")) {
        if (command_argc < 2) return CommandMetadataKeysResult::InvalidArguments;
        keys.push_back({command_argument + 1, ro_access});
        if (ascii_equal_icase(name, "sort")) {
            uint32_t destination = 0;
            for (uint32_t index = command_argument + 2; index + 1 < op.argc(); index++) {
                if (ascii_equal_icase(op.arg(index), Slice("STORE", 5)))
                    destination = index + 1;
            }
            if (destination) keys.push_back({destination, ow_update});
        }
        return CommandMetadataKeysResult::Success;
    }

    if (!metadata.key_spec_count) return CommandMetadataKeysResult::NoKeyArguments;
    bool usable_spec = false;
    for (uint32_t ref = 0; ref < metadata.key_spec_count; ref++) {
        const GeneratedKeySpec& spec =
            kGeneratedKeySpecs[kGeneratedKeySpecRefs[metadata.key_specs_offset + ref]];
        if (spec.flags & key_flag("not_key")) continue;
        usable_spec = true;

        uint16_t flags = spec.flags & ~key_flag("variable_flags");
        if (spec.flags & key_flag("variable_flags")) {
            if (ascii_equal_icase(name, "set")) {
                bool get = false;
                for (uint32_t index = command_argument + 3; index < op.argc(); index++)
                    get = get || ascii_equal_icase(op.arg(index), Slice("GET", 3));
                flags = get ? key_flag("RW") | key_flag("access") | key_flag("update")
                            : ow_update;
            } else if (ascii_equal_icase(name, "bitfield")) {
                bool write = false;
                for (uint32_t index = command_argument + 2; index < op.argc(); index++)
                    write = write || ascii_equal_icase(op.arg(index), Slice("SET", 3)) ||
                            ascii_equal_icase(op.arg(index), Slice("INCRBY", 6));
                flags = write ? key_flag("RW") | key_flag("access") | key_flag("update")
                              : ro_access;
            }
        }

        int32_t begin = -1;
        if (spec.begin_type == BeginType::Index) {
            begin = spec.begin_index;
        } else if (spec.begin_type == BeginType::Keyword) {
            const uint32_t start = static_cast<uint32_t>(std::max<int16_t>(spec.startfrom, 0));
            for (uint32_t index = start; index < command_argc; index++) {
                if (ascii_equal_icase(op.arg(command_argument + index), spec.keyword)) {
                    begin = static_cast<int32_t>(index + 1);
                    break;
                }
            }
            if (begin < 0) continue;
        } else {
            continue;
        }
        if (begin < 0 || static_cast<uint32_t>(begin) >= command_argc) continue;

        if (spec.find_type == FindType::Range) {
            int32_t last = spec.lastkey >= 0 ? begin + spec.lastkey
                                              : static_cast<int32_t>(command_argc) + spec.lastkey;
            if (last < begin) continue;
            if (spec.limit > 0)
                last = begin + (last - begin + 1) / spec.limit - 1;
            if (last >= static_cast<int32_t>(command_argc) || spec.keystep <= 0)
                return CommandMetadataKeysResult::InvalidArguments;
            for (int32_t index = begin; index <= last; index += spec.keystep)
                keys.push_back({command_argument + static_cast<uint32_t>(index), flags});
        } else if (spec.find_type == FindType::Keynum) {
            const int32_t count_index = begin + spec.keynumidx;
            const int32_t first = begin + spec.firstkey;
            if (count_index < 0 || first < 0 ||
                static_cast<uint32_t>(count_index) >= command_argc)
                return CommandMetadataKeysResult::InvalidArguments;
            uint64_t count = 0;
            bool canonical = false;
            const bool parsed = parse_nonnegative(
                op.arg(command_argument + static_cast<uint32_t>(count_index)), count, canonical);
            const bool script = ascii_equal_icase(name, "eval") ||
                                ascii_equal_icase(name, "evalsha") ||
                                ascii_equal_icase(name, "eval_ro") ||
                                ascii_equal_icase(name, "evalsha_ro") ||
                                ascii_equal_icase(name, "fcall") ||
                                ascii_equal_icase(name, "fcall_ro");
            if (!parsed || count > command_argc ||
                first + count * static_cast<uint64_t>(spec.keystep) > command_argc) {
                if (script) continue;
                return CommandMetadataKeysResult::InvalidArguments;
            }
            if (!count && !script) return CommandMetadataKeysResult::InvalidArguments;
            // Redis's lenient integer parser still locates keys for +1/01, while its key-spec
            // flags callback declines to classify the noncanonical spelling.
            if (!canonical) flags = 0;
            for (uint64_t index = 0; index < count; index++)
                keys.push_back({command_argument + static_cast<uint32_t>(first) +
                                    static_cast<uint32_t>(index) * spec.keystep,
                                flags});
        }
    }
    return usable_spec ? CommandMetadataKeysResult::Success
                       : CommandMetadataKeysResult::NoKeyArguments;
}

uint32_t command_metadata_key_flag_count() {
    return sizeof(kGeneratedKeyFlagNames) / sizeof(kGeneratedKeyFlagNames[0]);
}

const char* command_metadata_key_flag_name(uint32_t index) {
    return index < command_metadata_key_flag_count() ? kGeneratedKeyFlagNames[index] : nullptr;
}

}  // namespace tomo
