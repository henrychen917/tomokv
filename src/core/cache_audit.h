// Build-only cumulative cache-layout experiment. No runtime knob or allocation.
#pragma once
#ifndef TOMO_CACHE_AUDIT_ARM
#define TOMO_CACHE_AUDIT_ARM 5
#endif
#if TOMO_CACHE_AUDIT_ARM < 0 || TOMO_CACHE_AUDIT_ARM > 5
#error "TOMO_CACHE_AUDIT_ARM must be in [0, 5] (0 = current reference)"
#endif
