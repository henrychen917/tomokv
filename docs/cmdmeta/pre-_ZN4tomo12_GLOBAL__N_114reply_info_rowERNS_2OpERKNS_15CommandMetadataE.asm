
build/cmdmeta/PRE/src/cmd/cmdmeta.o:     file format elf64-x86-64


Disassembly of section .text:

0000000000002a20 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE>:
    2a20:	41 57                	push   %r15
    2a22:	41 56                	push   %r14
    2a24:	41 55                	push   %r13
    2a26:	49 89 f7             	mov    %rsi,%r15
    2a29:	41 54                	push   %r12
    2a2b:	55                   	push   %rbp
    2a2c:	53                   	push   %rbx
    2a2d:	be 0a 00 00 00       	mov    $0xa,%esi
    2a32:	48 81 ec 98 00 00 00 	sub    $0x98,%rsp
    2a39:	4c 8d 74 24 40       	lea    0x40(%rsp),%r14
    2a3e:	48 89 7c 24 10       	mov    %rdi,0x10(%rsp)
    2a43:	64 48 8b 04 25 28 00 00 00 	mov    %fs:0x28,%rax
    2a4c:	48 89 84 24 88 00 00 00 	mov    %rax,0x88(%rsp)
    2a54:	31 c0                	xor    %eax,%eax
    2a56:	48 89 7c 24 40       	mov    %rdi,0x40(%rsp)
    2a5b:	c6 44 24 48 00       	movb   $0x0,0x48(%rsp)
    2a60:	4c 89 f7             	mov    %r14,%rdi
    2a63:	e8 00 00 00 00       	call   2a68 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x48>
    2a68:	49 8b 1f             	mov    (%r15),%rbx
    2a6b:	48 89 df             	mov    %rbx,%rdi
    2a6e:	e8 00 00 00 00       	call   2a73 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x53>
    2a73:	48 89 de             	mov    %rbx,%rsi
    2a76:	4c 89 f7             	mov    %r14,%rdi
    2a79:	89 c2                	mov    %eax,%edx
    2a7b:	e8 10 d7 ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    2a80:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    2a85:	41 0f bf 57 08       	movswl 0x8(%r15),%edx
    2a8a:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    2a8e:	74 30                	je     2ac0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xa0>
    2a90:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    2a94:	75 2a                	jne    2ac0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xa0>
    2a96:	44 8b a0 a4 00 00 00 	mov    0xa4(%rax),%r12d
    2a9d:	45 85 e4             	test   %r12d,%r12d
    2aa0:	75 1e                	jne    2ac0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xa0>
    2aa2:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    2aa7:	75 17                	jne    2ac0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xa0>
    2aa9:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    2aad:	89 90 bc 00 00 00    	mov    %edx,0xbc(%rax)
    2ab3:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    2abe:	eb 0c                	jmp    2acc <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xac>
    2ac0:	48 0f bf f2          	movswq %dx,%rsi
    2ac4:	4c 89 f7             	mov    %r14,%rdi
    2ac7:	e8 a4 d8 ff ff       	call   370 <_ZN4tomo9reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    2acc:	48 8b 44 24 10       	mov    0x10(%rsp),%rax
    2ad1:	49 8b 77 10          	mov    0x10(%r15),%rsi
    2ad5:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 2adc <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xbc>
    2adc:	b9 13 00 00 00       	mov    $0x13,%ecx
    2ae1:	4c 89 f7             	mov    %r14,%rdi
    2ae4:	0f b6 40 1c          	movzbl 0x1c(%rax),%eax
    2ae8:	41 89 c0             	mov    %eax,%r8d
    2aeb:	88 44 24 08          	mov    %al,0x8(%rsp)
    2aef:	41 c0 e8 02          	shr    $0x2,%r8b
    2af3:	41 83 e0 01          	and    $0x1,%r8d
    2af7:	e8 04 f4 ff ff       	call   1f00 <_ZN4tomo12_GLOBAL__N_116reply_string_setERNS_2Op4SinkEmPKPKcjb>
    2afc:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    2b01:	41 0f bf 57 18       	movswl 0x18(%r15),%edx
    2b06:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    2b0a:	0f 84 70 01 00 00    	je     2c80 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x260>
    2b10:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    2b14:	0f 85 66 01 00 00    	jne    2c80 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x260>
    2b1a:	8b a8 a4 00 00 00    	mov    0xa4(%rax),%ebp
    2b20:	85 ed                	test   %ebp,%ebp
    2b22:	0f 85 58 01 00 00    	jne    2c80 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x260>
    2b28:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    2b2d:	0f 85 4d 01 00 00    	jne    2c80 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x260>
    2b33:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    2b37:	49 0f bf 77 1a       	movswq 0x1a(%r15),%rsi
    2b3c:	89 90 bc 00 00 00    	mov    %edx,0xbc(%rax)
    2b42:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    2b4d:	4c 89 f7             	mov    %r14,%rdi
    2b50:	e8 1b d8 ff ff       	call   370 <_ZN4tomo9reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    2b55:	48 8b 6c 24 40       	mov    0x40(%rsp),%rbp
    2b5a:	49 0f bf 77 1c       	movswq 0x1c(%r15),%rsi
    2b5f:	80 7d 1e 00          	cmpb   $0x0,0x1e(%rbp)
    2b63:	0f 85 df 01 00 00    	jne    2d48 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x328>
    2b69:	4c 89 f7             	mov    %r14,%rdi
    2b6c:	e8 ff d7 ff ff       	call   370 <_ZN4tomo9reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    2b71:	48 8b 44 24 10       	mov    0x10(%rsp),%rax
    2b76:	f3 49 0f b8 5f 20    	popcnt 0x20(%r15),%rbx
    2b7c:	f6 40 1c 04          	testb  $0x4,0x1c(%rax)
    2b80:	0f 84 11 02 00 00    	je     2d97 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x377>
    2b86:	48 8b 6c 24 40       	mov    0x40(%rsp),%rbp
    2b8b:	4c 8b 95 98 00 00 00 	mov    0x98(%rbp),%r10
    2b92:	4c 8b 45 28          	mov    0x28(%rbp),%r8
    2b96:	4d 85 d2             	test   %r10,%r10
    2b99:	74 1e                	je     2bb9 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x199>
    2b9b:	4d 85 c0             	test   %r8,%r8
    2b9e:	75 19                	jne    2bb9 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x199>
    2ba0:	8b 85 a4 00 00 00    	mov    0xa4(%rbp),%eax
    2ba6:	8b 8d a0 00 00 00    	mov    0xa0(%rbp),%ecx
    2bac:	48 8d 50 18          	lea    0x18(%rax),%rdx
    2bb0:	48 39 d1             	cmp    %rdx,%rcx
    2bb3:	0f 83 09 10 00 00    	jae    3bc2 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x11a2>
    2bb9:	4c 8b 65 30          	mov    0x30(%rbp),%r12
    2bbd:	49 8d 40 18          	lea    0x18(%r8),%rax
    2bc1:	c6 44 24 48 00       	movb   $0x0,0x48(%rsp)
    2bc6:	49 39 c4             	cmp    %rax,%r12
    2bc9:	0f 82 21 01 00 00    	jb     2cf0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x2d0>
    2bcf:	4c 8b 6d 20          	mov    0x20(%rbp),%r13
    2bd3:	4f 8d 54 05 00       	lea    0x0(%r13,%r8,1),%r10
    2bd8:	45 31 c0             	xor    %r8d,%r8d
    2bdb:	4d 8d 4a 01          	lea    0x1(%r10),%r9
    2bdf:	48 8d 74 24 70       	lea    0x70(%rsp),%rsi
    2be4:	31 c9                	xor    %ecx,%ecx
    2be6:	49 bc cd cc cc cc cc cc cc cc 	movabs $0xcccccccccccccccd,%r12
    2bf0:	41 c6 02 7e          	movb   $0x7e,(%r10)
    2bf4:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    2bff:	90                   	nop
    2c00:	48 89 d8             	mov    %rbx,%rax
    2c03:	89 cf                	mov    %ecx,%edi
    2c05:	48 ff c6             	inc    %rsi
    2c08:	ff c1                	inc    %ecx
    2c0a:	49 f7 e4             	mul    %r12
    2c0d:	48 89 d8             	mov    %rbx,%rax
    2c10:	48 c1 ea 03          	shr    $0x3,%rdx
    2c14:	4c 8d 1c 92          	lea    (%rdx,%rdx,4),%r11
    2c18:	4d 01 db             	add    %r11,%r11
    2c1b:	4c 29 d8             	sub    %r11,%rax
    2c1e:	83 c0 30             	add    $0x30,%eax
    2c21:	88 46 ff             	mov    %al,-0x1(%rsi)
    2c24:	48 89 d8             	mov    %rbx,%rax
    2c27:	48 89 d3             	mov    %rdx,%rbx
    2c2a:	48 83 f8 09          	cmp    $0x9,%rax
    2c2e:	77 d0                	ja     2c00 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1e0>
    2c30:	4d 8d 1c 09          	lea    (%r9,%rcx,1),%r11
    2c34:	4c 89 c8             	mov    %r9,%rax
    2c37:	42 8d 34 0f          	lea    (%rdi,%r9,1),%esi
    2c3b:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    2c40:	89 f2                	mov    %esi,%edx
    2c42:	29 c2                	sub    %eax,%edx
    2c44:	48 ff c0             	inc    %rax
    2c47:	0f b6 54 14 70       	movzbl 0x70(%rsp,%rdx,1),%edx
    2c4c:	88 50 ff             	mov    %dl,-0x1(%rax)
    2c4f:	49 39 c3             	cmp    %rax,%r11
    2c52:	75 ec                	jne    2c40 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x220>
    2c54:	49 01 c9             	add    %rcx,%r9
    2c57:	66 41 c7 01 0d 0a    	movw   $0xa0d,(%r9)
    2c5d:	49 83 c1 02          	add    $0x2,%r9
    2c61:	4d 29 d1             	sub    %r10,%r9
    2c64:	45 84 c0             	test   %r8b,%r8b
    2c67:	0f 84 1a 0f 00 00    	je     3b87 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1167>
    2c6d:	44 01 8d a4 00 00 00 	add    %r9d,0xa4(%rbp)
    2c74:	e9 29 01 00 00       	jmp    2da2 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x382>
    2c79:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
    2c80:	48 0f bf f2          	movswq %dx,%rsi
    2c84:	4c 89 f7             	mov    %r14,%rdi
    2c87:	e8 e4 d6 ff ff       	call   370 <_ZN4tomo9reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    2c8c:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    2c91:	49 0f bf 77 1a       	movswq 0x1a(%r15),%rsi
    2c96:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    2c9a:	0f 84 ad fe ff ff    	je     2b4d <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x12d>
    2ca0:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    2ca4:	0f 85 a3 fe ff ff    	jne    2b4d <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x12d>
    2caa:	8b 98 a4 00 00 00    	mov    0xa4(%rax),%ebx
    2cb0:	85 db                	test   %ebx,%ebx
    2cb2:	0f 85 95 fe ff ff    	jne    2b4d <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x12d>
    2cb8:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    2cbd:	0f 85 8a fe ff ff    	jne    2b4d <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x12d>
    2cc3:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    2cc7:	89 b0 bc 00 00 00    	mov    %esi,0xbc(%rax)
    2ccd:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    2cd8:	49 0f bf 77 1c       	movswq 0x1c(%r15),%rsi
    2cdd:	e9 87 fe ff ff       	jmp    2b69 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x149>
    2ce2:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    2ced:	0f 1f 00             	nopl   (%rax)
    2cf0:	4d 01 e4             	add    %r12,%r12
    2cf3:	49 39 c4             	cmp    %rax,%r12
    2cf6:	72 f8                	jb     2cf0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x2d0>
    2cf8:	4c 89 e7             	mov    %r12,%rdi
    2cfb:	4c 89 44 24 08       	mov    %r8,0x8(%rsp)
    2d00:	e8 00 00 00 00       	call   2d05 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x2e5>
    2d05:	48 8b 75 20          	mov    0x20(%rbp),%rsi
    2d09:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
    2d0e:	4c 89 e1             	mov    %r12,%rcx
    2d11:	48 89 c7             	mov    %rax,%rdi
    2d14:	49 89 c5             	mov    %rax,%r13
    2d17:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
    2d1c:	e8 00 00 00 00       	call   2d21 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x301>
    2d21:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
    2d26:	48 8d 45 38          	lea    0x38(%rbp),%rax
    2d2a:	48 39 c6             	cmp    %rax,%rsi
    2d2d:	74 08                	je     2d37 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x317>
    2d2f:	48 89 f7             	mov    %rsi,%rdi
    2d32:	e8 00 00 00 00       	call   2d37 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x317>
    2d37:	4c 8b 45 28          	mov    0x28(%rbp),%r8
    2d3b:	4c 89 6d 20          	mov    %r13,0x20(%rbp)
    2d3f:	4c 89 65 30          	mov    %r12,0x30(%rbp)
    2d43:	e9 8b fe ff ff       	jmp    2bd3 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1b3>
    2d48:	80 7d 1d 00          	cmpb   $0x0,0x1d(%rbp)
    2d4c:	0f 85 17 fe ff ff    	jne    2b69 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x149>
    2d52:	44 8b 9d a4 00 00 00 	mov    0xa4(%rbp),%r11d
    2d59:	45 85 db             	test   %r11d,%r11d
    2d5c:	0f 85 07 fe ff ff    	jne    2b69 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x149>
    2d62:	48 83 7d 28 00       	cmpq   $0x0,0x28(%rbp)
    2d67:	0f 85 fc fd ff ff    	jne    2b69 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x149>
    2d6d:	48 8b 44 24 10       	mov    0x10(%rsp),%rax
    2d72:	c6 45 1d 09          	movb   $0x9,0x1d(%rbp)
    2d76:	89 b5 bc 00 00 00    	mov    %esi,0xbc(%rbp)
    2d7c:	48 c7 85 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rbp)
    2d87:	f3 49 0f b8 5f 20    	popcnt 0x20(%r15),%rbx
    2d8d:	f6 40 1c 04          	testb  $0x4,0x1c(%rax)
    2d91:	0f 85 86 0e 00 00    	jne    3c1d <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x11fd>
    2d97:	48 89 de             	mov    %rbx,%rsi
    2d9a:	4c 89 f7             	mov    %r14,%rdi
    2d9d:	e8 00 00 00 00       	call   2da2 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x382>
    2da2:	48 8d 44 24 50       	lea    0x50(%rsp),%rax
    2da7:	4c 8d 25 00 00 00 00 	lea    0x0(%rip),%r12        # 2dae <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x38e>
    2dae:	31 ed                	xor    %ebp,%ebp
    2db0:	48 89 44 24 38       	mov    %rax,0x38(%rsp)
    2db5:	e9 dc 00 00 00       	jmp    2e96 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x476>
    2dba:	66 0f 1f 44 00 00    	nopw   0x0(%rax,%rax,1)
    2dc0:	41 8b 88 a4 00 00 00 	mov    0xa4(%r8),%ecx
    2dc7:	41 8b b8 a0 00 00 00 	mov    0xa0(%r8),%edi
    2dce:	48 8d 71 01          	lea    0x1(%rcx),%rsi
    2dd2:	48 39 f7             	cmp    %rsi,%rdi
    2dd5:	0f 83 95 02 00 00    	jae    3070 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x650>
    2ddb:	49 8b 48 30          	mov    0x30(%r8),%rcx
    2ddf:	c6 44 24 48 00       	movb   $0x0,0x48(%rsp)
    2de4:	48 85 c9             	test   %rcx,%rcx
    2de7:	0f 84 53 01 00 00    	je     2f40 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x520>
    2ded:	49 8b 58 20          	mov    0x20(%r8),%rbx
    2df1:	c6 04 13 2b          	movb   $0x2b,(%rbx,%rdx,1)
    2df5:	49 ff 40 28          	incq   0x28(%r8)
    2df9:	4c 89 ef             	mov    %r13,%rdi
    2dfc:	e8 00 00 00 00       	call   2e01 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x3e1>
    2e01:	4c 89 ee             	mov    %r13,%rsi
    2e04:	4c 89 f7             	mov    %r14,%rdi
    2e07:	48 89 c2             	mov    %rax,%rdx
    2e0a:	e8 00 00 00 00       	call   2e0f <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x3ef>
    2e0f:	4c 8b 6c 24 40       	mov    0x40(%rsp),%r13
    2e14:	49 8b 85 98 00 00 00 	mov    0x98(%r13),%rax
    2e1b:	49 8b 55 28          	mov    0x28(%r13),%rdx
    2e1f:	48 85 c0             	test   %rax,%rax
    2e22:	74 20                	je     2e44 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x424>
    2e24:	48 85 d2             	test   %rdx,%rdx
    2e27:	75 1b                	jne    2e44 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x424>
    2e29:	41 8b 8d a4 00 00 00 	mov    0xa4(%r13),%ecx
    2e30:	41 8b bd a0 00 00 00 	mov    0xa0(%r13),%edi
    2e37:	48 8d 71 02          	lea    0x2(%rcx),%rsi
    2e3b:	48 39 f7             	cmp    %rsi,%rdi
    2e3e:	0f 83 0c 02 00 00    	jae    3050 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x630>
    2e44:	49 8b 5d 30          	mov    0x30(%r13),%rbx
    2e48:	48 8d 42 02          	lea    0x2(%rdx),%rax
    2e4c:	c6 44 24 48 00       	movb   $0x0,0x48(%rsp)
    2e51:	48 39 c3             	cmp    %rax,%rbx
    2e54:	0f 82 86 01 00 00    	jb     2fe0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x5c0>
    2e5a:	4d 8b 45 20          	mov    0x20(%r13),%r8
    2e5e:	66 41 c7 04 10 0d 0a 	movw   $0xa0d,(%r8,%rdx,1)
    2e65:	49 83 45 28 02       	addq   $0x2,0x28(%r13)
    2e6a:	48 8b 7c 24 50       	mov    0x50(%rsp),%rdi
    2e6f:	48 8b 44 24 08       	mov    0x8(%rsp),%rax
    2e74:	48 39 c7             	cmp    %rax,%rdi
    2e77:	74 0e                	je     2e87 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x467>
    2e79:	48 8b 44 24 60       	mov    0x60(%rsp),%rax
    2e7e:	48 8d 70 01          	lea    0x1(%rax),%rsi
    2e82:	e8 00 00 00 00       	call   2e87 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x467>
    2e87:	ff c5                	inc    %ebp
    2e89:	49 83 c4 10          	add    $0x10,%r12
    2e8d:	83 fd 15             	cmp    $0x15,%ebp
    2e90:	0f 84 4a 02 00 00    	je     30e0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x6c0>
    2e96:	c4 c2 d3 f7 5f 20    	shrx   %rbp,0x20(%r15),%rbx
    2e9c:	83 e3 01             	and    $0x1,%ebx
    2e9f:	74 e6                	je     2e87 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x467>
    2ea1:	49 8b 0c 24          	mov    (%r12),%rcx
    2ea5:	48 8d 44 24 60       	lea    0x60(%rsp),%rax
    2eaa:	48 c7 44 24 58 01 00 00 00 	movq   $0x1,0x58(%rsp)
    2eb3:	66 c7 44 24 60 40 00 	movw   $0x40,0x60(%rsp)
    2eba:	48 89 44 24 08       	mov    %rax,0x8(%rsp)
    2ebf:	48 89 44 24 50       	mov    %rax,0x50(%rsp)
    2ec4:	48 89 cf             	mov    %rcx,%rdi
    2ec7:	48 89 4c 24 18       	mov    %rcx,0x18(%rsp)
    2ecc:	e8 00 00 00 00       	call   2ed1 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x4b1>
    2ed1:	48 8b 4c 24 18       	mov    0x18(%rsp),%rcx
    2ed6:	4c 8d 68 01          	lea    0x1(%rax),%r13
    2eda:	49 83 fd 0f          	cmp    $0xf,%r13
    2ede:	0f 87 cc 01 00 00    	ja     30b0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x690>
    2ee4:	48 85 c0             	test   %rax,%rax
    2ee7:	0f 85 a3 01 00 00    	jne    3090 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x670>
    2eed:	48 8b 44 24 08       	mov    0x8(%rsp),%rax
    2ef2:	4c 8b 44 24 40       	mov    0x40(%rsp),%r8
    2ef7:	4c 89 6c 24 58       	mov    %r13,0x58(%rsp)
    2efc:	42 c6 04 28 00       	movb   $0x0,(%rax,%r13,1)
    2f01:	4c 8b 6c 24 50       	mov    0x50(%rsp),%r13
    2f06:	49 8b 80 98 00 00 00 	mov    0x98(%r8),%rax
    2f0d:	49 8b 50 28          	mov    0x28(%r8),%rdx
    2f11:	48 85 c0             	test   %rax,%rax
    2f14:	74 09                	je     2f1f <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x4ff>
    2f16:	48 85 d2             	test   %rdx,%rdx
    2f19:	0f 84 a1 fe ff ff    	je     2dc0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x3a0>
    2f1f:	49 8b 48 30          	mov    0x30(%r8),%rcx
    2f23:	48 8d 5a 01          	lea    0x1(%rdx),%rbx
    2f27:	c6 44 24 48 00       	movb   $0x0,0x48(%rsp)
    2f2c:	48 39 d9             	cmp    %rbx,%rcx
    2f2f:	0f 83 b8 fe ff ff    	jae    2ded <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x3cd>
    2f35:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    2f40:	48 01 c9             	add    %rcx,%rcx
    2f43:	48 39 d9             	cmp    %rbx,%rcx
    2f46:	72 f8                	jb     2f40 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x520>
    2f48:	48 89 cf             	mov    %rcx,%rdi
    2f4b:	48 89 54 24 30       	mov    %rdx,0x30(%rsp)
    2f50:	4c 89 44 24 20       	mov    %r8,0x20(%rsp)
    2f55:	48 89 4c 24 18       	mov    %rcx,0x18(%rsp)
    2f5a:	e8 00 00 00 00       	call   2f5f <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x53f>
    2f5f:	4c 8b 44 24 20       	mov    0x20(%rsp),%r8
    2f64:	48 8b 4c 24 18       	mov    0x18(%rsp),%rcx
    2f69:	48 8b 54 24 30       	mov    0x30(%rsp),%rdx
    2f6e:	48 89 c7             	mov    %rax,%rdi
    2f71:	48 89 c3             	mov    %rax,%rbx
    2f74:	49 8b 70 20          	mov    0x20(%r8),%rsi
    2f78:	4c 89 44 24 28       	mov    %r8,0x28(%rsp)
    2f7d:	48 89 4c 24 20       	mov    %rcx,0x20(%rsp)
    2f82:	48 89 74 24 18       	mov    %rsi,0x18(%rsp)
    2f87:	e8 00 00 00 00       	call   2f8c <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x56c>
    2f8c:	4c 8b 44 24 28       	mov    0x28(%rsp),%r8
    2f91:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
    2f96:	48 8b 4c 24 20       	mov    0x20(%rsp),%rcx
    2f9b:	49 8d 40 38          	lea    0x38(%r8),%rax
    2f9f:	48 39 c6             	cmp    %rax,%rsi
    2fa2:	74 1c                	je     2fc0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x5a0>
    2fa4:	48 89 f7             	mov    %rsi,%rdi
    2fa7:	4c 89 44 24 20       	mov    %r8,0x20(%rsp)
    2fac:	48 89 4c 24 18       	mov    %rcx,0x18(%rsp)
    2fb1:	e8 00 00 00 00       	call   2fb6 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x596>
    2fb6:	4c 8b 44 24 20       	mov    0x20(%rsp),%r8
    2fbb:	48 8b 4c 24 18       	mov    0x18(%rsp),%rcx
    2fc0:	49 8b 50 28          	mov    0x28(%r8),%rdx
    2fc4:	49 89 58 20          	mov    %rbx,0x20(%r8)
    2fc8:	49 89 48 30          	mov    %rcx,0x30(%r8)
    2fcc:	e9 20 fe ff ff       	jmp    2df1 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x3d1>
    2fd1:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    2fdc:	0f 1f 40 00          	nopl   0x0(%rax)
    2fe0:	48 01 db             	add    %rbx,%rbx
    2fe3:	48 39 c3             	cmp    %rax,%rbx
    2fe6:	72 f8                	jb     2fe0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x5c0>
    2fe8:	48 89 df             	mov    %rbx,%rdi
    2feb:	48 89 54 24 18       	mov    %rdx,0x18(%rsp)
    2ff0:	e8 00 00 00 00       	call   2ff5 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x5d5>
    2ff5:	49 8b 75 20          	mov    0x20(%r13),%rsi
    2ff9:	48 8b 54 24 18       	mov    0x18(%rsp),%rdx
    2ffe:	48 89 d9             	mov    %rbx,%rcx
    3001:	48 89 c7             	mov    %rax,%rdi
    3004:	48 89 74 24 18       	mov    %rsi,0x18(%rsp)
    3009:	e8 00 00 00 00       	call   300e <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x5ee>
    300e:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
    3013:	49 89 c0             	mov    %rax,%r8
    3016:	49 8d 45 38          	lea    0x38(%r13),%rax
    301a:	48 39 c6             	cmp    %rax,%rsi
    301d:	74 12                	je     3031 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x611>
    301f:	48 89 f7             	mov    %rsi,%rdi
    3022:	4c 89 44 24 18       	mov    %r8,0x18(%rsp)
    3027:	e8 00 00 00 00       	call   302c <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x60c>
    302c:	4c 8b 44 24 18       	mov    0x18(%rsp),%r8
    3031:	49 8b 55 28          	mov    0x28(%r13),%rdx
    3035:	4d 89 45 20          	mov    %r8,0x20(%r13)
    3039:	49 89 5d 30          	mov    %rbx,0x30(%r13)
    303d:	e9 1c fe ff ff       	jmp    2e5e <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x43e>
    3042:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    304d:	0f 1f 00             	nopl   (%rax)
    3050:	66 c7 04 08 0d 0a    	movw   $0xa0d,(%rax,%rcx,1)
    3056:	c6 44 24 48 01       	movb   $0x1,0x48(%rsp)
    305b:	41 83 85 a4 00 00 00 02 	addl   $0x2,0xa4(%r13)
    3063:	e9 02 fe ff ff       	jmp    2e6a <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x44a>
    3068:	0f 1f 84 00 00 00 00 00 	nopl   0x0(%rax,%rax,1)
    3070:	c6 04 08 2b          	movb   $0x2b,(%rax,%rcx,1)
    3074:	c6 44 24 48 01       	movb   $0x1,0x48(%rsp)
    3079:	41 ff 80 a4 00 00 00 	incl   0xa4(%r8)
    3080:	e9 74 fd ff ff       	jmp    2df9 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x3d9>
    3085:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    3090:	48 83 f8 01          	cmp    $0x1,%rax
    3094:	74 3a                	je     30d0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x6b0>
    3096:	48 8d 7c 24 61       	lea    0x61(%rsp),%rdi
    309b:	48 89 c2             	mov    %rax,%rdx
    309e:	48 89 ce             	mov    %rcx,%rsi
    30a1:	e8 00 00 00 00       	call   30a6 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x686>
    30a6:	e9 42 fe ff ff       	jmp    2eed <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x4cd>
    30ab:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    30b0:	48 8b 7c 24 38       	mov    0x38(%rsp),%rdi
    30b5:	49 89 c0             	mov    %rax,%r8
    30b8:	31 d2                	xor    %edx,%edx
    30ba:	be 01 00 00 00       	mov    $0x1,%esi
    30bf:	e8 00 00 00 00       	call   30c4 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x6a4>
    30c4:	48 8b 44 24 50       	mov    0x50(%rsp),%rax
    30c9:	e9 24 fe ff ff       	jmp    2ef2 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x4d2>
    30ce:	66 90                	xchg   %ax,%ax
    30d0:	0f b6 01             	movzbl (%rcx),%eax
    30d3:	88 44 24 61          	mov    %al,0x61(%rsp)
    30d7:	e9 11 fe ff ff       	jmp    2eed <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x4cd>
    30dc:	0f 1f 40 00          	nopl   0x0(%rax)
    30e0:	48 8b 44 24 10       	mov    0x10(%rsp),%rax
    30e5:	41 0f b6 5f 2a       	movzbl 0x2a(%r15),%ebx
    30ea:	f6 40 1c 04          	testb  $0x4,0x1c(%rax)
    30ee:	0f 84 9c 0a 00 00    	je     3b90 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1170>
    30f4:	48 8b 6c 24 40       	mov    0x40(%rsp),%rbp
    30f9:	4c 8b 95 98 00 00 00 	mov    0x98(%rbp),%r10
    3100:	48 8b 75 28          	mov    0x28(%rbp),%rsi
    3104:	4d 85 d2             	test   %r10,%r10
    3107:	74 1e                	je     3127 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x707>
    3109:	48 85 f6             	test   %rsi,%rsi
    310c:	75 19                	jne    3127 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x707>
    310e:	8b 85 a4 00 00 00    	mov    0xa4(%rbp),%eax
    3114:	8b 8d a0 00 00 00    	mov    0xa0(%rbp),%ecx
    311a:	48 8d 50 18          	lea    0x18(%rax),%rdx
    311e:	48 39 d1             	cmp    %rdx,%rcx
    3121:	0f 83 c1 0a 00 00    	jae    3be8 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x11c8>
    3127:	4c 8b 65 30          	mov    0x30(%rbp),%r12
    312b:	48 8d 46 18          	lea    0x18(%rsi),%rax
    312f:	c6 44 24 48 00       	movb   $0x0,0x48(%rsp)
    3134:	49 39 c4             	cmp    %rax,%r12
    3137:	0f 82 b3 05 00 00    	jb     36f0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xcd0>
    313d:	4c 8b 6d 20          	mov    0x20(%rbp),%r13
    3141:	4d 8d 54 35 00       	lea    0x0(%r13,%rsi,1),%r10
    3146:	45 31 c0             	xor    %r8d,%r8d
    3149:	4d 8d 4a 01          	lea    0x1(%r10),%r9
    314d:	48 8d 74 24 70       	lea    0x70(%rsp),%rsi
    3152:	31 c9                	xor    %ecx,%ecx
    3154:	49 bc cd cc cc cc cc cc cc cc 	movabs $0xcccccccccccccccd,%r12
    315e:	41 c6 02 7e          	movb   $0x7e,(%r10)
    3162:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    316d:	0f 1f 00             	nopl   (%rax)
    3170:	48 89 d8             	mov    %rbx,%rax
    3173:	89 cf                	mov    %ecx,%edi
    3175:	48 ff c6             	inc    %rsi
    3178:	ff c1                	inc    %ecx
    317a:	49 f7 e4             	mul    %r12
    317d:	48 89 d8             	mov    %rbx,%rax
    3180:	48 c1 ea 03          	shr    $0x3,%rdx
    3184:	4c 8d 1c 92          	lea    (%rdx,%rdx,4),%r11
    3188:	4d 01 db             	add    %r11,%r11
    318b:	4c 29 d8             	sub    %r11,%rax
    318e:	83 c0 30             	add    $0x30,%eax
    3191:	88 46 ff             	mov    %al,-0x1(%rsi)
    3194:	48 89 d8             	mov    %rbx,%rax
    3197:	48 89 d3             	mov    %rdx,%rbx
    319a:	48 83 f8 09          	cmp    $0x9,%rax
    319e:	77 d0                	ja     3170 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x750>
    31a0:	4d 8d 1c 09          	lea    (%r9,%rcx,1),%r11
    31a4:	4c 89 c8             	mov    %r9,%rax
    31a7:	42 8d 34 0f          	lea    (%rdi,%r9,1),%esi
    31ab:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    31b0:	89 f2                	mov    %esi,%edx
    31b2:	29 c2                	sub    %eax,%edx
    31b4:	48 ff c0             	inc    %rax
    31b7:	0f b6 54 14 70       	movzbl 0x70(%rsp,%rdx,1),%edx
    31bc:	88 50 ff             	mov    %dl,-0x1(%rax)
    31bf:	49 39 c3             	cmp    %rax,%r11
    31c2:	75 ec                	jne    31b0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x790>
    31c4:	49 01 c9             	add    %rcx,%r9
    31c7:	66 41 c7 01 0d 0a    	movw   $0xa0d,(%r9)
    31cd:	49 83 c1 02          	add    $0x2,%r9
    31d1:	4d 29 d1             	sub    %r10,%r9
    31d4:	45 84 c0             	test   %r8b,%r8b
    31d7:	0f 84 dc 09 00 00    	je     3bb9 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1199>
    31dd:	44 01 8d a4 00 00 00 	add    %r9d,0xa4(%rbp)
    31e4:	31 db                	xor    %ebx,%ebx
    31e6:	41 80 7f 2a 00       	cmpb   $0x0,0x2a(%r15)
    31eb:	48 8d 2d 00 00 00 00 	lea    0x0(%rip),%rbp        # 31f2 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x7d2>
    31f2:	74 3a                	je     322e <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x80e>
    31f4:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    31ff:	90                   	nop
    3200:	41 0f b7 47 28       	movzwl 0x28(%r15),%eax
    3205:	01 d8                	add    %ebx,%eax
    3207:	ff c3                	inc    %ebx
    3209:	89 c0                	mov    %eax,%eax
    320b:	4c 8b 64 c5 00       	mov    0x0(%rbp,%rax,8),%r12
    3210:	4c 89 e7             	mov    %r12,%rdi
    3213:	e8 00 00 00 00       	call   3218 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x7f8>
    3218:	4c 89 e6             	mov    %r12,%rsi
    321b:	4c 89 f7             	mov    %r14,%rdi
    321e:	89 c2                	mov    %eax,%edx
    3220:	e8 6b cf ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3225:	41 0f b6 47 2a       	movzbl 0x2a(%r15),%eax
    322a:	39 c3                	cmp    %eax,%ebx
    322c:	72 d2                	jb     3200 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x7e0>
    322e:	48 8b 44 24 10       	mov    0x10(%rsp),%rax
    3233:	41 0f b6 5f 2e       	movzbl 0x2e(%r15),%ebx
    3238:	f6 40 1c 04          	testb  $0x4,0x1c(%rax)
    323c:	0f 84 5e 09 00 00    	je     3ba0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1180>
    3242:	48 8b 6c 24 40       	mov    0x40(%rsp),%rbp
    3247:	4c 8b 95 98 00 00 00 	mov    0x98(%rbp),%r10
    324e:	48 8b 75 28          	mov    0x28(%rbp),%rsi
    3252:	4d 85 d2             	test   %r10,%r10
    3255:	74 1e                	je     3275 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x855>
    3257:	48 85 f6             	test   %rsi,%rsi
    325a:	75 19                	jne    3275 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x855>
    325c:	8b 85 a4 00 00 00    	mov    0xa4(%rbp),%eax
    3262:	8b 8d a0 00 00 00    	mov    0xa0(%rbp),%ecx
    3268:	48 8d 50 18          	lea    0x18(%rax),%rdx
    326c:	48 39 d1             	cmp    %rdx,%rcx
    326f:	0f 83 60 09 00 00    	jae    3bd5 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x11b5>
    3275:	4c 8b 65 30          	mov    0x30(%rbp),%r12
    3279:	48 8d 46 18          	lea    0x18(%rsi),%rax
    327d:	c6 44 24 48 00       	movb   $0x0,0x48(%rsp)
    3282:	49 39 c4             	cmp    %rax,%r12
    3285:	0f 82 c5 04 00 00    	jb     3750 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd30>
    328b:	4c 8b 6d 20          	mov    0x20(%rbp),%r13
    328f:	4d 8d 54 35 00       	lea    0x0(%r13,%rsi,1),%r10
    3294:	45 31 c0             	xor    %r8d,%r8d
    3297:	4d 8d 4a 01          	lea    0x1(%r10),%r9
    329b:	48 8d 74 24 70       	lea    0x70(%rsp),%rsi
    32a0:	31 c9                	xor    %ecx,%ecx
    32a2:	49 bc cd cc cc cc cc cc cc cc 	movabs $0xcccccccccccccccd,%r12
    32ac:	41 c6 02 7e          	movb   $0x7e,(%r10)
    32b0:	48 89 d8             	mov    %rbx,%rax
    32b3:	89 cf                	mov    %ecx,%edi
    32b5:	48 ff c6             	inc    %rsi
    32b8:	ff c1                	inc    %ecx
    32ba:	49 f7 e4             	mul    %r12
    32bd:	48 89 d8             	mov    %rbx,%rax
    32c0:	48 c1 ea 03          	shr    $0x3,%rdx
    32c4:	4c 8d 1c 92          	lea    (%rdx,%rdx,4),%r11
    32c8:	4d 01 db             	add    %r11,%r11
    32cb:	4c 29 d8             	sub    %r11,%rax
    32ce:	83 c0 30             	add    $0x30,%eax
    32d1:	88 46 ff             	mov    %al,-0x1(%rsi)
    32d4:	48 89 d8             	mov    %rbx,%rax
    32d7:	48 89 d3             	mov    %rdx,%rbx
    32da:	48 83 f8 09          	cmp    $0x9,%rax
    32de:	77 d0                	ja     32b0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x890>
    32e0:	4d 8d 1c 09          	lea    (%r9,%rcx,1),%r11
    32e4:	4c 89 c8             	mov    %r9,%rax
    32e7:	42 8d 34 0f          	lea    (%rdi,%r9,1),%esi
    32eb:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    32f0:	89 f2                	mov    %esi,%edx
    32f2:	29 c2                	sub    %eax,%edx
    32f4:	48 ff c0             	inc    %rax
    32f7:	0f b6 54 14 70       	movzbl 0x70(%rsp,%rdx,1),%edx
    32fc:	88 50 ff             	mov    %dl,-0x1(%rax)
    32ff:	49 39 c3             	cmp    %rax,%r11
    3302:	75 ec                	jne    32f0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x8d0>
    3304:	49 01 c9             	add    %rcx,%r9
    3307:	66 41 c7 01 0d 0a    	movw   $0xa0d,(%r9)
    330d:	49 83 c1 02          	add    $0x2,%r9
    3311:	4d 29 d1             	sub    %r10,%r9
    3314:	45 84 c0             	test   %r8b,%r8b
    3317:	0f 84 93 08 00 00    	je     3bb0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1190>
    331d:	44 01 8d a4 00 00 00 	add    %r9d,0xa4(%rbp)
    3324:	31 c0                	xor    %eax,%eax
    3326:	41 80 7f 2e 00       	cmpb   $0x0,0x2e(%r15)
    332b:	4c 8d 25 00 00 00 00 	lea    0x0(%rip),%r12        # 3332 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x912>
    3332:	0f 84 fd 06 00 00    	je     3a35 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1015>
    3338:	41 89 c5             	mov    %eax,%r13d
    333b:	4c 89 7c 24 08       	mov    %r15,0x8(%rsp)
    3340:	e9 6d 02 00 00       	jmp    35b2 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xb92>
    3345:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    3350:	ba 05 00 00 00       	mov    $0x5,%edx
    3355:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 335c <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x93c>
    335c:	4c 89 f7             	mov    %r14,%rdi
    335f:	e8 2c ce ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3364:	ba 04 00 00 00       	mov    $0x4,%edx
    3369:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3370 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x950>
    3370:	4c 89 f7             	mov    %r14,%rdi
    3373:	e8 18 ce ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3378:	89 da                	mov    %ebx,%edx
    337a:	be 01 00 00 00       	mov    $0x1,%esi
    337f:	4c 89 f7             	mov    %r14,%rdi
    3382:	e8 00 00 00 00       	call   3387 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x967>
    3387:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 338e <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x96e>
    338e:	ba 05 00 00 00       	mov    $0x5,%edx
    3393:	4c 89 f7             	mov    %r14,%rdi
    3396:	e8 f5 cd ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    339b:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    33a0:	49 0f bf 77 0c       	movswq 0xc(%r15),%rsi
    33a5:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    33a9:	0f 84 14 06 00 00    	je     39c3 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfa3>
    33af:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    33b3:	0f 85 0a 06 00 00    	jne    39c3 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfa3>
    33b9:	44 8b 90 a4 00 00 00 	mov    0xa4(%rax),%r10d
    33c0:	45 85 d2             	test   %r10d,%r10d
    33c3:	0f 85 fa 05 00 00    	jne    39c3 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfa3>
    33c9:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    33ce:	0f 85 ef 05 00 00    	jne    39c3 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfa3>
    33d4:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    33d8:	89 b0 bc 00 00 00    	mov    %esi,0xbc(%rax)
    33de:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    33e9:	ba 09 00 00 00       	mov    $0x9,%edx
    33ee:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 33f5 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x9d5>
    33f5:	4c 89 f7             	mov    %r14,%rdi
    33f8:	e8 93 cd ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    33fd:	89 da                	mov    %ebx,%edx
    33ff:	be 02 00 00 00       	mov    $0x2,%esi
    3404:	4c 89 f7             	mov    %r14,%rdi
    3407:	e8 00 00 00 00       	call   340c <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x9ec>
    340c:	ba 04 00 00 00       	mov    $0x4,%edx
    3411:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3418 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x9f8>
    3418:	4c 89 f7             	mov    %r14,%rdi
    341b:	e8 70 cd ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3420:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    3425:	4d 8d 3c c4          	lea    (%r12,%rax,8),%r15
    3429:	41 0f b6 47 1a       	movzbl 0x1a(%r15),%eax
    342e:	84 c0                	test   %al,%al
    3430:	0f 85 7a 03 00 00    	jne    37b0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd90>
    3436:	ba 05 00 00 00       	mov    $0x5,%edx
    343b:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3442 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xa22>
    3442:	4c 89 f7             	mov    %r14,%rdi
    3445:	e8 46 cd ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    344a:	ba 04 00 00 00       	mov    $0x4,%edx
    344f:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3456 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xa36>
    3456:	4c 89 f7             	mov    %r14,%rdi
    3459:	e8 32 cd ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    345e:	89 da                	mov    %ebx,%edx
    3460:	be 03 00 00 00       	mov    $0x3,%esi
    3465:	4c 89 f7             	mov    %r14,%rdi
    3468:	e8 00 00 00 00       	call   346d <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xa4d>
    346d:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3474 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xa54>
    3474:	ba 07 00 00 00       	mov    $0x7,%edx
    3479:	4c 89 f7             	mov    %r14,%rdi
    347c:	e8 0f cd ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3481:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    3486:	49 0f bf 77 1c       	movswq 0x1c(%r15),%rsi
    348b:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    348f:	0f 84 6b 05 00 00    	je     3a00 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfe0>
    3495:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    3499:	0f 85 61 05 00 00    	jne    3a00 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfe0>
    349f:	44 8b 88 a4 00 00 00 	mov    0xa4(%rax),%r9d
    34a6:	45 85 c9             	test   %r9d,%r9d
    34a9:	0f 85 51 05 00 00    	jne    3a00 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfe0>
    34af:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    34b4:	0f 85 46 05 00 00    	jne    3a00 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfe0>
    34ba:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    34be:	89 b0 bc 00 00 00    	mov    %esi,0xbc(%rax)
    34c4:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    34cf:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 34d6 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xab6>
    34d6:	ba 07 00 00 00       	mov    $0x7,%edx
    34db:	4c 89 f7             	mov    %r14,%rdi
    34de:	e8 ad cc ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    34e3:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    34e8:	49 0f bf 74 c4 1e    	movswq 0x1e(%r12,%rax,8),%rsi
    34ee:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    34f3:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    34f7:	0f 84 f3 04 00 00    	je     39f0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfd0>
    34fd:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    3501:	0f 85 e9 04 00 00    	jne    39f0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfd0>
    3507:	44 8b 80 a4 00 00 00 	mov    0xa4(%rax),%r8d
    350e:	45 85 c0             	test   %r8d,%r8d
    3511:	0f 85 d9 04 00 00    	jne    39f0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfd0>
    3517:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    351c:	0f 85 ce 04 00 00    	jne    39f0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfd0>
    3522:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    3526:	89 b0 bc 00 00 00    	mov    %esi,0xbc(%rax)
    352c:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    3537:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 353e <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xb1e>
    353e:	ba 05 00 00 00       	mov    $0x5,%edx
    3543:	4c 89 f7             	mov    %r14,%rdi
    3546:	e8 45 cc ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    354b:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    3550:	49 0f bf 74 c4 20    	movswq 0x20(%r12,%rax,8),%rsi
    3556:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    355b:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    355f:	0f 84 b6 03 00 00    	je     391b <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xefb>
    3565:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    3569:	0f 85 ac 03 00 00    	jne    391b <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xefb>
    356f:	8b 90 a4 00 00 00    	mov    0xa4(%rax),%edx
    3575:	85 d2                	test   %edx,%edx
    3577:	0f 85 9e 03 00 00    	jne    391b <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xefb>
    357d:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    3582:	0f 85 93 03 00 00    	jne    391b <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xefb>
    3588:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    358c:	89 b0 bc 00 00 00    	mov    %esi,0xbc(%rax)
    3592:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    359d:	48 8b 44 24 08       	mov    0x8(%rsp),%rax
    35a2:	41 ff c5             	inc    %r13d
    35a5:	0f b6 40 2e          	movzbl 0x2e(%rax),%eax
    35a9:	41 39 c5             	cmp    %eax,%r13d
    35ac:	0f 83 7e 04 00 00    	jae    3a30 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1010>
    35b2:	48 8b 44 24 08       	mov    0x8(%rsp),%rax
    35b7:	48 8b 4c 24 10       	mov    0x10(%rsp),%rcx
    35bc:	0f b7 40 2c          	movzwl 0x2c(%rax),%eax
    35c0:	0f b6 49 1c          	movzbl 0x1c(%rcx),%ecx
    35c4:	44 01 e8             	add    %r13d,%eax
    35c7:	89 cb                	mov    %ecx,%ebx
    35c9:	88 4c 24 18          	mov    %cl,0x18(%rsp)
    35cd:	48 8d 0d 00 00 00 00 	lea    0x0(%rip),%rcx        # 35d4 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xbb4>
    35d4:	89 c0                	mov    %eax,%eax
    35d6:	0f b6 2c 01          	movzbl (%rcx,%rax,1),%ebp
    35da:	c0 eb 02             	shr    $0x2,%bl
    35dd:	83 e3 01             	and    $0x1,%ebx
    35e0:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    35e5:	89 da                	mov    %ebx,%edx
    35e7:	4d 8b 3c c4          	mov    (%r12,%rax,8),%r15
    35eb:	4d 85 ff             	test   %r15,%r15
    35ee:	0f 84 dc 03 00 00    	je     39d0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfb0>
    35f4:	be 04 00 00 00       	mov    $0x4,%esi
    35f9:	4c 89 f7             	mov    %r14,%rdi
    35fc:	e8 00 00 00 00       	call   3601 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xbe1>
    3601:	ba 05 00 00 00       	mov    $0x5,%edx
    3606:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 360d <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xbed>
    360d:	4c 89 f7             	mov    %r14,%rdi
    3610:	e8 7b cb ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3615:	4c 89 ff             	mov    %r15,%rdi
    3618:	e8 00 00 00 00       	call   361d <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xbfd>
    361d:	4c 89 fe             	mov    %r15,%rsi
    3620:	4c 89 f7             	mov    %r14,%rdi
    3623:	89 c2                	mov    %eax,%edx
    3625:	e8 66 cb ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    362a:	ba 05 00 00 00       	mov    $0x5,%edx
    362f:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3636 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xc16>
    3636:	4c 89 f7             	mov    %r14,%rdi
    3639:	e8 52 cb ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    363e:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    3643:	41 89 d8             	mov    %ebx,%r8d
    3646:	b9 0a 00 00 00       	mov    $0xa,%ecx
    364b:	41 0f b7 74 c4 08    	movzwl 0x8(%r12,%rax,8),%esi
    3651:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 3658 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xc38>
    3658:	4c 89 f7             	mov    %r14,%rdi
    365b:	4d 8d 3c c4          	lea    (%r12,%rax,8),%r15
    365f:	e8 9c e8 ff ff       	call   1f00 <_ZN4tomo12_GLOBAL__N_116reply_string_setERNS_2Op4SinkEmPKPKcjb>
    3664:	ba 0c 00 00 00       	mov    $0xc,%edx
    3669:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3670 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xc50>
    3670:	4c 89 f7             	mov    %r14,%rdi
    3673:	e8 18 cb ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3678:	89 da                	mov    %ebx,%edx
    367a:	be 02 00 00 00       	mov    $0x2,%esi
    367f:	4c 89 f7             	mov    %r14,%rdi
    3682:	e8 00 00 00 00       	call   3687 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xc67>
    3687:	ba 04 00 00 00       	mov    $0x4,%edx
    368c:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3693 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xc73>
    3693:	4c 89 f7             	mov    %r14,%rdi
    3696:	e8 f5 ca ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    369b:	41 0f b6 47 0a       	movzbl 0xa(%r15),%eax
    36a0:	84 c0                	test   %al,%al
    36a2:	0f 84 a8 fc ff ff    	je     3350 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x930>
    36a8:	3c 01                	cmp    $0x1,%al
    36aa:	0f 84 80 02 00 00    	je     3930 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xf10>
    36b0:	4c 89 f7             	mov    %r14,%rdi
    36b3:	ba 07 00 00 00       	mov    $0x7,%edx
    36b8:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 36bf <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xc9f>
    36bf:	e8 cc ca ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    36c4:	4c 89 f7             	mov    %r14,%rdi
    36c7:	ba 04 00 00 00       	mov    $0x4,%edx
    36cc:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 36d3 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xcb3>
    36d3:	e8 b8 ca ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    36d8:	89 da                	mov    %ebx,%edx
    36da:	31 f6                	xor    %esi,%esi
    36dc:	4c 89 f7             	mov    %r14,%rdi
    36df:	e8 00 00 00 00       	call   36e4 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xcc4>
    36e4:	e9 00 fd ff ff       	jmp    33e9 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x9c9>
    36e9:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
    36f0:	4d 01 e4             	add    %r12,%r12
    36f3:	49 39 c4             	cmp    %rax,%r12
    36f6:	72 f8                	jb     36f0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xcd0>
    36f8:	4c 89 e7             	mov    %r12,%rdi
    36fb:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
    3700:	e8 00 00 00 00       	call   3705 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xce5>
    3705:	4c 8b 45 20          	mov    0x20(%rbp),%r8
    3709:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
    370e:	4c 89 e1             	mov    %r12,%rcx
    3711:	48 89 c7             	mov    %rax,%rdi
    3714:	49 89 c5             	mov    %rax,%r13
    3717:	4c 89 c6             	mov    %r8,%rsi
    371a:	4c 89 44 24 08       	mov    %r8,0x8(%rsp)
    371f:	e8 00 00 00 00       	call   3724 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd04>
    3724:	4c 8b 44 24 08       	mov    0x8(%rsp),%r8
    3729:	48 8d 45 38          	lea    0x38(%rbp),%rax
    372d:	49 39 c0             	cmp    %rax,%r8
    3730:	74 08                	je     373a <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd1a>
    3732:	4c 89 c7             	mov    %r8,%rdi
    3735:	e8 00 00 00 00       	call   373a <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd1a>
    373a:	48 8b 75 28          	mov    0x28(%rbp),%rsi
    373e:	4c 89 6d 20          	mov    %r13,0x20(%rbp)
    3742:	4c 89 65 30          	mov    %r12,0x30(%rbp)
    3746:	e9 f6 f9 ff ff       	jmp    3141 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x721>
    374b:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    3750:	4d 01 e4             	add    %r12,%r12
    3753:	49 39 c4             	cmp    %rax,%r12
    3756:	72 f8                	jb     3750 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd30>
    3758:	4c 89 e7             	mov    %r12,%rdi
    375b:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
    3760:	e8 00 00 00 00       	call   3765 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd45>
    3765:	4c 8b 45 20          	mov    0x20(%rbp),%r8
    3769:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
    376e:	4c 89 e1             	mov    %r12,%rcx
    3771:	48 89 c7             	mov    %rax,%rdi
    3774:	49 89 c5             	mov    %rax,%r13
    3777:	4c 89 c6             	mov    %r8,%rsi
    377a:	4c 89 44 24 08       	mov    %r8,0x8(%rsp)
    377f:	e8 00 00 00 00       	call   3784 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd64>
    3784:	4c 8b 44 24 08       	mov    0x8(%rsp),%r8
    3789:	48 8d 45 38          	lea    0x38(%rbp),%rax
    378d:	49 39 c0             	cmp    %rax,%r8
    3790:	74 08                	je     379a <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd7a>
    3792:	4c 89 c7             	mov    %r8,%rdi
    3795:	e8 00 00 00 00       	call   379a <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xd7a>
    379a:	48 8b 75 28          	mov    0x28(%rbp),%rsi
    379e:	4c 89 6d 20          	mov    %r13,0x20(%rbp)
    37a2:	4c 89 65 30          	mov    %r12,0x30(%rbp)
    37a6:	e9 e4 fa ff ff       	jmp    328f <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x86f>
    37ab:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
    37b0:	3c 01                	cmp    $0x1,%al
    37b2:	74 3c                	je     37f0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xdd0>
    37b4:	4c 89 f7             	mov    %r14,%rdi
    37b7:	ba 07 00 00 00       	mov    $0x7,%edx
    37bc:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 37c3 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xda3>
    37c3:	e8 c8 c9 ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    37c8:	4c 89 f7             	mov    %r14,%rdi
    37cb:	ba 04 00 00 00       	mov    $0x4,%edx
    37d0:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 37d7 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xdb7>
    37d7:	e8 b4 c9 ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    37dc:	89 da                	mov    %ebx,%edx
    37de:	31 f6                	xor    %esi,%esi
    37e0:	4c 89 f7             	mov    %r14,%rdi
    37e3:	e8 00 00 00 00       	call   37e8 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xdc8>
    37e8:	e9 b0 fd ff ff       	jmp    359d <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xb7d>
    37ed:	0f 1f 00             	nopl   (%rax)
    37f0:	ba 06 00 00 00       	mov    $0x6,%edx
    37f5:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 37fc <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xddc>
    37fc:	4c 89 f7             	mov    %r14,%rdi
    37ff:	e8 8c c9 ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3804:	ba 04 00 00 00       	mov    $0x4,%edx
    3809:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3810 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xdf0>
    3810:	4c 89 f7             	mov    %r14,%rdi
    3813:	e8 78 c9 ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3818:	89 da                	mov    %ebx,%edx
    381a:	be 03 00 00 00       	mov    $0x3,%esi
    381f:	4c 89 f7             	mov    %r14,%rdi
    3822:	e8 00 00 00 00       	call   3827 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xe07>
    3827:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 382e <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xe0e>
    382e:	ba 09 00 00 00       	mov    $0x9,%edx
    3833:	4c 89 f7             	mov    %r14,%rdi
    3836:	e8 55 c9 ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    383b:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    3840:	49 0f bf 77 22       	movswq 0x22(%r15),%rsi
    3845:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    3849:	0f 84 d1 01 00 00    	je     3a20 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1000>
    384f:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    3853:	0f 85 c7 01 00 00    	jne    3a20 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1000>
    3859:	8b b8 a4 00 00 00    	mov    0xa4(%rax),%edi
    385f:	85 ff                	test   %edi,%edi
    3861:	0f 85 b9 01 00 00    	jne    3a20 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1000>
    3867:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    386c:	0f 85 ae 01 00 00    	jne    3a20 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1000>
    3872:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    3876:	89 b0 bc 00 00 00    	mov    %esi,0xbc(%rax)
    387c:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    3887:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 388e <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xe6e>
    388e:	ba 08 00 00 00       	mov    $0x8,%edx
    3893:	4c 89 f7             	mov    %r14,%rdi
    3896:	e8 f5 c8 ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    389b:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    38a0:	49 0f bf 74 c4 24    	movswq 0x24(%r12,%rax,8),%rsi
    38a6:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    38ab:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    38af:	0f 84 5b 01 00 00    	je     3a10 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xff0>
    38b5:	80 78 1d 00          	cmpb   $0x0,0x1d(%rax)
    38b9:	0f 85 51 01 00 00    	jne    3a10 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xff0>
    38bf:	8b 88 a4 00 00 00    	mov    0xa4(%rax),%ecx
    38c5:	85 c9                	test   %ecx,%ecx
    38c7:	0f 85 43 01 00 00    	jne    3a10 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xff0>
    38cd:	48 83 78 28 00       	cmpq   $0x0,0x28(%rax)
    38d2:	0f 85 38 01 00 00    	jne    3a10 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xff0>
    38d8:	c6 40 1d 09          	movb   $0x9,0x1d(%rax)
    38dc:	89 b0 bc 00 00 00    	mov    %esi,0xbc(%rax)
    38e2:	48 c7 80 98 00 00 00 00 00 00 00 	movq   $0x0,0x98(%rax)
    38ed:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 38f4 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xed4>
    38f4:	ba 07 00 00 00       	mov    $0x7,%edx
    38f9:	4c 89 f7             	mov    %r14,%rdi
    38fc:	e8 8f c8 ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3901:	48 8d 44 ad 00       	lea    0x0(%rbp,%rbp,4),%rax
    3906:	49 0f bf 74 c4 1e    	movswq 0x1e(%r12,%rax,8),%rsi
    390c:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    3911:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    3915:	0f 85 4a fc ff ff    	jne    3565 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xb45>
    391b:	4c 89 f7             	mov    %r14,%rdi
    391e:	e8 4d ca ff ff       	call   370 <_ZN4tomo9reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    3923:	e9 75 fc ff ff       	jmp    359d <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xb7d>
    3928:	0f 1f 84 00 00 00 00 00 	nopl   0x0(%rax,%rax,1)
    3930:	ba 07 00 00 00       	mov    $0x7,%edx
    3935:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 393c <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xf1c>
    393c:	4c 89 f7             	mov    %r14,%rdi
    393f:	e8 4c c8 ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3944:	ba 04 00 00 00       	mov    $0x4,%edx
    3949:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3950 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xf30>
    3950:	4c 89 f7             	mov    %r14,%rdi
    3953:	e8 38 c8 ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    3958:	89 da                	mov    %ebx,%edx
    395a:	be 02 00 00 00       	mov    $0x2,%esi
    395f:	4c 89 f7             	mov    %r14,%rdi
    3962:	e8 00 00 00 00       	call   3967 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xf47>
    3967:	ba 07 00 00 00       	mov    $0x7,%edx
    396c:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 3973 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xf53>
    3973:	4c 89 f7             	mov    %r14,%rdi
    3976:	e8 15 c8 ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    397b:	49 8b 77 10          	mov    0x10(%r15),%rsi
    397f:	48 89 f7             	mov    %rsi,%rdi
    3982:	48 89 74 24 18       	mov    %rsi,0x18(%rsp)
    3987:	e8 00 00 00 00       	call   398c <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xf6c>
    398c:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
    3991:	4c 89 f7             	mov    %r14,%rdi
    3994:	89 c2                	mov    %eax,%edx
    3996:	e8 f5 c7 ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    399b:	48 8d 35 00 00 00 00 	lea    0x0(%rip),%rsi        # 39a2 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xf82>
    39a2:	ba 09 00 00 00       	mov    $0x9,%edx
    39a7:	4c 89 f7             	mov    %r14,%rdi
    39aa:	e8 e1 c7 ff ff       	call   190 <_ZN4tomo10reply_bulkIRNS_2Op4SinkEEEvOT_NS_5SliceE.isra.0>
    39af:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
    39b4:	49 0f bf 77 18       	movswq 0x18(%r15),%rsi
    39b9:	80 78 1e 00          	cmpb   $0x0,0x1e(%rax)
    39bd:	0f 85 ec f9 ff ff    	jne    33af <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x98f>
    39c3:	4c 89 f7             	mov    %r14,%rdi
    39c6:	e8 a5 c9 ff ff       	call   370 <_ZN4tomo9reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    39cb:	e9 19 fa ff ff       	jmp    33e9 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x9c9>
    39d0:	be 03 00 00 00       	mov    $0x3,%esi
    39d5:	4c 89 f7             	mov    %r14,%rdi
    39d8:	e8 00 00 00 00       	call   39dd <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xfbd>
    39dd:	e9 48 fc ff ff       	jmp    362a <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xc0a>
    39e2:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    39ed:	0f 1f 00             	nopl   (%rax)
    39f0:	4c 89 f7             	mov    %r14,%rdi
    39f3:	e8 78 c9 ff ff       	call   370 <_ZN4tomo9reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    39f8:	e9 3a fb ff ff       	jmp    3537 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xb17>
    39fd:	0f 1f 00             	nopl   (%rax)
    3a00:	4c 89 f7             	mov    %r14,%rdi
    3a03:	e8 68 c9 ff ff       	call   370 <_ZN4tomo9reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    3a08:	e9 c2 fa ff ff       	jmp    34cf <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xaaf>
    3a0d:	0f 1f 00             	nopl   (%rax)
    3a10:	4c 89 f7             	mov    %r14,%rdi
    3a13:	e8 58 c9 ff ff       	call   370 <_ZN4tomo9reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    3a18:	e9 d0 fe ff ff       	jmp    38ed <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xecd>
    3a1d:	0f 1f 00             	nopl   (%rax)
    3a20:	4c 89 f7             	mov    %r14,%rdi
    3a23:	e8 48 c9 ff ff       	call   370 <_ZN4tomo9reply_intIRNS_2Op4SinkEEEvOT_x.part.0>
    3a28:	e9 5a fe ff ff       	jmp    3887 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0xe67>
    3a2d:	0f 1f 00             	nopl   (%rax)
    3a30:	4c 8b 7c 24 08       	mov    0x8(%rsp),%r15
    3a35:	4c 89 ff             	mov    %r15,%rdi
    3a38:	e8 b3 c6 ff ff       	call   f0 <_ZN4tomo12_GLOBAL__N_111child_countERKNS_15CommandMetadataE>
    3a3d:	85 c0                	test   %eax,%eax
    3a3f:	0f 84 8d 00 00 00    	je     3ad2 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x10b2>
    3a45:	89 c6                	mov    %eax,%esi
    3a47:	4c 89 f7             	mov    %r14,%rdi
    3a4a:	4c 8d 2d 00 00 00 00 	lea    0x0(%rip),%r13        # 3a51 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1031>
    3a51:	e8 00 00 00 00       	call   3a56 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1036>
    3a56:	4d 8d a5 20 46 00 00 	lea    0x4620(%r13),%r12
    3a5d:	0f 1f 00             	nopl   (%rax)
    3a60:	4d 8b 37             	mov    (%r15),%r14
    3a63:	49 8b 6d 00          	mov    0x0(%r13),%rbp
    3a67:	4c 89 f7             	mov    %r14,%rdi
    3a6a:	e8 00 00 00 00       	call   3a6f <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x104f>
    3a6f:	4c 89 f6             	mov    %r14,%rsi
    3a72:	48 89 ef             	mov    %rbp,%rdi
    3a75:	48 89 c2             	mov    %rax,%rdx
    3a78:	48 89 c3             	mov    %rax,%rbx
    3a7b:	e8 00 00 00 00       	call   3a80 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1060>
    3a80:	85 c0                	test   %eax,%eax
    3a82:	75 1c                	jne    3aa0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1080>
    3a84:	80 7c 1d 00 7c       	cmpb   $0x7c,0x0(%rbp,%rbx,1)
    3a89:	75 15                	jne    3aa0 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1080>
    3a8b:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
    3a90:	4c 89 ee             	mov    %r13,%rsi
    3a93:	e8 88 ef ff ff       	call   2a20 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE>
    3a98:	0f 1f 84 00 00 00 00 00 	nopl   0x0(%rax,%rax,1)
    3aa0:	49 83 c5 30          	add    $0x30,%r13
    3aa4:	4d 39 e5             	cmp    %r12,%r13
    3aa7:	75 b7                	jne    3a60 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1040>
    3aa9:	48 8b 84 24 88 00 00 00 	mov    0x88(%rsp),%rax
    3ab1:	64 48 2b 04 25 28 00 00 00 	sub    %fs:0x28,%rax
    3aba:	0f 85 65 01 00 00    	jne    3c25 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1205>
    3ac0:	48 81 c4 98 00 00 00 	add    $0x98,%rsp
    3ac7:	5b                   	pop    %rbx
    3ac8:	5d                   	pop    %rbp
    3ac9:	41 5c                	pop    %r12
    3acb:	41 5d                	pop    %r13
    3acd:	41 5e                	pop    %r14
    3acf:	41 5f                	pop    %r15
    3ad1:	c3                   	ret
    3ad2:	48 8b 44 24 10       	mov    0x10(%rsp),%rax
    3ad7:	f6 40 1c 04          	testb  $0x4,0x1c(%rax)
    3adb:	0f 84 2d 01 00 00    	je     3c0e <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x11ee>
    3ae1:	48 8b 6c 24 40       	mov    0x40(%rsp),%rbp
    3ae6:	48 8b 85 98 00 00 00 	mov    0x98(%rbp),%rax
    3aed:	4c 8b 65 28          	mov    0x28(%rbp),%r12
    3af1:	48 85 c0             	test   %rax,%rax
    3af4:	74 1e                	je     3b14 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x10f4>
    3af6:	4d 85 e4             	test   %r12,%r12
    3af9:	75 19                	jne    3b14 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x10f4>
    3afb:	8b 95 a4 00 00 00    	mov    0xa4(%rbp),%edx
    3b01:	8b b5 a0 00 00 00    	mov    0xa0(%rbp),%esi
    3b07:	48 8d 4a 18          	lea    0x18(%rdx),%rcx
    3b0b:	48 39 ce             	cmp    %rcx,%rsi
    3b0e:	0f 83 e7 00 00 00    	jae    3bfb <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x11db>
    3b14:	48 8b 5d 30          	mov    0x30(%rbp),%rbx
    3b18:	49 8d 44 24 18       	lea    0x18(%r12),%rax
    3b1d:	c6 44 24 48 00       	movb   $0x0,0x48(%rsp)
    3b22:	48 39 c3             	cmp    %rax,%rbx
    3b25:	72 19                	jb     3b40 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1120>
    3b27:	4c 8b 6d 20          	mov    0x20(%rbp),%r13
    3b2b:	43 c7 44 25 00 7e 30 0d 0a 	movl   $0xa0d307e,0x0(%r13,%r12,1)
    3b34:	48 83 45 28 04       	addq   $0x4,0x28(%rbp)
    3b39:	e9 6b ff ff ff       	jmp    3aa9 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1089>
    3b3e:	66 90                	xchg   %ax,%ax
    3b40:	48 01 db             	add    %rbx,%rbx
    3b43:	48 39 c3             	cmp    %rax,%rbx
    3b46:	72 f8                	jb     3b40 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1120>
    3b48:	48 89 df             	mov    %rbx,%rdi
    3b4b:	e8 00 00 00 00       	call   3b50 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1130>
    3b50:	4c 8b 75 20          	mov    0x20(%rbp),%r14
    3b54:	48 89 d9             	mov    %rbx,%rcx
    3b57:	4c 89 e2             	mov    %r12,%rdx
    3b5a:	48 89 c7             	mov    %rax,%rdi
    3b5d:	49 89 c5             	mov    %rax,%r13
    3b60:	4c 89 f6             	mov    %r14,%rsi
    3b63:	e8 00 00 00 00       	call   3b68 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1148>
    3b68:	48 8d 45 38          	lea    0x38(%rbp),%rax
    3b6c:	49 39 c6             	cmp    %rax,%r14
    3b6f:	74 08                	je     3b79 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1159>
    3b71:	4c 89 f7             	mov    %r14,%rdi
    3b74:	e8 00 00 00 00       	call   3b79 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1159>
    3b79:	4c 8b 65 28          	mov    0x28(%rbp),%r12
    3b7d:	4c 89 6d 20          	mov    %r13,0x20(%rbp)
    3b81:	48 89 5d 30          	mov    %rbx,0x30(%rbp)
    3b85:	eb a4                	jmp    3b2b <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x110b>
    3b87:	4c 01 4d 28          	add    %r9,0x28(%rbp)
    3b8b:	e9 12 f2 ff ff       	jmp    2da2 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x382>
    3b90:	48 89 de             	mov    %rbx,%rsi
    3b93:	4c 89 f7             	mov    %r14,%rdi
    3b96:	e8 00 00 00 00       	call   3b9b <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x117b>
    3b9b:	e9 44 f6 ff ff       	jmp    31e4 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x7c4>
    3ba0:	48 89 de             	mov    %rbx,%rsi
    3ba3:	4c 89 f7             	mov    %r14,%rdi
    3ba6:	e8 00 00 00 00       	call   3bab <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x118b>
    3bab:	e9 74 f7 ff ff       	jmp    3324 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x904>
    3bb0:	4c 01 4d 28          	add    %r9,0x28(%rbp)
    3bb4:	e9 6b f7 ff ff       	jmp    3324 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x904>
    3bb9:	4c 01 4d 28          	add    %r9,0x28(%rbp)
    3bbd:	e9 22 f6 ff ff       	jmp    31e4 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x7c4>
    3bc2:	49 01 c2             	add    %rax,%r10
    3bc5:	41 b8 01 00 00 00    	mov    $0x1,%r8d
    3bcb:	c6 44 24 48 01       	movb   $0x1,0x48(%rsp)
    3bd0:	e9 06 f0 ff ff       	jmp    2bdb <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1bb>
    3bd5:	49 01 c2             	add    %rax,%r10
    3bd8:	41 b8 01 00 00 00    	mov    $0x1,%r8d
    3bde:	c6 44 24 48 01       	movb   $0x1,0x48(%rsp)
    3be3:	e9 af f6 ff ff       	jmp    3297 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x877>
    3be8:	49 01 c2             	add    %rax,%r10
    3beb:	41 b8 01 00 00 00    	mov    $0x1,%r8d
    3bf1:	c6 44 24 48 01       	movb   $0x1,0x48(%rsp)
    3bf6:	e9 4e f5 ff ff       	jmp    3149 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x729>
    3bfb:	c7 04 10 7e 30 0d 0a 	movl   $0xa0d307e,(%rax,%rdx,1)
    3c02:	83 85 a4 00 00 00 04 	addl   $0x4,0xa4(%rbp)
    3c09:	e9 9b fe ff ff       	jmp    3aa9 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1089>
    3c0e:	31 f6                	xor    %esi,%esi
    3c10:	4c 89 f7             	mov    %r14,%rdi
    3c13:	e8 00 00 00 00       	call   3c18 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x11f8>
    3c18:	e9 8c fe ff ff       	jmp    3aa9 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1089>
    3c1d:	45 31 c0             	xor    %r8d,%r8d
    3c20:	e9 94 ef ff ff       	jmp    2bb9 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x199>
    3c25:	e8 00 00 00 00       	call   3c2a <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x120a>
    3c2a:	f3 0f 1e fa          	endbr64
    3c2e:	48 89 c3             	mov    %rax,%rbx
    3c31:	e9 00 00 00 00       	jmp    3c36 <_ZN4tomo12_GLOBAL__N_114reply_info_rowERNS_2OpERKNS_15CommandMetadataE+0x1216>

Disassembly of section .text._ZNSt6vectorIPKN4tomo15CommandMetadataESaIS3_EED2Ev:

Disassembly of section .text._ZN4tomo2Op4Sink6appendEPKcm:

Disassembly of section .text.unlikely:

Disassembly of section .text._ZN4tomo16reply_map_headerIRNS_2Op4SinkEEEvOT_mb:

Disassembly of section .text._ZN4tomo18reply_array_headerIRNS_2Op4SinkEEEvOT_m:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE9_M_mutateEmmPKcm:

Disassembly of section .text.startup:
