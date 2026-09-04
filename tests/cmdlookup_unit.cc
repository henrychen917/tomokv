// cmdlookup_unit.cc — exhaustive exactness check for the inline hot-verb resolve in command.h.
//
// command_lookup claims GET/SET/DEL (3 bytes) and MGET/MSET/INCR (4 bytes) without consulting the
// registry. This test enumerates EVERY 3-byte and 4-byte name (2^24 + 2^32 inputs) and requires the
// resolve to agree with the registry's own relation — length match plus per-byte ascii_upper
// equality against the canonical row name — for which row it returns, and to hand every other name
// to command_lookup_registry unchanged. Shorter and longer names are spot-checked for fallthrough.
//
// Build (pinned; no server involved):
//   g++ -std=c++20 -O2 -Wall -Wextra -Werror -I. tests/cmdlookup_unit.cc -o build/cmdlookup_unit
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "src/cmd/command.h"

namespace tomo {

HotCommandSpecs g_hot_command_specs;

namespace {
// Registry stand-in: records the exact Slice it was asked about and returns a sentinel.
alignas(CommandSpec) unsigned char g_row_storage[7][sizeof(CommandSpec)];
const CommandSpec* row(size_t i) { return reinterpret_cast<const CommandSpec*>(g_row_storage[i]); }
const CommandSpec* const kRegistrySentinel = row(6);
Slice g_last_registry_query;
uint64_t g_registry_calls = 0;
}  // namespace

const CommandSpec* command_lookup_registry(Slice name) {
    g_last_registry_query = name;
    g_registry_calls++;
    return kRegistrySentinel;
}

}  // namespace tomo

using namespace tomo;

namespace {

[[noreturn]] void fail(const char* message, const unsigned char* bytes, uint32_t n) {
    std::fprintf(stderr, "cmdlookup unit: %s (name =", message);
    for (uint32_t i = 0; i < n; i++) std::fprintf(stderr, " %02x", bytes[i]);
    std::fprintf(stderr, ")\n");
    std::exit(1);
}

uint8_t ascii_upper(uint8_t c) {
    return (c >= 'a' && c <= 'z') ? static_cast<uint8_t>(c - ('a' - 'A')) : c;
}

struct HotRow { const char* name; uint32_t len; const CommandSpec* spec; };

// commands.cc's command_equal: the relation the registry probe implements for a matching row.
bool command_equal(const unsigned char* p, uint32_t n, const HotRow& row) {
    if (row.len != n) return false;
    for (uint32_t i = 0; i < n; i++)
        if (ascii_upper(p[i]) != ascii_upper(static_cast<uint8_t>(row.name[i]))) return false;
    return true;
}

const CommandSpec* expected(const unsigned char* p, uint32_t n, const HotRow* rows, size_t count) {
    for (size_t i = 0; i < count; i++)
        if (command_equal(p, n, rows[i])) return rows[i].spec;
    return kRegistrySentinel;
}

// Returns the row the registry relation names (the sentinel for a miss) after checking the resolve.
const CommandSpec* check(const unsigned char* p, uint32_t n, const HotRow* rows, size_t count) {
    const uint64_t calls_before = g_registry_calls;
    const CommandSpec* want = expected(p, n, rows, count);
    const CommandSpec* got = command_lookup(Slice(reinterpret_cast<const char*>(p), n));
    if (got != want) fail("resolve disagrees with the registry relation", p, n);
    if (want == kRegistrySentinel) {
        if (g_registry_calls != calls_before + 1) fail("miss did not reach the registry", p, n);
        if (g_last_registry_query.p != reinterpret_cast<const char*>(p) ||
            g_last_registry_query.n != n)
            fail("registry was asked about a different name", p, n);
    } else if (g_registry_calls != calls_before) {
        fail("hit still consulted the registry", p, n);
    }
    return want;
}

}  // namespace

int main() {
    g_hot_command_specs.get  = row(0);
    g_hot_command_specs.set  = row(1);
    g_hot_command_specs.del  = row(2);
    g_hot_command_specs.mget = row(3);
    g_hot_command_specs.mset = row(4);
    g_hot_command_specs.incr = row(5);
    const HotRow rows[] = {
        {"GET", 3, row(0)}, {"SET", 3, row(1)}, {"DEL", 3, row(2)},
        {"MGET", 4, row(3)}, {"MSET", 4, row(4)}, {"INCR", 4, row(5)},
    };
    const size_t count = sizeof(rows) / sizeof(rows[0]);

    // Pre-init state: null rows must come back null for a hot spelling (registry says null too).
    {
        HotCommandSpecs saved = g_hot_command_specs;
        g_hot_command_specs = HotCommandSpecs{};
        const unsigned char get[] = {'g', 'e', 't'};
        if (command_lookup(Slice(reinterpret_cast<const char*>(get), 3)) != nullptr)
            fail("pre-init hot spelling did not resolve to null", get, 3);
        g_hot_command_specs = saved;
    }

    uint64_t hits = 0;
    unsigned char name[8];
    // Every 3-byte name.
    for (uint32_t v = 0; v < (1u << 24); v++) {
        name[0] = static_cast<unsigned char>(v);
        name[1] = static_cast<unsigned char>(v >> 8);
        name[2] = static_cast<unsigned char>(v >> 16);
        if (check(name, 3, rows, count) != kRegistrySentinel) hits++;
    }
    if (hits != 3 * 8) fail("3-byte hit count is not 3 verbs x 2^3 spellings", name, 3);
    // Every 4-byte name.
    hits = 0;
    uint32_t v = 0;
    do {
        std::memcpy(name, &v, 4);
        if (check(name, 4, rows, count) != kRegistrySentinel) hits++;
        v++;
    } while (v != 0);
    if (hits != 3 * 16) fail("4-byte hit count is not 3 verbs x 2^4 spellings", name, 4);
    // Other lengths always fall through, including prefixes and extensions of hot verbs.
    const char* others[] = {"", "G", "GE", "GETX", "MGETS", "EXISTS", "get\r", "SETNX", "INCRBY"};
    for (const char* other : others) {
        const uint32_t n = static_cast<uint32_t>(std::strlen(other));
        if (n == 3 || n == 4) continue;
        check(reinterpret_cast<const unsigned char*>(other), n, rows, count);
    }
    std::printf("cmdlookup unit: OK (2^24 + 2^32 names, %llu registry queries)\n",
                static_cast<unsigned long long>(g_registry_calls));
    return 0;
}
