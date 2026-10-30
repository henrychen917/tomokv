# Final linked-body inventory

Normalization resolves relocation targets, exact literal bytes and bounded switch destinations; it does not mask opcodes, immediates, registers, padding, member offsets or source-line constants.

10109 function groups: 8411 match headline, 1310 changed groups match a supplied lane POST, 388 remain composite/compiler-propagated differences. Every changed group and reason is listed in `changed-bodies.md` and `changed-bodies.json`.

The hot inventory also includes every body entered by the 116 command scopes. Its totals are 1,212 groups: 770 headline-identical, 323 lane-identical, and 119 remaining. A combined caller can carry more than one accepted lane and cannot equal either isolated caller. Identity is a proxy; the maintainer decides merit.

All ordinary GET/SET/MGET/MSET handler variants match headline except normal-namespace notification-enabled, no-borrow GET (`cmd_get<true,false>`), 799 -> 792 bytes. It exactly matches snapfix2, blockfix3, scriptfix2 and rlfix4. The difference outlines the missing-key reply sink advance; it is not an integration-only semantic change. The paired ordinary command scopes are flat for GET/SET and add nothing for INCR. TLS/notification miss instruction counts are outside that requested scope.

Additional compile-only trials of the notification unit restored that GET body at some budgets but changed the ordinary notification GET and/or SET bodies. No such trial was selected. `../notify-budget-*.json` and `../pruned-trial-receipts.json.gz` retain values, compiler recipes, IPA sizes, code digests and linked scores. The exact-all-hot-body identity target is therefore not fully met; the residual is explicit rather than hidden by a normalizer or a substituted old object.

The one source-level integration behavior change after merging is the cold FUNCTION LOAD unknown-option CR/LF correction (5e57bbdfd). All other production changes are lane merge resolutions or compile-budget selection. The ordinary function inventory does not include runtime performance claims.
