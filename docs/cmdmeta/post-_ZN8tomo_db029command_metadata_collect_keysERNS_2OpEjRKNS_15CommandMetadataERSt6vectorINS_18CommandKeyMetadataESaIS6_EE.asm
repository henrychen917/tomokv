
build/cmdmeta/POST/db0/src/cmd/cmdmeta.o:     file format elf64-x86-64


Disassembly of section .text:

0000000000000a40 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE>:
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
     a78:	e8 00 00 00 00       	call   a7d <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x3d>
     a7d:	31 d2                	xor    %edx,%edx
     a7f:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # a86 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x46>
     a86:	89 44 24 1c          	mov    %eax,0x1c(%rsp)
     a8a:	8b 83 cc 00 00 00    	mov    0xcc(%rbx),%eax
     a90:	44 29 f0             	sub    %r14d,%eax
     a93:	89 44 24 20          	mov    %eax,0x20(%rsp)
     a97:	b8 01 00 00 00       	mov    $0x1,%eax
     a9c:	85 c0                	test   %eax,%eax
     a9e:	0f 85 0c 01 00 00    	jne    bb0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x170>
     aa4:	b8 01 00 00 00       	mov    $0x1,%eax
     aa9:	c4 e2 69 f7 c0       	shlx   %edx,%eax,%eax
     aae:	89 44 24 70          	mov    %eax,0x70(%rsp)
     ab2:	45 31 e4             	xor    %r12d,%r12d
     ab5:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
     aba:	48 8d 2d 00 00 00 00 	lea    0x0(%rip),%rbp        # ac1 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x81>
     ac1:	48 8d 1d 00 00 00 00 	lea    0x0(%rip),%rbx        # ac8 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x88>
     ac8:	eb 13                	jmp    add <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x9d>
     aca:	66 0f 1f 44 00 00    	nopw   0x0(%rax,%rax,1)
     ad0:	4a 8b 7c e5 00       	mov    0x0(%rbp,%r12,8),%rdi
     ad5:	48 89 de             	mov    %rbx,%rsi
     ad8:	e8 00 00 00 00       	call   add <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x9d>
     add:	85 c0                	test   %eax,%eax
     adf:	0f 84 fb 05 00 00    	je     10e0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x6a0>
     ae5:	49 ff c4             	inc    %r12
     ae8:	49 83 fc 0a          	cmp    $0xa,%r12
     aec:	75 e2                	jne    ad0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x90>
     aee:	31 d2                	xor    %edx,%edx
     af0:	b8 01 00 00 00       	mov    $0x1,%eax
     af5:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # afc <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xbc>
     afc:	85 c0                	test   %eax,%eax
     afe:	0f 85 dc 00 00 00    	jne    be0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1a0>
     b04:	b8 01 00 00 00       	mov    $0x1,%eax
     b09:	c4 e2 69 f7 c0       	shlx   %edx,%eax,%eax
     b0e:	89 44 24 44          	mov    %eax,0x44(%rsp)
     b12:	45 31 e4             	xor    %r12d,%r12d
     b15:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
     b1a:	48 8d 2d 00 00 00 00 	lea    0x0(%rip),%rbp        # b21 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe1>
     b21:	48 8d 1d 00 00 00 00 	lea    0x0(%rip),%rbx        # b28 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe8>
     b28:	eb 13                	jmp    b3d <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xfd>
     b2a:	66 0f 1f 44 00 00    	nopw   0x0(%rax,%rax,1)
     b30:	4a 8b 7c e5 00       	mov    0x0(%rbp,%r12,8),%rdi
     b35:	48 89 de             	mov    %rbx,%rsi
     b38:	e8 00 00 00 00       	call   b3d <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xfd>
     b3d:	85 c0                	test   %eax,%eax
     b3f:	0f 84 bb 05 00 00    	je     1100 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x6c0>
     b45:	49 ff c4             	inc    %r12
     b48:	49 83 fc 0a          	cmp    $0xa,%r12
     b4c:	75 e2                	jne    b30 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xf0>
     b4e:	44 8b 74 24 1c       	mov    0x1c(%rsp),%r14d
     b53:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
     b58:	48 8d 1d 00 00 00 00 	lea    0x0(%rip),%rbx        # b5f <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x11f>
     b5f:	48 89 da             	mov    %rbx,%rdx
     b62:	44 89 f6             	mov    %r14d,%esi
     b65:	e8 06 f5 ff ff       	call   70 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
     b6a:	84 c0                	test   %al,%al
     b6c:	75 1c                	jne    b8a <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x14a>
     b6e:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
     b73:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # b7a <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x13a>
     b7a:	44 89 f6             	mov    %r14d,%esi
     b7d:	e8 ee f4 ff ff       	call   70 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
     b82:	84 c0                	test   %al,%al
     b84:	0f 84 3d 02 00 00    	je     dc7 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x387>
     b8a:	83 7c 24 20 01       	cmpl   $0x1,0x20(%rsp)
     b8f:	0f 87 9b 00 00 00    	ja     c30 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1f0>
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
     bb7:	74 57                	je     c10 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1d0>
     bb9:	48 8b 0c d6          	mov    (%rsi,%rdx,8),%rcx
     bbd:	0f b6 01             	movzbl (%rcx),%eax
     bc0:	83 e8 52             	sub    $0x52,%eax
     bc3:	75 eb                	jne    bb0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x170>
     bc5:	0f b6 41 01          	movzbl 0x1(%rcx),%eax
     bc9:	83 e8 4f             	sub    $0x4f,%eax
     bcc:	75 e2                	jne    bb0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x170>
     bce:	0f b6 41 02          	movzbl 0x2(%rcx),%eax
     bd2:	e9 c5 fe ff ff       	jmp    a9c <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x5c>
     bd7:	66 0f 1f 84 00 00 00 00 00 	nopw   0x0(%rax,%rax,1)
     be0:	48 ff c2             	inc    %rdx
     be3:	48 83 fa 0a          	cmp    $0xa,%rdx
     be7:	74 37                	je     c20 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1e0>
     be9:	48 8b 0c d6          	mov    (%rsi,%rdx,8),%rcx
     bed:	0f b6 01             	movzbl (%rcx),%eax
     bf0:	83 e8 4f             	sub    $0x4f,%eax
     bf3:	75 eb                	jne    be0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1a0>
     bf5:	0f b6 41 01          	movzbl 0x1(%rcx),%eax
     bf9:	83 e8 57             	sub    $0x57,%eax
     bfc:	75 e2                	jne    be0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1a0>
     bfe:	0f b6 41 02          	movzbl 0x2(%rcx),%eax
     c02:	e9 f5 fe ff ff       	jmp    afc <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xbc>
     c07:	66 0f 1f 84 00 00 00 00 00 	nopw   0x0(%rax,%rax,1)
     c10:	66 c7 44 24 70 00 00 	movw   $0x0,0x70(%rsp)
     c17:	e9 96 fe ff ff       	jmp    ab2 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x72>
     c1c:	0f 1f 40 00          	nopl   0x0(%rax)
     c20:	66 c7 44 24 44 00 00 	movw   $0x0,0x44(%rsp)
     c27:	e9 e6 fe ff ff       	jmp    b12 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd2>
     c2c:	0f 1f 40 00          	nopl   0x0(%rax)
     c30:	8b 44 24 40          	mov    0x40(%rsp),%eax
     c34:	44 8d 70 01          	lea    0x1(%rax),%r14d
     c38:	48 8b 44 24 38       	mov    0x38(%rsp),%rax
     c3d:	48 8b 68 08          	mov    0x8(%rax),%rbp
     c41:	48 8b 70 10          	mov    0x10(%rax),%rsi
     c45:	48 39 f5             	cmp    %rsi,%rbp
     c48:	0f 84 7c 0e 00 00    	je     1aca <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x108a>
     c4e:	0f b7 4c 24 70       	movzwl 0x70(%rsp),%ecx
     c53:	44 89 75 00          	mov    %r14d,0x0(%rbp)
     c57:	66 89 4d 04          	mov    %cx,0x4(%rbp)
     c5b:	48 8d 4d 08          	lea    0x8(%rbp),%rcx
     c5f:	48 89 0c 24          	mov    %rcx,(%rsp)
     c63:	48 89 48 08          	mov    %rcx,0x8(%rax)
     c67:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
     c6b:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
     c70:	48 89 da             	mov    %rbx,%rdx
     c73:	e8 f8 f3 ff ff       	call   70 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
     c78:	84 c0                	test   %al,%al
     c7a:	0f 84 40 01 00 00    	je     dc0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x380>
     c80:	8b 44 24 40          	mov    0x40(%rsp),%eax
     c84:	44 8d 70 02          	lea    0x2(%rax),%r14d
     c88:	44 8d 58 03          	lea    0x3(%rax),%r11d
     c8c:	48 8b 44 24 30       	mov    0x30(%rsp),%rax
     c91:	8b a8 cc 00 00 00    	mov    0xcc(%rax),%ebp
     c97:	41 39 eb             	cmp    %ebp,%r11d
     c9a:	0f 83 20 01 00 00    	jae    dc0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x380>
     ca0:	4c 8b b8 c0 00 00 00 	mov    0xc0(%rax),%r15
     ca7:	48 8d 05 00 00 00 00 	lea    0x0(%rip),%rax        # cae <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x26e>
     cae:	31 f6                	xor    %esi,%esi
     cb0:	4c 8d 2d 00 00 00 00 	lea    0x0(%rip),%r13        # cb7 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x277>
     cb7:	c4 e1 f9 6e c0       	vmovq  %rax,%xmm0
     cbc:	48 8d 05 00 00 00 00 	lea    0x0(%rip),%rax        # cc3 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x283>
     cc3:	41 89 ec             	mov    %ebp,%r12d
     cc6:	89 74 24 10          	mov    %esi,0x10(%rsp)
     cca:	c4 e1 f9 6e d0       	vmovq  %rax,%xmm2
     ccf:	48 8d 05 00 00 00 00 	lea    0x0(%rip),%rax        # cd6 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x296>
     cd6:	c4 e1 f9 6e d8       	vmovq  %rax,%xmm3
     cdb:	4c 89 fb             	mov    %r15,%rbx
     cde:	eb 15                	jmp    cf5 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x2b5>
     ce0:	45 8d 5e 02          	lea    0x2(%r14),%r11d
     ce4:	45 8d 73 01          	lea    0x1(%r11),%r14d
     ce8:	41 83 c3 02          	add    $0x2,%r11d
     cec:	45 39 e3             	cmp    %r12d,%r11d
     cef:	0f 83 95 00 00 00    	jae    d8a <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x34a>
     cf5:	44 89 f0             	mov    %r14d,%eax
     cf8:	48 85 db             	test   %rbx,%rbx
     cfb:	0f 84 1f 09 00 00    	je     1620 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xbe0>
     d01:	48 c1 e0 04          	shl    $0x4,%rax
     d05:	48 01 d8             	add    %rbx,%rax
     d08:	48 8b 28             	mov    (%rax),%rbp
     d0b:	44 8b 78 08          	mov    0x8(%rax),%r15d
     d0f:	b9 05 00 00 00       	mov    $0x5,%ecx
     d14:	4c 89 ea             	mov    %r13,%rdx
     d17:	44 89 fe             	mov    %r15d,%esi
     d1a:	48 89 ef             	mov    %rbp,%rdi
     d1d:	e8 de f2 ff ff       	call   0 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceES1_.isra.0>
     d22:	84 c0                	test   %al,%al
     d24:	75 ba                	jne    ce0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x2a0>
     d26:	b9 02 00 00 00       	mov    $0x2,%ecx
     d2b:	c4 e1 f9 7e c2       	vmovq  %xmm0,%rdx
     d30:	44 89 fe             	mov    %r15d,%esi
     d33:	48 89 ef             	mov    %rbp,%rdi
     d36:	e8 c5 f2 ff ff       	call   0 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceES1_.isra.0>
     d3b:	84 c0                	test   %al,%al
     d3d:	75 a5                	jne    ce4 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x2a4>
     d3f:	b9 03 00 00 00       	mov    $0x3,%ecx
     d44:	c4 e1 f9 7e d2       	vmovq  %xmm2,%rdx
     d49:	44 89 fe             	mov    %r15d,%esi
     d4c:	48 89 ef             	mov    %rbp,%rdi
     d4f:	e8 ac f2 ff ff       	call   0 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceES1_.isra.0>
     d54:	84 c0                	test   %al,%al
     d56:	75 8c                	jne    ce4 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x2a4>
     d58:	b9 05 00 00 00       	mov    $0x5,%ecx
     d5d:	c4 e1 f9 7e da       	vmovq  %xmm3,%rdx
     d62:	44 89 fe             	mov    %r15d,%esi
     d65:	48 89 ef             	mov    %rbp,%rdi
     d68:	e8 93 f2 ff ff       	call   0 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceES1_.isra.0>
     d6d:	84 c0                	test   %al,%al
     d6f:	74 05                	je     d76 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x336>
     d71:	44 89 5c 24 10       	mov    %r11d,0x10(%rsp)
     d76:	45 89 f3             	mov    %r14d,%r11d
     d79:	45 8d 73 01          	lea    0x1(%r11),%r14d
     d7d:	41 83 c3 02          	add    $0x2,%r11d
     d81:	45 39 e3             	cmp    %r12d,%r11d
     d84:	0f 82 6b ff ff ff    	jb     cf5 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x2b5>
     d8a:	8b 74 24 10          	mov    0x10(%rsp),%esi
     d8e:	85 f6                	test   %esi,%esi
     d90:	74 2e                	je     dc0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x380>
     d92:	48 8b 5c 24 38       	mov    0x38(%rsp),%rbx
     d97:	48 8b 04 24          	mov    (%rsp),%rax
     d9b:	48 39 43 10          	cmp    %rax,0x10(%rbx)
     d9f:	0f 84 5f 0e 00 00    	je     1c04 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x11c4>
     da5:	0f b7 4c 24 44       	movzwl 0x44(%rsp),%ecx
     daa:	48 8d 68 08          	lea    0x8(%rax),%rbp
     dae:	89 30                	mov    %esi,(%rax)
     db0:	66 89 48 04          	mov    %cx,0x4(%rax)
     db4:	48 89 6b 08          	mov    %rbp,0x8(%rbx)
     db8:	0f 1f 84 00 00 00 00 00 	nopl   0x0(%rax,%rax,1)
     dc0:	31 c0                	xor    %eax,%eax
     dc2:	e9 d3 fd ff ff       	jmp    b9a <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x15a>
     dc7:	48 8b 04 24          	mov    (%rsp),%rax
     dcb:	80 78 2e 00          	cmpb   $0x0,0x2e(%rax)
     dcf:	0f 84 3f 03 00 00    	je     1114 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x6d4>
     dd5:	8b 5c 24 40          	mov    0x40(%rsp),%ebx
     dd9:	45 31 f6             	xor    %r14d,%r14d
     ddc:	45 31 e4             	xor    %r12d,%r12d
     ddf:	8d 43 02             	lea    0x2(%rbx),%eax
     de2:	89 84 24 a8 00 00 00 	mov    %eax,0xa8(%rsp)
     de9:	48 89 84 24 90 00 00 00 	mov    %rax,0x90(%rsp)
     df1:	48 c1 e0 04          	shl    $0x4,%rax
     df5:	48 89 84 24 88 00 00 00 	mov    %rax,0x88(%rsp)
     dfd:	8d 43 03             	lea    0x3(%rbx),%eax
     e00:	48 8d 1d 00 00 00 00 	lea    0x0(%rip),%rbx        # e07 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x3c7>
     e07:	89 44 24 74          	mov    %eax,0x74(%rsp)
     e0b:	48 89 84 24 80 00 00 00 	mov    %rax,0x80(%rsp)
     e13:	48 c1 e0 04          	shl    $0x4,%rax
     e17:	48 89 44 24 78       	mov    %rax,0x78(%rsp)
     e1c:	0f 1f 40 00          	nopl   0x0(%rax)
     e20:	48 8b 04 24          	mov    (%rsp),%rax
     e24:	48 8d 0d 00 00 00 00 	lea    0x0(%rip),%rcx        # e2b <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x3eb>
     e2b:	45 31 ff             	xor    %r15d,%r15d
     e2e:	0f b7 40 2c          	movzwl 0x2c(%rax),%eax
     e32:	44 01 e0             	add    %r12d,%eax
     e35:	89 c0                	mov    %eax,%eax
     e37:	0f b6 2c 01          	movzbl (%rcx,%rax,1),%ebp
     e3b:	48 8d 0d 00 00 00 00 	lea    0x0(%rip),%rcx        # e42 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x402>
     e42:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
     e47:	44 0f b7 6c c1 08    	movzwl 0x8(%rcx,%rax,8),%r13d
     e4d:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
     e52:	eb 1c                	jmp    e70 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x430>
     e54:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
     e5f:	90                   	nop
     e60:	4a 8b 3c fb          	mov    (%rbx,%r15,8),%rdi
     e64:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # e6b <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x42b>
     e6b:	e8 00 00 00 00       	call   e70 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x430>
     e70:	85 c0                	test   %eax,%eax
     e72:	0f 84 a8 02 00 00    	je     1120 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x6e0>
     e78:	49 ff c7             	inc    %r15
     e7b:	49 83 ff 0a          	cmp    $0xa,%r15
     e7f:	75 df                	jne    e60 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x420>
     e81:	45 31 ff             	xor    %r15d,%r15d
     e84:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
     e89:	4c 8d 35 00 00 00 00 	lea    0x0(%rip),%r14        # e90 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x450>
     e90:	eb 1a                	jmp    eac <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x46c>
     e92:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
     e9d:	0f 1f 00             	nopl   (%rax)
     ea0:	4a 8b 3c fb          	mov    (%rbx,%r15,8),%rdi
     ea4:	4c 89 f6             	mov    %r14,%rsi
     ea7:	e8 00 00 00 00       	call   eac <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x46c>
     eac:	85 c0                	test   %eax,%eax
     eae:	0f 84 3c 03 00 00    	je     11f0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x7b0>
     eb4:	49 ff c7             	inc    %r15
     eb7:	49 83 ff 0a          	cmp    $0xa,%r15
     ebb:	75 e3                	jne    ea0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x460>
     ebd:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
     ec2:	48 8d 0d 00 00 00 00 	lea    0x0(%rip),%rcx        # ec9 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x489>
     ec9:	48 8d 04 c1          	lea    (%rcx,%rax,8),%rax
     ecd:	0f b6 50 0a          	movzbl 0xa(%rax),%edx
     ed1:	84 d2                	test   %dl,%dl
     ed3:	0f 85 67 02 00 00    	jne    1140 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x700>
     ed9:	44 0f bf 70 0c       	movswl 0xc(%rax),%r14d
     ede:	8b 74 24 20          	mov    0x20(%rsp),%esi
     ee2:	44 89 f0             	mov    %r14d,%eax
     ee5:	c1 e8 1f             	shr    $0x1f,%eax
     ee8:	41 39 f6             	cmp    %esi,%r14d
     eeb:	41 0f 93 c0          	setae  %r8b
     eef:	41 08 c0             	or     %al,%r8b
     ef2:	0f 85 b8 01 00 00    	jne    10b0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
     ef8:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
     efd:	48 8d 0d 00 00 00 00 	lea    0x0(%rip),%rcx        # f04 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x4c4>
     f04:	48 8d 04 c1          	lea    (%rcx,%rax,8),%rax
     f08:	0f b6 50 1a          	movzbl 0x1a(%rax),%edx
     f0c:	84 d2                	test   %dl,%dl
     f0e:	0f 85 4c 04 00 00    	jne    1360 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x920>
     f14:	0f bf 48 1c          	movswl 0x1c(%rax),%ecx
     f18:	66 85 c9             	test   %cx,%cx
     f1b:	0f 88 8f 08 00 00    	js     17b0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd70>
     f21:	0f b7 50 20          	movzwl 0x20(%rax),%edx
     f25:	66 85 d2             	test   %dx,%dx
     f28:	0f 8e 3e 09 00 00    	jle    186c <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe2c>
     f2e:	8d 41 01             	lea    0x1(%rcx),%eax
     f31:	0f bf ca             	movswl %dx,%ecx
     f34:	99                   	cltd
     f35:	f7 f9                	idiv   %ecx
     f37:	41 8d 4c 06 ff       	lea    -0x1(%r14,%rax,1),%ecx
     f3c:	39 4c 24 20          	cmp    %ecx,0x20(%rsp)
     f40:	0f 8e 4f fc ff ff    	jle    b95 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x155>
     f46:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
     f4b:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # f52 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x512>
     f52:	0f bf 54 c6 1e       	movswl 0x1e(%rsi,%rax,8),%edx
     f57:	66 85 d2             	test   %dx,%dx
     f5a:	0f 8e 35 fc ff ff    	jle    b95 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x155>
     f60:	41 39 ce             	cmp    %ecx,%r14d
     f63:	0f 8f 47 01 00 00    	jg     10b0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
     f69:	8b 44 24 40          	mov    0x40(%rsp),%eax
     f6d:	44 89 64 24 48       	mov    %r12d,0x48(%rsp)
     f72:	45 89 ec             	mov    %r13d,%r12d
     f75:	4c 8b 6c 24 38       	mov    0x38(%rsp),%r13
     f7a:	45 8d 3c 06          	lea    (%r14,%rax,1),%r15d
     f7e:	eb 20                	jmp    fa0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x560>
     f80:	44 89 7d 00          	mov    %r15d,0x0(%rbp)
     f84:	66 44 89 65 04       	mov    %r12w,0x4(%rbp)
     f89:	41 01 d6             	add    %edx,%r14d
     f8c:	48 83 c5 08          	add    $0x8,%rbp
     f90:	41 01 d7             	add    %edx,%r15d
     f93:	49 89 6d 08          	mov    %rbp,0x8(%r13)
     f97:	41 39 ce             	cmp    %ecx,%r14d
     f9a:	0f 8f 00 01 00 00    	jg     10a0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x660>
     fa0:	49 8b 6d 08          	mov    0x8(%r13),%rbp
     fa4:	49 8b 7d 10          	mov    0x10(%r13),%rdi
     fa8:	48 39 fd             	cmp    %rdi,%rbp
     fab:	75 d3                	jne    f80 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x540>
     fad:	4d 8b 45 00          	mov    0x0(%r13),%r8
     fb1:	49 89 eb             	mov    %rbp,%r11
     fb4:	48 be ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rsi
     fbe:	4d 29 c3             	sub    %r8,%r11
     fc1:	4c 89 d8             	mov    %r11,%rax
     fc4:	48 c1 f8 03          	sar    $0x3,%rax
     fc8:	48 39 f0             	cmp    %rsi,%rax
     fcb:	0f 84 c4 0e 00 00    	je     1e95 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1455>
     fd1:	4c 39 c5             	cmp    %r8,%rbp
     fd4:	0f 84 b6 08 00 00    	je     1890 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe50>
     fda:	48 8d 34 00          	lea    (%rax,%rax,1),%rsi
     fde:	48 39 c6             	cmp    %rax,%rsi
     fe1:	0f 82 a9 0a 00 00    	jb     1a90 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1050>
     fe7:	48 85 f6             	test   %rsi,%rsi
     fea:	0f 85 00 0e 00 00    	jne    1df0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x13b0>
     ff0:	45 31 d2             	xor    %r10d,%r10d
     ff3:	31 f6                	xor    %esi,%esi
     ff5:	45 89 3b             	mov    %r15d,(%r11)
     ff8:	66 45 89 63 04       	mov    %r12w,0x4(%r11)
     ffd:	c5 f9 ef c0          	vpxor  %xmm0,%xmm0,%xmm0
    1001:	4c 89 c0             	mov    %r8,%rax
    1004:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    100f:	90                   	nop
    1010:	4c 8b 08             	mov    (%rax),%r9
    1013:	48 83 c0 08          	add    $0x8,%rax
    1017:	48 83 c6 08          	add    $0x8,%rsi
    101b:	4c 89 4e f8          	mov    %r9,-0x8(%rsi)
    101f:	48 39 c5             	cmp    %rax,%rbp
    1022:	75 ec                	jne    1010 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x5d0>
    1024:	4c 29 c5             	sub    %r8,%rbp
    1027:	c4 e1 f9 7e c0       	vmovq  %xmm0,%rax
    102c:	48 8d 44 28 08       	lea    0x8(%rax,%rbp,1),%rax
    1031:	c4 e3 f9 22 c0 01    	vpinsrq $0x1,%rax,%xmm0,%xmm0
    1037:	4d 85 c0             	test   %r8,%r8
    103a:	74 40                	je     107c <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x63c>
    103c:	48 89 fe             	mov    %rdi,%rsi
    103f:	4c 89 c7             	mov    %r8,%rdi
    1042:	c5 f9 7f 44 24 60    	vmovdqa %xmm0,0x60(%rsp)
    1048:	89 94 24 a0 00 00 00 	mov    %edx,0xa0(%rsp)
    104f:	4c 29 c6             	sub    %r8,%rsi
    1052:	89 8c 24 98 00 00 00 	mov    %ecx,0x98(%rsp)
    1059:	4c 89 54 24 50       	mov    %r10,0x50(%rsp)
    105e:	e8 00 00 00 00       	call   1063 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x623>
    1063:	c5 f9 6f 44 24 60    	vmovdqa 0x60(%rsp),%xmm0
    1069:	8b 94 24 a0 00 00 00 	mov    0xa0(%rsp),%edx
    1070:	8b 8c 24 98 00 00 00 	mov    0x98(%rsp),%ecx
    1077:	4c 8b 54 24 50       	mov    0x50(%rsp),%r10
    107c:	41 01 d6             	add    %edx,%r14d
    107f:	c4 c1 7a 7f 45 00    	vmovdqu %xmm0,0x0(%r13)
    1085:	41 01 d7             	add    %edx,%r15d
    1088:	4d 89 55 10          	mov    %r10,0x10(%r13)
    108c:	41 39 ce             	cmp    %ecx,%r14d
    108f:	0f 8e 0b ff ff ff    	jle    fa0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x560>
    1095:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    10a0:	44 8b 64 24 48       	mov    0x48(%rsp),%r12d
    10a5:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    10b0:	41 be 01 00 00 00    	mov    $0x1,%r14d
    10b6:	48 8b 04 24          	mov    (%rsp),%rax
    10ba:	41 ff c4             	inc    %r12d
    10bd:	0f b6 40 2e          	movzbl 0x2e(%rax),%eax
    10c1:	41 39 c4             	cmp    %eax,%r12d
    10c4:	0f 82 56 fd ff ff    	jb     e20 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x3e0>
    10ca:	41 83 f6 01          	xor    $0x1,%r14d
    10ce:	43 8d 04 36          	lea    (%r14,%r14,1),%eax
    10d2:	e9 c3 fa ff ff       	jmp    b9a <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x15a>
    10d7:	66 0f 1f 84 00 00 00 00 00 	nopw   0x0(%rax,%rax,1)
    10e0:	b8 01 00 00 00       	mov    $0x1,%eax
    10e5:	c4 e2 19 f7 c0       	shlx   %r12d,%eax,%eax
    10ea:	66 09 44 24 70       	or     %ax,0x70(%rsp)
    10ef:	e9 fa f9 ff ff       	jmp    aee <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xae>
    10f4:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    10ff:	90                   	nop
    1100:	b8 01 00 00 00       	mov    $0x1,%eax
    1105:	c4 e2 19 f7 c0       	shlx   %r12d,%eax,%eax
    110a:	66 09 44 24 44       	or     %ax,0x44(%rsp)
    110f:	e9 3a fa ff ff       	jmp    b4e <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x10e>
    1114:	b8 02 00 00 00       	mov    $0x2,%eax
    1119:	e9 7c fa ff ff       	jmp    b9a <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x15a>
    111e:	66 90                	xchg   %ax,%ax
    1120:	b8 01 00 00 00       	mov    $0x1,%eax
    1125:	c4 e2 01 f7 c0       	shlx   %r15d,%eax,%eax
    112a:	66 41 85 c5          	test   %ax,%r13w
    112e:	75 86                	jne    10b6 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x676>
    1130:	e9 4c fd ff ff       	jmp    e81 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x441>
    1135:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    1140:	80 fa 01             	cmp    $0x1,%dl
    1143:	0f 85 67 ff ff ff    	jne    10b0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
    1149:	0f b7 50 18          	movzwl 0x18(%rax),%edx
    114d:	31 c9                	xor    %ecx,%ecx
    114f:	66 85 d2             	test   %dx,%dx
    1152:	0f 48 d1             	cmovs  %ecx,%edx
    1155:	8b 4c 24 20          	mov    0x20(%rsp),%ecx
    1159:	44 0f bf fa          	movswl %dx,%r15d
    115d:	41 39 cf             	cmp    %ecx,%r15d
    1160:	0f 83 4a ff ff ff    	jae    10b0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
    1166:	48 8b 40 10          	mov    0x10(%rax),%rax
    116a:	48 8b 74 24 30       	mov    0x30(%rsp),%rsi
    116f:	66 44 89 6c 24 50    	mov    %r13w,0x50(%rsp)
    1175:	44 89 64 24 48       	mov    %r12d,0x48(%rsp)
    117a:	48 89 6c 24 60       	mov    %rbp,0x60(%rsp)
    117f:	45 89 fc             	mov    %r15d,%r12d
    1182:	44 8b 6c 24 40       	mov    0x40(%rsp),%r13d
    1187:	41 89 cf             	mov    %ecx,%r15d
    118a:	4c 8b b6 c0 00 00 00 	mov    0xc0(%rsi),%r14
    1191:	48 89 c5             	mov    %rax,%rbp
    1194:	eb 33                	jmp    11c9 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x789>
    1196:	66 2e 0f 1f 84 00 00 00 00 00 	cs nopw 0x0(%rax,%rax,1)
    11a0:	48 c1 e0 04          	shl    $0x4,%rax
    11a4:	4c 01 f0             	add    %r14,%rax
    11a7:	8b 70 08             	mov    0x8(%rax),%esi
    11aa:	48 8b 38             	mov    (%rax),%rdi
    11ad:	48 89 ea             	mov    %rbp,%rdx
    11b0:	41 ff c4             	inc    %r12d
    11b3:	e8 b8 ee ff ff       	call   70 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    11b8:	84 c0                	test   %al,%al
    11ba:	0f 85 c0 05 00 00    	jne    1780 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd40>
    11c0:	45 39 fc             	cmp    %r15d,%r12d
    11c3:	0f 83 d7 fe ff ff    	jae    10a0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x660>
    11c9:	43 8d 44 25 00       	lea    0x0(%r13,%r12,1),%eax
    11ce:	4d 85 f6             	test   %r14,%r14
    11d1:	75 cd                	jne    11a0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x760>
    11d3:	48 8b 4c 24 30       	mov    0x30(%rsp),%rcx
    11d8:	48 83 c0 0d          	add    $0xd,%rax
    11dc:	48 c1 e0 04          	shl    $0x4,%rax
    11e0:	48 01 c8             	add    %rcx,%rax
    11e3:	eb c2                	jmp    11a7 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x767>
    11e5:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    11f0:	44 89 ea             	mov    %r13d,%edx
    11f3:	b8 01 00 00 00       	mov    $0x1,%eax
    11f8:	c4 e2 01 f7 c0       	shlx   %r15d,%eax,%eax
    11fd:	21 c2                	and    %eax,%edx
    11ff:	c4 42 78 f2 ed       	andn   %r13d,%eax,%r13d
    1204:	66 85 d2             	test   %dx,%dx
    1207:	0f 84 b0 fc ff ff    	je     ebd <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x47d>
    120d:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    1211:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1216:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 121d <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x7dd>
    121d:	e8 4e ee ff ff       	call   70 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    1222:	41 89 c6             	mov    %eax,%r14d
    1225:	84 c0                	test   %al,%al
    1227:	0f 85 13 04 00 00    	jne    1640 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xc00>
    122d:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    1231:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1236:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 123d <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x7fd>
    123d:	e8 2e ee ff ff       	call   70 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    1242:	84 c0                	test   %al,%al
    1244:	0f 84 73 fc ff ff    	je     ebd <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x47d>
    124a:	4c 8b 7c 24 30       	mov    0x30(%rsp),%r15
    124f:	41 8b 87 cc 00 00 00 	mov    0xcc(%r15),%eax
    1256:	39 84 24 a8 00 00 00 	cmp    %eax,0xa8(%rsp)
    125d:	0f 83 f2 00 00 00    	jae    1355 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x915>
    1263:	8b 4c 24 40          	mov    0x40(%rsp),%ecx
    1267:	4c 8b ac 24 88 00 00 00 	mov    0x88(%rsp),%r13
    126f:	c4 e1 f9 6e e5       	vmovq  %rbp,%xmm4
    1274:	44 89 64 24 48       	mov    %r12d,0x48(%rsp)
    1279:	29 c8                	sub    %ecx,%eax
    127b:	48 8b 8c 24 90 00 00 00 	mov    0x90(%rsp),%rcx
    1283:	83 e8 03             	sub    $0x3,%eax
    1286:	4c 8d 5c 01 01       	lea    0x1(%rcx,%rax,1),%r11
    128b:	49 8d 87 d0 00 00 00 	lea    0xd0(%r15),%rax
    1292:	c4 e1 f9 6e c8       	vmovq  %rax,%xmm1
    1297:	48 8d 05 00 00 00 00 	lea    0x0(%rip),%rax        # 129e <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x85e>
    129e:	c4 e1 f9 6e c0       	vmovq  %rax,%xmm0
    12a3:	48 8d 05 00 00 00 00 	lea    0x0(%rip),%rax        # 12aa <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x86a>
    12aa:	49 c1 e3 04          	shl    $0x4,%r11
    12ae:	c4 e1 f9 6e d0       	vmovq  %rax,%xmm2
    12b3:	eb 2a                	jmp    12df <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x89f>
    12b5:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    12c0:	49 8d 45 10          	lea    0x10(%r13),%rax
    12c4:	4c 39 d8             	cmp    %r11,%rax
    12c7:	0f 84 07 05 00 00    	je     17d4 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd94>
    12cd:	49 83 c5 20          	add    $0x20,%r13
    12d1:	4d 39 dd             	cmp    %r11,%r13
    12d4:	74 6c                	je     1342 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x902>
    12d6:	49 83 c5 10          	add    $0x10,%r13
    12da:	4d 39 dd             	cmp    %r11,%r13
    12dd:	74 63                	je     1342 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x902>
    12df:	45 84 f6             	test   %r14b,%r14b
    12e2:	75 f2                	jne    12d6 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x896>
    12e4:	49 8b 97 c0 00 00 00 	mov    0xc0(%r15),%rdx
    12eb:	c4 e1 f9 7e c8       	vmovq  %xmm1,%rax
    12f0:	4c 01 e8             	add    %r13,%rax
    12f3:	4a 8d 0c 2a          	lea    (%rdx,%r13,1),%rcx
    12f7:	48 85 d2             	test   %rdx,%rdx
    12fa:	c4 e1 f9 7e c2       	vmovq  %xmm0,%rdx
    12ff:	48 0f 45 c1          	cmovne %rcx,%rax
    1303:	b9 03 00 00 00       	mov    $0x3,%ecx
    1308:	48 8b 28             	mov    (%rax),%rbp
    130b:	44 8b 60 08          	mov    0x8(%rax),%r12d
    130f:	48 89 ef             	mov    %rbp,%rdi
    1312:	44 89 e6             	mov    %r12d,%esi
    1315:	e8 e6 ec ff ff       	call   0 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceES1_.isra.0>
    131a:	41 89 c6             	mov    %eax,%r14d
    131d:	84 c0                	test   %al,%al
    131f:	75 9f                	jne    12c0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x880>
    1321:	b9 06 00 00 00       	mov    $0x6,%ecx
    1326:	c4 e1 f9 7e d2       	vmovq  %xmm2,%rdx
    132b:	44 89 e6             	mov    %r12d,%esi
    132e:	48 89 ef             	mov    %rbp,%rdi
    1331:	e8 ca ec ff ff       	call   0 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceES1_.isra.0>
    1336:	49 83 c5 10          	add    $0x10,%r13
    133a:	41 89 c6             	mov    %eax,%r14d
    133d:	4d 39 dd             	cmp    %r11,%r13
    1340:	75 9d                	jne    12df <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x89f>
    1342:	44 8b 64 24 48       	mov    0x48(%rsp),%r12d
    1347:	c4 e1 f9 7e e5       	vmovq  %xmm4,%rbp
    134c:	45 84 f6             	test   %r14b,%r14b
    134f:	0f 85 89 04 00 00    	jne    17de <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd9e>
    1355:	44 0f b7 6c 24 70    	movzwl 0x70(%rsp),%r13d
    135b:	e9 5d fb ff ff       	jmp    ebd <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x47d>
    1360:	80 fa 01             	cmp    $0x1,%dl
    1363:	0f 85 47 fd ff ff    	jne    10b0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
    1369:	0f bf 50 22          	movswl 0x22(%rax),%edx
    136d:	0f bf 40 24          	movswl 0x24(%rax),%eax
    1371:	44 01 f2             	add    %r14d,%edx
    1374:	41 01 c6             	add    %eax,%r14d
    1377:	89 d0                	mov    %edx,%eax
    1379:	44 09 f0             	or     %r14d,%eax
    137c:	0f 88 13 f8 ff ff    	js     b95 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x155>
    1382:	8b 44 24 20          	mov    0x20(%rsp),%eax
    1386:	39 c2                	cmp    %eax,%edx
    1388:	0f 83 07 f8 ff ff    	jae    b95 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x155>
    138e:	48 8b 44 24 30       	mov    0x30(%rsp),%rax
    1393:	48 8b 88 c0 00 00 00 	mov    0xc0(%rax),%rcx
    139a:	8b 44 24 40          	mov    0x40(%rsp),%eax
    139e:	01 d0                	add    %edx,%eax
    13a0:	89 c0                	mov    %eax,%eax
    13a2:	48 85 c9             	test   %rcx,%rcx
    13a5:	0f 84 df 07 00 00    	je     1b8a <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x114a>
    13ab:	48 c1 e0 04          	shl    $0x4,%rax
    13af:	48 01 c8             	add    %rcx,%rax
    13b2:	44 8b 50 08          	mov    0x8(%rax),%r10d
    13b6:	48 8b 30             	mov    (%rax),%rsi
    13b9:	45 85 d2             	test   %r10d,%r10d
    13bc:	0f 84 6a 05 00 00    	je     192c <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xeec>
    13c2:	0f b6 06             	movzbl (%rsi),%eax
    13c5:	3c 2b                	cmp    $0x2b,%al
    13c7:	0f 84 50 05 00 00    	je     191d <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xedd>
    13cd:	41 83 fa 01          	cmp    $0x1,%r10d
    13d1:	41 0f 94 c0          	sete   %r8b
    13d5:	3c 30                	cmp    $0x30,%al
    13d7:	0f 95 c0             	setne  %al
    13da:	31 ff                	xor    %edi,%edi
    13dc:	41 09 c0             	or     %eax,%r8d
    13df:	89 f8                	mov    %edi,%eax
    13e1:	45 31 ff             	xor    %r15d,%r15d
    13e4:	49 b9 cd cc cc cc cc cc cc cc 	movabs $0xcccccccccccccccd,%r9
    13ee:	48 01 c6             	add    %rax,%rsi
    13f1:	29 f7                	sub    %esi,%edi
    13f3:	eb 40                	jmp    1435 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x9f5>
    13f5:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    1400:	0f be c8             	movsbl %al,%ecx
    1403:	83 e9 30             	sub    $0x30,%ecx
    1406:	48 63 c9             	movslq %ecx,%rcx
    1409:	48 89 ca             	mov    %rcx,%rdx
    140c:	48 f7 d2             	not    %rdx
    140f:	48 89 d0             	mov    %rdx,%rax
    1412:	49 f7 e1             	mul    %r9
    1415:	48 c1 ea 03          	shr    $0x3,%rdx
    1419:	4c 39 fa             	cmp    %r15,%rdx
    141c:	72 22                	jb     1440 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa00>
    141e:	4b 8d 04 bf          	lea    (%r15,%r15,4),%rax
    1422:	48 ff c6             	inc    %rsi
    1425:	4c 8d 3c 41          	lea    (%rcx,%rax,2),%r15
    1429:	8d 04 37             	lea    (%rdi,%rsi,1),%eax
    142c:	44 39 d0             	cmp    %r10d,%eax
    142f:	0f 83 c2 08 00 00    	jae    1cf7 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x12b7>
    1435:	0f b6 06             	movzbl (%rsi),%eax
    1438:	8d 50 d0             	lea    -0x30(%rax),%edx
    143b:	80 fa 09             	cmp    $0x9,%dl
    143e:	76 c0                	jbe    1400 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x9c0>
    1440:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    1444:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1449:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 1450 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa10>
    1450:	44 88 44 24 48       	mov    %r8b,0x48(%rsp)
    1455:	e8 16 ec ff ff       	call   70 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    145a:	89 c1                	mov    %eax,%ecx
    145c:	84 c0                	test   %al,%al
    145e:	0f 85 4c fc ff ff    	jne    10b0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
    1464:	44 0f b6 44 24 48    	movzbl 0x48(%rsp),%r8d
    146a:	45 31 ff             	xor    %r15d,%r15d
    146d:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    1471:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1476:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 147d <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa3d>
    147d:	88 4c 24 50          	mov    %cl,0x50(%rsp)
    1481:	44 88 44 24 48       	mov    %r8b,0x48(%rsp)
    1486:	e8 e5 eb ff ff       	call   70 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    148b:	44 0f b6 44 24 48    	movzbl 0x48(%rsp),%r8d
    1491:	0f b6 4c 24 50       	movzbl 0x50(%rsp),%ecx
    1496:	84 c0                	test   %al,%al
    1498:	0f 84 d0 04 00 00    	je     196e <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xf2e>
    149e:	84 c9                	test   %cl,%cl
    14a0:	0f 84 0a fc ff ff    	je     10b0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
    14a6:	8b 4c 24 20          	mov    0x20(%rsp),%ecx
    14aa:	4c 39 f9             	cmp    %r15,%rcx
    14ad:	0f 82 fd fb ff ff    	jb     10b0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
    14b3:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    14b8:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 14bf <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa7f>
    14bf:	48 0f bf 54 c6 1e    	movswq 0x1e(%rsi,%rax,8),%rdx
    14c5:	49 63 f6             	movslq %r14d,%rsi
    14c8:	48 89 d0             	mov    %rdx,%rax
    14cb:	49 0f af d7          	imul   %r15,%rdx
    14cf:	48 01 f2             	add    %rsi,%rdx
    14d2:	48 39 d1             	cmp    %rdx,%rcx
    14d5:	0f 82 d5 fb ff ff    	jb     10b0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
    14db:	4d 85 ff             	test   %r15,%r15
    14de:	0f 95 c2             	setne  %dl
    14e1:	31 c9                	xor    %ecx,%ecx
    14e3:	45 84 c0             	test   %r8b,%r8b
    14e6:	44 0f 44 e9          	cmove  %ecx,%r13d
    14ea:	84 d2                	test   %dl,%dl
    14ec:	0f 84 be fb ff ff    	je     10b0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
    14f2:	8b 4c 24 40          	mov    0x40(%rsp),%ecx
    14f6:	45 31 c0             	xor    %r8d,%r8d
    14f9:	4d 89 fa             	mov    %r15,%r10
    14fc:	44 89 64 24 48       	mov    %r12d,0x48(%rsp)
    1501:	44 0f bf c8          	movswl %ax,%r9d
    1505:	4c 8b 64 24 38       	mov    0x38(%rsp),%r12
    150a:	4d 89 c7             	mov    %r8,%r15
    150d:	41 01 ce             	add    %ecx,%r14d
    1510:	eb 21                	jmp    1533 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xaf3>
    1512:	44 89 75 00          	mov    %r14d,0x0(%rbp)
    1516:	66 44 89 6d 04       	mov    %r13w,0x4(%rbp)
    151b:	48 83 c5 08          	add    $0x8,%rbp
    151f:	49 89 6c 24 08       	mov    %rbp,0x8(%r12)
    1524:	49 ff c7             	inc    %r15
    1527:	45 01 ce             	add    %r9d,%r14d
    152a:	4d 39 d7             	cmp    %r10,%r15
    152d:	0f 83 6d fb ff ff    	jae    10a0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x660>
    1533:	49 8b 6c 24 08       	mov    0x8(%r12),%rbp
    1538:	49 8b 7c 24 10       	mov    0x10(%r12),%rdi
    153d:	48 39 fd             	cmp    %rdi,%rbp
    1540:	75 d0                	jne    1512 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xad2>
    1542:	49 8b 0c 24          	mov    (%r12),%rcx
    1546:	48 89 ee             	mov    %rbp,%rsi
    1549:	48 ba ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rdx
    1553:	48 29 ce             	sub    %rcx,%rsi
    1556:	48 89 f0             	mov    %rsi,%rax
    1559:	48 c1 f8 03          	sar    $0x3,%rax
    155d:	48 39 d0             	cmp    %rdx,%rax
    1560:	0f 84 2f 09 00 00    	je     1e95 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1455>
    1566:	48 39 cd             	cmp    %rcx,%rbp
    1569:	0f 84 d0 07 00 00    	je     1d3f <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x12ff>
    156f:	48 8d 14 00          	lea    (%rax,%rax,1),%rdx
    1573:	48 39 c2             	cmp    %rax,%rdx
    1576:	0f 82 53 08 00 00    	jb     1dcf <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x138f>
    157c:	48 85 d2             	test   %rdx,%rdx
    157f:	0f 85 f3 08 00 00    	jne    1e78 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1438>
    1585:	45 31 db             	xor    %r11d,%r11d
    1588:	45 31 c0             	xor    %r8d,%r8d
    158b:	31 d2                	xor    %edx,%edx
    158d:	44 89 36             	mov    %r14d,(%rsi)
    1590:	66 44 89 6e 04       	mov    %r13w,0x4(%rsi)
    1595:	48 89 c8             	mov    %rcx,%rax
    1598:	48 8b 30             	mov    (%rax),%rsi
    159b:	48 83 c0 08          	add    $0x8,%rax
    159f:	48 83 c2 08          	add    $0x8,%rdx
    15a3:	48 89 72 f8          	mov    %rsi,-0x8(%rdx)
    15a7:	48 39 c5             	cmp    %rax,%rbp
    15aa:	75 ec                	jne    1598 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xb58>
    15ac:	48 29 cd             	sub    %rcx,%rbp
    15af:	49 8d 44 28 08       	lea    0x8(%r8,%rbp,1),%rax
    15b4:	c4 c1 f9 6e f0       	vmovq  %r8,%xmm6
    15b9:	c4 e3 c9 22 c0 01    	vpinsrq $0x1,%rax,%xmm6,%xmm0
    15bf:	48 85 c9             	test   %rcx,%rcx
    15c2:	74 44                	je     1608 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xbc8>
    15c4:	48 89 fe             	mov    %rdi,%rsi
    15c7:	48 89 cf             	mov    %rcx,%rdi
    15ca:	c5 f9 7f 44 24 50    	vmovdqa %xmm0,0x50(%rsp)
    15d0:	44 89 8c 24 a0 00 00 00 	mov    %r9d,0xa0(%rsp)
    15d8:	48 29 ce             	sub    %rcx,%rsi
    15db:	4c 89 94 24 98 00 00 00 	mov    %r10,0x98(%rsp)
    15e3:	4c 89 5c 24 60       	mov    %r11,0x60(%rsp)
    15e8:	e8 00 00 00 00       	call   15ed <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xbad>
    15ed:	c5 f9 6f 44 24 50    	vmovdqa 0x50(%rsp),%xmm0
    15f3:	44 8b 8c 24 a0 00 00 00 	mov    0xa0(%rsp),%r9d
    15fb:	4c 8b 94 24 98 00 00 00 	mov    0x98(%rsp),%r10
    1603:	4c 8b 5c 24 60       	mov    0x60(%rsp),%r11
    1608:	c4 c1 7a 7f 04 24    	vmovdqu %xmm0,(%r12)
    160e:	4d 89 5c 24 10       	mov    %r11,0x10(%r12)
    1613:	e9 0c ff ff ff       	jmp    1524 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xae4>
    1618:	0f 1f 84 00 00 00 00 00 	nopl   0x0(%rax,%rax,1)
    1620:	48 8b 4c 24 30       	mov    0x30(%rsp),%rcx
    1625:	48 83 c0 0d          	add    $0xd,%rax
    1629:	48 c1 e0 04          	shl    $0x4,%rax
    162d:	48 01 c8             	add    %rcx,%rax
    1630:	e9 d3 f6 ff ff       	jmp    d08 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x2c8>
    1635:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    1640:	48 8b 4c 24 30       	mov    0x30(%rsp),%rcx
    1645:	8b 81 cc 00 00 00    	mov    0xcc(%rcx),%eax
    164b:	39 44 24 74          	cmp    %eax,0x74(%rsp)
    164f:	0f 83 97 06 00 00    	jae    1cec <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x12ac>
    1655:	8b 74 24 40          	mov    0x40(%rsp),%esi
    1659:	4c 8b 6c 24 78       	mov    0x78(%rsp),%r13
    165e:	44 89 64 24 48       	mov    %r12d,0x48(%rsp)
    1663:	4c 8d b9 d0 00 00 00 	lea    0xd0(%rcx),%r15
    166a:	4c 8d 35 00 00 00 00 	lea    0x0(%rip),%r14        # 1671 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xc31>
    1671:	49 89 cc             	mov    %rcx,%r12
    1674:	29 f0                	sub    %esi,%eax
    1676:	48 8b b4 24 80 00 00 00 	mov    0x80(%rsp),%rsi
    167e:	83 e8 04             	sub    $0x4,%eax
    1681:	4c 8d 5c 06 01       	lea    0x1(%rsi,%rax,1),%r11
    1686:	31 c0                	xor    %eax,%eax
    1688:	49 c1 e3 04          	shl    $0x4,%r11
    168c:	0f 1f 40 00          	nopl   0x0(%rax)
    1690:	84 c0                	test   %al,%al
    1692:	75 2a                	jne    16be <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xc7e>
    1694:	49 8b 94 24 c0 00 00 00 	mov    0xc0(%r12),%rdx
    169c:	4b 8d 04 2f          	lea    (%r15,%r13,1),%rax
    16a0:	4a 8d 0c 2a          	lea    (%rdx,%r13,1),%rcx
    16a4:	48 85 d2             	test   %rdx,%rdx
    16a7:	4c 89 f2             	mov    %r14,%rdx
    16aa:	48 0f 45 c1          	cmovne %rcx,%rax
    16ae:	b9 03 00 00 00       	mov    $0x3,%ecx
    16b3:	8b 70 08             	mov    0x8(%rax),%esi
    16b6:	48 8b 38             	mov    (%rax),%rdi
    16b9:	e8 42 e9 ff ff       	call   0 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceES1_.isra.0>
    16be:	49 83 c5 10          	add    $0x10,%r13
    16c2:	4d 39 dd             	cmp    %r11,%r13
    16c5:	75 c9                	jne    1690 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xc50>
    16c7:	44 8b 64 24 48       	mov    0x48(%rsp),%r12d
    16cc:	44 0f b7 6c 24 44    	movzwl 0x44(%rsp),%r13d
    16d2:	84 c0                	test   %al,%al
    16d4:	0f 84 e3 f7 ff ff    	je     ebd <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x47d>
    16da:	45 31 ff             	xor    %r15d,%r15d
    16dd:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
    16e2:	4c 8d 35 00 00 00 00 	lea    0x0(%rip),%r14        # 16e9 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xca9>
    16e9:	4c 8d 2d 00 00 00 00 	lea    0x0(%rip),%r13        # 16f0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xcb0>
    16f0:	eb 1a                	jmp    170c <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xccc>
    16f2:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    16fd:	0f 1f 00             	nopl   (%rax)
    1700:	4b 8b 3c fe          	mov    (%r14,%r15,8),%rdi
    1704:	4c 89 ee             	mov    %r13,%rsi
    1707:	e8 00 00 00 00       	call   170c <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xccc>
    170c:	85 c0                	test   %eax,%eax
    170e:	0f 84 a7 03 00 00    	je     1abb <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x107b>
    1714:	49 ff c7             	inc    %r15
    1717:	49 83 ff 0a          	cmp    $0xa,%r15
    171b:	75 e3                	jne    1700 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xcc0>
    171d:	31 d2                	xor    %edx,%edx
    171f:	45 31 ed             	xor    %r13d,%r13d
    1722:	48 89 6c 24 48       	mov    %rbp,0x48(%rsp)
    1727:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
    172c:	4c 8d 3d 00 00 00 00 	lea    0x0(%rip),%r15        # 1733 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xcf3>
    1733:	4c 89 ed             	mov    %r13,%rbp
    1736:	4c 8d 35 00 00 00 00 	lea    0x0(%rip),%r14        # 173d <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xcfd>
    173d:	41 89 d5             	mov    %edx,%r13d
    1740:	eb 1a                	jmp    175c <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd1c>
    1742:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    174d:	0f 1f 00             	nopl   (%rax)
    1750:	49 8b 3c ef          	mov    (%r15,%rbp,8),%rdi
    1754:	4c 89 f6             	mov    %r14,%rsi
    1757:	e8 00 00 00 00       	call   175c <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd1c>
    175c:	85 c0                	test   %eax,%eax
    175e:	0f 84 3b 03 00 00    	je     1a9f <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x105f>
    1764:	48 ff c5             	inc    %rbp
    1767:	48 83 fd 0a          	cmp    $0xa,%rbp
    176b:	75 e3                	jne    1750 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd10>
    176d:	48 8b 6c 24 48       	mov    0x48(%rsp),%rbp
    1772:	44 89 ea             	mov    %r13d,%edx
    1775:	83 ca 01             	or     $0x1,%edx
    1778:	41 89 d5             	mov    %edx,%r13d
    177b:	e9 3d f7 ff ff       	jmp    ebd <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x47d>
    1780:	45 89 e7             	mov    %r12d,%r15d
    1783:	44 0f b7 6c 24 50    	movzwl 0x50(%rsp),%r13d
    1789:	44 8b 64 24 48       	mov    0x48(%rsp),%r12d
    178e:	48 8b 6c 24 60       	mov    0x60(%rsp),%rbp
    1793:	45 89 fe             	mov    %r15d,%r14d
    1796:	45 85 ff             	test   %r15d,%r15d
    1799:	0f 89 3f f7 ff ff    	jns    ede <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x49e>
    179f:	e9 0c f9 ff ff       	jmp    10b0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
    17a4:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    17af:	90                   	nop
    17b0:	8b 74 24 20          	mov    0x20(%rsp),%esi
    17b4:	01 f1                	add    %esi,%ecx
    17b6:	41 39 ce             	cmp    %ecx,%r14d
    17b9:	0f 8f f1 f8 ff ff    	jg     10b0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
    17bf:	0f b7 50 20          	movzwl 0x20(%rax),%edx
    17c3:	66 85 d2             	test   %dx,%dx
    17c6:	0f 8e ab 00 00 00    	jle    1877 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe37>
    17cc:	44 29 f1             	sub    %r14d,%ecx
    17cf:	e9 5a f7 ff ff       	jmp    f2e <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x4ee>
    17d4:	44 8b 64 24 48       	mov    0x48(%rsp),%r12d
    17d9:	c4 e1 f9 7e e5       	vmovq  %xmm4,%rbp
    17de:	45 31 ff             	xor    %r15d,%r15d
    17e1:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
    17e6:	4c 8d 35 00 00 00 00 	lea    0x0(%rip),%r14        # 17ed <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xdad>
    17ed:	4c 8d 2d 00 00 00 00 	lea    0x0(%rip),%r13        # 17f4 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xdb4>
    17f4:	eb 16                	jmp    180c <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xdcc>
    17f6:	66 2e 0f 1f 84 00 00 00 00 00 	cs nopw 0x0(%rax,%rax,1)
    1800:	4b 8b 3c fe          	mov    (%r14,%r15,8),%rdi
    1804:	4c 89 ee             	mov    %r13,%rsi
    1807:	e8 00 00 00 00       	call   180c <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xdcc>
    180c:	85 c0                	test   %eax,%eax
    180e:	0f 84 b1 04 00 00    	je     1cc5 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1285>
    1814:	49 ff c7             	inc    %r15
    1817:	49 83 ff 0a          	cmp    $0xa,%r15
    181b:	75 e3                	jne    1800 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xdc0>
    181d:	66 c7 44 24 48 00 00 	movw   $0x0,0x48(%rsp)
    1824:	45 31 ff             	xor    %r15d,%r15d
    1827:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
    182c:	4c 8d 35 00 00 00 00 	lea    0x0(%rip),%r14        # 1833 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xdf3>
    1833:	4c 8d 2d 00 00 00 00 	lea    0x0(%rip),%r13        # 183a <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xdfa>
    183a:	eb 10                	jmp    184c <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe0c>
    183c:	0f 1f 40 00          	nopl   0x0(%rax)
    1840:	4b 8b 3c fe          	mov    (%r14,%r15,8),%rdi
    1844:	4c 89 ee             	mov    %r13,%rsi
    1847:	e8 00 00 00 00       	call   184c <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe0c>
    184c:	85 c0                	test   %eax,%eax
    184e:	0f 84 84 04 00 00    	je     1cd8 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1298>
    1854:	49 ff c7             	inc    %r15
    1857:	49 83 ff 0a          	cmp    $0xa,%r15
    185b:	75 e3                	jne    1840 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe00>
    185d:	44 0f b7 6c 24 48    	movzwl 0x48(%rsp),%r13d
    1863:	41 83 cd 01          	or     $0x1,%r13d
    1867:	e9 51 f6 ff ff       	jmp    ebd <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x47d>
    186c:	44 01 f1             	add    %r14d,%ecx
    186f:	39 ce                	cmp    %ecx,%esi
    1871:	0f 8e 1e f3 ff ff    	jle    b95 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x155>
    1877:	0f bf 50 1e          	movswl 0x1e(%rax),%edx
    187b:	66 85 d2             	test   %dx,%dx
    187e:	0f 8f e5 f6 ff ff    	jg     f69 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x529>
    1884:	e9 0c f3 ff ff       	jmp    b95 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x155>
    1889:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
    1890:	48 83 c0 01          	add    $0x1,%rax
    1894:	0f 82 f6 01 00 00    	jb     1a90 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1050>
    189a:	48 39 f0             	cmp    %rsi,%rax
    189d:	48 0f 47 c6          	cmova  %rsi,%rax
    18a1:	4c 8d 14 c5 00 00 00 00 	lea    0x0(,%rax,8),%r10
    18a9:	4c 89 d7             	mov    %r10,%rdi
    18ac:	89 94 24 ac 00 00 00 	mov    %edx,0xac(%rsp)
    18b3:	89 8c 24 a0 00 00 00 	mov    %ecx,0xa0(%rsp)
    18ba:	4c 89 9c 24 98 00 00 00 	mov    %r11,0x98(%rsp)
    18c2:	4c 89 44 24 60       	mov    %r8,0x60(%rsp)
    18c7:	4c 89 54 24 50       	mov    %r10,0x50(%rsp)
    18cc:	e8 00 00 00 00       	call   18d1 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe91>
    18d1:	4c 8b 54 24 50       	mov    0x50(%rsp),%r10
    18d6:	4c 8b 9c 24 98 00 00 00 	mov    0x98(%rsp),%r11
    18de:	4c 8b 44 24 60       	mov    0x60(%rsp),%r8
    18e3:	48 89 c6             	mov    %rax,%rsi
    18e6:	c4 e1 f9 6e c0       	vmovq  %rax,%xmm0
    18eb:	49 8b 7d 10          	mov    0x10(%r13),%rdi
    18ef:	8b 8c 24 a0 00 00 00 	mov    0xa0(%rsp),%ecx
    18f6:	8b 94 24 ac 00 00 00 	mov    0xac(%rsp),%edx
    18fd:	49 01 c2             	add    %rax,%r10
    1900:	49 01 c3             	add    %rax,%r11
    1903:	48 83 c0 08          	add    $0x8,%rax
    1907:	4c 39 c5             	cmp    %r8,%rbp
    190a:	45 89 3b             	mov    %r15d,(%r11)
    190d:	66 45 89 63 04       	mov    %r12w,0x4(%r11)
    1912:	0f 85 e9 f6 ff ff    	jne    1001 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x5c1>
    1918:	e9 14 f7 ff ff       	jmp    1031 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x5f1>
    191d:	bf 01 00 00 00       	mov    $0x1,%edi
    1922:	41 83 fa 01          	cmp    $0x1,%r10d
    1926:	0f 85 b3 fa ff ff    	jne    13df <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x99f>
    192c:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    1930:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1935:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 193c <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xefc>
    193c:	e8 2f e7 ff ff       	call   70 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    1941:	84 c0                	test   %al,%al
    1943:	0f 85 67 f7 ff ff    	jne    10b0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
    1949:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    194d:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1952:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 1959 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xf19>
    1959:	e8 12 e7 ff ff       	call   70 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    195e:	89 c1                	mov    %eax,%ecx
    1960:	84 c0                	test   %al,%al
    1962:	0f 85 48 f7 ff ff    	jne    10b0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
    1968:	45 31 c0             	xor    %r8d,%r8d
    196b:	45 31 ff             	xor    %r15d,%r15d
    196e:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    1972:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1977:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 197e <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xf3e>
    197e:	88 4c 24 50          	mov    %cl,0x50(%rsp)
    1982:	44 88 44 24 48       	mov    %r8b,0x48(%rsp)
    1987:	e8 e4 e6 ff ff       	call   70 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    198c:	44 0f b6 44 24 48    	movzbl 0x48(%rsp),%r8d
    1992:	0f b6 4c 24 50       	movzbl 0x50(%rsp),%ecx
    1997:	84 c0                	test   %al,%al
    1999:	0f 85 ff fa ff ff    	jne    149e <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa5e>
    199f:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    19a3:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    19a8:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 19af <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xf6f>
    19af:	88 4c 24 50          	mov    %cl,0x50(%rsp)
    19b3:	44 88 44 24 48       	mov    %r8b,0x48(%rsp)
    19b8:	e8 b3 e6 ff ff       	call   70 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    19bd:	44 0f b6 44 24 48    	movzbl 0x48(%rsp),%r8d
    19c3:	0f b6 4c 24 50       	movzbl 0x50(%rsp),%ecx
    19c8:	84 c0                	test   %al,%al
    19ca:	0f 85 ce fa ff ff    	jne    149e <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa5e>
    19d0:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    19d4:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    19d9:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 19e0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xfa0>
    19e0:	88 4c 24 50          	mov    %cl,0x50(%rsp)
    19e4:	44 88 44 24 48       	mov    %r8b,0x48(%rsp)
    19e9:	e8 82 e6 ff ff       	call   70 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    19ee:	44 0f b6 44 24 48    	movzbl 0x48(%rsp),%r8d
    19f4:	0f b6 4c 24 50       	movzbl 0x50(%rsp),%ecx
    19f9:	84 c0                	test   %al,%al
    19fb:	0f 85 9d fa ff ff    	jne    149e <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa5e>
    1a01:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    1a05:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1a0a:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 1a11 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xfd1>
    1a11:	88 4c 24 50          	mov    %cl,0x50(%rsp)
    1a15:	44 88 44 24 48       	mov    %r8b,0x48(%rsp)
    1a1a:	e8 51 e6 ff ff       	call   70 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    1a1f:	0f b6 4c 24 50       	movzbl 0x50(%rsp),%ecx
    1a24:	89 c6                	mov    %eax,%esi
    1a26:	84 c9                	test   %cl,%cl
    1a28:	0f 84 b0 03 00 00    	je     1dde <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x139e>
    1a2e:	8b 4c 24 20          	mov    0x20(%rsp),%ecx
    1a32:	4c 39 f9             	cmp    %r15,%rcx
    1a35:	0f 82 a3 03 00 00    	jb     1dde <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x139e>
    1a3b:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    1a40:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 1a47 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1007>
    1a47:	49 63 fe             	movslq %r14d,%rdi
    1a4a:	44 0f b6 44 24 48    	movzbl 0x48(%rsp),%r8d
    1a50:	48 0f bf 54 c2 1e    	movswq 0x1e(%rdx,%rax,8),%rdx
    1a56:	48 89 d0             	mov    %rdx,%rax
    1a59:	49 0f af d7          	imul   %r15,%rdx
    1a5d:	48 01 fa             	add    %rdi,%rdx
    1a60:	48 39 d1             	cmp    %rdx,%rcx
    1a63:	0f 82 75 03 00 00    	jb     1dde <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x139e>
    1a69:	4d 85 ff             	test   %r15,%r15
    1a6c:	0f 95 c2             	setne  %dl
    1a6f:	40 84 f6             	test   %sil,%sil
    1a72:	0f 85 69 fa ff ff    	jne    14e1 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xaa1>
    1a78:	84 d2                	test   %dl,%dl
    1a7a:	0f 85 61 fa ff ff    	jne    14e1 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xaa1>
    1a80:	e9 10 f1 ff ff       	jmp    b95 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x155>
    1a85:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    1a90:	49 ba f8 ff ff ff ff ff ff 7f 	movabs $0x7ffffffffffffff8,%r10
    1a9a:	e9 0a fe ff ff       	jmp    18a9 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe69>
    1a9f:	44 89 ea             	mov    %r13d,%edx
    1aa2:	b8 01 00 00 00       	mov    $0x1,%eax
    1aa7:	49 89 ed             	mov    %rbp,%r13
    1aaa:	48 8b 6c 24 48       	mov    0x48(%rsp),%rbp
    1aaf:	c4 e2 11 f7 c0       	shlx   %r13d,%eax,%eax
    1ab4:	09 c2                	or     %eax,%edx
    1ab6:	e9 ba fc ff ff       	jmp    1775 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xd35>
    1abb:	ba 01 00 00 00       	mov    $0x1,%edx
    1ac0:	c4 e2 01 f7 d2       	shlx   %r15d,%edx,%edx
    1ac5:	e9 55 fc ff ff       	jmp    171f <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xcdf>
    1aca:	48 8b 44 24 38       	mov    0x38(%rsp),%rax
    1acf:	49 89 ef             	mov    %rbp,%r15
    1ad2:	4c 8b 20             	mov    (%rax),%r12
    1ad5:	48 b8 ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rax
    1adf:	4d 29 e7             	sub    %r12,%r15
    1ae2:	4c 89 fa             	mov    %r15,%rdx
    1ae5:	48 c1 fa 03          	sar    $0x3,%rdx
    1ae9:	48 39 c2             	cmp    %rax,%rdx
    1aec:	0f 84 a3 03 00 00    	je     1e95 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1455>
    1af2:	4c 39 e5             	cmp    %r12,%rbp
    1af5:	0f 84 a4 00 00 00    	je     1b9f <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x115f>
    1afb:	48 8d 04 12          	lea    (%rdx,%rdx,1),%rax
    1aff:	48 39 d0             	cmp    %rdx,%rax
    1b02:	0f 82 28 02 00 00    	jb     1d30 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x12f0>
    1b08:	48 85 c0             	test   %rax,%rax
    1b0b:	0f 85 9b 00 00 00    	jne    1bac <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x116c>
    1b11:	0f b7 44 24 70       	movzwl 0x70(%rsp),%eax
    1b16:	45 31 ed             	xor    %r13d,%r13d
    1b19:	31 ff                	xor    %edi,%edi
    1b1b:	31 d2                	xor    %edx,%edx
    1b1d:	45 89 37             	mov    %r14d,(%r15)
    1b20:	66 41 89 47 04       	mov    %ax,0x4(%r15)
    1b25:	4c 89 e0             	mov    %r12,%rax
    1b28:	0f 1f 84 00 00 00 00 00 	nopl   0x0(%rax,%rax,1)
    1b30:	48 8b 08             	mov    (%rax),%rcx
    1b33:	48 83 c0 08          	add    $0x8,%rax
    1b37:	48 83 c2 08          	add    $0x8,%rdx
    1b3b:	48 89 4a f8          	mov    %rcx,-0x8(%rdx)
    1b3f:	48 39 c5             	cmp    %rax,%rbp
    1b42:	75 ec                	jne    1b30 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x10f0>
    1b44:	4c 29 e5             	sub    %r12,%rbp
    1b47:	48 8d 44 2f 08       	lea    0x8(%rdi,%rbp,1),%rax
    1b4c:	48 89 04 24          	mov    %rax,(%rsp)
    1b50:	c4 e1 f9 6e e7       	vmovq  %rdi,%xmm4
    1b55:	c4 e3 d9 22 04 24 01 	vpinsrq $0x1,(%rsp),%xmm4,%xmm0
    1b5c:	4d 85 e4             	test   %r12,%r12
    1b5f:	74 17                	je     1b78 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1138>
    1b61:	4c 29 e6             	sub    %r12,%rsi
    1b64:	4c 89 e7             	mov    %r12,%rdi
    1b67:	c5 f9 7f 44 24 20    	vmovdqa %xmm0,0x20(%rsp)
    1b6d:	e8 00 00 00 00       	call   1b72 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1132>
    1b72:	c5 f9 6f 44 24 20    	vmovdqa 0x20(%rsp),%xmm0
    1b78:	48 8b 44 24 38       	mov    0x38(%rsp),%rax
    1b7d:	c5 fa 7f 00          	vmovdqu %xmm0,(%rax)
    1b81:	4c 89 68 10          	mov    %r13,0x10(%rax)
    1b85:	e9 dd f0 ff ff       	jmp    c67 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x227>
    1b8a:	48 8b 4c 24 30       	mov    0x30(%rsp),%rcx
    1b8f:	48 83 c0 0d          	add    $0xd,%rax
    1b93:	48 c1 e0 04          	shl    $0x4,%rax
    1b97:	48 01 c8             	add    %rcx,%rax
    1b9a:	e9 13 f8 ff ff       	jmp    13b2 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x972>
    1b9f:	48 89 d0             	mov    %rdx,%rax
    1ba2:	48 83 c0 01          	add    $0x1,%rax
    1ba6:	0f 82 84 01 00 00    	jb     1d30 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x12f0>
    1bac:	48 ba ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rdx
    1bb6:	48 39 d0             	cmp    %rdx,%rax
    1bb9:	48 0f 46 d0          	cmovbe %rax,%rdx
    1bbd:	49 89 d5             	mov    %rdx,%r13
    1bc0:	49 c1 e5 03          	shl    $0x3,%r13
    1bc4:	4c 89 ef             	mov    %r13,%rdi
    1bc7:	e8 00 00 00 00       	call   1bcc <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x118c>
    1bcc:	48 89 c2             	mov    %rax,%rdx
    1bcf:	48 8b 44 24 38       	mov    0x38(%rsp),%rax
    1bd4:	49 01 d7             	add    %rdx,%r15
    1bd7:	49 01 d5             	add    %rdx,%r13
    1bda:	48 89 d7             	mov    %rdx,%rdi
    1bdd:	45 89 37             	mov    %r14d,(%r15)
    1be0:	48 8b 70 10          	mov    0x10(%rax),%rsi
    1be4:	0f b7 44 24 70       	movzwl 0x70(%rsp),%eax
    1be9:	66 41 89 47 04       	mov    %ax,0x4(%r15)
    1bee:	4c 39 e5             	cmp    %r12,%rbp
    1bf1:	0f 85 2e ff ff ff    	jne    1b25 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x10e5>
    1bf7:	48 8d 42 08          	lea    0x8(%rdx),%rax
    1bfb:	48 89 04 24          	mov    %rax,(%rsp)
    1bff:	e9 4c ff ff ff       	jmp    1b50 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1110>
    1c04:	48 8b 44 24 38       	mov    0x38(%rsp),%rax
    1c09:	48 8b 1c 24          	mov    (%rsp),%rbx
    1c0d:	4c 8b 20             	mov    (%rax),%r12
    1c10:	49 89 de             	mov    %rbx,%r14
    1c13:	48 b8 ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rax
    1c1d:	4d 29 e6             	sub    %r12,%r14
    1c20:	4c 89 f2             	mov    %r14,%rdx
    1c23:	48 c1 fa 03          	sar    $0x3,%rdx
    1c27:	48 39 c2             	cmp    %rax,%rdx
    1c2a:	0f 84 65 02 00 00    	je     1e95 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1455>
    1c30:	49 39 dc             	cmp    %rbx,%r12
    1c33:	0f 84 d4 01 00 00    	je     1e0d <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x13cd>
    1c39:	48 8d 04 12          	lea    (%rdx,%rdx,1),%rax
    1c3d:	48 39 d0             	cmp    %rdx,%rax
    1c40:	0f 82 26 02 00 00    	jb     1e6c <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x142c>
    1c46:	48 85 c0             	test   %rax,%rax
    1c49:	0f 85 c7 01 00 00    	jne    1e16 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x13d6>
    1c4f:	0f b7 44 24 44       	movzwl 0x44(%rsp),%eax
    1c54:	48 8b 0c 24          	mov    (%rsp),%rcx
    1c58:	41 89 36             	mov    %esi,(%r14)
    1c5b:	31 db                	xor    %ebx,%ebx
    1c5d:	31 f6                	xor    %esi,%esi
    1c5f:	66 41 89 46 04       	mov    %ax,0x4(%r14)
    1c64:	31 c0                	xor    %eax,%eax
    1c66:	4c 89 e2             	mov    %r12,%rdx
    1c69:	48 8b 3a             	mov    (%rdx),%rdi
    1c6c:	48 83 c2 08          	add    $0x8,%rdx
    1c70:	48 83 c0 08          	add    $0x8,%rax
    1c74:	48 89 78 f8          	mov    %rdi,-0x8(%rax)
    1c78:	48 8b 3c 24          	mov    (%rsp),%rdi
    1c7c:	48 39 fa             	cmp    %rdi,%rdx
    1c7f:	75 e8                	jne    1c69 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1229>
    1c81:	4c 29 e2             	sub    %r12,%rdx
    1c84:	c4 e1 f9 6e ee       	vmovq  %rsi,%xmm5
    1c89:	48 8d 44 16 08       	lea    0x8(%rsi,%rdx,1),%rax
    1c8e:	c4 e3 d1 22 c0 01    	vpinsrq $0x1,%rax,%xmm5,%xmm0
    1c94:	4d 85 e4             	test   %r12,%r12
    1c97:	74 18                	je     1cb1 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1271>
    1c99:	4c 29 e1             	sub    %r12,%rcx
    1c9c:	4c 89 e7             	mov    %r12,%rdi
    1c9f:	c5 f9 7f 04 24       	vmovdqa %xmm0,(%rsp)
    1ca4:	48 89 ce             	mov    %rcx,%rsi
    1ca7:	e8 00 00 00 00       	call   1cac <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x126c>
    1cac:	c5 f9 6f 04 24       	vmovdqa (%rsp),%xmm0
    1cb1:	48 8b 44 24 38       	mov    0x38(%rsp),%rax
    1cb6:	c5 fa 7f 00          	vmovdqu %xmm0,(%rax)
    1cba:	48 89 58 10          	mov    %rbx,0x10(%rax)
    1cbe:	31 c0                	xor    %eax,%eax
    1cc0:	e9 d5 ee ff ff       	jmp    b9a <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x15a>
    1cc5:	b8 01 00 00 00       	mov    $0x1,%eax
    1cca:	c4 e2 01 f7 c0       	shlx   %r15d,%eax,%eax
    1ccf:	89 44 24 48          	mov    %eax,0x48(%rsp)
    1cd3:	e9 4c fb ff ff       	jmp    1824 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xde4>
    1cd8:	b8 01 00 00 00       	mov    $0x1,%eax
    1cdd:	c4 e2 01 f7 c0       	shlx   %r15d,%eax,%eax
    1ce2:	66 09 44 24 48       	or     %ax,0x48(%rsp)
    1ce7:	e9 71 fb ff ff       	jmp    185d <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe1d>
    1cec:	44 0f b7 6c 24 44    	movzwl 0x44(%rsp),%r13d
    1cf2:	e9 c6 f1 ff ff       	jmp    ebd <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x47d>
    1cf7:	8b 74 24 1c          	mov    0x1c(%rsp),%esi
    1cfb:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    1d00:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 1d07 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x12c7>
    1d07:	44 88 44 24 48       	mov    %r8b,0x48(%rsp)
    1d0c:	e8 5f e3 ff ff       	call   70 <_ZN8tomo_db012_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
    1d11:	44 0f b6 44 24 48    	movzbl 0x48(%rsp),%r8d
    1d17:	84 c0                	test   %al,%al
    1d19:	0f 85 87 f7 ff ff    	jne    14a6 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa66>
    1d1f:	b9 01 00 00 00       	mov    $0x1,%ecx
    1d24:	e9 44 f7 ff ff       	jmp    146d <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xa2d>
    1d29:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
    1d30:	49 bd f8 ff ff ff ff ff ff 7f 	movabs $0x7ffffffffffffff8,%r13
    1d3a:	e9 85 fe ff ff       	jmp    1bc4 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1184>
    1d3f:	48 83 c0 01          	add    $0x1,%rax
    1d43:	0f 82 86 00 00 00    	jb     1dcf <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x138f>
    1d49:	48 39 d0             	cmp    %rdx,%rax
    1d4c:	48 0f 47 c2          	cmova  %rdx,%rax
    1d50:	4c 8d 1c c5 00 00 00 00 	lea    0x0(,%rax,8),%r11
    1d58:	4c 89 df             	mov    %r11,%rdi
    1d5b:	44 89 8c 24 ac 00 00 00 	mov    %r9d,0xac(%rsp)
    1d63:	4c 89 94 24 a0 00 00 00 	mov    %r10,0xa0(%rsp)
    1d6b:	48 89 b4 24 98 00 00 00 	mov    %rsi,0x98(%rsp)
    1d73:	48 89 4c 24 60       	mov    %rcx,0x60(%rsp)
    1d78:	4c 89 5c 24 50       	mov    %r11,0x50(%rsp)
    1d7d:	e8 00 00 00 00       	call   1d82 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1342>
    1d82:	4c 8b 5c 24 50       	mov    0x50(%rsp),%r11
    1d87:	48 8b b4 24 98 00 00 00 	mov    0x98(%rsp),%rsi
    1d8f:	48 8b 4c 24 60       	mov    0x60(%rsp),%rcx
    1d94:	48 89 c2             	mov    %rax,%rdx
    1d97:	49 89 c0             	mov    %rax,%r8
    1d9a:	49 8b 7c 24 10       	mov    0x10(%r12),%rdi
    1d9f:	4c 8b 94 24 a0 00 00 00 	mov    0xa0(%rsp),%r10
    1da7:	44 8b 8c 24 ac 00 00 00 	mov    0xac(%rsp),%r9d
    1daf:	49 01 c3             	add    %rax,%r11
    1db2:	48 01 c6             	add    %rax,%rsi
    1db5:	48 39 cd             	cmp    %rcx,%rbp
    1db8:	48 8d 40 08          	lea    0x8(%rax),%rax
    1dbc:	44 89 36             	mov    %r14d,(%rsi)
    1dbf:	66 44 89 6e 04       	mov    %r13w,0x4(%rsi)
    1dc4:	0f 85 cb f7 ff ff    	jne    1595 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xb55>
    1dca:	e9 e5 f7 ff ff       	jmp    15b4 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xb74>
    1dcf:	49 bb f8 ff ff ff ff ff ff 7f 	movabs $0x7ffffffffffffff8,%r11
    1dd9:	e9 7a ff ff ff       	jmp    1d58 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1318>
    1dde:	40 84 f6             	test   %sil,%sil
    1de1:	0f 84 ae ed ff ff    	je     b95 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x155>
    1de7:	e9 c4 f2 ff ff       	jmp    10b0 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x670>
    1dec:	0f 1f 40 00          	nopl   0x0(%rax)
    1df0:	48 b8 ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rax
    1dfa:	48 39 c6             	cmp    %rax,%rsi
    1dfd:	48 0f 46 c6          	cmovbe %rsi,%rax
    1e01:	49 89 c2             	mov    %rax,%r10
    1e04:	49 c1 e2 03          	shl    $0x3,%r10
    1e08:	e9 9c fa ff ff       	jmp    18a9 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0xe69>
    1e0d:	48 89 d0             	mov    %rdx,%rax
    1e10:	48 83 c0 01          	add    $0x1,%rax
    1e14:	72 56                	jb     1e6c <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x142c>
    1e16:	48 ba ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rdx
    1e20:	48 39 d0             	cmp    %rdx,%rax
    1e23:	48 0f 47 c2          	cmova  %rdx,%rax
    1e27:	48 8d 1c c5 00 00 00 00 	lea    0x0(,%rax,8),%rbx
    1e2f:	48 89 df             	mov    %rbx,%rdi
    1e32:	89 74 24 10          	mov    %esi,0x10(%rsp)
    1e36:	e8 00 00 00 00       	call   1e3b <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x13fb>
    1e3b:	8b 74 24 10          	mov    0x10(%rsp),%esi
    1e3f:	48 8b 4c 24 38       	mov    0x38(%rsp),%rcx
    1e44:	49 01 c6             	add    %rax,%r14
    1e47:	48 01 c3             	add    %rax,%rbx
    1e4a:	41 89 36             	mov    %esi,(%r14)
    1e4d:	0f b7 74 24 44       	movzwl 0x44(%rsp),%esi
    1e52:	48 8b 49 10          	mov    0x10(%rcx),%rcx
    1e56:	66 41 89 76 04       	mov    %si,0x4(%r14)
    1e5b:	48 8b 34 24          	mov    (%rsp),%rsi
    1e5f:	49 39 f4             	cmp    %rsi,%r12
    1e62:	74 3d                	je     1ea1 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1461>
    1e64:	48 89 c6             	mov    %rax,%rsi
    1e67:	e9 fa fd ff ff       	jmp    1c66 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1226>
    1e6c:	48 bb f8 ff ff ff ff ff ff 7f 	movabs $0x7ffffffffffffff8,%rbx
    1e76:	eb b7                	jmp    1e2f <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x13ef>
    1e78:	48 b8 ff ff ff ff ff ff ff 0f 	movabs $0xfffffffffffffff,%rax
    1e82:	48 39 c2             	cmp    %rax,%rdx
    1e85:	48 0f 46 c2          	cmovbe %rdx,%rax
    1e89:	49 89 c3             	mov    %rax,%r11
    1e8c:	49 c1 e3 03          	shl    $0x3,%r11
    1e90:	e9 c3 fe ff ff       	jmp    1d58 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1318>
    1e95:	48 8d 3d 00 00 00 00 	lea    0x0(%rip),%rdi        # 1e9c <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x145c>
    1e9c:	e8 00 00 00 00       	call   1ea1 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1461>
    1ea1:	48 8d 50 08          	lea    0x8(%rax),%rdx
    1ea5:	c4 e1 f9 6e f8       	vmovq  %rax,%xmm7
    1eaa:	c4 e3 c1 22 c2 01    	vpinsrq $0x1,%rdx,%xmm7,%xmm0
    1eb0:	e9 e4 fd ff ff       	jmp    1c99 <_ZN8tomo_db029command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE+0x1259>

Disassembly of section .text._ZNSt6vectorIPKN8tomo_db015CommandMetadataESaIS3_EED2Ev:

Disassembly of section .text._ZN8tomo_db02Op4Sink6appendEPKcm:

Disassembly of section .text.unlikely:

Disassembly of section .text._ZN8tomo_db016reply_map_headerIRNS_2Op4SinkEEEvOT_mb:

Disassembly of section .text._ZN8tomo_db018reply_array_headerIRNS_2Op4SinkEEEvOT_m:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE9_M_mutateEmmPKcm:

Disassembly of section .text.startup:
