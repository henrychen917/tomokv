// acl.h -- narrow command-family entry points. Bodies live in acl.inc's single TU stitch.
#pragma once

namespace tomo {

class Shard;
class Op;

void cmd_acl(Shard& shard, Op& op);

}  // namespace tomo
