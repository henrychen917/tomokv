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

struct WeightedLbMoveChoice {
    uint32_t item_index = UINT32_MAX;
    uint32_t source = UINT32_MAX;
    uint32_t destination = UINT32_MAX;
    double before_weight_spread = 0;
    double after_weight_spread = 0;
    double before_secondary_spread = 0;
    double after_secondary_spread = 0;
};

// The incremental face of the same placement policy. Pinned items contribute load but cannot be
// selected (the controller uses that for cooldown and already-selected candidates). A demand move
// must strictly improve demand spread. A secondary-only move must not worsen demand and must
// strictly improve the independent secondary spread. Count spread and stable ids break exact ties.
inline bool weighted_lb_best_incremental_move(const std::vector<WeightedLbItem>& items,
                                              const std::vector<uint32_t>& targets,
                                              bool demand_hot, bool secondary_hot,
                                              WeightedLbMoveChoice& choice) {
    choice = {};
    if (targets.size() < 2 || (!demand_hot && !secondary_hot)) return false;
    std::vector<double> load(targets.size(), 0);
    std::vector<double> secondary_load(targets.size(), 0);
    std::vector<uint32_t> count(targets.size(), 0);
    auto target_index = [&](uint32_t tid) {
        for (uint32_t i = 0; i < targets.size(); i++) if (targets[i] == tid) return i;
        return UINT32_MAX;
    };
    for (const WeightedLbItem& item : items) {
        const uint32_t owner = target_index(item.owner);
        if (owner == UINT32_MAX) return false;
        load[owner] += std::max(0.0, item.weight);
        secondary_load[owner] += std::max(0.0, item.secondary);
        count[owner]++;
    }
    auto spread = [](const auto& values) {
        const auto [lo, hi] = std::minmax_element(values.begin(), values.end());
        return values.empty() ? 0.0 : static_cast<double>(*hi - *lo);
    };
    const double old_weight = spread(load);
    const double old_secondary = spread(secondary_load);
    choice.before_weight_spread = old_weight;
    choice.before_secondary_spread = old_secondary;
    double best_weight = old_weight, best_secondary = old_secondary;
    uint32_t best_count = UINT32_MAX;
    for (uint32_t item_index = 0; item_index < items.size(); item_index++) {
        const WeightedLbItem& item = items[item_index];
        if (item.pinned) continue;
        const uint32_t source = target_index(item.owner);
        for (uint32_t destination = 0; destination < targets.size(); destination++) {
            if (destination == source) continue;
            load[source] -= std::max(0.0, item.weight);
            load[destination] += std::max(0.0, item.weight);
            secondary_load[source] -= std::max(0.0, item.secondary);
            secondary_load[destination] += std::max(0.0, item.secondary);
            count[source]--;
            count[destination]++;
            const double next_weight = spread(load);
            const double next_secondary = spread(secondary_load);
            const auto [count_lo, count_hi] = std::minmax_element(count.begin(), count.end());
            const uint32_t next_count = *count_hi - *count_lo;
            count[destination]--;
            count[source]++;
            secondary_load[destination] -= std::max(0.0, item.secondary);
            secondary_load[source] += std::max(0.0, item.secondary);
            load[destination] -= std::max(0.0, item.weight);
            load[source] += std::max(0.0, item.weight);

            const bool improves = demand_hot
                ? next_weight + 1e-9 < old_weight
                : next_weight <= old_weight + 1e-9 &&
                  next_secondary + 1e-9 < old_secondary;
            if (!improves) continue;
            if (choice.item_index == UINT32_MAX || next_weight < best_weight ||
                (next_weight == best_weight && next_secondary < best_secondary) ||
                (next_weight == best_weight && next_secondary == best_secondary &&
                 next_count < best_count) ||
                (next_weight == best_weight && next_secondary == best_secondary &&
                 next_count == best_count && item.id < items[choice.item_index].id) ||
                (next_weight == best_weight && next_secondary == best_secondary &&
                 next_count == best_count && item.id == items[choice.item_index].id &&
                 targets[destination] < choice.destination)) {
                choice.item_index = item_index;
                choice.source = item.owner;
                choice.destination = targets[destination];
                choice.after_weight_spread = next_weight;
                choice.after_secondary_spread = next_secondary;
                best_weight = next_weight;
                best_secondary = next_secondary;
                best_count = next_count;
            }
        }
    }
    return choice.item_index != UINT32_MAX;
}

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
