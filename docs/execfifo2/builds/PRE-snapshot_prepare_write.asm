
build/execfifo2/PRE:     file format elf64-x86-64


Disassembly of section .init:

Disassembly of section .plt:

Disassembly of section .plt.got:

Disassembly of section .plt.sec:

Disassembly of section .text:

0000000000493ae0 <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE>:
  493ae0:	endbr64
  493ae4:	push   %r15
  493ae6:	push   %r14
  493ae8:	push   %r13
  493aea:	mov    %rsi,%r9
  493aed:	push   %r12
  493aef:	push   %rbp
  493af0:	push   %rbx
  493af1:	mov    %rdx,%r14
  493af4:	sub    $0x28,%rsp
  493af8:	cmpb   $0x0,0xf0(%rdi)
  493aff:	movzbl 0x193(%rdi),%eax
  493b06:	mov    %rdi,%rbx
  493b09:	mov    %rcx,%r15
  493b0c:	jne    493c60 <tomo_multidb2_pad_79486+0x8f>
  493b12:	test   %al,%al
  493b14:	je     493c53 <tomo_multidb2_pad_79486+0x82>
  493b1a:	cmpb   $0x0,0x194(%rdi)
  493b21:	jne    493c80 <tomo_multidb2_pad_79486+0xaf>
  493b27:	mov    0xd0(%rdi),%rcx
  493b2e:	test   %rcx,%rcx
  493b31:	je     493c94 <tomo_multidb2_pad_79486+0xc3>
  493b37:	mov    %rsi,%rax
  493b3a:	mov    %rsi,%rbp
  493b3d:	xor    %r12d,%r12d
  493b40:	movabs $0xffffffffffff,%r13
  493b4a:	shr    $0x31,%rax
  493b4e:	shr    $0x21,%rbp
  493b52:	mov    %rax,%r8
  493b55:	xor    %rsi,%rbp
  493b58:	movabs $0xff51afd7ed558ccd,%rax
  493b62:	imul   %rax,%rbp
  493b66:	mov    %rbp,%rax
  493b69:	shr    $0x21,%rax
  493b6d:	xor    %rax,%rbp
  493b70:	movabs $0xc4ceb9fe1a85ec53,%rax
  493b7a:	imul   %rax,%rbp
  493b7e:	mov    %rbp,%rax
  493b81:	shr    $0x21,%rax
  493b85:	xor    %rax,%rbp
  493b88:	and    0xe8(%rdi),%ebp
  493b8e:	jmp    493baa <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE+0xca>
  493b90:	mov    0xe8(%rbx),%eax
  493b96:	inc    %r12d
  493b99:	cmp    %r12d,0xe0(%rbx)
  493ba0:	jb     493c94 <tomo_multidb2_pad_79486+0xc3>
  493ba6:	inc    %ebp
  493ba8:	and    %eax,%ebp
  493baa:	mov    %ebp,%eax
  493bac:	mov    (%rcx,%rax,8),%rax
  493bb0:	test   %rax,%rax
  493bb3:	je     493c94 <tomo_multidb2_pad_79486+0xc3>
  493bb9:	mov    %rax,%rdx
  493bbc:	and    %r13,%rdx
  493bbf:	je     493b90 <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE+0xb0>
  493bc1:	shr    $0x31,%rax
  493bc5:	cmp    %ax,%r8w
  493bc9:	jne    493b90 <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE+0xb0>
  493bcb:	movzbl 0x2(%rdx),%eax
  493bcf:	test   $0x2,%al

0000000000493bd1 <tomo_multidb2_pad_79486>:
  493bd1:	jne    493d90 <tomo_multidb2_pad_80033+0x89>
  493bd7:	movzbl 0x3(%rdx),%esi
  493bdb:	lea    0x0(,%rax,8),%rax
  493be3:	and    $0x8,%eax
  493be6:	lea    0x8(%rdx,%rax,1),%rdi
  493beb:	xor    %eax,%eax
  493bed:	vmovd  %esi,%xmm1
  493bf1:	vpinsrd $0x1,%eax,%xmm1,%xmm0
  493bf7:	vmovq  %xmm0,%rax
  493bfc:	cmp    %rax,%r15
  493bff:	jne    493b90 <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE+0xb0>
  493c01:	cmp    $0x7,%esi
  493c04:	jbe    494115 <tomo_multidb2_pad_81248+0x135>
  493c0a:	mov    %esi,%edx
  493c0c:	cmp    $0x20,%esi
  493c0f:	ja     494132 <tomo_multidb2_pad_81248+0x152>
  493c15:	mov    -0x8(%rdi,%rdx,1),%rax
  493c1a:	mov    (%rdi),%r10
  493c1d:	xor    -0x8(%rdx,%r14,1),%rax
  493c22:	xor    (%r14),%r10
  493c25:	or     %r10,%rax
  493c28:	cmp    $0x10,%esi
  493c2b:	jbe    493c45 <tomo_multidb2_pad_79486+0x74>
  493c2d:	mov    -0x10(%rdi,%rdx,1),%rsi
  493c32:	xor    -0x10(%rdx,%r14,1),%rsi
  493c37:	mov    0x8(%rdi),%rdx
  493c3b:	xor    0x8(%r14),%rdx
  493c3f:	or     %rdx,%rsi
  493c42:	or     %rsi,%rax
  493c45:	test   %rax,%rax
  493c48:	sete   %al
  493c4b:	test   %al,%al
  493c4d:	je     493b90 <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE+0xb0>
  493c53:	xor    %eax,%eax
  493c55:	jmp    493c85 <tomo_multidb2_pad_79486+0xb4>
  493c57:	nopw   0x0(%rax,%rax,1)
  493c60:	test   %al,%al
  493c62:	je     493c53 <tomo_multidb2_pad_79486+0x82>
  493c64:	cmpb   $0x0,0x194(%rdi)
  493c6b:	je     493f0e <tomo_multidb2_pad_80033+0x207>
  493c71:	data16 cs nopw 0x0(%rax,%rax,1)
  493c7c:	nopl   0x0(%rax)
  493c80:	mov    $0x2,%eax
  493c85:	add    $0x28,%rsp
  493c89:	pop    %rbx
  493c8a:	pop    %rbp
  493c8b:	pop    %r12
  493c8d:	pop    %r13
  493c8f:	pop    %r14
  493c91:	pop    %r15
  493c93:	ret
  493c94:	mov    0xd8(%rbx),%rcx
  493c9b:	test   %rcx,%rcx
  493c9e:	je     493c53 <tomo_multidb2_pad_79486+0x82>
  493ca0:	mov    %r9,%rax
  493ca3:	mov    %r9,%r12
  493ca6:	xor    %ebp,%ebp
  493ca8:	shr    $0x31,%rax
  493cac:	shr    $0x21,%r12
  493cb0:	mov    %rax,%r10
  493cb3:	xor    %r9,%r12
  493cb6:	movabs $0xff51afd7ed558ccd,%rax
  493cc0:	movabs $0xffffffffffff,%r9
  493cca:	imul   %rax,%r12
  493cce:	mov    %r12,%rax
  493cd1:	shr    $0x21,%rax
  493cd5:	xor    %rax,%r12
  493cd8:	movabs $0xc4ceb9fe1a85ec53,%rax
  493ce2:	imul   %rax,%r12
  493ce6:	mov    %r12,%rax
  493ce9:	shr    $0x21,%rax
  493ced:	xor    %rax,%r12
  493cf0:	and    0xec(%rbx),%r12d
  493cf7:	jmp    493d5a <tomo_multidb2_pad_80033+0x53>
  493cf9:	nopl   0x0(%rax)
  493d00:	movzbl 0x2(%r8),%eax
  493d05:	test   $0x2,%al

0000000000493d07 <tomo_multidb2_pad_80033>:
  493d07:	jne    493e00 <tomo_multidb2_pad_80033+0xf9>
  493d0d:	movzbl 0x3(%r8),%edx
  493d12:	lea    0x0(,%rax,8),%rax
  493d1a:	and    $0x8,%eax
  493d1d:	lea    0x8(%r8,%rax,1),%rdi
  493d22:	xor    %eax,%eax
  493d24:	vmovd  %edx,%xmm3
  493d28:	vpinsrd $0x1,%eax,%xmm3,%xmm2
  493d2e:	vmovq  %xmm2,%rax
  493d33:	cmp    %rax,%r15
  493d36:	je     493e59 <tomo_multidb2_pad_80033+0x152>
  493d3c:	nopl   0x0(%rax)
  493d40:	mov    0xec(%rbx),%eax
  493d46:	inc    %ebp
  493d48:	cmp    %ebp,0xe4(%rbx)
  493d4e:	jb     493c53 <tomo_multidb2_pad_79486+0x82>
  493d54:	inc    %r12d
  493d57:	and    %eax,%r12d
  493d5a:	mov    %r12d,%r13d
  493d5d:	shl    $0x3,%r13
  493d61:	mov    (%rcx,%r13,1),%rax
  493d65:	test   %rax,%rax
  493d68:	je     493c53 <tomo_multidb2_pad_79486+0x82>
  493d6e:	mov    %rax,%r8
  493d71:	and    %r9,%r8
  493d74:	je     493d40 <tomo_multidb2_pad_80033+0x39>
  493d76:	shr    $0x31,%rax
  493d7a:	cmp    %ax,%r10w
  493d7e:	jne    493d40 <tomo_multidb2_pad_80033+0x39>
  493d80:	jmp    493d00 <tomo_multidb2_pad_79486+0x12f>
  493d85:	data16 cs nopw 0x0(%rax,%rax,1)
  493d90:	movzbl 0x2(%rdx),%esi
  493d94:	xor    %eax,%eax
  493d96:	and    $0x2,%esi
  493d99:	je     493da4 <tomo_multidb2_pad_80033+0x9d>
  493d9b:	movzbl 0x3(%rdx),%eax
  493d9f:	inc    %eax
  493da1:	movzbl %al,%eax
  493da4:	movzbl 0x2(%rdx),%esi
  493da8:	and    $0x2,%esi
  493dab:	jne    493df0 <tomo_multidb2_pad_80033+0xe9>
  493dad:	movzbl 0x3(%rdx),%esi
  493db1:	movzbl 0x2(%rdx),%edi
  493db5:	movzbl 0x2(%rdx),%r11d
  493dba:	shr    $1,%dil
  493dbd:	lea    0x0(,%rdi,4),%r10
  493dc5:	lea    0x0(,%r11,8),%rdi
  493dcd:	and    $0x4,%r10d
  493dd1:	and    $0x8,%edi
  493dd4:	lea    0x8(%r10,%rdi,1),%rdi
  493dd9:	add    %rdx,%rdi
  493ddc:	jmp    493bed <tomo_multidb2_pad_79486+0x1c>
  493de1:	data16 cs nopw 0x0(%rax,%rax,1)
  493dec:	nopl   0x0(%rax)
  493df0:	mov    0x8(%rdx),%esi
  493df3:	jmp    493db1 <tomo_multidb2_pad_80033+0xaa>
  493df5:	data16 cs nopw 0x0(%rax,%rax,1)
  493e00:	movzbl 0x2(%r8),%edx
  493e05:	xor    %eax,%eax
  493e07:	and    $0x2,%edx
  493e0a:	je     493e16 <tomo_multidb2_pad_80033+0x10f>
  493e0c:	movzbl 0x3(%r8),%eax
  493e11:	inc    %eax
  493e13:	movzbl %al,%eax
  493e16:	movzbl 0x2(%r8),%edx
  493e1b:	and    $0x2,%edx
  493e1e:	jne    4940e7 <tomo_multidb2_pad_81248+0x107>
  493e24:	movzbl 0x3(%r8),%edx
  493e29:	movzbl 0x2(%r8),%esi
  493e2e:	movzbl 0x2(%r8),%r11d
  493e33:	shr    $1,%sil
  493e36:	lea    0x0(,%rsi,4),%rdi
  493e3e:	lea    0x0(,%r11,8),%rsi
  493e46:	and    $0x4,%edi
  493e49:	and    $0x8,%esi
  493e4c:	lea    0x8(%rdi,%rsi,1),%rdi
  493e51:	add    %r8,%rdi
  493e54:	jmp    493d24 <tomo_multidb2_pad_80033+0x1d>
  493e59:	cmp    $0x7,%edx
  493e5c:	jbe    4941f8 <tomo_multidb2_pad_81248+0x218>
  493e62:	mov    %edx,%esi
  493e64:	cmp    $0x20,%edx
  493e67:	ja     494220 <tomo_multidb2_pad_81248+0x240>
  493e6d:	mov    -0x8(%rdi,%rsi,1),%r11
  493e72:	mov    (%rdi),%rax
  493e75:	xor    -0x8(%rsi,%r14,1),%r11
  493e7a:	xor    (%r14),%rax
  493e7d:	or     %r11,%rax
  493e80:	cmp    $0x10,%edx
  493e83:	jbe    493e9d <tomo_multidb2_pad_80033+0x196>
  493e85:	mov    -0x10(%rdi,%rsi,1),%rdx
  493e8a:	xor    -0x10(%rsi,%r14,1),%rdx
  493e8f:	mov    0x8(%rdi),%rsi
  493e93:	xor    0x8(%r14),%rsi
  493e97:	or     %rsi,%rdx
  493e9a:	or     %rdx,%rax
  493e9d:	test   %rax,%rax
  493ea0:	jne    493d40 <tomo_multidb2_pad_80033+0x39>
  493ea6:	cmp    0x180(%rbx),%r12d
  493ead:	jb     493c53 <tomo_multidb2_pad_79486+0x82>
  493eb3:	testb  $0x1,0x6(%rcx,%r13,1)
  493eb9:	jne    493c53 <tomo_multidb2_pad_79486+0x82>
  493ebf:	mov    0x128(%rbx),%rdx
  493ec6:	movzbl 0x2(%r8),%eax
  493ecb:	test   $0x1,%al
  493ecd:	je     4940f0 <tomo_multidb2_pad_81248+0x110>
  493ed3:	movzbl 0x2(%r8),%eax
  493ed8:	test   $0x1,%al
  493eda:	je     4940f0 <tomo_multidb2_pad_81248+0x110>
  493ee0:	movzbl 0x2(%r8),%eax
  493ee5:	shr    $1,%al
  493ee7:	and    $0x1,%eax
  493eea:	mov    0x8(%r8,%rax,4),%rax
  493eef:	test   %rax,%rax
  493ef2:	js     4940f0 <tomo_multidb2_pad_81248+0x110>
  493ef8:	cmp    %rax,%rdx
  493efb:	jle    4940f0 <tomo_multidb2_pad_81248+0x110>
  493f01:	btsq   $0x30,(%rcx,%r13,1)
  493f07:	xor    %eax,%eax
  493f09:	jmp    493c85 <tomo_multidb2_pad_79486+0xb4>
  493f0e:	mov    %rdx,%rcx
  493f11:	mov    %rsi,(%rsp)
  493f15:	mov    %rsi,%rdx
  493f18:	mov    %r15,%r8
  493f1b:	xor    %esi,%esi
  493f1d:	call   493860 <_ZNK4tomo9FlatStore7find_inEimNS_5SliceE>
  493f22:	mov    (%rsp),%r9
  493f26:	test   %rax,%rax
  493f29:	jne    493c53 <tomo_multidb2_pad_79486+0x82>
  493f2f:	mov    0xd8(%rbx),%rcx
  493f36:	test   %rcx,%rcx
  493f39:	je     493c53 <tomo_multidb2_pad_79486+0x82>
  493f3f:	mov    %r9,%rax
  493f42:	mov    %r9,%r12
  493f45:	xor    %ebp,%ebp
  493f47:	movabs $0xffffffffffff,%r13
  493f51:	shr    $0x31,%rax
  493f55:	shr    $0x21,%r12
  493f59:	mov    %rax,%r8
  493f5c:	xor    %r9,%r12
  493f5f:	movabs $0xff51afd7ed558ccd,%rax
  493f69:	imul   %rax,%r12
  493f6d:	mov    %r12,%rax
  493f70:	shr    $0x21,%rax
  493f74:	xor    %rax,%r12
  493f77:	movabs $0xc4ceb9fe1a85ec53,%rax
  493f81:	imul   %rax,%r12
  493f85:	mov    %r12,%rax
  493f88:	shr    $0x21,%rax
  493f8c:	xor    %rax,%r12
  493f8f:	and    0xec(%rbx),%r12d
  493f96:	jmp    493fb2 <tomo_multidb2_pad_80033+0x2ab>
  493f98:	mov    0xec(%rbx),%eax
  493f9e:	inc    %ebp
  493fa0:	cmp    %ebp,0xe4(%rbx)
  493fa6:	jb     493c53 <tomo_multidb2_pad_79486+0x82>
  493fac:	inc    %r12d
  493faf:	and    %eax,%r12d
  493fb2:	mov    %r12d,%r10d
  493fb5:	shl    $0x3,%r10
  493fb9:	mov    (%rcx,%r10,1),%rax
  493fbd:	test   %rax,%rax
  493fc0:	je     493c53 <tomo_multidb2_pad_79486+0x82>
  493fc6:	mov    %rax,%r9
  493fc9:	and    %r13,%r9
  493fcc:	je     493f98 <tomo_multidb2_pad_80033+0x291>
  493fce:	shr    $0x31,%rax
  493fd2:	cmp    %ax,%r8w
  493fd6:	jne    493f98 <tomo_multidb2_pad_80033+0x291>
  493fd8:	movzbl 0x2(%r9),%edx
  493fdd:	test   $0x2,%dl

0000000000493fe0 <tomo_multidb2_pad_81248>:
  493fe0:	jne    4941a0 <tomo_multidb2_pad_81248+0x1c0>
  493fe6:	movzbl 0x3(%r9),%eax
  493feb:	lea    0x0(,%rdx,8),%rdx
  493ff3:	and    $0x8,%edx
  493ff6:	lea    0x8(%r9,%rdx,1),%rdi
  493ffb:	xor    %edx,%edx
  493ffd:	vmovd  %eax,%xmm5
  494001:	vpinsrd $0x1,%edx,%xmm5,%xmm4
  494007:	vmovq  %xmm4,%rdx
  49400c:	cmp    %rdx,%r15
  49400f:	jne    493f98 <tomo_multidb2_pad_80033+0x291>
  494011:	cmp    $0x7,%eax
  494014:	jbe    4942f9 <tomo_multidb2_pad_81248+0x319>
  49401a:	mov    %eax,%esi
  49401c:	cmp    $0x20,%eax
  49401f:	ja     4942be <tomo_multidb2_pad_81248+0x2de>
  494025:	mov    -0x8(%rdi,%rsi,1),%rdx
  49402a:	mov    (%rdi),%r11
  49402d:	xor    -0x8(%rsi,%r14,1),%rdx
  494032:	xor    (%r14),%r11
  494035:	or     %r11,%rdx
  494038:	cmp    $0x10,%eax
  49403b:	jbe    494055 <tomo_multidb2_pad_81248+0x75>
  49403d:	mov    -0x10(%rdi,%rsi,1),%rax
  494042:	xor    -0x10(%rsi,%r14,1),%rax
  494047:	mov    0x8(%rdi),%rsi
  49404b:	xor    0x8(%r14),%rsi
  49404f:	or     %rsi,%rax
  494052:	or     %rax,%rdx
  494055:	test   %rdx,%rdx
  494058:	sete   %al
  49405b:	test   %al,%al
  49405d:	je     493f98 <tomo_multidb2_pad_80033+0x291>
  494063:	cmp    0x180(%rbx),%r12d
  49406a:	jb     493c53 <tomo_multidb2_pad_79486+0x82>
  494070:	testb  $0x1,0x6(%rcx,%r10,1)
  494076:	jne    493c53 <tomo_multidb2_pad_79486+0x82>
  49407c:	mov    0x128(%rbx),%rdx
  494083:	movzbl 0x2(%r9),%eax
  494088:	test   $0x1,%al
  49408a:	je     4940b2 <tomo_multidb2_pad_81248+0xd2>
  49408c:	movzbl 0x2(%r9),%eax
  494091:	test   $0x1,%al
  494093:	je     4940b2 <tomo_multidb2_pad_81248+0xd2>
  494095:	movzbl 0x2(%r9),%eax
  49409a:	shr    $1,%al
  49409c:	and    $0x1,%eax
  49409f:	mov    0x8(%r9,%rax,4),%rax
  4940a4:	test   %rax,%rax
  4940a7:	js     4940b2 <tomo_multidb2_pad_81248+0xd2>
  4940a9:	cmp    %rax,%rdx
  4940ac:	jg     4942a5 <tomo_multidb2_pad_81248+0x2c5>
  4940b2:	cmpb   $0x0,0x238(%rbx)
  4940b9:	jne    4940dd <tomo_multidb2_pad_81248+0xfd>
  4940bb:	mov    $0x1,%ecx
  4940c0:	mov    %r12d,%edx
  4940c3:	mov    %r9,%rsi
  4940c6:	mov    %rbx,%rdi
  4940c9:	call   4930f0 <_ZN4tomo9FlatStore21snapshot_start_recordEPKNS_5KvObjEjb>
  4940ce:	test   %al,%al
  4940d0:	je     493c80 <tomo_multidb2_pad_79486+0xaf>
  4940d6:	incq   0x1b0(%rbx)
  4940dd:	mov    $0x1,%eax
  4940e2:	jmp    493c85 <tomo_multidb2_pad_79486+0xb4>
  4940e7:	mov    0x8(%r8),%edx
  4940eb:	jmp    493e29 <tomo_multidb2_pad_80033+0x122>
  4940f0:	cmpb   $0x0,0x238(%rbx)
  4940f7:	jne    4940dd <tomo_multidb2_pad_81248+0xfd>
  4940f9:	mov    $0x1,%ecx
  4940fe:	mov    %r12d,%edx
  494101:	mov    %r8,%rsi
  494104:	mov    %rbx,%rdi
  494107:	call   4930f0 <_ZN4tomo9FlatStore21snapshot_start_recordEPKNS_5KvObjEjb>
  49410c:	test   %al,%al
  49410e:	jne    4940d6 <tomo_multidb2_pad_81248+0xf6>
  494110:	jmp    493c80 <tomo_multidb2_pad_79486+0xaf>
  494115:	cmp    $0x3,%esi
  494118:	jbe    494160 <tomo_multidb2_pad_81248+0x180>
  49411a:	mov    -0x4(%rdi,%rsi,1),%eax
  49411e:	mov    (%rdi),%edx
  494120:	xor    -0x4(%rsi,%r14,1),%eax
  494125:	xor    (%r14),%edx
  494128:	or     %edx,%eax
  49412a:	sete   %al
  49412d:	jmp    493c4b <tomo_multidb2_pad_79486+0x7a>
  494132:	mov    %r14,%rsi
  494135:	mov    %rcx,0x10(%rsp)
  49413a:	mov    %r9,0x8(%rsp)
  49413f:	mov    %r8d,(%rsp)
  494143:	call   2c8a0 <memcmp@plt>
  494148:	mov    (%rsp),%r8d
  49414c:	mov    0x8(%rsp),%r9
  494151:	mov    0x10(%rsp),%rcx
  494156:	test   %eax,%eax
  494158:	sete   %al
  49415b:	jmp    493c4b <tomo_multidb2_pad_79486+0x7a>
  494160:	test   %esi,%esi
  494162:	je     493c53 <tomo_multidb2_pad_79486+0x82>
  494168:	movzbl (%r14),%eax
  49416c:	cmp    %al,(%rdi)
  49416e:	jne    493b90 <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE+0xb0>
  494174:	mov    %esi,%eax
  494176:	shr    $1,%eax
  494178:	movzbl (%r14,%rax,1),%edx
  49417d:	cmp    %dl,(%rdi,%rax,1)
  494180:	jne    493b90 <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE+0xb0>
  494186:	lea    -0x1(%rsi),%eax
  494189:	movzbl (%r14,%rax,1),%esi
  49418e:	cmp    %sil,(%rdi,%rax,1)
  494192:	jne    493b90 <_ZN4tomo9FlatStore22snapshot_prepare_writeEmNS_5SliceE+0xb0>
  494198:	xor    %eax,%eax
  49419a:	jmp    493c85 <tomo_multidb2_pad_79486+0xb4>
  49419f:	nop
  4941a0:	movzbl 0x2(%r9),%eax
  4941a5:	xor    %edx,%edx
  4941a7:	test   $0x2,%al
  4941a9:	je     4941b6 <tomo_multidb2_pad_81248+0x1d6>
  4941ab:	movzbl 0x3(%r9),%eax
  4941b0:	lea    0x1(%rax),%edx
  4941b3:	movzbl %dl,%edx
  4941b6:	movzbl 0x2(%r9),%eax
  4941bb:	test   $0x2,%al
  4941bd:	jne    49425e <tomo_multidb2_pad_81248+0x27e>
  4941c3:	movzbl 0x3(%r9),%eax
  4941c8:	movzbl 0x2(%r9),%esi
  4941cd:	movzbl 0x2(%r9),%r11d
  4941d2:	shr    $1,%sil
  4941d5:	lea    0x0(,%rsi,4),%rdi
  4941dd:	lea    0x0(,%r11,8),%rsi
  4941e5:	and    $0x4,%edi
  4941e8:	and    $0x8,%esi
  4941eb:	lea    0x8(%rdi,%rsi,1),%rdi
  4941f0:	add    %r9,%rdi
  4941f3:	jmp    493ffd <tomo_multidb2_pad_81248+0x1d>
  4941f8:	cmp    $0x3,%edx
  4941fb:	jbe    494267 <tomo_multidb2_pad_81248+0x287>
  4941fd:	mov    -0x4(%rdi,%rdx,1),%eax
  494201:	xor    -0x4(%rdx,%r14,1),%eax
  494206:	mov    (%rdi),%edx
  494208:	xor    (%r14),%edx
  49420b:	or     %edx,%eax
  49420d:	jne    493d40 <tomo_multidb2_pad_80033+0x39>
  494213:	jmp    493ea6 <tomo_multidb2_pad_80033+0x19f>
  494218:	nopl   0x0(%rax,%rax,1)
  494220:	mov    %rsi,%rdx
  494223:	mov    %r14,%rsi
  494226:	mov    %rcx,0x10(%rsp)
  49422b:	mov    %r8,0x8(%rsp)
  494230:	mov    %r10d,(%rsp)
  494234:	call   2c8a0 <memcmp@plt>
  494239:	mov    (%rsp),%r10d
  49423d:	mov    0x8(%rsp),%r8
  494242:	test   %eax,%eax
  494244:	mov    0x10(%rsp),%rcx
  494249:	movabs $0xffffffffffff,%r9
  494253:	jne    493d40 <tomo_multidb2_pad_80033+0x39>
  494259:	jmp    493ea6 <tomo_multidb2_pad_80033+0x19f>
  49425e:	mov    0x8(%r9),%eax
  494262:	jmp    4941c8 <tomo_multidb2_pad_81248+0x1e8>
  494267:	test   %edx,%edx
  494269:	je     493ea6 <tomo_multidb2_pad_80033+0x19f>
  49426f:	movzbl (%r14),%eax
  494273:	cmp    %al,(%rdi)
  494275:	jne    493d40 <tomo_multidb2_pad_80033+0x39>
  49427b:	mov    %edx,%eax
  49427d:	shr    $1,%eax
  49427f:	movzbl (%r14,%rax,1),%esi
  494284:	cmp    %sil,(%rdi,%rax,1)
  494288:	jne    493d40 <tomo_multidb2_pad_80033+0x39>
  49428e:	lea    -0x1(%rdx),%eax
  494291:	movzbl (%r14,%rax,1),%esi
  494296:	cmp    %sil,(%rdi,%rax,1)
  49429a:	jne    493d40 <tomo_multidb2_pad_80033+0x39>
  4942a0:	jmp    493ea6 <tomo_multidb2_pad_80033+0x19f>
  4942a5:	add    %rcx,%r10
  4942a8:	mov    $0x1,%eax
  4942ad:	shl    $0x30,%rax
  4942b1:	or     (%r10),%rax
  4942b4:	mov    %rax,(%r10)
  4942b7:	xor    %eax,%eax
  4942b9:	jmp    493c85 <tomo_multidb2_pad_79486+0xb4>
  4942be:	mov    %rsi,%rdx
  4942c1:	mov    %r14,%rsi
  4942c4:	mov    %rcx,0x18(%rsp)
  4942c9:	mov    %r9,0x10(%rsp)
  4942ce:	mov    %r10,0x8(%rsp)
  4942d3:	mov    %r8d,(%rsp)
  4942d7:	call   2c8a0 <memcmp@plt>
  4942dc:	mov    (%rsp),%r8d
  4942e0:	test   %eax,%eax
  4942e2:	mov    0x8(%rsp),%r10
  4942e7:	mov    0x10(%rsp),%r9
  4942ec:	mov    0x18(%rsp),%rcx
  4942f1:	sete   %al
  4942f4:	jmp    49405b <tomo_multidb2_pad_81248+0x7b>
  4942f9:	cmp    $0x3,%eax
  4942fc:	jbe    494318 <tomo_multidb2_pad_81248+0x338>
  4942fe:	mov    -0x4(%rdi,%rax,1),%edx
  494302:	xor    -0x4(%rax,%r14,1),%edx
  494307:	mov    %edx,%eax
  494309:	mov    (%rdi),%edx
  49430b:	xor    (%r14),%edx
  49430e:	or     %edx,%eax
  494310:	sete   %al
  494313:	jmp    49405b <tomo_multidb2_pad_81248+0x7b>
  494318:	test   %eax,%eax
  49431a:	je     494063 <tomo_multidb2_pad_81248+0x83>
  494320:	movzbl (%r14),%esi
  494324:	cmp    %sil,(%rdi)
  494327:	jne    493f98 <tomo_multidb2_pad_80033+0x291>
  49432d:	mov    %eax,%edx
  49432f:	shr    $1,%edx
  494331:	movzbl (%r14,%rdx,1),%esi
  494336:	cmp    %sil,(%rdi,%rdx,1)
  49433a:	jne    493f98 <tomo_multidb2_pad_80033+0x291>
  494340:	dec    %eax
  494342:	movzbl (%r14,%rax,1),%esi
  494347:	cmp    %sil,(%rdi,%rax,1)
  49434b:	jne    493f98 <tomo_multidb2_pad_80033+0x291>
  494351:	jmp    494063 <tomo_multidb2_pad_81248+0x83>

Disassembly of section .rlfence:

Disassembly of section .fini:
