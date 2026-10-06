
build/cmdmeta/POST/src/cmd/cmdmeta.o:     file format elf64-x86-64


Disassembly of section .text:

0000000000002360 <_ZN4tomo24command_metadata_resolveERNS_2OpEj>:
    2360:	f3 0f 1e fa          	endbr64
    2364:	41 57                	push   %r15
    2366:	41 56                	push   %r14
    2368:	41 55                	push   %r13
    236a:	41 54                	push   %r12
    236c:	55                   	push   %rbp
    236d:	53                   	push   %rbx
    236e:	48 89 fd             	mov    %rdi,%rbp
    2371:	48 83 ec 68          	sub    $0x68,%rsp
    2375:	89 f3                	mov    %esi,%ebx
    2377:	64 48 8b 04 25 28 00 00 00 	mov    %fs:0x28,%rax
    2380:	48 89 44 24 58       	mov    %rax,0x58(%rsp)
    2385:	31 c0                	xor    %eax,%eax
    2387:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    238c:	8b 87 cc 00 00 00    	mov    0xcc(%rdi),%eax
    2392:	39 c3                	cmp    %eax,%ebx
    2394:	0f 83 97 02 00 00    	jae    2631 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x2d1>
    239a:	85 db                	test   %ebx,%ebx
    239c:	0f 85 1e 02 00 00    	jne    25c0 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x260>
    23a2:	48 8b 17             	mov    (%rdi),%rdx
    23a5:	48 85 d2             	test   %rdx,%rdx
    23a8:	0f 84 12 02 00 00    	je     25c0 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x260>
    23ae:	0f b7 72 26          	movzwl 0x26(%rdx),%esi
    23b2:	48 8b 0d 00 00 00 00 	mov    0x0(%rip),%rcx        # 23b9 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x59>
    23b9:	48 8b 15 00 00 00 00 	mov    0x0(%rip),%rdx        # 23c0 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x60>
    23c0:	48 29 ca             	sub    %rcx,%rdx
    23c3:	48 c1 fa 03          	sar    $0x3,%rdx
    23c7:	48 39 d6             	cmp    %rdx,%rsi
    23ca:	0f 83 f0 04 00 00    	jae    28c0 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x560>
    23d0:	4c 8b 24 f1          	mov    (%rcx,%rsi,8),%r12
    23d4:	e9 0b 02 00 00       	jmp    25e4 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x284>
    23d9:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
    23e0:	3b 9f cc 00 00 00    	cmp    0xcc(%rdi),%ebx
    23e6:	0f 83 45 02 00 00    	jae    2631 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x2d1>
    23ec:	48 8b 87 c0 00 00 00 	mov    0xc0(%rdi),%rax
    23f3:	41 89 dd             	mov    %ebx,%r13d
    23f6:	48 85 c0             	test   %rax,%rax
    23f9:	0f 84 61 02 00 00    	je     2660 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x300>
    23ff:	4c 89 ea             	mov    %r13,%rdx
    2402:	48 c1 e2 04          	shl    $0x4,%rdx
    2406:	48 01 d0             	add    %rdx,%rax
    2409:	48 8b 38             	mov    (%rax),%rdi
    240c:	48 8b 70 08          	mov    0x8(%rax),%rsi
    2410:	ff c3                	inc    %ebx
    2412:	e8 00 00 00 00       	call   2417 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0xb7>
    2417:	49 89 c4             	mov    %rax,%r12
    241a:	3b 9d cc 00 00 00    	cmp    0xcc(%rbp),%ebx
    2420:	0f 83 6a 01 00 00    	jae    2590 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x230>
    2426:	48 8b 85 c0 00 00 00 	mov    0xc0(%rbp),%rax
    242d:	48 85 c0             	test   %rax,%rax
    2430:	0f 84 1a 02 00 00    	je     2650 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x2f0>
    2436:	49 c1 e5 04          	shl    $0x4,%r13
    243a:	49 01 c5             	add    %rax,%r13
    243d:	4d 8b 7d 00          	mov    0x0(%r13),%r15
    2441:	45 8b 75 08          	mov    0x8(%r13),%r14d
    2445:	4c 8d 6c 24 30       	lea    0x30(%rsp),%r13
    244a:	4c 89 6c 24 20       	mov    %r13,0x20(%rsp)
    244f:	4d 85 ff             	test   %r15,%r15
    2452:	75 09                	jne    245d <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0xfd>
    2454:	4d 85 f6             	test   %r14,%r14
    2457:	0f 85 48 05 00 00    	jne    29a5 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x645>
    245d:	49 83 fe 0f          	cmp    $0xf,%r14
    2461:	0f 87 e9 02 00 00    	ja     2750 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x3f0>
    2467:	49 83 fe 01          	cmp    $0x1,%r14
    246b:	0f 84 0f 03 00 00    	je     2780 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x420>
    2471:	4d 85 f6             	test   %r14,%r14
    2474:	0f 85 fd 04 00 00    	jne    2977 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x617>
    247a:	4c 89 e8             	mov    %r13,%rax
    247d:	4c 89 74 24 28       	mov    %r14,0x28(%rsp)
    2482:	42 c6 04 30 00       	movb   $0x0,(%rax,%r14,1)
    2487:	48 8b 44 24 28       	mov    0x28(%rsp),%rax
    248c:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
    2491:	4c 8d 70 01          	lea    0x1(%rax),%r14
    2495:	48 89 44 24 08       	mov    %rax,0x8(%rsp)
    249a:	4d 39 ef             	cmp    %r13,%r15
    249d:	0f 84 2d 04 00 00    	je     28d0 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x570>
    24a3:	48 8b 44 24 30       	mov    0x30(%rsp),%rax
    24a8:	4c 39 f0             	cmp    %r14,%rax
    24ab:	0f 82 1f 03 00 00    	jb     27d0 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x470>
    24b1:	48 8b 44 24 08       	mov    0x8(%rsp),%rax
    24b6:	41 c6 04 07 7c       	movb   $0x7c,(%r15,%rax,1)
    24bb:	48 8b 44 24 20       	mov    0x20(%rsp),%rax
    24c0:	4c 89 74 24 28       	mov    %r14,0x28(%rsp)
    24c5:	42 c6 04 30 00       	movb   $0x0,(%rax,%r14,1)
    24ca:	48 8b 85 c0 00 00 00 	mov    0xc0(%rbp),%rax
    24d1:	48 85 c0             	test   %rax,%rax
    24d4:	0f 84 d6 02 00 00    	je     27b0 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x450>
    24da:	48 c1 e3 04          	shl    $0x4,%rbx
    24de:	48 01 d8             	add    %rbx,%rax
    24e1:	48 8b 74 24 28       	mov    0x28(%rsp),%rsi
    24e6:	44 8b 40 08          	mov    0x8(%rax),%r8d
    24ea:	48 8b 08             	mov    (%rax),%rcx
    24ed:	48 b8 ff ff ff ff ff ff ff 7f 	movabs $0x7fffffffffffffff,%rax
    24f7:	48 29 f0             	sub    %rsi,%rax
    24fa:	4c 39 c0             	cmp    %r8,%rax
    24fd:	0f 82 81 04 00 00    	jb     2984 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x624>
    2503:	48 8b 7c 24 20       	mov    0x20(%rsp),%rdi
    2508:	49 8d 1c 30          	lea    (%r8,%rsi,1),%rbx
    250c:	4c 39 ef             	cmp    %r13,%rdi
    250f:	0f 84 0b 04 00 00    	je     2920 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x5c0>
    2515:	48 8b 44 24 30       	mov    0x30(%rsp),%rax
    251a:	48 39 d8             	cmp    %rbx,%rax
    251d:	0f 82 6d 02 00 00    	jb     2790 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x430>
    2523:	4d 85 c0             	test   %r8,%r8
    2526:	74 1d                	je     2545 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x1e5>
    2528:	48 01 f7             	add    %rsi,%rdi
    252b:	49 83 f8 01          	cmp    $0x1,%r8
    252f:	0f 84 4b 03 00 00    	je     2880 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x520>
    2535:	4c 89 c2             	mov    %r8,%rdx
    2538:	48 89 ce             	mov    %rcx,%rsi
    253b:	e8 00 00 00 00       	call   2540 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x1e0>
    2540:	48 8b 7c 24 20       	mov    0x20(%rsp),%rdi
    2545:	48 89 5c 24 28       	mov    %rbx,0x28(%rsp)
    254a:	c6 04 1f 00          	movb   $0x0,(%rdi,%rbx,1)
    254e:	8b 74 24 28          	mov    0x28(%rsp),%esi
    2552:	48 8b 7c 24 20       	mov    0x20(%rsp),%rdi
    2557:	e8 00 00 00 00       	call   255c <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x1fc>
    255c:	48 89 c3             	mov    %rax,%rbx
    255f:	48 85 c0             	test   %rax,%rax
    2562:	0f 84 08 01 00 00    	je     2670 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x310>
    2568:	48 8b 7c 24 20       	mov    0x20(%rsp),%rdi
    256d:	4c 39 ef             	cmp    %r13,%rdi
    2570:	74 0e                	je     2580 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x220>
    2572:	48 8b 44 24 30       	mov    0x30(%rsp),%rax
    2577:	48 8d 70 01          	lea    0x1(%rax),%rsi
    257b:	e8 00 00 00 00       	call   2580 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x220>
    2580:	49 89 dc             	mov    %rbx,%r12
    2583:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    258e:	66 90                	xchg   %ax,%ax
    2590:	48 8b 44 24 58       	mov    0x58(%rsp),%rax
    2595:	64 48 2b 04 25 28 00 00 00 	sub    %fs:0x28,%rax
    259e:	0f 85 db 03 00 00    	jne    297f <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x61f>
    25a4:	48 83 c4 68          	add    $0x68,%rsp
    25a8:	4c 89 e0             	mov    %r12,%rax
    25ab:	5b                   	pop    %rbx
    25ac:	5d                   	pop    %rbp
    25ad:	41 5c                	pop    %r12
    25af:	41 5d                	pop    %r13
    25b1:	41 5e                	pop    %r14
    25b3:	41 5f                	pop    %r15
    25b5:	c3                   	ret
    25b6:	66 2e 0f 1f 84 00 00 00 00 00 	cs nopw 0x0(%rax,%rax,1)
    25c0:	48 8b 85 c0 00 00 00 	mov    0xc0(%rbp),%rax
    25c7:	89 da                	mov    %ebx,%edx
    25c9:	48 85 c0             	test   %rax,%rax
    25cc:	74 72                	je     2640 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x2e0>
    25ce:	48 c1 e2 04          	shl    $0x4,%rdx
    25d2:	48 01 d0             	add    %rdx,%rax
    25d5:	48 8b 38             	mov    (%rax),%rdi
    25d8:	48 8b 70 08          	mov    0x8(%rax),%rsi
    25dc:	e8 00 00 00 00       	call   25e1 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x281>
    25e1:	49 89 c4             	mov    %rax,%r12
    25e4:	4d 85 e4             	test   %r12,%r12
    25e7:	74 0c                	je     25f5 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x295>
    25e9:	4c 89 e7             	mov    %r12,%rdi
    25ec:	e8 ff da ff ff       	call   f0 <_ZN4tomo12_GLOBAL__N_111child_countERKNS_15CommandMetadataE>
    25f1:	85 c0                	test   %eax,%eax
    25f3:	74 9b                	je     2590 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x230>
    25f5:	8b 85 cc 00 00 00    	mov    0xcc(%rbp),%eax
    25fb:	8d 53 01             	lea    0x1(%rbx),%edx
    25fe:	39 c2                	cmp    %eax,%edx
    2600:	73 8e                	jae    2590 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x230>
    2602:	48 8b 85 c0 00 00 00 	mov    0xc0(%rbp),%rax
    2609:	48 c1 e3 04          	shl    $0x4,%rbx
    260d:	48 85 c0             	test   %rax,%rax
    2610:	0f 84 3a 02 00 00    	je     2850 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x4f0>
    2616:	48 01 c3             	add    %rax,%rbx
    2619:	48 8b 0b             	mov    (%rbx),%rcx
    261c:	8b 5b 08             	mov    0x8(%rbx),%ebx
    261f:	48 c1 e2 04          	shl    $0x4,%rdx
    2623:	48 01 d0             	add    %rdx,%rax
    2626:	48 8b 30             	mov    (%rax),%rsi
    2629:	8b 68 08             	mov    0x8(%rax),%ebp
    262c:	83 fb 16             	cmp    $0x16,%ebx
    262f:	76 7f                	jbe    26b0 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x350>
    2631:	45 31 e4             	xor    %r12d,%r12d
    2634:	e9 57 ff ff ff       	jmp    2590 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x230>
    2639:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
    2640:	48 83 c2 0d          	add    $0xd,%rdx
    2644:	48 c1 e2 04          	shl    $0x4,%rdx
    2648:	48 8d 44 15 00       	lea    0x0(%rbp,%rdx,1),%rax
    264d:	eb 86                	jmp    25d5 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x275>
    264f:	90                   	nop
    2650:	49 83 c5 0d          	add    $0xd,%r13
    2654:	49 c1 e5 04          	shl    $0x4,%r13
    2658:	49 01 ed             	add    %rbp,%r13
    265b:	e9 dd fd ff ff       	jmp    243d <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0xdd>
    2660:	49 8d 45 0d          	lea    0xd(%r13),%rax
    2664:	48 c1 e0 04          	shl    $0x4,%rax
    2668:	48 01 f8             	add    %rdi,%rax
    266b:	e9 99 fd ff ff       	jmp    2409 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0xa9>
    2670:	4d 85 e4             	test   %r12,%r12
    2673:	74 10                	je     2685 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x325>
    2675:	4c 89 e7             	mov    %r12,%rdi
    2678:	e8 73 da ff ff       	call   f0 <_ZN4tomo12_GLOBAL__N_111child_countERKNS_15CommandMetadataE>
    267d:	85 c0                	test   %eax,%eax
    267f:	0f 85 e3 fe ff ff    	jne    2568 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x208>
    2685:	48 8b 7c 24 20       	mov    0x20(%rsp),%rdi
    268a:	4c 39 ef             	cmp    %r13,%rdi
    268d:	0f 84 fd fe ff ff    	je     2590 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x230>
    2693:	48 8b 44 24 30       	mov    0x30(%rsp),%rax
    2698:	48 8d 70 01          	lea    0x1(%rax),%rsi
    269c:	e8 00 00 00 00       	call   26a1 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x341>
    26a1:	e9 ea fe ff ff       	jmp    2590 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x230>
    26a6:	66 2e 0f 1f 84 00 00 00 00 00 	cs nopw 0x0(%rax,%rax,1)
    26b0:	89 da                	mov    %ebx,%edx
    26b2:	b8 17 00 00 00       	mov    $0x17,%eax
    26b7:	41 89 e8             	mov    %ebp,%r8d
    26ba:	48 29 d0             	sub    %rdx,%rax
    26bd:	49 39 c0             	cmp    %rax,%r8
    26c0:	0f 83 6b ff ff ff    	jae    2631 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x2d1>
    26c6:	4c 8d 64 24 40       	lea    0x40(%rsp),%r12
    26cb:	48 89 c8             	mov    %rcx,%rax
    26ce:	4c 89 e7             	mov    %r12,%rdi
    26d1:	83 fb 08             	cmp    $0x8,%ebx
    26d4:	0f 83 76 02 00 00    	jae    2950 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x5f0>
    26da:	31 c9                	xor    %ecx,%ecx
    26dc:	f6 c3 04             	test   $0x4,%bl
    26df:	74 09                	je     26ea <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x38a>
    26e1:	8b 08                	mov    (%rax),%ecx
    26e3:	89 0f                	mov    %ecx,(%rdi)
    26e5:	b9 04 00 00 00       	mov    $0x4,%ecx
    26ea:	f6 c3 02             	test   $0x2,%bl
    26ed:	74 0e                	je     26fd <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x39d>
    26ef:	44 0f b7 0c 08       	movzwl (%rax,%rcx,1),%r9d
    26f4:	66 44 89 0c 0f       	mov    %r9w,(%rdi,%rcx,1)
    26f9:	48 83 c1 02          	add    $0x2,%rcx
    26fd:	f6 c3 01             	test   $0x1,%bl
    2700:	74 07                	je     2709 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x3a9>
    2702:	0f b6 04 08          	movzbl (%rax,%rcx,1),%eax
    2706:	88 04 0f             	mov    %al,(%rdi,%rcx,1)
    2709:	c6 44 14 40 7c       	movb   $0x7c,0x40(%rsp,%rdx,1)
    270e:	b9 17 00 00 00       	mov    $0x17,%ecx
    2713:	48 ff c2             	inc    %rdx
    2716:	49 8d 3c 14          	lea    (%r12,%rdx,1),%rdi
    271a:	48 29 d1             	sub    %rdx,%rcx
    271d:	4c 89 c2             	mov    %r8,%rdx
    2720:	e8 00 00 00 00       	call   2725 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x3c5>
    2725:	4c 89 e7             	mov    %r12,%rdi
    2728:	8d 74 1d 01          	lea    0x1(%rbp,%rbx,1),%esi
    272c:	e8 00 00 00 00       	call   2731 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x3d1>
    2731:	49 89 c4             	mov    %rax,%r12
    2734:	48 85 c0             	test   %rax,%rax
    2737:	0f 85 53 fe ff ff    	jne    2590 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x230>
    273d:	e9 ef fe ff ff       	jmp    2631 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x2d1>
    2742:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    274d:	0f 1f 00             	nopl   (%rax)
    2750:	49 8d 7e 01          	lea    0x1(%r14),%rdi
    2754:	e8 00 00 00 00       	call   2759 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x3f9>
    2759:	4c 89 74 24 30       	mov    %r14,0x30(%rsp)
    275e:	48 89 c7             	mov    %rax,%rdi
    2761:	48 89 44 24 20       	mov    %rax,0x20(%rsp)
    2766:	4c 89 f2             	mov    %r14,%rdx
    2769:	4c 89 fe             	mov    %r15,%rsi
    276c:	e8 00 00 00 00       	call   2771 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x411>
    2771:	48 8b 44 24 20       	mov    0x20(%rsp),%rax
    2776:	e9 02 fd ff ff       	jmp    247d <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x11d>
    277b:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    2780:	41 0f b6 07          	movzbl (%r15),%eax
    2784:	88 44 24 30          	mov    %al,0x30(%rsp)
    2788:	e9 ed fc ff ff       	jmp    247a <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x11a>
    278d:	0f 1f 00             	nopl   (%rax)
    2790:	4c 8d 7c 24 20       	lea    0x20(%rsp),%r15
    2795:	31 d2                	xor    %edx,%edx
    2797:	4c 89 ff             	mov    %r15,%rdi
    279a:	e8 00 00 00 00       	call   279f <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x43f>
    279f:	48 8b 7c 24 20       	mov    0x20(%rsp),%rdi
    27a4:	e9 9c fd ff ff       	jmp    2545 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x1e5>
    27a9:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
    27b0:	48 83 c3 0d          	add    $0xd,%rbx
    27b4:	48 c1 e3 04          	shl    $0x4,%rbx
    27b8:	48 8d 44 1d 00       	lea    0x0(%rbp,%rbx,1),%rax
    27bd:	e9 1f fd ff ff       	jmp    24e1 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x181>
    27c2:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    27cd:	0f 1f 00             	nopl   (%rax)
    27d0:	4d 85 f6             	test   %r14,%r14
    27d3:	0f 88 e8 01 00 00    	js     29c1 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x661>
    27d9:	48 01 c0             	add    %rax,%rax
    27dc:	48 89 44 24 10       	mov    %rax,0x10(%rsp)
    27e1:	49 39 c6             	cmp    %rax,%r14
    27e4:	0f 82 a6 00 00 00    	jb     2890 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x530>
    27ea:	48 8b 7c 24 08       	mov    0x8(%rsp),%rdi
    27ef:	4c 89 74 24 10       	mov    %r14,0x10(%rsp)
    27f4:	48 83 c7 02          	add    $0x2,%rdi
    27f8:	0f 88 9f 00 00 00    	js     289d <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x53d>
    27fe:	4c 8d 7c 24 20       	lea    0x20(%rsp),%r15
    2803:	e8 00 00 00 00       	call   2808 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x4a8>
    2808:	48 83 7c 24 08 00    	cmpq   $0x0,0x8(%rsp)
    280e:	48 8b 4c 24 20       	mov    0x20(%rsp),%rcx
    2813:	49 89 c7             	mov    %rax,%r15
    2816:	0f 85 14 01 00 00    	jne    2930 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x5d0>
    281c:	4c 39 e9             	cmp    %r13,%rcx
    281f:	74 11                	je     2832 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x4d2>
    2821:	48 8b 44 24 30       	mov    0x30(%rsp),%rax
    2826:	48 89 cf             	mov    %rcx,%rdi
    2829:	48 8d 70 01          	lea    0x1(%rax),%rsi
    282d:	e8 00 00 00 00       	call   2832 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x4d2>
    2832:	48 8b 44 24 10       	mov    0x10(%rsp),%rax
    2837:	4c 89 7c 24 20       	mov    %r15,0x20(%rsp)
    283c:	48 89 44 24 30       	mov    %rax,0x30(%rsp)
    2841:	e9 6b fc ff ff       	jmp    24b1 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x151>
    2846:	66 2e 0f 1f 84 00 00 00 00 00 	cs nopw 0x0(%rax,%rax,1)
    2850:	48 83 c2 0d          	add    $0xd,%rdx
    2854:	48 8d 44 1d 00       	lea    0x0(%rbp,%rbx,1),%rax
    2859:	48 c1 e2 04          	shl    $0x4,%rdx
    285d:	48 8b 88 d0 00 00 00 	mov    0xd0(%rax),%rcx
    2864:	8b 98 d8 00 00 00    	mov    0xd8(%rax),%ebx
    286a:	48 8d 44 15 00       	lea    0x0(%rbp,%rdx,1),%rax
    286f:	e9 b2 fd ff ff       	jmp    2626 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x2c6>
    2874:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    287f:	90                   	nop
    2880:	0f b6 01             	movzbl (%rcx),%eax
    2883:	88 07                	mov    %al,(%rdi)
    2885:	48 8b 7c 24 20       	mov    0x20(%rsp),%rdi
    288a:	e9 b6 fc ff ff       	jmp    2545 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x1e5>
    288f:	90                   	nop
    2890:	48 8d 78 01          	lea    0x1(%rax),%rdi
    2894:	48 85 c0             	test   %rax,%rax
    2897:	0f 89 61 ff ff ff    	jns    27fe <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x49e>
    289d:	48 8b 44 24 58       	mov    0x58(%rsp),%rax
    28a2:	64 48 2b 04 25 28 00 00 00 	sub    %fs:0x28,%rax
    28ab:	0f 85 ce 00 00 00    	jne    297f <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x61f>
    28b1:	4c 8d 7c 24 20       	lea    0x20(%rsp),%r15
    28b6:	e8 00 00 00 00       	call   28bb <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x55b>
    28bb:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    28c0:	45 31 e4             	xor    %r12d,%r12d
    28c3:	e9 33 fd ff ff       	jmp    25fb <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x29b>
    28c8:	0f 1f 84 00 00 00 00 00 	nopl   0x0(%rax,%rax,1)
    28d0:	49 83 fe 10          	cmp    $0x10,%r14
    28d4:	0f 85 d7 fb ff ff    	jne    24b1 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x151>
    28da:	bf 1f 00 00 00       	mov    $0x1f,%edi
    28df:	4c 8d 7c 24 20       	lea    0x20(%rsp),%r15
    28e4:	e8 00 00 00 00       	call   28e9 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x589>
    28e9:	48 8b 4c 24 20       	mov    0x20(%rsp),%rcx
    28ee:	49 89 c7             	mov    %rax,%r15
    28f1:	48 c7 44 24 10 1e 00 00 00 	movq   $0x1e,0x10(%rsp)
    28fa:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
    28ff:	48 89 ce             	mov    %rcx,%rsi
    2902:	4c 89 ff             	mov    %r15,%rdi
    2905:	48 89 4c 24 18       	mov    %rcx,0x18(%rsp)
    290a:	e8 00 00 00 00       	call   290f <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x5af>
    290f:	48 8b 4c 24 18       	mov    0x18(%rsp),%rcx
    2914:	e9 03 ff ff ff       	jmp    281c <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x4bc>
    2919:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
    2920:	b8 0f 00 00 00       	mov    $0xf,%eax
    2925:	e9 f0 fb ff ff       	jmp    251a <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x1ba>
    292a:	66 0f 1f 44 00 00    	nopw   0x0(%rax,%rax,1)
    2930:	48 83 7c 24 08 01    	cmpq   $0x1,0x8(%rsp)
    2936:	75 c2                	jne    28fa <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x59a>
    2938:	0f b6 01             	movzbl (%rcx),%eax
    293b:	41 88 07             	mov    %al,(%r15)
    293e:	e9 d9 fe ff ff       	jmp    281c <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x4bc>
    2943:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    294e:	66 90                	xchg   %ax,%ax
    2950:	41 89 da             	mov    %ebx,%r10d
    2953:	31 c0                	xor    %eax,%eax
    2955:	41 83 e2 f8          	and    $0xfffffff8,%r10d
    2959:	89 c7                	mov    %eax,%edi
    295b:	83 c0 08             	add    $0x8,%eax
    295e:	4c 8b 0c 39          	mov    (%rcx,%rdi,1),%r9
    2962:	4d 89 0c 3c          	mov    %r9,(%r12,%rdi,1)
    2966:	44 39 d0             	cmp    %r10d,%eax
    2969:	72 ee                	jb     2959 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x5f9>
    296b:	49 8d 3c 04          	lea    (%r12,%rax,1),%rdi
    296f:	48 01 c8             	add    %rcx,%rax
    2972:	e9 63 fd ff ff       	jmp    26da <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x37a>
    2977:	4c 89 ef             	mov    %r13,%rdi
    297a:	e9 e7 fd ff ff       	jmp    2766 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x406>
    297f:	e8 00 00 00 00       	call   2984 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x624>
    2984:	48 8b 44 24 58       	mov    0x58(%rsp),%rax
    2989:	64 48 2b 04 25 28 00 00 00 	sub    %fs:0x28,%rax
    2992:	75 eb                	jne    297f <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x61f>
    2994:	48 8d 3d 00 00 00 00 	lea    0x0(%rip),%rdi        # 299b <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x63b>
    299b:	4c 8d 7c 24 20       	lea    0x20(%rsp),%r15
    29a0:	e8 00 00 00 00       	call   29a5 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x645>
    29a5:	48 8b 44 24 58       	mov    0x58(%rsp),%rax
    29aa:	64 48 2b 04 25 28 00 00 00 	sub    %fs:0x28,%rax
    29b3:	75 ca                	jne    297f <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x61f>
    29b5:	48 8d 3d 00 00 00 00 	lea    0x0(%rip),%rdi        # 29bc <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x65c>
    29bc:	e8 00 00 00 00       	call   29c1 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x661>
    29c1:	48 8b 44 24 58       	mov    0x58(%rsp),%rax
    29c6:	64 48 2b 04 25 28 00 00 00 	sub    %fs:0x28,%rax
    29cf:	75 ae                	jne    297f <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x61f>
    29d1:	48 8d 3d 00 00 00 00 	lea    0x0(%rip),%rdi        # 29d8 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x678>
    29d8:	4c 8d 7c 24 20       	lea    0x20(%rsp),%r15
    29dd:	e8 00 00 00 00       	call   29e2 <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x682>
    29e2:	f3 0f 1e fa          	endbr64
    29e6:	48 89 c3             	mov    %rax,%rbx
    29e9:	e9 00 00 00 00       	jmp    29ee <_ZN4tomo24command_metadata_resolveERNS_2OpEj+0x68e>

Disassembly of section .text._ZNSt6vectorIPKN4tomo15CommandMetadataESaIS3_EED2Ev:

Disassembly of section .text._ZN4tomo2Op4Sink6appendEPKcm:

Disassembly of section .text.unlikely:

Disassembly of section .text._ZN4tomo16reply_map_headerIRNS_2Op4SinkEEEvOT_mb:

Disassembly of section .text._ZN4tomo18reply_array_headerIRNS_2Op4SinkEEEvOT_m:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE9_M_mutateEmmPKcm:

Disassembly of section .text.startup:
