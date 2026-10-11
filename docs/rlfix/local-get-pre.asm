0000000000000000 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE>:
   0:	f3 0f 1e fa          	endbr64
   4:	55                   	push   %rbp
   5:	48 89 e5             	mov    %rsp,%rbp
   8:	41 57                	push   %r15
   a:	41 56                	push   %r14
   c:	41 55                	push   %r13
   e:	41 54                	push   %r12
  10:	53                   	push   %rbx
  11:	49 89 fe             	mov    %rdi,%r14
  14:	48 89 f3             	mov    %rsi,%rbx
  17:	48 83 e4 c0          	and    $0xffffffffffffffc0,%rsp
  1b:	4d 89 c4             	mov    %r8,%r12
  1e:	48 81 ec 00 01 00 00 	sub    $0x100,%rsp
  25:	64 48 8b 04 25 28 00 00 00 	mov    %fs:0x28,%rax
  2e:	48 89 84 24 f8 00 00 00 	mov    %rax,0xf8(%rsp)
  36:	31 c0                	xor    %eax,%eax
  38:	84 c9                	test   %cl,%cl
  3a:	74 34                	je     70 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x70>
  3c:	4d 85 c0             	test   %r8,%r8
  3f:	0f 85 41 06 00 00    	jne    686 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x686>
  45:	48 8b 84 24 f8 00 00 00 	mov    0xf8(%rsp),%rax
  4d:	64 48 2b 04 25 28 00 00 00 	sub    %fs:0x28,%rax
  56:	0f 85 0e 06 00 00    	jne    66a <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x66a>
  5c:	48 8d 65 d8          	lea    -0x28(%rbp),%rsp
  60:	5b                   	pop    %rbx
  61:	41 5c                	pop    %r12
  63:	41 5d                	pop    %r13
  65:	41 5e                	pop    %r14
  67:	41 5f                	pop    %r15
  69:	5d                   	pop    %rbp
  6a:	e9 00 00 00 00       	jmp    6f <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x6f>	6b: R_X86_64_PLT32	_ZN4tomo7ExLoopTILb1EE27prepare_captured_local_mgetERNS_2OpE-0x4
  6f:	90                   	nop
  70:	49 89 d5             	mov    %rdx,%r13
  73:	4d 85 c0             	test   %r8,%r8
  76:	0f 84 34 02 00 00    	je     2b0 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x2b0>
  7c:	41 0f b6 04 24       	movzbl (%r12),%eax
  81:	4d 8b 7c 24 10       	mov    0x10(%r12),%r15
  86:	49 8b 4c 24 18       	mov    0x18(%r12),%rcx
  8b:	3c 02                	cmp    $0x2,%al
  8d:	0f 84 5d 01 00 00    	je     1f0 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x1f0>
  93:	3c 01                	cmp    $0x1,%al
  95:	0f 84 b5 01 00 00    	je     250 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x250>
  9b:	3c 03                	cmp    $0x3,%al
  9d:	0f 84 bd 00 00 00    	je     160 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x160>
  a3:	4d 85 ff             	test   %r15,%r15
  a6:	0f 84 da 05 00 00    	je     686 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x686>
  ac:	49 83 7c 24 08 00    	cmpq   $0x0,0x8(%r12)
  b2:	0f 84 ce 05 00 00    	je     686 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x686>
  b8:	41 0f b6 47 02       	movzbl 0x2(%r15),%eax
  bd:	41 80 3f 00          	cmpb   $0x0,(%r15)
  c1:	0f 84 49 02 00 00    	je     310 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x310>
  c7:	48 b8 00 00 00 00 ff ff ff ff 	movabs $0xffffffff00000000,%rax
  d1:	48 c7 43 28 00 00 00 00 	movq   $0x0,0x28(%rbx)
  d9:	c6 43 1d 00          	movb   $0x0,0x1d(%rbx)
  dd:	c7 83 bc 00 00 00 00 00 00 00 	movl   $0x0,0xbc(%rbx)
  e7:	c7 83 a4 00 00 00 00 00 00 00 	movl   $0x0,0xa4(%rbx)
  f1:	48 c7 83 a8 00 00 00 00 00 00 00 	movq   $0x0,0xa8(%rbx)
  fc:	48 89 83 b0 00 00 00 	mov    %rax,0xb0(%rbx)
 103:	c6 84 24 b0 00 00 00 0b 	movb   $0xb,0xb0(%rsp)
 10b:	48 c7 84 24 b4 00 00 00 00 00 00 00 	movq   $0x0,0xb4(%rsp)
 117:	66 0f 1f 84 00 00 00 00 00 	nopw   0x0(%rax,%rax,1)
 120:	48 8b 8c 24 f8 00 00 00 	mov    0xf8(%rsp),%rcx
 128:	64 48 2b 0c 25 28 00 00 00 	sub    %fs:0x28,%rcx
 131:	48 8b 84 24 b0 00 00 00 	mov    0xb0(%rsp),%rax
 139:	8b 94 24 b8 00 00 00 	mov    0xb8(%rsp),%edx
 140:	0f 85 24 05 00 00    	jne    66a <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x66a>
 146:	48 8d 65 d8          	lea    -0x28(%rbp),%rsp
 14a:	5b                   	pop    %rbx
 14b:	41 5c                	pop    %r12
 14d:	41 5d                	pop    %r13
 14f:	41 5e                	pop    %r14
 151:	41 5f                	pop    %r15
 153:	5d                   	pop    %rbp
 154:	c3                   	ret
 155:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
 160:	48 b8 00 00 00 00 ff ff ff ff 	movabs $0xffffffff00000000,%rax
 16a:	c6 43 1d 00          	movb   $0x0,0x1d(%rbx)
 16e:	48 c7 43 28 00 00 00 00 	movq   $0x0,0x28(%rbx)
 176:	c7 83 bc 00 00 00 00 00 00 00 	movl   $0x0,0xbc(%rbx)
 180:	48 89 83 b0 00 00 00 	mov    %rax,0xb0(%rbx)
 187:	49 8b 85 c8 00 00 00 	mov    0xc8(%r13),%rax
 18e:	c7 83 a4 00 00 00 00 00 00 00 	movl   $0x0,0xa4(%rbx)
 198:	48 c7 83 a8 00 00 00 00 00 00 00 	movq   $0x0,0xa8(%rbx)
 1a3:	48 85 c0             	test   %rax,%rax
 1a6:	0f 84 da 04 00 00    	je     686 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x686>
 1ac:	80 b8 24 05 00 00 00 	cmpb   $0x0,0x524(%rax)
 1b3:	0f 84 cd 04 00 00    	je     686 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x686>
 1b9:	48 8b 80 48 05 00 00 	mov    0x548(%rax),%rax
 1c0:	48 8b 53 10          	mov    0x10(%rbx),%rdx
 1c4:	a8 02                	test   $0x2,%al
 1c6:	0f 85 34 02 00 00    	jne    400 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x400>
 1cc:	c6 84 24 b0 00 00 00 0d 	movb   $0xd,0xb0(%rsp)
 1d4:	48 c7 84 24 b4 00 00 00 00 00 00 00 	movq   $0x0,0xb4(%rsp)
 1e0:	e9 3b ff ff ff       	jmp    120 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x120>
 1e5:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
 1f0:	48 b8 00 00 00 00 ff ff ff ff 	movabs $0xffffffff00000000,%rax
 1fa:	48 c7 43 28 00 00 00 00 	movq   $0x0,0x28(%rbx)
 202:	c6 43 1d 00          	movb   $0x0,0x1d(%rbx)
 206:	c7 83 bc 00 00 00 00 00 00 00 	movl   $0x0,0xbc(%rbx)
 210:	c7 83 a4 00 00 00 00 00 00 00 	movl   $0x0,0xa4(%rbx)
 21a:	48 c7 83 a8 00 00 00 00 00 00 00 	movq   $0x0,0xa8(%rbx)
 225:	48 89 83 b0 00 00 00 	mov    %rax,0xb0(%rbx)
 22c:	c6 84 24 b0 00 00 00 09 	movb   $0x9,0xb0(%rsp)
 234:	48 c7 84 24 b4 00 00 00 00 00 00 00 	movq   $0x0,0xb4(%rsp)
 240:	e9 db fe ff ff       	jmp    120 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x120>
 245:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
 250:	48 b8 00 00 00 00 ff ff ff ff 	movabs $0xffffffff00000000,%rax
 25a:	48 c7 43 28 00 00 00 00 	movq   $0x0,0x28(%rbx)
 262:	c6 43 1d 00          	movb   $0x0,0x1d(%rbx)
 266:	c7 83 bc 00 00 00 00 00 00 00 	movl   $0x0,0xbc(%rbx)
 270:	c7 83 a4 00 00 00 00 00 00 00 	movl   $0x0,0xa4(%rbx)
 27a:	48 c7 83 a8 00 00 00 00 00 00 00 	movq   $0x0,0xa8(%rbx)
 285:	48 89 83 b0 00 00 00 	mov    %rax,0xb0(%rbx)
 28c:	c6 84 24 b0 00 00 00 0a 	movb   $0xa,0xb0(%rsp)
 294:	48 c7 84 24 b4 00 00 00 00 00 00 00 	movq   $0x0,0xb4(%rsp)
 2a0:	e9 7b fe ff ff       	jmp    120 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x120>
 2a5:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
 2b0:	48 8b 76 10          	mov    0x10(%rsi),%rsi
 2b4:	48 89 d7             	mov    %rdx,%rdi
 2b7:	e8 00 00 00 00       	call   2bc <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x2bc>	2b8: R_X86_64_PLT32	_ZNK4tomo9FlatStore19read_local_prefetchEm-0x4
 2bc:	45 31 c0             	xor    %r8d,%r8d
 2bf:	83 bb cc 00 00 00 01 	cmpl   $0x1,0xcc(%rbx)
 2c6:	76 20                	jbe    2e8 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x2e8>
 2c8:	48 8b 93 c0 00 00 00 	mov    0xc0(%rbx),%rdx
 2cf:	48 8d 83 e0 00 00 00 	lea    0xe0(%rbx),%rax
 2d6:	48 8d 4a 10          	lea    0x10(%rdx),%rcx
 2da:	48 85 d2             	test   %rdx,%rdx
 2dd:	48 0f 45 c1          	cmovne %rcx,%rax
 2e1:	4c 8b 20             	mov    (%rax),%r12
 2e4:	4c 8b 40 08          	mov    0x8(%rax),%r8
 2e8:	48 8b 53 10          	mov    0x10(%rbx),%rdx
 2ec:	4c 8d bc 24 c0 00 00 00 	lea    0xc0(%rsp),%r15
 2f4:	4c 89 e1             	mov    %r12,%rcx
 2f7:	4c 89 ee             	mov    %r13,%rsi
 2fa:	4c 89 ff             	mov    %r15,%rdi
 2fd:	4d 89 fc             	mov    %r15,%r12
 300:	e8 00 00 00 00       	call   305 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x305>	301: R_X86_64_PLT32	_ZNK4tomo9FlatStore27read_local_prefetch_captureEmNS_5SliceE-0x4
 305:	e9 72 fd ff ff       	jmp    7c <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x7c>
 30a:	66 0f 1f 44 00 00    	nopw   0x0(%rax,%rax,1)
 310:	a8 01                	test   $0x1,%al
 312:	74 7c                	je     390 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x390>
 314:	8d 14 00             	lea    (%rax,%rax,1),%edx
 317:	83 e2 04             	and    $0x4,%edx
 31a:	49 8b 54 17 08       	mov    0x8(%r15,%rdx,1),%rdx
 31f:	48 85 d2             	test   %rdx,%rdx
 322:	78 6c                	js     390 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x390>
 324:	49 39 96 58 01 00 00 	cmp    %rdx,0x158(%r14)
 32b:	7c 63                	jl     390 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x390>
 32d:	48 b8 00 00 00 00 ff ff ff ff 	movabs $0xffffffff00000000,%rax
 337:	48 c7 43 28 00 00 00 00 	movq   $0x0,0x28(%rbx)
 33f:	c6 43 1d 00          	movb   $0x0,0x1d(%rbx)
 343:	c7 83 bc 00 00 00 00 00 00 00 	movl   $0x0,0xbc(%rbx)
 34d:	c7 83 a4 00 00 00 00 00 00 00 	movl   $0x0,0xa4(%rbx)
 357:	48 c7 83 a8 00 00 00 00 00 00 00 	movq   $0x0,0xa8(%rbx)
 362:	48 89 83 b0 00 00 00 	mov    %rax,0xb0(%rbx)
 369:	c6 84 24 b0 00 00 00 0c 	movb   $0xc,0xb0(%rsp)
 371:	48 c7 84 24 b4 00 00 00 00 00 00 00 	movq   $0x0,0xb4(%rsp)
 37d:	e9 9e fd ff ff       	jmp    120 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x120>
 382:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
 38d:	0f 1f 00             	nopl   (%rax)
 390:	48 bf 00 00 00 00 ff ff ff ff 	movabs $0xffffffff00000000,%rdi
 39a:	48 c7 43 28 00 00 00 00 	movq   $0x0,0x28(%rbx)
 3a2:	c6 43 1d 00          	movb   $0x0,0x1d(%rbx)
 3a6:	c7 83 bc 00 00 00 00 00 00 00 	movl   $0x0,0xbc(%rbx)
 3b0:	c7 83 a4 00 00 00 00 00 00 00 	movl   $0x0,0xa4(%rbx)
 3ba:	48 c7 83 a8 00 00 00 00 00 00 00 	movq   $0x0,0xa8(%rbx)
 3c5:	48 89 bb b0 00 00 00 	mov    %rdi,0xb0(%rbx)
 3cc:	41 0f b6 57 01       	movzbl 0x1(%r15),%edx
 3d1:	80 fa 01             	cmp    $0x1,%dl
 3d4:	0f 84 c6 01 00 00    	je     5a0 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x5a0>
 3da:	f6 c2 fd             	test   $0xfd,%dl
 3dd:	0f 84 cd 00 00 00    	je     4b0 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x4b0>
 3e3:	c6 84 24 b0 00 00 00 0b 	movb   $0xb,0xb0(%rsp)
 3eb:	48 c7 84 24 b4 00 00 00 00 00 00 00 	movq   $0x0,0xb4(%rsp)
 3f7:	e9 24 fd ff ff       	jmp    120 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x120>
 3fc:	0f 1f 40 00          	nopl   0x0(%rax)
 400:	49 8b 8d c8 00 00 00 	mov    0xc8(%r13),%rcx
 407:	48 85 c9             	test   %rcx,%rcx
 40a:	0f 84 76 02 00 00    	je     686 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x686>
 410:	80 b9 24 05 00 00 00 	cmpb   $0x0,0x524(%rcx)
 417:	0f 84 69 02 00 00    	je     686 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x686>
 41d:	48 89 d0             	mov    %rdx,%rax
 420:	48 c1 e8 21          	shr    $0x21,%rax
 424:	48 31 d0             	xor    %rdx,%rax
 427:	48 ba cd 8c 55 ed d7 af 51 ff 	movabs $0xff51afd7ed558ccd,%rdx
 431:	48 0f af c2          	imul   %rdx,%rax
 435:	48 89 c2             	mov    %rax,%rdx
 438:	48 c1 ea 21          	shr    $0x21,%rdx
 43c:	48 31 d0             	xor    %rdx,%rax
 43f:	48 ba 53 ec 85 1a fe b9 ce c4 	movabs $0xc4ceb9fe1a85ec53,%rdx
 449:	48 0f af c2          	imul   %rdx,%rax
 44d:	48 89 c2             	mov    %rax,%rdx
 450:	48 c1 ea 21          	shr    $0x21,%rdx
 454:	48 31 d0             	xor    %rdx,%rax
 457:	48 89 c2             	mov    %rax,%rdx
 45a:	81 e2 ff 0f 00 00    	and    $0xfff,%edx
 460:	48 8b 94 d1 c0 05 00 00 	mov    0x5c0(%rcx,%rdx,8),%rdx
 468:	48 85 d2             	test   %rdx,%rdx
 46b:	0f 84 5b fd ff ff    	je     1cc <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x1cc>
 471:	78 1a                	js     48d <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x48d>
 473:	48 c1 e8 0c          	shr    $0xc,%rax
 477:	48 c1 ea 1f          	shr    $0x1f,%rdx
 47b:	b9 01 00 00 00       	mov    $0x1,%ecx
 480:	85 c0                	test   %eax,%eax
 482:	0f 44 c1             	cmove  %ecx,%eax
 485:	39 d0                	cmp    %edx,%eax
 487:	0f 85 3f fd ff ff    	jne    1cc <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x1cc>
 48d:	c6 84 24 b0 00 00 00 09 	movb   $0x9,0xb0(%rsp)
 495:	48 c7 84 24 b4 00 00 00 00 00 00 00 	movq   $0x0,0xb4(%rsp)
 4a1:	e9 7a fc ff ff       	jmp    120 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x120>
 4a6:	66 2e 0f 1f 84 00 00 00 00 00 	cs nopw 0x0(%rax,%rax,1)
 4b0:	44 0f b6 e0          	movzbl %al,%r12d
 4b4:	43 8d 34 24          	lea    (%r12,%r12,1),%esi
 4b8:	42 8d 3c e5 00 00 00 00 	lea    0x0(,%r12,8),%edi
 4c0:	83 e6 04             	and    $0x4,%esi
 4c3:	83 e7 08             	and    $0x8,%edi
 4c6:	48 01 fe             	add    %rdi,%rsi
 4c9:	a8 02                	test   $0x2,%al
 4cb:	0f 85 58 01 00 00    	jne    629 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x629>
 4d1:	41 0f b6 47 03       	movzbl 0x3(%r15),%eax
 4d6:	48 8d 74 06 08       	lea    0x8(%rsi,%rax,1),%rsi
 4db:	41 8b 47 04          	mov    0x4(%r15),%eax
 4df:	4c 01 fe             	add    %r15,%rsi
 4e2:	80 fa 02             	cmp    $0x2,%dl
 4e5:	75 03                	jne    4ea <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x4ea>
 4e7:	48 8b 36             	mov    (%rsi),%rsi
 4ea:	48 8d bc 24 b0 00 00 00 	lea    0xb0(%rsp),%rdi
 4f2:	89 c2                	mov    %eax,%edx
 4f4:	48 89 4c 24 38       	mov    %rcx,0x38(%rsp)
 4f9:	48 89 9c 24 b0 00 00 00 	mov    %rbx,0xb0(%rsp)
 501:	c6 84 24 b8 00 00 00 00 	movb   $0x0,0xb8(%rsp)
 509:	e8 00 00 00 00       	call   50e <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x50e>	50a: R_X86_64_PC32	_ZN4tomo10reply_bulkINS_2Op4SinkEEEvOT_NS_5SliceE.isra.0-0x4
 50e:	48 8b 4c 24 38       	mov    0x38(%rsp),%rcx
 513:	41 80 bd f0 00 00 00 00 	cmpb   $0x0,0xf0(%r13)
 51b:	49 8b 85 c8 00 00 00 	mov    0xc8(%r13),%rax
 522:	0f 84 38 fc ff ff    	je     160 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x160>
 528:	f6 c1 01             	test   $0x1,%cl
 52b:	0f 85 2f fc ff ff    	jne    160 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x160>
 531:	48 89 ce             	mov    %rcx,%rsi
 534:	48 ba ff ff ff ff ff ff ff 3f 	movabs $0x3fffffffffffffff,%rdx
 53e:	48 c1 ee 02          	shr    $0x2,%rsi
 542:	48 39 d6             	cmp    %rdx,%rsi
 545:	0f 84 15 fc ff ff    	je     160 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x160>
 54b:	48 85 c0             	test   %rax,%rax
 54e:	0f 84 32 01 00 00    	je     686 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x686>
 554:	80 b8 24 05 00 00 00 	cmpb   $0x0,0x524(%rax)
 55b:	0f 84 25 01 00 00    	je     686 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x686>
 561:	48 8b 80 48 05 00 00 	mov    0x548(%rax),%rax
 568:	48 31 c1             	xor    %rax,%rcx
 56b:	48 f7 c1 fd ff ff ff 	test   $0xfffffffffffffffd,%rcx
 572:	0f 85 e8 fb ff ff    	jne    160 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x160>
 578:	41 80 be 88 01 00 00 00 	cmpb   $0x0,0x188(%r14)
 580:	0f 85 e9 00 00 00    	jne    66f <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x66f>
 586:	c6 84 24 b0 00 00 00 00 	movb   $0x0,0xb0(%rsp)
 58e:	48 c7 84 24 b4 00 00 00 01 00 00 00 	movq   $0x1,0xb4(%rsp)
 59a:	e9 81 fb ff ff       	jmp    120 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x120>
 59f:	90                   	nop
 5a0:	44 0f b6 e0          	movzbl %al,%r12d
 5a4:	43 8d 14 24          	lea    (%r12,%r12,1),%edx
 5a8:	42 8d 34 e5 00 00 00 00 	lea    0x0(,%r12,8),%esi
 5b0:	83 e2 04             	and    $0x4,%edx
 5b3:	83 e6 08             	and    $0x8,%esi
 5b6:	48 01 f2             	add    %rsi,%rdx
 5b9:	a8 02                	test   $0x2,%al
 5bb:	0f 85 a0 00 00 00    	jne    661 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x661>
 5c1:	41 0f b6 77 03       	movzbl 0x3(%r15),%esi
 5c6:	49 8d 04 17          	lea    (%r15,%rdx,1),%rax
 5ca:	48 8b 74 06 08       	mov    0x8(%rsi,%rax,1),%rsi
 5cf:	48 85 f6             	test   %rsi,%rsi
 5d2:	78 5e                	js     632 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x632>
 5d4:	48 8d bc 24 e0 00 00 00 	lea    0xe0(%rsp),%rdi
 5dc:	48 89 4c 24 30       	mov    %rcx,0x30(%rsp)
 5e1:	48 89 7c 24 38       	mov    %rdi,0x38(%rsp)
 5e6:	e8 00 00 00 00       	call   5eb <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x5eb>	5e7: R_X86_64_PLT32	_ZN4tomo10u64_to_decEPcm-0x4
 5eb:	48 8b 4c 24 30       	mov    0x30(%rsp),%rcx
 5f0:	48 8b 7c 24 38       	mov    0x38(%rsp),%rdi
 5f5:	89 c2                	mov    %eax,%edx
 5f7:	48 8d 84 24 b0 00 00 00 	lea    0xb0(%rsp),%rax
 5ff:	48 89 fe             	mov    %rdi,%rsi
 602:	48 89 4c 24 38       	mov    %rcx,0x38(%rsp)
 607:	48 89 9c 24 b0 00 00 00 	mov    %rbx,0xb0(%rsp)
 60f:	48 89 c7             	mov    %rax,%rdi
 612:	c6 84 24 b8 00 00 00 00 	movb   $0x0,0xb8(%rsp)
 61a:	e8 00 00 00 00       	call   61f <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x61f>	61b: R_X86_64_PC32	_ZN4tomo10reply_bulkINS_2Op4SinkEEEvOT_NS_5SliceE.isra.0-0x4
 61f:	48 8b 4c 24 38       	mov    0x38(%rsp),%rcx
 624:	e9 ea fe ff ff       	jmp    513 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x513>
 629:	41 8b 47 08          	mov    0x8(%r15),%eax
 62d:	e9 a4 fe ff ff       	jmp    4d6 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x4d6>
 632:	48 8d bc 24 e1 00 00 00 	lea    0xe1(%rsp),%rdi
 63a:	48 f7 de             	neg    %rsi
 63d:	48 89 4c 24 38       	mov    %rcx,0x38(%rsp)
 642:	c6 84 24 e0 00 00 00 2d 	movb   $0x2d,0xe0(%rsp)
 64a:	e8 00 00 00 00       	call   64f <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x64f>	64b: R_X86_64_PLT32	_ZN4tomo10u64_to_decEPcm-0x4
 64f:	48 8b 4c 24 38       	mov    0x38(%rsp),%rcx
 654:	48 8d bc 24 e0 00 00 00 	lea    0xe0(%rsp),%rdi
 65c:	8d 50 01             	lea    0x1(%rax),%edx
 65f:	eb 96                	jmp    5f7 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x5f7>
 661:	41 8b 77 08          	mov    0x8(%r15),%esi
 665:	e9 5c ff ff ff       	jmp    5c6 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x5c6>
 66a:	e8 00 00 00 00       	call   66f <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x66f>	66b: R_X86_64_PLT32	__stack_chk_fail-0x4
 66f:	0f b6 73 1c          	movzbl 0x1c(%rbx),%esi
 673:	44 89 e1             	mov    %r12d,%ecx
 676:	4c 89 fa             	mov    %r15,%rdx
 679:	4c 89 f7             	mov    %r14,%rdi
 67c:	e8 00 00 00 00       	call   681 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x681>	67d: R_X86_64_PC32	.text.unlikely-0x4
 681:	e9 00 ff ff ff       	jmp    586 <_ZN4tomo7ExLoopTILb1EE18prepare_local_readERNS_2OpEPNS_9FlatStoreEbPKNS4_24ReadLocalPrefetchCaptureE+0x586>
 686:	e8 00 00 00 00       	call   68b <_ZN4tomo2Op4Sink7advanceEm.isra.0+0xb>	687: R_X86_64_PLT32	abort-0x4
