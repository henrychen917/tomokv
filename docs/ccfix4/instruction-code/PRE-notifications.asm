
build/ccfix4/instr-PRE:     file format elf64-x86-64


Disassembly of section .init:

Disassembly of section .plt:

Disassembly of section .plt.got:

Disassembly of section .plt.sec:

Disassembly of section .text:

<_ZN12_GLOBAL__N_113notificationsERN4tomo5ShardEj>:
	push   %r13
	push   %r12
	push   %rbp
	mov    %rdi,%r13
	push   %rbx
	mov    %esi,%r12d
	mov    $0x186a0,%ebx
	xor    %ebp,%ebp
	sub    $0x8,%rsp
	nopw   0x0(%rax,%rax,1)
	mov    %r12d,%esi
	mov    %r13,%rdi
	call   <_ZN4tomo19notify_flat_enabledEPvj>
	movzbl %al,%eax
	add    %rax,%rbp
	dec    %ebx
	jne    <_ZN12_GLOBAL__N_113notificationsERN4tomo5ShardEj+0x20>
	mov    %rbp,0x3dfc64(%rip)        # <_ZN12_GLOBAL__N_18consumedE>
	add    $0x8,%rsp
	pop    %rbx
	pop    %rbp
	pop    %r12
	pop    %r13
	ret

Disassembly of section .rlfence:

Disassembly of section .fini:
