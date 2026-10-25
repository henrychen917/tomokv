#!/bin/bash
# Correctness only. Every job is the gate's unchanged scheduling/leg interface.
set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT"
run_gate() {
  local label=$1 source=$2 binary=$3 jobs=$4
  local tier=${5:-quick}
  (
    cd "$source"
    GATE_ONLY_JOBS="$jobs" GATE_LEDGER="$ROOT/docs/ctlfix/$label" \
      tests/gate.sh "$tier" --server-cores 48-55 --load-cores 56-63 \
      --ports "${CTLFIX_PORTS:-35811-35820}" --candidate-binary "$binary"
  ) >"docs/ctlfix/$label.log" 2>&1
  local result=$?
  echo "$result" >"docs/ctlfix/$label.rc"
  printf '%s rc=%s\n' "$label" "$result"
  python3 tools/ctlfix_artifacts.py archive "docs/ctlfix/$label.log"
}
case ${1:-post} in
  pad)
    make -f tests/ctlfix.mk -j16 build/ctlfix-unit > docs/ctlfix/pad-unit-build.log 2>&1 || exit 1
    cp build/ctlfix-unit build/ctlfix-unit-POST
    python3 tools/ctlfix_artifacts.py pad build/ctlfix-unit-POST build/ctlfix-unit \
      docs/ctlfix/pad-unit-layout.json || exit 1
    trap 'mv -f build/ctlfix-unit-POST build/ctlfix-unit' EXIT
    GATE_ONLY_JOBS=flip_unit GATE_LEDGER="$ROOT/docs/ctlfix/pad-unit" \
      tests/gate.sh quick --server-cores 48-55 --load-cores 56-63 \
      --ports 35810-35819 --candidate-binary "$ROOT/build/tomokv-PAD-A" \
      > docs/ctlfix/pad-unit.log 2>&1
    echo "$?" > docs/ctlfix/pad-unit.rc
    mv -f build/ctlfix-unit-POST build/ctlfix-unit
    trap - EXIT
    python3 tools/ctlfix_artifacts.py archive docs/ctlfix/pad-unit.log
    GATE_ONLY_JOBS=flip_unit GATE_LEDGER="$ROOT/docs/ctlfix/post-unit-final" \
      tests/gate.sh quick --server-cores 48-55 --load-cores 56-63 \
      --ports 35810-35819 --candidate-binary "$ROOT/build/tomokv" \
      > docs/ctlfix/post-unit-final.log 2>&1
    echo "$?" > docs/ctlfix/post-unit-final.rc
    python3 tools/ctlfix_artifacts.py archive docs/ctlfix/post-unit-final.log
    ;;
  post)
    run_gate post-broad "$ROOT" "$ROOT/build/tomokv" \
      'config_unit flip_unit core_units flipfix_units lbplanner_units boot_grammar lb-stationary-1s lb-stationary-2s flip fliplisten flipctl flip_saturated debug-0 debug-1 fused-0 fused-1'
    ;;
  post-final)
    run_gate post-final "$ROOT" "$ROOT/build/tomokv" \
      'config_unit flip_unit core_units flipfix_units lbplanner_units boot_grammar lb-stationary-1s lb-stationary-2s flip fliplisten flipctl flip_saturated debug-0 debug-1 fused-0 fused-1'
    ;;
  pre)
    cp tests/ctlfix_unit.cc tests/ctlfix.mk tests/gate.sh tests/flipsettle_checks.inc build/ctlfix-pre/tests/
    [ -e build/ctlfix-pre/docs ] || ln -s "$ROOT/docs" build/ctlfix-pre/docs
    run_gate pre-broad "$ROOT/build/ctlfix-pre" "$ROOT/build/tomokv-PRE" \
      'config_unit flip_unit core_units flipfix_units lbplanner_units boot_grammar lb-stationary-1s lb-stationary-2s flip fliplisten flipctl flip_saturated'
    ;;
  epoll)
    # Only the default engine is changed. Explicit engine legs in job_flip still
    # override it, so uring and epoll churn/signal arms remain present.
    for arm in post pre; do
      binary="$ROOT/build/tomokv"; [ "$arm" != pre ] || binary="$ROOT/build/tomokv-PRE"
      wrapper="$ROOT/build/ctlfix-$arm-epoll"
      printf '#!/bin/bash\nexec %q --net-io epoll "$@"\n' "$binary" > "$wrapper"
      chmod +x "$wrapper"
      run_gate "$arm-epoll" "$ROOT" "$wrapper" \
        'flip flipctl flip_saturated lb-stationary-1s lb-stationary-2s'
    done
    ;;
  matrix)
    jobs='netio-1s netio-2s feature-cell-split-home-min feature-cell-fused-home-max-nopin feature-cell-split-shards-auto'
    for mode in 1s 2s; do
      for read_local in 0 1; do for client_lb in 0 1; do for reorder in 0 1; do for flip in 0 1; do
        jobs+=" feature-cell-$mode-$read_local-$client_lb-$reorder-$flip"
      done; done; done; done
    done
    run_gate post-feature-matrix "$ROOT" "$ROOT/build/tomokv" "$jobs"
    run_gate post-rlcache "$ROOT" "$ROOT/build/tomokv" rlcache full
    ;;
  differ)
    for engine in uring epoll; do
      for geometry in split armed-fused; do
        label="differ-$engine-$geometry"
        mkdir -p "docs/ctlfix/$label"
        GATE_LOAD_CORES=56-63 GATE_DIFFER_ORACLE_CORES=48-55 \
          GATE_DIFFER_NET_IO="$engine" GATE_DIFFER_GEOMETRY="$geometry" \
          GATE_DIFFER_OUT="$ROOT/docs/ctlfix/$label" \
          tests/differ_gate.sh "$ROOT/build/tomokv" 35831 35832 48-55 6:2 \
          >"docs/ctlfix/$label.log" 2>&1
        result=$?
        echo "$result" >"docs/ctlfix/$label.rc"
        printf '%s rc=%s\n' "$label" "$result"
      done
    done
    ;;
  *) echo 'want post|post-final|pre|epoll|matrix|differ|pad' >&2; exit 2;;
esac
