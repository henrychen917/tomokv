// t_sort.cc -- SORT's ordering core. The scatter engine owns BY/GET key dereference; see t_sort.h.
#include "t_sort.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <new>

#include "../base/numeric.h"

namespace tomo {
namespace {

// Local copies of two three-line helpers that live in other translation units' anonymous
// namespaces.  Duplicating the bytes is cheaper than widening two unrelated headers, and both are
// pinned by the differ suite against the reference.
int sort_binary_compare(Slice a, Slice b) {
    const uint32_t common = std::min(a.n, b.n);
    const int cmp = common ? std::memcmp(a.p, b.p, common) : 0;
    if (cmp != 0) return cmp < 0 ? -1 : 1;
    if (a.n == b.n) return 0;
    return a.n < b.n ? -1 : 1;
}

// Numeric SORT is the bare strtod again, but with sortCommand's extra ERANGE test, so "" sorts as
// zero and " 5" as five while a subnormal is refused. See src/base/numeric.h.
bool sort_number(const std::string& text, double& number) {
    return parse_double_sortable(Slice(text.data(), static_cast<uint32_t>(text.size())), number);
}

// One weighted row.  `weight_present` is the reference's NULL: a BY pattern whose key is missing,
// holds a non-string, or lacks the named hash field.
struct SortItem {
    uint32_t index = 0;          // position in the caller's `elements`, for stable ties
    double score = 0;
    std::string weight;
    bool weight_present = false;
};

}  // namespace

void sort_pattern_parse(Slice pattern, SortPattern& out) {
    out = SortPattern{};
    out.raw = pattern;
    out.self = pattern.n == 1 && pattern.p[0] == '#';
    const char* star = pattern.n ? static_cast<const char*>(
                                       std::memchr(pattern.p, '*', pattern.n))
                                 : nullptr;
    if (!star) return;
    out.has_star = true;
    out.prefix = Slice(pattern.p, static_cast<uint32_t>(star - pattern.p));
    const char* tail = star + 1;
    const uint32_t tail_len = static_cast<uint32_t>(pattern.p + pattern.n - tail);
    // "->" is a field separator only when it begins AFTER the '*' and has a non-empty tail;
    // otherwise it is ordinary key bytes.  Verified against the reference in both directions.
    const char* arrow = nullptr;
    for (uint32_t i = 0; tail_len >= 2 && i + 2 < tail_len; i++)
        if (tail[i] == '-' && tail[i + 1] == '>') { arrow = tail + i; break; }
    if (arrow) {
        out.suffix = Slice(tail, static_cast<uint32_t>(arrow - tail));
        out.field = Slice(arrow + 2, static_cast<uint32_t>(pattern.p + pattern.n - (arrow + 2)));
    } else {
        out.suffix = Slice(tail, tail_len);
    }
}

bool sort_pattern_key(const SortPattern& pattern, Slice element, std::string& key) {
    if (!pattern.has_star) return false;
    key.assign(pattern.prefix.p, pattern.prefix.n);
    key.append(element.p, element.n);
    key.append(pattern.suffix.p, pattern.suffix.n);
    return true;
}

SortStatus sort_run(const SortSpec& spec, const SortResolved* resolved,
                    std::vector<std::string>& elements,
                    std::vector<std::string>& values,
                    std::vector<uint8_t>& present) {
    values.clear();
    present.clear();
    try {
        // THE DETERMINISM RULE.  A set has no order of its own, so the reference refuses to let an
        // unordered dump become durable: BY <no-star> over a SET that is being STOREd is forced
        // back to an alphabetic sort.  (The reference applies the same rule to a SORT issued from
        // a script; SORT is not callable from scripts here, so that half has no site.)
        bool dontsort = spec.dontsort;
        bool alpha = spec.alpha;
        bool by_lookup = spec.by_given && spec.by.has_star;
        if (dontsort && spec.source_is_set && spec.store) {
            dontsort = false;
            alpha = true;
            by_lookup = false;
        }

        std::vector<SortItem> items;
        items.reserve(elements.size());
        for (uint32_t i = 0; i < elements.size(); i++) {
            SortItem item;
            item.index = i;
            if (!dontsort) {
                if (by_lookup) {
                    item.weight_present = resolved && resolved->by_values &&
                                          resolved->by_present &&
                                          i < resolved->by_values->size() &&
                                          i < resolved->by_present->size() &&
                                          (*resolved->by_present)[i];
                    if (item.weight_present) item.weight = (*resolved->by_values)[i];
                } else {
                    item.weight = elements[i];
                    item.weight_present = true;
                }
                if (!alpha) {
                    // A missing weight is zero, exactly as the reference leaves its initialised
                    // score untouched; only a PRESENT non-numeric weight is an error.
                    if (item.weight_present && !sort_number(item.weight, item.score))
                        return SortStatus::ConversionError;
                }
            }
            items.push_back(std::move(item));
        }

        if (!dontsort) {
            // Ties: the reference falls back to comparing the ELEMENTS for a numeric sort and
            // leaves alphabetic BY ties to its sort algorithm.  stable_sort makes the second case
            // reproducible (input order) instead of implementation-defined.
            auto compare = [&](const SortItem& a, const SortItem& b) {
                int cmp = 0;
                if (!alpha) {
                    if (a.score < b.score) cmp = -1;
                    else if (a.score > b.score) cmp = 1;
                    else cmp = sort_binary_compare(
                        Slice(elements[a.index].data(),
                              static_cast<uint32_t>(elements[a.index].size())),
                        Slice(elements[b.index].data(),
                              static_cast<uint32_t>(elements[b.index].size())));
                } else if (!a.weight_present || !b.weight_present) {
                    // NULL sorts before every present weight; two NULLs compare equal.
                    cmp = a.weight_present ? 1 : (b.weight_present ? -1 : 0);
                } else if (spec.store) {
                    cmp = sort_binary_compare(
                        Slice(a.weight.data(), static_cast<uint32_t>(a.weight.size())),
                        Slice(b.weight.data(), static_cast<uint32_t>(b.weight.size())));
                } else {
                    cmp = std::strcoll(a.weight.c_str(), b.weight.c_str());
                }
                return spec.descending ? cmp > 0 : cmp < 0;
            };
            std::stable_sort(items.begin(), items.end(), compare);
        } else if (spec.descending && !spec.source_is_set) {
            // With ordering suppressed the reference still honours DESC for the two types that
            // HAVE an order of their own (list insertion order, sorted-set score order) and
            // ignores it for a set.
            std::reverse(items.begin(), items.end());
        }

        const int64_t size = static_cast<int64_t>(items.size());
        const int64_t start = std::min<int64_t>(std::max<int64_t>(spec.offset, 0), size);
        const int64_t wanted = std::min<int64_t>(std::max<int64_t>(spec.count, -1), size);
        const int64_t end = wanted < 0 ? size : std::min<int64_t>(size, start + wanted);
        const size_t rows = static_cast<size_t>(std::max<int64_t>(end - start, 0));
        const size_t per_row = spec.gets.empty() ? 1 : spec.gets.size();
        values.reserve(rows * per_row);
        present.reserve(rows * per_row);
        for (int64_t i = start; i < end; i++) {
            std::string& element = elements[items[i].index];
            if (spec.gets.empty()) {
                values.push_back(std::move(element));
                present.push_back(1);
                continue;
            }
            for (size_t get = 0; get < spec.gets.size(); get++) {
                const SortPattern& pattern = spec.gets[get];
                if (pattern.self) {
                    values.push_back(element);
                    present.push_back(1);
                    continue;
                }
                std::string value;
                const size_t flat = static_cast<size_t>(items[i].index) * spec.gets.size() + get;
                const bool found = pattern.has_star && resolved && resolved->get_values &&
                                   resolved->get_present && flat < resolved->get_values->size() &&
                                   flat < resolved->get_present->size() &&
                                   (*resolved->get_present)[flat];
                if (found) value = (*resolved->get_values)[flat];
                values.push_back(std::move(value));
                present.push_back(found ? 1 : 0);
            }
        }
        return SortStatus::Ok;
    } catch (const std::bad_alloc&) {
        values.clear();
        present.clear();
        return SortStatus::Oom;
    }
}

}  // namespace tomo
