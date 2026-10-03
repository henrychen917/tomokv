# Sourced by gate.sh. Selection happens before workers start; job bodies, row
# watchdogs, ports and finalizers are shared with complete runs.
select_jobs(){
  [ "$GATE_PARTIAL" = 1 ] || return 0
  local name dependency changed=1 spec=${GATE_ONLY_JOBS//,/ }
  spec=${spec//$'\n'/ }
  local -a requested=() selected=()
  local -A available=() wanted=()
  for name in "${JOB_NAMES[@]}"; do available[$name]=1; done
  read -r -a requested <<< "$spec"
  [ "${#requested[@]}" -gt 0 ] || { echo 'GATE_ONLY_JOBS is empty' >&2; return 2; }
  for name in "${requested[@]}"; do
    case "$name" in
      production_units|core_tsan_build|waits_tsan_build|tailgen_build)
        echo "$name is a build-only prerequisite; select its consuming correctness job" >&2; return 2;;
      differ-split) wanted[differ-split-0]=1; wanted[differ-split-1]=1; wanted[differ-equivalence]=1;;
      differ-armed) wanted[differ-armed-0]=1; wanted[differ-armed-1]=1;;
      *)
        if ! [[ "$name" =~ ^[a-zA-Z0-9_-]+$ ]] || [ -z "${available[$name]:-}" ]; then
          echo "unknown gate job for $TIER tier: $name" >&2; return 2
        fi
        wanted[$name]=1;;
    esac
  done
  while [ "$changed" = 1 ]; do
    changed=0
    for name in "${!wanted[@]}"; do
      [ -n "${available[$name]:-}" ] || { echo "job unavailable in $TIER: $name" >&2; return 2; }
      for dependency in $(job_dependencies "$name"); do
        if [ -z "${wanted[$dependency]:-}" ]; then wanted[$dependency]=1; changed=1; fi
      done
    done
  done
  for name in "${JOB_NAMES[@]}"; do
    [ -z "${wanted[$name]:-}" ] || selected+=("$name")
  done
  JOB_NAMES=("${selected[@]}")
  printf 'PARTIAL jobs (including prerequisites): %s\n' "${JOB_NAMES[*]}"
}

partial_gate(){
  local name dir rc passed failed cleanup_rc=0
  # Wait for all finalizers before reading their completion evidence, exactly as
  # the full gate does at its correctness barrier.
  join_workers
  for name in "${JOB_NAMES[@]}"; do
    dir="$RUN_DIR/jobs/$name"
    if [ -s "$dir/ledger" ]; then
      collect_job "$name"
    elif [ -f "$dir/done" ] && read -r rc passed failed < "$dir/done" &&
         [ "$rc $passed $failed" = '0 0 0' ]; then
      # Build-only dependencies own no public row. Their consumers check the
      # usual unit-ready markers; failed helpers never disappear silently.
      cat "$dir/output.log"
    else
      bad "$(job_label "$name")" "prerequisite did not complete; see $dir"
    fi
  done
  phase end
  cleanup || cleanup_rc=$?
  echo "GATE(PARTIAL): $PASS ok, $FAIL FAIL; no EXPECT tally, ABBA, NIC or receipt; ledger: $LEDGER"
  [ "$FAIL" -eq 0 ] && [ "$cleanup_rc" -eq 0 ]
}
