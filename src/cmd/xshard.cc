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
#include <deque>
#include <fcntl.h>
#include <limits>
#include <memory>
#include <mutex>
#include <new>
#include <string>
#include <sys/random.h>
#include <sys/stat.h>
#include <unistd.h>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "command.h"
#include "acl.h"
#include "auth.h"
#include "blocking.h"
#include "debug.h"
#include "hll.h"
#include "multi.h"
#include "notify.h"
#include "../core/io_loop.h"
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
#include "blocking.inc"
#include "multi.inc"
#include "auth.inc"
#include "notify.inc"
