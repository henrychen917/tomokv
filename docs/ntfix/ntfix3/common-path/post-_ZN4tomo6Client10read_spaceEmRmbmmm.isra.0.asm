0000000000003aa0 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]>:
    3aa0:	41 57                	push   %r15
    3aa2:	41 56                	push   %r14
    3aa4:	41 55                	push   %r13
    3aa6:	49 89 d7             	mov    %rdx,%r15
    3aa9:	41 54                	push   %r12
    3aab:	55                   	push   %rbp
    3aac:	53                   	push   %rbx
    3aad:	89 ca                	mov    %ecx,%edx
    3aaf:	48 83 ec 28          	sub    $0x28,%rsp
    3ab3:	48 8b 5f 18          	mov    0x18(%rdi),%rbx
    3ab7:	8b 4f 04             	mov    0x4(%rdi),%ecx
    3aba:	49 89 fc             	mov    %rdi,%r12
    3abd:	8b 7f 08             	mov    0x8(%rdi),%edi
    3ac0:	4c 89 c0             	mov    %r8,%rax
    3ac3:	49 89 f6             	mov    %rsi,%r14
    3ac6:	4c 29 c8             	sub    %r9,%rax
    3ac9:	31 f6                	xor    %esi,%esi
    3acb:	49 89 dd             	mov    %rbx,%r13
    3ace:	49 29 cd             	sub    %rcx,%r13
    3ad1:	4d 39 c1             	cmp    %r8,%r9
    3ad4:	48 0f 43 c6          	cmovae %rsi,%rax
    3ad8:	48 89 fe             	mov    %rdi,%rsi
    3adb:	48 8d 6c 38 01       	lea    0x1(%rax,%rdi,1),%rbp
    3ae0:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
    3ae5:	48 39 c5             	cmp    %rax,%rbp
    3ae8:	48 0f 47 e8          	cmova  %rax,%rbp
    3aec:	39 cf                	cmp    %ecx,%edi
    3aee:	73 19                	jae    3b09 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x69>
    3af0:	49 8b 44 24 10       	mov    0x10(%r12),%rax
    3af5:	80 3c 38 2a          	cmpb   $0x2a,(%rax,%rdi,1)
    3af9:	74 0e                	je     3b09 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x69>
    3afb:	48 81 c7 01 00 01 00 	add    $0x10001,%rdi
    3b02:	48 39 fd             	cmp    %rdi,%rbp
    3b05:	48 0f 47 ef          	cmova  %rdi,%rbp
    3b09:	b8 00 00 10 00       	mov    $0x100000,%eax
    3b0e:	48 39 c5             	cmp    %rax,%rbp
    3b11:	48 0f 46 c5          	cmovbe %rbp,%rax
    3b15:	85 f6                	test   %esi,%esi
    3b17:	48 0f 44 c5          	cmove  %rbp,%rax
    3b1b:	4d 39 f5             	cmp    %r14,%r13
    3b1e:	40 0f 92 c6          	setb   %sil
    3b22:	40 84 d6             	test   %dl,%sil
    3b25:	74 05                	je     3b2c <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x8c>
    3b27:	48 39 c3             	cmp    %rax,%rbx
    3b2a:	72 64                	jb     3b90 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0xf0>
    3b2c:	48 39 eb             	cmp    %rbp,%rbx
    3b2f:	0f 83 00 00 00 00    	jae    3b35 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x95>	3b31: R_X86_64_PC32	.text.unlikely+0x258
    3b35:	4d 85 ed             	test   %r13,%r13
    3b38:	74 2f                	je     3b69 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0xc9>
    3b3a:	41 8b 44 24 04       	mov    0x4(%r12),%eax
    3b3f:	49 81 fd ff 07 00 00 	cmp    $0x7ff,%r13
    3b46:	76 18                	jbe    3b60 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0xc0>
    3b48:	4d 89 2f             	mov    %r13,(%r15)
    3b4b:	49 03 44 24 10       	add    0x10(%r12),%rax
    3b50:	48 83 c4 28          	add    $0x28,%rsp
    3b54:	5b                   	pop    %rbx
    3b55:	5d                   	pop    %rbp
    3b56:	41 5c                	pop    %r12
    3b58:	41 5d                	pop    %r13
    3b5a:	41 5e                	pop    %r14
    3b5c:	41 5f                	pop    %r15
    3b5e:	c3                   	ret
    3b5f:	90                   	nop
    3b60:	4a 8d 14 28          	lea    (%rax,%r13,1),%rdx
    3b64:	48 39 d5             	cmp    %rdx,%rbp
    3b67:	74 df                	je     3b48 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0xa8>
    3b69:	49 c7 07 00 00 00 00 	movq   $0x0,(%r15)
    3b70:	48 83 c4 28          	add    $0x28,%rsp
    3b74:	31 c0                	xor    %eax,%eax
    3b76:	5b                   	pop    %rbx
    3b77:	5d                   	pop    %rbp
    3b78:	41 5c                	pop    %r12
    3b7a:	41 5d                	pop    %r13
    3b7c:	41 5e                	pop    %r14
    3b7e:	41 5f                	pop    %r15
    3b80:	c3                   	ret
    3b81:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    3b8c:	0f 1f 40 00          	nopl   0x0(%rax)
    3b90:	4c 01 f1             	add    %r14,%rcx
    3b93:	48 01 db             	add    %rbx,%rbx
    3b96:	48 39 c1             	cmp    %rax,%rcx
    3b99:	48 0f 47 c8          	cmova  %rax,%rcx
    3b9d:	48 39 cb             	cmp    %rcx,%rbx
    3ba0:	73 16                	jae    3bb8 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x118>
    3ba2:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    3bad:	0f 1f 00             	nopl   (%rax)
    3bb0:	48 01 db             	add    %rbx,%rbx
    3bb3:	48 39 cb             	cmp    %rcx,%rbx
    3bb6:	72 f8                	jb     3bb0 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x110>
    3bb8:	48 39 c3             	cmp    %rax,%rbx
    3bbb:	0f 83 00 00 00 00    	jae    3bc1 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x121>	3bbd: R_X86_64_PC32	.text.unlikely+0x277
    3bc1:	49 8b 7c 24 10       	mov    0x10(%r12),%rdi
    3bc6:	48 89 de             	mov    %rbx,%rsi
    3bc9:	4c 89 4c 24 18       	mov    %r9,0x18(%rsp)
    3bce:	4c 89 44 24 10       	mov    %r8,0x10(%rsp)
    3bd3:	89 54 24 0c          	mov    %edx,0xc(%rsp)
    3bd7:	e8 00 00 00 00       	call   3bdc <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x13c>	3bd8: R_X86_64_PLT32	realloc-0x4
    3bdc:	8b 54 24 0c          	mov    0xc(%rsp),%edx
    3be0:	4c 8b 44 24 10       	mov    0x10(%rsp),%r8
    3be5:	4c 8b 4c 24 18       	mov    0x18(%rsp),%r9
    3bea:	48 85 c0             	test   %rax,%rax
    3bed:	74 1a                	je     3c09 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x169>
    3bef:	49 89 44 24 10       	mov    %rax,0x10(%r12)
    3bf4:	41 8b 44 24 04       	mov    0x4(%r12),%eax
    3bf9:	49 89 dd             	mov    %rbx,%r13
    3bfc:	49 89 5c 24 18       	mov    %rbx,0x18(%r12)
    3c01:	49 29 c5             	sub    %rax,%r13
    3c04:	e9 23 ff ff ff       	jmp    3b2c <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x8c>
    3c09:	49 8b 5c 24 18       	mov    0x18(%r12),%rbx
    3c0e:	e9 19 ff ff ff       	jmp    3b2c <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0]+0x8c>
