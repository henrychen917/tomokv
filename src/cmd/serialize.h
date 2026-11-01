// Redis-compatible DUMP / RESTORE value codec and command handlers.
#pragma once
#include <string>
#include <vector>
#include <cstdint>
#include "../base/slice.h"

namespace tomo {

// RDB FUNCTION2 records, without a file header or DUMP trailer. The native
// snapshot's metadata checksum encloses these records.
bool encode_function_records(const std::vector<std::string>&, std::vector<uint8_t>&);
bool decode_function_records(Slice, std::vector<std::string>&);

class Shard;
class Op;

void cmd_dump(Shard&, Op&);
void cmd_dump_notify(Shard&, Op&);
void cmd_restore(Shard&, Op&);
void cmd_restore_notify(Shard&, Op&);

}  // namespace tomo
