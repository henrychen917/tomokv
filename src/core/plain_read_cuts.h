#pragma once
#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <vector>

namespace tomo {

// IO-private references. Empty construction allocates nothing; only live cuts occupy slots.
// The low word identifies an Op's reference. Across a full low-word wrap, equal low words
// share the oldest cut conservatively until their LAST reference retires.
class PlainReadCuts {
    struct Entry {
        uint64_t cut;
        uint64_t refs;
    };
    std::vector<Entry> cuts_;

public:
    uint64_t floor() const { return cuts_.empty() ? UINT64_MAX : cuts_.front().cut + 1; }
    bool reuse(uint64_t cut) {
        if (cuts_.empty() || cuts_.back().cut != cut) return false;
        ++cuts_.back().refs;
        return true;
    }
    // Reserve before publishing a provisional floor: confirmation must not allocate.
    void reserve_one() {
        if (cuts_.size() == cuts_.capacity())
            cuts_.reserve(std::max<size_t>(8, cuts_.size() * 2));
    }
    void add(uint64_t cut) {
        if (reuse(cut)) return;
        if (!cuts_.empty() && cut - cuts_.front().cut >= (uint64_t{1} << 32)) {
            for (auto& entry : cuts_)
                if (static_cast<uint32_t>(entry.cut) == static_cast<uint32_t>(cut)) {
                    ++entry.refs;
                    return;
                }
        }
        if (!cuts_.empty() && cut < cuts_.back().cut) std::abort();
        cuts_.push_back({cut, 1});
    }
    void release(uint32_t low) {
        if (cuts_.empty()) std::abort();
        const uint64_t last = cuts_.back().cut;
        uint64_t cut = (last & ~uint64_t{UINT32_MAX}) | low;
        if (cut > last) cut -= uint64_t{1} << 32;
        auto it = std::lower_bound(cuts_.begin(), cuts_.end(), cut,
                                  [](const Entry& entry, uint64_t value) {
                                      return entry.cut < value;
                                  });
        if (it == cuts_.end() || it->cut != cut) {
            // A conservatively shared reference can name an earlier congruent epoch.
            it = std::find_if(cuts_.begin(), cuts_.end(), [low](const Entry& entry) {
                return static_cast<uint32_t>(entry.cut) == low;
            });
        }
        if (it == cuts_.end() || !it->refs) std::abort();
        if (--it->refs == 0) cuts_.erase(it);
    }
};

}  // namespace tomo
