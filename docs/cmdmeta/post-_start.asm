
build/cmdmeta/POST/tomokv:     file format elf64-x86-64


Disassembly of section .init:

Disassembly of section .plt:

Disassembly of section .plt.got:

Disassembly of section .plt.sec:

Disassembly of section .text:

0000000000055980 <_start>:
   55980:	f3 0f 1e fa          	endbr64
   55984:	31 ed                	xor    %ebp,%ebp
   55986:	49 89 d1             	mov    %rdx,%r9
   55989:	5e                   	pop    %rsi
   5598a:	48 89 e2             	mov    %rsp,%rdx
   5598d:	48 83 e4 f0          	and    $0xfffffffffffffff0,%rsp
   55991:	50                   	push   %rax
   55992:	54                   	push   %rsp
   55993:	45 31 c0             	xor    %r8d,%r8d
   55996:	31 c9                	xor    %ecx,%ecx
   55998:	48 8d 3d 51 39 ff ff 	lea    -0xc6af(%rip),%rdi        # 492f0 <main>
   5599f:	ff 15 4b 56 82 00    	call   *0x82564b(%rip)        # 87aff0 <__libc_start_main@GLIBC_2.34>
   559a5:	f4                   	hlt

Disassembly of section .rlfence:

Disassembly of section .fini:
