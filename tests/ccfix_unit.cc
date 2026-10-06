// Serverless semantic checks. No Server, listener, ring, or worker is started.
#include <cassert>
#include <cstdio>
#include <string>
#include <utility>
#include "src/cmd/command.h"
#include "src/cmd/notify.h"
#include "src/cmd/info_stats.h"
#include "src/core/thread.h"
#include "src/exec/op.h"
#include "src/net/resp.h"
namespace tomo { bool notify_keymiss_read_lookup(const Op&, Slice); }
using namespace tomo;

int main() {
    const std::pair<const char*, const char*> flags[] = {
        {"", ""}, {"AKE", "AKE"}, {"AKEn", "AKE"}, {"gnK", "gnK"},
        {"gKn", "gnK"}, {"Em", "Em"}, {"KEA", "AKE"}, {"$lshzxe", "$lshzxe"},
        {"g$lshzxetdnKEm", "AKEm"}, {"nKmE", "nKEm"}, {"AEmn", "AEm"},
    };
    for (auto [input, expected] : flags) {
        uint32_t mask = 0;
        assert(parse_notify_flags(Slice(input, std::strlen(input)), mask));
        assert(serialize_notify_flags(mask) == expected);
    }
#ifndef TOMO_CCFIX_FLAGS_ONLY
    for (const char* command : {"COPY", "SINTERSTORE", "SUNIONSTORE", "SDIFFSTORE", "BITOP", "SET"}) {
        Op op;
        CommandSpec spec(command, 2, -1, CmdFlags::Write, nullptr, 1, -1, 1);
        op.spec = &spec;
        std::string name(command), a("same-key"), b(name == "COPY" ? "other-key" : "same-key"), c("same-key");
        assert(op.push_arg(Slice(name.data(), name.size())));
        assert(op.push_arg(Slice(a.data(), a.size())));
        assert(op.push_arg(Slice(b.data(), b.size())));
        assert(op.push_arg(Slice(c.data(), c.size())));
        for (uint32_t arg = 1; arg < 4; ++arg) {
            const bool expected = name == "COPY" ? arg == 1 : name == "BITOP" ? arg == 3 :
                                  name == "SET" ? false : arg >= 2;
            assert(notify_keymiss_read_lookup(op, op.arg(arg)) == expected);
        }
        // Equal bytes alone must never turn a destination/foreign lookup into a read lookup.
        std::string unrelated("same-key");
        assert(!notify_keymiss_read_lookup(op, Slice(unrelated.data(), unrelated.size())));
    }
    ThreadCtx thread;
    thread.init_command_counts(4);
    thread.note_command(1);
    thread.note_command_rejected(1);
    thread.note_command_failed(1);
    assert(thread.command_calls(1) == 1 && thread.total_commands() == 1);
    assert(thread.command_rejected_calls(1) == 1 && thread.command_failed_calls(1) == 1);
    assert(thread.command_calls(0) == 0 && thread.command_rejected_calls(0) == 0 &&
           thread.command_failed_calls(0) == 0);
    thread.init_command_counts(0);
    thread.note_command_rejected(1);
    thread.note_command_failed(1);
    assert(thread.command_rejected_calls(1) == 0 && thread.command_failed_calls(1) == 0);

    // EXPECTED-DEVIATION CC18: real producers leave failed_calls at zero.
    // Keep this separate from the round-1 counter-storage checks above.
    assert(command_registry_init(false));
    thread.init_command_counts(command_registry_size());
    Shard shard;
    auto run = [&](std::initializer_list<const char*> args, bool rejected = false) {
        Op op;
        for (const char* arg : args) assert(op.push_arg(Slice(arg, std::strlen(arg))));
        op.spec = command_lookup(op.cmd_name());
        assert(op.spec);
        op.hash = FlatStore::hash_key(op.key());
        const uint64_t before = thread.command_failed_calls(op.spec->id);
        if (rejected) {
            thread.note_command_rejected(op.spec->id);
            reply_err(op.sink(), "NOPERM fixture denial");
        } else {
            thread.note_command(op.spec->id);
            op.spec->handler(shard, op);
        }
        const bool error = !op.reply.empty() && op.reply.data()[0] == '-';
        assert(thread.command_failed_calls(op.spec->id) == before);
        return error;
    };
    assert(!run({"LPUSH", "ccfix:list", "v"}));
    assert(run({"GET", "ccfix:list"}, true));
    assert(run({"GET", "ccfix:list"}));
    assert(!run({"GET", "ccfix:absent"}));
    assert(run({"SET", "ccfix:k", "v", "BADOPTION"}));
    assert(run({"EVALSHA", "0000000000000000000000000000000000000000", "0"}));
    const auto* get = command_lookup(Slice("GET", 3));
    assert(thread.command_calls(get->id) == 2);
    assert(thread.command_rejected_calls(get->id) == 1);
    assert(thread.command_failed_calls(get->id) == 0);
    // EXPECTED-DEVIATION: even multiple error members have no failure accounting.
    Op composed;
    composed.spec = get;
    reply_array_header(composed.sink(), 3);
    reply_bulk(composed.sink(), Slice("-ERR not an error", 17));
    reply_wrongtype(composed.sink());
    reply_syntax(composed.sink());
    assert(thread.command_failed_calls(get->id) == 0);
    std::puts("EXPECTED-DEVIATION CC18: executed errors do not increment failed_calls");
#endif
    std::puts("PASS ccfix serverless assertions");
}
