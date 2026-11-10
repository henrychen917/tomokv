# Control plane

TomoKV separates ownership changes from ordinary command execution. The
[architecture overview](../architecture.md) describes the full request path;
the [configuration reference](../configuration.md) lists operator controls.

## Ownership and load balancing

Each shard has one executor owner. `key-lb` and `client-lb` default to `1` and
independently enable shard and connection balancing. The planner uses sustained
work measurements to propose a move at a fixed IO/executor split. Ownership
changes drain the affected participants before publication; stale dispatched
tasks are forwarded to the current owner.

A shard transfer must adopt every owner-local structure in the same critical
section. `Server::adopt_shard_owner_state` rebinds retirement and notification
state before the new owner becomes visible. See
[server.h](../../src/core/server.h), [weighted_lb.h](../../src/core/weighted_lb.h),
and [lbplanner.cc](../../src/core/lbplanner.cc).

## Changing the role split

`flip-auto` defaults to `0`. In split mode the automatic controller estimates
demand, compares expected benefit with movement cost, and verifies or reverts
a role change. The explicit `FLIP` command exposes the operator-controlled path.
This verification belongs to the role controller; shard/client balancing does
not use the same verify/revert loop. The implementation is in
[flipctl.cc](../../src/core/flipctl.cc) and
[flip_policy.h](../../src/core/flip_policy.h).

## Fused scheduling

The boot-only `reorder` switch defaults to `0` and is resolved to `0` in split
mode. In fused mode it selects the scheduler in
[reorder.cc](../../src/core/reorder.cc). Only a connection's eligible head can
be selected. The scheduler ranks short and long tasks while tracking shadows,
and an oldest-task quota bounds delay in selection picks. This is not a
wall-clock latency guarantee. Admission rejects oversized batches.

Connection reply order is preserved independently by the
[reorder buffer](../../src/net/rob.h), including when commands execute on
different owners.
