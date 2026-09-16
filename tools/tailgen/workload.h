#pragma once

#include "pacing.h"

#include <algorithm>
#include <charconv>
#include <cctype>
#include <limits>
#include <string>
#include <string_view>
#include <vector>

namespace tailgen {

inline std::string_view trim(std::string_view value) {
    while (!value.empty() && std::isspace(static_cast<unsigned char>(value.front()))) value.remove_prefix(1);
    while (!value.empty() && std::isspace(static_cast<unsigned char>(value.back()))) value.remove_suffix(1);
    return value;
}
inline uint64_t unsigned_number(std::string_view text) {
    uint64_t value = 0;
    const auto parsed = std::from_chars(text.data(), text.data() + text.size(), value);
    if (text.empty() || parsed.ec != std::errc{} || parsed.ptr != text.data() + text.size())
        throw std::invalid_argument("invalid unsigned integer: " + std::string(text));
    return value;
}

struct KeySpace {
    std::string prefix, suffix;
    uint64_t first = 1, count = 1;

    static KeySpace parse(std::string_view text, std::string_view default_prefix) {
        const size_t open = text.find('{');
        if (open == std::string_view::npos) {
            const uint64_t count = unsigned_number(text);
            if (!count) throw std::invalid_argument("key count must be positive");
            return {std::string(default_prefix), "", 1, count};
        }
        const size_t dots = text.find("..", open + 1), close = text.find('}', open + 1);
        if (dots == std::string_view::npos || close == std::string_view::npos || dots >= close ||
            text.find('{', open + 1) != std::string_view::npos ||
            text.find('}', close + 1) != std::string_view::npos)
            throw std::invalid_argument("key pattern must contain one {first..last} range");
        const uint64_t first = unsigned_number(text.substr(open + 1, dots - open - 1));
        const uint64_t last = unsigned_number(text.substr(dots + 2, close - dots - 2));
        if (last < first || last - first == std::numeric_limits<uint64_t>::max())
            throw std::invalid_argument("invalid key range");
        return {std::string(text.substr(0, open)), std::string(text.substr(close + 1)), first, last - first + 1};
    }
    void append_bulk(std::string& out, Random& rng) const {
        char digits[32];
        const auto end = std::to_chars(digits, digits + sizeof digits, first + rng.bounded(count)).ptr;
        out += '$';
        out += std::to_string(prefix.size() + static_cast<size_t>(end - digits) + suffix.size());
        out += "\r\n";
        out += prefix;
        out.append(digits, end);
        out += suffix;
        out += "\r\n";
    }
};

enum class CommandClass { short_op, long_op };
struct Command {
    uint64_t through = 0;
    CommandClass kind = CommandClass::short_op;
    bool has_key = true;
    std::string prefix, suffix;
};

class Workload {
public:
    Workload(std::string_view mix, KeySpace short_keys, KeySpace long_keys)
        : short_(std::move(short_keys)), long_(std::move(long_keys)) {
        while (!mix.empty()) {
            const size_t comma = mix.find(',');
            const std::string_view entry = trim(mix.substr(0, comma));
            const size_t colon = entry.rfind(':');
            if (colon == std::string_view::npos) throw std::invalid_argument("mix needs COMMAND:weight entries");
            const uint64_t weight = unsigned_number(trim(entry.substr(colon + 1)));
            std::string name(trim(entry.substr(0, colon)));
            for (char& c : name) c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
            Command command;
            if (name == "GET") command.prefix = "*2\r\n$3\r\nGET\r\n";
            else if (name == "BITCOUNT") {
                command.prefix = "*2\r\n$8\r\nBITCOUNT\r\n";
                command.kind = CommandClass::long_op;
            } else if (name == "PING") {
                command.prefix = "*1\r\n$4\r\nPING\r\n";
                command.has_key = false;
            } else if (name.starts_with("SET ")) {
                const uint64_t bytes = unsigned_number(trim(std::string_view(name).substr(4)));
                if (bytes > 512 * 1024 * 1024) throw std::invalid_argument("SET payload exceeds 512 MiB");
                command.prefix = "*3\r\n$3\r\nSET\r\n";
                if (weight) command.suffix = "$" + std::to_string(bytes) + "\r\n" + std::string(bytes, 'x') + "\r\n";
            } else throw std::invalid_argument("supported mix commands: GET, SET <bytes>, BITCOUNT, PING");
            if (weight > std::numeric_limits<uint64_t>::max() - weight_)
                throw std::invalid_argument("mix weight sum overflow");
            if (weight) {
                weight_ += weight;
                command.through = weight_;
                commands_.push_back(std::move(command));
            }
            if (comma == std::string_view::npos) break;
            mix.remove_prefix(comma + 1);
            if (mix.empty()) throw std::invalid_argument("empty mix entry");
        }
        if (!weight_) throw std::invalid_argument("mix needs a positive weight");
    }

    CommandClass render(Random& rng, std::string& out) const {
        const uint64_t choice = rng.bounded(weight_);
        const Command* command = &commands_.front();
        for (const auto& c : commands_) if (choice < c.through) { command = &c; break; }
        out.assign(command->prefix);
        if (command->has_key)
            (command->kind == CommandClass::short_op ? short_ : long_).append_bulk(out, rng);
        out += command->suffix;
        return command->kind;
    }

private:
    KeySpace short_, long_;
    std::vector<Command> commands_;
    uint64_t weight_ = 0;
};

} // namespace tailgen
