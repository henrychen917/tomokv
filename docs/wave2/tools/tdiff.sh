#!/bin/bash
# tdiff.sh <objA> <objB> <mangled-symbol> -- call/relocation target multiset diff of one function
a=$1; b=$2; sym=$3
norm() { objdump -dr --no-show-raw-insn --disassemble="$sym" "$1" | sed -n '/^[0-9a-f]* <'"$sym"'>:/,/^$/p' | sed -E 's/^ *[0-9a-f]+:\t//; s/[0-9a-f]+ <([^>+]*)(\+0x[0-9a-f]+)?>/<\1>/g; s/#.*//; s/R_X86_64_[A-Z0-9_]+\t/R:/; s/\.(isra|part|constprop|cold)\.[0-9]+//g' | grep -o "R:[^ ]*\|call.*\|jmp *<.*" | sed -E 's/[-+]0x[0-9a-f]+$//' | sort | uniq -c; }
diff <(norm "$a") <(norm "$b") && echo "same targets ($(norm "$a" | wc -l) distinct)"
