0000000000000000 <tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)>:
   0:	f3 0f 1e fa          	endbr64
   4:	41 56                	push   %r14
   6:	41 55                	push   %r13
   8:	41 54                	push   %r12
   a:	49 89 d5             	mov    %rdx,%r13
   d:	55                   	push   %rbp
   e:	53                   	push   %rbx
   f:	48 89 fb             	mov    %rdi,%rbx
  12:	45 31 db             	xor    %r11d,%r11d
  15:	48 8b 53 18          	mov    0x18(%rbx),%rdx
  19:	44 8b 53 04          	mov    0x4(%rbx),%r10d
  1d:	89 cf                	mov    %ecx,%edi
  1f:	49 89 d6             	mov    %rdx,%r14
  22:	4c 89 d0             	mov    %r10,%rax
  25:	4d 29 d6             	sub    %r10,%r14
  28:	4d 39 c1             	cmp    %r8,%r9
  2b:	73 06                	jae    33 <tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)+0x33>
  2d:	4d 89 c3             	mov    %r8,%r11
  30:	4d 29 cb             	sub    %r9,%r11
  33:	45 31 c0             	xor    %r8d,%r8d
  36:	83 7b 4c 00          	cmpl   $0x0,0x4c(%rbx)
  3a:	8b 4b 08             	mov    0x8(%rbx),%ecx
  3d:	79 04                	jns    43 <tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)+0x43>
  3f:	44 8b 43 74          	mov    0x74(%rbx),%r8d
  43:	41 01 c8             	add    %ecx,%r8d
  46:	45 89 c0             	mov    %r8d,%r8d
  49:	4f 8d 64 03 01       	lea    0x1(%r11,%r8,1),%r12
  4e:	41 b8 ff ff ff ff    	mov    $0xffffffff,%r8d
  54:	4d 39 c4             	cmp    %r8,%r12
  57:	4d 0f 47 e0          	cmova  %r8,%r12
  5b:	39 c1                	cmp    %eax,%ecx
  5d:	73 1a                	jae    79 <tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)+0x79>
  5f:	4c 8b 43 10          	mov    0x10(%rbx),%r8
  63:	89 c8                	mov    %ecx,%eax
  65:	41 80 3c 00 2a       	cmpb   $0x2a,(%r8,%rax,1)
  6a:	74 0d                	je     79 <tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)+0x79>
  6c:	48 05 01 00 01 00    	add    $0x10001,%rax
  72:	49 39 c4             	cmp    %rax,%r12
  75:	4c 0f 47 e0          	cmova  %rax,%r12
  79:	4c 89 e0             	mov    %r12,%rax
  7c:	85 c9                	test   %ecx,%ecx
  7e:	74 0c                	je     8c <tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)+0x8c>
  80:	b8 00 00 10 00       	mov    $0x100000,%eax
  85:	49 39 c4             	cmp    %rax,%r12
  88:	49 0f 46 c4          	cmovbe %r12,%rax
  8c:	49 39 f6             	cmp    %rsi,%r14
  8f:	0f 92 c1             	setb   %cl
  92:	40 84 f9             	test   %dil,%cl
  95:	74 48                	je     df <tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)+0xdf>
  97:	48 39 c2             	cmp    %rax,%rdx
  9a:	73 43                	jae    df <tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)+0xdf>
  9c:	4c 01 d6             	add    %r10,%rsi
  9f:	48 01 d2             	add    %rdx,%rdx
  a2:	48 39 c6             	cmp    %rax,%rsi
  a5:	48 0f 47 f0          	cmova  %rax,%rsi
  a9:	48 39 f2             	cmp    %rsi,%rdx
  ac:	73 05                	jae    b3 <tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)+0xb3>
  ae:	48 01 d2             	add    %rdx,%rdx
  b1:	eb f6                	jmp    a9 <tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)+0xa9>
  b3:	48 8b 7b 10          	mov    0x10(%rbx),%rdi
  b7:	48 39 d0             	cmp    %rdx,%rax
  ba:	48 0f 46 d0          	cmovbe %rax,%rdx
  be:	48 89 d6             	mov    %rdx,%rsi
  c1:	48 89 d5             	mov    %rdx,%rbp
  c4:	e8 00 00 00 00       	call   c9 <tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)+0xc9>	c5: R_X86_64_PLT32	realloc-0x4
  c9:	48 85 c0             	test   %rax,%rax
  cc:	74 11                	je     df <tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)+0xdf>
  ce:	48 89 43 10          	mov    %rax,0x10(%rbx)
  d2:	8b 43 04             	mov    0x4(%rbx),%eax
  d5:	49 89 ee             	mov    %rbp,%r14
  d8:	48 89 6b 18          	mov    %rbp,0x18(%rbx)
  dc:	49 29 c6             	sub    %rax,%r14
  df:	8b 53 04             	mov    0x4(%rbx),%edx
  e2:	31 c0                	xor    %eax,%eax
  e4:	4c 39 e2             	cmp    %r12,%rdx
  e7:	73 06                	jae    ef <tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)+0xef>
  e9:	4c 89 e0             	mov    %r12,%rax
  ec:	48 29 d0             	sub    %rdx,%rax
  ef:	4c 39 f0             	cmp    %r14,%rax
  f2:	49 0f 47 c6          	cmova  %r14,%rax
  f6:	31 c9                	xor    %ecx,%ecx
  f8:	48 85 c0             	test   %rax,%rax
  fb:	74 1e                	je     11b <tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)+0x11b>
  fd:	48 3d ff 07 00 00    	cmp    $0x7ff,%rax
 103:	77 09                	ja     10e <tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)+0x10e>
 105:	48 8d 0c 02          	lea    (%rdx,%rax,1),%rcx
 109:	49 39 cc             	cmp    %rcx,%r12
 10c:	75 09                	jne    117 <tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)+0x117>
 10e:	48 8b 4b 10          	mov    0x10(%rbx),%rcx
 112:	48 01 d1             	add    %rdx,%rcx
 115:	eb 04                	jmp    11b <tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)+0x11b>
 117:	31 c0                	xor    %eax,%eax
 119:	31 c9                	xor    %ecx,%ecx
 11b:	49 89 45 00          	mov    %rax,0x0(%r13)
 11f:	48 89 c8             	mov    %rcx,%rax
 122:	5b                   	pop    %rbx
 123:	5d                   	pop    %rbp
 124:	41 5c                	pop    %r12
 126:	41 5d                	pop    %r13
 128:	41 5e                	pop    %r14
 12a:	c3                   	ret
