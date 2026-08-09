#!/usr/bin/env bash
# Role-scoped AMD resctrl/CAT harness for TomoKV.
#
# This script never starts a server or a load generator.  It only mounts/inspects
# resctrl, assigns already-running TIDs, applies an explicit L3 mask, and reads
# CQM/MBM counters.  Run the server in tomokv-thread-mode=static: a role flip
# changes the thread name, but resctrl membership does not follow that rename.

set -euo pipefail

RESCTRL=${RESCTRL:-/sys/fs/resctrl}
IO_GROUP=$RESCTRL/tomo_io
EX_GROUP=$RESCTRL/tomo_ex
AUX_GROUP=$RESCTRL/tomo_aux
LG_GROUP=$RESCTRL/tomo_loadgen

usage() {
    printf '%s\n' \
        "usage:" \
        "  $0 mount" \
        "  $0 info" \
        "  $0 show-tids SERVER_PID" \
        "  $0 setup SERVER_PID [LOADGEN_PID]" \
        "  $0 apply shared [NOISE_WAYS]" \
        "  $0 apply split IO_WAYS EX_WAYS [io-low|io-high] [NOISE_WAYS]" \
        "  $0 apply overlap ROLE_WAYS [low|high] [NOISE_WAYS]" \
        "  $0 sample [SECONDS [INTERVAL_SECONDS]]" \
        "  $0 reset" \
        "" \
        "setup discovers tomo-io-NNN/tomo-ex-NNN names under SERVER_PID; the" \
        "main SERVER_PID is fixed IO0. IO_TIDS/EX_TIDS may override discovery." \
        "NOISE_WAYS reserves low ways for a local load generator and server" \
        "background threads. Without it, split refuses a populated loadgen group."
}

die() {
    printf 'cache_role_resctrl: %s\n' "$*" >&2
    exit 1
}

need_root() {
    (( EUID == 0 )) || die "this operation must run as root"
}

is_mounted() {
    awk -v p="$RESCTRL" '$2 == p && $3 == "resctrl" { found=1 } END { exit !found }' /proc/mounts
}

need_mounted() {
    is_mounted || die "$RESCTRL is not a mounted resctrl filesystem (run '$0 mount')"
    [[ -r $RESCTRL/info/L3/cbm_mask ]] || die "L3 CAT is not exposed at $RESCTRL/info/L3"
}

mount_resctrl() {
    need_root
    mkdir -p "$RESCTRL"
    if ! is_mounted; then
        mount -t resctrl resctrl "$RESCTRL"
    fi
    need_mounted
    printf 'mounted %s; L3 cbm_mask=%s min_cbm_bits=%s\n' \
        "$RESCTRL" "$(<"$RESCTRL/info/L3/cbm_mask")" \
        "$(<"$RESCTRL/info/L3/min_cbm_bits")"
}

cbm_geometry() {
    local cbm_hex
    cbm_hex=$(<"$RESCTRL/info/L3/cbm_mask")
    cbm_hex=${cbm_hex#0x}
    CBM_FULL=$((16#$cbm_hex))
    CBM_WAYS=0
    local v=$CBM_FULL
    while (( v != 0 )); do
        CBM_WAYS=$(( CBM_WAYS + (v & 1) ))
        v=$(( v >> 1 ))
    done
    (( CBM_WAYS > 0 && CBM_WAYS < 63 )) || die "unsupported cbm_mask $cbm_hex"
    (( CBM_FULL == (1 << CBM_WAYS) - 1 )) || die "non-contiguous cbm_mask $cbm_hex is unsupported by this harness"
    CBM_MIN=$(<"$RESCTRL/info/L3/min_cbm_bits")
}

l3_domains() {
    local line payload entry
    local -a entries=()
    line=$(awk -F: '$1 == "L3" { print; exit }' "$RESCTRL/schemata")
    [[ -n $line ]] || die "no L3 line in $RESCTRL/schemata"
    payload=${line#L3:}
    IFS=';' read -r -a entries <<< "$payload"
    L3_IDS=()
    for entry in "${entries[@]}"; do
        L3_IDS+=("${entry%%=*}")
    done
    (( ${#L3_IDS[@]} > 0 )) || die "no L3 cache domains found"
}

mask_line() {
    local mask=$1 id out="" sep=""
    for id in "${L3_IDS[@]}"; do
        out+="${sep}${id}=$(printf '%x' "$mask")"
        sep=';'
    done
    printf 'L3:%s\n' "$out"
}

set_group_mask() {
    local group=$1 mask=$2 ways=0 v=$2
    while (( v != 0 )); do
        ways=$(( ways + (v & 1) ))
        v=$(( v >> 1 ))
    done
    (( ways >= CBM_MIN )) || die "mask $(printf '%x' "$mask") has $ways ways; hardware minimum is $CBM_MIN"
    mask_line "$mask" > "$group/schemata"
}

group_has_tasks() {
    [[ -d $1 ]] || return 1
    local tids
    tids=$(<"$1/tasks")
    [[ -n $tids ]]
}

normalize_tids() {
    tr ',:' '  ' <<< "$1"
}

show_tids() {
    local pid=$1 task tid comm role
    [[ -d /proc/$pid/task ]] || die "PID $pid has no task directory"
    printf 'tid\tcomm\trole\n'
    for task in /proc/"$pid"/task/*; do
        tid=${task##*/}
        comm=$(<"$task/comm")
        case "$comm" in
            tomo-io-*) role=IO ;;
            tomo-ex-*) role=EX ;;
            *) if [[ $tid == "$pid" ]]; then role=IO0-main; else role=AUX; fi ;;
        esac
        printf '%s\t%s\t%s\n' "$tid" "$comm" "$role"
    done | sort -n
}

write_tid() {
    local group=$1 tid=$2
    [[ -d /proc/$tid ]] || die "TID $tid exited before assignment"
    printf '%s\n' "$tid" > "$group/tasks"
}

setup_groups() {
    need_root
    need_mounted
    local pid=$1 lg_pid=${2:-} task tid comm
    [[ -d /proc/$pid/task ]] || die "server PID $pid has no task directory"
    cbm_geometry
    l3_domains

    local group
    for group in "$IO_GROUP" "$EX_GROUP" "$AUX_GROUP" "$LG_GROUP"; do
        [[ ! -e $group ]] || die "$group already exists; run '$0 reset' before a new setup"
    done
    mkdir "$IO_GROUP" "$EX_GROUP" "$AUX_GROUP"
    set_group_mask "$IO_GROUP" "$CBM_FULL"
    set_group_mask "$EX_GROUP" "$CBM_FULL"
    set_group_mask "$AUX_GROUP" "$CBM_FULL"

    local -a io=() ex=() aux=()
    if [[ -n ${IO_TIDS:-} || -n ${EX_TIDS:-} ]]; then
        [[ -n ${IO_TIDS:-} && -n ${EX_TIDS:-} ]] || die "set both IO_TIDS and EX_TIDS, or neither"
        read -r -a io <<< "$(normalize_tids "$IO_TIDS")"
        read -r -a ex <<< "$(normalize_tids "$EX_TIDS")"
        local x
        for x in "${io[@]}" "${ex[@]}"; do
            [[ -e /proc/$pid/task/$x ]] || die "explicit role TID $x is not a thread of server PID $pid"
        done
        local i e
        for i in "${io[@]}"; do
            for e in "${ex[@]}"; do
                [[ $i != "$e" ]] || die "TID $i appears in both IO_TIDS and EX_TIDS"
            done
        done
        local main_is_io=0
        for i in "${io[@]}"; do
            if [[ $i == "$pid" ]]; then main_is_io=1; fi
        done
        (( main_is_io )) || die "server PID/main TID $pid must be included in IO_TIDS as fixed IO0"
        for task in /proc/"$pid"/task/*; do
            tid=${task##*/}
            local found=0
            for x in "${io[@]}" "${ex[@]}"; do [[ $tid == "$x" ]] && found=1; done
            (( found )) || aux+=("$tid")
        done
    else
        io+=("$pid")                         # fixed main-thread IO0 endpoint
        for task in /proc/"$pid"/task/*; do
            tid=${task##*/}
            [[ $tid == "$pid" ]] && continue
            comm=$(<"$task/comm")
            case "$comm" in
                tomo-io-*) io+=("$tid") ;;
                tomo-ex-*) ex+=("$tid") ;;
                *) aux+=("$tid") ;;
            esac
        done
    fi
    (( ${#io[@]} > 0 )) || die "no IO TIDs found"
    (( ${#ex[@]} > 0 )) || die "no EX TIDs found; use the naming patch or explicit EX_TIDS"

    for tid in "${io[@]}"; do write_tid "$IO_GROUP" "$tid"; done
    for tid in "${ex[@]}"; do write_tid "$EX_GROUP" "$tid"; done
    for tid in "${aux[@]}"; do write_tid "$AUX_GROUP" "$tid"; done

    if [[ -n $lg_pid ]]; then
        [[ -d /proc/$lg_pid/task ]] || die "load-generator PID $lg_pid has no task directory"
        mkdir "$LG_GROUP"
        set_group_mask "$LG_GROUP" "$CBM_FULL"
        for task in /proc/"$lg_pid"/task/*; do write_tid "$LG_GROUP" "${task##*/}"; done
    fi

    printf 'assigned server %s: IO=%d EX=%d AUX=%d' "$pid" "${#io[@]}" "${#ex[@]}" "${#aux[@]}"
    if [[ -n $lg_pid ]]; then printf ' LOADGEN=%s' "$lg_pid"; fi
    printf '\n'
    show_tids "$pid"
}

apply_masks() {
    need_root
    need_mounted
    [[ -d $IO_GROUP && -d $EX_GROUP ]] || die "run setup first"
    cbm_geometry
    l3_domains
    local mode=${1:-}
    shift || true
    local io_mask ex_mask noise_mask=0 noise_ways=0

    case "$mode" in
        shared)
            noise_ways=${1:-0}
            (( noise_ways >= 0 && noise_ways < CBM_WAYS )) || die "bad NOISE_WAYS $noise_ways"
            (( noise_ways == 0 || noise_ways >= CBM_MIN )) || die "NOISE_WAYS is below min_cbm_bits=$CBM_MIN"
            if (( noise_ways == 0 )); then
                io_mask=$CBM_FULL
                ex_mask=$CBM_FULL
            else
                noise_mask=$(( (1 << noise_ways) - 1 ))
                io_mask=$(( CBM_FULL ^ noise_mask ))
                ex_mask=$io_mask
            fi
            ;;
        split)
            (( $# >= 2 )) || die "apply split needs IO_WAYS EX_WAYS"
            local io_ways=$1 ex_ways=$2 order=${3:-io-low}
            noise_ways=${4:-0}
            (( io_ways >= CBM_MIN && ex_ways >= CBM_MIN && noise_ways >= 0 )) || die "a requested partition is below min_cbm_bits=$CBM_MIN"
            (( noise_ways == 0 || noise_ways >= CBM_MIN )) || die "NOISE_WAYS is below min_cbm_bits=$CBM_MIN"
            (( io_ways + ex_ways + noise_ways == CBM_WAYS )) ||
                die "IO($io_ways)+EX($ex_ways)+NOISE($noise_ways) must equal $CBM_WAYS ways"
            noise_mask=$(( noise_ways == 0 ? 0 : (1 << noise_ways) - 1 ))
            local base=$noise_ways
            case "$order" in
                io-low)
                    io_mask=$(( ((1 << io_ways) - 1) << base ))
                    ex_mask=$(( ((1 << ex_ways) - 1) << (base + io_ways) ))
                    ;;
                io-high)
                    ex_mask=$(( ((1 << ex_ways) - 1) << base ))
                    io_mask=$(( ((1 << io_ways) - 1) << (base + ex_ways) ))
                    ;;
                *) die "order must be io-low or io-high" ;;
            esac
            if (( noise_ways == 0 )) && group_has_tasks "$LG_GROUP"; then
                die "local loadgen has a full overlapping mask; reserve NOISE_WAYS or use a remote loadgen"
            fi
            ;;
        overlap)
            (( $# >= 1 )) || die "apply overlap needs ROLE_WAYS"
            local role_ways=$1 where=${2:-low}
            noise_ways=${3:-0}
            (( role_ways >= CBM_MIN && noise_ways >= 0 && role_ways + noise_ways <= CBM_WAYS )) ||
                die "bad ROLE_WAYS/NOISE_WAYS for a $CBM_WAYS-way cache"
            (( noise_ways == 0 || noise_ways >= CBM_MIN )) || die "NOISE_WAYS is below min_cbm_bits=$CBM_MIN"
            noise_mask=$(( noise_ways == 0 ? 0 : (1 << noise_ways) - 1 ))
            case "$where" in
                low)  io_mask=$(( ((1 << role_ways) - 1) << noise_ways )) ;;
                high) io_mask=$(( ((1 << role_ways) - 1) << (CBM_WAYS - role_ways) )) ;;
                *) die "overlap placement must be low or high" ;;
            esac
            ex_mask=$io_mask
            if (( noise_ways == 0 )) && group_has_tasks "$LG_GROUP"; then
                die "local loadgen has a full mask outside the overlap control; reserve NOISE_WAYS or use a remote loadgen"
            fi
            ;;
        *) die "apply mode must be shared, split, or overlap" ;;
    esac

    set_group_mask "$IO_GROUP" "$io_mask"
    set_group_mask "$EX_GROUP" "$ex_mask"
    if (( noise_ways > 0 )); then
        [[ -d $AUX_GROUP ]] && set_group_mask "$AUX_GROUP" "$noise_mask"
        [[ -d $LG_GROUP ]] && set_group_mask "$LG_GROUP" "$noise_mask"
    else
        # Background server work is rare in the measurement configuration, but must not retain a
        # full mask that defeats an exclusive role split. Attribute its allocations to IO's ways.
        [[ -d $AUX_GROUP ]] && set_group_mask "$AUX_GROUP" "$io_mask"
        [[ -d $LG_GROUP ]] && set_group_mask "$LG_GROUP" "$CBM_FULL"
    fi

    printf 'applied %-7s IO=%x EX=%x' "$mode" "$io_mask" "$ex_mask"
    if (( noise_ways > 0 )); then printf ' AUX/LOADGEN=%x' "$noise_mask"; fi
    printf ' (%d total ways, min %d)\n' "$CBM_WAYS" "$CBM_MIN"
    printf '%s\n' 'CAT affects new allocations only; wait for occupancy/throughput to settle before measuring.'
}

show_info() {
    need_mounted
    cbm_geometry
    l3_domains
    printf 'L3 domains: %s\n' "${L3_IDS[*]}"
    printf 'cbm_mask=%x ways=%d min_cbm_bits=%d\n' "$CBM_FULL" "$CBM_WAYS" "$CBM_MIN"
    if [[ -r $RESCTRL/info/L3_MON/mon_features ]]; then
        printf 'monitor features:\n'
        sed 's/^/  /' "$RESCTRL/info/L3_MON/mon_features"
    else
        printf 'monitor features: unavailable\n'
    fi
    local group
    for group in "$IO_GROUP" "$EX_GROUP" "$AUX_GROUP" "$LG_GROUP"; do
        [[ -d $group ]] || continue
        printf '%s: tasks=%s schemata=%s\n' "${group##*/}" \
            "$(tr '\n' ',' < "$group/tasks" | sed 's/,$//')" \
            "$(awk -F: '$1 == "L3" { print }' "$group/schemata")"
    done
}

snapshot() {
    local stamp group mon domain occ total local
    stamp=$(date +%s.%N)
    for group in "$IO_GROUP" "$EX_GROUP" "$AUX_GROUP" "$LG_GROUP"; do
        [[ -d $group/mon_data ]] || continue
        for mon in "$group"/mon_data/mon_L3_*; do
            [[ -d $mon ]] || continue
            domain=${mon##*/mon_L3_}
            occ=NA; total=NA; local=NA
            [[ -r $mon/llc_occupancy ]] && occ=$(<"$mon/llc_occupancy")
            [[ -r $mon/mbm_total_bytes ]] && total=$(<"$mon/mbm_total_bytes")
            [[ -r $mon/mbm_local_bytes ]] && local=$(<"$mon/mbm_local_bytes")
            printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$stamp" "${group##*/}" "$domain" "$occ" "$total" "$local"
        done
    done
}

sample_groups() {
    need_mounted
    local duration=${1:-30} interval=${2:-1}
    [[ $duration =~ ^[0-9]+$ && $duration -gt 0 ]] || die "SECONDS must be a positive integer"
    [[ $interval =~ ^[0-9]+([.][0-9]+)?$ ]] || die "INTERVAL_SECONDS must be positive"
    awk -v i="$interval" 'BEGIN { exit !(i > 0) }' || die "INTERVAL_SECONDS must be greater than zero"
    printf 'time\tgroup\tdomain\tllc_occupancy_B\tmbm_total_B\tmbm_local_B\n'
    local start=$SECONDS
    while (( SECONDS - start <= duration )); do
        snapshot
        sleep "$interval"
    done
}

reset_groups() {
    need_root
    need_mounted
    local group tid
    for group in "$IO_GROUP" "$EX_GROUP" "$AUX_GROUP" "$LG_GROUP"; do
        [[ -d $group ]] || continue
        while read -r tid; do
            [[ -n $tid ]] && printf '%s\n' "$tid" > "$RESCTRL/tasks" || true
        done < "$group/tasks"
    done
    for group in "$IO_GROUP" "$EX_GROUP" "$AUX_GROUP" "$LG_GROUP"; do
        [[ -d $group ]] && rmdir "$group"
    done
    printf 'removed TomoKV resctrl groups; surviving tasks returned to the root group\n'
}

cmd=${1:-}
case "$cmd" in
    mount) mount_resctrl ;;
    info) show_info ;;
    show-tids) (( $# == 2 )) || { usage; exit 2; }; show_tids "$2" ;;
    setup) (( $# == 2 || $# == 3 )) || { usage; exit 2; }; setup_groups "$2" "${3:-}" ;;
    apply) shift; apply_masks "$@" ;;
    sample) shift; sample_groups "$@" ;;
    reset) reset_groups ;;
    *) usage; exit 2 ;;
esac
