## cfgfix2

Lane `cx-cfgfix2`, PRE `bc80de80b87ce482cf067a446a8411f7baef074a`.
No push. Builds and correctness runners use CPUs 32–47 only, `LC_ALL=C`,
and ports 21800–21899. Gate servers use CPUs 32–39, 16 shards, and split
ratio 6:2. No performance workload or full iteration gate is authorized here.

### Directed witnesses (in progress)

| Item | PRE witness | POST result | Mechanism | Residual |
|---|---|---|---|---|
| CG5.1 | All 12 malformed-file boots admit unauthenticated SET; Redis rejects 3/3 | All 12 rejected; scalar-password control passes in all four mode/engine legs | File variadic arguments cannot become subsequent CLI options; parser diagnostics retain physical line context | Redis defers the unknown-command ACL rule to ACL initialization; this is checked separately from fatal parser diagnostics |

The new rows use the gate's own selected-job interface. Receipts live under
`docs/cfgfix2/`. Initial failed verification remains in `build/cfgfix2/`;
parser regression helpers were updated to use the production per-line API.

The serverless GET/SET/INCR/MGET/MSET PRE census is retained in
`docs/cfgfix2/instructions/PRE/`; final POST comparison remains pending.

### Maintainer measurement request

Run the unchanged 14 generic cells plus 2s GET/SET at p1/p32 with the gate's
instrument. Retain cycles/op, IPC, instructions/op, completed rate and latency
for PRE/PRE and POST/POST nulls, PRE/POST and PRE/PAD-A. Acceptance is no
main-command regression in any cell; do not average away a failing cell.
This lane makes no throughput claim.

PAD-A will be type **A, behaviour twin**: PRE behavior with POST's aggregate
text start and size. Internal function placement and data layout remain PRE;
this size control is not an exact symbol-layout twin. Final hashes and row
counts will be recorded after all six items and verification finish.
