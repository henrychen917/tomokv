#!/usr/bin/env bash
# Summarize reconfirm.tsv: median ops across rounds per (system,workload,payload,pipeline),
# the THredis-vs-redis ratio, and a verdict vs the paper's key targets.
TSV=${1:-/shared/Projects/overnight_sweep/reconfirm.tsv}
[ -f "$TSV" ] || { echo "no $TSV yet"; exit 0; }
echo "rounds so far: $(awk -F'\t' 'NR>1{print $1}' "$TSV"|sort -un|tail -1)   rows: $(($(wc -l <"$TSV")-1))"
echo
echo "=== median ops by system/workload/payload/pipeline (memtier) ==="
awk -F'\t' 'NR>1 && $2=="memtier" && $7+0>0 {k=$3"|"$4"|"$5"|"$6; v[k][n[k]++]=$7}
END{for(k in v){c=n[k]; for(i=0;i<c;i++)for(j=i+1;j<c;j++)if(v[k][j]+0<v[k][i]+0){t=v[k][i];v[k][i]=v[k][j];v[k][j]=t}
 split(k,a,"|"); printf "%-11s %-6s d%-5s P%-3s  median=%-11d (n=%d)\n",a[1],a[2],a[3],a[4],v[k][int(c/2)],c}}' "$TSV" \
 | sort -k2,2 -k3,3 -k4,4 -k1,1
echo
echo "=== HEADLINE: GET 32B P32 — THredis vs baselines (paper: redis~4.0M, v4~8.17M, keydb~3.12M, dfly~5.15M) ==="
awk -F'\t' 'NR>1 && $2=="memtier" && $4=="GET" && $5==32 && $6==32 && $7+0>0{v[$3][n[$3]++]=$7}
END{for(s in v){c=n[s];for(i=0;i<c;i++)for(j=i+1;j<c;j++)if(v[s][j]+0<v[s][i]+0){t=v[s][i];v[s][i]=v[s][j];v[s][j]=t}; m[s]=v[s][int(c/2)]}
 r=m["redis"]; for(s in m) printf "  %-11s %-11d  %.2fx redis\n",s,m[s],(r>0?m[s]/r:0)}' "$TSV" | sort -t= -k2 -rn
echo
echo "=== redis-benchmark tiers (median) ==="
awk -F'\t' 'NR>1 && $2=="rbench" && $7+0>0{k=$3"|"$4; v[k][n[k]++]=$7}
END{for(k in v){c=n[k];for(i=0;i<c;i++)for(j=i+1;j<c;j++)if(v[k][j]+0<v[k][i]+0){t=v[k][i];v[k][i]=v[k][j];v[k][j]=t}
 split(k,a,"|"); printf "  %-11s %-14s median=%d (n=%d)\n",a[1],a[2],v[k][int(c/2)],c}}' "$TSV" | sort -k2,2 -k1,1
echo
echo "=== YCSB (median throughput ops) ==="
awk -F'\t' 'NR>1 && $2=="ycsb" && $7+0>0{k=$3"|"$4; v[k][n[k]++]=$7}
END{for(k in v){c=n[k];for(i=0;i<c;i++)for(j=i+1;j<c;j++)if(v[k][j]+0<v[k][i]+0){t=v[k][i];v[k][i]=v[k][j];v[k][j]=t}
 split(k,a,"|"); printf "  %-11s %-8s median=%d (n=%d)\n",a[1],a[2],v[k][int(c/2)],c}}' "$TSV" | sort -k2,2 -k1,1
echo
echo "=== crashes/failures logged ==="; awk -F'\t' 'NR>1 && $10!=""{print $3,$2,$4,$10}' "$TSV" | sort | uniq -c | sort -rn | head
