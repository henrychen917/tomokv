/*
 * Copyright (c) 2009-Present, Redis Ltd.
 * All rights reserved.
 *
 * Copyright (c) 2024-present, Valkey contributors.
 * All rights reserved.
 *
 * Licensed under your choice of (a) the Redis Source Available License 2.0
 * (RSALv2); or (b) the Server Side Public License v1 (SSPLv1); or (c) the
 * GNU Affero General Public License v3 (AGPLv3).
 *
 * Portions of this file are available under BSD3 terms; see REDISCONTRIBUTIONS for more information.
 */

#ifndef __REDIS_H
#define __REDIS_H

#include "fmacros.h"
#include "config.h"
#include "solarisfixes.h"
#include "rio.h"
#include "atomicvar.h"
#include "commands.h"
#include "object.h"

#include <stdio.h>
#include <stdlib.h>
#include <stddef.h>
#include <string.h>
#include <time.h>
#include <limits.h>
#include <unistd.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <syslog.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <lua.h>
#include <signal.h>

#ifdef HAVE_LIBSYSTEMD
#include <systemd/sd-daemon.h>
#endif

typedef long long mstime_t; /* millisecond time type. */
typedef long long ustime_t; /* microsecond time type. */

#include "ae.h"      /* Event driven programming library */
#include "sds.h"     /* Dynamic safe strings */
#include "entry.h"   /* Entry objects (field-value pairs with optional expiration) */
#include "ebuckets.h" /* expiry data structure */
#include "dict.h"    /* Hash tables */
#include "kvstore.h" /* Slot-based hash table */
#include "estore.h"  /* Expiration store */
#include "adlist.h"  /* Linked lists */
#include "zmalloc.h" /* total memory usage aware version of malloc/free */
#include "anet.h"    /* Networking the easy way */
#include "version.h" /* Version macro */
#include "util.h"    /* Misc functions useful in many places */
#include "latency.h" /* Latency monitor API */
#include "sparkline.h" /* ASCII graphs API */
#include "quicklist.h"  /* Lists are encoded as linked lists of
                           N-elements flat arrays */
#include "rax.h"     /* Radix tree */
#include "connection.h" /* Connection abstraction */
#include "eventnotifier.h" /* Event notification */
#include "memory_prefetch.h"

/* Forward declarations needed by redismodule.h and keymeta.h */
struct redisObject;
struct RedisModule;

/* This is a structure used to export some meta-information such as dbid to the module. */
struct RedisModuleKeyOptCtx {
    struct redisObject *from_key, *to_key; /* Optional name of key processed, NULL when unknown.
                                              In most cases, only 'from_key' is valid, but in callbacks
                                              such as `copy2`, both 'from_key' and 'to_key' are valid. */
    int from_dbid, to_dbid;                /* The dbid of the key being processed, -1 when unknown.
                                              In most cases, only 'from_dbid' is valid, but in callbacks such
                                              as `copy2`, 'from_dbid' and 'to_dbid' are both valid. */
}; 

#define REDISMODULE_CORE 1

#include "redismodule.h"    /* Redis modules API defines. */

/* Following includes allow test functions to be called from Redis main() */
#include "zipmap.h"
#include "ziplist.h" /* Compact list data structure */
#include "sha1.h"
#include "endianconv.h"
#include "crc64.h"
#include "keymeta.h"

struct hdr_histogram;

/* helpers */
#define numElements(x) (sizeof(x)/sizeof((x)[0]))

/* min/max */
#undef min
#undef max
#define min(a, b) ((a) < (b) ? (a) : (b))
#define max(a, b) ((a) > (b) ? (a) : (b))

/* Get the pointer of the outer struct from a member address */
#define redis_member2struct(struct_name, member_name, member_addr) \
            ((struct_name *)((char*)member_addr - offsetof(struct_name, member_name)))

/* Error codes */
#define C_OK                    0
#define C_ERR                   -1
#define C_RETRY                 -2

/* Static server configuration */
#define CONFIG_DEFAULT_HZ        10             /* Time interrupt calls/sec. */
#define CONFIG_MIN_HZ            1
#define CONFIG_MAX_HZ            500
#define MAX_CLIENTS_PER_CLOCK_TICK 200          /* HZ is adapted based on that. */
#define CRON_DBS_PER_CALL 16
#define CRON_DICTS_PER_DB 16
#define NET_MAX_WRITES_PER_EVENT (1024*64)
#define PROTO_SHARED_SELECT_CMDS 10
#define OBJ_SHARED_INTEGERS 10000
#define OBJ_SHARED_BULKHDR_LEN 32
#define OBJ_SHARED_HDR_STRLEN(_len_) (((_len_) < 10) ? 4 : 5) /* see shared.mbulkhdr etc. */
#define LOG_MAX_LEN    1024 /* Default maximum length of syslog messages.*/
#define AOF_REWRITE_ITEMS_PER_CMD 64
#define AOF_ANNOTATION_LINE_MAX_LEN 1024
#define CONFIG_RUN_ID_SIZE 40
#define RDB_EOF_MARK_SIZE 40
#define CONFIG_REPL_BACKLOG_MIN_SIZE (1024*16)          /* 16k */
#define CONFIG_BGSAVE_RETRY_DELAY 5 /* Wait a few secs before trying again. */
#define CONFIG_DEFAULT_PID_FILE "/var/run/redis.pid"
#define CONFIG_DEFAULT_BINDADDR_COUNT 2
#define CONFIG_DEFAULT_BINDADDR { "*", "-::*" }
#define NET_HOST_STR_LEN 256 /* Longest valid hostname */
#define NET_IP_STR_LEN 46 /* INET6_ADDRSTRLEN is 46, but we need to be sure */
#define NET_ADDR_STR_LEN (NET_IP_STR_LEN+32) /* Must be enough for ip:port */
#define NET_HOST_PORT_STR_LEN (NET_HOST_STR_LEN+32) /* Must be enough for hostname:port */
#define CONFIG_BINDADDR_MAX 16
#define CONFIG_MIN_RESERVED_FDS 32
#define CONFIG_DEFAULT_PROC_TITLE_TEMPLATE "{title} {listen-addr} {server-mode}"
#define INCREMENTAL_REHASHING_THRESHOLD_US 1000
#define CLIENTS_CRON_MIN_ITERATIONS 5

/* Stream IDMP configuration limits */
#define CONFIG_STREAM_IDMP_MIN_DURATION 1        /* Min IDMP duration in seconds. */
#define CONFIG_STREAM_IDMP_MAX_DURATION 86400    /* Max IDMP duration in seconds (24 hours). */
#define CONFIG_STREAM_IDMP_MIN_MAXSIZE 1         /* Min IDMP max entries. */
#define CONFIG_STREAM_IDMP_MAX_MAXSIZE 10000     /* Max IDMP max entries. */

#define ACTIVE_EXPIRE_CYCLE_SLOW 0
#define ACTIVE_EXPIRE_CYCLE_FAST 1

/* Children process will exit with this status code to signal that the
 * process terminated without an error: this is useful in order to kill
 * a saving child (RDB or AOF one), without triggering in the parent the
 * write protection that is normally turned on on write errors.
 * Usually children that are terminated with SIGUSR1 will exit with this
 * special code. */
#define SERVER_CHILD_NOERROR_RETVAL    255

/* Reading copy-on-write info is sometimes expensive and may slow down child
 * processes that report it continuously. We measure the cost of obtaining it
 * and hold back additional reading based on this factor. */
#define CHILD_COW_DUTY_CYCLE           100

/* Instantaneous metrics tracking. */
#define STATS_METRIC_SAMPLES 16     /* Number of samples per metric. */
#define STATS_METRIC_COMMAND 0      /* Number of commands executed. */
#define STATS_METRIC_NET_INPUT 1    /* Bytes read from network. */
#define STATS_METRIC_NET_OUTPUT 2   /* Bytes written to network. */
#define STATS_METRIC_NET_INPUT_REPLICATION 3   /* Bytes read from network during replication. */
#define STATS_METRIC_NET_OUTPUT_REPLICATION 4   /* Bytes written to network during replication. */
#define STATS_METRIC_EL_CYCLE 5     /* Number of eventloop cycled. */
#define STATS_METRIC_EL_DURATION 6  /* Eventloop duration. */
#define STATS_METRIC_COUNT 7

/* Protocol and I/O related defines */
#define PROTO_IOBUF_LEN         (1024*16)  /* Generic I/O buffer size */
#define PROTO_REPLY_CHUNK_BYTES (16*1024) /* 16k output buffer */
#define FAKE_BUF_START_BYTES  (1024)    /* 2s-auto D1: auto-mode initial fake buf */
#define FAKE_BUF_MAX_BYTES    (64*1024) /* 2s-auto D1: auto-mode cap */
#define PROTO_INLINE_MAX_SIZE   (1024*64) /* Max size of inline reads */
#define PROTO_MBULK_BIG_ARG     (1024*32)
#define PROTO_RESIZE_THRESHOLD  (1024*32) /* Threshold for determining whether to resize query buffer */
#define PROTO_REPLY_MIN_BYTES   (1024) /* the lower limit on reply buffer size */
#define REDIS_AUTOSYNC_BYTES (1024*1024*4) /* Sync file every 4MB. */

#define REPLY_BUFFER_DEFAULT_PEAK_RESET_TIME 5000 /* 5 seconds */

/* Reply copy avoidance thresholds */
#define COPY_AVOID_MIN_IO_THREADS 7          /* Minimum number of IO threads for copy avoidance */
#define COPY_AVOID_MIN_STRING_SIZE 16384     /* Minimum bulk string size for copy avoidance (no IO threads) */
#define COPY_AVOID_MIN_STRING_SIZE_THREADED 65536  /* Minimum bulk string size for copy avoidance (with IO threads) */

/* When configuring the server eventloop, we setup it so that the total number
 * of file descriptors we can handle are server.maxclients + RESERVED_FDS +
 * a few more to stay safe. Since RESERVED_FDS defaults to 32, we add 96
 * in order to make sure of not over provisioning more than 128 fds. */
#define CONFIG_FDSET_INCR (CONFIG_MIN_RESERVED_FDS+96)

/* Default lookahead value */
#define REDIS_DEFAULT_LOOKAHEAD 16

/* OOM Score Adjustment classes. */
#define CONFIG_OOM_MASTER 0
#define CONFIG_OOM_REPLICA 1
#define CONFIG_OOM_BGCHILD 2
#define CONFIG_OOM_COUNT 3

extern int configOOMScoreAdjValuesDefaults[CONFIG_OOM_COUNT];

/* Hash table parameters */
#define HASHTABLE_MAX_LOAD_FACTOR 1.618   /* Maximum hash table load factor. */

/* Max number of IO threads */
#define IO_THREADS_MAX_NUM 128

/* To make IO threads and main thread run in parallel, we will transfer clients
 * between them if the number of clients in the pending list reaches this value. */
#define IO_THREAD_MAX_PENDING_CLIENTS 16

/* Main thread id for doing IO work, whatever we enable or disable io thread
 * the main thread always does IO work, so we can consider that the main thread
 * is the io thread 0. */
#define IOTHREAD_MAIN_THREAD_ID 0

/* Command flags. Please check the definition of struct redisCommand in this file
 * for more information about the meaning of every flag. */
#define CMD_WRITE (1ULL<<0)
#define CMD_READONLY (1ULL<<1)
#define CMD_DENYOOM (1ULL<<2)
#define CMD_MODULE (1ULL<<3)           /* Command exported by module. */
#define CMD_ADMIN (1ULL<<4)
#define CMD_PUBSUB (1ULL<<5)
#define CMD_NOSCRIPT (1ULL<<6)
#define CMD_BLOCKING (1ULL<<8)       /* Has potential to block. */
#define CMD_LOADING (1ULL<<9)
#define CMD_STALE (1ULL<<10)
#define CMD_SKIP_MONITOR (1ULL<<11)
#define CMD_SKIP_SLOWLOG (1ULL<<12)
#define CMD_ASKING (1ULL<<13)
#define CMD_FAST (1ULL<<14)
#define CMD_NO_AUTH (1ULL<<15)
#define CMD_MAY_REPLICATE (1ULL<<16)
#define CMD_SENTINEL (1ULL<<17)
#define CMD_ONLY_SENTINEL (1ULL<<18)
#define CMD_NO_MANDATORY_KEYS (1ULL<<19)
#define CMD_PROTECTED (1ULL<<20)
#define CMD_MODULE_GETKEYS (1ULL<<21)  /* Use the modules getkeys interface. */
#define CMD_MODULE_NO_CLUSTER (1ULL<<22) /* Deny on Redis Cluster. */
#define CMD_NO_ASYNC_LOADING (1ULL<<23)
#define CMD_NO_MULTI (1ULL<<24)
#define CMD_MOVABLE_KEYS (1ULL<<25) /* The legacy range spec doesn't cover all keys.
                                     * Populated by populateCommandLegacyRangeSpec. */
#define CMD_ALLOW_BUSY ((1ULL<<26))
#define CMD_MODULE_GETCHANNELS (1ULL<<27)  /* Use the modules getchannels interface. */
#define CMD_TOUCHES_ARBITRARY_KEYS (1ULL<<28)
#define CMD_INTERNAL (1ULL<<29) /* Internal command. */

/* Command flags that describe ACLs categories. */
#define ACL_CATEGORY_KEYSPACE (1ULL<<0)
#define ACL_CATEGORY_READ (1ULL<<1)
#define ACL_CATEGORY_WRITE (1ULL<<2)
#define ACL_CATEGORY_SET (1ULL<<3)
#define ACL_CATEGORY_SORTEDSET (1ULL<<4)
#define ACL_CATEGORY_LIST (1ULL<<5)
#define ACL_CATEGORY_HASH (1ULL<<6)
#define ACL_CATEGORY_STRING (1ULL<<7)
#define ACL_CATEGORY_BITMAP (1ULL<<8)
#define ACL_CATEGORY_HYPERLOGLOG (1ULL<<9)
#define ACL_CATEGORY_GEO (1ULL<<10)
#define ACL_CATEGORY_STREAM (1ULL<<11)
#define ACL_CATEGORY_PUBSUB (1ULL<<12)
#define ACL_CATEGORY_ADMIN (1ULL<<13)
#define ACL_CATEGORY_FAST (1ULL<<14)
#define ACL_CATEGORY_SLOW (1ULL<<15)
#define ACL_CATEGORY_BLOCKING (1ULL<<16)
#define ACL_CATEGORY_DANGEROUS (1ULL<<17)
#define ACL_CATEGORY_CONNECTION (1ULL<<18)
#define ACL_CATEGORY_TRANSACTION (1ULL<<19)
#define ACL_CATEGORY_SCRIPTING (1ULL<<20)

/* Key-spec flags *
 * -------------- */
/* The following refer what the command actually does with the value or metadata
 * of the key, and not necessarily the user data or how it affects it.
 * Each key-spec may must have exactly one of these. Any operation that's not
 * distinctly deletion, overwrite or read-only would be marked as RW. */
#define CMD_KEY_RO (1ULL<<0)     /* Read-Only - Reads the value of the key, but
                                  * doesn't necessarily returns it. */
#define CMD_KEY_RW (1ULL<<1)     /* Read-Write - Reads and modifies/deletes
                                  * the data stored in the value of the key or
                                  * its metadata. */
#define CMD_KEY_OW (1ULL<<2)     /* Overwrite - Overwrites the data stored in
                                  * the value of the key. */
#define CMD_KEY_RM (1ULL<<3)     /* Deletes the key without reading it's value. */
/* The following refer to user data inside the value of the key, not the metadata
 * like LRU, type, cardinality. It refers to the logical operation on the user's
 * data (actual input strings / TTL), being used / returned / copied / changed,
 * It doesn't refer to modification or returning of metadata (like type, count,
 * presence of data). Any write that's not INSERT or DELETE, would be an UPDATE.
 * Each key-spec may have one of the writes with or without access, or none: */
#define CMD_KEY_ACCESS (1ULL<<4) /* Returns, copies or uses the user data from
                                  * the value of the key. */
#define CMD_KEY_UPDATE (1ULL<<5) /* Updates data to the value, new value may
                                  * depend on the old value. */
#define CMD_KEY_INSERT (1ULL<<6) /* Adds data to the value with no chance of
                                  * modification or deletion of existing data. */
#define CMD_KEY_DELETE (1ULL<<7) /* Explicitly deletes some content
                                  * from the value of the key. */
/* Other flags: */
#define CMD_KEY_NOT_KEY (1ULL<<8)     /* A 'fake' key that should be routed
                                       * like a key in cluster mode but is
                                       * excluded from other key checks. */
#define CMD_KEY_INCOMPLETE (1ULL<<9)  /* Means that the keyspec might not point
                                       * out to all keys it should cover */
#define CMD_KEY_VARIABLE_FLAGS (1ULL<<10)  /* Means that some keys might have
                                            * different flags depending on arguments */
#define CMD_KEY_PREFIX (1ULL<<11) /* Given key represents a prefix of a set of keys */

/* Key flags for when access type is unknown */
#define CMD_KEY_FULL_ACCESS (CMD_KEY_RW | CMD_KEY_ACCESS | CMD_KEY_UPDATE)

/* Key flags for how key is removed */
#define DB_FLAG_KEY_NONE 0
#define DB_FLAG_KEY_DELETED (1ULL<<0)
#define DB_FLAG_KEY_EXPIRED (1ULL<<1)
#define DB_FLAG_KEY_EVICTED (1ULL<<2)
#define DB_FLAG_KEY_OVERWRITE (1ULL<<3)
#define DB_FLAG_NO_UPDATE_KEYSIZES (1ULL<<4) /* Don't update keysizes histograms */

/* Channel flags share the same flag space as the key flags */
#define CMD_CHANNEL_PATTERN (1ULL<<11)     /* The argument is a channel pattern */
#define CMD_CHANNEL_SUBSCRIBE (1ULL<<12)   /* The command subscribes to channels */
#define CMD_CHANNEL_UNSUBSCRIBE (1ULL<<13) /* The command unsubscribes to channels */
#define CMD_CHANNEL_PUBLISH (1ULL<<14)     /* The command publishes to channels. */

/* AOF states */
#define AOF_OFF 0             /* AOF is off */
#define AOF_ON 1              /* AOF is on */
#define AOF_WAIT_REWRITE 2    /* AOF waits rewrite to start appending */

/* AOF return values for loadAppendOnlyFiles() and loadSingleAppendOnlyFile() */
#define AOF_OK 0
#define AOF_NOT_EXIST 1
#define AOF_EMPTY 2
#define AOF_OPEN_ERR 3
#define AOF_FAILED 4
#define AOF_TRUNCATED 5
#define AOF_BROKEN_RECOVERED 6

/* RDB return values for rdbLoad. */
#define RDB_OK 0
#define RDB_NOT_EXIST 1 /* RDB file doesn't exist. */
#define RDB_FAILED 2 /* Failed to load the RDB file. */

/* Command doc flags */
#define CMD_DOC_NONE 0
#define CMD_DOC_DEPRECATED (1<<0) /* Command is deprecated */
#define CMD_DOC_SYSCMD (1<<1) /* System (internal) command */

/* Client flags */
#define CLIENT_SLAVE (1<<0)   /* This client is a replica */
#define CLIENT_MASTER (1<<1)  /* This client is a master */
#define CLIENT_MONITOR (1<<2) /* This client is a slave monitor, see MONITOR */
#define CLIENT_MULTI (1<<3)   /* This client is in a MULTI context */
#define CLIENT_BLOCKED (1<<4) /* The client is waiting in a blocking operation */
#define CLIENT_DIRTY_CAS (1<<5) /* Watched keys modified. EXEC will fail. */
#define CLIENT_CLOSE_AFTER_REPLY (1<<6) /* Close after writing entire reply. */
#define CLIENT_UNBLOCKED (1<<7) /* This client was unblocked and is stored in
                                  server.unblocked_clients */
#define CLIENT_SCRIPT (1<<8) /* This is a non connected client used by Lua */
#define CLIENT_ASKING (1<<9)     /* Client issued the ASKING command */
#define CLIENT_CLOSE_ASAP (1<<10)/* Close this client ASAP */
#define CLIENT_UNIX_SOCKET (1<<11) /* Client connected via Unix domain socket */
#define CLIENT_DIRTY_EXEC (1<<12)  /* EXEC will fail for errors while queueing */
#define CLIENT_MASTER_FORCE_REPLY (1<<13)  /* Queue replies even if is master */
#define CLIENT_FORCE_AOF (1<<14)   /* Force AOF propagation of current cmd. */
#define CLIENT_FORCE_REPL (1<<15)  /* Force replication of current cmd. */
#define CLIENT_PRE_PSYNC (1<<16)   /* Instance don't understand PSYNC. */
#define CLIENT_READONLY (1<<17)    /* Cluster client is in read-only state. */
#define CLIENT_PUBSUB (1<<18)      /* Client is in Pub/Sub mode. */
#define CLIENT_PREVENT_AOF_PROP (1<<19)  /* Don't propagate to AOF. */
#define CLIENT_PREVENT_REPL_PROP (1<<20)  /* Don't propagate to slaves. */
#define CLIENT_PREVENT_PROP (CLIENT_PREVENT_AOF_PROP|CLIENT_PREVENT_REPL_PROP)
#define CLIENT_PENDING_WRITE (1<<21) /* Client has output to send but a write
                                        handler is yet not installed. */
#define CLIENT_REPLY_OFF (1<<22)   /* Don't send replies to client. */
#define CLIENT_REPLY_SKIP_NEXT (1<<23)  /* Set CLIENT_REPLY_SKIP for next cmd */
#define CLIENT_REPLY_SKIP (1<<24)  /* Don't send just this reply. */
#define CLIENT_LUA_DEBUG (1<<25)  /* Run EVAL in debug mode. */
#define CLIENT_LUA_DEBUG_SYNC (1<<26)  /* EVAL debugging without fork() */
#define CLIENT_MODULE (1<<27) /* Non connected client used by some module. */
#define CLIENT_PROTECTED (1<<28) /* Client should not be freed for now. */
#define CLIENT_EXECUTING_COMMAND (1<<29) /* Indicates that the client is currently in the process of handling
                                          a command. usually this will be marked only during call()
                                          however, blocked clients might have this flag kept until they
                                          will try to reprocess the command. */

#define CLIENT_PENDING_COMMAND (1<<30) /* Indicates the client has a fully
                                        * parsed command ready for execution. */
#define CLIENT_TRACKING (1ULL<<31) /* Client enabled keys tracking in order to
                                   perform client side caching. */
#define CLIENT_TRACKING_BROKEN_REDIR (1ULL<<32) /* Target client is invalid. */
#define CLIENT_TRACKING_BCAST (1ULL<<33) /* Tracking in BCAST mode. */
#define CLIENT_TRACKING_OPTIN (1ULL<<34)  /* Tracking in opt-in mode. */
#define CLIENT_TRACKING_OPTOUT (1ULL<<35) /* Tracking in opt-out mode. */
#define CLIENT_TRACKING_CACHING (1ULL<<36) /* CACHING yes/no was given,
                                              depending on optin/optout mode. */
#define CLIENT_TRACKING_NOLOOP (1ULL<<37) /* Don't send invalidation messages
                                             about writes performed by myself.*/
#define CLIENT_IN_TO_TABLE (1ULL<<38) /* This client is in the timeout table. */
#define CLIENT_PROTOCOL_ERROR (1ULL<<39) /* Protocol error chatting with it. */
#define CLIENT_CLOSE_AFTER_COMMAND (1ULL<<40) /* Close after executing commands
                                               * and writing entire reply. */
#define CLIENT_DENY_BLOCKING (1ULL<<41) /* Indicate that the client should not be blocked.
                                           currently, turned on inside MULTI, Lua, RM_Call,
                                           and AOF client */
#define CLIENT_REPL_RDBONLY (1ULL<<42) /* This client is a replica that only wants
                                          RDB without replication buffer. */
#define CLIENT_NO_EVICT (1ULL<<43) /* This client is protected against client
                                      memory eviction. */
#define CLIENT_ALLOW_OOM (1ULL<<44) /* Client used by RM_Call is allowed to fully execute
                                       scripts even when in OOM */
#define CLIENT_NO_TOUCH (1ULL<<45) /* This client will not touch LFU/LRU stats. */
#define CLIENT_PUSHING (1ULL<<46) /* This client is pushing notifications. */
#define CLIENT_MODULE_AUTH_HAS_RESULT (1ULL<<47) /* Indicates a client in the middle of module based
                                                    auth had been authenticated from the Module. */
#define CLIENT_MODULE_PREVENT_AOF_PROP (1ULL<<48) /* Module client do not want to propagate to AOF */
#define CLIENT_MODULE_PREVENT_REPL_PROP (1ULL<<49) /* Module client do not want to propagate to replica */
#define CLIENT_REEXECUTING_COMMAND (1ULL<<50) /* The client is re-executing the command. */
#define CLIENT_REPL_RDB_CHANNEL (1ULL<<51)      /* Client which is used for rdb delivery as part of rdb channel replication */
#define CLIENT_INTERNAL (1ULL<<52) /* Internal client connection */
#define CLIENT_ASM_MIGRATING (1ULL<<53) /* Client is migrating RDB/stream data during atomic slot migration. */
#define CLIENT_ASM_IMPORTING (1ULL<<54) /* Client is importing RDB/stream data during atomic slot migration. */

//ee451 new flag
#define CLIENT_EX_PENDING (1ULL << 55) //new ee451
#define CLIENT_PIPELINE_STALLED (1ULL << 56)
/* ee451 (thread-modes v1.6): this client is being MIGRATED off its current io
 * thread (reads paused, ring draining toward the quiesce fence). Cleared once the
 * destination io thread re-registers it. Only ever set/read by the client's owning
 * io thread and by the source thread during the drain window. */
#define CLIENT_MIGRATING (1ULL << 57)
/* Atomic MSET admission parked this client before taking a fake-ring slot. The
 * command remains at pending_cmds.head until its owning event loop retries it. */
#define CLIENT_ATOMIC_WINDOW_STALLED (1ULL << 58)
/* Any flag that does not let optimize FLUSH SYNC to run it in bg as blocking client ASYNC */
#define CLIENT_AVOID_BLOCKING_ASYNC_FLUSH (CLIENT_DENY_BLOCKING|CLIENT_MULTI|CLIENT_LUA_DEBUG|CLIENT_LUA_DEBUG_SYNC|CLIENT_MODULE)

/* Max deferred objects to be freed by IO thread for each client. */
#define CLIENT_MAX_DEFERRED_OBJECTS 32

/* Client flags for client IO */
#define CLIENT_IO_READ_ENABLED (1ULL<<0) /* Client can read from socket. */
#define CLIENT_IO_WRITE_ENABLED (1ULL<<1) /* Client can write to socket. */
#define CLIENT_IO_PENDING_COMMAND (1ULL<<2) /* Similar to CLIENT_PENDING_COMMAND. */
#define CLIENT_IO_REUSABLE_QUERYBUFFER (1ULL<<3) /* The client is using the reusable query buffer. */
#define CLIENT_IO_CLOSE_ASAP (1ULL<<4) /* Close this client ASAP in IO thread. */
#define CLIENT_IO_PENDING_CRON (1ULL<<5)  /* The client is pending cron job, to be processed in main thread. */



/* Definitions for client read errors. These error codes are used to indicate
 * various issues that can occur while reading or parsing data from a client. */
#define CLIENT_READ_TOO_BIG_INLINE_REQUEST 1
#define CLIENT_READ_UNBALANCED_QUOTES 2
#define CLIENT_READ_MASTER_USING_INLINE_PROTOCAL 3
#define CLIENT_READ_TOO_BIG_MBULK_COUNT_STRING 4
#define CLIENT_READ_TOO_BIG_BUCK_COUNT_STRING 5
#define CLIENT_READ_EXPECTED_DOLLAR 6
#define CLIENT_READ_INVALID_BUCK_LENGTH 7
#define CLIENT_READ_UNAUTH_BUCK_LENGTH 8
#define CLIENT_READ_INVALID_MULTIBUCK_LENGTH 9
#define CLIENT_READ_UNAUTH_MBUCK_COUNT 10
#define CLIENT_READ_CONN_DISCONNECTED 11
#define CLIENT_READ_CONN_CLOSED 12
#define CLIENT_READ_REACHED_MAX_QUERYBUF 13
#define CLIENT_READ_COMMAND_NOT_FOUND 14
#define CLIENT_READ_BAD_ARITY 15
#define CLIENT_READ_CROSS_SLOT 16

/* Client block type (btype field in client structure)
 * if CLIENT_BLOCKED flag is set. */
typedef enum blocking_type {
    BLOCKED_NONE,    /* Not blocked, no CLIENT_BLOCKED flag set. */
    BLOCKED_LIST,    /* BLPOP & co. */
    BLOCKED_WAIT,    /* WAIT for synchronous replication. */
    BLOCKED_WAITAOF, /* WAITAOF for AOF file fsync. */
    BLOCKED_MODULE,  /* Blocked by a loadable module. */
    BLOCKED_STREAM,  /* XREAD. */
    BLOCKED_ZSET,    /* BZPOP et al. */
    BLOCKED_POSTPONE, /* Blocked by processCommand, re-try processing later. */
    BLOCKED_POSTPONE_TRIM, /* Master client is blocked due to an active trim job. */
    BLOCKED_SHUTDOWN, /* SHUTDOWN. */
    BLOCKED_LAZYFREE, /* LAZYFREE */
    BLOCKED_NUM,      /* Number of blocked states. */
    BLOCKED_END       /* End of enumeration */
} blocking_type;

/* Client request types */
#define PROTO_REQ_INLINE 1
#define PROTO_REQ_MULTIBULK 2

/* Client classes for client limits, currently used only for
 * the max-client-output-buffer limit implementation. */
#define CLIENT_TYPE_NORMAL 0 /* Normal req-reply clients + MONITORs */
#define CLIENT_TYPE_SLAVE 1  /* Slaves. */
#define CLIENT_TYPE_PUBSUB 2 /* Clients subscribed to PubSub channels. */
#define CLIENT_TYPE_MASTER 3 /* Master. */
#define CLIENT_TYPE_COUNT 4  /* Total number of client types. */
#define CLIENT_TYPE_OBUF_COUNT 3 /* Number of clients to expose to output
                                    buffer configuration. Just the first
                                    three: normal, slave, pubsub. */

/* Slave replication state. Used in server.repl_state for slaves to remember
 * what to do next. */
typedef enum {
    REPL_STATE_NONE = 0,            /* No active replication */
    REPL_STATE_CONNECT,             /* Must connect to master */
    REPL_STATE_CONNECTING,          /* Connecting to master */
    /* --- Handshake states, must be ordered --- */
    REPL_STATE_RECEIVE_PING_REPLY,  /* Wait for PING reply */
    REPL_STATE_SEND_HANDSHAKE,      /* Send handshake sequence to master */
    REPL_STATE_RECEIVE_AUTH_REPLY,  /* Wait for AUTH reply */
    REPL_STATE_RECEIVE_PORT_REPLY,  /* Wait for REPLCONF reply */
    REPL_STATE_RECEIVE_IP_REPLY,    /* Wait for REPLCONF reply */
    REPL_STATE_RECEIVE_COMP_REPLY,  /* Wait for REPLCONF reply */
    REPL_STATE_RECEIVE_CAPA_REPLY,  /* Wait for REPLCONF reply */
    REPL_STATE_SEND_PSYNC,          /* Send PSYNC */
    REPL_STATE_RECEIVE_PSYNC_REPLY, /* Wait for PSYNC reply */
    /* --- End of handshake states --- */
    REPL_STATE_TRANSFER,        /* Receiving .rdb from master */
    REPL_STATE_CONNECTED,       /* Connected to master */
} repl_state;

/* Replica rdb channel replication state. Used in server.repl_rdb_ch_state for
 * replicas to remember what to do next. */
typedef enum {
    REPL_RDB_CH_STATE_NONE = 0,         /* No active rdb channel sync */
    REPL_RDB_CH_SEND_HANDSHAKE,         /* Send handshake sequence to master */
    REPL_RDB_CH_RECEIVE_AUTH_REPLY,     /* Wait for AUTH reply */
    REPL_RDB_CH_RECEIVE_REPLCONF_REPLY, /* Wait for REPLCONF reply */
    REPL_RDB_CH_RECEIVE_FULLRESYNC,     /* Wait for +FULLRESYNC reply */
    REPL_RDB_CH_RDB_LOADING,            /* Loading rdb using rdb channel */
} repl_rdb_channel_state;

#define REPL_MAIN_CH_NONE           (1 << 0)
#define REPL_MAIN_CH_ACCUMULATE_BUF (1 << 1)
#define REPL_MAIN_CH_STREAMING_BUF  (1 << 2)
#define REPL_MAIN_CH_CLOSE_ASAP     (1 << 3)

/* Replication debug flags for testing. */
#define REPL_DEBUG_PAUSE_NONE             (1 << 0)
#define REPL_DEBUG_AFTER_FORK             (1 << 1)
#define REPL_DEBUG_BEFORE_RDB_CHANNEL     (1 << 2)
#define REPL_DEBUG_ON_STREAMING_REPL_BUF  (1 << 3)

/* The state of an in progress coordinated failover */
typedef enum {
    NO_FAILOVER = 0,        /* No failover in progress */
    FAILOVER_WAIT_FOR_SYNC, /* Waiting for target replica to catch up */
    FAILOVER_IN_PROGRESS    /* Waiting for target replica to accept
                             * PSYNC FAILOVER request. */
} failover_state;

/* State of slaves from the POV of the master. Used in client->replstate.
 * In SEND_BULK and ONLINE state the slave receives new updates
 * in its output queue. In the WAIT_BGSAVE states instead the server is waiting
 * to start the next background saving in order to send updates to it. */
#define SLAVE_STATE_WAIT_BGSAVE_START 6 /* We need to produce a new RDB file. */
#define SLAVE_STATE_WAIT_BGSAVE_END 7 /* Waiting RDB file creation to finish. */
#define SLAVE_STATE_SEND_BULK 8 /* Sending RDB file to slave. */
#define SLAVE_STATE_ONLINE 9 /* RDB file transmitted, sending just updates. */
#define SLAVE_STATE_RDB_TRANSMITTED 10 /* RDB file transmitted - This state is used only for
                                        * a replica that only wants RDB without replication buffer  */
#define SLAVE_STATE_WAIT_RDB_CHANNEL 11 /* Main channel of replica is connected,
                                         * we are waiting rdbchannel connection to start delivery.*/
#define SLAVE_STATE_SEND_BULK_AND_STREAM 12 /* Main channel of a replica which uses rdb channel replication.
                                             * Sending RDB file and replication stream in parallel. */

/* Slave capabilities. */
#define SLAVE_CAPA_NONE             0
#define SLAVE_CAPA_EOF              (1<<0) /* Can parse the RDB EOF streaming format. */
#define SLAVE_CAPA_PSYNC2           (1<<1) /* Supports PSYNC2 protocol. */
#define SLAVE_CAPA_RDB_CHANNEL_REPL (1<<2) /* Supports rdb channel replication during full sync */

/* Slave requirements */
#define SLAVE_REQ_NONE                  0
#define SLAVE_REQ_RDB_EXCLUDE_DATA      (1 << 0) /* Exclude data from RDB */
#define SLAVE_REQ_RDB_EXCLUDE_FUNCTIONS (1 << 1) /* Exclude functions from RDB */
#define SLAVE_REQ_SLOTS_SNAPSHOT        (1 << 2) /* Only slots snapshot is required */
#define SLAVE_REQ_RDB_CHANNEL           (1 << 3) /* Use rdb channel replication, transfer RDB background */
#define SLAVE_REQ_RDB_NO_COMPRESS       (1 << 4) /* Don't enable RDB compression */
/* Mask of all bits in the slave requirements bitfield that represent non-standard (filtered) RDB requirements */
#define SLAVE_REQ_RDB_MASK (SLAVE_REQ_RDB_EXCLUDE_DATA | SLAVE_REQ_RDB_EXCLUDE_FUNCTIONS | SLAVE_REQ_SLOTS_SNAPSHOT)

/* Synchronous read timeout - slave side */
#define CONFIG_REPL_SYNCIO_TIMEOUT 5

/* The default number of replication backlog blocks to trim per call. */
#define REPL_BACKLOG_TRIM_BLOCKS_PER_CALL 64

/* In order to quickly find the requested offset for PSYNC requests,
 * we index some nodes in the replication buffer linked list into a rax. */
#define REPL_BACKLOG_INDEX_PER_BLOCKS 64

/* List related stuff */
#define LIST_HEAD 0
#define LIST_TAIL 1
#define ZSET_MIN 0
#define ZSET_MAX 1

/* Sort operations */
#define SORT_OP_GET 0

/* Log levels */
#define LL_DEBUG 0
#define LL_VERBOSE 1
#define LL_NOTICE 2
#define LL_WARNING 3
#define LL_NOTHING 4
#define LL_RAW (1<<10) /* Modifier to log without timestamp */

/* Supervision options */
#define SUPERVISED_NONE 0
#define SUPERVISED_AUTODETECT 1
#define SUPERVISED_SYSTEMD 2
#define SUPERVISED_UPSTART 3

/* Anti-warning macro... */
#define UNUSED(V) ((void) V)

#define ZSKIPLIST_MAXLEVEL 32 /* Should be enough for 2^64 elements */
#define ZSKIPLIST_P 0.25      /* Skiplist P = 1/4 */
#define ZSKIPLIST_MAX_SEARCH 10

/* Append only defines */
#define AOF_FSYNC_NO 0
#define AOF_FSYNC_ALWAYS 1
#define AOF_FSYNC_EVERYSEC 2

/* Replication diskless load defines */
#define REPL_DISKLESS_LOAD_DISABLED 0
#define REPL_DISKLESS_LOAD_WHEN_DB_EMPTY 1
#define REPL_DISKLESS_LOAD_SWAPDB 2
#define REPL_DISKLESS_LOAD_ALWAYS 3

/* TLS Client Authentication */
#define TLS_CLIENT_AUTH_NO 0
#define TLS_CLIENT_AUTH_YES 1
#define TLS_CLIENT_AUTH_OPTIONAL 2

/* TLS Client Certfiicate Authentication */
#define TLS_CLIENT_FIELD_OFF 0
#define TLS_CLIENT_FIELD_CN 1

/* Sanitize dump payload */
#define SANITIZE_DUMP_NO 0
#define SANITIZE_DUMP_YES 1
#define SANITIZE_DUMP_CLIENTS 2

/* Enable protected config/command */
#define PROTECTED_ACTION_ALLOWED_NO 0
#define PROTECTED_ACTION_ALLOWED_YES 1
#define PROTECTED_ACTION_ALLOWED_LOCAL 2

/* Sets operations codes */
#define SET_OP_UNION 0
#define SET_OP_DIFF 1
#define SET_OP_INTER 2

/* oom-score-adj defines */
#define OOM_SCORE_ADJ_NO 0
#define OOM_SCORE_RELATIVE 1
#define OOM_SCORE_ADJ_ABSOLUTE 2

/* Redis maxmemory strategies. Instead of using just incremental number
 * for this defines, we use a set of flags so that testing for certain
 * properties common to multiple policies is faster. */
#define MAXMEMORY_FLAG_LRU (1<<0)
#define MAXMEMORY_FLAG_LFU (1<<1)
#define MAXMEMORY_FLAG_ALLKEYS (1<<2)
#define MAXMEMORY_FLAG_LRM (1<<3)
#define MAXMEMORY_FLAG_NO_SHARED_INTEGERS \
    (MAXMEMORY_FLAG_LRU|MAXMEMORY_FLAG_LFU|MAXMEMORY_FLAG_LRM)

#define MAXMEMORY_VOLATILE_LRU ((0<<8)|MAXMEMORY_FLAG_LRU)
#define MAXMEMORY_VOLATILE_LFU ((1<<8)|MAXMEMORY_FLAG_LFU)
#define MAXMEMORY_VOLATILE_TTL (2<<8)
#define MAXMEMORY_VOLATILE_RANDOM (3<<8)
#define MAXMEMORY_ALLKEYS_LRU ((4<<8)|MAXMEMORY_FLAG_LRU|MAXMEMORY_FLAG_ALLKEYS)
#define MAXMEMORY_ALLKEYS_LFU ((5<<8)|MAXMEMORY_FLAG_LFU|MAXMEMORY_FLAG_ALLKEYS)
#define MAXMEMORY_ALLKEYS_RANDOM ((6<<8)|MAXMEMORY_FLAG_ALLKEYS)
#define MAXMEMORY_NO_EVICTION (7<<8)
#define MAXMEMORY_VOLATILE_LRM ((8<<8)|MAXMEMORY_FLAG_LRM)
#define MAXMEMORY_ALLKEYS_LRM ((9<<8)|MAXMEMORY_FLAG_LRM|MAXMEMORY_FLAG_ALLKEYS)

/* Units */
#define UNIT_SECONDS 0
#define UNIT_MILLISECONDS 1

/* SHUTDOWN flags */
#define SHUTDOWN_NOFLAGS 0      /* No flags. */
#define SHUTDOWN_SAVE 1         /* Force SAVE on SHUTDOWN even if no save
                                   points are configured. */
#define SHUTDOWN_NOSAVE 2       /* Don't SAVE on SHUTDOWN. */
#define SHUTDOWN_NOW 4          /* Don't wait for replicas to catch up. */
#define SHUTDOWN_FORCE 8        /* Don't let errors prevent shutdown. */

/* Cluster slot stats flags */
#define CLUSTER_SLOT_STATS_CPU 1  /* Track CPU usage per slot. */
#define CLUSTER_SLOT_STATS_NET 2  /* Track network bytes per slot. */
#define CLUSTER_SLOT_STATS_MEM 4  /* Track memory usage per slot. */
#define CLUSTER_SLOT_STATS_ALL (CLUSTER_SLOT_STATS_CPU | CLUSTER_SLOT_STATS_NET | CLUSTER_SLOT_STATS_MEM)

/* IO thread pause status */
#define IO_THREAD_UNPAUSED      0
#define IO_THREAD_PAUSING       1
#define IO_THREAD_PAUSED        2
#define IO_THREAD_RESUMING      3

/* Command call flags, see call() function */
#define CMD_CALL_NONE 0
#define CMD_CALL_PROPAGATE_AOF (1<<0)
#define CMD_CALL_PROPAGATE_REPL (1<<1)
#define CMD_CALL_FROM_MODULE (1<<2)  /* From RM_Call */
#define CMD_CALL_PROPAGATE (CMD_CALL_PROPAGATE_AOF|CMD_CALL_PROPAGATE_REPL)
#define CMD_CALL_FULL (CMD_CALL_PROPAGATE)

/* Command propagation flags, see propagateNow() function */
#define PROPAGATE_NONE 0
#define PROPAGATE_AOF 1
#define PROPAGATE_REPL 2

/* Actions pause types */
#define PAUSE_ACTION_CLIENT_WRITE     (1<<0)
#define PAUSE_ACTION_CLIENT_ALL       (1<<1) /* must be bigger than PAUSE_ACTION_CLIENT_WRITE */
#define PAUSE_ACTION_EXPIRE           (1<<2)
#define PAUSE_ACTION_EVICT            (1<<3)
#define PAUSE_ACTION_REPLICA          (1<<4) /* pause replica traffic */

/* common sets of actions to pause/unpause */
#define PAUSE_ACTIONS_CLIENT_WRITE_SET (PAUSE_ACTION_CLIENT_WRITE|\
                                        PAUSE_ACTION_EXPIRE|\
                                        PAUSE_ACTION_EVICT|\
                                        PAUSE_ACTION_REPLICA)
#define PAUSE_ACTIONS_CLIENT_ALL_SET   (PAUSE_ACTION_CLIENT_ALL|\
                                        PAUSE_ACTION_EXPIRE|\
                                        PAUSE_ACTION_EVICT|\
                                        PAUSE_ACTION_REPLICA)

/* Client pause purposes. Each purpose has its own end time and pause type. */
typedef enum {
    PAUSE_BY_CLIENT_COMMAND = 0,
    PAUSE_DURING_SHUTDOWN,
    PAUSE_DURING_FAILOVER,
    PAUSE_DURING_SLOT_HANDOFF,
    NUM_PAUSE_PURPOSES /* This value is the number of purposes above. */
} pause_purpose;

typedef struct {
    uint32_t paused_actions; /* Bitmask of actions */
    mstime_t end;
} pause_event;

/* Ways that a clusters endpoint can be described */
typedef enum {
    CLUSTER_ENDPOINT_TYPE_IP = 0,          /* Show IP address */
    CLUSTER_ENDPOINT_TYPE_HOSTNAME,        /* Show hostname */
    CLUSTER_ENDPOINT_TYPE_UNKNOWN_ENDPOINT /* Show NULL or empty */
} cluster_endpoint_type;

/* RDB active child save type. */
#define RDB_CHILD_TYPE_NONE 0
#define RDB_CHILD_TYPE_DISK 1     /* RDB is written to disk. */
#define RDB_CHILD_TYPE_SOCKET 2   /* RDB is written to slave socket. */

/* Keyspace changes notification classes. Every class is associated with a
 * character for configuration purposes. */
#define NOTIFY_KEYSPACE (1<<0)    /* K */
#define NOTIFY_KEYEVENT (1<<1)    /* E */
#define NOTIFY_GENERIC (1<<2)     /* g */
#define NOTIFY_STRING (1<<3)      /* $ */
#define NOTIFY_LIST (1<<4)        /* l */
#define NOTIFY_SET (1<<5)         /* s */
#define NOTIFY_HASH (1<<6)        /* h */
#define NOTIFY_ZSET (1<<7)        /* z */
#define NOTIFY_EXPIRED (1<<8)     /* x */
#define NOTIFY_EVICTED (1<<9)     /* e */
#define NOTIFY_STREAM (1<<10)     /* t */
#define NOTIFY_KEY_MISS (1<<11)   /* m (Note: This one is excluded from NOTIFY_ALL on purpose) */
#define NOTIFY_LOADED (1<<12)     /* module only key space notification, indicate a key loaded from rdb */
#define NOTIFY_MODULE (1<<13)     /* d, module key space notification */
#define NOTIFY_NEW (1<<14)        /* n, new key notification (Note: excluded from NOTIFY_ALL) */
#define NOTIFY_OVERWRITTEN (1<<15)   /* o, key overwrite notification (Note: excluded from NOTIFY_ALL) */
#define NOTIFY_TYPE_CHANGED (1<<16) /* c, key type changed notification (Note: excluded from NOTIFY_ALL) */
#define NOTIFY_KEY_TRIMMED (1<<17)     /* module only key space notification, indicates a key trimmed during slot migration */
#define NOTIFY_ALL (NOTIFY_GENERIC | NOTIFY_STRING | NOTIFY_LIST | NOTIFY_SET | NOTIFY_HASH | NOTIFY_ZSET | NOTIFY_EXPIRED | NOTIFY_EVICTED | NOTIFY_STREAM | NOTIFY_MODULE) /* A flag */

/* Using the following macro you can run code inside serverCron() with the
 * specified period, specified in milliseconds.
 * The actual resolution depends on server.hz. */
#define run_with_period(_ms_) if (((_ms_) <= 1000/server.hz) || !(server.cronloops%((_ms_)/(1000/server.hz))))

/* We can print the stacktrace, so our assert is defined this way: */
#define serverAssertWithInfo(_c,_o,_e) (likely(_e)?(void)0 : (_serverAssertWithInfo(_c,_o,#_e,__FILE__,__LINE__),redis_unreachable()))
#define serverAssert(_e) (likely(_e)?(void)0 : (_serverAssert(#_e,__FILE__,__LINE__),redis_unreachable()))
#define serverPanic(...) _serverPanic(__FILE__,__LINE__,__VA_ARGS__),redis_unreachable()

/* The following macros provide assertions that are only executed during test builds and should be used to add
 * assertions that are too computationally expensive or dangerous to run during normal operations.  */
#ifdef DEBUG_ASSERTIONS
#define debugServerAssertWithInfo(...) serverAssertWithInfo(__VA_ARGS__)
#define debugServerAssert(...) serverAssert(__VA_ARGS__)
#else
#define debugServerAssertWithInfo(...)
#define debugServerAssert(...)
#endif

/* latency histogram per command init settings */
#define LATENCY_HISTOGRAM_MIN_VALUE 1L        /* >= 1 nanosec */
#define LATENCY_HISTOGRAM_MAX_VALUE 1000000000L  /* <= 1 secs */
#define LATENCY_HISTOGRAM_PRECISION 2  /* Maintain a value precision of 2 significant digits across LATENCY_HISTOGRAM_MIN_VALUE and LATENCY_HISTOGRAM_MAX_VALUE range.
                                        * Value quantization within the range will thus be no larger than 1/100th (or 1%) of any value.
                                        * The total size per histogram should sit around 40 KiB Bytes. */

/* Busy module flags, see busy_module_yield_flags */
#define BUSY_MODULE_YIELD_NONE (0)
#define BUSY_MODULE_YIELD_EVENTS (1<<0)
#define BUSY_MODULE_YIELD_CLIENTS (1<<1)

/* Key prefetch configs */
#define PREFETCH_BATCH_MAX_SIZE 128

/*-----------------------------------------------------------------------------
 * Data types
 *----------------------------------------------------------------------------*/

/* A redis object, that is a type able to hold a string / list / set */

/* The actual Redis Object */
#define OBJ_STRING 0    /* String object. */
#define OBJ_LIST 1      /* List object. */
#define OBJ_SET 2       /* Set object. */
#define OBJ_ZSET 3      /* Sorted set object. */
#define OBJ_HASH 4      /* Hash object. */
#define OBJ_TYPE_BASIC_MAX 5 /* Max number of basic object types. */

/* The "module" object type is a special one that signals that the object
 * is one directly managed by a Redis module. In this case the value points
 * to a moduleValue struct, which contains the object value (which is only
 * handled by the module itself) and the RedisModuleType struct which lists
 * function pointers in order to serialize, deserialize, AOF-rewrite and
 * free the object.
 *
 * Inside the RDB file, module types are encoded as OBJ_MODULE followed
 * by a 64 bit module type ID, which has a 54 bits module-specific signature
 * in order to dispatch the loading to the right module, plus a 10 bits
 * encoding version. */
#define OBJ_MODULE 5    /* Module object. */
#define OBJ_STREAM 6    /* Stream object. */
#define OBJ_TYPE_MAX 7  /* Maximum number of object types */

/* Extract encver / signature from a module type ID. */
#define REDISMODULE_TYPE_ENCVER_BITS 10
#define REDISMODULE_TYPE_ENCVER_MASK ((1<<REDISMODULE_TYPE_ENCVER_BITS)-1)
#define REDISMODULE_TYPE_ENCVER(id) ((id) & REDISMODULE_TYPE_ENCVER_MASK)
#define REDISMODULE_TYPE_SIGN(id) (((id) & ~((uint64_t)REDISMODULE_TYPE_ENCVER_MASK)) >>REDISMODULE_TYPE_ENCVER_BITS)

/* Bit flags for moduleTypeAuxSaveFunc */
#define REDISMODULE_AUX_BEFORE_RDB (1<<0)
#define REDISMODULE_AUX_AFTER_RDB (1<<1)

struct RedisModule;
struct RedisModuleIO;
struct RedisModuleDigest;
struct RedisModuleCtx;
struct moduleLoadQueueEntry;
struct RedisModuleCommand;
struct clusterState;
struct slotRangeArray;

/* Each module type implementation should export a set of methods in order
 * to serialize and deserialize the value in the RDB file, rewrite the AOF
 * log, create the digest for "DEBUG DIGEST", and free the value when a key
 * is deleted. */
typedef void *(*moduleTypeLoadFunc)(struct RedisModuleIO *io, int encver);
typedef void (*moduleTypeSaveFunc)(struct RedisModuleIO *io, void *value);
typedef int (*moduleTypeAuxLoadFunc)(struct RedisModuleIO *rdb, int encver, int when);
typedef void (*moduleTypeAuxSaveFunc)(struct RedisModuleIO *rdb, int when);
typedef void (*moduleTypeRewriteFunc)(struct RedisModuleIO *io, struct redisObject *key, void *value);
typedef void (*moduleTypeDigestFunc)(struct RedisModuleDigest *digest, void *value);
typedef size_t (*moduleTypeMemUsageFunc)(const void *value);
typedef void (*moduleTypeFreeFunc)(void *value);
typedef size_t (*moduleTypeFreeEffortFunc)(struct redisObject *key, const void *value);
typedef void (*moduleTypeUnlinkFunc)(struct redisObject *key, void *value);
typedef void *(*moduleTypeCopyFunc)(struct redisObject *fromkey, struct redisObject *tokey, const void *value);
typedef int (*moduleTypeDefragFunc)(struct RedisModuleDefragCtx *ctx, struct redisObject *key, void **value);
typedef size_t (*moduleTypeMemUsageFunc2)(struct RedisModuleKeyOptCtx *ctx, const void *value, size_t sample_size);
typedef void (*moduleTypeFreeFunc2)(struct RedisModuleKeyOptCtx *ctx, void *value);
typedef size_t (*moduleTypeFreeEffortFunc2)(struct RedisModuleKeyOptCtx *ctx, const void *value);
typedef void (*moduleTypeUnlinkFunc2)(struct RedisModuleKeyOptCtx *ctx, void *value);
typedef void *(*moduleTypeCopyFunc2)(struct RedisModuleKeyOptCtx *ctx, const void *value);
typedef int (*moduleTypeAuthCallback)(struct RedisModuleCtx *ctx, void *username, void *password, const char **err);

/* Module Entity ID: module type or keymeta. */
typedef struct ModuleEntityId {
    struct RedisModule *module;
    char name[10]; /* 9 bytes name + null term. Charset: A-Z a-z 0-9 _- */
    uint64_t id; /* Higher 54 bits of type ID + 10 lower bits of encoding ver. */
} ModuleEntityId;

/* The module type, which is referenced in each value of a given type, defines
 * the methods and links to the module exporting the type. */
typedef struct RedisModuleType {
    ModuleEntityId entity;  /* module data type name and ID. */
    moduleTypeLoadFunc rdb_load;
    moduleTypeSaveFunc rdb_save;
    moduleTypeRewriteFunc aof_rewrite;
    moduleTypeMemUsageFunc mem_usage;
    moduleTypeDigestFunc digest;
    moduleTypeFreeFunc free;
    moduleTypeFreeEffortFunc free_effort;
    moduleTypeUnlinkFunc unlink;
    moduleTypeCopyFunc copy;
    moduleTypeDefragFunc defrag;
    moduleTypeAuxLoadFunc aux_load;
    moduleTypeAuxSaveFunc aux_save;
    moduleTypeMemUsageFunc2 mem_usage2;
    moduleTypeFreeEffortFunc2 free_effort2;
    moduleTypeUnlinkFunc2 unlink2;
    moduleTypeCopyFunc2 copy2;
    moduleTypeAuxSaveFunc aux_save2;
    int aux_save_triggers;
} moduleType;

/* In Redis objects 'robj' structures of type OBJ_MODULE, the value pointer
 * is set to the following structure, referencing the moduleType structure
 * in order to work with the value, and at the same time providing a raw
 * pointer to the value, as created by the module commands operating with
 * the module type.
 *
 * So for example in order to free such a value, it is possible to use
 * the following code:
 *
 *  if (robj->type == OBJ_MODULE) {
 *      moduleValue *mt = robj->ptr;
 *      mt->type->free(mt->value);
 *      zfree(mt); // We need to release this in-the-middle struct as well.
 *  }
 */
typedef struct moduleValue {
    moduleType *type;
    void *value;
} moduleValue;

/* Describe the state of the module during loading, and the indication which configs were loaded / applied already. */
typedef enum {
    MODULE_CONFIGS_DEFAULTS = 0x1, /* The registered defaults were applied. */
    MODULE_CONFIGS_USER_VALS  = 0x2, /* The user provided values were applied. */
    MODULE_CONFIGS_ALL_APPLIED = 0x3 /* Both of the above applied. */
} ModuleConfigsApplied;

/* This structure represents a module inside the system. */
struct RedisModule {
    void *handle;   /* Module dlopen() handle. */
    char *name;     /* Module name. */
    int ver;        /* Module version. We use just progressive integers. */
    int apiver;     /* Module API version as requested during initialization.*/
    list *types;    /* Module data types. */
    list *usedby;   /* List of modules using APIs from this one. */
    list *using;    /* List of modules we use some APIs of. */
    list *filters;  /* List of filters the module has registered. */
    list *module_configs; /* List of configurations the module has registered */
    ModuleConfigsApplied configs_initialized; /* Have the module configurations been initialized? */
    int in_call;    /* RM_Call() nesting level */
    int in_hook;    /* Hooks callback nesting level for this module (0 or 1). */
    int options;    /* Module options and capabilities. */
    int blocked_clients;         /* Count of RedisModuleBlockedClient in this module. */
    RedisModuleInfoFunc info_cb; /* Callback for module to add INFO fields. */
    RedisModuleDefragFunc defrag_cb;    /* Callback for global data defrag. */
    RedisModuleDefragFunc2 defrag_cb_2; /* Version 2 callback for global data defrag. */
    RedisModuleDefragFunc defrag_start_cb;    /* Callback indicating defrag started. */
    RedisModuleDefragFunc defrag_end_cb;      /* Callback indicating defrag ended. */
    struct moduleLoadQueueEntry *loadmod; /* Module load arguments for config rewrite. */
    int num_commands_with_acl_categories; /* Number of commands in this module included in acl categories */
    int onload;     /* Flag to identify if the call is being made from Onload (0 or 1) */
    size_t num_acl_categories_added; /* Number of acl categories added by this module. */
};
typedef struct RedisModule RedisModule;

/* The defrag context, used to manage state during calls to the data type
 * defrag callback.
 */
struct RedisModuleDefragCtx {
    monotime endtime;
    unsigned long *cursor;
    struct redisObject *key; /* Optional name of key processed, NULL when unknown. */
    int dbid;                /* The dbid of the key being processed, -1 when unknown. */
    long long last_stop_check_hits; /* Number of defrag hits at last check. */
    long long last_stop_check_misses; /* Number of defrag misses at last check. */
    int stopping; /* Flag indicating if defrag should stop. */
};
#define INIT_MODULE_DEFRAG_CTX(endtime, cursor, key, dbid) \
    ((RedisModuleDefragCtx) {               \
        (endtime), (cursor), (key), (dbid), \
        server.stat_active_defrag_hits,     \
        server.stat_active_defrag_misses    \
    })

/* This is a wrapper for the 'rio' streams used inside rdb.c in Redis, so that
 * the user does not have to take the total count of the written bytes nor
 * to care about error conditions. */
struct RedisModuleIO {
    size_t bytes;       /* Bytes read / written so far. */
    rio *rio;           /* Rio stream. */
    ModuleEntityId *entity; /* Module type or keymeta doing the operation. */
    int error;          /* True if error condition happened. */
    struct RedisModuleCtx *ctx; /* Optional context, see RM_GetContextFromIO()*/
    struct redisObject *key;    /* Optional name of key processed */
    int dbid;            /* The dbid of the key being processed, -1 when unknown. */
    sds pre_flush_buffer; /* A buffer that should be flushed before next write operation
                           * See rdbSaveSingleModuleAux for more details */
};

/* Initialize an IO context. Note that the 'ver' field is populated
 * inside rdb.c according to the version of the value to load. */
static inline void moduleInitIOContext(RedisModuleIO *io, ModuleEntityId *entity,
                                       rio *rioptr, struct redisObject *keyptr, int db) 
{
    io->rio = rioptr;
    io->entity = entity;
    io->bytes = 0;
    io->error = 0;
    io->key = keyptr;
    io->dbid = db;
    io->ctx = NULL;
    io->pre_flush_buffer = NULL;
}

/* This is a structure used to export DEBUG DIGEST capabilities to Redis
 * modules. We want to capture both the ordered and unordered elements of
 * a data structure, so that a digest can be created in a way that correctly
 * reflects the values. See the DEBUG DIGEST command implementation for more
 * background. */
struct RedisModuleDigest {
    unsigned char o[20];    /* Ordered elements. */
    unsigned char x[20];    /* Xored elements. */
    struct redisObject *key; /* Optional name of key processed */
    int dbid;                /* The dbid of the key being processed */
};

/* Just start with a digest composed of all zero bytes. */
#define moduleInitDigestContext(mdvar) do { \
    memset(mdvar.o,0,sizeof(mdvar.o)); \
    memset(mdvar.x,0,sizeof(mdvar.x)); \
} while(0)

/* Macro to check if the client is in the middle of module based authentication. */
#define clientHasModuleAuthInProgress(c) \
    ((c)->has_exec_tail && clientTail(c)->cold && clientTail(c)->cold->module_auth_ctx != NULL)

/* The string name for an object's type as listed above
 * Native types are checked against the OBJ_STRING, OBJ_LIST, OBJ_* defines,
 * and Module types have their registered name returned. */
char *getObjectTypeName(robj*);

/* Macro used to initialize a Redis object allocated on the stack.
 * Note that this macro is taken near the structure definition to make sure
 * we'll update it when the structure is changed, to avoid bugs like
 * bug #85 introduced exactly in this way. */
#define initStaticStringObject(_var,_ptr) do { \
    _var.refcount = OBJ_STATIC_REFCOUNT; \
    _var.type = OBJ_STRING; \
    _var.encoding = OBJ_ENCODING_RAW; \
    _var.metabits = 0; \
    _var.iskvobj = 0; \
    _var.ptr = _ptr; \
    _var.vmeta = NULL; \
} while(0)

struct evictionPoolEntry; /* Defined in evict.c */

/* Encoded buffers contain headers followed by either plain replies or
 * by bulk string references */
typedef enum {
    PLAIN_REPLY = 0, /* plain reply */
    BULK_STR_REF     /* bulk string references */
} payloadType;

/* Encoded reply buffers consist of chunks
 * Each chunk contains header followed by payload
 * The packed attribute is specified because buffer is accessed at arbitrary offsets,
 * so no benefit in data structure padding and applying packed saves the space in the buffer  */
typedef struct __attribute__((__packed__)) payloadHeader {
    size_t payload_len;   /* payload length in a reply buffer */
    uint8_t payload_type; /* one of payloadType */
} payloadHeader;
static_assert(offsetof(payloadHeader, payload_len) == 0, "payload_len must be at offset 0 to avoid unaligned access");

/* To avoid copy of whole string in reply buffer
 * we store pointers to object and string itself */
typedef struct __attribute__((__packed__)) bulkStrRef {
    robj *obj; /* pointer to object used for reference count management */
    unsigned int prefix_cnt;
    char prefix[LONG_STR_SIZE + 3]; /* $<len>\r\n */
    char crlf[2]; /* \r\n */
    /* ee451 (S8): owning worker id for zero-copy fake replies, or -1 for a
     * normal client. When >= 0, the post-send decrRefCount is routed to that
     * worker via freebackPush (sole refcount mutator for its shard); when -1,
     * released inline / via ioDeferFreeRobj as before. */
    int owner_ex;
} bulkStrRef;

/* This structure is used in order to represent the output buffer of a client,
 * which is actually a linked list of blocks like that, that is: client->reply. */
typedef struct clientReplyBlock {
    size_t size, used;
    char buf_encoded;
    char buf[];
} clientReplyBlock;

/* Replication buffer blocks is the list of replBufBlock.
 *
 * +--------------+       +--------------+       +--------------+
 * | refcount = 1 |  ...  | refcount = 0 |  ...  | refcount = 2 |
 * +--------------+       +--------------+       +--------------+
 *      |                                            /       \
 *      |                                           /         \
 *      |                                          /           \
 *  Repl Backlog                               Replica_A    Replica_B
 *
 * Each replica or replication backlog increments only the refcount of the
 * 'ref_repl_buf_node' which it points to. So when replica walks to the next
 * node, it should first increase the next node's refcount, and when we trim
 * the replication buffer nodes, we remove node always from the head node which
 * refcount is 0. If the refcount of the head node is not 0, we must stop
 * trimming and never iterate the next node.
 *
 * For replicas in IO threads we don't update the refcount while sending the
 * repl data, but only when the client is sent back to main. This avoids data
 * races. In order to achieve this, the replicas keep track of following:
 * - io_curr_repl_node - the current node we've reached.
 * - io_bound_repl_node - the last node in the replication buffer as seen by
 *                        the replica client before it was sent to IO thread
 *
 * When the client is sent to IO thread for the first time io_curr_repl_node is
 * initialized with ref_repl_buf_node.
 * When the client is sent back to main it can decrement ref_repl_buf_node's
 * refcount and increment it for io_curr_repl_node, since all the nodes
 * in-between are already sent and the client doesn't hold reference to them.
 *
 * `io_bound_repl_node` is needed because IO thread needs to know when to stop
 * sending data. If it was reading directly from the replication buffer,
 * there will be a data race, because main thread may be writing to it during
 * `feedReplicationBuffer`. `io_bound_repl_node` is cached in the client
 * together with its used size just before sending the client to IO thread
 * in `enqueuePendingClienstToIOThreads`. */

/* Similar with 'clientReplyBlock', it is used for shared buffers between
 * all replica clients and replication backlog. */
typedef struct replBufBlock {
    int refcount;           /* Number of replicas or repl backlog using. */
    long long id;           /* The unique incremental number. */
    long long repl_offset;  /* Start replication offset of the block. */
    size_t size;            /* Capacity of the buf in bytes */
    size_t used;            /* Count of written bytes */
    char buf[];
} replBufBlock;

/* Redis database representation. There are multiple databases identified
 * by integers from 0 (the default database) up to the max configured
 * database. The database number is the 'id' field in the structure. */
typedef struct redisDb {
    kvstore *keys;              /* The keyspace for this DB. As metadata, holds keysizes histogram */
    kvstore *expires;           /* Timeout of keys with a timeout set */
    estore *subexpires;         /* Timeout of sub-keys with a timeout set. (Currently only used for hashes) */
    dict *blocking_keys;        /* Keys with clients waiting for data (BLPOP)*/
    dict *blocking_keys_unblock_on_nokey;   /* Keys with clients waiting for
                                             * data, and should be unblocked if key is deleted (XREADEDGROUP).
                                             * This is a subset of blocking_keys*/
    dict *stream_claim_pending_keys; /* Keys with clients waiting to claim pending entries */
    dict *stream_idmp_keys; /* Stream keys with IDMP tracking */
    dict *ready_keys;           /* Blocked keys that received a PUSH */
    dict *watched_keys;         /* WATCHED keys for MULTI/EXEC CAS */
    int id;                     /* Database ID */
    redisAtomic int initialized; /* Heavy fields above are ready for use. */
    long long avg_ttl;          /* Average TTL, just for stats */
    unsigned long expires_cursor; /* Cursor of the active expire cycle. */
} redisDb;

/* Database arrays keep their stable addresses because clients and workers retain
 * redisDb pointers. Only the expensive contents are initialized lazily. */
static inline int dbIsInitialized(redisDb *db) {
    int initialized;
    atomicGetAcquire(db->initialized, initialized);
    return initialized;
}

/* maximum number of bins of keysizes histogram */
#define MAX_KEYSIZES_BINS 60
#define MAX_KEYSIZES_TYPES 5 /* static_assert at db.c verifies == OBJ_TYPE_BASIC_MAX */
typedef int64_t keysizesHist[MAX_KEYSIZES_TYPES][MAX_KEYSIZES_BINS];

/* Metadata structure used for kvstores with type `kvstoreExType`, managed outside kvstore */
typedef struct {
    keysizesHist keysizes_hist;
    keysizesHist allocsizes_hist;
} kvstoreMetadata;

/* Like kvstoreMetadata, this one per dict */
typedef struct {
    kvstoreDictMetaBase base;   /* must be first in struct ! */
    size_t alloc_size;          /* Total memory used (in bytes) by this slot */
    uint64_t cpu_usec;          /* CPU time (in microseconds) spent on given slot */
    uint64_t network_bytes_in;  /* Network ingress (in bytes) received for given slot */
    uint64_t network_bytes_out; /* Network egress (in bytes) sent for given slot */
    keysizesHist keysizes_hist;
} kvstoreDictMetadata;

/* forward declaration for functions ctx */
typedef struct functionsLibCtx functionsLibCtx;

/* Holding object that need to be populated during
 * rdb loading. On loading end it is possible to decide
 * whether not to set those objects on their rightful place.
 * For example: dbarray need to be set as main database on
 *              successful loading and dropped on failure. */
typedef struct rdbLoadingCtx {
    redisDb* dbarray;
    functionsLibCtx* functions_lib_ctx;
}rdbLoadingCtx;

typedef struct pendingCommand pendingCommand;
typedef struct multiState {
    pendingCommand **commands;     /* Array of pointers to MULTI commands */
    int executing_cmd;      /* The index of the currently executed transaction 
                               command (index in commands field) */
    int count;              /* Total number of MULTI commands */
    int cmd_flags;          /* The accumulated command flags OR-ed together.
                               So if at least a command has a given flag, it
                               will be set in this field. */
    int cmd_inv_flags;      /* Same as cmd_flags, OR-ing the ~flags. so that it
                               is possible to know if all the commands have a
                               certain flag. */
    size_t argv_len_sums;    /* mem used by all commands arguments */
    int alloc_count;         /* total number of pendingCommand struct memory reserved. */
    list watched_keys;       /* Keys WATCHED for MULTI/EXEC CAS. */
} multiState;

/* This structure holds the blocking operation state for a client.
 * The fields used depend on client->btype. */
typedef struct blockingState {
    /* Generic fields. */
    blocking_type btype;                  /* Type of blocking op if CLIENT_BLOCKED. */
    mstime_t timeout;           /* Blocking operation timeout. If UNIX current time
                                 * is > timeout then the operation timed out. */
    int unblock_on_nokey;       /* Whether to unblock the client when at least one of the keys
                                   is deleted or does not exist anymore */
    /* BLOCKED_LIST, BLOCKED_ZSET and BLOCKED_STREAM or any other Keys related blocking */
    dict *keys;                 /* The keys we are blocked on */

    /* BLOCKED_WAIT and BLOCKED_WAITAOF */
    int numreplicas;        /* Number of replicas we are waiting for ACK. */
    int numlocal;           /* Indication if WAITAOF is waiting for local fsync. */
    long long reploffset;   /* Replication offset to reach. */

    /* BLOCKED_MODULE */
    void *module_blocked_handle; /* RedisModuleBlockedClient structure.
                                    which is opaque for the Redis core, only
                                    handled in module.c. */

    void *async_rm_call_handle; /* RedisModuleAsyncRMCallPromise structure.
                                   which is opaque for the Redis core, only
                                   handled in module.c. */

    /* BLOCKED_LAZYFREE */
    monotime lazyfreeStartTime;
} blockingState;

/* The following structure represents a node in the server.ready_keys list,
 * where we accumulate all the keys that had clients blocked with a blocking
 * operation such as B[LR]POP, but received new data in the context of the
 * last executed command.
 *
 * After the execution of every command or script, we iterate over this list to check
 * if as a result we should serve data to clients blocked, unblocking them.
 * Note that server.ready_keys will not have duplicates as there dictionary
 * also called ready_keys in every structure representing a Redis database,
 * where we make sure to remember if a given key was already added in the
 * server.ready_keys list. */
typedef struct readyList {
    redisDb *db;
    robj *key;
} readyList;

/* List of pending commands. */
typedef struct pendingCommandList {
    pendingCommand *head;
    pendingCommand *tail;
    int len; /* Number of commands in the list */
    int ready_len; /* Number of commands that are ready to be processed */
} pendingCommandList;

/* Pending command pool management structure */
#define PENDING_COMMAND_POOL_SIZE 16
#define PENDING_COMMAND_POOL_MAX_SIZE 1024
typedef struct pendingCommandPool {
    pendingCommand **pool;  /* Pool array for reusing pendingCommand objects */
    int size;               /* Current number of objects in pool */
    int capacity;           /* Current capacity of the pool array */
    int min_size;           /* Minimum size since last check (indicates peak usage) */
} pendingCommandPool;

/* This structure represents a Redis user. This is useful for ACLs, the
 * user is associated to the connection after the connection is authenticated.
 * If there is no associated user, the connection uses the default user. */
#define USER_COMMAND_BITS_COUNT 1024    /* The total number of command bits
                                           in the user structure. The last valid
                                           command ID we can set in the user
                                           is USER_COMMAND_BITS_COUNT-1. */
#define USER_FLAG_ENABLED (1<<0)        /* The user is active. */
#define USER_FLAG_DISABLED (1<<1)       /* The user is disabled. */
#define USER_FLAG_NOPASS (1<<2)         /* The user requires no password, any
                                           provided password will work. For the
                                           default user, this also means that
                                           no AUTH is needed, and every
                                           connection is immediately
                                           authenticated. */
#define USER_FLAG_SANITIZE_PAYLOAD (1<<3)       /* The user require a deep RESTORE
                                                 * payload sanitization. */
#define USER_FLAG_SANITIZE_PAYLOAD_SKIP (1<<4)  /* The user should skip the
                                                 * deep sanitization of RESTORE
                                                 * payload. */

#define SELECTOR_FLAG_ROOT (1<<0)           /* This is the root user permission
                                             * selector. */
#define SELECTOR_FLAG_ALLKEYS (1<<1)        /* The user can mention any key. */
#define SELECTOR_FLAG_ALLCOMMANDS (1<<2)    /* The user can run all commands. */
#define SELECTOR_FLAG_ALLCHANNELS (1<<3)    /* The user can mention any Pub/Sub
                                               channel. */

typedef struct {
    sds name;       /* The username as an SDS string. */
    redisAtomic uint32_t flags; /* See USER_FLAG_* */
    list *passwords; /* A list of SDS valid passwords for this user. */
    list *selectors; /* A list of selectors this user validates commands
                        against. This list will always contain at least
                        one selector for backwards compatibility. */
    robj *acl_string; /* cached string represent of ACLs */
} user;

/* With multiplexing we need to take per-client state.
 * Clients are taken in a linked list. */

#define CLIENT_ID_AOF (UINT64_MAX) /* Reserved ID for the AOF client. If you
                                      need more reserved IDs use UINT64_MAX-1,
                                      -2, ... and so forth. */

/* Replication backlog is not a separate memory, it just is one consumer of
 * the global replication buffer. This structure records the reference of
 * replication buffers. Since the replication buffer block list may be very long,
 * it would cost much time to search replication offset on partial resync, so
 * we use one rax tree to index some blocks every REPL_BACKLOG_INDEX_PER_BLOCKS
 * to make searching offset from replication buffer blocks list faster. */
typedef struct replBacklog {
    listNode *ref_repl_buf_node; /* Referenced node of replication buffer blocks,
                                  * see the definition of replBufBlock. */
    size_t unindexed_count;      /* The count from last creating index block. */
    rax *blocks_index;           /* The index of recorded blocks of replication
                                  * buffer for quickly searching replication
                                  * offset on partial resynchronization. */
    long long histlen;           /* Backlog actual data length */
    long long offset;            /* Replication "master offset" of first
                                  * byte in the replication backlog buffer.*/
} replBacklog;

/* Used by replDataBuf during rdb channel replication to accumulate replication
 * stream on replica side. */
typedef struct replDataBufBlock {
    size_t used; /* Used bytes in the buf */
    size_t size; /* Size of the buf */
    char buf[];  /* Replication data */
} replDataBufBlock;

/* Linked list of replDataBufBlock structs, holds replication stream during
 * rdb channel replication on replica side. */
typedef struct replDataBuf {
    list *blocks; /* List of replDataBufBlock */
    size_t mem_used; /* Total allocated memory */
    size_t size;  /* Total number of bytes available in all blocks. */
    size_t used;  /* Total number of bytes actually used in all blocks. */
    size_t peak;  /* Peak number of bytes stored in all blocks. */
    size_t last_num_blocks; /* Used to verify we consume more than we read from
                             * the master connection while streaming buffer to
                             * the db. */
} replDataBuf;

#define DEFERRED_OBJECT_TYPE_PENDING_COMMAND 1
#define DEFERRED_OBJECT_TYPE_ROBJ 2
/* Structure to hold objects that need to be freed later by IO threads.
 * This allows the main thread to defer memory cleanup operations to
 * IO threads to avoid blocking the main event loop. */
typedef struct deferredObject {
    int type;    /* Pointer to the object to be freed */
    void *ptr;   /* Type of object: DEFERRED_OBJECT_TYPE_* */ 
} deferredObject;

#define SHOULD_CLUSTER_COMPATIBILITY_SAMPLE() \
            (server.cluster_compatibility_sample_ratio == 100 || \
             (double)rand()/RAND_MAX * 100 < server.cluster_compatibility_sample_ratio)

#ifdef LOG_REQ_RES
/* Structure used to log client's requests and their
 * responses (see logreqres.c) */
typedef struct {
    /* General */
    int argv_logged; /* 1 if the command was logged */
    /* Vars for log buffer */
    unsigned char *buf; /* Buffer holding the data (request and response) */
    size_t used;
    size_t capacity;
    /* Vars for offsets within the client's reply */
    struct {
        /* General */
        int saved; /* 1 if we already saved the offset (first time we call addReply*) */
        /* Offset within the static reply buffer */
        size_t bufpos;
        /* Offset within the reply block list */
        struct {
            int index;
            size_t used;
        } last_node;
    } offset;
} clientReqResInfo;
#endif
//ee451

/* =========================================================================
 * Tomo KV-dev custom threading & pipelining system.
 *
 * This fork removes stock Redis 6+ upstream I/O threads entirely
 * (`handleClientsWithPending*UsingThreads`, `io_threads_op`, etc. are gone).
 * The stock `io-threads` redis.conf directive still exists in config.c for
 * parse-compat but is inert — `server.io_threads_num` is never read.
 *
 * The live system is:
 *   - Custom IO threads: N threads sharing a SO_REUSEPORT listening socket;
 *     each owns a set of clients and its own event loop. Count configured
 *     via `tomokv-thread-io` -> server.io_threads (default 8, max
 *     TOMO_IO_THREADS_MAX).
 *   - Worker threads: M threads executing GET/SET/DEL on per-worker DB
 *     replicas. Count configured via `tomokv-thread-ex` ->
 *     server.ex_threads (default 3, max TOMO_EX_THREADS_MAX).
 *   - Per-client fake-client ring for pipelining. Depth configured via
 *     `tomokv-pipeline-depth` -> server.pipeline_ring_depth (default 16,
 *     max TOMO_PIPELINE_DEPTH_MAX (currently 32). Must be a power of two.
 *
 * Static arrays are sized by the compile-time MAX; loop bounds and slot
 * masks use the runtime server.my_* values so the build is stable while
 * actual resource usage scales with config. Each client's c->ring_mask is
 * derived from its current ring size because rings grow and decay independently.
 * ========================================================================= */

/* Compile-time maxes: bound array sizes in struct redisServer / client.
 * ee451 #83 (2026-08-05): RAISED 32/64 -> 128/128 after clearing every wall the raise touched:
 *   - lanes (802KB/worker inline) -> heap-sized to the runtime pool (initExThreads), so cap 128
 *     costs the same as cap 32 at a given thread count; heap-FAST (WQ hoist + exQueueFor TLS base)
 *     makes it perf-flat vs inline (measured +-0.4% instr/op io4ex4).
 *   - q_summary -> q_summary[TOMO_QS_WORDS]; TOMO_QS_WORDS = 3 at cap 128 and
 *     workers exchange only the runtime-live words before walking set bits.
 *   - ex_dirty_mask -> uint64 WORD ARRAY (TOMO_EX_MASK_WORDS); consume loop bounded by live words.
 *   - QSBR grace io_snap / io_pin_mask -> WORD ARRAY (TOMO_IO_MASK_WORDS), full-cleared on close
 *     (pool-recycled headers must not inherit a stale high-word bit -> premature-free/leak).
 *   - TOMO_SCAN_WORKER_BITS = 8 already encodes worker indices 0..255, so 128 workers fit with a
 *     spare bit; that wall is only reached past 256.
 * "Pay only when thread values need it": every widened path (masks, q_summary) iterates
 * (live+63)/64 == 1 word while <=64 slots are live, so a normal small-thread boot runs the exact
 * pre-#83 single-word code. The only unconditional cost is ~100KB of extra per-slot stat arrays in
 * the single redisServer instance (97->257 slots), noise against a multi-GB server. */
#define TOMO_IO_THREADS_MAX 128
#define TOMO_EX_THREADS_MAX 128

/* ee451 D (2026-08-05): static cost class, stamped once at populateCommandTable. C0/C1 are the
 * point ops (read/write split because GET/SET dominate), C2 bounded-element container ops, C3
 * range/aggregate (O(n) reply). The class picks the BUCKET; the per-class dynamic svc EWMA
 * supplies the MAGNITUDE (this is what separates 64B from 64KB regimes). */
/* ee451 #89: SIX cost classes (was 4). The reorder SJF sorts by these, so finer tiers isolate the
 * genuinely-expensive commands (full scans, 16MB GETRANGE) from the merely-medium ones instead of
 * lumping every range op into one bucket. Class is now 3 bits (tomo_cls & 0x07, values 0..5); the
 * argv-range flag moved to bit 3 (0x08); head-of-pipe stays bit 7 (0x80). Ordering low->high is
 * cheapest->dearest, which is exactly the emit order. */
#define TOMO_SVC_CLASSES 6
#define TOMO_CLS_PREAD  0   /* very-short read  (GET, EXISTS, TTL, STRLEN)                ~20us */
#define TOMO_CLS_PWRITE 1   /* very-short write (SET, INCR, DEL, EXPIRE)                  ~20us */
#define TOMO_CLS_ELEM   2   /* bounded 1-elem container op + tiny bounded range (<=16)    ~20-60us */
#define TOMO_CLS_SMALL  3   /* small bounded range (<=256 elems)                          ~100-500us */
#define TOMO_CLS_MED    4   /* medium range (<=4096) + medium whole-collection reads      ~0.5-4ms */
#define TOMO_CLS_BIG    5   /* large/unbounded range + heavy whole-collection (SORT/SCAN) ~4-44ms */
#define TOMO_CLS_RANGE  TOMO_CLS_BIG      /* back-compat alias: the default "range" tier is the big one */
#define TOMO_CLS_MASK   0x07              /* 3 bits of class */
/* bit 3: this range command's argv[2],argv[3] are an index window (ZRANGE/ZREVRANGE/LRANGE/GETRANGE);
 * tomoArgvClass parses it and demotes the static C5 to the size-appropriate tier. */
#define TOMO_CLS_ARGV_RANGE 0x08
#define TOMO_RORD_TIER_ELEM  16    /* argv range <= this => C2 ELEM  */
#define TOMO_RORD_TIER_SMALL 256   /* <= this => C3 SMALL */
#define TOMO_RORD_TIER_MED   4096  /* <= this => C4 MED; else C5 BIG. getrange window is /64 (bytes->elems) */
/* DEBUG TOMO-RORDMASK: independently ablate the passes in the reorder stack. */
#define TOMO_RORD_MASK_WORKER_GROUP 0x01
#define TOMO_RORD_MASK_AGE_SLICE    0x02
#define TOMO_RORD_MASK_DEP_FENCE    0x04
#define TOMO_RORD_MASK_HEAD_PROMO   0x08
#define TOMO_RORD_MASK_CLASS_SJF    0x10
#define TOMO_RORD_MASK_BUCKET_GROUP 0x20
#define TOMO_RORD_MASK_ALL          0x3F
/* Shinjuku (reorder mode 3) per-class service-time proxy (relative). argmax(wait/SLO) => a short
 * class (small SLO) outranks a long one until the long one has waited proportionally longer.
 * Monotonic in class; values are relative, calibrate later. */
static const uint32_t TOMO_CLS_SLO[TOMO_SVC_CLASSES] = { 1, 1, 4, 64, 1024, 16384 };
/* ee451 (#B2): the iotid slot space — 0 = main, 1..io_threads-1 (+ flip growth slots) = IO
 * threads, TOMO_IO_THREADS_MAX+1+wid = worker wid. Every per-thread stats array (kstat, cmdstat,
 * netstat, errstat, cmdstat_percmd) is dimensioned by it; spelled once so they cannot drift. */
#define TOMO_STAT_SLOTS (TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX)
/* Max value of tomokv-nodes. The per-node liveness arrays (tm_node_wlive/tm_node_iolive) are
 * [16], so this is a hard array bound, not a policy. */
#define TOMO_NODES_MAX 16

/* ---- tomokv-thread-mode (IMMUTABLE enum) ------------------------------------
 * ONE knob for the io/ex split policy. tomokv-thread-io / tomokv-thread-ex give the STARTING
 * split in BOTH modes; the mode only decides whether the controller may move away from it.
 *   auto   — the flip controller / quorum balancer may shift the io<->ex boundary at runtime.
 *   static — the boot split is held for the life of the process (reproducible measurement). */
#define TOMO_THREAD_MODE_AUTO   0
#define TOMO_THREAD_MODE_STATIC 1

/* ---- IO-utilisation observations -------------------------------------------
 * tmIoSignal.tm_work_us is explicitly bracketed productive IO work and is the ratio
 * controller's numerator. tm_busy_us retains sampled scheduled CPU for diagnostics only because
 * drain spin and short polls burn CPU without producing work. tm_idle_us supplies the separate
 * zero-event occupancy operand for the CLI/SRV demand gate; tm_wait_us remains diagnostic.
 * Neither occupancy nor CPU enters the productive direction ratio. */

/* ---- tomokv-pin-mode (IMMUTABLE enum) ---------------------------------------
 * Decides BOTH how threads are placed AND what a "node" (tomokv-nodes) means:
 *   float  — no pinning at all; the scheduler places threads. A node is a pure logical shard
 *            group (no placement meaning).
 *   ccd    — a node owns one shared-L3 group, or adjacent sorted-L3 groups when its width exceeds
 *            one group's physical cores. Threads alternate groups within a multi-group node and
 *            use SMT siblings only after exhausting physical cores. DEFAULT.
 *   numa   — a node is a NUMA node. Threads are packed per NUMA node.
 *   static — placement comes verbatim from tomokv-pin-io / tomokv-pin-ex (per role per node).
 * WHICH PARTITIONING IS BETTER (ccd vs numa) IS AN OPEN QUESTION on the target hardware; it is
 * answered by measurement on the EPYC/Threadripper box, which is exactly why it is one knob. */
#define TOMO_PIN_FLOAT  0
#define TOMO_PIN_CCD    1
#define TOMO_PIN_NUMA   2
#define TOMO_PIN_STATIC 3

/* Roles for the static per-role-per-node pin specs. */
#define TOMO_PIN_ROLE_IO 0
#define TOMO_PIN_ROLE_EX 1

#define TOMO_PIPELINE_DEPTH_MAX 32  /* fixed upper bound for the per-client fake/ready-slot arrays */
/* ee451 (v8): virtual-bucket indirection for key->shard. bucket = hash & TOMO_BUCKET_MASK
 * (TOMO_BUCKETS is a power of two so indexing stays a single AND), worker =
 * ex_bucket_table[bucket]. This (a) lifts the power-of-two WORKER-count limit (any
 * number of workers can own buckets) while keeping xxhash, and (b) is the foundation for
 * adaptive resharding: each worker owns a CONTIGUOUS bucket range, so rebalancing only
 * shifts a boundary between adjacent workers. The table ELEMENT is a worker id (<= 64,
 * TOMO_EX_THREADS_MAX), so it stays uint8_t regardless of bucket count; only the array
 * LENGTH scales with TOMO_BUCKETS. 16384 buckets = 16KB uint8_t table, still small/L2, and
 * 16384 == kvstore's native cluster-slot count so the shared-keyspace kvstore (one dict per
 * bucket) reuses kvstore's per-slot machinery directly. Finer buckets = smoother rebalance. */
#define TOMO_BUCKETS 16384
#define TOMO_BUCKET_MASK (TOMO_BUCKETS - 1)
/* ee451 (flatstore lb): coarse per-node load-tracking GROUPS for minimal-perturbation balancing.
 * A group aggregates (TOMO_BUCKETS/TOMO_LB_GROUPS) contiguous buckets. Per-worker relaxed counters
 * per group (single-writer = the owning worker) give the balancer per-GROUP load (sum over workers)
 * and per-WORKER load (sum over its groups) at 1Hz, cheaply (256*4B = 1KB/worker, L1-resident). The
 * balancer moves the minimal set of groups to reach a tolerance band instead of chasing the hottest.
 * 64 buckets/group at 16384 => granular enough to place load on any worker without per-bucket cost. */
#define TOMO_LB_GROUPS 256
#define TOMO_LB_GROUP_BUCKETS (TOMO_BUCKETS / TOMO_LB_GROUPS)
#define TOMO_LB_GROUP(bkt) ((unsigned)(bkt) / TOMO_LB_GROUP_BUCKETS)
/* ee451 (2026-07-28): SECOND LEVEL — a small ARMED per-BUCKET window inside one group.
 * WHY A SECOND LEVEL EXISTS. 64 buckets per group is the right granularity for "which part of this
 * shard is warm", and it is deliberately coarse so the counter array stays L1-resident. It is the
 * WRONG granularity for the balancer's hot-KEY veto: a single hot key is a single BUCKET, and
 * averaged over its 64 group-mates it looks exactly like 64 mildly-warm buckets — i.e. like
 * something a bucket flip could divide. Group counters therefore cannot make that veto engage, and
 * measured runs confirmed it never did.
 * WHY NOT JUST 16384 COUNTERS. Per-bucket counters for the whole table are 64KB/worker. The
 * increment is the same one instruction, but the hash-random working set grows 64x (1KB L1 -> 64KB,
 * past this core's L1d), and always-on load-balancing machinery on this fork has a <=3% throughput
 * budget. The veto's question is LOCAL — "is THIS candidate group's load one bucket or many?" — so
 * only one group needs resolution, and which group that is (the shard's hottest) is already known
 * from level 1. So the fine window is 64 counters, pointed by the 1 Hz balancer at the worker's own
 * hottest group and armed only when that group is genuinely concentrated.
 * The window is published as ONE 64-bit word (len<<32 | lo) so the worker reads a consistent pair
 * in a single relaxed load; len == 0 (the zcalloc state) means DISARMED and the data path pays one
 * never-taken, perfectly-predicted branch. */
#define TOMO_LB_FINE_WIN(lo, len) (((uint64_t)(uint32_t)(len) << 32) | (uint32_t)(lo))
/* ee451 (shared-kv S0.2a): kvstore dict-count bits for tomo sharding. dict index == ownership
 * bucket == xxh64(key) & TOMO_BUCKET_MASK — the SAME value ex_bucket_table keys on — so each
 * bucket-dict has exactly one owning worker (single-writer preserved at bucket granularity).
 * 14 bits == 16384 == kvstore's native cluster-slot configuration (well-tested path). */
#define TOMO_BUCKET_BITS 14
/* Top-level SCAN over non-shared (DICT-backed) worker DBs uses one opaque cursor across the
 * worker-owned kvstores. kvstoreScan already stores its 14-bit bucket/dict index in the low bits;
 * place the worker id immediately above it and leave the remaining 42 bits to dictScan's cursor.
 * A 42-bit cursor still addresses a table far beyond any supported key count, while keeping each
 * slice on its owning worker (a worker must never traverse another worker's dict). */
#define TOMO_SCAN_WORKER_BITS 8
#define TOMO_SCAN_WORKER_SHIFT TOMO_BUCKET_BITS
#define TOMO_SCAN_DICT_SHIFT (TOMO_BUCKET_BITS + TOMO_SCAN_WORKER_BITS)
#define TOMO_SCAN_WORKER_MASK ((1ULL << TOMO_SCAN_WORKER_BITS) - 1)
/* ee451 review: single-writer stat-counter idiom. Each such counter has exactly ONE writer
 * thread, so a relaxed load+store pair (NOT atomic_fetch_add — that is a lock'd RMW) compiles
 * to plain mov/add on x86-64: zero hot-path cost, while cross-thread readers get defined,
 * untorn values instead of the previous plain-access C data race (UB; torn 32-bit halves on
 * ILP32 targets could wrap a rate delta by ~2^32 and false-trigger the reshard balancer). */
#define tomoRelaxedBump(field, delta) \
    atomic_store_explicit(&(field), \
        atomic_load_explicit(&(field), memory_order_relaxed) + (delta), memory_order_relaxed)
#define tomoRelaxedRead(field) atomic_load_explicit(&(field), memory_order_relaxed)
#define tomoRelaxedSet(field, v) atomic_store_explicit(&(field), (v), memory_order_relaxed)

#define PIPELINE_DEPTH 16 /* default; runtime value lives in server.pipeline_ring_depth */
#define PIPELINE_QUEUE_MASK (PIPELINE_DEPTH - 1) /* kept for back-compat; prefer c->ring_mask */
/* ee451 (S5/atomics): multi-CDB reply signaling. Each CDB owns one independent
 * atomic byte per fake-ring slot and occupies exactly one cache line. A worker
 * release-stores 1 to the captured (cdb,slot); the owning IO thread acquire-loads
 * that exact byte and relaxed-stores 0 after consuming it.
 *
 * The old representation packed all slots into one uint32_t. Setting or clearing
 * one logical bit then required a locked fetch_or/fetch_and because other workers
 * could concurrently change other bits in the word. Separate atomic objects make
 * the real ownership visible: for one slot there is one completer and one drainer,
 * and slot reuse cannot begin until that drainer has cleared it. CDB cache-line
 * partitioning remains, so workers mapped to different CDBs still avoid sharing a
 * completion line. */
#define NUM_CDB_MAX 256
typedef struct cdbSlots {
    redisAtomic uint8_t ready[TOMO_PIPELINE_DEPTH_MAX];
    char _pad[CACHE_LINE_SIZE -
              sizeof(redisAtomic uint8_t) * TOMO_PIPELINE_DEPTH_MAX];
} __attribute__((aligned(CACHE_LINE_SIZE))) cdbSlots;
_Static_assert(sizeof(redisAtomic uint8_t) == 1,
               "reply-ready atomics must occupy one byte");
_Static_assert(ATOMIC_CHAR_LOCK_FREE == 2,
               "reply-ready byte atomics must always be lock-free");
_Static_assert(sizeof(cdbSlots) == CACHE_LINE_SIZE,
               "each reply CDB must occupy exactly one cache line");

/* ---- R1 own-read gate: exact key sets ---------------------------------------------------
 * Per-group / per-read key hashes retained for the EXACT disjointness test (csKeysCollide).
 * Past this many written keys a group's own 64-bit signature is >= 16 of 64 bits, i.e. the
 * filter is >= 91% false-positive anyway and the group's inline region is already spilling, so
 * it stays filter-only and every filter hit against it HOLDS (charged to ownread_conserv). */
#define CS_EXACT_KEYS_MAX 16

/* One completed-but-not-yet-published group's key set, COPIED off the group at the moment it
 * leaves the connection's R1 FIFO (csMsetPopComplete) and dropped when its pending count is
 * decremented (csMsetPubRetire). Between those two points the group is invisible to the FIFO
 * walk while it still counts as pending, and the walk used to have no choice but to hold; this
 * record is what lets it answer exactly instead. It is a COPY, not a pointer: csReassemble
 * frees the group (and csgFree()s g->key_h) as soon as the head's reply slot is published,
 * which happens INSIDE that window.
 *
 * `tag` is the group's address, kept for identity only — the record is retired in FIFO order
 * and the tag asserts that discipline. It is NEVER dereferenced: by then the group may be gone. */
typedef struct csPubRec {
    uintptr_t tag;                    /* the csGroup this record stands for; compare, never deref */
    uint64_t key_sig;                 /* copy of csGroup.key_sig */
    int key_h_n;                      /* copy of csGroup.key_h_n; 0 => filter-only (conservative) */
    uint64_t key_h[CS_EXACT_KEYS_MAX];/* copy of csGroup.key_h[0..key_h_n) */
} csPubRec;

/* FIFO ring of the above, one per connection that has ever registered an atomic group (lazily
 * allocated in csMsetRegister, so a server with tomokv-atomic off never allocates one).
 *
 * SIZED FROM THE STRUCTURAL BOUND, not from a guess. Every registered group owns a fake-ring
 * slot from dispatch until csReassemble, and the pending-count decrement happens BEFORE that
 * reassembly, so
 *     concurrently detached <= mset_pending_count <= dispatchid - flushid
 *                           <= c->ring_size <= server.pipeline_ring_depth <= 32,
 * where tomokv-pipeline-depth is IMMUTABLE_CONFIG and therefore fixed boot->shutdown. Rounding
 * that up to a power of two makes the ring provably impossible to overflow, at a cost of
 * (depth * 152) bytes for a connection whose fake ring already holds `depth` fakes with a 16KB
 * reply buffer each — i.e. ~1% of the ring it is sized from.
 *
 * Overflow nevertheless remains SAFE and self-healing, and the check stays: a group that finds
 * the ring full gets no record, the walk then sees pending > (linked + recorded) and takes the
 * same conservative hold it always took, counted in ownread_conserv. That arm is now unreachable
 * by the argument above, which makes any non-zero conserv on a plain MGET/MSET cell a report
 * that the argument is wrong — the cheap insurance, same as the retire's tag assert. */
typedef struct csMsetPub {
    unsigned int head, tail;          /* FIFO cursors; (tail - head) records live, wrap is fine */
    unsigned int mask;                /* capacity - 1; capacity is a power of two >= pipeline depth */
    csPubRec rec[];                   /* [mask + 1] */
} csMsetPub;

struct tomoUringClient;
typedef struct client client;

/* Rare client state lives behind one nullable sidecar. The regular request,
 * dispatch and reply paths must not allocate it. Individual subsystems use
 * the initialized bits so, for example, CLIENT TRACKING does not also create
 * the blocking-key dictionary. */
#define CLIENT_COLD_PUBSUB  (1U << 0)
#define CLIENT_COLD_REPL    (1U << 1)
#define CLIENT_COLD_BLOCKED (1U << 2)

typedef struct clientCold {
    unsigned int initialized;

    /* MULTI/EXEC and WATCH. Commands remain NULL until first queued. */
    multiState mstate;

    /* Blocking commands. bstate.keys is created only when blocking starts. */
    blockingState bstate;

    /* Pub/Sub and client-side caching/tracking. */
    dict *pubsub_channels;
    dict *pubsub_patterns;
    dict *pubsubshard_channels;
    uint64_t client_tracking_redirection;
    rax *client_tracking_prefixes;

    /* Replication-only connection state. reploff_next and woff deliberately
     * remain inline in client: both are touched by ordinary command handling. */
    int replstate;
    int repl_start_cmd_stream_on_ack;
    int repldbfd;
    off_t repldboff;
    off_t repldbsize;
    sds replpreamble;
    long long read_reploff;
    long long io_read_reploff;
    long long reploff;
    long long repl_applied;
    long long repl_ack_off;
    long long repl_aof_off;
    long long repl_ack_time;
    long long io_repl_ack_time;
    long long repl_last_partial_write;
    long long psync_initial_offset;
    char replid[CONFIG_RUN_ID_SIZE+1];
    int slave_listening_port;
    char *slave_addr;
    int slave_capa;
    int slave_req;
    uint64_t main_ch_client_id;
    listNode *ref_repl_buf_node;
    size_t ref_block_pos;
    listNode *io_curr_repl_node;
    size_t io_curr_block_pos;
    listNode *io_bound_repl_node;
    size_t io_bound_block_pos;
    mstime_t io_last_repl_cron;

    /* Module authentication / blocked-client bookkeeping. */
    void *module_blocked_client;
    void *module_auth_ctx;
    RedisModuleUserChangedFunc auth_callback;
    void *auth_callback_privdata;
    void *auth_module;

    /* BLOCKED_POSTPONE membership belongs to the blocking subsystem. */
    listNode *postponed_list_node;
} clientCold;

#ifdef LOG_REQ_RES
#define CLIENT_EXEC_TAIL_BYTES 904
#else
#define CLIENT_EXEC_TAIL_BYTES 840
#endif

/* State which is never required by the plain GET/SET execution lane. The byte
 * member fixes the allocation contract; grouping by alignment leaves reserve
 * for field growth without moving the 320-byte execution core. */
typedef union clientExecTail {
    struct {
        /* Keep the CDB pointer at full-client offset 320. Its pointee remains
         * cache-line isolated; this split must not add a dependent load to the
         * EX->IO completion publication path. */
        cdbSlots *reply_cdb;
        /* Connection-owned controller state. A fake never owns another fake
         * ring, which is the four-line hole removed by the core allocation. */
        client *fakeClients[TOMO_PIPELINE_DEPTH_MAX];
        struct csGroup *mset_pending_head;
        struct csGroup *mset_pending_tail;
        struct csMsetPub *mset_pub;
        uint64_t mset_next_install_order; /* ownread: connection-global order reserved at R1 registration */
        double fake_ring_hwm_ewma;
        _Atomic int *drain_ack;
        uint64_t drain_fence_gen; /* ee451 O1: fence_gen this drain sentinel was pushed under; worker A
                                   * acks its slot only if this still equals the live fence_gen, so a
                                   * stale sentinel left by an aborted prior fence cannot forge a drain. */
        listNode *mig_parked_node;
        listNode *atomic_window_parked_node;
        uint64_t id;
        robj *name;
        robj *lib_name;
        robj *lib_ver;
        sds querybuf;
        size_t qb_pos;
        size_t querybuf_peak;
        robj **original_argv;
        deferredObject *deferred_objects;
        robj **io_deferred_objects;
        struct redisCommand *lastcmd;
        struct redisCommand *lookedcmd;
        struct redisCommand *realcmd;
        long bulklen;
        list *deferred_reply_errors;
        time_t ctime;
        long duration;
        dictEntry *cur_script;
        time_t lastinteraction;
        time_t io_lastinteraction;
        time_t obuf_soft_limit_reached_time;
        mstime_t io_last_client_cron;
        long long reploff_next;
        long long woff;
        sds peerid;
        sds sockname;
        listNode *client_list_node;
        listNode *io_thread_client_list_node;
        size_t last_memory_usage;
        listNode clients_pending_ex_node;
        listNode clients_pending_write_node;
        listNode pending_ref_reply_node;
        mstime_t buf_peak_last_reset_time;
        unsigned long long net_input_bytes;
        unsigned long long net_output_bytes;
        struct asmTask *task;
        char *node_id;
        struct tomoFlushBar *flush_bar;
        clientCold *cold;
        struct tomoUringClient *uring;
#ifdef LOG_REQ_RES
        clientReqResInfo reqres;
#endif

        unsigned int dispatchid;
        unsigned int flushid;
        unsigned int fake_ring_cur_depth;
        unsigned int ring_size;
        unsigned int ring_mask;
        unsigned int ring_want_grow;
        unsigned int cs_barrier;
        redisAtomic int mset_pending_lock;
        redisAtomic int mset_drain_latch;
        redisAtomic unsigned int mset_pending_count;
        redisAtomic int mset_read_waiting;
        unsigned int fake_ring_decay_skip;
        unsigned int fake_ring_hwm_win;
        int cssub_idx;
        int is_flush;
        int flush_dbid;
        int flush_async;
        int mig_parked_tid;
        int atomic_window_parked_tid;
        int original_argc;
        int deferred_objects_num;
        int io_deferred_objects_num;
        int io_deferred_objects_size;
        int reqtype;
        int multibulklen;
        int last_memory_type;
        redisAtomic int pending_read;
        uint8_t read_error;
        /* p1direct per-conn mode state. All three are io-owner-written plain bytes:
         * p1d_mode/p1d_streak are only ever touched by the owning io thread; p1d_inflight
         * is set by the owner before the dispatch publish and cleared after the completion
         * consume, so the worker-side phase-trace peek that reads it does so strictly
         * inside the window where its value is 1 (race-free by publication order). They
         * occupy the alignment hole after read_error — tail size unchanged. */
        uint8_t p1d_mode;       /* TOMO_P1D_DIRECT (boot default) | TOMO_P1D_FC */
        uint8_t p1d_inflight;   /* 1 while a DIRECT dispatch is in flight on ex */
        uint8_t p1d_streak;     /* consecutive clean singleton rounds while in FC (saturating) */
        /* IO-owned provenance for mode-2 cross-node reply prefetch. A bit is
         * set when any worker producing this ring generation is remote. */
        uint32_t prefetch_io_xnode_slots;
        /* Selected successful socket/CQE receive observation. Its P1 command
         * consumes this t0 into the pending-command handoff record. */
        uint64_t phase_recv_us;
        /* Debug phase tracing: packed (origin node, t4 monotonic usec) for the
         * one sampled P1 reply waiting for its first successful send. */
        uint64_t phase_send_stamp;
    };
    unsigned char _layout[CLIENT_EXEC_TAIL_BYTES];
    uint64_t _align;
} clientExecTail;

/* The worker/IO handoff object is exactly five 64-byte layout regions. A full
 * client appends one tail in the same allocation; an express fake omits it. */
typedef struct client {
    union {
        struct {
            int isFake;
            uint8_t tid;
            uint8_t running_tid;
            uint8_t io_flags;
            uint8_t buf_encoded;
            client *parent;
            uint64_t flags;
            connection *conn;
            redisDb *db;
            user *user;
            struct redisCommand *cmd;
            robj **argv;

            list *reply;
            char *buf;
            pendingCommandList pending_cmds;
            pendingCommand *current_pending_cmd;
            struct csGroup *csgroup;
            struct csGroup *csparent;

            payloadHeader *last_header;
            uint64_t prefetch_key_hash;
            dict *prefetch_dict;
            /* Strict-order consumes arrival_us before the prefetch pass writes
             * its bucket look-ahead. The two values cannot be live together. */
            union {
                unsigned long prefetch_bucket_idx;
                uint64_t arrival_us;
            };
            const void *tomo_bkt_ptr;
            uint64_t tomo_key_h;
            uint64_t tomo_read_snapshot;
            uint64_t tomo_read_snapshot_gen;   /* dispatch group-pin close generation */

            unsigned long long reply_bytes;
            size_t sentlen;
            size_t net_input_bytes_curr_cmd;
            size_t net_output_bytes_curr_cmd;
            size_t buf_peak;
            size_t bufpos;
            size_t buf_usable_size;
            unsigned long long commands_processed;

            unsigned int tomo_read_snapshot_pinned;
            unsigned int fake_slot;
            int cdb;
            int prefetch_key_hash_valid;
            int resp;
            int argc;
            int argv_len;
            int authenticated;
            int slot;
            int cluster_compatibility_check_slot;
            int tomo_bkt;
            int16_t tomo_local_worker;
            uint8_t tomo_script_gate;
            /* Tail lvalues must only be formed after this test. Ring-slot
             * promotion happens while the slot is idle, before publication. */
            uint8_t has_exec_tail;
            redisAtomic int tomo_watch_worker;
            redisAtomic unsigned int tomo_dirty_cas;
            size_t all_argv_len_sum;
        };
        unsigned char _exec_core_layout[320];
        uint64_t _exec_core_align;
    };
    clientExecTail exec_tail[];
} client;

#define CLIENT_FULL_SIZE (sizeof(client) + sizeof(clientExecTail))

#define clientTail(c) ((c)->exec_tail)

_Static_assert(sizeof(client) == 320, "client execution core must stay 320 bytes");
_Static_assert(offsetof(client, exec_tail) == 320, "client tail must follow the execution core");
_Static_assert(TOMO_EX_THREADS_MAX <= INT16_MAX, "client worker id no longer fits its core field");
_Static_assert(sizeof(clientExecTail) == CLIENT_EXEC_TAIL_BYTES, "client execution tail size changed");
_Static_assert(offsetof(clientExecTail, reply_cdb) == 0, "CDB pointer must remain a direct offset load");
#ifndef LOG_REQ_RES
_Static_assert(CLIENT_FULL_SIZE == 1160, "full client must stay within the audited byte budget");
#endif
#if UINTPTR_MAX == UINT64_MAX
_Static_assert(offsetof(client, flags) == 16, "client flags left hot line 0");
_Static_assert(offsetof(client, reply) == 64, "client reply left hot line 1");
_Static_assert(offsetof(client, prefetch_key_hash) == 136, "client prefetch state left hot line 2");
_Static_assert(offsetof(client, reply_bytes) == 192, "client reply accounting left hot line 3");
_Static_assert(offsetof(client, argc) == 276, "client argv state left hot line 4");
#endif

/* ===== p1 DIRECT-CLIENT: the EX_OWNED ownership window (design 2026-08-19) =============
 *
 * In DIRECT mode the dispatch hands the REAL client* to an ex thread (no fake wrapper).
 * The window is delimited by the flag every dispatched execution object already carries:
 * CLIENT_EX_PENDING on a NON-fake client == "an ex thread is executing on this real
 * client right now". The owning io thread sets it immediately before the SPSC dispatch
 * publish and clears it when it consumes the completion byte, so for the owner the flag
 * is program-ordered; the worker observes it through the queue's release/acquire pair.
 *
 * While the window is open, EVERY io-side toucher must defer/skip this client:
 *   - clientsCronRunClient (querybuf resize, obuf limit check, timeout processing,
 *     output-buffer resize, fake-ring decay, memory sampling),
 *   - CLIENT KILL / freeClient / freeClientAsync (record CLOSE_ASAP intent, act after
 *     handback via the async-free walker, which already skips EX_PENDING clients),
 *   - client-lb / flip connection migration (start walks skip; the handoff already
 *     waits on tmClientQuiesced's dispatchid==flushid fence),
 *   - the reply path's output-buffer-limit close (re-checked io-side at handback).
 * Ex touches ONLY exec-visible fields (argv, db context, c->buf/bufpos, reply metrics);
 * never events, the socket, querybuf, or migration fields. */
static inline int clientExOwnedReal(const client *c) {
    return !c->isFake && (c->flags & CLIENT_EX_PENDING);
}

/* p1direct per-conn mode values (clientExecTail.p1d_mode). DIRECT is the boot state:
 * the first command on a fresh conn is always a singleton. */
#define TOMO_P1D_DIRECT 0
#define TOMO_P1D_FC     1

/* Flags that disqualify a conn from DIRECT dispatch outright. The fake path executes
 * with a four-flag SUBSET (moveExecutionStateSlim), so a conn whose full flag word
 * carries connection-scoped semantics the GET/SET proc or its reply path could observe
 * (replication identities, reply silencing, tracking, teardown, migration, parks) must
 * stay on the fake path where those flags are stripped for the execution object. */
#define TOMO_P1D_DISQUALIFY_FLAGS \
    (CLIENT_MULTI | CLIENT_BLOCKED | CLIENT_UNBLOCKED | CLIENT_SLAVE | CLIENT_MASTER | \
     CLIENT_MONITOR | CLIENT_TRACKING | CLIENT_REPLY_OFF | CLIENT_REPLY_SKIP | \
     CLIENT_REPLY_SKIP_NEXT | CLIENT_CLOSE_AFTER_REPLY | CLIENT_CLOSE_ASAP | \
     CLIENT_PROTECTED | CLIENT_MIGRATING | CLIENT_SCRIPT | CLIENT_MODULE | \
     CLIENT_INTERNAL | CLIENT_ASM_MIGRATING | CLIENT_ASM_IMPORTING | CLIENT_PUSHING | \
     CLIENT_PENDING_WRITE | CLIENT_PUBSUB)
/* CLIENT_PUBSUB: PUBLISH delivery writes the SUBSCRIBER's c->buf from the publisher's io
 * thread (addReplyPubsubMessage), and RESP3 subscribers may still issue GET. A DIRECT flight
 * would widen that pre-existing two-writer window from the splice instant to the whole
 * flight — subscribers stay on the fake path. */

/* p1direct witness counters (anti-vacuous rule: every closed path ships a counter that
 * proves it opened). One cache line per io identity, owner-incremented with plain stores;
 * INFO folds the slots. INVARIANT: dispatches == handbacks at quiesce — a lasting gap is
 * exactly the captured wedge signature (parsed+dispatched, argv held, events unarmed,
 * conn starved forever). deferred_kills may be bumped from a non-owner thread (a killer
 * thread records intent); that writer indexes its own slot, so slots stay single-writer. */
typedef struct tomoP1DirectStats {
    unsigned long long dispatches;          /* direct dispatches (io, at push) */
    unsigned long long handbacks;           /* direct completions consumed (io, at drain) */
    unsigned long long mode_to_fc;          /* per-conn DIRECT->FC transitions */
    unsigned long long mode_to_direct;      /* per-conn FC->DIRECT transitions */
    unsigned long long deferred_cron_touches;  /* clientsCronRunClient skipped an EX_OWNED conn */
    unsigned long long deferred_migrations;    /* migration start/handoff deferred on EX_OWNED */
    unsigned long long deferred_kills;         /* kill intent recorded on an EX_OWNED conn */
    unsigned long long spill_fallbacks;        /* direct reply overflowed c->buf => conn -> FC */
} __attribute__((aligned(CACHE_LINE_SIZE))) tomoP1DirectStats;
_Static_assert(sizeof(tomoP1DirectStats) == CACHE_LINE_SIZE,
               "p1direct witness slot must occupy exactly one owner line");
extern tomoP1DirectStats tomo_p1d_stats[TOMO_IO_THREADS_MAX + 1];
/* Master toggle (DEBUG TOMO-P1DIRECT <0|1>, default ON; 0 forces all-FC without touching
 * per-conn mode state — the validation A/B lever). Deliberately NOT a config knob. */
extern _Atomic int tomo_p1direct_enabled;
/* Non-io callers (a killer thread recording intent from a cold teardown path) fold
 * into slot 0; the guard keeps a worker-range iotid from indexing out of bounds. */
#define TOMO_P1D_BUMP(fieldname) do { \
        int _p1d_slot = (iotid >= 0 && iotid <= TOMO_IO_THREADS_MAX) ? iotid : 0; \
        tomo_p1d_stats[_p1d_slot].fieldname++; \
    } while (0)

/* Non-allocating cold-state readers. Call the subsystem initializer before a
 * write; these helpers deliberately return NULL for never-used state. */
static inline multiState *clientMultiState(client *c) {
    clientCold *cold = c->has_exec_tail ? clientTail(c)->cold : NULL;
    return cold ? &cold->mstate : NULL;
}

static inline blockingState *clientBlockingState(client *c) {
    clientCold *cold = c->has_exec_tail ? clientTail(c)->cold : NULL;
    return cold && (cold->initialized & CLIENT_COLD_BLOCKED) ? &cold->bstate : NULL;
}

static inline clientCold *clientPubSubData(client *c) {
    clientCold *cold = c->has_exec_tail ? clientTail(c)->cold : NULL;
    return cold && (cold->initialized & CLIENT_COLD_PUBSUB) ? cold : NULL;
}

static inline clientCold *clientReplicationData(client *c) {
    clientCold *cold = c->has_exec_tail ? clientTail(c)->cold : NULL;
    return cold && (cold->initialized & CLIENT_COLD_REPL) ? cold : NULL;
}

/* ee451 (v7): cross-shard scatter-gather group. Lives on the GROUP HEAD fake (the ring
 * slot that represents one multi-key command). Each sub-fake runs the per-shard
 * subcommand on its worker; the LAST sub to complete (pending hits 0, release) sets the
 * group head's reply-ready byte so the IO drain reassembles. Single-writer-per-key is
 * preserved: each key is still touched only by its owning shard's worker. */
typedef enum { CS_MGET=0, CS_MSET, CS_DEL, CS_EXISTS, CS_KEYS, CS_SETOP, CS_RENAME,
               CS_RENAMENX, CS_COPY, CS_SMOVE, CS_SSTORE, CS_SETCARD,
               CS_ZOP, CS_ZSTORE, CS_ZRANGESTORE, CS_SORTSTORE, CS_GEOSTORE,
               CS_ZCARD, CS_BITOP, CS_PFCOUNT, CS_PFMERGE, CS_LCS, CS_XREAD,
               CS_LMOVE, CS_MSETNX, CS_LMPOP, CS_ZMPOP, CS_BLPOP, CS_BZPOP,
               CS_LOCAL /* xshard-localfast: all keys on ONE worker -> single sub runs the
                         * REAL PROC with the full original argv; reply spliced verbatim */
             } csCmdType;
struct sortXShardCtx;
/* CS_SETOP operation kind (carried in csGroup.setop). */
#define CS_SETOP_INTER     0
#define CS_SETOP_UNION     1
#define CS_SETOP_DIFF      2
/* ee451 (universal xshard): 2-HOP phase machine. Read-then-write / move / conditional commands GATHER
 * on the SOURCE shard(s) in HOP1, then the IO DRAIN (never a worker — a worker's iotid is not an SPSC
 * producer slot) launches HOP2 to WRITE the serialized result to the DEST shard. Data crossing shards
 * is a private refcount-free DUMP/sds blob (S8-safe: no live robj crosses a thread). */
#define CS_PH_HOP1         0   /* default (zcalloc) => every 1-hop group is unaffected */
#define CS_PH_HOP2         1
/* g->err codes (reuse the existing atomic err; 0/1 keep SETOP's none/WRONGTYPE meaning). */
#define CS_ERR_NONE        0
#define CS_ERR_WRONGTYPE   1
#define CS_ERR_NOKEY       2
#define CS_ERR_NX_EXISTS   3
#define CS_ERR_EMPTY       4
#define CS_ERR_BADHLL      5   /* PF*: string is not a valid HLL (stock -WRONGTYPE ... text) */
#define CS_ERR_CORRUPT     6   /* PF*: hllMerge detected corruption (stock -INVALIDOBJ text) */
#define CS_ERR_SAMEOBJ     7   /* COPY same key + same dest-db (stock "source and destination
                                * objects are the same"); 2-hop path has no raw-proc guard */
#define CS_ERR_SUBREPLY    8   /* a HOP1 stock helper emitted the final error into its sub */
#define CS_ERR_SORTNUM     9   /* external SORT BY value failed stock's numeric conversion */
#define CS_ERR_WOULDBLOCK  10  /* blocking multi-key probe found no immediately-ready key */
/* hyperloglog.c — xshard coordinator helpers over gathered HLL objects (step 7). */
int isHLLObject(robj *o);
uint64_t hllCountMulti(robj **hlls, int n, int *err);
robj *hllMergeObjects(robj **hlls, int n, int *err);
/* HOP2 launcher shape (registry row -> g->h2_op). Worker-side SEMANTICS stay in csSubExec's
 * ctype switch; this only tells csLaunchHop2 HOW to build the second wave. */
#define CS_H2_NONE         0
#define CS_H2_PLAN         1   /* launch the g->h2sub[] plan (dest write +/- src-side op) */
#define CS_H2_SCATTER      2   /* step 8 (MSETNX): re-run the coalesced write wave */
/* HOP2 per-sub roles (g->h2sub[cssub_idx].action). */
#define CS_H2A_WRITE       1   /* dest-side op: RESTORE / SET / SADD / PUSH per ctype */
#define CS_H2A_SRCOP       2   /* src-side op: DEL / SREM / POP per ctype */
#define CS_H2_MAX          3   /* dest-write + src-op + spare (probe subs live in HOP1) */
/* HOP2 flags (g->h2_flags, from options parsed at dispatch/prep). */
#define CS_H2F_REPLACE     1   /* COPY REPLACE: overwrite dst instead of NX-failing */
#define CS_H2F_FROM_LEFT   2   /* LMOVE family: pop src from LEFT (else RIGHT) */
#define CS_H2F_TO_LEFT     4   /* LMOVE family: push dst on LEFT (else RIGHT) */
/* HOP1 probe-verdict bits (atomic fetch_or into g->probe; disjoint writers per sub,
 * published to the coordinator by the pending barrier). */
#define CS_PR_DST_EXISTS    1  /* probe sub: dst key present (RENAMENX NX verdict) */
#define CS_PR_DST_WRONGTYPE 2  /* probe sub: dst present with wrong type (SMOVE) */
#define CS_PR_SRC_MISSING   4  /* src sub: src key absent (SMOVE :0) */
#define CS_PR_SRC_WRONGTYPE 8  /* src sub: src wrong type (SMOVE WRONGTYPE) */
#define CS_PR_MEMBER       16  /* src sub: member present in src set (SMOVE) */
/* reply shape after HOP2 / for 2-hop commands. */
#define CS2_OK             1
#define CS2_INT            2
#define CS2_NIL            3
/* ---- xshard registry: port state ---- */
#define CS_PORT_UNPORTED   0   /* row exists for the SAFE-GATE only (argc hooks); reject */
#define CS_PORT_OK         1   /* fully ported: classify + dispatch through the table */
#define CS_PORT_EXEMPT     2   /* multi-key but deliberately allowed through the gate
                                * (emergency compat escape; NO row uses it at ship time) */
/* ---- xshard registry: route kind ---- */
#define CS_RT_GATHER       0   /* scatter/gather over the command's own key list */
#define CS_RT_FANALL       1   /* one sub per worker, full argv (KEYS) */
#define CS_RT_TWOHOP       2   /* single-src gather (+opt dst probe) -> HOP2 plan (RENAME, moves) */

/* T6 command-to-worker resolution. Ordinary keyless and malformed forms stay on the stock path;
 * keyspace-wide forms and concrete multi-owner key sets return CROSS. */
#define TOMO_SW_NONE       (-1)
#define TOMO_SW_CROSS      (-2)
#define TOMO_SW_INVALID    (-3)
/* ---- result slots dispatchGather allocates ---- */
#define CS_RES_NONE        0
#define CS_RES_MGETVALS    1   /* coalesced string slots; CS_MGET uses retained g->mget_refs */
#define CS_RES_SETMEM      2   /* g->setmem/setcnt[nkeys] — ALWAYS (legacy + coalesced) */
#define CS_RES_KEYREPORT   3   /* g->klen/ktype[nkeys] (ordered MPOP/BPOP probes) */
#define CS_RES_ZSETMEM     4   /* setmem/setcnt + parallel zscore[nkeys] (step 6 Z-ops) */
#define CS_RES_XREAD       5   /* g->xread_out/status[nkeys] — ordered stream reply fragments */
/* ---- posmap selector for csBuildCoalescedSubs ---- */
#define CS_POS_NONE        0
#define CS_POS_MGET        1   /* &g->mget_pos  */
#define CS_POS_SETOP       2   /* &g->setop_pos */
#define CS_POS_XREAD       3   /* &g->xread_pos */
/* ---- coalesce gate ----
 * The tomokv-mget-coalesce / -setop-coalesce knobs were retired (coalescing is unconditional),
 * but the k>=3 THRESHOLD is NOT the knob's off-state: it is the live gate for every 2-key
 * cross-shard MGET/SETOP, where the <=2 subs do not amortize the slot/pos allocations. Two tags
 * (not one) because the two families are gated independently if that ever has to change. */
#define CS_CO_ALWAYS       0   /* MSET/DEL/EXISTS: always one sub per distinct shard */
#define CS_CO_MGET_K3      1   /* MGET family: coalesce iff nkeys >= 3, else legacy per-key */
#define CS_CO_SETOP_K3     2   /* SETOP family: coalesce iff nkeys >= 3, else legacy per-key */
/* argv-index accessor: 0 in a zero-initialized row means "keys start at argv[1]" */
#define csFirstKeyArg(s) ((s)->firstkey_argi ? (int)(s)->firstkey_argi : 1)

typedef struct csH2Sub {
    uint8_t action;    /* CS_H2A_* — read as g->h2sub[sub->cssub_idx].action from step 4 on */
    int32_t key_argi;  /* head->argv index of this sub's key. int32 NOT int16 (review #3): an
                        * ordered-pop prep rewrites it to firstkey+winner, and argc can reach the
                        * ~1M multibulk limit, so int16 (max 32767) truncated to a negative index
                        * => OOB argv read / crash on a many-key MPOP. */
} csH2Sub;
struct csCmdSpec;      /* fwd — full definition next to struct redisCommand below */
typedef struct csMsetInstall {
    kvobj *kv;                   /* exact store object returned by setKeyVersioned */
    int owner;                   /* sole owner that applies both embedded operations */
    uint32_t install_order;      /* per-key install-order tie break for duplicate keys */
} csMsetInstall;

typedef struct csGroup {
    redisAtomic int pending;   /* sub-fakes not yet complete; last decrementer signals slot */
    int nsub;                  /* number of sub-fakes = nkeys (one sub per key) */
    csCmdType ctype;
    int nkeys;                 /* original key count */
    client **subs;             /* [nsub] sub-fakes (freed at drain) */
    client *head;              /* the group-head fake (the ring slot) */
    uint64_t key_sig;          /* OR of 1ULL << (tomo key hash & 63) for every written key */
    /* R1 own-read gate, EXACT arm. key_sig is one bit per key, so at 8 written keys two
     * disjoint 8-key sets already alias ~66% of the time and the filter almost never proves
     * disjointness. key_h carries the FULL hash of every key that contributed to key_sig, so a
     * filter "maybe" can be settled exactly. Deliberately adjacent to key_sig: the FIFO walk
     * reads all three from one cache line.
     *   key_h_n == 0  =>  no vector (too many keys, or a shape that never built one): the walk
     *                     cannot prove disjointness and must HOLD (charged to ownread_conserv).
     *   key_h_n  > 0  =>  key_h[0..key_h_n) is COMPLETE w.r.t. key_sig. Publishing key_h_n is
     *                     the commit point; it is written only after every slot is filled, so a
     *                     half-built vector reads as "no vector" (hold) and never as "disjoint".
     * Storage lives in this group's own allocation (inline bump region, heap only if it spilled)
     * and is written once, on the head's IO thread, before csMsetRegister publishes g. It is
     * therefore reachable exactly as long as the group is LINKED in the FIFO: csMsetPopComplete
     * copies key_sig/key_h into a connection-owned csPubRec on the way out, because past that
     * point csReassemble may free this whole allocation at any moment. */
    union {
        uint64_t *key_h;       /* [key_h_n] full tomo key hashes of the written keys */
        uint64_t *mget_hash;   /* MGET-only routing-hash scratch; group is never in R1 */
    };
    int key_h_n;               /* 0 => filter-only (conservative); see above */
    uint64_t version_seq;      /* UNCOMMITTED while installing, then the group commit ticket */
    uint64_t read_seq;         /* command snapshot S while version_seq remains the write ticket */
    struct csGroup *commit_next; /* CS_MSET global ticket-order queue link */
    client *mset_client;         /* real-client owner of the R1 pending FIFO */
    struct csGroup *mset_pending_prev;
    struct csGroup *mset_pending_next;
    redisAtomic int mset_complete;      /* every owner installed this group */
    redisAtomic int mset_install_count;
    csMsetInstall *mset_installs;       /* [version_install_expected], atomic-write arm only */
    uint64_t mset_install_order_base; /* first connection-global install order reserved by this group */
    int versioned_write;         /* this group is an atomic version-bag write */
    int version_install_expected; /* successful group's exact whole-value install count */
    int version_commit_ready;    /* current worker wave is the final install wave */
    int version_abort;           /* semantic no-op/error: cancel reservations, publish no ticket */
    int version_nx;              /* RENAMENX/COPY NX destination reservation */
    int version_nx_reserving;    /* current wave is acquiring that destination reservation */
    redisAtomic int msetnx_retry;       /* reservations blocked by an earlier pending owner */
    uint8_t *msetnx_state;              /* [nkeys], coordinator-visible reservation verdict */
    int snapshot_pinned;       /* snapshot-reading group uses its head's dispatch pin */
    redisAtomic long rcount;   /* DEL/EXISTS: summed integer result */
    /* ee451 (v11-F): cross-shard set-ops (SINTER/SUNION/SDIFF). Each per-key sub gathers its
     * set's members as freshly-allocated sds COPIES (private, refcount-free => safe to free on
     * the coordinator after the pending barrier — no freeback ring needed, unlike MGET's shared
     * values). The coordinator computes union/inter/diff over setmem[] and replies. */
    int setop;                 /* CS_SETOP_{INTER,UNION,DIFF} */
    redisAtomic int err;       /* CS_SETOP: a sub saw a non-set (WRONGTYPE) key */
    sds **setmem;              /* CS_SETOP: [nsub] arrays of member-sds copies (worker-alloc) */
    long *setcnt;              /* CS_SETOP: [nsub] member count for setmem[i] (0 if missing key) */
    double **zscore;           /* CS_Z*: [nkeys] per-key score arrays parallel to setmem
                                * (worker-alloc; a plain-set source contributes 1.0 per stock) */
    /* ee451 (xshard OPT-1): COALESCED MGET. One sub per distinct owner writes retained value
     * references into original-position slots. The IO owner copies bytes into the real reply
     * with copy avoidance disabled, then routes each decref through S8 to mget_owner[pos]; it
     * never mutates a worker-owned refcount. This removes the former per-hit SDS allocation and
     * second value copy. mget_hash reuses the routing pass's full hash for the worker FLAT read.
     * Other CS_RES_MGETVALS commands still use private mget_vals SDS images because their
     * coordinator computations require independently-owned bytes. NULL mget_refs identifies the
     * legacy one-key-sub MGET path, whose serialized buffers are spliced as before. */
    union {
        robj **mget_refs;       /* CS_MGET coalesced: [nkeys] retained values (NULL=nil) */
        sds *mget_vals;         /* other string-image gathers: private position-indexed copies */
    };
    int **mget_pos;            /* CS_MGET coalesced: [nsub] per-sub original-position lists */
    int **setop_pos;           /* CS_SETOP coalesced: [nsub] per-sub original-key-position lists (NULL=legacy per-key subs). setmem/setcnt stay indexed by ORIGINAL key position. */
    client **xread_out;        /* CS_XREAD: [nkeys] bare [key,entries] reply fragments */
    uint8_t *xread_status;     /* CS_XREAD: per-position empty / hit / error verdict */
    int **xread_pos;           /* CS_XREAD: sub-local stream -> original request position */
    long long xread_count;     /* parsed COUNT (0 means unlimited, matching stock XREAD) */
    int  posmap_nsub;          /* ROW COUNT of mget_pos/setop_pos, captured when they were built.
                                * NOT g->nsub: nsub is repurposed by every later pipeline stage
                                * (HOP2 plan, per-key fan-out, SIZES->apply), so freeing a posmap
                                * with the CURRENT nsub under-frees (leak) or over-walks (OOB).
                                * Only one build's posmaps are live at a time -- the HOP1 teardown
                                * frees and NULLs both before HOP2 rebuilds. */
    /* cs_node_lock DELETED 2026-07-27 with the node-local borrow: CS_LOCAL is now always a
     * single-OWNER localfast (all keys on one worker), so its sub needs only that worker's lock. */
    /* ee451 (universal xshard) 2-HOP phase machine — all zero-default (=> inert 1-hop group). */
    int phase;                 /* CS_PH_HOP1 (0) | CS_PH_HOP2 */
    int has_hop2;              /* 1 => drain launches HOP2 after the HOP1 barrier (else reassemble+reply) */
    int h2_op;                 /* CS_H2_* launcher shape (from the registry row) */
    const struct csCmdSpec *spec; /* registry row, stamped at dispatch on GATHER/TWOHOP groups
                                * (NULL on FANALL); COLD reads only (launch/reassemble) */
    csH2Sub h2sub[CS_H2_MAX];  /* HOP2 plan, stamped at dispatch from the row; the csLaunchHop2
                                * prep case may rewrite it (ordered-pop winner) */
    int h2_nsub;               /* planned HOP2 subs; 0 on all 1-hop groups */
    int h2_dbid;               /* COPY DB option; dispatch inits to head->db->id */
    int h2_flags;              /* CS_H2F_* (COPY REPLACE), parsed at dispatch */
    sds h2_payload;            /* serialized value blob (DUMP/raw) — private, refcount-free, freed at teardown */
    long long h2_pexpireat;    /* absolute expire ms for the restored key (-1 = none) */
    int cs2_kind;              /* reply shape (CS2_OK/CS2_INT/CS2_NIL) for the final reply */
    /* ee451 merge-execution pipeline. INTER uses SIZES (per-shard sub reports per-key set
     * sizes) -> GATHER1 (smallest key's members only) -> PROBE chain (per remaining shard,
     * candidates probed against that shard's whole key slice and survivors shrink). UNION/DIFF
     * use one LOCAL-* wave: every source shard reduces its own slice and exports only a distinct
     * partial; the coordinator merges those partials. STORE rows feed the final result into the
     * normal destination HOP2. All source stages remain lock-free reads.
     * pipe_cand is coordinator-written BEFORE the stage sub is pushed (SPSC release/acquire
     * publishes it); pipe_verdict is worker-written, drain-acquired via the completion byte. */
    int pipe_stage;            /* 0=off, CS_PIPE_* otherwise */
    int pipe_next;             /* next index into pipe_order for the PROBE chain */
    int pipe_nshard;           /* distinct shards */
    long *pipe_scard;          /* [nkeys] per-key size (INTER SIZES / local ZUNION occurrences) */
    int  *pipe_order;          /* [nshard] shard visit order for PROBE (ascending min-key-size) */
    sds  *pipe_cand;           /* [pipe_ncand] candidate members (coordinator-owned copies) */
    long  pipe_ncand;          /* live candidates (compacted between stages) */
    uint8_t *pipe_verdict;     /* [pipe_ncand] worker-written per-candidate survive flags */
    int  *pipe_shard_of;       /* [nkeys] key -> worker (stamped at dispatch) */
    int   pipe_smallest;       /* key position of the globally smallest set */
    /* Z INTER extension: cand-major per-key contribution matrix (CS_ZOP/CS_ZSTORE; NULL for counts).
     * pipe_cscore[c*nkeys + k] = raw score of candidate c in key k (weights applied at the
     * reassemble fold, in stock cardinality-ascending key order). Rows compact with cand. */
    double *pipe_cscore;
    int *pipe_probe_pos;       /* [pipe_probe_nk] original key positions of in-flight PROBE argv */
    int pipe_probe_nk;
    /* UNION/DIFF shard-local partials. pipe_part[p] contains each member at most once for source
     * shard p. For DIFF, pipe_base_part is the partial that owns original key 0; that worker has
     * already subtracted the rest of its local slice. ZDIFF carries scores only on that base
     * partial. ZUNION additionally retains compact member-index/score arrays per ORIGINAL key so
     * the coordinator can fold contributions in the exact pre-refactor order (IEEE addition is
     * not associative); repeated member SDS bytes are still shipped only once per shard. */
    int pipe_npart;
    int pipe_base_part;
    sds **pipe_part;           /* [pipe_npart] arrays of shard-distinct member copies */
    long *pipe_partcnt;        /* [pipe_npart] lengths of pipe_part[] */
    double **pipe_partscore;   /* [pipe_npart], ZDIFF base scores; NULL entries otherwise */
    long **pipe_midx;          /* [nkeys], ZUNION occurrence -> index in pipe_part[key_part] */
    double **pipe_zraw;        /* [nkeys], ZUNION raw scores parallel to pipe_midx */
    int *pipe_key_part;        /* [nkeys], ZUNION original key -> shard partial */
    long long cs2_intreply;    /* integer reply accumulator (e.g. *STORE cardinality) */
    /* ---- HOP1 verdict storage (written from step 4/9 on; declared now so future rows are
     * provably implementable without a shape change): ---- */
    /* ee451 (#B2): commandstats accounting for the GROUP. A cross-shard command is one command the
     * client sent, fanned into one sub per owning shard, so it must contribute exactly one `calls`
     * — counted at csReassemble, the group's single completion point, exactly like #B1's
     * numCommandsBump. `usec` is the SUM of the subs' proc times (the work the command cost the
     * server), not the group's wall clock, which would fold in queueing and scatter latency that
     * stock's per-command `usec` never contains. Multi-sub stages update it concurrently and retain
     * an atomic RMW; a singleton stage uses the owner-local atomic load/store idiom. */
    redisAtomic long long usec;  /* summed sub proc time, microseconds */
    redisAtomic int had_err;     /* a sub emitted an error reply => failed_calls */
    redisAtomic long long probe; /* dst-probe lane: exists/type verdict (step 4+) */
    long *klen;                  /* [nkeys] per-original-key length reports (step 9) */
    union {
        uint8_t *ktype;         /* ordered key-report gathers: type by original position */
        uint8_t *mget_owner;    /* CS_MGET coalesced: S8 return owner, indexed by position */
    };
    /* T3 SORT BY/GET pipeline. The source worker constructs an opaque, refcount-free SORT
     * context; later owner-bucketed dereference waves fill mget_vals and use sort_fields to
     * distinguish string lookups from hash-field lookups. All three fields are private to
     * this command path and are released at its coordinator teardown. */
    struct sortXShardCtx *sort_ctx;
    int sort_stage;
    sds *sort_fields;            /* [nkeys], NULL = external string key, non-NULL = hash field */
    /* ---- INLINE (small-size) storage for this group's coordinator-owned arrays. ----
     * Standard inline-then-spill container storage: LLVM SmallVector, folly::small_vector,
     * absl::InlinedVector, std::string SSO. A cross-shard command is SMALL and SHORT-LIVED --
     * MGET(4) over 4 shards used to make and destroy TWELVE separate heap blocks (this struct,
     * subs[], mget_vals[], mget_pos[], one int[] per sub, and one argv[] per sub) for a working
     * set of ~192 bytes.
     * Those arrays are now carved out of a bump region that lives INSIDE this allocation, so the
     * common case costs ONE allocation and the arrays share cache lines with the header.
     * Overflow spills to zmalloc (csgAlloc/csgFree), so nkeys/nsub gain no new limit.
     * inl is a FLEXIBLE array: each group is sized at creation from ITS OWN command shape
     * (csInlineWant), so a command that needs one 32-byte array pays for 32 bytes and not for
     * the largest shape any command might have. There is no knob — see csGroupNew. */
    uint16_t inl_cap;            /* bytes of inl[] actually allocated (0 => every array on the heap) */
    uint16_t inl_used;           /* bump cursor; monotone, NEVER rewound (see csgAlloc) */
    long long inl[];             /* 8-aligned bump region, zeroed at creation */
} csGroup;
/* Ceiling on the per-group inline region: above this the arrays spill to the heap, which is
 * always correct (csgAlloc/csgFree). It bounds the memset and the cache footprint a single
 * pathological command (a 1M-key MGET) can impose on the group allocation. The reference
 * MGET(4)/MSET(4) shapes need 192/128 bytes including sub argv; larger shapes spill safely.
 * Set to 0 to build the mechanism out entirely (A/B). */
#define CS_INLINE_MAX_BYTES 512

/* ee451 (v7): FLUSHALL/FLUSHDB. The IO thread bumps each worker's flush_req (a side-channel
 * generation counter, NOT the command queue — so no fake-client lifecycle to race on, and the
 * IO event loop is never blocked). Each worker, at the TOP of its main loop (before popping its
 * next command batch), notices req != its private flush_seen and empties its OWN shard DBs
 * (single-writer preserved). Because the flush check precedes the batch pop, any command issued
 * after FLUSHALL is guaranteed to observe the emptied shard, so "FLUSHALL; GET -> nil" holds.
 * The reply returns once the flush is scheduled (effectively FLUSHALL ASYNC). A mutex in
 * flushAllShards serializes concurrent flushes so the per-worker flush_* fields aren't torn. */
void flushAllShards(client *c, int dbid, int async);   /* server.c; called by db.c flush cmds */
void tomoFlatResizeQuiesce(void);  /* server.c; wait out every in-flight FLATSTORE resize before a
                                    * NON-WORKER mutation that may span shared node dbs */
void tomoFlatResizeWorkerQuiesce(int worker_id); /* wait only for the worker's node resize */
int tomoFlatResizeWorkerActive(int worker_id);
typedef struct tomoFlatResizeProgress {
    unsigned long long drives;
    unsigned long long completed_chunks;
    int state;
    int active;
} tomoFlatResizeProgress;
void tomoFlatResizeWorkerProgress(int worker_id, tomoFlatResizeProgress *progress);
void tomoFlatResizeWorkerWaitStep(int worker_id);
void tomoFlatResizeWakeWorker(int worker_id);    /* wake that node's immutable resize owner */
void tomoFlatResizeLogSlot(kvstore *kvs, struct flatTable *old, uint64_t slot);
void tomoFlatResizeLogDelete(kvstore *kvs, struct flatTable *old, const sds key);
extern _Atomic unsigned long long flat_insert_full_waits;
extern _Atomic unsigned long long flat_insert_full_wait_us_max;
int migSuppressLazyExpire(redisDb *db, sds keyname); /* W6-E2: 1 = DRAINING fence — treat in-range key as expired WITHOUT deleting */
void reshardDebug(client *c);                     /* v8d: DEBUG RESHARD START|STATUS */
void reshardAutoTune(void);                       /* per-node EWMA key balancer, driven at 1 Hz */

/* ee451 (v8d): reshard phases. The COPY ENGINE that once backed them (the A->B effect log, the
 * cold scan, the B-side replay and A's post-flip range delete) was DELETED 2026-07-28: a reshard
 * only ever moves a bucket range between two workers of ONE node, and those workers share ONE
 * physical flat kvstore (shared_node_dbs), so the cutover is a drain-fence plus an ownership flip
 * in ex_bucket_table — no key ever moves. reshardArm now REFUSES any (src,dst) pair on different
 * physical dbs, which is what made the copy path reachable at all. Value 4 stays reserved so a
 * live DEBUG RESHARD STATUS keeps the historical phase integers. */
typedef enum { MIG_IDLE=0, MIG_COPYING=1, MIG_DRAINING=2, MIG_FLIPPED=3, MIG_DONE=5 } migPhase;
//ee451
/* Worker queue capacity: size of the ring each IO thread pushes fake-client
 * jobs into for a given worker. Always a power of two. Runtime value lives
 * in server.ex_queue_size; TOMO_EX_QUEUE_SIZE_MAX caps the static
 * array. Memory footprint at max:
 *   num_workers * (io_threads + 1) * TOMO_EX_QUEUE_SIZE_MAX * sizeof(ptr)
 * With defaults (3/8/1024) that's ~216KB across all queues; the MAX bound
 * (2048) keeps worst case manageable. */
#define TOMO_QS_WORDS ((TOMO_IO_THREADS_MAX + 1 + 63) / 64)  /* q_summary words (see exThread) */
#define TOMO_EX_MASK_WORDS ((TOMO_EX_THREADS_MAX + 63) / 64)     /* ee451 #83: ex_dirty_mask words */
#define TOMO_IO_MASK_WORDS ((TOMO_IO_THREADS_MAX + 1 + 63) / 64) /* ee451 #83: io_pin_mask words */
#define TOMO_EX_QUEUE_SIZE_MAX 2048
/* (EX_QUEUE_SIZE / EX_QUEUE_MASK DELETED 2026-07-28: they were tomokv-ex-queue-depth's default
 * and its derived mask, kept "for back-compat" with nothing left to be compatible with — no
 * translation unit referenced either. The live values are server.ex_queue_size/ex_queue_mask,
 * derived in initServer.) */
#define EX_THREADS_NUM 4    /* default; runtime value lives in server.ex_threads. ANY count is
                                 * legal — getWorkerForCommand routes through ex_bucket_table, not
                                 * a power-of-two mask (that mask was deleted 2026-07-28). */
#define IO_THREADS_NUM 8        /* default; runtime value lives in server.io_threads */
/* How many fakes a worker drains per lock acquire on one IO-thread queue.
 * Larger = fewer mutex traffic pings, better cache locality in exec loop,
 * higher latency for the last fake in the batch. 16 matches PIPELINE_DEPTH
 * so a single-client burst can be drained in one shot. */
#define WORKER_POP_BATCH 16

/* ── Worker prefetch: structural constants (2026-07-28 knob retirement) ───────────────────────
 * The ten tomokv-pf-* / tomokv-prefetch-* knobs were retired from the config surface on
 * 2026-07-28. Nine of them shipped in their AUTO arm; the AUTO arm is now hardwired and these
 * constants are what is left. They are STRUCTURAL (properties of the pipeline), not tuning: an
 * operator had no information the server does not measure for itself.
 *
 * WHAT THE MECHANISM IS. exPrefetchBatch (server.c) is GROUP PREFETCHING with software
 * pipelining: a batch of independent lookups is walked stage by stage, each stage issuing its
 * prefetch for the whole group before any lookup dereferences the line it just requested. The
 * prefetch DISTANCE is the group size — the standard form — which is exactly what the retired
 * knobs' AUTO arm (-1) meant: "width follows the current batch occupancy n". No history, so a
 * workload shift re-tunes on the very next batch.
 *
 * WHY NOT AMAC HERE. AMAC (Kocberber et al., "Asynchronous Memory Access Chaining", VLDB'15)
 * keeps a per-lookup state machine and refills a completed slot from a fresh lookup, so the
 * group never stalls on its slowest member. That buys something only when the chains have
 * VARIABLE depth — hash chains of differing length, tree descents of differing height — because
 * a plain group prefetcher must then wait out the longest chain in the group. Tomo's flat table
 * does not have that shape: a 15-bit tag in the slot gates the kvobj dereference, so a hit is a
 * CONSTANT ~2 dependent steps (slot line, then kvobj) and a miss is 1. With constant depth every
 * group member finishes in the same number of stages, AMAC's refill never fires, and all that is
 * left of it is the per-slot state-machine bookkeeping — a cost with no matching benefit.
 * The round-robin cursor in exPrefetchBatch already gives the part that DOES pay: a lookup's
 * dereference happens a full rotation after its prefetch was issued. Revisit this only if a
 * variable-depth structure enters the hot path (a real collision-chain fallback, a tree index).
 *
 * EX-SIDE vs IO-SIDE (for the planned io+ex prefetch work). The stage set splits cleanly by
 * which thread owns the memory, which is the split that work will need:
 *   IO-SIDE-CAPABLE — the front end already touches these before dispatch, so they could be
 *   issued at parse/dispatch time on the IO thread: PFS_STRUCT (client struct + exec fields),
 *   PFS_ARGV (argv vector), PFS_KEYOBJ (key robj header), PFS_KEYBYTES (key bytes). None of
 *   them reads the keyspace. PFS_HASH is a boundary case: the SipHash compute is IO-side-safe
 *   (pure function of the key bytes, and the bucket id it yields is what dispatch routes on),
 *   but the bucket-line prefetch it issues is EX-side memory.
 *   EX-SIDE ONLY — these dereference the shard's keyspace, which only the owning worker may
 *   touch under its bucket lock: the bucket-line half of PFS_HASH, PFS_ENTRY (bucket -> entry),
 *   PFS_VALUE (entry -> kvobj/value), and the FLAT SLOT -> KVOBJ pair. Issuing these from an IO
 *   thread would read a table another thread is mutating; a prefetch of a stale address is
 *   harmless, but the table/slot scratch it needs is worker-private state.
 * Note this file already carries the plumbing for the cross-thread half: PFS_HASH stashes
 * (prefetch_key_hash, prefetch_dict, prefetch_bucket_idx) on the fake client, which is precisely
 * the handoff an IO-side issuer would fill in and an EX-side consumer would read. */
#define TOMO_PF_W_VALUE_MIN 4     /* value chase cannot cover a scoreboard rotation below this */
#define TOMO_PF_W_VALUE_MAX 256   /* ceiling only; must merely exceed any reachable batch size */
/* #3 exec-loop next-op look-ahead distance.
 *
 * ⚠ SELECTING AUTO HERE IS CURRENTLY A NO-OP — THE LOOK-AHEAD STILL NEVER FIRES. This was meant
 * to be the one retirement that changes runtime behaviour: tomokv-pf-w-nextop shipped at 0 = OFF,
 * so the look-ahead had never run in a shipped build, and the owner ruled it ON ("next op prefetch
 * on for now might change that later"). Hardwiring AUTO does select the branch — but the AUTO arm
 * resolves the look-ahead DISTANCE to the batch occupancy n, and the exec loop then computes
 *     la = j + n,  with j iterating [0, n),  guarded by  if (la < n)
 * so la >= n for every j and the guard is false unconditionally. The body is unreachable. AUTO and
 * 0 are therefore behaviourally identical today, which is why the merge that flipped this measured
 * as a wash in every regime rather than as the predicted cost.
 *
 * MEASURED 2026-07-29, io7/ex1, 4M keys, gate open (ls_pref_instr_disp.all per prefetch batch):
 *   AUTO (this file, la = j+n) .... 193.87 and 195.05 on two runs
 *   strict 4 (la = j+4) ........... 207.65      <- +7.1%, i.e. ~13 extra prefetches/batch,
 *                                                  matching the ~13.6 fakes/batch the loop runs
 * The counter plainly resolves the look-ahead when it fires, and sees nothing from the AUTO arm.
 *
 * The value is left at AUTO rather than reset to 0 so the owner's ruling stays recorded in the
 * code. TO ACTUALLY ENABLE IT the distance has to become a real look-ahead (a small constant, or
 * a fraction of n — NOT n itself), and that is a genuine new behaviour that needs its own A/B in
 * the ex1 + gate-open regime before it ships; it was deliberately not done as part of a knob
 * retirement. The asymmetry below still governs WHERE it could ever matter once fixed.
 *
 * WHERE IT WOULD CHANGE ANYTHING ONCE THE DISTANCE IS FIXED — the asymmetry matters, and getting
 * it wrong once already forced a revert (a "these stages are dead, delete them" conclusion that
 * was false at ex=1):
 *   ex >= 2 workers per node  -> shared_node_dbs, so the keyspace kvstore carries KVSTORE_FLAT.
 *                                The enabled storage path issues SLOT/KVOBJ hints but deliberately
 *                                leaves the DICT-only prefetch_key_hash_valid at 0. That is exactly
 *                                the input this DICT look-ahead is gated on, so on a flat store it
 *                                still CANNOT fire, knob or no knob. No change.
 *   ex == 1 worker per node   -> shared_node_dbs is false, the keyspace stays DICT-backed,
 *                                PFS_HASH populates the (hash, dict, bucket_idx) stash, and this
 *                                look-ahead becomes live. io7/ex1 is a standard test config, so
 *                                this is a real configuration, not a corner case.
 * Net: once the distance is fixed, it would change behaviour ONLY at one worker per node. */
#define TOMO_PFW_NEXTOP_AUTO (-1) /* look-ahead = current batch occupancy n -- see above: as a
                                   * DISTANCE this lands past the end of the batch every time */
#define TOMO_PF_W_NEXTOP TOMO_PFW_NEXTOP_AUTO  /* owner ruling 2026-07-28: ON (was 0 = OFF).
                                                * Selected, but a no-op until the distance is
                                                * fixed -- see the block above. */

/* Lock-free SPSC ring buffer. The architecture already guarantees that
 * each exQueue has exactly one producer (the IO thread whose index
 * matches queues[]) and exactly one consumer (the owning worker thread),
 * so we don't need a mutex — atomic head/tail indices with
 * acquire/release ordering are sufficient and ~60ns cheaper per op.
 *
 * Field layout notes:
 *   - `head` is written only by the consumer (worker).
 *   - `tail` is written only by the producer (IO thread).
 *   - They're placed on separate cache lines (CACHE_LINE_SIZE padding)
 *     so that the producer writing `tail` doesn't invalidate the
 *     consumer's copy of the line that holds `head` (and vice versa).
 *   - `jobs[]` trails `tail` — the producer writes `jobs[tail]` right
 *     before advancing `tail`, so co-located with tail's cache line is
 *     acceptable (no cross-core false sharing with head). */
typedef struct exQueue {
    redisAtomic unsigned int head __attribute__((aligned(CACHE_LINE_SIZE)));
    /* ee451: SPSC index caching (DPDK/folly style). cached_tail is a
     * non-atomic snapshot of `tail` touched ONLY by the consumer (owning
     * worker). It sits right after `head` so it lands on head's cache line,
     * which the consumer already owns/dirties — no new shared line. The
     * consumer tests "empty" against cached_tail and only acquire-reloads the
     * real tail when the cache says empty. cached_tail can only lag the true
     * tail (one producer monotonically advances it), so the cached check is
     * always conservative — never a false not-empty. */
    unsigned int cached_tail;
    /* ee451 (H2, reshard drain fence): consumer-published EXECUTION frontier.
     * `head` is advanced by exQueuePopBatch BEFORE the popped batch runs, so
     * `head == tail` means "nothing left to POP", NOT "nothing in flight" — a
     * worker that has popped 16 commands and is executing them reads as EMPTY.
     * That is the steady state of a busy worker, and the cutover fence used to
     * conclude "idle producer" from it and flip bucket ownership out from under
     * commands still executing on the old owner (silent lost write / two owners
     * mutating one bucket at once).
     * `retired` is stored ONCE PER BATCH, after the last command of that batch
     * has executed, so `retired == tail` is the real quiescence predicate.
     * Written only by the consumer (the owning worker); it sits on head's cache
     * line, which the consumer already owns and dirties, so it costs no new
     * shared line and one relaxed store per batch of up to WORKER_POP_BATCH. */
    redisAtomic unsigned int retired;
    redisAtomic unsigned int tail __attribute__((aligned(CACHE_LINE_SIZE)));
    /* ee451: cached_head — non-atomic snapshot of `head`, touched ONLY by the
     * producer (owning IO thread). Sits after `tail` on tail's cache line,
     * which the producer already owns. The producer tests "full" against
     * cached_head and only acquire-reloads the real head when the cache says
     * full. cached_head can only lag the true head — never a false not-full. */
    unsigned int cached_head;
    /* ee451 (S4): batched producer-side push. exQueuePush writes jobs[] and
     * advances this producer-private staged_tail WITHOUT publishing; the owning
     * IO thread publishes all staged jobs with ONE release-store of `tail` per
     * queue at flushExQueues(). In addition to eager parse-batch flushes and the
     * pre-sleep reply walk, ae closes every non-empty partial batch after that
     * loop pass's callbacks. Collapses a busy pass's cross-CCD tail stores
     * without carrying a partial batch into the next poll. Producer-private,
     * lives on tail's line. */
    unsigned int staged_tail;
    client *jobs[TOMO_EX_QUEUE_SIZE_MAX] __attribute__((aligned(CACHE_LINE_SIZE)));
} exQueue;

/* ee451 (S8): free-back ring. For zero-copy large-value replies, a worker
 * takes a +1 ref on the value and the IO thread sends it by reference; the
 * matching decrRefCount must run on the OWNING WORKER (the sole mutator of that
 * shard's value refcounts) to avoid the cross-thread refcount race. After the
 * send, the IO thread enqueues the value here; the worker drains and decrefs.
 * One ring per producing IO thread => SPSC (producer = IO thread iotid,
 * consumer = the owning worker). */
#define FREEBACK_RING_SIZE 1024
#define FREEBACK_RING_MASK (FREEBACK_RING_SIZE - 1)
typedef struct freebackRing {
    redisAtomic unsigned int head __attribute__((aligned(CACHE_LINE_SIZE))); /* consumer (worker) */
    redisAtomic unsigned int tail __attribute__((aligned(CACHE_LINE_SIZE))); /* producer (IO thread) */
    void *objs[FREEBACK_RING_SIZE] __attribute__((aligned(CACHE_LINE_SIZE)));
    /* Retained-ref fence evidence (2026-08-17): server.migration.gen at push, per entry. The drain
     * compares it against the live gen and counts tomokv_freeback_stale_owner_drains when an entry's
     * flight crossed a migration transition — the vacuous-validation witness that the retention
     * window the cutover ref-fence exists for was actually exercised (a run that never trips it
     * proves nothing about that fence). Same producer/consumer discipline as objs[]: written before
     * the tail release-publish, read after the tail acquire. */
    uint32_t gens[FREEBACK_RING_SIZE];
} freebackRing;

/* ee451 (#4): branch-predictor-style forward predictor — a table of 2-bit
 * saturating counters indexed by key hash (gshare: XOR'd with a global-history
 * register). MSB set => predict "forward". Per worker (no sharing). */

/* ee451 (thread-modes v1): polymorphic thread modes (THREAD-MODES-DESIGN.md).
 * A thread is not born io/ex — it HOLDS a mode and the controller flips the
 * mode mix. The per-thread mode/target_mode atomics live on polyThreadCtx (mode
 * is THREAD state, not exThread state).
 *
 * THERE IS DELIBERATELY NO ZERO MODE (2026-07-28, spare removal). TOMO_MODE_PARKED
 * used to be 0, which meant "a zeroed polyThreadCtx is a parked thread" — a valid,
 * silent default. The spare it existed for is gone: the controller has exactly two
 * moves, grow-front (EX->IO) and grow-back (IO->EX), and a poly thread ALWAYS holds
 * a real role. Numbering from 1 makes a zero-initialised mode an UNINITIALISED-
 * CONTEXT BUG that trips the checkpoint assert, instead of silently meaning IO.
 * Do not add a zero enumerator back.
 *
 * UNSET (-1) is the ONLY non-role value and it is not a mode a thread can be shifted
 * to: it is what a ctx publishes between pthread_create and its first checkpoint,
 * so a control-plane reader can tell "not adopted yet" from "running as IO". Both
 * fields are _Atomic int (not the enum type), so the negative is representable.
 * The numeric values of IO/EX are UNCHANGED — DEBUG TOMO-IOLOAD prints them.
 *
 * TOMO_MODE_WB (=3, the 3-stage fork's write-back mode) was deleted 2026-07-28 on the
 * HEAD side: this is the 2-stage line, it had no slice, no knob and no way to be
 * adopted. It is NOT re-added here — a mode no thread can adopt is a control-plane
 * value that only ever mis-reads. 3 stays unused so the 3-stage fork can keep it. */
typedef enum {
    TOMO_MODE_UNSET = -1,
    TOMO_MODE_IO    = 1,
    TOMO_MODE_EX    = 2,
} tomoThreadMode;

typedef struct exThread {
    int id;
    pthread_t thread;
    /* ee451 (flip-actuator, F1): db is IO-thread READ-HOT — processCommand loads
     * server.exThreads[ex_id].db per dispatched op (express/MGET/worker dispatch paths) — but is
     * assigned ONCE in initExThreads and never mutated (the per-node shared kvstore pointer is
     * immutable across reshard and flip). Keep it on this boot-immutable, writer-free
     * head line (id/thread) instead of the tail line the owning worker dirties every op
     * (w_ewma_vsize/ops_total/tm_*), which bounced it cross-core on every dispatch. */
    redisDb *db;
    /* One ready bit per producer lane. The producer writes jobs[], release-publishes
     * its SPSC tail, and only then release-ORs the bit (publish-then-set). The worker
     * loads live words, walks only set bits, clears the bits of lanes it actually
     * probed, and acquire-loads each such lane's REAL tail once more
     * (clear-then-recheck). cached_tail is never allowed to make the keep/clear
     * decision. Thus a publication racing the clear is either observed by the
     * final tail probe or leaves its later bit set; data cannot exist without one
     * of those two witnesses. Locally carried backlog is release-ORed back before
     * the slice exits.
     *
     * A missed bit means a queued fake is never popped: its reply-ready byte is never
     * set, flushid cannot advance, the client's ring wedges full and it stalls forever
     * (the silent reply-loss failure documented at exDispatchPush). Every tail
     * publication therefore goes through exHandoffPublishLane. */
    _Atomic uint64_t q_summary[TOMO_QS_WORDS]
        __attribute__((aligned(CACHE_LINE_SIZE)));
    _Atomic unsigned int stamp_pending; /* CURE2 owner stamp/prune jobs */
    unsigned long long handoff_missed;   /* retained INFO correctness counter; must stay zero */
    unsigned int handoff_dense_tick;     /* retained layout/stat slot */
    /* ee451 #83 (2026-08-05): lanes are HEAP arrays sized to the runtime pool (nlanes =
     * io_threads + num_workers + 1), NOT inline arrays sized to the compile cap. This is the change
     * that makes the cap raise affordable: inline at cap 128 would be ~3MB/worker faulted for even a
     * 4-thread boot; heap-sizing to the runtime count means cap 128 costs the same as cap 32 at a
     * given thread count — the "pay only when thread values need it" property. Layout INSIDE a lane
     * (exQueue/freebackRing) is unchanged, so the SPSC hot path is untouched; the only new cost is
     * one pointer load per lane access, recovered by hoisting the base out of the pop loop and
     * TLS-caching the per-worker dispatch base (exQueueFor). Measured heap == inline at cap 32.
     *
     * ALIGNMENT BREAK is load-bearing: nlanes/queues/freeback are READ-ONLY after init but loaded on
     * EVERY lane access by BOTH sides. Leaving them on the q_summary line (producers fetch_or
     * that line per dispatch) put the lane POINTERS on a contended line: measured p32 GET -5.2%. On
     * their own line both sides cache them Shared forever. */
    __attribute__((aligned(CACHE_LINE_SIZE))) int nlanes;
    exQueue *queues;
    /* ee451 (S8): one free-back ring per IO thread (incl. main = 0). */
    freebackRing *freeback;
    /* ee451 (flip-actuator, F1): `db` relocated to the head line above; the owner-written fields
     * below now have NO IO-thread reader on their line (no dispatch false-sharing). */
    /* ee451 (#3): per-worker windowed write-rate (recent write activity). */
    /* ee451 (gem5): EWMA of served read reply size (≈ value bytes), alpha=1/16. Drives
     * value-size-adaptive pf-w-value: big values ⇒ narrower value-chase (avoid LFB oversub). */
    unsigned int w_ewma_vsize;
    /* ee451 (v8d): monotonic per-worker op counter (control-plane only). Bumped relaxed in the
     * worker loop, sampled once/sec by the EWMA load-balancer in serverCron. Own cache line region
     * (per-worker struct) so the sampling read causes no false sharing on the hot path. */
    _Atomic uint64_t ops_total;   /* single-writer (owning worker); tomoRelaxedBump/Read */
    /* L0 prefetch observability. Single-writer (the owning worker); INFO reads them racily, which
     * is fine for a stat. These exist because EVERY prefetch A/B in this project's history was
     * unfalsifiable without them -- one recorded ablation compared prefetch-OFF against
     * prefetch-OFF because the gate was already shut and nothing reported it. */
    unsigned long long pf_batches;   /* exPrefetchBatch entries */
    unsigned long long pf_gated;     /* ... that returned at the DRAM-residency gate */
    unsigned long long pf_issued;    /* prefetch stages actually issued */
    /* ee451 (flatstore lb): coarse per-group op counts, single-writer (owning worker), non-atomic
     * (the balancer's 1Hz relaxed read tolerates a torn word — it is an approximate load signal).
     * Indexed by TOMO_LB_GROUP(bucket). A worker only touches buckets it owns, so it only writes the
     * groups of its own virtual shard; the balancer sums across workers for per-group load. */
    uint32_t lb_grp_ops[TOMO_LB_GROUPS];
    /* ee451 (v8d): worker loop heartbeat, bumped on EVERY exSlice pass (FLATSTORE FIX D made it
     * unconditional — it is the QSBR quiescence signal; the "migration only" it says here has been
     * false since). The cutover coordinator uses worker B's heartbeat to confirm B has looped past
     * phase==DONE before it publishes migration_active=0 — an RCU-style quiesce, not a timing guess. */
    _Atomic int in_flat_section;  /* FLATSTORE Stage-2 (review fix): 1 while this worker is INSIDE an exSlice batch that may touch a flat table. Coordinator drains this to 0 to quiesce — IDENTITY-COMPLETE (covers mid-flip workers the old tmWorkerLive predicate missed). */
    _Atomic uint64_t loop_seq;
    unsigned long long pf_cached_min;   /* ee451 (v14): cached prefetch gate threshold (avoids a 64-bit divide per batch) */
    unsigned pf_gate_tick;
    int pf_cached_w4;                   /* ee451 (v14): cached value-chase width (avoids budget/ev idiv per batch, gate-open path) */              /* recompute the divide every 64 batches; EWMA moves slowly */
    /* ee451 (v13): forward-predictor / bakeoff state removed with the VF apparatus. */
    /* ee451 (thread-modes step 4, balancer signals): owner-written plain fields, sampled
     * racily by the 4Hz balancer on the main thread (control plane tolerates torn/stale
     * reads — EWMAs/monotonic counters only). All gated on tomokv-thread-mode auto so the
     * balance-off hot path pays one predicted branch. */
    unsigned int tm_qdepth_ewma_q4;  /* leaky EWMA (Q4, alpha 1/8) of STANDING queue backlog:
                                      * items still waiting after a full pop pass (summed over
                                      * producers). Folded on work passes; 0-folded on idle
                                      * EPISODES (yield events), so it decays within µs of real
                                      * idleness but is NOT diluted by cheap spin passes. HIGH =
                                      * the worker is persistently behind its arrivals. */
    /* ee451 (rank-5 cleanup): tm_work_slices / tm_idle_episodes deleted — v1 scaffolding
     * for the pass/episode busy ratios that calibration ruled OUT (see tm_busy_us below);
     * they were written on the hot path and read by nothing.
     * NOTE: the FLATSTORE reclaim fields above added 24B to this region, so the old
     * "tail block packs in one 64B line" claim no longer holds verbatim. They are
     * worker-private (written only by the owning worker), so they share a line only with
     * other worker-private fields — the property that matters is that they are NOT next to
     * loop_seq/in_flat_section, which every worker now polls in flatBatchReady. */
    /* ee451 2026-08-04: wall µs this worker spent with an EMPTY QUEUE, measured as whole idle
     * EPISODES (2 clock reads per episode, never per spin round). This drives the retained
     * worker-only modes. The ratio mode instead pairs exThread.tm_productive_us with
     * tmIoSignal.tm_work_us. Together the worker observations decompose wall:
     *     raw occupied | productive | idle (no work available) | residual (not scheduled)
     * The residual is the one that matters for balance: it means the role is starved of CPU, not
     * of threads, so growing that role cannot help. */
    unsigned int tm_idle_us;
    /* ee451 D svc plane: per-class execution time, FULL population — the duration is computed
     * anyway for cmdstats at the exExecFake exit, so this is two plain adds on the owner's own
     * line. Swept 1 Hz by tomoSvcTick into the published svc EWMAs. Wrap-safe cumulative. */
    unsigned int svc_us[TOMO_SVC_CLASSES];
    unsigned int svc_ops[TOMO_SVC_CLASSES];
    unsigned int rord_worst_age_us;  /* ee451 D: worst stage->exec wait seen (reorder bound check) */
    unsigned int tm_busy_us;         /* Raw request-pass occupancy: first pop -> work-pass end.
                                      * Feeds demand/capacity gates and INFO/A-B; it includes
                                      * scanning/bookkeeping after a pop. Wraps at ~71min. */
    unsigned int tm_productive_us;   /* Productive EX µs: sum of command-execution -> result-
                                      * publication spans for non-empty aggregates. This is the
                                      * direction-ratio U_EX numerator. Wraps at ~71min. */
    /* ee451 FLATSTORE reclaim-capacity fix: this worker's OWN QSBR retire list, its closed grace
     * batches (FIFO: head = oldest so the drain can stop at the first non-ready one), and a recycle
     * list of spent batch headers. Written ONLY by this worker (via flat_local_sink), never by any
     * other thread, so they need no atomics — that is what makes the retire path atomic-free, and it
     * is why main must NOT steal them (a non-live worker can still enter exSlice and push; see the
     * NOTE above flatReclaimTableClose in server.c). The worker frees its own values once the grace
     * passes: same jemalloc arena as the allocation, on a thread that has the cycles.
     * PLACEMENT: appended at the very END of the struct on purpose. Inserting them mid-struct shifted
     * the carefully-tuned hot block (the `db`/tm_* line the F1 false-sharing fix established) and
     * measured -16% on p32 SET; appending leaves every pre-existing field's relative layout intact,
     * and they still sit far from loop_seq/in_flat_section, which every worker polls in
     * flatBatchReady. */
    /* PAD: force the worker-private reclaim fields onto their own cache line. Without this they
     * land on the same line as loop_seq / in_flat_section (build-time _Static_assert in server.c
     * enforces it — an earlier "move to the end of the struct" did NOT actually separate them), and
     * a write on every retire would ping-pong a line every other worker polls in flatBatchReady. */
    char flat_pad[CACHE_LINE_SIZE];
    struct flatRetireNode *flat_retire_local;
    struct flatBatch *flat_batches_local;   /* FIFO head = oldest */
    struct flatBatch *flat_batches_tail;    /* FIFO tail = newest (append point) */
    struct flatBatch *flat_batch_spare;     /* recycled batch headers (a batch is ~544B) */
    int flat_batch_spare_n;                 /* bounded: a long non-worker region can queue many
                                             * batches, and freeing them all would otherwise park an
                                             * unbounded free-list for the process lifetime */
    /* ee451 (bug #42): per-worker ACTIVE-EXPIRE cycle state. All are worker-private (written
     * only by the owning worker from exSlice), so they need no atomics; aexp_active is read racily
     * by INFO on another thread, which is fine for a stat. Appended at the very END for the same
     * reason the reclaim fields above were: inserting mid-struct shifts the tuned hot block.
     *   aexp_gen    last server.tomo_expire_gen this worker acted on (edge-triggers the cycle)
     *   aexp_dbid   sweep cursor: which db (0..dbnum-1) — carried across ticks so every db is swept
     *   aexp_bucket sweep cursor: which bucket-dict WITHIN this worker's own [lo,hi) range
     *   aexp_cursor kvstoreScan cursor inside that one bucket-dict (0 = bucket finished)
     *   asubexp_*   the parallel db/bucket/backlog state for HASH-FIELD TTLs (bug #50). subexpires
     *               is an estore bucketed by the SAME tomo bucket index as the keyspace
     *               (estoreCreate(.., TOMO_BUCKET_BITS), estoreAdd keyed by getKeySlot), so the
     *               owner's [lo,hi) range selects it exactly and no dictScan cursor is needed —
     *               ebExpire drains a bucket to completion or to the field quota.
     * A reshard moves the range under us; the cursor is then simply out of range and restarts at
     * the range start. That costs one re-sweep, never a wrong-owner touch (see exActiveExpireCycle). */
    uint32_t aexp_gen;
    int aexp_dbid;
    int aexp_bucket;
    unsigned long long aexp_cursor;
    unsigned long long aexp_active;         /* keys this worker actively expired (folded into INFO) */
    int asubexp_dbid;
    int asubexp_bucket;
    unsigned long long asubexp_sequence;    /* fields expired while a bucket remains backlogged */
    unsigned long long asubexp_active;      /* fields actively expired (folded into INFO) */
    /* ee451 (2026-07-28): the ARMED per-BUCKET load window (see TOMO_LB_FINE_WIN). lb_fine_win is
     * written ONLY by the main thread (the 1 Hz balancer) and read relaxed by the owning worker;
     * the counters are written ONLY by the owning worker and read (never written) by the balancer,
     * which diffs them against its own snapshot — the same single-writer discipline lb_grp_ops
     * uses, so no atomic RMW appears on the data path. len == 0 => disarmed => never touched.
     * PLACEMENT: at the very END, for the reason the reclaim block above documents — inserting
     * fields mid-struct shifts the tuned hot block and has measured -16% on p32 SET here. Appending
     * leaves every pre-existing field's offset unchanged, which also means an A/B of this feature
     * against the previous build cannot be contaminated by layout. */
    _Atomic uint64_t lb_fine_win;
    uint32_t lb_fine_ops[TOMO_LB_GROUP_BUCKETS];
    /* Flat storage-stage proof counters (2s-flatpf 1d3fe3375, cherry-picked WITHOUT its parent's
     * per-key recency filter — that mechanism was measured a wash at its engineered best case,
     * hot30/cold70 40M, and rejected under hardcode-or-delete). Appended to preserve every tuned
     * predecessor offset; folded by INFO exactly like pf_batches/pf_gated/pf_issued. */
    unsigned long long pf_issued_slot;
    unsigned long long pf_issued_kvobj;
    /* Retained DB-value references (2026-08-17): +1 for every value reference this worker retains
     * PAST its own command execution and returns to itself through the S8 free-back ring — the
     * coalesced-MGET retention (csSubExec CS_MGET) and the RAW zero-copy reply str_ref
     * (_addBulkStrRefToBufferOrList, owner_ex >= 0); -1 per object drained in freebackDrainAll.
     * robj.refcount is a non-atomic whole-word RMW, safe only while a value has exactly ONE
     * mutating thread; a bucket-ownership cutover inside a retention window breaks that identity
     * (freeback decref on the OLD owner vs DB-side refcount ops on the NEW owner = lost update,
     * early free, decrRefCount panic on the corpse). The reshard coordinator therefore waits for
     * this to reach 0 before the flip commits (CO_WAIT_APPLIED, reshardCoordinatorTick).
     * SINGLE-WRITER: every increment site runs on this worker's own thread (retention happens in
     * its command execution / reply build) and the drain decrements on the same thread, so no RMW
     * is needed — tomoExRetainedAdd does a relaxed load + RELEASE store; the coordinator
     * acquire-loads. PLACEMENT: appended at the very end per this struct's standing rule
     * (mid-struct inserts shift the tuned hot block; measured -16% p32 SET). It shares the
     * owner-written stats tail line (pf_issued_*): the coordinator reads it only on cutover ticks,
     * so there is no steady-state cross-thread traffic on the line. */
    _Atomic int retained_refs;
} exThread;

/* Single-writer add/sub for exThread.retained_refs (see the field comment). Owner thread only:
 * relaxed load (no other writer exists) + release store, so a coordinator that acquire-loads 0
 * also observes every decrRefCount that preceded the final decrement. */
static inline void tomoExRetainedAdd(exThread *w, int n) {
    int v = atomic_load_explicit(&w->retained_refs, memory_order_relaxed) + n;
    atomic_store_explicit(&w->retained_refs, v, memory_order_release);
}

typedef struct __attribute__((aligned(CACHE_LINE_SIZE))) {
    uint8_t id;                                 /* The unique ID assigned, if IO_THREADS_MAX_NUM is more
                                                 * than 256, we should also promote the data type. */
    pthread_t tid;                              /* Pthread ID */
    redisAtomic int paused;                     /* Paused status for the io thread. */
    redisAtomic int running;                    /* Running if true, main thread can send clients directly. */
    aeEventLoop *el;                            /* Main event loop of io thread. */
    list *pending_clients;                      /* List of clients with pending writes. */
    list *processing_clients;                   /* List of clients being processed. */
    eventNotifier *pending_clients_notifier;    /* Used to wake up the loop when write should be performed. */
    pthread_mutex_t pending_clients_mutex;      /* Mutex for pending write list */
    list *pending_clients_to_main_thread;       /* Clients that are waiting to be executed by the main thread. */
    list *clients;                              /* IO thread managed clients. */
} IOThread;

/* Context for streaming replDataBuf to database */
typedef struct replDataBufToDbCtx {
    void *privdata;                     /* Private data of context */
    client *client;                     /* Client to process commands */
    size_t applied_offset;              /* Offset applied to the database */
    int  (*should_continue)(void *ctx); /* Check if we should continue */
    void (*yield_callback)(void *ctx);  /* Yield to the event loop */
} replDataBufToDbCtx;

/* ACL information */
typedef struct aclInfo {
    long long user_auth_failures; /* Auth failure counts on user level */
    long long invalid_cmd_accesses; /* Invalid command accesses that user doesn't have permission to */
    long long invalid_key_accesses; /* Invalid key accesses that user doesn't have permission to */
    long long invalid_channel_accesses; /* Invalid channel accesses that user doesn't have permission to */
    long long acl_access_denied_tls_cert; /* TLS clients with cert not matching any existing user. */
} aclInfo;

struct saveparam {
    time_t seconds;
    int changes;
};

struct moduleLoadQueueEntry {
    sds path;
    int argc;
    robj **argv;
};

struct sentinelLoadQueueEntry {
    int argc;
    sds *argv;
    int linenum;
    sds line;
};

struct sentinelConfig {
    list *pre_monitor_cfg;
    list *monitor_cfg;
    list *post_monitor_cfg;
};

struct sharedObjectsStruct {
    robj *ok, *err, *emptybulk, *czero, *cone, *pong, *space,
    *queued, *null[4], *nullarray[4], *emptymap[4], *emptyset[4],
    *emptyarray, *wrongtypeerr, *nokeyerr, *syntaxerr, *sameobjecterr,
    *outofrangeerr, *noscripterr, *loadingerr,
    *slowevalerr, *slowscripterr, *slowmoduleerr, *bgsaveerr,
    *masterdownerr, *roslaveerr, *execaborterr, *noautherr, *noreplicaserr,
    *busykeyerr, *oomerr, *plus, *messagebulk, *pmessagebulk, *subscribebulk,
    *unsubscribebulk, *psubscribebulk, *punsubscribebulk, *del, *unlink,
    *rpop, *lpop, *lpush, *rpoplpush, *lmove, *blmove, *zpopmin, *zpopmax,
    *emptyscan, *multi, *exec, *left, *right, *hset, *srem, *xgroup, *xclaim,
    *script, *replconf, *eval, *persist, *set, *pexpireat, *pexpire,
    *hdel, *hpexpireat, *hpersist, *hsetex,
    *time, *pxat, *absttl, *retrycount, *force, *justid, *entriesread,
    *lastid, *ping, *setid, *keepttl, *load, *createconsumer, *fields,
    *getack, *special_asterick, *special_equals, *default_username, *redacted,
    *ssubscribebulk,*sunsubscribebulk, *smessagebulk,
    *select[PROTO_SHARED_SELECT_CMDS],
    *integers[OBJ_SHARED_INTEGERS],
    *mbulkhdr[OBJ_SHARED_BULKHDR_LEN], /* "*<value>\r\n" */
    *bulkhdr[OBJ_SHARED_BULKHDR_LEN],  /* "$<value>\r\n" */
    *maphdr[OBJ_SHARED_BULKHDR_LEN],   /* "%<value>\r\n" */
    *sethdr[OBJ_SHARED_BULKHDR_LEN];   /* "~<value>\r\n" */
    sds minstring, maxstring;
};

/* ZSETs use a specialized version of Skiplists */

/* Node info placed in level[0].span since it's unused at level 0 (static assert verified) */
typedef struct zskiplistNodeInfo {
    uint16_t sdsoffset;  /* Offset from node start to sds data (after sds header) */
    uint8_t levels;      /* Number of levels in this node (1-32) */
    uint8_t reserved;
} zskiplistNodeInfo;

typedef struct zskiplistNode {
    double score;
    struct zskiplistNode *backward;
    struct zskiplistLevel {
        struct zskiplistNode *forward;
        /* Span is the number of elements between this node and the next node at this level.
         * At level 0, span is repurposed to store zskiplistNodeInfo for regular nodes, */
        unsigned long span;
    } level[];
    /* sds ele is embedded after level[] array (assist zslGetNodeElement(node) to access it) */
} zskiplistNode;

typedef struct zskiplist {
    struct zskiplistNode *header, *tail;
    /* Last node participating at each level. This lets ordered tail inserts
     * update every terminal span without searching for the predecessors. */
    struct zskiplistNode *level_tail[ZSKIPLIST_MAXLEVEL];
    unsigned long length;
    int level;
    size_t alloc_size;
} zskiplist;

typedef struct zset {
    dict *dict;
    zskiplist *zsl;
} zset;

typedef struct clientBufferLimitsConfig {
    unsigned long long hard_limit_bytes;
    unsigned long long soft_limit_bytes;
    time_t soft_limit_seconds;
} clientBufferLimitsConfig;

extern clientBufferLimitsConfig clientBufferLimitsDefaults[CLIENT_TYPE_OBUF_COUNT];

/* The redisOp structure defines a Redis Operation, that is an instance of
 * a command with an argument vector, database ID, propagation target
 * (PROPAGATE_*), and command pointer.
 *
 * Currently only used to additionally propagate more commands to AOF/Replication
 * after the propagation of the executed command. */
typedef struct redisOp {
    robj **argv;
    int argc, dbid, target;
} redisOp;

/* Defines an array of Redis operations. There is an API to add to this
 * structure in an easy way.
 *
 * int redisOpArrayAppend(redisOpArray *oa, int dbid, robj **argv, int argc, int target);
 * void redisOpArrayFree(redisOpArray *oa);
 */
typedef struct redisOpArray {
    redisOp *ops;
    int numops;
    int capacity;
} redisOpArray;

/* This structure is returned by the getMemoryOverheadData() function in
 * order to return memory overhead information. */
struct redisMemOverhead {
    size_t peak_allocated;
    size_t total_allocated;
    size_t startup_allocated;
    size_t repl_backlog;
    size_t replica_fullsync_buffer;
    size_t clients_slaves;
    size_t clients_normal;
    size_t cluster_links;
    size_t aof_buffer;
    size_t eval_caches;
    size_t functions_caches;
    size_t script_vm;
    size_t overhead_total;
    size_t dataset;
    size_t total_keys;
    size_t bytes_per_key;
    float dataset_perc;
    float peak_perc;
    float total_frag;
    ssize_t total_frag_bytes;
    float allocator_frag;
    ssize_t allocator_frag_bytes;
    float allocator_rss;
    ssize_t allocator_rss_bytes;
    float rss_extra;
    size_t rss_extra_bytes;
    size_t num_dbs;
    size_t overhead_db_hashtable_lut;
    size_t overhead_db_hashtable_rehashing;
    unsigned long db_dict_rehashing_count;
    size_t asm_import_input_buffer;
    size_t asm_migrate_output_buffer;
    struct {
        size_t dbid;
        size_t overhead_ht_main;
        size_t overhead_ht_expires;
    } *db;
};

/* Replication error behavior determines the replica behavior
 * when it receives an error over the replication stream. In
 * either case the error is logged. */
typedef enum {
    PROPAGATION_ERR_BEHAVIOR_IGNORE = 0,
    PROPAGATION_ERR_BEHAVIOR_PANIC,
    PROPAGATION_ERR_BEHAVIOR_PANIC_ON_REPLICAS
} replicationErrorBehavior;

/* This structure can be optionally passed to RDB save/load functions in
 * order to implement additional functionalities, by storing and loading
 * metadata to the RDB file.
 *
 * For example, to use select a DB at load time, useful in
 * replication in order to make sure that chained slaves (slaves of slaves)
 * select the correct DB and are able to accept the stream coming from the
 * top-level master. */
typedef struct rdbSaveInfo {
    /* Used saving and loading. */
    int repl_stream_db;  /* DB to select in server.master client. */

    /* Used only loading. */
    int repl_id_is_set;  /* True if repl_id field is set. */
    char repl_id[CONFIG_RUN_ID_SIZE+1];     /* Replication ID. */
    long long repl_offset;                  /* Replication offset. */
} rdbSaveInfo;

#define RDB_SAVE_INFO_INIT {-1,0,"0000000000000000000000000000000000000000",-1}

struct malloc_stats {
    size_t zmalloc_used;
    size_t process_rss;
    size_t allocator_allocated;
    size_t allocator_active;
    size_t allocator_resident;
    size_t allocator_muzzy;
    size_t allocator_frag_smallbins_bytes;
    size_t lua_allocator_allocated;
    size_t lua_allocator_active;
    size_t lua_allocator_resident;
    size_t lua_allocator_frag_smallbins_bytes;
};

/*-----------------------------------------------------------------------------
 * TLS Context Configuration
 *----------------------------------------------------------------------------*/

typedef struct redisTLSContextConfig {
    char *cert_file;                /* Server side and optionally client side cert file name */
    char *key_file;                 /* Private key filename for cert_file */
    char *key_file_pass;            /* Optional password for key_file */
    char *client_cert_file;         /* Certificate to use as a client; if none, use cert_file */
    char *client_key_file;          /* Private key filename for client_cert_file */
    char *client_key_file_pass;     /* Optional password for client_key_file */
    int client_auth_user;           /* Field to be used for automatic TLS authentication based on client TLS certificate */
    char *dh_params_file;
    char *ca_cert_file;
    char *ca_cert_dir;
    char *protocols;
    char *ciphers;
    char *ciphersuites;
    int prefer_server_ciphers;
    int session_caching;
    int session_cache_size;
    int session_cache_timeout;
} redisTLSContextConfig;

/*-----------------------------------------------------------------------------
 * AOF manifest definition
 *----------------------------------------------------------------------------*/
typedef enum {
    AOF_FILE_TYPE_BASE  = 'b', /* BASE file */
    AOF_FILE_TYPE_HIST  = 'h', /* HISTORY file */
    AOF_FILE_TYPE_INCR  = 'i', /* INCR file */
} aof_file_type;

typedef struct {
    sds           file_name;  /* file name */
    long long     file_seq;   /* file sequence */
    aof_file_type file_type;  /* file type */
    long long     start_offset;  /* the start replication offset of the file */
    long long     end_offset;    /* the end replication offset of the file */
} aofInfo;

typedef struct {
    aofInfo     *base_aof_info;       /* BASE file information. NULL if there is no BASE file. */
    list        *incr_aof_list;       /* INCR AOFs list. We may have multiple INCR AOF when rewrite fails. */
    list        *history_aof_list;    /* HISTORY AOF list. When the AOFRW success, The aofInfo contained in
                                         `base_aof_info` and `incr_aof_list` will be moved to this list. We
                                         will delete these AOF files when AOFRW finish. */
    long long   curr_base_file_seq;   /* The sequence number used by the current BASE file. */
    long long   curr_incr_file_seq;   /* The sequence number used by the current INCR file. */
    int         dirty;                /* 1 Indicates that the aofManifest in the memory is inconsistent with
                                         disk, we need to persist it immediately. */
} aofManifest;

/*-----------------------------------------------------------------------------
 * Global server state
 *----------------------------------------------------------------------------*/

/* AIX defines hz to __hz, we don't use this define and in order to allow
 * Redis build on AIX we need to undef it. */
#ifdef _AIX
#undef hz
#endif

#define CHILD_TYPE_NONE 0
#define CHILD_TYPE_RDB 1
#define CHILD_TYPE_AOF 2
#define CHILD_TYPE_LDB 3
#define CHILD_TYPE_MODULE 4

typedef enum childInfoType {
    CHILD_INFO_TYPE_CURRENT_INFO,
    CHILD_INFO_TYPE_AOF_COW_SIZE,
    CHILD_INFO_TYPE_RDB_COW_SIZE,
    CHILD_INFO_TYPE_MODULE_COW_SIZE
} childInfoType;

typedef struct hotkeyStats hotkeyStats;
//ee451

typedef struct {
    int id;
    pthread_t tid;
    aeEventLoop *el;
    int fd;
} ioThreadArgs;

/* ee451 (thread-modes v1, step 2): per-poly-thread context (the poly-thread apparatus).
 * A poly thread owns a FIXED PAIR of identity slots for its whole life, assigned at
 * creation and NEVER shared with another live thread — the historic worker-slot
 * crash class was two live threads aliasing one __thread iotid slot, so slots are
 * statically partitioned, never handed between threads:
 *
 *   io_slot: identity among IO producer slots — iotid while in IO mode. Slots
 *     [1..io_threads) are the BASE io threads (per-slot client lists, worker
 *     queues[slot]/freeback[slot] and fence_acked[slot] all exist for them).
 *     Slots [io_threads .. io_threads+tm_ngrow_io) are the GROWTH slots a worker
 *     adopts when it grow-fronts; initExThreads/initServer size the per-slot state
 *     for them too. Any remaining EX-born io_slot (io_threads+1+w) is a reserved
 *     NAME only (unique, but no listener/event loop) — polyThreadMain refuses IO
 *     mode without an io binding.
 *
 *   ex_slot: identity among workers — iotid = TOMO_IO_THREADS_MAX+1+ex_slot while
 *     in EX mode. Slots [0..num_workers-1] are EX-capable (own an exThread +
 *     shard); a grown io thread keeps its ex_slot and revives into it on grow-back.
 *     IO-born threads' ex_slots (num_workers+1+i) remain reserved names only:
 *     polyThreadMain refuses EX mode without an ex binding.
 *
 * mode is written ONLY by the owning thread, at a checkpoint (between slices,
 * never mid-slice); target_mode ONLY by the control plane (the flip controller,
 * or DEBUG TOMO-MODESHIFT driving it by hand) — with ONE deliberate exception: an
 * io thread completing its own IO-EXIT stores its grow-back target from
 * tmMigServiceOut, because only that thread knows when the last conn left. The
 * iotid TLS store happens exclusively through the role-identity helpers at the
 * checkpoint, BEFORE the first slice using that identity. A dormant EX safety slice
 * takes EX identity only for that slice and restores IO identity before ioSlice. */
typedef struct polyThreadCtx {
    exThread *ex;          /* EX binding (shard + queues); NULL = not EX-capable (step 2) */
    ioThreadArgs *io;      /* IO binding (event loop + listener); NULL = not IO-capable */
    int io_slot;           /* fixed IO identity (iotid in IO mode) */
    int ex_slot;           /* fixed EX identity (iotid = TOMO_IO_THREADS_MAX+1+ex_slot in EX mode) */
    int io_listening;      /* thread-private after boot: listener live (a growth slot starts 0 = bound, dormant) */
    _Atomic int mode;         /* tomoThreadMode; written by the thread at checkpoints. NEVER 0 —
                               * TOMO_MODE_UNSET (-1) until the first checkpoint, then IO or EX. */
    _Atomic int target_mode;  /* tomoThreadMode; written by the control plane. NEVER 0. */
    pthread_t thread;
} polyThreadCtx;

/* ee451 (thread-modes v1.6): CONNECTION MIGRATION — move a plain request/response
 * client from io thread A to io thread B with zero loss. An fd is process-global;
 * only its epoll registration is thread-local, so the client struct (querybuf, reply
 * buffers, pipeline ring) travels intact and only the epoll membership + per-iotid
 * bookkeeping change hands. The handoff happens at the per-conn QUIESCE FENCE
 * (dispatchid==flushid AND replies flushed) — the SAME fence stateful commands gate
 * on (processCommand) — so nothing in-flight references A when B takes over.
 *
 * One mailbox per io-capable thread slot (indexed by iotid, 0..TOMO_IO_THREADS_MAX;
 * main=0 is excluded from migration in v1). The control plane (main thread) never
 * touches another thread's epoll: it only sets a REQUEST and wakes the source, which
 * executes the whole protocol on its OWN event loop. Source hands the client to the
 * destination's INBOX (mutex-guarded MPSC — migration is control-plane-rare, never a
 * hot path) and wakes it; the destination re-registers on its own loop. */
typedef enum {
    TM_MIGREQ_NONE = 0,
    TM_MIGREQ_REBALANCE,     /* move req_data's count conns to req_data's dest (no mode change) */
    TM_MIGREQ_IOEXIT,        /* leave accept group, move ALL migratable conns out; then take the
                              * EX role iff req_data's then_ex (grow-back), else stay IO and idle */
    TM_MIGREQ_IOEXIT_CANCEL  /* abort an in-flight IO-EXIT: re-join the accept group, stay IO (flip give-up) */
} tmMigReqKind;

enum {
    TM_MIGREQ_SLOT_EMPTY = 0,
    TM_MIGREQ_SLOT_READY,
    TM_MIGREQ_SLOT_RESERVED
};

typedef struct tmMigMailbox {
    /* INBOX: clients migrating INTO this thread. Producers = source io threads (push
     * under inbox_lock); consumer = this thread (drains in its beforeSleepIO). */
    list *inbox;
    pthread_mutex_t inbox_lock;
    _Atomic int inbox_n;          /* == listLength(inbox), maintained under the lock; lets the
                                   * consumer skip locking on the common (empty) path */
    eventNotifier *notifier;      /* wakes this thread's loop on inbox push or new request */
    /* SOURCE REQUEST (control plane -> this thread; published before req_pending). */
    _Atomic int req_pending;      /* one node: EMPTY/READY boolean edge; multi-node:
                                   * TM_MIGREQ_SLOT_* publication/reservation state */
    _Atomic uint64_t req_data;    /* kind/dest/count/then_ex packed into one atomic publication:
                                   * multi-node publishers own RESERVED while filling this word,
                                   * then release-publish READY for the source owner. */
    /* SOURCE working state (owning thread only; no lock — single writer). */
    list *migrating_out;          /* clients with CLIENT_MIGRATING, draining to quiesce */
    _Atomic int io_exiting;       /* IO-EXIT in progress: request the EX role once client count
                                   * hits 0. Written by the owner only, but read CROSS-THREAD by
                                   * tmGatherLiveDests / the rebalance dest fallback /
                                   * tomoMigrateTest. Stays 1 through the IO->EX checkpoint and
                                   * throughout the EX role; a future IO adoption release-clears it
                                   * only after publishing mode==IO. Destination eligibility uses
                                   * acquire loads, so no source can select the slot before that
                                   * adoption is complete. */
    int accept_left;              /* IO-EXIT: this thread already left the reuseport group */
    int exit_then_ex;             /* owner's latched copy of req_then_ex for the current exit */
    int exit_logged;              /* one-shot: "IO-EXIT complete" printed for THIS exit — the
                                   * drained state re-fires every service pass, so an unlatched
                                   * log would spam; re-armed when the next exit request lands */
    int batch_dest;               /* REBALANCE: owner-latched destination for the current batch */
} tmMigMailbox;

/* ee451 (#B2): PER-THREAD, PER-COMMAND stats shard.
 *
 * THE DEFECT it cures is #B1's: workers never enter call(), so every counter call() maintains was
 * only ever bumped for the main/IO-thread inline minority. #B1 fixed the ONE global command
 * counter; these are the PER-COMMAND ones behind INFO commandstats and INFO latencystats.
 *
 * Sharding shape: [thread][command id], NOT [command][thread]. A whole thread's per-command block
 * is one contiguous allocation that only that thread writes, so no padding is needed BETWEEN
 * commands (same writer) and there is no false sharing BETWEEN threads (different blocks). The
 * transposed layout would need 64B of padding per (command, thread) pair — ~2.6MB of mostly-cold
 * lines — and would scatter one thread's working set across every command.
 *
 * Indexed by redisCommand.id, the same dense id ACL already assigns (ACLGetCommandID), so
 * subcommands get their own slots and module commands need no special case. */
typedef struct tomoCmdStat {
    _Atomic long long calls;          /* single-writer per (slot,id); tomoRelaxedBump/Read/Set */
    _Atomic long long microseconds;
    _Atomic long long rejected_calls;
    _Atomic long long failed_calls;
} tomoCmdStat;

/* Command-id capacity of one per-thread block. USER_COMMAND_BITS_COUNT is not an arbitrary cap:
 * it is the id space ACL itself can address (ACLSetSelectorCommandBit rejects id >= it), so a
 * command that does not fit here is already un-ACL-able in this server. 1024 ids * 32B = 32KB per
 * block, allocated lazily by the first thread that executes anything. */
#define TOMO_CMDSTAT_IDS USER_COMMAND_BITS_COUNT

/* Errorstats has arbitrary string keys, so it cannot use cmdstat's dense command-id array.
 * Each iotid owns one rax for lookup and publishes an immutable list of the same entries for
 * cross-thread INFO readers. The rax, head and retired list are owner-only; published is the
 * only pointer a reader may follow. Cache-line alignment keeps different error-producing
 * threads from sharing the shard-control line. */
struct redisError;
typedef struct tomoErrorGeneration {
    rax *index;
    struct tomoErrorGeneration *next;
} tomoErrorGeneration;

typedef struct tomoErrorStatShard {
    rax *index;                         /* owner-only current-generation lookup table */
    struct redisError *head;            /* owner-only current immutable-list head */
    tomoErrorGeneration *retired;       /* owner-only tables awaiting reader quiescence */
    uint64_t generation;                /* owner-only generation represented by index/head */
    _Atomic(struct redisError *) published; /* release-published immutable head; readers only */
} __attribute__((aligned(CACHE_LINE_SIZE))) tomoErrorStatShard;

struct redisServer {
    /* new front end io */
    ioThreadArgs *ioThreads;
    int replyWorking[TOMO_IO_THREADS_MAX + 1];
    int custom_io_threads_active;
    /* General */
    pid_t pid;                  /* Main process pid. */
    pthread_t main_thread_id;         /* Main thread id */
    char *configfile;           /* Absolute config file path, or NULL */
    char *executable;           /* Absolute executable file path. */
    char **exec_argv;           /* Executable argv vector (copy). */
    int dynamic_hz;             /* Change hz value depending on # of clients. */
    int config_hz;              /* Configured HZ value. May be different than
                                   the actual 'hz' field value if dynamic-hz
                                   is enabled. */
    mode_t umask;               /* The umask value of the process on startup */
    int hz;                     /* serverCron() calls frequency in hertz */
    int in_fork_child;          /* indication that this is a fork child */
    exThread *exThreads;
    list *clients_pending_ex[TOMO_IO_THREADS_MAX + 1]; //ee451 per-thread worker handoff queue, index 0 = main thread
    /* ee451 (H2 handover): clients PARKED by the cutover range-hold, per io thread. Only the owning
     * io thread touches its own list (park at dispatch, release at beforeSleep, unlink at free), so
     * no lock. See migHoldClientIfDraining: the hold is per-COMMAND and keyed on the migrating
     * bucket range, and it parks the ONE client that asked for the range — never the thread and
     * never a worker, so every other client on this thread, and both workers' other buckets, keep
     * running at full rate for the whole window. */
    list *clients_mig_parked[TOMO_IO_THREADS_MAX + 1];
    /* Clients refused before atomic-MSET group creation, retried only by their owning IO loop. */
    list *clients_atomic_window_parked[TOMO_IO_THREADS_MAX + 1];
    int num_workers;
    /* ee451 (thread-modes): worker-slot accounting.
     * num_workers is the CONFIGURED count W — the number of worker SLOTS that exist. It sizes
     * ex_dbs/exThreads and bounds every control-plane fold over ALL slots (RDB save, DBSIZE,
     * stats, producer-side flushExQueues/cross-shard scratch). Pin-map bases, num_cdb
     * resolution and the poly-registry layout key off it and it never changes at runtime.
     * (The old num_workers_alloc = W+1 sizing existed only for a reserve worker slot that no
     * longer exists, 2026-07-28; alloc was then identically W, so the field was deleted rather
     * than left as a synonym that could drift.)
     * num_workers_live = the CONSUMING worker set: read by the reshard autotuner, KEYS fan-all,
     * FLUSHALL sentinels and RANDOMKEY weighting — anything that would hand work to a thread
     * that must be running exSlice to ever pop it. A grown-front slot is still allocated but
     * not live. Writers: only the flip accounting transaction on main — grow-front claims EX
     * before arming its outbound migration and publishes IO (or rolls EX back); grow-back publishes
     * the complete IO->EX move after the thread adopts EX and before its optional bucket seed.
     * Producer-side coverage stays keyed off num_workers, never num_workers_live, so every allocated
     * slot remains covered through either transition. */
    _Atomic int num_workers_live;
    /* ee451 (per-node flip): per-NODE live prefixes. Node n's live workers are the prefix
     * [n*ex_per_node, n*ex_per_node + tm_node_wlive[n]) — grow-front converts the node's HIGHEST
     * live worker (LIFO within the node), so per-node contiguity holds even though the GLOBAL live
     * set is no longer one prefix. num_workers_live stays the SUM (legacy consumers see totals);
     * membership tests go through tmWorkerLive(). tm_node_iolive counts the node's live io threads
     * (base + grown). topo_nodes==1: node 0 mirrors the globals (identical behavior). */
    _Atomic int tm_node_wlive[16];       /* TM_MAXNODE — keep in sync with server.c */
    _Atomic int tm_node_iolive[16];
    _Atomic int io_threads_live;   /* flip: global count of live IO roles (grows front on ex->io,
                                    * shrinks on io->ex). The slot set is dense only on one node;
                                    * multi-node growth slots are node-partitioned and mode-tested. */
    _Atomic(struct polyThreadCtx *) tm_flip_ctx;
                                   /* the flip claim + published poly ctx. NULL = idle; a private
                                    * marker = claimed while the winner initializes the plain state
                                    * below; otherwise the converting ctx. Every actuator wins the
                                    * NULL->marker CAS before selecting its mutable role slot. */
    int tm_flip_target;            /* successful claimer writes before release-publishing the ctx;
                                    * owning semi-main reads after acquire-loading it. UNSET when idle
                                    * — NOT 0, which is not a mode (see tomoThreadMode). */
    int tm_flip_phase;             /* grow-back phase machine: 0=await IO-EXIT+EX adoption, 1=arm the
                                    * seed migration, 2=await seed FLIP, 3=await IO-EXIT rollback ack */
    _Atomic int tm_flip_gb_state;  /* grow-back commit arbitration: IDLE -> DRAINING -> exactly one
                                    * of COMMITTED/CANCEL_REQUESTED; the latter ends at ROLLED_BACK.
                                    * Prevents the watchdog cancel from racing the IO owner's EX commit. */
    mstime_t tm_flip_abort_ms;     /* grow-back phase-0 watchdog: wall-clock deadline for the conn drain;
                                    * abort past it. TIME, not ticks: tmFlipTick runs per event-loop
                                    * iteration, so a tick count is load-dependent (40 iterations ~ 1ms
                                    * under P32 load). */
    int tm_flip_aborted_node;      /* one-node legacy abort tag; multi-node uses per-node atomics */
    int tm_flip_aborted;           /* one-node legacy abort flag, preserving the frozen controller path */
    _Atomic uint64_t reshard_done_seq;  /* bumped on every completed bucket-range move; the flip
                                    * controller's settle gate waits for this to go QUIET before
                                    * judging a probe (a mid-rebalance measurement under-reads the
                                    * new config and wedges the hill-climb in a worse one). */
    /* ee451 (H2): drain-fence observability. Both are cumulative and exported in INFO, because a
     * fence whose window is never entered proves nothing about the fence (§G vacuous validation).
     * midbatch = how many times the coordinator saw a producer's queue EMPTY while worker A still
     * had that queue's popped batch in flight — i.e. the exact state the old idle-ack acked on.
     * aborts = cutovers abandoned because the fence did not complete in time (see the knob). */
    _Atomic uint64_t reshard_fence_midbatch;
    _Atomic uint64_t reshard_fence_aborts;
    int reshard_fence_timeout_ms;  /* 0 = wait forever; N = abort a cutover whose drain fence has
                                    * not completed within N ms (never flips: pure anti-hang net) */
    int tm_flip_wslot;             /* grow-back: revived worker index (ex_slot) being seeded */
    int tm_ngrow_io;               /* flip: number of growth io binding slots reserved */
    /* ee451 (auto symmetric pool, 2026-07-29): in thread-mode AUTO the operator's io/ex split is the
     * STARTING POINT, not the reachable range — every non-anchor thread is provisioned as a worker
     * with a dormant io binding (one base IO per node, pool_per_node-1 workers) and the split is
     * applied at boot by BIRTHING each node's worker suffix in IO mode. These two carry GLOBAL live
     * totals for that split; everywhere else `io_threads`/`num_workers` keep their provisioned-count
     * meaning (pin bases, registry layout) and the LIVE counts are io_threads_live /
     * num_workers_live as before. In STATIC mode they are just the configured counts and nothing
     * below changes. */
    int tm_boot_io_live;           /* io threads LIVE at boot (io_threads_live seed) */
    int tm_boot_w_live;            /* workers LIVE at boot (num_workers_live seed, bucket-table split) */
    int tm_pool_symmetric;         /* 1 = the auto remap above was applied */
    int tm_flip_rebalance;     /* flip: on grow-front, EWMA-pull existing conns onto the new io thread (default 1) */
    int tm_client_lb;          /* continuous client LB (tmClientBalanceCron); split from tm_flip_rebalance 2026-07-28 */
    /* Tomo KV-dev custom threading/pipelining runtime state. io_threads/ex_threads come from
     * redis.conf (`tomokv-thread-io`, `tomokv-thread-ex`); pipeline_ring_depth comes from
     * `tomokv-pipeline-depth`, and ex_queue_size/ex_queue_mask are derived from the thread shape
     * (tomokv-ex-queue-depth is retired — see the derivation in initServer). */
    int io_threads;
    int ex_threads;
    /* One immutable numeric gate for the complete io_uring network backend.
     * 0 keeps epoll and allocates no ring/buffer/op machinery; 1 selects the
     * existing ring; 2 selects the isolated Helio-style staged backend. */
    int io_uring;
    /* FLATSTORE is UNCONDITIONAL as of 2026-07-28 (thredis_flat_store / flat_load_pct deleted):
     * a shared node db (shared_node_dbs) is always a flat table, and the resize trigger uses the
     * FLAT_LOAD_PCT compile-time target. `shared_node_dbs` alone is the predicate everywhere. */
    _Atomic int flat_resize_active[TOMO_NODES_MAX]; /* FLATSTORE Stage-2: per-node worker park gates */
    /* ee451 (bug #42, worker active expiry): the CADENCE signal for the per-worker active-expire
     * cycle. Main is the sole writer and bumps with the owner-local relaxed load/store idiom;
     * workers poll relaxed and run one bounded pass after observing a new generation. It carries
     * no payload: an old value merely coalesces ticks until a later exSlice. */
    _Atomic uint32_t tomo_expire_gen;
    /* ee451 (thread-modes v1, step 2): the poly-thread apparatus — every tomokv thread runs
     * polyThreadMain with a preset mode. The pool is ALWAYS fully active: there is no reserve
     * thread, so the pool size is exactly io_threads + num_workers and a flip only ever moves
     * the boundary between the two roles. DERIVED from tomokv-thread-mode (both `auto` and
     * `static` run the poly threads; they differ only in whether the controller is allowed to
     * actuate). Not a user knob. */
    int poly_threads;
    /* (modeshift_test DELETED 2026-07-28 with the tomokv-modeshift-test knob: it was the
     * hand-driven mode-retarget used before the controller existed; nothing read it.) */
    /* tomokv-thread-mode: TOMO_THREAD_MODE_AUTO | TOMO_THREAD_MODE_STATIC. IMMUTABLE.
     * The ONE knob that decides whether the io/ex split may move at runtime. */
    int thread_mode;
    /* ee451 (thread-modes step 4): the flip controller may ACTUATE. DERIVED: 1 iff
     * thread_mode == AUTO. 0 = no signal folding anywhere (every hook is behind this bool, so
     * the hot path pays one predicted branch) and the boot split from tomokv-thread-io/-ex is
     * held for the life of the process. Not a user knob. */
    int thread_auto;
    /* (tomokv-flip-signal DELETED 2026-08-10: the productive-work ratio is the only trigger
     * signal; see the tombstone note in server.c.) */

    /* ee451 node-topology config (2026-07-22): the pool is nodes * cores_per_node threads, ALWAYS
     * fully active (no reserve thread). io_per_node + ex_per_node <= cores_per_node. io_threads /
     * ex_threads are DERIVED (nodes * per-node). thread_mode=static fixes the split; auto lets the
     * controller flip the io/ex boundary WITHIN each node's core budget. */
    int prefetch_ex_level;   /* tomokv-prefetch-ex: 0=off, 1=storage, 2=storage+xnode messages */
    int topo_nodes;            /* tomokv-nodes: node count. NOT necessarily a NUMA node — it owns
                                * one or more adjacent shared-L3 groups in `ccd` mode and one NUMA
                                * domain in `numa` mode. Hence topo_ (topology), not numa_. */
    int cores_per_node;        /* tomokv-cores-per-node; pool = topo_nodes * cores_per_node */
    int io_per_node;           /* provisioned base-IO stride per node; configured IO split in STATIC */
    int ex_per_node;           /* provisioned worker stride per node; configured EX split in STATIC;
                                * their sum stays within cores_per_node */
    /* (The ex_threads_min/max pair is GONE 2026-07-28, following the IO-side pair before it.
     * Their only reader was the reserve-thread quorum balancer, deleted with the reserve. The
     * bounds are structural, not numeric: grow-front refuses below 2 live workers in a node,
     * grow-back refuses when the node has no grown io slot to reclaim, and the IO-side headroom
     * is tm_ngrow_io. A derived-then-never-read field is worse than no field.) */
    /* ee451 (thread-modes): coordinator side-channel for FLIP-driven migrations.
     * 0 = ordinary migration (no flip tail);
     * 2 = GROW-FRONT: the converting worker's whole range has been moved out and torn down,
     *     so the coordinator tail retargets tm_flip_ctx to its flip target (IO).
     * 3 = GROW-BACK seed: associates the migration with the active flip but needs no coordinator
     *     role-change tail (IO->EX accounting was already published at EX adoption).
     * Written inside reshardArm's admission lock and read + cleared by the single coordinator of
     * that migration, so a competing ordinary arm cannot inherit a flip action. */
    int tm_mig_flip_action;
    int pipeline_ring_depth;
    int ex_queue_size;
    unsigned int ex_queue_mask;
    /* (ex_dispatch_mask DELETED 2026-07-28: a v8 leftover — worker routing goes through the
     * ex_bucket_table indirection, never a mask, so nothing had read it since v8.) */
    /* ee451 (v8): bucket->worker map (hot path) and the per-worker contiguous range ends
     * (worker i owns buckets [i? ex_bucket_end[i-1]:0, ex_bucket_end[i]) — used by
     * the adjacent-boundary-shift rebalancer). */
    uint8_t  ex_bucket_table[TOMO_BUCKETS];
    int      ex_bucket_end[TOMO_EX_THREADS_MAX];
    /* ee451 (v8d): online resharding = drain fence + ownership flip. migration_active is read once
     * (relaxed) per command on the hot path -> isolated on its own read-mostly cache line (written
     * only at migration start/end) to avoid false-sharing every IO core. The rest lives on a
     * separate line. (The effect-log/scan/replay counters that used to live here — issued_seq,
     * applied_seq, log, outstanding_a_refs, scan_done — went with the copy engine.) */
    _Alignas(64) _Atomic unsigned char migration_active;
    struct {
        _Atomic uint64_t gen;          /* phase-transition epoch (release on write, acquire on read) */
        int lo, hi;                    /* migrating bucket range [lo,hi) (published before active=1) */
        int src, dst;                  /* adjacent workers: A (src) -> B (dst) */
        _Atomic int phase;             /* migPhase: IDLE/COPYING/DRAINING/FLIPPED/DONE */
        _Atomic int fence_acked[TOMO_IO_THREADS_MAX + 1]; /* cutover drain-fence: per producer-slot ack.
                                        * Set by worker A when it EXECUTES that slot's drain sentinel.
                                        * (The old "or the queue looked empty for 2ms" idle-ack was
                                        * removed 2026-07-28 — see the H2 note on reshardCoordinatorTick:
                                        * an empty queue is the steady state of a busy worker.) */
        _Atomic uint64_t fence_gen;    /* MONOTONIC across migrations; producers push once per value */
        _Atomic uint64_t fence_stale_acks; /* ee451 O1: count of drain sentinels rejected because they
                                            * belonged to an earlier (aborted) fence generation. */
    } migration;
    redisDb **ex_dbs;
    /* ee451 (shared-kv S0.2b): the PHYSICAL db arrays — exactly one per NODE.
     * ex_dbs[w] ALIASES node_dbs[tmNodeOfWorker(w)], so every existing exThreads[w].db
     * access lands on the node's shared kvstore; a worker owns the bucket-dicts of its bucket
     * range within it (dict index == bucket). shared_node_dbs gates every behavior fork
     * (SHARED_MT kvstores, flush barrier, reshard=flip, capture off). */
    redisDb **node_dbs;
    int n_node_dbs;            /* number of physical node db arrays == node count */
    int shared_node_dbs;       /* 1 = workers share per-node kvstores (workers-per-node > 1) */
    redisDb *db;
    dict *commands;             /* Command table */
    dict *orig_commands;        /* Command table before command renaming. */
    aeEventLoop *el;
    /* Errorstats control is split from the INFO-reader pin so INFO's cold RMW never invalidates
     * the state cache line read on each error reply. state = generation<<1 | disabled. */
    struct {
        _Atomic uint64_t state;
        char _pad[CACHE_LINE_SIZE - sizeof(uint64_t)];
    } errorstats_ctl __attribute__((aligned(CACHE_LINE_SIZE)));
    struct {
        _Atomic unsigned int n;
        char _pad[CACHE_LINE_SIZE - sizeof(unsigned int)];
    } errorstats_readers __attribute__((aligned(CACHE_LINE_SIZE)));
    tomoErrorStatShard errorstats[TOMO_STAT_SLOTS];
    unsigned int lruclock; /* Clock for LRU eviction */
    redisAtomic int shutdown_asap; /* Shutdown ordered by signal handler. */
    redisAtomic int crashing;      /* Server is crashing report. */
    mstime_t shutdown_mstime;   /* Timestamp to limit graceful shutdown. */
    redisAtomic int last_sig_received;      /* Indicates the last SIGNAL received, if any (e.g., SIGINT or SIGTERM). */
    int shutdown_flags;         /* Flags passed to prepareForShutdown(). */
    int activerehashing;        /* Incremental rehash in serverCron() */
    int active_defrag_running;  /* Active defragmentation running (holds current scan aggressiveness) */
    char *pidfile;              /* PID file path */
    int arch_bits;              /* 32 or 64 depending on sizeof(long) */
    int cronloops;              /* Number of times the cron function run */
    char runid[CONFIG_RUN_ID_SIZE+1];  /* ID always different at every exec. */
    int sentinel_mode;          /* True if this instance is a Sentinel. */
    size_t initial_memory_usage; /* Bytes used after initialization. */
    int always_show_logo;       /* Show logo even for non-stdout logging. */
    redisAtomic unsigned int in_exec; /* # of threads currently inside EXEC */
    int busy_module_yield_flags;         /* Are we inside a busy module? (triggered by RM_Yield). see BUSY_MODULE_YIELD_ flags. */
    const char *busy_module_yield_reply; /* When non-null, we are inside RM_Yield. */
    char *ignore_warnings;      /* Config: warnings that should be ignored. */
    int client_pause_in_transaction; /* Was a client pause executed during this Exec? */
    int thp_enabled;                 /* If true, THP is enabled. */
    size_t page_size;                /* The page size of OS. */
    redisAtomic int running;    /* Running if true, IO threads can send clients without notification */
    /* Modules */
    dict *moduleapi;            /* Exported core APIs dictionary for modules. */
    dict *sharedapi;            /* Like moduleapi but containing the APIs that
                                   modules share with each other. */
    dict *module_configs_queue; /* Unmapped configs are queued here, assumed to be module config. Applied after modules are loaded during startup or arguments to loadex. */
    list *loadmodule_queue;     /* List of modules to load at startup. */
    int module_pipe[2];         /* Pipe used to awake the event loop by module threads. */
    pid_t child_pid;            /* PID of current child */
    int child_type;             /* Type of current child */
    redisAtomic int module_gil_acquring; /* Indicates whether the GIL is being acquiring by the main thread. */
    /* Networking */
    int port;                   /* TCP listening port */
    int tls_port;               /* TLS listening port */
    int tcp_backlog;            /* TCP listen() backlog */
    char *bindaddr[CONFIG_BINDADDR_MAX]; /* Addresses we should bind to */
    int bindaddr_count;         /* Number of addresses in server.bindaddr[] */
    char *bind_source_addr;     /* Source address to bind on for outgoing connections */
    char *unixsocket;           /* UNIX socket path */
    unsigned int unixsocketperm; /* UNIX socket permission (see mode_t) */
    connListener listeners[CONN_TYPE_MAX]; /* TCP/Unix/TLS even more types */
    uint32_t socket_mark_id;    /* ID for listen socket marking */
    connListener clistener;     /* Cluster bus listener */
    //ee451 per-thread client lists, index 0 = main thread, 1..N = io threads
    list *clients[TOMO_IO_THREADS_MAX + 1];
    list *clients_to_close[TOMO_IO_THREADS_MAX + 1];
    list *clients_pending_write[TOMO_IO_THREADS_MAX + 1];
    list *clients_with_pending_ref_reply[TOMO_IO_THREADS_MAX + 1];
    list *slaves, *monitors;    /* List of slaves and MONITORs */
    //ee451 per-thread current/executing client, index 0 = main thread, 1..N = io threads,
    // and TOMO_IO_THREADS_MAX+1 .. +TOMO_EX_THREADS_MAX = worker threads. Worker threads run
    // command procs directly (bypassing call()) and index these arrays by their OWN iotid, so
    // they must have private slots. Sharing slot 0 with the main thread (the pre-fix behavior,
    // since workers never set iotid) is a data race: a worker reads/writes server.current_client[0]
    // — a foreign client the main thread concurrently reassigns and frees — which caused the
    // worker-side UAF read (lookupKey/getKeySlot, Signature B) and the heap corruption in the
    // overwrite old-value free path (dbSetValue -> tryDeferFreeClientObject, Signature A).
    /* ee451 (audit fix, hot-path): exExecFake stores to these 4x per executed command (set+clear
     * across both arrays) from every worker; as plain 8-byte slots, 8 workers' slots share one 64B
     * line = cross-core store ping-pong on the hottest path (the padding cure that went to kstat/
     * netstat but was missed here). Pad each slot to a cache line. Accessed as .p everywhere. */
    struct { client *p; char _pad[CACHE_LINE_SIZE - sizeof(client *)]; }
        current_client[TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX] __attribute__((aligned(CACHE_LINE_SIZE)));
    struct { client *p; char _pad[CACHE_LINE_SIZE - sizeof(client *)]; }
        executing_client[TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX] __attribute__((aligned(CACHE_LINE_SIZE)));

#ifdef LOG_REQ_RES
    char *req_res_logfile; /* Path of log file for logging all requests and their replies. If NULL, no logging will be performed */
    unsigned int client_default_resp;
#endif

    rax *clients_timeout_table; /* Radix tree for blocked clients timeouts. */
    /* ee451 (A-F.4): `int execution_nesting` USED TO LIVE HERE. It is now the thread-local
     * `execution_nesting` declared below — see the block comment at its definition in server.c. */
    rax *clients_index[TOMO_IO_THREADS_MAX + 1];         /* Active clients dictionary by client ID. */
    uint32_t paused_actions;   /* Bitmask of actions that are currently paused */
    list *postponed_clients;       /* List of postponed clients */
    pause_event client_pause_per_purpose[NUM_PAUSE_PURPOSES];
    char neterr[ANET_ERR_LEN];   /* Error buffer for anet.c */
    dict *migrate_cached_sockets;/* MIGRATE cached sockets */
    redisAtomic uint64_t next_client_id; /* Next client unique ID. Incremental. */
    int protected_mode;         /* Don't accept external connections. */
    int io_threads_num;         /* Number of IO threads to use. */
    int io_threads_clients_num[IO_THREADS_MAX_NUM]; /* Number of clients assigned to each IO thread. */
    int io_threads_active;      /* Is IO threads currently active? */
    pendingCommandPool cmd_pool; /* Shared pool for reusing pendingCommand,
                                  * only when IO threads disabled */
    int prefetch_batch_max_size;/* Maximum number of keys to prefetch in a single batch */
    long long events_processed_while_blocked; /* processEventsWhileBlocked() */
    int enable_protected_configs;    /* Enable the modification of protected configs, see PROTECTED_ACTION_ALLOWED_* */
    int enable_debug_cmd;            /* Enable DEBUG commands, see PROTECTED_ACTION_ALLOWED_* */
    int enable_module_cmd;           /* Enable MODULE commands, see PROTECTED_ACTION_ALLOWED_* */

    /* RDB / AOF loading information */
    volatile sig_atomic_t loading; /* We are loading data from disk if true */
    volatile sig_atomic_t async_loading; /* We are loading data without blocking the db being served */
    off_t loading_total_bytes;
    off_t loading_rdb_used_mem;
    off_t loading_loaded_bytes;
    time_t loading_start_time;
    off_t loading_process_events_interval_bytes;
    /* Fields used only for stats */
    time_t stat_starttime;          /* Server start time */
    long long stat_numcommands;     /* legacy scalar (unused on hot path; folded from cmdstat at INFO) */
    long long stat_numconnections;  /* Number of connections received */
    long long stat_expiredkeys;     /* Number of expired keys */
    long long stat_expiredkeys_active; /* Number of expired keys by active expire */
    long long stat_expired_subkeys; /* Number of expired subkeys (Currently only hash-fields) */
    long long stat_expired_subkeys_active; /* Number of expired subkeys by active expire */
    double stat_expired_stale_perc; /* Percentage of keys probably expired */
    long long stat_expired_time_cap_reached_count; /* Early expire cycle stops.*/
    long long stat_expire_cycle_time_used; /* Cumulative microseconds used. */
    long long stat_evictedkeys;     /* Number of evicted keys (maxmemory) */
    long long stat_evictedclients;  /* Number of evicted clients */
    long long stat_evictedscripts;  /* Number of evicted lua scripts. */
    long long stat_total_eviction_exceeded_time;  /* Total time over the memory limit, unit us */
    monotime stat_last_eviction_exceeded_time;  /* Timestamp of current eviction start, unit us */
    long long stat_keyspace_hits;   /* legacy scalar (unused on hot path; folded from kstat at INFO) */
    long long stat_keyspace_misses; /* legacy scalar (unused on hot path; folded from kstat at INFO) */
    /* ee451 (S6): per-thread keyspace hit/miss counters. The single shared
     * stat_keyspace_hits/misses lines were RMW'd by EVERY worker on EVERY
     * lookup — one cache line bounced across all CCDs per command. Each thread
     * now bumps its own cache-line-isolated slot (indexed by iotid); INFO folds
     * them and CONFIG RESETSTAT zeroes them. Pure stats, no control-flow read,
     * so this also removes a genuine non-atomic data race on the globals. */
    struct {
        _Atomic long long hits;     /* single-writer per slot; tomoRelaxedBump/Read/Set */
        _Atomic long long misses;
        /* Atomic bag-resolution census. These share the owner-local line that
         * lookupKey already dirties for hits/misses, avoiding a shared RMW. */
        _Atomic unsigned long long atomic_read_fast;
        _Atomic unsigned long long atomic_read_slow;
        _Atomic long long flat_hash_reuses; /* guarded tomo_key_h consumed by a FLAT lookup */
        char _pad[CACHE_LINE_SIZE - 5 * sizeof(long long)];
    } kstat[TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX] __attribute__((aligned(CACHE_LINE_SIZE)));
    /* ee451 (#B1): per-thread executed-command counters. stat_numcommands lived only in call(),
     * which worker threads never enter (they run cmd->proc directly from exExecFake, and the
     * scatter subs from csSubExec), so INFO total_commands_processed / instantaneous_ops_per_sec /
     * DEBUG TOMO-JESTATS's per-op derivations reported only the main+IO-thread inline fraction —
     * on this fork, a small minority of the traffic. Same cure as kstat/netstat/dirty_shard rather
     * than a shared ++: one shared line RMW'd by every worker is BOTH a lost-update race on a
     * non-atomic long long AND a cache line bounced across every CCD once per command. Each thread
     * bumps its own cache-line-isolated slot (indexed by iotid); getNumCommands() folds on the COLD
     * read path (INFO/DEBUG/cron) and CONFIG RESETSTAT zeroes them.
     * COUNTING RULE: one increment per CLIENT-VISIBLE command, wherever it executes —
     *   call()          inline/main-thread commands (and blocked.c's unblock accounting),
     *   exExecFake()    single-key worker-routed commands,
     *   csReassemble()  cross-shard groups, counted ONCE per group at completion, NOT once per
     *                   scatter sub: an 8-key MGET is one command the client sent, not 4. */
    struct {
        _Atomic long long n;        /* single-writer per slot; tomoRelaxedBump/Read/Set */
        char _pad[CACHE_LINE_SIZE - sizeof(long long)];
    } cmdstat[TOMO_STAT_SLOTS] __attribute__((aligned(CACHE_LINE_SIZE)));
    /* ee451 (#B2): per-thread PER-COMMAND stats — the commandstats/latencystats half of #B1.
     * cmd->calls / ->microseconds / ->rejected_calls / ->failed_calls / ->latency_histogram were
     * only ever touched inside call(), so INFO commandstats and INFO latencystats reported the
     * inline minority of this fork's traffic and nothing a worker executed. They were ALSO written
     * concurrently by every IO thread that does enter call() — a non-atomic RMW on one shared line
     * per command, i.e. lost updates as well as an undercount.
     *
     * Each entry below is a pointer to that thread's own block (see tomoCmdStat), allocated on the
     * thread's first executed command and published with a RELEASE store; readers acquire-load.
     * The pointer array itself is written once per thread and then read-only, so it does not bounce.
     * getCommandStats() folds legacy scalar + every slot on the COLD read path only. */
    tomoCmdStat * _Atomic cmdstat_percmd[TOMO_STAT_SLOTS];
    /* ee451 (#B2): per-thread PER-COMMAND latency histograms, same indexing. A histogram cannot be
     * "summed" like a counter, so these are MERGED (hdr_add, which adds the source's counts into
     * the destination's matching buckets) into one throwaway histogram at read time — see
     * tomoCmdLatMerge(). All shards share the identical hdr configuration, so the merge is exact:
     * every bucket maps 1:1 and hdr_add drops nothing. Each histogram has exactly ONE writer, so
     * this also removes the pre-existing multi-IO-thread lost-update race on the single shared
     * cmd->latency_histogram. */
    struct hdr_histogram ** _Atomic cmdlat_percmd[TOMO_STAT_SLOTS];
    /* ee451 (#B2): per-thread error-reply counters. server.stat_total_error_replies was a plain
     * ++ from afterErrorReply, which runs on whatever thread emitted the reply — every worker
     * included. Sharding it fixes that race AND gives the "did THIS command fail?" delta that
     * commandstats' failed_calls needs on threads that never enter call(): the thread's own slot
     * is a single-writer counter, so (after - before) around a proc is exact with no atomic RMW
     * and no shared line. getTotalErrorReplies() folds. */
    struct {
        _Atomic long long n;        /* single-writer per slot; tomoRelaxedBump/Read/Set */
        char _pad[CACHE_LINE_SIZE - sizeof(long long)];
    } errstat[TOMO_STAT_SLOTS] __attribute__((aligned(CACHE_LINE_SIZE)));
    /* ee451 (#A2): per-thread network byte counters. stat_net_input/output_bytes were single shared
     * atomics hit with a lock xadd once per read event AND once per write event from EVERY io thread —
     * a contended cross-core line (plus the two adjacent counters false-sharing one line). Same cure
     * as kstat: each thread bumps its own cache-line-isolated slot (indexed by iotid) when
     * hardwired-on (v13, knob retired); readers fold via getNetInput/OutputBytes(). The legacy atomics stay
     * as the fold BASELINE (repl paths + resets still use them). */
    struct {
        _Atomic long long in;       /* single-writer per slot; tomoRelaxedBump/Read/Set. Note the
                                     * cross-thread RESETSTAT zeroing keeps its lost-update window
                                     * (an in-flight owner bump can overwrite the reset) but is now
                                     * defined behavior; exact resets would need per-slot baselines. */
        _Atomic long long out;
        char _pad[CACHE_LINE_SIZE - 2 * sizeof(long long)];
    } netstat[TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX] __attribute__((aligned(CACHE_LINE_SIZE)));
    long long stat_active_defrag_hits;      /* number of allocations moved */
    long long stat_active_defrag_misses;    /* number of allocations scanned but not moved */
    long long stat_active_defrag_key_hits;  /* number of keys with moved allocations */
    long long stat_active_defrag_key_misses;/* number of keys scanned and not moved */
    long long stat_active_defrag_scanned;   /* number of dictEntries scanned */
    long long stat_total_active_defrag_time; /* Total time memory fragmentation over the limit, unit us */
    monotime stat_last_active_defrag_time; /* Timestamp of current active defrag start */
    size_t stat_peak_memory;        /* Max used memory record */
    time_t stat_peak_memory_time;   /* Time when stat_peak_memory was recorded */
    long long stat_aof_rewrites;    /* number of aof file rewrites performed */
    long long stat_aofrw_consecutive_failures; /* The number of consecutive failures of aofrw */
    long long stat_rdb_saves;       /* number of rdb saves performed */
    long long stat_rdb_consecutive_failures; /* The number of consecutive failures of rdb saves */
    long long stat_fork_time;       /* Time needed to perform latest fork() */
    double stat_fork_rate;          /* Fork rate in GB/sec. */
    long long stat_total_forks;     /* Total count of fork. */
    long long stat_rejected_conn;   /* Clients rejected because of maxclients */
    long long stat_sync_full;       /* Number of full resyncs with slaves. */
    long long stat_sync_partial_ok; /* Number of accepted PSYNC requests. */
    long long stat_sync_partial_err;/* Number of unaccepted PSYNC requests. */
    list *slowlog;                  /* SLOWLOG list of commands */
    long long slowlog_entry_id;     /* SLOWLOG current entry ID */
    long long slowlog_log_slower_than; /* SLOWLOG time limit (to get logged) */
    unsigned long slowlog_max_len;     /* SLOWLOG max number of items logged */
    struct malloc_stats cron_malloc_stats; /* sampled in serverCron(). */
    redisAtomic long long stat_net_input_bytes; /* Bytes read from network. */
    redisAtomic long long stat_net_output_bytes; /* Bytes written to network. */
    redisAtomic long long stat_net_repl_input_bytes; /* Bytes read during replication, added to stat_net_input_bytes in 'info'. */
    redisAtomic long long stat_net_repl_output_bytes; /* Bytes written during replication, added to stat_net_output_bytes in 'info'. */
    size_t stat_current_cow_peak;   /* Peak size of copy on write bytes. */
    size_t stat_current_cow_bytes;  /* Copy on write bytes while child is active. */
    monotime stat_current_cow_updated;  /* Last update time of stat_current_cow_bytes */
    size_t stat_current_save_keys_processed;  /* Processed keys while child is active. */
    size_t stat_current_save_keys_total;  /* Number of keys when child started. */
    size_t stat_rdb_cow_bytes;      /* Copy on write bytes during RDB saving. */
    size_t stat_aof_cow_bytes;      /* Copy on write bytes during AOF rewrite. */
    size_t stat_module_cow_bytes;   /* Copy on write bytes during module fork. */
    double stat_module_progress;   /* Module save progress. */
    size_t stat_clients_type_memory[CLIENT_TYPE_COUNT];/* Mem usage by type */
    size_t stat_cluster_links_memory; /* Mem usage by cluster links */
    long long stat_unexpected_error_replies; /* Number of unexpected (aof-loading, replica to master, etc.) error replies */
    long long stat_total_error_replies; /* Total number of issued error replies ( command + rejected errors ) */
    long long stat_dump_payload_sanitizations; /* Number deep dump payloads integrity validations. */
    redisAtomic long long stat_io_reads_processed[IO_THREADS_MAX_NUM]; /* Number of read events processed by IO / Main threads */
    redisAtomic long long stat_io_writes_processed[IO_THREADS_MAX_NUM]; /* Number of write events processed by IO / Main threads */
    redisAtomic long long stat_client_qbuf_limit_disconnections;  /* Total number of clients reached query buf length limit */
    long long stat_client_outbuf_limit_disconnections;  /* Total number of clients reached output buf length limit */
    long long stat_cluster_incompatible_ops; /* Number of operations that are incompatible with cluster mode */
    long long stat_total_prefetch_entries;  /* Total number of prefetched dict entries */
    long long stat_total_prefetch_batches;  /* Total number of prefetched batches */
    /* The following two are used to track instantaneous metrics, like
     * number of operations per second, network traffic. */
    struct {
        long long last_sample_base;  /* The divisor of last sample window */
        long long last_sample_value; /* The dividend of last sample window */
        long long samples[STATS_METRIC_SAMPLES];
        int idx;
    } inst_metric[STATS_METRIC_COUNT];
    long long stat_reply_buffer_shrinks; /* Total number of output buffer shrinks */
    long long stat_reply_buffer_expands; /* Total number of output buffer expands */
    monotime el_start;
    /* The following two are used to record the max number of commands executed in one eventloop.
     * Note that commands in transactions are also counted. */
    long long el_cmd_cnt_start;
    long long el_cmd_cnt_max;
    /* The sum of active-expire, active-defrag and all other tasks done by cron and beforeSleep,
       but excluding read, write and AOF, which are counted by other sets of metrics. */
    monotime el_cron_duration;
    durationStats duration_stats[EL_DURATION_TYPE_NUM];

    /* Hotkey tracking */
    hotkeyStats *hotkeys;

    /* Configuration */
    int verbosity;                  /* Loglevel in redis.conf */
    int hide_user_data_from_log;    /* In the event of an assertion failure, hide command arguments from the operator */
    int maxidletime;                /* Client timeout in seconds */
    int tcpkeepalive;               /* Set SO_KEEPALIVE if non-zero. */
    int active_expire_enabled;      /* Can be disabled for testing purposes. */
    int active_expire_effort;       /* From 1 (default) to 10, active effort. */
    /* ee451 (F-clock family, 2026-07-28): these two are now ONLY the process-wide operator
     * override set by `DEBUG SET-ALLOW-ACCESS-EXPIRED` (the tcl suites use it to read expired
     * hash fields). The per-execution-context guard that module.c raises around unlink /
     * keyspace-notification callbacks moved to the thread-locals below — see the comment on
     * tomo_access_expired for why keeping it here was a correctness bug, not a style wart. */
    int allow_access_expired;       /* If > 0, allow access to logically expired keys */
    int allow_access_trimmed;       /* If > 0, allow access to logically trimmed keys */
    int active_defrag_enabled;
    int sanitize_dump_payload;      /* Enables deep sanitization for ziplist and listpack in RDB and RESTORE. */
    int skip_checksum_validation;   /* Disable checksum validation for RDB and RESTORE payload. */
    int jemalloc_bg_thread;         /* Enable jemalloc background thread */
    int active_defrag_configuration_changed; /* defrag configuration has been changed and need to reconsider
                                              * active_defrag_running in computeDefragCycles. */
    size_t active_defrag_ignore_bytes; /* minimum amount of fragmentation waste to start active defrag */
    int active_defrag_threshold_lower; /* minimum percentage of fragmentation to start active defrag */
    int active_defrag_threshold_upper; /* maximum percentage of fragmentation at which we use maximum effort */
    int active_defrag_cycle_min;       /* minimal effort for defrag in CPU percentage */
    int active_defrag_cycle_max;       /* maximal effort for defrag in CPU percentage */
    unsigned long active_defrag_max_scan_fields; /* maximum number of fields of set/hash/zset/list to process from within the main dict scan */
    size_t client_max_querybuf_len; /* Limit for client query buffer length */
    int lookahead;                  /* how many commands in each client pipeline to decode and prefetch */
    int dbnum;                      /* Total number of configured DBs */
    int supervised;                 /* 1 if supervised, 0 otherwise. */
    int supervised_mode;            /* See SUPERVISED_* */
    int daemonize;                  /* True if running as a daemon */
    int set_proc_title;             /* True if change proc title */
    char *proc_title_template;      /* Process title template format */
    clientBufferLimitsConfig client_obuf_limits[CLIENT_TYPE_OBUF_COUNT];
    _Atomic int pause_cron;         /* Don't run cron tasks (debug); peer semi-mains also read it */
    int dict_resizing;              /* Whether to allow main dict and expired dict to be resized (debug) */
    int latency_tracking_enabled;   /* 1 if extended latency tracking is enabled, 0 otherwise. */
    double *latency_tracking_info_percentiles; /* Extended latency tracking info output percentile list configuration. */
    int latency_tracking_info_percentiles_len;
    int memory_tracking_enabled;    /* Account used memory per slot */
    unsigned int max_new_tls_conns_per_cycle; /* The maximum number of tls connections that will be accepted during each invocation of the event loop. */
    unsigned int max_new_conns_per_cycle; /* The maximum number of tcp connections that will be accepted during each invocation of the event loop. */
    int cluster_compatibility_sample_ratio; /* Sampling ratio for cluster mode incompatible commands. */
    int lazyexpire_nested_arbitrary_keys; /* If disabled, avoid lazy-expire from commands that touch arbitrary keys (SCAN/RANDOMKEY) within transactions */

    /* AOF persistence */
    int aof_enabled;                /* AOF configuration */
    int aof_state;                  /* AOF_(ON|OFF|WAIT_REWRITE) */
    int aof_fsync;                  /* Kind of fsync() policy */
    char *aof_filename;             /* Basename of the AOF file and manifest file */
    char *aof_dirname;              /* Name of the AOF directory */
    int aof_no_fsync_on_rewrite;    /* Don't fsync if a rewrite is in prog. */
    int aof_rewrite_perc;           /* Rewrite AOF if % growth is > M and... */
    off_t aof_rewrite_min_size;     /* the AOF file is at least N bytes. */
    off_t aof_rewrite_base_size;    /* AOF size on latest startup or rewrite. */
    off_t aof_current_size;         /* AOF current size (Including BASE + INCRs). */
    off_t aof_last_incr_size;       /* The size of the latest incr AOF. */
    off_t aof_last_incr_fsync_offset; /* AOF offset which is already requested to be synced to disk.
                                       * Compare with the aof_last_incr_size. */
    int aof_flush_sleep;            /* Micros to sleep before flush. (used by tests) */
    int aof_rewrite_scheduled;      /* Rewrite once BGSAVE terminates. */
    sds aof_buf;      /* AOF buffer, written before entering the event loop */
    int aof_fd;       /* File descriptor of currently selected AOF file */
    int aof_selected_db; /* Currently selected DB in AOF */
    mstime_t aof_flush_postponed_start; /* mstime of postponed AOF flush */
    mstime_t aof_last_fsync;            /* mstime of last fsync() */
    time_t aof_rewrite_time_last;   /* Time used by last AOF rewrite run. */
    time_t aof_rewrite_time_start;  /* Current AOF rewrite start time. */
    time_t aof_cur_timestamp;       /* Current record timestamp in AOF */
    int aof_timestamp_enabled;      /* Enable record timestamp in AOF */
    int aof_lastbgrewrite_status;   /* C_OK or C_ERR */
    unsigned long aof_delayed_fsync;  /* delayed AOF fsync() counter */
    int aof_rewrite_incremental_fsync;/* fsync incrementally while aof rewriting? */
    int rdb_save_incremental_fsync;   /* fsync incrementally while rdb saving? */
    int aof_last_write_status;      /* C_OK or C_ERR */
    int aof_last_write_errno;       /* Valid if aof write/fsync status is ERR */
    int aof_load_truncated;         /* Don't stop on unexpected AOF EOF. */
    off_t aof_load_corrupt_tail_max_size; /* The max size of broken AOF tail than can be ignored. */
    int aof_use_rdb_preamble;       /* Specify base AOF to use RDB encoding on AOF rewrites. */
    redisAtomic int aof_bio_fsync_status; /* Status of AOF fsync in bio job. */
    redisAtomic int aof_bio_fsync_errno;  /* Errno of AOF fsync in bio job. */
    aofManifest *aof_manifest;       /* Used to track AOFs. */
    int aof_disable_auto_gc;         /* If disable automatically deleting HISTORY type AOFs?
                                        default no. (for testings). */

    /* RDB persistence */
    long long dirty;                /* Changes to DB from the last save. With opt_perthread_dirty ON this
                                     * holds the FOLD BASELINE (bgsave subtracts / resets adjust it); the
                                     * live per-command counts accumulate in dirty_shard[] and getDirty()
                                     * returns dirty + sum(shards). */
    long long dirty_before_bgsave;  /* Used to restore dirty on failed BGSAVE */
    /* ee451 (#4): per-thread shard of the dirty counter. The single `dirty` line was ++'d by EVERY EX
     * worker on EVERY write (exExecFake calls cmd->proc directly) -> one cache line bounced across all
     * CCDs per write, plus a genuine non-atomic torn-++ race between workers. Each thread now bumps its
     * own cache-line-isolated slot (indexed by iotid); getDirty() folds them. The call() before/after
     * delta and in-command local deltas read this thread's slot only (DIRTY_LOCAL) so they capture just
     * the running command's changes, unpolluted by concurrent threads. Gated by opt_perthread_dirty. */
    struct {
        long long v;
        char _pad[CACHE_LINE_SIZE - sizeof(long long)];
    } dirty_shard[TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX] __attribute__((aligned(CACHE_LINE_SIZE)));
    long long rdb_last_load_keys_expired;  /* number of expired keys when loading RDB */
    long long rdb_last_load_keys_loaded;   /* number of loaded keys when loading RDB */
    int bgsave_aborted;             /* Set when killing a child, to treat it as aborted even if it succeeds. */
    struct saveparam *saveparams;   /* Save points array for RDB */
    int saveparamslen;              /* Number of saving points */
    char *rdb_filename;             /* Name of RDB file */
    int rdb_compression;            /* Use compression in RDB? */
    int rdb_checksum;               /* Use RDB checksum? */
    int rdb_del_sync_files;         /* Remove RDB files used only for SYNC if
                                       the instance does not use persistence. */
    time_t lastsave;                /* Unix time of last successful save */
    time_t lastbgsave_try;          /* Unix time of last attempted bgsave */
    time_t rdb_save_time_last;      /* Time used by last RDB save run. */
    time_t rdb_save_time_start;     /* Current RDB save start time. */
    int rdb_bgsave_scheduled;       /* BGSAVE when possible if true. */
    int rdb_child_type;             /* Type of save by active child. */
    int lastbgsave_status;          /* C_OK or C_ERR */
    int stop_writes_on_bgsave_err;  /* Don't allow writes if can't BGSAVE */
    int rdb_pipe_read;              /* RDB pipe used to transfer the rdb data */
                                    /* to the parent process in diskless repl. */
    int rdb_child_exit_pipe;        /* Used by the diskless parent allow child exit. */
    connection **rdb_pipe_conns;    /* Connections which are currently the */
    int rdb_pipe_numconns;          /* target of diskless rdb fork child. */
    int rdb_pipe_numconns_writing;  /* Number of rdb conns with pending writes. */
    char *rdb_pipe_buff;            /* In diskless replication, this buffer holds data */
    int rdb_pipe_bufflen;           /* that was read from the rdb pipe. */
    int rdb_key_save_delay;         /* Delay in microseconds between keys while
                                     * writing aof or rdb. (for testings). negative
                                     * value means fractions of microseconds (on average). */
    int key_load_delay;             /* Delay in microseconds between keys while
                                     * loading aof or rdb. (for testings). negative
                                     * value means fractions of microseconds (on average). */
    /* Pipe and data structures for child -> parent info sharing. */
    int child_info_pipe[2];         /* Pipe used to write the child_info_data. */
    int child_info_nread;           /* Num of bytes of the last read from pipe */
    /* Propagation of commands in AOF / replication */
    redisOpArray also_propagate;    /* Additional command to propagate. */
    int replication_allowed;        /* Are we allowed to replicate? */
    /* Logging */
    char *logfile;                  /* Path of log file */
    int syslog_enabled;             /* Is syslog enabled? */
    char *syslog_ident;             /* Syslog ident */
    int syslog_facility;            /* Syslog facility */
    int crashlog_enabled;           /* Enable signal handler for crashlog.
                                     * disable for clean core dumps. */
    int memcheck_enabled;           /* Enable memory check on crash. */
    int use_exit_on_panic;          /* Use exit() on panic and assert rather than
                                     * abort(). useful for Valgrind. */
    /* Shutdown */
    int shutdown_timeout;           /* Graceful shutdown time limit in seconds. */
    int shutdown_on_sigint;         /* Shutdown flags configured for SIGINT. */
    int shutdown_on_sigterm;        /* Shutdown flags configured for SIGTERM. */

    /* Replication (master) */
    char replid[CONFIG_RUN_ID_SIZE+1];  /* My current replication ID. */
    char replid2[CONFIG_RUN_ID_SIZE+1]; /* replid inherited from master*/
    long long master_repl_offset;   /* My current replication offset */
    long long second_replid_offset; /* Accept offsets up to this for replid2. */
    redisAtomic long long fsynced_reploff_pending;/* Largest replication offset to
                                     * potentially have been fsynced, applied to
                                       fsynced_reploff only when AOF state is AOF_ON
                                       (not during the initial rewrite) */
    long long fsynced_reploff;      /* Largest replication offset that has been confirmed to be fsynced */
    int slaveseldb;                 /* Last SELECTed DB in replication output */
    int repl_ping_slave_period;     /* Master pings the slave every N seconds */
    replBacklog *repl_backlog;      /* Replication backlog for partial syncs */
    long long repl_backlog_size;    /* Backlog circular buffer size */
    long long repl_full_sync_buffer_limit; /* Accumulated repl data limit during rdb channel replication */
    replDataBuf repl_full_sync_buffer;  /* Accumulated replication data for rdb channel replication */
    time_t repl_backlog_time_limit; /* Time without slaves after the backlog
                                       gets released. */
    time_t repl_no_slaves_since;    /* We have no slaves since that time.
                                       Only valid if server.slaves len is 0. */
    int repl_min_slaves_to_write;   /* Min number of slaves to write. */
    int repl_min_slaves_max_lag;    /* Max lag of <count> slaves to write. */
    int repl_good_slaves_count;     /* Number of slaves with lag <= max_lag. */
    int repl_diskless_sync;         /* Master send RDB to slaves sockets directly. */
    int repl_diskless_load;         /* Slave parse RDB directly from the socket.
                                     * see REPL_DISKLESS_LOAD_* enum */
    int repl_diskless_sync_delay;   /* Delay to start a diskless repl BGSAVE. */
    int repl_diskless_sync_max_replicas;/* Max replicas for diskless repl BGSAVE
                                         * delay (start sooner if they all connect). */
    int repl_rdb_channel;           /* Config used to determine if the replica should
                                     * use rdb channel replication for full syncs. */
    int repl_debug_pause;           /* Debug config to force the main process to pause. */
    size_t repl_buffer_mem;         /* The memory of replication buffer. */
    list *repl_buffer_blocks;       /* Replication buffers blocks list
                                     * (serving replica clients and repl backlog) */
    time_t repl_stream_lastio;      /* Unix time of the latest sending replication stream. */
    /* Replication (slave) */
    char *masteruser;               /* AUTH with this user and masterauth with master */
    sds masterauth;                 /* AUTH with this password with master */
    char *masterhost;               /* Hostname of master */
    int masterport;                 /* Port of master */
    int repl_timeout;               /* Timeout after N seconds of master idle */
    client *master;     /* Client that is master for this slave */
    client *cached_master; /* Cached master to be reused for PSYNC. */
    int repl_syncio_timeout; /* Timeout for synchronous I/O calls */
    int repl_state;          /* Replication status if the instance is a slave */
    int repl_rdb_ch_state; /* State of the replica's rdb channel during rdb channel replication */
    int repl_main_ch_state; /* State of the replica's main channel during rdb channel replication */
    uint64_t repl_num_master_disconnection; /* Number of master connection was disconnected */
    uint64_t repl_main_ch_client_id; /* Main channel client id received in +RDBCHANNELSYNC reply. */
    off_t repl_transfer_size; /* Size of RDB to read from master during sync. */
    off_t repl_transfer_read; /* Amount of RDB read from master during sync. */
    off_t repl_transfer_last_fsync_off; /* Offset when we fsync-ed last time. */
    connection *repl_transfer_s;     /* Slave -> Master SYNC connection */
    connection *repl_rdb_transfer_s; /* Slave -> Master FULL SYNC connection (RDB download) */
    int repl_transfer_fd;    /* Slave -> Master SYNC temp file descriptor */
    char *repl_transfer_tmpfile; /* Slave-> master SYNC temp file name */
    time_t repl_transfer_lastio; /* Unix time of the latest read, for timeout */
    int repl_serve_stale_data; /* Serve stale data when link is down? */
    int repl_slave_ro;          /* Slave is read only? */
    int repl_slave_ignore_maxmemory;    /* If true slaves do not evict. */
    time_t repl_down_since; /* Unix time at which link with master went down */
    time_t repl_up_since;   /* Unix time that master link is fully up and healthy */
    int repl_disable_tcp_nodelay;   /* Disable TCP_NODELAY after SYNC? */
    int slave_priority;             /* Reported in INFO and used by Sentinel. */
    int replica_announced;          /* If true, replica is announced by Sentinel */
    int slave_announce_port;        /* Give the master this listening port. */
    char *slave_announce_ip;        /* Give the master this ip address. */
    int propagation_error_behavior; /* Configures the behavior of the replica
                                     * when it receives an error on the replication stream */
    int repl_ignore_disk_write_error;   /* Configures whether replicas panic when unable to
                                         * persist writes to AOF. */
    /* The following two fields is where we store master PSYNC replid/offset
     * while the PSYNC is in progress. At the end we'll copy the fields into
     * the server->master client structure. */
    char master_replid[CONFIG_RUN_ID_SIZE+1];  /* Master PSYNC runid. */
    long long master_initial_offset;           /* Master PSYNC offset. */
    int repl_slave_lazy_flush;          /* Lazy FLUSHALL before loading DB? */
    /* Synchronous replication. */
    list *clients_waiting_acks;         /* Clients waiting in WAIT or WAITAOF. */
    int get_ack_from_slaves;            /* If true we send REPLCONF GETACK. */
    long long repl_current_sync_attempts;    /* Number of times in current configuration, the replica attempted to sync since the last success. */
    long long repl_total_sync_attempts;      /* Number of times in current configuration, the replica attempted to sync to a master  */
    time_t repl_disconnect_start_time;       /* Unix time that master disconnection start */
    time_t repl_total_disconnect_time;       /* The total cumulative time we've been disconnected as a replica, visible when the link is up too. */
    /* Limits */
    unsigned int maxclients;            /* Max number of simultaneous clients */
    unsigned long long maxmemory;   /* Max number of memory bytes to use */
    ssize_t maxmemory_clients;       /* Compatibility config; nonzero is unsupported */
    int maxmemory_policy;           /* Policy for key eviction */
    int maxmemory_samples;          /* Precision of random sampling */
    int maxmemory_eviction_tenacity;/* Aggressiveness of eviction processing */
    int lfu_log_factor;             /* LFU logarithmic counter factor. */
    int lfu_decay_time;             /* LFU counter decay factor. */
    long long proto_max_bulk_len;   /* Protocol bulk length maximum size. */
    int oom_score_adj_values[CONFIG_OOM_COUNT];   /* Linux oom_score_adj configuration */
    int oom_score_adj;                            /* If true, oom_score_adj is managed */
    int disable_thp;                              /* If true, disable THP by syscall */
    /* Blocked clients */
    unsigned int blocked_clients;   /* # of clients executing a blocking cmd.*/
    unsigned int blocked_clients_by_type[BLOCKED_NUM];
    list *unblocked_clients[TOMO_IO_THREADS_MAX + 1]; /* list of clients to unblock before next loop */
    list *ready_keys;        /* List of readyList structures for BLPOP & co */
    /* Client side caching. */
    unsigned int tracking_clients;  /* # of clients with tracking enabled.*/
    size_t tracking_table_max_keys; /* Max number of keys in tracking table. */
    list *tracking_pending_keys; /* tracking invalidation keys pending to flush */
    list *pending_push_messages; /* pending publish or other push messages to flush */
    /* Zip structure config, see redis.conf for more information  */
    size_t hash_max_listpack_entries;
    size_t hash_max_listpack_value;
    size_t set_max_intset_entries;
    size_t set_max_listpack_entries;
    size_t set_max_listpack_value;
    size_t zset_max_listpack_entries;
    size_t zset_max_listpack_value;
    size_t hll_sparse_max_bytes;
    size_t stream_node_max_bytes;
    long long stream_node_max_entries;
    /* Stream IDMP parameters */
    long long stream_idmp_duration;     /* Default IDMP duration in seconds. */
    long long stream_idmp_maxsize;      /* Default IDMP max entries. */
    /* List parameters */
    int list_max_listpack_size;
    int list_compress_depth;
    /* time cache */
    redisAtomic time_t unixtime; /* Unix time sampled every cron cycle. */
    time_t timezone;            /* Cached timezone. As set by tzset(). */
    redisAtomic int daylight_active; /* Currently in daylight saving time. */
    mstime_t mstime;            /* 'unixtime' in milliseconds. */
    ustime_t ustime;            /* 'unixtime' in microseconds. */
    int accum_call_count_since_ustime; /* Command count since last ustime update */
    monotime monotonic_us_when_ustime; /* Monotonic time when last ustime update */
    mstime_t cmd_time_snapshot; /* Time snapshot of the root execution nesting. */
    size_t blocking_op_nesting; /* Nesting level of blocking operation, used to reset blocked_last_cron. */
    long long blocked_last_cron; /* Indicate the mstime of the last time we did cron jobs from a blocking operation */
    /* Pubsub */
    kvstore *pubsub_channels;  /* Map channels to list of subscribed clients */
    dict *pubsub_patterns;  /* A dict of pubsub_patterns */
    int notify_keyspace_events; /* Events to propagate via Pub/Sub. This is an
                                   xor of NOTIFY_... flags. */
    kvstore *pubsubshard_channels;  /* Map shard channels in every slot to list of subscribed clients */
    unsigned int pubsub_clients; /* # of clients in Pub/Sub mode */
    redisAtomic unsigned int watching_clients; /* # of clients watching keys (workers may dirty/unwatch) */
    /* Cluster */
    int cluster_enabled;      /* Is cluster enabled? */
    int cluster_port;         /* Set the cluster port for a node. */
    mstime_t cluster_node_timeout; /* Cluster node timeout. */
    mstime_t cluster_ping_interval;    /* A debug configuration for setting how often cluster nodes send ping messages. */
    char *cluster_configfile; /* Cluster auto-generated config file name. */
    long long asm_handoff_max_lag_bytes; /* Maximum lag in bytes before pausing writes for ASM handoff. */
    long long asm_write_pause_timeout; /* Timeout in milliseconds to pause writes during ASM handoff. */
    long long asm_sync_buffer_drain_timeout; /* Timeout in milliseconds for sync buffer to drain during ASM. */
    int asm_max_archived_tasks; /* Maximum number of archived ASM tasks to keep in memory. */
    struct clusterState *cluster;  /* State of the cluster */
    int cluster_migration_barrier; /* Cluster replicas migration barrier. */
    int cluster_allow_replica_migration; /* Automatic replica migrations to orphaned masters and from empty masters */
    int cluster_slave_validity_factor; /* Slave max data age for failover. */
    int cluster_require_full_coverage; /* If true, put the cluster down if
                                          there is at least an uncovered slot.*/
    int cluster_slave_no_failover;  /* Prevent slave from starting a failover
                                       if the master is in failure state. */
    char *cluster_announce_ip;  /* IP address to announce on cluster bus. */
    char *cluster_announce_hostname;  /* hostname to announce on cluster bus. */
    char *cluster_announce_human_nodename;  /* Human readable node name assigned to a node. */
    int cluster_preferred_endpoint_type; /* Use the announced hostname when available. */
    int cluster_announce_port;     /* base port to announce on cluster bus. */
    int cluster_announce_tls_port; /* TLS port to announce on cluster bus. */
    int cluster_announce_bus_port; /* bus port to announce on cluster bus. */
    int cluster_module_flags;      /* Set of flags that Redis modules are able
                                      to set in order to suppress certain
                                      native Redis Cluster features. Check the
                                      REDISMODULE_CLUSTER_FLAG_*. */
    int cluster_module_trim_disablers; /* Number of module requests to disable trimming */
    int cluster_allow_reads_when_down; /* Are reads allowed when the cluster
                                        is down? */
    int cluster_config_file_lock_fd;   /* cluster config fd, will be flocked. */
    unsigned long long cluster_link_msg_queue_limit_bytes;  /* Memory usage limit on individual link msg queue */
    int cluster_drop_packet_filter; /* Debug config that allows tactically
                                   * dropping packets of a specific type */
    int cluster_slot_stats_enabled; /* Cluster slot usage statistics tracking enabled. */
    /* Scripting */
    unsigned int lua_arena;         /* eval lua arena used in jemalloc. */
    mstime_t busy_reply_threshold;  /* Script / module timeout in milliseconds */
    int pre_command_oom_state;         /* OOM before command (script?) was started */
    int script_disable_deny_script;    /* Allow running commands marked "noscript" inside a script. */
    int lua_enable_deprecated_api;     /* Config to enable deprecated api */
    int key_memory_histograms;         /* Config to enable key memory histograms */
    /* Lazy free */
    int lazyfree_lazy_eviction;
    int lazyfree_lazy_expire;
    int lazyfree_lazy_server_del;
    int lazyfree_lazy_user_del;
    int lazyfree_lazy_user_flush;
    /* Latency monitor */
    long long latency_monitor_threshold;
    dict *latency_events;
    /* ACLs */
    char *acl_filename;           /* ACL Users file. NULL if not configured. */
    unsigned long acllog_max_len; /* Maximum length of the ACL LOG list. */
    sds requirepass;              /* Remember the cleartext password set with
                                     the old "requirepass" directive for
                                     backward compatibility with Redis <= 5. */
    int acl_pubsub_default;      /* Default ACL pub/sub channels flag */
    aclInfo acl_info; /* ACL info */
    /* Assert & bug reporting */
    int watchdog_period;  /* Software watchdog period in ms. 0 = off */
    /* System hardware info */
    size_t system_memory_size;  /* Total memory in system as reported by OS */
    /* TLS Configuration */
    int tls_cluster;
    int tls_replication;
    int tls_auth_clients;
    redisTLSContextConfig tls_ctx_config;
    /* cpu affinity */
    char *server_cpulist; /* cpu affinity list of redis server main/io thread. */
    char *bio_cpulist; /* cpu affinity list of bio thread. */
    char *aof_rewrite_cpulist; /* cpu affinity list of aof rewrite process. */
    char *bgsave_cpulist; /* cpu affinity list of bgsave process. */
    /* Sentinel config */
    struct sentinelConfig *sentinel_config; /* sentinel config to load at startup time. */
    /* Coordinate failover info */
    mstime_t failover_end_time; /* Deadline for failover command. */
    int force_failover; /* If true then failover will be forced at the
                         * deadline, otherwise failover is aborted. */
    char *target_replica_host; /* Failover target host. If null during a
                                * failover then any replica can be used. */
    int target_replica_port; /* Failover target port */
    int failover_state; /* Failover state */
    int cluster_allow_pubsubshard_when_down; /* Is pubsubshard allowed when the cluster
                                                is down, doesn't affect pubsub global. */
    long reply_buffer_peak_reset_time; /* The amount of time (in milliseconds) to wait between reply buffer peak resets */
    int reply_buffer_resizing_enabled; /* Is reply buffer resizing enabled (1 by default) */
    int reply_copy_avoidance_enabled; /* Is reply copy avoidance enabled (1 by default) */
    /* ee451 (v4): per-optimization runtime toggles for the ablation sweep. All
     * default 1 (= the v3 behavior). Pinning is intentionally NOT toggleable.
     * S3 cache-line mask isolation is a compile-time struct layout and is also
     * not represented here (always on). */
    int zerocopy_min_value;    /* v8: zero-copy reply forwarding gated by value size. 0 = OFF;
                                * N = use copy-avoidance only for values >= N bytes (it pays on
                                * large values, +20-24% at 16-64KB; neutral below ~1KB). */
    int num_cdb;               /* S5: resolved at init = one bus per worker when the box has >1 L3 domain, else 1 */
    /* Per-STAGE prefetch width fields DELETED 2026-07-28 with the eight tomokv-pf-w-* knobs
     * (struct/argv/keyobj/keybytes/hash/entry/value/nextop). THE STAGES THEMSELVES ARE UNTOUCHED
     * — see exPrefetchBatch in server.c and the constants next to WORKER_POP_BATCH above. The
     * fields and their config entries were deleted together deliberately: a retired knob's field
     * was initialised by the config table, so a field that outlives its knob falls to 0 by
     * omission. No field, no way to zero it. */
    /* ee451: independent batch + value-forward trigger knobs (runtime). */
    size_t detected_l3_bytes;      /* v13: L3 size self-read from sysfs at startup (for -1=auto thresholds) */
    int detected_l3_domains;      /* L1a: distinct L3 domains (CCX/CCD); workers-per-L3 for the prefetch gate */
    int os_opts;               /* v12: OS/Linux opts — TCP_QUICKACK on client sockets + MADV_HUGEPAGE on hot allocs. default off. */
    int os_busypoll;           /* v12: SO_BUSY_POLL on client sockets (kernel busy-polls; burns CPU). SEPARATE knob — suspected v12 throughput regression. default off. */
    /* xshard knob fields DELETED 2026-07-28 (mget-coalesce / setop-coalesce / mset-move /
     * xshard-guard / -pipeline / -localfast / mcmd-lock): every one of them is now an
     * unconditional property of the fork, folded into the code at its use sites. */
    int strict_order;          /* cross-IO-thread strict ordering: 0=off (batched rotation), 1=strict (global-oldest first), N>=2=eps of (N-1)us to retain batching. default 0. */
    int phase_trace_sample;    /* tomokv-phase-trace: 0=off; N samples one P1 request in N per IO owner. */
    int prefetch_io_level;     /* tomokv-prefetch-io: 0=off, 1=next-run ring-tail write warm,
                                * 2=mode 1 plus topology-gated cross-node reply prefetch. */
    int tomo_reorder;          /* ee451 D: admission reorder level. 0=off (no machinery on the
                                * path), 1=worker partition (structural), 2=+class SJF + same-key
                                * guard + same-bucket grouping. Mutually exclusive with
                                * strict_order (reorder defers). default 0. */
    int tomo_atomic;           /* tomokv-atomic: epoch-versioned MSET/MGET atomicity. default off. */
    int tomo_atomic_window;    /* max admitted atomic MSET groups; 0 = unlimited. default 64: smaller in-flight populations keep version piles shallow and the whole atomic pipeline cache-hot — measured better than 512 in EVERY regime (64-key adversarial AND 2M realistic, 1:1 AND 9:1). */
    /* (no xshard_inline_* field: the inline region is sized per command by csInlineWant) */
    /* ee451 (v8d): EWMA adaptive load-balancer (control plane only — never on the routing hot path). */
    char *pin_io_spec;         /* tomokv-pin-io: per-role-per-node cpu spec, e.g.
                                * "node0=0-3 node1=8,9,10,11". Used only with pin-mode static. */
    char *pin_ex_spec;         /* tomokv-pin-ex: same grammar, for the EX (worker) role. */
    int reshard_min_ops;         /* tomokv-key-lb: 0 = balancer OFF (nothing runs, nothing is
                                  * allocated); N = min mean shard ops/sec before a shard is a
                                  * migration candidate. Default 20000. */
    /* 2s-auto T2/T3/D1/D3 mode fields DELETED 2026-07-28 (drain-tail-skip / express-slim /
     * fake-buf / fake-ring-depth) and l3_kb with them: all are unconditionally in their AUTO
     * arm now. The controllers themselves are untouched -- only the mode selectors are gone. */
    _Atomic double express_hit_ewma;   /* T3 controller EWMA of GET+SET hit ratio [0,1];
                                        * single-writer (main cron), read by IO threads in the
                                        * dispatch hot path — tomoRelaxedRead ONCE per decision
                                        * (the old double-read Schmitt gate could act on two
                                        * different values) */
    /* prefetch_min_keys / pf_value_budget_kb DELETED 2026-07-28 with tomokv-prefetch-min-keys and
     * tomokv-pf-value-budget-kb. Both shipped in their AUTO arm and both AUTO derivations are now
     * unconditional in exPrefetchBatch: the residency gate is 8 x (detected L3 / workers-per-L3
     * domain) / measured footprint, and the value-chase budget is half this worker's L3 share.
     * Fields deleted, not seeded — see the note on the pf_w_* deletion above. */
    int pin_mode;                /* tomokv-pin-mode: TOMO_PIN_FLOAT / _CCD / _NUMA / _STATIC.
                                  * Also decides what a "node" IS (see topo_nodes). */
    /* Local environment */
    char *locale_collate;
    int dbg_assert_keysizes;       /* Assert keysizes histogram after each command */
    int dbg_assert_alloc_per_slot; /* Assert per-slot alloc_size after each command */
};

/* we use 6 so that all getKeyResult fits a cacheline */
#define MAX_KEYS_BUFFER 6

typedef struct {
    int pos; /* The position of the key within the client array */
    int flags; /* The flags associated with the key access, see
                  CMD_KEY_* for more information */
} keyReference;

/* A result structure for the various getkeys function calls. It lists the
 * keys as indices to the provided argv. This functionality is also re-used
 * for returning channel information.
 */
typedef struct {
    int numkeys;                                 /* Number of key indices return */
    int size;                                    /* Available array size */
    keyReference keysbuf[MAX_KEYS_BUFFER];       /* Pre-allocated buffer, to save heap allocations */
    keyReference *keys;                          /* Key indices array, points to keysbuf or heap */
} getKeysResult;
#define GETKEYS_RESULT_INIT { 0, MAX_KEYS_BUFFER, {{0}}, NULL }

/*-----------------------------------------------------------------------------
 * Hotkey tracking
 *----------------------------------------------------------------------------*/

/* Hotkeys tracking metric flags */
#define HOTKEYS_TRACK_CPU (1ULL << 0)
#define HOTKEYS_TRACK_NET (1ULL << 1)
#define HOTKEYS_METRICS_COUNT 2 /* NOTE: update if adding new metric */

/* A structure for tracking hotkey statistics by given metrics. */
struct hotkeyStats {
    struct chkTopK *cpu;
    struct chkTopK *net;
    mstime_t start; /* Initial time point for wall time tracking */

    /* Only keys from selected slots will be tracked. If slots is NULL,
     * all keys are tracked. Stored as a sorted slotRangeArray. */
    struct slotRangeArray *slots;

    /* Statistics counters. */
    uint64_t time_sampled_commands_selected_slots;  /* microseconds */
    uint64_t time_all_commands_selected_slots;       /* microseconds */
    uint64_t time_all_commands_all_slots;            /* microseconds */
    uint64_t net_bytes_sampled_commands_selected_slots;
    uint64_t net_bytes_all_commands_selected_slots;
    uint64_t net_bytes_all_commands_all_slots;

    /* rusage stats for CPU time tracking */
    struct timeval ru_utime;
    struct timeval ru_stime;

    int tracking_count; /* Count of top hotkeys we want to track */
    int sample_ratio; /* Track a key with probability 1 / sample_ratio */
    int active; /* True if tracking is currently active */
    mstime_t duration; /* Tracking duration */
    uint64_t tracked_metrics;  /* Bit flags: HOTKEYS_TRACK_CPU, HOTKEYS_TRACK_NET, etc. */
    mstime_t cpu_time;  /* Total CPU time spent updating the topk struct in milliseconds */

    /* Current command related fields */
    getKeysResult keys_result; /* Key results for current command */
    client *current_client;
    int is_sampled; /* Indicates whether or not keys from cmd are sampled via sample_ratio */
    int is_in_selected_slots; /* Indicates whether or not keys from cmd are in selected_slots */
};

typedef struct hotkeyMetrics {
    uint64_t cpu_time_usec;
    uint64_t net_bytes;
} hotkeyMetrics;

/* pendingCommand flags */
enum {
    PENDING_CMD_FLAG_INCOMPLETE = 1 << 0,     /* Command parsing is incomplete, still waiting for more data */
    PENDING_CMD_FLAG_PREPROCESSED = 1 << 1,   /* This command has passed pre-processing */
    PENDING_CMD_KEYS_RESULT_VALID = 1 << 2,   /* Command's keys_result is valid and cached */
    PENDING_CMD_KEYS_RESULT_ALLOCATED = 1 << 3, /* keys_result owns a heap array that must be released */
    /* tomokv-phase-trace owns bits 4..11 while a sampled pending command is
     * carried IO -> fake -> EX -> IO. State 0 begins at recv completion. */
    PENDING_CMD_PHASE_TRACE = 1 << 4,
    PENDING_CMD_PHASE_STATE_SHIFT = 5,
    PENDING_CMD_PHASE_STATE_MASK = 7 << PENDING_CMD_PHASE_STATE_SHIFT,
    PENDING_CMD_PHASE_NODE_SHIFT = 8,
    PENDING_CMD_PHASE_NODE_MASK = 15 << PENDING_CMD_PHASE_NODE_SHIFT,
#ifdef DEBUG_ASSERTIONS
    PENDING_CMD_DEBUG_INPUT_INITIALIZED = 1 << 27,
    PENDING_CMD_DEBUG_CMD_INITIALIZED = 1 << 28,
    PENDING_CMD_DEBUG_REPLOFF_INITIALIZED = 1 << 29,
    PENDING_CMD_DEBUG_SLOT_INITIALIZED = 1 << 30,
#endif
};

/* Parser state and parse result of a command from a client's input buffer. */
struct pendingCommand {
    int argc;                 /* Num of arguments of current command. */
    int argv_len;             /* Size of argv array (may be more than argc) */
    robj **argv;              /* Arguments of current command. */
    size_t argv_len_sum;      /* Sum of lengths of objects in argv list. */
    unsigned long long input_bytes;
    struct redisCommand *cmd;
    getKeysResult keys_result;
    union {
        long long reploff;    /* replication clients only; set before command activation */
        uint64_t phase_us;    /* debug phase timestamp for sampled non-replication requests */
    };
    int flags;
    int slot;         /* The slot the command is executing against. Set to INVALID_CLUSTER_SLOT
                       * if no slot is being used or if the command has a cross slot error */
    uint8_t read_error;
    uint64_t argv_released_mask; /* ee451 (v14 deepint): bit j set = worker released argv[j] (DB-aliased
                                  * ref); freePendingCommand skips it. Lets the worker signal releases
                                  * WITHOUT writing the io-owned argv[] array (the decref bounce). */

    struct pendingCommand *next;
    struct pendingCommand *prev;
};

#ifdef DEBUG_ASSERTIONS
#define pendingCommandDebugMark(_pcmd, _bits) ((_pcmd)->flags |= (_bits))

static inline void debugAssertPendingCommandMetadata(const pendingCommand *pcmd, int reploff_is_read) {
    debugServerAssert(pcmd->flags & PENDING_CMD_DEBUG_INPUT_INITIALIZED);
    debugServerAssert(pcmd->flags & PENDING_CMD_DEBUG_CMD_INITIALIZED);
    debugServerAssert(pcmd->flags & PENDING_CMD_DEBUG_SLOT_INITIALIZED);
    if (reploff_is_read)
        debugServerAssert(pcmd->flags & PENDING_CMD_DEBUG_REPLOFF_INITIALIZED);
}

static inline void debugAssertPendingCommandKeysResult(const pendingCommand *pcmd) {
    debugServerAssert(pcmd->flags & PENDING_CMD_KEYS_RESULT_VALID);
    debugServerAssert(pcmd->keys_result.numkeys >= 0);
    debugServerAssert(pcmd->keys_result.numkeys <= pcmd->keys_result.size);
    debugServerAssert(pcmd->keys_result.numkeys == 0 || pcmd->keys_result.keys != NULL);
    for (int i = 0; i < pcmd->keys_result.numkeys; i++)
        debugServerAssert(pcmd->keys_result.keys[i].pos >= 0 &&
                          pcmd->keys_result.keys[i].pos < pcmd->argc);
}
#else
#define pendingCommandDebugMark(_pcmd, _bits) ((void)0)
#define debugAssertPendingCommandMetadata(_pcmd, _reploff_is_read) ((void)0)
#define debugAssertPendingCommandKeysResult(_pcmd) ((void)0)
#endif

/* Key specs definitions.
 *
 * Brief: This is a scheme that tries to describe the location
 * of key arguments better than the old [first,last,step] scheme
 * which is limited and doesn't fit many commands.
 *
 * There are two steps:
 * 1. begin_search (BS): in which index should we start searching for keys?
 * 2. find_keys (FK): relative to the output of BS, how can we will which args are keys?
 *
 * There are two types of BS:
 * 1. index: key args start at a constant index
 * 2. keyword: key args start just after a specific keyword
 *
 * There are two kinds of FK:
 * 1. range: keys end at a specific index (or relative to the last argument)
 * 2. keynum: there's an arg that contains the number of key args somewhere before the keys themselves
 */

/* WARNING! Must be synced with generate-command-code.py and RedisModuleKeySpecBeginSearchType */
typedef enum {
    KSPEC_BS_INVALID = 0, /* Must be 0 */
    KSPEC_BS_UNKNOWN,
    KSPEC_BS_INDEX,
    KSPEC_BS_KEYWORD
} kspec_bs_type;

/* WARNING! Must be synced with generate-command-code.py and RedisModuleKeySpecFindKeysType */
typedef enum {
    KSPEC_FK_INVALID = 0, /* Must be 0 */
    KSPEC_FK_UNKNOWN,
    KSPEC_FK_RANGE,
    KSPEC_FK_KEYNUM
} kspec_fk_type;

/* WARNING! This struct must match RedisModuleCommandKeySpec */
typedef struct {
    /* Declarative data */
    const char *notes;
    uint64_t flags;
    kspec_bs_type begin_search_type;
    union {
        struct {
            /* The index from which we start the search for keys */
            int pos;
        } index;
        struct {
            /* The keyword that indicates the beginning of key args */
            const char *keyword;
            /* An index in argv from which to start searching.
             * Can be negative, which means start search from the end, in reverse
             * (Example: -2 means to start in reverse from the penultimate arg) */
            int startfrom;
        } keyword;
    } bs;
    kspec_fk_type find_keys_type;
    union {
        /* NOTE: Indices in this struct are relative to the result of the begin_search step!
         * These are: range.lastkey, keynum.keynumidx, keynum.firstkey */
        struct {
            /* Index of the last key.
             * Can be negative, in which case it's not relative. -1 indicating till the last argument,
             * -2 one before the last and so on. */
            int lastkey;
            /* How many args should we skip after finding a key, in order to find the next one. */
            int keystep;
            /* If lastkey is -1, we use limit to stop the search by a factor. 0 and 1 mean no limit.
             * 2 means 1/2 of the remaining args, 3 means 1/3, and so on. */
            int limit;
        } range;
        struct {
            /* Index of the argument containing the number of keys to come */
            int keynumidx;
            /* Index of the fist key (Usually it's just after keynumidx, in
             * which case it should be set to keynumidx+1). */
            int firstkey;
            /* How many args should we skip after finding a key, in order to find the next one. */
            int keystep;
        } keynum;
    } fk;
} keySpec;

#ifdef LOG_REQ_RES

/* Must be synced with generate-command-code.py */
typedef enum {
    JSON_TYPE_STRING,
    JSON_TYPE_INTEGER,
    JSON_TYPE_BOOLEAN,
    JSON_TYPE_OBJECT,
    JSON_TYPE_ARRAY,
} jsonType;

typedef struct jsonObjectElement {
    jsonType type;
    const char *key;
    union {
        const char *string;
        long long integer;
        int boolean;
        struct jsonObject *object;
        struct {
            struct jsonObject **objects;
            int length;
        } array;
    } value;
} jsonObjectElement;

typedef struct jsonObject {
    struct jsonObjectElement *elements;
    int length;
} jsonObject;

#endif

/* WARNING! This struct must match RedisModuleCommandHistoryEntry */
typedef struct {
    const char *since;
    const char *changes;
} commandHistory;

/* Must be synced with COMMAND_GROUP_STR and generate-command-code.py */
typedef enum {
    COMMAND_GROUP_GENERIC,
    COMMAND_GROUP_STRING,
    COMMAND_GROUP_LIST,
    COMMAND_GROUP_SET,
    COMMAND_GROUP_SORTED_SET,
    COMMAND_GROUP_HASH,
    COMMAND_GROUP_PUBSUB,
    COMMAND_GROUP_TRANSACTIONS,
    COMMAND_GROUP_CONNECTION,
    COMMAND_GROUP_SERVER,
    COMMAND_GROUP_SCRIPTING,
    COMMAND_GROUP_HYPERLOGLOG,
    COMMAND_GROUP_CLUSTER,
    COMMAND_GROUP_SENTINEL,
    COMMAND_GROUP_GEO,
    COMMAND_GROUP_STREAM,
    COMMAND_GROUP_BITMAP,
    COMMAND_GROUP_MODULE,
} redisCommandGroup;

typedef void redisCommandProc(client *c);
typedef int redisGetKeysProc(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);

/* ee451 (xshard registry): one row per cross-shard-RELEVANT command proc. PORTED rows drive
 * classification and dispatch entirely from data; UNPORTED rows exist so the inverted SAFE-GATE
 * can express argc-dependent safety and stay greppable. Matched to redisCommand by PROC POINTER
 * once at populateCommandTable (cmd->cs_spec) — rename-command-proof, never scanned at runtime. */
typedef struct csCmdSpec {
    redisCommandProc *proc;   /* match key (populate-time only) */
    const char *name;         /* boot-audit logging only; matching is by proc */
    uint8_t ported;           /* CS_PORT_* */
    int8_t  ctype;            /* csCmdType for csSubExec/csReassemble; -1 on UNPORTED rows */
    uint8_t route;            /* CS_RT_* */
    int8_t  setop;            /* CS_SETOP_* when ctype==CS_SETOP */
    /* -- classification gates (fail => NOT cross-shard => whitelist/inline, as today) -- */
    int16_t min_argc;         /* argc <  min_argc => fall through (DEL: 3 keeps argc==2
                               * on the worker whitelist) */
    int16_t max_argc;         /* 0 = unlimited (KEYS: 2) */
    uint8_t argc_odd;         /* 1 => argc must be odd (MSET/MSETNX) */
    int  (*shape_ok)(client *c); /* optional; 0 => fall through INLINE so the STOCK proc
                               * emits its own parse error before any key access (BITOP
                               * NOT n>1, bad LIMIT). NO ported Step-R row sets this. */
    /* -- gather geometry (CS_RT_GATHER) -- */
    int8_t  firstkey_argi;    /* 0 => 1. (S*STORE:2, ZUNIONSTORE:3, BITOP:3 ...) */
    int8_t  numkeys_argi;     /* 0 => keys run to argc; else argv index of numkeys */
    int8_t  nkeys_fixed;      /* 0 => derive as above; LCS has exactly 2 keys before options */
    int8_t  key_stride;       /* 1, or 2 for MSET/MSETNX (k v pairs) */
    int8_t  per_key_extra;    /* extra argv slots appended per key (MSET value = 1) */
    int  (*gather_geom)(client *c, int *first, int *nkeys); /* optional dynamic key span;
                               * XREAD finds the STREAMS split at runtime */
    uint8_t cs_write;         /* run migHoldKeyIfDraining per key (writes only) */
    uint8_t notouch;          /* per-key sub lookups pass LOOKUP_NOTOUCH (no LRU/LFU bump).
                               * EXISTS and TOUCH share ctype=CS_EXISTS but differ HERE: stock
                               * existsCommand looks up with LOOKUP_NOTOUCH, stock touchCommand
                               * deliberately touches. The flag lives on the ROW, not the ctype,
                               * because that is exactly where the two commands diverge. */
    uint8_t res_kind;         /* CS_RES_* result slots to allocate */
    uint8_t pos_kind;         /* CS_POS_* posmap for csBuildCoalescedSubs */
    uint8_t co_gate;          /* CS_CO_* */
    /* -- HOP2 geometry (CS_RT_TWOHOP, or CS_RT_GATHER with has_hop2) -- */
    uint8_t has_hop2;         /* GATHER route: dest write follows the gather barrier */
    int8_t  src_argi;         /* TWOHOP: argv index of the single gather/src key */
    int8_t  dst_argi;         /* argv index of the dest key; 0 = none/dynamic */
    int  (*dynamic_dst_argi)(client *c); /* TWOHOP dynamic destination resolver (SORT STORE,
                               * GEORADIUS STORE/STOREDIST); NULL for static/MPOP-plan rows */
    uint8_t h1_probe_dst;     /* TWOHOP: add a HOP1 probe sub on the dst shard (step 4+) */
    int8_t  h1_extra_argi;    /* TWOHOP: head->argv index appended to HOP1 sub 0's argv
                               * (SMOVE member — sub owns its own copy; 0 = none) */
    uint8_t h2_del_src;       /* HOP2 plan also gets a CS_H2A_SRCOP sub on src */
    uint8_t h2_op;            /* CS_H2_* launcher shape */
    uint8_t cs2_kind;         /* CS2_* final reply shape tag */
    uint8_t block_reject;     /* blocking variant: never run a parking proc on a worker fake;
                               * the ctype decides whether would-block is nil or a safe error */
    /* -- callbacks (the ONLY code-bearing fields) -- */
    void (*append_extra)(client *head, client *sub, int origpos); /* MSET value append */
    int  (*unsafe_check)(client *c);  /* UNPORTED or hybrid PORTED rows: nonzero => reject form */
    int16_t safe_max_argc;    /* UNPORTED rows without a hook: argc <= this falls through
                               * (PFCOUNT: 2); 0 = always reject */
} csCmdSpec;

/* Redis command structure.
 *
 * Note that the command table is in commands.c and it is auto-generated.
 *
 * This is the meaning of the flags:
 *
 * CMD_WRITE:       Write command (may modify the key space).
 *
 * CMD_READONLY:    Commands just reading from keys without changing the content.
 *                  Note that commands that don't read from the keyspace such as
 *                  TIME, SELECT, INFO, administrative commands, and connection
 *                  or transaction related commands (multi, exec, discard, ...)
 *                  are not flagged as read-only commands, since they affect the
 *                  server or the connection in other ways.
 *
 * CMD_DENYOOM:     May increase memory usage once called. Don't allow if out
 *                  of memory.
 *
 * CMD_ADMIN:       Administrative command, like SAVE or SHUTDOWN.
 *
 * CMD_PUBSUB:      Pub/Sub related command.
 *
 * CMD_NOSCRIPT:    Command not allowed in scripts.
 *
 * CMD_BLOCKING:    The command has the potential to block the client.
 *
 * CMD_LOADING:     Allow the command while loading the database.
 *
 * CMD_NO_ASYNC_LOADING: Deny during async loading (when a replica uses diskless
 *                       sync swapdb, and allows access to the old dataset)
 *
 * CMD_STALE:       Allow the command while a slave has stale data but is not
 *                  allowed to serve this data. Normally no command is accepted
 *                  in this condition but just a few.
 *
 * CMD_SKIP_MONITOR:  Do not automatically propagate the command on MONITOR.
 *
 * CMD_SKIP_SLOWLOG:  Do not automatically propagate the command to the slowlog.
 *
 * CMD_ASKING:      Perform an implicit ASKING for this command, so the
 *                  command will be accepted in cluster mode if the slot is marked
 *                  as 'importing'.
 *
 * CMD_FAST:        Fast command: O(1) or O(log(N)) command that should never
 *                  delay its execution as long as the kernel scheduler is giving
 *                  us time. Note that commands that may trigger a DEL as a side
 *                  effect (like SET) are not fast commands.
 *
 * CMD_NO_AUTH:     Command doesn't require authentication
 *
 * CMD_MAY_REPLICATE:   Command may produce replication traffic, but should be
 *                      allowed under circumstances where write commands are disallowed.
 *                      Examples include PUBLISH, which replicates pubsub messages,and
 *                      EVAL, which may execute write commands, which are replicated,
 *                      or may just execute read commands. A command can not be marked
 *                      both CMD_WRITE and CMD_MAY_REPLICATE
 *
 * CMD_SENTINEL:    This command is present in sentinel mode.
 *
 * CMD_ONLY_SENTINEL: This command is present only when in sentinel mode.
 *                    And should be removed from redis.
 *
 * CMD_NO_MANDATORY_KEYS: This key arguments for this command are optional.
 *
 * CMD_NO_MULTI: The command is not allowed inside a transaction
 *
 * CMD_ALLOW_BUSY: The command can run while another command is running for
 *                 a long time (timedout script, module command that yields)
 *
 * CMD_TOUCHES_ARBITRARY_KEYS: The command may touch (and cause lazy-expire)
 *                             arbitrary key (i.e not provided in argv)
 *
 * CMD_INTERNAL: The command may perform operations without performing
 *               validations such as ACL.
 *
 * The following additional flags are only used in order to put commands
 * in a specific ACL category. Commands can have multiple ACL categories.
 * See redis.conf for the exact meaning of each.
 *
 * @keyspace, @read, @write, @set, @sortedset, @list, @hash, @string, @bitmap,
 * @hyperloglog, @stream, @admin, @fast, @slow, @pubsub, @blocking, @dangerous,
 * @connection, @transaction, @scripting, @geo.
 *
 * Note that:
 *
 * 1) The read-only flag implies the @read ACL category.
 * 2) The write flag implies the @write ACL category.
 * 3) The fast flag implies the @fast ACL category.
 * 4) The admin flag implies the @admin and @dangerous ACL category.
 * 5) The pub-sub flag implies the @pubsub ACL category.
 * 6) The lack of fast flag implies the @slow ACL category.
 * 7) The non obvious "keyspace" category includes the commands
 *    that interact with keys without having anything to do with
 *    specific data structures, such as: DEL, RENAME, MOVE, SELECT,
 *    TYPE, EXPIRE*, PEXPIRE*, TTL, PTTL, ...
 */
/* ee451 (v14) routing byte bits (redisCommand.tomo_route), stamped at populate time. */
#define TOMO_R_STATEFUL 1u   /* multi/exec/subscribe/auth/... — run on real client, ring-drained */
#define TOMO_R_EXPRESS  2u   /* getCommand/setCommand — the express dispatch lane */
#define TOMO_R_CROSS    4u   /* proc CAN be cross-shard (derived: registry row with ported==CS_PORT_OK) */
#define TOMO_R_XGUARD   8u   /* multi-key-capable AND not table-PORTED => SAFE-GATE checks it */
#define TOMO_R_SCRIPTFAM 16u /* eval/fcall/script/function-subcommand — serializes on the script fence */
#define TOMO_R_ATOMIC_READ 32u /* atomic mode: command needs a pinned version-bag snapshot */
struct redisCommand {
    /* Declarative data */
    const char *declared_name; /* A string representing the command declared_name.
                                * It is a const char * for native commands and SDS for module commands. */
    const char *summary; /* Summary of the command (optional). */
    const char *complexity; /* Complexity description (optional). */
    const char *since; /* Debut version of the command (optional). */
    int doc_flags; /* Flags for documentation (see CMD_DOC_*). */
    const char *replaced_by; /* In case the command is deprecated, this is the successor command. */
    const char *deprecated_since; /* In case the command is deprecated, when did it happen? */
    redisCommandGroup group; /* Command group */
    commandHistory *history; /* History of the command */
    int num_history;
    const char **tips; /* An array of strings that are meant to be tips for clients/proxies regarding this command */
    int num_tips;
    redisCommandProc *proc; /* Command implementation */
    int arity; /* Number of arguments, it is possible to use -N to say >= N */
    uint64_t flags; /* Command flags, see CMD_*. */
    uint64_t acl_categories; /* ACl categories, see ACL_CATEGORY_*. */
    keySpec *key_specs;
    int key_specs_num;
    /* Use a function to determine keys arguments in a command line.
     * Used for Redis Cluster redirect (may be NULL) */
    redisGetKeysProc *getkeys_proc;
    int num_args; /* Length of args array. */
    /* Array of subcommands (may be NULL) */
    struct redisCommand *subcommands;
    /* Array of arguments (may be NULL) */
    struct redisCommandArg *args;
#ifdef LOG_REQ_RES
    /* Reply schema */
    struct jsonObject *reply_schema;
#endif

    /* Runtime populated data */
    long long microseconds, calls, rejected_calls, failed_calls;
    int id;     /* Command ID. This is a progressive ID starting from 0 that
                   is assigned at runtime, and is used in order to check
                   ACLs. A connection is able to execute a given command if
                   the user associated to the connection has this command
                   bit set in the bitmap of allowed commands. */
    sds fullname; /* A SDS string representing the command fullname. */
    struct hdr_histogram* latency_histogram; /*points to the command latency command histogram (unit of time nanosecond) */
    keySpec legacy_range_key_spec; /* The legacy (first,last,step) key spec is
                                     * still maintained (if applicable) so that
                                     * we can still support the reply format of
                                     * COMMAND INFO and COMMAND GETKEYS */
    dict *subcommands_dict; /* A dictionary that holds the subcommands, the key is the subcommand sds name
                             * (not the fullname), and the value is the redisCommand structure pointer. */
    struct redisCommand *parent;
    struct RedisModuleCommand *module_cmd; /* A pointer to the module command data (NULL if native command) */
    unsigned char tomo_route; /* ee451 (v14): routing byte, stamped once at populateCommandTable
                               * (struct END so commands.def positional init is unaffected);
                               * replaces per-op proc-pointer compare chains on dispatch. TOMO_R_* */
    const struct csCmdSpec *cs_spec; /* ee451 (xshard registry): row or NULL, stamped at populate
                               * (struct END for the same positional-init reason as tomo_route) */
    /* ee451 D: TOMO_CLS_* cost class (stamped at table init). TAIL member on purpose —
     * commands.def initializes this struct POSITIONALLY, so new fields must trail. */
    uint8_t tomo_cls;
};

struct redisError {
    _Atomic long long count;       /* one shard owner writes; INFO snapshot readers load */
    uint64_t generation;
    size_t name_len;
    struct redisError *next;       /* immutable after this entry is release-published */
    unsigned char name[];          /* arbitrary error name, also used as the owner-rax key */
};

struct redisFunctionSym {
    char *name;
    unsigned long pointer;
};

typedef struct _redisSortObject {
    robj *obj;
    union {
        double score;
        robj *cmpobj;
    } u;
} redisSortObject;

typedef struct _redisSortOperation {
    int type;
    robj *pattern;
} redisSortOperation;

/* Structure to hold list iteration abstraction. */
typedef struct {
    robj *subject;
    unsigned char encoding;
    unsigned char direction; /* Iteration direction */

    unsigned char *lpi; /* listpack iterator */
    quicklistIter iter; /* quicklist iterator */
} listTypeIterator;

/* Structure for an entry while iterating over a list. */
typedef struct {
    listTypeIterator *li;
    unsigned char *lpe; /* Entry in listpack */
    quicklistEntry entry; /* Entry in quicklist */
} listTypeEntry;

/* Structure to hold set iteration abstraction. */
typedef struct {
    robj *subject;
    int encoding;
    int ii; /* intset iterator */
    dictIterator di;
    unsigned char *lpi; /* listpack iterator */
} setTypeIterator;

/* Structure to hold hash iteration abstraction. Note that iteration over
 * hashes involves both fields and values. Because it is possible that
 * not both are required, store pointers in the iterator to avoid
 * unnecessary memory allocation for fields/values. */
typedef struct {
    robj *subject;
    int encoding;

    unsigned char *fptr, *vptr, *tptr;
    uint64_t expire_time; /* Only used with OBJ_ENCODING_LISTPACK_EX */

    dictIterator di;
    dictEntry *de;
} hashTypeIterator;

#include "stream.h"  /* Stream data type header file. */

#define OBJ_HASH_KEY 1
#define OBJ_HASH_VALUE 2

/* Hash-field data type (of t_hash.c) - now using entry directly
 * Note: entry* is used directly instead of a typedef for clarity */

/*-----------------------------------------------------------------------------
 * Extern declarations
 *----------------------------------------------------------------------------*/

extern struct redisServer server;
extern struct sharedObjectsStruct shared;
extern dictType objectKeyPointerValueDictType;

/* ee451 (#4): dirty-counter accessors. iotid is the current thread's index (ae.h). When
 * opt_perthread_dirty is OFF these are byte-identical to the legacy server.dirty arithmetic.
 *   markDirty(n)  - a write made n changes: accumulate into THIS thread's shard.
 *   DIRTY_LOCAL   - this thread's running count, for the call() before/after delta and any
 *                   in-command local delta (captures only the command's own changes).
 *   getDirty()    - global fold (baseline + all shards): save-point trigger, INFO, bgsave snapshot.
 *   resetDirtyCounter() - zero the effective total without a shard-zeroing race: re-baseline so
 *                   getDirty()==0 while in-flight increments stay counted. */
#define DIRTY_NSHARD (TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX)
#define markDirty(n) do { server.dirty_shard[iotid].v += (n); } while (0)   /* ee451 (v13): #4 hardwired */
#define DIRTY_LOCAL (server.dirty_shard[iotid].v)
/* ee451 (#A2): folded per-thread network byte counters (defined in server.c) */
long long getNetInputBytes(void);
long long getNetOutputBytes(void);
/* ee451 (#B1): folded per-thread executed-command counter (defined in server.c). COLD path only —
 * it walks every slot's cache line, so never call it per command or per event-loop iteration. */
long long getNumCommands(void);
/* ee451 (#B1): count one client-visible command against THIS thread's slot. Valid on every thread
 * that can execute a command (main, io, worker) — iotid indexes the same 0..96 slot space as
 * current_client[]/kstat[]/dirty_shard[]. */
#define numCommandsBump() tomoRelaxedBump(server.cmdstat[iotid].n, 1)

/* ---- ee451 (#B2): per-thread per-command stats (INFO commandstats / latencystats) ------------
 *
 * Hot-path cost of the whole apparatus, per ordinary direct worker command: ONE raw exit-counter
 * read plus one delta conversion; the enter boundary is amortized across the pop batch by reusing
 * the preceding command's exit. Then two relaxed loads of this
 * thread's own errstat line, one acquire load of a read-only pointer, one bounds compare, and
 * 2-3 relaxed stores into a cache line no other thread touches. No atomic RMW, no shared line,
 * no allocation after the first command a thread runs. Batch reuse makes the timing side cheaper
 * than the pair of clock reads stock Redis pays inside call() for every command. */

/* Declared early (its stock prototype is much further down) — tomoCmdLatRecord needs it here. */
void updateCommandLatencyHistogram(struct hdr_histogram** latency_histogram, int64_t duration_hist);

/* Lazily allocate + publish THIS thread's blocks. Cold: taken once per thread. */
tomoCmdStat *tomoCmdStatBlockAlloc(void);
struct hdr_histogram **tomoCmdLatBlockAlloc(void);

/* Fold legacy scalars + every thread slot for one command. COLD read path only. */
void getCommandStats(struct redisCommand *cmd, long long *calls, long long *usec,
                     long long *rejected, long long *failed);
/* Merge every per-thread histogram (plus the legacy one) for a command into a NEW histogram.
 * Returns NULL when the command has no samples at all; otherwise the caller owns the result and
 * must hdr_close() it. COLD read path only (INFO latencystats / LATENCY HISTOGRAM). */
struct hdr_histogram *tomoCmdLatMerge(struct redisCommand *cmd);
/* Zero one command's shards (CONFIG RESETSTAT, module command unregister). */
void tomoCmdStatResetOne(struct redisCommand *cmd);
/* ee451 (#B2): folded per-thread error-reply counter (INFO total_error_replies). COLD path. */
long long getTotalErrorReplies(void);
/* THIS thread's error-reply count. Single-writer, so a delta across a proc is exact. HOT-safe. */
#define tomoErrRepliesLocal() tomoRelaxedRead(server.errstat[iotid].n)
#define tomoErrRepliesBump()  tomoRelaxedBump(server.errstat[iotid].n, 1)

/* Record one completed execution of `cmd` against this thread's shard.
 * usec = the proc's own duration, matching call()'s c->duration accounting. */
static inline void tomoCmdStatAddCall(struct redisCommand *cmd, long long usec, int failed) {
    unsigned int id = (unsigned int)cmd->id;
    if (__builtin_expect(id >= TOMO_CMDSTAT_IDS, 0)) return;   /* un-ACL-able id; see TOMO_CMDSTAT_IDS */
    tomoCmdStat *blk = atomic_load_explicit(&server.cmdstat_percmd[iotid], memory_order_acquire);
    if (__builtin_expect(blk == NULL, 0) && (blk = tomoCmdStatBlockAlloc()) == NULL) return;
    tomoRelaxedBump(blk[id].calls, 1);
    tomoRelaxedBump(blk[id].microseconds, usec);
    if (__builtin_expect(failed != 0, 0)) tomoRelaxedBump(blk[id].failed_calls, 1);
}

/* rejected_calls / failed_calls without a call (the incrCommandStatsOnError shapes). */
static inline void tomoCmdStatAddErr(struct redisCommand *cmd, int rejected, int failed) {
    unsigned int id = (unsigned int)cmd->id;
    if (__builtin_expect(id >= TOMO_CMDSTAT_IDS, 0)) return;
    tomoCmdStat *blk = atomic_load_explicit(&server.cmdstat_percmd[iotid], memory_order_acquire);
    if (__builtin_expect(blk == NULL, 0) && (blk = tomoCmdStatBlockAlloc()) == NULL) return;
    if (rejected) tomoRelaxedBump(blk[id].rejected_calls, 1);
    if (failed)   tomoRelaxedBump(blk[id].failed_calls, 1);
}

/* Add usec to a command without counting a call (module background-duration accounting). */
static inline void tomoCmdStatAddUsec(struct redisCommand *cmd, long long usec) {
    unsigned int id = (unsigned int)cmd->id;
    if (__builtin_expect(id >= TOMO_CMDSTAT_IDS, 0)) return;
    tomoCmdStat *blk = atomic_load_explicit(&server.cmdstat_percmd[iotid], memory_order_acquire);
    if (__builtin_expect(blk == NULL, 0) && (blk = tomoCmdStatBlockAlloc()) == NULL) return;
    tomoRelaxedBump(blk[id].microseconds, usec);
}

/* Record one latency sample (microseconds) into THIS thread's histogram for `cmd`. The histogram
 * is created on first use by its one and only writer; the pointer is published with release so
 * the cold merge path can acquire-load it. */
static inline void tomoCmdLatRecord(struct redisCommand *cmd, long long usec) {
    unsigned int id = (unsigned int)cmd->id;
    if (__builtin_expect(id >= TOMO_CMDSTAT_IDS, 0)) return;
    struct hdr_histogram **blk =
        atomic_load_explicit(&server.cmdlat_percmd[iotid], memory_order_acquire);
    if (__builtin_expect(blk == NULL, 0) && (blk = tomoCmdLatBlockAlloc()) == NULL) return;
    struct hdr_histogram *h = blk[id];
    updateCommandLatencyHistogram(&h, usec * 1000);
    if (__builtin_expect(h != blk[id], 0))
        atomic_store_explicit((_Atomic(struct hdr_histogram *) *)&blk[id], h, memory_order_release);
}
static inline long long getDirty(void) {
    long long s = server.dirty;                 /* baseline carries bgsave subtracts + resets */
    for (int i = 0; i < DIRTY_NSHARD; i++) s += server.dirty_shard[i].v;
    return s;
}
static inline void resetDirtyCounter(void) {
    long long s = 0;
    for (int i = 0; i < DIRTY_NSHARD; i++) s += server.dirty_shard[i].v;
    server.dirty = -s;                           /* baseline cancels current shards -> getDirty()==0 */
}
extern dictType objectKeyHeapPointerValueDictType;
extern dictType setDictType;
extern dictType BenchmarkDictType;
extern dictType zsetDictType;
extern dictType dbDictType;
extern double R_Zero, R_PosInf, R_NegInf, R_Nan;
extern dictType hashDictType;
extern dictType entryHashDictType;
extern dictType entryHashDictTypeWithHFE;
extern dictType stringSetDictType;
extern dictType externalStringType;
extern dictType sdsHashDictType;
extern dictType clientDictType;
extern dictType objToDictDictType;
extern dictType dbExpiresDictType;
extern dictType modulesDictType;
extern dictType sdsReplyDictType;
extern dictType keylistDictType;
extern kvstoreType kvstoreBaseType;
extern kvstoreType kvstoreExType;
extern dict *modules;

extern EbucketsType subexpiresBucketsType;  /* global expires */
extern EbucketsType hashFieldExpireBucketsType; /* local per hash */

//extern __thread int iotid;

/*-----------------------------------------------------------------------------
 * Functions prototypes
 *----------------------------------------------------------------------------*/

/* Command metadata */
void populateCommandLegacyRangeSpec(struct redisCommand *c);

/* Modules */
void moduleInitModulesSystem(void);
void moduleInitModulesSystemLast(void);
void modulesCron(void);
int moduleOnLoad(int (*onload)(void *, void **, int), const char *path, void *handle, void **module_argv, int module_argc, int is_loadex);
int moduleLoad(const char *path, void **argv, int argc, int is_loadex);
int moduleUnload(sds name, const char **errmsg, int forced_unload);
void moduleLoadInternalModules(void);
void moduleLoadFromQueue(void);
int moduleGetCommandKeysViaAPI(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);
int moduleGetCommandChannelsViaAPI(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);
moduleType *moduleTypeLookupModuleByID(uint64_t id);
moduleType *moduleTypeLookupModuleByName(const char *name);
moduleType *moduleTypeLookupModuleByNameIgnoreCase(const char *name);
void moduleTypeNameByID(char *name, uint64_t moduleid);
const char *moduleTypeModuleName(moduleType *mt);
const char *moduleNameFromCommand(struct redisCommand *cmd);
void moduleFreeContext(struct RedisModuleCtx *ctx);
void moduleCallCommandUnblockedHandler(client *c);
int isModuleClientUnblocked(client *c);
void unblockClientFromModule(client *c);
void moduleHandleBlockedClients(void);
void moduleBlockedClientTimedOut(client *c);
void modulePipeReadable(aeEventLoop *el, int fd, void *privdata, int mask);
size_t moduleCount(void);
/* ee451 (O/perf): see the comment at moduleAcquireGIL. main skips the per-iteration GIL round trip
 * until some other thread has actually asked for the lock. */
int moduleGILNeedsHandoff(void);
void moduleAcquireGILForMainLoop(void);
void moduleAcquireGIL(void);
int moduleTryAcquireGIL(void);
void moduleReleaseGIL(void);
void moduleNotifyKeyspaceEvent(int type, const char *event, robj *key, int dbid);
void firePostExecutionUnitJobs(void);
void moduleCallCommandFilters(client *c);
void modulePostExecutionUnitOperations(void);
void ModuleForkDoneHandler(int exitcode, int bysignal);
int TerminateModuleForkChild(int child_pid, int wait);
ssize_t rdbSaveModulesAux(rio *rdb, int when);
int moduleAllDatatypesHandleErrors(void);
int moduleAllModulesHandleReplAsyncLoad(void);
sds modulesCollectInfo(sds info, dict *sections_dict, int for_crash_report, int sections);
void moduleFireServerEvent(uint64_t eid, int subid, void *data);
void processModuleLoadingProgressEvent(int is_aof);
int moduleTryServeClientBlockedOnKey(client *c, robj *key);
void moduleUnblockClient(client *c);
int moduleBlockedClientMayTimeout(client *c);
int moduleClientIsBlockedOnKeys(client *c);
void moduleNotifyUserChanged(client *c);
void moduleNotifyKeyUnlink(robj *key, kvobj *kv, int dbid, int flags);
size_t moduleGetFreeEffort(robj *key, robj *val, int dbid);
size_t moduleGetMemUsage(robj *key, robj *val, size_t sample_size, int dbid);
robj *moduleTypeDupOrReply(client *c, robj *fromkey, robj *tokey, int todb, robj *value);
int moduleDefragValue(robj *key, robj *obj, int dbid);
int moduleLateDefrag(robj *key, robj *value, unsigned long *cursor, monotime endtime, int dbid);
void moduleDefragStart(void);
void moduleDefragEnd(void);
void *moduleGetHandleByName(char *modulename);
int moduleIsModuleCommand(void *module_handle, struct redisCommand *cmd);
int moduleHasSubscribersForKeyspaceEvent(int type);
int moduleHasKeyspaceChangeCallbacks(int type);

/* pcmd */
void initPendingCommand(pendingCommand *pcmd);
void freePendingCommand(client *c, pendingCommand *pcmd);
void pendingCommandReturnBatchBegin(void);
void pendingCommandReturnBatchEnd(void);
void addPendingCommand(pendingCommandList *queue, pendingCommand *cmd);
pendingCommand *popPendingCommandFromHead(pendingCommandList *queue);
pendingCommand *popPendingCommandFromTail(pendingCommandList *queue);
void shrinkPendingCommandPool(void);

/* ee451 (F-clock family, 2026-07-28): "I am inside a module unlink / keyspace-notification
 * callback" is per-EXECUTION-CONTEXT state, not server state. It used to live in the plain ints
 * server.allow_access_expired / .allow_access_trimmed, which moduleNotifyKeyUnlink() bumps and
 * restores around EVERY key overwrite and EVERY delete (db.c setKey / dbGenericDelete) — i.e. on
 * the hot path of every worker thread. N workers doing non-atomic ++/-- on one shared int lose
 * updates, so the counter random-walks off zero and STAYS there, and every reader of
 * keyIsExpired() then answers "not expired" for the rest of the process's life: lazy expiry dies
 * server-wide under load. Measured on the unfixed build: 4 workers, 8 loader connections, the
 * counter reached +7227 in ~4s and a `SET k v PX 60` key was still readable 25s later.
 * Thread-local is both race-free and semantically exact — the guard only ever meant "on THIS
 * thread, right now". The globals above stay for the DEBUG operator override, which is set once
 * from one thread and is meant to be process-wide. */
extern __thread int tomo_access_expired;
extern __thread int tomo_access_trimmed;
static inline int accessExpiredAllowed(void) { return server.allow_access_expired || tomo_access_expired; }
static inline int accessTrimmedAllowed(void) { return server.allow_access_trimmed || tomo_access_trimmed; }

/* Utils */
long long ustime(void);
mstime_t mstime(void);
mstime_t commandTimeSnapshot(void);
void getRandomHexChars(char *p, size_t len);
void getRandomBytes(unsigned char *p, size_t len);
uint64_t crc64(uint64_t crc, const unsigned char *s, uint64_t l);
void exitFromChild(int retcode, int from_signal);
long long redisPopcount(void *s, long count);
int redisSetProcTitle(char *title);
int validateProcTitleTemplate(const char *template);
int redisCommunicateSystemd(const char *sd_notify_msg);
void redisSetCpuAffinity(const char *cpulist);

/* afterErrorReply flags */
#define ERR_REPLY_FLAG_NO_STATS_UPDATE (1ULL<<0) /* Indicating that we should not update
                                                    error stats after sending error reply */
/* networking.c -- Networking and Client related operations */
client *createClient(connection *conn);
void freeClient(client *c);
clientCold *getClientCold(client *c);
void tomoIoDrainNote(unsigned int nread);  /* owner read-batch demand accumulator (server.c) */
void freeClientCold(client *c);
void initClientPubSubData(client *c);
void freeClientPubSubData(client *c);
void initClientReplicationData(client *c);
void initClientModuleData(client *c);
void freeClientModuleData(client *c);
void freeClientAsync(client *c);
void deauthenticateAndCloseClient(client *c);
void logInvalidUseAndFreeClientAsync(client *c, const char *fmt, ...);
int beforeNextClient(client *c);
void clearClientConnectionState(client *c);
void resetClient(client *c, int num_pcmds_to_free);
void resetClientQbufState(client *c);
/* ee451 (#44): nested-command-frame counter, defined in networking.c, reported as
 * INFO tomokv_nested_cmd_frames. See the definition for why it exists. */
extern _Atomic unsigned long long tomo_nested_cmd_frames;
/* ee451 (N): CLOSE_ASAP clients deferred by freeClientsInAsyncFreeQueue because their worker ring
 * was still in flight; defined in networking.c, reported as INFO tomokv_close_deferred_ring. */
extern _Atomic unsigned long long tomo_close_deferred_ring;
/* Bounded atomic-MSET admission. This includes every admitted versioned-write group until its
 * single csReassemble teardown, including groups whose real connection has disconnected. */
extern _Atomic unsigned long long tomo_atomic_promotions;
void tomoAtomicWindowChanged(void);
void tomoAtomicUnstallClient(client *c);
void freeClientOriginalArgv(client *c);
void freeClientArgv(client *c);
void freeClientPendingCommands(client *c, int num_pcmds_to_free);
void tryDeferFreeClientObject(client *c, int type, void *ptr);
void freeClientDeferredObjects(client *c, int free_array);
void freeClientIODeferredObjects(client *c, int free_array);
void sendReplyToClient(connection *conn);
void tomoPhaseRecvComplete(client *c);
void tomoPhaseRequestParsed(client *c, pendingCommand *pcmd);
void tomoPhaseSendDone(client *c);
void *addReplyDeferredLen(client *c);
void setDeferredArrayLen(client *c, void *node, long length);
void setDeferredMapLen(client *c, void *node, long length);
void setDeferredSetLen(client *c, void *node, long length);
void setDeferredAttributeLen(client *c, void *node, long length);
void setDeferredPushLen(client *c, void *node, long length);
int isClientReadErrorFatal(client *c);
int processInputBuffer(client *c);
int appendClientInputFromUring(client *c, const void *buf, size_t len);
int processClientInputFromUring(client *c);
void tomoUringInputBatchBegin(void);
void tomoUringInputBatchHarvestDone(void);
void tomoUringInputBatchEnd(void);
void acceptCommonHandler(connection *conn, int flags, char *ip);
void readQueryFromClient(connection *conn);
int prepareClientToWrite(client *c);
int clientPrepareReplyIOV(client *c, struct iovec *iov, int iovmax,
                          size_t byte_limit, size_t *iov_bytes_len);
int clientReplyIOVCanAsync(client *c);
void clientConsumeReplyBytes(client *c, size_t nwritten);
void addReplyNull(client *c);
void addReplyNullArray(client *c);
void addReplyBool(client *c, int b);
void addReplyVerbatim(client *c, const char *s, size_t len, const char *ext);
void addReplyProto(client *c, const char *s, size_t len);
void AddReplyFromClient(client *c, client *src);
void addReplyBulk(client *c, robj *obj);
void addReplyBulkWithFlag(client *c, robj *obj, int avoid_copy);
void addReplyBulkCString(client *c, const char *s);
void addReplyBulkCBuffer(client *c, const void *p, size_t len);
void addReplyBulkLongLong(client *c, long long ll);
void addReply(client *c, robj *obj);
void addReplyStatusLength(client *c, const char *s, size_t len);
void addReplySds(client *c, sds s);
void addReplyBulkSds(client *c, sds s);
void setDeferredReplyBulkSds(client *c, void *node, sds s);
void addReplyErrorObject(client *c, robj *err);
void addReplyOrErrorObject(client *c, robj *reply);
void afterErrorReply(client *c, const char *s, size_t len, int flags);
void addReplyErrorFormatInternal(client *c, int flags, const char *fmt, va_list ap);
void addReplyErrorSdsEx(client *c, sds err, int flags);
void addReplyErrorSdsExSafe(client *c, sds err, int flags);
void addReplyErrorSds(client *c, sds err);
void addReplyErrorSdsSafe(client *c, sds err);
void addReplyError(client *c, const char *err);
void addReplyErrorArity(client *c);
void addReplyErrorExpireTime(client *c);
void addReplyStatus(client *c, const char *status);
void addReplyStatusSafe(client *c, const char *s);
void addReplyDouble(client *c, double d);
void addReplyBigNum(client *c, const char *num, size_t len);
void addReplyHumanLongDouble(client *c, long double d);
void addReplyLongLong(client *c, long long ll);
void addReplyLongLongFromStr(client *c, robj* str);
void addReplyArrayLen(client *c, long length);
void addReplyMapLen(client *c, long length);
void addReplySetLen(client *c, long length);
void addReplyAttributeLen(client *c, long length);
void addReplyPushLen(client *c, long length);
void addReplyHelp(client *c, const char **help);
void addExtendedReplyHelp(client *c, const char **help, const char **extended_help);
void addReplySubcommandSyntaxError(client *c);
void addReplyLoadedModules(client *c);
void copyReplicaOutputBuffer(client *dst, client *src);
void addListRangeReply(client *c, robj *o, long start, long end, int reverse);
void deferredAfterErrorReply(client *c, list *errors);
size_t sdsZmallocSize(sds s);
size_t getStringObjectSdsUsedMemory(robj *o);
void freeClientReplyValue(void *o);
void *dupClientReplyValue(void *o);
char *getClientPeerId(client *client);
char *getClientSockName(client *client);
sds catClientInfoString(sds s, client *client);
sds getAllClientsInfoString(int type);
int clientSetName(client *c, robj *name, const char **err);
void rewriteClientCommandVector(client *c, int argc, ...);
void rewriteClientCommandArgument(client *c, int i, robj *newval);
void replaceClientCommandVector(client *c, int argc, robj **argv);
void redactClientCommandArgument(client *c, int argc);
size_t getClientOutputBufferMemoryUsage(client *c);
size_t getNormalClientPendingReplyBytes(client *c);
size_t getClientMemoryUsage(client *c, size_t *output_buffer_mem_usage);
int freeClientsInAsyncFreeQueue(void);
int closeClientOnOutputBufferLimitReached(client *c, int async);
int getClientType(client *c);
int getClientTypeByName(char *name);
char *getClientTypeName(int class);
void flushSlavesOutputBuffers(void);
void disconnectSlaves(void);
int listenToPort(connListener *fds);
void pauseActions(pause_purpose purpose, mstime_t end, uint32_t actions_bitmask);
void unpauseActions(pause_purpose purpose);
uint32_t isPausedActions(uint32_t action_bitmask);
uint32_t isPausedActionsWithUpdate(uint32_t action_bitmask);
void updatePausedActions(void);
void unblockPostponedClients(void);
void processEventsWhileBlocked(void);
void whileBlockedCron(void);
void blockingOperationStarts(void);
void blockingOperationEnds(void);
int handleClientsWithPendingWrites(void);
int clientHasPendingReplies(client *c);
void unlinkClient(client *c);
void tryUnlinkClientFromPendingRefReply(client *c, int force);
int writeToClient(client *c, int handler_installed);
void linkClient(client *c);
void protectClient(client *c);
void unprotectClient(client *c);
client *lookupClientByID(uint64_t id);
int authRequired(client *c);
void putClientInPendingWriteQueue(client *c);
getKeysResult *getClientCachedKeyResult(client *c);
/* reply macros */
#define ADD_REPLY_BULK_CBUFFER_STRING_CONSTANT(c, str) addReplyBulkCBuffer(c, str, strlen(str))

/* iothread.c - the threaded io implementation */
void initThreadedIO(void);
void killIOThreads(void);
void pauseIOThread(int id);
void resumeIOThread(int id);
void pauseAllIOThreads(void);
void resumeAllIOThreads(void);
void pauseIOThreadsRange(int start, int end);
void resumeIOThreadsRange(int start, int end);
int resizeAllIOThreadsEventLoops(size_t newsize);
int sendPendingClientsToIOThreads(void);
void enqueuePendingClientsToMainThread(client *c, int unbind);
void enqueuePendingClienstToIOThreads(client *c);
void handleClientReadError(client *c);
void unbindClientFromIOThreadEventLoop(client *c);
int processClientsOfAllIOThreads(void);
int processClientsFromMainThread(IOThread *t);
void assignClientToIOThread(client *c);
void keepClientInMainThread(client *c);
void fetchClientFromIOThread(client *c);
int isClientMustHandledByMainThread(client *c);

/* logreqres.c - logging of requests and responses */
void reqresReset(client *c, int free_buf);
void reqresSaveClientReplyOffset(client *c);
size_t reqresAppendRequest(client *c);
size_t reqresAppendResponse(client *c);

#ifdef __GNUC__
void addReplyErrorFormatEx(client *c, int flags, const char *fmt, ...)
    __attribute__((format(printf, 3, 4)));
void addReplyErrorFormat(client *c, const char *fmt, ...)
    __attribute__((format(printf, 2, 3)));
void addReplyStatusFormat(client *c, const char *fmt, ...)
    __attribute__((format(printf, 2, 3)));
#else
void addReplyErrorFormatEx(client *c, int flags, const char *fmt, ...);
void addReplyErrorFormat(client *c, const char *fmt, ...);
void addReplyStatusFormat(client *c, const char *fmt, ...);
#endif

/* Client side caching (tracking mode) */
void enableTracking(client *c, uint64_t redirect_to, uint64_t options, robj **prefix, size_t numprefix);
void disableTracking(client *c);
void trackingRememberKeys(client *tracking, client *executing);
void trackingInvalidateKey(client *c, robj *keyobj, int bcast);
void trackingScheduleKeyInvalidation(uint64_t client_id, robj *keyobj);
void trackingHandlePendingKeyInvalidations(void);
void trackingInvalidateKeysOnFlush(int async);
void freeTrackingRadixTree(rax *rt);
void freeTrackingRadixTreeAsync(rax *rt);
void freeErrorsRadixTreeAsync(rax *errors);
void trackingLimitUsedSlots(void);
uint64_t trackingGetTotalItems(void);
uint64_t trackingGetTotalKeys(void);
uint64_t trackingGetTotalPrefixes(void);
void trackingBroadcastInvalidationMessages(void);
int checkPrefixCollisionsOrReply(client *c, robj **prefix, size_t numprefix);

/* List data type */
void listTypePush(robj *subject, robj *value, int where);
robj *listTypePop(robj *subject, int where);
unsigned long listTypeLength(const robj *subject);
size_t listTypeAllocSize(const robj *o);
void listTypeInitIterator(listTypeIterator *li, robj *subject, long index, unsigned char direction);
void listTypeResetIterator(listTypeIterator *li);
void listTypeSetIteratorDirection(listTypeIterator *li, listTypeEntry *entry, unsigned char direction);
int listTypeNext(listTypeIterator *li, listTypeEntry *entry);
robj *listTypeGet(listTypeEntry *entry);
unsigned char *listTypeGetValue(listTypeEntry *entry, size_t *vlen, long long *lval);
void listTypeInsert(listTypeEntry *entry, robj *value, int where);
void listTypeReplace(listTypeEntry *entry, robj *value);
int listTypeEqual(listTypeEntry *entry, robj *o, size_t object_len,
                  long long *cached_longval, int *cached_valid);
void listTypeDelete(listTypeIterator *iter, listTypeEntry *entry);
robj *listTypeDup(robj *o);
void listTypeDelRange(robj *o, long start, long stop);
void popGenericCommand(client *c, int where);
void listElementsRemoved(client *c, robj *key, int where, robj *o, long count, size_t oldsize, int signal, int *deleted);
typedef enum {
    LIST_CONV_AUTO,
    LIST_CONV_GROWING,
    LIST_CONV_SHRINKING,
} list_conv_type;
typedef void (*beforeConvertCB)(void *data);
void listTypeTryConversion(robj *o, list_conv_type lct, beforeConvertCB fn, void *data);
void listTypeTryConversionAppend(robj *o, robj **argv, int start, int end, beforeConvertCB fn, void *data);

/* MULTI/EXEC/WATCH... */
void unwatchAllKeys(client *c);
unsigned long tomoTotalWatchedKeys(void);
void tomoTouchWatchedKeysOnFlush(redisDb *db, int worker);
void initClientMultiState(client *c);
void freeClientMultiState(client *c);
void queueMultiCommand(client *c, uint64_t cmd_flags);
size_t multiStateMemOverhead(client *c);
void touchWatchedKey(redisDb *db, robj *key);
int isWatchedKeyExpired(client *c);
void touchAllWatchedKeysInDb(redisDb *emptied, redisDb *replaced_with, struct slotRangeArray *slots);
void discardTransaction(client *c);
void flagTransaction(client *c);
void execCommandAbort(client *c, sds error);

unsigned char *getObjectReadOnlyString(robj *o, long *len, char *llbuf);

unsigned long long estimateObjectIdleTime(robj *o);
#define sdsEncodedObject(objptr) (objptr->encoding == OBJ_ENCODING_RAW || objptr->encoding == OBJ_ENCODING_EMBSTR)

/* Synchronous I/O with timeout */
ssize_t syncWrite(int fd, char *ptr, ssize_t size, long long timeout);
ssize_t syncRead(int fd, char *ptr, ssize_t size, long long timeout);
ssize_t syncReadLine(int fd, char *ptr, ssize_t size, long long timeout);

/* Replication */
void replicationFeedSlaves(list *slaves, int dictid, robj **argv, int argc);
void replicationFeedStreamFromMasterStream(char *buf, size_t buflen);
void resetReplicationBuffer(void);
void feedReplicationBuffer(char *buf, size_t len);
void freeReplicaReferencedReplBuffer(client *replica);
void replicationFeedMonitors(client *c, list *monitors, int dictid, robj **argv, int argc);
void updateSlavesWaitingBgsave(int bgsaveerr, int type);
void replicationCron(void);
void replicationStartPendingFork(void);
void replicationHandleMasterDisconnection(void);
void replicationCacheMaster(client *c);
void resizeReplicationBacklog(void);
void replicationSetMaster(char *ip, int port);
void replicationUnsetMaster(void);
void refreshGoodSlavesCount(void);
int checkGoodReplicasStatus(void);
void processClientsWaitingReplicas(void);
void unblockClientWaitingReplicas(client *c);
int replicationCountAcksByOffset(long long offset);
int replicationCountAOFAcksByOffset(long long offset);
void replicationSendNewlineToMaster(void);
long long replicationGetSlaveOffset(void);
char *replicationGetSlaveName(client *c);
long long getPsyncInitialOffset(void);
int replicationSetupSlaveForFullResync(client *slave, long long offset);
void changeReplicationId(void);
void clearReplicationId2(void);
void createReplicationBacklog(void);
void freeReplicationBacklog(void);
void replicationCacheMasterUsingMyself(void);
void feedReplicationBacklog(void *ptr, size_t len);
void incrementalTrimReplicationBacklog(size_t blocks);
int canFeedReplicaReplBuffer(client *replica);
void rebaseReplicationBuffer(long long base_repl_offset);
void showLatestBacklog(void);
void rdbPipeReadHandler(struct aeEventLoop *eventLoop, int fd, void *clientData, int mask);
void rdbPipeWriteHandlerConnRemoved(struct connection *conn);
void clearFailoverState(void);
void updateFailoverStatus(void);
void abortFailover(const char *err);
const char *getFailoverStateString(void);
int replicationCheckHasMainChannel(client *slave);
unsigned long replicationLogicalReplicaCount(void);
void replDataBufInit(replDataBuf *buf);
void replDataBufClear(replDataBuf *buf);
void replDataBufReadFromConn(connection *conn, replDataBuf *buf, void (*error_handler)(connection *conn));
int replDataBufStreamToDb(replDataBuf *buf, replDataBufToDbCtx *ctx);
int replicaFromIOThreadHasPendingRead(client *c);
void putReplicasInPendingClientsToIOThreads(void);
int replicationCronRunMasterClient(void);

/* Generic persistence functions */
void startLoadingFile(size_t size, char* filename, int rdbflags);
void startLoading(size_t size, int rdbflags, int async);
void loadingSetFlags(char *filename, size_t size, int async);
void loadingFireEvent(int rdbflags);
void loadingAbsProgress(off_t pos);
void loadingIncrProgress(off_t size);
void stopLoading(int success);
void updateLoadingFileName(char* filename);
void startSaving(int rdbflags);
void stopSaving(int success);
int allPersistenceDisabled(void);

#define DISK_ERROR_TYPE_AOF 1       /* Don't accept writes: AOF errors. */
#define DISK_ERROR_TYPE_RDB 2       /* Don't accept writes: RDB errors. */
#define DISK_ERROR_TYPE_NONE 0      /* No problems, we can accept writes. */
int writeCommandsDeniedByDiskError(void);
sds writeCommandsGetDiskErrorMessage(int);

/* RDB persistence */
#include "rdb.h"
void killRDBChild(void);
int bg_unlink(const char *filename);

/* AOF persistence */
void flushAppendOnlyFile(int force);
void feedAppendOnlyFile(int dictid, robj **argv, int argc);
void aofRemoveTempFile(pid_t childpid);
int rewriteAppendOnlyFileBackground(void);
int loadAppendOnlyFiles(aofManifest *am);
void stopAppendOnly(void);
int startAppendOnly(void);
void startAppendOnlyWithRetry(void);
void applyAppendOnlyConfig(void);
void backgroundRewriteDoneHandler(int exitcode, int bysignal);
void killAppendOnlyChild(void);
void aofLoadManifestFromDisk(void);
void aofOpenIfNeededOnServerStart(void);
void aofManifestFree(aofManifest *am);
int aofDelHistoryFiles(void);
int aofRewriteLimited(void);
void updateCurIncrAofEndOffset(void);
void updateReplOffsetAndResetEndOffset(void);
int rewriteObject(rio *r, robj *key, robj *o, int dbid, long long expiretime);

/* Child info */
void openChildInfoPipe(void);
void closeChildInfoPipe(void);
void sendChildInfoGeneric(childInfoType info_type, size_t keys, double progress, char *pname);
void sendChildCowInfo(childInfoType info_type, char *pname);
void sendChildInfo(childInfoType info_type, size_t keys, char *pname);
void receiveChildInfo(void);

/* Fork helpers */
int redisFork(int purpose);
int hasActiveChildProcess(void);
void resetChildState(void);
int isMutuallyExclusiveChildType(int type);

/* acl.c -- Authentication related prototypes. */
extern rax *Users;
extern user *DefaultUser;
void ACLInit(void);
/* Return values for ACLCheckAllPerm(). */
#define ACL_OK 0
#define ACL_DENIED_CMD 1
#define ACL_DENIED_KEY 2
#define ACL_DENIED_AUTH 3 /* Only used for ACL LOG entries. */
#define ACL_DENIED_CHANNEL 4 /* Only used for pub/sub commands */
#define ACL_INVALID_TLS_CERT_AUTH 5 /* Only used for TLS Auto-authentication */

/* Context values for addACLLogEntry(). */
#define ACL_LOG_CTX_TOPLEVEL 0
#define ACL_LOG_CTX_LUA 1
#define ACL_LOG_CTX_MULTI 2
#define ACL_LOG_CTX_MODULE 3

/* ACL key permission types */
#define ACL_READ_PERMISSION (1<<0)
#define ACL_WRITE_PERMISSION (1<<1)
#define ACL_ALL_PERMISSION (ACL_READ_PERMISSION|ACL_WRITE_PERMISSION)

/* Return codes for Authentication functions to indicate the result. */
typedef enum {
    AUTH_OK = 0,
    AUTH_ERR,
    AUTH_NOT_HANDLED,
    AUTH_BLOCKED
} AuthResult;

int ACLCheckUserCredentials(robj *username, robj *password);
int ACLAuthenticateUser(client *c, robj *username, robj *password, robj **err);
int checkModuleAuthentication(client *c, robj *username, robj *password, robj **err);
void addAuthErrReply(client *c, robj *err);
unsigned long ACLGetCommandID(sds cmdname);
void ACLClearCommandID(void);
user *ACLGetUserByName(const char *name, size_t namelen);
int ACLUserCheckKeyPerm(user *u, const char *key, int keylen, int flags);
int ACLUserCheckChannelPerm(user *u, sds channel, int literal);
int ACLCheckAllUserCommandPerm(user *u, struct redisCommand *cmd, robj **argv, int argc, getKeysResult *key_result, int *idxptr);
int ACLUserCheckCmdWithUnrestrictedKeyAccess(user *u, struct redisCommand *cmd, robj **argv, int argc, int flags);
int ACLCheckAllPerm(client *c, int *idxptr);
int ACLSetUser(user *u, const char *op, ssize_t oplen);
sds ACLStringSetUser(user *u, sds username, sds *argv, int argc);
uint64_t ACLGetCommandCategoryFlagByName(const char *name);
int ACLAddCommandCategory(const char *name, uint64_t flag);
void ACLCleanupCategoriesOnFailure(size_t num_acl_categories_added);
int ACLAppendUserForLoading(sds *argv, int argc, int *argc_err);
const char *ACLSetUserStringError(void);
int ACLLoadConfiguredUsers(void);
robj *ACLDescribeUser(user *u);
void ACLLoadUsersAtStartup(void);
void addReplyCommandCategories(client *c, struct redisCommand *cmd);
user *ACLCreateUnlinkedUser(void);
void ACLFreeUserAndKillClients(user *u);
void addACLLogEntry(client *c, int reason, int context, int argpos, sds username, sds object);
sds getAclErrorMessage(int acl_res, user *user, struct redisCommand *cmd, sds errored_val, int verbose);
void ACLUpdateDefaultUserPassword(sds password);
sds genRedisInfoStringACLStats(sds info);
void ACLRecomputeCommandBitsFromCommandRulesAllUsers(void);

/* Sorted sets data type */

/* Input flags. */
#define ZADD_IN_NONE 0
#define ZADD_IN_INCR (1<<0)    /* Increment the score instead of setting it. */
#define ZADD_IN_NX (1<<1)      /* Don't touch elements not already existing. */
#define ZADD_IN_XX (1<<2)      /* Only touch elements already existing. */
#define ZADD_IN_GT (1<<3)      /* Only update existing when new scores are higher. */
#define ZADD_IN_LT (1<<4)      /* Only update existing when new scores are lower. */

/* Output flags. */
#define ZADD_OUT_NOP (1<<0)     /* Operation not performed because of conditionals.*/
#define ZADD_OUT_NAN (1<<1)     /* Only touch elements already existing. */
#define ZADD_OUT_ADDED (1<<2)   /* The element was new and was added. */
#define ZADD_OUT_UPDATED (1<<3) /* The element already existed, score updated. */

/* Struct to hold an inclusive/exclusive range spec by score comparison. */
typedef struct {
    double min, max;
    int minex, maxex; /* are min or max exclusive? */
} zrangespec;

/* Struct to hold an inclusive/exclusive range spec by lexicographic comparison. */
typedef struct {
    sds min, max;     /* May be set to shared.(minstring|maxstring) */
    int minex, maxex; /* are min or max exclusive? */
} zlexrangespec;

/* flags for incrCommandFailedCalls */
#define ERROR_COMMAND_REJECTED (1<<0) /* Indicate to update the command rejected stats */
#define ERROR_COMMAND_FAILED (1<<1) /* Indicate to update the command failed stats */

zskiplist *zslCreate(void);
void zslFree(zskiplist *zsl);
size_t zslAllocSize(const zskiplist *zsl);
sds zslGetNodeElement(const zskiplistNode *node);
int zslCompareWithNode(double score, sds ele, const zskiplistNode *n);
zskiplistNode *zslInsert(zskiplist *zsl, double score, sds ele);
unsigned char *zzlInsert(unsigned char *zl, sds ele, double score);
zskiplistNode *zslNthInRange(zskiplist *zsl, zrangespec *range, long n, unsigned long *out_rank);
double zzlGetScore(unsigned char *sptr);
void zzlNext(unsigned char *zl, unsigned char **eptr, unsigned char **sptr);
void zzlPrev(unsigned char *zl, unsigned char **eptr, unsigned char **sptr);
unsigned char *zzlFirstInRange(unsigned char *zl, zrangespec *range);
unsigned char *zzlLastInRange(unsigned char *zl, zrangespec *range);
unsigned long zsetLength(const robj *zobj);
size_t zsetAllocSize(const robj *o);
void zsetConvert(robj *zobj, int encoding);
void zsetConvertToListpackIfNeeded(robj *zobj, size_t maxelelen, size_t totelelen);
int zsetScore(robj *zobj, sds member, double *score);
unsigned long zslGetRank(zskiplist *zsl, double score, sds o);
int zsetAdd(robj *zobj, double score, sds ele, int in_flags, int *out_flags, double *newscore);
long zsetRank(robj *zobj, sds ele, int reverse, double *score);
int zsetDel(robj *zobj, sds ele);
robj *zsetDup(robj *o);
void genericZpopCommand(client *c, robj **keyv, int keyc, int where, int emitkey, long count, int use_nested_array, int reply_nil_when_empty, int *deleted);
sds lpGetObject(unsigned char *sptr);
int zslValueGteMin(double value, zrangespec *spec);
int zslValueLteMax(double value, zrangespec *spec);
void zslFreeLexRange(zlexrangespec *spec);
int zslParseLexRange(robj *min, robj *max, zlexrangespec *spec);
unsigned char *zzlFirstInLexRange(unsigned char *zl, zlexrangespec *range);
unsigned char *zzlLastInLexRange(unsigned char *zl, zlexrangespec *range);
zskiplistNode *zslNthInLexRange(zskiplist *zsl, zlexrangespec *range, long n, unsigned long *out_rank);
int zzlLexValueGteMin(unsigned char *p, zlexrangespec *spec);
int zzlLexValueLteMax(unsigned char *p, zlexrangespec *spec);
int zslLexValueGteMin(sds value, zlexrangespec *spec);
int zslLexValueLteMax(sds value, zlexrangespec *spec);

/* Core functions */
int getMaxmemoryState(size_t *total, size_t *logical, size_t *tofree, float *level);
void updatePeakMemory(void);
size_t freeMemoryGetNotCountedMemory(void);
int overMaxmemoryAfterAlloc(size_t moremem);
uint64_t getCommandFlags(client *c);
void preprocessCommand(client *c, pendingCommand *pcmd);
int processCommand(client *c);
void commandProcessed(client *c);
void prepareForNextCommand(client *c, int update_slot_stats);
int processPendingCommandAndInputBuffer(client *c);
int processCommandAndResetClient(client *c);
int areCommandKeysInSameSlot(client *c, int *hashslot);
void setupSignalHandlers(void);
int createSocketAcceptHandler(connListener *sfd, aeFileProc *accept_handler);
connListener *listenerByType(const char *typename);
int changeListener(connListener *listener);
void closeListener(connListener *listener);
struct redisCommand *lookupSubcommand(struct redisCommand *container, sds sub_name);
struct redisCommand *lookupCommand(robj **argv, int argc);
struct redisCommand *lookupCommandBySdsLogic(dict *commands, sds s);
struct redisCommand *lookupCommandBySds(sds s);
struct redisCommand *lookupCommandByCStringLogic(dict *commands, const char *s);
struct redisCommand *lookupCommandByCString(const char *s);
struct redisCommand *lookupCommandOrOriginal(robj **argv, int argc);
int commandCheckExistence(client *c, sds *err);
int commandCheckArity(struct redisCommand *cmd, int argc, sds *err);
void startCommandExecution(void);
int incrCommandStatsOnError(struct redisCommand *cmd, int flags);
void call(client *c, int flags);
void alsoPropagate(int dbid, robj **argv, int argc, int target);
void postExecutionUnitOperations(void);
int redisOpArrayAppend(redisOpArray *oa, int dbid, robj **argv, int argc, int target);
void redisOpArrayFree(redisOpArray *oa);
void forceCommandPropagation(client *c, int flags);
void preventCommandPropagation(client *c);
void preventCommandAOF(client *c);
void preventCommandReplication(client *c);
void slowlogPushCurrentCommand(client *c, struct redisCommand *cmd, ustime_t duration);
void updateCommandLatencyHistogram(struct hdr_histogram** latency_histogram, int64_t duration_hist);
int prepareForShutdown(int flags);
void replyToClientsBlockedOnShutdown(void);
int abortShutdown(void);
void afterCommand(client *c);
int mustObeyClient(client *c);
#ifdef __GNUC__
void _serverLog(int level, const char *fmt, ...)
    __attribute__((format(printf, 2, 3)));
void serverLogFromHandler(int level, const char *fmt, ...)
    __attribute__((format(printf, 2, 3)));
#else
void serverLogFromHandler(int level, const char *fmt, ...);
void _serverLog(int level, const char *fmt, ...);
#endif
void serverLogRaw(int level, const char *msg);
void serverLogRawFromHandler(int level, const char *msg);
void usage(void);
void updateDictResizePolicy(void);
void populateCommandTable(void);
void tomoSvcTick(void);   /* ee451 D: 1 Hz svc-plane fold */
void tomoReorderDrain(void);   /* ee451 D: reorder scratch -> lanes (flushExQueues top) */
robj *commandNameIntern(const char *p, size_t len);  /* ee451 (v14): argv[0] interning */
void resetCommandTableStats(dict* commands);
void resetErrorTableStats(void);
void adjustOpenFilesLimit(void);
void incrementErrorCount(const char *fullerr, size_t namelen);
void closeListeningSockets(int unlink_unix_socket);
void updateCachedTime(int update_daylight_info);
/* ee451 (A-F.4): execution nesting depth is PER THREAD, not per process. Every reader means
 * "how deep is the unit *I* am running in"; see the definition in server.c. */
extern __thread int execution_nesting;
/* T6: EXEC can run concurrently on independent owner workers. Local semantic checks use
 * tomo_in_exec; the server counter only answers the process-wide persistence/fork question. */
extern __thread int tomo_in_exec;
void tomoExecEnter(void);
void tomoExecExit(void);
int tomoAnyExecRunning(void);
void enterExecutionUnit(int update_cached_time, long long us);
void exitExecutionUnit(void);
void resetServerStats(void);
void activeDefragCycle(void);
void defragWhileBlocked(void);
unsigned int getLRUClock(void);
unsigned int LRU_CLOCK(void);
const char *evictPolicyToString(void);
struct redisMemOverhead *getMemoryOverheadData(void);
void freeMemoryOverheadData(struct redisMemOverhead *mh);
void checkChildrenDone(void);
int setOOMScoreAdj(int process_class);
void rejectCommandFormat(client *c, const char *fmt, ...);
void *activeDefragAlloc(void *ptr);
void *activeDefragAllocRaw(size_t size);
void activeDefragFreeRaw(void *ptr);
robj *activeDefragStringOb(robj* ob);
void dismissSds(sds s);
void dismissMemory(void* ptr, size_t size_hint);
void dismissMemoryInChild(void);
int clientsCronRunClient(client *c);

#define RESTART_SERVER_NONE 0
#define RESTART_SERVER_GRACEFULLY (1<<0)     /* Do proper shutdown. */
#define RESTART_SERVER_CONFIG_REWRITE (1<<1) /* CONFIG REWRITE before restart.*/
int restartServer(int flags, mstime_t delay);
uint64_t tomoKeyHash(const void *key, size_t len);
int getKeySlot(sds key);
int calculateKeySlot(sds key);

/* kvstore wrappers */
int dbExpand(redisDb *db, uint64_t db_size, int try_expand);
int dbExpandExpires(redisDb *db, uint64_t db_size, int try_expand);
kvobj *dbFind(redisDb *db, sds key);
kvobj *dbFindByLink(redisDb *db, sds key, dictEntryLink *link);
kvobj *dbFindExpires(redisDb *db, sds key);
unsigned long long dbSize(redisDb *db);
unsigned long long dbScan(redisDb *db, unsigned long long cursor, dictScanFunction *scan_cb, void *privdata);
/* FLATSTORE QSBR: open/close a reader region from outside server.c (see flatExternEnter). Any
 * thread that walks a flat table holding RAW kvobj pointers must be inside one, or a worker can
 * free what it is dereferencing. Nesting-safe. */
void flatQsbrRegionEnter(void);
void flatQsbrRegionExit(void);

/* Set data type */
robj *setTypeCreate(sds value, size_t size_hint);
int setTypeAdd(robj *subject, sds value);
int setTypeAddAux(robj *set, char *str, size_t len, int64_t llval, int str_is_sds);
int setTypeRemove(robj *subject, sds value);
int setTypeRemoveAux(robj *set, char *str, size_t len, int64_t llval, int str_is_sds);
int setTypeIsMember(robj *subject, sds value);
int setTypeIsMemberAux(robj *set, char *str, size_t len, int64_t llval, int str_is_sds);
void setTypeInitIterator(setTypeIterator *si, robj *subject);
void setTypeResetIterator(setTypeIterator *si);
int setTypeNext(setTypeIterator *si, char **str, size_t *len, int64_t *llele);
sds setTypeNextObject(setTypeIterator *si);
int setTypeRandomElement(robj *setobj, char **str, size_t *len, int64_t *llele);
unsigned long setTypeSize(const robj *subject);
size_t setTypeAllocSize(const robj *o);
void setTypeConvert(robj *subject, int enc);
int setTypeConvertAndExpand(robj *setobj, int enc, unsigned long cap, int panic);
robj *setTypeDup(robj *o);

/* Data structure for OBJ_ENCODING_LISTPACK_EX for hash. It contains listpack
 * and metadata fields for hash field expiration.*/
typedef struct listpackEx {
    ExpireMeta meta;  /* To be used in order to register the hash in the
                         global ebuckets subexpires with next, minimum,
                         hash-field to expire. TTL value might be inaccurate
                         up-to few seconds due to optimization consideration. */
    void *lp;         /* listpack that contains 'key-value-ttl' tuples which
                         are ordered by ttl. */
} listpackEx;

/* Each dict of hash object that has fields with time-Expiration will have the
 * following metadata attached to dict header.
 * Note that alloc_size field must be first because hash objects without expre
 * already use sizeof(size_t) bytes of metadata for memory accounting. */
typedef struct htMetadataEx {
    size_t alloc_size;       /* Total memory used for keys and values */
    ExpireMeta expireMeta;   /* embedded ExpireMeta in dict.
                                To be used in order to register the hash in the
                                subexpires DB with next minimum hash-field to expire.
                                TTL value might be inaccurate up-to few seconds due
                                to optimization consideration. */
    ebuckets hfe;            /* DS of Hash Fields Expiration, associated to each hash */
} htMetadataEx;

/* hash metadata helpers */
static inline htMetadataEx *htGetMetadataEx(dict *d) {
    return (htMetadataEx *)dictMetadata(d);
}

static inline size_t *htGetMetadataSize(dict *d) {
    return (size_t *)dictMetadata(d);
}

/* Hash data type */
#define HASH_SET_TAKE_FIELD (1<<0)
#define HASH_SET_TAKE_VALUE (1<<1)
#define HASH_SET_COPY 0

/* Hash field lazy expiration flags. Used by core hashTypeGetValue() and its callers */
#define HFE_LAZY_EXPIRE              (0)    /* Delete expired field, and if last field also the hash */
#define HFE_LAZY_AVOID_FIELD_DEL     (1<<0) /* Avoid deleting expired field */
#define HFE_LAZY_AVOID_HASH_DEL      (1<<1) /* Avoid deleting hash if the field is the last one */
#define HFE_LAZY_NO_NOTIFICATION     (1<<2) /* Do not send notification, used when multiple fields
                                             * may expire and only one notification is desired. */
#define HFE_LAZY_NO_SIGNAL           (1<<3)    /* Do not send signal, used when multiple fields
                                             * may expire and only one signal is desired. */
#define HFE_LAZY_ACCESS_EXPIRED      (1<<4) /* Avoid lazy expire and allow access to expired fields */
#define HFE_LAZY_NO_UPDATE_KEYSIZES  (1<<5) /* If field lazy deleted, avoid updating keysizes histogram */
#define HFE_LAZY_NO_UPDATE_ALLOCSIZES (1<<6) /* If field lazy deleted, avoid updating slot allocation sizes */

void hashTypeConvert(redisDb *db, robj *o, int enc);
void hashTypeTryConversion(redisDb *db, kvobj *kv, robj **argv, int start, int end);
int hashTypeExists(redisDb *db, kvobj *kv, sds field, int hfeFlags, int *isHashDeleted);
int hashTypeDelete(robj *o, void *key);
unsigned long hashTypeLength(const robj *o, int subtractExpiredFields);
size_t hashTypeAllocSize(const robj *o);
void hashTypeInitIterator(hashTypeIterator *hi, robj *subject);
void hashTypeResetIterator(hashTypeIterator *hi);
int hashTypeNext(hashTypeIterator *hi, int skipExpiredFields);
void hashTypeCurrentFromListpack(hashTypeIterator *hi, int what,
                                 unsigned char **vstr,
                                 unsigned int *vlen,
                                 long long *vll,
                                 uint64_t *expireTime);
void hashTypeCurrentFromHashTable(hashTypeIterator *hi, int what, char **str,
                                  size_t *len, uint64_t *expireTime);
void hashTypeCurrentObject(hashTypeIterator *hi, int what, unsigned char **vstr,
                           unsigned int *vlen, long long *vll, uint64_t *expireTime);
sds hashTypeCurrentObjectNewSds(hashTypeIterator *hi, int what);
Entry *hashTypeCurrentObjectNewEntry(hashTypeIterator *hi, size_t *usable);
int hashTypeGetValueObject(redisDb *db, kvobj *kv, sds field, int hfeFlags,
                           robj **val, uint64_t *expireTime, int *isHashDeleted);
int hashTypeSet(redisDb *db, kvobj *kv, sds field, sds value, int flags);
robj *hashTypeDup(kvobj *kv, uint64_t *minHashExpire);
uint64_t hashTypeExpire(redisDb *db, kvobj *o, uint32_t *quota, int updateSubexpires, int activeEx);
void hashTypeFree(robj *o);
int hashTypeIsExpired(const robj *o, uint64_t expireAt);
unsigned char *hashTypeListpackGetLp(robj *o);
uint64_t hashTypeGetMinExpire(robj *o, int accurate);
ebuckets *hashTypeGetDictMetaHFE(dict *d);
void initDictExpireMetadata(robj *o);
struct listpackEx *listpackExCreate(void);
void listpackExAddNew(robj *o, char *field, size_t flen,
                      char *value, size_t vlen, uint64_t expireAt);

/* Pub / Sub */
int pubsubUnsubscribeAllChannels(client *c, int notify);
int pubsubUnsubscribeShardAllChannels(client *c, int notify);
void pubsubShardUnsubscribeAllChannelsInSlot(unsigned int slot);
int pubsubUnsubscribeAllPatterns(client *c, int notify);
int pubsubPublishMessage(robj *channel, robj *message, int sharded);
int pubsubPublishMessageAndPropagateToCluster(robj *channel, robj *message, int sharded);
void addReplyPubsubMessage(client *c, robj *channel, robj *msg, robj *message_bulk);
int serverPubsubSubscriptionCount(void);
int serverPubsubShardSubscriptionCount(void);
size_t pubsubMemOverhead(client *c);
void unmarkClientAsPubSub(client *c);
int pubsubTotalSubscriptions(void);
dict *getClientPubSubChannels(client *c);
dict *getClientPubSubShardChannels(client *c);

/* Keyspace events notification */
void notifyKeyspaceEvent(int type, const char *event, robj *key, int dbid);
int keyspaceEventsStringToFlags(char *classes);
sds keyspaceEventsFlagsToString(int flags);

/* Configuration */
/* Configuration Flags */
#define MODIFIABLE_CONFIG 0 /* This is the implied default for a standard
                             * config, which is mutable. */
#define IMMUTABLE_CONFIG (1ULL<<0) /* Can this value only be set at startup? */
#define SENSITIVE_CONFIG (1ULL<<1) /* Does this value contain sensitive information */
#define DEBUG_CONFIG (1ULL<<2) /* Values that are useful for debugging. */
#define MULTI_ARG_CONFIG (1ULL<<3) /* This config receives multiple arguments. */
#define HIDDEN_CONFIG (1ULL<<4) /* This config is hidden in `config get <pattern>` (used for tests/debugging) */
#define PROTECTED_CONFIG (1ULL<<5) /* Becomes immutable if enable-protected-configs is enabled. */
#define DENY_LOADING_CONFIG (1ULL<<6) /* This config is forbidden during loading. */
#define ALIAS_CONFIG (1ULL<<7) /* For configs with multiple names, this flag is set on the alias. */
#define MODULE_CONFIG (1ULL<<8) /* This config is a module config */
#define VOLATILE_CONFIG (1ULL<<9) /* The config is a reference to the config data and not the config data itself (ex.
                                   * a file name containing more configuration like a tls key). In this case we want
                                   * to apply the configuration change even if the new config value is the same as
                                   * the old. */

#define INTEGER_CONFIG 0 /* No flags means a simple integer configuration */
#define MEMORY_CONFIG (1<<0) /* Indicates if this value can be loaded as a memory value */
#define PERCENT_CONFIG (1<<1) /* Indicates if this value can be loaded as a percent (and stored as a negative int) */
#define OCTAL_CONFIG (1<<2) /* This value uses octal representation */

/* Enum Configs contain an array of configEnum objects that match a string with an integer. */
typedef struct configEnum {
    char *name;
    int val;
} configEnum;

/* Type of configuration. */
typedef enum {
    BOOL_CONFIG,
    NUMERIC_CONFIG,
    STRING_CONFIG,
    SDS_CONFIG,
    ENUM_CONFIG,
    SPECIAL_CONFIG,
} configType;

void loadServerConfig(char *filename, char config_from_stdin, char *options);
void appendServerSaveParams(time_t seconds, int changes);
void resetServerSaveParams(void);
struct rewriteConfigState; /* Forward declaration to export API. */
int rewriteConfigRewriteLine(struct rewriteConfigState *state, const char *option, sds line, int force);
void rewriteConfigMarkAsProcessed(struct rewriteConfigState *state, const char *option);
int rewriteConfig(char *path, int force_write);
void initConfigValues(void);
void removeConfig(sds name);
sds getConfigDebugInfo(void);
int allowProtectedAction(int config, client *c);
static inline int clusterSlotStatsEnabled(int stat) { return server.cluster_enabled && (server.cluster_slot_stats_enabled & stat); }

/* Module Configuration */
typedef struct ModuleConfig ModuleConfig;
int performModuleConfigSetFromName(sds name, sds value, const char **err);
int performModuleConfigSetDefaultFromName(sds name, const char **err);
void addModuleBoolConfig(sds name, sds alias, int flags, void *privdata, int default_val);
void addModuleStringConfig(sds name, sds alias, int flags, void *privdata, sds default_val);
void addModuleEnumConfig(sds name, sds alias, int flags, void *privdata, int default_val, configEnum *enum_vals, int num_enum_vals);
void addModuleNumericConfig(sds name, sds alias, int flags, void *privdata, long long default_val, int conf_flags, long long lower, long long upper);
void addModuleConfigApply(list *module_configs, ModuleConfig *module_config);
int moduleConfigApply(ModuleConfig *module_config, const char **err);
int moduleConfigApplyConfig(list *module_configs, const char **err, const char **err_arg_name);
int moduleConfigNeedsApply(ModuleConfig *config);
int getModuleBoolConfig(ModuleConfig *module_config);
int setModuleBoolConfig(ModuleConfig *config, int val, const char **err);
sds getModuleStringConfig(ModuleConfig *module_config);
int setModuleStringConfig(ModuleConfig *config, sds strval, const char **err);
int getModuleEnumConfig(ModuleConfig *module_config);
int setModuleEnumConfig(ModuleConfig *config, int val, const char **err);
long long getModuleNumericConfig(ModuleConfig *module_config);
int setModuleNumericConfig(ModuleConfig *config, long long val, const char **err);

/* API for modules to access config values. */
dictIterator *moduleGetConfigIterator(void);
const char *moduleConfigIteratorNext(dictIterator **iter, sds pattern, int is_glob, configType *typehint);
int moduleGetConfigType(sds name, configType *res);
int moduleGetBoolConfig(sds name, int *res);
int moduleGetStringConfig(sds name, sds *res);
int moduleGetEnumConfig(sds name, sds *res);
int moduleGetNumericConfig(sds name, long long *res);
int moduleSetBoolConfig(client *c, sds name, int val, const char **err);
int moduleSetStringConfig(client *c, sds name, const char *val, const char **err);
int moduleSetEnumConfig(client *c, sds name, sds *vals, int vals_cnt, const char **err);
int moduleSetNumericConfig(client *c, sds name, long long val, const char **err);

/* db.c -- Keyspace access API */
void updateKeysizesHist(redisDb *db, int didx, uint32_t type, int64_t oldLen, int64_t newLen);
void updateSlotAllocSize(redisDb *db, int didx, kvobj *kv, int64_t oldsize, int64_t newsize);
void updateSlotHist(keysizesHist kvstoreHist, keysizesHist dictHist, uint32_t type, int64_t oldLen, int64_t newLen);
void dbgAssertKeysizesHist(redisDb *db);
void dbgAssertAllocSizePerSlot(redisDb *db);
int removeExpire(redisDb *db, robj *key);
void deleteExpiredKeyAndPropagate(redisDb *db, robj *keyobj);
void deleteEvictedKeyAndPropagate(redisDb *db, robj *keyobj, long long *key_mem_freed);
void propagateDeletion(redisDb *db, robj *key, int lazy);
int keyIsExpired(redisDb *db, sds key, kvobj *kv);
int confAllowsExpireDel(void);
long long getExpire(redisDb *db, sds key, kvobj *kv);
kvobj *setExpire(client *c, redisDb *db, robj *key, long long when);
kvobj *setExpireByLink(client *c, redisDb *db, sds key, long long when, dictEntryLink link);
int checkAlreadyExpired(long long when);
int parseExtendedExpireArgumentsOrReply(client *c, int *flags);
kvobj *lookupKeyRead(redisDb *db, robj *key);
kvobj *lookupKeyWrite(redisDb *db, robj *key);
void updateLFU(robj *val);
kvobj *lookupKeyWriteWithLink(redisDb *db, robj *key, dictEntryLink *link);
kvobj *lookupKeyReadOrReply(client *c, robj *key, robj *reply);
kvobj *lookupKeyWriteOrReply(client *c, robj *key, robj *reply);
kvobj *lookupKeyReadWithFlags(redisDb *db, robj *key, int flags);
kvobj *lookupKeyWriteWithFlags(redisDb *db, robj *key, int flags);
kvobj *kvobjCommandLookup(client *c, robj *key);
/* ee451: read-run value forwarding (same-key read chains on a worker). */
kvobj *kvobjCommandLookupOrReply(client *c, robj *key, robj *reply);

#define LOOKUP_NONE 0
#define LOOKUP_NOTOUCH (1<<0)        /* Don't update LRU. */
#define LOOKUP_NONOTIFY (1<<1)       /* Don't trigger keyspace event on key misses. */
#define LOOKUP_NOSTATS (1<<2)        /* Don't update keyspace hits/misses counters. */
#define LOOKUP_WRITE (1<<3)          /* Delete expired keys even in replicas. */
#define LOOKUP_NOEXPIRE (1<<4)       /* Avoid deleting lazy expired keys. */
#define LOOKUP_ACCESS_EXPIRED (1<<5) /* Allow lookup to expired key. */
#define LOOKUP_ACCESS_TRIMMED (1<<6) /* Allow lookup to key in slots being trimmed. */
#define LOOKUP_NOEFFECTS (LOOKUP_NONOTIFY | LOOKUP_NOSTATS | LOOKUP_NOTOUCH | LOOKUP_NOEXPIRE) /* Avoid any effects from fetching the key */

static inline kvobj *dictGetKV(const dictEntry *de) {return (kvobj *) dictGetKey(de);}
kvobj *dbAdd(redisDb *db, robj *key, robj **valref);
kvobj *dbAddByLink(redisDb *db, robj *key, robj **valref, dictEntryLink *link);
kvobj *dbAddInternal(redisDb *db, robj *key, robj **valref, dictEntryLink *link, const KeyMetaSpec *m,
                     int embedRawOk);
kvobj *dbAddRDBLoad(redisDb *db, sds key, robj **valref, const KeyMetaSpec *keyMetaSpec);
void dbReplaceValue(redisDb *db, robj *key, kvobj **ioKeyVal, int updateKeySizes);
void dbReplaceValueWithLink(redisDb *db, robj *key, robj **val, dictEntryLink link);

#define SETKEY_KEEPTTL 1
#define SETKEY_NO_SIGNAL 2
#define SETKEY_ALREADY_EXIST 4
#define SETKEY_DOESNT_EXIST 8
/* CANDIDATE (census rank-3): caller guarantees the stored value is final -- it
 * will not be mutated in place through the *valref result without first going
 * through dbUnshareStringValue(). Lets kvobjSetEx() copy a small RAW string
 * value into the kvobj allocation (single-allocation EMBSTR). See kvobjSetEx(). */
#define SETKEY_EMBED_RAW 16

void setKey(client *c, redisDb *db, robj *key, robj **ioval, int flags);
kvobj *setKeyVersioned(client *c, redisDb *db, robj *key, robj **ioval, int flags,
                       uint64_t version_seq, long long version_expire);
void tomoApplyVersionStamp(kvobj *kv, uint64_t version_seq);
void tomoCancelVersion(kvobj *kv);
void tomoArmVersionRetire(kvobj *kv, uint64_t version_seq);
void tomoVersionPruneAfterGrace(kvobj *anchor);
void tomoRetireDetachedBag(kvstore *kvs, kvobj *head);
void tomoAtomicLifecycleEnsure(void);
void tomoAtomicLifecycleRelease(struct tomoVerMeta *vmeta);
void tomoAtomicOwnerCheck(struct tomoVerMeta *vmeta, int executing_owner,
                          int prune_callback);
/* Return the command's already-pinned snapshot without touching commit_seq.
 * False means this is a single-owner/current read which may linearize now. */
static inline int tomoPinnedReadSnapshot(uint64_t *snapshot) {
    client *c = server.current_client[iotid].p;
    if (!c) return 0;
    if (c->tomo_read_snapshot_pinned) {
        *snapshot = c->tomo_read_snapshot;
        return 1;
    }
    if (c->csparent) {
        csGroup *g = c->csparent;
        if (g->snapshot_pinned) {
            *snapshot = g->read_seq;
            return 1;
        }
        if (g->head && g->head->tomo_read_snapshot_pinned) {
            *snapshot = g->head->tomo_read_snapshot;
            return 1;
        }
    }
    return 0;
}
uint64_t tomoCurrentReadSnapshot(void);
uint64_t tomoCommittedSeq(void);
void setKeyByLink(client *c, redisDb *db, robj *key, robj **valref, int flags, dictEntryLink *link);
robj *dbRandomKey(redisDb *db);
int dbGenericDelete(redisDb *db, robj *key, int async, int flags);
int dbSyncDelete(redisDb *db, robj *key);
int dbDelete(redisDb *db, robj *key);
int dbDeleteSkipKeysizesUpdate(redisDb *db, robj *key);
kvobj *dbUnshareStringValue(redisDb *db, robj *key, kvobj *o);
kvobj *dbUnshareStringValueByLink(redisDb *db, robj *key, kvobj *kv, dictEntryLink link);

#define FLUSH_TYPE_ALL   0
#define FLUSH_TYPE_DB    1
#define FLUSH_TYPE_SLOTS 2
void replySlotsFlushAndFree(client *c, struct slotRangeArray *slots);
int flushCommandCommon(client *c, int type, int flags, struct slotRangeArray *ranges);
#define EMPTYDB_NO_FLAGS 0      /* No flags. */
#define EMPTYDB_ASYNC (1<<0)    /* Reclaim memory in another thread. */
#define EMPTYDB_NOFUNCTIONS (1<<1) /* Indicate not to flush the functions. */
long long emptyData(int dbnum, int flags, void(callback)(dict*));
long long emptyDbStructure(redisDb *dbarray, int dbnum, int async, void(callback)(dict*));
void flushAllDataAndResetRDB(int flags);
long long dbTotalServerKeyCount(void);
redisDb *initTempDb(void);
void discardTempDb(redisDb *tempDb);
void ensureLogicalDbInitialized(int id);
void ensureTempDbInitialized(redisDb *db);

int selectDb(client *c, int id);
void keyModified(client *c, redisDb *db, robj *key, robj *val, int signal);
void signalFlushedDb(int dbid, int async, struct slotRangeArray *slots);
void scanGenericCommand(client *c, robj *o, unsigned long long cursor);
int parseScanCursorOrReply(client *c, robj *o, unsigned long long *cursor);
int dbAsyncDelete(redisDb *db, robj *key);
void emptyDbAsync(redisDb *db);
void streamMoveIdmpKeys(dict *src, dict *dst, int slot);
void emptyDbDataAsync(kvstore *keys, kvstore *expires, ebuckets hexpires, dict *stream_idmp_keys);
size_t lazyfreeGetPendingObjectsCount(void);
size_t lazyfreeGetFreedObjectsCount(void);
void lazyfreeResetStats(void);
void freeObjAsync(robj *key, robj *obj, int dbid);
void freeReplicationBacklogRefMemAsync(list *blocks, rax *index);

/* API to get key arguments from commands */
#define GET_KEYSPEC_DEFAULT 0
#define GET_KEYSPEC_INCLUDE_NOT_KEYS (1<<0) /* Consider 'fake' keys as keys */
#define GET_KEYSPEC_RETURN_PARTIAL (1<<1) /* Return all keys that can be found */

int getKeysFromCommandWithSpecs(struct redisCommand *cmd, robj **argv, int argc, int search_flags, getKeysResult *result);
keyReference *getKeysPrepareResult(getKeysResult *result, int numkeys);
int getKeysFromCommand(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);
int getSlotFromCommand(struct redisCommand *cmd, robj **argv, int argc);
int doesCommandHaveKeys(struct redisCommand *cmd);
int getChannelsFromCommand(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);
int doesCommandHaveChannelsWithFlags(struct redisCommand *cmd, int flags);
/* Free the result of getKeysFromCommand. Inline (ee451 v14, teardown shave): this runs on
 * every command teardown (freePendingCommand / reclaimPendingCommand), where the common case
 * is "nothing to free" — either keys was never prepared (NULL: argc==0 / read_error /
 * non-preprocessed paths; the out-of-line version paid a zfree(NULL) call for it) or keys
 * points at the inline keysbuf. Folds the cross-TU call into one predicted-not-taken branch;
 * only the rare heap-keys case (> MAX_KEYS_BUFFER) reaches zfree. */
static inline void getKeysFreeResult(getKeysResult *result) {
    if (result && result->keys && result->keys != result->keysbuf)
        zfree(result->keys);
}
int extractKeysAndSlot(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result, int *slot);
int sintercardGetKeys(struct redisCommand *cmd,robj **argv, int argc, getKeysResult *result);
int zunionInterDiffGetKeys(struct redisCommand *cmd,robj **argv, int argc, getKeysResult *result);
int zunionInterDiffStoreGetKeys(struct redisCommand *cmd,robj **argv, int argc, getKeysResult *result);
int evalGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);
int functionGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);
int sortGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);
int sortROGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);
int migrateGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);
int georadiusGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);
int xreadGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);
int lmpopGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);
int blmpopGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);
int zmpopGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);
int bzmpopGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);
int setGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);
int delexGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);
int bitfieldGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result);

unsigned short crc16(const char *buf, int len);

/* Sentinel */
void initSentinelConfig(void);
void initSentinel(void);
void sentinelTimer(void);
const char *sentinelHandleConfiguration(char **argv, int argc);
void queueSentinelConfig(sds *argv, int argc, int linenum, sds line);
void loadSentinelConfigFromQueue(void);
void sentinelIsRunning(void);
void sentinelCheckConfigFile(void);
void sentinelCommand(client *c);
void sentinelInfoCommand(client *c);
void sentinelPublishCommand(client *c);
void sentinelRoleCommand(client *c);

/* redis-check-rdb & aof */
int redis_check_rdb(char *rdbfilename, FILE *fp);
int redis_check_rdb_main(int argc, char **argv, FILE *fp);
int redis_check_aof_main(int argc, char **argv);

/* Scripting */
void scriptingInit(int setup);
int ldbRemoveChild(pid_t pid);
void ldbKillForkedSessions(void);
int ldbPendingChildren(void);
void luaLdbLineHook(lua_State *lua, lua_Debug *ar);
void freeLuaScriptsSync(dict *lua_scripts, list *lua_scripts_lru_list, lua_State *lua);
void freeLuaScriptsAsync(dict *lua_scripts, list *lua_scripts_lru_list, lua_State *lua);
void freeFunctionsAsync(functionsLibCtx *functions_lib_ctx, dict *engines);
int ldbIsEnabled(void);
void ldbLog(sds entry);
void ldbLogRedisReply(char *reply);
void sha1hex(char *digest, char *script, size_t len);
unsigned long evalScriptsMemoryVM(void);
dict* evalScriptsDict(void);
unsigned long evalScriptsMemoryEngine(void);
uint64_t evalGetCommandFlags(client *c, uint64_t orig_flags);
uint64_t fcallGetCommandFlags(client *c, uint64_t orig_flags);
int isInsideYieldingLongCommand(void);

typedef struct luaScript {
    uint64_t flags;
    robj *body;
    listNode *node;  /* list node in lua_scripts_lru_list list. */
} luaScript;
/* Cache of recently used small arguments to avoid malloc calls. */
#define LUA_CMD_OBJCACHE_SIZE 32
#define LUA_CMD_OBJCACHE_MAX_LEN 64

/* Blocked clients API */
void processUnblockedClients(void);
void initClientBlockingState(client *c);
void freeClientBlockingState(client *c);
void blockClient(client *c, int btype);
void unblockClient(client *c, int queue_for_reprocessing);
void unblockClientOnTimeout(client *c);
void unblockClientOnError(client *c, const char *err_str);
void queueClientForReprocessing(client *c);
int blockedClientMayTimeout(client *c);
void replyToBlockedClientTimedOut(client *c);
int getTimeoutFromObjectOrReply(client *c, robj *object, mstime_t *timeout, int unit);
void disconnectAllBlockedClients(void);
void handleClientsBlockedOnKeys(void);
void signalKeyAsReady(redisDb *db, robj *key, int type);
void blockForKeys(client *c, int btype, robj **keys, int numkeys, mstime_t timeout, int unblock_on_nokey);
void blockClientShutdown(client *c);
void blockPostponeClient(client *c);
void blockPostponeClientWithType(client *c, int btype);
void blockForReplication(client *c, mstime_t timeout, long long offset, long numreplicas);
void blockForAofFsync(client *c, mstime_t timeout, long long offset, int numlocal, long numreplicas);
void signalDeletedKeyAsReady(redisDb *db, robj *key, int type);
void updateStatsOnUnblock(client *c, long blocked_us, long reply_us, int had_errors);
void scanDatabaseForDeletedKeys(redisDb *emptied, redisDb *replaced_with, struct slotRangeArray *slots);
void totalNumberOfStatefulKeys(unsigned long *blocking_keys, unsigned long *bloking_keys_on_nokey, unsigned long *watched_keys);
void blockedBeforeSleep(void);

/* timeout.c -- Blocked clients timeout and connections timeout. */
void addClientToTimeoutTable(client *c);
void removeClientFromTimeoutTable(client *c);
void handleBlockedClientsTimeout(void);
int clientsCronHandleTimeout(client *c, mstime_t now_ms);

/* t_stream.c -- Handling of stream data structures */
void handleClaimableStreamEntries(void);
void handleExpiredIdmpEntries(void);

/* expire.c -- Handling of expired keys */
void activeExpireCycle(int type);
/* ee451 (bug #42/#50): the SHARDED half of active expiry, for whole keys AND hash fields.
 * activeExpireCycle()/activeSubexpiresCycle() above walk server.db, which is the empty decoy under
 * sharding; this one is run BY a worker, on its OWN bucket range of the real node db, at the
 * cadence server.tomo_expire_gen publishes. See expire.c for the full rationale (why not on main,
 * why not via activeExpireCycleTryExpire, and why the hash-field half takes the whole node's
 * worker-lock set rather than just the owner's). */
void exActiveExpireCycle(exThread *worker);
void expireSlaveKeys(void);
void rememberSlaveKeyWithExpire(redisDb *db, sds key);
void flushSlaveKeysWithExpireList(void);
size_t getSlaveKeyWithExpireCount(void);
uint64_t activeSubexpires(redisDb *db, int slot, uint32_t maxFieldsToExpire);

/* evict.c -- maxmemory handling and LRU eviction. */
void evictionPoolAlloc(void);
#define LFU_INIT_VAL 5
unsigned long LFUGetTimeInMinutes(void);
uint8_t LFULogIncr(uint8_t value);
unsigned long LFUDecrAndReturn(robj *o);
#define EVICT_OK 0
#define EVICT_RUNNING 1
#define EVICT_FAIL 2
int performEvictions(void);
void startEvictionTimeProc(void);

/* Keys hashing / comparison functions for dict.c hash tables. */
uint64_t dictSdsHash(const void *key);
uint64_t dictPtrHash(const void *key);
uint64_t dictSdsCaseHash(const void *key);
size_t dictSdsKeyLen(dict *d, const void *key);
int dictSdsKeyCompare(dictCmpCache *cache, const void *key1, const void *key2);
int dictSdsKeyCaseCompare(dictCmpCache *cache, const void *key1, const void *key2);
void dictSdsDestructor(dict *d, void *val);
void dictListDestructor(dict *d, void *val);
void *dictSdsDup(dict *d, const void *key);

/* Git SHA1 */
char *redisGitSHA1(void);
char *redisGitDirty(void);
uint64_t redisBuildId(void);
const char *redisBuildIdRaw(void);
char *redisBuildIdString(void);

/* XXH3 hash of a string as hex string */
sds stringDigest(robj *o);
int validateHexDigest(client *c, const sds digest);

/* Hotkey tracking */
hotkeyStats *hotkeyStatsCreate(int count, int duration, int sample_ratio,
                               struct slotRangeArray *slots, uint64_t tracked_metrics);
void hotkeyStatsRelease(hotkeyStats *hotkeys);
void hotkeyStatsPreCurrentCmd(hotkeyStats *hotkeys, client *c);
void hotkeyStatsUpdateCurrentCmd(hotkeyStats *hotkeys, hotkeyMetrics metrics);
void hotkeyStatsPostCurrentCmd(hotkeyStats *hotkeys);
size_t hotkeysGetMemoryUsage(hotkeyStats *hotkeys);

/* Commands prototypes */
void authCommand(client *c);
void pingCommand(client *c);
void echoCommand(client *c);
void commandCommand(client *c);
void commandCountCommand(client *c);
void commandListCommand(client *c);
void commandInfoCommand(client *c);
void commandGetKeysCommand(client *c);
void commandGetKeysAndFlagsCommand(client *c);
void commandHelpCommand(client *c);
void commandDocsCommand(client *c);
void setCommand(client *c);
void setnxCommand(client *c);
void setexCommand(client *c);
void psetexCommand(client *c);
void getCommand(client *c);
void getexCommand(client *c);
void getdelCommand(client *c);
void delCommand(client *c);
void delexCommand(client *c);
void unlinkCommand(client *c);
void existsCommand(client *c);
void setbitCommand(client *c);
void getbitCommand(client *c);
void bitfieldCommand(client *c);
void bitfieldroCommand(client *c);
void setrangeCommand(client *c);
void getrangeCommand(client *c);
void incrCommand(client *c);
void decrCommand(client *c);
void incrbyCommand(client *c);
void decrbyCommand(client *c);
void incrbyfloatCommand(client *c);
void selectCommand(client *c);
void swapdbCommand(client *c);
void randomkeyCommand(client *c);
void keysCommand(client *c);
void scanCommand(client *c);
void dbsizeCommand(client *c);
void lastsaveCommand(client *c);
void saveCommand(client *c);
void bgsaveCommand(client *c);
void bgrewriteaofCommand(client *c);
void shutdownCommand(client *c);
void slowlogCommand(client *c);
void moveCommand(client *c);
void copyCommand(client *c);
void renameCommand(client *c);
void renamenxCommand(client *c);
void lpushCommand(client *c);
void rpushCommand(client *c);
void lpushxCommand(client *c);
void rpushxCommand(client *c);
void linsertCommand(client *c);
void lpopCommand(client *c);
void rpopCommand(client *c);
void lmpopCommand(client *c);
void llenCommand(client *c);
void lindexCommand(client *c);
void lrangeCommand(client *c);
void ltrimCommand(client *c);
void typeCommand(client *c);
void lsetCommand(client *c);
void saddCommand(client *c);
void sremCommand(client *c);
void smoveCommand(client *c);
void sismemberCommand(client *c);
void smismemberCommand(client *c);
void scardCommand(client *c);
void spopCommand(client *c);
void srandmemberCommand(client *c);
void sinterCommand(client *c);
void smembersCommand(client *c);
void sinterCardCommand(client *c);
void sinterstoreCommand(client *c);
void sunionCommand(client *c);
void sunionstoreCommand(client *c);
void sdiffCommand(client *c);
void sdiffstoreCommand(client *c);
void sscanCommand(client *c);
void syncCommand(client *c);
void flushdbCommand(client *c);
void flushallCommand(client *c);
void trimslotsCommand(client *c);
void sortCommand(client *c);
void sortroCommand(client *c);
robj *sortStoreResultObject(client *c);
struct sortXShardCtx *sortXShardPrepare(client *c, int readonly);
int sortXShardNeedsBy(const struct sortXShardCtx *ctx);
int sortXShardBuildByDeref(struct sortXShardCtx *ctx, robj ***keys, sds **fields);
int sortXShardApplyBy(struct sortXShardCtx *ctx, sds *values);
int sortXShardBuildGetDeref(struct sortXShardCtx *ctx, robj ***keys, sds **fields);
void sortXShardApplyGet(struct sortXShardCtx *ctx, sds *values);
int sortXShardHasStore(const struct sortXShardCtx *ctx);
unsigned int sortXShardOutputLen(const struct sortXShardCtx *ctx);
robj *sortXShardStoreResultObject(const struct sortXShardCtx *ctx);
void sortXShardReply(client *c, const struct sortXShardCtx *ctx);
void sortXShardFree(struct sortXShardCtx *ctx);
void lremCommand(client *c);
void lposCommand(client *c);
void rpoplpushCommand(client *c);
void lmoveCommand(client *c);
void infoCommand(client *c);
void mgetCommand(client *c);
void monitorCommand(client *c);
void expireCommand(client *c);
void expireatCommand(client *c);
void pexpireCommand(client *c);
void pexpireatCommand(client *c);
void getsetCommand(client *c);
void ttlCommand(client *c);
void touchCommand(client *c);
void pttlCommand(client *c);
void expiretimeCommand(client *c);
void pexpiretimeCommand(client *c);
void persistCommand(client *c);
void replicaofCommand(client *c);
void roleCommand(client *c);
extern int tm_flip_trace;
extern int tomo_disp_window_forced_zero;
extern _Atomic int tomo_disp_window[TOMO_IO_THREADS_MAX + 1];
extern int tomo_rord_mask;
extern int tomo_rord_diag;
extern int tomo_rord_unsafe_diag;
extern int tm_rord_trace;
void debugCommand(client *c);
void msetCommand(client *c);
void msetnxCommand(client *c);
void msetexCommand(client *c);
void zaddCommand(client *c);
void zincrbyCommand(client *c);
void zrangeCommand(client *c);
void zrangebyscoreCommand(client *c);
void zrevrangebyscoreCommand(client *c);
void zrangebylexCommand(client *c);
void zrevrangebylexCommand(client *c);
void zcountCommand(client *c);
void zlexcountCommand(client *c);
void zrevrangeCommand(client *c);
void zcardCommand(client *c);
void zremCommand(client *c);
void zscoreCommand(client *c);
void zmscoreCommand(client *c);
void zremrangebyscoreCommand(client *c);
void zremrangebylexCommand(client *c);
void zpopminCommand(client *c);
void zpopmaxCommand(client *c);
void zmpopCommand(client *c);
void bzpopminCommand(client *c);
void bzpopmaxCommand(client *c);
void bzmpopCommand(client *c);
void zrandmemberCommand(client *c);
void multiCommand(client *c);
void execCommand(client *c);
void discardCommand(client *c);
void blpopCommand(client *c);
void brpopCommand(client *c);
void blmpopCommand(client *c);
void brpoplpushCommand(client *c);
void blmoveCommand(client *c);
void appendCommand(client *c);
void strlenCommand(client *c);
void zrankCommand(client *c);
void zrevrankCommand(client *c);
void hsetCommand(client *c);
void hsetexCommand(client *c);
void hpexpireCommand(client *c);
void hexpireCommand(client *c);
void hpexpireatCommand(client *c);
void hexpireatCommand(client *c);
void httlCommand(client *c);
void hpttlCommand(client *c);
void hexpiretimeCommand(client *c);
void hpexpiretimeCommand(client *c);
void hpersistCommand(client *c);
void hsetnxCommand(client *c);
void hgetCommand(client *c);
void hmgetCommand(client *c);
void hgetexCommand(client *c);
void hgetdelCommand(client *c);
void hdelCommand(client *c);
void hlenCommand(client *c);
void hstrlenCommand(client *c);
void zremrangebyrankCommand(client *c);
void zunionstoreCommand(client *c);
void zinterstoreCommand(client *c);
void zdiffstoreCommand(client *c);
void zunionCommand(client *c);
void zinterCommand(client *c);
void zinterCardCommand(client *c);
void zrangestoreCommand(client *c);
robj *zrangestoreResultObject(client *c);
void zdiffCommand(client *c);
void zscanCommand(client *c);
void hkeysCommand(client *c);
void hvalsCommand(client *c);
void hgetallCommand(client *c);
void hexistsCommand(client *c);
void hscanCommand(client *c);
void hrandfieldCommand(client *c);
void configSetCommand(client *c);
void configGetCommand(client *c);
void configResetStatCommand(client *c);
void configRewriteCommand(client *c);
void configHelpCommand(client *c);
int configExists(const sds name);
void hincrbyCommand(client *c);
void hincrbyfloatCommand(client *c);
void subscribeCommand(client *c);
void unsubscribeCommand(client *c);
void psubscribeCommand(client *c);
void punsubscribeCommand(client *c);
void publishCommand(client *c);
void pubsubCommand(client *c);
void spublishCommand(client *c);
void ssubscribeCommand(client *c);
void sunsubscribeCommand(client *c);
void watchCommand(client *c);
void unwatchCommand(client *c);
void clusterCommand(client *c);
void clusterSlotStatsCommand(client *c);
void restoreCommand(client *c);
void migrateCommand(client *c);
void askingCommand(client *c);
void readonlyCommand(client *c);
void readwriteCommand(client *c);
void sflushCommand(client *c);
int verifyDumpPayload(unsigned char *p, size_t len, uint16_t *rdbver_ptr);
void dumpCommand(client *c);
void clientCommand(client *c);
void helloCommand(client *c);
void clientSetinfoCommand(client *c);
void evalCommand(client *c);
void evalRoCommand(client *c);
void evalShaCommand(client *c);
void evalShaRoCommand(client *c);
void scriptCommand(client *c);
void fcallCommand(client *c);
void fcallroCommand(client *c);
void functionLoadCommand(client *c);
void functionDeleteCommand(client *c);
void functionKillCommand(client *c);
void functionStatsCommand(client *c);
void functionListCommand(client *c);
void functionHelpCommand(client *c);
void functionFlushCommand(client *c);
void functionRestoreCommand(client *c);
void functionDumpCommand(client *c);
void timeCommand(client *c);
void bitopCommand(client *c);
void bitcountCommand(client *c);
void bitposCommand(client *c);
void replconfCommand(client *c);
void waitCommand(client *c);
void waitaofCommand(client *c);
void georadiusbymemberCommand(client *c);
void georadiusbymemberroCommand(client *c);
void georadiusCommand(client *c);
void georadiusroCommand(client *c);
void geoaddCommand(client *c);
void geohashCommand(client *c);
void geoposCommand(client *c);
void geodistCommand(client *c);
void geosearchCommand(client *c);
void geosearchstoreCommand(client *c);
robj *geoStoreResultObject(client *c);
void pfselftestCommand(client *c);
void pfaddCommand(client *c);
void pfcountCommand(client *c);
void pfmergeCommand(client *c);
void pfdebugCommand(client *c);
void latencyCommand(client *c);
void moduleCommand(client *c);
void securityWarningCommand(client *c);
void xaddCommand(client *c);
void xrangeCommand(client *c);
void xrevrangeCommand(client *c);
void xlenCommand(client *c);
void xreadCommand(client *c);
int xreadCommandReadOne(client *c, robj *key, robj *idarg, long long count);
void xgroupCommand(client *c);
void xsetidCommand(client *c);
void xidmprecordCommand(client *c);
void xackCommand(client *c);
void xackdelCommand(client *c);
void xpendingCommand(client *c);
void xclaimCommand(client *c);
void xautoclaimCommand(client *c);
void xinfoCommand(client *c);
void xcfgsetCommand(client *c);
void xdelCommand(client *c);
void xdelexCommand(client *c);
void xtrimCommand(client *c);
void lolwutCommand(client *c);
void aclCommand(client *c);
void hotkeysCommand(client *c);
void lcsCommand(client *c);
void lcsCommandGeneric(client *c, robj *obja, robj *objb, robj **argv, int argc);
void quitCommand(client *c);
void resetCommand(client *c);
void failoverCommand(client *c);
void digestCommand(client *c);

#if defined(__GNUC__)
void *calloc(size_t count, size_t size) __attribute__ ((deprecated));
void free(void *ptr) __attribute__ ((deprecated));
void *malloc(size_t size) __attribute__ ((deprecated));
void *realloc(void *ptr, size_t size) __attribute__ ((deprecated));
#endif

/* Debugging stuff */
void _serverAssertWithInfo(const client *c, const robj *o, const char *estr, const char *file, int line);
void _serverAssert(const char *estr, const char *file, int line);
#ifdef __GNUC__
void _serverPanic(const char *file, int line, const char *msg, ...)
    __attribute__ ((format (printf, 3, 4)));
#else
void _serverPanic(const char *file, int line, const char *msg, ...);
#endif
void serverLogObjectDebugInfo(const robj *o);
void setupDebugSigHandlers(void);
void setupSigSegvHandler(void);
void removeSigSegvHandlers(void);
const char *getSafeInfoString(const char *s, size_t len, char **tmp);
dict *genInfoSectionDict(robj **argv, int argc, char **defaults, int *out_all, int *out_everything);
void releaseInfoSectionDict(dict *sec);
sds genRedisInfoString(dict *section_dict, int all_sections, int everything);
sds genModulesInfoString(sds info);
void applyWatchdogPeriod(void);
void watchdogScheduleSignal(int period);
void serverLogHexDump(int level, char *descr, void *value, size_t len);
int memtest_preserving_test(unsigned long *m, size_t bytes, int passes);
void mixDigest(unsigned char *digest, const void *ptr, size_t len);
void xorDigest(unsigned char *digest, const void *ptr, size_t len);
sds catSubCommandFullname(const char *parent_name, const char *sub_name);
void commandAddSubcommand(struct redisCommand *parent, struct redisCommand *subcommand, const char *declared_name);
void debugDelay(int usec);
void killThreads(void);
void makeThreadKillable(void);
void swapMainDbWithTempDb(redisDb *tempDb);
sds getVersion(void);
void debugPauseProcess(void);

//ee451 new
void initIOThreads(void);

/* Worker thread functions */
void exQueueInit(exQueue *q);
int exQueuePush(exQueue *q, client *c);
int exQueuePopBatch(exQueue *q, client **out, int max);
void flushExQueues(void);   /* ee451 (S4): publish staged pushes for this iotid at producer boundaries */
void migUnparkClient(client *c);  /* ee451 (H2 handover): drop a dying client from the range-hold park list */
void freebackPush(int ex_id, robj *obj);   /* ee451 (S8): IO->worker value free-back */
void queueToWorker(client *c, int ex_id);
void initExThreads(void);
void handleWorkerReplies(void);
int canDispatchToWorker(client *c);
int getWorkerForCommand(client *c);
int exIndexForKey(const void *keyptr, size_t len);  /* ee451: key->shard (dispatch + RDB load) */
int tomoCommandSingleWorker(struct redisCommand *cmd, robj **argv, int argc, int hold_migration);
int tomoKeyBucket(const void *keyptr, size_t len);  /* ee451 (S0.2a): key->bucket == kvstore dict index (db.c getKeySlot) */
client *createFakeClient(client *parent);               /* ee451 (v7): for cross-shard sub-fakes */
client *createCoreFakeClient(client *parent);           /* 320-byte plain GET/SET ring fake */
client *promoteFakeClient(client *c);                   /* idle ring-slot promotion */
client *createPooledFakeClient(client *parent);         /* ee451 (v11): pooled cross-shard sub-fake */
void freePooledFakeClient(client *c);                   /* ee451 (v11): return sub-fake to per-iotid pool */
void freeFakeClient(client *c);
extern _Atomic unsigned long long tomo_fake_core_allocs;
extern _Atomic unsigned long long tomo_fake_tail_promotions;
void *polyThreadMain(void *arg);   /* ee451 (thread-modes v1, step 2): unified mode-dispatching main (arg = polyThreadCtx*) */
/* ee451 (thread-modes v1.6): connection migration. */
extern tmMigMailbox tm_mig_mbox[TOMO_IO_THREADS_MAX + 1];  /* one per io-capable slot (0..io_threads); main=0 unused */
void tmMigInitSlot(int io_slot, struct aeEventLoop *el);  /* build this slot's mailbox + register its wakeup fd on el */
void tmMigServiceOut(void);                           /* source side: start + complete pending migrations (beforeSleepIO) */
void tmMigDrainInbox(void);                           /* dest side: adopt incoming migrated clients (beforeSleepIO) */
void tmMigForgetOnFree(client *c);                    /* freeClient hook: drop a dying client from migrating_out */
int tomoGrowFront(const char **err);
int tomoGrowBack(const char **err);
void tmFlipTick(void);
int tomoMigrateTest(int val, const char **err);       /* control plane: DEBUG TOMO-MODESHIFT 5 (io-exit) / 6 (rebalance) */
int tomoNodeFlipTest(int val, const char **err);      /* per-node flip: DEBUG TOMO-MODESHIFT 70+n / 80+n */
void tomoWkrLockPub(int w);                            /* per-worker mcmd lock (db.c RANDOMKEY expire) */
void tomoWkrUnlockPub(int w);
/* tomokv-pin-io / tomokv-pin-ex spec parser. Grammar (whitespace-separated tokens):
 *     node<N>=<cpu>[,<cpu>|<lo>-<hi>]...        e.g. "node0=0-3 node1=8,9,10,11"
 * Returns 1 on success. On failure returns 0 and points *err at a static buffer naming the
 * offending token. `out` (may be NULL when only validating) is filled with the cpu ids:
 * out[node*TOMO_EX_THREADS_MAX + i], and out_n[node] gets that node's cpu count. */
int tomoPinSpecParse(const char *spec, const char *knob, int *out, int *out_n, const char **err);
/* Log redaction helpers: return "*redacted*" when hide-user-data-from-log is on. */
static inline const char *redactLogCstr(const char *s) {
    return server.hide_user_data_from_log ? "*redacted*" : (s ? s : "(null)");
}

/* Use macro for checking log level to avoid evaluating arguments in cases log
 * should be ignored due to low level. */
#define serverLog(level, ...) do {\
        if (((level)&0xff) < server.verbosity) break;\
        _serverLog(level, __VA_ARGS__);\
    } while(0)

#define redisDebug(fmt, ...) \
    printf("DEBUG %s:%d > " fmt "\n", __FILE__, __LINE__, __VA_ARGS__)
#define redisDebugMark() \
    printf("-- MARK %s:%d --\n", __FILE__, __LINE__)

int iAmMaster(void);

#define STRINGIFY_(x) #x
#define STRINGIFY(x) STRINGIFY_(x)

#endif
