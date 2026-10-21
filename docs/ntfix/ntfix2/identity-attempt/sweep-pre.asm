
build/ntfix-pre/db0/src/core/reorder.o:     file format elf64-x86-64


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
  15:	48 8b 2f             	mov    (%rdi),%rbp
  18:	64 48 8b 04 25 28 00 	mov    %fs:0x28,%rax
  1f:	00 00 
  21:	48 89 44 24 18       	mov    %rax,0x18(%rsp)
  26:	31 c0                	xor    %eax,%eax
  28:	80 bf 98 01 00 00 00 	cmpb   $0x0,0x198(%rdi)
  2f:	74 1a                	je     4b <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x4b>
  31:	0f b6 85 d0 3f 01 00 	movzbl 0x13fd0(%rbp),%eax
  38:	3c 04                	cmp    $0x4,%al
  3a:	0f 84 30 02 00 00    	je     270 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x270>
  40:	3c 01                	cmp    $0x1,%al
  42:	0f 84 28 02 00 00    	je     270 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x270>
  48:	48 8b 2f             	mov    (%rdi),%rbp
  4b:	48 89 e6             	mov    %rsp,%rsi
  4e:	31 ff                	xor    %edi,%edi
  50:	c5 f9 ef c0          	vpxor  %xmm0,%xmm0,%xmm0
  54:	4c 8b a3 d8 16 00 00 	mov    0x16d8(%rbx),%r12
  5b:	4c 8b 6b 08          	mov    0x8(%rbx),%r13
  5f:	c5 f9 7f 04 24       	vmovdqa %xmm0,(%rsp)
  64:	e8 00 00 00 00       	call   69 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x69>
			65: R_X86_64_PLT32	clock_gettime-0x4
  69:	48 8b 4c 24 08       	mov    0x8(%rsp),%rcx
  6e:	48 69 34 24 e8 03 00 	imul   $0x3e8,(%rsp),%rsi
  75:	00 
  76:	48 b8 db 34 b6 d7 82 	movabs $0x431bde82d7b634db,%rax
  7d:	de 1b 43 
  80:	48 f7 e9             	imul   %rcx
  83:	48 c1 f9 3f          	sar    $0x3f,%rcx
  87:	48 c1 fa 12          	sar    $0x12,%rdx
  8b:	48 29 ca             	sub    %rcx,%rdx
  8e:	48 01 d6             	add    %rdx,%rsi
  91:	80 bb 9a 01 00 00 00 	cmpb   $0x0,0x19a(%rbx)
  98:	48 89 b3 58 01 00 00 	mov    %rsi,0x158(%rbx)
  9f:	0f 85 ab 01 00 00    	jne    250 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x250>
  a5:	48 8b bb d8 16 00 00 	mov    0x16d8(%rbx),%rdi
  ac:	48 85 ff             	test   %rdi,%rdi
  af:	0f 84 b3 01 00 00    	je     268 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x268>
  b5:	80 7f 21 00          	cmpb   $0x0,0x21(%rdi)
  b9:	0f 84 cb 00 00 00    	je     18a <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x18a>
  bf:	44 8b 57 18          	mov    0x18(%rdi),%r10d
  c3:	44 8b 47 10          	mov    0x10(%rdi),%r8d
  c7:	45 31 c9             	xor    %r9d,%r9d
  ca:	31 f6                	xor    %esi,%esi
  cc:	45 85 d2             	test   %r10d,%r10d
  cf:	0f 84 db 01 00 00    	je     2b0 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2b0>
  d5:	66 66 2e 0f 1f 84 00 	data16 cs nopw 0x0(%rax,%rax,1)
  dc:	00 00 00 00 
  e0:	41 8d 14 30          	lea    (%r8,%rsi,1),%edx
  e4:	81 e2 ff 03 00 00    	and    $0x3ff,%edx
  ea:	48 89 d0             	mov    %rdx,%rax
  ed:	48 c1 e0 04          	shl    $0x4,%rax
  f1:	48 03 07             	add    (%rdi),%rax
  f4:	48 8b 08             	mov    (%rax),%rcx
  f7:	4c 8b 58 08          	mov    0x8(%rax),%r11
  fb:	48 85 c9             	test   %rcx,%rcx
  fe:	74 55                	je     155 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x155>
 100:	48 8b 81 c0 00 00 00 	mov    0xc0(%rcx),%rax
 107:	4c 8b 81 00 01 00 00 	mov    0x100(%rcx),%r8
 10e:	4d 89 de             	mov    %r11,%r14
 111:	4d 29 c6             	sub    %r8,%r14
 114:	4c 29 c0             	sub    %r8,%rax
 117:	44 8b 47 10          	mov    0x10(%rdi),%r8d
 11b:	49 39 c6             	cmp    %rax,%r14
 11e:	73 35                	jae    155 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x155>
 120:	48 8b 81 08 01 00 00 	mov    0x108(%rcx),%rax
 127:	4c 0f a3 d8          	bt     %r11,%rax
 12b:	73 28                	jae    155 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x155>
 12d:	43 8d 04 01          	lea    (%r9,%r8,1),%eax
 131:	41 ff c1             	inc    %r9d
 134:	25 ff 03 00 00       	and    $0x3ff,%eax
 139:	49 89 c6             	mov    %rax,%r14
 13c:	49 c1 e6 04          	shl    $0x4,%r14
 140:	4c 03 37             	add    (%rdi),%r14
 143:	49 89 0e             	mov    %rcx,(%r14)
 146:	48 8b 4f 08          	mov    0x8(%rdi),%rcx
 14a:	4d 89 5e 08          	mov    %r11,0x8(%r14)
 14e:	0f b6 14 11          	movzbl (%rcx,%rdx,1),%edx
 152:	88 14 01             	mov    %dl,(%rcx,%rax,1)
 155:	ff c6                	inc    %esi
 157:	41 39 f2             	cmp    %esi,%r10d
 15a:	75 84                	jne    e0 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0xe0>
 15c:	48 8b 83 d8 16 00 00 	mov    0x16d8(%rbx),%rax
 163:	45 01 c8             	add    %r9d,%r8d
 166:	c6 47 21 00          	movb   $0x0,0x21(%rdi)
 16a:	41 81 e0 ff 03 00 00 	and    $0x3ff,%r8d
 171:	c4 c1 79 6e c8       	vmovd  %r8d,%xmm1
 176:	c4 c3 71 22 c1 01    	vpinsrd $0x1,%r9d,%xmm1,%xmm0
 17c:	c5 f9 d6 47 14       	vmovq  %xmm0,0x14(%rdi)
 181:	48 85 c0             	test   %rax,%rax
 184:	0f 84 16 01 00 00    	je     2a0 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2a0>
 18a:	be ff ff ff ff       	mov    $0xffffffff,%esi
 18f:	48 89 df             	mov    %rbx,%rdi
 192:	e8 00 00 00 00       	call   197 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x197>
			193: R_X86_64_PLT32	_ZN8tomo_db07ExLoopTILb1EE30drain_local_reads_bounded_implILb0EEEjj-0x4
 197:	41 89 c7             	mov    %eax,%r15d
 19a:	48 89 df             	mov    %rbx,%rdi
 19d:	e8 00 00 00 00       	call   1a2 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1a2>
			19e: R_X86_64_PLT32	_ZN8tomo_db07ExLoopTILb1EE29compact_local_read_tombstonesEv-0x4
 1a2:	48 89 df             	mov    %rbx,%rdi
 1a5:	e8 00 00 00 00       	call   1aa <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1aa>
			1a6: R_X86_64_PLT32	_ZN8tomo_db07ExLoopTILb1EE8r7_sweepILj32ELb1ELb0ELb0EEEjv-0x4
 1aa:	48 8b bb d8 16 00 00 	mov    0x16d8(%rbx),%rdi
 1b1:	41 01 c7             	add    %eax,%r15d
 1b4:	48 85 ff             	test   %rdi,%rdi
 1b7:	74 0c                	je     1c5 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1c5>
 1b9:	48 83 c7 38          	add    $0x38,%rdi
 1bd:	e8 00 00 00 00       	call   1c2 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1c2>
			1be: R_X86_64_PLT32	_ZN8tomo_db022ReadLocalDeferredQueue11drain_readyEv-0x4
 1c2:	41 01 c7             	add    %eax,%r15d
 1c5:	45 85 ff             	test   %r15d,%r15d
 1c8:	74 13                	je     1dd <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1dd>
 1ca:	8b 83 10 01 00 00    	mov    0x110(%rbx),%eax
 1d0:	85 c0                	test   %eax,%eax
 1d2:	79 09                	jns    1dd <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1dd>
 1d4:	48 8d 7b 10          	lea    0x10(%rbx),%rdi
 1d8:	e8 00 00 00 00       	call   1dd <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1dd>
			1d9: R_X86_64_PLT32	io_uring_submit_and_get_events-0x4
 1dd:	4d 85 e4             	test   %r12,%r12
 1e0:	75 2e                	jne    210 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x210>
 1e2:	48 8b 44 24 18       	mov    0x18(%rsp),%rax
 1e7:	64 48 2b 04 25 28 00 	sub    %fs:0x28,%rax
 1ee:	00 00 
 1f0:	0f 85 ec 00 00 00    	jne    2e2 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2e2>
 1f6:	48 83 c4 28          	add    $0x28,%rsp
 1fa:	44 89 f8             	mov    %r15d,%eax
 1fd:	5b                   	pop    %rbx
 1fe:	5d                   	pop    %rbp
 1ff:	41 5c                	pop    %r12
 201:	41 5d                	pop    %r13
 203:	41 5e                	pop    %r14
 205:	41 5f                	pop    %r15
 207:	c3                   	ret
 208:	0f 1f 84 00 00 00 00 	nopl   0x0(%rax,%rax,1)
 20f:	00 
 210:	48 8b 85 d8 75 01 00 	mov    0x175d8(%rbp),%rax
 217:	48 85 c0             	test   %rax,%rax
 21a:	0f 84 df 00 00 00    	je     2ff <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2ff>
 220:	48 8b 00             	mov    (%rax),%rax
 223:	48 85 c0             	test   %rax,%rax
 226:	0f 88 d3 00 00 00    	js     2ff <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2ff>
 22c:	49 8b 95 60 05 00 00 	mov    0x560(%r13),%rdx
 233:	48 85 d2             	test   %rdx,%rdx
 236:	0f 84 c3 00 00 00    	je     2ff <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2ff>
 23c:	48 87 02             	xchg   %rax,(%rdx)
 23f:	eb a1                	jmp    1e2 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1e2>
 241:	66 66 2e 0f 1f 84 00 	data16 cs nopw 0x0(%rax,%rax,1)
 248:	00 00 00 00 
 24c:	0f 1f 40 00          	nopl   0x0(%rax)
 250:	48 89 df             	mov    %rbx,%rdi
 253:	e8 00 00 00 00       	call   258 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x258>
			254: R_X86_64_PLT32	_ZN8tomo_db07ExLoopTILb1EE39read_local_rebind_owned_shards_after_lbEv-0x4
 258:	48 8b bb d8 16 00 00 	mov    0x16d8(%rbx),%rdi
 25f:	48 85 ff             	test   %rdi,%rdi
 262:	0f 85 4d fe ff ff    	jne    b5 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0xb5>
 268:	45 31 ff             	xor    %r15d,%r15d
 26b:	e9 32 ff ff ff       	jmp    1a2 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x1a2>
 270:	48 8b 44 24 18       	mov    0x18(%rsp),%rax
 275:	64 48 2b 04 25 28 00 	sub    %fs:0x28,%rax
 27c:	00 00 
 27e:	75 62                	jne    2e2 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2e2>
 280:	48 83 c4 28          	add    $0x28,%rsp
 284:	48 89 df             	mov    %rbx,%rdi
 287:	5b                   	pop    %rbx
 288:	5d                   	pop    %rbp
 289:	41 5c                	pop    %r12
 28b:	41 5d                	pop    %r13
 28d:	41 5e                	pop    %r14
 28f:	41 5f                	pop    %r15
 291:	e9 00 00 00 00       	jmp    296 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x296>
			292: R_X86_64_PLT32	_ZN8tomo_db07ExLoopTILb1EE18r7_fused_pass_implILj32ELb1ELb0ELb0EEEjv-0x4
 296:	66 2e 0f 1f 84 00 00 	cs nopw 0x0(%rax,%rax,1)
 29d:	00 00 00 
 2a0:	45 31 ff             	xor    %r15d,%r15d
 2a3:	e9 f2 fe ff ff       	jmp    19a <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x19a>
 2a8:	0f 1f 84 00 00 00 00 	nopl   0x0(%rax,%rax,1)
 2af:	00 
 2b0:	41 81 e0 ff 03 00 00 	and    $0x3ff,%r8d
 2b7:	c6 47 21 00          	movb   $0x0,0x21(%rdi)
 2bb:	c4 c1 79 6e c0       	vmovd  %r8d,%xmm0
 2c0:	c5 f9 d6 47 14       	vmovq  %xmm0,0x14(%rdi)
 2c5:	e9 c0 fe ff ff       	jmp    18a <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x18a>
 2ca:	4d 85 e4             	test   %r12,%r12
 2cd:	75 21                	jne    2f0 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2f0>
 2cf:	c5 f8 77             	vzeroupper
 2d2:	48 8b 44 24 18       	mov    0x18(%rsp),%rax
 2d7:	64 48 2b 04 25 28 00 	sub    %fs:0x28,%rax
 2de:	00 00 
 2e0:	74 32                	je     314 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x314>
 2e2:	e8 00 00 00 00       	call   2e7 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2e7>
			2e3: R_X86_64_PLT32	__stack_chk_fail-0x4
 2e7:	f3 0f 1e fa          	endbr64
 2eb:	48 89 c3             	mov    %rax,%rbx
 2ee:	eb da                	jmp    2ca <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2ca>
 2f0:	48 8b 85 d8 75 01 00 	mov    0x175d8(%rbp),%rax
 2f7:	48 85 c0             	test   %rax,%rax
 2fa:	75 08                	jne    304 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x304>
 2fc:	c5 f8 77             	vzeroupper
 2ff:	e8 00 00 00 00       	call   304 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x304>
			300: R_X86_64_PLT32	abort-0x4
 304:	48 8b 30             	mov    (%rax),%rsi
 307:	4c 89 ef             	mov    %r13,%rdi
 30a:	c5 f8 77             	vzeroupper
 30d:	e8 00 00 00 00       	call   312 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x312>
			30e: R_X86_64_PLT32	_ZN8tomo_db09ThreadCtx23publish_read_local_tickEm-0x4
 312:	eb be                	jmp    2d2 <_ZN8tomo_db07ExLoopTILb1EE19r7_fused_sweep_implILj32ELb1ELb0ELb0EEEjv+0x2d2>
 314:	48 89 df             	mov    %rbx,%rdi
 317:	e8 00 00 00 00       	call   31c <_ZN8tomo_db06IoLoop32r7_fused_demote_local_read_batchEPNS_6ClientEPKmPKNS_23ReadLocalFallbackReasonEjRj.cold+0x16>
			318: R_X86_64_PLT32	_Unwind_Resume-0x4
