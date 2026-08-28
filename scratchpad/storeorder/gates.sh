#!/bin/bash
# gates.sh <atomic>  -- the containment battery against one boot on 7610 (target) + 7611 (oracle)
set -u
R=/home/user/Projects/tomokv-cpp-storeorder
AT=$1
cd "$R" || exit 1
"$R/scratchpad/storeorder/stop.sh" 7610
PID=$("$R/scratchpad/storeorder/boot.sh" 7610 96-107 "$R/build/tomokv" --shards 16 --ratio 6:6 \
      --atomic "$AT" --enable-debug-command yes) || exit 1
echo "== atomic=$AT pid=$PID"
pass=0; fail=0
for t in storeorder multires atomic_torn atomic_ryow atomfix execatomic execiso execfix \
         multi_exec concur ryow xacct xscript scriptatomic writer_atomic session_monotonic \
         s6 xmove zsetops lcs tracking torture blockmulti debug resp3 limits geo edgeproto \
         lua_scripting bitfield blocking stream streamgroups hexpire; do
  [ -f "tests/$t.py" ] || continue
  out=$(timeout 900 python3 "tests/$t.py" 127.0.0.1 7610 2>&1); rc=$?
  if [ $rc = 0 ]; then pass=$((pass+1));
  else fail=$((fail+1)); echo "  FAIL($rc) $t: $(echo "$out" | tail -2 | tr '\n' ' ' | cut -c1-200)"; fi
done
echo "BATTERIES atomic=$AT -> pass=$pass fail=$fail"
