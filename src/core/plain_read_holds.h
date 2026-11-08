#pragma once
#include <array>
#include <cstdint>
#include <cstdlib>

namespace tomo {

// IO-private generations. A connection holds at most two references; dead interior
// generations remain in the fixed ring until its oldest live generation retires.
class PlainReadHolds {
public:
    static constexpr uint32_t kSlots = 512;
    static constexpr uint64_t kMask = kSlots - 1;
    static_assert((kSlots & (kSlots - 1)) == 0 && kSlots < UINT16_MAX);

    uint64_t floor() const {
        return head_ == tail_ ? UINT64_MAX : gens_[head_ & kMask].cut + 1;
    }

    uint16_t acquire(uint64_t cut, bool& created) {
        if (head_ != tail_) {
            Gen& newest = gens_[(tail_ - 1) & kMask];
            if (cut < newest.cut) std::abort();
            if (newest.cut == cut || tail_ - head_ == kSlots) {
                ++newest.refs;
                created = false;
                return static_cast<uint16_t>((tail_ - 1) & kMask);
            }
        }
        gens_[tail_ & kMask] = Gen{cut, 1};
        created = true;
        return static_cast<uint16_t>(tail_++ & kMask);
    }

    // Only the just-created generation may advance, after publishing and confirming.
    void raise_newest(uint64_t cut) { gens_[(tail_ - 1) & kMask].cut = cut; }

    void release(uint16_t slot) {
        if (slot >= kSlots || !gens_[slot].refs) std::abort();
        if (--gens_[slot].refs) return;
        while (head_ != tail_ && gens_[head_ & kMask].refs == 0) ++head_;
    }

private:
    struct Gen {
        uint64_t cut = 0;
        uint64_t refs = 0;
    };
    std::array<Gen, kSlots> gens_{};
    uint64_t head_ = 0, tail_ = 0;
};

}  // namespace tomo
