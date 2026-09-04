// aof_stream_owner.h -- typed ownership of the physical AOF stream.
#pragma once

#include <cstdint>
#include <variant>

namespace tomo {

// The AOF writer owns one physical byte stream. Ordinarily it holds an OpenToken, which is the
// capability required to append a control frame. A large logical record exchanges that capability
// for a LargeToken until its final frame is appended. Keeping the alternatives as different types
// makes a control append unavailable in the only state where it would be unsafe.
class AofStreamOwner {
public:
    class OpenToken final {
    public:
        OpenToken(const OpenToken&) = delete;
        OpenToken& operator=(const OpenToken&) = delete;
        OpenToken(OpenToken&&) noexcept = default;
        OpenToken& operator=(OpenToken&&) noexcept = default;
        ~OpenToken() = default;

    private:
        friend class AofStreamOwner;
        OpenToken() noexcept = default;
    };

    class LargeToken final {
    public:
        LargeToken(const LargeToken&) = delete;
        LargeToken& operator=(const LargeToken&) = delete;
        LargeToken(LargeToken&&) noexcept = default;
        LargeToken& operator=(LargeToken&&) noexcept = default;
        ~LargeToken() = default;

        uint32_t producer() const noexcept { return producer_; }
        uint64_t begin_offset() const noexcept { return begin_offset_; }

    private:
        friend class AofStreamOwner;
        LargeToken(uint32_t producer, uint64_t begin_offset) noexcept
            : producer_(producer), begin_offset_(begin_offset) {}

        uint32_t producer_;
        uint64_t begin_offset_;
    };

    AofStreamOwner() noexcept : state_(OpenToken{}) {}
    AofStreamOwner(const AofStreamOwner&) = delete;
    AofStreamOwner& operator=(const AofStreamOwner&) = delete;

    const OpenToken* open_token() const noexcept {
        return std::get_if<OpenToken>(&state_);
    }
    const LargeToken* large_token() const noexcept {
        return std::get_if<LargeToken>(&state_);
    }

    // A transition invalidates the token reference passed to it. Callers deliberately perform no
    // more work through that reference after exchanging capabilities.
    void begin_large(const OpenToken&, uint32_t producer, uint64_t begin_offset) noexcept {
        state_ = LargeToken{producer, begin_offset};
    }
    void finish_large(const LargeToken&) noexcept {
        state_ = OpenToken{};
    }

private:
    std::variant<OpenToken, LargeToken> state_;
};

}  // namespace tomo
