<_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE>:
       0:	endbr64
       4:	push   %rbp
       5:	mov    %rsp,%rbp
       8:	push   %r15
       a:	push   %r14
       c:	push   %r13
       e:	push   %r12
      10:	push   %r10
      12:	push   %rbx
      13:	mov    %rdi,%r13
      16:	sub    $0x4f0,%rsp
      1d:	mov    %fs:0x28,%rax
      26:	mov    %rax,-0x38(%rbp)
      2a:	xor    %eax,%eax
      2c:	lea    0x1978(%rdi),%rax
      33:	mov    %rax,%rdi
      36:	mov    %rax,-0x4d0(%rbp)
      3d:	call   42 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x42>
			3e: R_X86_64_PLT32	_ZN4tomo19multi_reap_deferredERSt6vectorIPNS_14MultiExecStateESaIS2_EE-0x4
      42:	mov    %eax,-0x4a8(%rbp)
      48:	mov    0x190(%r13),%rax
      4f:	mov    (%rax),%eax
      51:	add    $0x7a3,%rax
      57:	shl    $0x6,%rax
      5b:	add    0x188(%r13),%rax
      62:	mov    (%rax),%rdx
      65:	test   %rdx,%rdx
      68:	jne    6c0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x6c0>
      6e:	mov    0x19a0(%r13),%rax
      75:	cmp    0x19c0(%r13),%rax
      7c:	je     507 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x507>
      82:	mov    -0x4a8(%rbp),%r8d
      89:	lea    -0x440(%rbp),%r9
      90:	vpxor  %xmm2,%xmm2,%xmm2
      94:	data16 cs nopw 0x0(%rax,%rax,1)
      9f:	nop
      a0:	mov    (%rax),%rbx
      a3:	vmovdqu8 %zmm2,(%r9)
      a9:	vmovdqu8 %zmm2,0x40(%r9)
      b0:	vmovdqu8 %zmm2,0x80(%r9)
      b7:	vmovdqu8 %zmm2,0xc0(%r9)
      be:	vmovdqu8 %zmm2,0x100(%r9)
      c5:	vmovdqu8 %zmm2,0x140(%r9)
      cc:	vmovdqu8 %zmm2,0x180(%r9)
      d3:	vmovdqu8 %zmm2,0x1c0(%r9)
      da:	test   %rbx,%rbx
      dd:	je     690 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x690>
      e3:	mov    0x228(%rbx),%rax
      ea:	mov    0x220(%rbx),%rdx
      f1:	xor    %ecx,%ecx
      f3:	mov    %rax,%rsi
      f6:	sub    %rdx,%rsi
      f9:	sar    $0x2,%rsi
      fd:	mov    %esi,%r15d
     100:	mov    %esi,%edi
     102:	test   %esi,%esi
     104:	jne    11e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x11e>
     106:	jmp    1b84 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1b84>
     10b:	nopl   0x0(%rax,%rax,1)
     110:	mov    0x228(%rbx),%rax
     117:	mov    0x220(%rbx),%rdx
     11e:	sub    %rdx,%rax
     121:	mov    0x188(%r13),%rsi
     128:	sar    $0x2,%rax
     12c:	cmp    %rax,%rcx
     12f:	jae    670 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x670>
     135:	movslq (%rdx,%rcx,4),%rax
     139:	lea    0x111b8(,%rax,4),%rax
     141:	mov    (%rsi,%rax,1),%eax
     144:	inc    %rcx
     147:	incl   -0x440(%rbp,%rax,4)
     14e:	cmp    %rcx,%rdi
     151:	jne    110 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x110>
     153:	mov    0x188(%r13),%rdx
     15a:	mov    0x103e0(%rdx),%rsi
     161:	mov    0x103e8(%rdx),%rax
     168:	sub    %rsi,%rax
     16b:	sar    $0x3,%rax
     16f:	test   %eax,%eax
     171:	je     1e0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1e0>
     173:	xor    %ecx,%ecx
     175:	data16 cs nopw 0x0(%rax,%rax,1)
     180:	mov    (%r9,%rcx,4),%edi
     184:	test   %edi,%edi
     186:	je     1bb <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1bb>
     188:	mov    (%rsi,%rcx,8),%rdx
     18c:	mov    0x190(%r13),%rax
     193:	mov    0x48(%rdx),%rsi
     197:	mov    (%rax),%edx
     199:	shl    $0x7,%rdx
     19d:	mov    0x40(%rsi,%rdx,1),%r10d
     1a2:	mov    (%rsi,%rdx,1),%eax
     1a5:	add    0x54(%rsi,%rdx,1),%eax
     1a9:	sub    %r10d,%eax
     1ac:	cmp    %edi,%eax
     1ae:	jb     500 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x500>
     1b4:	mov    0x188(%r13),%rdx
     1bb:	mov    0x103e0(%rdx),%rsi
     1c2:	mov    0x103e8(%rdx),%rax
     1c9:	inc    %rcx
     1cc:	sub    %rsi,%rax
     1cf:	sar    $0x3,%rax
     1d3:	cmp    %eax,%ecx
     1d5:	jb     180 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x180>
     1d7:	test   %r15d,%r15d
     1da:	je     4be <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4be>
     1e0:	mov    %rbx,%rax
     1e3:	xor    %r14d,%r14d
     1e6:	mov    %r8d,-0x4b8(%rbp)
     1ed:	mov    %r9,-0x4c0(%rbp)
     1f4:	or     $0x1,%rax
     1f8:	mov    %rax,-0x4b0(%rbp)
     1ff:	mov    %r15d,%eax
     202:	mov    %rax,-0x4a8(%rbp)
     209:	jmp    30a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x30a>
     20e:	xchg   %ax,%ax
     210:	lea    0x40(%rdx,%rax,1),%rcx
     215:	lea    (%rdx,%rax,1),%r9
     219:	mov    (%rcx),%r15d
     21c:	vmovq  %r9,%xmm4
     221:	lea    0x1(%r15),%esi
     225:	mov    %esi,%r9d
     228:	sub    0x44(%rdx,%rax,1),%r9d
     22d:	cmp    %r9d,0x54(%rdx,%rax,1)
     232:	jb     410 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x410>
     238:	mov    $0x0,%r9d
     23e:	decl   0x53c(%r12)
     246:	jne    260 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x260>
     248:	mov    0x538(%r12),%eax
     250:	mov    0x530(%r12),%r9d
     258:	mov    %eax,0x53c(%r12)
     260:	shl    $0x7,%rdi
     264:	mov    0x4c(%rdx,%rdi,1),%eax
     268:	and    %r15d,%eax
     26b:	add    0x48(%rdx,%rdi,1),%eax
     26f:	mov    -0x4b0(%rbp),%rdi
     276:	shl    $0x5,%rax
     27a:	add    0x4000(%rdx),%rax
     281:	movq   $0x0,(%rax)
     288:	movq   $0xffffffffffffffff,0x8(%rax)
     290:	mov    %r10d,0x10(%rax)
     294:	mov    %r9d,0x14(%rax)
     298:	mov    %rdi,0x18(%rax)
     29c:	mov    %esi,(%rcx)
     29e:	mov    %r11d,%eax
     2a1:	mov    %r11d,%edx
     2a4:	shr    $0x6,%eax
     2a7:	and    $0x1,%eax
     2aa:	and    $0x3f,%edx
     2ad:	lea    0x2b8(%r8,%rax,8),%rax
     2b5:	mov    (%rax),%rsi
     2b8:	bt     %r11,%rsi
     2bc:	jb     2f0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2f0>
     2be:	lock bts %rdx,(%rax)
     2c3:	jb     2f0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2f0>
     2c5:	mov    0x48(%r8),%rax
     2c9:	mov    0x8(%r8),%rsi
     2cd:	test   %rsi,%rsi
     2d0:	je     2f0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2f0>
     2d2:	movzbl 0x4040(%rax),%eax
     2d9:	test   %al,%al
     2db:	jne    5c0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x5c0>
     2e1:	data16 cs nopw 0x0(%rax,%rax,1)
     2ec:	nopl   0x0(%rax)
     2f0:	mov    -0x4a8(%rbp),%rax
     2f7:	inc    %r14
     2fa:	cmp    %rax,%r14
     2fd:	je     4b0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4b0>
     303:	mov    0x188(%r13),%rdx
     30a:	test   %rbx,%rbx
     30d:	je     5f0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x5f0>
     313:	mov    0x220(%rbx),%rsi
     31a:	mov    0x228(%rbx),%rax
     321:	sub    %rsi,%rax
     324:	sar    $0x2,%rax
     328:	cmp    %rax,%r14
     32b:	jae    5f0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x5f0>
     331:	movslq (%rsi,%r14,4),%rax
     335:	mov    %rax,%r10
     338:	lea    0x111b8(,%rax,4),%rax
     340:	mov    (%rdx,%rax,1),%eax
     343:	mov    0x190(%r13),%r12
     34a:	mov    0x103e0(%rdx),%rdx
     351:	mov    (%r12),%r11d
     355:	mov    (%rdx,%rax,8),%r8
     359:	mov    0x538(%r12),%r9d
     361:	mov    %r11d,%edi
     364:	mov    0x48(%r8),%rdx
     368:	mov    %rdi,%rax
     36b:	shl    $0x7,%rax
     36f:	test   %r9d,%r9d
     372:	jne    210 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x210>
     378:	lea    0x40(%rdx,%rax,1),%rsi
     37d:	lea    (%rdx,%rax,1),%rcx
     381:	mov    (%rsi),%r15d
     384:	vmovq  %rsi,%xmm6
     389:	vmovq  %rcx,%xmm5
     38e:	lea    0x1(%r15),%esi
     392:	mov    %esi,%ecx
     394:	sub    0x44(%rdx,%rax,1),%ecx
     398:	cmp    %ecx,0x54(%rdx,%rax,1)
     39c:	jae    3bd <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x3bd>
     39e:	mov    (%rdx,%rax,1),%eax
     3a1:	vmovq  %xmm5,%rcx
     3a6:	mov    %eax,0x44(%rcx)
     3a9:	mov    %esi,%ecx
     3ab:	sub    %eax,%ecx
     3ad:	mov    %ecx,%eax
     3af:	vmovq  %xmm5,%rcx
     3b4:	cmp    %eax,0x54(%rcx)
     3b7:	jb     540 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x540>
     3bd:	shl    $0x7,%rdi
     3c1:	mov    0x4c(%rdx,%rdi,1),%eax
     3c5:	and    %r15d,%eax
     3c8:	add    0x48(%rdx,%rdi,1),%eax
     3cc:	mov    -0x4b0(%rbp),%rdi
     3d3:	shl    $0x5,%rax
     3d7:	add    0x4000(%rdx),%rax
     3de:	movq   $0x0,(%rax)
     3e5:	movq   $0xffffffffffffffff,0x8(%rax)
     3ed:	mov    %r10d,0x10(%rax)
     3f1:	movl   $0x0,0x14(%rax)
     3f8:	mov    %rdi,0x18(%rax)
     3fc:	vmovq  %xmm6,%rax
     401:	mov    %esi,(%rax)
     403:	jmp    29e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x29e>
     408:	nopl   0x0(%rax,%rax,1)
     410:	mov    (%rdx,%rax,1),%r9d
     414:	vmovq  %xmm4,%rax
     419:	mov    %r9d,0x44(%rax)
     41d:	mov    %esi,%eax
     41f:	sub    %r9d,%eax
     422:	vmovq  %xmm4,%r9
     427:	cmp    %eax,0x54(%r9)
     42b:	jae    238 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x238>
     431:	mov    0x4008(%rdx),%esi
     437:	mov    %rdi,%rax
     43a:	test   %esi,%esi
     43c:	je     682 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x682>
     442:	mov    %rdx,%rcx
     445:	xor    %esi,%esi
     447:	xor    %r8d,%r8d
     44a:	nopw   0x0(%rax,%rax,1)
     450:	mov    (%rcx),%r9d
     453:	inc    %r8d
     456:	sub    $0xffffffffffffff80,%rcx
     45a:	mov    -0x40(%rcx),%edi
     45d:	sub    %r9d,%edi
     460:	add    %rdi,%rsi
     463:	cmp    0x4008(%rdx),%r8d
     46a:	jb     450 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x450>
     46c:	mov    0x400c(%rdx),%edi
     472:	shl    $0x7,%rax
     476:	lea    (%rdx,%rax,1),%rcx
     47a:	add    %rdi,0x68(%rdx,%rax,1)
     47f:	mov    0x58(%rcx),%rbx
     483:	add    0x60(%rcx),%rsi
     487:	inc    %rbx
     48a:	vmovq  %rbx,%xmm0
     48f:	vpinsrq $0x1,%rsi,%xmm0,%xmm0
     495:	vmovdqu %xmm0,0x58(%rdx,%rax,1)
     49b:	incq   0x3f8(%r12)
     4a3:	vzeroupper
     4a6:	call   4ab <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4ab>
			4a7: R_X86_64_PLT32	abort-0x4
     4ab:	nopl   0x0(%rax,%rax,1)
     4b0:	mov    -0x4b8(%rbp),%r8d
     4b7:	mov    -0x4c0(%rbp),%r9
     4be:	test   %rbx,%rbx
     4c1:	je     4c7 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4c7>
     4c3:	movb   $0x1,0x42(%rbx)
     4c7:	mov    0x19b0(%r13),%rbx
     4ce:	mov    0x19a0(%r13),%rax
     4d5:	lea    -0x8(%rbx),%rdx
     4d9:	cmp    %rdx,%rax
     4dc:	je     600 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x600>
     4e2:	add    $0x8,%rax
     4e6:	inc    %r8d
     4e9:	mov    %rax,0x19a0(%r13)
     4f0:	cmp    0x19c0(%r13),%rax
     4f7:	jne    a0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xa0>
     4fd:	nopl   (%rax)
     500:	mov    %r8d,-0x4a8(%rbp)
     507:	mov    -0x38(%rbp),%rax
     50b:	sub    %fs:0x28,%rax
     514:	jne    1ab6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab6>
     51a:	mov    -0x4a8(%rbp),%eax
     520:	vzeroupper
     523:	lea    -0x30(%rbp),%rsp
     527:	pop    %rbx
     528:	pop    %r10
     52a:	pop    %r12
     52c:	pop    %r13
     52e:	pop    %r14
     530:	pop    %r15
     532:	pop    %rbp
     533:	ret
     534:	data16 cs nopw 0x0(%rax,%rax,1)
     53f:	nop
     540:	mov    0x4008(%rdx),%ecx
     546:	mov    %r9d,%esi
     549:	mov    %rdi,%rax
     54c:	test   %ecx,%ecx
     54e:	je     67a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x67a>
     554:	mov    %rdx,%rcx
     557:	xor    %r8d,%r8d
     55a:	nopw   0x0(%rax,%rax,1)
     560:	mov    (%rcx),%r9d
     563:	inc    %esi
     565:	sub    $0xffffffffffffff80,%rcx
     569:	mov    -0x40(%rcx),%edi
     56c:	sub    %r9d,%edi
     56f:	add    %rdi,%r8
     572:	cmp    0x4008(%rdx),%esi
     578:	jb     560 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x560>
     57a:	mov    0x400c(%rdx),%esi
     580:	shl    $0x7,%rax
     584:	lea    (%rdx,%rax,1),%rcx
     588:	add    %rsi,0x68(%rdx,%rax,1)
     58d:	mov    0x58(%rcx),%rbx
     591:	add    0x60(%rcx),%r8
     595:	inc    %rbx
     598:	vmovq  %rbx,%xmm0
     59d:	vpinsrq $0x1,%r8,%xmm0,%xmm0
     5a3:	vmovdqu %xmm0,0x58(%rdx,%rax,1)
     5a9:	incq   0x3f8(%r12)
     5b1:	vzeroupper
     5b4:	jmp    4a6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4a6>
     5b9:	nopl   0x0(%rax)
     5c0:	lea    0xac8(%r13),%rdi
     5c7:	movabs $0x500000000000000,%rdx
     5d1:	vzeroupper
     5d4:	call   5d9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x5d9>
			5d5: R_X86_64_PC32	.text+0xd0fc
     5d9:	vpxor  %xmm2,%xmm2,%xmm2
     5dd:	incq   0x438(%r12)
     5e5:	jmp    2f0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2f0>
     5ea:	nopw   0x0(%rax,%rax,1)
     5f0:	mov    $0x111b4,%eax
     5f5:	mov    $0xffffffff,%r10d
     5fb:	jmp    340 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x340>
     600:	mov    0x19a8(%r13),%rdi
     607:	mov    $0x200,%esi
     60c:	mov    %r9,-0x4b0(%rbp)
     613:	mov    %r8d,-0x4a8(%rbp)
     61a:	vzeroupper
     61d:	call   622 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x622>
			61e: R_X86_64_PLT32	_ZdlPvm-0x4
     622:	mov    0x19b8(%r13),%rax
     629:	mov    -0x4b0(%rbp),%r9
     630:	mov    -0x4a8(%rbp),%r8d
     637:	vpxor  %xmm2,%xmm2,%xmm2
     63b:	lea    0x8(%rax),%rdx
     63f:	mov    0x8(%rax),%rax
     643:	mov    %rdx,0x19b8(%r13)
     64a:	vmovq  %rax,%xmm1
     64f:	lea    0x200(%rax),%rdx
     656:	vpinsrq $0x1,%rdx,%xmm1,%xmm0
     65c:	vmovdqu %xmm0,0x19a8(%r13)
     665:	jmp    4e6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4e6>
     66a:	nopw   0x0(%rax,%rax,1)
     670:	mov    $0x111b4,%eax
     675:	jmp    141 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x141>
     67a:	xor    %r8d,%r8d
     67d:	jmp    57a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x57a>
     682:	xor    %esi,%esi
     684:	jmp    46c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x46c>
     689:	nopl   0x0(%rax)
     690:	mov    0x188(%r13),%rdx
     697:	xor    %r15d,%r15d
     69a:	mov    0x103e0(%rdx),%rsi
     6a1:	mov    0x103e8(%rdx),%rax
     6a8:	sub    %rsi,%rax
     6ab:	sar    $0x3,%rax
     6af:	test   %eax,%eax
     6b1:	jne    173 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x173>
     6b7:	jmp    4c7 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4c7>
     6bc:	nopl   0x0(%rax)
     6c0:	xor    %edx,%edx
     6c2:	xchg   %rdx,(%rax)
     6c5:	mov    %rdx,%rax
     6c8:	test   %rdx,%rdx
     6cb:	je     6e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x6e>
     6d1:	xor    %esi,%esi
     6d3:	jmp    6db <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x6db>
     6d5:	mov    %rax,%rsi
     6d8:	mov    %rcx,%rax
     6db:	mov    (%rax),%rcx
     6de:	mov    %rax,%rdx
     6e1:	mov    %rsi,(%rax)
     6e4:	test   %rcx,%rcx
     6e7:	jne    6d5 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x6d5>
     6e9:	mov    %rsi,-0x4d8(%rbp)
     6f0:	jmp    752 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x752>
     6f2:	cmpb   $0x0,0x5a0(%r14)
     6fa:	jne    7b0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x7b0>
     700:	cmpb   $0x0,0x5d6(%r14)
     708:	je     918 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x918>
     70e:	mov    -0x4c8(%rbp),%rax
     715:	mov    %r13,%rdi
     718:	movb   $0x2,0xb8(%rax)
     71f:	mov    -0x4c0(%rbp),%rsi
     726:	vzeroupper
     729:	call   72e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x72e>
			72a: R_X86_64_PLT32	_ZN4tomo6IoLoop11mark_activeEPNS_6ClientE-0x4
     72e:	addl   $0x2,-0x4a8(%rbp)
     735:	mov    -0x4d8(%rbp),%rax
     73c:	test   %rax,%rax
     73f:	je     6e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x6e>
     745:	mov    %rax,%rdx
     748:	mov    (%rax),%rax
     74b:	mov    %rax,-0x4d8(%rbp)
     752:	cmpb   $0x1,0x18(%rdx)
     756:	je     8dc <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x8dc>
     75c:	mov    0x8(%rdx),%rdx
     760:	mov    0x5c8(%rdx),%rax
     767:	mov    0x18(%rdx),%rbx
     76b:	mov    %rdx,-0x498(%rbp)
     772:	mov    %eax,%ecx
     774:	and    $0x7,%eax
     777:	mov    %rbx,-0x4c0(%rbp)
     77e:	shr    $0x3,%ecx
     781:	and    $0x7,%ecx
     784:	imul   $0x150,%rax,%rax
     78b:	add    0x80(%rbx,%rcx,8),%rax
     793:	mov    %rax,-0x4c8(%rbp)
     79a:	movzbl 0x621(%rdx),%eax
     7a1:	mov    -0x498(%rbp),%r14
     7a8:	test   %al,%al
     7aa:	jne    6f2 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x6f2>
     7b0:	mov    -0x4c0(%rbp),%rbx
     7b7:	mov    0x188(%r13),%rax
     7be:	cmpb   $0x0,0x32(%rbx)
     7c2:	jne    7fc <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x7fc>
     7c4:	mov    -0x4c0(%rbp),%rbx
     7cb:	movzbl 0x33(%rbx),%ebx
     7cf:	mov    %bl,-0x4f0(%rbp)
     7d5:	test   %bl,%bl
     7d7:	jne    7fc <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x7fc>
     7d9:	movzbl 0x14cc0(%rax),%edx
     7e0:	and    $0x1,%edx
     7e3:	je     b58 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xb58>
     7e9:	mov    %r14,%rdi
     7ec:	call   7f1 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x7f1>
			7ed: R_X86_64_PC32	.text+0xc0c
     7f1:	incl   -0x4a8(%rbp)
     7f7:	jmp    735 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x735>
     7fc:	mov    0x208c0(%rax),%rdx
     803:	cmp    %rdx,%r14
     806:	je     900 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x900>
     80c:	movb   $0x1,0x578(%r14)
     814:	mov    -0x4c0(%rbp),%rax
     81b:	mov    0x790(%rax),%rax
     822:	test   %rax,%rax
     825:	je     bd8 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xbd8>
     82b:	vzeroupper
     82e:	mov    -0x498(%rbp),%rdx
     835:	mov    0x30(%rax),%r15
     839:	mov    0x38(%rax),%r14
     83d:	mov    0x40(%rax),%rbx
     841:	vmovdqu 0x78(%rdx),%xmm6
     846:	mov    %r15,%r12
     849:	vmovdqu %xmm6,0x30(%rax)
     84e:	mov    0x88(%rdx),%rcx
     855:	mov    %rcx,0x40(%rax)
     859:	movq   $0x0,0x78(%rdx)
     861:	movq   $0x0,0x80(%rdx)
     86c:	movq   $0x0,0x88(%rdx)
     877:	cmp    %r14,%r15
     87a:	je     891 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x891>
     87c:	nopl   0x0(%rax)
     880:	mov    %r12,%rdi
     883:	add    $0x30,%r12
     887:	call   88c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x88c>
			888: R_X86_64_PLT32	_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv-0x4
     88c:	cmp    %r12,%r14
     88f:	jne    880 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x880>
     891:	test   %r15,%r15
     894:	je     8a4 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x8a4>
     896:	sub    %r15,%rbx
     899:	mov    %r15,%rdi
     89c:	mov    %rbx,%rsi
     89f:	call   8a4 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x8a4>
			8a0: R_X86_64_PLT32	_ZdlPvm-0x4
     8a4:	mov    -0x4c0(%rbp),%rsi
     8ab:	mov    %r13,%rdi
     8ae:	call   8b3 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x8b3>
			8af: R_X86_64_PLT32	_ZN4tomo17multi_close_entryERNS_6IoLoopERNS_6ClientE-0x4
     8b3:	mov    %r13,%rdi
     8b6:	mov    -0x4c8(%rbp),%rax
     8bd:	movb   $0x2,0xb8(%rax)
     8c4:	mov    -0x4c0(%rbp),%rsi
     8cb:	call   8d0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x8d0>
			8cc: R_X86_64_PLT32	_ZN4tomo6IoLoop11mark_activeEPNS_6ClientE-0x4
     8d0:	addl   $0x2,-0x4a8(%rbp)
     8d7:	jmp    735 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x735>
     8dc:	mov    0x190(%r13),%rax
     8e3:	mov    (%rax),%eax
     8e5:	shl    $0x6,%rax
     8e9:	add    0x188(%r13),%rax
     8f0:	mov    0x10(%rdx),%rdx
     8f4:	mov    %rdx,0x1e8f0(%rax)
     8fb:	jmp    7f1 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x7f1>
     900:	lock andb $0xfd,0x14cc0(%rax)
     908:	movq   $0x0,0x208c0(%rax)
     913:	jmp    80c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x80c>
     918:	mov    $0x40,%edi
     91d:	vzeroupper
     920:	call   925 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x925>
			921: R_X86_64_PLT32	_Znwm-0x4
     925:	mov    %rax,%r12
     928:	mov    0x0(%rip),%rax        # 92f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x92f>
			92b: R_X86_64_PC32	.LC92-0x4
     92f:	vpxor  %xmm0,%xmm0,%xmm0
     933:	lea    -0x240(%rbp),%rdi
     93a:	vmovdqu8 %ymm0,0x10(%r12)
     945:	mov    %rdi,-0x4b0(%rbp)
     94c:	lea    -0x220(%rbp),%rdi
     953:	lea    0x10(%r12),%r15
     958:	vmovdqu8 %xmm0,0x30(%r12)
     960:	mov    0x60(%r14),%rbx
     964:	mov    %rdi,-0x4b8(%rbp)
     96b:	mov    %rax,0x8(%r12)
     970:	lea    0x0(%rip),%rax        # 977 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x977>
			973: R_X86_64_PC32	_ZTVSt23_Sp_counted_ptr_inplaceIN4tomo23PubSubNotificationChainESaIvELN9__gnu_cxx12_Lock_policyE2EE+0xc
     977:	mov    %rax,(%r12)
     97b:	mov    0x68(%r14),%rax
     97f:	mov    %rax,-0x4c0(%rbp)
     986:	cmp    %rax,%rbx
     989:	je     b50 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xb50>
     98f:	vzeroupper
     992:	mov    (%rbx),%rdx
     995:	cmpb   $0x9,0x28(%rdx)
     999:	jne    aa0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xaa0>
     99f:	mov    %rdx,%rdi
     9a2:	lea    0x0(%rip),%rsi        # 9a9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x9a9>
			9a5: R_X86_64_PC32	.LC354-0x4
     9a9:	mov    %rdx,-0x4c8(%rbp)
     9b0:	call   9b5 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x9b5>
			9b1: R_X86_64_PC32	.text+0x696c
     9b5:	mov    -0x4c8(%rbp),%rdx
     9bc:	test   %al,%al
     9be:	jne    9de <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x9de>
     9c0:	mov    %rdx,%rdi
     9c3:	lea    0x0(%rip),%rsi        # 9ca <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x9ca>
			9c6: R_X86_64_PC32	.LC355-0x4
     9ca:	call   9cf <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x9cf>
			9cb: R_X86_64_PC32	.text+0x696c
     9cf:	mov    -0x4c8(%rbp),%rdx
     9d6:	test   %al,%al
     9d8:	je     aa0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xaa0>
     9de:	mov    0x8(%rdx),%rsi
     9e2:	mov    -0x4b0(%rbp),%rdi
     9e9:	add    $0x20,%rsi
     9ed:	call   9f2 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x9f2>
			9ee: R_X86_64_PLT32	_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEC1ERKS4_-0x4
     9f2:	mov    (%rbx),%rax
     9f5:	mov    -0x4b8(%rbp),%rdi
     9fc:	mov    0x8(%rax),%rsi
     a00:	add    $0x40,%rsi
     a04:	call   a09 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xa09>
			a05: R_X86_64_PLT32	_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEC1ERKS4_-0x4
     a09:	mov    (%rbx),%rdi
     a0c:	lea    0x0(%rip),%rsi        # a13 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xa13>
			a0f: R_X86_64_PC32	.LC355-0x4
     a13:	mov    0x20(%rdi),%rax
     a17:	mov    %rax,-0x200(%rbp)
     a1e:	call   a23 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xa23>
			a1f: R_X86_64_PC32	.text+0x696c
     a23:	mov    %al,-0x1f8(%rbp)
     a29:	mov    0x20(%r12),%rax
     a2e:	cmp    0x28(%r12),%rax
     a33:	je     f6d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xf6d>
     a39:	mov    -0x4b0(%rbp),%rsi
     a40:	mov    %rax,%rdi
     a43:	mov    %rax,-0x4c8(%rbp)
     a4a:	call   a4f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xa4f>
			a4b: R_X86_64_PLT32	_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEC1EOS4_-0x4
     a4f:	mov    -0x4c8(%rbp),%rax
     a56:	mov    -0x4b8(%rbp),%rsi
     a5d:	lea    0x20(%rax),%rdi
     a61:	call   a66 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xa66>
			a62: R_X86_64_PLT32	_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEC1EOS4_-0x4
     a66:	mov    -0x200(%rbp),%rdx
     a6d:	mov    -0x4c8(%rbp),%rax
     a74:	mov    %rdx,0x40(%rax)
     a78:	movzbl -0x1f8(%rbp),%edx
     a7f:	mov    %dl,0x48(%rax)
     a82:	addq   $0x50,0x20(%r12)
     a88:	mov    -0x4b8(%rbp),%rdi
     a8f:	call   a94 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xa94>
			a90: R_X86_64_PLT32	_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv-0x4
     a94:	mov    -0x4b0(%rbp),%rdi
     a9b:	call   aa0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xaa0>
			a9c: R_X86_64_PLT32	_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv-0x4
     aa0:	add    $0x8,%rbx
     aa4:	cmp    %rbx,-0x4c0(%rbp)
     aab:	jne    992 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x992>
     ab1:	cmpb   $0x0,0x0(%rip)        # ab8 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xab8>
			ab3: R_X86_64_PC32	__libc_single_threaded-0x5
     ab8:	vmovq  %r15,%xmm3
     abd:	lea    0x0(%rip),%rax        # ac4 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xac4>
			ac0: R_X86_64_PC32	_ZZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopEENUlPvE_4_FUNES3_-0x4
     ac4:	mov    %r14,0x38(%r12)
     ac9:	vpinsrq $0x1,%r12,%xmm3,%xmm0
     acf:	mov    %rax,0x30(%r12)
     ad4:	movb   $0x1,0x5d6(%r14)
     adc:	vmovdqa %xmm0,-0x460(%rbp)
     ae4:	je     bf5 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xbf5>
     aea:	incl   0x8(%r12)
     aef:	mov    0x8(%r15),%rax
     af3:	cmp    %rax,0x10(%r15)
     af7:	je     b32 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xb32>
     af9:	mov    0x190(%r13),%rax
     b00:	lea    -0x460(%rbp),%r14
     b07:	lea    0x1a10(%r13),%rdi
     b0e:	mov    0x1a20(%r13),%rbx
     b15:	mov    %r14,%rsi
     b18:	mov    (%rax),%eax
     b1a:	mov    %eax,(%r15)
     b1d:	mov    0x1a40(%r13),%r15
     b24:	call   b29 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xb29>
			b25: R_X86_64_PC32	.text+0x57ec
     b29:	cmp    %rbx,%r15
     b2c:	je     1b70 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1b70>
     b32:	mov    -0x458(%rbp),%rdi
     b39:	test   %rdi,%rdi
     b3c:	je     b43 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xb43>
     b3e:	call   b43 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xb43>
			b3f: R_X86_64_PLT32	_ZNSt16_Sp_counted_baseILN9__gnu_cxx12_Lock_policyE2EE10_M_releaseEv-0x4
     b43:	mov    %r12,%rdi
     b46:	call   b4b <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xb4b>
			b47: R_X86_64_PLT32	_ZNSt16_Sp_counted_baseILN9__gnu_cxx12_Lock_policyE2EE10_M_releaseEv-0x4
     b4b:	jmp    72e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x72e>
     b50:	vzeroupper
     b53:	jmp    ab1 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xab1>
     b58:	mov    0x208c0(%rax),%rdx
     b5f:	test   %rdx,%rdx
     b62:	jne    1a0b <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1a0b>
     b68:	vzeroupper
     b6b:	call   b70 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xb70>
			b6c: R_X86_64_PLT32	_ZN4tomo6now_nsEv-0x4
     b70:	cmp    0x5d8(%r14),%rax
     b77:	jb     7e9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x7e9>
     b7d:	cmpb   $0x0,0x5a0(%r14)
     b85:	jne    f86 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xf86>
     b8b:	mov    -0x498(%rbp),%r12
     b92:	cmpb   $0x0,0x5d4(%r12)
     b9b:	jne    c10 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xc10>
     b9d:	mov    0x188(%r13),%rbx
     ba4:	mov    0x190(%r13),%rax
     bab:	mov    %rax,-0x4b0(%rbp)
     bb2:	lea    0x14cc0(%rbx),%rax
     bb9:	mov    %rax,-0x4e0(%rbp)
     bc0:	movzbl 0x14cc0(%rbx),%eax
     bc7:	test   $0x1,%al
     bc9:	je     c48 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xc48>
     bcb:	mov    %r12,%rdi
     bce:	call   bd3 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xbd3>
			bcf: R_X86_64_PC32	.text+0xc0c
     bd3:	jmp    7f1 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x7f1>
     bd8:	mov    -0x4c0(%rbp),%rdi
     bdf:	vzeroupper
     be2:	call   be7 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xbe7>
			be3: R_X86_64_PC32	.text+0x174c
     be7:	test   %rax,%rax
     bea:	jne    82e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x82e>
     bf0:	jmp    8a4 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x8a4>
     bf5:	lock incl 0x8(%r12)
     bfb:	mov    -0x460(%rbp),%r15
     c02:	test   %r15,%r15
     c05:	jne    aef <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xaef>
     c0b:	jmp    b32 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xb32>
     c10:	mov    0x59c(%r12),%eax
     c18:	movzbl 0x598(%r12),%ecx
     c21:	mov    0x188(%r13),%rbx
     c28:	cmp    $0x1,%cl
     c2b:	sbb    $0xffffffff,%eax
     c2e:	mov    0x208d0(%rbx),%edx
     c34:	cmp    %edx,%eax
     c36:	jb     19e8 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x19e8>
     c3c:	mov    -0x498(%rbp),%r12
     c43:	jmp    ba4 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xba4>
     c48:	mov    0x208c0(%rbx),%rax
     c4f:	lea    0x208c0(%rbx),%rdx
     c56:	test   %rax,%rax
     c59:	jne    19d3 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x19d3>
     c5f:	mov    (%rdx),%rax
     c62:	cmp    %rax,%r12
     c65:	je     c74 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xc74>
     c67:	xor    %eax,%eax
     c69:	lock cmpxchg %r12,(%rdx)
     c6e:	jne    bcb <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xbcb>
     c74:	mov    0x5e8(%r12),%r15
     c7c:	test   %r15,%r15
     c7f:	jne    eb3 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xeb3>
     c85:	mov    0x103e8(%rbx),%rax
     c8c:	sub    0x103e0(%rbx),%rax
     c93:	sar    $0x3,%rax
     c97:	test   %eax,%eax
     c99:	je     1abe <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1abe>
     c9f:	lea    0x1e8f0(%rbx),%rcx
     ca6:	xor    %esi,%esi
     ca8:	mov    (%rcx),%rax
     cab:	cmp    -0x10(%rcx),%rax
     caf:	jne    bcb <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xbcb>
     cb5:	mov    0x103e0(%rbx),%rdx
     cbc:	mov    0x103e8(%rbx),%rax
     cc3:	inc    %esi
     cc5:	add    $0x40,%rcx
     cc9:	sub    %rdx,%rax
     ccc:	sar    $0x3,%rax
     cd0:	cmp    %eax,%esi
     cd2:	jb     ca8 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xca8>
     cd4:	lea    0x5f0(%r12),%rdi
     cdc:	mov    0x5f0(%r12),%rcx
     ce4:	mov    %rdi,-0x4e8(%rbp)
     ceb:	cmp    0x5f8(%r12),%rcx
     cf3:	je     cfd <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xcfd>
     cf5:	mov    %rcx,0x5f8(%r12)
     cfd:	movl   $0x0,-0x460(%rbp)
     d07:	test   %eax,%eax
     d09:	je     1b63 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1b63>
     d0f:	lea    -0x460(%rbp),%r14
     d16:	movl   $0x0,-0x4b8(%rbp)
     d20:	mov    (%rdx,%r15,1),%rax
     d24:	movzbl 0x4(%rax),%eax
     d28:	test   %al,%al
     d2a:	je     d41 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xd41>
     d2c:	cmpb   $0x1,0x182(%rbx)
     d33:	je     e96 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xe96>
     d39:	cmp    $0x1,%al
     d3b:	je     e96 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xe96>
     d41:	mov    0x103e0(%rbx),%rdx
     d48:	mov    0x103e8(%rbx),%rax
     d4f:	incl   -0x4b8(%rbp)
     d55:	mov    -0x4b8(%rbp),%edi
     d5b:	add    $0x8,%r15
     d5f:	sub    %rdx,%rax
     d62:	mov    %edi,-0x460(%rbp)
     d68:	sar    $0x3,%rax
     d6c:	cmp    %eax,%edi
     d6e:	jb     d20 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xd20>
     d70:	mov    -0x4e0(%rbp),%rax
     d77:	lock orb $0x2,(%rax)
     d7b:	mov    $0x1,%edi
     d80:	mov    %r14,%rsi
     d83:	call   d88 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xd88>
			d84: R_X86_64_PLT32	clock_gettime-0x4
     d88:	imul   $0x3b9aca00,-0x460(%rbp),%rax
     d93:	mov    0x5f0(%r12),%r15
     d9b:	mov    0x5f8(%r12),%r14
     da3:	add    -0x458(%rbp),%rax
     daa:	mov    %rax,0x5e0(%r12)
     db2:	mov    0x208c8(%rbx),%rax
     db9:	inc    %rax
     dbc:	mov    %rax,0x208c8(%rbx)
     dc3:	mov    %rax,0x5e8(%r12)
     dcb:	cmp    %r14,%r15
     dce:	je     fa7 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xfa7>
     dd4:	lea    0xac8(%r13),%rdi
     ddb:	mov    %rdi,-0x4b8(%rbp)
     de2:	mov    %r13,%rdi
     de5:	mov    %r12,%r13
     de8:	mov    %rdi,%r12
     deb:	jmp    e09 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xe09>
     ded:	mov    %rax,0x1e8f0(%rbx,%rdx,1)
     df5:	add    $0x4,%r15
     df9:	cmp    %r15,%r14
     dfc:	je     eaa <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xeaa>
     e02:	mov    0x5e8(%r13),%rax
     e09:	mov    (%r15),%esi
     e0c:	mov    -0x4b0(%rbp),%rcx
     e13:	mov    %rsi,%rdx
     e16:	shl    $0x6,%rdx
     e1a:	lea    (%rbx,%rdx,1),%rdi
     e1e:	mov    %rax,0x1e8e0(%rdi)
     e25:	cmp    (%rcx),%esi
     e27:	je     ded <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xded>
     e29:	lea    0x1e8d0(%rbx,%rdx,1),%r8
     e31:	lea    0x1e8c0(%rbx,%rdx,1),%rdx
     e39:	mov    (%rdx),%rax
     e3c:	mov    %rax,0x1e8d0(%rdi)
     e43:	lock cmpxchg %r8,(%rdx)
     e48:	jne    e3c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xe3c>
     e4a:	mov    0x103e0(%rbx),%rax
     e51:	mov    (%rax,%rsi,8),%rax
     e55:	mov    0x8(%rax),%rdx
     e59:	test   %rdx,%rdx
     e5c:	je     df5 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xdf5>
     e5e:	movzbl 0x2b0(%rax),%edx
     e65:	test   %dl,%dl
     e67:	je     df5 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xdf5>
     e69:	mov    0x8(%rax),%rsi
     e6d:	movabs $0x500000000000000,%rdx
     e77:	mov    -0x4b8(%rbp),%rdi
     e7e:	call   e83 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xe83>
			e7f: R_X86_64_PC32	.text+0xd0fc
     e83:	mov    -0x4b0(%rbp),%rax
     e8a:	incq   0x438(%rax)
     e91:	jmp    df5 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xdf5>
     e96:	mov    -0x4e8(%rbp),%rdi
     e9d:	mov    %r14,%rsi
     ea0:	call   ea5 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xea5>
			ea1: R_X86_64_PLT32	_ZNSt6vectorIjSaIjEE9push_backERKj-0x4
     ea5:	jmp    d41 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xd41>
     eaa:	mov    %r12,%rax
     ead:	mov    %r13,%r12
     eb0:	mov    %rax,%r13
     eb3:	mov    0x5f0(%r12),%rax
     ebb:	mov    0x5f8(%r12),%rsi
     ec3:	cmp    %rsi,%rax
     ec6:	je     fa7 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xfa7>
     ecc:	mov    $0x1,%ecx
     ed1:	mov    (%rax),%edx
     ed3:	shl    $0x6,%rdx
     ed7:	add    %rbx,%rdx
     eda:	mov    0x1e8f0(%rdx),%rdx
     ee1:	cmp    %rdx,0x5e8(%r12)
     ee9:	sete   %dl
     eec:	add    $0x4,%rax
     ef0:	and    %edx,%ecx
     ef2:	cmp    %rax,%rsi
     ef5:	jne    ed1 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xed1>
     ef7:	test   %cl,%cl
     ef9:	jne    fa7 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xfa7>
     eff:	lea    -0x460(%rbp),%r14
     f06:	mov    $0x1,%edi
     f0b:	mov    %r14,%rsi
     f0e:	call   f13 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xf13>
			f0f: R_X86_64_PLT32	clock_gettime-0x4
     f13:	imul   $0x3b9aca00,-0x460(%rbp),%rax
     f1e:	add    -0x458(%rbp),%rax
     f25:	sub    0x5e0(%r12),%rax
     f2d:	cmp    $0x3b9ac9ff,%rax
     f33:	jbe    bcb <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xbcb>
     f39:	mov    -0x4b0(%rbp),%rax
     f40:	mov    (%rax),%eax
     f42:	shl    $0x7,%rax
     f46:	add    %rbx,%rax
     f49:	lock incq 0x1a908(%rax)
     f51:	mov    -0x4e0(%rbp),%rax
     f58:	lock andb $0xfd,(%rax)
     f5c:	movq   $0x0,0x5e8(%r12)
     f68:	jmp    bcb <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xbcb>
     f6d:	mov    -0x4b0(%rbp),%rdx
     f74:	lea    0x18(%r12),%rdi
     f79:	mov    %rax,%rsi
     f7c:	call   f81 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xf81>
			f7d: R_X86_64_PLT32	_ZNSt6vectorIN4tomo22PubSubNotificationItemESaIS1_EE17_M_realloc_insertIJS1_EEEvN9__gnu_cxx17__normal_iteratorIPS1_S3_EEDpOT_-0x4
     f81:	jmp    a88 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xa88>
     f86:	movzbl 0x599(%r14),%eax
     f8e:	test   %al,%al
     f90:	jne    b8b <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xb8b>
     f96:	mov    -0x498(%rbp),%rdi
     f9d:	call   fa2 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xfa2>
			f9e: R_X86_64_PC32	.text+0xc0c
     fa2:	jmp    7f1 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x7f1>
     fa7:	mov    0x103e8(%rbx),%rax
     fae:	lea    0x14d08(%rbx),%rsi
     fb5:	xor    %ecx,%ecx
     fb7:	xor    %edx,%edx
     fb9:	sub    0x103e0(%rbx),%rax
     fc0:	sar    $0x3,%rax
     fc4:	test   %eax,%eax
     fc6:	je     1031 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1031>
     fc8:	mov    (%rsi),%rax
     fcb:	inc    %edx
     fcd:	add    $0x40,%rsi
     fd1:	add    %rax,%rcx
     fd4:	mov    0x103e8(%rbx),%rax
     fdb:	sub    0x103e0(%rbx),%rax
     fe2:	sar    $0x3,%rax
     fe6:	cmp    %eax,%edx
     fe8:	jb     fc8 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xfc8>
     fea:	test   %eax,%eax
     fec:	je     1a8c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1a8c>
     ff2:	lea    0x14d00(%rbx),%rdi
     ff9:	xor    %edx,%edx
     ffb:	xor    %esi,%esi
     ffd:	mov    (%rdi),%rax
    1000:	inc    %esi
    1002:	add    $0x40,%rdi
    1006:	add    %rax,%rdx
    1009:	mov    0x103e8(%rbx),%rax
    1010:	sub    0x103e0(%rbx),%rax
    1017:	sar    $0x3,%rax
    101b:	cmp    %eax,%esi
    101d:	jb     ffd <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xffd>
    101f:	cmp    %rcx,%rdx
    1022:	jb     4a6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4a6>
    1028:	cmp    %rdx,%rcx
    102b:	jne    eff <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xeff>
    1031:	mov    -0x498(%rbp),%rax
    1038:	movb   $0x1,-0x4f0(%rbp)
    103f:	mov    %rax,-0x4b0(%rbp)
    1046:	mov    -0x4b0(%rbp),%rax
    104d:	cmpb   $0x0,0x42(%rax)
    1051:	je     144d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x144d>
    1057:	mov    -0x4b0(%rbp),%rax
    105e:	cmpb   $0x0,0xc(%rax)
    1062:	jne    19ab <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x19ab>
    1068:	mov    -0x4b0(%rbp),%rbx
    106f:	xor    %ecx,%ecx
    1071:	mov    0x10(%rbx),%rdi
    1075:	mov    0x20(%rbx),%edx
    1078:	mov    0x18(%rbx),%rsi
    107c:	mov    %rdi,-0x510(%rbp)
    1083:	call   1088 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1088>
			1084: R_X86_64_PC32	.text+0x2c8cc
    1088:	mov    %rax,-0x4b8(%rbp)
    108f:	test   %rax,%rax
    1092:	je     26b8 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x26b8>
    1098:	mov    0x68(%rbx),%rax
    109c:	mov    0x60(%rbx),%rdx
    10a0:	movabs $0x1ffffffffffffff8,%rcx
    10aa:	vpxor  %xmm0,%xmm0,%xmm0
    10ae:	movq   $0x0,-0x470(%rbp)
    10b9:	vmovdqa %xmm0,-0x480(%rbp)
    10c1:	mov    %rax,-0x518(%rbp)
    10c8:	sub    %rdx,%rax
    10cb:	cmp    %rax,%rcx
    10ce:	jb     2652 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2652>
    10d4:	test   %rax,%rax
    10d7:	jne    1a38 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1a38>
    10dd:	mov    -0x518(%rbp),%rbx
    10e4:	mov    %rdx,-0x500(%rbp)
    10eb:	cmp    %rbx,%rdx
    10ee:	je     1264 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1264>
    10f4:	mov    -0x500(%rbp),%rax
    10fb:	mov    -0x478(%rbp),%r15
    1102:	mov    (%rax),%rbx
    1105:	cmp    -0x470(%rbp),%r15
    110c:	je     142c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x142c>
    1112:	mov    (%rbx),%rax
    1115:	mov    %rax,(%r15)
    1118:	mov    0x10(%rbx),%rax
    111c:	sub    0x8(%rbx),%rax
    1120:	movq   $0x0,0x8(%r15)
    1128:	movq   $0x0,0x10(%r15)
    1130:	movq   $0x0,0x18(%r15)
    1138:	je     1419 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1419>
    113e:	movabs $0x7fffffffffffffe0,%rdi
    1148:	mov    %rax,%r12
    114b:	cmp    %rax,%rdi
    114e:	jb     1ae8 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ae8>
    1154:	lea    -0x480(%rbp),%rax
    115b:	mov    %r12,%rdi
    115e:	mov    %rax,-0x4e8(%rbp)
    1165:	call   116a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x116a>
			1166: R_X86_64_PLT32	_Znwm-0x4
    116a:	mov    %rax,-0x4e0(%rbp)
    1171:	vpbroadcastq -0x4e0(%rbp),%xmm0
    117a:	mov    -0x4e0(%rbp),%rax
    1181:	add    %rax,%r12
    1184:	vmovdqu %xmm0,0x8(%r15)
    118a:	mov    %r12,0x18(%r15)
    118e:	mov    0x10(%rbx),%rdi
    1192:	mov    0x8(%rbx),%r14
    1196:	mov    %rdi,-0x508(%rbp)
    119d:	cmp    %r14,%rdi
    11a0:	je     1232 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1232>
    11a6:	mov    %rax,%rbx
    11a9:	jmp    11d0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x11d0>
    11ab:	cmp    $0x1,%r12
    11af:	je     1223 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1223>
    11b1:	test   %r12,%r12
    11b4:	jne    120f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x120f>
    11b6:	mov    %r12,0x8(%rbx)
    11ba:	add    $0x20,%r14
    11be:	add    $0x20,%rbx
    11c2:	movb   $0x0,(%rdi,%r12,1)
    11c7:	cmp    %r14,-0x508(%rbp)
    11ce:	je     1239 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1239>
    11d0:	lea    0x10(%rbx),%rdi
    11d4:	mov    0x8(%r14),%r12
    11d8:	mov    %rdi,(%rbx)
    11db:	mov    (%r14),%rax
    11de:	mov    %rax,-0x4e8(%rbp)
    11e5:	cmp    $0xf,%r12
    11e9:	jbe    11ab <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x11ab>
    11eb:	test   %r12,%r12
    11ee:	js     1b0f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1b0f>
    11f4:	mov    %r12,%rdi
    11f7:	inc    %rdi
    11fa:	js     1a20 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1a20>
    1200:	call   1205 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1205>
			1201: R_X86_64_PLT32	_Znwm-0x4
    1205:	mov    %rax,%rdi
    1208:	mov    %rax,(%rbx)
    120b:	mov    %r12,0x10(%rbx)
    120f:	mov    -0x4e8(%rbp),%rsi
    1216:	mov    %r12,%rdx
    1219:	call   121e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x121e>
			121a: R_X86_64_PLT32	memcpy-0x4
    121e:	mov    (%rbx),%rdi
    1221:	jmp    11b6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x11b6>
    1223:	mov    -0x4e8(%rbp),%rax
    122a:	movzbl (%rax),%eax
    122d:	mov    %al,0x10(%rbx)
    1230:	jmp    11b6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x11b6>
    1232:	mov    -0x4e0(%rbp),%rbx
    1239:	lea    0x20(%r15),%rax
    123d:	mov    %rbx,0x10(%r15)
    1241:	mov    %rax,-0x478(%rbp)
    1248:	addq   $0x8,-0x500(%rbp)
    1250:	mov    -0x500(%rbp),%rax
    1257:	cmp    %rax,-0x518(%rbp)
    125e:	jne    10f4 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x10f4>
    1264:	mov    -0x4b8(%rbp),%rsi
    126b:	mov    -0x510(%rbp),%rdi
    1272:	lea    -0x480(%rbp),%rax
    1279:	mov    %rax,%rdx
    127c:	mov    %rax,-0x4e8(%rbp)
    1283:	call   1288 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1288>
			1284: R_X86_64_PC32	.text+0x3d0ec
    1288:	test   %al,%al
    128a:	je     2dba <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2dba>
    1290:	mov    -0x4b8(%rbp),%rax
    1297:	mov    -0x4b0(%rbp),%rbx
    129e:	mov    0x78(%rax),%r14
    12a2:	mov    %r14,%rdi
    12a5:	cmp    %rbx,%rax
    12a8:	je     2585 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2585>
    12ae:	mov    -0x4b0(%rbp),%rax
    12b5:	mov    0x80(%rax),%rbx
    12bc:	mov    0x78(%rax),%r15
    12c0:	mov    -0x4b8(%rbp),%rax
    12c7:	mov    0x88(%rax),%rax
    12ce:	mov    %rbx,-0x500(%rbp)
    12d5:	sub    %r15,%rbx
    12d8:	mov    %r15,%r12
    12db:	mov    %rbx,-0x4e0(%rbp)
    12e2:	mov    %rax,-0x508(%rbp)
    12e9:	sub    %r14,%rax
    12ec:	cmp    %rbx,%rax
    12ef:	jb     24a5 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x24a5>
    12f5:	mov    -0x4b8(%rbp),%rax
    12fc:	mov    -0x4e0(%rbp),%rbx
    1303:	mov    0x80(%rax),%rax
    130a:	mov    %rax,-0x508(%rbp)
    1311:	sub    %r14,%rax
    1314:	cmp    %rbx,%rax
    1317:	jb     22a0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x22a0>
    131d:	test   %rbx,%rbx
    1320:	jle    1c50 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1c50>
    1326:	sar    $0x4,%rbx
    132a:	movabs $0xaaaaaaaaaaaaaaab,%rax
    1334:	mov    %rbx,%rdx
    1337:	imul   %rax,%rdx
    133b:	mov    %rdx,-0x500(%rbp)
    1342:	jmp    1391 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1391>
    1344:	test   %r15,%r15
    1347:	jne    13f8 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x13f8>
    134d:	mov    %r15,0x8(%r14)
    1351:	movb   $0x0,(%rax,%r15,1)
    1356:	mov    0x20(%r12),%rax
    135b:	add    $0x30,%r14
    135f:	add    $0x30,%r12
    1363:	mov    %rax,-0x10(%r14)
    1367:	mov    -0x8(%r12),%eax
    136c:	mov    %eax,-0x8(%r14)
    1370:	movzbl -0x4(%r12),%eax
    1376:	mov    %al,-0x4(%r14)
    137a:	movzbl -0x3(%r12),%eax
    1380:	mov    %al,-0x3(%r14)
    1384:	decq   -0x500(%rbp)
    138b:	je     1c50 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1c50>
    1391:	cmp    %r12,%r14
    1394:	je     1356 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1356>
    1396:	mov    (%r14),%rax
    1399:	lea    0x10(%r14),%rdx
    139d:	mov    0x8(%r12),%r15
    13a2:	cmp    %rdx,%rax
    13a5:	je     1bf2 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1bf2>
    13ab:	mov    0x10(%r14),%rbx
    13af:	cmp    %r15,%rbx
    13b2:	jae    1344 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1344>
    13b4:	test   %r15,%r15
    13b7:	js     1c24 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1c24>
    13bd:	add    %rbx,%rbx
    13c0:	cmp    %rbx,%r15
    13c3:	jae    1c14 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1c14>
    13c9:	test   %rbx,%rbx
    13cc:	js     1bfc <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1bfc>
    13d2:	lea    0x1(%rbx),%rdi
    13d6:	call   13db <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x13db>
			13d7: R_X86_64_PLT32	_Znwm-0x4
    13db:	mov    %r14,%rdi
    13de:	mov    %rax,-0x518(%rbp)
    13e5:	call   13ea <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x13ea>
			13e6: R_X86_64_PLT32	_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv-0x4
    13ea:	mov    -0x518(%rbp),%rax
    13f1:	mov    %rbx,0x10(%r14)
    13f5:	mov    %rax,(%r14)
    13f8:	mov    (%r12),%rsi
    13fc:	cmp    $0x1,%r15
    1400:	je     1b30 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1b30>
    1406:	mov    %r15,%rdx
    1409:	mov    %rax,%rdi
    140c:	call   1411 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1411>
			140d: R_X86_64_PLT32	memcpy-0x4
    1411:	mov    (%r14),%rax
    1414:	jmp    134d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x134d>
    1419:	xor    %r12d,%r12d
    141c:	movq   $0x0,-0x4e0(%rbp)
    1427:	jmp    1171 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1171>
    142c:	lea    -0x480(%rbp),%rax
    1433:	mov    %rbx,%rdx
    1436:	mov    %r15,%rsi
    1439:	mov    %rax,%rdi
    143c:	mov    %rax,-0x4e8(%rbp)
    1443:	call   1448 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1448>
			1444: R_X86_64_PLT32	_ZNSt6vectorIN4tomo18MultiQueuedCommandESaIS1_EE17_M_realloc_insertIJRKS1_EEEvN9__gnu_cxx17__normal_iteratorIPS1_S3_EEDpOT_-0x4
    1448:	jmp    1248 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1248>
    144d:	mov    -0x4b0(%rbp),%rdi
    1454:	vpxor  %xmm0,%xmm0,%xmm0
    1458:	mov    0x188(%r13),%r15
    145f:	lea    -0x240(%rbp),%r8
    1466:	mov    0x228(%rdi),%rax
    146d:	mov    0x220(%rdi),%rcx
    1474:	mov    0x5c8(%rdi),%rbx
    147b:	movb   $0x1,0x579(%rdi)
    1482:	vmovdqu8 %zmm0,-0x240(%rbp)
    1489:	vmovdqu8 %zmm0,-0x200(%rbp)
    1490:	vmovdqu8 %zmm0,-0x1c0(%rbp)
    1497:	vmovdqu8 %zmm0,-0x180(%rbp)
    149e:	mov    %rax,%rdx
    14a1:	mov    %rbx,-0x4b8(%rbp)
    14a8:	vmovdqu8 %zmm0,-0x140(%rbp)
    14af:	mov    0x190(%r13),%rbx
    14b6:	sub    %rcx,%rdx
    14b9:	vmovdqu8 %zmm0,-0x100(%rbp)
    14c0:	sar    $0x2,%rdx
    14c4:	vmovdqu8 %zmm0,-0xc0(%rbp)
    14cb:	vmovdqu8 %zmm0,-0x80(%rbp)
    14d2:	mov    %rdx,%r12
    14d5:	test   %edx,%edx
    14d7:	je     1523 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1523>
    14d9:	mov    %edx,%esi
    14db:	xor    %edx,%edx
    14dd:	jmp    14f4 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x14f4>
    14df:	mov    -0x4b0(%rbp),%rdi
    14e6:	mov    0x228(%rdi),%rax
    14ed:	mov    0x220(%rdi),%rcx
    14f4:	sub    %rcx,%rax
    14f7:	sar    $0x2,%rax
    14fb:	cmp    %rax,%rdx
    14fe:	jae    26de <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x26de>
    1504:	movslq (%rcx,%rdx,4),%rax
    1508:	lea    0x111b8(,%rax,4),%rax
    1510:	mov    (%r15,%rax,1),%eax
    1514:	inc    %rdx
    1517:	incl   -0x240(%rbp,%rax,4)
    151e:	cmp    %rdx,%rsi
    1521:	jne    14df <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x14df>
    1523:	mov    0x103e8(%r15),%rsi
    152a:	mov    0x103e0(%r15),%rax
    1531:	xor    %ecx,%ecx
    1533:	mov    %rsi,%rdx
    1536:	sub    %rax,%rdx
    1539:	sar    $0x3,%rdx
    153d:	test   %edx,%edx
    153f:	je     158d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x158d>
    1541:	mov    (%r8,%rcx,4),%edi
    1545:	test   %edi,%edi
    1547:	je     157c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x157c>
    1549:	mov    (%rax,%rcx,8),%rax
    154d:	mov    (%rbx),%edx
    154f:	mov    0x48(%rax),%rsi
    1553:	shl    $0x7,%rdx
    1557:	mov    0x40(%rsi,%rdx,1),%r9d
    155c:	mov    (%rsi,%rdx,1),%eax
    155f:	add    0x54(%rsi,%rdx,1),%eax
    1563:	sub    %r9d,%eax
    1566:	cmp    %edi,%eax
    1568:	jb     197c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x197c>
    156e:	mov    0x103e0(%r15),%rax
    1575:	mov    0x103e8(%r15),%rsi
    157c:	mov    %rsi,%rdx
    157f:	inc    %rcx
    1582:	sub    %rax,%rdx
    1585:	sar    $0x3,%rdx
    1589:	cmp    %edx,%ecx
    158b:	jb     1541 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1541>
    158d:	mov    -0x4b0(%rbp),%rax
    1594:	cmpb   $0x0,0x44(%rax)
    1598:	jne    18fc <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x18fc>
    159e:	vzeroupper
    15a1:	lea    -0x460(%rbp),%r14
    15a8:	xor    %edi,%edi
    15aa:	mov    %r14,%rsi
    15ad:	call   15b2 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x15b2>
			15ae: R_X86_64_PLT32	clock_gettime-0x4
    15b2:	mov    -0x458(%rbp),%rcx
    15b9:	movabs $0x431bde82d7b634db,%rax
    15c3:	imul   $0x3e8,-0x460(%rbp),%rsi
    15ce:	imul   %rcx
    15d1:	sar    $0x3f,%rcx
    15d5:	mov    %rdx,%rax
    15d8:	sar    $0x12,%rax
    15dc:	sub    %rcx,%rax
    15df:	add    %rax,%rsi
    15e2:	mov    -0x4b0(%rbp),%rax
    15e9:	mov    0x68(%rax),%rdx
    15ed:	mov    %rsi,0x48(%rax)
    15f1:	mov    0x60(%rax),%rax
    15f5:	cmp    %rdx,%rax
    15f8:	je     1624 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1624>
    15fa:	mov    (%rax),%rcx
    15fd:	mov    0xe0(%rcx),%rcx
    1604:	test   %rcx,%rcx
    1607:	je     161b <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x161b>
    1609:	mov    -0x4b0(%rbp),%rdi
    1610:	mov    0x48(%rdi),%rsi
    1614:	mov    %rsi,0x118(%rcx)
    161b:	add    $0x8,%rax
    161f:	cmp    %rax,%rdx
    1622:	jne    15fa <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x15fa>
    1624:	mov    -0x4b0(%rbp),%rax
    162b:	lea    0x622(%rax),%rcx
    1632:	movzbl 0x622(%rax),%eax
    1639:	test   %al,%al
    163b:	je     1bb0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1bb0>
    1641:	mov    -0x4b0(%rbp),%rax
    1648:	mov    -0x4b8(%rbp),%rdi
    164f:	movabs $0xfffffffb00000000,%rcx
    1659:	mov    %rdi,0x5c8(%rax)
    1660:	mov    -0x4c8(%rbp),%rdi
    1667:	mov    %rcx,0xb0(%rdi)
    166e:	cmpb   $0x0,0x42(%rax)
    1672:	mov    %rax,0xa8(%rdi)
    1679:	jne    4a6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4a6>
    167f:	cmpb   $0x0,0x60c(%rax)
    1686:	je     2606 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2606>
    168c:	mov    -0x4c0(%rbp),%rax
    1693:	mov    -0x4b0(%rbp),%rdi
    169a:	mov    0x790(%rax),%rax
    16a1:	movb   $0x1,0x42(%rdi)
    16a5:	test   %rax,%rax
    16a8:	je     16b4 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x16b4>
    16aa:	cmp    %rdi,0x48(%rax)
    16ae:	je     1be5 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1be5>
    16b4:	mov    -0x4b0(%rbp),%rax
    16bb:	cmpb   $0x0,0xe(%rax)
    16bf:	je     25f0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x25f0>
    16c5:	lea    0x3c0(%rbx),%rax
    16cc:	mov    %rax,-0x4e0(%rbp)
    16d3:	test   %r12d,%r12d
    16d6:	je     1826 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1826>
    16dc:	mov    -0x4b0(%rbp),%rax
    16e3:	lea    0x668(%r13),%r10
    16ea:	lea    0x5e8(%r13),%r11
    16f1:	mov    %r13,%r9
    16f4:	mov    %r10,-0x500(%rbp)
    16fb:	or     $0x1,%rax
    16ff:	mov    %rax,-0x4e8(%rbp)
    1706:	mov    %r12d,%eax
    1709:	xor    %r12d,%r12d
    170c:	mov    %r12,%r8
    170f:	mov    %rax,-0x4c8(%rbp)
    1716:	mov    -0x4b0(%rbp),%rax
    171d:	mov    0x220(%rax),%rdx
    1724:	mov    0x228(%rax),%rax
    172b:	mov    %rax,-0x4f0(%rbp)
    1732:	sub    %rdx,%rax
    1735:	sar    $0x2,%rax
    1739:	cmp    %rax,%r8
    173c:	jae    2613 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2613>
    1742:	movslq (%rdx,%r8,4),%rdx
    1746:	mov    %rdx,%rax
    1749:	lea    0x111b8(,%rdx,4),%rdx
    1751:	mov    %r9,-0x518(%rbp)
    1758:	mov    %r8,-0x510(%rbp)
    175f:	mov    %r11,-0x508(%rbp)
    1766:	mov    (%r15,%rdx,1),%r12d
    176a:	mov    %r12d,-0x4f0(%rbp)
    1771:	mov    0x103e0(%r15),%rdx
    1778:	mov    -0x4c0(%rbp),%rcx
    177f:	mov    (%rdx,%r12,8),%rdi
    1783:	mov    %rcx,-0x460(%rbp)
    178a:	mov    -0x4b8(%rbp),%rcx
    1791:	mov    %eax,-0x450(%rbp)
    1797:	movl   $0x0,-0x44c(%rbp)
    17a1:	mov    -0x4e8(%rbp),%rax
    17a8:	mov    (%rbx),%esi
    17aa:	mov    %r14,%rdx
    17ad:	mov    %rcx,-0x458(%rbp)
    17b4:	mov    -0x4e0(%rbp),%rcx
    17bb:	mov    %rax,-0x448(%rbp)
    17c2:	call   17c7 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x17c7>
			17c3: R_X86_64_PLT32	_ZN4tomo9ThreadCtx15post_task_quietEjRKNS_4TaskERNS_11LoopSignalsE-0x4
    17c7:	test   %al,%al
    17c9:	je     4a6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4a6>
    17cf:	mov    -0x508(%rbp),%r11
    17d6:	mov    -0x510(%rbp),%r8
    17dd:	mov    -0x518(%rbp),%r9
    17e4:	lea    (%r11,%r12,1),%rax
    17e8:	cmpb   $0x0,(%rax)
    17eb:	jne    1813 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1813>
    17ed:	movb   $0x1,(%rax)
    17f0:	mov    0x868(%r9),%eax
    17f7:	mov    -0x500(%rbp),%rdi
    17fe:	mov    -0x4f0(%rbp),%r10d
    1805:	lea    0x1(%rax),%edx
    1808:	mov    %edx,0x868(%r9)
    180f:	mov    %r10d,(%rdi,%rax,4)
    1813:	inc    %r8
    1816:	cmp    %r8,-0x4c8(%rbp)
    181d:	jne    1716 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1716>
    1823:	mov    %r9,%r13
    1826:	mov    0x190(%r13),%rax
    182d:	mov    (%rax),%eax
    182f:	shl    $0x7,%rax
    1833:	add    0x188(%r13),%rax
    183a:	lock incq 0x1a8f8(%rax)
    1842:	mov    0x190(%r13),%r14
    1849:	mov    0x868(%r13),%r8d
    1850:	mov    (%r14),%eax
    1853:	test   %r8d,%r8d
    1856:	je     18d6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x18d6>
    1858:	mov    %eax,%edx
    185a:	mov    $0x1,%ebx
    185f:	xor    %r12d,%r12d
    1862:	shr    $0x6,%edx
    1865:	shlx   %rax,%rbx,%rbx
    186a:	and    $0x1,%edx
    186d:	and    $0x3f,%eax
    1870:	lea    0x2b8(,%rdx,8),%r15
    1878:	mov    0x188(%r13),%rcx
    187f:	mov    0x668(%r13,%r12,4),%edx
    1887:	mov    0x103e0(%rcx),%rcx
    188e:	movb   $0x0,0x5e8(%r13,%rdx,1)
    1897:	mov    (%rcx,%rdx,8),%rdx
    189b:	lea    (%rdx,%r15,1),%rcx
    189f:	mov    (%rcx),%rsi
    18a2:	test   %rsi,%rbx
    18a5:	jne    18ca <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x18ca>
    18a7:	lock bts %rax,(%rcx)
    18ac:	jb     18ca <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x18ca>
    18ae:	mov    0x48(%rdx),%rcx
    18b2:	mov    0x8(%rdx),%rsi
    18b6:	test   %rsi,%rsi
    18b9:	je     18ca <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x18ca>
    18bb:	movzbl 0x4040(%rcx),%edx
    18c2:	test   %dl,%dl
    18c4:	jne    2622 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2622>
    18ca:	inc    %r12
    18cd:	cmp    0x868(%r13),%r12d
    18d4:	jb     1878 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1878>
    18d6:	mov    -0x4c0(%rbp),%rsi
    18dd:	mov    %r13,%rdi
    18e0:	movl   $0x0,0x868(%r13)
    18eb:	call   18f0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x18f0>
			18ec: R_X86_64_PLT32	_ZN4tomo6IoLoop11mark_activeEPNS_6ClientE-0x4
    18f0:	addl   $0x2,-0x4a8(%rbp)
    18f7:	jmp    735 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x735>
    18fc:	mov    0x4f8(%r13),%rax
    1903:	sub    0x4f0(%r13),%rax
    190a:	cmp    $0x38,%rax
    190e:	ja     197c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x197c>
    1910:	mov    -0x4c8(%rbp),%rax
    1917:	testb  $0x20,0x1c(%rax)
    191b:	je     2180 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2180>
    1921:	mov    $0xffffffff,%edx
    1926:	mov    0x14cb8(%r15),%rcx
    192d:	mov    -0x4c8(%rbp),%rdi
    1934:	mov    %rcx,%rax
    1937:	shl    $0x20,%rdx
    193b:	and    %rdx,%rax
    193e:	mov    0xc(%rdi),%esi
    1941:	or     %rsi,%rax
    1944:	cmp    %rax,%rcx
    1947:	jae    194c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x194c>
    1949:	add    %rdx,%rax
    194c:	mov    -0x4b0(%rbp),%r14
    1953:	mov    (%rbx),%ecx
    1955:	lea    0x2e8(%r13),%rdi
    195c:	mov    %r15,%rsi
    195f:	mov    %r14,%rdx
    1962:	mov    %rax,(%r14)
    1965:	vzeroupper
    1968:	call   196d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x196d>
			1969: R_X86_64_PLT32	_ZN4tomo16ScatterArenaPool17register_snapshotERNS_6ServerEPNS_11SnapshotCutEj-0x4
    196d:	test   %al,%al
    196f:	jne    218c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x218c>
    1975:	movq   $0xffffffffffffffff,(%r14)
    197c:	mov    -0x4c0(%rbp),%rax
    1983:	mov    -0x4c0(%rbp),%rbx
    198a:	mov    -0x4b0(%rbp),%rdi
    1991:	movzbl 0x35(%rax),%eax
    1995:	mov    %al,-0x4b8(%rbp)
    199b:	or     $0x1,%eax
    199e:	mov    %al,0x35(%rbx)
    19a1:	call   19a6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x19a6>
			19a2: R_X86_64_PC32	.text+0xc0c
    19a6:	jmp    7f1 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x7f1>
    19ab:	mov    0x190(%r13),%rax
    19b2:	mov    0x188(%r13),%rsi
    19b9:	mov    -0x4b0(%rbp),%rdx
    19c0:	lea    0x2e8(%r13),%rdi
    19c7:	mov    (%rax),%ecx
    19c9:	call   19ce <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x19ce>
			19ca: R_X86_64_PC32	.text+0x611c
    19ce:	jmp    1068 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1068>
    19d3:	mov    0x208c0(%rbx),%rax
    19da:	cmp    %rax,%r12
    19dd:	jne    bcb <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xbcb>
    19e3:	jmp    c5f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xc5f>
    19e8:	mov    0x208c0(%rbx),%r12
    19ef:	mov    -0x498(%rbp),%rax
    19f6:	mov    %rax,-0x4b0(%rbp)
    19fd:	cmp    %r12,%rax
    1a00:	jne    1046 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1046>
    1a06:	jmp    b9d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xb9d>
    1a0b:	mov    0x208c0(%rax),%rax
    1a12:	cmp    %rax,%r14
    1a15:	jne    7e9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x7e9>
    1a1b:	jmp    b68 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xb68>
    1a20:	mov    -0x38(%rbp),%rax
    1a24:	sub    %fs:0x28,%rax
    1a2d:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    1a33:	call   1a38 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1a38>
			1a34: R_X86_64_PLT32	_ZSt17__throw_bad_allocv-0x4
    1a38:	sar    $0x3,%rax
    1a3c:	shl    $0x5,%rax
    1a40:	mov    %rax,%rbx
    1a43:	lea    -0x480(%rbp),%rax
    1a4a:	mov    %rbx,%rdi
    1a4d:	mov    %rax,-0x4e8(%rbp)
    1a54:	call   1a59 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1a59>
			1a55: R_X86_64_PLT32	_Znwm-0x4
    1a59:	vpbroadcastq %rax,%xmm0
    1a5f:	add    %rbx,%rax
    1a62:	mov    %rax,-0x470(%rbp)
    1a69:	mov    -0x4b0(%rbp),%rax
    1a70:	vmovdqa %xmm0,-0x480(%rbp)
    1a78:	mov    0x60(%rax),%rdx
    1a7c:	mov    0x68(%rax),%rax
    1a80:	mov    %rax,-0x518(%rbp)
    1a87:	jmp    10dd <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x10dd>
    1a8c:	test   %rcx,%rcx
    1a8f:	je     1031 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1031>
    1a95:	jmp    4a6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4a6>
    1a9a:	dec    %rax
    1a9d:	je     2c0c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2c0c>
    1aa3:	mov    -0x38(%rbp),%rax
    1aa7:	sub    %fs:0x28,%rax
    1ab0:	je     2c36 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2c36>
    1ab6:	vzeroupper
    1ab9:	call   1abe <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1abe>
			1aba: R_X86_64_PLT32	__stack_chk_fail-0x4
    1abe:	mov    0x5f0(%r12),%rax
    1ac6:	lea    -0x460(%rbp),%r14
    1acd:	cmp    0x5f8(%r12),%rax
    1ad5:	je     d70 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xd70>
    1adb:	mov    %rax,0x5f8(%r12)
    1ae3:	jmp    d70 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xd70>
    1ae8:	test   %rax,%rax
    1aeb:	jns    1b3d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1b3d>
    1aed:	mov    -0x38(%rbp),%rax
    1af1:	sub    %fs:0x28,%rax
    1afa:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    1afc:	lea    -0x480(%rbp),%rax
    1b03:	mov    %rax,-0x4e8(%rbp)
    1b0a:	call   1b0f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1b0f>
			1b0b: R_X86_64_PLT32	_ZSt28__throw_bad_array_new_lengthv-0x4
    1b0f:	mov    -0x38(%rbp),%rax
    1b13:	sub    %fs:0x28,%rax
    1b1c:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    1b1e:	lea    0x0(%rip),%rdi        # 1b25 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1b25>
			1b21: R_X86_64_PC32	.LC156-0x4
    1b25:	call   1b2a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1b2a>
			1b26: R_X86_64_PLT32	_ZSt20__throw_length_errorPKc-0x4
    1b2a:	nopw   0x0(%rax,%rax,1)
    1b30:	movzbl (%rsi),%edx
    1b33:	mov    %dl,(%rax)
    1b35:	mov    (%r14),%rax
    1b38:	jmp    134d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x134d>
    1b3d:	mov    -0x38(%rbp),%rax
    1b41:	sub    %fs:0x28,%rax
    1b4a:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    1b50:	lea    -0x480(%rbp),%rax
    1b57:	mov    %rax,-0x4e8(%rbp)
    1b5e:	call   1b63 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1b63>
			1b5f: R_X86_64_PLT32	_ZSt17__throw_bad_allocv-0x4
    1b63:	lea    -0x460(%rbp),%r14
    1b6a:	jmp    d70 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xd70>
    1b6f:	nop
    1b70:	mov    0x1a20(%r13),%rsi
    1b77:	mov    %r13,%rdi
    1b7a:	call   1b7f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1b7f>
			1b7b: R_X86_64_PLT32	_ZN4tomo6IoLoop24pubsub_notification_sendERKSt10shared_ptrINS_23PubSubNotificationChainEE-0x4
    1b7f:	jmp    b32 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xb32>
    1b84:	mov    0x188(%r13),%rdx
    1b8b:	mov    0x103e0(%rdx),%rsi
    1b92:	mov    0x103e8(%rdx),%rax
    1b99:	sub    %rsi,%rax
    1b9c:	sar    $0x3,%rax
    1ba0:	test   %eax,%eax
    1ba2:	jne    173 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x173>
    1ba8:	jmp    4c3 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4c3>
    1bad:	nopl   (%rax)
    1bb0:	mov    0x103e8(%r15),%rdx
    1bb7:	mov    (%rbx),%eax
    1bb9:	sub    0x103e0(%r15),%rdx
    1bc0:	sar    $0x3,%rdx
    1bc4:	cmp    %edx,%eax
    1bc6:	jae    4a6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4a6>
    1bcc:	add    $0x534,%rax
    1bd2:	shl    $0x6,%rax
    1bd6:	add    %r15,%rax
    1bd9:	lock incq (%rax)
    1bdd:	movb   $0x1,(%rcx)
    1be0:	jmp    1641 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1641>
    1be5:	movq   $0x0,0x48(%rax)
    1bed:	jmp    16b4 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x16b4>
    1bf2:	mov    $0xf,%ebx
    1bf7:	jmp    13af <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x13af>
    1bfc:	mov    -0x38(%rbp),%rax
    1c00:	sub    %fs:0x28,%rax
    1c09:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    1c0f:	call   1c14 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1c14>
			1c10: R_X86_64_PLT32	_ZSt17__throw_bad_allocv-0x4
    1c14:	mov    %r15,%rdi
    1c17:	inc    %rdi
    1c1a:	js     1bfc <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1bfc>
    1c1c:	mov    %r15,%rbx
    1c1f:	jmp    13d6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x13d6>
    1c24:	mov    -0x38(%rbp),%rax
    1c28:	sub    %fs:0x28,%rax
    1c31:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    1c37:	lea    0x0(%rip),%rdi        # 1c3e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1c3e>
			1c3a: R_X86_64_PC32	.LC156-0x4
    1c3e:	call   1c43 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1c43>
			1c3f: R_X86_64_PLT32	_ZSt20__throw_length_errorPKc-0x4
    1c43:	data16 cs nopw 0x0(%rax,%rax,1)
    1c4e:	xchg   %ax,%ax
    1c50:	cmp    %r14,-0x508(%rbp)
    1c57:	je     1c7f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1c7f>
    1c59:	mov    (%r14),%rdi
    1c5c:	lea    0x10(%r14),%rax
    1c60:	cmp    %rax,%rdi
    1c63:	je     1c72 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1c72>
    1c65:	mov    0x10(%r14),%rax
    1c69:	lea    0x1(%rax),%rsi
    1c6d:	call   1c72 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1c72>
			1c6e: R_X86_64_PLT32	_ZdlPvm-0x4
    1c72:	add    $0x30,%r14
    1c76:	cmp    %r14,-0x508(%rbp)
    1c7d:	jne    1c59 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1c59>
    1c7f:	mov    -0x4b8(%rbp),%rax
    1c86:	mov    0x78(%rax),%r14
    1c8a:	mov    -0x4e0(%rbp),%rbx
    1c91:	add    %r14,%rbx
    1c94:	mov    -0x4b8(%rbp),%rax
    1c9b:	mov    %rbx,0x80(%rax)
    1ca2:	mov    -0x4b8(%rbp),%rax
    1ca9:	lea    0x220(%rax),%r12
    1cb0:	cmp    %rbx,%r14
    1cb3:	je     1cca <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1cca>
    1cb5:	mov    0x28(%r14),%esi
    1cb9:	mov    %r12,%rdi
    1cbc:	call   1cc1 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1cc1>
			1cbd: R_X86_64_PC32	.text+0x385c
    1cc1:	add    $0x30,%r14
    1cc5:	cmp    %rbx,%r14
    1cc8:	jne    1cb5 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1cb5>
    1cca:	mov    -0x4b8(%rbp),%rax
    1cd1:	mov    0x90(%rax),%rbx
    1cd8:	cmp    %rbx,0x98(%rax)
    1cdf:	je     296c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x296c>
    1ce5:	mov    -0x510(%rbp),%rax
    1cec:	movzbl 0x10438(%rax),%eax
    1cf3:	test   %al,%al
    1cf5:	je     1eeb <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1eeb>
    1cfb:	mov    -0x4b8(%rbp),%rax
    1d02:	vpxor  %xmm0,%xmm0,%xmm0
    1d06:	movq   $0x0,-0x450(%rbp)
    1d11:	vmovdqa %xmm0,-0x460(%rbp)
    1d19:	mov    0x90(%rax),%r15
    1d20:	mov    0x98(%rax),%rax
    1d27:	mov    %rax,-0x4e0(%rbp)
    1d2e:	cmp    %rax,%r15
    1d31:	je     1e1d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1e1d>
    1d37:	xor    %r14d,%r14d
    1d3a:	xor    %edx,%edx
    1d3c:	jmp    1d6a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1d6a>
    1d3e:	mov    %eax,(%rdx)
    1d40:	add    $0x4,%rdx
    1d44:	mov    %rdx,-0x458(%rbp)
    1d4b:	add    $0x30,%r15
    1d4f:	cmp    %r15,-0x4e0(%rbp)
    1d56:	je     1e1d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1e1d>
    1d5c:	mov    -0x458(%rbp),%rdx
    1d63:	mov    -0x450(%rbp),%r14
    1d6a:	mov    0x28(%r15),%eax
    1d6e:	mov    %eax,-0x500(%rbp)
    1d74:	cmp    %r14,%rdx
    1d77:	jne    1d3e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1d3e>
    1d79:	mov    -0x460(%rbp),%r12
    1d80:	mov    %rdx,%rax
    1d83:	movabs $0x1fffffffffffffff,%rbx
    1d8d:	sub    %r12,%rax
    1d90:	mov    %rax,-0x508(%rbp)
    1d97:	sar    $0x2,%rax
    1d9b:	cmp    %rbx,%rax
    1d9e:	je     226d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x226d>
    1da4:	cmp    %rdx,%r12
    1da7:	je     224c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x224c>
    1dad:	lea    (%rax,%rax,1),%rdx
    1db1:	cmp    %rax,%rdx
    1db4:	jb     2240 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2240>
    1dba:	xor    %ebx,%ebx
    1dbc:	xor    %edi,%edi
    1dbe:	test   %rdx,%rdx
    1dc1:	jne    2206 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2206>
    1dc7:	mov    -0x508(%rbp),%rax
    1dce:	mov    -0x500(%rbp),%ecx
    1dd4:	vmovq  %rdi,%xmm7
    1dd9:	lea    0x4(%rdi,%rax,1),%rdx
    1dde:	mov    %ecx,(%rdi,%rax,1)
    1de1:	vpinsrq $0x1,%rdx,%xmm7,%xmm6
    1de7:	vmovdqa %xmm6,-0x500(%rbp)
    1def:	test   %rax,%rax
    1df2:	jg     294e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x294e>
    1df8:	test   %r12,%r12
    1dfb:	jne    2959 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2959>
    1e01:	vmovdqa -0x500(%rbp),%xmm3
    1e09:	mov    %rbx,-0x450(%rbp)
    1e10:	vmovdqa %xmm3,-0x460(%rbp)
    1e18:	jmp    1d4b <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1d4b>
    1e1d:	mov    -0x4b8(%rbp),%rax
    1e24:	lea    -0x460(%rbp),%r14
    1e2b:	lea    -0x490(%rbp),%rbx
    1e32:	cmpq   $0x0,0x1b0(%rax)
    1e3a:	je     1e5f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1e5f>
    1e3c:	lea    -0x490(%rbp),%rbx
    1e43:	lea    -0x460(%rbp),%r14
    1e4a:	movl   $0x0,-0x490(%rbp)
    1e54:	mov    %rbx,%rsi
    1e57:	mov    %r14,%rdi
    1e5a:	call   1e5f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1e5f>
			1e5b: R_X86_64_PC32	.text+0x3d5c
    1e5f:	mov    -0x510(%rbp),%rsi
    1e66:	mov    %r14,%rdx
    1e69:	mov    %rbx,%rdi
    1e6c:	add    $0x103f8,%rsi
    1e73:	call   1e78 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1e78>
			1e74: R_X86_64_PLT32	_ZN4tomo16aof_create_groupERNS_10AofManagerERKSt6vectorIjSaIjEE-0x4
    1e78:	mov    -0x4b8(%rbp),%rax
    1e7f:	vmovdqa -0x490(%rbp),%xmm0
    1e87:	movq   $0x0,-0x488(%rbp)
    1e92:	movq   $0x0,-0x490(%rbp)
    1e9d:	mov    0x638(%rax),%rdi
    1ea4:	vmovdqu %xmm0,0x630(%rax)
    1eac:	vmovq  %xmm0,%rax
    1eb1:	test   %rdi,%rdi
    1eb4:	je     1eda <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1eda>
    1eb6:	call   1ebb <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ebb>
			1eb7: R_X86_64_PLT32	_ZNSt16_Sp_counted_baseILN9__gnu_cxx12_Lock_policyE2EE10_M_releaseEv-0x4
    1ebb:	mov    -0x488(%rbp),%rdi
    1ec2:	test   %rdi,%rdi
    1ec5:	je     1ecc <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ecc>
    1ec7:	call   1ecc <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ecc>
			1ec8: R_X86_64_PLT32	_ZNSt16_Sp_counted_baseILN9__gnu_cxx12_Lock_policyE2EE10_M_releaseEv-0x4
    1ecc:	mov    -0x4b8(%rbp),%rax
    1ed3:	mov    0x630(%rax),%rax
    1eda:	test   %rax,%rax
    1edd:	je     2c53 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2c53>
    1ee3:	mov    %r14,%rdi
    1ee6:	call   1eeb <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1eeb>
			1ee7: R_X86_64_PLT32	_ZNSt6vectorIjSaIjEED1Ev-0x4
    1eeb:	mov    -0x478(%rbp),%r12
    1ef2:	mov    -0x480(%rbp),%rbx
    1ef9:	cmp    %rbx,%r12
    1efc:	je     1f68 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1f68>
    1efe:	mov    %r13,%rax
    1f01:	mov    %rbx,%r13
    1f04:	mov    %rbx,-0x4e0(%rbp)
    1f0b:	mov    %rax,%r15
    1f0e:	mov    0x10(%r13),%rbx
    1f12:	mov    0x8(%r13),%r14
    1f16:	cmp    %r14,%rbx
    1f19:	je     1f41 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1f41>
    1f1b:	mov    (%r14),%rdi
    1f1e:	lea    0x10(%r14),%rax
    1f22:	cmp    %rax,%rdi
    1f25:	je     1f34 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1f34>
    1f27:	mov    0x10(%r14),%rax
    1f2b:	lea    0x1(%rax),%rsi
    1f2f:	call   1f34 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1f34>
			1f30: R_X86_64_PLT32	_ZdlPvm-0x4
    1f34:	add    $0x20,%r14
    1f38:	cmp    %r14,%rbx
    1f3b:	jne    1f1b <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1f1b>
    1f3d:	mov    0x8(%r13),%r14
    1f41:	test   %r14,%r14
    1f44:	je     1f55 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1f55>
    1f46:	mov    0x18(%r13),%rsi
    1f4a:	mov    %r14,%rdi
    1f4d:	sub    %r14,%rsi
    1f50:	call   1f55 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1f55>
			1f51: R_X86_64_PLT32	_ZdlPvm-0x4
    1f55:	add    $0x20,%r13
    1f59:	cmp    %r13,%r12
    1f5c:	jne    1f0e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1f0e>
    1f5e:	mov    -0x4e0(%rbp),%rbx
    1f65:	mov    %r15,%r13
    1f68:	test   %rbx,%rbx
    1f6b:	je     1f7f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1f7f>
    1f6d:	mov    -0x470(%rbp),%rsi
    1f74:	mov    %rbx,%rdi
    1f77:	sub    %rbx,%rsi
    1f7a:	call   1f7f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1f7f>
			1f7b: R_X86_64_PLT32	_ZdlPvm-0x4
    1f7f:	mov    -0x4b0(%rbp),%rdi
    1f86:	mov    -0x4b8(%rbp),%rbx
    1f8d:	mov    0x580(%rdi),%rax
    1f94:	mov    %rax,0x580(%rbx)
    1f9b:	mov    0x588(%rdi),%eax
    1fa1:	mov    %eax,0x588(%rbx)
    1fa7:	mov    0x58c(%rdi),%eax
    1fad:	mov    %eax,0x58c(%rbx)
    1fb3:	mov    0x59c(%rdi),%eax
    1fb9:	movzbl 0x598(%rdi),%edx
    1fc0:	cmp    $0x1,%dl
    1fc3:	sbb    $0xffffffff,%eax
    1fc6:	mov    %eax,0x59c(%rbx)
    1fcc:	mov    0x5d0(%rdi),%eax
    1fd2:	mov    %eax,-0x4e0(%rbp)
    1fd8:	inc    %eax
    1fda:	mov    %eax,0x5d0(%rbx)
    1fe0:	mov    0x5c8(%rdi),%rax
    1fe7:	mov    %rax,0x5c8(%rbx)
    1fee:	movzbl 0x5d4(%rdi),%eax
    1ff5:	and    %al,0x5d4(%rbx)
    1ffb:	mov    0x30(%rdi),%rax
    1fff:	movb   $0x1,0x41(%rbx)
    2003:	movb   $0x0,0xf(%rbx)
    2007:	mov    %rax,0x30(%rbx)
    200b:	mov    0x228(%rbx),%rax
    2012:	sub    0x220(%rbx),%rax
    2019:	sar    $0x2,%rax
    201d:	mov    %eax,0x618(%rbx)
    2023:	mov    %eax,0x61c(%rbx)
    2029:	mov    %eax,0x624(%rbx)
    202f:	mov    0x1978(%r13),%rcx
    2036:	mov    0x1980(%r13),%rbx
    203d:	sub    %rcx,%rbx
    2040:	mov    %rbx,%rdx
    2043:	sar    $0x3,%rdx
    2047:	inc    %rdx
    204a:	mov    %rdx,%rax
    204d:	shr    $0x3c,%rax
    2051:	jne    2904 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2904>
    2057:	mov    0x1988(%r13),%rax
    205e:	sub    %rcx,%rax
    2061:	sar    $0x3,%rax
    2065:	cmp    %rdx,%rax
    2068:	jb     28b4 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x28b4>
    206e:	mov    -0x4b0(%rbp),%rbx
    2075:	mov    -0x4b8(%rbp),%rdi
    207c:	movzbl -0x4f0(%rbp),%ecx
    2083:	movzbl 0x40(%rbx),%eax
    2087:	mov    %al,0x40(%rdi)
    208a:	mov    0x38(%rbx),%rax
    208e:	mov    %rax,0x38(%rdi)
    2092:	movb   $0x0,0x40(%rbx)
    2096:	mov    %rbx,%rax
    2099:	mov    %cl,0x579(%rdi)
    209f:	mov    %rdi,%rbx
    20a2:	mov    0x188(%r13),%rdi
    20a9:	test   %cl,%cl
    20ab:	je     26e8 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x26e8>
    20b1:	lock cmpxchg %rbx,0x208c0(%rdi)
    20ba:	jne    4a6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4a6>
    20c0:	sub    $0x8,%rsp
    20c4:	lea    0x868(%r13),%rax
    20cb:	lea    -0x460(%rbp),%r14
    20d2:	mov    0x190(%r13),%rsi
    20d9:	mov    0x188(%r13),%rdi
    20e0:	push   %r14
    20e2:	push   %rax
    20e3:	lea    0x668(%r13),%rax
    20ea:	push   %rax
    20eb:	lea    0x5e8(%r13),%rax
    20f2:	mov    -0x4b8(%rbp),%r9
    20f9:	mov    -0x4c8(%rbp),%r8
    2100:	push   %rax
    2101:	mov    -0x4b0(%rbp),%rax
    2108:	mov    -0x4c0(%rbp),%rcx
    210f:	lea    0x2e8(%r13),%rdx
    2116:	push   0x5c8(%rax)
    211c:	call   2121 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2121>
			211d: R_X86_64_PLT32	_ZN4tomo22multi_dispatch_attemptILb0EZNS_27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopEEUlvE0_EEbRNS_6ServerERNS_9ThreadCtxERNS_16ScatterArenaPoolERNS_6ClientERNS_2OpEPNS_14MultiExecStateEmPbPjRjOT0_-0x4
    2121:	add    $0x30,%rsp
    2125:	test   %al,%al
    2127:	jne    274e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x274e>
    212d:	mov    0x188(%r13),%rdx
    2134:	mov    -0x4b8(%rbp),%rax
    213b:	mov    -0x4b0(%rbp),%rbx
    2142:	lock cmpxchg %rbx,0x208c0(%rdx)
    214b:	jne    4a6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x4a6>
    2151:	mov    -0x4b8(%rbp),%rbx
    2158:	mov    -0x4b0(%rbp),%r15
    215f:	movzbl 0x40(%rbx),%eax
    2163:	mov    %rbx,%rdi
    2166:	mov    %al,0x40(%r15)
    216a:	movb   $0x0,0x40(%rbx)
    216e:	call   2173 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2173>
			216f: R_X86_64_PC32	.text+0x3476c
    2173:	mov    %r15,%rdi
    2176:	call   217b <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x217b>
			2177: R_X86_64_PC32	.text+0xc0c
    217b:	jmp    7f1 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x7f1>
    2180:	mov    0x14cb8(%r15),%rax
    2187:	jmp    194c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x194c>
    218c:	lock incq 0x16d68(%r15)
    2194:	lock incq 0x16d60(%r15)
    219c:	mov    0x16d1c(%r15),%r14d
    21a3:	test   %r14d,%r14d
    21a6:	je     15a1 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x15a1>
    21ac:	mov    -0x4b0(%rbp),%rax
    21b3:	mov    0x220(%rax),%rcx
    21ba:	mov    0x228(%rax),%rax
    21c1:	mov    %rax,-0x4e0(%rbp)
    21c8:	sub    %rcx,%rax
    21cb:	cmp    $0x4,%rax
    21cf:	jbe    15a1 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x15a1>
    21d5:	mov    (%rcx),%eax
    21d7:	mov    -0x4b0(%rbp),%rdi
    21de:	mov    %eax,0x58(%rdi)
    21e1:	call   21e6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x21e6>
			21e2: R_X86_64_PLT32	_ZN4tomo6now_nsEv-0x4
    21e6:	mov    -0x4b0(%rbp),%rdi
    21ed:	mov    %rax,%rcx
    21f0:	mov    %r14d,%eax
    21f3:	imul   $0x3e8,%rax,%rax
    21fa:	add    %rcx,%rax
    21fd:	mov    %rax,0x50(%rdi)
    2201:	jmp    15a1 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x15a1>
    2206:	movabs $0x1fffffffffffffff,%rax
    2210:	cmp    %rax,%rdx
    2213:	cmova  %rax,%rdx
    2217:	lea    0x0(,%rdx,4),%rbx
    221f:	mov    %rbx,%rdi
    2222:	lea    -0x460(%rbp),%r14
    2229:	call   222e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x222e>
			222a: R_X86_64_PLT32	_Znwm-0x4
    222e:	mov    -0x450(%rbp),%r14
    2235:	mov    %rax,%rdi
    2238:	add    %rax,%rbx
    223b:	jmp    1dc7 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1dc7>
    2240:	movabs $0x7ffffffffffffffc,%rbx
    224a:	jmp    221f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x221f>
    224c:	add    $0x1,%rax
    2250:	jb     2240 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2240>
    2252:	movabs $0x1fffffffffffffff,%rdx
    225c:	cmp    %rdx,%rax
    225f:	cmova  %rdx,%rax
    2263:	lea    0x0(,%rax,4),%rbx
    226b:	jmp    221f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x221f>
    226d:	mov    -0x38(%rbp),%rax
    2271:	sub    %fs:0x28,%rax
    227a:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    2280:	lea    0x0(%rip),%rdi        # 2287 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2287>
			2283: R_X86_64_PC32	.LC80-0x4
    2287:	lea    -0x460(%rbp),%r14
    228e:	call   2293 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2293>
			228f: R_X86_64_PLT32	_ZSt20__throw_length_errorPKc-0x4
    2293:	data16 cs nopw 0x0(%rax,%rax,1)
    229e:	xchg   %ax,%ax
    22a0:	lea    (%r15,%rax,1),%rbx
    22a4:	mov    %rbx,-0x518(%rbp)
    22ab:	test   %rax,%rax
    22ae:	jg     230d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x230d>
    22b0:	jmp    23c7 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x23c7>
    22b5:	data16 cs nopw 0x0(%rax,%rax,1)
    22c0:	test   %r15,%r15
    22c3:	jne    2374 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2374>
    22c9:	mov    %r15,0x8(%r14)
    22cd:	movb   $0x0,(%rax,%r15,1)
    22d2:	mov    0x20(%r12),%rax
    22d7:	add    $0x30,%r14
    22db:	add    $0x30,%r12
    22df:	mov    %rax,-0x10(%r14)
    22e3:	mov    -0x8(%r12),%eax
    22e8:	mov    %eax,-0x8(%r14)
    22ec:	movzbl -0x4(%r12),%eax
    22f2:	mov    %al,-0x4(%r14)
    22f6:	movzbl -0x3(%r12),%eax
    22fc:	mov    %al,-0x3(%r14)
    2300:	cmp    %r12,-0x518(%rbp)
    2307:	je     2395 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2395>
    230d:	cmp    %r14,%r12
    2310:	je     22d2 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x22d2>
    2312:	mov    (%r14),%rax
    2315:	lea    0x10(%r14),%rdx
    2319:	mov    0x8(%r12),%r15
    231e:	cmp    %rdx,%rax
    2321:	je     2591 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2591>
    2327:	mov    0x10(%r14),%rbx
    232b:	cmp    %r15,%rbx
    232e:	jae    22c0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x22c0>
    2330:	test   %r15,%r15
    2333:	js     25c3 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x25c3>
    2339:	add    %rbx,%rbx
    233c:	cmp    %rbx,%r15
    233f:	jae    25b3 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x25b3>
    2345:	test   %rbx,%rbx
    2348:	js     259b <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x259b>
    234e:	lea    0x1(%rbx),%rdi
    2352:	call   2357 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2357>
			2353: R_X86_64_PLT32	_Znwm-0x4
    2357:	mov    %r14,%rdi
    235a:	mov    %rax,-0x500(%rbp)
    2361:	call   2366 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2366>
			2362: R_X86_64_PLT32	_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv-0x4
    2366:	mov    -0x500(%rbp),%rax
    236d:	mov    %rbx,0x10(%r14)
    2371:	mov    %rax,(%r14)
    2374:	mov    (%r12),%rsi
    2378:	cmp    $0x1,%r15
    237c:	je     248b <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x248b>
    2382:	mov    %r15,%rdx
    2385:	mov    %rax,%rdi
    2388:	call   238d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x238d>
			2389: R_X86_64_PLT32	memcpy-0x4
    238d:	mov    (%r14),%rax
    2390:	jmp    22c9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x22c9>
    2395:	mov    -0x4b8(%rbp),%rax
    239c:	mov    -0x4b0(%rbp),%rbx
    23a3:	mov    0x78(%rax),%rdi
    23a7:	mov    0x80(%rbx),%rcx
    23ae:	mov    0x80(%rax),%rax
    23b5:	mov    0x78(%rbx),%r15
    23b9:	mov    %rcx,-0x500(%rbp)
    23c0:	mov    %rax,-0x508(%rbp)
    23c7:	mov    -0x508(%rbp),%r12
    23ce:	mov    %rdi,%r14
    23d1:	mov    %r12,%rax
    23d4:	sub    %rdi,%rax
    23d7:	add    %rax,%r15
    23da:	cmp    %r15,-0x500(%rbp)
    23e1:	jne    243b <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x243b>
    23e3:	jmp    1c8a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1c8a>
    23e8:	nopl   0x0(%rax,%rax,1)
    23f0:	cmp    $0x1,%r14
    23f4:	je     2498 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2498>
    23fa:	test   %r14,%r14
    23fd:	jne    2477 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2477>
    23ff:	mov    %r14,0x8(%r12)
    2404:	movb   $0x0,(%rdi,%r14,1)
    2409:	mov    0x20(%r15),%rax
    240d:	add    $0x30,%r12
    2411:	add    $0x30,%r15
    2415:	mov    %rax,-0x10(%r12)
    241a:	mov    -0x8(%r15),%eax
    241e:	mov    %eax,-0x8(%r12)
    2423:	movzwl -0x4(%r15),%eax
    2428:	mov    %ax,-0x4(%r12)
    242e:	cmp    %r15,-0x500(%rbp)
    2435:	je     1c7f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1c7f>
    243b:	mov    0x8(%r15),%r14
    243f:	lea    0x10(%r12),%rdi
    2444:	mov    %rdi,(%r12)
    2448:	mov    (%r15),%rbx
    244b:	cmp    $0xf,%r14
    244f:	jbe    23f0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x23f0>
    2451:	test   %r14,%r14
    2454:	js     299e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x299e>
    245a:	mov    %r14,%rdi
    245d:	inc    %rdi
    2460:	js     2986 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2986>
    2466:	call   246b <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x246b>
			2467: R_X86_64_PLT32	_Znwm-0x4
    246b:	mov    %rax,%rdi
    246e:	mov    %rax,(%r12)
    2472:	mov    %r14,0x10(%r12)
    2477:	mov    %r14,%rdx
    247a:	mov    %rbx,%rsi
    247d:	call   2482 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2482>
			247e: R_X86_64_PLT32	memcpy-0x4
    2482:	mov    (%r12),%rdi
    2486:	jmp    23ff <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x23ff>
    248b:	movzbl (%rsi),%edx
    248e:	mov    %dl,(%rax)
    2490:	mov    (%r14),%rax
    2493:	jmp    22c9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x22c9>
    2498:	movzbl (%rbx),%eax
    249b:	mov    %al,0x10(%r12)
    24a0:	jmp    23ff <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x23ff>
    24a5:	movabs $0x7fffffffffffffe0,%rax
    24af:	cmp    %rbx,%rax
    24b2:	jb     2a61 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2a61>
    24b8:	mov    -0x4e0(%rbp),%rdi
    24bf:	call   24c4 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x24c4>
			24c0: R_X86_64_PLT32	_Znwm-0x4
    24c4:	mov    %rax,%r14
    24c7:	mov    %rax,%r12
    24ca:	cmp    %r15,-0x500(%rbp)
    24d1:	jne    252a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x252a>
    24d3:	jmp    29d4 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x29d4>
    24d8:	nopl   0x0(%rax,%rax,1)
    24e0:	cmp    $0x1,%rbx
    24e4:	je     29c0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x29c0>
    24ea:	test   %rbx,%rbx
    24ed:	jne    256d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x256d>
    24ef:	mov    %rbx,0x8(%r12)
    24f4:	movb   $0x0,(%rdi,%rbx,1)
    24f8:	mov    0x20(%r15),%rax
    24fc:	add    $0x30,%r12
    2500:	add    $0x30,%r15
    2504:	mov    %rax,-0x10(%r12)
    2509:	mov    -0x8(%r15),%eax
    250d:	mov    %eax,-0x8(%r12)
    2512:	movzwl -0x4(%r15),%eax
    2517:	mov    %ax,-0x4(%r12)
    251d:	cmp    %r15,-0x500(%rbp)
    2524:	je     29d4 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x29d4>
    252a:	lea    0x10(%r12),%rdi
    252f:	mov    0x8(%r15),%rbx
    2533:	mov    %rdi,(%r12)
    2537:	mov    (%r15),%rax
    253a:	mov    %rax,-0x508(%rbp)
    2541:	cmp    $0xf,%rbx
    2545:	jbe    24e0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x24e0>
    2547:	test   %rbx,%rbx
    254a:	js     2a91 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2a91>
    2550:	mov    %rbx,%rdi
    2553:	inc    %rdi
    2556:	js     2a79 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2a79>
    255c:	call   2561 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2561>
			255d: R_X86_64_PLT32	_Znwm-0x4
    2561:	mov    %rax,%rdi
    2564:	mov    %rax,(%r12)
    2568:	mov    %rbx,0x10(%r12)
    256d:	mov    -0x508(%rbp),%rsi
    2574:	mov    %rbx,%rdx
    2577:	call   257c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x257c>
			2578: R_X86_64_PLT32	memcpy-0x4
    257c:	mov    (%r12),%rdi
    2580:	jmp    24ef <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x24ef>
    2585:	mov    0x80(%rax),%rbx
    258c:	jmp    1ca2 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ca2>
    2591:	mov    $0xf,%ebx
    2596:	jmp    232b <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x232b>
    259b:	mov    -0x38(%rbp),%rax
    259f:	sub    %fs:0x28,%rax
    25a8:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    25ae:	call   25b3 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x25b3>
			25af: R_X86_64_PLT32	_ZSt17__throw_bad_allocv-0x4
    25b3:	mov    %r15,%rdi
    25b6:	inc    %rdi
    25b9:	js     259b <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x259b>
    25bb:	mov    %r15,%rbx
    25be:	jmp    2352 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2352>
    25c3:	mov    -0x38(%rbp),%rax
    25c7:	sub    %fs:0x28,%rax
    25d0:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    25d6:	lea    0x0(%rip),%rdi        # 25dd <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x25dd>
			25d9: R_X86_64_PC32	.LC156-0x4
    25dd:	call   25e2 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x25e2>
			25de: R_X86_64_PLT32	_ZSt20__throw_length_errorPKc-0x4
    25e2:	data16 cs nopw 0x0(%rax,%rax,1)
    25ed:	nopl   (%rax)
    25f0:	mov    (%rbx),%eax
    25f2:	shl    $0x7,%rax
    25f6:	add    %r15,%rax
    25f9:	lock incq 0x1a8c0(%rax)
    2601:	jmp    16c5 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x16c5>
    2606:	mov    %rax,%rdi
    2609:	call   260e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x260e>
			260a: R_X86_64_PC32	.text+0x111c
    260e:	jmp    168c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x168c>
    2613:	mov    $0x111b4,%edx
    2618:	mov    $0xffffffff,%eax
    261d:	jmp    1751 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1751>
    2622:	lea    0xac8(%r13),%rdi
    2629:	movabs $0x500000000000000,%rdx
    2633:	mov    %rax,-0x4b0(%rbp)
    263a:	call   263f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x263f>
			263b: R_X86_64_PC32	.text+0xd0fc
    263f:	mov    -0x4b0(%rbp),%rax
    2646:	incq   0x438(%r14)
    264d:	jmp    18ca <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x18ca>
    2652:	mov    -0x38(%rbp),%rax
    2656:	sub    %fs:0x28,%rax
    265f:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    2665:	lea    -0x480(%rbp),%rax
    266c:	lea    0x0(%rip),%rdi        # 2673 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2673>
			266f: R_X86_64_PC32	.LC116-0x4
    2673:	mov    %rax,-0x4e8(%rbp)
    267a:	call   267f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x267f>
			267b: R_X86_64_PLT32	_ZSt20__throw_length_errorPKc-0x4
    267f:	vzeroupper
    2682:	call   2687 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2687>
			2683: R_X86_64_PLT32	__cxa_end_catch-0x4
    2687:	mov    -0x4e8(%rbp),%rdi
    268e:	vzeroupper
    2691:	call   2696 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2696>
			2692: R_X86_64_PLT32	_ZNSt6vectorIN4tomo18MultiQueuedCommandESaIS1_EED1Ev-0x4
    2696:	dec    %r12
    2699:	jne    2b65 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b65>
    269f:	mov    %rbx,%rdi
    26a2:	call   26a7 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x26a7>
			26a3: R_X86_64_PLT32	__cxa_begin_catch-0x4
    26a7:	mov    -0x4b8(%rbp),%rdi
    26ae:	call   26b3 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x26b3>
			26af: R_X86_64_PC32	.text+0x3476c
    26b3:	call   26b8 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x26b8>
			26b4: R_X86_64_PLT32	__cxa_end_catch-0x4
    26b8:	call   26bd <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x26bd>
			26b9: R_X86_64_PLT32	_ZN4tomo6now_nsEv-0x4
    26bd:	mov    -0x4b0(%rbp),%rbx
    26c4:	add    $0xf4240,%rax
    26ca:	mov    %rbx,%rdi
    26cd:	mov    %rax,0x5d8(%rbx)
    26d4:	call   26d9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x26d9>
			26d5: R_X86_64_PC32	.text+0xc0c
    26d9:	jmp    7f1 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x7f1>
    26de:	mov    $0x111b4,%eax
    26e3:	jmp    1510 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1510>
    26e8:	sub    $0x8,%rsp
    26ec:	lea    0x868(%r13),%rax
    26f3:	lea    -0x460(%rbp),%r14
    26fa:	mov    0x190(%r13),%rsi
    2701:	push   %r14
    2703:	push   %rax
    2704:	lea    0x668(%r13),%rax
    270b:	mov    -0x4b8(%rbp),%r9
    2712:	push   %rax
    2713:	lea    0x5e8(%r13),%rax
    271a:	mov    -0x4c8(%rbp),%r8
    2721:	mov    -0x4c0(%rbp),%rcx
    2728:	push   %rax
    2729:	mov    -0x4b0(%rbp),%rax
    2730:	lea    0x2e8(%r13),%rdx
    2737:	push   0x5c8(%rax)
    273d:	call   2742 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2742>
			273e: R_X86_64_PLT32	_ZN4tomo22multi_dispatch_attemptILb0EZNS_27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopEEUlvE0_EEbRNS_6ServerERNS_9ThreadCtxERNS_16ScatterArenaPoolERNS_6ClientERNS_2OpEPNS_14MultiExecStateEmPbPjRjOT0_-0x4
    2742:	add    $0x30,%rsp
    2746:	test   %al,%al
    2748:	je     2151 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2151>
    274e:	mov    -0x4b0(%rbp),%rax
    2755:	mov    0x78(%rax),%r12
    2759:	mov    0x80(%rax),%r14
    2760:	cmp    %r14,%r12
    2763:	je     2787 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2787>
    2765:	mov    %r12,%rbx
    2768:	mov    %rbx,%rdi
    276b:	add    $0x30,%rbx
    276f:	call   2774 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2774>
			2770: R_X86_64_PLT32	_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv-0x4
    2774:	cmp    %rbx,%r14
    2777:	jne    2768 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2768>
    2779:	mov    -0x4b0(%rbp),%rax
    2780:	mov    %r12,0x80(%rax)
    2787:	mov    -0x4b0(%rbp),%rax
    278e:	mov    -0x4d0(%rbp),%rdi
    2795:	lea    -0x498(%rbp),%rsi
    279c:	movb   $0x1,0x43(%rax)
    27a0:	call   27a5 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x27a5>
			27a1: R_X86_64_PLT32	_ZNSt6vectorIPN4tomo14MultiExecStateESaIS2_EE9push_backERKS2_-0x4
    27a5:	mov    0x190(%r13),%rax
    27ac:	mov    (%rax),%eax
    27ae:	shl    $0x7,%rax
    27b2:	add    0x188(%r13),%rax
    27b9:	lock incq 0x1a8c8(%rax)
    27c1:	cmpb   $0x0,-0x4f0(%rbp)
    27c8:	jne    2866 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2866>
    27ce:	mov    0x190(%r13),%r14
    27d5:	mov    0x868(%r13),%edi
    27dc:	mov    (%r14),%eax
    27df:	test   %edi,%edi
    27e1:	je     18d6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x18d6>
    27e7:	mov    %eax,%edx
    27e9:	mov    $0x1,%ebx
    27ee:	xor    %r12d,%r12d
    27f1:	shr    $0x6,%edx
    27f4:	shlx   %rax,%rbx,%rbx
    27f9:	and    $0x1,%edx
    27fc:	and    $0x3f,%eax
    27ff:	lea    0x2b8(,%rdx,8),%r15
    2807:	mov    0x188(%r13),%rcx
    280e:	mov    0x668(%r13,%r12,4),%edx
    2816:	mov    0x103e0(%rcx),%rcx
    281d:	movb   $0x0,0x5e8(%r13,%rdx,1)
    2826:	mov    (%rcx,%rdx,8),%rdx
    282a:	lea    (%rdx,%r15,1),%rcx
    282e:	mov    (%rcx),%rsi
    2831:	test   %rsi,%rbx
    2834:	jne    2855 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2855>
    2836:	lock bts %rax,(%rcx)
    283b:	jb     2855 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2855>
    283d:	mov    0x48(%rdx),%rcx
    2841:	mov    0x8(%rdx),%rsi
    2845:	test   %rsi,%rsi
    2848:	je     2855 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2855>
    284a:	movzbl 0x4040(%rcx),%edx
    2851:	test   %dl,%dl
    2853:	jne    2887 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2887>
    2855:	inc    %r12
    2858:	cmp    0x868(%r13),%r12d
    285f:	jb     2807 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2807>
    2861:	jmp    18d6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x18d6>
    2866:	mov    0x190(%r13),%rax
    286d:	mov    (%rax),%eax
    286f:	shl    $0x7,%rax
    2873:	add    0x188(%r13),%rax
    287a:	lock incq 0x1a8f8(%rax)
    2882:	jmp    27ce <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x27ce>
    2887:	lea    0xac8(%r13),%rdi
    288e:	movabs $0x500000000000000,%rdx
    2898:	mov    %rax,-0x4b0(%rbp)
    289f:	call   28a4 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x28a4>
			28a0: R_X86_64_PC32	.text+0xd0fc
    28a4:	mov    -0x4b0(%rbp),%rax
    28ab:	incq   0x438(%r14)
    28b2:	jmp    2855 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2855>
    28b4:	lea    0x8(%rbx),%r14
    28b8:	mov    %r14,%rdi
    28bb:	call   28c0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x28c0>
			28bc: R_X86_64_PLT32	_Znwm-0x4
    28c0:	mov    0x1978(%r13),%r15
    28c7:	mov    0x1980(%r13),%rdx
    28ce:	mov    %rax,%r12
    28d1:	sub    %r15,%rdx
    28d4:	test   %rdx,%rdx
    28d7:	jg     2937 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2937>
    28d9:	test   %r15,%r15
    28dc:	jne    2923 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2923>
    28de:	add    %r12,%rbx
    28e1:	vmovq  %r12,%xmm3
    28e6:	add    %r14,%r12
    28e9:	vpinsrq $0x1,%rbx,%xmm3,%xmm0
    28ef:	mov    %r12,0x1988(%r13)
    28f6:	vmovdqu %xmm0,0x1978(%r13)
    28ff:	jmp    206e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x206e>
    2904:	mov    -0x38(%rbp),%rax
    2908:	sub    %fs:0x28,%rax
    2911:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    2917:	lea    0x0(%rip),%rdi        # 291e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x291e>
			291a: R_X86_64_PC32	.LC116-0x4
    291e:	call   2923 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2923>
			291f: R_X86_64_PLT32	_ZSt20__throw_length_errorPKc-0x4
    2923:	mov    0x1988(%r13),%rsi
    292a:	sub    %r15,%rsi
    292d:	mov    %r15,%rdi
    2930:	call   2935 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2935>
			2931: R_X86_64_PLT32	_ZdlPvm-0x4
    2935:	jmp    28de <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x28de>
    2937:	mov    %r15,%rsi
    293a:	mov    %rax,%rdi
    293d:	call   2942 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2942>
			293e: R_X86_64_PLT32	memmove-0x4
    2942:	mov    0x1988(%r13),%rsi
    2949:	sub    %r15,%rsi
    294c:	jmp    292d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x292d>
    294e:	mov    %rax,%rdx
    2951:	mov    %r12,%rsi
    2954:	call   2959 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2959>
			2955: R_X86_64_PLT32	memmove-0x4
    2959:	mov    %r14,%rsi
    295c:	mov    %r12,%rdi
    295f:	sub    %r12,%rsi
    2962:	call   2967 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2967>
			2963: R_X86_64_PLT32	_ZdlPvm-0x4
    2967:	jmp    1e01 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1e01>
    296c:	mov    -0x4b8(%rbp),%rax
    2973:	cmpq   $0x0,0x1b0(%rax)
    297b:	jne    1ce5 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ce5>
    2981:	jmp    1eeb <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1eeb>
    2986:	mov    -0x38(%rbp),%rax
    298a:	sub    %fs:0x28,%rax
    2993:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    2999:	call   299e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x299e>
			299a: R_X86_64_PLT32	_ZSt17__throw_bad_allocv-0x4
    299e:	mov    -0x38(%rbp),%rax
    29a2:	sub    %fs:0x28,%rax
    29ab:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    29b1:	lea    0x0(%rip),%rdi        # 29b8 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x29b8>
			29b4: R_X86_64_PC32	.LC156-0x4
    29b8:	call   29bd <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x29bd>
			29b9: R_X86_64_PLT32	_ZSt20__throw_length_errorPKc-0x4
    29bd:	nopl   (%rax)
    29c0:	mov    -0x508(%rbp),%rax
    29c7:	movzbl (%rax),%eax
    29ca:	mov    %al,0x10(%r12)
    29cf:	jmp    24ef <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x24ef>
    29d4:	mov    -0x4b8(%rbp),%rax
    29db:	mov    0x78(%rax),%rdi
    29df:	mov    0x80(%rax),%r12
    29e6:	mov    %rdi,%rbx
    29e9:	cmp    %rdi,%r12
    29ec:	je     2a1b <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2a1b>
    29ee:	mov    (%rbx),%rdi
    29f1:	lea    0x10(%rbx),%rax
    29f5:	cmp    %rax,%rdi
    29f8:	je     2a07 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2a07>
    29fa:	mov    0x10(%rbx),%rax
    29fe:	lea    0x1(%rax),%rsi
    2a02:	call   2a07 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2a07>
			2a03: R_X86_64_PLT32	_ZdlPvm-0x4
    2a07:	add    $0x30,%rbx
    2a0b:	cmp    %rbx,%r12
    2a0e:	jne    29ee <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x29ee>
    2a10:	mov    -0x4b8(%rbp),%rax
    2a17:	mov    0x78(%rax),%rdi
    2a1b:	test   %rdi,%rdi
    2a1e:	je     2a40 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2a40>
    2a20:	mov    -0x4b8(%rbp),%rax
    2a27:	mov    0x88(%rax),%rax
    2a2e:	mov    %rax,%rsi
    2a31:	mov    %rax,-0x500(%rbp)
    2a38:	sub    %rdi,%rsi
    2a3b:	call   2a40 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2a40>
			2a3c: R_X86_64_PLT32	_ZdlPvm-0x4
    2a40:	mov    -0x4e0(%rbp),%rbx
    2a47:	mov    -0x4b8(%rbp),%rax
    2a4e:	add    %r14,%rbx
    2a51:	mov    %r14,0x78(%rax)
    2a55:	mov    %rbx,0x88(%rax)
    2a5c:	jmp    1c94 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1c94>
    2a61:	mov    -0x38(%rbp),%rax
    2a65:	sub    %fs:0x28,%rax
    2a6e:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    2a74:	call   2a79 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2a79>
			2a75: R_X86_64_PLT32	_ZSt28__throw_bad_array_new_lengthv-0x4
    2a79:	mov    -0x38(%rbp),%rax
    2a7d:	sub    %fs:0x28,%rax
    2a86:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    2a8c:	call   2a91 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2a91>
			2a8d: R_X86_64_PLT32	_ZSt17__throw_bad_allocv-0x4
    2a91:	mov    -0x38(%rbp),%rax
    2a95:	sub    %fs:0x28,%rax
    2a9e:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    2aa4:	lea    0x0(%rip),%rdi        # 2aab <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2aab>
			2aa7: R_X86_64_PC32	.LC156-0x4
    2aab:	call   2ab0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2ab0>
			2aac: R_X86_64_PLT32	_ZSt20__throw_length_errorPKc-0x4
    2ab0:	endbr64
    2ab4:	mov    %rax,%rdi
    2ab7:	jmp    2ac2 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2ac2>
    2ab9:	endbr64
    2abd:	mov    %rax,%rdi
    2ac0:	jmp    2ae4 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2ae4>
    2ac2:	vzeroupper
    2ac5:	call   2aca <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2aca>
			2ac6: R_X86_64_PLT32	__cxa_begin_catch-0x4
    2aca:	mov    -0x508(%rbp),%rbx
    2ad1:	cmp    %r12,%rbx
    2ad4:	je     2b02 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b02>
    2ad6:	mov    %rbx,%rdi
    2ad9:	add    $0x30,%rbx
    2add:	call   2ae2 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2ae2>
			2ade: R_X86_64_PLT32	_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv-0x4
    2ae2:	jmp    2ad1 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2ad1>
    2ae4:	vzeroupper
    2ae7:	mov    %r14,%rbx
    2aea:	call   2aef <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2aef>
			2aeb: R_X86_64_PLT32	__cxa_begin_catch-0x4
    2aef:	cmp    %rbx,%r12
    2af2:	je     2b1a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b1a>
    2af4:	mov    %rbx,%rdi
    2af7:	add    $0x30,%rbx
    2afb:	call   2b00 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b00>
			2afc: R_X86_64_PLT32	_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv-0x4
    2b00:	jmp    2aef <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2aef>
    2b02:	mov    -0x38(%rbp),%rax
    2b06:	sub    %fs:0x28,%rax
    2b0f:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    2b15:	call   2b1a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b1a>
			2b16: R_X86_64_PLT32	__cxa_rethrow-0x4
    2b1a:	mov    -0x38(%rbp),%rax
    2b1e:	sub    %fs:0x28,%rax
    2b27:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    2b2d:	call   2b32 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b32>
			2b2e: R_X86_64_PLT32	__cxa_rethrow-0x4
    2b32:	endbr64
    2b36:	mov    %rax,%rbx
    2b39:	mov    %rdx,%r12
    2b3c:	jmp    267f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x267f>
    2b41:	endbr64
    2b45:	mov    %rax,%rbx
    2b48:	jmp    2b80 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b80>
    2b4a:	mov    -0x458(%rbp),%rdi
    2b51:	test   %rdi,%rdi
    2b54:	jne    2c90 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2c90>
    2b5a:	vzeroupper
    2b5d:	mov    %r12,%rdi
    2b60:	call   2b65 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b65>
			2b61: R_X86_64_PLT32	_ZNSt16_Sp_counted_baseILN9__gnu_cxx12_Lock_policyE2EE10_M_releaseEv-0x4
    2b65:	mov    -0x38(%rbp),%rax
    2b69:	sub    %fs:0x28,%rax
    2b72:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    2b78:	mov    %rbx,%rdi
    2b7b:	call   2b80 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b80>
			2b7c: R_X86_64_PLT32	_Unwind_Resume-0x4
    2b80:	vzeroupper
    2b83:	call   2b88 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b88>
			2b84: R_X86_64_PLT32	__cxa_end_catch-0x4
    2b88:	mov    %rbx,%rdi
    2b8b:	call   2b90 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b90>
			2b8c: R_X86_64_PLT32	__cxa_begin_catch-0x4
    2b90:	mov    -0x4e0(%rbp),%rsi
    2b97:	mov    %r14,%rdi
    2b9a:	call   2b9f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b9f>
			2b9b: R_X86_64_PLT32	_ZdlPvm-0x4
    2b9f:	mov    -0x38(%rbp),%rax
    2ba3:	sub    %fs:0x28,%rax
    2bac:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    2bb2:	call   2bb7 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2bb7>
			2bb3: R_X86_64_PLT32	__cxa_rethrow-0x4
    2bb7:	endbr64
    2bbb:	mov    %rax,%rbx
    2bbe:	jmp    2bcc <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2bcc>
    2bc0:	endbr64
    2bc4:	mov    %rax,%rbx
    2bc7:	mov    %rdx,%r12
    2bca:	jmp    2bd6 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2bd6>
    2bcc:	vzeroupper
    2bcf:	call   2bd4 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2bd4>
			2bd0: R_X86_64_PLT32	__cxa_end_catch-0x4
    2bd4:	jmp    2b65 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b65>
    2bd6:	vzeroupper
    2bd9:	call   2bde <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2bde>
			2bda: R_X86_64_PLT32	__cxa_end_catch-0x4
    2bde:	jmp    2687 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2687>
    2be3:	endbr64
    2be7:	mov    %rax,%rdi
    2bea:	mov    %rdx,%rax
    2bed:	jmp    1a9a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1a9a>
    2bf2:	endbr64
    2bf6:	mov    %rax,%rbx
    2bf9:	mov    %rdx,%r12
    2bfc:	mov    %r14,%rdi
    2bff:	vzeroupper
    2c02:	call   2c07 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2c07>
			2c03: R_X86_64_PLT32	_ZNSt6vectorIjSaIjEED1Ev-0x4
    2c07:	jmp    2687 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2687>
    2c0c:	vzeroupper
    2c0f:	call   2c14 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2c14>
			2c10: R_X86_64_PLT32	__cxa_begin_catch-0x4
    2c14:	mov    -0x4b8(%rbp),%rdi
    2c1b:	call   2c20 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2c20>
			2c1c: R_X86_64_PC32	.text+0x3476c
    2c20:	mov    -0x4b0(%rbp),%rdi
    2c27:	call   2c2c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2c2c>
			2c28: R_X86_64_PC32	.text+0xc0c
    2c2c:	call   2c31 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2c31>
			2c2d: R_X86_64_PLT32	__cxa_end_catch-0x4
    2c31:	jmp    7f1 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x7f1>
    2c36:	vzeroupper
    2c39:	call   2c3e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2c3e>
			2c3a: R_X86_64_PLT32	_Unwind_Resume-0x4
    2c3e:	endbr64
    2c42:	jmp    2bbb <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2bbb>
    2c47:	endbr64
    2c4b:	mov    %rax,%rbx
    2c4e:	jmp    2b4a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b4a>
    2c53:	mov    $0x8,%edi
    2c58:	call   2c5d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2c5d>
			2c59: R_X86_64_PLT32	__cxa_allocate_exception-0x4
    2c5d:	mov    %rax,%rdi
    2c60:	lea    0x0(%rip),%rax        # 2c67 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2c67>
			2c63: R_X86_64_PC32	_ZTVSt9bad_alloc+0xc
    2c67:	mov    %rax,(%rdi)
    2c6a:	mov    -0x38(%rbp),%rax
    2c6e:	sub    %fs:0x28,%rax
    2c77:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    2c7d:	mov    0x0(%rip),%rdx        # 2c84 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2c84>
			2c80: R_X86_64_REX_GOTPCRELX	_ZNSt9bad_allocD1Ev-0x4
    2c84:	lea    0x0(%rip),%rsi        # 2c8b <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2c8b>
			2c87: R_X86_64_PC32	_ZTISt9bad_alloc-0x4
    2c8b:	call   2c90 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2c90>
			2c8c: R_X86_64_PLT32	__cxa_throw-0x4
    2c90:	vzeroupper
    2c93:	call   2c98 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2c98>
			2c94: R_X86_64_PLT32	_ZNSt16_Sp_counted_baseILN9__gnu_cxx12_Lock_policyE2EE10_M_releaseEv-0x4
    2c98:	jmp    2b5d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b5d>
    2c9d:	endbr64
    2ca1:	mov    %rax,%rbx
    2ca4:	mov    %rdx,%r12
    2ca7:	jmp    2687 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2687>
    2cac:	endbr64
    2cb0:	mov    %rax,%rbx
    2cb3:	mov    %rdx,%r15
    2cb6:	jmp    2cd0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2cd0>
    2cb8:	endbr64
    2cbc:	mov    %rax,%rbx
    2cbf:	mov    %rdx,%r15
    2cc2:	jmp    2cf5 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2cf5>
    2cc4:	endbr64
    2cc8:	mov    %rax,%rbx
    2ccb:	mov    %rdx,%r15
    2cce:	jmp    2d04 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2d04>
    2cd0:	dec    %r15
    2cd3:	jne    2d31 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2d31>
    2cd5:	mov    %rax,%rdi
    2cd8:	vzeroupper
    2cdb:	call   2ce0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2ce0>
			2cdc: R_X86_64_PLT32	__cxa_begin_catch-0x4
    2ce0:	mov    %r14,%rdi
    2ce3:	call   2ce8 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2ce8>
			2ce4: R_X86_64_PC32	.text+0xc0c
    2ce8:	vzeroupper
    2ceb:	call   2cf0 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2cf0>
			2cec: R_X86_64_PLT32	__cxa_end_catch-0x4
    2cf0:	jmp    7f1 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x7f1>
    2cf5:	mov    -0x4b0(%rbp),%rdi
    2cfc:	vzeroupper
    2cff:	call   2d04 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2d04>
			2d00: R_X86_64_PLT32	_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv-0x4
    2d04:	dec    %r15
    2d07:	jne    2d34 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2d34>
    2d09:	mov    %rbx,%rdi
    2d0c:	vzeroupper
    2d0f:	call   2d14 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2d14>
			2d10: R_X86_64_PLT32	__cxa_begin_catch-0x4
    2d14:	mov    %r14,%rdi
    2d17:	call   2d1c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2d1c>
			2d18: R_X86_64_PC32	.text+0xc0c
    2d1c:	vzeroupper
    2d1f:	call   2d24 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2d24>
			2d20: R_X86_64_PLT32	__cxa_end_catch-0x4
    2d24:	mov    %r12,%rdi
    2d27:	call   2d2c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2d2c>
			2d28: R_X86_64_PLT32	_ZNSt16_Sp_counted_baseILN9__gnu_cxx12_Lock_policyE2EE10_M_releaseEv-0x4
    2d2c:	jmp    7f1 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x7f1>
    2d31:	xor    %r12d,%r12d
    2d34:	test   %r12,%r12
    2d37:	jne    2b5a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b5a>
    2d3d:	vzeroupper
    2d40:	jmp    2b65 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2b65>
    2d45:	endbr64
    2d49:	mov    %rax,%rdi
    2d4c:	jmp    2d5a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2d5a>
    2d4e:	endbr64
    2d52:	mov    %rax,%rdi
    2d55:	mov    %rdx,%rax
    2d58:	jmp    2d7c <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2d7c>
    2d5a:	vzeroupper
    2d5d:	call   2d62 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2d62>
			2d5e: R_X86_64_PLT32	__cxa_begin_catch-0x4
    2d62:	mov    -0x4e0(%rbp),%r12
    2d69:	cmp    %r12,%rbx
    2d6c:	je     2da2 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2da2>
    2d6e:	mov    %r12,%rdi
    2d71:	add    $0x20,%r12
    2d75:	call   2d7a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2d7a>
			2d76: R_X86_64_PLT32	_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv-0x4
    2d7a:	jmp    2d69 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2d69>
    2d7c:	dec    %rax
    2d7f:	jne    1aa3 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1aa3>
    2d85:	vzeroupper
    2d88:	call   2d8d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2d8d>
			2d89: R_X86_64_PLT32	__cxa_begin_catch-0x4
    2d8d:	mov    %r12,%rsi
    2d90:	mov    %rbx,%rdi
    2d93:	call   2d98 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2d98>
			2d94: R_X86_64_PLT32	_ZN4tomo6Server21txn_exclusive_releaseEPKv-0x4
    2d98:	call   2d9d <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2d9d>
			2d99: R_X86_64_PLT32	__cxa_end_catch-0x4
    2d9d:	jmp    bcb <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0xbcb>
    2da2:	mov    -0x38(%rbp),%rax
    2da6:	sub    %fs:0x28,%rax
    2daf:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    2db5:	call   2dba <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2dba>
			2db6: R_X86_64_PLT32	__cxa_rethrow-0x4
    2dba:	mov    $0x8,%edi
    2dbf:	call   2dc4 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2dc4>
			2dc0: R_X86_64_PLT32	__cxa_allocate_exception-0x4
    2dc4:	mov    %rax,%rdi
    2dc7:	lea    0x0(%rip),%rax        # 2dce <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2dce>
			2dca: R_X86_64_PC32	_ZTVSt9bad_alloc+0xc
    2dce:	mov    %rax,(%rdi)
    2dd1:	mov    -0x38(%rbp),%rax
    2dd5:	sub    %fs:0x28,%rax
    2dde:	jne    1ab9 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x1ab9>
    2de4:	mov    0x0(%rip),%rdx        # 2deb <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2deb>
			2de7: R_X86_64_REX_GOTPCRELX	_ZNSt9bad_allocD1Ev-0x4
    2deb:	lea    0x0(%rip),%rsi        # 2df2 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2df2>
			2dee: R_X86_64_PC32	_ZTISt9bad_alloc-0x4
    2df2:	call   2df7 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2df7>
			2df3: R_X86_64_PLT32	__cxa_throw-0x4
    2df7:	endbr64
    2dfb:	mov    %rax,%rbx
    2dfe:	mov    %rdx,%r15
    2e01:	jmp    2e0f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2e0f>
    2e03:	endbr64
    2e07:	mov    %rax,%rbx
    2e0a:	mov    %rdx,%r12
    2e0d:	jmp    2e2f <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2e2f>
    2e0f:	mov    -0x4b8(%rbp),%rdi
    2e16:	vzeroupper
    2e19:	call   2e1e <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2e1e>
			2e1a: R_X86_64_PLT32	_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv-0x4
    2e1e:	mov    -0x4b0(%rbp),%rdi
    2e25:	call   2e2a <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2e2a>
			2e26: R_X86_64_PLT32	_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv-0x4
    2e2a:	jmp    2d04 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2d04>
    2e2f:	vzeroupper
    2e32:	call   2e37 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2e37>
			2e33: R_X86_64_PLT32	__cxa_end_catch-0x4
    2e37:	lea    0x8(%r15),%rdi
    2e3b:	call   2e40 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2e40>
			2e3c: R_X86_64_PLT32	_ZNSt12_Vector_baseINSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEESaIS5_EED2Ev-0x4
    2e40:	lea    -0x480(%rbp),%rax
    2e47:	mov    %rax,-0x4e8(%rbp)
    2e4e:	jmp    2687 <_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE+0x2687>
