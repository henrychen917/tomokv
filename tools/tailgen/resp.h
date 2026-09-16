#pragma once

#include <algorithm>
#include <array>
#include <charconv>
#include <cstdint>
#include <stdexcept>
#include <string_view>

namespace tailgen {

// Incremental RESP2 scalar parser. Bulk payloads are skipped without buffering;
// every byte of their framing is checked. A callback marks EACH complete reply,
// including when several replies share one read. Arrays/pushes are unexpected
// for the supported command set and fail the run instead of losing FIFO order.
class RespParser {
public:
    bool at_boundary() const { return state_ == State::type; }

    template <class Reply>
    void feed(std::string_view input, Reply&& reply) {
        size_t i = 0;
        while (i < input.size()) {
            if (state_ == State::bulk) {
                const size_t n = static_cast<size_t>(std::min<uint64_t>(remaining_, input.size() - i));
                remaining_ -= n;
                i += n;
                if (!remaining_) state_ = State::bulk_cr;
                continue;
            }
            const char c = input[i++];
            switch (state_) {
            case State::type:
                if (c != '+' && c != '-' && c != ':' && c != '$') bad();
                type_ = c;
                used_ = 0;
                state_ = State::line;
                break;
            case State::line:
                if (c == '\n') bad();
                if (c == '\r') { state_ = State::line_lf; break; }
                if (used_ < line_.size()) line_[used_++] = c;
                else if (type_ == ':' || type_ == '$') bad();
                break;
            case State::line_lf: {
                if (c != '\n') bad();
                if (type_ == '$' || type_ == ':') {
                    std::string_view number(line_.data(), used_);
                    if (number.starts_with('+')) {
                        number.remove_prefix(1);
                        if (number.starts_with('-')) bad();
                    }
                    int64_t value = 0;
                    const auto parsed = std::from_chars(number.data(), number.data() + number.size(), value);
                    if (number.empty() || parsed.ec != std::errc{} || parsed.ptr != number.data() + number.size()) bad();
                    if (type_ == '$') {
                        if (value < -1) bad();
                        if (value >= 0) {
                            remaining_ = static_cast<uint64_t>(value);
                            state_ = remaining_ ? State::bulk : State::bulk_cr;
                            break;
                        }
                    }
                }
                state_ = State::type;
                reply(type_ == '-', std::string_view(line_.data(), used_));
                break;
            }
            case State::bulk_cr:
                if (c != '\r') bad();
                state_ = State::bulk_lf;
                break;
            case State::bulk_lf:
                if (c != '\n') bad();
                state_ = State::type;
                reply(false, std::string_view{});
                break;
            case State::bulk: break;
            }
        }
    }

private:
    [[noreturn]] static void bad() { throw std::runtime_error("malformed or unsupported RESP reply"); }
    enum class State { type, line, line_lf, bulk, bulk_cr, bulk_lf };
    State state_ = State::type;
    char type_ = 0;
    std::array<char, 160> line_{}; // bounded numeric header / error preview only
    size_t used_ = 0;
    uint64_t remaining_ = 0;
};

} // namespace tailgen
