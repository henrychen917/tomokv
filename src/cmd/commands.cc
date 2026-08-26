// commands.cc — boot-built aggregate command index.
//
// Command ownership stays in t_*.cc. This file knows only how to validate and index rows, so the
// type lanes and server-compat lane can add commands without a central handler switch.
#include "command.h"
#include "acl_categories_generated.h"

#include <cstdio>
#include <cstring>
#include <new>
#include <vector>

namespace tomo {
namespace {

struct Registry {
    std::vector<CommandSpec> entries;
    std::vector<CommandSpec> notify_entries;
    std::vector<CommandSpec> tls_entries;
    std::vector<CommandSpec> tls_notify_entries;
    std::vector<const CommandSpec*> slots;
    uint64_t acl_categories[256] = {};
    uint32_t mask = 0;
    bool built = false;
};

Registry g_registry;

inline uint8_t ascii_upper(uint8_t c) {
    return (c >= 'a' && c <= 'z') ? static_cast<uint8_t>(c - ('a' - 'A')) : c;
}

uint64_t command_hash(const char* p, size_t n) {
    uint64_t h = 1469598103934665603ULL;
    for (size_t i = 0; i < n; i++) {
        h ^= ascii_upper(static_cast<uint8_t>(p[i]));
        h *= 1099511628211ULL;
    }
    h ^= n;
    h ^= h >> 33;
    h *= 0xff51afd7ed558ccdULL;
    h ^= h >> 33;
    return h;
}

const AclCommandCategoryDefinition* generated_acl_categories(const char* name) {
    size_t lo = 0, hi = kAclCommandCategoryCount;
    while (lo < hi) {
        const size_t mid = lo + (hi - lo) / 2;
        const int order = std::strcmp(kAclCommandCategories[mid].name, name);
        if (order < 0) lo = mid + 1;
        else hi = mid;
    }
    return lo < kAclCommandCategoryCount && !std::strcmp(kAclCommandCategories[lo].name, name)
        ? &kAclCommandCategories[lo] : nullptr;
}

bool command_equal(Slice input, const char* canonical) {
    const size_t n = std::strlen(canonical);
    if (input.n != n) return false;
    for (size_t i = 0; i < n; i++)
        if (ascii_upper(static_cast<uint8_t>(input.p[i])) !=
            ascii_upper(static_cast<uint8_t>(canonical[i]))) return false;
    return true;
}

}  // namespace

bool command_registry_init(bool tls_enabled) {
    if (g_registry.built) return true;
    const CommandTable families[] = {
        string_command_table(), hash_command_table(), list_command_table(),
        set_command_table(), zset_command_table(), zset_ops_command_table(),
        geo_command_table(), stream_command_table(),
        stream_group_command_table(), server_command_table(),
        scripting_command_table(), functions_command_table(),
    };
    size_t total = 0;
    for (const CommandTable& family : families) total += family.size;
    if (total > 255) {
        std::fprintf(stderr, "command registry exceeds the reserved 255 ACL command bits\n");
        return false;
    }
    size_t cap = 8;
    while (cap < total * 2) cap <<= 1;
    try {
        g_registry.slots.assign(cap, nullptr);
    } catch (const std::bad_alloc&) {
        return false;
    }
    g_registry.mask = static_cast<uint32_t>(cap - 1);

    try {
        g_registry.entries.reserve(total);
        for (const CommandTable& family : families)
            for (size_t i = 0; i < family.size; i++) {
                CommandSpec copy = family.specs[i];
                const AclCommandCategoryDefinition* categories =
                    generated_acl_categories(copy.name);
                if (!categories) {
                    std::fprintf(stderr, "missing generated ACL categories for '%s'\n", copy.name);
                    return false;
                }
                copy.id = static_cast<uint16_t>(g_registry.entries.size());
                g_registry.acl_categories[copy.id] = categories->categories;
                g_registry.entries.push_back(copy);
            }
    } catch (const std::bad_alloc&) {
        g_registry.entries.clear();
        g_registry.notify_entries.clear();
        g_registry.tls_entries.clear();
        g_registry.tls_notify_entries.clear();
        g_registry.slots.clear();
        return false;
    }

    try {
        g_registry.notify_entries = g_registry.entries;
        for (CommandSpec& entry : g_registry.notify_entries) {
            entry.flags |= CmdFlags::NotifySelected;
            entry.handler = entry.handler_notify;
        }
    } catch (const std::bad_alloc&) {
        g_registry.entries.clear();
        g_registry.notify_entries.clear();
        g_registry.tls_entries.clear();
        g_registry.tls_notify_entries.clear();
        g_registry.slots.clear();
        return false;
    }
    if (tls_enabled) {
        try {
            g_registry.tls_entries = g_registry.entries;
            g_registry.tls_notify_entries = g_registry.notify_entries;
            for (size_t i = 0; i < g_registry.entries.size(); i++) {
                if (std::strcmp(g_registry.entries[i].name, "GET")) continue;
                g_registry.tls_entries[i].handler = cmd_get_tls;
                g_registry.tls_notify_entries[i].handler = cmd_get_tls_notify;
            }
        } catch (const std::bad_alloc&) {
            g_registry.entries.clear();
            g_registry.notify_entries.clear();
            g_registry.tls_entries.clear();
            g_registry.tls_notify_entries.clear();
            g_registry.slots.clear();
            return false;
        }
    }
    if (g_registry.entries.size() != kAclCommandCategoryCount) {
        std::fprintf(stderr, "generated ACL category table has %zu rows for %zu commands\n",
                     kAclCommandCategoryCount, g_registry.entries.size());
        return false;
    }

    for (const CommandSpec& entry : g_registry.entries) {
        const CommandSpec* spec = &entry;
        const size_t n = std::strlen(spec->name);
        if (n == 0 || spec->min_arity < 1 ||
            (spec->max_arity >= 0 && spec->max_arity < spec->min_arity) ||
            spec->first_key < 0 || spec->key_step < 0 ||
            (!(spec->flags & (CmdFlags::ConnLocal | CmdFlags::AllShards |
                              CmdFlags::RandomShard | CmdFlags::CursorShard |
                              CmdFlags::ConfigRoute | CmdFlags::MultiShard |
                              CmdFlags::ScriptRoute)) &&
             spec->first_key >= spec->min_arity)) {
            std::fprintf(stderr, "invalid command registry row '%s'\n", spec->name);
            return false;
        }
        size_t pos = command_hash(spec->name, n) & g_registry.mask;
        while (g_registry.slots[pos]) {
            if (command_equal(Slice(spec->name, static_cast<uint32_t>(n)),
                              g_registry.slots[pos]->name)) {
                std::fprintf(stderr, "duplicate command registry row '%s'\n", spec->name);
                return false;
            }
            pos = (pos + 1) & g_registry.mask;
        }
        g_registry.slots[pos] = spec;
    }
    g_registry.built = true;
    return true;
}

const CommandSpec* command_lookup(Slice name) {
    if (!g_registry.built || name.n == 0) return nullptr;
    size_t pos = command_hash(name.p, name.n) & g_registry.mask;
    for (size_t probes = 0; probes < g_registry.slots.size(); probes++) {
        const CommandSpec* spec = g_registry.slots[pos];
        if (!spec) return nullptr;
        if (command_equal(name, spec->name)) return spec;
        pos = (pos + 1) & g_registry.mask;
    }
    return nullptr;
}

bool command_arity_ok(const CommandSpec& spec, uint32_t argc) {
    return argc >= static_cast<uint32_t>(spec.min_arity) &&
           (spec.max_arity < 0 || argc <= static_cast<uint32_t>(spec.max_arity));
}

uint32_t command_registry_size() {
    return static_cast<uint32_t>(g_registry.entries.size());
}

const CommandSpec* command_registry_at(uint32_t id) {
    return id < g_registry.entries.size() ? &g_registry.entries[id] : nullptr;
}

uint64_t command_acl_category_mask(const CommandSpec& spec) {
    return g_registry.acl_categories[spec.id];
}

const CommandSpec* command_notify_variant(const CommandSpec* spec) {
    return spec && spec->id < g_registry.notify_entries.size()
        ? &g_registry.notify_entries[spec->id] : spec;
}

const CommandSpec* command_tls_variant(const CommandSpec* spec) {
    if (!spec || g_registry.tls_entries.empty() || spec->id >= g_registry.tls_entries.size())
        return spec;
    return (spec->flags & CmdFlags::NotifySelected)
        ? &g_registry.tls_notify_entries[spec->id]
        : &g_registry.tls_entries[spec->id];
}

}  // namespace tomo
