
/home/user/Projects/cx-ntfix/build/ntfix2/trials/db0_src_core_reorder.o.351109036952a1d4.o:     file format elf64-x86-64


Disassembly of section .text._ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv:

0000000000000000 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv>:
   0:	f3 0f 1e fa          	endbr64
   4:	41 57                	push   %r15
   6:	41 56                	push   %r14
   8:	41 55                	push   %r13
   a:	41 54                	push   %r12
   c:	55                   	push   %rbp
   d:	53                   	push   %rbx
   e:	48 89 fb             	mov    %rdi,%rbx
  11:	48 83 ec 28          	sub    $0x28,%rsp
  15:	4c 8b 27             	mov    (%rdi),%r12
  18:	64 48 8b 04 25 28 00 	mov    %fs:0x28,%rax
  1f:	00 00 
  21:	48 89 44 24 18       	mov    %rax,0x18(%rsp)
  26:	31 c0                	xor    %eax,%eax
  28:	80 bf 98 01 00 00 00 	cmpb   $0x0,0x198(%rdi)
  2f:	74 1c                	je     4d <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x4d>
  31:	41 0f b6 84 24 d0 3f 	movzbl 0x13fd0(%r12),%eax
  38:	01 00 
  3a:	3c 04                	cmp    $0x4,%al
  3c:	0f 84 1e 02 00 00    	je     260 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x260>
  42:	3c 01                	cmp    $0x1,%al
  44:	0f 84 16 02 00 00    	je     260 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x260>
  4a:	4c 8b 27             	mov    (%rdi),%r12
  4d:	48 89 e6             	mov    %rsp,%rsi
  50:	31 ff                	xor    %edi,%edi
  52:	c5 f9 ef c0          	vpxor  %xmm0,%xmm0,%xmm0
  56:	4c 8b ab d8 16 00 00 	mov    0x16d8(%rbx),%r13
  5d:	4c 8b 73 08          	mov    0x8(%rbx),%r14
  61:	c5 f9 7f 04 24       	vmovdqa %xmm0,(%rsp)
  66:	e8 00 00 00 00       	call   6b <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x6b>
			67: R_X86_64_PLT32	clock_gettime-0x4
  6b:	48 8b 4c 24 08       	mov    0x8(%rsp),%rcx
  70:	48 69 34 24 e8 03 00 	imul   $0x3e8,(%rsp),%rsi
  77:	00 
  78:	48 b8 db 34 b6 d7 82 	movabs $0x431bde82d7b634db,%rax
  7f:	de 1b 43 
  82:	48 f7 e9             	imul   %rcx
  85:	48 c1 f9 3f          	sar    $0x3f,%rcx
  89:	48 c1 fa 12          	sar    $0x12,%rdx
  8d:	48 29 ca             	sub    %rcx,%rdx
  90:	48 01 d6             	add    %rdx,%rsi
  93:	80 bb 9a 01 00 00 00 	cmpb   $0x0,0x19a(%rbx)
  9a:	48 89 b3 58 01 00 00 	mov    %rsi,0x158(%rbx)
  a1:	0f 85 99 01 00 00    	jne    240 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x240>
  a7:	48 83 bb d8 16 00 00 	cmpq   $0x0,0x16d8(%rbx)
  ae:	00 
  af:	0f 84 a1 01 00 00    	je     256 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x256>
  b5:	48 89 df             	mov    %rbx,%rdi
  b8:	e8 00 00 00 00       	call   bd <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0xbd>
			b9: R_X86_64_PLT32	_ZN8tomo_db07ExLoopTILb1EE29compact_local_read_tombstonesEv-0x4
  bd:	48 83 bb d8 16 00 00 	cmpq   $0x0,0x16d8(%rbx)
  c4:	00 
  c5:	0f 84 e8 01 00 00    	je     2b3 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2b3>
  cb:	be ff ff ff ff       	mov    $0xffffffff,%esi
  d0:	48 89 df             	mov    %rbx,%rdi
  d3:	e8 00 00 00 00       	call   d8 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0xd8>
			d4: R_X86_64_PLT32	_ZN8tomo_db07ExLoopTILb1EE30drain_local_reads_bounded_implILb0EEEjj-0x4
  d8:	48 8b bb d8 16 00 00 	mov    0x16d8(%rbx),%rdi
  df:	89 c5                	mov    %eax,%ebp
  e1:	48 85 ff             	test   %rdi,%rdi
  e4:	0f 84 c9 01 00 00    	je     2b3 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2b3>
  ea:	80 7f 21 00          	cmpb   $0x0,0x21(%rdi)
  ee:	0f 84 b6 00 00 00    	je     1aa <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1aa>
  f4:	44 8b 57 18          	mov    0x18(%rdi),%r10d
  f8:	44 8b 47 10          	mov    0x10(%rdi),%r8d
  fc:	45 31 c9             	xor    %r9d,%r9d
  ff:	45 85 d2             	test   %r10d,%r10d
 102:	0f 84 87 00 00 00    	je     18f <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x18f>
 108:	31 f6                	xor    %esi,%esi
 10a:	66 0f 1f 44 00 00    	nopw   0x0(%rax,%rax,1)
 110:	41 8d 14 30          	lea    (%r8,%rsi,1),%edx
 114:	81 e2 ff 03 00 00    	and    $0x3ff,%edx
 11a:	48 89 d0             	mov    %rdx,%rax
 11d:	48 c1 e0 04          	shl    $0x4,%rax
 121:	48 03 07             	add    (%rdi),%rax
 124:	48 8b 08             	mov    (%rax),%rcx
 127:	4c 8b 58 08          	mov    0x8(%rax),%r11
 12b:	48 85 c9             	test   %rcx,%rcx
 12e:	74 55                	je     185 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x185>
 130:	48 8b 81 c0 00 00 00 	mov    0xc0(%rcx),%rax
 137:	4c 8b b9 00 01 00 00 	mov    0x100(%rcx),%r15
 13e:	4d 89 d8             	mov    %r11,%r8
 141:	4d 29 f8             	sub    %r15,%r8
 144:	4c 29 f8             	sub    %r15,%rax
 147:	49 39 c0             	cmp    %rax,%r8
 14a:	44 8b 47 10          	mov    0x10(%rdi),%r8d
 14e:	73 35                	jae    185 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x185>
 150:	48 8b 81 08 01 00 00 	mov    0x108(%rcx),%rax
 157:	4c 0f a3 d8          	bt     %r11,%rax
 15b:	73 28                	jae    185 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x185>
 15d:	43 8d 04 08          	lea    (%r8,%r9,1),%eax
 161:	41 ff c1             	inc    %r9d
 164:	25 ff 03 00 00       	and    $0x3ff,%eax
 169:	49 89 c7             	mov    %rax,%r15
 16c:	49 c1 e7 04          	shl    $0x4,%r15
 170:	4c 03 3f             	add    (%rdi),%r15
 173:	49 89 0f             	mov    %rcx,(%r15)
 176:	48 8b 4f 08          	mov    0x8(%rdi),%rcx
 17a:	4d 89 5f 08          	mov    %r11,0x8(%r15)
 17e:	0f b6 14 11          	movzbl (%rcx,%rdx,1),%edx
 182:	88 14 01             	mov    %dl,(%rcx,%rax,1)
 185:	ff c6                	inc    %esi
 187:	41 39 f2             	cmp    %esi,%r10d
 18a:	75 84                	jne    110 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x110>
 18c:	45 01 c8             	add    %r9d,%r8d
 18f:	41 81 e0 ff 03 00 00 	and    $0x3ff,%r8d
 196:	c6 47 21 00          	movb   $0x0,0x21(%rdi)
 19a:	c4 c1 79 6e c8       	vmovd  %r8d,%xmm1
 19f:	c4 c3 71 22 c1 01    	vpinsrd $0x1,%r9d,%xmm1,%xmm0
 1a5:	c5 f9 d6 47 14       	vmovq  %xmm0,0x14(%rdi)
 1aa:	48 89 df             	mov    %rbx,%rdi
 1ad:	e8 00 00 00 00       	call   1b2 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1b2>
			1ae: R_X86_64_PLT32	_ZN8tomo_db07ExLoopTILb1EE8r7_sweepILj32ELb1ELb0ELb0EEEjv-0x4
 1b2:	48 8b bb d8 16 00 00 	mov    0x16d8(%rbx),%rdi
 1b9:	01 c5                	add    %eax,%ebp
 1bb:	48 85 ff             	test   %rdi,%rdi
 1be:	74 0b                	je     1cb <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1cb>
 1c0:	48 83 c7 38          	add    $0x38,%rdi
 1c4:	e8 00 00 00 00       	call   1c9 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1c9>
			1c5: R_X86_64_PLT32	_ZN8tomo_db022ReadLocalDeferredQueue11drain_readyEv-0x4
 1c9:	01 c5                	add    %eax,%ebp
 1cb:	85 ed                	test   %ebp,%ebp
 1cd:	74 13                	je     1e2 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1e2>
 1cf:	8b 83 10 01 00 00    	mov    0x110(%rbx),%eax
 1d5:	85 c0                	test   %eax,%eax
 1d7:	79 09                	jns    1e2 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1e2>
 1d9:	48 8d 7b 10          	lea    0x10(%rbx),%rdi
 1dd:	e8 00 00 00 00       	call   1e2 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1e2>
			1de: R_X86_64_PLT32	io_uring_submit_and_get_events-0x4
 1e2:	4d 85 ed             	test   %r13,%r13
 1e5:	75 29                	jne    210 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x210>
 1e7:	48 8b 44 24 18       	mov    0x18(%rsp),%rax
 1ec:	64 48 2b 04 25 28 00 	sub    %fs:0x28,%rax
 1f3:	00 00 
 1f5:	0f 85 a3 00 00 00    	jne    29e <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x29e>
 1fb:	48 83 c4 28          	add    $0x28,%rsp
 1ff:	89 e8                	mov    %ebp,%eax
 201:	5b                   	pop    %rbx
 202:	5d                   	pop    %rbp
 203:	41 5c                	pop    %r12
 205:	41 5d                	pop    %r13
 207:	41 5e                	pop    %r14
 209:	41 5f                	pop    %r15
 20b:	c3                   	ret
 20c:	0f 1f 40 00          	nopl   0x0(%rax)
 210:	49 8b 84 24 d8 75 01 	mov    0x175d8(%r12),%rax
 217:	00 
 218:	48 85 c0             	test   %rax,%rax
 21b:	0f 84 92 00 00 00    	je     2b3 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2b3>
 221:	48 8b 00             	mov    (%rax),%rax
 224:	48 85 c0             	test   %rax,%rax
 227:	0f 88 86 00 00 00    	js     2b3 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2b3>
 22d:	49 8b 96 60 05 00 00 	mov    0x560(%r14),%rdx
 234:	48 85 d2             	test   %rdx,%rdx
 237:	74 7a                	je     2b3 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2b3>
 239:	48 87 02             	xchg   %rax,(%rdx)
 23c:	eb a9                	jmp    1e7 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1e7>
 23e:	66 90                	xchg   %ax,%ax
 240:	48 89 df             	mov    %rbx,%rdi
 243:	e8 00 00 00 00       	call   248 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x248>
			244: R_X86_64_PLT32	_ZN8tomo_db07ExLoopTILb1EE39read_local_rebind_owned_shards_after_lbEv-0x4
 248:	48 83 bb d8 16 00 00 	cmpq   $0x0,0x16d8(%rbx)
 24f:	00 
 250:	0f 85 5f fe ff ff    	jne    b5 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0xb5>
 256:	31 ed                	xor    %ebp,%ebp
 258:	e9 4d ff ff ff       	jmp    1aa <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1aa>
 25d:	0f 1f 00             	nopl   (%rax)
 260:	48 8b 44 24 18       	mov    0x18(%rsp),%rax
 265:	64 48 2b 04 25 28 00 	sub    %fs:0x28,%rax
 26c:	00 00 
 26e:	75 2e                	jne    29e <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x29e>
 270:	48 83 c4 28          	add    $0x28,%rsp
 274:	48 89 df             	mov    %rbx,%rdi
 277:	5b                   	pop    %rbx
 278:	5d                   	pop    %rbp
 279:	41 5c                	pop    %r12
 27b:	41 5d                	pop    %r13
 27d:	41 5e                	pop    %r14
 27f:	41 5f                	pop    %r15
 281:	e9 00 00 00 00       	jmp    286 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x286>
			282: R_X86_64_PLT32	_ZN8tomo_db07ExLoopTILb1EE18r7_fused_pass_implILj32ELb1ELb0ELb0EEEjv-0x4
 286:	4d 85 ed             	test   %r13,%r13
 289:	75 18                	jne    2a3 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2a3>
 28b:	c5 f8 77             	vzeroupper
 28e:	48 8b 44 24 18       	mov    0x18(%rsp),%rax
 293:	64 48 2b 04 25 28 00 	sub    %fs:0x28,%rax
 29a:	00 00 
 29c:	74 33                	je     2d1 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2d1>
 29e:	e8 00 00 00 00       	call   2a3 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2a3>
			29f: R_X86_64_PLT32	__stack_chk_fail-0x4
 2a3:	49 8b 84 24 d8 75 01 	mov    0x175d8(%r12),%rax
 2aa:	00 
 2ab:	48 85 c0             	test   %rax,%rax
 2ae:	75 11                	jne    2c1 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2c1>
 2b0:	c5 f8 77             	vzeroupper
 2b3:	e8 00 00 00 00       	call   2b8 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2b8>
			2b4: R_X86_64_PLT32	abort-0x4
 2b8:	f3 0f 1e fa          	endbr64
 2bc:	48 89 c3             	mov    %rax,%rbx
 2bf:	eb c5                	jmp    286 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x286>
 2c1:	48 8b 30             	mov    (%rax),%rsi
 2c4:	4c 89 f7             	mov    %r14,%rdi
 2c7:	c5 f8 77             	vzeroupper
 2ca:	e8 00 00 00 00       	call   2cf <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2cf>
			2cb: R_X86_64_PLT32	_ZN8tomo_db09ThreadCtx23publish_read_local_tickEm-0x4
 2cf:	eb bd                	jmp    28e <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x28e>
 2d1:	48 89 df             	mov    %rbx,%rdi
 2d4:	e8 00 00 00 00       	call   2d9 <.LC250+0x11>
			2d5: R_X86_64_PLT32	_Unwind_Resume-0x4
