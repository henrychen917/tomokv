# Multi-key atomicity — torn-read probe (60 s, 6 clients on the same 8 keys)

A torn read = an MGET observing a partial MSET. Redis and TomoKV atomic=on are the zero controls that validate the probe. **Dragonfly tears at 0.74% on v1.39 defaults**; TomoKV's epoch-MVCC knob is torn-free at ~8% read / ~17% write cost, and still out-read Dragonfly by 68% inside this probe.

| configuration | MGETs | torn | rate | MSETs |
|---|---|---|---|---|
| TomoKV atomic=off | 16,194,480 | 3,943,086 | 24.35% | 23,470,592 |
| TomoKV atomic=on | 14,915,296 | 0 | 0.00% | 19,372,144 |
| Dragonfly v1.39 | 8,858,848 | 65,279 | 0.74% | 8,849,728 |
| Redis | 19,113,584 | 0 | 0.00% | 25,084,912 |
