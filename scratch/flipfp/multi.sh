#!/bin/bash
# Multi-thread confirmation on our own CCX: N fused server threads pinned to $SRVCORES, one replay
# connection per client core in $CLICORES, perf stat aggregated over the server cores. Same slope
# method as pmu.sh (N1/N2 ops PER CONNECTION). Every op whose shard owner is not the connection's
# thread crosses threads exactly as it does on the 32-core box; here the crossings land in ONE L3
# domain, so they appear as ls_dmnd_fills_from_sys.local_ccx rather than near_cache.
#
#   multi.sh <binary> <tag> <out.csv> [reps]   env: SRVCORES CLICORES SHAPES RINGS N1 N2 PMU_GROUPS
set -u
BIN="$1"; TAG="$2"; OUT="$3"; REPS="${4:-1}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SRVCORES=${SRVCORES:-188-191}; CLICORES=${CLICORES:-56 57 58 59}
PORT=${PORT:-8096}
SRVCORE="$SRVCORES"   # lib's boot_srv pins the server to this (a range => one thread per cpu)
source "$HERE/lib.sh"
N1=${N1:-1000000}; N2=${N2:-3000000}
SHAPES=${SHAPES:-"get_hit set_over mixed11x delset"}
RINGS=${RINGS:-"4096 1048576"}
KEYLEN=${KEYLEN:-16}; VLEN=${VLEN:-32}; PIPE=${PIPE:-32}
LOG=$(mktemp /tmp/cyclemap-multi-$TAG.XXXXXX)
declare -A G
G[td]="ls_not_halted_cyc,ex_ret_ops,de_src_op_disp.all,de_no_dispatch_per_slot.no_ops_from_frontend,de_no_dispatch_per_slot.backend_stalls,de_no_dispatch_per_slot.smt_contention"
G[be]="cycles,instructions,cycles:u,instructions:u,ex_no_retire.load_not_complete,ex_no_retire.not_complete"
G[nr]="cycles,ex_no_retire.all,ex_no_retire.empty,ex_no_retire.other,ex_no_retire.thread_not_selected,ls_not_halted_cyc"
G[rs]="cycles,de_dis_dispatch_token_stalls1.store_queue_rsrc_stall,de_dis_dispatch_token_stalls1.load_queue_rsrc_stall,de_dis_dispatch_token_stalls2.retire_token_stall,de_dis_dispatch_token_stalls1.int_phy_reg_file_rsrc_stall,de_dis_dispatch_token_stalls1.taken_brnch_buffer_rsrc"
G[fl]="ls_dmnd_fills_from_sys.local_l2,ls_dmnd_fills_from_sys.local_ccx,ls_dmnd_fills_from_sys.near_cache,ls_dmnd_fills_from_sys.far_cache,ls_dmnd_fills_from_sys.dram_io_near,ls_dmnd_fills_from_sys.dram_io_far"
G[f2]="ls_any_fills_from_sys.all,ls_dmnd_fills_from_sys.all,ls_hw_pf_dc_fills.all,ls_sw_pf_dc_fills.all,ls_mab_alloc.load_store_allocations,ls_stlf"
G[fe]="ic_tag_hit_miss.instruction_cache_miss,ic_cache_fill_l2,ic_cache_fill_sys,ex_ret_brn_misp,ex_ret_brn,resyncs_or_nc_redirects"
G[lk]="ls_locks.bus_lock,ls_l1_d_tlb_miss.all,ls_l1_d_tlb_miss.all_l2_miss,ls_tlb_flush.all,l2_cache_req_stat.ic_dc_miss_in_l2,l2_cache_req_stat.dc_access_in_l2"
G[l2]="l2_cache_req_stat.ls_rd_blk_c,l2_cache_req_stat.ls_rd_blk_x,l2_cache_req_stat.ls_rd_blk_l_hit_x,l2_cache_req_stat.ls_rd_blk_l_hit_s,l2_cache_req_stat.ls_rd_blk_cs,ls_dispatch.store_dispatch"
G[ld]="ls_dispatch.ld_dispatch,ls_dispatch.ld_st_dispatch,de_src_op_disp.op_cache,de_src_op_disp.decoder,de_src_op_disp.loop_buffer,ex_ret_ucode_ops"
G[af]="ls_any_fills_from_sys.local_l2,ls_any_fills_from_sys.local_ccx,ls_any_fills_from_sys.near_cache,ls_any_fills_from_sys.far_cache,ls_any_fills_from_sys.dram_io_near,ls_any_fills_from_sys.all"
G[st]="l2_request_g1.rd_blk_l,l2_request_g1.rd_blk_x,l2_request_g1.change_to_x,l2_request_g1.ls_rd_blk_c_s,ls_mab_alloc.all_allocations,ls_mab_alloc.hardware_prefetcher_allocations"
# USER-ONLY views of the top-down and queue-stall groups: the kernel share (recv/send, and the
# block/wake path of an under-fed server) is separated from the user-side op cost.
G[tdu]="ls_not_halted_cyc:u,ex_ret_ops:u,de_src_op_disp.all:u,de_no_dispatch_per_slot.no_ops_from_frontend:u,de_no_dispatch_per_slot.backend_stalls:u,de_no_dispatch_per_slot.smt_contention:u"
G[beu]="cycles:u,instructions:u,ex_no_retire.load_not_complete:u,ex_no_retire.not_complete:u,de_dis_dispatch_token_stalls1.store_queue_rsrc_stall:u,de_dis_dispatch_token_stalls2.retire_token_stall:u"
G[flu]="ls_dmnd_fills_from_sys.local_l2:u,ls_dmnd_fills_from_sys.local_ccx:u,ls_dmnd_fills_from_sys.dram_io_near:u,ls_any_fills_from_sys.local_ccx:u,l2_request_g1.rd_blk_x:u,l2_request_g1.change_to_x:u"
PMU_GROUPS=${PMU_GROUPS:-"td tdu be beu nr rs fl flu af f2 st fe lk l2 ld"}

# The SMT siblings of the SERVER cores are what matter for contamination.
expand_cores(){ local part; for part in $(echo "$1" | tr ',' ' '); do case "$part" in *-*) seq ${part%-*} ${part#*-};; *) echo "$part";; esac; done; }
sib_list(){ for c in $(expand_cores "$SRVCORES"); do if [ "$c" -lt 128 ]; then echo -n "$((c+128)) "; else echo -n "$((c-128)) "; fi; done; }
SIBS=$(sib_list)
# wait_quiet gates on the SERVER cpus and their SMT siblings only: other lanes' drivers on our driver cores
# merely under-feed the server, which the busy-fraction column records.
export MYCPUS="$SIBS $(expand_cores "$SRVCORES" | tr '\n' ' ')"
# Entries are filtered for emptiness: a trailing space in the list used to make the machine-wide "cpu"
# aggregate line match, so the "sibling" busy check measured the whole box and redid passes 4x.
cpu_stat_sum(){ awk -v list="$1" 'BEGIN{n=split(list,a," "); for(i=1;i<=n;i++) if (a[i]!="") want["cpu"a[i]]=1} ($1 in want){idle+=$5+$6; for(i=2;i<=NF;i++) tot+=$i} END{print idle, tot}' /proc/stat; }
SIBMAX=${SIBMAX:-2}
# FOREIGN TIME-SHARING on the server cores themselves (other lanes' unpinned load generators float onto
# them): per pass, foreign% = (busy ticks on SRVCORES - this server's own utime+stime) / total ticks.
# A pass above FOREIGNMAX is redone (up to 4x) and the value is recorded as CSV column 12 either way.
FOREIGNMAX=${FOREIGNMAX:-2}
SRVCPUS=$(expand_cores "$SRVCORES" | tr "\n" " ")
srv_ticks(){ awk '{print $14+$15}' /proc/$SRV/stat 2>/dev/null || echo 0; }

# Saturation check: DEBUG LBSIGNALS thread rows carry busy_ns idle_ns cpu_ns (fields 8-10) and
# wakes_sent/recv (14-15). The per-pass delta says how much of the counted on-CPU time was work
# (busy) versus the idle spin of an under-fed loop; an unsaturated cell inflates cycles/op.
lbsnap(){ /tmp/claude-1000/redis74/src/redis-cli -p "$PORT" debug lbsignals 2>/dev/null | awk '$1=="thread" {b+=$8; i+=$9; c+=$10; w+=$14; r+=$15} END {print b+0, i+0, c+0, w+0, r+0}'; }
# run the replay fleet once: N ops per connection; -> total ops, aggregate rate
fleet(){ local n=$1 shape=$2 ring=$3 pids=() c outf tot=0 rate=0
  outf=$(mktemp /tmp/cyclemap-fleet.XXXXXX)
  for c in $CLICORES; do
    taskset -c "$c" "$HERE/replay" "$PORT" "$shape" "$KEYLEN" "$n" "$PIPE" "$VLEN" "$ring" "${ORDER:-seq}" "${CONNS:-1}" >> "$outf" 2>/dev/null &
    pids+=($!)
  done
  wait "${pids[@]}"
  awk '{ops+=$1; if ($2>t) t=$2} END{printf "%d %.0f", ops, (t>0? ops/t : 0)}' "$outf"; rm -f "$outf"; }

pass(){ local n=$1 shape=$2 ring=$3 grp=$4 rep=$5 pf res ops rate sib try busy=0,0,0 foreign=0 k0 u0 k1 u1 s0 s1
  local t_start=$(date +%s)
  for try in $(seq 1 200); do
    wait_quiet
    pf=$(mktemp /tmp/cyclemap-perf.XXXXXX)
    read i0 t0 < <(cpu_stat_sum "$SIBS")
    read k0 u0 < <(cpu_stat_sum "$SRVCPUS"); s0=$(srv_ticks)
    read b0 d0 c0 w0 r0 < <(lbsnap)
    taskset -c "${CLICORES%% *}" perf stat -e "${G[$grp]}" -x, -o "$pf" -p "$SRV" -- bash -c "$(declare -f fleet); HERE='$HERE'; PORT=$PORT; CLICORES='$CLICORES'; KEYLEN=$KEYLEN; PIPE=$PIPE; VLEN=$VLEN; fleet $n $shape $ring" > /tmp/cyclemap-fleet-res.$$ 2>/dev/null
    read ops rate < /tmp/cyclemap-fleet-res.$$
    read i1 t1 < <(cpu_stat_sum "$SIBS")
    read k1 u1 < <(cpu_stat_sum "$SRVCPUS"); s1=$(srv_ticks)
    read b1 d1 c1 w1 r1 < <(lbsnap)
    foreign=$(awk -v a="$k0" -v b="$k1" -v c="$u0" -v d="$u1" -v e="$s0" -v f="$s1" 'BEGIN{ if (d-c>0) { x=100*((d-c)-(b-a)-(f-e))/(d-c); if (x<0) x=0; printf "%.1f", x } else print "0"}')
    busy=$(awk -v a="$b0" -v b="$b1" -v c="$d0" -v d="$d1" -v e="$c0" -v f="$c1" -v w="$w0" -v x="$w1" \
        'BEGIN{ db=b-a; di=d-c; dc=f-e; if (db+di>0) printf "%.3f,%.3f,%d", db/(db+di), (dc>0? (dc-db)/dc : 0), x-w; else print "0,0,0"}')
    sib=$(awk -v a="$i0" -v b="$i1" -v c="$t0" -v d="$t1" 'BEGIN{ if (d-c>0) printf "%.1f", 100*(1-(b-a)/(d-c)); else print "0"}')
    if awk -v s="$sib" -v m="$SIBMAX" -v f="$foreign" -v fm="$FOREIGNMAX" 'BEGIN{exit !(s>m || f>fm)}'; then
      echo "  server siblings busy ${sib}% / foreign time on server cores ${foreign}% during $shape/$grp/$n: redo ($try)" >&2
      if [ $(( $(date +%s) - t_start )) -lt "${PASS_BUDGET_S:-480}" ]; then rm -f "$pf"; sleep 1; continue; fi
      echo "  pass budget exhausted for $shape/$grp/$n: keeping a contaminated pass (flagged)" >&2
    fi
    break
  done
  grep -v '^#' "$pf" | awk -F, -v t="$TAG" -v r="$rep" -v g="$ring${ORDER_TAG:-}" -v s="$shape" -v gr="$grp" -v n="$ops" -v ra="$rate" -v sb="$sib" \
      -v bz="$busy" -v fo="$foreign" 'NF>=3 && $1 ~ /^[0-9]/ {print t","r","g","s","gr","$3","n","$1","ra","sb","bz","fo}' >> "$OUT"
  rm -f "$pf" /tmp/cyclemap-fleet-res.$$; }

for rep in $(seq 1 "$REPS"); do
  boot_srv "$BIN" "$LOG" --enable-debug-command yes ${EXTRA:-} || { echo "boot failed ($TAG rep $rep)"; exit 1; }
  for ring in $RINGS; do
    taskset -c "${CLICORES%% *}" "$HERE/replay" "$PORT" warm "$KEYLEN" 0 0 "$VLEN" "$ring" >/dev/null || { echo "warm failed"; stop_srv; exit 1; }
    fleet "$N1" set_over "$ring" >/dev/null
    # SETTLE (flip-auto cells): keep the server loaded until the controller has anchored, so the
    # maneuver's age sampling never overlaps a measured pass; log the controller state either way.
    if [ "${SETTLE_S:-0}" -gt 0 ]; then
      st=$(date +%s); while [ $(( $(date +%s) - st )) -lt "$SETTLE_S" ]; do fleet "$N1" set_over "$ring" >/dev/null; done
      /tmp/claude-1000/redis74/src/redis-cli -p "$PORT" info flipctl 2>/dev/null | tr -d '\r' | grep -E '^flipctl_(state|phase|triggers|fingerprint_triggers|signature_band)' | tr '\n' ' ' | sed "s/^/  $TAG rep$rep settle: /" >&2; echo >&2
    fi
    for shape in $SHAPES; do
      for grp in $PMU_GROUPS; do
        pass "$N1" "$shape" "$ring" "$grp" "$rep"
        pass "$N2" "$shape" "$ring" "$grp" "$rep"
      done
      echo "  $TAG rep$rep ring=$ring $shape done" >&2
    done
  done
  if [ "${SETTLE_S:-0}" -gt 0 ]; then
    /tmp/claude-1000/redis74/src/redis-cli -p "$PORT" info flipctl 2>/dev/null | tr -d '\r' | grep -E '^flipctl_(state|phase|triggers|fingerprint_triggers|signature_band|rate_band)' | tr '\n' ' ' | sed "s/^/  $TAG rep$rep end: /" >&2; echo >&2
    /tmp/claude-1000/redis74/src/redis-cli -p "$PORT" debug flipctl 2>/dev/null | tr -d '\r' | sed "s/^/  $TAG rep$rep dbg: /" >&2
  fi
  stop_srv
  grep -E "^t[0-9]+ +uni|^wb:" "$LOG" | tail -12 >&2
done
echo "done $TAG ($REPS reps) -> $OUT"
