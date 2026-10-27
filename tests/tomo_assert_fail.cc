// Directed failure in a real production site. Invalid bucket bounds must abort
// before init can consult the server or install any shard state. No listener.
#include "src/core/shard.h"

int main() {
    auto* shard = new tomo::Shard;
    shard->init(nullptr, 0, 2, 1, 0, tomo::TypeLimits{}, tomo::StreamLimits{});
    return 0;  // A missing assertion is a test failure, not a successful probe.
}
