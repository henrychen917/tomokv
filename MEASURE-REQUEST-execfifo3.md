# Remove FIFO's incidental plain-command parser cost

## execfifo3

PRE: `e32b04a44`. FIFO source: `2461efbbb` (`cx-execfifo2`), with its frozen
POST executable retained unchanged. Lane: `cx-execfifo3`, CPUs 96–111,
ports 20600–20699, `LC_ALL=C` on every correctness/oracle boot. No push.

The production diff changes **three GCC inlining-budget values in Makefile**.
FIFO/C1 increases the initial IPA size of both fused units by 2,031
instructions. Their old ceilings caused ordinary RESP length parsing to be
outlined. The multi-database main unit grows by 1,646 and loses inlining of
`Client::nothing_to_write` in split parsing (+44 instructions and three
explicit memory operands per batch of 32). The corrected ceilings restore
the former absolute allowances; its linked trial also returns exactly to PRE.
Every FIFO source predicate, queue operation, hand-off, boundary and ownership
rule remains unchanged. No field, allocation, runtime branch or knob is added.

The original owner-command scopes missed this cost because they start after
parsing. In the db0 linked parser at batch 32:

| Cell | PRE instructions | FIFO | POST trial | PRE explicit memory operands | FIFO | POST trial |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1s SET, read-local 0 | 23,669 | 25,045 | 23,669 | 7,784 | 8,488 | 7,784 |
| 1s SET, read-local 1 | 27,427 | 28,803 | 27,427 | 8,939 | 9,643 | 8,939 |
| 1s INCR, read-local 0 | 21,205 | 22,485 | 21,205 | 7,272 | 7,880 | 7,272 |
| 1s INCR, read-local 1 | 24,963 | 26,243 | 24,963 | 8,427 | 9,035 | 8,427 |
| 2s SET | 20,646 | 20,646 | 20,646 | 6,173 | 6,173 | 6,173 |

These are finite serverless instruction/access counts, **not throughput**.
The [source/access audit](docs/execfifo3/audit.md) explains why the suspected
unconditional FIFO waiter-state access is absent: the existing Shard+8 gate
short-circuits before the registry, in both ordinary and read-local writes.
Final-image scope, counter and correctness receipts are being collected.

### Gate accounting

**DQ=0, DF=0 relative to execfifo2.** No gate row is added, removed or moved.
The inherited FIFO/C1 rows still precede the quick-tier exit; the inherited
request remains **992 quick / 1009 full**, versus the untouched source
constants 977/994. Only the maintainer changes those constants.

### Artifacts and control semantics

Artifacts live in `build/execfifo3/`: `PRE`, `FIFO`, `POST`, `POST-layout`,
and `PAD-A`. [SHA256SUMS](docs/execfifo3/SHA256SUMS) and the
[artifact manifest](docs/execfifo3/arms.json) bind the exact images.

PAD-A is **type A, behaviour twin**: PRE behaviour in the identical combined
POST-layout image. The control pair has identical ELF sections, symbols and
function addresses; only the entry jump changes. Its exact twin is
`POST-layout`, not the smaller release `POST`. The entry chooses different
PRE/POST function bodies within that common image, so this does not hold
their executed instruction addresses fixed. The release comparison remains
necessary; no stronger code-placement control is claimed.

### Maintainer measurement request — NOT RUN here

Use the gate's instrument on the quiet box, identical allocation and offered
load for every arm, three blocks per comparison. Retain individual blocks,
cycles/op, instructions/op and IPC.

1. Run the generic cells against PRE for both FIFO and POST:
   `h05,h06,p8g,p8s,d1g_l0,d1s_l0,d32s_l1,d8s_l1,d32g_l1,x9_32_l1,x9_32_l0,m8g_l0,v1g_l0,d128g_l0`,
   plus the four `cc_2s_get/set_p1/p32` nulls. Prioritize **d32s_l1** and
   **x9_32_l0**. Run POST-layout versus PAD-A on the same cells. Main commands
   must meet the owner's zero-regression rule against PRE.
2. Retain the 64-connection EXEC merit (`exec-merit.py --cells all --blocks 3
   --secs 20 --threads 16 --conns 64`, pipeline 4), both modes and atomic
   settings, hot and uncontended. Compare POST with both PRE and FIFO;
   retain the four plain-writer clients' completions and share.
3. Retain execfifo2's same-owner/same-shard/cross-owner depth sweep and
   contended-script merit, using the same cells and harness versions as its
   request. POST must retain FIFO's measured advantages; instruction savings
   alone do not decide this.

All throughput cells, load generators and full `iteration` are **NOT RUN**:
they remain maintainer work. Correctness uses only selected gate jobs, the
Redis 7.4 oracle, differential suites and serverless fixtures.
