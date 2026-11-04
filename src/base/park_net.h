// Missed-wake safety net of every parked worker loop: the IO, fused and executor parks on both
// network engines, and the persistence pumps' waits. A parked thread wakes for a CQE (epoll: its
// mailbox eventfd), its database or shutdown fd, or this timeout. The timeout is NOT the liveness
// guarantee -- every producer owes its consumer a wake -- it only bounds the damage of a missed
// one, which is why a missed wake shows up as a <= 50 ms blip that no gate threshold can see.
//
// TEST-ONLY DIAGNOSTIC, never a runtime knob and never defined by a production build:
//   make park-net-arm            -> build/park-net/tomokv with -DTOMO_PARK_NET_MS=$(PARK_NET_MS)
// stretches the net (default 2000 ms) so a missed wake becomes a deterministic multi-second stall
// that a gate row can assert. In that build the client-cron beat (1000/hz) no longer caps an IO
// park either; the cron still runs at the first pass after its deadline. WAIT, accept-retry and
// TRACKING ON deadlines keep capping the park. TOMO_MDBQSBR_LIVE_PARK (the mdbqsbr live twins)
// is the 5400 ms instance of the same option.
#pragma once

#if defined(TOMO_MDBQSBR_LIVE_PARK) && !defined(TOMO_PARK_NET_MS)
// 2 x 3 x (2 x 50 ms x (8 + 1)): beyond the namespace watchdog at the twins' gate geometry.
#define TOMO_PARK_NET_MS 5400
#endif

namespace tomo {
#ifdef TOMO_PARK_NET_MS
inline constexpr unsigned kParkNetMs = TOMO_PARK_NET_MS;
inline constexpr bool kParkNetStretched = true;
static_assert(TOMO_PARK_NET_MS > 50, "the diagnostic only ever stretches the net");
#else
inline constexpr unsigned kParkNetMs = 50;  // == Ring::kWaitTimeoutMs (asserted in uring.h)
inline constexpr bool kParkNetStretched = false;
#endif
}  // namespace tomo
