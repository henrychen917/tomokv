# Actual cache event mapping

Kernel `7.0.0-30-generic`, audit pinned to CPU 111 with `LC_ALL=C`.
The [commands and return codes](results.json) retain each availability probe.
These probes run only `/bin/true`, not a server or workload.

`perf list --details cache-misses` maps the generic event to
`cpu/event=0x64,umask=0x09/`. The named
`l2_cache_req_stat.ic_dc_miss_in_l2` has exactly the same encoding and describes
instruction/data requests that miss L2. The existing raw `cache-misses:u`
counts therefore remain valid as combined **L2** misses, not LLC misses.
See [generic mapping](cache-alias.txt) and [named mapping](l2-event.txt).

Direct LLC measurements are **NOT RUN**. The exposed PMUs contain no AMD L3
device. `perf stat -e LLC-load-misses:u -- /bin/true` returns 1 with
“The LLC-load-misses:u event is not supported.” The named
`l3_lookup_state.l3_miss` probe returns 129 because no PMU provides that event.
The L3 metric expressions printed by `perf list` do not make their underlying
events available. Raw failure output is retained in
[llc-miss-probe.txt](llc-miss-probe.txt) and
[l3-named-probe.txt](l3-named-probe.txt).

The recorded remote-CCX cache fills, local-CCX fills and L2 exclusive-state
requests are available coherence-related proxies. They do not distinguish
dirty HITM transfers or attribute traffic to a FIFO line. No kernel module,
system PMU setting or other global configuration was changed.
