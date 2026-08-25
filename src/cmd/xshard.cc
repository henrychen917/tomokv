// xshard.cc -- arena-backed, owner-only cross-shard execution.
#include "xshard.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <cctype>
#include <charconv>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <new>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

#include "command.h"
#include "hll.h"
#include "../core/server.h"
#include "../core/thread.h"
#include "../exec/op.h"
#include "../net/conn.h"
#include "../net/resp.h"
#include "../net/uring.h"
#include "../snapshot/format.h"
#include "../store/kvobj.h"


#include "scatter_engine.inc"
#include "xshard_commands.inc"
#include "atomics_glue.inc"
