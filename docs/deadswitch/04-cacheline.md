# 4 — Independent masked-queue cache-line literal: DEAD; canonical value shared

PRE `dab740964` declares both constants as 64. POST includes `exqueue.h` directly,
derives the compatibility name `kMaskedQueueCacheLine` from `tomo::kCacheLine`,
and adds the requested assertion tying the names. The queue's existing slot-size,
ConsumerLine, ProducerLine and Lane assertions still refer to that derived value.
There is now one independent numerical cache-line setting for these queues.
Retaining the alias avoids an unnecessary interface rename; it is not a second
hardware assumption.

`build/deadswitch/04-cacheline` includes the previously proved candidates 1 and 3.
It was rebuilt in both namespaces with unchanged compiler flags. The direct
PRE/POST linked proof shows every loadable section's bytes, address, size and
alignment identical (build-ID excluded); debug ELF bytes differ.
The hot inventory is 1492/1492, and the full inventory is 17078/17078 with
no changed bodies. This full build exercises every emitted queue instantiation
and every static layout assertion. No runtime policy or allocation changes.

`constant-spellings.txt` records the tests/tools grep. Gate rows +0/+0. No PAD.
