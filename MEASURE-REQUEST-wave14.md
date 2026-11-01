# Wave 14 integration and measurement request

## wave14 integration

Work in progress on `cx-wave14`, based on `105c5818cc`. No push. All six
lane reports were read before integration. Merge order: witnessfix, rootcore,
blockfix4, rootcompat, clientcompat, execfifo3. The maintainer's two merit
addenda authorize every merge. Lane branches are read-only inputs.

Builds and correctness work use CPUs 0–31, builds at most `-j32`, ports
20000–20099, and `LC_ALL=C` on every boot. Only selected correctness jobs,
oracles, differential suites, and finite serverless instruction scopes run
here. Performance/load generators and the full iteration remain maintainer work.

The supplied headline path omits one hash character. The existing frozen image
is `/home/user/Projects/bench-bins/tomokv-headline-105c5818cc`.

Expected lane-only DQ=DF=43: witnessfix 2, rootcore 7, blockfix4 5,
rootcompat 9, clientcompat 5, execfifo3 15. This predicts 1089 quick / 1106
full against 1046/1063. Exact declarations, collector placement, and any
integration additions will be reconciled before delivery. EXPECT constants
remain untouched.

MISCONF recovery and the WAITAOF non-mutation receipt are known differences,
as required by the integration brief. Their directed checks will retain
arming and exact observed behavior instead of unconditionally failing or
accepting arbitrary errors. Other lane residuals remain explicit exclusions.

Validation, semantic interactions, compile trials, command-scope counts,
arm hashes, and maintainer measurement recipes are pending. No completed
proof or throughput claim is made by this initial record.
