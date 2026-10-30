
build/wave10/arms/PRE:     file format elf64-x86-64


Disassembly of section .init:

Disassembly of section .plt:

Disassembly of section .plt.got:

Disassembly of section .plt.sec:

Disassembly of section .text:

00000000005dfc60 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE>:
  5dfc60:	endbr64
  5dfc64:	push   %rbp
  5dfc65:	push   %rbx
  5dfc66:	mov    %rdi,%rbp
  5dfc69:	mov    %rsi,%rbx
  5dfc6c:	sub    $0x38,%rsp
  5dfc70:	mov    %fs:0x28,%rax
  5dfc79:	mov    %rax,0x28(%rsp)
  5dfc7e:	xor    %eax,%eax
  5dfc80:	cmpl   $0x1,0xcc(%rsi)
  5dfc87:	jbe    5dfda0 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x140>
  5dfc8d:	mov    0xc0(%rsi),%rdx
  5dfc94:	lea    0xe0(%rsi),%rax
  5dfc9b:	lea    0x10(%rdx),%rcx
  5dfc9f:	test   %rdx,%rdx
  5dfca2:	cmovne %rcx,%rax
  5dfca6:	mov    (%rax),%rdx
  5dfca9:	mov    0x8(%rax),%rcx
  5dfcad:	mov    0x10(%rbx),%rsi
  5dfcb1:	lea    0x38(%rbp),%rdi
  5dfcb5:	lea    0x538(%rbp),%r8
  5dfcbc:	call   5763e0 <_ZN4tomo9FlatStore11find_notifyEmNS_5SliceEPNS_14FlatNotifySinkE>
  5dfcc1:	mov    %rax,%rsi
  5dfcc4:	test   %rax,%rax
  5dfcc7:	je     5dfdb0 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x150>
  5dfccd:	incq   0x3f0(%rbp)
  5dfcd4:	cmpb   $0x0,(%rax)
  5dfcd7:	mov    %rbx,(%rsp)
  5dfcdb:	movb   $0x0,0x8(%rsp)
  5dfce0:	je     5dfd20 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0xc0>
  5dfce2:	mov    %rsp,%rdi
  5dfce5:	mov    $0x44,%edx
  5dfcea:	lea    0x27445f(%rip),%rsi        # 854150 <_IO_stdin_used+0xb150>
  5dfcf1:	call   468360 <_ZN4tomo2Op4Sink6appendEPKcm>
  5dfcf6:	mov    0x28(%rsp),%rax
  5dfcfb:	sub    %fs:0x28,%rax
  5dfd04:	jne    5dff7a <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x31a>
  5dfd0a:	add    $0x38,%rsp
  5dfd0e:	pop    %rbx
  5dfd0f:	pop    %rbp
  5dfd10:	ret
  5dfd11:	data16 cs nopw 0x0(%rax,%rax,1)
  5dfd1c:	nopl   0x0(%rax)
  5dfd20:	movzbl 0x1(%rax),%eax
  5dfd24:	cmp    $0x1,%al
  5dfd26:	je     5dfec0 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x260>
  5dfd2c:	cmp    $0x2,%al
  5dfd2e:	je     5dfe20 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x1c0>
  5dfd34:	mov    0x4(%rsi),%ecx
  5dfd37:	movzbl 0x2(%rsi),%eax
  5dfd3b:	movzbl 0x2(%rsi),%edx
  5dfd3f:	shr    $1,%al
  5dfd41:	lea    0x0(,%rdx,8),%rdx
  5dfd49:	lea    0x0(,%rax,4),%rax
  5dfd51:	and    $0x8,%edx
  5dfd54:	and    $0x4,%eax
  5dfd57:	add    %rdx,%rax
  5dfd5a:	movzbl 0x2(%rsi),%edx
  5dfd5e:	and    $0x2,%edx
  5dfd61:	jne    5dfef0 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x290>
  5dfd67:	movzbl 0x3(%rsi),%edx
  5dfd6b:	lea    0x8(%rax,%rdx,1),%rax
  5dfd70:	add    %rax,%rsi
  5dfd73:	mov    0xc(%rbp),%eax
  5dfd76:	test   %eax,%eax
  5dfd78:	je     5dfd82 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x122>
  5dfd7a:	cmp    %eax,%ecx
  5dfd7c:	jb     5dfd82 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x122>
  5dfd7e:	orb    $0x2,0x1c(%rbx)
  5dfd82:	lea    0x10(%rsp),%rdi
  5dfd87:	mov    %ecx,%edx
  5dfd89:	mov    %rbx,0x10(%rsp)
  5dfd8e:	movb   $0x0,0x18(%rsp)
  5dfd93:	call   5dda40 <_ZN4tomo10reply_bulkINS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
  5dfd98:	jmp    5dfcf6 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x96>
  5dfd9d:	nopl   (%rax)
  5dfda0:	xor    %ecx,%ecx
  5dfda2:	xor    %edx,%edx
  5dfda4:	jmp    5dfcad <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x4d>
  5dfda9:	nopl   0x0(%rax)
  5dfdb0:	incq   0x3f8(%rbp)
  5dfdb7:	mov    %rbx,0x10(%rsp)
  5dfdbc:	movb   $0x0,0x18(%rsp)
  5dfdc1:	testb  $0x4,0x1c(%rbx)
  5dfdc5:	je     5dfe70 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x210>
  5dfdcb:	cmpb   $0x0,0x1e(%rbx)
  5dfdcf:	je     5dff00 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2a0>
  5dfdd5:	cmpb   $0x0,0x1d(%rbx)
  5dfdd9:	jne    5dff00 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2a0>
  5dfddf:	mov    0xa4(%rbx),%eax
  5dfde5:	test   %eax,%eax
  5dfde7:	jne    5dff00 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2a0>
  5dfded:	cmpq   $0x0,0x28(%rbx)
  5dfdf2:	jne    5dff00 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2a0>
  5dfdf8:	movb   $0x6,0x1d(%rbx)
  5dfdfc:	movl   $0x0,0xbc(%rbx)
  5dfe06:	movq   $0x0,0x98(%rbx)
  5dfe11:	jmp    5dfcf6 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x96>
  5dfe16:	cs nopw 0x0(%rax,%rax,1)
  5dfe20:	movzbl 0x2(%rsi),%eax
  5dfe24:	movzbl 0x2(%rsi),%edx
  5dfe28:	shr    $1,%al
  5dfe2a:	lea    0x0(,%rdx,8),%rdx
  5dfe32:	lea    0x0(,%rax,4),%rax
  5dfe3a:	and    $0x8,%edx
  5dfe3d:	and    $0x4,%eax
  5dfe40:	add    %rdx,%rax
  5dfe43:	movzbl 0x2(%rsi),%edx
  5dfe47:	and    $0x2,%edx
  5dfe4a:	jne    5dff20 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2c0>
  5dfe50:	movzbl 0x3(%rsi),%edx
  5dfe54:	add    %rsi,%rax
  5dfe57:	mov    0x4(%rsi),%ecx
  5dfe5a:	mov    0x8(%rdx,%rax,1),%rsi
  5dfe5f:	jmp    5dfd73 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x113>
  5dfe64:	data16 cs nopw 0x0(%rax,%rax,1)
  5dfe6f:	nop
  5dfe70:	cmpb   $0x0,0x1e(%rbx)
  5dfe74:	je     5dff30 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2d0>
  5dfe7a:	cmpb   $0x0,0x1d(%rbx)
  5dfe7e:	jne    5dff30 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2d0>
  5dfe84:	mov    0xa4(%rbx),%edx
  5dfe8a:	test   %edx,%edx
  5dfe8c:	jne    5dff30 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2d0>
  5dfe92:	cmpq   $0x0,0x28(%rbx)
  5dfe97:	jne    5dff30 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x2d0>
  5dfe9d:	movb   $0x2,0x1d(%rbx)
  5dfea1:	movl   $0x0,0xbc(%rbx)
  5dfeab:	movq   $0x0,0x98(%rbx)
  5dfeb6:	jmp    5dfcf6 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x96>
  5dfebb:	nopl   0x0(%rax,%rax,1)
  5dfec0:	mov    0x28(%rsp),%rax
  5dfec5:	sub    %fs:0x28,%rax
  5dfece:	jne    5dff7a <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x31a>
  5dfed4:	add    $0x38,%rsp
  5dfed8:	mov    %rbx,%rdi
  5dfedb:	pop    %rbx
  5dfedc:	pop    %rbp
  5dfedd:	jmp    5ddc20 <_ZN4tomo12_GLOBAL__N_117reply_string_bulkERNS_2OpEPKNS_5KvObjE>
  5dfee2:	data16 cs nopw 0x0(%rax,%rax,1)
  5dfeed:	nopl   (%rax)
  5dfef0:	mov    0x8(%rsi),%edx
  5dfef3:	jmp    5dfd6b <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x10b>
  5dfef8:	nopl   0x0(%rax,%rax,1)
  5dff00:	lea    0x10(%rsp),%rdi
  5dff05:	mov    $0x3,%edx
  5dff0a:	lea    0x26a9ce(%rip),%rsi        # 84a8df <_IO_stdin_used+0x18df>
  5dff11:	call   468360 <_ZN4tomo2Op4Sink6appendEPKcm>
  5dff16:	jmp    5dfcf6 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x96>
  5dff1b:	nopl   0x0(%rax,%rax,1)
  5dff20:	mov    0x8(%rsi),%edx
  5dff23:	jmp    5dfe54 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x1f4>
  5dff28:	nopl   0x0(%rax,%rax,1)
  5dff30:	lea    0x10(%rsp),%rdi
  5dff35:	mov    $0x5,%esi
  5dff3a:	call   56e9c0 <_ZN4tomo2Op4Sink7reserveEm>
  5dff3f:	cmpb   $0x0,0x18(%rsp)
  5dff44:	movl   $0xd312d24,(%rax)
  5dff4a:	movb   $0xa,0x4(%rax)
  5dff4e:	mov    0x10(%rsp),%rax
  5dff53:	je     5dff70 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x310>
  5dff55:	addl   $0x5,0xa4(%rax)
  5dff5c:	jmp    5dfcf6 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x96>
  5dff61:	data16 cs nopw 0x0(%rax,%rax,1)
  5dff6c:	nopl   0x0(%rax)
  5dff70:	addq   $0x5,0x28(%rax)
  5dff75:	jmp    5dfcf6 <_ZN4tomo12_GLOBAL__N_17cmd_getILb1ELb0EEEvRNS_5ShardERNS_2OpE+0x96>
  5dff7a:	call   1f950 <__stack_chk_fail@plt>

Disassembly of section .rlfence:

Disassembly of section .fini:
