// t_server.cc — connection-local server, stats and live configuration commands.
//
// These handlers execute on an IO owner. They may read immutable/published shard state and update
// the atomically published live config, but they never inspect a worker-owned FlatStore.
#include "command.h"
#include "../core/server.h"
#include "../exec/op.h"
#include "../net/resp.h"

#include <climits>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace tomo {
namespace {

Server* g_server = nullptr;

bool parse_u64(Slice input, uint64_t& out) {
    if (input.empty()) return false;
    uint64_t value = 0;
    for (uint32_t i = 0; i < input.n; i++) {
        const char ch = input.p[i];
        if (ch < '0' || ch > '9') return false;
        const uint32_t digit = static_cast<uint32_t>(ch - '0');
        if (value > (UINT64_MAX - digit) / 10) return false;
        value = value * 10 + digit;
    }
    out = value;
    return true;
}

bool parse_ll(Slice input, long long& out) {
    if (input.empty() || input.n > 20) return false;
    char text[24];
    std::memcpy(text, input.p, input.n);
    text[input.n] = '\0';
    char* end = nullptr;
    out = std::strtoll(text, &end, 10);
    return end == text + input.n;
}

void reply_config_value(Op& op, const char* name, const char* value) {
    reply_array_header(op.sink(), 2);
    reply_bulk(op.sink(), Slice(name, static_cast<uint32_t>(std::strlen(name))));
    reply_bulk(op.sink(), Slice(value, static_cast<uint32_t>(std::strlen(value))));
}

void reply_config_u64(Op& op, const char* name, uint64_t value) {
    char text[24];
    const uint32_t length = u64_to_dec(text, value);
    reply_array_header(op.sink(), 2);
    reply_bulk(op.sink(), Slice(name, static_cast<uint32_t>(std::strlen(name))));
    reply_bulk(op.sink(), Slice(text, length));
}

void cmd_dbsize(Shard&, Op& op) {
    uint64_t keys = 0;
    if (g_server) for (uint32_t i = 0; i < g_server->nshards(); i++)
        keys += g_server->shard(static_cast<int32_t>(i)).published_size();
    reply_int(op.sink(), static_cast<long long>(keys));
}

void cmd_info(Shard&, Op& op) {
    char buf[1024];
    uint64_t keys = 0, hits = 0, misses = 0, ops = 0, evicted = 0;
    uint32_t nshards = 0;
    if (g_server) {
        nshards = g_server->nshards();
        for (uint32_t i = 0; i < nshards; i++) {
            const Shard& shard = g_server->shard(static_cast<int32_t>(i));
            keys += shard.published_size();
            hits += shard.stats().hits;
            misses += shard.stats().misses;
            ops += shard.stats().ops;
            evicted += shard.published_evicted();
        }
    }
    const int length = std::snprintf(buf, sizeof(buf),
        "# Server\r\ntomokv_version:0.1-cpp\r\n"
        "# Keyspace\r\ndb0:keys=%llu\r\n"
        "# Stats\r\ntotal_commands_processed:%llu\r\nkeyspace_hits:%llu\r\nkeyspace_misses:%llu\r\n"
        "evicted_keys:%llu\r\n"
        "# Tomo\r\ntomokv_shards:%u\r\n",
        (unsigned long long)keys, (unsigned long long)ops,
        (unsigned long long)hits, (unsigned long long)misses,
        (unsigned long long)evicted, nshards);
    reply_bulk(op.sink(), Slice(buf, static_cast<uint32_t>(length)));
}

void cmd_select(Shard&, Op& op) {
    long long db = 0;
    if (!parse_ll(op.arg(1), db) || db != 0) {
        reply_err(op.sink(), "ERR this server supports a single keyspace; only SELECT 0 is valid");
        return;
    }
    reply_ok(op.sink());
}

void config_error(Op& op, const char* message, Slice value) {
    char text[192];
    const int length = std::snprintf(text, sizeof(text), "ERR %s '%.*s'",
                                     message, static_cast<int>(value.n), value.p);
    if (length <= 0) reply_err(op.sink(), "ERR invalid CONFIG argument");
    else {
        text[sizeof(text) - 1] = '\0';
        reply_err(op.sink(), text);
    }
}

void config_get(Op& op) {
    if (!g_server || op.argc() != 3) { reply_array_header(op.sink(), 0); return; }
    const MaxmemoryConfigSnapshot snapshot = g_server->maxmemory_config_snapshot();
    const Slice pattern = op.arg(2);
    if (pattern.eq_icase("maxmemory")) {
        reply_config_u64(op, "maxmemory", snapshot.maxmemory);
    } else if (pattern.eq_icase("maxmemory-policy")) {
        reply_config_value(op, "maxmemory-policy", maxmemory_policy_name(snapshot.policy));
    } else if (pattern.eq_icase("maxmemory-samples")) {
        reply_config_u64(op, "maxmemory-samples", snapshot.samples);
    } else if (pattern.n == 1 && pattern.p[0] == '*') {
        char memory[24], samples[24];
        const uint32_t memory_len = u64_to_dec(memory, snapshot.maxmemory);
        const uint32_t samples_len = u64_to_dec(samples, snapshot.samples);
        const char* policy = maxmemory_policy_name(snapshot.policy);
        reply_array_header(op.sink(), 6);
        reply_bulk(op.sink(), Slice("maxmemory", 9));
        reply_bulk(op.sink(), Slice(memory, memory_len));
        reply_bulk(op.sink(), Slice("maxmemory-policy", 16));
        reply_bulk(op.sink(), Slice(policy, static_cast<uint32_t>(std::strlen(policy))));
        reply_bulk(op.sink(), Slice("maxmemory-samples", 17));
        reply_bulk(op.sink(), Slice(samples, samples_len));
    } else {
        reply_array_header(op.sink(), 0);
    }
}

void config_set(Op& op) {
    if (!g_server || op.argc() < 4 || (op.argc() & 1)) {
        reply_syntax(op.sink());
        return;
    }

    MaxmemoryConfigSnapshot desired = g_server->maxmemory_config_snapshot();
    bool set_memory = false, set_policy = false, set_samples = false;
    for (uint32_t i = 2; i < op.argc(); i += 2) {
        const Slice name = op.arg(i);
        const Slice value = op.arg(i + 1);
        if (name.eq_icase("maxmemory")) {
            if (!parse_u64(value, desired.maxmemory)) {
                config_error(op, "invalid maxmemory byte count", value); return;
            }
            set_memory = true;
        } else if (name.eq_icase("maxmemory-policy")) {
            if (!parse_maxmemory_policy(value.sv(), desired.policy)) {
                config_error(op, "invalid maxmemory policy", value); return;
            }
            set_policy = true;
        } else if (name.eq_icase("maxmemory-samples")) {
            uint64_t samples = 0;
            if (!parse_u64(value, samples) || samples == 0 || samples > 64) {
                config_error(op, "maxmemory-samples must be 1..64, got", value); return;
            }
            desired.samples = static_cast<uint32_t>(samples);
            set_samples = true;
        } else {
            config_error(op, "unsupported CONFIG parameter", name); return;
        }
    }
    // Validation above is all-or-nothing. One odd/even publication covers every supplied pair;
    // executors consume the resulting values at the start of a subsequent loop pass.
    if (set_memory || set_policy || set_samples)
        g_server->set_maxmemory_config(desired.maxmemory, desired.policy, desired.samples,
                                       set_memory, set_policy, set_samples);
    reply_ok(op.sink());
}

void cmd_config(Shard&, Op& op) {
    // eq_icase lowercases the INPUT and compares against the literal, so the literal must be
    // lowercase -- "GET" here matched nothing and every CONFIG fell through to the empty array.
    if (op.arg(1).eq_icase("get")) { config_get(op); return; }
    if (op.arg(1).eq_icase("set")) { config_set(op); return; }
    reply_array_header(op.sink(), 0);
}

void cmd_ping(Shard&, Op& op) {
    if (op.argc() == 2) reply_bulk(op.sink(), op.arg(1)); else reply_pong(op.sink());
}
void cmd_echo(Shard&, Op& op)    { reply_bulk(op.sink(), op.arg(1)); }
void cmd_command(Shard&, Op& op) { reply_array_header(op.sink(), 0); }

static const CommandSpec kTable[] = {
    // name       min max flags                                  handler      first last step
    {"PING",      1, -1,  CmdFlags::ConnLocal,                   cmd_ping,      0,  0,  0},
    {"ECHO",      2,  2,  CmdFlags::ConnLocal,                   cmd_echo,      0,  0,  0},
    {"COMMAND",   1, -1,  CmdFlags::ConnLocal | CmdFlags::Admin, cmd_command,   0,  0,  0},
    {"DBSIZE",    1,  1,  CmdFlags::ConnLocal | CmdFlags::Admin, cmd_dbsize,    0,  0,  0},
    {"INFO",      1, -1,  CmdFlags::ConnLocal | CmdFlags::Admin, cmd_info,      0,  0,  0},
    {"SELECT",    2,  2,  CmdFlags::ConnLocal,                   cmd_select,    0,  0,  0},
    {"CONFIG",    2, -1,  CmdFlags::ConnLocal | CmdFlags::Admin, cmd_config,    0,  0,  0},
};

}  // namespace

void command_bind_server(Server* server) { g_server = server; }

CommandTable server_command_table() {
    return {kTable, sizeof(kTable) / sizeof(kTable[0])};
}

}  // namespace tomo
