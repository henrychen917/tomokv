// Cold Redis 7.4 CONFIG SET grammar and diagnostics for network parameters.
#pragma once
#include "../core/config.h"
#include "../base/slice.h"
#include <charconv>
#include <cstring>
#include <string>

namespace tomo {
inline bool network_config_name(const char* name) {
    return !std::strcmp(name, "port") || !std::strcmp(name, "bind") ||
           !std::strcmp(name, "unixsocket") || !std::strcmp(name, "unixsocketperm") ||
           !std::strcmp(name, "tcp-backlog") || !std::strcmp(name, "tcp-keepalive") ||
           !std::strcmp(name, "maxclients") || !std::strcmp(name, "timeout") ||
           !std::strcmp(name, "proto-max-bulk-len") ||
           !std::strcmp(name, "client-query-buffer-limit") ||
           !std::strcmp(name, "client-output-buffer-limit") ||
           !std::strcmp(name, "protected-mode") || !std::strncmp(name, "tls-", 4);
}

// -1: another configuration family, 0: invalid, 1: normalized successfully.
inline int normalize_network_config(const char* name, Slice input, std::string& out,
                                    const char*& error) {
    if (!std::strcmp(name, "proto-max-bulk-len")) {
        uint64_t value;
        if (!cfg_parse_query_buffer_limit(input.p, input.n, value, error)) return 0;
        out = std::to_string(value);
        return 1;
    }
    if (!std::strcmp(name, "protected-mode")) {
        if (cfg_memory_suffix(input.p, input.n, "yes")) { out = "yes"; return 1; }
        if (cfg_memory_suffix(input.p, input.n, "no")) { out = "no"; return 1; }
        error = "argument must be 'yes' or 'no'";
        return 0;
    }
    const bool clients = !std::strcmp(name, "maxclients");
    if (!clients && std::strcmp(name, "timeout") && std::strcmp(name, "tcp-keepalive"))
        return -1;
    int64_t value = 0;
    const auto result = std::from_chars(input.p, input.p + input.n, value);
    if (result.ec != std::errc{} || result.ptr != input.p + input.n ||
        std::to_string(value) != std::string(input.p, input.n)) {
        error = "argument couldn't be parsed into an integer";
        return 0;
    }
    if (value < (clients ? 1 : 0) || uint64_t(value) > (clients ? UINT32_MAX : INT_MAX)) {
        error = clients ? "argument must be between 1 and 4294967295 inclusive" :
                          "argument must be between 0 and 2147483647 inclusive";
        return 0;
    }
    out = std::to_string(value);
    return 1;
}
} // namespace tomo
