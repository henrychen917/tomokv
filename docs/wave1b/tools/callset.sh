#!/bin/bash
# callset.sh <objA> <objB> <mangled>  -- compare multisets of relocation targets + insn counts
a=$1; b=$2; s=$3
t() { objdump -dr --no-show-raw-insn --disassemble="$s" "$1" | sed -n '/^[0-9a-f]* <'"$s"'>:/,/^$/p' | grep -oP 'R_X86_64_\w+\s+\K\S+' | sed -E 's/[-+]0x[0-9a-f]+$//; s/\.LC[0-9]+/.LC/' | sort; }
n() { objdump -d --no-show-raw-insn --disassemble="$s" "$1" | sed -n '/^[0-9a-f]* <'"$s"'>:/,/^$/p' | grep -cP '^\s+[0-9a-f]+:\t'; }
echo "insns: $(n $a) vs $(n $b)"
diff <(t $a | uniq -c) <(t $b | uniq -c) && echo "relocation target multiset: identical"
