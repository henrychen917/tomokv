// weighted_lb.h -- the one placement policy shared by FLIP and the continuous controller.
//
// Demand is primary. An optional second load vector (bytes for buckets) is compared
// lexicographically, never blended into demand. Count remains a hard invariant: every target
// finishes with floor/ceil item count, including the all-zero boot window. Items are considered
// largest-first and placed on the least loaded eligible target; current ownership and target id
// only break exact ties. This is deterministic, allocation-only code and never runs on a request
// path.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

namespace tomo {

struct WeightedLbItem {
    uint64_t id = 0;
    uint32_t owner = 0;
    double weight = 0;
    bool pinned = false;
    // A lexicographic second objective, never blended into demand. Bucket placement uses bytes;
    // client placement leaves it zero.
    double secondary = 0;
};

struct WeightedLbAssignment {
    uint64_t id = 0;
    uint32_t source = 0;
    uint32_t destination = 0;
    double weight = 0;
    double secondary = 0;
};

inline bool weighted_lb_partition(const std::vector<WeightedLbItem>& items,
                                  const std::vector<uint32_t>& targets,
                                  std::vector<WeightedLbAssignment>& out) {
    out.clear();
    if (targets.empty()) return items.empty();
    const uint32_t low = static_cast<uint32_t>(items.size() / targets.size());
    const uint32_t high = low + (items.size() % targets.size() != 0);
    std::vector<uint32_t> count(targets.size(), 0);
    std::vector<double> load(targets.size(), 0);
    std::vector<double> secondary_load(targets.size(), 0);
    std::vector<uint32_t> destination(items.size(), UINT32_MAX);
    auto target_index = [&](uint32_t tid) {
        for (uint32_t i = 0; i < targets.size(); i++) if (targets[i] == tid) return i;
        return UINT32_MAX;
    };

    for (uint32_t i = 0; i < items.size(); i++) {
        if (!items[i].pinned) continue;
        const uint32_t at = target_index(items[i].owner);
        if (at == UINT32_MAX || count[at] == high) return false;
        destination[i] = at;
        count[at]++;
        load[at] += std::max(0.0, items[i].weight);
        secondary_load[at] += std::max(0.0, items[i].secondary);
    }

    std::vector<uint32_t> order;
    order.reserve(items.size());
    for (uint32_t i = 0; i < items.size(); i++) if (!items[i].pinned) order.push_back(i);
    std::stable_sort(order.begin(), order.end(), [&](uint32_t a, uint32_t b) {
        if (items[a].weight != items[b].weight) return items[a].weight > items[b].weight;
        if (items[a].secondary != items[b].secondary)
            return items[a].secondary > items[b].secondary;
        return items[a].id < items[b].id;
    });

    for (uint32_t ordinal = 0; ordinal < order.size(); ordinal++) {
        uint32_t deficit = 0;
        for (uint32_t c : count) if (c < low) deficit += low - c;
        const uint32_t remaining = static_cast<uint32_t>(order.size() - ordinal);
        const bool must_fill_low = remaining == deficit;
        const uint32_t item = order[ordinal];
        uint32_t best = UINT32_MAX;
        for (uint32_t t = 0; t < targets.size(); t++) {
            if (count[t] >= high || (must_fill_low && count[t] >= low)) continue;
            if (best == UINT32_MAX || load[t] < load[best] ||
                (load[t] == load[best] && secondary_load[t] < secondary_load[best]) ||
                (load[t] == load[best] && secondary_load[t] == secondary_load[best] &&
                 count[t] < count[best]) ||
                (load[t] == load[best] && secondary_load[t] == secondary_load[best] &&
                 count[t] == count[best] &&
                 targets[t] == items[item].owner && targets[best] != items[item].owner) ||
                (load[t] == load[best] && secondary_load[t] == secondary_load[best] &&
                 count[t] == count[best] &&
                 (targets[t] == items[item].owner) == (targets[best] == items[item].owner) &&
                 targets[t] < targets[best])) best = t;
        }
        if (best == UINT32_MAX) return false;
        destination[item] = best;
        count[best]++;
        load[best] += std::max(0.0, items[item].weight);
        secondary_load[best] += std::max(0.0, items[item].secondary);
    }

    for (uint32_t c : count) if (c < low || c > high) return false;
    out.reserve(items.size());
    for (uint32_t i = 0; i < items.size(); i++) {
        if (destination[i] == UINT32_MAX) return false;
        out.push_back(WeightedLbAssignment{
            items[i].id, items[i].owner, targets[destination[i]],
            std::max(0.0, items[i].weight), std::max(0.0, items[i].secondary)});
    }
    return true;
}

}  // namespace tomo
