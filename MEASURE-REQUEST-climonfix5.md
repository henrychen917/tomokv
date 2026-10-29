## climonfix5

Base: `aaf658f85` on `cx-climonfix5`; PRE `393d6ceb1`, C4 production
source `c369ccc41`. No push. All lane processes use CPUs 16–31; correctness
servers use ports 20200–20299 and `LC_ALL=C`.

Work in progress: remove unarmed script/transaction bookkeeping while retaining
climonfix4 semantics. No throughput measurements or claims. The final report will
record instruction scopes, all correctness results and any NOT RUN obligations,
four binary hashes, and the maintainer's requested merit comparisons.

No gate row is added or removed: DQ=0, DF=0 over climonfix4's 909/926.
`EXPECT_QUICK` and `EXPECT_FULL` remain untouched.
