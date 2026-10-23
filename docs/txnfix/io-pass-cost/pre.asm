<_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE>:
   0:	endbr64
   4:	push   %rbp
   5:	mov    %rsp,%rbp
   8:	push   %r15
   a:	push   %r14
   c:	push   %r13
   e:	push   %r12
  10:	push   %rbx
  11:	mov    %rdi,%r13
  14:	add    $0x1978,%rdi
  1b:	sub    $0x238,%rsp
  22:	mov    %fs:0x28,%rax
  2b:	mov    %rax,0x228(%rsp)
  33:	xor    %eax,%eax
  35:	call   3a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x3a>
			36: R_X86_64_PLT32	_ZN4tomo19multi_reap_deferredERSt6vectorIPNS_14MultiExecStateESaIS2_EE-0x4
  3a:	mov    %eax,%r8d
  3d:	mov    0x19a0(%r13),%rax
  44:	cmp    0x19c0(%r13),%rax
  4b:	je     4b3 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4b3>
  51:	lea    0x20(%rsp),%r9
  56:	vpxor  %xmm2,%xmm2,%xmm2
  5a:	nopw   0x0(%rax,%rax,1)
  60:	mov    (%rax),%rbx
  63:	vmovdqu8 %zmm2,(%r9)
  69:	vmovdqu8 %zmm2,0x40(%r9)
  70:	vmovdqu8 %zmm2,0x80(%r9)
  77:	vmovdqu8 %zmm2,0xc0(%r9)
  7e:	vmovdqu8 %zmm2,0x100(%r9)
  85:	vmovdqu8 %zmm2,0x140(%r9)
  8c:	vmovdqu8 %zmm2,0x180(%r9)
  93:	vmovdqu8 %zmm2,0x1c0(%r9)
  9a:	test   %rbx,%rbx
  9d:	je     5f0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x5f0>
  a3:	mov    0x228(%rbx),%rax
  aa:	mov    0x220(%rbx),%rdx
  b1:	xor    %ecx,%ecx
  b3:	mov    %rax,%rsi
  b6:	sub    %rdx,%rsi
  b9:	sar    $0x2,%rsi
  bd:	mov    %esi,%r15d
  c0:	mov    %esi,%edi
  c2:	test   %esi,%esi
  c4:	jne    de <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xde>
  c6:	jmp    61c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x61c>
  cb:	nopl   0x0(%rax,%rax,1)
  d0:	mov    0x228(%rbx),%rax
  d7:	mov    0x220(%rbx),%rdx
  de:	sub    %rdx,%rax
  e1:	mov    0x188(%r13),%rsi
  e8:	sar    $0x2,%rax
  ec:	cmp    %rax,%rcx
  ef:	jae    5d0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x5d0>
  f5:	movslq (%rdx,%rcx,4),%rax
  f9:	lea    0x111b8(,%rax,4),%rax
 101:	mov    (%rsi,%rax,1),%eax
 104:	inc    %rcx
 107:	incl   0x20(%rsp,%rax,4)
 10b:	cmp    %rdi,%rcx
 10e:	jne    d0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xd0>
 110:	mov    0x188(%r13),%rdx
 117:	mov    0x103e0(%rdx),%rsi
 11e:	mov    0x103e8(%rdx),%rax
 125:	sub    %rsi,%rax
 128:	sar    $0x3,%rax
 12c:	test   %eax,%eax
 12e:	je     1a0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1a0>
 130:	xor    %ecx,%ecx
 132:	data16 cs nopw 0x0(%rax,%rax,1)
 13d:	nopl   (%rax)
 140:	mov    (%r9,%rcx,4),%edi
 144:	test   %edi,%edi
 146:	je     17b <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x17b>
 148:	mov    (%rsi,%rcx,8),%rdx
 14c:	mov    0x190(%r13),%rax
 153:	mov    0x48(%rdx),%rsi
 157:	mov    (%rax),%edx
 159:	shl    $0x7,%rdx
 15d:	mov    0x40(%rsi,%rdx,1),%r10d
 162:	mov    (%rsi,%rdx,1),%eax
 165:	add    0x54(%rsi,%rdx,1),%eax
 169:	sub    %r10d,%eax
 16c:	cmp    %edi,%eax
 16e:	jb     4b0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4b0>
 174:	mov    0x188(%r13),%rdx
 17b:	mov    0x103e0(%rdx),%rsi
 182:	mov    0x103e8(%rdx),%rax
 189:	inc    %rcx
 18c:	sub    %rsi,%rax
 18f:	sar    $0x3,%rax
 193:	cmp    %eax,%ecx
 195:	jb     140 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x140>
 197:	test   %r15d,%r15d
 19a:	je     469 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x469>
 1a0:	mov    %rbx,%rax
 1a3:	xor    %r14d,%r14d
 1a6:	mov    %r8d,0xc(%rsp)
 1ab:	mov    %r9,(%rsp)
 1af:	or     $0x1,%rax
 1b3:	mov    %rax,0x10(%rsp)
 1b8:	mov    %r15d,%eax
 1bb:	mov    %rax,0x18(%rsp)
 1c0:	jmp    2b8 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b8>
 1c5:	data16 cs nopw 0x0(%rax,%rax,1)
 1d0:	lea    0x40(%rdx,%rax,1),%rcx
 1d5:	lea    (%rdx,%rax,1),%r9
 1d9:	mov    (%rcx),%r15d
 1dc:	vmovq  %r9,%xmm4
 1e1:	lea    0x1(%r15),%esi
 1e5:	mov    %esi,%r9d
 1e8:	sub    0x44(%rdx,%rax,1),%r9d
 1ed:	cmp    %r9d,0x54(%rdx,%rax,1)
 1f2:	jb     3c0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x3c0>
 1f8:	mov    $0x0,%r9d
 1fe:	decl   0x53c(%r12)
 206:	jne    220 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x220>
 208:	mov    0x538(%r12),%eax
 210:	mov    0x530(%r12),%r9d
 218:	mov    %eax,0x53c(%r12)
 220:	shl    $0x7,%rdi
 224:	mov    0x4c(%rdx,%rdi,1),%eax
 228:	and    %r15d,%eax
 22b:	add    0x48(%rdx,%rdi,1),%eax
 22f:	mov    0x10(%rsp),%rdi
 234:	shl    $0x5,%rax
 238:	add    0x4000(%rdx),%rax
 23f:	movq   $0x0,(%rax)
 246:	movq   $0xffffffffffffffff,0x8(%rax)
 24e:	mov    %r10d,0x10(%rax)
 252:	mov    %r9d,0x14(%rax)
 256:	mov    %rdi,0x18(%rax)
 25a:	mov    %esi,(%rcx)
 25c:	mov    %r11d,%eax
 25f:	mov    %r11d,%edx
 262:	shr    $0x6,%eax
 265:	and    $0x1,%eax
 268:	and    $0x3f,%edx
 26b:	lea    0x2b8(%r8,%rax,8),%rax
 273:	mov    (%rax),%rsi
 276:	bt     %r11,%rsi
 27a:	jb     2a0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2a0>
 27c:	lock bts %rdx,(%rax)
 281:	jb     2a0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2a0>
 283:	mov    0x48(%r8),%rax
 287:	mov    0x8(%r8),%rsi
 28b:	test   %rsi,%rsi
 28e:	je     2a0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2a0>
 290:	movzbl 0x4040(%rax),%eax
 297:	test   %al,%al
 299:	jne    520 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x520>
 29f:	nop
 2a0:	mov    0x18(%rsp),%rax
 2a5:	inc    %r14
 2a8:	cmp    %rax,%r14
 2ab:	je     460 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x460>
 2b1:	mov    0x188(%r13),%rdx
 2b8:	test   %rbx,%rbx
 2bb:	je     550 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x550>
 2c1:	mov    0x220(%rbx),%rsi
 2c8:	mov    0x228(%rbx),%rax
 2cf:	sub    %rsi,%rax
 2d2:	sar    $0x2,%rax
 2d6:	cmp    %rax,%r14
 2d9:	jae    550 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x550>
 2df:	movslq (%rsi,%r14,4),%rax
 2e3:	mov    %rax,%r10
 2e6:	lea    0x111b8(,%rax,4),%rax
 2ee:	mov    (%rdx,%rax,1),%eax
 2f1:	mov    0x190(%r13),%r12
 2f8:	mov    0x103e0(%rdx),%rdx
 2ff:	mov    (%r12),%r11d
 303:	mov    (%rdx,%rax,8),%r8
 307:	mov    0x538(%r12),%r9d
 30f:	mov    %r11d,%edi
 312:	mov    0x48(%r8),%rdx
 316:	mov    %rdi,%rax
 319:	shl    $0x7,%rax
 31d:	test   %r9d,%r9d
 320:	jne    1d0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1d0>
 326:	lea    0x40(%rdx,%rax,1),%rsi
 32b:	lea    (%rdx,%rax,1),%rcx
 32f:	mov    (%rsi),%r15d
 332:	vmovq  %rsi,%xmm3
 337:	vmovq  %rcx,%xmm5
 33c:	lea    0x1(%r15),%esi
 340:	mov    %esi,%ecx
 342:	sub    0x44(%rdx,%rax,1),%ecx
 346:	cmp    %ecx,0x54(%rdx,%rax,1)
 34a:	jae    36b <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x36b>
 34c:	mov    (%rdx,%rax,1),%eax
 34f:	vmovq  %xmm5,%rcx
 354:	mov    %eax,0x44(%rcx)
 357:	mov    %esi,%ecx
 359:	sub    %eax,%ecx
 35b:	mov    %ecx,%eax
 35d:	vmovq  %xmm5,%rcx
 362:	cmp    %eax,0x54(%rcx)
 365:	jb     4e0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4e0>
 36b:	shl    $0x7,%rdi
 36f:	mov    0x4c(%rdx,%rdi,1),%eax
 373:	and    %r15d,%eax
 376:	add    0x48(%rdx,%rdi,1),%eax
 37a:	mov    0x10(%rsp),%rdi
 37f:	shl    $0x5,%rax
 383:	add    0x4000(%rdx),%rax
 38a:	movq   $0x0,(%rax)
 391:	movq   $0xffffffffffffffff,0x8(%rax)
 399:	mov    %r10d,0x10(%rax)
 39d:	movl   $0x0,0x14(%rax)
 3a4:	mov    %rdi,0x18(%rax)
 3a8:	vmovq  %xmm3,%rax
 3ad:	mov    %esi,(%rax)
 3af:	jmp    25c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x25c>
 3b4:	data16 cs nopw 0x0(%rax,%rax,1)
 3bf:	nop
 3c0:	mov    (%rdx,%rax,1),%r9d
 3c4:	vmovq  %xmm4,%rax
 3c9:	mov    %r9d,0x44(%rax)
 3cd:	mov    %esi,%eax
 3cf:	sub    %r9d,%eax
 3d2:	vmovq  %xmm4,%r9
 3d7:	cmp    %eax,0x54(%r9)
 3db:	jae    1f8 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1f8>
 3e1:	mov    0x4008(%rdx),%esi
 3e7:	mov    %rdi,%rax
 3ea:	test   %esi,%esi
 3ec:	je     5da <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x5da>
 3f2:	mov    %rdx,%rcx
 3f5:	xor    %r8d,%r8d
 3f8:	xor    %edi,%edi
 3fa:	nopw   0x0(%rax,%rax,1)
 400:	mov    (%rcx),%r9d
 403:	inc    %edi
 405:	sub    $0xffffffffffffff80,%rcx
 409:	mov    -0x40(%rcx),%esi
 40c:	sub    %r9d,%esi
 40f:	add    %rsi,%r8
 412:	cmp    0x4008(%rdx),%edi
 418:	jb     400 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x400>
 41a:	mov    $0x1,%ebx
 41f:	mov    0x400c(%rdx),%ecx
 425:	vmovq  %rbx,%xmm0
 42a:	shl    $0x7,%rax
 42e:	vpinsrq $0x1,%r8,%xmm0,%xmm0
 434:	vpaddq 0x58(%rdx,%rax,1),%xmm0,%xmm0
 43a:	add    %rcx,0x68(%rdx,%rax,1)
 43f:	vmovdqu %xmm0,0x58(%rdx,%rax,1)
 445:	mov    0x3f8(%r12),%rax
 44d:	inc    %rax
 450:	mov    %rax,0x3f8(%r12)
 458:	vzeroupper
 45b:	call   460 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x460>
			45c: R_X86_64_PLT32	abort-0x4
 460:	mov    0xc(%rsp),%r8d
 465:	mov    (%rsp),%r9
 469:	test   %rbx,%rbx
 46c:	je     472 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x472>
 46e:	movb   $0x1,0x42(%rbx)
 472:	mov    0x19b0(%r13),%rbx
 479:	mov    0x19a0(%r13),%rax
 480:	lea    -0x8(%rbx),%rdx
 484:	cmp    %rdx,%rax
 487:	je     560 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x560>
 48d:	add    $0x8,%rax
 491:	inc    %r8d
 494:	mov    %rax,0x19a0(%r13)
 49b:	cmp    %rax,0x19c0(%r13)
 4a2:	jne    60 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x60>
 4a8:	nopl   0x0(%rax,%rax,1)
 4b0:	vzeroupper
 4b3:	mov    0x228(%rsp),%rax
 4bb:	sub    %fs:0x28,%rax
 4c4:	jne    645 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x645>
 4ca:	add    $0x238,%rsp
 4d1:	mov    %r8d,%eax
 4d4:	pop    %rbx
 4d5:	pop    %r12
 4d7:	pop    %r13
 4d9:	pop    %r14
 4db:	pop    %r15
 4dd:	pop    %rbp
 4de:	ret
 4df:	nop
 4e0:	mov    0x4008(%rdx),%ecx
 4e6:	mov    %r9d,%esi
 4e9:	mov    %rdi,%rax
 4ec:	test   %ecx,%ecx
 4ee:	je     5da <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x5da>
 4f4:	mov    %rdx,%rcx
 4f7:	xor    %r8d,%r8d
 4fa:	nopw   0x0(%rax,%rax,1)
 500:	mov    (%rcx),%r9d
 503:	inc    %esi
 505:	sub    $0xffffffffffffff80,%rcx
 509:	mov    -0x40(%rcx),%edi
 50c:	sub    %r9d,%edi
 50f:	add    %rdi,%r8
 512:	cmp    0x4008(%rdx),%esi
 518:	jb     500 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x500>
 51a:	jmp    41a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x41a>
 51f:	nop
 520:	lea    0xac8(%r13),%rdi
 527:	movabs $0x500000000000000,%rdx
 531:	vzeroupper
 534:	call   539 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x539>
			535: R_X86_64_PC32	.text+0x7e6c
 539:	vpxor  %xmm2,%xmm2,%xmm2
 53d:	incq   0x438(%r12)
 545:	jmp    2a0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2a0>
 54a:	nopw   0x0(%rax,%rax,1)
 550:	mov    $0x111b4,%eax
 555:	mov    $0xffffffff,%r10d
 55b:	jmp    2ee <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2ee>
 560:	mov    0x19a8(%r13),%rdi
 567:	mov    $0x200,%esi
 56c:	mov    %r9,0x10(%rsp)
 571:	mov    %r8d,0x18(%rsp)
 576:	vzeroupper
 579:	call   57e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x57e>
			57a: R_X86_64_PLT32	_ZdlPvm-0x4
 57e:	mov    0x19b8(%r13),%rax
 585:	mov    0x10(%rsp),%r9
 58a:	mov    0x18(%rsp),%r8d
 58f:	vpxor  %xmm2,%xmm2,%xmm2
 593:	lea    0x8(%rax),%rdx
 597:	mov    0x8(%rax),%rax
 59b:	mov    %rdx,0x19b8(%r13)
 5a2:	vmovq  %rax,%xmm1
 5a7:	lea    0x200(%rax),%rdx
 5ae:	vpinsrq $0x1,%rdx,%xmm1,%xmm0
 5b4:	vmovdqu %xmm0,0x19a8(%r13)
 5bd:	jmp    491 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x491>
 5c2:	data16 cs nopw 0x0(%rax,%rax,1)
 5cd:	nopl   (%rax)
 5d0:	mov    $0x111b4,%eax
 5d5:	jmp    101 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x101>
 5da:	xor    %r8d,%r8d
 5dd:	jmp    41a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x41a>
 5e2:	data16 cs nopw 0x0(%rax,%rax,1)
 5ed:	nopl   (%rax)
 5f0:	mov    0x188(%r13),%rdx
 5f7:	xor    %r15d,%r15d
 5fa:	mov    0x103e0(%rdx),%rsi
 601:	mov    0x103e8(%rdx),%rax
 608:	sub    %rsi,%rax
 60b:	sar    $0x3,%rax
 60f:	test   %eax,%eax
 611:	jne    130 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x130>
 617:	jmp    472 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x472>
 61c:	mov    0x188(%r13),%rdx
 623:	mov    0x103e0(%rdx),%rsi
 62a:	mov    0x103e8(%rdx),%rax
 631:	sub    %rsi,%rax
 634:	sar    $0x3,%rax
 638:	test   %eax,%eax
 63a:	jne    130 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x130>
 640:	jmp    46e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x46e>
 645:	call   64a <.LC398+0x2>
			646: R_X86_64_PLT32	__stack_chk_fail-0x4
