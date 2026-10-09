# Uncommitted tail of lane aclkeys4b (mainline note, 2026-10-09 08:40)

The lane finished its fix, report and proofs (HEAD 053910418, 08:05) and then
continued into a byte-stability refactor of the DEBUG xread-registration-hold
dispatch (t_server.cc / blocking_debug.cc) plus a tools/aclkeys4_budget.py
extension (08:10-08:19). The codex content filter stopped the run at 08:21
before that refactor was finished or built. The mainline saved the diff as
`uncommitted-tail-0821.patch` and reverted the working files to HEAD so the
landing gates exactly the reported, built state (POST build/tomokv sha256
3679da87..., recorded in SHA256SUMS). The body-audit output directory the lane
left untracked is committed alongside as evidence.
