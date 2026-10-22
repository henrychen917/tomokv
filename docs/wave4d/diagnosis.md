# wave4d call-site diagnosis (incoming merge)

The linked call-site inventory covers all ten residual command groups against
both frozen headline and moverfix POST. `call-sites.json.gz` retains every site,
including indirect calls, tail branches and exact offsets; `call-differences.json`
retains all multiplicity differences. The strict normalizer is unchanged.

* The four `cmd_xshard_only_impl` and two `store_xstring_selected` bodies have
  **no call-site or instruction-encoding difference** against either reference.
  The local MGET lookup/reply loop is unchanged. Their strict mismatches are
  compiler table names and anonymous scalar references (data bytes were verified
  by wave4c). There is no missing inline callee to restore in these six groups.
* DB0 `xshard_execute` has one additional outlined callee against moverfix:
  `std::mutex::lock` on SWAPDB's shape-transition lock. Moverfix instead calls
  `pthread_mutex_lock` and its error path calls `std::__throw_system_error`.
  The merge also loses the separate `__stack_chk_fail` call associated with the
  previous cold-region shape. Its exception fragment has identical call targets
  against moverfix, with shifted instructions/landing pads. The main body is
  23,183 versus 23,221 bytes; cold is 380 versus 383.
* Against headline, DB0 `xshard_execute` additionally has moverfix's intentional
  new `execute_live_pop` and `execute_plain_element_mover` calls and changed
  `execute_atomic_apply` cloning; the old element removal/push/pop calls move
  into those helpers. These must remain. The detailed source/inline attribution
  and MGET reachability analysis will accompany the source trial results.
* Normal armed `cmd_set_prebuilt<true>` inlines one `FlatStore::deadline` call
  that headline/moverfix outline. DB0 instead calls `KvObj::key` at two sites
  that were inline. These decisions are already present in compat2 POST, whose
  expiry-observation guard changes the body; clockcut adds exactly seven deadline
  branch-opcode changes per body. This composed correctness behavior cannot equal
  a frozen single-lane binary. Neither armed SET body executes for MGET.

No finding here establishes a throughput cause. The pending source trials and
bounded instruction diagnostic must be judged separately from strict identity.
