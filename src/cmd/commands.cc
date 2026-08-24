// commands.cc — boot-built aggregate command index.
//
// Command ownership stays in t_*.cc. This file knows only how to validate and index rows, so five
// lanes can add commands independently without editing a central handler switch.
#include "command.h"

#include <cstdio>
#include <cstring>
#include <new>
#include <vector>

namespace tomo {
namespace {

struct Registry {
    std::vector<const CommandSpec*> slots;
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

bool command_equal(Slice input, const char* canonical) {
    const size_t n = std::strlen(canonical);
    if (input.n != n) return false;
    for (size_t i = 0; i < n; i++)
        if (ascii_upper(static_cast<uint8_t>(input.p[i])) !=
            ascii_upper(static_cast<uint8_t>(canonical[i]))) return false;
    return true;
}

}  // namespace

bool command_registry_init() {
    if (g_registry.built) return true;
    const CommandTable families[] = {
        string_command_table(), hash_command_table(), list_command_table(),
        set_command_table(), zset_command_table(), server_command_table(),
    };
    size_t total = 0;
    for (const CommandTable& family : families) total += family.size;
    size_t cap = 8;
    while (cap < total * 2) cap <<= 1;
    try {
        g_registry.slots.assign(cap, nullptr);
    } catch (const std::bad_alloc&) {
        return false;
    }
    g_registry.mask = static_cast<uint32_t>(cap - 1);

    for (const CommandTable& family : families) {
        for (size_t i = 0; i < family.size; i++) {
            const CommandSpec* spec = &family.specs[i];
            const size_t n = std::strlen(spec->name);
            if (n == 0 || spec->min_arity < 1 ||
                (spec->max_arity >= 0 && spec->max_arity < spec->min_arity) ||
                spec->first_key < 0 || spec->key_step < 0 ||
                (!(spec->flags & CmdFlags::ConnLocal) && spec->first_key >= spec->min_arity)) {
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

}  // namespace tomo
