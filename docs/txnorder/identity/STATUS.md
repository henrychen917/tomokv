# Initial complete cost check — rejected

This coherent build passes 1208/1208 selected-hot and 601/601 + 603/603
lbstall bodies. Both ScatterState constructors/destructors and xshard_destroy
match PRE. However, the production-object MGET fixture finds DB0 xshard_execute
at 324 instructions versus PRE 322 (two fragments). This is a real cost-bar
failure; the selected-body pass does not override it. The trace and difference
are retained in ../paths/mget and ../paths/mget-comparison.json. Follow-up
compiler isolation and final reproof are required.

The full checker exits 1 because the task intentionally changes cmd_debug_impl,
which is outside its existing CONFIG/INFO/ACL exception; its assertion was not
edited. Linked runtime sections also differ. Neither is called whole-binary
identity. See the complete changed-body inventory.
