#pragma once

#include <cstdint>
#include <vector>

#include "t_zset.h"

namespace tomo {

class Op;
class Shard;

struct GeoRoute {
    bool store = false;
    bool store_distance = false;
    uint32_t source_arg = 1;
    uint32_t destination_arg = 0;
};

enum class GeoBuildResult : uint8_t { Ok, MissingMember, Oom };

// Shared with the scatter lowering. Validation writes Redis-compatible errors into the op.
bool geo_prepare_route(Op& op, GeoRoute& route);
GeoBuildResult geo_build_store(Op& op, const std::vector<ZsetEntry>& source,
                               std::vector<ZsetEntry>& destination);
void cmd_geo_xshard_local(Shard& shard, Op& op, bool notify);

}  // namespace tomo
