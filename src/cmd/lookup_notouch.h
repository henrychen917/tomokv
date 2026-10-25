#pragma once
#include "../store/flatstore.h"

namespace tomo {
// Redis LOOKUP_NOTOUCH is per lookup, independent of CLIENT NO-TOUCH. Preserve
// the enclosing task's setting, including nested script/EXEC calls.
class LookupNoTouch {
    FlatStore& store_;
    bool previous_;
public:
    explicit LookupNoTouch(FlatStore& store, bool enabled = true)
        : store_(store), previous_(store.no_touch()) {
        store_.set_no_touch(previous_ || enabled);
    }
    ~LookupNoTouch() { store_.set_no_touch(previous_); }
};
} // namespace tomo
