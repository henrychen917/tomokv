# Bounded PRE pub/sub control

Eight fresh gate jobs use the unmodified pub/sub assertion inventory, 1s and 2s, 16 shards, 6:2, CPUs 48–55 and ports 20340–20349. Every runtime summary binds actual PRE SHA `2e07ea8a5be37d357ba05370b3a00f4bf473e09a40f91e94016ee8d5953e5309`; the manifest's survey SHA is not a runtime identity.

Attempt 2 reproduces `PUBLISH/PSUBSCRIBE after PUNSUBSCRIBE without arguments` on 2s: expected publisher count 0, got 1. No assertion was removed. The remaining seven attempts pass both modes; all eight 1s legs pass. UNSUBSCRIBE does not fail within this eight-attempt bound; its exact PRE failure is separately recorded in `../pre-tcl-control/`. Together the two controls establish both first-release Tcl pub/sub failures on PRE, without claiming they failed together or on every geometry. The isolated final POST full subset passes in both modes. The underlying intermittent baseline defects are not repaired by this lane.
