#pragma once

#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace tailgen {

struct Interval { uint64_t begin, end; };

// A worker owns these counters and intervals. The final union across workers
// measures wall time with ANY connection above the threshold, without a shared
// atomic store on the request path or averaging away a single saturated worker.
class Outstanding {
public:
    Outstanding(size_t connections, uint64_t threshold, uint64_t begin, uint64_t end)
        : counts_(connections), threshold_(threshold), begin_(begin), end_(end) {}

    void advance(uint64_t now) {
        if (!started_ && now >= begin_) {
            started_ = true;
            for (uint64_t n : counts_) maximum_ = std::max(maximum_, n);
        }
    }
    void add(size_t connection, uint64_t now) { change(connection, true, now); }
    void complete(size_t connection, uint64_t now) { change(connection, false, now); }
    uint64_t total() const { return total_; }
    uint64_t maximum() const { return maximum_; }
    const std::vector<Interval>& finish() {
        advance(end_);
        if (over_) save(opened_, end_);
        over_ = 0;
        return intervals_;
    }

private:
    void save(uint64_t a, uint64_t b) {
        a = std::max(a, begin_);
        b = std::min(b, end_);
        if (a < b) intervals_.push_back({a, b});
    }
    void change(size_t connection, bool add, uint64_t now) {
        advance(now); // capture any warmup backlog before this event changes it
        uint64_t& count = counts_.at(connection);
        const bool was_over = threshold_ && count > threshold_;
        if (add) { ++count; ++total_; }
        else {
            if (!count) throw std::logic_error("outstanding count underflow");
            --count; --total_;
        }
        if (now >= begin_ && now < end_) maximum_ = std::max(maximum_, count);
        const bool is_over = threshold_ && count > threshold_;
        if (!was_over && is_over) {
            if (!over_++) opened_ = now;
        } else if (was_over && !is_over) {
            if (!--over_) save(opened_, now);
        }
    }
    std::vector<uint64_t> counts_; // required open-loop counters even with witness disabled
    std::vector<Interval> intervals_; // threshold=0 never pushes or allocates here
    uint64_t threshold_, begin_, end_, total_ = 0, maximum_ = 0;
    uint64_t over_ = 0, opened_ = 0;
    bool started_ = false;
};

inline uint64_t union_ns(std::vector<Interval> intervals) {
    if (intervals.empty()) return 0;
    std::sort(intervals.begin(), intervals.end(), [](auto a, auto b) { return a.begin < b.begin; });
    Interval current = intervals.front();
    uint64_t total = 0;
    for (size_t i = 1; i < intervals.size(); ++i) {
        if (intervals[i].begin <= current.end) current.end = std::max(current.end, intervals[i].end);
        else { total += current.end - current.begin; current = intervals[i]; }
    }
    return total + current.end - current.begin;
}

} // namespace tailgen
