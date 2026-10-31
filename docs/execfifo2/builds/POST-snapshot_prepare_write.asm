
build/execfifo2/POST:     file format elf64-x86-64


Disassembly of section .init:

Disassembly of section .plt:

Disassembly of section .plt.got:

Disassembly of section .plt.sec:

Disassembly of section .text:

0000000000496530 <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE>:
  496530:	endbr64
  496534:	push   %r15
  496536:	push   %r14
  496538:	push   %r13
  49653a:	mov    %rsi,%r14
  49653d:	push   %r12
  49653f:	push   %rbp
  496540:	push   %rbx
  496541:	mov    %rdi,%rbp
  496544:	sub    $0x58,%rsp
  496548:	mov    %rdx,%r15
  49654b:	mov    %rcx,%r8
  49654e:	mov    %fs:0x28,%rax
  496557:	mov    %rax,0x48(%rsp)
  49655c:	xor    %eax,%eax
  49655e:	cmpb   $0x0,0xf0(%rdi)
  496565:	movzbl 0x193(%rdi),%eax
  49656c:	jne    4966c0 <tomo_multidb2_pad_81749+0x8f>
  496572:	test   %al,%al
  496574:	je     4966b3 <tomo_multidb2_pad_81749+0x82>
  49657a:	cmpb   $0x0,0x194(%rdi)
  496581:	jne    4966e0 <tomo_multidb2_pad_81749+0xaf>
  496587:	mov    0xd0(%rdi),%rcx
  49658e:	test   %rcx,%rcx
  496591:	je     496708 <tomo_multidb2_pad_81749+0xd7>
  496597:	mov    %rsi,%rax
  49659a:	mov    %rsi,%rbx
  49659d:	xor    %r12d,%r12d
  4965a0:	movabs $0xffffffffffff,%r13
  4965aa:	shr    $0x31,%rax
  4965ae:	shr    $0x21,%rbx
  4965b2:	mov    %rax,%r9
  4965b5:	xor    %rsi,%rbx
  4965b8:	movabs $0xff51afd7ed558ccd,%rax
  4965c2:	imul   %rax,%rbx
  4965c6:	mov    %rbx,%rax
  4965c9:	shr    $0x21,%rax
  4965cd:	xor    %rax,%rbx
  4965d0:	movabs $0xc4ceb9fe1a85ec53,%rax
  4965da:	imul   %rax,%rbx
  4965de:	mov    %rbx,%rax
  4965e1:	shr    $0x21,%rax
  4965e5:	xor    %rax,%rbx
  4965e8:	and    0xe8(%rdi),%ebx
  4965ee:	jmp    49660a <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE+0xda>
  4965f0:	mov    0xe8(%rbp),%eax
  4965f6:	inc    %r12d
  4965f9:	cmp    %r12d,0xe0(%rbp)
  496600:	jb     496708 <tomo_multidb2_pad_81749+0xd7>
  496606:	inc    %ebx
  496608:	and    %eax,%ebx
  49660a:	mov    %ebx,%eax
  49660c:	mov    (%rcx,%rax,8),%rax
  496610:	test   %rax,%rax
  496613:	je     496708 <tomo_multidb2_pad_81749+0xd7>
  496619:	mov    %rax,%rdx
  49661c:	and    %r13,%rdx
  49661f:	je     4965f0 <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE+0xc0>
  496621:	shr    $0x31,%rax
  496625:	cmp    %ax,%r9w
  496629:	jne    4965f0 <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE+0xc0>
  49662b:	movzbl 0x2(%rdx),%eax
  49662f:	test   $0x2,%al

0000000000496631 <tomo_multidb2_pad_81749>:
  496631:	jne    4967f0 <tomo_multidb2_pad_82288+0x79>
  496637:	movzbl 0x3(%rdx),%esi
  49663b:	lea    0x0(,%rax,8),%rax
  496643:	and    $0x8,%eax
  496646:	lea    0x8(%rdx,%rax,1),%rdi
  49664b:	xor    %eax,%eax
  49664d:	vmovd  %esi,%xmm1
  496651:	vpinsrd $0x1,%eax,%xmm1,%xmm0
  496657:	vmovq  %xmm0,%rax
  49665c:	cmp    %rax,%r8
  49665f:	jne    4965f0 <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE+0xc0>
  496661:	cmp    $0x7,%esi
  496664:	jbe    496b3b <tomo_multidb2_pad_82288+0x3c4>
  49666a:	mov    %esi,%edx
  49666c:	cmp    $0x20,%esi
  49666f:	ja     496b58 <tomo_multidb2_pad_82288+0x3e1>
  496675:	mov    -0x8(%rdi,%rdx,1),%rax
  49667a:	mov    (%rdi),%r10
  49667d:	xor    -0x8(%rdx,%r15,1),%rax
  496682:	xor    (%r15),%r10
  496685:	or     %r10,%rax
  496688:	cmp    $0x10,%esi
  49668b:	jbe    4966a5 <tomo_multidb2_pad_81749+0x74>
  49668d:	mov    -0x10(%rdi,%rdx,1),%rsi
  496692:	xor    -0x10(%rdx,%r15,1),%rsi
  496697:	mov    0x8(%rdi),%rdx
  49669b:	xor    0x8(%r15),%rdx
  49669f:	or     %rdx,%rsi
  4966a2:	or     %rsi,%rax
  4966a5:	test   %rax,%rax
  4966a8:	sete   %al
  4966ab:	test   %al,%al
  4966ad:	je     4965f0 <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE+0xc0>
  4966b3:	xor    %eax,%eax
  4966b5:	jmp    4966e5 <tomo_multidb2_pad_81749+0xb4>
  4966b7:	nopw   0x0(%rax,%rax,1)
  4966c0:	test   %al,%al
  4966c2:	je     4966b3 <tomo_multidb2_pad_81749+0x82>
  4966c4:	cmpb   $0x0,0x194(%rdi)
  4966cb:	je     496973 <tomo_multidb2_pad_82288+0x1fc>
  4966d1:	data16 cs nopw 0x0(%rax,%rax,1)
  4966dc:	nopl   0x0(%rax)
  4966e0:	mov    $0x2,%eax
  4966e5:	mov    0x48(%rsp),%rdx
  4966ea:	sub    %fs:0x28,%rdx
  4966f3:	jne    496c83 <tomo_multidb2_pad_82288+0x50c>
  4966f9:	add    $0x58,%rsp
  4966fd:	pop    %rbx
  4966fe:	pop    %rbp
  4966ff:	pop    %r12
  496701:	pop    %r13
  496703:	pop    %r14
  496705:	pop    %r15
  496707:	ret
  496708:	mov    0xd8(%rbp),%rcx
  49670f:	test   %rcx,%rcx
  496712:	je     4966b3 <tomo_multidb2_pad_81749+0x82>
  496714:	mov    %r14,%rax
  496717:	mov    %r14,%r12
  49671a:	xor    %ebx,%ebx
  49671c:	movabs $0xffffffffffff,%r10
  496726:	shr    $0x31,%rax
  49672a:	shr    $0x21,%r12
  49672e:	mov    %rax,%r9
  496731:	xor    %r14,%r12
  496734:	movabs $0xff51afd7ed558ccd,%rax
  49673e:	imul   %rax,%r12
  496742:	mov    %r12,%rax
  496745:	shr    $0x21,%rax
  496749:	xor    %rax,%r12
  49674c:	movabs $0xc4ceb9fe1a85ec53,%rax
  496756:	imul   %rax,%r12
  49675a:	mov    %r12,%rax
  49675d:	shr    $0x21,%rax
  496761:	xor    %rax,%r12
  496764:	and    0xec(%rbp),%r12d
  49676b:	jmp    4967c6 <tomo_multidb2_pad_82288+0x4f>
  49676d:	nopl   (%rax)
  496770:	movzbl 0x2(%r14),%eax
  496775:	test   $0x2,%al

0000000000496777 <tomo_multidb2_pad_82288>:
  496777:	jne    496860 <tomo_multidb2_pad_82288+0xe9>
  49677d:	movzbl 0x3(%r14),%edx
  496782:	lea    0x0(,%rax,8),%rax
  49678a:	and    $0x8,%eax
  49678d:	lea    0x8(%r14,%rax,1),%rdi
  496792:	xor    %eax,%eax
  496794:	vmovd  %edx,%xmm3
  496798:	vpinsrd $0x1,%eax,%xmm3,%xmm2
  49679e:	vmovq  %xmm2,%rax
  4967a3:	cmp    %rax,%r8
  4967a6:	je     4968b9 <tomo_multidb2_pad_82288+0x142>
  4967ac:	mov    0xec(%rbp),%eax
  4967b2:	inc    %ebx
  4967b4:	cmp    %ebx,0xe4(%rbp)
  4967ba:	jb     4966b3 <tomo_multidb2_pad_81749+0x82>
  4967c0:	inc    %r12d
  4967c3:	and    %eax,%r12d
  4967c6:	mov    %r12d,%r13d
  4967c9:	shl    $0x3,%r13
  4967cd:	mov    (%rcx,%r13,1),%rax
  4967d1:	test   %rax,%rax
  4967d4:	je     4966b3 <tomo_multidb2_pad_81749+0x82>
  4967da:	mov    %rax,%r14
  4967dd:	and    %r10,%r14
  4967e0:	je     4967ac <tomo_multidb2_pad_82288+0x35>
  4967e2:	shr    $0x31,%rax
  4967e6:	cmp    %ax,%r9w
  4967ea:	jne    4967ac <tomo_multidb2_pad_82288+0x35>
  4967ec:	jmp    496770 <tomo_multidb2_pad_81749+0x13f>
  4967ee:	xchg   %ax,%ax
  4967f0:	movzbl 0x2(%rdx),%esi
  4967f4:	xor    %eax,%eax
  4967f6:	and    $0x2,%esi
  4967f9:	je     496804 <tomo_multidb2_pad_82288+0x8d>
  4967fb:	movzbl 0x3(%rdx),%eax
  4967ff:	inc    %eax
  496801:	movzbl %al,%eax
  496804:	movzbl 0x2(%rdx),%esi
  496808:	and    $0x2,%esi
  49680b:	jne    496850 <tomo_multidb2_pad_82288+0xd9>
  49680d:	movzbl 0x3(%rdx),%esi
  496811:	movzbl 0x2(%rdx),%edi
  496815:	movzbl 0x2(%rdx),%r11d
  49681a:	shr    $1,%dil
  49681d:	lea    0x0(,%rdi,4),%r10
  496825:	lea    0x0(,%r11,8),%rdi
  49682d:	and    $0x4,%r10d
  496831:	and    $0x8,%edi
  496834:	lea    0x8(%r10,%rdi,1),%rdi
  496839:	add    %rdx,%rdi
  49683c:	jmp    49664d <tomo_multidb2_pad_81749+0x1c>
  496841:	data16 cs nopw 0x0(%rax,%rax,1)
  49684c:	nopl   0x0(%rax)
  496850:	mov    0x8(%rdx),%esi
  496853:	jmp    496811 <tomo_multidb2_pad_82288+0x9a>
  496855:	data16 cs nopw 0x0(%rax,%rax,1)
  496860:	movzbl 0x2(%r14),%edx
  496865:	xor    %eax,%eax
  496867:	and    $0x2,%edx
  49686a:	je     496876 <tomo_multidb2_pad_82288+0xff>
  49686c:	movzbl 0x3(%r14),%eax
  496871:	inc    %eax
  496873:	movzbl %al,%eax
  496876:	movzbl 0x2(%r14),%edx
  49687b:	and    $0x2,%edx
  49687e:	jne    496b0d <tomo_multidb2_pad_82288+0x396>
  496884:	movzbl 0x3(%r14),%edx
  496889:	movzbl 0x2(%r14),%esi
  49688e:	movzbl 0x2(%r14),%r11d
  496893:	shr    $1,%sil
  496896:	lea    0x0(,%rsi,4),%rdi
  49689e:	lea    0x0(,%r11,8),%rsi
  4968a6:	and    $0x4,%edi
  4968a9:	and    $0x8,%esi
  4968ac:	lea    0x8(%rdi,%rsi,1),%rdi
  4968b1:	add    %r14,%rdi
  4968b4:	jmp    496794 <tomo_multidb2_pad_82288+0x1d>
  4968b9:	cmp    $0x7,%edx
  4968bc:	jbe    496bd0 <tomo_multidb2_pad_82288+0x459>
  4968c2:	mov    %edx,%esi
  4968c4:	cmp    $0x20,%edx
  4968c7:	ja     496bed <tomo_multidb2_pad_82288+0x476>
  4968cd:	mov    -0x8(%rdi,%rsi,1),%r11
  4968d2:	mov    (%rdi),%rax
  4968d5:	xor    -0x8(%rsi,%r15,1),%r11
  4968da:	xor    (%r15),%rax
  4968dd:	or     %r11,%rax
  4968e0:	cmp    $0x10,%edx
  4968e3:	jbe    4968fd <tomo_multidb2_pad_82288+0x186>
  4968e5:	mov    -0x10(%rdi,%rsi,1),%rdx
  4968ea:	xor    -0x10(%rsi,%r15,1),%rdx
  4968ef:	mov    0x8(%rdi),%rsi
  4968f3:	xor    0x8(%r15),%rsi
  4968f7:	or     %rsi,%rdx
  4968fa:	or     %rdx,%rax
  4968fd:	test   %rax,%rax
  496900:	sete   %al
  496903:	test   %al,%al
  496905:	je     4967ac <tomo_multidb2_pad_82288+0x35>
  49690b:	cmp    0x180(%rbp),%r12d
  496912:	jb     4966b3 <tomo_multidb2_pad_81749+0x82>
  496918:	testb  $0x1,0x6(%rcx,%r13,1)
  49691e:	jne    4966b3 <tomo_multidb2_pad_81749+0x82>
  496924:	mov    0x128(%rbp),%rdx
  49692b:	movzbl 0x2(%r14),%eax
  496930:	test   $0x1,%al
  496932:	je     496b16 <tomo_multidb2_pad_82288+0x39f>
  496938:	movzbl 0x2(%r14),%eax
  49693d:	test   $0x1,%al
  49693f:	je     496b16 <tomo_multidb2_pad_82288+0x39f>
  496945:	movzbl 0x2(%r14),%eax
  49694a:	shr    $1,%al
  49694c:	and    $0x1,%eax
  49694f:	mov    0x8(%r14,%rax,4),%rax
  496954:	test   %rax,%rax
  496957:	js     496b16 <tomo_multidb2_pad_82288+0x39f>
  49695d:	cmp    %rax,%rdx
  496960:	jle    496b16 <tomo_multidb2_pad_82288+0x39f>
  496966:	btsq   $0x30,(%rcx,%r13,1)
  49696c:	xor    %eax,%eax
  49696e:	jmp    4966e5 <tomo_multidb2_pad_81749+0xb4>
  496973:	mov    %rdx,%rcx
  496976:	mov    %rsi,%rdx
  496979:	xor    %esi,%esi
  49697b:	mov    %r8,0x8(%rsp)
  496980:	call   4962b0 <_ZNK4tomo9FlatStore7find_inEimNS_5SliceE>
  496985:	mov    0x8(%rsp),%r8
  49698a:	test   %rax,%rax
  49698d:	jne    4966b3 <tomo_multidb2_pad_81749+0x82>
  496993:	mov    0xd8(%rbp),%rax
  49699a:	mov    %r15,0x20(%rsp)
  49699f:	mov    %r8,0x28(%rsp)
  4969a4:	test   %rax,%rax
  4969a7:	je     4966b3 <tomo_multidb2_pad_81749+0x82>
  4969ad:	mov    %r14,%rbx
  4969b0:	movabs $0xff51afd7ed558ccd,%rdx
  4969ba:	mov    %r14,%rsi
  4969bd:	xor    %r13d,%r13d
  4969c0:	shr    $0x21,%rbx
  4969c4:	xor    %r14,%rbx
  4969c7:	movabs $0xffffffffffff,%r14
  4969d1:	imul   %rdx,%rbx
  4969d5:	shr    $0x31,%rsi
  4969d9:	mov    %rbx,%rdx
  4969dc:	mov    %rsi,%r15
  4969df:	shr    $0x21,%rdx
  4969e3:	xor    %rdx,%rbx
  4969e6:	movabs $0xc4ceb9fe1a85ec53,%rdx
  4969f0:	imul   %rdx,%rbx
  4969f4:	mov    %rbx,%rdx
  4969f7:	shr    $0x21,%rdx
  4969fb:	xor    %rdx,%rbx
  4969fe:	and    0xec(%rbp),%ebx
  496a04:	jmp    496a2f <tomo_multidb2_pad_82288+0x2b8>
  496a06:	cs nopw 0x0(%rax,%rax,1)
  496a10:	inc    %ebx
  496a12:	inc    %r13d
  496a15:	and    0xec(%rbp),%ebx
  496a1b:	cmp    %r13d,0xe4(%rbp)
  496a22:	jb     4966b3 <tomo_multidb2_pad_81749+0x82>
  496a28:	mov    0xd8(%rbp),%rax
  496a2f:	mov    %ebx,%r12d
  496a32:	shl    $0x3,%r12
  496a36:	mov    (%rax,%r12,1),%rax
  496a3a:	test   %rax,%rax
  496a3d:	je     4966b3 <tomo_multidb2_pad_81749+0x82>
  496a43:	mov    %rax,%r8
  496a46:	and    %r14,%r8
  496a49:	je     496a10 <tomo_multidb2_pad_82288+0x299>
  496a4b:	shr    $0x31,%rax
  496a4f:	cmp    %ax,%r15w
  496a53:	jne    496a10 <tomo_multidb2_pad_82288+0x299>
  496a55:	mov    %r8,%rdi
  496a58:	mov    %r8,0x8(%rsp)
  496a5d:	call   490e60 <_ZNK4tomo5KvObj3keyEv>
  496a62:	lea    0x20(%rsp),%rsi
  496a67:	lea    0x30(%rsp),%rdi
  496a6c:	mov    %rax,0x30(%rsp)
  496a71:	mov    %rdx,0x38(%rsp)
  496a76:	call   48ff60 <_ZNK4tomo5Slice6key_eqERKS0_>
  496a7b:	mov    0x8(%rsp),%r8
  496a80:	test   %al,%al
  496a82:	je     496a10 <tomo_multidb2_pad_82288+0x299>
  496a84:	cmp    0x180(%rbp),%ebx
  496a8a:	jb     4966b3 <tomo_multidb2_pad_81749+0x82>
  496a90:	mov    0xd8(%rbp),%rcx
  496a97:	testb  $0x1,0x6(%rcx,%r12,1)
  496a9d:	jne    4966b3 <tomo_multidb2_pad_81749+0x82>
  496aa3:	mov    0x128(%rbp),%rdx
  496aaa:	movzbl 0x2(%r8),%eax
  496aaf:	test   $0x1,%al
  496ab1:	je     496ad9 <tomo_multidb2_pad_82288+0x362>
  496ab3:	movzbl 0x2(%r8),%eax
  496ab8:	test   $0x1,%al
  496aba:	je     496ad9 <tomo_multidb2_pad_82288+0x362>
  496abc:	movzbl 0x2(%r8),%eax
  496ac1:	shr    $1,%al
  496ac3:	and    $0x1,%eax
  496ac6:	mov    0x8(%r8,%rax,4),%rax
  496acb:	test   %rax,%rax
  496ace:	js     496ad9 <tomo_multidb2_pad_82288+0x362>
  496ad0:	cmp    %rax,%rdx
  496ad3:	jg     496c68 <tomo_multidb2_pad_82288+0x4f1>
  496ad9:	cmpb   $0x0,0x238(%rbp)
  496ae0:	jne    496b03 <tomo_multidb2_pad_82288+0x38c>
  496ae2:	mov    $0x1,%ecx
  496ae7:	mov    %ebx,%edx
  496ae9:	mov    %r8,%rsi
  496aec:	mov    %rbp,%rdi
  496aef:	call   495b40 <_ZN4tomo9FlatStore21snapshot_start_recordEPKNS_5KvObjEjb>
  496af4:	test   %al,%al
  496af6:	je     4966e0 <tomo_multidb2_pad_81749+0xaf>
  496afc:	incq   0x1b0(%rbp)
  496b03:	mov    $0x1,%eax
  496b08:	jmp    4966e5 <tomo_multidb2_pad_81749+0xb4>
  496b0d:	mov    0x8(%r14),%edx
  496b11:	jmp    496889 <tomo_multidb2_pad_82288+0x112>
  496b16:	cmpb   $0x0,0x238(%rbp)
  496b1d:	jne    496b03 <tomo_multidb2_pad_82288+0x38c>
  496b1f:	mov    $0x1,%ecx
  496b24:	mov    %r12d,%edx
  496b27:	mov    %r14,%rsi
  496b2a:	mov    %rbp,%rdi
  496b2d:	call   495b40 <_ZN4tomo9FlatStore21snapshot_start_recordEPKNS_5KvObjEjb>
  496b32:	test   %al,%al
  496b34:	jne    496afc <tomo_multidb2_pad_82288+0x385>
  496b36:	jmp    4966e0 <tomo_multidb2_pad_81749+0xaf>
  496b3b:	cmp    $0x3,%esi
  496b3e:	jbe    496b88 <tomo_multidb2_pad_82288+0x411>
  496b40:	mov    -0x4(%rdi,%rsi,1),%eax
  496b44:	mov    (%rdi),%edx
  496b46:	xor    -0x4(%rsi,%r15,1),%eax
  496b4b:	xor    (%r15),%edx
  496b4e:	or     %edx,%eax
  496b50:	sete   %al
  496b53:	jmp    4966ab <tomo_multidb2_pad_81749+0x7a>
  496b58:	mov    %r15,%rsi
  496b5b:	mov    %rcx,0x18(%rsp)
  496b60:	mov    %r8,0x10(%rsp)
  496b65:	mov    %r9d,0x8(%rsp)
  496b6a:	call   2c8a0 <memcmp@plt>
  496b6f:	mov    0x8(%rsp),%r9d
  496b74:	mov    0x10(%rsp),%r8
  496b79:	mov    0x18(%rsp),%rcx
  496b7e:	test   %eax,%eax
  496b80:	sete   %al
  496b83:	jmp    4966ab <tomo_multidb2_pad_81749+0x7a>
  496b88:	test   %esi,%esi
  496b8a:	je     4966b3 <tomo_multidb2_pad_81749+0x82>
  496b90:	movzbl (%r15),%eax
  496b94:	cmp    %al,(%rdi)
  496b96:	jne    4965f0 <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE+0xc0>
  496b9c:	mov    %esi,%eax
  496b9e:	shr    $1,%eax
  496ba0:	movzbl (%r15,%rax,1),%edx
  496ba5:	cmp    %dl,(%rdi,%rax,1)
  496ba8:	jne    4965f0 <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE+0xc0>
  496bae:	lea    -0x1(%rsi),%eax
  496bb1:	movzbl (%r15,%rax,1),%esi
  496bb6:	cmp    %sil,(%rdi,%rax,1)
  496bba:	jne    4965f0 <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE+0xc0>
  496bc0:	xor    %eax,%eax
  496bc2:	jmp    4966e5 <tomo_multidb2_pad_81749+0xb4>
  496bc7:	nopw   0x0(%rax,%rax,1)
  496bd0:	cmp    $0x3,%edx
  496bd3:	jbe    496c2a <tomo_multidb2_pad_82288+0x4b3>
  496bd5:	mov    -0x4(%rdi,%rdx,1),%eax
  496bd9:	xor    -0x4(%rdx,%r15,1),%eax
  496bde:	mov    (%rdi),%edx
  496be0:	xor    (%r15),%edx
  496be3:	or     %edx,%eax
  496be5:	sete   %al
  496be8:	jmp    496903 <tomo_multidb2_pad_82288+0x18c>
  496bed:	mov    %rsi,%rdx
  496bf0:	mov    %r15,%rsi
  496bf3:	mov    %rcx,0x18(%rsp)
  496bf8:	mov    %r8,0x10(%rsp)
  496bfd:	mov    %r9d,0x8(%rsp)
  496c02:	call   2c8a0 <memcmp@plt>
  496c07:	mov    0x8(%rsp),%r9d
  496c0c:	mov    0x10(%rsp),%r8
  496c11:	test   %eax,%eax
  496c13:	mov    0x18(%rsp),%rcx
  496c18:	movabs $0xffffffffffff,%r10
  496c22:	sete   %al
  496c25:	jmp    496903 <tomo_multidb2_pad_82288+0x18c>
  496c2a:	test   %edx,%edx
  496c2c:	je     49690b <tomo_multidb2_pad_82288+0x194>
  496c32:	movzbl (%r15),%eax
  496c36:	cmp    %al,(%rdi)
  496c38:	jne    4967ac <tomo_multidb2_pad_82288+0x35>
  496c3e:	mov    %edx,%eax
  496c40:	shr    $1,%eax
  496c42:	movzbl (%r15,%rax,1),%esi
  496c47:	cmp    %sil,(%rdi,%rax,1)
  496c4b:	jne    4967ac <tomo_multidb2_pad_82288+0x35>
  496c51:	lea    -0x1(%rdx),%eax
  496c54:	movzbl (%r15,%rax,1),%esi
  496c59:	cmp    %sil,(%rdi,%rax,1)
  496c5d:	jne    4967ac <tomo_multidb2_pad_82288+0x35>
  496c63:	jmp    49690b <tomo_multidb2_pad_82288+0x194>
  496c68:	add    %rcx,%r12
  496c6b:	mov    $0x1,%eax
  496c70:	shl    $0x30,%rax
  496c74:	or     (%r12),%rax
  496c78:	mov    %rax,(%r12)
  496c7c:	xor    %eax,%eax
  496c7e:	jmp    4966e5 <tomo_multidb2_pad_81749+0xb4>
  496c83:	call   2ba10 <__stack_chk_fail@plt>

Disassembly of section .rlfence:

Disassembly of section .fini:
