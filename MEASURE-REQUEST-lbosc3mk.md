# lbosc3mk: Makefile output-directory repair

Baseline: `dab7409642bf0a6d125fb5f479e6d190c7636083`.
Implementation: `edd7d9f6dabb2b11e8a0ccd7cf8d1968c4494ca4` on `cx-lbosc3mk`.
Build-system-only change: 89 additive `mkdir -p` recipe lines. All original
Makefile lines, targets, prerequisites, output paths, flags and tool invocations
are unchanged. `src/`, tools, tests and `tests/gate.sh` are untouched.

## Defect and scope

The shell opens `build/lbosc3/unit-pad.log` before starting
`tools/lbosc3_pad.py`. PRE Makefile:697 had no creator for `build/lbosc3/`.
The tool's own receipt-directory creation therefore could not run. The failed
PAD target prevented creation of `build/lbplanner-units`, which made the gate's
existing handoff row fail its readiness check.

POST Makefile:783 creates `build/lbosc3/unit-pad-proof` before the unchanged
command at :784. Recursive `mkdir -p` creates the proof directory, the log's
parent `build/lbosc3/`, and the binary's parent `build/` together.

The audit covers all 703 PRE Makefile lines and all 146 recipe blocks, including
compiler/linker `-o`, generated-source and receipt arguments, redirections,
copies, marker writes and recursive builds. POST has 792 lines.

The ten other compile recipes with no directory-providing prerequisite were:
`build/ktls-keyupdate-unit` (PRE :210), `build/exbatch/PRE/unit.o` (:302),
`build/reorder-unit` (:533), `build/reorder-unit-asan` (:535),
`build/r7shadow-unit` (:573), `build/r7shadow-unit-asan` (:575),
`build/r7shadow-instr` (:579), `build/wbland-clause-unit` (:641),
`build/wbland-db0-clause-unit` (:643), and `build/lbplanner-trace` (:703).
The frozen exbatch fixture still requires its documented external PRE inputs;
this change supplies only its missing output parent.

The remaining 78 additions apply the requested same-recipe/order-only criterion
to outputs previously protected by normal prerequisites or by the tool itself.
They are explicit directory provisioning, not 78 additional reproduced failures.
Nested generator and receipt directories are supplied before their tools run.
The unchanged recipes comprise 41 with existing `mkdir`, seven recursive-build
recipes, one with an order-only directory-providing prerequisite, and eight
execution/cleanup recipes with no output path argument or redirection.

All six shell file-redirection sites were checked; no append redirect or `tee`
exists. The `>>` inside the quoted `sed` replacement is C++ syntax.

| Output | PRE line | POST line | Result |
| --- | ---: | ---: | --- |
| `build/climon-mask-old/src/core/climon_mask.h` | 224 | 235 | Existing preceding `mkdir` covers header and binary; unchanged. |
| `build/multidb2-pad.json` | 383 | 421 | Added parent creation at POST :420. |
| `build/multidb-pad.json` | 385 | 424 | Added parent creation at POST :423. |
| `build/lbplanner-unit-pad.log` | 693 | 778 | Added binary/log/proof parent creation at POST :777. |
| `build/lbplanner-pad.log` | 695 | 781 | Added binary/log/proof parent creation at POST :780. |
| `build/lbosc3/unit-pad.log` | 697 | 784 | Added parent/proof creation at POST :783; reproduced defect. |

## Fresh-worktree proof

All requested proofs passed. Builds used `taskset -c 112-127 make -j16` with
default flags and GNU Make 4.3 / g++ 13.3.0. The Python checks inherited the same
CPU affinity. No quiet-screen refusal occurred. No server, benchmark, gate or
push was run. Other audited targets were reviewed statically, not individually
built or executed.

| Proof | PRE | POST |
| --- | --- | --- |
| Fresh `make build/lbplanner-units` | Exit 2: exact missing-directory failure; no unit marker | Exit 0; unit marker and PAD log/proof present |
| `python3 tests/lbplanner_checks.py` | Not run: required PAD missing | Exit 0; all 14 result rows pass, including nested timing controls and both modes |
| Default `make` | Exit 0 | Exit 0, starting with no `build/` |
| Unmodified `build/tomokv` | 186,412,208 bytes | 186,412,208 bytes; `cmp` exit 0 |

Three detached worktrees were created and removed sequentially at the same
absolute path. Each began with no `build/`. PRE's default build followed its
failed unit build and reused the successfully compiled production objects.
The POST default and unit builds each used a separate freshly created tree.
Reusing the *path*, after removing the previous worktree, preserves the default
compiler's debug compilation-directory strings for the byte comparison. No
objects or directories were carried into either POST tree; no prefix-map flags,
stripping or binary normalization were used.

The following path names abbreviate the actual commands below:

```sh
LBOSC3MK_ROOT=/home/user/Projects/cx-lbosc3mk
LBOSC3MK_FRESH=/home/user/Projects/cx-lbosc3mk/build/lbosc3mk/fresh
LBOSC3MK_EVIDENCE=/home/user/Projects/cx-lbosc3mk/build/lbosc3mk/evidence
```

PRE creation, from the lane root:

```sh
mkdir -p build/lbosc3mk/evidence build/lbosc3mk/pre build/lbosc3mk/post
git worktree add --detach "$LBOSC3MK_FRESH" dab740964
```

Output: `Preparing worktree (detached HEAD dab740964)` and
`HEAD is now at dab740964 Merge lbosc3 (b20d2c9af) into cx-final: gate iteration 519 rows, 0 gating FAIL`.
From that detached tree:

```sh
test ! -e build
taskset -c 112-127 make -j16 build/lbplanner-units > "$LBOSC3MK_EVIDENCE/pre-lbplanner-make.log" 2>&1
```

The freshness check exited 0; make exited 2. Relevant output from the
[complete PRE unit-build log](docs/lbosc3mk/pre-lbplanner-make.log.gz):

```text
python3 tools/lbosc3_pad.py build/lbplanner-unit build/lbosc3-unit-pad build/lbosc3/unit-pad-proof > build/lbosc3/unit-pad.log
/bin/sh: 1: cannot create build/lbosc3/unit-pad.log: Directory nonexistent
make: *** [Makefile:697: build/lbosc3-unit-pad] Error 2
make: *** Waiting for unfinished jobs....
```

Still in the PRE tree:

```sh
test ! -e build/lbosc3 && test ! -e build/lbplanner-units
taskset -c 112-127 make -j16 > "$LBOSC3MK_EVIDENCE/pre-default-make.log" 2>&1
sha256sum build/tomokv
```

Both checks and default make exited 0; the
[complete PRE default-build log](docs/lbosc3mk/pre-default-make.log.gz) records the
unchanged compile/link commands. From the lane root:

```sh
cp build/lbosc3mk/fresh/build/tomokv build/lbosc3mk/pre/tomokv
git -C build/lbosc3mk/fresh status --porcelain=v1
git worktree remove "$LBOSC3MK_FRESH"
git worktree add --detach "$LBOSC3MK_FRESH" edd7d9f6dabb2b11e8a0ccd7cf8d1968c4494ca4
```

Status was empty; removal exited 0. POST creation reported
`Preparing worktree (detached HEAD edd7d9f6d)` and
`HEAD is now at edd7d9f6d Create missing Makefile output directories before writing`.
In the fresh POST default-build tree:

```sh
test ! -e build
taskset -c 112-127 make -j16 > "$LBOSC3MK_EVIDENCE/post-default-make.log" 2>&1
sha256sum build/tomokv
```

Freshness and make both exited 0. The
[complete POST default-build log](docs/lbosc3mk/post-default-make.log.gz) includes
the final link. From the lane root:

```sh
cp build/lbosc3mk/fresh/build/tomokv build/lbosc3mk/post/tomokv
sha256sum build/lbosc3mk/pre/tomokv build/lbosc3mk/post/tomokv
cmp build/lbosc3mk/pre/tomokv build/lbosc3mk/post/tomokv
```

`cmp` exited 0 with no output. SHA-256 pair:

```text
eeb7d524b6b250f0376538fa255605718b15b11283f9fe7e39949d80bb3a4916  build/lbosc3mk/pre/tomokv
eeb7d524b6b250f0376538fa255605718b15b11283f9fe7e39949d80bb3a4916  build/lbosc3mk/post/tomokv
```

The binaries remain at those ignored lane-local paths. From the lane root,
remove the POST default-build tree and create the separate POST unit-build tree:

```sh
git -C build/lbosc3mk/fresh status --porcelain=v1
git worktree remove "$LBOSC3MK_FRESH"
git worktree add --detach "$LBOSC3MK_FRESH" edd7d9f6dabb2b11e8a0ccd7cf8d1968c4494ca4
```

Again, status was empty, removal exited 0 and creation reported the same POST
commit. In the fresh POST unit-build tree:

```sh
test ! -e build
taskset -c 112-127 make -j16 build/lbplanner-units > "$LBOSC3MK_EVIDENCE/post-lbplanner-make.log" 2>&1
test -f build/lbplanner-units
cat build/lbosc3/unit-pad.log
taskset -c 112-127 python3 tests/lbplanner_checks.py > "$LBOSC3MK_EVIDENCE/post-lbplanner-checks.log" 2>&1
```

Every command exited 0. The
[complete POST unit-build log](docs/lbosc3mk/post-lbplanner-make.log.gz) records
the PAD recipe completing. Its log output was:

```text
PASS LBOSC3 PAD-A: exact function/section tables, PRE source closure, 1 policy bypasses, 3 negative controls
```

The [PAD proof](docs/lbosc3mk/lbosc3-unit-pad-proof.json) and
[all 14 passing check rows](docs/lbosc3mk/lbplanner-checks.json) are committed.
The [complete check output](docs/lbosc3mk/post-lbplanner-checks.log.gz) is:

```text
PASS production PASS LB record lifetime: late reader acquires replacement; active reader defers one consumption
PASS LB monitor handoff: both modes/branches; once; stale epochs; zero IO allocations
PASS no-publish FAIL core concurrency: monitor must produce a finished plan; unarmed witness fails
PASS stale-flip FAIL core concurrency: stale topology plan dropped without drain
PASS stale-lb FAIL core concurrency: stale topology plan dropped without drain
PASS duplicate FAIL core concurrency: finished plan consumed exactly once
PASS copy-on-io FAIL core concurrency: IO handoff allocates and frees nothing
PASS record-reuse FAIL core concurrency: record reuse waits for the cancelled drain reader, without blocking IO
PASS client-drain-first-tail: POST2/PAD-A2, both modes, three isolated negative controls
PASS PAD-A PASS PAD-A PRE behavior: IO-hosted key/client search, direct drain, cron, fresh parse gates
PASS POST-rejects-PRE FAIL core concurrency: PAD monitor never runs LB search
PASS LBOSC3 PASS LBOSC3 residual objective
PASS LBOSC3 consecutive streak, bounded widening, expiry, topology reset
PASS LBOSC3 both modes: real moves and stationary hold
PASS LBOSC3-PAD-A PASS LBOSC3 residual objective
PASS LBOSC3 both modes: real moves and stationary hold
PASS LBOSC3-rejects-PRE FAIL core concurrency: key objective chooses the least transfer inside the residual band
PASS LBOSC3-PRE-rejects-POST FAIL core concurrency: key objective chooses the least transfer inside the residual band
```

The `FAIL core concurrency` text above is the required rejection from deliberately
broken controls; every enclosing check reports `PASS`.

After copying the receipts out, final cleanup from the lane root was:

```sh
git -C build/lbosc3mk/fresh status --porcelain=v1
git worktree remove "$LBOSC3MK_FRESH"
test ! -e build/lbosc3mk/fresh
```

Status was empty and both commands exited 0. All three temporary trees were
removed using `git worktree remove`; no `rm -rf` or `make clean` was used.
Full build/check logs are preserved as gzip files in `docs/lbosc3mk/`.

Static validation also passed: `git diff --check`; exact correspondence of all
146 PRE/POST recipe line mappings; and reconstruction of the entire original
Makefile by removing only the 89 added `mkdir` lines. This proves no target,
prerequisite, existing output command or compiler flag changed.

## Gate rows and production receipt

Rows: **+0 quick / +0 full**. The existing handoff row is emitted at
`tests/gate.sh:1353–1358`, before the quick-tier exit at :3402–3407. No row is
added or retired. `EXPECT_QUICK=502` at :284 and `EXPECT_FULL=519` at :285 are
unchanged, and `git diff dab740964 -- tests/gate.sh` is empty.

The committed root [production.diff](production.diff) is a zero-byte receipt
generated with `git diff dab740964 -- src/ > production.diff`. Its SHA-256 is
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
It was committed with the implementation, not left as an untracked receipt.

No performance measurement is requested. The existing unit PAD arms are type
**A: behaviour twins**, PRE behaviour with candidate text size/layout. They are
used by the existing correctness checks; this change adds no PAD or benchmark
arm and makes no performance claim.

## Complete recipe audit

Line numbers below refer to PRE `dab740964` and POST `edd7d9f6d`. Ranges include
every line of each recipe, including continuation lines; added directory
creation lines are explicitly identified. `$(dir $@)` denotes the current
target's parent, including nested and overridden `BUILD_ROOT` paths. Tools
retain responsibility for their internal descendants. Dependency-only aliases,
variable assignments and target-specific flags have no output-writing recipe.

| Recipe / target | PRE recipe lines | POST recipe lines | Directory provisioning |
| --- | ---: | ---: | --- |
| `connreset-trace` | 55 | 55 | Unchanged: recursive `all` uses object-directory recipes; any subsequent copy already has `build/`. |
| `build/persistfix/aof-test.o` | 62–63 | 62–63 | Unchanged: `@mkdir -p $(dir $@)` at 62. |
| `build/persistfix/unit.o` | 65–66 | 65–66 | Unchanged: `@mkdir -p $(dir $@)` at 65. |
| `build/persistfix-unit` | 68 | 68–69 | Added `@mkdir -p $(dir $@)` at 68. |
| `build/persistfix-controls/%/aof.cc` | 70 | 71–72 | Added `@mkdir -p $(dir $@)` at 71. |
| `build/persistfix-controls/%/aof.o` | 72 | 74–75 | Added `@mkdir -p $(dir $@)` at 74. |
| `build/persistfix-controls/%/db0-aof.o` | 74 | 77–78 | Added `@mkdir -p $(dir $@)` at 77. |
| `build/persistfix-controls/%/unit` | 76 | 80–81 | Added `@mkdir -p $(dir $@)` at 80. |
| `build/persistfix-units` | 80 | 85–86 | Added `@mkdir -p $(dir $@)` at 85. |
| `build/persistfix-controls/%/tomokv` | 84 | 90–91 | Added `@mkdir -p $(dir $@)` at 90. |
| `$(BIN)` | 89 | 96–97 | Added `@mkdir -p $(dir $@)` at 96. |
| `$(BUILD_ROOT)/db0/%.o` | 165–166 | 173–174 | Unchanged: `@mkdir -p $(dir $@)` at 173. |
| `$(BUILD_ROOT)/%.o` | 169–170 | 177–178 | Unchanged: `@mkdir -p $(dir $@)` at 177. |
| `asan` | 173–174 | 181–182 | Unchanged: recursive `all` uses object-directory recipes; any subsequent copy already has `build/`. |
| `tsan` | 177–178 | 185–186 | Unchanged: recursive `all` uses object-directory recipes; any subsequent copy already has `build/`. |
| `rlcachedbg` | 185–186 | 193–194 | Unchanged: recursive `all` uses object-directory recipes; any subsequent copy already has `build/`. |
| `rlcache-nofix` | 192–193 | 200–201 | Unchanged: recursive `all` uses object-directory recipes; any subsequent copy already has `build/`. |
| `noreserve` | 199–200 | 207–208 | Unchanged: recursive `all` uses object-directory recipes; any subsequent copy already has `build/`. |
| `build/ktls-keyupdate` | 206–207 | 214–215 | Unchanged: `@mkdir -p build` at 214. |
| `build/ktls-keyupdate-unit` | 210–211 | 218–220 | Added `@mkdir -p $(dir $@)` at 218. |
| `build/splitlocal-unit.cc` | 213 | 222–223 | Added `@mkdir -p $(dir $@)` at 222. |
| `build/splitlocal-unit` | 215 | 225–226 | Added `@mkdir -p $(dir $@)` at 225. |
| `build/config-parser-test` | 217–218 | 228–229 | Unchanged: `@mkdir -p build` at 228. |
| `build/climon-mask-unit` | 220–221 | 231–232 | Unchanged: `@mkdir -p build` at 231. |
| `build/climon-mask-old-unit` | 223–225 | 234–236 | Unchanged: `@mkdir -p build/climon-mask-old/src/core` at 234. |
| `build/flipctl-unit` | 228–229 | 239–240 | Unchanged: `@mkdir -p build` at 239. |
| `build/read-local-ring-unit` | 232–233 | 243–244 | Unchanged: `@mkdir -p build` at 243. |
| `build/read-local-write-ring-unit` | 235–236 | 246–247 | Unchanged: `@mkdir -p build` at 246. |
| `build/rlfence-unit` | 238–239 | 249–250 | Unchanged: `@mkdir -p build` at 249. |
| `build/store-regression` | 242–244 | 253–255 | Unchanged: `@mkdir -p build` at 253. |
| `build/store-regression-sidecar` | 246–248 | 257–259 | Unchanged: `@mkdir -p build` at 257. |
| `build/store-regression-tsan` | 250–253 | 261–264 | Unchanged: `@mkdir -p build` at 261. |
| `build/waits-unit` | 255–256 | 266–267 | Unchanged: `@mkdir -p build` at 266. |
| `unit` | 258–265 | 269–276 | Unchanged: no output path argument or redirection; execution/cleanup only. Not run for this audit. |
| `build/encodingfix-unit` | 271 | 282–283 | Added `@mkdir -p $(dir $@)` at 282. |
| `build/storesize/multidb.cc` | 277 | 289–290 | Added `@mkdir -p $(dir $@)` at 289. |
| `build/storesize/multidb.o` | 279 | 292–293 | Added `@mkdir -p $(dir $@)` at 292. |
| `build/storesize/db0-multidb.o` | 281 | 295–296 | Added `@mkdir -p $(dir $@)` at 295. |
| `build/storesize-unit` | 283 | 298–299 | Added `@mkdir -p $(dir $@)` at 298. |
| `build/at15-unit` | 286 | 302–303 | Added `@mkdir -p $(dir $@)` at 302. |
| `build/at15-db0-unit` | 288 | 305–306 | Added `@mkdir -p $(dir $@)` at 305. |
| `build/execabort-watch-unit` | 291 | 309–310 | Added `@mkdir -p $(dir $@)` at 309. |
| `build/execabort-watch-db0-unit` | 293 | 312–313 | Added `@mkdir -p $(dir $@)` at 312. |
| `build/exbatch-unit` | 296 | 316–317 | Added `@mkdir -p $(dir $@)` at 316. |
| `build/exbatch-db0-unit` | 298 | 319–320 | Added `@mkdir -p $(dir $@)` at 319. |
| `build/exbatch/PRE/unit.o` | 302 | 324–325 | Added `@mkdir -p $(dir $@)` at 324. |
| `build/exbatch/PRE/unit` | 304 | 327–328 | Added `@mkdir -p $(dir $@)` at 327. |
| `build/flushfix-unit` | 310 | 334–335 | Added `@mkdir -p $(dir $@)` at 334. |
| `build/flushfix-pre-unit` | 312 | 337–338 | Added `@mkdir -p $(dir $@)` at 337. |
| `build/flushfix/pre-source/.emitted` | 314 | 340–341 | Added `@mkdir -p $(dir $@)` at 340. |
| `build/flushfix/pre/src/cmd/%.o` | 316–317 | 343–344 | Unchanged: `@mkdir -p $(dir $@)` at 343. |
| `build/flushfix/pre/db0/src/cmd/%.o` | 319–320 | 346–347 | Unchanged: `@mkdir -p $(dir $@)` at 346. |
| `build/kvobj-header-unit` | 322–323 | 349–350 | Unchanged: `@mkdir -p build` at 349. |
| `build/kvobj-header-db0-unit` | 325–326 | 352–353 | Unchanged: `@mkdir -p build` at 352. |
| `build/flushfix-header-controls/%/unit` | 329–330 | 356–358 | Added `@mkdir -p build/flushfix-header-controls/$*/source` at 356. |
| `build/flushfix-units` | 332 | 360–361 | Added `@mkdir -p $(dir $@)` at 360. |
| `build/multidb-unit` | 341 | 370 | Unchanged: order-only `build/mdbqsbr-unit` (PRE 367 / POST 401) guarantees `build/`. |
| `build/mdbqsbr-asan/%.o` | 351–352 | 380–381 | Unchanged: `@mkdir -p $(dir $@)` at 380. |
| `build/mdbqsbr-tsan/%.o` | 354–355 | 383–384 | Unchanged: `@mkdir -p $(dir $@)` at 383. |
| `build/mdbqsbr-unit` | 358 | 387–388 | Added `@mkdir -p $(dir $@)` at 387. |
| `build/mdbqsbr-unit-tsan` | 360 | 390–391 | Added `@mkdir -p $(dir $@)` at 390. |
| `build/core-concurrency-mdbqsbr-asan` | 362 | 393–394 | Added `@mkdir -p $(dir $@)` at 393. |
| `build/rltopo-unit` | 364 | 396–397 | Added `@mkdir -p $(dir $@)` at 396. |
| `build/core-concurrency-mdbqsbr-tsan` | 366 | 399–400 | Added `@mkdir -p $(dir $@)` at 399. |
| `mdbqsbr-live-arms` | 373–374 | 407–408 | Unchanged: recursive `all` uses object-directory recipes; any subsequent copy already has `build/`. |
| `build/multidb-boundary-unit` | 377 | 411–412 | Added `@mkdir -p $(dir $@)` at 411. |
| `build/multidb-cost-unit` | 379 | 414–415 | Added `@mkdir -p $(dir $@)` at 414. |
| `build/multidb-cost-unit-multi` | 381 | 417–418 | Added `@mkdir -p $(dir $@)` at 417. |
| `build/tomokv-multidb2-pad` | 383 | 420–421 | Added `@mkdir -p $(dir $@)` at 420. |
| `build/tomokv-multidb-pad` | 385 | 423–424 | Added `@mkdir -p $(dir $@)` at 423. |
| `build/rehash-waits-unit` | 387 | 426–427 | Added `@mkdir -p $(dir $@)` at 426. |
| `build/overlap-prefetch-unit` | 391 | 431–432 | Added `@mkdir -p $(dir $@)` at 431. |
| `build/core-concurrency-unit` | 394 | 435–436 | Added `@mkdir -p $(dir $@)` at 435. |
| `build/atomic-survivors-unit` | 400–401 | 442–444 | Added `@mkdir -p $(dir $@)` at 442. |
| `build/owner-arena-unit` | 406–408 | 449–452 | Added `@mkdir -p $(dir $@)` at 449. |
| `owner-arena-unit` | 413–416 | 457–460 | Unchanged: no output path argument or redirection; execution/cleanup only. Not run for this audit. |
| `build/l4prebuild-unit` | 424–426 | 468–471 | Added `@mkdir -p $(dir $@)` at 468. |
| `build/tomokv-pad` | 431 | 476–477 | Added `@mkdir -p $(dir $@)` at 476. |
| `l4prebuild-unit` | 434–437 | 480–483 | Unchanged: no output path argument or redirection; execution/cleanup only. Not run for this audit. |
| `build/l4prebuild-tsan/%.o` | 445–446 | 491–492 | Unchanged: `@mkdir -p $(dir $@)` at 491. |
| `build/l4prebuild-unit-tsan` | 449–451 | 495–498 | Added `@mkdir -p $(dir $@)` at 495. |
| `l4prebuild-unit-tsan` | 454–457 | 501–504 | Unchanged: no output path argument or redirection; execution/cleanup only. Not run for this audit. |
| `build/benchtxn` | 463–464 | 510–511 | Unchanged: `@mkdir -p build` at 510. |
| `build/broaden-bench` | 466–467 | 513–514 | Unchanged: `@mkdir -p build` at 513. |
| `build/tailgen` | 475–476 | 522–523 | Unchanged: `@mkdir -p build` at 522. |
| `build/tailgen-unit` | 478–479 | 525–526 | Unchanged: `@mkdir -p build` at 525. |
| `build/tailgen-unit-asan` | 481–482 | 528–529 | Unchanged: `@mkdir -p build` at 528. |
| `build/tailgen-unit-tsan` | 484–485 | 531–532 | Unchanged: `@mkdir -p build` at 531. |
| `tailgen-unit` | 488 | 535 | Unchanged: no output path argument or redirection; execution/cleanup only. Not run for this audit. |
| `tailgen-unit-asan` | 490 | 537 | Unchanged: no output path argument or redirection; execution/cleanup only. Not run for this audit. |
| `tailgen-unit-tsan` | 492 | 539 | Unchanged: no output path argument or redirection; execution/cleanup only. Not run for this audit. |
| `clean` | 496 | 543 | Unchanged: no output path argument or redirection; execution/cleanup only. Not run for this audit. |
| `build/tests/%.o` | 506–507 | 553–554 | Unchanged: `@mkdir -p $(dir $@)` at 553. |
| `build/netcmd-unit` | 509 | 556–557 | Added `@mkdir -p $(dir $@)` at 556. |
| `build/db0/tests/%.o` | 514–515 | 562–563 | Unchanged: `@mkdir -p $(dir $@)` at 562. |
| `build/netcmd-unit-db0` | 519 | 567–568 | Added `@mkdir -p $(dir $@)` at 567. |
| `build/reorderscan-unit` | 526–527 | 575–576 | Unchanged: `@mkdir -p build` at 575. |
| `build/reorderscan-unit-asan` | 529–530 | 578–579 | Unchanged: `@mkdir -p build` at 578. |
| `build/reorder-unit` | 533 | 582–583 | Added `@mkdir -p $(dir $@)` at 582. |
| `build/reorder-unit-asan` | 535 | 585–586 | Added `@mkdir -p $(dir $@)` at 585. |
| `build/reorder-engagement-unit` | 538 | 589–590 | Added `@mkdir -p $(dir $@)` at 589. |
| `build/reorder-engagement-unit-db0` | 540–541 | 592–594 | Added `@mkdir -p $(dir $@)` at 592. |
| `reorder-checks` | 547–551 | 600–605 | Added `@mkdir -p build/reorder-checks/multi build/reorder-checks/db0 build/reorder-checks/identity` at 600. |
| `build/r7shadow3/reorder-witness.o` | 556–557 | 610–611 | Unchanged: `@mkdir -p $(dir $@)` at 610. |
| `build/r7shadow-split-unit` | 559–561 | 613–616 | Added `@mkdir -p $(dir $@)` at 613. |
| `build/r7shadow3/reorder-witness-db0.o` | 563–565 | 618–620 | Unchanged: `@mkdir -p $(dir $@)` at 618. |
| `build/r7shadow-split-unit-db0` | 567–570 | 622–626 | Added `@mkdir -p $(dir $@)` at 622. |
| `build/r7shadow-unit` | 573 | 629–630 | Added `@mkdir -p $(dir $@)` at 629. |
| `build/r7shadow-unit-asan` | 575 | 632–633 | Added `@mkdir -p $(dir $@)` at 632. |
| `build/r7shadow-instr` | 579 | 637–638 | Added `@mkdir -p $(dir $@)` at 637. |
| `build/signalacct-core-unit` | 585 | 644–645 | Added `@mkdir -p $(dir $@)` at 644. |
| `build/wb-rule-unit` | 594–595 | 654–655 | Unchanged: `@mkdir -p build` at 654. |
| `build/wb-rule-db0-unit` | 597–598 | 657–658 | Unchanged: `@mkdir -p build` at 657. |
| `build/wb-rule-phase-unit` | 600 | 660–661 | Added `@mkdir -p $(dir $@)` at 660. |
| `build/wb-rule-db0-phase-unit` | 602 | 663–664 | Added `@mkdir -p $(dir $@)` at 663. |
| `build/wb-rule-controls/%/unit (policy arms)` | 604–605 | 666–668 | Added `@mkdir -p build/wb-rule-controls/$*/source` at 666. |
| `build/wb-rule-controls/%/unit (phase arms)` | 607–608 | 670–672 | Added `@mkdir -p build/wb-rule-controls/$*/source` at 670. |
| `build/wb-rule-units` | 612 | 676–677 | Added `@mkdir -p $(dir $@)` at 676. |
| `build/wb-rule-completion-unit` | 619–620 | 684–685 | Unchanged: `@mkdir -p build` at 684. |
| `build/wb-rule-db0-completion-unit` | 622–623 | 687–688 | Unchanged: `@mkdir -p build` at 687. |
| `build/wb-rule-completion-controls/%/source/.emitted` | 625–626 | 690–692 | Added `@mkdir -p $(dir $@)` at 690. |
| `build/wb-rule-completion-controls/%/unit` | 628 | 694–695 | Added `@mkdir -p $(dir $@)` at 694. |
| `build/wb-rule-completion-controls/%/db0-unit` | 630 | 697–698 | Added `@mkdir -p $(dir $@)` at 697. |
| `build/wbland-unit` | 635–636 | 703–704 | Unchanged: `@mkdir -p build` at 703. |
| `build/wbland-db0-unit` | 638–639 | 706–707 | Unchanged: `@mkdir -p build` at 706. |
| `build/wbland-clause-unit` | 641 | 709–710 | Added `@mkdir -p $(dir $@)` at 709. |
| `build/wbland-db0-clause-unit` | 643 | 712–713 | Added `@mkdir -p $(dir $@)` at 712. |
| `build/wbland-controls/%/unit` | 645–646 | 715–717 | Added `@mkdir -p build/wbland-controls/$*/source` at 715. |
| `build/wbland-clause-controls/%/unit` | 648–649 | 719–721 | Added `@mkdir -p build/wbland-clause-controls/$*/source` at 719. |
| `build/wbland-units` | 653 | 725–726 | Added `@mkdir -p $(dir $@)` at 725. |
| `build/lanefull-db0-unit` | 659 | 732–733 | Added `@mkdir -p $(dir $@)` at 732. |
| `$(BUILD_ROOT)/shutdown-unit` | 665 | 739–740 | Added `@mkdir -p $(dir $@)` at 739. |
| `$(BUILD_ROOT)/shutsave-unit` | 668 | 743–744 | Added `@mkdir -p $(dir $@)` at 743. |
| `build/netcap-unit` | 671 | 747–748 | Added `@mkdir -p $(dir $@)` at 747. |
| `build/lbplanner-unit` | 676 | 753–754 | Added `@mkdir -p $(dir $@)` at 753. |
| `build/lbplanner-unit-tsan` | 678 | 756–757 | Added `@mkdir -p $(dir $@)` at 756. |
| `build/lbplanner-controls/%/source/src/core/io_loop.h` | 683 | 762–763 | Added `@mkdir -p $(dir $@)` at 762. |
| `build/lbplanner-controls/%/unit (timing arms)` | 685 | 765–766 | Added `@mkdir -p $(dir $@)` at 765. |
| `build/lbplanner-controls/%/lbplanner.cc` | 687 | 768–769 | Added `@mkdir -p $(dir $@)` at 768. |
| `build/lbplanner-controls/%/lbplanner.o` | 689 | 771–772 | Added `@mkdir -p $(dir $@)` at 771. |
| `build/lbplanner-controls/%/unit` | 691 | 774–775 | Added `@mkdir -p $(dir $@)` at 774. |
| `build/lbplanner-unit-pad` | 693 | 777–778 | Added `@mkdir -p $(dir $@) build/lbplanner-unit-pad-proof` at 777. |
| `build/tomokv-lbplanner-pad` | 695 | 780–781 | Added `@mkdir -p $(dir $@) build/lbplanner-pad-proof` at 780. |
| `build/lbosc3-unit-pad` | 697 | 783–784 | Added `@mkdir -p build/lbosc3/unit-pad-proof` at 783. |
| `build/lbplanner-units` | 699 | 786–787 | Added `@mkdir -p $(dir $@)` at 786. |
| `build/lbplanner-trace` | 703 | 791–792 | Added `@mkdir -p $(dir $@)` at 791. |
