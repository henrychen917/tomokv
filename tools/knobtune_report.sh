#!/usr/bin/env bash
# Summarize knobtune.tsv: median ops per config/cell across rounds, best config per cell,
# OFAT knob deltas vs thread baseline, leave-one-out deltas vs allopt_full, value sweeps.
# mawk-compatible (no gawk arrays-of-arrays): medians via string-append + split + insertion sort.
TSV=${1:-/shared/Projects/overnight_sweep/knobtune.tsv}
[ -f "$TSV" ] || { echo "no $TSV yet"; exit 0; }
CELLS="GET_d32_P32 GET_d256_P32 SET_d256_P32 GET_d1024_P32 MIX_d64_P16 HOT_G256 FB_ETC"
echo "rounds: $(awk -F'\t' 'NR>1{if($1+0>r)r=$1} END{print r}' "$TSV")   rows: $(($(wc -l <"$TSV")-1))"

# emit "cell|config|median|n" for every (config,cell)
med_table(){ awk -F'\t' 'NR>1 && $5+0>0 {k=$3"|"$4; v[k]=v[k]" "$5}
 END{for(k in v){m=split(v[k],a," ")
   for(i=2;i<=m;i++){t=a[i];j=i-1;while(j>0&&a[j]+0>t+0){a[j+1]=a[j];j--}a[j+1]=t}
   split(k,p,"|"); printf "%s|%s|%.0f|%d\n",p[2],p[1],a[int((m+1)/2)],m}}' "$TSV"; }
MT=$(med_table)

for cell in $CELLS; do
  echo; echo "=== $cell — configs ranked by median ops (best first) ==="
  echo "$MT" | awk -F'|' -v c="$cell" '$1==c{printf "%14.0f  %-18s (n=%d)\n",$3,$2,$4}' | sort -rn
done

echo; echo "=== OFAT: each knob ON vs thread baseline (2s_thr_io6w4 / 3s_thr_i4e4w2), % ==="
echo "$MT" | awk -F'|' '{md[$2"|"$1]=$3}
 END{split("GET_d32_P32 GET_d256_P32 SET_d256_P32 GET_d1024_P32 MIX_d64_P16 HOT_G256 FB_ETC",cl," ")
  for(ci in cl){c=cl[ci]; b2=md["2s_thr_io6w4|"c]; b3=md["3s_thr_i4e4w2|"c]
   for(k in md){split(k,p,"|"); if(p[2]!=c)continue
    if(p[1] ~ /^2s_knob/ && b2>0) printf "  %-17s %-14s %+7.1f%%\n",p[1],c,(md[k]-b2)/b2*100
    if(p[1] ~ /^3s_knob/ && b3>0) printf "  %-17s %-14s %+7.1f%%\n",p[1],c,(md[k]-b3)/b3*100}}}' | sort -k1,1 -k2,2

echo; echo "=== LEAVE-ONE-OUT: knob OFF vs allopt_full (NEGATIVE = that knob HELPS when others on), % ==="
echo "$MT" | awk -F'|' '{md[$2"|"$1]=$3}
 END{split("GET_d32_P32 GET_d256_P32 SET_d256_P32 GET_d1024_P32 MIX_d64_P16 HOT_G256 FB_ETC",cl," ")
  for(ci in cl){c=cl[ci]; f2=md["2s_allopt_full|"c]; f3=md["3s_allopt_full|"c]
   for(k in md){split(k,p,"|"); if(p[2]!=c)continue
    if(p[1] ~ /^2s_loo/ && f2>0) printf "  %-17s %-14s %+7.1f%%\n",p[1],c,(md[k]-f2)/f2*100
    if(p[1] ~ /^3s_loo/ && f3>0) printf "  %-17s %-14s %+7.1f%%\n",p[1],c,(md[k]-f3)/f3*100}}}' | sort -k1,1 -k2,2

echo; echo "=== VALUE sweeps (pf-w-nextop / num-cdb amounts), median ops ==="
echo "$MT" | awk -F'|' '$2 ~ /_val_/{printf "  %-17s %-14s %12.0f\n",$2,$1,$3}' | sort -k2,2 -k1,1

echo; echo "=== crashes/failures ==="
awk -F'\t' 'NR>1 && $6!=""{print $2,$3,$6}' "$TSV" | sort | uniq -c | sort -rn | head
