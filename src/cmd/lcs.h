// lcs.h — LCS key1 key2 [LEN] [IDX] [MINMATCHLEN n] [WITHMATCHLEN].
//
// The two keys may live on different shards, so the command is lowered through the ordinary
// scatter/gather machinery: each owner serializes its string into the coordinating op's
// ObjectImage, and the last owner to finish runs the dynamic program. The algorithm and the reply
// shapes live here rather than in the shared scatter file so the feature stays one file.
#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace tomo {

class Op;

struct LcsOptions {
    bool len = false;
    bool idx = false;
    bool withmatchlen = false;
    uint64_t minmatchlen = 0;
};

// One aligned run of the longest common subsequence, in the order redis emits them: from the end
// of both strings backwards.
struct LcsMatch {
    uint32_t a_start = 0, a_end = 0;
    uint32_t b_start = 0, b_end = 0;
    uint32_t length = 0;
};

struct LcsResult {
    std::string value;                 // the subsequence itself; empty for LEN/IDX
    uint64_t length = 0;
    std::vector<LcsMatch> matches;
};

// Parses the trailing option words starting at argv[3]. Writes a complete error reply into `op`
// and returns false on any grammar violation.
bool lcs_parse_options(Op& op, LcsOptions& out);

// Classic O(n*m) dynamic program. Returns false only when the DP table cannot be allocated, in
// which case `error` names the redis-compatible message.
bool lcs_compute(const std::string& a, const std::string& b, const LcsOptions& options,
                 LcsResult& out, const char*& error);

// Emits the RESP for a completed result. Called on the connection's IO thread at retirement.
void lcs_reply(Op& op, const LcsOptions& options, const LcsResult& result);

}  // namespace tomo
