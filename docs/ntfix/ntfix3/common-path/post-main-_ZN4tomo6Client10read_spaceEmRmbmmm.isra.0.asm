0000000000003770 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]>:
    3770:	41 57                	push   %r15
    3772:	41 56                	push   %r14
    3774:	41 55                	push   %r13
    3776:	49 89 d7             	mov    %rdx,%r15
    3779:	41 54                	push   %r12
    377b:	55                   	push   %rbp
    377c:	53                   	push   %rbx
    377d:	89 ca                	mov    %ecx,%edx
    377f:	48 83 ec 28          	sub    $0x28,%rsp
    3783:	48 8b 5f 18          	mov    0x18(%rdi),%rbx
    3787:	8b 4f 04             	mov    0x4(%rdi),%ecx
    378a:	49 89 fc             	mov    %rdi,%r12
    378d:	8b 7f 08             	mov    0x8(%rdi),%edi
    3790:	4c 89 c0             	mov    %r8,%rax
    3793:	49 89 f6             	mov    %rsi,%r14
    3796:	4c 29 c8             	sub    %r9,%rax
    3799:	31 f6                	xor    %esi,%esi
    379b:	49 89 dd             	mov    %rbx,%r13
    379e:	49 29 cd             	sub    %rcx,%r13
    37a1:	4d 39 c1             	cmp    %r8,%r9
    37a4:	48 0f 43 c6          	cmovae %rsi,%rax
    37a8:	48 89 fe             	mov    %rdi,%rsi
    37ab:	48 8d 6c 38 01       	lea    0x1(%rax,%rdi,1),%rbp
    37b0:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
    37b5:	48 39 c5             	cmp    %rax,%rbp
    37b8:	48 0f 47 e8          	cmova  %rax,%rbp
    37bc:	39 cf                	cmp    %ecx,%edi
    37be:	73 19                	jae    37d9 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x69>
    37c0:	49 8b 44 24 10       	mov    0x10(%r12),%rax
    37c5:	80 3c 38 2a          	cmpb   $0x2a,(%rax,%rdi,1)
    37c9:	74 0e                	je     37d9 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x69>
    37cb:	48 81 c7 01 00 01 00 	add    $0x10001,%rdi
    37d2:	48 39 fd             	cmp    %rdi,%rbp
    37d5:	48 0f 47 ef          	cmova  %rdi,%rbp
    37d9:	b8 00 00 10 00       	mov    $0x100000,%eax
    37de:	48 39 c5             	cmp    %rax,%rbp
    37e1:	48 0f 46 c5          	cmovbe %rbp,%rax
    37e5:	85 f6                	test   %esi,%esi
    37e7:	48 0f 44 c5          	cmove  %rbp,%rax
    37eb:	4d 39 f5             	cmp    %r14,%r13
    37ee:	40 0f 92 c6          	setb   %sil
    37f2:	40 84 d6             	test   %dl,%sil
    37f5:	74 05                	je     37fc <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x8c>
    37f7:	48 39 c3             	cmp    %rax,%rbx
    37fa:	72 64                	jb     3860 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0xf0>
    37fc:	48 39 eb             	cmp    %rbp,%rbx
    37ff:	0f 83 00 00 00 00    	jae    3805 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x95>	3801: R_X86_64_PC32	.text.unlikely+0x19a
    3805:	4d 85 ed             	test   %r13,%r13
    3808:	74 2f                	je     3839 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0xc9>
    380a:	41 8b 44 24 04       	mov    0x4(%r12),%eax
    380f:	49 81 fd ff 07 00 00 	cmp    $0x7ff,%r13
    3816:	76 18                	jbe    3830 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0xc0>
    3818:	4d 89 2f             	mov    %r13,(%r15)
    381b:	49 03 44 24 10       	add    0x10(%r12),%rax
    3820:	48 83 c4 28          	add    $0x28,%rsp
    3824:	5b                   	pop    %rbx
    3825:	5d                   	pop    %rbp
    3826:	41 5c                	pop    %r12
    3828:	41 5d                	pop    %r13
    382a:	41 5e                	pop    %r14
    382c:	41 5f                	pop    %r15
    382e:	c3                   	ret
    382f:	90                   	nop
    3830:	4a 8d 14 28          	lea    (%rax,%r13,1),%rdx
    3834:	48 39 d5             	cmp    %rdx,%rbp
    3837:	74 df                	je     3818 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0xa8>
    3839:	49 c7 07 00 00 00 00 	movq   $0x0,(%r15)
    3840:	48 83 c4 28          	add    $0x28,%rsp
    3844:	31 c0                	xor    %eax,%eax
    3846:	5b                   	pop    %rbx
    3847:	5d                   	pop    %rbp
    3848:	41 5c                	pop    %r12
    384a:	41 5d                	pop    %r13
    384c:	41 5e                	pop    %r14
    384e:	41 5f                	pop    %r15
    3850:	c3                   	ret
    3851:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    385c:	0f 1f 40 00          	nopl   0x0(%rax)
    3860:	4c 01 f1             	add    %r14,%rcx
    3863:	48 01 db             	add    %rbx,%rbx
    3866:	48 39 c1             	cmp    %rax,%rcx
    3869:	48 0f 47 c8          	cmova  %rax,%rcx
    386d:	48 39 cb             	cmp    %rcx,%rbx
    3870:	73 16                	jae    3888 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x118>
    3872:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    387d:	0f 1f 00             	nopl   (%rax)
    3880:	48 01 db             	add    %rbx,%rbx
    3883:	48 39 cb             	cmp    %rcx,%rbx
    3886:	72 f8                	jb     3880 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x110>
    3888:	48 39 c3             	cmp    %rax,%rbx
    388b:	0f 83 00 00 00 00    	jae    3891 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x121>	388d: R_X86_64_PC32	.text.unlikely+0x1b9
    3891:	49 8b 7c 24 10       	mov    0x10(%r12),%rdi
    3896:	48 89 de             	mov    %rbx,%rsi
    3899:	4c 89 4c 24 18       	mov    %r9,0x18(%rsp)
    389e:	4c 89 44 24 10       	mov    %r8,0x10(%rsp)
    38a3:	89 54 24 0c          	mov    %edx,0xc(%rsp)
    38a7:	e8 00 00 00 00       	call   38ac <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x13c>	38a8: R_X86_64_PLT32	realloc-0x4
    38ac:	8b 54 24 0c          	mov    0xc(%rsp),%edx
    38b0:	4c 8b 44 24 10       	mov    0x10(%rsp),%r8
    38b5:	4c 8b 4c 24 18       	mov    0x18(%rsp),%r9
    38ba:	48 85 c0             	test   %rax,%rax
    38bd:	74 1a                	je     38d9 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x169>
    38bf:	49 89 44 24 10       	mov    %rax,0x10(%r12)
    38c4:	41 8b 44 24 04       	mov    0x4(%r12),%eax
    38c9:	49 89 dd             	mov    %rbx,%r13
    38cc:	49 89 5c 24 18       	mov    %rbx,0x18(%r12)
    38d1:	49 29 c5             	sub    %rax,%r13
    38d4:	e9 23 ff ff ff       	jmp    37fc <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x8c>
    38d9:	49 8b 5c 24 18       	mov    0x18(%r12),%rbx
    38de:	e9 19 ff ff ff       	jmp    37fc <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x8c>
