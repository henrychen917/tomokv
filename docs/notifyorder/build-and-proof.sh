#!/bin/bash
set -eu
cd /home/user/Projects/cx-notifyorder
taskset -c 96-111 make -j16 all $(cat docs/notifyorder/production-targets.txt) mdbqsbr-live-arms \
  >docs/notifyorder/build-frozen.log 2>&1
taskset -c 96-111 make -q all $(cat docs/notifyorder/production-targets.txt) mdbqsbr-live-arms \
  >docs/notifyorder/freshness-frozen.log 2>&1
# Fail fast on serverless contracts before the long live matrix.
taskset -c 96-111 env GATE_ONLY_JOBS="$(cat docs/notifyorder/serverless-jobs.txt)" \
  bash tests/gate.sh full --server-cores 96-104 --load-cores 105-111 --load-smt '' \
  --ports 25800-25899 --candidate-binary "$PWD/build/tomokv" \
  >docs/notifyorder/gate-serverless-post.log 2>&1
if taskset -c 96-111 python3 tools/ccfix_audit.py build/notifyorder/pre build \
    docs/notifyorder/identity-resolved >docs/notifyorder/identity-resolved.log 2>&1; then
  printf 'resolved identity diagnostic rc=0\n' >docs/notifyorder/identity-resolved-status.log
else
  printf 'resolved identity diagnostic rc=%s\n' "$?" >docs/notifyorder/identity-resolved-status.log
fi
taskset -c 96-111 python3 docs/notifyorder/identity.py build/notifyorder/pre build \
  docs/notifyorder/identity-final >docs/notifyorder/identity-final.log 2>&1
taskset -c 96-111 python3 docs/notifyorder/artifacts.py reasons docs/notifyorder/identity-final \
  >>docs/notifyorder/identity-final.log
taskset -c 96-111 python3 docs/notifyorder/artifacts.py pad build/tomokv \
  build/notifyorder/tomokv-pad-a docs/notifyorder/pad-a.json >docs/notifyorder/pad-a.log
taskset -c 96-111 python3 docs/notifyorder/artifacts.py no-salvage build/tomokv \
  build/notifyorder/tomokv-no-salvage docs/notifyorder/no-salvage-server.json \
  >docs/notifyorder/no-salvage-server.log
sha256sum build/notifyorder/pre/tomokv build/tomokv build/notifyorder/tomokv-pad-a \
  >docs/notifyorder/SHA256SUMS
taskset -c 96-111 bash docs/notifyorder/run-final-proof.sh
