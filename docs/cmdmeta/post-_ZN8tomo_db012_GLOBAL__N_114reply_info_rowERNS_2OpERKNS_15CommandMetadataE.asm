
build/cmdmeta/POST/db0/src/cmd/cmdmeta.o:     file format elf64-x86-64


Disassembly of section .text:

0000000000002a10 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE>:
    2a10:	41 57                	push   %r15
    2a12:	41 56                	push   %r14
    2a14:	41 55                	push   %r13
    2a16:	49 89 f7             	mov    %rsi,%r15
    2a19:	41 54                	push   %r12
    2a1b:	55                   	push   %rbp
    2a1c:	53                   	push   %rbx
    2a1d:	be 0a 00 00 00       	mov    $0xa,%esi
    2a22:	48 81 ec 98 00 00 00 	sub    $0x98,%rsp
    2a29:	4c 8d 74 24 40       	lea    0x40(%rsp),%r14
    2a2e:	48 89 7c 24 10       	mov    %rdi,0x10(%rsp)
    2a33:	64 48 8b 04 25 28 00 00 00 	mov    %fs:0x28,%rax
    2a3c:	48 89 84 24 88 00 00 00 	mov    %rax,0x88(%rsp)
    2a44:	31 c0                	xor    %eax,%eax
    2a46:	48 89 7c 24 40       	mov    %rdi,0x40(%rsp)
    2a4b:	c6 44 24 48 00       	movb   $0x0,0x48(%rsp)
    2a50:	4c 89 f7             	mov    %r14,%rdi
    2a53:	e8 00 00 00 00       	call   2a58 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x48>
    2a58:	49 8b 1f             	mov    (%r15),%rbx
    2a5b:	48 89 df             	mov    %rbx,%rdi
    2a5e:	e8 00 00 00 00       	call   2a63 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x53>
    2a63:	48 89 de             	mov    %rbx,%rsi
    2a66:	4c 89 f7             	mov    %r14,%rdi
    2a69:	89 c2                	mov    %eax,%edx
    2a6b:	e8 20 d7 ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    2a70:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    2a75:	41 0f bf 57 08       	movswl 0x8(%r15),%edx
    2a7a:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    2a7e:	74 30                	je     2ab0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xa0>
    2a80:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    2a84:	75 2a                	jne    2ab0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xa0>
    2a86:	44 8b a0 a4 00 00 00 	mov    0xa4(%rax),%r12d
    2a8d:	45 85 e4             	test   %r12d,%r12d
    2a90:	75 1e                	jne    2ab0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xa0>
    2a92:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    2a97:	75 17                	jne    2ab0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xa0>
    2a99:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    2a9d:	89 90 bc 00 00 00    	mov    %edx,0xbc(%rax)
    2aa3:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    2aae:	eb 0c                	jmp    2abc <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xac>
    2ab0:	48 0f bf f2          	movswq %dx,%rsi
    2ab4:	4c 89 f7             	mov    %r14,%rdi
    2ab7:	e8 b4 d8 ff ff       	call   370 <_ZN8tomo_db09reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    2abc:	48 8b 44 24 10       	mov    0x10(%rsp),%rax
    2ac1:	49 8b 77 10          	mov    0x10(%r15),%rsi
    2ac5:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 2acc <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xbc>
    2acc:	b9 13 00 00 00       	mov    $0x13,%ecx
    2ad1:	4c 89 f7             	mov    %r14,%rdi
    2ad4:	0f b6 40 1c          	movzbl 0x1c(%rax),%eax
    2ad8:	41 89 c0             	mov    %eax,%r8d
    2adb:	88 44 24 08          	mov    %al,0x8(%rsp)
    2adf:	41 c0 e8 02          	shr    $0x2,%r8b
    2ae3:	41 83 e0 01          	and    $0x1,%r8d
    2ae7:	e8 04 f4 ff ff       	call   1ef0 <_ZN8tomo_db012_GLOBAL__N_116reply_string_setERNS_2Op4SinkEmPKPKcjb>
    2aec:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    2af1:	41 0f bf 57 18       	movswl 0x18(%r15),%edx
    2af6:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    2afa:	0f 84 70 01 00 00    	je     2c70 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x260>
    2b00:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    2b04:	0f 85 66 01 00 00    	jne    2c70 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x260>
    2b0a:	8b a8 a4 00 00 00    	mov    0xa4(%rax),%ebp
    2b10:	85 ed                	test   %ebp,%ebp
    2b12:	0f 85 58 01 00 00    	jne    2c70 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x260>
    2b18:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    2b1d:	0f 85 4d 01 00 00    	jne    2c70 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x260>
    2b23:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    2b27:	49 0f bf 77 1a       	movswq 0x1a(%r15),%rsi
    2b2c:	89 90 bc 00 00 00    	mov    %edx,0xbc(%rax)
    2b32:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    2b3d:	4c 89 f7             	mov    %r14,%rdi
    2b40:	e8 2b d8 ff ff       	call   370 <_ZN8tomo_db09reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    2b45:	48 8b 6c 24 40       	mov    0x40(%rsp),%rbp
    2b4a:	49 0f bf 77 1c       	movswq 0x1c(%r15),%rsi
    2b4f:	80 7d 1e 00          	cmpb   $0x0,0x1e(%rbp)
    2b53:	0f 85 df 01 00 00    	jne    2d38 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x328>
    2b59:	4c 89 f7             	mov    %r14,%rdi
    2b5c:	e8 0f d8 ff ff       	call   370 <_ZN8tomo_db09reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    2b61:	48 8b 44 24 10       	mov    0x10(%rsp),%rax
    2b66:	f3 49 0f b8 5f 20    	popcnt 0x20(%r15),%rbx
    2b6c:	f6 40 1c 04          	testb  $0x4,0x1c(%rax)
    2b70:	0f 84 11 02 00 00    	je     2d87 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x377>
    2b76:	48 8b 6c 24 40       	mov    0x40(%rsp),%rbp
    2b7b:	4c 8b 95 98 00 00 00 	mov    0x98(%rbp),%r10
    2b82:	4c 8b 45 28          	mov    0x28(%rbp),%r8
    2b86:	4d 85 d2             	test   %r10,%r10
    2b89:	74 1e                	je     2ba9 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x199>
    2b8b:	4d 85 c0             	test   %r8,%r8
    2b8e:	75 19                	jne    2ba9 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x199>
    2b90:	8b 85 a4 00 00 00    	mov    0xa4(%rbp),%eax
    2b96:	8b 8d a0 00 00 00    	mov    0xa0(%rbp),%ecx
    2b9c:	48 8d 50 18          	lea    0x18(%rax),%rdx
    2ba0:	48 39 d1             	cmp    %rdx,%rcx
    2ba3:	0f 83 09 10 00 00    	jae    3bb2 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x11a2>
    2ba9:	4c 8b 65 30          	mov    0x30(%rbp),%r12
    2bad:	49 8d 40 18          	lea    0x18(%r8),%rax
    2bb1:	c6 44 24 48 00       	movb   $0x0,0x48(%rsp)
    2bb6:	49 39 c4             	cmp    %rax,%r12
    2bb9:	0f 82 21 01 00 00    	jb     2ce0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x2d0>
    2bbf:	4c 8b 6d 20          	mov    0x20(%rbp),%r13
    2bc3:	4f 8d 54 05 00       	lea    0x0(%r13,%r8,1),%r10
    2bc8:	45 31 c0             	xor    %r8d,%r8d
    2bcb:	4d 8d 4a 01          	lea    0x1(%r10),%r9
    2bcf:	48 8d 74 24 70       	lea    0x70(%rsp),%rsi
    2bd4:	31 c9                	xor    %ecx,%ecx
    2bd6:	49 bc cd cc cc cc cc cc cc cc 	movabs $0xcccccccccccccccd,%r12
    2be0:	41 c6 02 7e          	movb   $0x7e,(%r10)
    2be4:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    2bef:	90                   	nop
    2bf0:	48 89 d8             	mov    %rbx,%rax
    2bf3:	89 cf                	mov    %ecx,%edi
    2bf5:	48 ff c6             	inc    %rsi
    2bf8:	ff c1                	inc    %ecx
    2bfa:	49 f7 e4             	mul    %r12
    2bfd:	48 89 d8             	mov    %rbx,%rax
    2c00:	48 c1 ea 03          	shr    $0x3,%rdx
    2c04:	4c 8d 1c 92          	lea    (%rdx,%rdx,4),%r11
    2c08:	4d 01 db             	add    %r11,%r11
    2c0b:	4c 29 d8             	sub    %r11,%rax
    2c0e:	83 c0 30             	add    $0x30,%eax
    2c11:	88 46 ff             	mov    %al,-0x1(%rsi)
    2c14:	48 89 d8             	mov    %rbx,%rax
    2c17:	48 89 d3             	mov    %rdx,%rbx
    2c1a:	48 83 f8 09          	cmp    $0x9,%rax
    2c1e:	77 d0                	ja     2bf0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1e0>
    2c20:	4d 8d 1c 09          	lea    (%r9,%rcx,1),%r11
    2c24:	4c 89 c8             	mov    %r9,%rax
    2c27:	42 8d 34 0f          	lea    (%rdi,%r9,1),%esi
    2c2b:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    2c30:	89 f2                	mov    %esi,%edx
    2c32:	29 c2                	sub    %eax,%edx
    2c34:	48 ff c0             	inc    %rax
    2c37:	0f b6 54 14 70       	movzbl 0x70(%rsp,%rdx,1),%edx
    2c3c:	88 50 ff             	mov    %dl,-0x1(%rax)
    2c3f:	49 39 c3             	cmp    %rax,%r11
    2c42:	75 ec                	jne    2c30 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x220>
    2c44:	49 01 c9             	add    %rcx,%r9
    2c47:	66 41 c7 01 0d 0a    	movw   $0xa0d,(%r9)
    2c4d:	49 83 c1 02          	add    $0x2,%r9
    2c51:	4d 29 d1             	sub    %r10,%r9
    2c54:	45 84 c0             	test   %r8b,%r8b
    2c57:	0f 84 1a 0f 00 00    	je     3b77 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1167>
    2c5d:	44 01 8d a4 00 00 00 	add    %r9d,0xa4(%rbp)
    2c64:	e9 29 01 00 00       	jmp    2d92 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x382>
    2c69:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
    2c70:	48 0f bf f2          	movswq %dx,%rsi
    2c74:	4c 89 f7             	mov    %r14,%rdi
    2c77:	e8 f4 d6 ff ff       	call   370 <_ZN8tomo_db09reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    2c7c:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    2c81:	49 0f bf 77 1a       	movswq 0x1a(%r15),%rsi
    2c86:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    2c8a:	0f 84 ad fe ff ff    	je     2b3d <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x12d>
    2c90:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    2c94:	0f 85 a3 fe ff ff    	jne    2b3d <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x12d>
    2c9a:	8b 98 a4 00 00 00    	mov    0xa4(%rax),%ebx
    2ca0:	85 db                	test   %ebx,%ebx
    2ca2:	0f 85 95 fe ff ff    	jne    2b3d <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x12d>
    2ca8:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    2cad:	0f 85 8a fe ff ff    	jne    2b3d <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x12d>
    2cb3:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    2cb7:	89 b0 bc 00 00 00    	mov    %esi,0xbc(%rax)
    2cbd:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    2cc8:	49 0f bf 77 1c       	movswq 0x1c(%r15),%rsi
    2ccd:	e9 87 fe ff ff       	jmp    2b59 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x149>
    2cd2:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    2cdd:	0f 1f 00             	nopl   (%rax)
    2ce0:	4d 01 e4             	add    %r12,%r12
    2ce3:	49 39 c4             	cmp    %rax,%r12
    2ce6:	72 f8                	jb     2ce0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x2d0>
    2ce8:	4c 89 e7             	mov    %r12,%rdi
    2ceb:	4c 89 44 24 08       	mov    %r8,0x8(%rsp)
    2cf0:	e8 00 00 00 00       	call   2cf5 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x2e5>
    2cf5:	48 8b 75 20          	mov    0x20(%rbp),%rsi
    2cf9:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
    2cfe:	4c 89 e1             	mov    %r12,%rcx
    2d01:	48 89 c7             	mov    %rax,%rdi
    2d04:	49 89 c5             	mov    %rax,%r13
    2d07:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
    2d0c:	e8 00 00 00 00       	call   2d11 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x301>
    2d11:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
    2d16:	48 8d 45 38          	lea    0x38(%rbp),%rax
    2d1a:	48 39 c6             	cmp    %rax,%rsi
    2d1d:	74 08                	je     2d27 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x317>
    2d1f:	48 89 f7             	mov    %rsi,%rdi
    2d22:	e8 00 00 00 00       	call   2d27 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x317>
    2d27:	4c 8b 45 28          	mov    0x28(%rbp),%r8
    2d2b:	4c 89 6d 20          	mov    %r13,0x20(%rbp)
    2d2f:	4c 89 65 30          	mov    %r12,0x30(%rbp)
    2d33:	e9 8b fe ff ff       	jmp    2bc3 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1b3>
    2d38:	80 7d 1d 00          	cmpb   $0x0,0x1d(%rbp)
    2d3c:	0f 85 17 fe ff ff    	jne    2b59 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x149>
    2d42:	44 8b 9d a4 00 00 00 	mov    0xa4(%rbp),%r11d
    2d49:	45 85 db             	test   %r11d,%r11d
    2d4c:	0f 85 07 fe ff ff    	jne    2b59 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x149>
    2d52:	48 83 7d 28 00       	cmpq   $0x0,0x28(%rbp)
    2d57:	0f 85 fc fd ff ff    	jne    2b59 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x149>
    2d5d:	48 8b 44 24 10       	mov    0x10(%rsp),%rax
    2d62:	c6 45 1d 09          	movb   $0x9,0x1d(%rbp)
    2d66:	89 b5 bc 00 00 00    	mov    %esi,0xbc(%rbp)
    2d6c:	48 c7 85 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rbp)
    2d77:	f3 49 0f b8 5f 20    	popcnt 0x20(%r15),%rbx
    2d7d:	f6 40 1c 04          	testb  $0x4,0x1c(%rax)
    2d81:	0f 85 86 0e 00 00    	jne    3c0d <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x11fd>
    2d87:	48 89 de             	mov    %rbx,%rsi
    2d8a:	4c 89 f7             	mov    %r14,%rdi
    2d8d:	e8 00 00 00 00       	call   2d92 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x382>
    2d92:	48 8d 44 24 50       	lea    0x50(%rsp),%rax
    2d97:	4c 8d 25 00 00 00 00 	lea    0x0(%rip),%r12        # 2d9e <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x38e>
    2d9e:	31 ed                	xor    %ebp,%ebp
    2da0:	48 89 44 24 38       	mov    %rax,0x38(%rsp)
    2da5:	e9 dc 00 00 00       	jmp    2e86 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x476>
    2daa:	66 0f 1f 44 00 00    	nopw   0x0(%rax,%rax,1)
    2db0:	41 8b 88 a4 00 00 00 	mov    0xa4(%r8),%ecx
    2db7:	41 8b b8 a0 00 00 00 	mov    0xa0(%r8),%edi
    2dbe:	48 8d 71 01          	lea    0x1(%rcx),%rsi
    2dc2:	48 39 f7             	cmp    %rsi,%rdi
    2dc5:	0f 83 95 02 00 00    	jae    3060 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x650>
    2dcb:	49 8b 48 30          	mov    0x30(%r8),%rcx
    2dcf:	c6 44 24 48 00       	movb   $0x0,0x48(%rsp)
    2dd4:	48 85 c9             	test   %rcx,%rcx
    2dd7:	0f 84 53 01 00 00    	je     2f30 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x520>
    2ddd:	49 8b 58 20          	mov    0x20(%r8),%rbx
    2de1:	c6 04 13 2b          	movb   $0x2b,(%rbx,%rdx,1)
    2de5:	49 ff 40 28          	incq   0x28(%r8)
    2de9:	4c 89 ef             	mov    %r13,%rdi
    2dec:	e8 00 00 00 00       	call   2df1 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x3e1>
    2df1:	4c 89 ee             	mov    %r13,%rsi
    2df4:	4c 89 f7             	mov    %r14,%rdi
    2df7:	48 89 c2             	mov    %rax,%rdx
    2dfa:	e8 00 00 00 00       	call   2dff <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x3ef>
    2dff:	4c 8b 6c 24 40       	mov    0x40(%rsp),%r13
    2e04:	49 8b 85 98 00 00 00 	mov    0x98(%r13),%rax
    2e0b:	49 8b 55 28          	mov    0x28(%r13),%rdx
    2e0f:	48 85 c0             	test   %rax,%rax
    2e12:	74 20                	je     2e34 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x424>
    2e14:	48 85 d2             	test   %rdx,%rdx
    2e17:	75 1b                	jne    2e34 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x424>
    2e19:	41 8b 8d a4 00 00 00 	mov    0xa4(%r13),%ecx
    2e20:	41 8b bd a0 00 00 00 	mov    0xa0(%r13),%edi
    2e27:	48 8d 71 02          	lea    0x2(%rcx),%rsi
    2e2b:	48 39 f7             	cmp    %rsi,%rdi
    2e2e:	0f 83 0c 02 00 00    	jae    3040 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x630>
    2e34:	49 8b 5d 30          	mov    0x30(%r13),%rbx
    2e38:	48 8d 42 02          	lea    0x2(%rdx),%rax
    2e3c:	c6 44 24 48 00       	movb   $0x0,0x48(%rsp)
    2e41:	48 39 c3             	cmp    %rax,%rbx
    2e44:	0f 82 86 01 00 00    	jb     2fd0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x5c0>
    2e4a:	4d 8b 45 20          	mov    0x20(%r13),%r8
    2e4e:	66 41 c7 04 10 0d 0a 	movw   $0xa0d,(%r8,%rdx,1)
    2e55:	49 83 45 28 02       	addq   $0x2,0x28(%r13)
    2e5a:	48 8b 7c 24 50       	mov    0x50(%rsp),%rdi
    2e5f:	48 8b 44 24 08       	mov    0x8(%rsp),%rax
    2e64:	48 39 c7             	cmp    %rax,%rdi
    2e67:	74 0e                	je     2e77 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x467>
    2e69:	48 8b 44 24 60       	mov    0x60(%rsp),%rax
    2e6e:	48 8d 70 01          	lea    0x1(%rax),%rsi
    2e72:	e8 00 00 00 00       	call   2e77 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x467>
    2e77:	ff c5                	inc    %ebp
    2e79:	49 83 c4 10          	add    $0x10,%r12
    2e7d:	83 fd 15             	cmp    $0x15,%ebp
    2e80:	0f 84 4a 02 00 00    	je     30d0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x6c0>
    2e86:	c4 c2 d3 f7 5f 20    	shrx   %rbp,0x20(%r15),%rbx
    2e8c:	83 e3 01             	and    $0x1,%ebx
    2e8f:	74 e6                	je     2e77 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x467>
    2e91:	49 8b 0c 24          	mov    (%r12),%rcx
    2e95:	48 8d 44 24 60       	lea    0x60(%rsp),%rax
    2e9a:	48 c7 44 24 58 01 00 00 00 	movq   $0x1,0x58(%rsp)
    2ea3:	66 c7 44 24 60 40 00 	movw   $0x40,0x60(%rsp)
    2eaa:	48 89 44 24 08       	mov    %rax,0x8(%rsp)
    2eaf:	48 89 44 24 50       	mov    %rax,0x50(%rsp)
    2eb4:	48 89 cf             	mov    %rcx,%rdi
    2eb7:	48 89 4c 24 18       	mov    %rcx,0x18(%rsp)
    2ebc:	e8 00 00 00 00       	call   2ec1 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x4b1>
    2ec1:	48 8b 4c 24 18       	mov    0x18(%rsp),%rcx
    2ec6:	4c 8d 68 01          	lea    0x1(%rax),%r13
    2eca:	49 83 fd 0f          	cmp    $0xf,%r13
    2ece:	0f 87 cc 01 00 00    	ja     30a0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x690>
    2ed4:	48 85 c0             	test   %rax,%rax
    2ed7:	0f 85 a3 01 00 00    	jne    3080 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x670>
    2edd:	48 8b 44 24 08       	mov    0x8(%rsp),%rax
    2ee2:	4c 8b 44 24 40       	mov    0x40(%rsp),%r8
    2ee7:	4c 89 6c 24 58       	mov    %r13,0x58(%rsp)
    2eec:	42 c6 04 28 00       	movb   $0x0,(%rax,%r13,1)
    2ef1:	4c 8b 6c 24 50       	mov    0x50(%rsp),%r13
    2ef6:	49 8b 80 98 00 00 00 	mov    0x98(%r8),%rax
    2efd:	49 8b 50 28          	mov    0x28(%r8),%rdx
    2f01:	48 85 c0             	test   %rax,%rax
    2f04:	74 09                	je     2f0f <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x4ff>
    2f06:	48 85 d2             	test   %rdx,%rdx
    2f09:	0f 84 a1 fe ff ff    	je     2db0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x3a0>
    2f0f:	49 8b 48 30          	mov    0x30(%r8),%rcx
    2f13:	48 8d 5a 01          	lea    0x1(%rdx),%rbx
    2f17:	c6 44 24 48 00       	movb   $0x0,0x48(%rsp)
    2f1c:	48 39 d9             	cmp    %rbx,%rcx
    2f1f:	0f 83 b8 fe ff ff    	jae    2ddd <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x3cd>
    2f25:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    2f30:	48 01 c9             	add    %rcx,%rcx
    2f33:	48 39 d9             	cmp    %rbx,%rcx
    2f36:	72 f8                	jb     2f30 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x520>
    2f38:	48 89 cf             	mov    %rcx,%rdi
    2f3b:	48 89 54 24 30       	mov    %rdx,0x30(%rsp)
    2f40:	4c 89 44 24 20       	mov    %r8,0x20(%rsp)
    2f45:	48 89 4c 24 18       	mov    %rcx,0x18(%rsp)
    2f4a:	e8 00 00 00 00       	call   2f4f <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x53f>
    2f4f:	4c 8b 44 24 20       	mov    0x20(%rsp),%r8
    2f54:	48 8b 4c 24 18       	mov    0x18(%rsp),%rcx
    2f59:	48 8b 54 24 30       	mov    0x30(%rsp),%rdx
    2f5e:	48 89 c7             	mov    %rax,%rdi
    2f61:	48 89 c3             	mov    %rax,%rbx
    2f64:	49 8b 70 20          	mov    0x20(%r8),%rsi
    2f68:	4c 89 44 24 28       	mov    %r8,0x28(%rsp)
    2f6d:	48 89 4c 24 20       	mov    %rcx,0x20(%rsp)
    2f72:	48 89 74 24 18       	mov    %rsi,0x18(%rsp)
    2f77:	e8 00 00 00 00       	call   2f7c <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x56c>
    2f7c:	4c 8b 44 24 28       	mov    0x28(%rsp),%r8
    2f81:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
    2f86:	48 8b 4c 24 20       	mov    0x20(%rsp),%rcx
    2f8b:	49 8d 40 38          	lea    0x38(%r8),%rax
    2f8f:	48 39 c6             	cmp    %rax,%rsi
    2f92:	74 1c                	je     2fb0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x5a0>
    2f94:	48 89 f7             	mov    %rsi,%rdi
    2f97:	4c 89 44 24 20       	mov    %r8,0x20(%rsp)
    2f9c:	48 89 4c 24 18       	mov    %rcx,0x18(%rsp)
    2fa1:	e8 00 00 00 00       	call   2fa6 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x596>
    2fa6:	4c 8b 44 24 20       	mov    0x20(%rsp),%r8
    2fab:	48 8b 4c 24 18       	mov    0x18(%rsp),%rcx
    2fb0:	49 8b 50 28          	mov    0x28(%r8),%rdx
    2fb4:	49 89 58 20          	mov    %rbx,0x20(%r8)
    2fb8:	49 89 48 30          	mov    %rcx,0x30(%r8)
    2fbc:	e9 20 fe ff ff       	jmp    2de1 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x3d1>
    2fc1:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    2fcc:	0f 1f 40 00          	nopl   0x0(%rax)
    2fd0:	48 01 db             	add    %rbx,%rbx
    2fd3:	48 39 c3             	cmp    %rax,%rbx
    2fd6:	72 f8                	jb     2fd0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x5c0>
    2fd8:	48 89 df             	mov    %rbx,%rdi
    2fdb:	48 89 54 24 18       	mov    %rdx,0x18(%rsp)
    2fe0:	e8 00 00 00 00       	call   2fe5 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x5d5>
    2fe5:	49 8b 75 20          	mov    0x20(%r13),%rsi
    2fe9:	48 8b 54 24 18       	mov    0x18(%rsp),%rdx
    2fee:	48 89 d9             	mov    %rbx,%rcx
    2ff1:	48 89 c7             	mov    %rax,%rdi
    2ff4:	48 89 74 24 18       	mov    %rsi,0x18(%rsp)
    2ff9:	e8 00 00 00 00       	call   2ffe <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x5ee>
    2ffe:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
    3003:	49 89 c0             	mov    %rax,%r8
    3006:	49 8d 45 38          	lea    0x38(%r13),%rax
    300a:	48 39 c6             	cmp    %rax,%rsi
    300d:	74 12                	je     3021 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x611>
    300f:	48 89 f7             	mov    %rsi,%rdi
    3012:	4c 89 44 24 18       	mov    %r8,0x18(%rsp)
    3017:	e8 00 00 00 00       	call   301c <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x60c>
    301c:	4c 8b 44 24 18       	mov    0x18(%rsp),%r8
    3021:	49 8b 55 28          	mov    0x28(%r13),%rdx
    3025:	4d 89 45 20          	mov    %r8,0x20(%r13)
    3029:	49 89 5d 30          	mov    %rbx,0x30(%r13)
    302d:	e9 1c fe ff ff       	jmp    2e4e <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x43e>
    3032:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    303d:	0f 1f 00             	nopl   (%rax)
    3040:	66 c7 04 08 0d 0a    	movw   $0xa0d,(%rax,%rcx,1)
    3046:	c6 44 24 48 01       	movb   $0x1,0x48(%rsp)
    304b:	41 83 85 a4 00 00 00 02 	addl   $0x2,0xa4(%r13)
    3053:	e9 02 fe ff ff       	jmp    2e5a <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x44a>
    3058:	0f 1f 84 00 00 00 00 00 	nopl   0x0(%rax,%rax,1)
    3060:	c6 04 08 2b          	movb   $0x2b,(%rax,%rcx,1)
    3064:	c6 44 24 48 01       	movb   $0x1,0x48(%rsp)
    3069:	41 ff 80 a4 00 00 00 	incl   0xa4(%r8)
    3070:	e9 74 fd ff ff       	jmp    2de9 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x3d9>
    3075:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    3080:	48 83 f8 01          	cmp    $0x1,%rax
    3084:	74 3a                	je     30c0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x6b0>
    3086:	48 8d 7c 24 61       	lea    0x61(%rsp),%rdi
    308b:	48 89 c2             	mov    %rax,%rdx
    308e:	48 89 ce             	mov    %rcx,%rsi
    3091:	e8 00 00 00 00       	call   3096 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x686>
    3096:	e9 42 fe ff ff       	jmp    2edd <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x4cd>
    309b:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    30a0:	48 8b 7c 24 38       	mov    0x38(%rsp),%rdi
    30a5:	49 89 c0             	mov    %rax,%r8
    30a8:	31 d2                	xor    %edx,%edx
    30aa:	be 01 00 00 00       	mov    $0x1,%esi
    30af:	e8 00 00 00 00       	call   30b4 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x6a4>
    30b4:	48 8b 44 24 50       	mov    0x50(%rsp),%rax
    30b9:	e9 24 fe ff ff       	jmp    2ee2 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x4d2>
    30be:	66 90                	xchg   %ax,%ax
    30c0:	0f b6 01             	movzbl (%rcx),%eax
    30c3:	88 44 24 61          	mov    %al,0x61(%rsp)
    30c7:	e9 11 fe ff ff       	jmp    2edd <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x4cd>
    30cc:	0f 1f 40 00          	nopl   0x0(%rax)
    30d0:	48 8b 44 24 10       	mov    0x10(%rsp),%rax
    30d5:	41 0f b6 5f 2a       	movzbl 0x2a(%r15),%ebx
    30da:	f6 40 1c 04          	testb  $0x4,0x1c(%rax)
    30de:	0f 84 9c 0a 00 00    	je     3b80 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1170>
    30e4:	48 8b 6c 24 40       	mov    0x40(%rsp),%rbp
    30e9:	4c 8b 95 98 00 00 00 	mov    0x98(%rbp),%r10
    30f0:	48 8b 75 28          	mov    0x28(%rbp),%rsi
    30f4:	4d 85 d2             	test   %r10,%r10
    30f7:	74 1e                	je     3117 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x707>
    30f9:	48 85 f6             	test   %rsi,%rsi
    30fc:	75 19                	jne    3117 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x707>
    30fe:	8b 85 a4 00 00 00    	mov    0xa4(%rbp),%eax
    3104:	8b 8d a0 00 00 00    	mov    0xa0(%rbp),%ecx
    310a:	48 8d 50 18          	lea    0x18(%rax),%rdx
    310e:	48 39 d1             	cmp    %rdx,%rcx
    3111:	0f 83 c1 0a 00 00    	jae    3bd8 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x11c8>
    3117:	4c 8b 65 30          	mov    0x30(%rbp),%r12
    311b:	48 8d 46 18          	lea    0x18(%rsi),%rax
    311f:	c6 44 24 48 00       	movb   $0x0,0x48(%rsp)
    3124:	49 39 c4             	cmp    %rax,%r12
    3127:	0f 82 b3 05 00 00    	jb     36e0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xcd0>
    312d:	4c 8b 6d 20          	mov    0x20(%rbp),%r13
    3131:	4d 8d 54 35 00       	lea    0x0(%r13,%rsi,1),%r10
    3136:	45 31 c0             	xor    %r8d,%r8d
    3139:	4d 8d 4a 01          	lea    0x1(%r10),%r9
    313d:	48 8d 74 24 70       	lea    0x70(%rsp),%rsi
    3142:	31 c9                	xor    %ecx,%ecx
    3144:	49 bc cd cc cc cc cc cc cc cc 	movabs $0xcccccccccccccccd,%r12
    314e:	41 c6 02 7e          	movb   $0x7e,(%r10)
    3152:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    315d:	0f 1f 00             	nopl   (%rax)
    3160:	48 89 d8             	mov    %rbx,%rax
    3163:	89 cf                	mov    %ecx,%edi
    3165:	48 ff c6             	inc    %rsi
    3168:	ff c1                	inc    %ecx
    316a:	49 f7 e4             	mul    %r12
    316d:	48 89 d8             	mov    %rbx,%rax
    3170:	48 c1 ea 03          	shr    $0x3,%rdx
    3174:	4c 8d 1c 92          	lea    (%rdx,%rdx,4),%r11
    3178:	4d 01 db             	add    %r11,%r11
    317b:	4c 29 d8             	sub    %r11,%rax
    317e:	83 c0 30             	add    $0x30,%eax
    3181:	88 46 ff             	mov    %al,-0x1(%rsi)
    3184:	48 89 d8             	mov    %rbx,%rax
    3187:	48 89 d3             	mov    %rdx,%rbx
    318a:	48 83 f8 09          	cmp    $0x9,%rax
    318e:	77 d0                	ja     3160 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x750>
    3190:	4d 8d 1c 09          	lea    (%r9,%rcx,1),%r11
    3194:	4c 89 c8             	mov    %r9,%rax
    3197:	42 8d 34 0f          	lea    (%rdi,%r9,1),%esi
    319b:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    31a0:	89 f2                	mov    %esi,%edx
    31a2:	29 c2                	sub    %eax,%edx
    31a4:	48 ff c0             	inc    %rax
    31a7:	0f b6 54 14 70       	movzbl 0x70(%rsp,%rdx,1),%edx
    31ac:	88 50 ff             	mov    %dl,-0x1(%rax)
    31af:	49 39 c3             	cmp    %rax,%r11
    31b2:	75 ec                	jne    31a0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x790>
    31b4:	49 01 c9             	add    %rcx,%r9
    31b7:	66 41 c7 01 0d 0a    	movw   $0xa0d,(%r9)
    31bd:	49 83 c1 02          	add    $0x2,%r9
    31c1:	4d 29 d1             	sub    %r10,%r9
    31c4:	45 84 c0             	test   %r8b,%r8b
    31c7:	0f 84 dc 09 00 00    	je     3ba9 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1199>
    31cd:	44 01 8d a4 00 00 00 	add    %r9d,0xa4(%rbp)
    31d4:	31 db                	xor    %ebx,%ebx
    31d6:	41 80 7f 2a 00       	cmpb   $0x0,0x2a(%r15)
    31db:	48 8d 2d 00 00 00 00 	lea    0x0(%rip),%rbp        # 31e2 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x7d2>
    31e2:	74 3a                	je     321e <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x80e>
    31e4:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    31ef:	90                   	nop
    31f0:	41 0f b7 47 28       	movzwl 0x28(%r15),%eax
    31f5:	01 d8                	add    %ebx,%eax
    31f7:	ff c3                	inc    %ebx
    31f9:	89 c0                	mov    %eax,%eax
    31fb:	4c 8b 64 c5 00       	mov    0x0(%rbp,%rax,8),%r12
    3200:	4c 89 e7             	mov    %r12,%rdi
    3203:	e8 00 00 00 00       	call   3208 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x7f8>
    3208:	4c 89 e6             	mov    %r12,%rsi
    320b:	4c 89 f7             	mov    %r14,%rdi
    320e:	89 c2                	mov    %eax,%edx
    3210:	e8 7b cf ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3215:	41 0f b6 47 2a       	movzbl 0x2a(%r15),%eax
    321a:	39 c3                	cmp    %eax,%ebx
    321c:	72 d2                	jb     31f0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x7e0>
    321e:	48 8b 44 24 10       	mov    0x10(%rsp),%rax
    3223:	41 0f b6 5f 2e       	movzbl 0x2e(%r15),%ebx
    3228:	f6 40 1c 04          	testb  $0x4,0x1c(%rax)
    322c:	0f 84 5e 09 00 00    	je     3b90 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1180>
    3232:	48 8b 6c 24 40       	mov    0x40(%rsp),%rbp
    3237:	4c 8b 95 98 00 00 00 	mov    0x98(%rbp),%r10
    323e:	48 8b 75 28          	mov    0x28(%rbp),%rsi
    3242:	4d 85 d2             	test   %r10,%r10
    3245:	74 1e                	je     3265 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x855>
    3247:	48 85 f6             	test   %rsi,%rsi
    324a:	75 19                	jne    3265 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x855>
    324c:	8b 85 a4 00 00 00    	mov    0xa4(%rbp),%eax
    3252:	8b 8d a0 00 00 00    	mov    0xa0(%rbp),%ecx
    3258:	48 8d 50 18          	lea    0x18(%rax),%rdx
    325c:	48 39 d1             	cmp    %rdx,%rcx
    325f:	0f 83 60 09 00 00    	jae    3bc5 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x11b5>
    3265:	4c 8b 65 30          	mov    0x30(%rbp),%r12
    3269:	48 8d 46 18          	lea    0x18(%rsi),%rax
    326d:	c6 44 24 48 00       	movb   $0x0,0x48(%rsp)
    3272:	49 39 c4             	cmp    %rax,%r12
    3275:	0f 82 c5 04 00 00    	jb     3740 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd30>
    327b:	4c 8b 6d 20          	mov    0x20(%rbp),%r13
    327f:	4d 8d 54 35 00       	lea    0x0(%r13,%rsi,1),%r10
    3284:	45 31 c0             	xor    %r8d,%r8d
    3287:	4d 8d 4a 01          	lea    0x1(%r10),%r9
    328b:	48 8d 74 24 70       	lea    0x70(%rsp),%rsi
    3290:	31 c9                	xor    %ecx,%ecx
    3292:	49 bc cd cc cc cc cc cc cc cc 	movabs $0xcccccccccccccccd,%r12
    329c:	41 c6 02 7e          	movb   $0x7e,(%r10)
    32a0:	48 89 d8             	mov    %rbx,%rax
    32a3:	89 cf                	mov    %ecx,%edi
    32a5:	48 ff c6             	inc    %rsi
    32a8:	ff c1                	inc    %ecx
    32aa:	49 f7 e4             	mul    %r12
    32ad:	48 89 d8             	mov    %rbx,%rax
    32b0:	48 c1 ea 03          	shr    $0x3,%rdx
    32b4:	4c 8d 1c 92          	lea    (%rdx,%rdx,4),%r11
    32b8:	4d 01 db             	add    %r11,%r11
    32bb:	4c 29 d8             	sub    %r11,%rax
    32be:	83 c0 30             	add    $0x30,%eax
    32c1:	88 46 ff             	mov    %al,-0x1(%rsi)
    32c4:	48 89 d8             	mov    %rbx,%rax
    32c7:	48 89 d3             	mov    %rdx,%rbx
    32ca:	48 83 f8 09          	cmp    $0x9,%rax
    32ce:	77 d0                	ja     32a0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x890>
    32d0:	4d 8d 1c 09          	lea    (%r9,%rcx,1),%r11
    32d4:	4c 89 c8             	mov    %r9,%rax
    32d7:	42 8d 34 0f          	lea    (%rdi,%r9,1),%esi
    32db:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    32e0:	89 f2                	mov    %esi,%edx
    32e2:	29 c2                	sub    %eax,%edx
    32e4:	48 ff c0             	inc    %rax
    32e7:	0f b6 54 14 70       	movzbl 0x70(%rsp,%rdx,1),%edx
    32ec:	88 50 ff             	mov    %dl,-0x1(%rax)
    32ef:	49 39 c3             	cmp    %rax,%r11
    32f2:	75 ec                	jne    32e0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x8d0>
    32f4:	49 01 c9             	add    %rcx,%r9
    32f7:	66 41 c7 01 0d 0a    	movw   $0xa0d,(%r9)
    32fd:	49 83 c1 02          	add    $0x2,%r9
    3301:	4d 29 d1             	sub    %r10,%r9
    3304:	45 84 c0             	test   %r8b,%r8b
    3307:	0f 84 93 08 00 00    	je     3ba0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1190>
    330d:	44 01 8d a4 00 00 00 	add    %r9d,0xa4(%rbp)
    3314:	31 c0                	xor    %eax,%eax
    3316:	41 80 7f 2e 00       	cmpb   $0x0,0x2e(%r15)
    331b:	4c 8d 25 00 00 00 00 	lea    0x0(%rip),%r12        # 3322 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x912>
    3322:	0f 84 fd 06 00 00    	je     3a25 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1015>
    3328:	41 89 c5             	mov    %eax,%r13d
    332b:	4c 89 7c 24 08       	mov    %r15,0x8(%rsp)
    3330:	e9 6d 02 00 00       	jmp    35a2 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xb92>
    3335:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    3340:	ba 05 00 00 00       	mov    $0x5,%edx
    3345:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 334c <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x93c>
    334c:	4c 89 f7             	mov    %r14,%rdi
    334f:	e8 3c ce ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3354:	ba 04 00 00 00       	mov    $0x4,%edx
    3359:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3360 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x950>
    3360:	4c 89 f7             	mov    %r14,%rdi
    3363:	e8 28 ce ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3368:	89 da                	mov    %ebx,%edx
    336a:	be 01 00 00 00       	mov    $0x1,%esi
    336f:	4c 89 f7             	mov    %r14,%rdi
    3372:	e8 00 00 00 00       	call   3377 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x967>
    3377:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 337e <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x96e>
    337e:	ba 05 00 00 00       	mov    $0x5,%edx
    3383:	4c 89 f7             	mov    %r14,%rdi
    3386:	e8 05 ce ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    338b:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    3390:	49 0f bf 77 0c       	movswq 0xc(%r15),%rsi
    3395:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    3399:	0f 84 14 06 00 00    	je     39b3 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfa3>
    339f:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    33a3:	0f 85 0a 06 00 00    	jne    39b3 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfa3>
    33a9:	44 8b 90 a4 00 00 00 	mov    0xa4(%rax),%r10d
    33b0:	45 85 d2             	test   %r10d,%r10d
    33b3:	0f 85 fa 05 00 00    	jne    39b3 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfa3>
    33b9:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    33be:	0f 85 ef 05 00 00    	jne    39b3 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfa3>
    33c4:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    33c8:	89 b0 bc 00 00 00    	mov    %esi,0xbc(%rax)
    33ce:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    33d9:	ba 09 00 00 00       	mov    $0x9,%edx
    33de:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 33e5 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x9d5>
    33e5:	4c 89 f7             	mov    %r14,%rdi
    33e8:	e8 a3 cd ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    33ed:	89 da                	mov    %ebx,%edx
    33ef:	be 02 00 00 00       	mov    $0x2,%esi
    33f4:	4c 89 f7             	mov    %r14,%rdi
    33f7:	e8 00 00 00 00       	call   33fc <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x9ec>
    33fc:	ba 04 00 00 00       	mov    $0x4,%edx
    3401:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3408 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x9f8>
    3408:	4c 89 f7             	mov    %r14,%rdi
    340b:	e8 80 cd ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3410:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    3415:	4d 8d 3c c4          	lea    (%r12,%rax,8),%r15
    3419:	41 0f b6 47 1a       	movzbl 0x1a(%r15),%eax
    341e:	84 c0                	test   %al,%al
    3420:	0f 85 7a 03 00 00    	jne    37a0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd90>
    3426:	ba 05 00 00 00       	mov    $0x5,%edx
    342b:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3432 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xa22>
    3432:	4c 89 f7             	mov    %r14,%rdi
    3435:	e8 56 cd ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    343a:	ba 04 00 00 00       	mov    $0x4,%edx
    343f:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3446 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xa36>
    3446:	4c 89 f7             	mov    %r14,%rdi
    3449:	e8 42 cd ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    344e:	89 da                	mov    %ebx,%edx
    3450:	be 03 00 00 00       	mov    $0x3,%esi
    3455:	4c 89 f7             	mov    %r14,%rdi
    3458:	e8 00 00 00 00       	call   345d <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xa4d>
    345d:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3464 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xa54>
    3464:	ba 07 00 00 00       	mov    $0x7,%edx
    3469:	4c 89 f7             	mov    %r14,%rdi
    346c:	e8 1f cd ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3471:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    3476:	49 0f bf 77 1c       	movswq 0x1c(%r15),%rsi
    347b:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    347f:	0f 84 6b 05 00 00    	je     39f0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfe0>
    3485:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    3489:	0f 85 61 05 00 00    	jne    39f0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfe0>
    348f:	44 8b 88 a4 00 00 00 	mov    0xa4(%rax),%r9d
    3496:	45 85 c9             	test   %r9d,%r9d
    3499:	0f 85 51 05 00 00    	jne    39f0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfe0>
    349f:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    34a4:	0f 85 46 05 00 00    	jne    39f0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfe0>
    34aa:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    34ae:	89 b0 bc 00 00 00    	mov    %esi,0xbc(%rax)
    34b4:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    34bf:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 34c6 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xab6>
    34c6:	ba 07 00 00 00       	mov    $0x7,%edx
    34cb:	4c 89 f7             	mov    %r14,%rdi
    34ce:	e8 bd cc ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    34d3:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    34d8:	49 0f bf 74 c4 1e    	movswq 0x1e(%r12,%rax,8),%rsi
    34de:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    34e3:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    34e7:	0f 84 f3 04 00 00    	je     39e0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfd0>
    34ed:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    34f1:	0f 85 e9 04 00 00    	jne    39e0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfd0>
    34f7:	44 8b 80 a4 00 00 00 	mov    0xa4(%rax),%r8d
    34fe:	45 85 c0             	test   %r8d,%r8d
    3501:	0f 85 d9 04 00 00    	jne    39e0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfd0>
    3507:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    350c:	0f 85 ce 04 00 00    	jne    39e0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfd0>
    3512:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    3516:	89 b0 bc 00 00 00    	mov    %esi,0xbc(%rax)
    351c:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    3527:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 352e <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xb1e>
    352e:	ba 05 00 00 00       	mov    $0x5,%edx
    3533:	4c 89 f7             	mov    %r14,%rdi
    3536:	e8 55 cc ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    353b:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    3540:	49 0f bf 74 c4 20    	movswq 0x20(%r12,%rax,8),%rsi
    3546:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    354b:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    354f:	0f 84 b6 03 00 00    	je     390b <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xefb>
    3555:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    3559:	0f 85 ac 03 00 00    	jne    390b <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xefb>
    355f:	8b 90 a4 00 00 00    	mov    0xa4(%rax),%edx
    3565:	85 d2                	test   %edx,%edx
    3567:	0f 85 9e 03 00 00    	jne    390b <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xefb>
    356d:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    3572:	0f 85 93 03 00 00    	jne    390b <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xefb>
    3578:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    357c:	89 b0 bc 00 00 00    	mov    %esi,0xbc(%rax)
    3582:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    358d:	48 8b 44 24 08       	mov    0x8(%rsp),%rax
    3592:	41 ff c5             	inc    %r13d
    3595:	0f b6 40 2e          	movzbl 0x2e(%rax),%eax
    3599:	41 39 c5             	cmp    %eax,%r13d
    359c:	0f 83 7e 04 00 00    	jae    3a20 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1010>
    35a2:	48 8b 44 24 08       	mov    0x8(%rsp),%rax
    35a7:	48 8b 4c 24 10       	mov    0x10(%rsp),%rcx
    35ac:	0f b7 40 2c          	movzwl 0x2c(%rax),%eax
    35b0:	0f b6 49 1c          	movzbl 0x1c(%rcx),%ecx
    35b4:	44 01 e8             	add    %r13d,%eax
    35b7:	89 cb                	mov    %ecx,%ebx
    35b9:	88 4c 24 18          	mov    %cl,0x18(%rsp)
    35bd:	48 8d 0d 00 00 00 00 	lea    0x0(%rip),%rcx        # 35c4 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xbb4>
    35c4:	89 c0                	mov    %eax,%eax
    35c6:	0f b6 2c 01          	movzbl (%rcx,%rax,1),%ebp
    35ca:	c0 eb 02             	shr    $0x2,%bl
    35cd:	83 e3 01             	and    $0x1,%ebx
    35d0:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    35d5:	89 da                	mov    %ebx,%edx
    35d7:	4d 8b 3c c4          	mov    (%r12,%rax,8),%r15
    35db:	4d 85 ff             	test   %r15,%r15
    35de:	0f 84 dc 03 00 00    	je     39c0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfb0>
    35e4:	be 04 00 00 00       	mov    $0x4,%esi
    35e9:	4c 89 f7             	mov    %r14,%rdi
    35ec:	e8 00 00 00 00       	call   35f1 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xbe1>
    35f1:	ba 05 00 00 00       	mov    $0x5,%edx
    35f6:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 35fd <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xbed>
    35fd:	4c 89 f7             	mov    %r14,%rdi
    3600:	e8 8b cb ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3605:	4c 89 ff             	mov    %r15,%rdi
    3608:	e8 00 00 00 00       	call   360d <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xbfd>
    360d:	4c 89 fe             	mov    %r15,%rsi
    3610:	4c 89 f7             	mov    %r14,%rdi
    3613:	89 c2                	mov    %eax,%edx
    3615:	e8 76 cb ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    361a:	ba 05 00 00 00       	mov    $0x5,%edx
    361f:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3626 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xc16>
    3626:	4c 89 f7             	mov    %r14,%rdi
    3629:	e8 62 cb ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    362e:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    3633:	41 89 d8             	mov    %ebx,%r8d
    3636:	b9 0a 00 00 00       	mov    $0xa,%ecx
    363b:	41 0f b7 74 c4 08    	movzwl 0x8(%r12,%rax,8),%esi
    3641:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 3648 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xc38>
    3648:	4c 89 f7             	mov    %r14,%rdi
    364b:	4d 8d 3c c4          	lea    (%r12,%rax,8),%r15
    364f:	e8 9c e8 ff ff       	call   1ef0 <_ZN8tomo_db012_GLOBAL__N_116reply_string_setERNS_2Op4SinkEmPKPKcjb>
    3654:	ba 0c 00 00 00       	mov    $0xc,%edx
    3659:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3660 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xc50>
    3660:	4c 89 f7             	mov    %r14,%rdi
    3663:	e8 28 cb ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3668:	89 da                	mov    %ebx,%edx
    366a:	be 02 00 00 00       	mov    $0x2,%esi
    366f:	4c 89 f7             	mov    %r14,%rdi
    3672:	e8 00 00 00 00       	call   3677 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xc67>
    3677:	ba 04 00 00 00       	mov    $0x4,%edx
    367c:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3683 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xc73>
    3683:	4c 89 f7             	mov    %r14,%rdi
    3686:	e8 05 cb ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    368b:	41 0f b6 47 0a       	movzbl 0xa(%r15),%eax
    3690:	84 c0                	test   %al,%al
    3692:	0f 84 a8 fc ff ff    	je     3340 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x930>
    3698:	3c 01                	cmp    $0x1,%al
    369a:	0f 84 80 02 00 00    	je     3920 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xf10>
    36a0:	4c 89 f7             	mov    %r14,%rdi
    36a3:	ba 07 00 00 00       	mov    $0x7,%edx
    36a8:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 36af <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xc9f>
    36af:	e8 dc ca ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    36b4:	4c 89 f7             	mov    %r14,%rdi
    36b7:	ba 04 00 00 00       	mov    $0x4,%edx
    36bc:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 36c3 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xcb3>
    36c3:	e8 c8 ca ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    36c8:	89 da                	mov    %ebx,%edx
    36ca:	31 f6                	xor    %esi,%esi
    36cc:	4c 89 f7             	mov    %r14,%rdi
    36cf:	e8 00 00 00 00       	call   36d4 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xcc4>
    36d4:	e9 00 fd ff ff       	jmp    33d9 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x9c9>
    36d9:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
    36e0:	4d 01 e4             	add    %r12,%r12
    36e3:	49 39 c4             	cmp    %rax,%r12
    36e6:	72 f8                	jb     36e0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xcd0>
    36e8:	4c 89 e7             	mov    %r12,%rdi
    36eb:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
    36f0:	e8 00 00 00 00       	call   36f5 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xce5>
    36f5:	4c 8b 45 20          	mov    0x20(%rbp),%r8
    36f9:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
    36fe:	4c 89 e1             	mov    %r12,%rcx
    3701:	48 89 c7             	mov    %rax,%rdi
    3704:	49 89 c5             	mov    %rax,%r13
    3707:	4c 89 c6             	mov    %r8,%rsi
    370a:	4c 89 44 24 08       	mov    %r8,0x8(%rsp)
    370f:	e8 00 00 00 00       	call   3714 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd04>
    3714:	4c 8b 44 24 08       	mov    0x8(%rsp),%r8
    3719:	48 8d 45 38          	lea    0x38(%rbp),%rax
    371d:	49 39 c0             	cmp    %rax,%r8
    3720:	74 08                	je     372a <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd1a>
    3722:	4c 89 c7             	mov    %r8,%rdi
    3725:	e8 00 00 00 00       	call   372a <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd1a>
    372a:	48 8b 75 28          	mov    0x28(%rbp),%rsi
    372e:	4c 89 6d 20          	mov    %r13,0x20(%rbp)
    3732:	4c 89 65 30          	mov    %r12,0x30(%rbp)
    3736:	e9 f6 f9 ff ff       	jmp    3131 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x721>
    373b:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    3740:	4d 01 e4             	add    %r12,%r12
    3743:	49 39 c4             	cmp    %rax,%r12
    3746:	72 f8                	jb     3740 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd30>
    3748:	4c 89 e7             	mov    %r12,%rdi
    374b:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
    3750:	e8 00 00 00 00       	call   3755 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd45>
    3755:	4c 8b 45 20          	mov    0x20(%rbp),%r8
    3759:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
    375e:	4c 89 e1             	mov    %r12,%rcx
    3761:	48 89 c7             	mov    %rax,%rdi
    3764:	49 89 c5             	mov    %rax,%r13
    3767:	4c 89 c6             	mov    %r8,%rsi
    376a:	4c 89 44 24 08       	mov    %r8,0x8(%rsp)
    376f:	e8 00 00 00 00       	call   3774 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd64>
    3774:	4c 8b 44 24 08       	mov    0x8(%rsp),%r8
    3779:	48 8d 45 38          	lea    0x38(%rbp),%rax
    377d:	49 39 c0             	cmp    %rax,%r8
    3780:	74 08                	je     378a <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd7a>
    3782:	4c 89 c7             	mov    %r8,%rdi
    3785:	e8 00 00 00 00       	call   378a <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd7a>
    378a:	48 8b 75 28          	mov    0x28(%rbp),%rsi
    378e:	4c 89 6d 20          	mov    %r13,0x20(%rbp)
    3792:	4c 89 65 30          	mov    %r12,0x30(%rbp)
    3796:	e9 e4 fa ff ff       	jmp    327f <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x86f>
    379b:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    37a0:	3c 01                	cmp    $0x1,%al
    37a2:	74 3c                	je     37e0 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xdd0>
    37a4:	4c 89 f7             	mov    %r14,%rdi
    37a7:	ba 07 00 00 00       	mov    $0x7,%edx
    37ac:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 37b3 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xda3>
    37b3:	e8 d8 c9 ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    37b8:	4c 89 f7             	mov    %r14,%rdi
    37bb:	ba 04 00 00 00       	mov    $0x4,%edx
    37c0:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 37c7 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xdb7>
    37c7:	e8 c4 c9 ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    37cc:	89 da                	mov    %ebx,%edx
    37ce:	31 f6                	xor    %esi,%esi
    37d0:	4c 89 f7             	mov    %r14,%rdi
    37d3:	e8 00 00 00 00       	call   37d8 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xdc8>
    37d8:	e9 b0 fd ff ff       	jmp    358d <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xb7d>
    37dd:	0f 1f 00             	nopl   (%rax)
    37e0:	ba 06 00 00 00       	mov    $0x6,%edx
    37e5:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 37ec <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xddc>
    37ec:	4c 89 f7             	mov    %r14,%rdi
    37ef:	e8 9c c9 ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    37f4:	ba 04 00 00 00       	mov    $0x4,%edx
    37f9:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3800 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xdf0>
    3800:	4c 89 f7             	mov    %r14,%rdi
    3803:	e8 88 c9 ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3808:	89 da                	mov    %ebx,%edx
    380a:	be 03 00 00 00       	mov    $0x3,%esi
    380f:	4c 89 f7             	mov    %r14,%rdi
    3812:	e8 00 00 00 00       	call   3817 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xe07>
    3817:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 381e <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xe0e>
    381e:	ba 09 00 00 00       	mov    $0x9,%edx
    3823:	4c 89 f7             	mov    %r14,%rdi
    3826:	e8 65 c9 ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    382b:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    3830:	49 0f bf 77 22       	movswq 0x22(%r15),%rsi
    3835:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    3839:	0f 84 d1 01 00 00    	je     3a10 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1000>
    383f:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    3843:	0f 85 c7 01 00 00    	jne    3a10 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1000>
    3849:	8b b8 a4 00 00 00    	mov    0xa4(%rax),%edi
    384f:	85 ff                	test   %edi,%edi
    3851:	0f 85 b9 01 00 00    	jne    3a10 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1000>
    3857:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    385c:	0f 85 ae 01 00 00    	jne    3a10 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1000>
    3862:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    3866:	89 b0 bc 00 00 00    	mov    %esi,0xbc(%rax)
    386c:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    3877:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 387e <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xe6e>
    387e:	ba 08 00 00 00       	mov    $0x8,%edx
    3883:	4c 89 f7             	mov    %r14,%rdi
    3886:	e8 05 c9 ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    388b:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    3890:	49 0f bf 74 c4 24    	movswq 0x24(%r12,%rax,8),%rsi
    3896:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    389b:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    389f:	0f 84 5b 01 00 00    	je     3a00 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xff0>
    38a5:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    38a9:	0f 85 51 01 00 00    	jne    3a00 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xff0>
    38af:	8b 88 a4 00 00 00    	mov    0xa4(%rax),%ecx
    38b5:	85 c9                	test   %ecx,%ecx
    38b7:	0f 85 43 01 00 00    	jne    3a00 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xff0>
    38bd:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    38c2:	0f 85 38 01 00 00    	jne    3a00 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xff0>
    38c8:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    38cc:	89 b0 bc 00 00 00    	mov    %esi,0xbc(%rax)
    38d2:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    38dd:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 38e4 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xed4>
    38e4:	ba 07 00 00 00       	mov    $0x7,%edx
    38e9:	4c 89 f7             	mov    %r14,%rdi
    38ec:	e8 9f c8 ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    38f1:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    38f6:	49 0f bf 74 c4 1e    	movswq 0x1e(%r12,%rax,8),%rsi
    38fc:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    3901:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    3905:	0f 85 4a fc ff ff    	jne    3555 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xb45>
    390b:	4c 89 f7             	mov    %r14,%rdi
    390e:	e8 5d ca ff ff       	call   370 <_ZN8tomo_db09reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    3913:	e9 75 fc ff ff       	jmp    358d <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xb7d>
    3918:	0f 1f 84 00 00 00 00 00 	nopl   0x0(%rax,%rax,1)
    3920:	ba 07 00 00 00       	mov    $0x7,%edx
    3925:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 392c <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xf1c>
    392c:	4c 89 f7             	mov    %r14,%rdi
    392f:	e8 5c c8 ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3934:	ba 04 00 00 00       	mov    $0x4,%edx
    3939:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3940 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xf30>
    3940:	4c 89 f7             	mov    %r14,%rdi
    3943:	e8 48 c8 ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3948:	89 da                	mov    %ebx,%edx
    394a:	be 02 00 00 00       	mov    $0x2,%esi
    394f:	4c 89 f7             	mov    %r14,%rdi
    3952:	e8 00 00 00 00       	call   3957 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xf47>
    3957:	ba 07 00 00 00       	mov    $0x7,%edx
    395c:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3963 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xf53>
    3963:	4c 89 f7             	mov    %r14,%rdi
    3966:	e8 25 c8 ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    396b:	49 8b 77 10          	mov    0x10(%r15),%rsi
    396f:	48 89 f7             	mov    %rsi,%rdi
    3972:	48 89 74 24 18       	mov    %rsi,0x18(%rsp)
    3977:	e8 00 00 00 00       	call   397c <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xf6c>
    397c:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
    3981:	4c 89 f7             	mov    %r14,%rdi
    3984:	89 c2                	mov    %eax,%edx
    3986:	e8 05 c8 ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    398b:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3992 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xf82>
    3992:	ba 09 00 00 00       	mov    $0x9,%edx
    3997:	4c 89 f7             	mov    %r14,%rdi
    399a:	e8 f1 c7 ff ff       	call   190 <_ZN8tomo_db010reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    399f:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    39a4:	49 0f bf 77 18       	movswq 0x18(%r15),%rsi
    39a9:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    39ad:	0f 85 ec f9 ff ff    	jne    339f <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x98f>
    39b3:	4c 89 f7             	mov    %r14,%rdi
    39b6:	e8 b5 c9 ff ff       	call   370 <_ZN8tomo_db09reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    39bb:	e9 19 fa ff ff       	jmp    33d9 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x9c9>
    39c0:	be 03 00 00 00       	mov    $0x3,%esi
    39c5:	4c 89 f7             	mov    %r14,%rdi
    39c8:	e8 00 00 00 00       	call   39cd <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfbd>
    39cd:	e9 48 fc ff ff       	jmp    361a <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xc0a>
    39d2:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    39dd:	0f 1f 00             	nopl   (%rax)
    39e0:	4c 89 f7             	mov    %r14,%rdi
    39e3:	e8 88 c9 ff ff       	call   370 <_ZN8tomo_db09reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    39e8:	e9 3a fb ff ff       	jmp    3527 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xb17>
    39ed:	0f 1f 00             	nopl   (%rax)
    39f0:	4c 89 f7             	mov    %r14,%rdi
    39f3:	e8 78 c9 ff ff       	call   370 <_ZN8tomo_db09reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    39f8:	e9 c2 fa ff ff       	jmp    34bf <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xaaf>
    39fd:	0f 1f 00             	nopl   (%rax)
    3a00:	4c 89 f7             	mov    %r14,%rdi
    3a03:	e8 68 c9 ff ff       	call   370 <_ZN8tomo_db09reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    3a08:	e9 d0 fe ff ff       	jmp    38dd <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xecd>
    3a0d:	0f 1f 00             	nopl   (%rax)
    3a10:	4c 89 f7             	mov    %r14,%rdi
    3a13:	e8 58 c9 ff ff       	call   370 <_ZN8tomo_db09reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    3a18:	e9 5a fe ff ff       	jmp    3877 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xe67>
    3a1d:	0f 1f 00             	nopl   (%rax)
    3a20:	4c 8b 7c 24 08       	mov    0x8(%rsp),%r15
    3a25:	4c 89 ff             	mov    %r15,%rdi
    3a28:	e8 c3 c6 ff ff       	call   f0 <_ZN8tomo_db012_GLOBAL__N_111child_countERKNS_15CommandMetadataE>
    3a2d:	85 c0                	test   %eax,%eax
    3a2f:	0f 84 8d 00 00 00    	je     3ac2 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x10b2>
    3a35:	89 c6                	mov    %eax,%esi
    3a37:	4c 89 f7             	mov    %r14,%rdi
    3a3a:	4c 8d 2d 00 00 00 00 	lea    0x0(%rip),%r13        # 3a41 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1031>
    3a41:	e8 00 00 00 00       	call   3a46 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1036>
    3a46:	4d 8d a5 f0 3f 00 00 	lea    0x3ff0(%r13),%r12
    3a4d:	0f 1f 00             	nopl   (%rax)
    3a50:	4d 8b 37             	mov    (%r15),%r14
    3a53:	49 8b 6d 00          	mov    0x0(%r13),%rbp
    3a57:	4c 89 f7             	mov    %r14,%rdi
    3a5a:	e8 00 00 00 00       	call   3a5f <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x104f>
    3a5f:	4c 89 f6             	mov    %r14,%rsi
    3a62:	48 89 ef             	mov    %rbp,%rdi
    3a65:	48 89 c2             	mov    %rax,%rdx
    3a68:	48 89 c3             	mov    %rax,%rbx
    3a6b:	e8 00 00 00 00       	call   3a70 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1060>
    3a70:	85 c0                	test   %eax,%eax
    3a72:	75 1c                	jne    3a90 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1080>
    3a74:	80 7c 1d 00 7c       	cmpb   $0x7c,0x0(%rbp,%rbx,1)
    3a79:	75 15                	jne    3a90 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1080>
    3a7b:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    3a80:	4c 89 ee             	mov    %r13,%rsi
    3a83:	e8 88 ef ff ff       	call   2a10 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE>
    3a88:	0f 1f 84 00 00 00 00 00 	nopl   0x0(%rax,%rax,1)
    3a90:	49 83 c5 30          	add    $0x30,%r13
    3a94:	4d 39 e5             	cmp    %r12,%r13
    3a97:	75 b7                	jne    3a50 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1040>
    3a99:	48 8b 84 24 88 00 00 00 	mov    0x88(%rsp),%rax
    3aa1:	64 48 2b 04 25 28 00 00 00 	sub    %fs:0x28,%rax
    3aaa:	0f 85 65 01 00 00    	jne    3c15 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1205>
    3ab0:	48 81 c4 98 00 00 00 	add    $0x98,%rsp
    3ab7:	5b                   	pop    %rbx
    3ab8:	5d                   	pop    %rbp
    3ab9:	41 5c                	pop    %r12
    3abb:	41 5d                	pop    %r13
    3abd:	41 5e                	pop    %r14
    3abf:	41 5f                	pop    %r15
    3ac1:	c3                   	ret
    3ac2:	48 8b 44 24 10       	mov    0x10(%rsp),%rax
    3ac7:	f6 40 1c 04          	testb  $0x4,0x1c(%rax)
    3acb:	0f 84 2d 01 00 00    	je     3bfe <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x11ee>
    3ad1:	48 8b 6c 24 40       	mov    0x40(%rsp),%rbp
    3ad6:	48 8b 85 98 00 00 00 	mov    0x98(%rbp),%rax
    3add:	4c 8b 65 28          	mov    0x28(%rbp),%r12
    3ae1:	48 85 c0             	test   %rax,%rax
    3ae4:	74 1e                	je     3b04 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x10f4>
    3ae6:	4d 85 e4             	test   %r12,%r12
    3ae9:	75 19                	jne    3b04 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x10f4>
    3aeb:	8b 95 a4 00 00 00    	mov    0xa4(%rbp),%edx
    3af1:	8b b5 a0 00 00 00    	mov    0xa0(%rbp),%esi
    3af7:	48 8d 4a 18          	lea    0x18(%rdx),%rcx
    3afb:	48 39 ce             	cmp    %rcx,%rsi
    3afe:	0f 83 e7 00 00 00    	jae    3beb <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x11db>
    3b04:	48 8b 5d 30          	mov    0x30(%rbp),%rbx
    3b08:	49 8d 44 24 18       	lea    0x18(%r12),%rax
    3b0d:	c6 44 24 48 00       	movb   $0x0,0x48(%rsp)
    3b12:	48 39 c3             	cmp    %rax,%rbx
    3b15:	72 19                	jb     3b30 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1120>
    3b17:	4c 8b 6d 20          	mov    0x20(%rbp),%r13
    3b1b:	43 c7 44 25 00 7e 30 0d 0a 	movl   $0xa0d307e,0x0(%r13,%r12,1)
    3b24:	48 83 45 28 04       	addq   $0x4,0x28(%rbp)
    3b29:	e9 6b ff ff ff       	jmp    3a99 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1089>
    3b2e:	66 90                	xchg   %ax,%ax
    3b30:	48 01 db             	add    %rbx,%rbx
    3b33:	48 39 c3             	cmp    %rax,%rbx
    3b36:	72 f8                	jb     3b30 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1120>
    3b38:	48 89 df             	mov    %rbx,%rdi
    3b3b:	e8 00 00 00 00       	call   3b40 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1130>
    3b40:	4c 8b 75 20          	mov    0x20(%rbp),%r14
    3b44:	48 89 d9             	mov    %rbx,%rcx
    3b47:	4c 89 e2             	mov    %r12,%rdx
    3b4a:	48 89 c7             	mov    %rax,%rdi
    3b4d:	49 89 c5             	mov    %rax,%r13
    3b50:	4c 89 f6             	mov    %r14,%rsi
    3b53:	e8 00 00 00 00       	call   3b58 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1148>
    3b58:	48 8d 45 38          	lea    0x38(%rbp),%rax
    3b5c:	49 39 c6             	cmp    %rax,%r14
    3b5f:	74 08                	je     3b69 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1159>
    3b61:	4c 89 f7             	mov    %r14,%rdi
    3b64:	e8 00 00 00 00       	call   3b69 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1159>
    3b69:	4c 8b 65 28          	mov    0x28(%rbp),%r12
    3b6d:	4c 89 6d 20          	mov    %r13,0x20(%rbp)
    3b71:	48 89 5d 30          	mov    %rbx,0x30(%rbp)
    3b75:	eb a4                	jmp    3b1b <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x110b>
    3b77:	4c 01 4d 28          	add    %r9,0x28(%rbp)
    3b7b:	e9 12 f2 ff ff       	jmp    2d92 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x382>
    3b80:	48 89 de             	mov    %rbx,%rsi
    3b83:	4c 89 f7             	mov    %r14,%rdi
    3b86:	e8 00 00 00 00       	call   3b8b <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x117b>
    3b8b:	e9 44 f6 ff ff       	jmp    31d4 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x7c4>
    3b90:	48 89 de             	mov    %rbx,%rsi
    3b93:	4c 89 f7             	mov    %r14,%rdi
    3b96:	e8 00 00 00 00       	call   3b9b <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x118b>
    3b9b:	e9 74 f7 ff ff       	jmp    3314 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x904>
    3ba0:	4c 01 4d 28          	add    %r9,0x28(%rbp)
    3ba4:	e9 6b f7 ff ff       	jmp    3314 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x904>
    3ba9:	4c 01 4d 28          	add    %r9,0x28(%rbp)
    3bad:	e9 22 f6 ff ff       	jmp    31d4 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x7c4>
    3bb2:	49 01 c2             	add    %rax,%r10
    3bb5:	41 b8 01 00 00 00    	mov    $0x1,%r8d
    3bbb:	c6 44 24 48 01       	movb   $0x1,0x48(%rsp)
    3bc0:	e9 06 f0 ff ff       	jmp    2bcb <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1bb>
    3bc5:	49 01 c2             	add    %rax,%r10
    3bc8:	41 b8 01 00 00 00    	mov    $0x1,%r8d
    3bce:	c6 44 24 48 01       	movb   $0x1,0x48(%rsp)
    3bd3:	e9 af f6 ff ff       	jmp    3287 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x877>
    3bd8:	49 01 c2             	add    %rax,%r10
    3bdb:	41 b8 01 00 00 00    	mov    $0x1,%r8d
    3be1:	c6 44 24 48 01       	movb   $0x1,0x48(%rsp)
    3be6:	e9 4e f5 ff ff       	jmp    3139 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x729>
    3beb:	c7 04 10 7e 30 0d 0a 	movl   $0xa0d307e,(%rax,%rdx,1)
    3bf2:	83 85 a4 00 00 00 04 	addl   $0x4,0xa4(%rbp)
    3bf9:	e9 9b fe ff ff       	jmp    3a99 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1089>
    3bfe:	31 f6                	xor    %esi,%esi
    3c00:	4c 89 f7             	mov    %r14,%rdi
    3c03:	e8 00 00 00 00       	call   3c08 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x11f8>
    3c08:	e9 8c fe ff ff       	jmp    3a99 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1089>
    3c0d:	45 31 c0             	xor    %r8d,%r8d
    3c10:	e9 94 ef ff ff       	jmp    2ba9 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x199>
    3c15:	e8 00 00 00 00       	call   3c1a <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x120a>
    3c1a:	f3 0f 1e fa          	endbr64
    3c1e:	48 89 c3             	mov    %rax,%rbx
    3c21:	e9 00 00 00 00       	jmp    3c26 <_ZN8tomo_db012_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1216>

Disassembly of section .text._ZNSt6vectorIPKN8tomo_db015CommandMetadataESaIS3_EED2Ev:

Disassembly of section .text._ZN8tomo_db02Op4Sink6appendEPKcm:

Disassembly of section .text.unlikely:

Disassembly of section .text._ZN8tomo_db016reply_map_headerIRNS_2Op4SinkEEEvOT_mb:

Disassembly of section .text._ZN8tomo_db018reply_array_headerIRNS_2Op4SinkEEEvOT_m:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE9_M_mutateEmmPKcm:

Disassembly of section .text.startup:
