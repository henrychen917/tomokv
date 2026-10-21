0000000000000580 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]>:
     580:	41 56                	push   %r14
     582:	41 55                	push   %r13
     584:	41 54                	push   %r12
     586:	49 89 d5             	mov    %rdx,%r13
     589:	55                   	push   %rbp
     58a:	48 89 fd             	mov    %rdi,%rbp
     58d:	53                   	push   %rbx
     58e:	89 cf                	mov    %ecx,%edi
     590:	48 8b 4d 18          	mov    0x18(%rbp),%rcx
     594:	8b 45 04             	mov    0x4(%rbp),%eax
     597:	4c 89 c2             	mov    %r8,%rdx
     59a:	4c 29 ca             	sub    %r9,%rdx
     59d:	49 89 ce             	mov    %rcx,%r14
     5a0:	49 29 c6             	sub    %rax,%r14
     5a3:	4d 39 c1             	cmp    %r8,%r9
     5a6:	44 8b 4d 08          	mov    0x8(%rbp),%r9d
     5aa:	41 b8 00 00 00 00    	mov    $0x0,%r8d
     5b0:	49 0f 43 d0          	cmovae %r8,%rdx
     5b4:	4a 8d 5c 0a 01       	lea    0x1(%rdx,%r9,1),%rbx
     5b9:	ba ff ff ff ff       	mov    $0xffffffff,%edx
     5be:	4d 89 c8             	mov    %r9,%r8
     5c1:	48 39 d3             	cmp    %rdx,%rbx
     5c4:	48 0f 47 da          	cmova  %rdx,%rbx
     5c8:	41 39 c1             	cmp    %eax,%r9d
     5cb:	73 19                	jae    5e6 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x66>
     5cd:	48 8b 55 10          	mov    0x10(%rbp),%rdx
     5d1:	42 80 3c 0a 2a       	cmpb   $0x2a,(%rdx,%r9,1)
     5d6:	74 0e                	je     5e6 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x66>
     5d8:	49 81 c1 01 00 01 00 	add    $0x10001,%r9
     5df:	4c 39 cb             	cmp    %r9,%rbx
     5e2:	49 0f 47 d9          	cmova  %r9,%rbx
     5e6:	ba 00 00 10 00       	mov    $0x100000,%edx
     5eb:	48 39 d3             	cmp    %rdx,%rbx
     5ee:	48 0f 46 d3          	cmovbe %rbx,%rdx
     5f2:	45 85 c0             	test   %r8d,%r8d
     5f5:	48 0f 44 d3          	cmove  %rbx,%rdx
     5f9:	49 39 f6             	cmp    %rsi,%r14
     5fc:	41 0f 92 c0          	setb   %r8b
     600:	41 84 f8             	test   %dil,%r8b
     603:	74 05                	je     60a <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x8a>
     605:	48 39 d1             	cmp    %rdx,%rcx
     608:	72 66                	jb     670 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0xf0>
     60a:	48 39 d8             	cmp    %rbx,%rax
     60d:	73 41                	jae    650 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0xd0>
     60f:	48 89 da             	mov    %rbx,%rdx
     612:	48 29 c2             	sub    %rax,%rdx
     615:	4c 39 f2             	cmp    %r14,%rdx
     618:	49 0f 47 d6          	cmova  %r14,%rdx
     61c:	48 85 d2             	test   %rdx,%rdx
     61f:	74 31                	je     652 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0xd2>
     621:	48 81 fa ff 07 00 00 	cmp    $0x7ff,%rdx
     628:	76 16                	jbe    640 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0xc0>
     62a:	48 03 45 10          	add    0x10(%rbp),%rax
     62e:	49 89 55 00          	mov    %rdx,0x0(%r13)
     632:	5b                   	pop    %rbx
     633:	5d                   	pop    %rbp
     634:	41 5c                	pop    %r12
     636:	41 5d                	pop    %r13
     638:	41 5e                	pop    %r14
     63a:	c3                   	ret
     63b:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
     640:	48 8d 0c 10          	lea    (%rax,%rdx,1),%rcx
     644:	48 39 cb             	cmp    %rcx,%rbx
     647:	74 e1                	je     62a <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0xaa>
     649:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
     650:	31 d2                	xor    %edx,%edx
     652:	49 89 55 00          	mov    %rdx,0x0(%r13)
     656:	31 c0                	xor    %eax,%eax
     658:	5b                   	pop    %rbx
     659:	5d                   	pop    %rbp
     65a:	41 5c                	pop    %r12
     65c:	41 5d                	pop    %r13
     65e:	41 5e                	pop    %r14
     660:	c3                   	ret
     661:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
     66c:	0f 1f 40 00          	nopl   0x0(%rax)
     670:	48 01 c6             	add    %rax,%rsi
     673:	48 01 c9             	add    %rcx,%rcx
     676:	48 39 d6             	cmp    %rdx,%rsi
     679:	48 0f 47 f2          	cmova  %rdx,%rsi
     67d:	48 39 f1             	cmp    %rsi,%rcx
     680:	73 16                	jae    698 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x118>
     682:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
     68d:	0f 1f 00             	nopl   (%rax)
     690:	48 01 c9             	add    %rcx,%rcx
     693:	48 39 f1             	cmp    %rsi,%rcx
     696:	72 f8                	jb     690 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x110>
     698:	48 8b 7d 10          	mov    0x10(%rbp),%rdi
     69c:	48 39 ca             	cmp    %rcx,%rdx
     69f:	48 0f 46 ca          	cmovbe %rdx,%rcx
     6a3:	48 89 ce             	mov    %rcx,%rsi
     6a6:	49 89 cc             	mov    %rcx,%r12
     6a9:	e8 00 00 00 00       	call   6ae <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x12e>	6aa: R_X86_64_PLT32	realloc-0x4
     6ae:	48 85 c0             	test   %rax,%rax
     6b1:	74 16                	je     6c9 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x149>
     6b3:	48 89 45 10          	mov    %rax,0x10(%rbp)
     6b7:	8b 45 04             	mov    0x4(%rbp),%eax
     6ba:	4d 89 e6             	mov    %r12,%r14
     6bd:	4c 89 65 18          	mov    %r12,0x18(%rbp)
     6c1:	49 29 c6             	sub    %rax,%r14
     6c4:	e9 41 ff ff ff       	jmp    60a <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x8a>
     6c9:	8b 45 04             	mov    0x4(%rbp),%eax
     6cc:	e9 39 ff ff ff       	jmp    60a <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x8a>
