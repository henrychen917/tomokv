
build/cmdmeta/PRE/src/cmd/cmdmeta.o:     file format elf64-x86-64


Disassembly of section .text:

0000000000000a40 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE>:
     a40:	f3 0f 1e fa          	endbr64
     a44:	41 57                	push   %r15
     a46:	41 56                	push   %r14
     a48:	41 55                	push   %r13
     a4a:	41 89 f6             	mov    %esi,%r14d
     a4d:	41 54                	push   %r12
     a4f:	55                   	push   %rbp
     a50:	53                   	push   %rbx
     a51:	48 89 fb             	mov    %rdi,%rbx
     a54:	48 81 ec b8 00 00 00 	sub    $0xb8,%rsp
     a5b:	48 8b 02             	mov    (%rdx),%rax
     a5e:	48 89 7c 24 30       	mov    %rdi,0x30(%rsp)
     a63:	89 74 24 40          	mov    %esi,0x40(%rsp)
     a67:	48 89 14 24          	mov    %rdx,(%rsp)
     a6b:	48 89 4c 24 38       	mov    %rcx,0x38(%rsp)
     a70:	48 89 c7             	mov    %rax,%rdi
     a73:	48 89 44 24 10       	mov    %rax,0x10(%rsp)
     a78:	e8 00 00 00 00       	call   a7d <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x3d>
     a7d:	31 d2                	xor    %edx,%edx
     a7f:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # a86 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x46>
     a86:	89 44 24 1c          	mov    %eax,0x1c(%rsp)
     a8a:	8b 83 cc 00 00 00    	mov    0xcc(%rbx),%eax
     a90:	44 29 f0             	sub    %r14d,%eax
     a93:	89 44 24 20          	mov    %eax,0x20(%rsp)
     a97:	b8 01 00 00 00       	mov    $0x1,%eax
     a9c:	85 c0                	test   %eax,%eax
     a9e:	0f 85 0c 01 00 00    	jne    bb0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x170>
     aa4:	b8 01 00 00 00       	mov    $0x1,%eax
     aa9:	c4 e2 69 f7 c0       	shlx   %edx,%eax,%eax
     aae:	89 44 24 70          	mov    %eax,0x70(%rsp)
     ab2:	45 31 e4             	xor    %r12d,%r12d
     ab5:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
     aba:	48 8d 2d 00 00 00 00 	lea    0x0(%rip),%rbp        # ac1 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x81>
     ac1:	48 8d 1d 00 00 00 00 	lea    0x0(%rip),%rbx        # ac8 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x88>
     ac8:	eb 13                	jmp    add <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x9d>
     aca:	66 0f 1f 44 00 00    	nopw   0x0(%rax,%rax,1)
     ad0:	4a 8b 7c e5 00       	mov    0x0(%rbp,%r12,8),%rdi
     ad5:	48 89 de             	mov    %rbx,%rsi
     ad8:	e8 00 00 00 00       	call   add <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x9d>
     add:	85 c0                	test   %eax,%eax
     adf:	0f 84 0b 06 00 00    	je     10f0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x6b0>
     ae5:	49 ff c4             	inc    %r12
     ae8:	49 83 fc 0a          	cmp    $0xa,%r12
     aec:	75 e2                	jne    ad0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x90>
     aee:	31 d2                	xor    %edx,%edx
     af0:	b8 01 00 00 00       	mov    $0x1,%eax
     af5:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # afc <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xbc>
     afc:	85 c0                	test   %eax,%eax
     afe:	0f 85 dc 00 00 00    	jne    be0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1a0>
     b04:	b8 01 00 00 00       	mov    $0x1,%eax
     b09:	c4 e2 69 f7 c0       	shlx   %edx,%eax,%eax
     b0e:	89 44 24 44          	mov    %eax,0x44(%rsp)
     b12:	45 31 e4             	xor    %r12d,%r12d
     b15:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
     b1a:	48 8d 2d 00 00 00 00 	lea    0x0(%rip),%rbp        # b21 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe1>
     b21:	48 8d 1d 00 00 00 00 	lea    0x0(%rip),%rbx        # b28 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe8>
     b28:	eb 13                	jmp    b3d <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xfd>
     b2a:	66 0f 1f 44 00 00    	nopw   0x0(%rax,%rax,1)
     b30:	4a 8b 7c e5 00       	mov    0x0(%rbp,%r12,8),%rdi
     b35:	48 89 de             	mov    %rbx,%rsi
     b38:	e8 00 00 00 00       	call   b3d <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xfd>
     b3d:	85 c0                	test   %eax,%eax
     b3f:	0f 84 cb 05 00 00    	je     1110 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x6d0>
     b45:	49 ff c4             	inc    %r12
     b48:	49 83 fc 0a          	cmp    $0xa,%r12
     b4c:	75 e2                	jne    b30 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xf0>
     b4e:	44 8b 74 24 1c       	mov    0x1c(%rsp),%r14d
     b53:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
     b58:	48 8d 1d 00 00 00 00 	lea    0x0(%rip),%rbx        # b5f <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x11f>
     b5f:	48 89 da             	mov    %rbx,%rdx
     b62:	44 89 f6             	mov    %r14d,%esi
     b65:	e8 06 f5 ff ff       	call   70 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
     b6a:	84 c0                	test   %al,%al
     b6c:	75 1c                	jne    b8a <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x14a>
     b6e:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
     b73:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # b7a <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x13a>
     b7a:	44 89 f6             	mov    %r14d,%esi
     b7d:	e8 ee f4 ff ff       	call   70 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
     b82:	84 c0                	test   %al,%al
     b84:	0f 84 3d 02 00 00    	je     dc7 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x387>
     b8a:	83 7c 24 20 01       	cmpl   $0x1,0x20(%rsp)
     b8f:	0f 87 9b 00 00 00    	ja     c30 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1f0>
     b95:	b8 01 00 00 00       	mov    $0x1,%eax
     b9a:	48 81 c4 b8 00 00 00 	add    $0xb8,%rsp
     ba1:	5b                   	pop    %rbx
     ba2:	5d                   	pop    %rbp
     ba3:	41 5c                	pop    %r12
     ba5:	41 5d                	pop    %r13
     ba7:	41 5e                	pop    %r14
     ba9:	41 5f                	pop    %r15
     bab:	c3                   	ret
     bac:	0f 1f 40 00          	nopl   0x0(%rax)
     bb0:	48 ff c2             	inc    %rdx
     bb3:	48 83 fa 0a          	cmp    $0xa,%rdx
     bb7:	74 57                	je     c10 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1d0>
     bb9:	48 8b 0c d6          	mov    (%rsi,%rdx,8),%rcx
     bbd:	0f b6 01             	movzbl (%rcx),%eax
     bc0:	83 e8 52             	sub    $0x52,%eax
     bc3:	75 eb                	jne    bb0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x170>
     bc5:	0f b6 41 01          	movzbl 0x1(%rcx),%eax
     bc9:	83 e8 4f             	sub    $0x4f,%eax
     bcc:	75 e2                	jne    bb0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x170>
     bce:	0f b6 41 02          	movzbl 0x2(%rcx),%eax
     bd2:	e9 c5 fe ff ff       	jmp    a9c <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x5c>
     bd7:	66 0f 1f 84 00 00 00 00 00 	nopw   0x0(%rax,%rax,1)
     be0:	48 ff c2             	inc    %rdx
     be3:	48 83 fa 0a          	cmp    $0xa,%rdx
     be7:	74 37                	je     c20 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1e0>
     be9:	48 8b 0c d6          	mov    (%rsi,%rdx,8),%rcx
     bed:	0f b6 01             	movzbl (%rcx),%eax
     bf0:	83 e8 4f             	sub    $0x4f,%eax
     bf3:	75 eb                	jne    be0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1a0>
     bf5:	0f b6 41 01          	movzbl 0x1(%rcx),%eax
     bf9:	83 e8 57             	sub    $0x57,%eax
     bfc:	75 e2                	jne    be0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1a0>
     bfe:	0f b6 41 02          	movzbl 0x2(%rcx),%eax
     c02:	e9 f5 fe ff ff       	jmp    afc <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xbc>
     c07:	66 0f 1f 84 00 00 00 00 00 	nopw   0x0(%rax,%rax,1)
     c10:	66 c7 44 24 70 00 00 	movw   $0x0,0x70(%rsp)
     c17:	e9 96 fe ff ff       	jmp    ab2 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x72>
     c1c:	0f 1f 40 00          	nopl   0x0(%rax)
     c20:	66 c7 44 24 44 00 00 	movw   $0x0,0x44(%rsp)
     c27:	e9 e6 fe ff ff       	jmp    b12 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd2>
     c2c:	0f 1f 40 00          	nopl   0x0(%rax)
     c30:	8b 44 24 40          	mov    0x40(%rsp),%eax
     c34:	44 8d 70 01          	lea    0x1(%rax),%r14d
     c38:	48 8b 44 24 38       	mov    0x38(%rsp),%rax
     c3d:	48 8b 68 08          	mov    0x8(%rax),%rbp
     c41:	48 8b 78 10          	mov    0x10(%rax),%rdi
     c45:	48 39 fd             	cmp    %rdi,%rbp
     c48:	0f 84 8c 0e 00 00    	je     1ada <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x109a>
     c4e:	0f b7 4c 24 70       	movzwl 0x70(%rsp),%ecx
     c53:	44 89 75 00          	mov    %r14d,0x0(%rbp)
     c57:	66 89 4d 04          	mov    %cx,0x4(%rbp)
     c5b:	48 8d 4d 08          	lea    0x8(%rbp),%rcx
     c5f:	48 89 0c 24          	mov    %rcx,(%rsp)
     c63:	48 89 48 08          	mov    %rcx,0x8(%rax)
     c67:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
     c6b:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
     c70:	48 89 da             	mov    %rbx,%rdx
     c73:	e8 f8 f3 ff ff       	call   70 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
     c78:	84 c0                	test   %al,%al
     c7a:	0f 84 40 01 00 00    	je     dc0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x380>
     c80:	8b 44 24 40          	mov    0x40(%rsp),%eax
     c84:	44 8d 70 02          	lea    0x2(%rax),%r14d
     c88:	44 8d 58 03          	lea    0x3(%rax),%r11d
     c8c:	48 8b 44 24 30       	mov    0x30(%rsp),%rax
     c91:	8b a8 cc 00 00 00    	mov    0xcc(%rax),%ebp
     c97:	41 39 eb             	cmp    %ebp,%r11d
     c9a:	0f 83 20 01 00 00    	jae    dc0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x380>
     ca0:	4c 8b b8 c0 00 00 00 	mov    0xc0(%rax),%r15
     ca7:	48 8d 05 00 00 00 00 	lea    0x0(%rip),%rax        # cae <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x26e>
     cae:	31 f6                	xor    %esi,%esi
     cb0:	4c 8d 2d 00 00 00 00 	lea    0x0(%rip),%r13        # cb7 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x277>
     cb7:	c4 e1 f9 6e c0       	vmovq  %rax,%xmm0
     cbc:	48 8d 05 00 00 00 00 	lea    0x0(%rip),%rax        # cc3 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x283>
     cc3:	41 89 ec             	mov    %ebp,%r12d
     cc6:	89 74 24 10          	mov    %esi,0x10(%rsp)
     cca:	c4 e1 f9 6e d0       	vmovq  %rax,%xmm2
     ccf:	48 8d 05 00 00 00 00 	lea    0x0(%rip),%rax        # cd6 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x296>
     cd6:	c4 e1 f9 6e d8       	vmovq  %rax,%xmm3
     cdb:	4c 89 fb             	mov    %r15,%rbx
     cde:	eb 15                	jmp    cf5 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x2b5>
     ce0:	45 8d 5e 02          	lea    0x2(%r14),%r11d
     ce4:	45 8d 73 01          	lea    0x1(%r11),%r14d
     ce8:	41 83 c3 02          	add    $0x2,%r11d
     cec:	45 39 e3             	cmp    %r12d,%r11d
     cef:	0f 83 95 00 00 00    	jae    d8a <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x34a>
     cf5:	44 89 f0             	mov    %r14d,%eax
     cf8:	48 85 db             	test   %rbx,%rbx
     cfb:	0f 84 2f 09 00 00    	je     1630 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xbf0>
     d01:	48 c1 e0 04          	shl    $0x4,%rax
     d05:	48 01 d8             	add    %rbx,%rax
     d08:	48 8b 28             	mov    (%rax),%rbp
     d0b:	44 8b 78 08          	mov    0x8(%rax),%r15d
     d0f:	b9 05 00 00 00       	mov    $0x5,%ecx
     d14:	4c 89 ea             	mov    %r13,%rdx
     d17:	44 89 fe             	mov    %r15d,%esi
     d1a:	48 89 ef             	mov    %rbp,%rdi
     d1d:	e8 de f2 ff ff       	call   0 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceES1_.constprop.0.isra.0>
     d22:	84 c0                	test   %al,%al
     d24:	75 ba                	jne    ce0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x2a0>
     d26:	b9 02 00 00 00       	mov    $0x2,%ecx
     d2b:	c4 e1 f9 7e c2       	vmovq  %xmm0,%rdx
     d30:	44 89 fe             	mov    %r15d,%esi
     d33:	48 89 ef             	mov    %rbp,%rdi
     d36:	e8 c5 f2 ff ff       	call   0 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceES1_.constprop.0.isra.0>
     d3b:	84 c0                	test   %al,%al
     d3d:	75 a5                	jne    ce4 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x2a4>
     d3f:	b9 03 00 00 00       	mov    $0x3,%ecx
     d44:	c4 e1 f9 7e d2       	vmovq  %xmm2,%rdx
     d49:	44 89 fe             	mov    %r15d,%esi
     d4c:	48 89 ef             	mov    %rbp,%rdi
     d4f:	e8 ac f2 ff ff       	call   0 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceES1_.constprop.0.isra.0>
     d54:	84 c0                	test   %al,%al
     d56:	75 8c                	jne    ce4 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x2a4>
     d58:	b9 05 00 00 00       	mov    $0x5,%ecx
     d5d:	c4 e1 f9 7e da       	vmovq  %xmm3,%rdx
     d62:	44 89 fe             	mov    %r15d,%esi
     d65:	48 89 ef             	mov    %rbp,%rdi
     d68:	e8 93 f2 ff ff       	call   0 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceES1_.constprop.0.isra.0>
     d6d:	84 c0                	test   %al,%al
     d6f:	74 05                	je     d76 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x336>
     d71:	44 89 5c 24 10       	mov    %r11d,0x10(%rsp)
     d76:	45 89 f3             	mov    %r14d,%r11d
     d79:	45 8d 73 01          	lea    0x1(%r11),%r14d
     d7d:	41 83 c3 02          	add    $0x2,%r11d
     d81:	45 39 e3             	cmp    %r12d,%r11d
     d84:	0f 82 6b ff ff ff    	jb     cf5 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x2b5>
     d8a:	8b 74 24 10          	mov    0x10(%rsp),%esi
     d8e:	85 f6                	test   %esi,%esi
     d90:	74 2e                	je     dc0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x380>
     d92:	48 8b 5c 24 38       	mov    0x38(%rsp),%rbx
     d97:	48 8b 04 24          	mov    (%rsp),%rax
     d9b:	48 39 43 10          	cmp    %rax,0x10(%rbx)
     d9f:	0f 84 68 0e 00 00    	je     1c0d <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x11cd>
     da5:	0f b7 4c 24 44       	movzwl 0x44(%rsp),%ecx
     daa:	48 8d 68 08          	lea    0x8(%rax),%rbp
     dae:	89 30                	mov    %esi,(%rax)
     db0:	66 89 48 04          	mov    %cx,0x4(%rax)
     db4:	48 89 6b 08          	mov    %rbp,0x8(%rbx)
     db8:	0f 1f 84 00 00 00 00 00 	nopl   0x0(%rax,%rax,1)
     dc0:	31 c0                	xor    %eax,%eax
     dc2:	e9 d3 fd ff ff       	jmp    b9a <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x15a>
     dc7:	48 8b 04 24          	mov    (%rsp),%rax
     dcb:	80 78 2e 00          	cmpb   $0x0,0x2e(%rax)
     dcf:	0f 84 4f 03 00 00    	je     1124 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x6e4>
     dd5:	8b 5c 24 40          	mov    0x40(%rsp),%ebx
     dd9:	45 31 f6             	xor    %r14d,%r14d
     ddc:	45 31 e4             	xor    %r12d,%r12d
     ddf:	8d 43 02             	lea    0x2(%rbx),%eax
     de2:	89 84 24 a8 00 00 00 	mov    %eax,0xa8(%rsp)
     de9:	48 89 84 24 88 00 00 00 	mov    %rax,0x88(%rsp)
     df1:	48 c1 e0 04          	shl    $0x4,%rax
     df5:	48 89 84 24 90 00 00 00 	mov    %rax,0x90(%rsp)
     dfd:	8d 43 03             	lea    0x3(%rbx),%eax
     e00:	48 8d 1d 00 00 00 00 	lea    0x0(%rip),%rbx        # e07 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x3c7>
     e07:	89 44 24 74          	mov    %eax,0x74(%rsp)
     e0b:	48 89 84 24 80 00 00 00 	mov    %rax,0x80(%rsp)
     e13:	48 c1 e0 04          	shl    $0x4,%rax
     e17:	48 89 44 24 78       	mov    %rax,0x78(%rsp)
     e1c:	0f 1f 40 00          	nopl   0x0(%rax)
     e20:	48 8b 04 24          	mov    (%rsp),%rax
     e24:	48 8d 0d 00 00 00 00 	lea    0x0(%rip),%rcx        # e2b <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x3eb>
     e2b:	45 31 ff             	xor    %r15d,%r15d
     e2e:	0f b7 40 2c          	movzwl 0x2c(%rax),%eax
     e32:	44 01 e0             	add    %r12d,%eax
     e35:	89 c0                	mov    %eax,%eax
     e37:	0f b6 2c 01          	movzbl (%rcx,%rax,1),%ebp
     e3b:	48 8d 0d 00 00 00 00 	lea    0x0(%rip),%rcx        # e42 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x402>
     e42:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
     e47:	44 0f b7 6c c1 08    	movzwl 0x8(%rcx,%rax,8),%r13d
     e4d:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
     e52:	eb 1c                	jmp    e70 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x430>
     e54:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
     e5f:	90                   	nop
     e60:	4a 8b 3c fb          	mov    (%rbx,%r15,8),%rdi
     e64:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # e6b <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x42b>
     e6b:	e8 00 00 00 00       	call   e70 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x430>
     e70:	85 c0                	test   %eax,%eax
     e72:	0f 84 b8 02 00 00    	je     1130 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x6f0>
     e78:	49 ff c7             	inc    %r15
     e7b:	49 83 ff 0a          	cmp    $0xa,%r15
     e7f:	75 df                	jne    e60 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x420>
     e81:	45 31 ff             	xor    %r15d,%r15d
     e84:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
     e89:	4c 8d 35 00 00 00 00 	lea    0x0(%rip),%r14        # e90 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x450>
     e90:	eb 1a                	jmp    eac <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x46c>
     e92:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
     e9d:	0f 1f 00             	nopl   (%rax)
     ea0:	4a 8b 3c fb          	mov    (%rbx,%r15,8),%rdi
     ea4:	4c 89 f6             	mov    %r14,%rsi
     ea7:	e8 00 00 00 00       	call   eac <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x46c>
     eac:	85 c0                	test   %eax,%eax
     eae:	0f 84 4c 03 00 00    	je     1200 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x7c0>
     eb4:	49 ff c7             	inc    %r15
     eb7:	49 83 ff 0a          	cmp    $0xa,%r15
     ebb:	75 e3                	jne    ea0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x460>
     ebd:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
     ec2:	48 8d 0d 00 00 00 00 	lea    0x0(%rip),%rcx        # ec9 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x489>
     ec9:	48 8d 04 c1          	lea    (%rcx,%rax,8),%rax
     ecd:	0f b6 50 0a          	movzbl 0xa(%rax),%edx
     ed1:	84 d2                	test   %dl,%dl
     ed3:	0f 85 77 02 00 00    	jne    1150 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x710>
     ed9:	44 0f bf 70 0c       	movswl 0xc(%rax),%r14d
     ede:	8b 74 24 20          	mov    0x20(%rsp),%esi
     ee2:	44 89 f0             	mov    %r14d,%eax
     ee5:	c1 e8 1f             	shr    $0x1f,%eax
     ee8:	41 39 f6             	cmp    %esi,%r14d
     eeb:	41 0f 93 c0          	setae  %r8b
     eef:	41 08 c0             	or     %al,%r8b
     ef2:	0f 85 c8 01 00 00    	jne    10c0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x680>
     ef8:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
     efd:	48 8d 0d 00 00 00 00 	lea    0x0(%rip),%rcx        # f04 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x4c4>
     f04:	48 8d 04 c1          	lea    (%rcx,%rax,8),%rax
     f08:	0f b6 50 1a          	movzbl 0x1a(%rax),%edx
     f0c:	84 d2                	test   %dl,%dl
     f0e:	0f 85 5c 04 00 00    	jne    1370 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x930>
     f14:	0f bf 48 1c          	movswl 0x1c(%rax),%ecx
     f18:	66 85 c9             	test   %cx,%cx
     f1b:	0f 88 9f 08 00 00    	js     17c0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd80>
     f21:	0f b7 50 20          	movzwl 0x20(%rax),%edx
     f25:	66 85 d2             	test   %dx,%dx
     f28:	0f 8e 4e 09 00 00    	jle    187c <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe3c>
     f2e:	8d 41 01             	lea    0x1(%rcx),%eax
     f31:	0f bf ca             	movswl %dx,%ecx
     f34:	99                   	cltd
     f35:	f7 f9                	idiv   %ecx
     f37:	41 8d 4c 06 ff       	lea    -0x1(%r14,%rax,1),%ecx
     f3c:	8b 44 24 20          	mov    0x20(%rsp),%eax
     f40:	39 c1                	cmp    %eax,%ecx
     f42:	0f 8d 4d fc ff ff    	jge    b95 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x155>
     f48:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
     f4d:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # f54 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x514>
     f54:	0f bf 54 c6 1e       	movswl 0x1e(%rsi,%rax,8),%edx
     f59:	66 85 d2             	test   %dx,%dx
     f5c:	0f 8e 33 fc ff ff    	jle    b95 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x155>
     f62:	41 39 ce             	cmp    %ecx,%r14d
     f65:	0f 8f 55 01 00 00    	jg     10c0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x680>
     f6b:	8b 44 24 40          	mov    0x40(%rsp),%eax
     f6f:	44 89 64 24 48       	mov    %r12d,0x48(%rsp)
     f74:	45 89 ec             	mov    %r13d,%r12d
     f77:	4c 8b 6c 24 38       	mov    0x38(%rsp),%r13
     f7c:	45 8d 3c 06          	lea    (%r14,%rax,1),%r15d
     f80:	eb 2e                	jmp    fb0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x570>
     f82:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
     f8d:	0f 1f 00             	nopl   (%rax)
     f90:	44 89 7d 00          	mov    %r15d,0x0(%rbp)
     f94:	66 44 89 65 04       	mov    %r12w,0x4(%rbp)
     f99:	41 01 d6             	add    %edx,%r14d
     f9c:	48 83 c5 08          	add    $0x8,%rbp
     fa0:	41 01 d7             	add    %edx,%r15d
     fa3:	49 89 6d 08          	mov    %rbp,0x8(%r13)
     fa7:	44 39 f1             	cmp    %r14d,%ecx
     faa:	0f 8c 00 01 00 00    	jl     10b0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
     fb0:	49 8b 6d 08          	mov    0x8(%r13),%rbp
     fb4:	49 8b 7d 10          	mov    0x10(%r13),%rdi
     fb8:	48 39 fd             	cmp    %rdi,%rbp
     fbb:	75 d3                	jne    f90 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x550>
     fbd:	4d 8b 45 00          	mov    0x0(%r13),%r8
     fc1:	49 89 eb             	mov    %rbp,%r11
     fc4:	48 be ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rsi
     fce:	4d 29 c3             	sub    %r8,%r11
     fd1:	4c 89 d8             	mov    %r11,%rax
     fd4:	48 c1 f8 03          	sar    $0x3,%rax
     fd8:	48 39 f0             	cmp    %rsi,%rax
     fdb:	0f 84 c4 0e 00 00    	je     1ea5 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1465>
     fe1:	4c 39 c5             	cmp    %r8,%rbp
     fe4:	0f 84 b6 08 00 00    	je     18a0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe60>
     fea:	48 8d 34 00          	lea    (%rax,%rax,1),%rsi
     fee:	48 39 c6             	cmp    %rax,%rsi
     ff1:	0f 82 a9 0a 00 00    	jb     1aa0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1060>
     ff7:	48 85 f6             	test   %rsi,%rsi
     ffa:	0f 85 00 0e 00 00    	jne    1e00 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x13c0>
    1000:	45 31 d2             	xor    %r10d,%r10d
    1003:	31 f6                	xor    %esi,%esi
    1005:	45 89 3b             	mov    %r15d,(%r11)
    1008:	66 45 89 63 04       	mov    %r12w,0x4(%r11)
    100d:	c5 f9 ef c0          	vpxor  %xmm0,%xmm0,%xmm0
    1011:	4c 89 c0             	mov    %r8,%rax
    1014:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    101f:	90                   	nop
    1020:	4c 8b 08             	mov    (%rax),%r9
    1023:	48 83 c0 08          	add    $0x8,%rax
    1027:	48 83 c6 08          	add    $0x8,%rsi
    102b:	4c 89 4e f8          	mov    %r9,-0x8(%rsi)
    102f:	48 39 c5             	cmp    %rax,%rbp
    1032:	75 ec                	jne    1020 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x5e0>
    1034:	4c 29 c5             	sub    %r8,%rbp
    1037:	c4 e1 f9 7e c0       	vmovq  %xmm0,%rax
    103c:	48 8d 44 28 08       	lea    0x8(%rax,%rbp,1),%rax
    1041:	c4 e3 f9 22 c0 01    	vpinsrq $0x1,%rax,%xmm0,%xmm0
    1047:	4d 85 c0             	test   %r8,%r8
    104a:	74 40                	je     108c <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x64c>
    104c:	48 89 fe             	mov    %rdi,%rsi
    104f:	4c 89 c7             	mov    %r8,%rdi
    1052:	c5 f9 7f 44 24 50    	vmovdqa %xmm0,0x50(%rsp)
    1058:	89 94 24 a0 00 00 00 	mov    %edx,0xa0(%rsp)
    105f:	4c 29 c6             	sub    %r8,%rsi
    1062:	89 8c 24 98 00 00 00 	mov    %ecx,0x98(%rsp)
    1069:	4c 89 54 24 60       	mov    %r10,0x60(%rsp)
    106e:	e8 00 00 00 00       	call   1073 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x633>
    1073:	c5 f9 6f 44 24 50    	vmovdqa 0x50(%rsp),%xmm0
    1079:	8b 94 24 a0 00 00 00 	mov    0xa0(%rsp),%edx
    1080:	8b 8c 24 98 00 00 00 	mov    0x98(%rsp),%ecx
    1087:	4c 8b 54 24 60       	mov    0x60(%rsp),%r10
    108c:	41 01 d6             	add    %edx,%r14d
    108f:	c4 c1 7a 7f 45 00    	vmovdqu %xmm0,0x0(%r13)
    1095:	41 01 d7             	add    %edx,%r15d
    1098:	4d 89 55 10          	mov    %r10,0x10(%r13)
    109c:	44 39 f1             	cmp    %r14d,%ecx
    109f:	0f 8d 0b ff ff ff    	jge    fb0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x570>
    10a5:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    10b0:	44 8b 64 24 48       	mov    0x48(%rsp),%r12d
    10b5:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    10c0:	41 be 01 00 00 00    	mov    $0x1,%r14d
    10c6:	48 8b 04 24          	mov    (%rsp),%rax
    10ca:	41 ff c4             	inc    %r12d
    10cd:	0f b6 40 2e          	movzbl 0x2e(%rax),%eax
    10d1:	41 39 c4             	cmp    %eax,%r12d
    10d4:	0f 82 46 fd ff ff    	jb     e20 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x3e0>
    10da:	41 83 f6 01          	xor    $0x1,%r14d
    10de:	43 8d 04 36          	lea    (%r14,%r14,1),%eax
    10e2:	e9 b3 fa ff ff       	jmp    b9a <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x15a>
    10e7:	66 0f 1f 84 00 00 00 00 00 	nopw   0x0(%rax,%rax,1)
    10f0:	b8 01 00 00 00       	mov    $0x1,%eax
    10f5:	c4 e2 19 f7 c0       	shlx   %r12d,%eax,%eax
    10fa:	66 09 44 24 70       	or     %ax,0x70(%rsp)
    10ff:	e9 ea f9 ff ff       	jmp    aee <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xae>
    1104:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    110f:	90                   	nop
    1110:	b8 01 00 00 00       	mov    $0x1,%eax
    1115:	c4 e2 19 f7 c0       	shlx   %r12d,%eax,%eax
    111a:	66 09 44 24 44       	or     %ax,0x44(%rsp)
    111f:	e9 2a fa ff ff       	jmp    b4e <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x10e>
    1124:	b8 02 00 00 00       	mov    $0x2,%eax
    1129:	e9 6c fa ff ff       	jmp    b9a <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x15a>
    112e:	66 90                	xchg   %ax,%ax
    1130:	b8 01 00 00 00       	mov    $0x1,%eax
    1135:	c4 e2 01 f7 c0       	shlx   %r15d,%eax,%eax
    113a:	66 41 85 c5          	test   %ax,%r13w
    113e:	75 86                	jne    10c6 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x686>
    1140:	e9 3c fd ff ff       	jmp    e81 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x441>
    1145:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    1150:	80 fa 01             	cmp    $0x1,%dl
    1153:	0f 85 67 ff ff ff    	jne    10c0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x680>
    1159:	0f b7 50 18          	movzwl 0x18(%rax),%edx
    115d:	31 c9                	xor    %ecx,%ecx
    115f:	66 85 d2             	test   %dx,%dx
    1162:	0f 48 d1             	cmovs  %ecx,%edx
    1165:	8b 4c 24 20          	mov    0x20(%rsp),%ecx
    1169:	44 0f bf fa          	movswl %dx,%r15d
    116d:	41 39 cf             	cmp    %ecx,%r15d
    1170:	0f 83 4a ff ff ff    	jae    10c0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x680>
    1176:	48 8b 40 10          	mov    0x10(%rax),%rax
    117a:	48 8b 74 24 30       	mov    0x30(%rsp),%rsi
    117f:	66 44 89 6c 24 50    	mov    %r13w,0x50(%rsp)
    1185:	44 89 64 24 48       	mov    %r12d,0x48(%rsp)
    118a:	48 89 6c 24 60       	mov    %rbp,0x60(%rsp)
    118f:	45 89 fc             	mov    %r15d,%r12d
    1192:	44 8b 6c 24 40       	mov    0x40(%rsp),%r13d
    1197:	41 89 cf             	mov    %ecx,%r15d
    119a:	4c 8b b6 c0 00 00 00 	mov    0xc0(%rsi),%r14
    11a1:	48 89 c5             	mov    %rax,%rbp
    11a4:	eb 33                	jmp    11d9 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x799>
    11a6:	66 2e 0f 1f 84 00 00 00 00 00 	cs nopw 0x0(%rax,%rax,1)
    11b0:	48 c1 e0 04          	shl    $0x4,%rax
    11b4:	4c 01 f0             	add    %r14,%rax
    11b7:	8b 70 08             	mov    0x8(%rax),%esi
    11ba:	48 8b 38             	mov    (%rax),%rdi
    11bd:	48 89 ea             	mov    %rbp,%rdx
    11c0:	41 ff c4             	inc    %r12d
    11c3:	e8 a8 ee ff ff       	call   70 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    11c8:	84 c0                	test   %al,%al
    11ca:	0f 85 c0 05 00 00    	jne    1790 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd50>
    11d0:	45 39 fc             	cmp    %r15d,%r12d
    11d3:	0f 83 d7 fe ff ff    	jae    10b0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
    11d9:	43 8d 44 25 00       	lea    0x0(%r13,%r12,1),%eax
    11de:	4d 85 f6             	test   %r14,%r14
    11e1:	75 cd                	jne    11b0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x770>
    11e3:	48 8b 4c 24 30       	mov    0x30(%rsp),%rcx
    11e8:	48 83 c0 0d          	add    $0xd,%rax
    11ec:	48 c1 e0 04          	shl    $0x4,%rax
    11f0:	48 01 c8             	add    %rcx,%rax
    11f3:	eb c2                	jmp    11b7 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x777>
    11f5:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    1200:	44 89 ea             	mov    %r13d,%edx
    1203:	b8 01 00 00 00       	mov    $0x1,%eax
    1208:	c4 e2 01 f7 c0       	shlx   %r15d,%eax,%eax
    120d:	21 c2                	and    %eax,%edx
    120f:	c4 42 78 f2 ed       	andn   %r13d,%eax,%r13d
    1214:	66 85 d2             	test   %dx,%dx
    1217:	0f 84 a0 fc ff ff    	je     ebd <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x47d>
    121d:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    1221:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1226:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 122d <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x7ed>
    122d:	e8 3e ee ff ff       	call   70 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    1232:	41 89 c6             	mov    %eax,%r14d
    1235:	84 c0                	test   %al,%al
    1237:	0f 85 13 04 00 00    	jne    1650 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xc10>
    123d:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    1241:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1246:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 124d <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x80d>
    124d:	e8 1e ee ff ff       	call   70 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    1252:	84 c0                	test   %al,%al
    1254:	0f 84 63 fc ff ff    	je     ebd <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x47d>
    125a:	4c 8b 7c 24 30       	mov    0x30(%rsp),%r15
    125f:	41 8b 87 cc 00 00 00 	mov    0xcc(%r15),%eax
    1266:	39 84 24 a8 00 00 00 	cmp    %eax,0xa8(%rsp)
    126d:	0f 83 f2 00 00 00    	jae    1365 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x925>
    1273:	8b 4c 24 40          	mov    0x40(%rsp),%ecx
    1277:	4c 8b ac 24 90 00 00 00 	mov    0x90(%rsp),%r13
    127f:	c4 e1 f9 6e e5       	vmovq  %rbp,%xmm4
    1284:	44 89 64 24 48       	mov    %r12d,0x48(%rsp)
    1289:	29 c8                	sub    %ecx,%eax
    128b:	48 8b 8c 24 88 00 00 00 	mov    0x88(%rsp),%rcx
    1293:	83 e8 03             	sub    $0x3,%eax
    1296:	4c 8d 5c 01 01       	lea    0x1(%rcx,%rax,1),%r11
    129b:	49 8d 87 d0 00 00 00 	lea    0xd0(%r15),%rax
    12a2:	c4 e1 f9 6e c8       	vmovq  %rax,%xmm1
    12a7:	48 8d 05 00 00 00 00 	lea    0x0(%rip),%rax        # 12ae <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x86e>
    12ae:	c4 e1 f9 6e c0       	vmovq  %rax,%xmm0
    12b3:	48 8d 05 00 00 00 00 	lea    0x0(%rip),%rax        # 12ba <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x87a>
    12ba:	49 c1 e3 04          	shl    $0x4,%r11
    12be:	c4 e1 f9 6e d0       	vmovq  %rax,%xmm2
    12c3:	eb 2a                	jmp    12ef <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x8af>
    12c5:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    12d0:	49 8d 45 10          	lea    0x10(%r13),%rax
    12d4:	49 39 c3             	cmp    %rax,%r11
    12d7:	0f 84 07 05 00 00    	je     17e4 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xda4>
    12dd:	49 83 c5 20          	add    $0x20,%r13
    12e1:	4d 39 eb             	cmp    %r13,%r11
    12e4:	74 6c                	je     1352 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x912>
    12e6:	49 83 c5 10          	add    $0x10,%r13
    12ea:	4d 39 eb             	cmp    %r13,%r11
    12ed:	74 63                	je     1352 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x912>
    12ef:	45 84 f6             	test   %r14b,%r14b
    12f2:	75 f2                	jne    12e6 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x8a6>
    12f4:	49 8b 97 c0 00 00 00 	mov    0xc0(%r15),%rdx
    12fb:	c4 e1 f9 7e c8       	vmovq  %xmm1,%rax
    1300:	4c 01 e8             	add    %r13,%rax
    1303:	4a 8d 0c 2a          	lea    (%rdx,%r13,1),%rcx
    1307:	48 85 d2             	test   %rdx,%rdx
    130a:	c4 e1 f9 7e c2       	vmovq  %xmm0,%rdx
    130f:	48 0f 45 c1          	cmovne %rcx,%rax
    1313:	b9 03 00 00 00       	mov    $0x3,%ecx
    1318:	48 8b 28             	mov    (%rax),%rbp
    131b:	44 8b 60 08          	mov    0x8(%rax),%r12d
    131f:	48 89 ef             	mov    %rbp,%rdi
    1322:	44 89 e6             	mov    %r12d,%esi
    1325:	e8 d6 ec ff ff       	call   0 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceES1_.constprop.0.isra.0>
    132a:	41 89 c6             	mov    %eax,%r14d
    132d:	84 c0                	test   %al,%al
    132f:	75 9f                	jne    12d0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x890>
    1331:	b9 06 00 00 00       	mov    $0x6,%ecx
    1336:	c4 e1 f9 7e d2       	vmovq  %xmm2,%rdx
    133b:	44 89 e6             	mov    %r12d,%esi
    133e:	48 89 ef             	mov    %rbp,%rdi
    1341:	e8 ba ec ff ff       	call   0 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceES1_.constprop.0.isra.0>
    1346:	49 83 c5 10          	add    $0x10,%r13
    134a:	41 89 c6             	mov    %eax,%r14d
    134d:	4d 39 eb             	cmp    %r13,%r11
    1350:	75 9d                	jne    12ef <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x8af>
    1352:	44 8b 64 24 48       	mov    0x48(%rsp),%r12d
    1357:	c4 e1 f9 7e e5       	vmovq  %xmm4,%rbp
    135c:	45 84 f6             	test   %r14b,%r14b
    135f:	0f 85 89 04 00 00    	jne    17ee <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xdae>
    1365:	44 0f b7 6c 24 70    	movzwl 0x70(%rsp),%r13d
    136b:	e9 4d fb ff ff       	jmp    ebd <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x47d>
    1370:	80 fa 01             	cmp    $0x1,%dl
    1373:	0f 85 47 fd ff ff    	jne    10c0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x680>
    1379:	0f bf 50 22          	movswl 0x22(%rax),%edx
    137d:	0f bf 40 24          	movswl 0x24(%rax),%eax
    1381:	44 01 f2             	add    %r14d,%edx
    1384:	41 01 c6             	add    %eax,%r14d
    1387:	89 d0                	mov    %edx,%eax
    1389:	44 09 f0             	or     %r14d,%eax
    138c:	0f 88 03 f8 ff ff    	js     b95 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x155>
    1392:	8b 44 24 20          	mov    0x20(%rsp),%eax
    1396:	39 c2                	cmp    %eax,%edx
    1398:	0f 83 f7 f7 ff ff    	jae    b95 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x155>
    139e:	48 8b 44 24 30       	mov    0x30(%rsp),%rax
    13a3:	48 8b 88 c0 00 00 00 	mov    0xc0(%rax),%rcx
    13aa:	8b 44 24 40          	mov    0x40(%rsp),%eax
    13ae:	01 d0                	add    %edx,%eax
    13b0:	89 c0                	mov    %eax,%eax
    13b2:	48 85 c9             	test   %rcx,%rcx
    13b5:	0f 84 de 07 00 00    	je     1b99 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1159>
    13bb:	48 c1 e0 04          	shl    $0x4,%rax
    13bf:	48 01 c8             	add    %rcx,%rax
    13c2:	44 8b 50 08          	mov    0x8(%rax),%r10d
    13c6:	48 8b 30             	mov    (%rax),%rsi
    13c9:	45 85 d2             	test   %r10d,%r10d
    13cc:	0f 84 6a 05 00 00    	je     193c <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xefc>
    13d2:	0f b6 06             	movzbl (%rsi),%eax
    13d5:	3c 2b                	cmp    $0x2b,%al
    13d7:	0f 84 50 05 00 00    	je     192d <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xeed>
    13dd:	41 83 fa 01          	cmp    $0x1,%r10d
    13e1:	41 0f 94 c0          	sete   %r8b
    13e5:	3c 30                	cmp    $0x30,%al
    13e7:	0f 95 c0             	setne  %al
    13ea:	31 ff                	xor    %edi,%edi
    13ec:	41 09 c0             	or     %eax,%r8d
    13ef:	89 f8                	mov    %edi,%eax
    13f1:	45 31 ff             	xor    %r15d,%r15d
    13f4:	49 b9 cd cc cc cc cc cc cc cc 	movabs $0xcccccccccccccccd,%r9
    13fe:	48 01 c6             	add    %rax,%rsi
    1401:	29 f7                	sub    %esi,%edi
    1403:	eb 40                	jmp    1445 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa05>
    1405:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    1410:	0f be c8             	movsbl %al,%ecx
    1413:	83 e9 30             	sub    $0x30,%ecx
    1416:	48 63 c9             	movslq %ecx,%rcx
    1419:	48 89 ca             	mov    %rcx,%rdx
    141c:	48 f7 d2             	not    %rdx
    141f:	48 89 d0             	mov    %rdx,%rax
    1422:	49 f7 e1             	mul    %r9
    1425:	48 c1 ea 03          	shr    $0x3,%rdx
    1429:	4c 39 fa             	cmp    %r15,%rdx
    142c:	72 22                	jb     1450 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa10>
    142e:	4b 8d 04 bf          	lea    (%r15,%r15,4),%rax
    1432:	48 ff c6             	inc    %rsi
    1435:	4c 8d 3c 41          	lea    (%rcx,%rax,2),%r15
    1439:	8d 04 37             	lea    (%rdi,%rsi,1),%eax
    143c:	44 39 d0             	cmp    %r10d,%eax
    143f:	0f 83 bb 08 00 00    	jae    1d00 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x12c0>
    1445:	0f b6 06             	movzbl (%rsi),%eax
    1448:	8d 50 d0             	lea    -0x30(%rax),%edx
    144b:	80 fa 09             	cmp    $0x9,%dl
    144e:	76 c0                	jbe    1410 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x9d0>
    1450:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    1454:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1459:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 1460 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa20>
    1460:	44 88 44 24 48       	mov    %r8b,0x48(%rsp)
    1465:	e8 06 ec ff ff       	call   70 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    146a:	89 c1                	mov    %eax,%ecx
    146c:	84 c0                	test   %al,%al
    146e:	0f 85 4c fc ff ff    	jne    10c0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x680>
    1474:	44 0f b6 44 24 48    	movzbl 0x48(%rsp),%r8d
    147a:	45 31 ff             	xor    %r15d,%r15d
    147d:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    1481:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1486:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 148d <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa4d>
    148d:	88 4c 24 50          	mov    %cl,0x50(%rsp)
    1491:	44 88 44 24 48       	mov    %r8b,0x48(%rsp)
    1496:	e8 d5 eb ff ff       	call   70 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    149b:	44 0f b6 44 24 48    	movzbl 0x48(%rsp),%r8d
    14a1:	0f b6 4c 24 50       	movzbl 0x50(%rsp),%ecx
    14a6:	84 c0                	test   %al,%al
    14a8:	0f 84 d0 04 00 00    	je     197e <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xf3e>
    14ae:	84 c9                	test   %cl,%cl
    14b0:	0f 84 0a fc ff ff    	je     10c0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x680>
    14b6:	8b 4c 24 20          	mov    0x20(%rsp),%ecx
    14ba:	4c 39 f9             	cmp    %r15,%rcx
    14bd:	0f 82 fd fb ff ff    	jb     10c0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x680>
    14c3:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    14c8:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 14cf <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa8f>
    14cf:	48 0f bf 54 c6 1e    	movswq 0x1e(%rsi,%rax,8),%rdx
    14d5:	49 63 f6             	movslq %r14d,%rsi
    14d8:	48 89 d0             	mov    %rdx,%rax
    14db:	49 0f af d7          	imul   %r15,%rdx
    14df:	48 01 f2             	add    %rsi,%rdx
    14e2:	48 39 d1             	cmp    %rdx,%rcx
    14e5:	0f 82 d5 fb ff ff    	jb     10c0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x680>
    14eb:	4d 85 ff             	test   %r15,%r15
    14ee:	0f 95 c2             	setne  %dl
    14f1:	31 c9                	xor    %ecx,%ecx
    14f3:	45 84 c0             	test   %r8b,%r8b
    14f6:	44 0f 44 e9          	cmove  %ecx,%r13d
    14fa:	84 d2                	test   %dl,%dl
    14fc:	0f 84 be fb ff ff    	je     10c0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x680>
    1502:	8b 4c 24 40          	mov    0x40(%rsp),%ecx
    1506:	45 31 c0             	xor    %r8d,%r8d
    1509:	4d 89 fa             	mov    %r15,%r10
    150c:	44 89 64 24 48       	mov    %r12d,0x48(%rsp)
    1511:	44 0f bf c8          	movswl %ax,%r9d
    1515:	4c 8b 64 24 38       	mov    0x38(%rsp),%r12
    151a:	4d 89 c7             	mov    %r8,%r15
    151d:	41 01 ce             	add    %ecx,%r14d
    1520:	eb 21                	jmp    1543 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xb03>
    1522:	44 89 75 00          	mov    %r14d,0x0(%rbp)
    1526:	66 44 89 6d 04       	mov    %r13w,0x4(%rbp)
    152b:	48 83 c5 08          	add    $0x8,%rbp
    152f:	49 89 6c 24 08       	mov    %rbp,0x8(%r12)
    1534:	49 ff c7             	inc    %r15
    1537:	45 01 ce             	add    %r9d,%r14d
    153a:	4d 39 d7             	cmp    %r10,%r15
    153d:	0f 83 6d fb ff ff    	jae    10b0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
    1543:	49 8b 6c 24 08       	mov    0x8(%r12),%rbp
    1548:	49 8b 7c 24 10       	mov    0x10(%r12),%rdi
    154d:	48 39 fd             	cmp    %rdi,%rbp
    1550:	75 d0                	jne    1522 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xae2>
    1552:	49 8b 0c 24          	mov    (%r12),%rcx
    1556:	48 89 ee             	mov    %rbp,%rsi
    1559:	48 ba ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rdx
    1563:	48 29 ce             	sub    %rcx,%rsi
    1566:	48 89 f0             	mov    %rsi,%rax
    1569:	48 c1 f8 03          	sar    $0x3,%rax
    156d:	48 39 d0             	cmp    %rdx,%rax
    1570:	0f 84 2f 09 00 00    	je     1ea5 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1465>
    1576:	48 39 cd             	cmp    %rcx,%rbp
    1579:	0f 84 d0 07 00 00    	je     1d4f <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x130f>
    157f:	48 8d 14 00          	lea    (%rax,%rax,1),%rdx
    1583:	48 39 c2             	cmp    %rax,%rdx
    1586:	0f 82 53 08 00 00    	jb     1ddf <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x139f>
    158c:	48 85 d2             	test   %rdx,%rdx
    158f:	0f 85 f3 08 00 00    	jne    1e88 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1448>
    1595:	45 31 c0             	xor    %r8d,%r8d
    1598:	45 31 db             	xor    %r11d,%r11d
    159b:	31 d2                	xor    %edx,%edx
    159d:	44 89 36             	mov    %r14d,(%rsi)
    15a0:	66 44 89 6e 04       	mov    %r13w,0x4(%rsi)
    15a5:	48 89 c8             	mov    %rcx,%rax
    15a8:	48 8b 30             	mov    (%rax),%rsi
    15ab:	48 83 c0 08          	add    $0x8,%rax
    15af:	48 83 c2 08          	add    $0x8,%rdx
    15b3:	48 89 72 f8          	mov    %rsi,-0x8(%rdx)
    15b7:	48 39 c5             	cmp    %rax,%rbp
    15ba:	75 ec                	jne    15a8 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xb68>
    15bc:	48 29 cd             	sub    %rcx,%rbp
    15bf:	49 8d 44 28 08       	lea    0x8(%r8,%rbp,1),%rax
    15c4:	c4 c1 f9 6e f0       	vmovq  %r8,%xmm6
    15c9:	c4 e3 c9 22 c0 01    	vpinsrq $0x1,%rax,%xmm6,%xmm0
    15cf:	48 85 c9             	test   %rcx,%rcx
    15d2:	74 44                	je     1618 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xbd8>
    15d4:	48 89 fe             	mov    %rdi,%rsi
    15d7:	48 89 cf             	mov    %rcx,%rdi
    15da:	c5 f9 7f 44 24 60    	vmovdqa %xmm0,0x60(%rsp)
    15e0:	44 89 8c 24 a0 00 00 00 	mov    %r9d,0xa0(%rsp)
    15e8:	48 29 ce             	sub    %rcx,%rsi
    15eb:	4c 89 94 24 98 00 00 00 	mov    %r10,0x98(%rsp)
    15f3:	4c 89 5c 24 50       	mov    %r11,0x50(%rsp)
    15f8:	e8 00 00 00 00       	call   15fd <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xbbd>
    15fd:	c5 f9 6f 44 24 60    	vmovdqa 0x60(%rsp),%xmm0
    1603:	44 8b 8c 24 a0 00 00 00 	mov    0xa0(%rsp),%r9d
    160b:	4c 8b 94 24 98 00 00 00 	mov    0x98(%rsp),%r10
    1613:	4c 8b 5c 24 50       	mov    0x50(%rsp),%r11
    1618:	c4 c1 7a 7f 04 24    	vmovdqu %xmm0,(%r12)
    161e:	4d 89 5c 24 10       	mov    %r11,0x10(%r12)
    1623:	e9 0c ff ff ff       	jmp    1534 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xaf4>
    1628:	0f 1f 84 00 00 00 00 00 	nopl   0x0(%rax,%rax,1)
    1630:	48 8b 4c 24 30       	mov    0x30(%rsp),%rcx
    1635:	48 83 c0 0d          	add    $0xd,%rax
    1639:	48 c1 e0 04          	shl    $0x4,%rax
    163d:	48 01 c8             	add    %rcx,%rax
    1640:	e9 c3 f6 ff ff       	jmp    d08 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x2c8>
    1645:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    1650:	48 8b 4c 24 30       	mov    0x30(%rsp),%rcx
    1655:	8b 81 cc 00 00 00    	mov    0xcc(%rcx),%eax
    165b:	39 44 24 74          	cmp    %eax,0x74(%rsp)
    165f:	0f 83 90 06 00 00    	jae    1cf5 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x12b5>
    1665:	8b 74 24 40          	mov    0x40(%rsp),%esi
    1669:	4c 8b 6c 24 78       	mov    0x78(%rsp),%r13
    166e:	44 89 64 24 48       	mov    %r12d,0x48(%rsp)
    1673:	4c 8d b9 d0 00 00 00 	lea    0xd0(%rcx),%r15
    167a:	4c 8d 35 00 00 00 00 	lea    0x0(%rip),%r14        # 1681 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xc41>
    1681:	49 89 cc             	mov    %rcx,%r12
    1684:	29 f0                	sub    %esi,%eax
    1686:	48 8b b4 24 80 00 00 00 	mov    0x80(%rsp),%rsi
    168e:	83 e8 04             	sub    $0x4,%eax
    1691:	4c 8d 5c 06 01       	lea    0x1(%rsi,%rax,1),%r11
    1696:	31 c0                	xor    %eax,%eax
    1698:	49 c1 e3 04          	shl    $0x4,%r11
    169c:	0f 1f 40 00          	nopl   0x0(%rax)
    16a0:	84 c0                	test   %al,%al
    16a2:	75 2a                	jne    16ce <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xc8e>
    16a4:	49 8b 94 24 c0 00 00 00 	mov    0xc0(%r12),%rdx
    16ac:	4b 8d 04 2f          	lea    (%r15,%r13,1),%rax
    16b0:	4a 8d 0c 2a          	lea    (%rdx,%r13,1),%rcx
    16b4:	48 85 d2             	test   %rdx,%rdx
    16b7:	4c 89 f2             	mov    %r14,%rdx
    16ba:	48 0f 45 c1          	cmovne %rcx,%rax
    16be:	b9 03 00 00 00       	mov    $0x3,%ecx
    16c3:	8b 70 08             	mov    0x8(%rax),%esi
    16c6:	48 8b 38             	mov    (%rax),%rdi
    16c9:	e8 32 e9 ff ff       	call   0 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceES1_.constprop.0.isra.0>
    16ce:	49 83 c5 10          	add    $0x10,%r13
    16d2:	4d 39 dd             	cmp    %r11,%r13
    16d5:	75 c9                	jne    16a0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xc60>
    16d7:	44 8b 64 24 48       	mov    0x48(%rsp),%r12d
    16dc:	44 0f b7 6c 24 44    	movzwl 0x44(%rsp),%r13d
    16e2:	84 c0                	test   %al,%al
    16e4:	0f 84 d3 f7 ff ff    	je     ebd <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x47d>
    16ea:	45 31 ff             	xor    %r15d,%r15d
    16ed:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
    16f2:	4c 8d 35 00 00 00 00 	lea    0x0(%rip),%r14        # 16f9 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xcb9>
    16f9:	4c 8d 2d 00 00 00 00 	lea    0x0(%rip),%r13        # 1700 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xcc0>
    1700:	eb 1a                	jmp    171c <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xcdc>
    1702:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    170d:	0f 1f 00             	nopl   (%rax)
    1710:	4b 8b 3c fe          	mov    (%r14,%r15,8),%rdi
    1714:	4c 89 ee             	mov    %r13,%rsi
    1717:	e8 00 00 00 00       	call   171c <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xcdc>
    171c:	85 c0                	test   %eax,%eax
    171e:	0f 84 a7 03 00 00    	je     1acb <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x108b>
    1724:	49 ff c7             	inc    %r15
    1727:	49 83 ff 0a          	cmp    $0xa,%r15
    172b:	75 e3                	jne    1710 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xcd0>
    172d:	31 d2                	xor    %edx,%edx
    172f:	45 31 ed             	xor    %r13d,%r13d
    1732:	48 89 6c 24 48       	mov    %rbp,0x48(%rsp)
    1737:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
    173c:	4c 8d 3d 00 00 00 00 	lea    0x0(%rip),%r15        # 1743 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd03>
    1743:	4c 89 ed             	mov    %r13,%rbp
    1746:	4c 8d 35 00 00 00 00 	lea    0x0(%rip),%r14        # 174d <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd0d>
    174d:	41 89 d5             	mov    %edx,%r13d
    1750:	eb 1a                	jmp    176c <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd2c>
    1752:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    175d:	0f 1f 00             	nopl   (%rax)
    1760:	49 8b 3c ef          	mov    (%r15,%rbp,8),%rdi
    1764:	4c 89 f6             	mov    %r14,%rsi
    1767:	e8 00 00 00 00       	call   176c <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd2c>
    176c:	85 c0                	test   %eax,%eax
    176e:	0f 84 3b 03 00 00    	je     1aaf <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x106f>
    1774:	48 ff c5             	inc    %rbp
    1777:	48 83 fd 0a          	cmp    $0xa,%rbp
    177b:	75 e3                	jne    1760 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd20>
    177d:	48 8b 6c 24 48       	mov    0x48(%rsp),%rbp
    1782:	44 89 ea             	mov    %r13d,%edx
    1785:	83 ca 01             	or     $0x1,%edx
    1788:	41 89 d5             	mov    %edx,%r13d
    178b:	e9 2d f7 ff ff       	jmp    ebd <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x47d>
    1790:	45 89 e7             	mov    %r12d,%r15d
    1793:	44 0f b7 6c 24 50    	movzwl 0x50(%rsp),%r13d
    1799:	44 8b 64 24 48       	mov    0x48(%rsp),%r12d
    179e:	48 8b 6c 24 60       	mov    0x60(%rsp),%rbp
    17a3:	45 89 fe             	mov    %r15d,%r14d
    17a6:	45 85 ff             	test   %r15d,%r15d
    17a9:	0f 89 2f f7 ff ff    	jns    ede <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x49e>
    17af:	e9 0c f9 ff ff       	jmp    10c0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x680>
    17b4:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    17bf:	90                   	nop
    17c0:	8b 74 24 20          	mov    0x20(%rsp),%esi
    17c4:	01 f1                	add    %esi,%ecx
    17c6:	41 39 ce             	cmp    %ecx,%r14d
    17c9:	0f 8f f1 f8 ff ff    	jg     10c0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x680>
    17cf:	0f b7 50 20          	movzwl 0x20(%rax),%edx
    17d3:	66 85 d2             	test   %dx,%dx
    17d6:	0f 8e ab 00 00 00    	jle    1887 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe47>
    17dc:	44 29 f1             	sub    %r14d,%ecx
    17df:	e9 4a f7 ff ff       	jmp    f2e <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x4ee>
    17e4:	44 8b 64 24 48       	mov    0x48(%rsp),%r12d
    17e9:	c4 e1 f9 7e e5       	vmovq  %xmm4,%rbp
    17ee:	45 31 ff             	xor    %r15d,%r15d
    17f1:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
    17f6:	4c 8d 35 00 00 00 00 	lea    0x0(%rip),%r14        # 17fd <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xdbd>
    17fd:	4c 8d 2d 00 00 00 00 	lea    0x0(%rip),%r13        # 1804 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xdc4>
    1804:	eb 16                	jmp    181c <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xddc>
    1806:	66 2e 0f 1f 84 00 00 00 00 00 	cs nopw 0x0(%rax,%rax,1)
    1810:	4b 8b 3c fe          	mov    (%r14,%r15,8),%rdi
    1814:	4c 89 ee             	mov    %r13,%rsi
    1817:	e8 00 00 00 00       	call   181c <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xddc>
    181c:	85 c0                	test   %eax,%eax
    181e:	0f 84 aa 04 00 00    	je     1cce <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x128e>
    1824:	49 ff c7             	inc    %r15
    1827:	49 83 ff 0a          	cmp    $0xa,%r15
    182b:	75 e3                	jne    1810 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xdd0>
    182d:	66 c7 44 24 48 00 00 	movw   $0x0,0x48(%rsp)
    1834:	45 31 ff             	xor    %r15d,%r15d
    1837:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
    183c:	4c 8d 35 00 00 00 00 	lea    0x0(%rip),%r14        # 1843 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe03>
    1843:	4c 8d 2d 00 00 00 00 	lea    0x0(%rip),%r13        # 184a <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe0a>
    184a:	eb 10                	jmp    185c <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe1c>
    184c:	0f 1f 40 00          	nopl   0x0(%rax)
    1850:	4b 8b 3c fe          	mov    (%r14,%r15,8),%rdi
    1854:	4c 89 ee             	mov    %r13,%rsi
    1857:	e8 00 00 00 00       	call   185c <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe1c>
    185c:	85 c0                	test   %eax,%eax
    185e:	0f 84 7d 04 00 00    	je     1ce1 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x12a1>
    1864:	49 ff c7             	inc    %r15
    1867:	49 83 ff 0a          	cmp    $0xa,%r15
    186b:	75 e3                	jne    1850 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe10>
    186d:	44 0f b7 6c 24 48    	movzwl 0x48(%rsp),%r13d
    1873:	41 83 cd 01          	or     $0x1,%r13d
    1877:	e9 41 f6 ff ff       	jmp    ebd <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x47d>
    187c:	44 01 f1             	add    %r14d,%ecx
    187f:	39 f1                	cmp    %esi,%ecx
    1881:	0f 8d 0e f3 ff ff    	jge    b95 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x155>
    1887:	0f bf 50 1e          	movswl 0x1e(%rax),%edx
    188b:	66 85 d2             	test   %dx,%dx
    188e:	0f 8f d7 f6 ff ff    	jg     f6b <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x52b>
    1894:	e9 fc f2 ff ff       	jmp    b95 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x155>
    1899:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
    18a0:	48 83 c0 01          	add    $0x1,%rax
    18a4:	0f 82 f6 01 00 00    	jb     1aa0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1060>
    18aa:	48 39 f0             	cmp    %rsi,%rax
    18ad:	48 0f 47 c6          	cmova  %rsi,%rax
    18b1:	4c 8d 14 c5 00 00 00 00 	lea    0x0(,%rax,8),%r10
    18b9:	4c 89 d7             	mov    %r10,%rdi
    18bc:	89 94 24 ac 00 00 00 	mov    %edx,0xac(%rsp)
    18c3:	89 8c 24 a0 00 00 00 	mov    %ecx,0xa0(%rsp)
    18ca:	4c 89 9c 24 98 00 00 00 	mov    %r11,0x98(%rsp)
    18d2:	4c 89 44 24 60       	mov    %r8,0x60(%rsp)
    18d7:	4c 89 54 24 50       	mov    %r10,0x50(%rsp)
    18dc:	e8 00 00 00 00       	call   18e1 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xea1>
    18e1:	4c 8b 54 24 50       	mov    0x50(%rsp),%r10
    18e6:	4c 8b 9c 24 98 00 00 00 	mov    0x98(%rsp),%r11
    18ee:	4c 8b 44 24 60       	mov    0x60(%rsp),%r8
    18f3:	48 89 c6             	mov    %rax,%rsi
    18f6:	c4 e1 f9 6e c0       	vmovq  %rax,%xmm0
    18fb:	49 8b 7d 10          	mov    0x10(%r13),%rdi
    18ff:	8b 8c 24 a0 00 00 00 	mov    0xa0(%rsp),%ecx
    1906:	8b 94 24 ac 00 00 00 	mov    0xac(%rsp),%edx
    190d:	49 01 c2             	add    %rax,%r10
    1910:	49 01 c3             	add    %rax,%r11
    1913:	48 83 c0 08          	add    $0x8,%rax
    1917:	4c 39 c5             	cmp    %r8,%rbp
    191a:	45 89 3b             	mov    %r15d,(%r11)
    191d:	66 45 89 63 04       	mov    %r12w,0x4(%r11)
    1922:	0f 85 e9 f6 ff ff    	jne    1011 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x5d1>
    1928:	e9 14 f7 ff ff       	jmp    1041 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x601>
    192d:	bf 01 00 00 00       	mov    $0x1,%edi
    1932:	41 83 fa 01          	cmp    $0x1,%r10d
    1936:	0f 85 b3 fa ff ff    	jne    13ef <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x9af>
    193c:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    1940:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1945:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 194c <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xf0c>
    194c:	e8 1f e7 ff ff       	call   70 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    1951:	84 c0                	test   %al,%al
    1953:	0f 85 67 f7 ff ff    	jne    10c0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x680>
    1959:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    195d:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1962:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 1969 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xf29>
    1969:	e8 02 e7 ff ff       	call   70 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    196e:	89 c1                	mov    %eax,%ecx
    1970:	84 c0                	test   %al,%al
    1972:	0f 85 48 f7 ff ff    	jne    10c0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x680>
    1978:	45 31 c0             	xor    %r8d,%r8d
    197b:	45 31 ff             	xor    %r15d,%r15d
    197e:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    1982:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1987:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 198e <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xf4e>
    198e:	88 4c 24 50          	mov    %cl,0x50(%rsp)
    1992:	44 88 44 24 48       	mov    %r8b,0x48(%rsp)
    1997:	e8 d4 e6 ff ff       	call   70 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    199c:	44 0f b6 44 24 48    	movzbl 0x48(%rsp),%r8d
    19a2:	0f b6 4c 24 50       	movzbl 0x50(%rsp),%ecx
    19a7:	84 c0                	test   %al,%al
    19a9:	0f 85 ff fa ff ff    	jne    14ae <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa6e>
    19af:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    19b3:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    19b8:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 19bf <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xf7f>
    19bf:	88 4c 24 50          	mov    %cl,0x50(%rsp)
    19c3:	44 88 44 24 48       	mov    %r8b,0x48(%rsp)
    19c8:	e8 a3 e6 ff ff       	call   70 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    19cd:	44 0f b6 44 24 48    	movzbl 0x48(%rsp),%r8d
    19d3:	0f b6 4c 24 50       	movzbl 0x50(%rsp),%ecx
    19d8:	84 c0                	test   %al,%al
    19da:	0f 85 ce fa ff ff    	jne    14ae <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa6e>
    19e0:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    19e4:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    19e9:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 19f0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xfb0>
    19f0:	88 4c 24 50          	mov    %cl,0x50(%rsp)
    19f4:	44 88 44 24 48       	mov    %r8b,0x48(%rsp)
    19f9:	e8 72 e6 ff ff       	call   70 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    19fe:	44 0f b6 44 24 48    	movzbl 0x48(%rsp),%r8d
    1a04:	0f b6 4c 24 50       	movzbl 0x50(%rsp),%ecx
    1a09:	84 c0                	test   %al,%al
    1a0b:	0f 85 9d fa ff ff    	jne    14ae <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa6e>
    1a11:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    1a15:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1a1a:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 1a21 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xfe1>
    1a21:	88 4c 24 50          	mov    %cl,0x50(%rsp)
    1a25:	44 88 44 24 48       	mov    %r8b,0x48(%rsp)
    1a2a:	e8 41 e6 ff ff       	call   70 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    1a2f:	0f b6 4c 24 50       	movzbl 0x50(%rsp),%ecx
    1a34:	89 c6                	mov    %eax,%esi
    1a36:	84 c9                	test   %cl,%cl
    1a38:	0f 84 b0 03 00 00    	je     1dee <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x13ae>
    1a3e:	8b 4c 24 20          	mov    0x20(%rsp),%ecx
    1a42:	4c 39 f9             	cmp    %r15,%rcx
    1a45:	0f 82 a3 03 00 00    	jb     1dee <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x13ae>
    1a4b:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    1a50:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 1a57 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1017>
    1a57:	49 63 fe             	movslq %r14d,%rdi
    1a5a:	44 0f b6 44 24 48    	movzbl 0x48(%rsp),%r8d
    1a60:	48 0f bf 54 c2 1e    	movswq 0x1e(%rdx,%rax,8),%rdx
    1a66:	48 89 d0             	mov    %rdx,%rax
    1a69:	49 0f af d7          	imul   %r15,%rdx
    1a6d:	48 01 fa             	add    %rdi,%rdx
    1a70:	48 39 d1             	cmp    %rdx,%rcx
    1a73:	0f 82 75 03 00 00    	jb     1dee <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x13ae>
    1a79:	4d 85 ff             	test   %r15,%r15
    1a7c:	0f 95 c2             	setne  %dl
    1a7f:	40 84 f6             	test   %sil,%sil
    1a82:	0f 85 69 fa ff ff    	jne    14f1 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xab1>
    1a88:	84 d2                	test   %dl,%dl
    1a8a:	0f 85 61 fa ff ff    	jne    14f1 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xab1>
    1a90:	e9 00 f1 ff ff       	jmp    b95 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x155>
    1a95:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    1aa0:	49 ba f8 ff ff ff ff ff ff 7f 	movabs $0x7ffffffffffffff8,%r10
    1aaa:	e9 0a fe ff ff       	jmp    18b9 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe79>
    1aaf:	44 89 ea             	mov    %r13d,%edx
    1ab2:	b8 01 00 00 00       	mov    $0x1,%eax
    1ab7:	49 89 ed             	mov    %rbp,%r13
    1aba:	48 8b 6c 24 48       	mov    0x48(%rsp),%rbp
    1abf:	c4 e2 11 f7 c0       	shlx   %r13d,%eax,%eax
    1ac4:	09 c2                	or     %eax,%edx
    1ac6:	e9 ba fc ff ff       	jmp    1785 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd45>
    1acb:	ba 01 00 00 00       	mov    $0x1,%edx
    1ad0:	c4 e2 01 f7 d2       	shlx   %r15d,%edx,%edx
    1ad5:	e9 55 fc ff ff       	jmp    172f <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xcef>
    1ada:	48 8b 44 24 38       	mov    0x38(%rsp),%rax
    1adf:	49 89 ef             	mov    %rbp,%r15
    1ae2:	4c 8b 20             	mov    (%rax),%r12
    1ae5:	48 b8 ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rax
    1aef:	4d 29 e7             	sub    %r12,%r15
    1af2:	4c 89 fa             	mov    %r15,%rdx
    1af5:	48 c1 fa 03          	sar    $0x3,%rdx
    1af9:	48 39 c2             	cmp    %rax,%rdx
    1afc:	0f 84 a3 03 00 00    	je     1ea5 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1465>
    1b02:	4c 39 e5             	cmp    %r12,%rbp
    1b05:	0f 84 a3 00 00 00    	je     1bae <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x116e>
    1b0b:	48 8d 04 12          	lea    (%rdx,%rdx,1),%rax
    1b0f:	48 39 d0             	cmp    %rdx,%rax
    1b12:	0f 82 28 02 00 00    	jb     1d40 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1300>
    1b18:	48 85 c0             	test   %rax,%rax
    1b1b:	0f 85 9a 00 00 00    	jne    1bbb <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x117b>
    1b21:	0f b7 44 24 70       	movzwl 0x70(%rsp),%eax
    1b26:	45 31 ed             	xor    %r13d,%r13d
    1b29:	45 89 37             	mov    %r14d,(%r15)
    1b2c:	66 41 89 47 04       	mov    %ax,0x4(%r15)
    1b31:	31 c0                	xor    %eax,%eax
    1b33:	4c 29 e5             	sub    %r12,%rbp
    1b36:	48 89 c2             	mov    %rax,%rdx
    1b39:	4c 89 e1             	mov    %r12,%rcx
    1b3c:	48 01 c5             	add    %rax,%rbp
    1b3f:	90                   	nop
    1b40:	48 8b 31             	mov    (%rcx),%rsi
    1b43:	48 83 c2 08          	add    $0x8,%rdx
    1b47:	48 83 c1 08          	add    $0x8,%rcx
    1b4b:	48 89 72 f8          	mov    %rsi,-0x8(%rdx)
    1b4f:	48 39 d5             	cmp    %rdx,%rbp
    1b52:	75 ec                	jne    1b40 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1100>
    1b54:	48 8d 4d 08          	lea    0x8(%rbp),%rcx
    1b58:	48 89 0c 24          	mov    %rcx,(%rsp)
    1b5c:	c4 e1 f9 6e e0       	vmovq  %rax,%xmm4
    1b61:	c4 e3 d9 22 04 24 01 	vpinsrq $0x1,(%rsp),%xmm4,%xmm0
    1b68:	4d 85 e4             	test   %r12,%r12
    1b6b:	74 1a                	je     1b87 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1147>
    1b6d:	48 89 fe             	mov    %rdi,%rsi
    1b70:	4c 89 e7             	mov    %r12,%rdi
    1b73:	c5 f9 7f 44 24 20    	vmovdqa %xmm0,0x20(%rsp)
    1b79:	4c 29 e6             	sub    %r12,%rsi
    1b7c:	e8 00 00 00 00       	call   1b81 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1141>
    1b81:	c5 f9 6f 44 24 20    	vmovdqa 0x20(%rsp),%xmm0
    1b87:	48 8b 44 24 38       	mov    0x38(%rsp),%rax
    1b8c:	c5 fa 7f 00          	vmovdqu %xmm0,(%rax)
    1b90:	4c 89 68 10          	mov    %r13,0x10(%rax)
    1b94:	e9 ce f0 ff ff       	jmp    c67 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x227>
    1b99:	48 8b 4c 24 30       	mov    0x30(%rsp),%rcx
    1b9e:	48 83 c0 0d          	add    $0xd,%rax
    1ba2:	48 c1 e0 04          	shl    $0x4,%rax
    1ba6:	48 01 c8             	add    %rcx,%rax
    1ba9:	e9 14 f8 ff ff       	jmp    13c2 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x982>
    1bae:	48 89 d0             	mov    %rdx,%rax
    1bb1:	48 83 c0 01          	add    $0x1,%rax
    1bb5:	0f 82 85 01 00 00    	jb     1d40 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1300>
    1bbb:	48 ba ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rdx
    1bc5:	48 39 d0             	cmp    %rdx,%rax
    1bc8:	48 0f 46 d0          	cmovbe %rax,%rdx
    1bcc:	49 89 d5             	mov    %rdx,%r13
    1bcf:	49 c1 e5 03          	shl    $0x3,%r13
    1bd3:	4c 89 ef             	mov    %r13,%rdi
    1bd6:	e8 00 00 00 00       	call   1bdb <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x119b>
    1bdb:	48 8b 4c 24 38       	mov    0x38(%rsp),%rcx
    1be0:	49 01 c7             	add    %rax,%r15
    1be3:	49 01 c5             	add    %rax,%r13
    1be6:	45 89 37             	mov    %r14d,(%r15)
    1be9:	48 8b 79 10          	mov    0x10(%rcx),%rdi
    1bed:	0f b7 4c 24 70       	movzwl 0x70(%rsp),%ecx
    1bf2:	66 41 89 4f 04       	mov    %cx,0x4(%r15)
    1bf7:	4c 39 e5             	cmp    %r12,%rbp
    1bfa:	0f 85 33 ff ff ff    	jne    1b33 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x10f3>
    1c00:	48 8d 48 08          	lea    0x8(%rax),%rcx
    1c04:	48 89 0c 24          	mov    %rcx,(%rsp)
    1c08:	e9 4f ff ff ff       	jmp    1b5c <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x111c>
    1c0d:	48 8b 44 24 38       	mov    0x38(%rsp),%rax
    1c12:	48 8b 1c 24          	mov    (%rsp),%rbx
    1c16:	4c 8b 20             	mov    (%rax),%r12
    1c19:	49 89 de             	mov    %rbx,%r14
    1c1c:	48 b8 ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rax
    1c26:	4d 29 e6             	sub    %r12,%r14
    1c29:	4c 89 f2             	mov    %r14,%rdx
    1c2c:	48 c1 fa 03          	sar    $0x3,%rdx
    1c30:	48 39 c2             	cmp    %rax,%rdx
    1c33:	0f 84 6c 02 00 00    	je     1ea5 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1465>
    1c39:	49 39 dc             	cmp    %rbx,%r12
    1c3c:	0f 84 db 01 00 00    	je     1e1d <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x13dd>
    1c42:	48 8d 04 12          	lea    (%rdx,%rdx,1),%rax
    1c46:	48 39 d0             	cmp    %rdx,%rax
    1c49:	0f 82 2d 02 00 00    	jb     1e7c <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x143c>
    1c4f:	48 85 c0             	test   %rax,%rax
    1c52:	0f 85 ce 01 00 00    	jne    1e26 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x13e6>
    1c58:	0f b7 44 24 44       	movzwl 0x44(%rsp),%eax
    1c5d:	48 8b 0c 24          	mov    (%rsp),%rcx
    1c61:	41 89 36             	mov    %esi,(%r14)
    1c64:	31 db                	xor    %ebx,%ebx
    1c66:	31 f6                	xor    %esi,%esi
    1c68:	66 41 89 46 04       	mov    %ax,0x4(%r14)
    1c6d:	31 c0                	xor    %eax,%eax
    1c6f:	4c 89 e2             	mov    %r12,%rdx
    1c72:	48 8b 3a             	mov    (%rdx),%rdi
    1c75:	48 83 c2 08          	add    $0x8,%rdx
    1c79:	48 83 c0 08          	add    $0x8,%rax
    1c7d:	48 89 78 f8          	mov    %rdi,-0x8(%rax)
    1c81:	48 8b 3c 24          	mov    (%rsp),%rdi
    1c85:	48 39 fa             	cmp    %rdi,%rdx
    1c88:	75 e8                	jne    1c72 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1232>
    1c8a:	4c 29 e2             	sub    %r12,%rdx
    1c8d:	c4 e1 f9 6e ee       	vmovq  %rsi,%xmm5
    1c92:	48 8d 44 16 08       	lea    0x8(%rsi,%rdx,1),%rax
    1c97:	c4 e3 d1 22 c0 01    	vpinsrq $0x1,%rax,%xmm5,%xmm0
    1c9d:	4d 85 e4             	test   %r12,%r12
    1ca0:	74 18                	je     1cba <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x127a>
    1ca2:	4c 29 e1             	sub    %r12,%rcx
    1ca5:	4c 89 e7             	mov    %r12,%rdi
    1ca8:	c5 f9 7f 04 24       	vmovdqa %xmm0,(%rsp)
    1cad:	48 89 ce             	mov    %rcx,%rsi
    1cb0:	e8 00 00 00 00       	call   1cb5 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1275>
    1cb5:	c5 f9 6f 04 24       	vmovdqa (%rsp),%xmm0
    1cba:	48 8b 44 24 38       	mov    0x38(%rsp),%rax
    1cbf:	c5 fa 7f 00          	vmovdqu %xmm0,(%rax)
    1cc3:	48 89 58 10          	mov    %rbx,0x10(%rax)
    1cc7:	31 c0                	xor    %eax,%eax
    1cc9:	e9 cc ee ff ff       	jmp    b9a <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x15a>
    1cce:	b8 01 00 00 00       	mov    $0x1,%eax
    1cd3:	c4 e2 01 f7 c0       	shlx   %r15d,%eax,%eax
    1cd8:	89 44 24 48          	mov    %eax,0x48(%rsp)
    1cdc:	e9 53 fb ff ff       	jmp    1834 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xdf4>
    1ce1:	b8 01 00 00 00       	mov    $0x1,%eax
    1ce6:	c4 e2 01 f7 c0       	shlx   %r15d,%eax,%eax
    1ceb:	66 09 44 24 48       	or     %ax,0x48(%rsp)
    1cf0:	e9 78 fb ff ff       	jmp    186d <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe2d>
    1cf5:	44 0f b7 6c 24 44    	movzwl 0x44(%rsp),%r13d
    1cfb:	e9 bd f1 ff ff       	jmp    ebd <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x47d>
    1d00:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    1d04:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1d09:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 1d10 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x12d0>
    1d10:	44 88 44 24 48       	mov    %r8b,0x48(%rsp)
    1d15:	e8 56 e3 ff ff       	call   70 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    1d1a:	44 0f b6 44 24 48    	movzbl 0x48(%rsp),%r8d
    1d20:	84 c0                	test   %al,%al
    1d22:	0f 85 8e f7 ff ff    	jne    14b6 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa76>
    1d28:	b9 01 00 00 00       	mov    $0x1,%ecx
    1d2d:	e9 4b f7 ff ff       	jmp    147d <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa3d>
    1d32:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    1d3d:	0f 1f 00             	nopl   (%rax)
    1d40:	49 bd f8 ff ff ff ff ff ff 7f 	movabs $0x7ffffffffffffff8,%r13
    1d4a:	e9 84 fe ff ff       	jmp    1bd3 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1193>
    1d4f:	48 83 c0 01          	add    $0x1,%rax
    1d53:	0f 82 86 00 00 00    	jb     1ddf <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x139f>
    1d59:	48 39 d0             	cmp    %rdx,%rax
    1d5c:	48 0f 47 c2          	cmova  %rdx,%rax
    1d60:	4c 8d 1c c5 00 00 00 00 	lea    0x0(,%rax,8),%r11
    1d68:	4c 89 df             	mov    %r11,%rdi
    1d6b:	44 89 8c 24 ac 00 00 00 	mov    %r9d,0xac(%rsp)
    1d73:	4c 89 94 24 a0 00 00 00 	mov    %r10,0xa0(%rsp)
    1d7b:	48 89 b4 24 98 00 00 00 	mov    %rsi,0x98(%rsp)
    1d83:	48 89 4c 24 60       	mov    %rcx,0x60(%rsp)
    1d88:	4c 89 5c 24 50       	mov    %r11,0x50(%rsp)
    1d8d:	e8 00 00 00 00       	call   1d92 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1352>
    1d92:	4c 8b 5c 24 50       	mov    0x50(%rsp),%r11
    1d97:	48 8b b4 24 98 00 00 00 	mov    0x98(%rsp),%rsi
    1d9f:	48 8b 4c 24 60       	mov    0x60(%rsp),%rcx
    1da4:	48 89 c2             	mov    %rax,%rdx
    1da7:	49 89 c0             	mov    %rax,%r8
    1daa:	49 8b 7c 24 10       	mov    0x10(%r12),%rdi
    1daf:	4c 8b 94 24 a0 00 00 00 	mov    0xa0(%rsp),%r10
    1db7:	44 8b 8c 24 ac 00 00 00 	mov    0xac(%rsp),%r9d
    1dbf:	49 01 c3             	add    %rax,%r11
    1dc2:	48 01 c6             	add    %rax,%rsi
    1dc5:	48 39 cd             	cmp    %rcx,%rbp
    1dc8:	48 8d 40 08          	lea    0x8(%rax),%rax
    1dcc:	44 89 36             	mov    %r14d,(%rsi)
    1dcf:	66 44 89 6e 04       	mov    %r13w,0x4(%rsi)
    1dd4:	0f 85 cb f7 ff ff    	jne    15a5 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xb65>
    1dda:	e9 e5 f7 ff ff       	jmp    15c4 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xb84>
    1ddf:	49 bb f8 ff ff ff ff ff ff 7f 	movabs $0x7ffffffffffffff8,%r11
    1de9:	e9 7a ff ff ff       	jmp    1d68 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1328>
    1dee:	40 84 f6             	test   %sil,%sil
    1df1:	0f 84 9e ed ff ff    	je     b95 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x155>
    1df7:	e9 c4 f2 ff ff       	jmp    10c0 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x680>
    1dfc:	0f 1f 40 00          	nopl   0x0(%rax)
    1e00:	48 b8 ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rax
    1e0a:	48 39 c6             	cmp    %rax,%rsi
    1e0d:	48 0f 46 c6          	cmovbe %rsi,%rax
    1e11:	49 89 c2             	mov    %rax,%r10
    1e14:	49 c1 e2 03          	shl    $0x3,%r10
    1e18:	e9 9c fa ff ff       	jmp    18b9 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe79>
    1e1d:	48 89 d0             	mov    %rdx,%rax
    1e20:	48 83 c0 01          	add    $0x1,%rax
    1e24:	72 56                	jb     1e7c <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x143c>
    1e26:	48 ba ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rdx
    1e30:	48 39 d0             	cmp    %rdx,%rax
    1e33:	48 0f 47 c2          	cmova  %rdx,%rax
    1e37:	48 8d 1c c5 00 00 00 00 	lea    0x0(,%rax,8),%rbx
    1e3f:	48 89 df             	mov    %rbx,%rdi
    1e42:	89 74 24 10          	mov    %esi,0x10(%rsp)
    1e46:	e8 00 00 00 00       	call   1e4b <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x140b>
    1e4b:	8b 74 24 10          	mov    0x10(%rsp),%esi
    1e4f:	48 8b 4c 24 38       	mov    0x38(%rsp),%rcx
    1e54:	49 01 c6             	add    %rax,%r14
    1e57:	48 01 c3             	add    %rax,%rbx
    1e5a:	41 89 36             	mov    %esi,(%r14)
    1e5d:	0f b7 74 24 44       	movzwl 0x44(%rsp),%esi
    1e62:	48 8b 49 10          	mov    0x10(%rcx),%rcx
    1e66:	66 41 89 76 04       	mov    %si,0x4(%r14)
    1e6b:	48 8b 34 24          	mov    (%rsp),%rsi
    1e6f:	49 39 f4             	cmp    %rsi,%r12
    1e72:	74 3d                	je     1eb1 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1471>
    1e74:	48 89 c6             	mov    %rax,%rsi
    1e77:	e9 f3 fd ff ff       	jmp    1c6f <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x122f>
    1e7c:	48 bb f8 ff ff ff ff ff ff 7f 	movabs $0x7ffffffffffffff8,%rbx
    1e86:	eb b7                	jmp    1e3f <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x13ff>
    1e88:	48 b8 ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rax
    1e92:	48 39 c2             	cmp    %rax,%rdx
    1e95:	48 0f 46 c2          	cmovbe %rdx,%rax
    1e99:	49 89 c3             	mov    %rax,%r11
    1e9c:	49 c1 e3 03          	shl    $0x3,%r11
    1ea0:	e9 c3 fe ff ff       	jmp    1d68 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1328>
    1ea5:	48 8d 3d 00 00 00 00 	lea    0x0(%rip),%rdi        # 1eac <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x146c>
    1eac:	e8 00 00 00 00       	call   1eb1 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1471>
    1eb1:	48 8d 50 08          	lea    0x8(%rax),%rdx
    1eb5:	c4 e1 f9 6e f8       	vmovq  %rax,%xmm7
    1eba:	c4 e3 c1 22 c2 01    	vpinsrq $0x1,%rdx,%xmm7,%xmm0
    1ec0:	e9 dd fd ff ff       	jmp    1ca2 <_ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1262>

Disassembly of section .text._ZNSt6vectorIPKN4tomo15CommandMetadataESaIS3_EED2Ev:

Disassembly of section .text._ZN4tomo2Op4Sink6appendEPKcm:

Disassembly of section .text.unlikely:

Disassembly of section .text._ZN4tomo16reply_map_headerIRNS_2Op4SinkEEEvOT_mb:

Disassembly of section .text._ZN4tomo18reply_array_headerIRNS_2Op4SinkEEEvOT_m:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE9_M_mutateEmmPKcm:

Disassembly of section .text.startup:
