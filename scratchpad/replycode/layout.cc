#include <cstdio>
#include <cstddef>
#include "src/exec/op.h"
#include "src/base/slice.h"
using namespace tomo;
static Op g;
#define P(f) std::printf("%-22s off=%3zu size=%3zu\n", #f, (size_t)((char*)&g.f - (char*)&g), sizeof(g.f))
int main(){
  std::printf("sizeof(Op)=%zu align=%zu\n", sizeof(Op), alignof(Op));
  std::printf("sizeof(SmallBuf<96>)=%zu  sizeof(Slice)=%zu\n", sizeof(SmallBuf<96>), sizeof(Slice));
  P(spec); P(shard); P(read_cut_lo); P(hash); P(rbuf_off);
  P(reply); P(direct); P(direct_cap); P(direct_len);
  P(zc_ptr); P(zc_len); P(zc_shard); P(state);
  return 0;
}
