// A rotation grace period cannot protect a still-pending network descriptor.
// Exercise the real retirement ring, without dereferencing a dangling pointer.
#include "src/core/read_local.h"
#include "src/exec/op.h"
#include <cassert>
#include <cstdio>

int main() {
    tomo::ReadLocalRetireRing ring;
    tomo::Op reply;
    const char bytes[] = "pending send";
    reply.zc_ptr = bytes;
    reply.zc_len = sizeof(bytes) - 1;
    const auto slot = ring.push();
    assert(ring.seal(7) == 1); // owner removes/replaces the captured value
    bool reclaimed = false;
    auto destroy = [&](uint32_t at) { assert(at == slot); reclaimed = true; };
    assert(ring.drain_below(7, destroy) == 0);
    // Reader publishes its next rotation; socket progress is not part of QSBR.
    assert(ring.drain_below(8, destroy) == 1);
    assert(reclaimed && reply.zc_ptr == bytes && reply.zc_len != 0);
    // The owner-only borrow registry is the separate lifetime witness for owner
    // GETs. A lane must not insert into that unsynchronized vector/hash index.
    reply.zc_ptr = nullptr;
    reply.zc_len = 0;
    std::puts("RL4.11 lifetime: rotation grace expires with a network descriptor still live");
}
