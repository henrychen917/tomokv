# Runtime bind and port: handoff to fliplisten

Redis 7.4 validates CONFIG SET bind/port, creates replacement listeners and returns
an error without changing the live configuration if rebinding fails. Established
connections survive a successful change. TomoKV currently stores both names as
boot-only registry entries. This lane changes network error formatting, not that
listener lifecycle; it implements no runtime bind/port mutation.

The listener ownership extension in fliplisten should supply a transaction with
prepare, commit and abort phases. Prepare opens the entire replacement IPv4
SO_REUSEPORT set using the requested address/port and existing backlog, on the
event engines that will own admission after the commit. Failure closes only the
prepared descriptors, preserves the old accepting set and CONFIG GET values,
and returns the oracle's argument-specific error. Port zero disables TCP without
disabling TLS or AF_UNIX. The owner ruling retaining one IPv4 bind address still
applies; this is not an IPv6 or address-list extension.

Commit must publish one listener generation and the associated CONFIG snapshot
at the ownership cut. Every IO owner acknowledges installation before old
listeners are retired. Pending accepts and existing clients must retain an owner
through the cut; simply closing SO_REUSEPORT listeners loses queued connections
(IO4.3/NT4.4). FLIP and CONFIG must use the same serialized listener transaction,
including rollback, shutdown and engine-specific accept cancellation fences.
No thread may observe the new CONFIG GET value while admission still uses a
partially installed listener generation.

Directed oracle tests should cover changing only port, only bind, both in one
CONFIG SET, disabling/re-enabling TCP, bind failure on an occupied port, invalid
address/port, duplicate parameters, established clients, connections queued at
commit, concurrent FLIP, and shutdown during prepare. Exercise 1s/2s and
epoll/io_uring with the gate's eight-core, 16-shard, 6:2 split geometry. Record
the exact Redis error and unchanged CONFIG GET values on each rejected update.

TLS context reload is a separate cold publication problem: prepare a complete
SSL_CTX, publish it to new handshakes, and retain the old context for existing
connections. Changing tls-port also requires this listener transaction. The
default-cipher fix in netfix does not implement live TLS configuration.
