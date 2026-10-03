// Offline kind-A controls for the exbatch competition. There is no runtime switch.
// The five-byte NOP is replaced by an equal-width jump only in a copied ELF.
// Non-allocated records let the verifier enumerate every site, including inlines
// and both database namespaces. The label remains a compiler-visible CFG edge,
// so its stack/register contract is valid in the patched binary as well.
#pragma once
#if defined(__x86_64__) && defined(__GNUC__)
#define TOMO_EXBATCH_TWIN(label, item) \
    asm goto("1: .byte 0x0f,0x1f,0x44,0x00,0x00\n" \
             ".pushsection .exbatch_pad,\"\",@progbits\n" \
             ".balign 8\n.quad 1b, %l[" #label "], " #item "\n.popsection\n" \
             : : : "memory" : label)
#else
#define TOMO_EXBATCH_TWIN(label, item) do {} while (false)
#endif
