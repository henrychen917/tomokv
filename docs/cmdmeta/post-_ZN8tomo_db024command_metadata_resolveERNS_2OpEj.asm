
build/cmdmeta/POST/db0/src/cmd/cmdmeta.o:     file format elf64-x86-64


Disassembly of section .text:

0000000000002350 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj>:
    2350:	f3 0f 1e fa          	endbr64
    2354:	41 57                	push   %r15
    2356:	41 56                	push   %r14
    2358:	41 55                	push   %r13
    235a:	41 54                	push   %r12
    235c:	55                   	push   %rbp
    235d:	53                   	push   %rbx
    235e:	48 89 fd             	mov    %rdi,%rbp
    2361:	48 83 ec 68          	sub    $0x68,%rsp
    2365:	89 f3                	mov    %esi,%ebx
    2367:	64 48 8b 04 25 28 00 00 00 	mov    %fs:0x28,%rax
    2370:	48 89 44 24 58       	mov    %rax,0x58(%rsp)
    2375:	31 c0                	xor    %eax,%eax
    2377:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    237c:	8b 87 cc 00 00 00    	mov    0xcc(%rdi),%eax
    2382:	39 c3                	cmp    %eax,%ebx
    2384:	0f 83 9a 02 00 00    	jae    2624 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x2d4>
    238a:	85 db                	test   %ebx,%ebx
    238c:	0f 85 1e 02 00 00    	jne    25b0 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x260>
    2392:	48 8b 17             	mov    (%rdi),%rdx
    2395:	48 85 d2             	test   %rdx,%rdx
    2398:	0f 84 12 02 00 00    	je     25b0 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x260>
    239e:	0f b7 72 26          	movzwl 0x26(%rdx),%esi
    23a2:	48 8b 0d 00 00 00 00 	mov    0x0(%rip),%rcx        # 23a9 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x59>
    23a9:	48 8b 15 00 00 00 00 	mov    0x0(%rip),%rdx        # 23b0 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x60>
    23b0:	48 29 ca             	sub    %rcx,%rdx
    23b3:	48 c1 fa 03          	sar    $0x3,%rdx
    23b7:	48 39 d6             	cmp    %rdx,%rsi
    23ba:	0f 83 f0 04 00 00    	jae    28b0 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x560>
    23c0:	4c 8b 24 f1          	mov    (%rcx,%rsi,8),%r12
    23c4:	e9 0a 02 00 00       	jmp    25d3 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x283>
    23c9:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
    23d0:	3b 9f cc 00 00 00    	cmp    0xcc(%rdi),%ebx
    23d6:	0f 83 48 02 00 00    	jae    2624 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x2d4>
    23dc:	48 8b 87 c0 00 00 00 	mov    0xc0(%rdi),%rax
    23e3:	41 89 dd             	mov    %ebx,%r13d
    23e6:	48 85 c0             	test   %rax,%rax
    23e9:	0f 84 61 02 00 00    	je     2650 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x300>
    23ef:	4c 89 ea             	mov    %r13,%rdx
    23f2:	48 c1 e2 04          	shl    $0x4,%rdx
    23f6:	48 01 d0             	add    %rdx,%rax
    23f9:	48 8b 38             	mov    (%rax),%rdi
    23fc:	8b 70 08             	mov    0x8(%rax),%esi
    23ff:	ff c3                	inc    %ebx
    2401:	e8 00 00 00 00       	call   2406 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0xb6>
    2406:	49 89 c4             	mov    %rax,%r12
    2409:	3b 9d cc 00 00 00    	cmp    0xcc(%rbp),%ebx
    240f:	0f 83 6b 01 00 00    	jae    2580 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x230>
    2415:	48 8b 85 c0 00 00 00 	mov    0xc0(%rbp),%rax
    241c:	48 85 c0             	test   %rax,%rax
    241f:	0f 84 1b 02 00 00    	je     2640 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x2f0>
    2425:	49 c1 e5 04          	shl    $0x4,%r13
    2429:	49 01 c5             	add    %rax,%r13
    242c:	4d 8b 7d 00          	mov    0x0(%r13),%r15
    2430:	45 8b 75 08          	mov    0x8(%r13),%r14d
    2434:	4c 8d 6c 24 30       	lea    0x30(%rsp),%r13
    2439:	4c 89 6c 24 20       	mov    %r13,0x20(%rsp)
    243e:	4d 85 ff             	test   %r15,%r15
    2441:	75 09                	jne    244c <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0xfc>
    2443:	4d 85 f6             	test   %r14,%r14
    2446:	0f 85 49 05 00 00    	jne    2995 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x645>
    244c:	49 83 fe 0f          	cmp    $0xf,%r14
    2450:	0f 87 ea 02 00 00    	ja     2740 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x3f0>
    2456:	49 83 fe 01          	cmp    $0x1,%r14
    245a:	0f 84 10 03 00 00    	je     2770 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x420>
    2460:	4d 85 f6             	test   %r14,%r14
    2463:	0f 85 fe 04 00 00    	jne    2967 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x617>
    2469:	4c 89 e8             	mov    %r13,%rax
    246c:	4c 89 74 24 28       	mov    %r14,0x28(%rsp)
    2471:	42 c6 04 30 00       	movb   $0x0,(%rax,%r14,1)
    2476:	48 8b 44 24 28       	mov    0x28(%rsp),%rax
    247b:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
    2480:	4c 8d 70 01          	lea    0x1(%rax),%r14
    2484:	48 89 44 24 08       	mov    %rax,0x8(%rsp)
    2489:	4d 39 ef             	cmp    %r13,%r15
    248c:	0f 84 2e 04 00 00    	je     28c0 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x570>
    2492:	48 8b 44 24 30       	mov    0x30(%rsp),%rax
    2497:	4c 39 f0             	cmp    %r14,%rax
    249a:	0f 82 20 03 00 00    	jb     27c0 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x470>
    24a0:	48 8b 44 24 08       	mov    0x8(%rsp),%rax
    24a5:	41 c6 04 07 7c       	movb   $0x7c,(%r15,%rax,1)
    24aa:	48 8b 44 24 20       	mov    0x20(%rsp),%rax
    24af:	4c 89 74 24 28       	mov    %r14,0x28(%rsp)
    24b4:	42 c6 04 30 00       	movb   $0x0,(%rax,%r14,1)
    24b9:	48 8b 85 c0 00 00 00 	mov    0xc0(%rbp),%rax
    24c0:	48 85 c0             	test   %rax,%rax
    24c3:	0f 84 d7 02 00 00    	je     27a0 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x450>
    24c9:	48 c1 e3 04          	shl    $0x4,%rbx
    24cd:	48 01 d8             	add    %rbx,%rax
    24d0:	48 8b 74 24 28       	mov    0x28(%rsp),%rsi
    24d5:	44 8b 40 08          	mov    0x8(%rax),%r8d
    24d9:	48 8b 08             	mov    (%rax),%rcx
    24dc:	48 b8 ff ff ff ff ff ff ff 7f 	movabs $0x7fffffffffffffff,%rax
    24e6:	48 29 f0             	sub    %rsi,%rax
    24e9:	4c 39 c0             	cmp    %r8,%rax
    24ec:	0f 82 82 04 00 00    	jb     2974 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x624>
    24f2:	48 8b 7c 24 20       	mov    0x20(%rsp),%rdi
    24f7:	49 8d 1c 30          	lea    (%r8,%rsi,1),%rbx
    24fb:	4c 39 ef             	cmp    %r13,%rdi
    24fe:	0f 84 0c 04 00 00    	je     2910 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x5c0>
    2504:	48 8b 44 24 30       	mov    0x30(%rsp),%rax
    2509:	48 39 d8             	cmp    %rbx,%rax
    250c:	0f 82 6e 02 00 00    	jb     2780 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x430>
    2512:	4d 85 c0             	test   %r8,%r8
    2515:	74 1d                	je     2534 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x1e4>
    2517:	48 01 f7             	add    %rsi,%rdi
    251a:	49 83 f8 01          	cmp    $0x1,%r8
    251e:	0f 84 4c 03 00 00    	je     2870 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x520>
    2524:	4c 89 c2             	mov    %r8,%rdx
    2527:	48 89 ce             	mov    %rcx,%rsi
    252a:	e8 00 00 00 00       	call   252f <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x1df>
    252f:	48 8b 7c 24 20       	mov    0x20(%rsp),%rdi
    2534:	48 89 5c 24 28       	mov    %rbx,0x28(%rsp)
    2539:	c6 04 1f 00          	movb   $0x0,(%rdi,%rbx,1)
    253d:	8b 74 24 28          	mov    0x28(%rsp),%esi
    2541:	48 8b 7c 24 20       	mov    0x20(%rsp),%rdi
    2546:	e8 00 00 00 00       	call   254b <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x1fb>
    254b:	48 89 c3             	mov    %rax,%rbx
    254e:	48 85 c0             	test   %rax,%rax
    2551:	0f 84 09 01 00 00    	je     2660 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x310>
    2557:	48 8b 7c 24 20       	mov    0x20(%rsp),%rdi
    255c:	4c 39 ef             	cmp    %r13,%rdi
    255f:	74 0e                	je     256f <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x21f>
    2561:	48 8b 44 24 30       	mov    0x30(%rsp),%rax
    2566:	48 8d 70 01          	lea    0x1(%rax),%rsi
    256a:	e8 00 00 00 00       	call   256f <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x21f>
    256f:	49 89 dc             	mov    %rbx,%r12
    2572:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    257d:	0f 1f 00             	nopl   (%rax)
    2580:	48 8b 44 24 58       	mov    0x58(%rsp),%rax
    2585:	64 48 2b 04 25 28 00 00 00 	sub    %fs:0x28,%rax
    258e:	0f 85 db 03 00 00    	jne    296f <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x61f>
    2594:	48 83 c4 68          	add    $0x68,%rsp
    2598:	4c 89 e0             	mov    %r12,%rax
    259b:	5b                   	pop    %rbx
    259c:	5d                   	pop    %rbp
    259d:	41 5c                	pop    %r12
    259f:	41 5d                	pop    %r13
    25a1:	41 5e                	pop    %r14
    25a3:	41 5f                	pop    %r15
    25a5:	c3                   	ret
    25a6:	66 2e 0f 1f 84 00 00 00 00 00 	cs nopw 0x0(%rax,%rax,1)
    25b0:	48 8b 85 c0 00 00 00 	mov    0xc0(%rbp),%rax
    25b7:	89 da                	mov    %ebx,%edx
    25b9:	48 85 c0             	test   %rax,%rax
    25bc:	74 72                	je     2630 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x2e0>
    25be:	48 c1 e2 04          	shl    $0x4,%rdx
    25c2:	48 01 d0             	add    %rdx,%rax
    25c5:	48 8b 38             	mov    (%rax),%rdi
    25c8:	8b 70 08             	mov    0x8(%rax),%esi
    25cb:	e8 00 00 00 00       	call   25d0 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x280>
    25d0:	49 89 c4             	mov    %rax,%r12
    25d3:	4d 85 e4             	test   %r12,%r12
    25d6:	74 0c                	je     25e4 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x294>
    25d8:	4c 89 e7             	mov    %r12,%rdi
    25db:	e8 10 db ff ff       	call   f0 <_ZN8tomo_db012_GLOBAL__N_111child_countERKNS_15CommandMetadataE>
    25e0:	85 c0                	test   %eax,%eax
    25e2:	74 9c                	je     2580 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x230>
    25e4:	8b 85 cc 00 00 00    	mov    0xcc(%rbp),%eax
    25ea:	8d 53 01             	lea    0x1(%rbx),%edx
    25ed:	39 c2                	cmp    %eax,%edx
    25ef:	73 8f                	jae    2580 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x230>
    25f1:	48 8b 85 c0 00 00 00 	mov    0xc0(%rbp),%rax
    25f8:	48 c1 e3 04          	shl    $0x4,%rbx
    25fc:	48 85 c0             	test   %rax,%rax
    25ff:	0f 84 3b 02 00 00    	je     2840 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x4f0>
    2605:	48 01 c3             	add    %rax,%rbx
    2608:	48 8b 0b             	mov    (%rbx),%rcx
    260b:	8b 5b 08             	mov    0x8(%rbx),%ebx
    260e:	48 c1 e2 04          	shl    $0x4,%rdx
    2612:	48 01 d0             	add    %rdx,%rax
    2615:	48 8b 30             	mov    (%rax),%rsi
    2618:	8b 68 08             	mov    0x8(%rax),%ebp
    261b:	83 fb 16             	cmp    $0x16,%ebx
    261e:	0f 86 7c 00 00 00    	jbe    26a0 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x350>
    2624:	45 31 e4             	xor    %r12d,%r12d
    2627:	e9 54 ff ff ff       	jmp    2580 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x230>
    262c:	0f 1f 40 00          	nopl   0x0(%rax)
    2630:	48 83 c2 0d          	add    $0xd,%rdx
    2634:	48 c1 e2 04          	shl    $0x4,%rdx
    2638:	48 8d 44 15 00       	lea    0x0(%rbp,%rdx,1),%rax
    263d:	eb 86                	jmp    25c5 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x275>
    263f:	90                   	nop
    2640:	49 83 c5 0d          	add    $0xd,%r13
    2644:	49 c1 e5 04          	shl    $0x4,%r13
    2648:	49 01 ed             	add    %rbp,%r13
    264b:	e9 dc fd ff ff       	jmp    242c <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0xdc>
    2650:	49 8d 45 0d          	lea    0xd(%r13),%rax
    2654:	48 c1 e0 04          	shl    $0x4,%rax
    2658:	48 01 f8             	add    %rdi,%rax
    265b:	e9 99 fd ff ff       	jmp    23f9 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0xa9>
    2660:	4d 85 e4             	test   %r12,%r12
    2663:	74 10                	je     2675 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x325>
    2665:	4c 89 e7             	mov    %r12,%rdi
    2668:	e8 83 da ff ff       	call   f0 <_ZN8tomo_db012_GLOBAL__N_111child_countERKNS_15CommandMetadataE>
    266d:	85 c0                	test   %eax,%eax
    266f:	0f 85 e2 fe ff ff    	jne    2557 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x207>
    2675:	48 8b 7c 24 20       	mov    0x20(%rsp),%rdi
    267a:	4c 39 ef             	cmp    %r13,%rdi
    267d:	0f 84 fd fe ff ff    	je     2580 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x230>
    2683:	48 8b 44 24 30       	mov    0x30(%rsp),%rax
    2688:	48 8d 70 01          	lea    0x1(%rax),%rsi
    268c:	e8 00 00 00 00       	call   2691 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x341>
    2691:	e9 ea fe ff ff       	jmp    2580 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x230>
    2696:	66 2e 0f 1f 84 00 00 00 00 00 	cs nopw 0x0(%rax,%rax,1)
    26a0:	89 da                	mov    %ebx,%edx
    26a2:	b8 17 00 00 00       	mov    $0x17,%eax
    26a7:	41 89 e8             	mov    %ebp,%r8d
    26aa:	48 29 d0             	sub    %rdx,%rax
    26ad:	49 39 c0             	cmp    %rax,%r8
    26b0:	0f 83 6e ff ff ff    	jae    2624 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x2d4>
    26b6:	4c 8d 64 24 40       	lea    0x40(%rsp),%r12
    26bb:	48 89 c8             	mov    %rcx,%rax
    26be:	4c 89 e7             	mov    %r12,%rdi
    26c1:	83 fb 08             	cmp    $0x8,%ebx
    26c4:	0f 83 76 02 00 00    	jae    2940 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x5f0>
    26ca:	31 c9                	xor    %ecx,%ecx
    26cc:	f6 c3 04             	test   $0x4,%bl
    26cf:	74 09                	je     26da <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x38a>
    26d1:	8b 08                	mov    (%rax),%ecx
    26d3:	89 0f                	mov    %ecx,(%rdi)
    26d5:	b9 04 00 00 00       	mov    $0x4,%ecx
    26da:	f6 c3 02             	test   $0x2,%bl
    26dd:	74 0e                	je     26ed <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x39d>
    26df:	44 0f b7 0c 08       	movzwl (%rax,%rcx,1),%r9d
    26e4:	66 44 89 0c 0f       	mov    %r9w,(%rdi,%rcx,1)
    26e9:	48 83 c1 02          	add    $0x2,%rcx
    26ed:	f6 c3 01             	test   $0x1,%bl
    26f0:	74 07                	je     26f9 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x3a9>
    26f2:	0f b6 04 08          	movzbl (%rax,%rcx,1),%eax
    26f6:	88 04 0f             	mov    %al,(%rdi,%rcx,1)
    26f9:	c6 44 14 40 7c       	movb   $0x7c,0x40(%rsp,%rdx,1)
    26fe:	b9 17 00 00 00       	mov    $0x17,%ecx
    2703:	48 ff c2             	inc    %rdx
    2706:	49 8d 3c 14          	lea    (%r12,%rdx,1),%rdi
    270a:	48 29 d1             	sub    %rdx,%rcx
    270d:	4c 89 c2             	mov    %r8,%rdx
    2710:	e8 00 00 00 00       	call   2715 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x3c5>
    2715:	4c 89 e7             	mov    %r12,%rdi
    2718:	8d 74 1d 01          	lea    0x1(%rbp,%rbx,1),%esi
    271c:	e8 00 00 00 00       	call   2721 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x3d1>
    2721:	49 89 c4             	mov    %rax,%r12
    2724:	48 85 c0             	test   %rax,%rax
    2727:	0f 85 53 fe ff ff    	jne    2580 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x230>
    272d:	e9 f2 fe ff ff       	jmp    2624 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x2d4>
    2732:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    273d:	0f 1f 00             	nopl   (%rax)
    2740:	49 8d 7e 01          	lea    0x1(%r14),%rdi
    2744:	e8 00 00 00 00       	call   2749 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x3f9>
    2749:	4c 89 74 24 30       	mov    %r14,0x30(%rsp)
    274e:	48 89 c7             	mov    %rax,%rdi
    2751:	48 89 44 24 20       	mov    %rax,0x20(%rsp)
    2756:	4c 89 f2             	mov    %r14,%rdx
    2759:	4c 89 fe             	mov    %r15,%rsi
    275c:	e8 00 00 00 00       	call   2761 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x411>
    2761:	48 8b 44 24 20       	mov    0x20(%rsp),%rax
    2766:	e9 01 fd ff ff       	jmp    246c <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x11c>
    276b:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    2770:	41 0f b6 07          	movzbl (%r15),%eax
    2774:	88 44 24 30          	mov    %al,0x30(%rsp)
    2778:	e9 ec fc ff ff       	jmp    2469 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x119>
    277d:	0f 1f 00             	nopl   (%rax)
    2780:	4c 8d 7c 24 20       	lea    0x20(%rsp),%r15
    2785:	31 d2                	xor    %edx,%edx
    2787:	4c 89 ff             	mov    %r15,%rdi
    278a:	e8 00 00 00 00       	call   278f <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x43f>
    278f:	48 8b 7c 24 20       	mov    0x20(%rsp),%rdi
    2794:	e9 9b fd ff ff       	jmp    2534 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x1e4>
    2799:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
    27a0:	48 83 c3 0d          	add    $0xd,%rbx
    27a4:	48 c1 e3 04          	shl    $0x4,%rbx
    27a8:	48 8d 44 1d 00       	lea    0x0(%rbp,%rbx,1),%rax
    27ad:	e9 1e fd ff ff       	jmp    24d0 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x180>
    27b2:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    27bd:	0f 1f 00             	nopl   (%rax)
    27c0:	4d 85 f6             	test   %r14,%r14
    27c3:	0f 88 e8 01 00 00    	js     29b1 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x661>
    27c9:	48 01 c0             	add    %rax,%rax
    27cc:	48 89 44 24 10       	mov    %rax,0x10(%rsp)
    27d1:	49 39 c6             	cmp    %rax,%r14
    27d4:	0f 82 a6 00 00 00    	jb     2880 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x530>
    27da:	48 8b 7c 24 08       	mov    0x8(%rsp),%rdi
    27df:	4c 89 74 24 10       	mov    %r14,0x10(%rsp)
    27e4:	48 83 c7 02          	add    $0x2,%rdi
    27e8:	0f 88 9f 00 00 00    	js     288d <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x53d>
    27ee:	4c 8d 7c 24 20       	lea    0x20(%rsp),%r15
    27f3:	e8 00 00 00 00       	call   27f8 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x4a8>
    27f8:	48 83 7c 24 08 00    	cmpq   $0x0,0x8(%rsp)
    27fe:	48 8b 4c 24 20       	mov    0x20(%rsp),%rcx
    2803:	49 89 c7             	mov    %rax,%r15
    2806:	0f 85 14 01 00 00    	jne    2920 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x5d0>
    280c:	4c 39 e9             	cmp    %r13,%rcx
    280f:	74 11                	je     2822 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x4d2>
    2811:	48 8b 44 24 30       	mov    0x30(%rsp),%rax
    2816:	48 89 cf             	mov    %rcx,%rdi
    2819:	48 8d 70 01          	lea    0x1(%rax),%rsi
    281d:	e8 00 00 00 00       	call   2822 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x4d2>
    2822:	48 8b 44 24 10       	mov    0x10(%rsp),%rax
    2827:	4c 89 7c 24 20       	mov    %r15,0x20(%rsp)
    282c:	48 89 44 24 30       	mov    %rax,0x30(%rsp)
    2831:	e9 6a fc ff ff       	jmp    24a0 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x150>
    2836:	66 2e 0f 1f 84 00 00 00 00 00 	cs nopw 0x0(%rax,%rax,1)
    2840:	48 83 c2 0d          	add    $0xd,%rdx
    2844:	48 8d 44 1d 00       	lea    0x0(%rbp,%rbx,1),%rax
    2849:	48 c1 e2 04          	shl    $0x4,%rdx
    284d:	48 8b 88 d0 00 00 00 	mov    0xd0(%rax),%rcx
    2854:	8b 98 d8 00 00 00    	mov    0xd8(%rax),%ebx
    285a:	48 8d 44 15 00       	lea    0x0(%rbp,%rdx,1),%rax
    285f:	e9 b1 fd ff ff       	jmp    2615 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x2c5>
    2864:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    286f:	90                   	nop
    2870:	0f b6 01             	movzbl (%rcx),%eax
    2873:	88 07                	mov    %al,(%rdi)
    2875:	48 8b 7c 24 20       	mov    0x20(%rsp),%rdi
    287a:	e9 b5 fc ff ff       	jmp    2534 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x1e4>
    287f:	90                   	nop
    2880:	48 8d 78 01          	lea    0x1(%rax),%rdi
    2884:	48 85 c0             	test   %rax,%rax
    2887:	0f 89 61 ff ff ff    	jns    27ee <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x49e>
    288d:	48 8b 44 24 58       	mov    0x58(%rsp),%rax
    2892:	64 48 2b 04 25 28 00 00 00 	sub    %fs:0x28,%rax
    289b:	0f 85 ce 00 00 00    	jne    296f <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x61f>
    28a1:	4c 8d 7c 24 20       	lea    0x20(%rsp),%r15
    28a6:	e8 00 00 00 00       	call   28ab <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x55b>
    28ab:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    28b0:	45 31 e4             	xor    %r12d,%r12d
    28b3:	e9 32 fd ff ff       	jmp    25ea <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x29a>
    28b8:	0f 1f 84 00 00 00 00 00 	nopl   0x0(%rax,%rax,1)
    28c0:	49 83 fe 10          	cmp    $0x10,%r14
    28c4:	0f 85 d6 fb ff ff    	jne    24a0 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x150>
    28ca:	bf 1f 00 00 00       	mov    $0x1f,%edi
    28cf:	4c 8d 7c 24 20       	lea    0x20(%rsp),%r15
    28d4:	e8 00 00 00 00       	call   28d9 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x589>
    28d9:	48 8b 4c 24 20       	mov    0x20(%rsp),%rcx
    28de:	49 89 c7             	mov    %rax,%r15
    28e1:	48 c7 44 24 10 1e 00 00 00 	movq   $0x1e,0x10(%rsp)
    28ea:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
    28ef:	48 89 ce             	mov    %rcx,%rsi
    28f2:	4c 89 ff             	mov    %r15,%rdi
    28f5:	48 89 4c 24 18       	mov    %rcx,0x18(%rsp)
    28fa:	e8 00 00 00 00       	call   28ff <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x5af>
    28ff:	48 8b 4c 24 18       	mov    0x18(%rsp),%rcx
    2904:	e9 03 ff ff ff       	jmp    280c <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x4bc>
    2909:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
    2910:	b8 0f 00 00 00       	mov    $0xf,%eax
    2915:	e9 ef fb ff ff       	jmp    2509 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x1b9>
    291a:	66 0f 1f 44 00 00    	nopw   0x0(%rax,%rax,1)
    2920:	48 83 7c 24 08 01    	cmpq   $0x1,0x8(%rsp)
    2926:	75 c2                	jne    28ea <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x59a>
    2928:	0f b6 01             	movzbl (%rcx),%eax
    292b:	41 88 07             	mov    %al,(%r15)
    292e:	e9 d9 fe ff ff       	jmp    280c <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x4bc>
    2933:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    293e:	66 90                	xchg   %ax,%ax
    2940:	41 89 da             	mov    %ebx,%r10d
    2943:	31 c0                	xor    %eax,%eax
    2945:	41 83 e2 f8          	and    $0xfffffff8,%r10d
    2949:	89 c7                	mov    %eax,%edi
    294b:	83 c0 08             	add    $0x8,%eax
    294e:	4c 8b 0c 39          	mov    (%rcx,%rdi,1),%r9
    2952:	4d 89 0c 3c          	mov    %r9,(%r12,%rdi,1)
    2956:	44 39 d0             	cmp    %r10d,%eax
    2959:	72 ee                	jb     2949 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x5f9>
    295b:	49 8d 3c 04          	lea    (%r12,%rax,1),%rdi
    295f:	48 01 c8             	add    %rcx,%rax
    2962:	e9 63 fd ff ff       	jmp    26ca <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x37a>
    2967:	4c 89 ef             	mov    %r13,%rdi
    296a:	e9 e7 fd ff ff       	jmp    2756 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x406>
    296f:	e8 00 00 00 00       	call   2974 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x624>
    2974:	48 8b 44 24 58       	mov    0x58(%rsp),%rax
    2979:	64 48 2b 04 25 28 00 00 00 	sub    %fs:0x28,%rax
    2982:	75 eb                	jne    296f <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x61f>
    2984:	48 8d 3d 00 00 00 00 	lea    0x0(%rip),%rdi        # 298b <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x63b>
    298b:	4c 8d 7c 24 20       	lea    0x20(%rsp),%r15
    2990:	e8 00 00 00 00       	call   2995 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x645>
    2995:	48 8b 44 24 58       	mov    0x58(%rsp),%rax
    299a:	64 48 2b 04 25 28 00 00 00 	sub    %fs:0x28,%rax
    29a3:	75 ca                	jne    296f <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x61f>
    29a5:	48 8d 3d 00 00 00 00 	lea    0x0(%rip),%rdi        # 29ac <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x65c>
    29ac:	e8 00 00 00 00       	call   29b1 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x661>
    29b1:	48 8b 44 24 58       	mov    0x58(%rsp),%rax
    29b6:	64 48 2b 04 25 28 00 00 00 	sub    %fs:0x28,%rax
    29bf:	75 ae                	jne    296f <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x61f>
    29c1:	48 8d 3d 00 00 00 00 	lea    0x0(%rip),%rdi        # 29c8 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x678>
    29c8:	4c 8d 7c 24 20       	lea    0x20(%rsp),%r15
    29cd:	e8 00 00 00 00       	call   29d2 <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x682>
    29d2:	f3 0f 1e fa          	endbr64
    29d6:	48 89 c3             	mov    %rax,%rbx
    29d9:	e9 00 00 00 00       	jmp    29de <_ZN8tomo_db024command_metadata_resolveERNS_2OpEj+0x68e>

Disassembly of section .text._ZNSt6vectorIPKN8tomo_db015CommandMetadataESaIS3_EED2Ev:

Disassembly of section .text._ZN8tomo_db02Op4Sink6appendEPKcm:

Disassembly of section .text.unlikely:

Disassembly of section .text._ZN8tomo_db016reply_map_headerIRNS_2Op4SinkEEEvOT_mb:

Disassembly of section .text._ZN8tomo_db018reply_array_headerIRNS_2Op4SinkEEEvOT_m:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE9_M_mutateEmmPKcm:

Disassembly of section .text.startup:
