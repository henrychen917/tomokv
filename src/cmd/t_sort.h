// t_sort.h -- SORT's ordering core and its BY/GET dereference.
//
// WHY THIS FILE EXISTS SEPARATELY FROM THE SCATTER ENGINE. Every other multi-key command names its
// keys in argv, so the router can resolve every owner before the first byte is read. SORT's BY and
// GET patterns do not: `SORT mylist BY weight_*` names one key per ELEMENT of mylist, and the
// element values are not known until mylist has already been read on its owner. The scatter engine
// therefore resolves those names in a second read wave and gives this ordering core the gathered
// values. No shard/store access lives in this file.
//
// Patterns are SUBSTITUTION TEMPLATES, not globs.  The first '*' is replaced by the element and
// nothing else is special; a backslash escapes nothing.  A "->field" beginning after that '*' with
// a non-empty tail selects a hash field.
#pragma once
#include <cstdint>
#include <string>
#include <vector>
#include "../base/slice.h"

namespace tomo {

struct SortPattern {
    Slice raw;
    Slice prefix;            // bytes before the first '*'
    Slice suffix;            // bytes after it, up to "->field" when that is present
    Slice field;             // hash field, empty when the pattern names a plain string key
    bool  has_star = false;  // false => this pattern never reads a key
    bool  self = false;      // the literal "#": the element itself
};

void sort_pattern_parse(Slice pattern, SortPattern& out);
bool sort_pattern_key(const SortPattern& pattern, Slice element, std::string& key);

// A SORT that has to run the general path: BY and/or GET were given.  `dontsort` is the reference's
// rule that a BY pattern with no '*' suppresses ordering entirely.
struct SortSpec {
    bool alpha = false;
    bool descending = false;
    bool store = false;
    bool by_given = false;
    bool dontsort = false;
    bool source_is_set = false;
    bool source_is_list = false;
    int64_t offset = 0;
    int64_t count = -1;
    SortPattern by;
    std::vector<SortPattern> gets;
};

enum class SortStatus : uint8_t { Ok, ConversionError, Oom };

// Values gathered by the scatter engine, indexed in the source's natural element order. GET values
// are flattened as element-index * spec.gets.size() + GET-index. A clear presence byte is the
// reference's NULL (missing key, wrong type, or absent/lapsed hash field).
struct SortResolved {
    const std::vector<std::string>* by_values = nullptr;
    const std::vector<uint8_t>* by_present = nullptr;
    const std::vector<std::string>* get_values = nullptr;
    const std::vector<uint8_t>* get_present = nullptr;
};

// Orders `elements` (already in the source's natural order) per `spec`, applies LIMIT, then
// projects the GET patterns.  `values`/`present` are parallel: a false `present` is a RESP null,
// and an empty string when the result is being STOREd.  With no GET patterns every row is present
// and holds the element itself.
//
// `resolved` is non-null when BY/GET contains a `*`; every value in it was read by the concrete
// key's owner under the command's one snapshot/time cut. It may be null only when no lookup is
// needed.
SortStatus sort_run(const SortSpec& spec, const SortResolved* resolved,
                    std::vector<std::string>& elements,
                    std::vector<std::string>& values,
                    std::vector<uint8_t>& present);

// Exported by t_hash.cc / t_hash_ttl.cc for the hash-field form of a pattern.  Both are read-only:
// a lapsed field reads as absent rather than being reaped, because the reaping path is written for
// the key the command was routed on and would emit and erase under the wrong name.
bool hash_field_value_ro(const struct KvObj* object, Slice field, Slice& value);
bool hash_ttl_field_lapsed(const struct KvObj* object, Slice field, int64_t now_ms);

}  // namespace tomo
