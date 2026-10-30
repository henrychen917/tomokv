
build/tomokv:     file format elf64-x86-64


Disassembly of section .init:

Disassembly of section .plt:

Disassembly of section .plt.got:

Disassembly of section .plt.sec:

Disassembly of section .text:

00000000005fc6a0 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE>:
  5fc6a0:	endbr64
  5fc6a4:	push   %rbp
  5fc6a5:	push   %rbx
  5fc6a6:	mov    %rdi,%rbp
  5fc6a9:	mov    %rsi,%rbx
  5fc6ac:	sub    $0x38,%rsp
  5fc6b0:	mov    %fs:0x28,%rax
  5fc6b9:	mov    %rax,0x28(%rsp)
  5fc6be:	xor    %eax,%eax
  5fc6c0:	cmpl   $0x1,0xcc(%rsi)
  5fc6c7:	jbe    5fc7e0 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x140>
  5fc6cd:	mov    0xc0(%rsi),%rdx
  5fc6d4:	lea    0xe0(%rsi),%rax
  5fc6db:	lea    0x10(%rdx),%rcx
  5fc6df:	test   %rdx,%rdx
  5fc6e2:	cmovne %rcx,%rax
  5fc6e6:	mov    (%rax),%rdx
  5fc6e9:	mov    0x8(%rax),%rcx
  5fc6ed:	mov    0x10(%rbx),%rsi
  5fc6f1:	lea    0x38(%rbp),%rdi
  5fc6f5:	lea    0x538(%rbp),%r8
  5fc6fc:	call   592d70 <_ZN4tomo9FlatStore11find_notifyEmNS_5SliceEPNS_14FlatNotifySinkE>
  5fc701:	mov    %rax,%rsi
  5fc704:	test   %rax,%rax
  5fc707:	je     5fc7f0 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x150>
  5fc70d:	incq   0x3f0(%rbp)
  5fc714:	cmpb   $0x0,(%rax)
  5fc717:	mov    %rbx,(%rsp)
  5fc71b:	movb   $0x0,0x8(%rsp)
  5fc720:	je     5fc760 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0xc0>
  5fc722:	mov    %rsp,%rdi
  5fc725:	mov    $0x44,%edx
  5fc72a:	lea    0x27dd17(%rip),%rsi        # 87a448 <_IO_stdin_used+0xb448>
  5fc731:	call   484780 <_ZN4tomo2Op4Sink6appendEPKcm>
  5fc736:	mov    0x28(%rsp),%rax
  5fc73b:	sub    %fs:0x28,%rax
  5fc744:	jne    5fc9b3 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x313>
  5fc74a:	add    $0x38,%rsp
  5fc74e:	pop    %rbx
  5fc74f:	pop    %rbp
  5fc750:	ret
  5fc751:	data16 cs nopw 0x0(%rax,%rax,1)
  5fc75c:	nopl   0x0(%rax)
  5fc760:	movzbl 0x1(%rax),%eax
  5fc764:	cmp    $0x1,%al
  5fc766:	je     5fc900 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x260>
  5fc76c:	cmp    $0x2,%al
  5fc76e:	je     5fc860 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x1c0>
  5fc774:	mov    0x4(%rsi),%ecx
  5fc777:	movzbl 0x2(%rsi),%eax
  5fc77b:	movzbl 0x2(%rsi),%edx
  5fc77f:	shr    $1,%al
  5fc781:	lea    0x0(,%rdx,8),%rdx
  5fc789:	lea    0x0(,%rax,4),%rax
  5fc791:	and    $0x8,%edx
  5fc794:	and    $0x4,%eax
  5fc797:	add    %rdx,%rax
  5fc79a:	movzbl 0x2(%rsi),%edx
  5fc79e:	and    $0x2,%edx
  5fc7a1:	jne    5fc930 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x290>
  5fc7a7:	movzbl 0x3(%rsi),%edx
  5fc7ab:	lea    0x8(%rax,%rdx,1),%rax
  5fc7b0:	add    %rax,%rsi
  5fc7b3:	mov    0xc(%rbp),%eax
  5fc7b6:	test   %eax,%eax
  5fc7b8:	je     5fc7c2 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x122>
  5fc7ba:	cmp    %eax,%ecx
  5fc7bc:	jb     5fc7c2 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x122>
  5fc7be:	orb    $0x2,0x1c(%rbx)
  5fc7c2:	lea    0x10(%rsp),%rdi
  5fc7c7:	mov    %ecx,%edx
  5fc7c9:	mov    %rbx,0x10(%rsp)
  5fc7ce:	movb   $0x0,0x18(%rsp)
  5fc7d3:	call   5fa480 <_ZN4tomo10reply_bulkINS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
  5fc7d8:	jmp    5fc736 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x96>
  5fc7dd:	nopl   (%rax)
  5fc7e0:	xor    %ecx,%ecx
  5fc7e2:	xor    %edx,%edx
  5fc7e4:	jmp    5fc6ed <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x4d>
  5fc7e9:	nopl   0x0(%rax)
  5fc7f0:	incq   0x3f8(%rbp)
  5fc7f7:	mov    %rbx,0x10(%rsp)
  5fc7fc:	movb   $0x0,0x18(%rsp)
  5fc801:	testb  $0x4,0x1c(%rbx)
  5fc805:	je     5fc8b0 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x210>
  5fc80b:	cmpb   $0x0,0x1e(%rbx)
  5fc80f:	je     5fc940 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2a0>
  5fc815:	cmpb   $0x0,0x1d(%rbx)
  5fc819:	jne    5fc940 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2a0>
  5fc81f:	mov    0xa4(%rbx),%eax
  5fc825:	test   %eax,%eax
  5fc827:	jne    5fc940 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2a0>
  5fc82d:	cmpq   $0x0,0x28(%rbx)
  5fc832:	jne    5fc940 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2a0>
  5fc838:	movb   $0x6,0x1d(%rbx)
  5fc83c:	movl   $0x0,0xbc(%rbx)
  5fc846:	movq   $0x0,0x98(%rbx)
  5fc851:	jmp    5fc736 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x96>
  5fc856:	cs nopw 0x0(%rax,%rax,1)
  5fc860:	movzbl 0x2(%rsi),%eax
  5fc864:	movzbl 0x2(%rsi),%edx
  5fc868:	shr    $1,%al
  5fc86a:	lea    0x0(,%rdx,8),%rdx
  5fc872:	lea    0x0(,%rax,4),%rax
  5fc87a:	and    $0x8,%edx
  5fc87d:	and    $0x4,%eax
  5fc880:	add    %rdx,%rax
  5fc883:	movzbl 0x2(%rsi),%edx
  5fc887:	and    $0x2,%edx
  5fc88a:	jne    5fc960 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2c0>
  5fc890:	movzbl 0x3(%rsi),%edx
  5fc894:	add    %rsi,%rax
  5fc897:	mov    0x4(%rsi),%ecx
  5fc89a:	mov    0x8(%rdx,%rax,1),%rsi
  5fc89f:	jmp    5fc7b3 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x113>
  5fc8a4:	data16 cs nopw 0x0(%rax,%rax,1)
  5fc8af:	nop
  5fc8b0:	cmpb   $0x0,0x1e(%rbx)
  5fc8b4:	je     5fc970 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2d0>
  5fc8ba:	cmpb   $0x0,0x1d(%rbx)
  5fc8be:	jne    5fc970 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2d0>
  5fc8c4:	mov    0xa4(%rbx),%edx
  5fc8ca:	test   %edx,%edx
  5fc8cc:	jne    5fc970 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2d0>
  5fc8d2:	cmpq   $0x0,0x28(%rbx)
  5fc8d7:	jne    5fc970 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2d0>
  5fc8dd:	movb   $0x2,0x1d(%rbx)
  5fc8e1:	movl   $0x0,0xbc(%rbx)
  5fc8eb:	movq   $0x0,0x98(%rbx)
  5fc8f6:	jmp    5fc736 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x96>
  5fc8fb:	nopl   0x0(%rax,%rax,1)
  5fc900:	mov    0x28(%rsp),%rax
  5fc905:	sub    %fs:0x28,%rax
  5fc90e:	jne    5fc9b3 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x313>
  5fc914:	add    $0x38,%rsp
  5fc918:	mov    %rbx,%rdi
  5fc91b:	pop    %rbx
  5fc91c:	pop    %rbp
  5fc91d:	jmp    5fa660 <_ZN4tomo12_GLOBAL__N_117reply_string_bulkERNS_2OpEPKNS_5KvObjE>
  5fc922:	data16 cs nopw 0x0(%rax,%rax,1)
  5fc92d:	nopl   (%rax)
  5fc930:	mov    0x8(%rsi),%edx
  5fc933:	jmp    5fc7ab <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x10b>
  5fc938:	nopl   0x0(%rax,%rax,1)
  5fc940:	lea    0x10(%rsp),%rdi
  5fc945:	mov    $0x3,%edx
  5fc94a:	lea    0x27412c(%rip),%rsi        # 870a7d <_IO_stdin_used+0x1a7d>
  5fc951:	call   484780 <_ZN4tomo2Op4Sink6appendEPKcm>
  5fc956:	jmp    5fc736 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x96>
  5fc95b:	nopl   0x0(%rax,%rax,1)
  5fc960:	mov    0x8(%rsi),%edx
  5fc963:	jmp    5fc894 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x1f4>
  5fc968:	nopl   0x0(%rax,%rax,1)
  5fc970:	lea    0x10(%rsp),%rdi
  5fc975:	mov    $0x5,%esi
  5fc97a:	call   4846b0 <_ZN4tomo2Op4Sink7reserveEm>
  5fc97f:	movl   $0xd312d24,(%rax)
  5fc985:	movb   $0xa,0x4(%rax)
  5fc989:	mov    0x28(%rsp),%rax
  5fc98e:	sub    %fs:0x28,%rax
  5fc997:	jne    5fc9b3 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x313>
  5fc999:	movzbl 0x18(%rsp),%esi
  5fc99e:	mov    0x10(%rsp),%rdi
  5fc9a3:	add    $0x38,%rsp
  5fc9a7:	mov    $0x5,%edx
  5fc9ac:	pop    %rbx
  5fc9ad:	pop    %rbp
  5fc9ae:	jmp    5fa140 <_ZN4tomo2Op4Sink7advanceEm.isra.0>
  5fc9b3:	call   2ba10 <__stack_chk_fail@plt>

Disassembly of section .rlfence:

Disassembly of section .fini:
