// Finite storage checks shared by PRE and F11: no server, sockets, timers or PMU sampling.
// Compile this SAME source with -I<arm> to attribute allocations and inspect generated wrappers.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "src/net/resp.h"
#include "src/net/rob.h"

extern "C" {
__attribute__((noinline)) tomo::Slice cache_l3_arg(const tomo::Op& op, uint32_t i) {
    return op.arg(i);
}
__attribute__((noinline)) void cache_l3_shrink(tomo::Op& op) { op.shrink(); }
__attribute__((noinline)) void cache_l3_retire_storage(tomo::Op& op) {
    if (op.oversized()) op.shrink();
}
__attribute__((noinline)) char* cache_l3_reserve(tomo::Op& op, size_t n) {
    return op.reply.reserve(n);
}
}

#ifndef TOMO_STAGE_COST_ASM
struct Counts {
    size_t news = 0, mallocs = 0, reallocs = 0, frees = 0, bytes = 0;
    Counts operator-(const Counts& b) const {
        return {news-b.news, mallocs-b.mallocs, reallocs-b.reallocs,
                frees-b.frees, bytes-b.bytes};
    }
};
static Counts calls;
extern "C" {
void* __real_malloc(size_t);
void* __real_realloc(void*, size_t);
void __real_free(void*);
void* __real__Znwm(size_t);
void* __real__Znam(size_t);
void* __wrap_malloc(size_t n) { ++calls.mallocs; calls.bytes += n; return __real_malloc(n); }
void* __wrap_realloc(void* p, size_t n) {
    ++calls.reallocs; calls.bytes += n; return __real_realloc(p, n);
}
void __wrap_free(void* p) { if (p) ++calls.frees; __real_free(p); }
void* __wrap__Znwm(size_t n) { ++calls.news; calls.bytes += n; return __real__Znwm(n); }
void* __wrap__Znam(size_t n) { ++calls.news; calls.bytes += n; return __real__Znam(n); }
}

static void check(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL multikey storage: %s\n", why); std::abort(); }
}

template <bool Codes> static void multikey(bool mget, bool direct) {
    char value[65];
    std::memset(value, 'v', 64);
    value[64] = 0;
    char wire[1024];
    size_t length = std::snprintf(wire, sizeof(wire), "*%u\r\n$4\r\n%s\r\n",
                                 mget ? 9 : 17, mget ? "MGET" : "MSET");
    for (unsigned i = 0; i < 8; ++i) {
        length += std::snprintf(wire + length, sizeof(wire) - length, "$2\r\nk%u\r\n", i);
        if (!mget)
            length += std::snprintf(wire + length, sizeof(wire) - length, "$64\r\n%s\r\n", value);
    }
    check(length < sizeof(wire), "fixture fits the request buffer");
    char expected[1024];
    size_t expected_length = std::snprintf(expected, sizeof(expected), mget ? "*8\r\n" : "+OK\r\n");
    if (mget) for (unsigned i = 0; i < 8; ++i)
        expected_length += std::snprintf(expected + expected_length, sizeof(expected) - expected_length,
                                         "$64\r\n%s\r\n", value);

    const Counts empty_before = calls;
    tomo::Rob<8> rob;
    check(calls.news == empty_before.news && calls.mallocs == empty_before.mallocs &&
          calls.reallocs == empty_before.reallocs, "empty ROB allocates nothing");
    char* homes[8]{};
    // Two wraps force reuse of every body after argv-triggered shrink, in both reply-code modes.
    for (unsigned round = 0; round < 16; ++round) {
        const Counts acquire_before = calls;
        tomo::Op* op = rob.template acquire<Codes>();
        check(op != nullptr, "acquire reused slot");
        const Counts acquire = calls - acquire_before;
        check(acquire.news == (round == 0) && acquire.mallocs == 0 && acquire.reallocs == 0,
              "only the first slot acquisition allocates a chunk");
        if (round < 8) homes[round] = op->reply.data();
        check(op->reply.data() == homes[round % 8] && op->reply.cap() == 96,
              "reused reply starts at its bound home");
        const Counts parse_before = calls;
        uint32_t pos = 0;
        const char* error = nullptr;
        check(tomo::resp_parse(wire, length, pos, *op, &error) == tomo::ParseResult::Ok &&
              pos == length && error == nullptr, "the actual RESP parser accepts every argument");
        const Counts parse = calls - parse_before;
        check(op->argc() == (mget ? 9u : 17u) && op->oversized(), "argv really spills beyond eight");
        check(parse.news == 0 && parse.mallocs == 0 && parse.reallocs == (mget ? 1u : 2u) &&
              parse.bytes == (mget ? 256u : 768u), "argv allocation count and bytes match PRE");
        for (unsigned i = 0; i < 8; ++i) {
            const tomo::Slice key = cache_l3_arg(*op, 1 + i * (mget ? 1 : 2));
            check(key.n == 2 && key.p[0] == 'k' && key.p[1] == char('0' + i),
                  "heap argument lookup preserves all key positions");
            if (!mget) check(op->arg(2 + i * 2).sv() == std::string_view(value, 64), "MSET value");
        }
        char direct_bytes[1024];
        if (direct) { op->direct = direct_bytes; op->direct_cap = sizeof(direct_bytes); }
        const Counts reply_before = calls;
        if (mget) {
            tomo::reply_array_header(op->sink(), 8);
            for (unsigned i = 0; i < 8; ++i) tomo::reply_bulk(op->sink(), tomo::Slice(value, 64));
        } else {
            tomo::reply_ok(op->sink());
        }
        const Counts reply = calls - reply_before;
        const bool grew = mget && !direct;
        check(reply.news == 0 && reply.reallocs == 0 && reply.mallocs == (grew ? 3u : 0u) &&
              reply.bytes == (grew ? 1344u : 0u), "reply growth adds no F11 allocation");
        const bool coded = Codes && !mget;
        if (coded) {
            check(op->reply_code_ == static_cast<uint8_t>(tomo::ReplyCode::Ok) &&
                  op->reply.empty() && op->direct_len == 0, "MSET uses a whole coded reply");
        } else {
            const char* bytes = direct ? direct_bytes : op->reply.data();
            const size_t count = direct ? op->direct_len : op->reply.size();
            check(count == expected_length && !std::memcmp(bytes, expected, count),
                  "reply serialization preserves every byte");
        }
        rob.publish();
        op->state.store(tomo::OpState::Done, std::memory_order_release);
        const Counts retire_before = calls;
        check(rob.drain([](tomo::Op&) {}) == 1, "retire exactly one command");
        const Counts retire = calls - retire_before;
        check(retire.news == 0 && retire.mallocs == 0 && retire.reallocs == 0 &&
              retire.frees == (grew ? 2u : 1u), "retirement frees argv and only an actual heap reply");
        check(!op->oversized() && op->reply.data() == homes[round % 8] && op->reply.cap() == 96,
              "argv-triggered retirement restores home before reuse");
        if (round == 0)
            std::printf("{\"op_bytes\":%zu,\"command\":\"%s8\",\"codes\":%d,\"direct\":%d,"
                        "\"chunk_bytes\":%zu,\"argv_reallocs\":%zu,\"argv_bytes\":%zu,"
                        "\"reply_mallocs\":%zu,\"reply_bytes\":%zu,\"retire_frees\":%zu}\n",
                        sizeof(tomo::Op), mget ? "MGET" : "MSET", Codes, direct,
                        acquire.bytes, parse.reallocs, parse.bytes, reply.mallocs, reply.bytes, retire.frees);
    }
}

int main() {
    for (bool mget : {true, false}) for (bool direct : {false, true}) {
        multikey<false>(mget, direct);
        multikey<true>(mget, direct);
    }
    std::puts("multikey storage unit: byte checks, allocation counts and two ROB wraps passed");
}
#endif
