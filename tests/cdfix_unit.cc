// Serverless CD6/CD7/CD8/CD13 witnesses. Link the same witness with PRE and POST objects.
// Redis's unmodified geohash.c/util.c are linked ONLY into this test for the coordinate oracle.
#include "src/cmd/command.h"
#include "src/cmd/geo.h"
#include "src/core/shard.h"
#include "src/exec/op.h"
#include <cstdio>
#include <cstring>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

extern "C" int cdfix_oracle_geopos(double longitude, double latitude, double xy[2],
                                  char* x, size_t xlen, char* y, size_t ylen);

using namespace tomo;
namespace {
void require(bool ok, const std::string& why) {
    if (!ok) throw std::runtime_error(why);
}
std::string bulk(const std::string& value) {
    return "$" + std::to_string(value.size()) + "\r\n" + value + "\r\n";
}
std::string hex(const std::string& value) {
    std::string result;
    for (unsigned char c : value) {
        result += "0123456789abcdef"[c >> 4];
        result += "0123456789abcdef"[c & 15];
    }
    return result;
}
struct Fixture {
    Shard shard;
    bool resp3, notify;
    Fixture(bool protocol = false, bool notifications = false)
        : resp3(protocol), notify(notifications) {
        shard.init_private(nullptr, 0, TypeLimits{}, StreamLimits{});
    }
    std::string run(const std::vector<std::string>& args) {
        Op op;
        for (const auto& arg : args)
            require(op.push_arg(Slice(arg.data(), arg.size())), "argument allocation");
        op.spec = command_lookup(op.arg(0));
        require(op.spec, "registered command " + args[0]);
        if (op.spec->first_key > 0)
            op.hash = FlatStore::hash_key(op.arg(op.spec->first_key));
        if (resp3) op.mark_resp3();
        if (args[0] == "GEORADIUS" || args[0] == "GEORADIUSBYMEMBER")
            cmd_geo_xshard_local(shard, op, notify);
        else
            (notify ? op.spec->handler_notify : op.spec->handler)(shard, op);
        return {op.reply.data(), op.reply.size()};
    }
    KvObj* object(const std::string& key) {
        const Slice name(key.data(), key.size());
        return shard.store().find_no_touch(FlatStore::hash_key(name), name);
    }
};

struct Reply {
    char type;
    std::string text;
    std::vector<Reply> children;
};
Reply parse(const std::string& wire, size_t& pos) {
    require(pos < wire.size(), "missing RESP frame");
    const char type = wire[pos++];
    const size_t end = wire.find("\r\n", pos);
    require(end != std::string::npos, "missing CRLF");
    Reply result{type, wire.substr(pos, end - pos), {}};
    pos = end + 2;
    if (type == '$') {
        const size_t size = std::stoull(result.text);
        result.text = wire.substr(pos, size);
        require(wire.substr(pos + size, 2) == "\r\n", "invalid bulk length");
        pos += size + 2;
    } else if (type == '*' || type == '~') {
        const unsigned count = std::stoul(result.text);
        for (unsigned i = 0; i < count; ++i) result.children.push_back(parse(wire, pos));
    }
    return result;
}
Reply parse(const std::string& wire) {
    size_t pos = 0;
    Reply result = parse(wire, pos);
    require(pos == wire.size(), "extra RESP bytes");
    return result;
}

void coordinates() {
    unsigned comparisons = 0, trimmed = 0;
    for (bool resp3 : {false, true}) for (bool notify : {false, true}) {
        Fixture f(resp3, notify);
        std::mt19937_64 rng(0xcdf1707);
        std::uniform_real_distribution<double> lon(-179.99, 179.99), lat(-85.05, 85.05);
        for (unsigned i = 0; i < 512; ++i) {
            const double x = lon(rng), y = lat(rng);
            char xs[64], ys[64];
            std::snprintf(xs, sizeof(xs), "%.17g", x);
            std::snprintf(ys, sizeof(ys), "%.17g", y);
            require(f.run({"GEOADD", "geo", xs, ys, "m"}) == (i ? ":0\r\n" : ":1\r\n"),
                    "seed coordinate");
            double xy[2];
            char human[2][96];
            require(cdfix_oracle_geopos(x, y, xy, human[0], sizeof(human[0]),
                                        human[1], sizeof(human[1])), "Redis coordinate oracle");
            std::string expected = "*1\r\n*2\r\n";
            for (unsigned axis = 0; axis < 2; ++axis) {
                char fixed[96];
                const int size = std::strlen(human[axis]);
                const int untrimmed = std::snprintf(fixed, sizeof(fixed), "%.17Lf",
                                                   static_cast<long double>(xy[axis]));
                trimmed += size < untrimmed;
                expected += resp3 ? "," + std::string(human[axis], size) + "\r\n"
                                  : bulk(std::string(human[axis], size));
            }
            const std::string actual = f.run({"GEOPOS", "geo", "m"});
            require(actual == expected, "CD7 point=" + std::to_string(i) + " RESP" +
                    (resp3 ? "3" : "2") + " actual=" + hex(actual) + " oracle=" + hex(expected));
            ++comparisons;
        }
    }
    require(trimmed > 200, "coordinate spread never exercised trailing-zero trim");
    std::printf("CD7: %u byte-exact GEOPOS replies, %u trimmed coordinates, RESP2/3 notify off/on\n",
                comparisons, trimmed);
}

void stores() {
    unsigned cases = 0;
    for (bool resp3 : {false, true}) for (bool notify : {false, true})
    for (bool by_member : {false, true}) for (bool distances : {false, true})
    for (bool existing : {false, true}) {
        Fixture f(resp3, notify);
        require(f.run({"GEOADD", "geo", "13", "38", "a", "13.01", "38.01", "b"}) == ":2\r\n",
                "seed radius source");
        if (existing) {
            require(f.run({"SET", "first", "keep"}) == "+OK\r\n", "seed first destination");
            require(f.run({"SET", "last", "replace"}) == "+OK\r\n", "seed last destination");
        }
        auto radius = by_member ? std::vector<std::string>{"GEORADIUSBYMEMBER", "geo", "a"}
                                : std::vector<std::string>{"GEORADIUS", "geo", "13", "38"};
        radius.insert(radius.end(), {"10", "km"});
        auto control = radius;
        control.insert(control.end(), {distances ? "STOREDIST" : "STORE", "control"});
        require(f.run(control) == ":2\r\n", "single STORE control");
        radius.insert(radius.end(), {distances ? "STORE" : "STOREDIST", "first",
                                     distances ? "STOREDIST" : "STORE", "last"});
        require(f.run(radius) == ":2\r\n", "double STORE reply");
        require(f.run({"EXISTS", "first"}) == (existing ? ":1\r\n" : ":0\r\n"),
                "CD8 first destination existence changed");
        require(f.run({"TYPE", "first"}) == (existing ? "+string\r\n" : "+none\r\n"),
                "CD8 first destination type changed");
        require(f.run({"ZRANGE", "first", "0", "-1", "WITHSCORES"}) ==
                    (existing ? "-WRONGTYPE Operation against a key holding the wrong kind of value\r\n"
                              : "*0\r\n"), "CD8 first destination contents changed");
        require(f.run({"EXISTS", "last"}) == ":1\r\n" && f.run({"TYPE", "last"}) == "+zset\r\n",
                "CD8 last destination was not written");
        require(f.run({"ZRANGE", "last", "0", "-1", "WITHSCORES"}) ==
                f.run({"ZRANGE", "control", "0", "-1", "WITHSCORES"}),
                "CD8 last token did not select the score mode");
        ++cases;
    }
    std::printf("CD8: %u STORE orders/verbs/destinations/protocols/notification cases\n", cases);
}

void encoding() {
    for (bool notify : {false, true}) {
        Fixture f(false, notify);
        for (unsigned i = 0; i < 160; ++i)
            require(f.run({"ZADD", "geo", std::to_string(i), "m" + std::to_string(i)}) == ":1\r\n",
                    "seed expanded zset");
        for (unsigned i = 2; i < 160; ++i)
            require(f.run({"ZREM", "geo", "m" + std::to_string(i)}) == ":1\r\n", "shrink zset");
        require(f.run({"OBJECT", "ENCODING", "geo"}) == bulk("skiplist"), "expanded witness");
        require(f.run({"GEOADD", "geo", "13", "38", "m0"}) == ":0\r\n", "update member");
        require(f.run({"OBJECT", "ENCODING", "geo"}) == bulk("skiplist"), "CD13 GEOADD demoted encoding");
        require(f.run({"GEORADIUS", "geo", "13", "38", "40000", "km", "STORE", "geo"}) == ":2\r\n",
                "self STORE");
        require(f.run({"OBJECT", "ENCODING", "geo"}) == bulk("listpack"), "STORE must allow compaction");
    }
    std::puts("CD13: GEOADD retains skiplist; STORE can compact; notify off/on");
}

void metadata() {
    for (bool notify : {false, true}) for (uint8_t meta : {5, 12, 31}) {
        Fixture f(false, notify);
        f.shard.configure_maxmemory(true, 1ULL << 28, MaxmemoryPolicy::AllKeysLfu, 5);
        require(f.run({"GEOADD", "geo", "13", "38", "m"}) == ":1\r\n", "seed LFU object");
        f.object("geo")->set_eviction_meta(meta);
        // Suppress access increments to witness exact bit preservation, independently of LFU RNG.
        f.shard.store().set_no_touch(true);
        require(f.run({"GEOADD", "geo", "13.01", "38.01", "m"}) == ":0\r\n", "update LFU object");
        require(f.object("geo")->eviction_meta() == meta, "CD13 GEOADD reset eviction metadata");
        for (const char* mode : {"STORE", "STOREDIST"}) {
            require(f.run({"GEORADIUS", "geo", "13", "38", "40000", "km", mode, "geo"}) == ":1\r\n",
                    "replace LFU object");
            require(f.object("geo")->eviction_meta() == meta, "CD13 STORE reset eviction metadata");
        }
    }
    std::puts("CD13: exact metadata 5/12/31 retained by GEOADD/STORE/STOREDIST; notify off/on");
}

// Hex transcripts for the review report. These call handlers directly, never a listener.
void wire_examples() {
    for (bool resp3 : {false, true}) for (bool distances : {false, true}) {
        Fixture f(resp3);
        auto record = [&](std::vector<std::string> args) {
            std::string command;
            for (const auto& arg : args) command += (command.empty() ? "" : " ") + arg;
            std::printf("RESP%d %s -> %s\n", resp3 ? 3 : 2, command.c_str(),
                        hex(f.run(args)).c_str());
        };
        record({"GEOADD", "coordinate", "-160.5371430516242981", "32.99910767291845559", "m"});
        record({"GEOPOS", "coordinate", "m"});
        record({"GEOADD", "geo", "13", "38", "a", "13.01", "38.01", "b"});
        record({"GEORADIUSBYMEMBER", "geo", "a", "10", "km",
                distances ? "STORE" : "STOREDIST", "first",
                distances ? "STOREDIST" : "STORE", "last"});
        for (const char* key : {"first", "last"}) {
            record({"EXISTS", key});
            record({"TYPE", key});
            record({"ZRANGE", key, "0", "-1", "WITHSCORES"});
        }
    }
}

void scan() {
    for (bool resp3 : {false, true}) for (bool notify : {false, true}) {
        Fixture f(resp3, notify);
        std::set<std::string> expected, seen;
        for (unsigned i = 0; i < 192; ++i) {
            const std::string member = "steady:" + std::to_string(i);
            expected.insert(member);
            require(f.run({"SADD", "set", member}) == ":1\r\n", "seed scan population");
        }
        require(CollectionRef(f.object("set")).encoding() == CollectionEncoding::Hashtable,
                "SSCAN must use expanded table");
        auto& table = CollectionRef(f.object("set")).external_as<SetVal>()->table;
        std::string cursor = "0";
        unsigned sequence = 0, rehashes = 0, pages = 0;
        bool ended = false;
        // Once occupied slots reach 70%, single fresh insert/delete pairs force a tombstone
        // rehash. Witness the actual generation change before EVERY continuation, or fail.
        for (; pages < 1024; ++pages) {
            const auto reply = parse(f.run({"SSCAN", "set", cursor, "COUNT", "7", "MATCH", "steady:*"}));
            require(reply.type == '*' && reply.children.size() == 2 &&
                    reply.children[0].type == '$' && reply.children[1].type == '*', "SSCAN frame");
            cursor = reply.children[0].text;
            for (const auto& value : reply.children[1].children) {
                require(value.type == '$', "SSCAN member frame");
                seen.insert(value.text);
            }
            if (cursor == "0") { ended = true; break; }
            const uint32_t old_generation = table.generation();
            for (unsigned attempt = 0; attempt < 4096 && table.generation() == old_generation; ++attempt) {
                const std::string member = "temporary:" + std::to_string(sequence++);
                require(f.run({"SADD", "set", member}) == ":1\r\n", "fresh churn insertion");
                require(f.run({"SREM", "set", member}) == ":1\r\n", "fresh churn deletion");
            }
            require(table.generation() != old_generation, "churn never rehashed (vacuous witness)");
            ++rehashes;
        }
        require(ended, "CD6 SSCAN did not terminate with rehash between every call");
        require(pages > 1 && rehashes == pages, "scan did not paginate and rehash");
        require(seen == expected, "CD6 scan missed a permanent member");
        std::printf("CD6: RESP%d notify=%d %u pages, %u witnessed rehashes, 192 members covered\n",
                    resp3 ? 3 : 2, notify, pages + 1, rehashes);
    }
}

void scan_growth() {
    // Deliberately collide at the final home bucket, so physical probes wrap across slot zero.
    // Then resize between pages. Reversing a physical-slot cursor (without HOME filtering) must
    // fail this coverage witness even though it terminates and survives the generation churn.
    for (unsigned seed = 0; seed < 8; ++seed) {
        Fixture f;
        std::set<std::string> expected, seen;
        for (unsigned candidate = 0; expected.size() < 16; ++candidate) {
            const std::string member = "steady:" + std::to_string(seed) + ":wrap:" + std::to_string(candidate);
            const Slice slice(member.data(), member.size());
            if ((mix64(FlatStore::hash_key(slice)) & 511) != 511) continue;
            expected.insert(member);
            require(f.run({"SADD", "set", member}) == ":1\r\n", "seed wrapping home cluster");
        }
        for (unsigned i = 0; i < 176; ++i) {
            const std::string member = "steady:" + std::to_string(seed) + ":" + std::to_string(i);
            expected.insert(member);
            require(f.run({"SADD", "set", member}) == ":1\r\n", "seed growth population");
        }
        auto& table = CollectionRef(f.object("set")).external_as<SetVal>()->table;
        require(table.slot_count() == 512, "initial collision mask must match table");
        std::vector<std::string> transient;
        std::string cursor = "0";
        unsigned growths = 0;
        bool ended = false;
        for (unsigned page = 0; page < 8192; ++page) {
            const unsigned add = page == 2 ? 256 : page == 8 ? 768 : page == 21 ? 2048 : 0;
            if (add) {
                const uint32_t before = table.slot_count();
                for (unsigned i = 0; i < add; ++i) {
                    transient.push_back("temporary:" + std::to_string(page) + ":" + std::to_string(i));
                    require(f.run({"SADD", "set", transient.back()}) == ":1\r\n", "growth insertion");
                }
                require(table.slot_count() > before, "growth window never opened");
                ++growths;
            }
            if (page == 5 || page == 13 || page == 34) {
                for (const auto& member : transient)
                    require(f.run({"SREM", "set", member}) == ":1\r\n", "growth cleanup");
                transient.clear();
            }
            const auto reply = parse(f.run({"SSCAN", "set", cursor, "COUNT", "1", "MATCH", "steady:*"}));
            cursor = reply.children.at(0).text;
            for (const auto& member : reply.children.at(1).children) seen.insert(member.text);
            if (cursor == "0") { ended = true; break; }
        }
        require(growths == 3, "all three growth windows must open");
        require(ended, "growth scan never terminated");
        require(seen == expected, "CD6 HOME scan lost permanent members during growth/wraparound");
    }
    std::puts("CD6: 8 growth/wraparound cases, three witnessed capacity increases per scan");
}
}  // namespace

int main(int argc, char** argv) {
    require(command_registry_init(false), "command registry initialization");
    if (argc == 2 && std::string(argv[1]) == "wire") { wire_examples(); return 0; }
    unsigned failed = 0, tested = 0;
    const struct { const char* name; void (*run)(); } cases[] = {
        {"scan", scan}, {"scan-growth", scan_growth}, {"coordinates", coordinates}, {"stores", stores},
        {"encoding", encoding}, {"metadata", metadata},
    };
    for (const auto& item : cases) {
        if (argc > 1 && std::string(argv[1]) != item.name) continue;
        ++tested;
        try { item.run(); std::printf("PASS %s\n", item.name); }
        catch (const std::exception& e) { ++failed; std::printf("FAIL %s: %s\n", item.name, e.what()); }
    }
    require(tested > 0, "unknown test case");
    return failed ? 1 : 0;
}
