#!/bin/bash
# fdiff.sh <objA> <objB> <mangled-symbol>  -- normalized disassembly diff of one function
a=$1; b=$2; sym=$3
norm() { objdump -dr --no-show-raw-insn --disassemble="$sym" "$1" | sed -n '/^[0-9a-f]* <'"$sym"'>:/,/^$/p' | sed -E 's/^ *[0-9a-f]+:\t//; s/[0-9a-f]+ <([^>+]*)(\+0x[0-9a-f]+)?>/<\1>/g; s/#.*//; s/R_X86_64_[A-Z0-9_]+\t/R:/; s/\.(isra|part|constprop|cold)\.[0-9]+//g' ; }
diff <(norm "$a") <(norm "$b")
