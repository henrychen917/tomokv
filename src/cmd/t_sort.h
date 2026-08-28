// t_sort.h -- SORT's ordering core and its BY/GET dereference.
//
// WHY THIS FILE EXISTS SEPARATELY FROM THE SCATTER ENGINE.  Every other multi-key command names
// its keys in argv, so the router can resolve every owner before the first byte is read.  SORT's
// BY and GET patterns do not: `SORT mylist BY weight_*` names one key per ELEMENT of mylist, and
// the element values are not known until mylist has already been read on its owner.  The derived
// names therefore route to arbitrary shards, discovered one wave too late for the engine to have
// posted a task to their owners.
//
// THE ADMISSION RULE.  A shard is touched only by its owning executor, and that is not negotiable.
// So the dereference is admitted exactly when it provably cannot leave the owner: when ONE executor
// owns every shard (sort_deref_local below).  In that configuration the source's owner may read any
// derived key directly, because it is that key's owner too.  Otherwise the command is refused with
// a specific error, which is what the reference server itself does in cluster mode -- see
// NOTES-SORT.md for the option analysis and the refusal argument.
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

class Server;
class Shard;

struct SortPattern {
    Slice raw;
    Slice prefix;            // bytes before the first '*'
    Slice suffix;            // bytes after it, up to "->field" when that is present
    Slice field;             // hash field, empty when the pattern names a plain string key
    bool  has_star = false;  // false => this pattern never reads a key
    bool  self = false;      // the literal "#": the element itself
};

void sort_pattern_parse(Slice pattern, SortPattern& out);

// True when one executor owns every shard, i.e. when a BY/GET dereference cannot name a key owned
// by another thread.  Boot-time constant.
bool sort_deref_local(Server& server);

// The two refusals, worded like the reference's cluster-mode pair and like this tree's existing
// ACL pair, so a client that keys on "<OPTION> option of SORT denied" keeps working.
inline constexpr const char* kSortByDenied =
    "ERR BY option of SORT denied when keys formed by the pattern may be owned by another executor";
inline constexpr const char* kSortGetDenied =
    "ERR GET option of SORT denied when keys formed by the pattern may be owned by another executor";

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
    // THE COMMAND'S READ CONTEXT, carried explicitly. The cut and the originating connection are
    // per-store state that the owning task binds only on the shard it was posted for, so a derived
    // key on a second shard has to be resolved under these or it answers from before this
    // connection's own last write. Only the cross-shard path can supply them, which is why a
    // dereferencing SORT is kept off the same-owner fast path.
    uint64_t read_snapshot = ~uint64_t{0};
    uint64_t origin_conn_id = 0;
    int64_t offset = 0;
    int64_t count = -1;
    SortPattern by;
    std::vector<SortPattern> gets;
};

enum class SortStatus : uint8_t { Ok, ConversionError, Oom };

// Orders `elements` (already in the source's natural order) per `spec`, applies LIMIT, then
// projects the GET patterns.  `values`/`present` are parallel: a false `present` is a RESP null,
// and an empty string when the result is being STOREd.  With no GET patterns every row is present
// and holds the element itself.
//
// `owner` is the executor's shard for the SOURCE key; derived keys are resolved through
// owner->server(), which is legal only under sort_deref_local (enforced by the caller at parse).
// It may be null exactly when the spec dereferences nothing -- no BY pattern with a '*' and no GET
// pattern other than `#` -- which is the ordinary `SORT key [ALPHA] [LIMIT]` form.
SortStatus sort_run(Shard* owner, bool notify, const SortSpec& spec,
                    std::vector<std::string>& elements,
                    std::vector<std::string>& values,
                    std::vector<uint8_t>& present);

// Exported by t_hash.cc / t_hash_ttl.cc for the hash-field form of a pattern.  Both are read-only:
// a lapsed field reads as absent rather than being reaped, because the reaping path is written for
// the key the command was routed on and would emit and erase under the wrong name.
bool hash_field_value_ro(const struct KvObj* object, Slice field, Slice& value);
bool hash_ttl_field_lapsed(const struct KvObj* object, Slice field, int64_t now_ms);

}  // namespace tomo
