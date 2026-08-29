// glob.cc -- the single Redis-compatible glob matcher for command surfaces.

#include "command.h"

#include <cctype>
#include <utility>

namespace tomo {
namespace {

bool glob_match_impl(const char* pattern, uint32_t pattern_len,
                     const char* string, uint32_t string_len, bool nocase,
                     bool& skip_longer_matches, uint32_t nesting) {
    // Match Redis's protection against abusive patterns that recurse through '*'.
    if (nesting > 1000) return false;

    while (pattern_len && string_len) {
        switch (pattern[0]) {
            case '*': {
                while (pattern_len > 1 && pattern[1] == '*') {
                    pattern++;
                    pattern_len--;
                }
                if (pattern_len == 1) return true;
                while (string_len) {
                    if (glob_match_impl(pattern + 1, pattern_len - 1,
                                        string, string_len, nocase,
                                        skip_longer_matches, nesting + 1))
                        return true;
                    if (skip_longer_matches) return false;
                    string++;
                    string_len--;
                }
                skip_longer_matches = true;
                return false;
            }
            case '?':
                string++;
                string_len--;
                break;
            case '[': {
                pattern++;
                pattern_len--;
                bool negate = pattern_len && pattern[0] == '^';
                if (negate) {
                    pattern++;
                    pattern_len--;
                }
                bool matched = false;
                while (true) {
                    if (pattern_len >= 2 && pattern[0] == '\\') {
                        pattern++;
                        pattern_len--;
                        if (pattern[0] == string[0]) matched = true;
                    } else if (pattern_len && pattern[0] == ']') {
                        break;
                    } else if (pattern_len == 0) {
                        // Redis backs up over the final class byte so the outer increment consumes
                        // it. That makes an unterminated class act as if it ended with the pattern.
                        pattern--;
                        pattern_len++;
                        break;
                    } else if (pattern_len >= 3 && pattern[1] == '-') {
                        int start = static_cast<signed char>(pattern[0]);
                        int end = static_cast<signed char>(pattern[2]);
                        int candidate = static_cast<signed char>(string[0]);
                        if (start > end) std::swap(start, end);
                        if (nocase) {
                            start = std::tolower(start);
                            end = std::tolower(end);
                            candidate = std::tolower(candidate);
                        }
                        pattern += 2;
                        pattern_len -= 2;
                        if (candidate >= start && candidate <= end) matched = true;
                    } else if (!nocase) {
                        if (pattern[0] == string[0]) matched = true;
                    } else if (std::tolower(static_cast<signed char>(pattern[0])) ==
                               std::tolower(static_cast<signed char>(string[0]))) {
                        matched = true;
                    }
                    pattern++;
                    pattern_len--;
                }
                if (negate) matched = !matched;
                if (!matched) return false;
                string++;
                string_len--;
                break;
            }
            case '\\':
                if (pattern_len >= 2) {
                    pattern++;
                    pattern_len--;
                }
                [[fallthrough]];
            default:
                if (!nocase) {
                    if (pattern[0] != string[0]) return false;
                } else if (std::tolower(static_cast<signed char>(pattern[0])) !=
                           std::tolower(static_cast<signed char>(string[0]))) {
                    return false;
                }
                string++;
                string_len--;
                break;
        }
        pattern++;
        pattern_len--;
        if (string_len == 0) {
            while (pattern_len && pattern[0] == '*') {
                pattern++;
                pattern_len--;
            }
            break;
        }
    }
    return pattern_len == 0 && string_len == 0;
}

}  // namespace

bool command_glob_match(Slice pattern, Slice text, bool nocase) {
    bool skip_longer_matches = false;
    return glob_match_impl(pattern.p, pattern.n, text.p, text.n, nocase,
                           skip_longer_matches, 0);
}

}  // namespace tomo
