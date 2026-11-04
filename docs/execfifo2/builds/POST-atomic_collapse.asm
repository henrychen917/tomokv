
build/execfifo2/POST:     file format elf64-x86-64


Disassembly of section .init:

Disassembly of section .plt:

Disassembly of section .plt.got:

Disassembly of section .plt.sec:

Disassembly of section .text:

00000000004bf7a0 <_ZN4tomo9FlatStore15atomic_collapseEmm>:
  4bf7a0:	endbr64
  4bf7a4:	push   %r15
  4bf7a6:	push   %r14
  4bf7a8:	push   %r13
  4bf7aa:	mov    %rdx,%rcx
  4bf7ad:	push   %r12
  4bf7af:	push   %rbp
  4bf7b0:	push   %rbx
  4bf7b1:	sub    $0xc8,%rsp
  4bf7b8:	mov    %rdi,0x40(%rsp)
  4bf7bd:	mov    %fs:0x28,%rax
  4bf7c6:	mov    %rax,0xb8(%rsp)
  4bf7ce:	xor    %eax,%eax
  4bf7d0:	movzbl 0xf0(%rdi),%eax
  4bf7d7:	mov    %al,0x48(%rsp)
  4bf7db:	test   %al,%al
  4bf7dd:	jne    4bfb38 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x398>
  4bf7e3:	mov    0x40(%rsp),%rdx
  4bf7e8:	mov    0xc8(%rdx),%rax
  4bf7ef:	test   %rax,%rax
  4bf7f2:	je     4bfac0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x320>
  4bf7f8:	mov    0x210(%rax),%edi
  4bf7fe:	test   %edi,%edi
  4bf800:	je     4bfac0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x320>
  4bf806:	cmpb   $0x0,0x193(%rdx)
  4bf80d:	jne    4bfac0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x320>
  4bf813:	mov    (%rax),%r15
  4bf816:	test   %r15,%r15
  4bf819:	je     4bfac0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x320>
  4bf81f:	xor    %edx,%edx
  4bf821:	jmp    4bf86a <_ZN4tomo9FlatStore15atomic_collapseEmm+0xca>
  4bf823:	data16 cs nopw 0x0(%rax,%rax,1)
  4bf82e:	xchg   %ax,%ax
  4bf830:	movzbl (%rdi),%edi
  4bf833:	mov    0x30(%r15),%rax
  4bf837:	test   %rax,%rax
  4bf83a:	je     4bfb10 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x370>
  4bf840:	mov    (%rax),%rax
  4bf843:	cmp    $0xffffffffffffffff,%rax
  4bf847:	je     4bfb1e <_ZN4tomo9FlatStore15atomic_collapseEmm+0x37e>
  4bf84d:	test   %dil,%dil
  4bf850:	je     4bf889 <_ZN4tomo9FlatStore15atomic_collapseEmm+0xe9>
  4bf852:	mov    0x7c(%r15),%eax
  4bf856:	add    %rdx,%rax
  4bf859:	jb     4bfac0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x320>
  4bf85f:	mov    (%r15),%r15
  4bf862:	mov    %rax,%rdx
  4bf865:	test   %r15,%r15
  4bf868:	je     4bf8b0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x110>
  4bf86a:	mov    0x30(%r15),%rax
  4bf86e:	test   %rax,%rax
  4bf871:	je     4bfaf0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x350>
  4bf877:	mov    0x40(%r15),%rdi
  4bf87b:	test   %rdi,%rdi
  4bf87e:	jne    4bf830 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x90>
  4bf880:	mov    (%rax),%rax
  4bf883:	cmp    $0xffffffffffffffff,%rax
  4bf887:	je     4bf8b0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x110>
  4bf889:	test   %rax,%rax
  4bf88c:	sete   %dil
  4bf890:	cmp    %rsi,%rax
  4bf893:	setae  %r8b
  4bf897:	or     %r8b,%dil
  4bf89a:	jne    4bf8b0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x110>
  4bf89c:	cmp    %rax,%rcx
  4bf89f:	jae    4bf852 <_ZN4tomo9FlatStore15atomic_collapseEmm+0xb2>
  4bf8a1:	data16 cs nopw 0x0(%rax,%rax,1)
  4bf8ac:	nopl   0x0(%rax)
  4bf8b0:	mov    %rdx,0x50(%rsp)
  4bf8b5:	cmpq   $0x0,0x50(%rsp)
  4bf8bb:	je     4bfac0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x320>
  4bf8c1:	mov    0x40(%rsp),%rax
  4bf8c6:	mov    0xc8(%rax),%rdx
  4bf8cd:	mov    (%rdx),%rax
  4bf8d0:	cmp    %r15,%rax
  4bf8d3:	je     4c0550 <tomo_multidb2_pad_380927+0x8b5>
  4bf8d9:	xor    %ecx,%ecx
  4bf8db:	xor    %edi,%edi
  4bf8dd:	jmp    4bf8f7 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x157>
  4bf8df:	nop
  4bf8e0:	mov    (%rdx),%rcx
  4bf8e3:	mov    (%rax),%rax
  4bf8e6:	cmp    $0xffffffffffffffff,%rcx
  4bf8ea:	cmove  %rdi,%rcx
  4bf8ee:	cmp    %r15,%rax
  4bf8f1:	je     4bfb76 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x3d6>
  4bf8f7:	mov    0x30(%rax),%rdx
  4bf8fb:	test   %rdx,%rdx
  4bf8fe:	je     4bf925 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x185>
  4bf900:	mov    0x40(%rax),%rsi
  4bf904:	test   %rsi,%rsi
  4bf907:	je     4bfb30 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x390>
  4bf90d:	movzbl (%rsi),%edx
  4bf910:	test   %dl,%dl
  4bf912:	jne    4bff09 <tomo_multidb2_pad_380927+0x26e>
  4bf918:	mov    0x30(%rax),%rdx
  4bf91c:	test   %rdx,%rdx
  4bf91f:	jne    4bfb30 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x390>
  4bf925:	mov    0x58(%rax),%rdx
  4bf929:	cmp    $0xffffffffffffffff,%rdx
  4bf92d:	cmove  %rdi,%rdx
  4bf931:	cmp    %rcx,%rdx
  4bf934:	jb     4bff09 <tomo_multidb2_pad_380927+0x26e>
  4bf93a:	mov    0x30(%rax),%rdx
  4bf93e:	test   %rdx,%rdx
  4bf941:	jne    4bf8e0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x140>
  4bf943:	mov    0x58(%rax),%rcx
  4bf947:	jmp    4bf8e3 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x143>
  4bf949:	nopl   0x0(%rax)
  4bf950:	mov    0x8(%rsp),%rbp
  4bf955:	cmpb   $0x0,0x89(%r15)
  4bf95d:	jne    4bfe94 <tomo_multidb2_pad_380927+0x1f9>
  4bf963:	mov    0x38(%r15),%rdx
  4bf967:	test   %rdx,%rdx
  4bf96a:	je     4bf97c <_ZN4tomo9FlatStore15atomic_collapseEmm+0x1dc>
  4bf96c:	mov    0x48(%r15),%rsi
  4bf970:	test   %rsi,%rsi
  4bf973:	je     4bf979 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x1d9>
  4bf975:	decl   (%rsi)
  4bf977:	jne    4bf97c <_ZN4tomo9FlatStore15atomic_collapseEmm+0x1dc>
  4bf979:	lock decl (%rdx)
  4bf97c:	mov    0xb0(%r14),%rax
  4bf983:	test   %rax,%rax
  4bf986:	je     4bf98b <_ZN4tomo9FlatStore15atomic_collapseEmm+0x1eb>
  4bf988:	incq   (%rax)
  4bf98b:	mov    0xc8(%r14),%rax
  4bf992:	decl   0x210(%rax)
  4bf998:	cmpq   $0x0,0x28(%r15)
  4bf99d:	je     4bf9a5 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x205>
  4bf99f:	decb   0x526(%rax)
  4bf9a5:	mov    0x18(%r15),%rsi
  4bf9a9:	mov    0x50(%r15),%rdx
  4bf9ad:	test   %rsi,%rsi
  4bf9b0:	je     4bfe2c <tomo_multidb2_pad_380927+0x191>
  4bf9b6:	mov    0x10(%r15),%rdx
  4bf9ba:	mov    %rdx,0x10(%rsi)
  4bf9be:	test   %rdx,%rdx
  4bf9c1:	je     4bfe10 <tomo_multidb2_pad_380927+0x175>
  4bf9c7:	mov    0xc8(%r14),%rax
  4bf9ce:	mov    %rsi,0x18(%rdx)
  4bf9d2:	movq   $0x0,0x18(%r15)
  4bf9da:	movq   $0x0,0x10(%r15)
  4bf9e2:	cmpb   $0x0,0x89(%r15)
  4bf9ea:	jne    4c0421 <tomo_multidb2_pad_380927+0x786>
  4bf9f0:	mov    0x70(%r15),%rsi
  4bf9f4:	cmp    $0x8,%rsi
  4bf9f8:	jbe    4bfdb4 <tomo_multidb2_pad_380927+0x119>
  4bf9fe:	cmp    $0x80,%rsi
  4bfa05:	jbe    4bfe7f <tomo_multidb2_pad_380927+0x1e4>
  4bfa0b:	lea    -0x1(%rsi),%rdx
  4bfa0f:	mov    $0x3d,%edi
  4bfa14:	mov    $0x38,%r8d
  4bfa1a:	lzcnt  %rdx,%rdx
  4bfa1f:	sub    %edx,%edi
  4bfa21:	sub    %edx,%r8d
  4bfa24:	shrx   %rdi,%rsi,%rdi
  4bfa29:	lea    0x4(%rdi,%r8,4),%edx
  4bfa2e:	cmp    $0x2f,%edx
  4bfa31:	ja     4bfa3c <_ZN4tomo9FlatStore15atomic_collapseEmm+0x29c>
  4bfa33:	test   %rax,%rax
  4bfa36:	jne    4bfdbf <tomo_multidb2_pad_380927+0x124>
  4bfa3c:	xor    %edx,%edx
  4bfa3e:	mov    %r15,%rdi
  4bfa41:	call   2bf70 <sdallocx@plt>
  4bfa46:	cmp    %rbp,0x10(%rsp)
  4bfa4b:	jne    4bfbc0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x420>
  4bfa51:	mov    0x40(%rsp),%rax
  4bfa56:	mov    0x10(%rsp),%r15
  4bfa5b:	mov    0xc8(%rax),%rdx
  4bfa62:	mov    %r15,(%rdx)
  4bfa65:	test   %r15,%r15
  4bfa68:	je     4c0c91 <tomo_multidb2_pad_380927+0xff6>
  4bfa6e:	movq   $0x0,0x8(%r15)
  4bfa76:	cmpq   $0x0,0x210(%rdx)
  4bfa7e:	jne    4bfa95 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2f5>
  4bfa80:	mov    0x40(%rsp),%rax
  4bfa85:	mov    0x88(%rax),%rax
  4bfa8c:	test   %rax,%rax
  4bfa8f:	je     4bfa95 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2f5>
  4bfa91:	lock decq (%rax)
  4bfa95:	mov    0x40(%rsp),%rax
  4bfa9a:	mov    0xa8(%rax),%rax
  4bfaa1:	test   %rax,%rax
  4bfaa4:	je     4bfaae <_ZN4tomo9FlatStore15atomic_collapseEmm+0x30e>
  4bfaa6:	mov    0x50(%rsp),%rcx
  4bfaab:	add    %rcx,(%rax)
  4bfaae:	movb   $0x1,0x48(%rsp)
  4bfab3:	data16 cs nopw 0x0(%rax,%rax,1)
  4bfabe:	xchg   %ax,%ax
  4bfac0:	mov    0xb8(%rsp),%rax
  4bfac8:	sub    %fs:0x28,%rax
  4bfad1:	jne    4c1972 <tomo_multidb2_pad_380927+0x1cd7>
  4bfad7:	movzbl 0x48(%rsp),%eax
  4bfadc:	add    $0xc8,%rsp
  4bfae3:	pop    %rbx
  4bfae4:	pop    %rbp
  4bfae5:	pop    %r12
  4bfae7:	pop    %r13
  4bfae9:	pop    %r14
  4bfaeb:	pop    %r15
  4bfaed:	ret
  4bfaee:	xchg   %ax,%ax
  4bfaf0:	mov    0x58(%r15),%rax
  4bfaf4:	cmp    $0xffffffffffffffff,%rax
  4bfaf8:	jne    4bf889 <_ZN4tomo9FlatStore15atomic_collapseEmm+0xe9>
  4bfafe:	jmp    4bf8b0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x110>
  4bfb03:	data16 cs nopw 0x0(%rax,%rax,1)
  4bfb0e:	xchg   %ax,%ax
  4bfb10:	mov    0x58(%r15),%rax
  4bfb14:	cmp    $0xffffffffffffffff,%rax
  4bfb18:	jne    4bf84d <_ZN4tomo9FlatStore15atomic_collapseEmm+0xad>
  4bfb1e:	test   %dil,%dil
  4bfb21:	jne    4bf852 <_ZN4tomo9FlatStore15atomic_collapseEmm+0xb2>
  4bfb27:	jmp    4bf8b0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x110>
  4bfb2c:	nopl   0x0(%rax)
  4bfb30:	mov    (%rdx),%rdx
  4bfb33:	jmp    4bf929 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x189>
  4bfb38:	mov    0xb8(%rsp),%rax
  4bfb40:	sub    %fs:0x28,%rax
  4bfb49:	jne    4c1972 <tomo_multidb2_pad_380927+0x1cd7>
  4bfb4f:	mov    0x40(%rsp),%rdi
  4bfb54:	add    $0xc8,%rsp
  4bfb5b:	pop    %rbx
  4bfb5c:	pop    %rbp
  4bfb5d:	pop    %r12
  4bfb5f:	pop    %r13
  4bfb61:	pop    %r14
  4bfb63:	pop    %r15
  4bfb65:	jmp    4bcfb0 <_ZN4tomo9FlatStore26atomic_collapse_read_localEmm>
  4bfb6a:	mov    (%r14),%r14
  4bfb6d:	cmp    %r14,%r15
  4bfb70:	jne    4bff30 <tomo_multidb2_pad_380927+0x295>
  4bfb76:	mov    0x40(%rsp),%rax
  4bfb7b:	mov    0xc8(%rax),%rdx
  4bfb82:	mov    0x50(%rsp),%rax
  4bfb87:	mov    (%rdx),%r14
  4bfb8a:	add    %rax,0x528(%rdx)
  4bfb91:	cmp    %r14,%r15
  4bfb94:	je     4bfa62 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2c2>
  4bfb9a:	mov    %r14,%rbp
  4bfb9d:	mov    0x40(%rsp),%r14
  4bfba2:	movabs $0xc4ceb9fe1a85ec53,%r12
  4bfbac:	mov    %r15,0x10(%rsp)
  4bfbb1:	data16 cs nopw 0x0(%rax,%rax,1)
  4bfbbc:	nopl   0x0(%rax)
  4bfbc0:	mov    %rbp,%r15
  4bfbc3:	xor    %r13d,%r13d
  4bfbc6:	mov    0x0(%rbp),%rbp
  4bfbca:	mov    0x7c(%r15),%eax
  4bfbce:	test   %eax,%eax
  4bfbd0:	je     4bf955 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x1b5>
  4bfbd6:	mov    %rbp,0x8(%rsp)
  4bfbdb:	mov    %r13,%rbp
  4bfbde:	jmp    4bfc7d <_ZN4tomo9FlatStore15atomic_collapseEmm+0x4dd>
  4bfbe3:	data16 cs nopw 0x0(%rax,%rax,1)
  4bfbee:	xchg   %ax,%ax
  4bfbf0:	lea    0x8(%rax,%r13,1),%r13
  4bfbf5:	cmp    $0x2,%cl
  4bfbf8:	ja     4bfd70 <tomo_multidb2_pad_380927+0xd5>
  4bfbfe:	test   %cl,%cl
  4bfc00:	je     4bfd60 <tomo_multidb2_pad_380927+0xc5>
  4bfc06:	add    $0x8,%r13
  4bfc0a:	cmp    $0x80,%r13
  4bfc11:	jbe    4bfd40 <tomo_multidb2_pad_380927+0xa5>
  4bfc17:	dec    %r13
  4bfc1a:	mov    $0x3d,%ecx
  4bfc1f:	lzcnt  %r13,%rax
  4bfc24:	sub    %eax,%ecx
  4bfc26:	mov    $0x1,%eax
  4bfc2b:	shlx   %rcx,%rax,%rax
  4bfc30:	add    %rax,%r13
  4bfc33:	neg    %rax
  4bfc36:	and    %rax,%r13
  4bfc39:	mov    %rbx,%rdi
  4bfc3c:	call   484070 <_ZN4tomo20kvobj_external_bytesILb0EEEmPKNS_5KvObjEPKv.isra.0>
  4bfc41:	mov    (%r14),%rcx
  4bfc44:	add    %r13,%rax
  4bfc47:	mov    %rcx,%rsi
  4bfc4a:	sub    %rax,%rsi
  4bfc4d:	cmp    %rax,%rcx
  4bfc50:	jb     4bfd9e <tomo_multidb2_pad_380927+0x103>
  4bfc56:	mov    %rsi,(%r14)
  4bfc59:	mov    %r14,%rdi
  4bfc5c:	mov    %rbx,%rsi
  4bfc5f:	call   494730 <_ZN4tomo9FlatStore19retire_detached_objEPNS_5KvObjE>
  4bfc64:	movq   $0x0,0x90(%r15,%rbp,8)
  4bfc70:	inc    %rbp
  4bfc73:	cmp    0x7c(%r15),%ebp
  4bfc77:	jae    4bf950 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x1b0>
  4bfc7d:	mov    0x90(%r15,%rbp,8),%rbx
  4bfc85:	test   %rbx,%rbx
  4bfc88:	je     4bfc70 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x4d0>
  4bfc8a:	movzbl 0x1(%rbx),%ecx
  4bfc8e:	mov    0x4(%rbx),%esi
  4bfc91:	movzbl 0x2(%rbx),%edi
  4bfc95:	movzbl 0x2(%rbx),%eax
  4bfc99:	test   $0x2,%al

00000000004bfc9b <tomo_multidb2_pad_380927>:
  4bfc9b:	jne    4bfd00 <tomo_multidb2_pad_380927+0x65>
  4bfc9d:	movzbl 0x3(%rbx),%eax
  4bfca1:	vmovd  %eax,%xmm0
  4bfca5:	xor    %eax,%eax
  4bfca7:	vpinsrd $0x1,%eax,%xmm0,%xmm3
  4bfcad:	vmovq  %xmm3,%rax
  4bfcb2:	cmp    $0xff,%rax
  4bfcb8:	mov    %rax,%r13
  4bfcbb:	sbb    %rax,%rax
  4bfcbe:	mov    %r13d,%r13d
  4bfcc1:	and    $0xfffffffffffffffc,%rax
  4bfcc5:	add    $0xc,%rax
  4bfcc9:	and    $0x1,%edi
  4bfccc:	jne    4bfbf0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x450>
  4bfcd2:	add    %rax,%r13
  4bfcd5:	cmp    $0x2,%cl
  4bfcd8:	ja     4bfd90 <tomo_multidb2_pad_380927+0xf5>
  4bfcde:	test   %cl,%cl
  4bfce0:	jne    4bfc06 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x466>
  4bfce6:	add    %rsi,%r13
  4bfce9:	cmp    $0x8,%r13
  4bfced:	je     4bfc39 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x499>
  4bfcf3:	jmp    4bfc0a <_ZN4tomo9FlatStore15atomic_collapseEmm+0x46a>
  4bfcf8:	nopl   0x0(%rax,%rax,1)
  4bfd00:	movzbl 0x2(%rbx),%r8d
  4bfd05:	xor    %eax,%eax
  4bfd07:	and    $0x2,%r8d
  4bfd0b:	je     4bfd16 <tomo_multidb2_pad_380927+0x7b>
  4bfd0d:	movzbl 0x3(%rbx),%eax
  4bfd11:	inc    %eax
  4bfd13:	movzbl %al,%eax
  4bfd16:	movzbl 0x2(%rbx),%r8d
  4bfd1b:	and    $0x2,%r8d
  4bfd1f:	jne    4bfd50 <tomo_multidb2_pad_380927+0xb5>
  4bfd21:	movzbl 0x3(%rbx),%edx
  4bfd25:	vmovd  %edx,%xmm0
  4bfd29:	movzbl 0x2(%rbx),%r8d
  4bfd2e:	movzbl 0x2(%rbx),%r8d
  4bfd33:	jmp    4bfca7 <tomo_multidb2_pad_380927+0xc>
  4bfd38:	nopl   0x0(%rax,%rax,1)
  4bfd40:	add    $0xf,%r13
  4bfd44:	and    $0xfffffffffffffff0,%r13
  4bfd48:	jmp    4bfc39 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x499>
  4bfd4d:	nopl   (%rax)
  4bfd50:	vmovd  0x8(%rbx),%xmm0
  4bfd55:	jmp    4bfd29 <tomo_multidb2_pad_380927+0x8e>
  4bfd57:	nopw   0x0(%rax,%rax,1)
  4bfd60:	add    %rsi,%r13
  4bfd63:	jmp    4bfc0a <_ZN4tomo9FlatStore15atomic_collapseEmm+0x46a>
  4bfd68:	nopl   0x0(%rax,%rax,1)
  4bfd70:	mov    %esi,%eax
  4bfd72:	add    %r13,%rax
  4bfd75:	cmp    $0x3,%cl
  4bfd78:	cmove  %rax,%r13
  4bfd7c:	jmp    4bfc0a <_ZN4tomo9FlatStore15atomic_collapseEmm+0x46a>
  4bfd81:	data16 cs nopw 0x0(%rax,%rax,1)
  4bfd8c:	nopl   0x0(%rax)
  4bfd90:	cmp    $0x3,%cl
  4bfd93:	je     4bfce6 <tomo_multidb2_pad_380927+0x4b>
  4bfd99:	jmp    4bfce9 <tomo_multidb2_pad_380927+0x4e>
  4bfd9e:	mov    0xc0(%r14),%rax
  4bfda5:	test   %rax,%rax
  4bfda8:	je     4bfdad <tomo_multidb2_pad_380927+0x112>
  4bfdaa:	incq   (%rax)
  4bfdad:	xor    %esi,%esi
  4bfdaf:	jmp    4bfc56 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x4b6>
  4bfdb4:	xor    %edx,%edx
  4bfdb6:	test   %rax,%rax
  4bfdb9:	je     4bfa3c <_ZN4tomo9FlatStore15atomic_collapseEmm+0x29c>
  4bfdbf:	mov    0x520(%rax),%edi
  4bfdc5:	cmp    $0xfff,%edi
  4bfdcb:	ja     4bfa3c <_ZN4tomo9FlatStore15atomic_collapseEmm+0x29c>
  4bfdd1:	mov    0x538(%rax),%r8
  4bfdd8:	add    %rsi,%r8
  4bfddb:	cmp    $0x400000,%r8
  4bfde2:	ja     4bfa3c <_ZN4tomo9FlatStore15atomic_collapseEmm+0x29c>
  4bfde8:	mov    %edx,%edx
  4bfdea:	inc    %edi
  4bfdec:	add    $0x40,%rdx
  4bfdf0:	mov    0x20(%rax,%rdx,8),%rsi
  4bfdf5:	mov    %rsi,0x20(%r15)
  4bfdf9:	mov    %r15,0x20(%rax,%rdx,8)
  4bfdfe:	mov    %edi,0x520(%rax)
  4bfe04:	mov    %r8,0x538(%rax)
  4bfe0b:	jmp    4bfa46 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2a6>
  4bfe10:	mov    0xc8(%r14),%rax
  4bfe17:	movq   $0x0,0x18(%r15)
  4bfe1f:	movq   $0x0,0x10(%r15)
  4bfe27:	jmp    4bf9e2 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x242>
  4bfe2c:	mov    %rdx,%rax
  4bfe2f:	movabs $0xff51afd7ed558ccd,%rcx
  4bfe39:	mov    0xc8(%r14),%rdi
  4bfe40:	shr    $0x21,%rax
  4bfe44:	xor    %rdx,%rax
  4bfe47:	imul   %rcx,%rax
  4bfe4b:	mov    %rax,%rdx
  4bfe4e:	shr    $0x21,%rdx
  4bfe52:	xor    %rdx,%rax
  4bfe55:	imul   %r12,%rax
  4bfe59:	mov    %rax,%rdx
  4bfe5c:	shr    $0x21,%rdx
  4bfe60:	xor    %rdx,%rax
  4bfe63:	and    $0x3f,%eax
  4bfe66:	cmp    %r15,0x10(%rdi,%rax,8)
  4bfe6b:	jne    4c0421 <tomo_multidb2_pad_380927+0x786>
  4bfe71:	mov    0x10(%r15),%rdx
  4bfe75:	mov    %rdx,0x10(%rdi,%rax,8)
  4bfe7a:	jmp    4bf9be <_ZN4tomo9FlatStore15atomic_collapseEmm+0x21e>
  4bfe7f:	mov    %rsi,%rdx
  4bfe82:	shr    $0x4,%rdx
  4bfe86:	test   %rax,%rax
  4bfe89:	jne    4bfdbf <tomo_multidb2_pad_380927+0x124>
  4bfe8f:	jmp    4bfa3c <_ZN4tomo9FlatStore15atomic_collapseEmm+0x29c>
  4bfe94:	mov    0xc8(%r14),%rbx
  4bfe9b:	test   %rbx,%rbx
  4bfe9e:	je     4c0421 <tomo_multidb2_pad_380927+0x786>
  4bfea4:	cmpb   $0x0,0x524(%rbx)
  4bfeab:	je     4c0421 <tomo_multidb2_pad_380927+0x786>
  4bfeb1:	vmovq  %r15,%xmm7
  4bfeb6:	lea    0xa0(%rsp),%rdx
  4bfebe:	lea    0x5c0(%rbx),%rdi
  4bfec5:	vpinsrq $0x1,%r14,%xmm7,%xmm0
  4bfecb:	vmovdqa %xmm0,0xa0(%rsp)
  4bfed4:	mov    0x80(%r15),%esi
  4bfedb:	call   4a8f70 <_ZN4tomo17ForeignReadSafety10close_spanIZNS_9FlatStore28read_local_pending_unpublishERNS_11AtomicEntryEEUljE_EEvjOT_>
  4bfee0:	mov    0x584(%rbx),%eax
  4bfee6:	test   %eax,%eax
  4bfee8:	je     4c10e0 <tomo_multidb2_pad_380927+0x1445>
  4bfeee:	dec    %eax
  4bfef0:	mov    %eax,0x584(%rbx)
  4bfef6:	je     4c051b <tomo_multidb2_pad_380927+0x880>
  4bfefc:	movb   $0x0,0x89(%r15)
  4bff04:	jmp    4bf963 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x1c3>
  4bff09:	mov    0x40(%rsp),%rax
  4bff0e:	mov    0xc8(%rax),%rdx
  4bff15:	mov    (%rdx),%r14
  4bff18:	cmp    %r14,%r15
  4bff1b:	je     4c0550 <tomo_multidb2_pad_380927+0x8b5>
  4bff21:	data16 cs nopw 0x0(%rax,%rax,1)
  4bff2c:	nopl   0x0(%rax)
  4bff30:	mov    0x30(%r14),%rax
  4bff34:	test   %rax,%rax
  4bff37:	je     4bff5e <tomo_multidb2_pad_380927+0x2c3>
  4bff39:	mov    0x40(%r14),%rdx
  4bff3d:	test   %rdx,%rdx
  4bff40:	je     4c0493 <tomo_multidb2_pad_380927+0x7f8>
  4bff46:	movzbl (%rdx),%eax
  4bff49:	test   %al,%al
  4bff4b:	jne    4c014d <tomo_multidb2_pad_380927+0x4b2>
  4bff51:	mov    0x30(%r14),%rax
  4bff55:	test   %rax,%rax
  4bff58:	jne    4c0493 <tomo_multidb2_pad_380927+0x7f8>
  4bff5e:	mov    0x58(%r14),%r13
  4bff62:	xor    %eax,%eax
  4bff64:	cmp    $0xffffffffffffffff,%r13
  4bff68:	cmove  %rax,%r13
  4bff6c:	mov    0x40(%rsp),%rax
  4bff71:	mov    0xc8(%rax),%rax
  4bff78:	mov    (%rax),%rbp
  4bff7b:	mov    %rbp,%r12
  4bff7e:	cmp    %r14,%rbp
  4bff81:	jne    4bffb6 <tomo_multidb2_pad_380927+0x31b>
  4bff83:	jmp    4bfb6a <_ZN4tomo9FlatStore15atomic_collapseEmm+0x3ca>
  4bff88:	nopl   0x0(%rax,%rax,1)
  4bff90:	mov    (%rax),%rax
  4bff93:	cmp    %rax,%r13
  4bff96:	jae    4bffa9 <tomo_multidb2_pad_380927+0x30e>
  4bff98:	cmp    $0xffffffffffffffff,%rax
  4bff9c:	je     4bffa9 <tomo_multidb2_pad_380927+0x30e>
  4bff9e:	mov    0x68(%r12),%rax
  4bffa3:	and    0x68(%r14),%rax
  4bffa7:	jne    4bffd0 <tomo_multidb2_pad_380927+0x335>
  4bffa9:	mov    (%r12),%r12
  4bffad:	cmp    %r14,%r12
  4bffb0:	je     4bfb6a <_ZN4tomo9FlatStore15atomic_collapseEmm+0x3ca>
  4bffb6:	mov    0x30(%r12),%rax
  4bffbb:	test   %rax,%rax
  4bffbe:	jne    4bff90 <tomo_multidb2_pad_380927+0x2f5>
  4bffc0:	mov    0x58(%r12),%rax
  4bffc5:	jmp    4bff93 <tomo_multidb2_pad_380927+0x2f8>
  4bffc7:	nopw   0x0(%rax,%rax,1)
  4bffd0:	mov    0x7c(%r12),%edx
  4bffd5:	test   %edx,%edx
  4bffd7:	je     4bffa9 <tomo_multidb2_pad_380927+0x30e>
  4bffd9:	xor    %ebp,%ebp
  4bffdb:	mov    %r13,0x30(%rsp)
  4bffe0:	mov    %r12,%rbx
  4bffe3:	mov    %rbp,%r13
  4bffe6:	jmp    4c0022 <tomo_multidb2_pad_380927+0x387>
  4bffe8:	nopl   0x0(%rax,%rax,1)
  4bfff0:	mov    0x78(%rbx),%esi
  4bfff3:	mov    %r13d,%ebp
  4bfff6:	add    %r13d,%esi
  4bfff9:	call   53fdf0 <_ZN4tomo22xshard_atomic_key_hashEPKNS_12ScatterStateEj>
  4bfffe:	mov    $0x1,%ecx
  4c0003:	mov    %rax,%r12
  4c0006:	shlx   %rax,%rcx,%rax
  4c000b:	and    0x68(%r14),%rax
  4c000f:	jne    4c03a0 <tomo_multidb2_pad_380927+0x705>
  4c0015:	inc    %r13
  4c0018:	cmp    0x7c(%rbx),%r13d
  4c001c:	jae    4c0385 <tomo_multidb2_pad_380927+0x6ea>
  4c0022:	mov    0x28(%rbx),%rdi
  4c0026:	test   %rdi,%rdi
  4c0029:	jne    4bfff0 <tomo_multidb2_pad_380927+0x355>
  4c002b:	mov    0x60(%rbx),%r12
  4c002f:	mov    $0x1,%ecx
  4c0034:	mov    %r12d,%eax
  4c0037:	shlx   %rax,%rcx,%rax
  4c003c:	and    0x68(%r14),%rax
  4c0040:	je     4c0015 <tomo_multidb2_pad_380927+0x37a>
  4c0042:	mov    0x80(%rbx),%edx
  4c0048:	vmovd  0x84(%rbx),%xmm0
  4c0050:	movzbl 0x8b(%rbx),%eax
  4c0057:	lea    0x90(%rbx,%rdx,8),%rcx
  4c005f:	mov    %rcx,0x10(%rsp)
  4c0064:	vpinsrd $0x1,%eax,%xmm0,%xmm4
  4c006a:	mov    0x7c(%r14),%eax
  4c006e:	vmovq  %xmm4,0x8(%rsp)
  4c0074:	test   %eax,%eax
  4c0076:	je     4c0015 <tomo_multidb2_pad_380927+0x37a>
  4c0078:	xor    %ebp,%ebp
  4c007a:	mov    %r13,0x20(%rsp)
  4c007f:	mov    %rbx,%r13
  4c0082:	mov    %rbp,%rbx
  4c0085:	jmp    4c00b3 <tomo_multidb2_pad_380927+0x418>
  4c0087:	nopw   0x0(%rax,%rax,1)
  4c0090:	mov    0x78(%r14),%esi
  4c0094:	mov    %ebx,%ebp
  4c0096:	add    %ebx,%esi
  4c0098:	call   53fdf0 <_ZN4tomo22xshard_atomic_key_hashEPKNS_12ScatterStateEj>
  4c009d:	cmp    %r12,%rax
  4c00a0:	je     4c0300 <tomo_multidb2_pad_380927+0x665>
  4c00a6:	inc    %rbx
  4c00a9:	cmp    0x7c(%r14),%ebx
  4c00ad:	jae    4c0370 <tomo_multidb2_pad_380927+0x6d5>
  4c00b3:	mov    0x28(%r14),%rdi
  4c00b7:	test   %rdi,%rdi
  4c00ba:	jne    4c0090 <tomo_multidb2_pad_380927+0x3f5>
  4c00bc:	cmp    %r12,0x60(%r14)
  4c00c0:	jne    4c00a6 <tomo_multidb2_pad_380927+0x40b>
  4c00c2:	mov    0x80(%r14),%esi
  4c00c9:	movzbl 0x8b(%r14),%edx
  4c00d1:	mov    0x84(%r14),%eax
  4c00d8:	lea    0x90(%r14,%rsi,8),%rdi
  4c00e0:	vmovd  %eax,%xmm2
  4c00e4:	vpinsrd $0x1,%edx,%xmm2,%xmm1
  4c00ea:	vmovq  %xmm1,%rdx
  4c00ef:	cmp    %rdx,0x8(%rsp)
  4c00f4:	jne    4c00a6 <tomo_multidb2_pad_380927+0x40b>
  4c00f6:	cmp    $0x7,%eax
  4c00f9:	jbe    4c049b <tomo_multidb2_pad_380927+0x800>
  4c00ff:	mov    %eax,%esi
  4c0101:	cmp    $0x20,%eax
  4c0104:	ja     4c04bd <tomo_multidb2_pad_380927+0x822>
  4c010a:	mov    0x10(%rsp),%rcx
  4c010f:	mov    -0x8(%rdi,%rsi,1),%rdx
  4c0114:	mov    (%rdi),%r8
  4c0117:	xor    -0x8(%rcx,%rsi,1),%rdx
  4c011c:	xor    (%rcx),%r8
  4c011f:	or     %r8,%rdx
  4c0122:	cmp    $0x10,%eax
  4c0125:	jbe    4c013f <tomo_multidb2_pad_380927+0x4a4>
  4c0127:	mov    -0x10(%rdi,%rsi,1),%rax
  4c012c:	xor    -0x10(%rcx,%rsi,1),%rax
  4c0131:	mov    0x8(%rdi),%rsi
  4c0135:	xor    0x8(%rcx),%rsi
  4c0139:	or     %rsi,%rax
  4c013c:	or     %rax,%rdx
  4c013f:	test   %rdx,%rdx
  4c0142:	sete   %al
  4c0145:	test   %al,%al
  4c0147:	je     4c00a6 <tomo_multidb2_pad_380927+0x40b>
  4c014d:	mov    0x50(%rsp),%rcx
  4c0152:	movabs $0x555555555555555,%rax
  4c015c:	cmp    %rcx,%rax
  4c015f:	jb     4bfac0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x320>
  4c0165:	mov    0x40(%rsp),%rax
  4c016a:	mov    0x50(%rax),%rdx
  4c016e:	cmp    0x58(%rax),%rdx
  4c0172:	je     4c0178 <tomo_multidb2_pad_380927+0x4dd>
  4c0174:	mov    %rdx,0x58(%rax)
  4c0178:	mov    0x40(%rsp),%rax
  4c017d:	movabs $0xaaaaaaaaaaaaaaab,%rcx
  4c0187:	mov    0x60(%rax),%rax
  4c018b:	mov    %rax,0x8(%rsp)
  4c0190:	sub    %rdx,%rax
  4c0193:	sar    $0x3,%rax
  4c0197:	imul   %rcx,%rax
  4c019b:	mov    0x50(%rsp),%rcx
  4c01a0:	cmp    %rcx,%rax
  4c01a3:	jb     4c1370 <tomo_multidb2_pad_380927+0x16d5>
  4c01a9:	mov    0x40(%rsp),%rax
  4c01ae:	xor    %r10d,%r10d
  4c01b1:	mov    %r10,%r12
  4c01b4:	mov    0xc8(%rax),%rax
  4c01bb:	mov    (%rax),%rbp
  4c01be:	cmp    %rbp,%r15
  4c01c1:	je     4c0a4e <tomo_multidb2_pad_380927+0xdb3>
  4c01c7:	mov    0x7c(%rbp),%eax
  4c01ca:	xor    %ecx,%ecx
  4c01cc:	test   %eax,%eax
  4c01ce:	je     4c0a41 <tomo_multidb2_pad_380927+0xda6>
  4c01d4:	mov    %rcx,%rax
  4c01d7:	mov    %r12,%rcx
  4c01da:	mov    %rax,%r12
  4c01dd:	jmp    4c02c5 <tomo_multidb2_pad_380927+0x62a>
  4c01e2:	data16 cs nopw 0x0(%rax,%rax,1)
  4c01ed:	nopl   (%rax)
  4c01f0:	mov    0x78(%rbp),%esi
  4c01f3:	mov    %rcx,0x8(%rsp)
  4c01f8:	mov    %r12d,%ebx
  4c01fb:	add    %r12d,%esi
  4c01fe:	call   53fdf0 <_ZN4tomo22xshard_atomic_key_hashEPKNS_12ScatterStateEj>
  4c0203:	mov    0x28(%rbp),%rdi
  4c0207:	mov    0x8(%rsp),%rcx
  4c020c:	mov    %rax,%r13
  4c020f:	test   %rdi,%rdi
  4c0212:	je     4c02d6 <tomo_multidb2_pad_380927+0x63b>
  4c0218:	cmpb   $0x0,0x8a(%rbp)
  4c021f:	je     4c0590 <tomo_multidb2_pad_380927+0x8f5>
  4c0225:	cmp    0x7c(%rbp),%ebx
  4c0228:	jae    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c022e:	mov    0x80(%rbp),%edi
  4c0234:	lea    0x90(,%rdi,8),%rsi
  4c023c:	lea    0x0(%rbp,%rsi,1),%rax
  4c0241:	test   %ebx,%ebx
  4c0243:	jne    4c0570 <tomo_multidb2_pad_380927+0x8d5>
  4c0249:	mov    (%rax),%eax
  4c024b:	cmp    %eax,0x84(%rbp)
  4c0251:	jb     4c0421 <tomo_multidb2_pad_380927+0x786>
  4c0257:	movzbl 0x8b(%rbp),%edx
  4c025e:	lea    (%rsi,%rdi,4),%r14
  4c0262:	sub    %ebx,%eax
  4c0264:	add    %rbx,%r14
  4c0267:	vmovd  %eax,%xmm0
  4c026b:	add    %rbp,%r14
  4c026e:	mov    %r13d,%eax
  4c0271:	mov    $0x1,%r8d
  4c0277:	vpinsrd $0x1,%edx,%xmm0,%xmm0
  4c027d:	shlx   %rax,%r8,%r8
  4c0282:	test   %rcx,%r8
  4c0285:	jne    4c06d8 <tomo_multidb2_pad_380927+0xa3d>
  4c028b:	mov    0x40(%rsp),%rax
  4c0290:	mov    0x58(%rax),%rbx
  4c0294:	mov    0x60(%rax),%rdi
  4c0298:	cmp    %rdi,%rbx
  4c029b:	je     4c05b4 <tomo_multidb2_pad_380927+0x919>
  4c02a1:	vmovq  %xmm0,0x10(%rbx)
  4c02a6:	mov    %r13,(%rbx)
  4c02a9:	mov    %r14,0x8(%rbx)
  4c02ad:	add    $0x18,%rbx
  4c02b1:	mov    %rbx,0x58(%rax)
  4c02b5:	or     %r8,%rcx
  4c02b8:	inc    %r12
  4c02bb:	cmp    0x7c(%rbp),%r12d
  4c02bf:	jae    4c0a3e <tomo_multidb2_pad_380927+0xda3>
  4c02c5:	mov    0x28(%rbp),%rdi
  4c02c9:	test   %rdi,%rdi
  4c02cc:	jne    4c01f0 <tomo_multidb2_pad_380927+0x555>
  4c02d2:	mov    0x60(%rbp),%r13
  4c02d6:	mov    0x80(%rbp),%eax
  4c02dc:	vmovd  0x84(%rbp),%xmm0
  4c02e4:	movzbl 0x8b(%rbp),%edx
  4c02eb:	lea    0x90(%rbp,%rax,8),%r14
  4c02f3:	jmp    4c026e <tomo_multidb2_pad_380927+0x5d3>
  4c02f8:	nopl   0x0(%rax,%rax,1)
  4c0300:	mov    0x28(%r14),%rdi
  4c0304:	test   %rdi,%rdi
  4c0307:	je     4c00c2 <tomo_multidb2_pad_380927+0x427>
  4c030d:	cmpb   $0x0,0x8a(%r14)
  4c0315:	je     4c0430 <tomo_multidb2_pad_380927+0x795>
  4c031b:	cmp    0x7c(%r14),%ebp
  4c031f:	jae    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c0325:	mov    0x80(%r14),%edi
  4c032c:	lea    0x90(,%rdi,8),%rsi
  4c0334:	lea    (%r14,%rsi,1),%rax
  4c0338:	test   %ebp,%ebp
  4c033a:	jne    4c0410 <tomo_multidb2_pad_380927+0x775>
  4c0340:	mov    (%rax),%eax
  4c0342:	cmp    %eax,0x84(%r14)
  4c0349:	jb     4c0421 <tomo_multidb2_pad_380927+0x786>
  4c034f:	lea    (%rsi,%rdi,4),%rdi
  4c0353:	movzbl 0x8b(%r14),%edx
  4c035b:	sub    %ebp,%eax
  4c035d:	add    %rbp,%rdi
  4c0360:	add    %r14,%rdi
  4c0363:	jmp    4c00e0 <tomo_multidb2_pad_380927+0x445>
  4c0368:	nopl   0x0(%rax,%rax,1)
  4c0370:	mov    %r13,%rbx
  4c0373:	mov    0x20(%rsp),%r13
  4c0378:	inc    %r13
  4c037b:	cmp    0x7c(%rbx),%r13d
  4c037f:	jb     4c0022 <tomo_multidb2_pad_380927+0x387>
  4c0385:	mov    0x30(%rsp),%r13
  4c038a:	mov    %rbx,%r12
  4c038d:	jmp    4bffa9 <tomo_multidb2_pad_380927+0x30e>
  4c0392:	data16 cs nopw 0x0(%rax,%rax,1)
  4c039d:	nopl   (%rax)
  4c03a0:	mov    0x28(%rbx),%rdi
  4c03a4:	test   %rdi,%rdi
  4c03a7:	je     4c0042 <tomo_multidb2_pad_380927+0x3a7>
  4c03ad:	cmpb   $0x0,0x8a(%rbx)
  4c03b4:	je     4c0470 <tomo_multidb2_pad_380927+0x7d5>
  4c03ba:	cmp    0x7c(%rbx),%r13d
  4c03be:	jae    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c03c0:	mov    0x80(%rbx),%ecx
  4c03c6:	lea    0x90(,%rcx,8),%rdx
  4c03ce:	lea    (%rbx,%rdx,1),%rax
  4c03d2:	test   %r13d,%r13d
  4c03d5:	jne    4c0450 <tomo_multidb2_pad_380927+0x7b5>
  4c03d7:	mov    (%rax),%esi
  4c03d9:	cmp    %esi,0x84(%rbx)
  4c03df:	jb     4c0421 <tomo_multidb2_pad_380927+0x786>
  4c03e1:	lea    (%rdx,%rcx,4),%rdx
  4c03e5:	mov    %ebp,%ecx
  4c03e7:	sub    %ebp,%esi
  4c03e9:	movzbl 0x8b(%rbx),%eax
  4c03f0:	add    %rcx,%rdx
  4c03f3:	vmovd  %esi,%xmm0
  4c03f7:	lea    (%rbx,%rdx,1),%rcx
  4c03fb:	mov    %rcx,0x10(%rsp)
  4c0400:	jmp    4c0064 <tomo_multidb2_pad_380927+0x3c9>
  4c0405:	data16 cs nopw 0x0(%rax,%rax,1)
  4c0410:	lea    -0x1(%rbp),%edx
  4c0413:	mov    (%rax,%rdx,4),%ebp
  4c0416:	mov    (%rax,%rbx,4),%eax
  4c0419:	cmp    %ebp,%eax
  4c041b:	jae    4c0342 <tomo_multidb2_pad_380927+0x6a7>
  4c0421:	call   2c1b0 <abort@plt>
  4c0426:	cs nopw 0x0(%rax,%rax,1)
  4c0430:	mov    0x78(%r14),%esi
  4c0434:	add    %ebp,%esi
  4c0436:	call   53fe30 <_ZN4tomo23xshard_atomic_key_sliceEPKNS_12ScatterStateEj>
  4c043b:	mov    %rax,%rdi
  4c043e:	mov    %edx,%eax
  4c0440:	shr    $0x20,%rdx
  4c0444:	jmp    4c00e0 <tomo_multidb2_pad_380927+0x445>
  4c0449:	nopl   0x0(%rax)
  4c0450:	lea    -0x1(%r13),%esi
  4c0454:	mov    (%rax,%rsi,4),%ebp
  4c0457:	mov    (%rax,%r13,4),%esi
  4c045b:	cmp    %ebp,%esi
  4c045d:	jae    4c03d9 <tomo_multidb2_pad_380927+0x73e>
  4c0463:	jmp    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c0465:	data16 cs nopw 0x0(%rax,%rax,1)
  4c0470:	mov    0x78(%rbx),%esi
  4c0473:	add    %r13d,%esi
  4c0476:	call   53fe30 <_ZN4tomo23xshard_atomic_key_sliceEPKNS_12ScatterStateEj>
  4c047b:	mov    %rax,%rcx
  4c047e:	mov    %rdx,%rax
  4c0481:	vmovd  %edx,%xmm0
  4c0485:	shr    $0x20,%rax
  4c0489:	mov    %rcx,0x10(%rsp)
  4c048e:	jmp    4c0064 <tomo_multidb2_pad_380927+0x3c9>
  4c0493:	mov    (%rax),%r13
  4c0496:	jmp    4bff62 <tomo_multidb2_pad_380927+0x2c7>
  4c049b:	cmp    $0x3,%eax
  4c049e:	jbe    4c04d4 <tomo_multidb2_pad_380927+0x839>
  4c04a0:	mov    0x10(%rsp),%rcx
  4c04a5:	mov    -0x4(%rdi,%rax,1),%edx
  4c04a9:	xor    -0x4(%rcx,%rax,1),%edx
  4c04ad:	mov    %edx,%eax
  4c04af:	mov    (%rdi),%edx
  4c04b1:	xor    (%rcx),%edx
  4c04b3:	or     %edx,%eax
  4c04b5:	sete   %al
  4c04b8:	jmp    4c0145 <tomo_multidb2_pad_380927+0x4aa>
  4c04bd:	mov    %rsi,%rdx
  4c04c0:	mov    0x10(%rsp),%rsi
  4c04c5:	call   2c8a0 <memcmp@plt>
  4c04ca:	test   %eax,%eax
  4c04cc:	sete   %al
  4c04cf:	jmp    4c0145 <tomo_multidb2_pad_380927+0x4aa>
  4c04d4:	test   %eax,%eax
  4c04d6:	je     4c014d <tomo_multidb2_pad_380927+0x4b2>
  4c04dc:	mov    0x10(%rsp),%rcx
  4c04e1:	movzbl (%rcx),%ecx
  4c04e4:	cmp    %cl,(%rdi)
  4c04e6:	jne    4c00a6 <tomo_multidb2_pad_380927+0x40b>
  4c04ec:	mov    0x10(%rsp),%rcx
  4c04f1:	mov    %eax,%edx
  4c04f3:	shr    $1,%edx
  4c04f5:	movzbl (%rcx,%rdx,1),%ecx
  4c04f9:	cmp    %cl,(%rdi,%rdx,1)
  4c04fc:	jne    4c00a6 <tomo_multidb2_pad_380927+0x40b>
  4c0502:	mov    0x10(%rsp),%rcx
  4c0507:	dec    %eax
  4c0509:	movzbl (%rcx,%rax,1),%ecx
  4c050d:	cmp    %cl,(%rdi,%rax,1)
  4c0510:	jne    4c00a6 <tomo_multidb2_pad_380927+0x40b>
  4c0516:	jmp    4c014d <tomo_multidb2_pad_380927+0x4b2>
  4c051b:	mov    0xc5d0(%rbx),%rax
  4c0522:	cmp    $0xffffffffffffffff,%rax
  4c0526:	je     4bfefc <tomo_multidb2_pad_380927+0x261>
  4c052c:	lock btrq $0x1,0x548(%rbx)
  4c0536:	jb     4bfefc <tomo_multidb2_pad_380927+0x261>
  4c053c:	jmp    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c0541:	data16 cs nopw 0x0(%rax,%rax,1)
  4c054c:	nopl   0x0(%rax)
  4c0550:	mov    0x50(%rsp),%rax
  4c0555:	add    %rax,0x528(%rdx)
  4c055c:	jmp    4bfa62 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2c2>
  4c0561:	data16 cs nopw 0x0(%rax,%rax,1)
  4c056c:	nopl   0x0(%rax)
  4c0570:	lea    -0x1(%rbx),%edx
  4c0573:	mov    (%rax,%rdx,4),%ebx
  4c0576:	mov    (%rax,%r12,4),%eax
  4c057a:	cmp    %ebx,%eax
  4c057c:	jae    4c024b <tomo_multidb2_pad_380927+0x5b0>
  4c0582:	jmp    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c0587:	nopw   0x0(%rax,%rax,1)
  4c0590:	mov    0x78(%rbp),%esi
  4c0593:	mov    %rcx,0x8(%rsp)
  4c0598:	add    %ebx,%esi
  4c059a:	call   53fe30 <_ZN4tomo23xshard_atomic_key_sliceEPKNS_12ScatterStateEj>
  4c059f:	mov    0x8(%rsp),%rcx
  4c05a4:	vmovd  %edx,%xmm0
  4c05a8:	mov    %rax,%r14
  4c05ab:	shr    $0x20,%rdx
  4c05af:	jmp    4c026e <tomo_multidb2_pad_380927+0x5d3>
  4c05b4:	mov    0x40(%rsp),%rax
  4c05b9:	mov    %rbx,%rsi
  4c05bc:	movabs $0xaaaaaaaaaaaaaaab,%rdx
  4c05c6:	mov    0x50(%rax),%r9
  4c05ca:	sub    %r9,%rsi
  4c05cd:	mov    %rsi,%rax
  4c05d0:	sar    $0x3,%rax
  4c05d4:	imul   %rdx,%rax
  4c05d8:	movabs $0x555555555555555,%rdx
  4c05e2:	cmp    %rdx,%rax
  4c05e5:	je     4c1801 <tomo_multidb2_pad_380927+0x1b66>
  4c05eb:	cmp    %r9,%rbx
  4c05ee:	je     4c099d <tomo_multidb2_pad_380927+0xd02>
  4c05f4:	lea    (%rax,%rax,1),%rdx
  4c05f8:	cmp    %rax,%rdx
  4c05fb:	jb     4c0c25 <tomo_multidb2_pad_380927+0xf8a>
  4c0601:	test   %rdx,%rdx
  4c0604:	jne    4c1e53 <tomo_multidb2_pad_380927+0x21b8>
  4c060a:	xor    %r10d,%r10d
  4c060d:	xor    %edx,%edx
  4c060f:	vmovq  %xmm0,0x10(%rsi)
  4c0614:	mov    %r13,(%rsi)
  4c0617:	mov    %r14,0x8(%rsi)
  4c061b:	vpxor  %xmm0,%xmm0,%xmm0
  4c061f:	mov    %r9,%rax
  4c0622:	data16 cs nopw 0x0(%rax,%rax,1)
  4c062d:	nopl   (%rax)
  4c0630:	vmovdqu (%rax),%xmm6
  4c0634:	mov    0x10(%rax),%rsi
  4c0638:	add    $0x18,%rax
  4c063c:	add    $0x18,%rdx
  4c0640:	mov    %rsi,-0x8(%rdx)
  4c0644:	vmovdqu %xmm6,-0x18(%rdx)
  4c0649:	cmp    %rax,%rbx
  4c064c:	jne    4c0630 <tomo_multidb2_pad_380927+0x995>
  4c064e:	lea    -0x18(%rbx),%rax
  4c0652:	movabs $0xaaaaaaaaaaaaaab,%rdx
  4c065c:	sub    %r9,%rax
  4c065f:	shr    $0x3,%rax
  4c0663:	imul   %rdx,%rax
  4c0667:	movabs $0x1fffffffffffffff,%rdx
  4c0671:	and    %rdx,%rax
  4c0674:	vmovq  %xmm0,%rdx
  4c0679:	lea    (%rax,%rax,2),%rax
  4c067d:	lea    0x30(%rdx,%rax,8),%rax
  4c0682:	vpinsrq $0x1,%rax,%xmm0,%xmm0
  4c0688:	test   %r9,%r9
  4c068b:	je     4c06c5 <tomo_multidb2_pad_380927+0xa2a>
  4c068d:	sub    %r9,%rdi
  4c0690:	vmovdqa %xmm0,0x20(%rsp)
  4c0696:	mov    %rcx,0x30(%rsp)
  4c069b:	mov    %r10,0x10(%rsp)
  4c06a0:	mov    %rdi,%rsi
  4c06a3:	mov    %r9,%rdi
  4c06a6:	mov    %r8,0x8(%rsp)
  4c06ab:	call   2be30 <_ZdlPvm@plt>
  4c06b0:	vmovdqa 0x20(%rsp),%xmm0
  4c06b6:	mov    0x30(%rsp),%rcx
  4c06bb:	mov    0x10(%rsp),%r10
  4c06c0:	mov    0x8(%rsp),%r8
  4c06c5:	mov    0x40(%rsp),%rax
  4c06ca:	vmovdqu %xmm0,0x50(%rax)
  4c06cf:	mov    %r10,0x60(%rax)
  4c06d3:	jmp    4c02b5 <tomo_multidb2_pad_380927+0x61a>
  4c06d8:	mov    0x40(%rsp),%rax
  4c06dd:	mov    0x50(%rax),%rbx
  4c06e1:	mov    0x58(%rax),%r9
  4c06e5:	cmp    %rbx,%r9
  4c06e8:	je     4c028b <tomo_multidb2_pad_380927+0x5f0>
  4c06ee:	mov    %r12,%rax
  4c06f1:	vmovq  %xmm0,%r10
  4c06f6:	mov    %r14,%rsi
  4c06f9:	mov    %r9,%r12
  4c06fc:	mov    %r10,%r14
  4c06ff:	mov    %rax,%r9
  4c0702:	jmp    4c0711 <tomo_multidb2_pad_380927+0xa76>
  4c0704:	add    $0x18,%rbx
  4c0708:	cmp    %rbx,%r12
  4c070b:	je     4c0992 <tomo_multidb2_pad_380927+0xcf7>
  4c0711:	cmp    %r13,(%rbx)
  4c0714:	jne    4c0704 <tomo_multidb2_pad_380927+0xa69>
  4c0716:	cmp    %r14,0x10(%rbx)
  4c071a:	jne    4c0704 <tomo_multidb2_pad_380927+0xa69>
  4c071c:	mov    0x10(%rbx),%eax
  4c071f:	mov    0x8(%rbx),%rdi
  4c0723:	cmp    $0x7,%eax
  4c0726:	jbe    4c0c70 <tomo_multidb2_pad_380927+0xfd5>
  4c072c:	mov    %eax,%r10d
  4c072f:	cmp    $0x20,%eax
  4c0732:	ja     4c0c9e <tomo_multidb2_pad_380927+0x1003>
  4c0738:	mov    -0x8(%rdi,%r10,1),%rdx
  4c073d:	mov    (%rdi),%r11
  4c0740:	xor    -0x8(%rsi,%r10,1),%rdx
  4c0745:	xor    (%rsi),%r11
  4c0748:	or     %r11,%rdx
  4c074b:	cmp    $0x10,%eax
  4c074e:	jbe    4c0768 <tomo_multidb2_pad_380927+0xacd>
  4c0750:	mov    -0x10(%rdi,%r10,1),%rax
  4c0755:	mov    0x8(%rdi),%rdi
  4c0759:	xor    -0x10(%rsi,%r10,1),%rax
  4c075e:	xor    0x8(%rsi),%rdi
  4c0762:	or     %rdi,%rax
  4c0765:	or     %rax,%rdx
  4c0768:	test   %rdx,%rdx
  4c076b:	sete   %al
  4c076e:	test   %al,%al
  4c0770:	je     4c0704 <tomo_multidb2_pad_380927+0xa69>
  4c0772:	mov    0x50(%rsp),%rax
  4c0777:	mov    $0x8,%ebx
  4c077c:	lea    (%rax,%rax,1),%rdx
  4c0780:	mov    $0x1d,%eax
  4c0785:	jmp    4c0792 <tomo_multidb2_pad_380927+0xaf7>
  4c0787:	add    %rbx,%rbx
  4c078a:	dec    %eax
  4c078c:	je     4bfac0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x320>
  4c0792:	cmp    %rdx,%rbx
  4c0795:	jb     4c0787 <tomo_multidb2_pad_380927+0xaec>
  4c0797:	mov    0x50(%rsp),%rcx
  4c079c:	movabs $0x111111111111111,%rax
  4c07a6:	cmp    %rcx,%rax
  4c07a9:	jb     4bfac0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x320>
  4c07af:	mov    0x40(%rsp),%rcx
  4c07b4:	mov    0x8(%rcx),%rax
  4c07b8:	cmp    0x10(%rcx),%rax
  4c07bc:	je     4c07c2 <tomo_multidb2_pad_380927+0xb27>
  4c07be:	mov    %rax,0x10(%rcx)
  4c07c2:	mov    0x40(%rsp),%r14
  4c07c7:	mov    0x50(%rsp),%rsi
  4c07cc:	lea    0x8(%r14),%rdi
  4c07d0:	call   4b48a0 <_ZNSt6vectorIN4tomo17AtomicCollapseKeyESaIS1_EE7reserveEm>
  4c07d5:	xor    %r11d,%r11d
  4c07d8:	xor    %ebp,%ebp
  4c07da:	lea    0xa0(%rsp),%rdx
  4c07e2:	lea    0x20(%r14),%rdi
  4c07e6:	mov    %rbx,%rsi
  4c07e9:	mov    %r11,0xa0(%rsp)
  4c07f1:	mov    %ebp,0xa8(%rsp)
  4c07f8:	mov    %rdx,0x8(%rsp)
  4c07fd:	call   4bce30 <_ZNSt6vectorIN4tomo18AtomicCollapseSlotESaIS1_EE14_M_fill_assignEmRKS1_>
  4c0802:	mov    0x38(%r14),%rax
  4c0806:	cmp    0x40(%r14),%rax
  4c080a:	je     4c0810 <tomo_multidb2_pad_380927+0xb75>
  4c080c:	mov    %rax,0x40(%r14)
  4c0810:	mov    0x50(%rsp),%r14
  4c0815:	mov    0x40(%rsp),%r13
  4c081a:	mov    %r14,%rsi
  4c081d:	lea    0x38(%r13),%rbp
  4c0821:	shr    $1,%rsi
  4c0824:	mov    %rbp,%rdi
  4c0827:	add    %r14,%rsi
  4c082a:	call   4b4990 <_ZNSt6vectorIPN4tomo5KvObjESaIS2_EE7reserveEm>
  4c082f:	mov    0xc8(%r13),%rax
  4c0836:	mov    %r13,0x98(%rsp)
  4c083e:	dec    %ebx
  4c0840:	lea    0x8c(%rsp),%rdx
  4c0848:	mov    %ebx,0x8c(%rsp)
  4c084f:	mov    %rdx,0x90(%rsp)
  4c0857:	mov    (%rax),%r13
  4c085a:	add    %r14,0x530(%rax)
  4c0861:	lea    0x90(%rsp),%r14
  4c0869:	cmp    %r13,%r15
  4c086c:	je     4c1698 <tomo_multidb2_pad_380927+0x19fd>
  4c0872:	mov    0x7c(%r13),%r10d
  4c0876:	xor    %ebx,%ebx
  4c0878:	test   %r10d,%r10d
  4c087b:	jne    4c0978 <tomo_multidb2_pad_380927+0xcdd>
  4c0881:	jmp    4c113a <tomo_multidb2_pad_380927+0x149f>
  4c0886:	cs nopw 0x0(%rax,%rax,1)
  4c0890:	mov    0x78(%r13),%esi
  4c0894:	add    %ebx,%esi
  4c0896:	call   53fdf0 <_ZN4tomo22xshard_atomic_key_hashEPKNS_12ScatterStateEj>
  4c089b:	mov    %rax,%r12
  4c089e:	mov    0x10(%rsp),%esi
  4c08a2:	mov    %r13,%rdi
  4c08a5:	call   481da0 <_ZNK4tomo9FlatStore16atomic_entry_keyERKNS_11AtomicEntryEj.isra.0>
  4c08aa:	mov    0x90(%r13,%rbx,8),%r8
  4c08b2:	mov    %r12,%rsi
  4c08b5:	mov    %r14,%rdi
  4c08b8:	mov    %rdx,%rcx
  4c08bb:	mov    %rax,%rdx
  4c08be:	call   4a3f00 <_ZZN4tomo9FlatStore20atomic_collapse_implILb0EEEbmmENKUlmNS_5SliceEPNS_5KvObjEE_clEmS2_S4_>
  4c08c3:	mov    0x40(%rsp),%rcx
  4c08c8:	mov    %eax,%eax
  4c08ca:	imul   $0x78,%rax,%rax
  4c08ce:	add    0x8(%rcx),%rax
  4c08d2:	mov    0x20(%rax),%rcx
  4c08d6:	test   %rcx,%rcx
  4c08d9:	je     4c0967 <tomo_multidb2_pad_380927+0xccc>
  4c08df:	mov    0x30(%rcx),%rdx
  4c08e3:	mov    0x90(%r13,%rbx,8),%rdi
  4c08eb:	test   %rdx,%rdx
  4c08ee:	je     4c0911 <tomo_multidb2_pad_380927+0xc76>
  4c08f0:	mov    0x40(%rcx),%rsi
  4c08f4:	test   %rsi,%rsi
  4c08f7:	je     4c1649 <tomo_multidb2_pad_380927+0x19ae>
  4c08fd:	movzbl (%rsi),%edx
  4c0900:	test   %dl,%dl
  4c0902:	jne    4c0967 <tomo_multidb2_pad_380927+0xccc>
  4c0904:	mov    0x30(%rcx),%rdx
  4c0908:	test   %rdx,%rdx
  4c090b:	jne    4c1649 <tomo_multidb2_pad_380927+0x19ae>
  4c0911:	mov    0x58(%rcx),%rdx
  4c0915:	xor    %esi,%esi
  4c0917:	cmp    $0xffffffffffffffff,%rdx
  4c091b:	vmovq  0x50(%rcx),%xmm0
  4c0920:	cmove  %rsi,%rdx
  4c0924:	cmpb   $0x0,0x70(%rax)
  4c0928:	je     4c0940 <tomo_multidb2_pad_380927+0xca5>
  4c092a:	vmovq  %xmm0,%rcx
  4c092f:	cmp    %rcx,0x60(%rax)
  4c0933:	jne    4c0940 <tomo_multidb2_pad_380927+0xca5>
  4c0935:	mov    0x68(%rax),%rcx
  4c0939:	cmp    %rcx,%rdx
  4c093c:	cmovb  %rcx,%rdx
  4c0940:	cmpb   $0x0,0x58(%rax)
  4c0944:	vpinsrq $0x1,%rdx,%xmm0,%xmm0
  4c094a:	movb   $0x1,0x70(%rax)
  4c094e:	vmovdqu %xmm0,0x60(%rax)
  4c0953:	je     4c095b <tomo_multidb2_pad_380927+0xcc0>
  4c0955:	cmp    0x50(%rax),%rdx
  4c0959:	jb     4c0967 <tomo_multidb2_pad_380927+0xccc>
  4c095b:	mov    %rdi,0x28(%rax)
  4c095f:	mov    %rdx,0x50(%rax)
  4c0963:	movb   $0x1,0x58(%rax)
  4c0967:	inc    %rbx
  4c096a:	mov    %r13,0x20(%rax)
  4c096e:	cmp    0x7c(%r13),%ebx
  4c0972:	jae    4c113a <tomo_multidb2_pad_380927+0x149f>
  4c0978:	mov    0x28(%r13),%rdi
  4c097c:	mov    %ebx,0x10(%rsp)
  4c0980:	test   %rdi,%rdi
  4c0983:	jne    4c0890 <tomo_multidb2_pad_380927+0xbf5>
  4c0989:	mov    0x60(%r13),%r12
  4c098d:	jmp    4c089e <tomo_multidb2_pad_380927+0xc03>
  4c0992:	mov    %rsi,%r14
  4c0995:	mov    %r9,%r12
  4c0998:	jmp    4c028b <tomo_multidb2_pad_380927+0x5f0>
  4c099d:	add    $0x1,%rax
  4c09a1:	jb     4c0c25 <tomo_multidb2_pad_380927+0xf8a>
  4c09a7:	movabs $0x555555555555555,%rdx
  4c09b1:	cmp    %rdx,%rax
  4c09b4:	cmova  %rdx,%rax
  4c09b8:	lea    (%rax,%rax,2),%r10
  4c09bc:	shl    $0x3,%r10
  4c09c0:	vmovq  %xmm0,0x58(%rsp)
  4c09c6:	mov    %rcx,0x60(%rsp)
  4c09cb:	mov    %rsi,0x30(%rsp)
  4c09d0:	mov    %r9,0x20(%rsp)
  4c09d5:	mov    %r10,%rdi
  4c09d8:	mov    %r8,0x10(%rsp)
  4c09dd:	mov    %r10,0x8(%rsp)
  4c09e2:	call   2c120 <_Znwm@plt>
  4c09e7:	vmovq  0x58(%rsp),%xmm0
  4c09ed:	mov    0x8(%rsp),%r10
  4c09f2:	mov    0x30(%rsp),%rsi
  4c09f7:	mov    %rax,%rdx
  4c09fa:	mov    0x40(%rsp),%rax
  4c09ff:	mov    0x20(%rsp),%r9
  4c0a04:	mov    0x10(%rsp),%r8
  4c0a09:	mov    0x60(%rsp),%rcx
  4c0a0e:	add    %rdx,%rsi
  4c0a11:	add    %rdx,%r10
  4c0a14:	mov    0x60(%rax),%rdi
  4c0a18:	mov    %rdx,%rax
  4c0a1b:	vmovq  %xmm0,0x10(%rsi)
  4c0a20:	mov    %r13,(%rsi)
  4c0a23:	add    $0x18,%rax
  4c0a27:	cmp    %r9,%rbx
  4c0a2a:	vmovq  %rdx,%xmm0
  4c0a2f:	mov    %r14,0x8(%rsi)
  4c0a33:	jne    4c061f <tomo_multidb2_pad_380927+0x984>
  4c0a39:	jmp    4c0682 <tomo_multidb2_pad_380927+0x9e7>
  4c0a3e:	mov    %rcx,%r12
  4c0a41:	mov    0x0(%rbp),%rbp
  4c0a45:	cmp    %rbp,%r15
  4c0a48:	jne    4c01c7 <tomo_multidb2_pad_380927+0x52c>
  4c0a4e:	mov    0x40(%rsp),%rbx
  4c0a53:	mov    %r15,%rsi
  4c0a56:	mov    %rbx,%rdi
  4c0a59:	call   4a6d10 <_ZN4tomo9FlatStore32atomic_prepare_rollback_capacityEPNS_11AtomicEntryE>
  4c0a5e:	test   %al,%al
  4c0a60:	je     4bfac0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x320>
  4c0a66:	mov    0xc8(%rbx),%rax
  4c0a6d:	mov    0x50(%rsp),%rdx
  4c0a72:	mov    %rbx,%rcx
  4c0a75:	xor    %ebx,%ebx
  4c0a77:	mov    (%rax),%r14
  4c0a7a:	add    %rdx,0x530(%rax)
  4c0a81:	cmp    %r14,%r15
  4c0a84:	je     4c1081 <tomo_multidb2_pad_380927+0x13e6>
  4c0a8a:	mov    %r15,0x60(%rsp)
  4c0a8f:	mov    %r14,%r13
  4c0a92:	mov    %rcx,%r15
  4c0a95:	mov    %r13,%r14
  4c0a98:	xor    %r9d,%r9d
  4c0a9b:	mov    0x0(%r13),%r13
  4c0a9f:	cmpq   $0x0,0x30(%r14)
  4c0aa4:	je     4c0ab8 <tomo_multidb2_pad_380927+0xe1d>
  4c0aa6:	mov    0x40(%r14),%rdx
  4c0aaa:	test   %rdx,%rdx
  4c0aad:	je     4c0ab8 <tomo_multidb2_pad_380927+0xe1d>
  4c0aaf:	movzbl (%rdx),%edx
  4c0ab2:	test   %dl,%dl
  4c0ab4:	setne  %r9b
  4c0ab8:	mov    0x7c(%r14),%eax
  4c0abc:	test   %eax,%eax
  4c0abe:	je     4c0f74 <tomo_multidb2_pad_380927+0x12d9>
  4c0ac4:	movq   $0x0,0x30(%rsp)
  4c0acd:	mov    %r13,0x70(%rsp)
  4c0ad2:	mov    %r9b,0x6f(%rsp)
  4c0ad7:	mov    %rbx,0x78(%rsp)
  4c0adc:	jmp    4c0bea <tomo_multidb2_pad_380927+0xf4f>
  4c0ae1:	mov    0x30(%rsp),%rax
  4c0ae6:	mov    0x78(%r14),%esi
  4c0aea:	add    %eax,%esi
  4c0aec:	mov    %eax,%ebp
  4c0aee:	call   53fdf0 <_ZN4tomo22xshard_atomic_key_hashEPKNS_12ScatterStateEj>
  4c0af3:	mov    0x28(%r14),%rdi
  4c0af7:	mov    %rax,%rbx
  4c0afa:	test   %rdi,%rdi
  4c0afd:	je     4c0bfb <tomo_multidb2_pad_380927+0xf60>
  4c0b03:	cmpb   $0x0,0x8a(%r14)
  4c0b0b:	je     4c0c50 <tomo_multidb2_pad_380927+0xfb5>
  4c0b11:	cmp    0x7c(%r14),%ebp
  4c0b15:	jae    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c0b1b:	mov    0x80(%r14),%edi
  4c0b22:	lea    0x90(,%rdi,8),%rsi
  4c0b2a:	lea    (%r14,%rsi,1),%rax
  4c0b2e:	test   %ebp,%ebp
  4c0b30:	jne    4c0c34 <tomo_multidb2_pad_380927+0xf99>
  4c0b36:	mov    (%rax),%eax
  4c0b38:	cmp    %eax,0x84(%r14)
  4c0b3f:	jb     4c0421 <tomo_multidb2_pad_380927+0x786>
  4c0b45:	movzbl 0x8b(%r14),%ecx
  4c0b4d:	sub    %ebp,%eax
  4c0b4f:	lea    (%rsi,%rdi,4),%r12
  4c0b53:	vmovd  %eax,%xmm0
  4c0b57:	mov    %ebp,%eax
  4c0b59:	add    %rax,%r12
  4c0b5c:	lea    (%r14,%r12,1),%rax
  4c0b60:	mov    %rax,0x20(%rsp)
  4c0b65:	mov    0x30(%rsp),%rax
  4c0b6a:	cmpb   $0x0,0x6f(%rsp)
  4c0b6f:	vpinsrd $0x1,%ecx,%xmm0,%xmm7
  4c0b75:	vmovq  %xmm7,%rcx
  4c0b7a:	vmovq  %xmm7,0x58(%rsp)
  4c0b80:	mov    0x90(%r14,%rax,8),%rax
  4c0b88:	mov    %rax,0x8(%rsp)
  4c0b8d:	jne    4c0ce4 <tomo_multidb2_pad_380927+0x1049>
  4c0b93:	mov    0x8(%rsp),%rax
  4c0b98:	test   %rax,%rax
  4c0b9b:	je     4c0bc7 <tomo_multidb2_pad_380927+0xf2c>
  4c0b9d:	mov    %rax,%rdi
  4c0ba0:	call   491030 <_ZN4tomo10kvobj_sizeEPKNS_5KvObjE>
  4c0ba5:	mov    (%r15),%rcx
  4c0ba8:	mov    %rcx,%rdx
  4c0bab:	sub    %rax,%rdx
  4c0bae:	cmp    %rax,%rcx
  4c0bb1:	jb     4c1600 <tomo_multidb2_pad_380927+0x1965>
  4c0bb7:	mov    0x8(%rsp),%rsi
  4c0bbc:	mov    %r15,%rdi
  4c0bbf:	mov    %rdx,(%r15)
  4c0bc2:	call   494730 <_ZN4tomo9FlatStore19retire_detached_objEPNS_5KvObjE>
  4c0bc7:	mov    0x30(%rsp),%rax
  4c0bcc:	movq   $0x0,0x90(%r14,%rax,8)
  4c0bd8:	inc    %rax
  4c0bdb:	cmp    0x7c(%r14),%eax
  4c0bdf:	jae    4c0f60 <tomo_multidb2_pad_380927+0x12c5>
  4c0be5:	mov    %rax,0x30(%rsp)
  4c0bea:	mov    0x28(%r14),%rdi
  4c0bee:	test   %rdi,%rdi
  4c0bf1:	jne    4c0ae1 <tomo_multidb2_pad_380927+0xe46>
  4c0bf7:	mov    0x60(%r14),%rbx
  4c0bfb:	mov    0x80(%r14),%eax
  4c0c02:	vmovd  0x84(%r14),%xmm0
  4c0c0b:	movzbl 0x8b(%r14),%ecx
  4c0c13:	lea    0x90(%r14,%rax,8),%rax
  4c0c1b:	mov    %rax,0x20(%rsp)
  4c0c20:	jmp    4c0b65 <tomo_multidb2_pad_380927+0xeca>
  4c0c25:	movabs $0x7ffffffffffffff8,%r10
  4c0c2f:	jmp    4c09c0 <tomo_multidb2_pad_380927+0xd25>
  4c0c34:	mov    0x30(%rsp),%rcx
  4c0c39:	lea    -0x1(%rbp),%edx
  4c0c3c:	mov    (%rax,%rdx,4),%ebp
  4c0c3f:	mov    (%rax,%rcx,4),%eax
  4c0c42:	cmp    %ebp,%eax
  4c0c44:	jae    4c0b38 <tomo_multidb2_pad_380927+0xe9d>
  4c0c4a:	jmp    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c0c4f:	nop
  4c0c50:	mov    0x78(%r14),%esi
  4c0c54:	add    %ebp,%esi
  4c0c56:	call   53fe30 <_ZN4tomo23xshard_atomic_key_sliceEPKNS_12ScatterStateEj>
  4c0c5b:	mov    %rdx,%rcx
  4c0c5e:	vmovd  %edx,%xmm0
  4c0c62:	mov    %rax,0x20(%rsp)
  4c0c67:	shr    $0x20,%rcx
  4c0c6b:	jmp    4c0b65 <tomo_multidb2_pad_380927+0xeca>
  4c0c70:	cmp    $0x3,%eax
  4c0c73:	jbe    4c1100 <tomo_multidb2_pad_380927+0x1465>
  4c0c79:	mov    -0x4(%rdi,%rax,1),%edx
  4c0c7d:	xor    -0x4(%rsi,%rax,1),%edx
  4c0c81:	mov    %edx,%eax
  4c0c83:	mov    (%rdi),%edx
  4c0c85:	xor    (%rsi),%edx
  4c0c87:	or     %edx,%eax
  4c0c89:	sete   %al
  4c0c8c:	jmp    4c076e <tomo_multidb2_pad_380927+0xad3>
  4c0c91:	movq   $0x0,0x8(%rdx)
  4c0c99:	jmp    4bfa76 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2d6>
  4c0c9e:	mov    %r10,%rdx
  4c0ca1:	vmovq  %xmm0,0x58(%rsp)
  4c0ca7:	mov    %r9,0x30(%rsp)
  4c0cac:	mov    %r8,0x20(%rsp)
  4c0cb1:	mov    %rcx,0x10(%rsp)
  4c0cb6:	mov    %rsi,0x8(%rsp)
  4c0cbb:	call   2c8a0 <memcmp@plt>
  4c0cc0:	vmovq  0x58(%rsp),%xmm0
  4c0cc6:	test   %eax,%eax
  4c0cc8:	mov    0x8(%rsp),%rsi
  4c0ccd:	mov    0x10(%rsp),%rcx
  4c0cd2:	mov    0x20(%rsp),%r8
  4c0cd7:	mov    0x30(%rsp),%r9
  4c0cdc:	sete   %al
  4c0cdf:	jmp    4c076e <tomo_multidb2_pad_380927+0xad3>
  4c0ce4:	test   %rax,%rax
  4c0ce7:	je     4c163b <tomo_multidb2_pad_380927+0x19a0>
  4c0ced:	mov    0x8(%rsp),%rax
  4c0cf2:	movzbl 0x2(%rax),%eax
  4c0cf6:	test   $0x1,%al
  4c0cf8:	je     4c0d1f <tomo_multidb2_pad_380927+0x1084>
  4c0cfa:	mov    0x8(%rsp),%rdx
  4c0cff:	movzbl 0x2(%rdx),%eax
  4c0d03:	shr    $1,%al
  4c0d05:	and    $0x1,%eax
  4c0d08:	mov    0x8(%rdx,%rax,4),%rax
  4c0d0d:	test   %rax,%rax
  4c0d10:	js     4c0d1f <tomo_multidb2_pad_380927+0x1084>
  4c0d12:	cmp    %rax,0x188(%r15)
  4c0d19:	jg     4c163b <tomo_multidb2_pad_380927+0x19a0>
  4c0d1f:	mov    0x8(%rsp),%rax
  4c0d24:	mov    %rax,0x48(%rsp)
  4c0d29:	mov    %ebx,%eax
  4c0d2b:	mov    $0x1,%edx
  4c0d30:	shlx   %rax,%rdx,%rbp
  4c0d35:	mov    0x60(%rsp),%rax
  4c0d3a:	test   %rax,%rax
  4c0d3d:	je     4c14fa <tomo_multidb2_pad_380927+0x185f>
  4c0d43:	mov    %rax,%r12
  4c0d46:	mov    %rbx,%rax
  4c0d49:	mov    %rcx,0x50(%rsp)
  4c0d4e:	mov    %rbp,%rbx
  4c0d51:	mov    %rax,%rbp
  4c0d54:	jmp    4c0d63 <tomo_multidb2_pad_380927+0x10c8>
  4c0d56:	mov    (%r12),%r12
  4c0d5a:	test   %r12,%r12
  4c0d5d:	je     4c14f7 <tomo_multidb2_pad_380927+0x185c>
  4c0d63:	mov    %rbx,%rax
  4c0d66:	and    0x68(%r12),%rax
  4c0d6b:	je     4c0d56 <tomo_multidb2_pad_380927+0x10bb>
  4c0d6d:	mov    0x7c(%r12),%eax
  4c0d72:	xor    %r13d,%r13d
  4c0d75:	test   %eax,%eax
  4c0d77:	je     4c0d56 <tomo_multidb2_pad_380927+0x10bb>
  4c0d79:	mov    0x28(%r12),%rdi
  4c0d7e:	test   %rdi,%rdi
  4c0d81:	je     4c0db2 <tomo_multidb2_pad_380927+0x1117>
  4c0d83:	mov    0x78(%r12),%esi
  4c0d88:	mov    %r13d,0x10(%rsp)
  4c0d8d:	add    %r13d,%esi
  4c0d90:	call   53fdf0 <_ZN4tomo22xshard_atomic_key_hashEPKNS_12ScatterStateEj>
  4c0d95:	cmp    %rax,%rbp
  4c0d98:	je     4c0eb0 <tomo_multidb2_pad_380927+0x1215>
  4c0d9e:	inc    %r13
  4c0da1:	cmp    0x7c(%r12),%r13d
  4c0da6:	jae    4c0d56 <tomo_multidb2_pad_380927+0x10bb>
  4c0da8:	mov    0x28(%r12),%rdi
  4c0dad:	test   %rdi,%rdi
  4c0db0:	jne    4c0d83 <tomo_multidb2_pad_380927+0x10e8>
  4c0db2:	cmp    0x60(%r12),%rbp
  4c0db7:	jne    4c0d9e <tomo_multidb2_pad_380927+0x1103>
  4c0db9:	mov    0x80(%r12),%edx
  4c0dc1:	movzbl 0x8b(%r12),%ecx
  4c0dca:	mov    0x84(%r12),%eax
  4c0dd2:	lea    0x90(%r12,%rdx,8),%rdi
  4c0dda:	vmovd  %eax,%xmm6
  4c0dde:	vpinsrd $0x1,%ecx,%xmm6,%xmm5
  4c0de4:	vmovq  %xmm5,%rdx
  4c0de9:	cmp    %rdx,0x50(%rsp)
  4c0dee:	jne    4c0d9e <tomo_multidb2_pad_380927+0x1103>
  4c0df0:	cmp    $0x7,%eax
  4c0df3:	jbe    4c1616 <tomo_multidb2_pad_380927+0x197b>
  4c0df9:	mov    %eax,%ecx
  4c0dfb:	cmp    $0x20,%eax
  4c0dfe:	ja     4c14e0 <tomo_multidb2_pad_380927+0x1845>
  4c0e04:	mov    0x20(%rsp),%r11
  4c0e09:	mov    -0x8(%rdi,%rcx,1),%rdx
  4c0e0e:	mov    (%rdi),%rsi
  4c0e11:	xor    -0x8(%r11,%rcx,1),%rdx
  4c0e16:	xor    (%r11),%rsi
  4c0e19:	or     %rsi,%rdx
  4c0e1c:	cmp    $0x10,%eax
  4c0e1f:	jbe    4c0e39 <tomo_multidb2_pad_380927+0x119e>
  4c0e21:	mov    -0x10(%rdi,%rcx,1),%rax
  4c0e26:	xor    -0x10(%r11,%rcx,1),%rax
  4c0e2b:	mov    0x8(%rdi),%rcx
  4c0e2f:	xor    0x8(%r11),%rcx
  4c0e33:	or     %rcx,%rax
  4c0e36:	or     %rax,%rdx
  4c0e39:	test   %rdx,%rdx
  4c0e3c:	sete   %al
  4c0e3f:	test   %al,%al
  4c0e41:	je     4c0d9e <tomo_multidb2_pad_380927+0x1103>
  4c0e47:	mov    %r13d,%r13d
  4c0e4a:	lea    0x90(%r12,%r13,8),%rbx
  4c0e52:	mov    (%rbx),%rbp
  4c0e55:	test   %rbp,%rbp
  4c0e58:	je     4c0e77 <tomo_multidb2_pad_380927+0x11dc>
  4c0e5a:	mov    %rbp,%rdi
  4c0e5d:	call   491030 <_ZN4tomo10kvobj_sizeEPKNS_5KvObjE>
  4c0e62:	mov    %rax,%rdx
  4c0e65:	mov    (%r15),%rax
  4c0e68:	cmp    %rdx,%rax
  4c0e6b:	jb     4c1a30 <tomo_multidb2_pad_380927+0x1d95>
  4c0e71:	sub    %rdx,%rax
  4c0e74:	mov    %rax,(%r15)
  4c0e77:	mov    0x48(%rsp),%rax
  4c0e7c:	cmp    %rax,%rbp
  4c0e7f:	je     4c0e8c <tomo_multidb2_pad_380927+0x11f1>
  4c0e81:	mov    %rbp,%rsi
  4c0e84:	mov    %r15,%rdi
  4c0e87:	call   494730 <_ZN4tomo9FlatStore19retire_detached_objEPNS_5KvObjE>
  4c0e8c:	mov    0x48(%rsp),%rax
  4c0e91:	mov    0x8(%rsp),%rdi
  4c0e96:	mov    %rax,(%rbx)
  4c0e99:	test   %rdi,%rdi
  4c0e9c:	je     4c0bc7 <tomo_multidb2_pad_380927+0xf2c>
  4c0ea2:	cmp    %rax,%rdi
  4c0ea5:	je     4c0bc7 <tomo_multidb2_pad_380927+0xf2c>
  4c0eab:	jmp    4c0ba0 <tomo_multidb2_pad_380927+0xf05>
  4c0eb0:	mov    0x28(%r12),%rdi
  4c0eb5:	test   %rdi,%rdi
  4c0eb8:	je     4c0db9 <tomo_multidb2_pad_380927+0x111e>
  4c0ebe:	cmpb   $0x0,0x8a(%r12)
  4c0ec7:	je     4c0f23 <tomo_multidb2_pad_380927+0x1288>
  4c0ec9:	mov    %r13d,%ecx
  4c0ecc:	cmp    0x7c(%r12),%r13d
  4c0ed1:	jae    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c0ed7:	mov    0x80(%r12),%esi
  4c0edf:	lea    0x90(,%rsi,8),%rdx
  4c0ee7:	lea    (%r12,%rdx,1),%rax
  4c0eeb:	test   %r13d,%r13d
  4c0eee:	jne    4c0f40 <tomo_multidb2_pad_380927+0x12a5>
  4c0ef0:	mov    (%rax),%eax
  4c0ef2:	cmp    %eax,0x84(%r12)
  4c0efa:	jb     4c0421 <tomo_multidb2_pad_380927+0x786>
  4c0f00:	mov    0x10(%rsp),%r11d
  4c0f05:	lea    (%rdx,%rsi,4),%rdi
  4c0f09:	movzbl 0x8b(%r12),%ecx
  4c0f12:	mov    %r11d,%edx
  4c0f15:	sub    %r11d,%eax
  4c0f18:	add    %rdx,%rdi
  4c0f1b:	add    %r12,%rdi
  4c0f1e:	jmp    4c0dda <tomo_multidb2_pad_380927+0x113f>
  4c0f23:	mov    0x78(%r12),%esi
  4c0f28:	add    %r13d,%esi
  4c0f2b:	call   53fe30 <_ZN4tomo23xshard_atomic_key_sliceEPKNS_12ScatterStateEj>
  4c0f30:	mov    %rax,%rdi
  4c0f33:	mov    %edx,%eax
  4c0f35:	shr    $0x20,%rdx
  4c0f39:	mov    %edx,%ecx
  4c0f3b:	jmp    4c0dda <tomo_multidb2_pad_380927+0x113f>
  4c0f40:	dec    %ecx
  4c0f42:	mov    (%rax,%rcx,4),%ecx
  4c0f45:	mov    (%rax,%r13,4),%eax
  4c0f49:	mov    %ecx,0x10(%rsp)
  4c0f4d:	cmp    %ecx,%eax
  4c0f4f:	jae    4c0ef2 <tomo_multidb2_pad_380927+0x1257>
  4c0f51:	jmp    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c0f56:	cs nopw 0x0(%rax,%rax,1)
  4c0f60:	mov    0x78(%rsp),%rbx
  4c0f65:	mov    0x30(%rsp),%rax
  4c0f6a:	mov    0x70(%rsp),%r13
  4c0f6f:	lea    0x1(%rbx,%rax,1),%rbx
  4c0f74:	cmpb   $0x0,0x89(%r14)
  4c0f7c:	jne    4c1996 <tomo_multidb2_pad_380927+0x1cfb>
  4c0f82:	mov    0x38(%r14),%rsi
  4c0f86:	test   %rsi,%rsi
  4c0f89:	je     4c0f9b <tomo_multidb2_pad_380927+0x1300>
  4c0f8b:	mov    0x48(%r14),%rcx
  4c0f8f:	test   %rcx,%rcx
  4c0f92:	je     4c0f98 <tomo_multidb2_pad_380927+0x12fd>
  4c0f94:	decl   (%rcx)
  4c0f96:	jne    4c0f9b <tomo_multidb2_pad_380927+0x1300>
  4c0f98:	lock decl (%rsi)
  4c0f9b:	mov    0xb0(%r15),%rdx
  4c0fa2:	test   %rdx,%rdx
  4c0fa5:	je     4c0faa <tomo_multidb2_pad_380927+0x130f>
  4c0fa7:	incq   (%rdx)
  4c0faa:	mov    0xc8(%r15),%rcx
  4c0fb1:	decl   0x210(%rcx)
  4c0fb7:	cmpq   $0x0,0x28(%r14)
  4c0fbc:	je     4c0fc4 <tomo_multidb2_pad_380927+0x1329>
  4c0fbe:	decb   0x526(%rcx)
  4c0fc4:	mov    0x18(%r14),%rdi
  4c0fc8:	mov    0x50(%r14),%rcx
  4c0fcc:	test   %rdi,%rdi
  4c0fcf:	je     4c1427 <tomo_multidb2_pad_380927+0x178c>
  4c0fd5:	mov    0x10(%r14),%rsi
  4c0fd9:	mov    %rsi,0x10(%rdi)
  4c0fdd:	test   %rsi,%rsi
  4c0fe0:	je     4c140b <tomo_multidb2_pad_380927+0x1770>
  4c0fe6:	mov    0xc8(%r15),%rcx
  4c0fed:	mov    %rdi,0x18(%rsi)
  4c0ff1:	movq   $0x0,0x18(%r14)
  4c0ff9:	movq   $0x0,0x10(%r14)
  4c1001:	cmpb   $0x0,0x89(%r14)
  4c1009:	jne    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c100f:	mov    0x70(%r14),%rsi
  4c1013:	cmp    $0x8,%rsi
  4c1017:	jbe    4c1484 <tomo_multidb2_pad_380927+0x17e9>
  4c101d:	cmp    $0x80,%rsi
  4c1024:	jbe    4c15e1 <tomo_multidb2_pad_380927+0x1946>
  4c102a:	lea    -0x1(%rsi),%rdi
  4c102e:	mov    $0x3d,%edx
  4c1033:	mov    $0x38,%r8d
  4c1039:	lzcnt  %rdi,%rdi
  4c103e:	sub    %edi,%edx
  4c1040:	sub    %edi,%r8d
  4c1043:	shrx   %rdx,%rsi,%rdx
  4c1048:	lea    0x4(%rdx,%r8,4),%edx
  4c104d:	cmp    $0x2f,%edx
  4c1050:	ja     4c105b <tomo_multidb2_pad_380927+0x13c0>
  4c1052:	test   %rcx,%rcx
  4c1055:	jne    4c148f <tomo_multidb2_pad_380927+0x17f4>
  4c105b:	xor    %edx,%edx
  4c105d:	mov    %r14,%rdi
  4c1060:	call   2bf70 <sdallocx@plt>
  4c1065:	cmp    %r13,0x60(%rsp)
  4c106a:	jne    4c0a95 <tomo_multidb2_pad_380927+0xdfa>
  4c1070:	mov    0x40(%rsp),%rax
  4c1075:	mov    0x60(%rsp),%r15
  4c107a:	mov    0xc8(%rax),%rax
  4c1081:	mov    %r15,(%rax)
  4c1084:	test   %r15,%r15
  4c1087:	je     4c1e47 <tomo_multidb2_pad_380927+0x21ac>
  4c108d:	movq   $0x0,0x8(%r15)
  4c1095:	cmpq   $0x0,0x210(%rax)
  4c109d:	jne    4c10b4 <tomo_multidb2_pad_380927+0x1419>
  4c109f:	mov    0x40(%rsp),%rax
  4c10a4:	mov    0x88(%rax),%rax
  4c10ab:	test   %rax,%rax
  4c10ae:	je     4c10b4 <tomo_multidb2_pad_380927+0x1419>
  4c10b0:	lock decq (%rax)
  4c10b4:	mov    0x40(%rsp),%rax
  4c10b9:	mov    0xa8(%rax),%rax
  4c10c0:	test   %rax,%rax
  4c10c3:	je     4bfaae <_ZN4tomo9FlatStore15atomic_collapseEmm+0x30e>
  4c10c9:	add    %rbx,(%rax)
  4c10cc:	jmp    4bfaae <_ZN4tomo9FlatStore15atomic_collapseEmm+0x30e>
  4c10d1:	data16 cs nopw 0x0(%rax,%rax,1)
  4c10dc:	nopl   0x0(%rax)
  4c10e0:	mov    0xc5d0(%rbx),%rax
  4c10e7:	cmp    $0xffffffffffffffff,%rax
  4c10eb:	je     4bfefc <tomo_multidb2_pad_380927+0x261>
  4c10f1:	jmp    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c10f6:	cs nopw 0x0(%rax,%rax,1)
  4c1100:	test   %eax,%eax
  4c1102:	je     4c0772 <tomo_multidb2_pad_380927+0xad7>
  4c1108:	movzbl (%rsi),%edx
  4c110b:	cmp    %dl,(%rdi)
  4c110d:	jne    4c0704 <tomo_multidb2_pad_380927+0xa69>
  4c1113:	mov    %eax,%edx
  4c1115:	shr    $1,%edx
  4c1117:	movzbl (%rsi,%rdx,1),%r11d
  4c111c:	cmp    %r11b,(%rdi,%rdx,1)
  4c1120:	jne    4c0704 <tomo_multidb2_pad_380927+0xa69>
  4c1126:	dec    %eax
  4c1128:	movzbl (%rsi,%rax,1),%edx
  4c112c:	cmp    %dl,(%rdi,%rax,1)
  4c112f:	jne    4c0704 <tomo_multidb2_pad_380927+0xa69>
  4c1135:	jmp    4c0772 <tomo_multidb2_pad_380927+0xad7>
  4c113a:	mov    0x0(%r13),%r13
  4c113e:	cmp    %r13,%r15
  4c1141:	jne    4c0872 <tomo_multidb2_pad_380927+0xbd7>
  4c1147:	mov    0x40(%rsp),%rax
  4c114c:	mov    0x8(%rax),%r14
  4c1150:	mov    0x10(%rax),%rdx
  4c1154:	cmp    %r14,%rdx
  4c1157:	je     4c1e2a <tomo_multidb2_pad_380927+0x218f>
  4c115d:	add    $0x8,%r14
  4c1161:	mov    %rbp,0x30(%rsp)
  4c1166:	xor    %r13d,%r13d
  4c1169:	mov    $0x1,%r12d
  4c116f:	mov    %r14,%rbp
  4c1172:	mov    %rdx,0x20(%rsp)
  4c1177:	mov    -0x8(%rbp),%ebx
  4c117a:	shlx   %rbx,%r12,%rax
  4c117f:	mov    %r15,%rbx
  4c1182:	mov    %rax,0x10(%rsp)
  4c1187:	mov    0x38(%rbp),%rax
  4c118b:	test   %r15,%r15
  4c118e:	je     4c1342 <tomo_multidb2_pad_380927+0x16a7>
  4c1194:	test   %rax,%rax
  4c1197:	jne    4c123e <tomo_multidb2_pad_380927+0x15a3>
  4c119d:	mov    0x10(%rsp),%rax
  4c11a2:	and    0x68(%rbx),%rax
  4c11a6:	jne    4c11c2 <tomo_multidb2_pad_380927+0x1527>
  4c11a8:	mov    (%rbx),%rax
  4c11ab:	test   %rax,%rax
  4c11ae:	je     4c134b <tomo_multidb2_pad_380927+0x16b0>
  4c11b4:	mov    %rax,%rbx
  4c11b7:	mov    0x10(%rsp),%rax
  4c11bc:	and    0x68(%rbx),%rax
  4c11c0:	je     4c11a8 <tomo_multidb2_pad_380927+0x150d>
  4c11c2:	mov    0x7c(%rbx),%r9d
  4c11c6:	test   %r9d,%r9d
  4c11c9:	je     4c11a8 <tomo_multidb2_pad_380927+0x150d>
  4c11cb:	xor    %r14d,%r14d
  4c11ce:	jmp    4c11ee <tomo_multidb2_pad_380927+0x1553>
  4c11d0:	mov    0x78(%rbx),%esi
  4c11d3:	add    %r14d,%esi
  4c11d6:	call   53fdf0 <_ZN4tomo22xshard_atomic_key_hashEPKNS_12ScatterStateEj>
  4c11db:	cmp    %rax,-0x8(%rbp)
  4c11df:	je     4c11fd <tomo_multidb2_pad_380927+0x1562>
  4c11e1:	inc    %r14d
  4c11e4:	cmp    0x7c(%rbx),%r14d
  4c11e8:	jae    4c1332 <tomo_multidb2_pad_380927+0x1697>
  4c11ee:	mov    0x28(%rbx),%rdi
  4c11f2:	test   %rdi,%rdi
  4c11f5:	jne    4c11d0 <tomo_multidb2_pad_380927+0x1535>
  4c11f7:	mov    0x60(%rbx),%rax
  4c11fb:	jmp    4c11db <tomo_multidb2_pad_380927+0x1540>
  4c11fd:	mov    %r14d,%esi
  4c1200:	mov    %rbx,%rdi
  4c1203:	call   481da0 <_ZNK4tomo9FlatStore16atomic_entry_keyERKNS_11AtomicEntryEj.isra.0>
  4c1208:	mov    0x8(%rsp),%rdi
  4c120d:	mov    %rbp,%rsi
  4c1210:	mov    %rax,0xa0(%rsp)
  4c1218:	mov    %rdx,0xa8(%rsp)
  4c1220:	call   48ff60 <_ZNK4tomo5Slice6key_eqERKS0_>
  4c1225:	test   %al,%al
  4c1227:	je     4c11e1 <tomo_multidb2_pad_380927+0x1546>
  4c1229:	mov    %rbx,0x38(%rbp)
  4c122d:	cmpq   $0x0,(%rbx)
  4c1231:	mov    %rbx,%rax
  4c1234:	mov    %r14d,0x40(%rbp)
  4c1238:	je     4c1342 <tomo_multidb2_pad_380927+0x16a7>
  4c123e:	mov    0x40(%rbp),%edx
  4c1241:	mov    0x90(%rax,%rdx,8),%rax
  4c1249:	mov    0x18(%rbp),%rcx
  4c124d:	mov    %rax,0x28(%rbp)
  4c1251:	mov    0x30(%rcx),%rdx
  4c1255:	test   %rdx,%rdx
  4c1258:	je     4c127f <tomo_multidb2_pad_380927+0x15e4>
  4c125a:	mov    0x40(%rcx),%rsi
  4c125e:	test   %rsi,%rsi
  4c1261:	je     4c198e <tomo_multidb2_pad_380927+0x1cf3>
  4c1267:	movzbl (%rsi),%edx
  4c126a:	test   %dl,%dl
  4c126c:	jne    4c1977 <tomo_multidb2_pad_380927+0x1cdc>
  4c1272:	mov    0x30(%rcx),%rdx
  4c1276:	test   %rdx,%rdx
  4c1279:	jne    4c198e <tomo_multidb2_pad_380927+0x1cf3>
  4c127f:	mov    0x58(%rcx),%rdx
  4c1283:	xor    %esi,%esi
  4c1285:	cmp    $0xffffffffffffffff,%rdx
  4c1289:	vmovq  0x50(%rcx),%xmm0
  4c128e:	cmove  %rsi,%rdx
  4c1292:	cmpb   $0x0,0x68(%rbp)
  4c1296:	je     4c12ae <tomo_multidb2_pad_380927+0x1613>
  4c1298:	vmovq  %xmm0,%rcx
  4c129d:	cmp    %rcx,0x58(%rbp)
  4c12a1:	jne    4c12ae <tomo_multidb2_pad_380927+0x1613>
  4c12a3:	mov    0x60(%rbp),%rcx
  4c12a7:	cmp    %rcx,%rdx
  4c12aa:	cmovb  %rcx,%rdx
  4c12ae:	cmpb   $0x0,0x50(%rbp)
  4c12b2:	vpinsrq $0x1,%rdx,%xmm0,%xmm0
  4c12b8:	movb   $0x1,0x68(%rbp)
  4c12bc:	vmovdqu %xmm0,0x58(%rbp)
  4c12c1:	je     4c1a60 <tomo_multidb2_pad_380927+0x1dc5>
  4c12c7:	cmp    0x48(%rbp),%rdx
  4c12cb:	jae    4c1a60 <tomo_multidb2_pad_380927+0x1dc5>
  4c12d1:	mov    0x20(%rbp),%rax
  4c12d5:	test   %rax,%rax
  4c12d8:	je     4c1317 <tomo_multidb2_pad_380927+0x167c>
  4c12da:	movzbl 0x2(%rax),%edx
  4c12de:	and    $0x1,%edx
  4c12e1:	je     4c1308 <tomo_multidb2_pad_380927+0x166d>
  4c12e3:	movzbl 0x2(%rax),%edx
  4c12e7:	shr    $1,%dl
  4c12e9:	and    $0x1,%edx
  4c12ec:	mov    0x8(%rax,%rdx,4),%rdx
  4c12f1:	test   %rdx,%rdx
  4c12f4:	js     4c1308 <tomo_multidb2_pad_380927+0x166d>
  4c12f6:	mov    0x40(%rsp),%rcx
  4c12fb:	cmp    %rdx,0x188(%rcx)
  4c1302:	jg     4c1a71 <tomo_multidb2_pad_380927+0x1dd6>
  4c1308:	cmpq   $0x0,0x38(%rbp)
  4c130d:	mov    %rax,0x20(%rbp)
  4c1311:	je     4c1a7d <tomo_multidb2_pad_380927+0x1de2>
  4c1317:	lea    0x78(%rbp),%rax
  4c131b:	lea    0x70(%rbp),%r8
  4c131f:	cmp    %r8,0x20(%rsp)
  4c1324:	je     4c1a90 <tomo_multidb2_pad_380927+0x1df5>
  4c132a:	mov    %rax,%rbp
  4c132d:	jmp    4c1177 <tomo_multidb2_pad_380927+0x14dc>
  4c1332:	mov    (%rbx),%rbx
  4c1335:	mov    0x38(%rbp),%rax
  4c1339:	test   %rbx,%rbx
  4c133c:	jne    4c1194 <tomo_multidb2_pad_380927+0x14f9>
  4c1342:	test   %rax,%rax
  4c1345:	jne    4c123e <tomo_multidb2_pad_380927+0x15a3>
  4c134b:	mov    -0x8(%rbp),%rsi
  4c134f:	mov    0x0(%rbp),%rdx
  4c1353:	mov    0x8(%rbp),%rcx
  4c1357:	mov    0x40(%rsp),%rdi
  4c135c:	call   4929b0 <_ZNK4tomo9FlatStore20atomic_find_physicalEmNS_5SliceE>
  4c1361:	jmp    4c1249 <tomo_multidb2_pad_380927+0x15ae>
  4c1366:	cs nopw 0x0(%rax,%rax,1)
  4c1370:	mov    0x40(%rsp),%r14
  4c1375:	lea    (%rcx,%rcx,2),%rbp
  4c1379:	shl    $0x3,%rbp
  4c137d:	mov    %rbp,%rdi
  4c1380:	mov    0x58(%r14),%rax
  4c1384:	mov    %rax,%rbx
  4c1387:	mov    %rax,0x8(%rsp)
  4c138c:	sub    %rdx,%rbx
  4c138f:	call   2c120 <_Znwm@plt>
  4c1394:	mov    0x50(%r14),%rdi
  4c1398:	mov    0x58(%r14),%rcx
  4c139c:	mov    %rax,%r12
  4c139f:	mov    %rax,%rdx
  4c13a2:	mov    %rdi,%rax
  4c13a5:	cmp    %rdi,%rcx
  4c13a8:	je     4c13c8 <tomo_multidb2_pad_380927+0x172d>
  4c13aa:	vmovdqu (%rax),%xmm7
  4c13ae:	mov    0x10(%rax),%rsi
  4c13b2:	add    $0x18,%rax
  4c13b6:	add    $0x18,%rdx
  4c13ba:	mov    %rsi,-0x8(%rdx)
  4c13be:	vmovdqu %xmm7,-0x18(%rdx)
  4c13c3:	cmp    %rax,%rcx
  4c13c6:	jne    4c13aa <tomo_multidb2_pad_380927+0x170f>
  4c13c8:	test   %rdi,%rdi
  4c13cb:	je     4c13e6 <tomo_multidb2_pad_380927+0x174b>
  4c13cd:	mov    0x40(%rsp),%rax
  4c13d2:	mov    0x60(%rax),%rax
  4c13d6:	mov    %rax,%rsi
  4c13d9:	mov    %rax,0x8(%rsp)
  4c13de:	sub    %rdi,%rsi
  4c13e1:	call   2be30 <_ZdlPvm@plt>
  4c13e6:	mov    0x40(%rsp),%rcx
  4c13eb:	add    %r12,%rbx
  4c13ee:	vmovq  %r12,%xmm7
  4c13f3:	lea    (%r12,%rbp,1),%rax
  4c13f7:	vpinsrq $0x1,%rbx,%xmm7,%xmm0
  4c13fd:	vmovdqu %xmm0,0x50(%rcx)
  4c1402:	mov    %rax,0x60(%rcx)
  4c1406:	jmp    4c01a9 <tomo_multidb2_pad_380927+0x50e>
  4c140b:	mov    0xc8(%r15),%rcx
  4c1412:	movq   $0x0,0x18(%r14)
  4c141a:	movq   $0x0,0x10(%r14)
  4c1422:	jmp    4c1001 <tomo_multidb2_pad_380927+0x1366>
  4c1427:	mov    %rcx,%rdx
  4c142a:	movabs $0xff51afd7ed558ccd,%rax
  4c1434:	shr    $0x21,%rdx
  4c1438:	xor    %rcx,%rdx
  4c143b:	imul   %rax,%rdx
  4c143f:	movabs $0xc4ceb9fe1a85ec53,%rax
  4c1449:	mov    %rdx,%rcx
  4c144c:	shr    $0x21,%rcx
  4c1450:	xor    %rcx,%rdx
  4c1453:	imul   %rax,%rdx
  4c1457:	mov    %rdx,%rcx
  4c145a:	shr    $0x21,%rcx
  4c145e:	xor    %rcx,%rdx
  4c1461:	mov    0xc8(%r15),%rcx
  4c1468:	and    $0x3f,%edx
  4c146b:	cmp    0x10(%rcx,%rdx,8),%r14
  4c1470:	jne    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c1476:	mov    0x10(%r14),%rsi
  4c147a:	mov    %rsi,0x10(%rcx,%rdx,8)
  4c147f:	jmp    4c0fdd <tomo_multidb2_pad_380927+0x1342>
  4c1484:	xor    %edx,%edx
  4c1486:	test   %rcx,%rcx
  4c1489:	je     4c105b <tomo_multidb2_pad_380927+0x13c0>
  4c148f:	mov    0x520(%rcx),%edi
  4c1495:	cmp    $0xfff,%edi
  4c149b:	ja     4c105b <tomo_multidb2_pad_380927+0x13c0>
  4c14a1:	mov    0x538(%rcx),%r8
  4c14a8:	add    %rsi,%r8
  4c14ab:	cmp    $0x400000,%r8
  4c14b2:	ja     4c105b <tomo_multidb2_pad_380927+0x13c0>
  4c14b8:	mov    %edx,%edx
  4c14ba:	inc    %edi
  4c14bc:	add    $0x40,%rdx
  4c14c0:	mov    0x20(%rcx,%rdx,8),%rsi
  4c14c5:	mov    %rsi,0x20(%r14)
  4c14c9:	mov    %r14,0x20(%rcx,%rdx,8)
  4c14ce:	mov    %edi,0x520(%rcx)
  4c14d4:	mov    %r8,0x538(%rcx)
  4c14db:	jmp    4c1065 <tomo_multidb2_pad_380927+0x13ca>
  4c14e0:	mov    0x20(%rsp),%rsi
  4c14e5:	mov    %rcx,%rdx
  4c14e8:	call   2c8a0 <memcmp@plt>
  4c14ed:	test   %eax,%eax
  4c14ef:	sete   %al
  4c14f2:	jmp    4c0e3f <tomo_multidb2_pad_380927+0x11a4>
  4c14f7:	mov    %rbp,%rbx
  4c14fa:	mov    0x20(%rsp),%rdx
  4c14ff:	mov    0x58(%rsp),%rcx
  4c1504:	mov    %rbx,%rsi
  4c1507:	mov    %r15,%rdi
  4c150a:	call   4929b0 <_ZNK4tomo9FlatStore20atomic_find_physicalEmNS_5SliceE>
  4c150f:	mov    %rax,%rbp
  4c1512:	mov    0x48(%rsp),%rax
  4c1517:	cmp    %rax,%rbp
  4c151a:	je     4c1593 <tomo_multidb2_pad_380927+0x18f8>
  4c151c:	movzbl 0x5ddeb5(%rip),%eax        # a9f3d8 <_ZN4tomo22atomic_tripwire_detail5armedE>
  4c1523:	test   %al,%al
  4c1525:	je     4c1565 <tomo_multidb2_pad_380927+0x18ca>
  4c1527:	cmpq   $0x0,0x5ddeb1(%rip)        # a9f3e0 <_ZN4tomo22atomic_tripwire_detail5stateE>
  4c152f:	je     4c1565 <tomo_multidb2_pad_380927+0x18ca>
  4c1531:	mov    0x30(%r14),%rax
  4c1535:	test   %rax,%rax
  4c1538:	je     4c1a4a <tomo_multidb2_pad_380927+0x1daf>
  4c153e:	mov    (%rax),%rcx
  4c1541:	cmp    $0xffffffffffffffff,%rcx
  4c1545:	jne    4c1549 <tomo_multidb2_pad_380927+0x18ae>
  4c1547:	xor    %ecx,%ecx
  4c1549:	xor    %edx,%edx
  4c154b:	cmpq   $0x0,0x48(%rsp)
  4c1551:	mov    %rbx,%rdi
  4c1554:	sete   %dl
  4c1557:	xor    %esi,%esi
  4c1559:	test   %rbp,%rbp
  4c155c:	sete   %sil
  4c1560:	call   490ca0 <_ZN4tomo30atomic_tripwire_collapse_writeEmbbm>
  4c1565:	mov    0x48(%rsp),%r8
  4c156a:	mov    0x20(%rsp),%rdx
  4c156f:	mov    %rbx,%rsi
  4c1572:	mov    %r15,%rdi
  4c1575:	mov    0x58(%rsp),%rcx
  4c157a:	call   493cf0 <_ZN4tomo9FlatStore24atomic_exchange_physicalEmNS_5SliceEPNS_5KvObjE>
  4c157f:	cmp    %rax,%rbp
  4c1582:	jne    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c1588:	mov    %rbp,%rsi
  4c158b:	mov    %r15,%rdi
  4c158e:	call   494730 <_ZN4tomo9FlatStore19retire_detached_objEPNS_5KvObjE>
  4c1593:	mov    0x8(%rsp),%rax
  4c1598:	test   %rax,%rax
  4c159b:	je     4c0bc7 <tomo_multidb2_pad_380927+0xf2c>
  4c15a1:	mov    %rax,%rdi
  4c15a4:	call   491030 <_ZN4tomo10kvobj_sizeEPKNS_5KvObjE>
  4c15a9:	mov    %rax,%rdx
  4c15ac:	mov    (%r15),%rax
  4c15af:	cmp    %rdx,%rax
  4c15b2:	jb     4c1a53 <tomo_multidb2_pad_380927+0x1db8>
  4c15b8:	sub    %rdx,%rax
  4c15bb:	mov    %rax,(%r15)
  4c15be:	mov    0x8(%rsp),%rax
  4c15c3:	mov    0x48(%rsp),%rcx
  4c15c8:	cmp    %rcx,%rax
  4c15cb:	je     4c0bc7 <tomo_multidb2_pad_380927+0xf2c>
  4c15d1:	mov    %rax,%rsi
  4c15d4:	mov    %r15,%rdi
  4c15d7:	call   494730 <_ZN4tomo9FlatStore19retire_detached_objEPNS_5KvObjE>
  4c15dc:	jmp    4c0bc7 <tomo_multidb2_pad_380927+0xf2c>
  4c15e1:	mov    %rsi,%rdx
  4c15e4:	shr    $0x4,%rdx
  4c15e8:	test   %rcx,%rcx
  4c15eb:	jne    4c148f <tomo_multidb2_pad_380927+0x17f4>
  4c15f1:	jmp    4c105b <tomo_multidb2_pad_380927+0x13c0>
  4c15f6:	cs nopw 0x0(%rax,%rax,1)
  4c1600:	mov    0xc0(%r15),%rax
  4c1607:	test   %rax,%rax
  4c160a:	je     4c160f <tomo_multidb2_pad_380927+0x1974>
  4c160c:	incq   (%rax)
  4c160f:	xor    %edx,%edx
  4c1611:	jmp    4c0bb7 <tomo_multidb2_pad_380927+0xf1c>
  4c1616:	cmp    $0x3,%eax
  4c1619:	jbe    4c1651 <tomo_multidb2_pad_380927+0x19b6>
  4c161b:	mov    0x20(%rsp),%rcx
  4c1620:	mov    -0x4(%rdi,%rax,1),%edx
  4c1624:	xor    -0x4(%rcx,%rax,1),%edx
  4c1628:	mov    %edx,%eax
  4c162a:	mov    (%rdi),%edx
  4c162c:	xor    (%rcx),%edx
  4c162e:	or     %edx,%eax
  4c1630:	jne    4c0d9e <tomo_multidb2_pad_380927+0x1103>
  4c1636:	jmp    4c0e47 <tomo_multidb2_pad_380927+0x11ac>
  4c163b:	movq   $0x0,0x48(%rsp)
  4c1644:	jmp    4c0d29 <tomo_multidb2_pad_380927+0x108e>
  4c1649:	mov    (%rdx),%rdx
  4c164c:	jmp    4c0915 <tomo_multidb2_pad_380927+0xc7a>
  4c1651:	test   %eax,%eax
  4c1653:	je     4c0e47 <tomo_multidb2_pad_380927+0x11ac>
  4c1659:	mov    0x20(%rsp),%rcx
  4c165e:	movzbl (%rcx),%ecx
  4c1661:	cmp    %cl,(%rdi)
  4c1663:	jne    4c0d9e <tomo_multidb2_pad_380927+0x1103>
  4c1669:	mov    0x20(%rsp),%rcx
  4c166e:	mov    %eax,%edx
  4c1670:	shr    $1,%edx
  4c1672:	movzbl (%rcx,%rdx,1),%ecx
  4c1676:	cmp    %cl,(%rdi,%rdx,1)
  4c1679:	jne    4c0d9e <tomo_multidb2_pad_380927+0x1103>
  4c167f:	mov    0x20(%rsp),%rcx
  4c1684:	dec    %eax
  4c1686:	movzbl (%rcx,%rax,1),%ecx
  4c168a:	cmp    %cl,(%rdi,%rax,1)
  4c168d:	jne    4c0d9e <tomo_multidb2_pad_380927+0x1103>
  4c1693:	jmp    4c0e47 <tomo_multidb2_pad_380927+0x11ac>
  4c1698:	mov    0x40(%rsp),%rax
  4c169d:	mov    0x8(%rax),%r14
  4c16a1:	mov    0x10(%rax),%rdx
  4c16a5:	cmp    %rdx,%r14
  4c16a8:	jne    4c115d <tomo_multidb2_pad_380927+0x14c2>
  4c16ae:	mov    0x40(%rsp),%r14
  4c16b3:	mov    0x40(%r14),%rsi
  4c16b7:	mov    0x38(%r14),%rdi
  4c16bb:	call   4b4bd0 <_ZSt4sortIN9__gnu_cxx17__normal_iteratorIPPN4tomo5KvObjESt6vectorIS4_SaIS4_EEEEEvT_SA_>
  4c16c0:	mov    0x40(%r14),%rbx
  4c16c4:	mov    0x38(%r14),%rdi
  4c16c8:	mov    %rbx,%rsi
  4c16cb:	call   4b4e40 <_ZSt6uniqueIN9__gnu_cxx17__normal_iteratorIPPN4tomo5KvObjESt6vectorIS4_SaIS4_EEEEET_SA_SA_>
  4c16d0:	mov    %rbx,%rdx
  4c16d3:	mov    %rbp,%rdi
  4c16d6:	mov    %rax,%rsi
  4c16d9:	call   4b4dc0 <_ZNSt6vectorIPN4tomo5KvObjESaIS2_EE5eraseEN9__gnu_cxx17__normal_iteratorIPKS2_S4_EES9_>
  4c16de:	mov    0x38(%r14),%rbx
  4c16e2:	mov    0x40(%r14),%rbp
  4c16e6:	cmp    %rbx,%rbp
  4c16e9:	je     4c1701 <tomo_multidb2_pad_380927+0x1a66>
  4c16eb:	mov    (%rbx),%rsi
  4c16ee:	mov    0x40(%rsp),%rdi
  4c16f3:	add    $0x8,%rbx
  4c16f7:	call   494730 <_ZN4tomo9FlatStore19retire_detached_objEPNS_5KvObjE>
  4c16fc:	cmp    %rbx,%rbp
  4c16ff:	jne    4c16eb <tomo_multidb2_pad_380927+0x1a50>
  4c1701:	mov    0x40(%rsp),%rax
  4c1706:	mov    0x40(%rsp),%r13
  4c170b:	xor    %ebx,%ebx
  4c170d:	mov    $0x3d,%r12d
  4c1713:	mov    0xc8(%rax),%rax
  4c171a:	mov    (%rax),%r14
  4c171d:	cmp    %r14,%r15
  4c1720:	jne    4c17ac <tomo_multidb2_pad_380927+0x1b11>
  4c1726:	jmp    4c189d <tomo_multidb2_pad_380927+0x1c02>
  4c172b:	nopl   0x0(%rax,%rax,1)
  4c1730:	mov    %rbp,%rsi
  4c1733:	mov    %r13,%rdi
  4c1736:	incq   (%rax)
  4c1739:	call   492900 <_ZN4tomo9FlatStore18atomic_unlink_connERNS_11AtomicEntryE>
  4c173e:	mov    0xc8(%r13),%rdx
  4c1745:	cmpb   $0x0,0x89(%rbp)
  4c174c:	jne    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c1752:	mov    0x70(%rbp),%rsi
  4c1756:	cmp    $0x8,%rsi
  4c175a:	jbe    4c1885 <tomo_multidb2_pad_380927+0x1bea>
  4c1760:	cmp    $0x80,%rsi
  4c1767:	jbe    4c1824 <tomo_multidb2_pad_380927+0x1b89>
  4c176d:	lea    -0x1(%rsi),%rax
  4c1771:	mov    %r12d,%ecx
  4c1774:	mov    $0x38,%edi
  4c1779:	lzcnt  %rax,%rax
  4c177e:	sub    %eax,%ecx
  4c1780:	sub    %eax,%edi
  4c1782:	shrx   %rcx,%rsi,%rcx
  4c1787:	lea    0x4(%rcx,%rdi,4),%eax
  4c178b:	test   %rdx,%rdx
  4c178e:	je     4c1799 <tomo_multidb2_pad_380927+0x1afe>
  4c1790:	cmp    $0x2f,%eax
  4c1793:	jbe    4c1834 <tomo_multidb2_pad_380927+0x1b99>
  4c1799:	xor    %edx,%edx
  4c179b:	mov    %rbp,%rdi
  4c179e:	call   2bf70 <sdallocx@plt>
  4c17a3:	cmp    %r14,%r15
  4c17a6:	je     4c1891 <tomo_multidb2_pad_380927+0x1bf6>
  4c17ac:	mov    %r14,%rbp
  4c17af:	mov    (%r14),%r14
  4c17b2:	cmpb   $0x0,0x89(%rbp)
  4c17b9:	jne    4c18c8 <tomo_multidb2_pad_380927+0x1c2d>
  4c17bf:	mov    0x38(%rbp),%rcx
  4c17c3:	test   %rcx,%rcx
  4c17c6:	je     4c17d8 <tomo_multidb2_pad_380927+0x1b3d>
  4c17c8:	mov    0x48(%rbp),%rdx
  4c17cc:	test   %rdx,%rdx
  4c17cf:	je     4c17d5 <tomo_multidb2_pad_380927+0x1b3a>
  4c17d1:	decl   (%rdx)
  4c17d3:	jne    4c17d8 <tomo_multidb2_pad_380927+0x1b3d>
  4c17d5:	lock decl (%rcx)
  4c17d8:	mov    0xb0(%r13),%rax
  4c17df:	inc    %ebx
  4c17e1:	test   %rax,%rax
  4c17e4:	jne    4c1730 <tomo_multidb2_pad_380927+0x1a95>
  4c17ea:	mov    %rbp,%rsi
  4c17ed:	mov    %r13,%rdi
  4c17f0:	call   492900 <_ZN4tomo9FlatStore18atomic_unlink_connERNS_11AtomicEntryE>
  4c17f5:	mov    0xc8(%r13),%rdx
  4c17fc:	jmp    4c1745 <tomo_multidb2_pad_380927+0x1aaa>
  4c1801:	mov    0xb8(%rsp),%rax
  4c1809:	sub    %fs:0x28,%rax
  4c1812:	jne    4c1972 <tomo_multidb2_pad_380927+0x1cd7>
  4c1818:	lea    0x3c1838(%rip),%rdi        # 883057 <_IO_stdin_used+0x57>
  4c181f:	call   2bfa0 <_ZSt20__throw_length_errorPKc@plt>
  4c1824:	mov    %rsi,%rax
  4c1827:	shr    $0x4,%rax
  4c182b:	test   %rdx,%rdx
  4c182e:	je     4c1799 <tomo_multidb2_pad_380927+0x1afe>
  4c1834:	mov    0x520(%rdx),%ecx
  4c183a:	cmp    $0xfff,%ecx
  4c1840:	ja     4c1799 <tomo_multidb2_pad_380927+0x1afe>
  4c1846:	mov    0x538(%rdx),%rdi
  4c184d:	add    %rsi,%rdi
  4c1850:	cmp    $0x400000,%rdi
  4c1857:	ja     4c1799 <tomo_multidb2_pad_380927+0x1afe>
  4c185d:	mov    %eax,%eax
  4c185f:	inc    %ecx
  4c1861:	add    $0x40,%rax
  4c1865:	mov    0x20(%rdx,%rax,8),%rsi
  4c186a:	mov    %rsi,0x20(%rbp)
  4c186e:	mov    %rbp,0x20(%rdx,%rax,8)
  4c1873:	mov    %ecx,0x520(%rdx)
  4c1879:	mov    %rdi,0x538(%rdx)
  4c1880:	jmp    4c17a3 <tomo_multidb2_pad_380927+0x1b08>
  4c1885:	xor    %eax,%eax
  4c1887:	test   %rdx,%rdx
  4c188a:	jne    4c1834 <tomo_multidb2_pad_380927+0x1b99>
  4c188c:	jmp    4c1799 <tomo_multidb2_pad_380927+0x1afe>
  4c1891:	mov    0x40(%rsp),%rax
  4c1896:	mov    0xc8(%rax),%rax
  4c189d:	mov    %r15,(%rax)
  4c18a0:	test   %r15,%r15
  4c18a3:	je     4c1967 <tomo_multidb2_pad_380927+0x1ccc>
  4c18a9:	xor    %ecx,%ecx
  4c18ab:	mov    %rcx,0x8(%r15)
  4c18af:	sub    %ebx,0x210(%rax)
  4c18b5:	cmpq   $0x0,0x210(%rax)
  4c18bd:	jne    4bfa95 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2f5>
  4c18c3:	jmp    4bfa80 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2e0>
  4c18c8:	mov    0xc8(%r13),%rax
  4c18cf:	test   %rax,%rax
  4c18d2:	je     4c0421 <tomo_multidb2_pad_380927+0x786>
  4c18d8:	cmpb   $0x0,0x524(%rax)
  4c18df:	je     4c0421 <tomo_multidb2_pad_380927+0x786>
  4c18e5:	vmovq  %rbp,%xmm5
  4c18ea:	mov    0x8(%rsp),%rdx
  4c18ef:	lea    0x5c0(%rax),%rdi
  4c18f6:	mov    %rax,0x10(%rsp)
  4c18fb:	vpinsrq $0x1,%r13,%xmm5,%xmm0
  4c1901:	vmovdqa %xmm0,0xa0(%rsp)
  4c190a:	mov    0x80(%rbp),%esi
  4c1910:	call   4a8f70 <_ZN4tomo17ForeignReadSafety10close_spanIZNS_9FlatStore28read_local_pending_unpublishERNS_11AtomicEntryEEUljE_EEvjOT_>
  4c1915:	mov    0x10(%rsp),%rax
  4c191a:	mov    0x584(%rax),%edx
  4c1920:	test   %edx,%edx
  4c1922:	je     4c1956 <tomo_multidb2_pad_380927+0x1cbb>
  4c1924:	dec    %edx
  4c1926:	mov    %edx,0x584(%rax)
  4c192c:	jne    4c194a <tomo_multidb2_pad_380927+0x1caf>
  4c192e:	mov    0xc5d0(%rax),%rdx
  4c1935:	inc    %rdx
  4c1938:	je     4c194a <tomo_multidb2_pad_380927+0x1caf>
  4c193a:	lock btrq $0x1,0x548(%rax)
  4c1944:	jae    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c194a:	movb   $0x0,0x89(%rbp)
  4c1951:	jmp    4c17bf <tomo_multidb2_pad_380927+0x1b24>
  4c1956:	mov    0xc5d0(%rax),%rax
  4c195d:	inc    %rax
  4c1960:	je     4c194a <tomo_multidb2_pad_380927+0x1caf>
  4c1962:	jmp    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c1967:	xor    %edx,%edx
  4c1969:	mov    %rdx,0x8(%rax)
  4c196d:	jmp    4c18af <tomo_multidb2_pad_380927+0x1c14>
  4c1972:	call   2ba10 <__stack_chk_fail@plt>
  4c1977:	cmpb   $0x0,0x50(%rbp)
  4c197b:	jne    4c12d1 <tomo_multidb2_pad_380927+0x1636>
  4c1981:	mov    0x10(%rbp),%rax
  4c1985:	mov    %rax,0x20(%rbp)
  4c1989:	jmp    4c12d5 <tomo_multidb2_pad_380927+0x163a>
  4c198e:	mov    (%rdx),%rdx
  4c1991:	jmp    4c1283 <tomo_multidb2_pad_380927+0x15e8>
  4c1996:	mov    0xc8(%r15),%rbp
  4c199d:	test   %rbp,%rbp
  4c19a0:	je     4c0421 <tomo_multidb2_pad_380927+0x786>
  4c19a6:	cmpb   $0x0,0x524(%rbp)
  4c19ad:	je     4c0421 <tomo_multidb2_pad_380927+0x786>
  4c19b3:	vmovq  %r14,%xmm5
  4c19b8:	lea    0xa0(%rsp),%rdx
  4c19c0:	lea    0x5c0(%rbp),%rdi
  4c19c7:	vpinsrq $0x1,%r15,%xmm5,%xmm0
  4c19cd:	vmovdqa %xmm0,0xa0(%rsp)
  4c19d6:	mov    0x80(%r14),%esi
  4c19dd:	call   4a8f70 <_ZN4tomo17ForeignReadSafety10close_spanIZNS_9FlatStore28read_local_pending_unpublishERNS_11AtomicEntryEEUljE_EEvjOT_>
  4c19e2:	mov    0x584(%rbp),%edx
  4c19e8:	test   %edx,%edx
  4c19ea:	je     4c1a1f <tomo_multidb2_pad_380927+0x1d84>
  4c19ec:	dec    %edx
  4c19ee:	mov    %edx,0x584(%rbp)
  4c19f4:	jne    4c1a12 <tomo_multidb2_pad_380927+0x1d77>
  4c19f6:	mov    0xc5d0(%rbp),%rdx
  4c19fd:	inc    %rdx
  4c1a00:	je     4c1a12 <tomo_multidb2_pad_380927+0x1d77>
  4c1a02:	lock btrq $0x1,0x548(%rbp)
  4c1a0c:	jae    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c1a12:	movb   $0x0,0x89(%r14)
  4c1a1a:	jmp    4c0f82 <tomo_multidb2_pad_380927+0x12e7>
  4c1a1f:	mov    0xc5d0(%rbp),%rdx
  4c1a26:	inc    %rdx
  4c1a29:	je     4c1a12 <tomo_multidb2_pad_380927+0x1d77>
  4c1a2b:	jmp    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c1a30:	mov    0xc0(%r15),%rax
  4c1a37:	test   %rax,%rax
  4c1a3a:	je     4c1a3f <tomo_multidb2_pad_380927+0x1da4>
  4c1a3c:	incq   (%rax)
  4c1a3f:	xor    %r13d,%r13d
  4c1a42:	mov    %r13,(%r15)
  4c1a45:	jmp    4c0e77 <tomo_multidb2_pad_380927+0x11dc>
  4c1a4a:	mov    0x58(%r14),%rcx
  4c1a4e:	jmp    4c1541 <tomo_multidb2_pad_380927+0x18a6>
  4c1a53:	mov    %r15,%rdi
  4c1a56:	call   481ac0 <_ZN4tomo9FlatStore16atomic_gauge_subEm.part.0>
  4c1a5b:	jmp    4c15be <tomo_multidb2_pad_380927+0x1923>
  4c1a60:	mov    %rax,0x20(%rbp)
  4c1a64:	mov    %rdx,0x48(%rbp)
  4c1a68:	movb   $0x1,0x50(%rbp)
  4c1a6c:	jmp    4c12d5 <tomo_multidb2_pad_380927+0x163a>
  4c1a71:	xor    %r8d,%r8d
  4c1a74:	mov    %r8,0x20(%rbp)
  4c1a78:	jmp    4c1317 <tomo_multidb2_pad_380927+0x167c>
  4c1a7d:	cmpq   $0x0,0x28(%rbp)
  4c1a82:	jne    4c1317 <tomo_multidb2_pad_380927+0x167c>
  4c1a88:	inc    %r13d
  4c1a8b:	jmp    4c1317 <tomo_multidb2_pad_380927+0x167c>
  4c1a90:	mov    0x30(%rsp),%rbp
  4c1a95:	test   %r13d,%r13d
  4c1a98:	je     4c1aaf <tomo_multidb2_pad_380927+0x1e14>
  4c1a9a:	mov    0x40(%rsp),%rdi
  4c1a9f:	mov    %r13d,%esi
  4c1aa2:	call   4a6910 <_ZN4tomo9FlatStore23atomic_prepare_capacityEj>
  4c1aa7:	test   %al,%al
  4c1aa9:	je     4bfac0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x320>
  4c1aaf:	mov    0x40(%rsp),%rax
  4c1ab4:	mov    0x40(%rsp),%r13
  4c1ab9:	mov    0x8(%rax),%r14
  4c1abd:	mov    0x10(%rax),%r12
  4c1ac1:	cmp    %r14,%r12
  4c1ac4:	jne    4c1b51 <tomo_multidb2_pad_380927+0x1eb6>
  4c1aca:	jmp    4c1e2a <tomo_multidb2_pad_380927+0x218f>
  4c1acf:	nop
  4c1ad0:	mov    0x48(%r14),%ecx
  4c1ad4:	lea    0x90(%rdx,%rcx,8),%rbx
  4c1adc:	cmp    %rax,(%rbx)
  4c1adf:	je     4c1b48 <tomo_multidb2_pad_380927+0x1ead>
  4c1ae1:	movzbl 0x5dd8f0(%rip),%eax        # a9f3d8 <_ZN4tomo22atomic_tripwire_detail5armedE>
  4c1ae8:	test   %al,%al
  4c1aea:	je     4c1b16 <tomo_multidb2_pad_380927+0x1e7b>
  4c1aec:	cmpq   $0x0,0x5dd8ec(%rip)        # a9f3e0 <_ZN4tomo22atomic_tripwire_detail5stateE>
  4c1af4:	je     4c1b16 <tomo_multidb2_pad_380927+0x1e7b>
  4c1af6:	xor    %edx,%edx
  4c1af8:	cmpq   $0x0,0x28(%r14)
  4c1afd:	mov    0x50(%r14),%rcx
  4c1b01:	mov    (%r14),%rdi
  4c1b04:	sete   %dl
  4c1b07:	xor    %esi,%esi
  4c1b09:	cmpq   $0x0,(%rbx)
  4c1b0d:	sete   %sil
  4c1b11:	call   490ca0 <_ZN4tomo30atomic_tripwire_collapse_writeEmbbm>
  4c1b16:	mov    (%rbx),%rdi
  4c1b19:	test   %rdi,%rdi
  4c1b1c:	je     4c1b41 <tomo_multidb2_pad_380927+0x1ea6>
  4c1b1e:	call   491030 <_ZN4tomo10kvobj_sizeEPKNS_5KvObjE>
  4c1b23:	mov    %rax,%rdx
  4c1b26:	mov    0x0(%r13),%rax
  4c1b2a:	cmp    %rdx,%rax
  4c1b2d:	jb     4c1b9b <tomo_multidb2_pad_380927+0x1f00>
  4c1b2f:	sub    %rdx,%rax
  4c1b32:	mov    %rax,0x0(%r13)
  4c1b36:	mov    %rbx,%rsi
  4c1b39:	mov    %rbp,%rdi
  4c1b3c:	call   4b4a60 <_ZNSt6vectorIPN4tomo5KvObjESaIS2_EE9push_backERKS2_>
  4c1b41:	mov    0x28(%r14),%rax
  4c1b45:	mov    %rax,(%rbx)
  4c1b48:	add    $0x78,%r14
  4c1b4c:	cmp    %r14,%r12
  4c1b4f:	je     4c1ba5 <tomo_multidb2_pad_380927+0x1f0a>
  4c1b51:	mov    0x40(%r14),%rdx
  4c1b55:	mov    0x28(%r14),%rax
  4c1b59:	test   %rdx,%rdx
  4c1b5c:	jne    4c1ad0 <tomo_multidb2_pad_380927+0x1e35>
  4c1b62:	cmp    %rax,0x30(%r14)
  4c1b66:	je     4c1b48 <tomo_multidb2_pad_380927+0x1ead>
  4c1b68:	call   490c80 <_ZN4tomo23atomic_tripwire_enabledEv>
  4c1b6d:	test   %al,%al
  4c1b6f:	jne    4c1e6d <tomo_multidb2_pad_380927+0x21d2>
  4c1b75:	mov    0x28(%r14),%r8
  4c1b79:	mov    0x8(%r14),%rdx
  4c1b7d:	mov    0x10(%r14),%rcx
  4c1b81:	mov    %r13,%rdi
  4c1b84:	mov    (%r14),%rsi
  4c1b87:	call   493cf0 <_ZN4tomo9FlatStore24atomic_exchange_physicalEmNS_5SliceEPNS_5KvObjE>
  4c1b8c:	mov    %rax,0x38(%r14)
  4c1b90:	cmp    0x30(%r14),%rax
  4c1b94:	je     4c1b48 <tomo_multidb2_pad_380927+0x1ead>
  4c1b96:	jmp    4c0421 <tomo_multidb2_pad_380927+0x786>
  4c1b9b:	mov    %r13,%rdi
  4c1b9e:	call   481ac0 <_ZN4tomo9FlatStore16atomic_gauge_subEm.part.0>
  4c1ba3:	jmp    4c1b36 <tomo_multidb2_pad_380927+0x1e9b>
  4c1ba5:	mov    0x40(%rsp),%rax
  4c1baa:	mov    0xc8(%rax),%rax
  4c1bb1:	mov    (%rax),%r14
  4c1bb4:	cmp    %r14,%r15
  4c1bb7:	je     4c1cd0 <tomo_multidb2_pad_380927+0x2035>
  4c1bbd:	mov    0x40(%rsp),%rbx
  4c1bc2:	lea    0x90(%rsp),%r12
  4c1bca:	mov    %r15,0x20(%rsp)
  4c1bcf:	mov    %rbp,0x48(%rsp)
  4c1bd4:	mov    %r12,0x58(%rsp)
  4c1bd9:	mov    0x7c(%r14),%esi
  4c1bdd:	xor    %ebp,%ebp
  4c1bdf:	test   %esi,%esi
  4c1be1:	jne    4c1c81 <tomo_multidb2_pad_380927+0x1fe6>
  4c1be7:	jmp    4c1cb8 <tomo_multidb2_pad_380927+0x201d>
  4c1bec:	nopl   0x0(%rax)
  4c1bf0:	mov    0x78(%r14),%esi
  4c1bf4:	add    %ebp,%esi
  4c1bf6:	call   53fdf0 <_ZN4tomo22xshard_atomic_key_hashEPKNS_12ScatterStateEj>
  4c1bfb:	mov    %rax,%rsi
  4c1bfe:	mov    0x10(%rsp),%rdx
  4c1c03:	mov    0x18(%rsp),%rcx
  4c1c08:	mov    0x58(%rsp),%rdi
  4c1c0d:	xor    %r8d,%r8d
  4c1c10:	call   4a3f00 <_ZZN4tomo9FlatStore20atomic_collapse_implILb0EEEbmmENKUlmNS_5SliceEPNS_5KvObjEE_clEmS2_S4_>
  4c1c15:	mov    %eax,%edx
  4c1c17:	imul   $0x78,%rdx,%rdx
  4c1c1b:	add    0x8(%rbx),%rdx
  4c1c1f:	cmpq   $0x0,0x40(%rdx)
  4c1c24:	mov    %rdx,%r12
  4c1c27:	je     4c1c2f <tomo_multidb2_pad_380927+0x1f94>
  4c1c29:	cmp    0x28(%rdx),%r13
  4c1c2d:	je     4c1c6c <tomo_multidb2_pad_380927+0x1fd1>
  4c1c2f:	mov    %r13,%rdi
  4c1c32:	call   491030 <_ZN4tomo10kvobj_sizeEPKNS_5KvObjE>
  4c1c37:	mov    (%rbx),%rsi
  4c1c3a:	mov    %rsi,%rcx
  4c1c3d:	sub    %rax,%rcx
  4c1c40:	cmp    %rax,%rsi
  4c1c43:	jb     4c1da3 <tomo_multidb2_pad_380927+0x2108>
  4c1c49:	mov    %rcx,(%rbx)
  4c1c4c:	cmp    0x28(%r12),%r13
  4c1c51:	je     4c1c6c <tomo_multidb2_pad_380927+0x1fd1>
  4c1c53:	mov    0x40(%rbx),%rax
  4c1c57:	cmp    0x48(%rbx),%rax
  4c1c5b:	je     4c1d16 <tomo_multidb2_pad_380927+0x207b>
  4c1c61:	mov    %r13,(%rax)
  4c1c64:	add    $0x8,%rax
  4c1c68:	mov    %rax,0x40(%rbx)
  4c1c6c:	movq   $0x0,0x90(%r14,%rbp,8)
  4c1c78:	inc    %rbp
  4c1c7b:	cmp    0x7c(%r14),%ebp
  4c1c7f:	jae    4c1cb8 <tomo_multidb2_pad_380927+0x201d>
  4c1c81:	mov    0x90(%r14,%rbp,8),%r13
  4c1c89:	test   %r13,%r13
  4c1c8c:	je     4c1c78 <tomo_multidb2_pad_380927+0x1fdd>
  4c1c8e:	mov    %r14,%rdi
  4c1c91:	mov    %ebp,%esi
  4c1c93:	call   481da0 <_ZNK4tomo9FlatStore16atomic_entry_keyERKNS_11AtomicEntryEj.isra.0>
  4c1c98:	mov    0x28(%r14),%rdi
  4c1c9c:	mov    %rax,0x10(%rsp)
  4c1ca1:	mov    %rdx,0x18(%rsp)
  4c1ca6:	test   %rdi,%rdi
  4c1ca9:	jne    4c1bf0 <tomo_multidb2_pad_380927+0x1f55>
  4c1caf:	mov    0x60(%r14),%rsi
  4c1cb3:	jmp    4c1bfe <tomo_multidb2_pad_380927+0x1f63>
  4c1cb8:	mov    (%r14),%r14
  4c1cbb:	cmp    %r14,0x20(%rsp)
  4c1cc0:	jne    4c1bd9 <tomo_multidb2_pad_380927+0x1f3e>
  4c1cc6:	mov    0x20(%rsp),%r15
  4c1ccb:	mov    0x48(%rsp),%rbp
  4c1cd0:	mov    0x40(%rsp),%rcx
  4c1cd5:	mov    0x8(%rcx),%rax
  4c1cd9:	mov    0x10(%rcx),%r12
  4c1cdd:	lea    0x38(%rax),%rbx
  4c1ce1:	cmp    %rax,%r12
  4c1ce4:	jne    4c1cf3 <tomo_multidb2_pad_380927+0x2058>
  4c1ce6:	jmp    4c16ae <tomo_multidb2_pad_380927+0x1a13>
  4c1ceb:	nopl   0x0(%rax,%rax,1)
  4c1cf0:	mov    %rax,%rbx
  4c1cf3:	cmpq   $0x0,(%rbx)
  4c1cf7:	je     4c1d04 <tomo_multidb2_pad_380927+0x2069>
  4c1cf9:	mov    %rbx,%rsi
  4c1cfc:	mov    %rbp,%rdi
  4c1cff:	call   4b4a60 <_ZNSt6vectorIPN4tomo5KvObjESaIS2_EE9push_backERKS2_>
  4c1d04:	lea    0x78(%rbx),%rax
  4c1d08:	add    $0x40,%rbx
  4c1d0c:	cmp    %rbx,%r12
  4c1d0f:	jne    4c1cf0 <tomo_multidb2_pad_380927+0x2055>
  4c1d11:	jmp    4c16ae <tomo_multidb2_pad_380927+0x1a13>
  4c1d16:	mov    0x38(%rbx),%r12
  4c1d1a:	mov    %rax,%rsi
  4c1d1d:	movabs $0xfffffffffffffff,%rcx
  4c1d27:	sub    %r12,%rsi
  4c1d2a:	mov    %rsi,%rdx
  4c1d2d:	sar    $0x3,%rdx
  4c1d31:	cmp    %rcx,%rdx
  4c1d34:	je     4c1801 <tomo_multidb2_pad_380927+0x1b66>
  4c1d3a:	cmp    %r12,%rax
  4c1d3d:	je     4c1de1 <tomo_multidb2_pad_380927+0x2146>
  4c1d43:	lea    (%rdx,%rdx,1),%rax
  4c1d47:	cmp    %rdx,%rax
  4c1d4a:	jb     4c1e1e <tomo_multidb2_pad_380927+0x2183>
  4c1d50:	xor    %edi,%edi
  4c1d52:	xor    %r15d,%r15d
  4c1d55:	mov    %rdi,0x10(%rsp)
  4c1d5a:	test   %rax,%rax
  4c1d5d:	jne    4c1dea <tomo_multidb2_pad_380927+0x214f>
  4c1d63:	lea    0x8(%r15,%rsi,1),%rax
  4c1d68:	vmovq  %r15,%xmm7
  4c1d6d:	mov    %r13,(%r15,%rsi,1)
  4c1d71:	vpinsrq $0x1,%rax,%xmm7,%xmm6
  4c1d77:	vmovdqa %xmm6,0x30(%rsp)
  4c1d7d:	test   %rsi,%rsi
  4c1d80:	jg     4c1dca <tomo_multidb2_pad_380927+0x212f>
  4c1d82:	test   %r12,%r12
  4c1d85:	jne    4c1db9 <tomo_multidb2_pad_380927+0x211e>
  4c1d87:	vmovdqa 0x30(%rsp),%xmm5
  4c1d8d:	mov    0x10(%rsp),%rcx
  4c1d92:	add    %r15,%rcx
  4c1d95:	vmovdqu %xmm5,0x38(%rbx)
  4c1d9a:	mov    %rcx,0x48(%rbx)
  4c1d9e:	jmp    4c1c6c <tomo_multidb2_pad_380927+0x1fd1>
  4c1da3:	mov    0xc0(%rbx),%rax
  4c1daa:	test   %rax,%rax
  4c1dad:	je     4c1db2 <tomo_multidb2_pad_380927+0x2117>
  4c1daf:	incq   (%rax)
  4c1db2:	xor    %ecx,%ecx
  4c1db4:	jmp    4c1c49 <tomo_multidb2_pad_380927+0x1fae>
  4c1db9:	mov    0x48(%rbx),%rsi
  4c1dbd:	sub    %r12,%rsi
  4c1dc0:	mov    %r12,%rdi
  4c1dc3:	call   2be30 <_ZdlPvm@plt>
  4c1dc8:	jmp    4c1d87 <tomo_multidb2_pad_380927+0x20ec>
  4c1dca:	mov    %rsi,%rdx
  4c1dcd:	mov    %r15,%rdi
  4c1dd0:	mov    %r12,%rsi
  4c1dd3:	call   2b7a0 <memmove@plt>
  4c1dd8:	mov    0x48(%rbx),%rsi
  4c1ddc:	sub    %r12,%rsi
  4c1ddf:	jmp    4c1dc0 <tomo_multidb2_pad_380927+0x2125>
  4c1de1:	add    $0x1,%rdx
  4c1de5:	mov    %rdx,%rax
  4c1de8:	jb     4c1e1e <tomo_multidb2_pad_380927+0x2183>
  4c1dea:	movabs $0xfffffffffffffff,%rdx
  4c1df4:	cmp    %rdx,%rax
  4c1df7:	cmova  %rdx,%rax
  4c1dfb:	shl    $0x3,%rax
  4c1dff:	mov    %rsi,0x30(%rsp)
  4c1e04:	mov    %rax,%rdi
  4c1e07:	mov    %rax,0x10(%rsp)
  4c1e0c:	call   2c120 <_Znwm@plt>
  4c1e11:	mov    0x30(%rsp),%rsi
  4c1e16:	mov    %rax,%r15
  4c1e19:	jmp    4c1d63 <tomo_multidb2_pad_380927+0x20c8>
  4c1e1e:	movabs $0xfffffffffffffff,%rax
  4c1e28:	jmp    4c1dfb <tomo_multidb2_pad_380927+0x2160>
  4c1e2a:	mov    0x40(%rsp),%rax
  4c1e2f:	mov    0xc8(%rax),%rax
  4c1e36:	mov    (%rax),%r14
  4c1e39:	cmp    %r14,%r15
  4c1e3c:	jne    4c1bbd <tomo_multidb2_pad_380927+0x1f22>
  4c1e42:	jmp    4c16ae <tomo_multidb2_pad_380927+0x1a13>
  4c1e47:	xor    %r12d,%r12d
  4c1e4a:	mov    %r12,0x8(%rax)
  4c1e4e:	jmp    4c1095 <tomo_multidb2_pad_380927+0x13fa>
  4c1e53:	movabs $0x555555555555555,%rax
  4c1e5d:	cmp    %rax,%rdx
  4c1e60:	cmovbe %rdx,%rax
  4c1e64:	imul   $0x18,%rax,%r10
  4c1e68:	jmp    4c09c0 <tomo_multidb2_pad_380927+0xd25>
  4c1e6d:	xor    %edx,%edx
  4c1e6f:	cmpq   $0x0,0x28(%r14)
  4c1e74:	mov    0x50(%r14),%rcx
  4c1e78:	mov    (%r14),%rdi
  4c1e7b:	sete   %dl
  4c1e7e:	xor    %esi,%esi
  4c1e80:	cmpq   $0x0,0x30(%r14)
  4c1e85:	sete   %sil
  4c1e89:	call   490ca0 <_ZN4tomo30atomic_tripwire_collapse_writeEmbbm>
  4c1e8e:	jmp    4c1b75 <tomo_multidb2_pad_380927+0x1eda>
  4c1e93:	endbr64
  4c1e97:	mov    %rax,%rdi
  4c1e9a:	mov    %rdx,%rax
  4c1e9d:	jmp    4c1ea5 <tomo_multidb2_pad_380927+0x220a>
  4c1e9f:	endbr64
  4c1ea3:	jmp    4c1e97 <tomo_multidb2_pad_380927+0x21fc>
  4c1ea5:	dec    %rax
  4c1ea8:	jne    4c1ebc <tomo_multidb2_pad_380927+0x2221>
  4c1eaa:	vzeroupper
  4c1ead:	call   2b610 <__cxa_begin_catch@plt>
  4c1eb2:	call   2c290 <__cxa_end_catch@plt>
  4c1eb7:	jmp    4bfac0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x320>
  4c1ebc:	mov    0xb8(%rsp),%rax
  4c1ec4:	sub    %fs:0x28,%rax
  4c1ecd:	jne    4c1ed7 <tomo_multidb2_pad_380927+0x223c>
  4c1ecf:	vzeroupper
  4c1ed2:	call   2c060 <_Unwind_Resume@plt>
  4c1ed7:	vzeroupper
  4c1eda:	call   2ba10 <__stack_chk_fail@plt>

Disassembly of section .rlfence:

Disassembly of section .fini:
