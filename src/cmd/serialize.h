// Redis-compatible DUMP / RESTORE value codec and command handlers.
#pragma once

namespace tomo {

class Shard;
class Op;

void cmd_dump(Shard&, Op&);
void cmd_dump_notify(Shard&, Op&);
void cmd_restore(Shard&, Op&);
void cmd_restore_notify(Shard&, Op&);

}  // namespace tomo
