
build/ntfix-pre/src/main.o:     file format elf64-x86-64


Disassembly of section .text._ZN4tomo6IoLoop10epoll_recvEPNS_6ClientE:

0000000000000000 <tomo::IoLoop::epoll_recv(tomo::Client*)>:
   0:	f3 0f 1e fa          	endbr64
   4:	41 57                	push   %r15
   6:	41 56                	push   %r14
   8:	41 55                	push   %r13
   a:	49 89 fe             	mov    %rdi,%r14
   d:	41 54                	push   %r12
   f:	55                   	push   %rbp
  10:	53                   	push   %rbx
  11:	45 31 e4             	xor    %r12d,%r12d
  14:	48 83 ec 18          	sub    $0x18,%rsp
  18:	48 89 f3             	mov    %rsi,%rbx
  1b:	31 c9                	xor    %ecx,%ecx
  1d:	48 83 bb 90 07 00 00 00 	cmpq   $0x0,0x790(%rbx)
  25:	0f 85 c5 02 00 00    	jne    2f0 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x2f0>
  2b:	49 8b 86 88 01 00 00 	mov    0x188(%r14),%rax
  32:	0f b6 80 a0 76 01 00 	movzbl 0x176a0(%rax),%eax
  39:	a8 01                	test   $0x1,%al
  3b:	0f 85 7f 02 00 00    	jne    2c0 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x2c0>
  41:	49 8b be e0 1b 00 00 	mov    0x1be0(%r14),%rdi
  48:	4c 8b 83 c0 00 00 00 	mov    0xc0(%rbx),%r8
  4f:	4c 8b 93 00 01 00 00 	mov    0x100(%rbx),%r10
  56:	48 89 f8             	mov    %rdi,%rax
  59:	48 29 c8             	sub    %rcx,%rax
  5c:	48 8b 53 18          	mov    0x18(%rbx),%rdx
  60:	8b 73 04             	mov    0x4(%rbx),%esi
  63:	49 89 d7             	mov    %rdx,%r15
  66:	49 29 f7             	sub    %rsi,%r15
  69:	48 39 f9             	cmp    %rdi,%rcx
  6c:	8b 7b 08             	mov    0x8(%rbx),%edi
  6f:	49 0f 43 c4          	cmovae %r12,%rax
  73:	48 8d 6c 38 01       	lea    0x1(%rax,%rdi,1),%rbp
  78:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
  7d:	48 89 f9             	mov    %rdi,%rcx
  80:	48 39 c5             	cmp    %rax,%rbp
  83:	48 0f 47 e8          	cmova  %rax,%rbp
  87:	39 f7                	cmp    %esi,%edi
  89:	73 18                	jae    a3 <tomo::IoLoop::epoll_recv(tomo::Client*)+0xa3>
  8b:	48 8b 43 10          	mov    0x10(%rbx),%rax
  8f:	80 3c 38 2a          	cmpb   $0x2a,(%rax,%rdi,1)
  93:	74 0e                	je     a3 <tomo::IoLoop::epoll_recv(tomo::Client*)+0xa3>
  95:	48 81 c7 01 00 01 00 	add    $0x10001,%rdi
  9c:	48 39 fd             	cmp    %rdi,%rbp
  9f:	48 0f 47 ef          	cmova  %rdi,%rbp
  a3:	b8 00 00 10 00       	mov    $0x100000,%eax
  a8:	48 39 c5             	cmp    %rax,%rbp
  ab:	48 0f 46 c5          	cmovbe %rbp,%rax
  af:	85 c9                	test   %ecx,%ecx
  b1:	48 0f 44 c5          	cmove  %rbp,%rax
  b5:	4d 39 d0             	cmp    %r10,%r8
  b8:	40 0f 94 c7          	sete   %dil
  bc:	49 81 ff ff 3f 00 00 	cmp    $0x3fff,%r15
  c3:	0f 96 c1             	setbe  %cl
  c6:	40 84 cf             	test   %cl,%dil
  c9:	74 09                	je     d4 <tomo::IoLoop::epoll_recv(tomo::Client*)+0xd4>
  cb:	48 39 c2             	cmp    %rax,%rdx
  ce:	0f 82 8c 01 00 00    	jb     260 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x260>
  d4:	48 39 ee             	cmp    %rbp,%rsi
  d7:	72 17                	jb     f0 <tomo::IoLoop::epoll_recv(tomo::Client*)+0xf0>
  d9:	48 83 c4 18          	add    $0x18,%rsp
  dd:	5b                   	pop    %rbx
  de:	5d                   	pop    %rbp
  df:	41 5c                	pop    %r12
  e1:	41 5d                	pop    %r13
  e3:	41 5e                	pop    %r14
  e5:	41 5f                	pop    %r15
  e7:	c3                   	ret
  e8:	0f 1f 84 00 00 00 00 00 	nopl   0x0(%rax,%rax,1)
  f0:	49 89 ed             	mov    %rbp,%r13
  f3:	49 29 f5             	sub    %rsi,%r13
  f6:	4d 39 fd             	cmp    %r15,%r13
  f9:	4d 0f 47 ef          	cmova  %r15,%r13
  fd:	4d 85 ed             	test   %r13,%r13
 100:	74 d7                	je     d9 <tomo::IoLoop::epoll_recv(tomo::Client*)+0xd9>
 102:	49 81 fd ff 07 00 00 	cmp    $0x7ff,%r13
 109:	77 0a                	ja     115 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x115>
 10b:	49 8d 44 35 00       	lea    0x0(%r13,%rsi,1),%rax
 110:	48 39 c5             	cmp    %rax,%rbp
 113:	75 c4                	jne    d9 <tomo::IoLoop::epoll_recv(tomo::Client*)+0xd9>
 115:	48 03 73 10          	add    0x10(%rbx),%rsi
 119:	74 be                	je     d9 <tomo::IoLoop::epoll_recv(tomo::Client*)+0xd9>
 11b:	8b 3b                	mov    (%rbx),%edi
 11d:	b9 40 00 00 00       	mov    $0x40,%ecx
 122:	4c 89 ea             	mov    %r13,%rdx
 125:	e8 00 00 00 00       	call   12a <tomo::IoLoop::epoll_recv(tomo::Client*)+0x12a>	126: R_X86_64_PLT32	recv-0x4
 12a:	48 89 c5             	mov    %rax,%rbp
 12d:	48 85 c0             	test   %rax,%rax
 130:	0f 8f 8a 00 00 00    	jg     1c0 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x1c0>
 136:	0f 84 04 01 00 00    	je     240 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x240>
 13c:	e8 00 00 00 00       	call   141 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x141>	13d: R_X86_64_PLT32	__errno_location-0x4
 141:	8b 00                	mov    (%rax),%eax
 143:	83 f8 04             	cmp    $0x4,%eax
 146:	0f 84 cf fe ff ff    	je     1b <tomo::IoLoop::epoll_recv(tomo::Client*)+0x1b>
 14c:	83 f8 0b             	cmp    $0xb,%eax
 14f:	0f 84 d0 00 00 00    	je     225 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x225>
 155:	80 7b 33 00          	cmpb   $0x0,0x33(%rbx)
 159:	0f 85 7a ff ff ff    	jne    d9 <tomo::IoLoop::epoll_recv(tomo::Client*)+0xd9>
 15f:	4d 8b a6 20 18 00 00 	mov    0x1820(%r14),%r12
 166:	49 8b 96 28 18 00 00 	mov    0x1828(%r14),%rdx
 16d:	49 39 d4             	cmp    %rdx,%r12
 170:	0f 84 35 02 00 00    	je     3ab <tomo::IoLoop::epoll_recv(tomo::Client*)+0x3ab>
 176:	4c 89 e0             	mov    %r12,%rax
 179:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
 180:	48 3b 18             	cmp    (%rax),%rbx
 183:	0f 84 50 ff ff ff    	je     d9 <tomo::IoLoop::epoll_recv(tomo::Client*)+0xd9>
 189:	48 83 c0 08          	add    $0x8,%rax
 18d:	48 39 c2             	cmp    %rax,%rdx
 190:	75 ee                	jne    180 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x180>
 192:	49 3b 96 30 18 00 00 	cmp    0x1830(%r14),%rdx
 199:	0f 84 9e 01 00 00    	je     33d <tomo::IoLoop::epoll_recv(tomo::Client*)+0x33d>
 19f:	48 89 1a             	mov    %rbx,(%rdx)
 1a2:	48 83 c2 08          	add    $0x8,%rdx
 1a6:	49 89 96 28 18 00 00 	mov    %rdx,0x1828(%r14)
 1ad:	48 83 c4 18          	add    $0x18,%rsp
 1b1:	5b                   	pop    %rbx
 1b2:	5d                   	pop    %rbp
 1b3:	41 5c                	pop    %r12
 1b5:	41 5d                	pop    %r13
 1b7:	41 5e                	pop    %r14
 1b9:	41 5f                	pop    %r15
 1bb:	c3                   	ret
 1bc:	0f 1f 40 00          	nopl   0x0(%rax)
 1c0:	49 8b 86 90 01 00 00 	mov    0x190(%r14),%rax
 1c7:	48 ff 80 28 05 00 00 	incq   0x528(%rax)
 1ce:	31 c0                	xor    %eax,%eax
 1d0:	01 6b 04             	add    %ebp,0x4(%rbx)
 1d3:	48 83 bb 90 07 00 00 00 	cmpq   $0x0,0x790(%rbx)
 1db:	0f 85 4f 01 00 00    	jne    330 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x330>
 1e1:	49 8b 96 88 01 00 00 	mov    0x188(%r14),%rdx
 1e8:	0f b6 92 a0 76 01 00 	movzbl 0x176a0(%rdx),%edx
 1ef:	83 e2 01             	and    $0x1,%edx
 1f2:	0f 85 08 01 00 00    	jne    300 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x300>
 1f8:	49 8b 96 e0 1b 00 00 	mov    0x1be0(%r14),%rdx
 1ff:	48 39 c2             	cmp    %rax,%rdx
 202:	72 3c                	jb     240 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x240>
 204:	8b 4b 04             	mov    0x4(%rbx),%ecx
 207:	48 29 c2             	sub    %rax,%rdx
 20a:	2b 4b 08             	sub    0x8(%rbx),%ecx
 20d:	48 39 ca             	cmp    %rcx,%rdx
 210:	72 2e                	jb     240 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x240>
 212:	41 8b 86 78 05 00 00 	mov    0x578(%r14),%eax
 219:	89 43 0c             	mov    %eax,0xc(%rbx)
 21c:	4c 39 ed             	cmp    %r13,%rbp
 21f:	0f 83 f6 fd ff ff    	jae    1b <tomo::IoLoop::epoll_recv(tomo::Client*)+0x1b>
 225:	c6 43 29 01          	movb   $0x1,0x29(%rbx)
 229:	48 83 c4 18          	add    $0x18,%rsp
 22d:	5b                   	pop    %rbx
 22e:	5d                   	pop    %rbp
 22f:	41 5c                	pop    %r12
 231:	41 5d                	pop    %r13
 233:	41 5e                	pop    %r14
 235:	41 5f                	pop    %r15
 237:	c3                   	ret
 238:	0f 1f 84 00 00 00 00 00 	nopl   0x0(%rax,%rax,1)
 240:	48 83 c4 18          	add    $0x18,%rsp
 244:	48 89 de             	mov    %rbx,%rsi
 247:	4c 89 f7             	mov    %r14,%rdi
 24a:	5b                   	pop    %rbx
 24b:	5d                   	pop    %rbp
 24c:	41 5c                	pop    %r12
 24e:	41 5d                	pop    %r13
 250:	41 5e                	pop    %r14
 252:	41 5f                	pop    %r15
 254:	e9 00 00 00 00       	jmp    259 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x259>	255: R_X86_64_PLT32	tomo::IoLoop::epoll_request_close(tomo::Client*)-0x4
 259:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
 260:	48 81 c6 00 40 00 00 	add    $0x4000,%rsi
 267:	48 01 d2             	add    %rdx,%rdx
 26a:	48 39 c6             	cmp    %rax,%rsi
 26d:	48 0f 47 f0          	cmova  %rax,%rsi
 271:	48 39 f2             	cmp    %rsi,%rdx
 274:	73 12                	jae    288 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x288>
 276:	66 2e 0f 1f 84 00 00 00 00 00 	cs nopw 0x0(%rax,%rax,1)
 280:	48 01 d2             	add    %rdx,%rdx
 283:	48 39 f2             	cmp    %rsi,%rdx
 286:	72 f8                	jb     280 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x280>
 288:	48 8b 7b 10          	mov    0x10(%rbx),%rdi
 28c:	48 39 d0             	cmp    %rdx,%rax
 28f:	48 0f 46 d0          	cmovbe %rax,%rdx
 293:	48 89 d6             	mov    %rdx,%rsi
 296:	49 89 d5             	mov    %rdx,%r13
 299:	e8 00 00 00 00       	call   29e <tomo::IoLoop::epoll_recv(tomo::Client*)+0x29e>	29a: R_X86_64_PLT32	realloc-0x4
 29e:	48 85 c0             	test   %rax,%rax
 2a1:	0f 84 8f 01 00 00    	je     436 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x436>
 2a7:	8b 73 04             	mov    0x4(%rbx),%esi
 2aa:	4d 89 ef             	mov    %r13,%r15
 2ad:	48 89 43 10          	mov    %rax,0x10(%rbx)
 2b1:	4c 89 6b 18          	mov    %r13,0x18(%rbx)
 2b5:	49 29 f7             	sub    %rsi,%r15
 2b8:	e9 17 fe ff ff       	jmp    d4 <tomo::IoLoop::epoll_recv(tomo::Client*)+0xd4>
 2bd:	0f 1f 00             	nopl   (%rax)
 2c0:	80 bb b5 07 00 00 00 	cmpb   $0x0,0x7b5(%rbx)
 2c7:	0f 85 74 fd ff ff    	jne    41 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x41>
 2cd:	49 8b be e0 1b 00 00 	mov    0x1be0(%r14),%rdi
 2d4:	b8 00 00 10 00       	mov    $0x100000,%eax
 2d9:	48 39 c7             	cmp    %rax,%rdi
 2dc:	48 0f 47 f8          	cmova  %rax,%rdi
 2e0:	e9 63 fd ff ff       	jmp    48 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x48>
 2e5:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
 2f0:	48 89 df             	mov    %rbx,%rdi
 2f3:	e8 00 00 00 00       	call   2f8 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x2f8>	2f4: R_X86_64_PLT32	tomo::multi_session_query_bytes(tomo::Client const&)-0x4
 2f8:	48 89 c1             	mov    %rax,%rcx
 2fb:	e9 2b fd ff ff       	jmp    2b <tomo::IoLoop::epoll_recv(tomo::Client*)+0x2b>
 300:	80 bb b5 07 00 00 00 	cmpb   $0x0,0x7b5(%rbx)
 307:	0f 85 eb fe ff ff    	jne    1f8 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x1f8>
 30d:	49 8b 96 e0 1b 00 00 	mov    0x1be0(%r14),%rdx
 314:	b9 00 00 10 00       	mov    $0x100000,%ecx
 319:	48 39 ca             	cmp    %rcx,%rdx
 31c:	48 0f 47 d1          	cmova  %rcx,%rdx
 320:	e9 da fe ff ff       	jmp    1ff <tomo::IoLoop::epoll_recv(tomo::Client*)+0x1ff>
 325:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
 330:	48 89 df             	mov    %rbx,%rdi
 333:	e8 00 00 00 00       	call   338 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x338>	334: R_X86_64_PLT32	tomo::multi_session_query_bytes(tomo::Client const&)-0x4
 338:	e9 a4 fe ff ff       	jmp    1e1 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x1e1>
 33d:	4c 29 e2             	sub    %r12,%rdx
 340:	48 89 d0             	mov    %rdx,%rax
 343:	48 89 d5             	mov    %rdx,%rbp
 346:	48 ba ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rdx
 350:	48 c1 f8 03          	sar    $0x3,%rax
 354:	48 39 d0             	cmp    %rdx,%rax
 357:	0f 84 e1 00 00 00    	je     43e <tomo::IoLoop::epoll_recv(tomo::Client*)+0x43e>
 35d:	48 8d 14 00          	lea    (%rax,%rax,1),%rdx
 361:	48 39 c2             	cmp    %rax,%rdx
 364:	0f 82 99 00 00 00    	jb     403 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x403>
 36a:	45 31 ed             	xor    %r13d,%r13d
 36d:	31 ff                	xor    %edi,%edi
 36f:	48 85 d2             	test   %rdx,%rdx
 372:	0f 85 a3 00 00 00    	jne    41b <tomo::IoLoop::epoll_recv(tomo::Client*)+0x41b>
 378:	48 8d 54 2f 08       	lea    0x8(%rdi,%rbp,1),%rdx
 37d:	c4 e1 f9 6e cf       	vmovq  %rdi,%xmm1
 382:	48 89 1c 2f          	mov    %rbx,(%rdi,%rbp,1)
 386:	c4 e3 f1 22 c2 01    	vpinsrq $0x1,%rdx,%xmm1,%xmm0
 38c:	48 85 ed             	test   %rbp,%rbp
 38f:	7f 3f                	jg     3d0 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x3d0>
 391:	4d 85 e4             	test   %r12,%r12
 394:	75 79                	jne    40f <tomo::IoLoop::epoll_recv(tomo::Client*)+0x40f>
 396:	c4 c1 7a 7f 86 20 18 00 00 	vmovdqu %xmm0,0x1820(%r14)
 39f:	4d 89 ae 30 18 00 00 	mov    %r13,0x1830(%r14)
 3a6:	e9 2e fd ff ff       	jmp    d9 <tomo::IoLoop::epoll_recv(tomo::Client*)+0xd9>
 3ab:	41 bd 08 00 00 00    	mov    $0x8,%r13d
 3b1:	31 ed                	xor    %ebp,%ebp
 3b3:	4d 39 a6 30 18 00 00 	cmp    %r12,0x1830(%r14)
 3ba:	0f 85 df fd ff ff    	jne    19f <tomo::IoLoop::epoll_recv(tomo::Client*)+0x19f>
 3c0:	4c 89 ef             	mov    %r13,%rdi
 3c3:	e8 00 00 00 00       	call   3c8 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x3c8>	3c4: R_X86_64_PLT32	operator new(unsigned long)-0x4
 3c8:	48 89 c7             	mov    %rax,%rdi
 3cb:	49 01 c5             	add    %rax,%r13
 3ce:	eb a8                	jmp    378 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x378>
 3d0:	4c 89 e6             	mov    %r12,%rsi
 3d3:	48 89 ea             	mov    %rbp,%rdx
 3d6:	c5 f9 7f 04 24       	vmovdqa %xmm0,(%rsp)
 3db:	e8 00 00 00 00       	call   3e0 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x3e0>	3dc: R_X86_64_PLT32	memmove-0x4
 3e0:	49 8b b6 30 18 00 00 	mov    0x1830(%r14),%rsi
 3e7:	c5 f9 6f 04 24       	vmovdqa (%rsp),%xmm0
 3ec:	4c 29 e6             	sub    %r12,%rsi
 3ef:	4c 89 e7             	mov    %r12,%rdi
 3f2:	c5 f9 7f 04 24       	vmovdqa %xmm0,(%rsp)
 3f7:	e8 00 00 00 00       	call   3fc <tomo::IoLoop::epoll_recv(tomo::Client*)+0x3fc>	3f8: R_X86_64_PLT32	operator delete(void*, unsigned long)-0x4
 3fc:	c5 f9 6f 04 24       	vmovdqa (%rsp),%xmm0
 401:	eb 93                	jmp    396 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x396>
 403:	49 bd f8 ff ff ff ff ff ff 7f 	movabs $0x7ffffffffffffff8,%r13
 40d:	eb b1                	jmp    3c0 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x3c0>
 40f:	49 8b b6 30 18 00 00 	mov    0x1830(%r14),%rsi
 416:	4c 29 e6             	sub    %r12,%rsi
 419:	eb d4                	jmp    3ef <tomo::IoLoop::epoll_recv(tomo::Client*)+0x3ef>
 41b:	48 b8 ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rax
 425:	48 39 c2             	cmp    %rax,%rdx
 428:	48 0f 47 d0          	cmova  %rax,%rdx
 42c:	4c 8d 2c d5 00 00 00 00 	lea    0x0(,%rdx,8),%r13
 434:	eb 8a                	jmp    3c0 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x3c0>
 436:	8b 73 04             	mov    0x4(%rbx),%esi
 439:	e9 96 fc ff ff       	jmp    d4 <tomo::IoLoop::epoll_recv(tomo::Client*)+0xd4>
 43e:	48 8d 3d 00 00 00 00 	lea    0x0(%rip),%rdi        # 445 <tomo::IoLoop::epoll_recv(tomo::Client*)+0x445>	441: R_X86_64_PC32	.LC3-0x4
 445:	e8 00 00 00 00       	call   44a <.LC362>	446: R_X86_64_PLT32	std::__throw_length_error(char const*)-0x4
