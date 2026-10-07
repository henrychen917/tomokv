
build/ccfix4/instr-POST:     file format elf64-x86-64


Disassembly of section .init:

Disassembly of section .plt:

Disassembly of section .plt.got:

Disassembly of section .plt.sec:

Disassembly of section .text:

<_ZN12_GLOBAL__N_15callsERN4tomo9ThreadCtxE>:
	mov    $0x186a0,%eax
	data16 cs nopw 0x0(%rax,%rax,1)
	cmpl   $0x1,0x70(%rdi)
	jbe    <_ZN12_GLOBAL__N_15callsERN4tomo9ThreadCtxE+0x1e>
	mov    0x68(%rdi),%rdx
	incq   0x8(%rdx)
	incq   0x198(%rdi)
	dec    %eax
	jne    <_ZN12_GLOBAL__N_15callsERN4tomo9ThreadCtxE+0x10>
	ret

Disassembly of section .rlfence:

Disassembly of section .fini:
