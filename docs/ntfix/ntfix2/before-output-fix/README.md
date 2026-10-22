# Superseded N3/N4 validation snapshot

The limits corpus and all directed rows passed here. The required epoll infofix
differential then reached its output-rate assertion: input accounting was fixed,
but `total_net_output_bytes` stayed zero. Both plain epoll send paths and the
userspace TLS epoll ciphertext path lacked the update present in io_uring.
The production-unit build and differential coordinator were stopped by their
owned process groups to rebuild after that additional in-place accounting fix.
Their partial runs are retained here, not counted as final passes.

The initial N3 boundary-control fixture used a ten-argument PING, exposing the
separate pre-existing AUTH/arity precedence difference. The final control uses
a valid ten-argument DEL. The N4 unit initially requested a two-byte receive
offer, below production's minimum offer; the final fixture uses kRbufInitial
like the real caller. Assertions were not weakened.
