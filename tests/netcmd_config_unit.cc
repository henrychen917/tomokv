#include "netcmd_unit.h"
#include "src/cmd/server_tail.cc"
#include <filesystem>
#include <thread>
#include <barrier>
#include <sys/stat.h>

namespace {
std::atomic<bool> rewrite_arm{false};
std::atomic<unsigned> rewrite_opens{0};
std::barrier rewrite_opened(2);
ino_t rewrite_inodes[2]{};
void observe_open(int fd) {
    if (!rewrite_arm.load()) return;
    const auto index = rewrite_opens.fetch_add(1);
    check(index < 2, "exactly two rewrite opens");
    struct stat info{}; check(::fstat(fd, &info) == 0, "rewrite inode identified");
    rewrite_inodes[index] = info.st_ino;
    rewrite_opened.arrive_and_wait(); // both files are open before either writer may write/rename
}

void knob_matrix() {
    tomo::Server* server = tomo::command_server();
    tomo::Shard& shard = server->shard(0);
    auto get = [&](const char* name, const char* value) {
        const std::string expected = "*2\r\n$" + std::to_string(std::strlen(name)) + "\r\n" +
            name + "\r\n$" + std::to_string(std::strlen(value)) + "\r\n" + value + "\r\n";
        check(execute(shard, {"CONFIG", "GET", name}) == expected, "knob matrix GET round trip");
    };
    auto set = [&](std::initializer_list<const char*> values, bool accepted) {
        tomo::Op op; args(op, values);
        check(tomo::command_validate_config_set(op) == accepted, "knob matrix SET validation");
        if (accepted) {
            op.spec->handler(shard, op);
            // Successful owner fragments are folded into one OK by the real scatter path.
            check(op.reply.size() == 0, "knob matrix owner fragment applied without error");
        } else {
            check(op.reply.size() && op.reply.data()[0] == '-', "rejected SET has an error reply");
        }
    };
    // These bindings are boot-latched in the lane. Their startup SET/GET round trip must
    // expose actual non-default values; live SET must fail and leave the value intact.
    for (const auto& [name, value] : {
             std::pair{"hll-sparse-max-bytes", "1024"}, {"aof-load-truncated", "no"},
             {"unixsocketperm", "600"}, {"port", "6397"}, {"bind", "127.0.0.2"},
             {"unixsocket", "build/unused-knob-matrix.sock"}}) {
        get(name, value);
        set({"CONFIG", "SET", name, value}, false);
        get(name, value);
    }
    const struct {
        const char* name; const char* alias; const char* tomo_alias;
        const char* input; const char* output;
    } rows[] = {
        {"hash-max-listpack-entries", "hash-max-ziplist-entries", "hash-max-compact-entries", "5", "5"},
        {"hash-max-listpack-value", "hash-max-ziplist-value", "hash-max-compact-value", "1kb", "1024"},
        {"list-max-listpack-size", "list-max-ziplist-size", nullptr, "-3", "-3"},
        {"set-max-listpack-entries", nullptr, nullptr, "6", "6"},
        {"set-max-listpack-value", nullptr, nullptr, "20", "20"},
        {"zset-max-listpack-entries", "zset-max-ziplist-entries", "zset-max-compact-entries", "8", "8"},
        {"zset-max-listpack-value", "zset-max-ziplist-value", "zset-max-compact-value", "2k", "2000"},
    };
    for (const auto& row : rows) {
        for (const char* spelling : {row.name, row.alias, row.tomo_alias}) {
            if (!spelling) continue;
            const bool legacy = spelling == row.tomo_alias;
            set({"CONFIG", "SET", spelling, legacy ? "007" : row.input}, true);
            for (const char* name : {row.name, row.alias, row.tomo_alias})
                if (name) get(name, legacy ? "7" : row.output);
        }
    }
    const auto& limits = shard.type_limits();
    check(limits.hash.max_entries == 7 && limits.hash.max_value == 7 &&
          limits.zset.max_entries == 7 && limits.zset.max_value == 7 &&
          limits.list.max_entries == UINT32_MAX && limits.list.max_value == 16384 &&
          limits.set.max_entries == 6 && limits.set.max_value == 20,
          "knob matrix SET changes the owner's actual limits, not just GET");
    for (const auto& row : rows) {
        if (row.alias) {
            set({"CONFIG", "SET", row.name, "8", row.alias, "9"}, true);
            get(row.name, "9"); get(row.alias, "9");
            set({"CONFIG", "SET", row.name, "10", row.alias, "bad"}, false);
            get(row.name, "9"); get(row.alias, "9");
        }
        const std::string before = execute(shard, {"CONFIG", "GET", row.name});
        const auto owner_before = shard.type_limits();
        set({"CONFIG", "SET", row.name, "11", row.name, "12"}, false);
        check(execute(shard, {"CONFIG", "GET", row.name}) == before &&
              !std::memcmp(&owner_before, &shard.type_limits(), sizeof(owner_before)),
              "duplicate SET leaves both published and owner values unchanged");
    }
    set({"CONFIG", "SET", "hash-max-listpack-entries", "9223372036854775807",
         "zset-max-listpack-value", "4294967296"}, true);
    get("hash-max-ziplist-entries", "9223372036854775807");
    get("zset-max-compact-value", "4294967296");
    check(shard.type_limits().hash.max_entries == UINT32_MAX &&
          shard.type_limits().zset.max_value == UINT32_MAX, "full Redis range saturates owner limits");
    for (const char* name : {"hash-max-listpack-entries", "hash-max-listpack-value"}) {
        const std::string before = execute(shard, {"CONFIG", "GET", name});
        tomo::Op op; args(op, {"CONFIG", "SET", name});
        check(op.push_arg(tomo::Slice("1\0x", 3)), "malformed bulk fixture argument");
        check(!tomo::command_validate_config_set(op), "embedded NUL rejected by shared parser");
        check(execute(shard, {"CONFIG", "GET", name}) == before, "malformed bulk leaves GET intact");
    }
}
}
extern "C" int __real_mkstemp(char*);
extern "C" FILE* __real_fopen(const char*, const char*);
extern "C" int __wrap_mkstemp(char* path) {
    const int fd = __real_mkstemp(path);
    if (fd >= 0 && std::strstr(path, ".rewrite.")) observe_open(fd);
    return fd;
}
extern "C" FILE* __wrap_fopen(const char* path, const char* mode) {
    FILE* file = __real_fopen(path, mode);
    if (file && std::strstr(path, ".rewrite.")) observe_open(::fileno(file));
    return file;
}

void test_config_bounds(const char* only) {
    tomo::Server server;
    tomo::command_bind_server(&server);
    // Keep the real CONFIG registry, without live worker publication or server startup.
    tomo::command_bind_server(nullptr);
    tomo::Shard shard;
    shard.init_private(nullptr, 0, tomo::TypeLimits{}, tomo::StreamLimits{});
    for (const char* name : {"latency-monitor-threshold", "stream-node-max-entries",
                             "stream-node-max-bytes"}) {
        if (only && std::strcmp(only, name)) continue;
        // CONFIG owner fragments leave successful OK assembly to the scatter coordinator.
        check(execute(shard, {"CONFIG", "SET", name, "17"}) .empty(),
              "valid uint32 config accepted");
        const auto before = execute(shard, {"CONFIG", "GET", name});
        for (const char* value : {"4294967296", "4294967297", "9223372036854775807", "-1"}) {
            const std::string expected = std::string("-ERR CONFIG SET failed (possibly related to argument '") +
                name + "') - argument must be between 0 and 4294967295 inclusive\r\n";
            check(execute(shard, {"CONFIG", "SET", "zc-min", "23", name, value}) == expected,
                  "out-of-range config rejected with exact bounds and Redis error grammar");
            check(execute(shard, {"CONFIG", "GET", name}) == before,
                  "rejected uint32 config leaves reported value intact");
            check(shard.zc_min() == UINT32_MAX, "failed CONFIG SET publishes no preceding pair");
            check(shard.stream_limits().node_max_entries != 0 &&
                  shard.stream_limits().node_max_bytes != 0,
                  "rejected stream limits did not silently disable a rollover axis");
        }
        for (const char* value : {"0", "4294967295"})
            check(execute(shard, {"CONFIG", "SET", name, value}) .empty(),
                  "both supported config endpoints accepted");
        check(execute(shard, {"CONFIG", "SET", name, "17"}) .empty(), "restore config");
    }
    check(execute(shard, {"CONFIG", "SET", "stream-node-max-bytes", "4kb"}) .empty() &&
          shard.stream_limits().node_max_bytes == 4096, "stream byte limit accepts Redis memory grammar");
}

void test_config_rewrite() {
    knob_matrix();
    check(tomo::config_quote("77") == "77", "simple scalar keeps its original spelling");
    const std::string value = "pass with spaces\n\r\t\"'\\tail";
    std::vector<std::string> words;
    check(tomo::cfg_split_args(tomo::config_quote(value).c_str(), words), "quoted config parses");
    check(words.size() == 1 && words[0] == value, "config string round trip");
    // The harness binds a server whose config path is initialized below by its friend fixture.
    const char* path = tomo::command_server()->cfg().conf_path;
    std::FILE* original = std::fopen(path, "w"); check(original, "create original config");
    std::fputs("user reader on nopass ~* +get\nload \"/tmp/recovery source.tomo\"\nrequirepass old\n"
               "hash-max-ziplist-entries 3\nhash-max-ziplist-value 9\nlist-max-ziplist-size -1\n"
               "zset-max-ziplist-entries 3\nzset-max-ziplist-value 9\n"
               "hash-max-compact-entries 4\nhash-max-compact-value 10\n"
               "zset-max-compact-entries 4\nzset-max-compact-value 10\n", original);
    std::fclose(original);
    std::string error;
    check(tomo::config_rewrite(error), "first rewrite");
    std::ifstream in(path); std::string body((std::istreambuf_iterator<char>(in)), {});
    check(body.find("user reader on nopass ~* +get\n") != std::string::npos, "inline ACL survived rewrite");
    check(body.find("load \"/tmp/recovery source.tomo\"\n") != std::string::npos, "recovery source survived rewrite");
    check(body.find("max-ziplist-") == std::string::npos, "stale encoding aliases were replaced");
    check(body.find("max-compact-") == std::string::npos, "stale TomoKV aliases were replaced");
    for (const char* name : {"hash-max-listpack-entries", "hash-max-listpack-value", "list-max-listpack-size",
                             "zset-max-listpack-entries", "zset-max-listpack-value"})
        check(body.find(std::string(name) + " ") != std::string::npos, "canonical encoding directive emitted");
    for (const char* directive : {"hll-sparse-max-bytes 1024\n", "aof-load-truncated no\n",
                                  "unixsocketperm 600\n", "port 6397\n", "bind 127.0.0.2\n",
                                  "unixsocket build/unused-knob-matrix.sock\n"})
        check(body.find(directive) != std::string::npos, "boot binding survived rewrite with actual value");
    std::vector<std::string> loaded;
    check(tomo::load_conf_file(path, loaded), "rewritten config loads");
    auto password = std::find(loaded.begin(), loaded.end(), "--requirepass");
    check(password != loaded.end() && ++password != loaded.end() && *password == value, "password preserved as one token");
    rewrite_arm.store(true);
    bool success[2]{};
    std::thread a([&] { std::string err; success[0] = tomo::config_rewrite(err); });
    std::thread b([&] { std::string err; success[1] = tomo::config_rewrite(err); });
    a.join(); b.join(); rewrite_arm.store(false);
    check(rewrite_opens.load() == 2, "two rewrite opens overlapped before either rename");
    check(rewrite_inodes[0] != rewrite_inodes[1], "concurrent writers own distinct temporary inodes");
    check(success[0] && success[1], "both concurrent rewrites completed");
    std::ifstream after(path); std::string final((std::istreambuf_iterator<char>(after)), {});
    check(final == body, "concurrent rewrites preserve exact complete bytes");
}
