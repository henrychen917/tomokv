
build/cmdmeta/PRE/src/cmd/cmdmeta.o:     file format elf64-x86-64


Disassembly of section .text:

0000000000000600 <_ZN4tomo23command_metadata_lookupENS_5SliceE>:
     600:	f3 0f 1e fa          	endbr64
     604:	41 56                	push   %r14
     606:	41 55                	push   %r13
     608:	41 54                	push   %r12
     60a:	55                   	push   %rbp
     60b:	48 89 fd             	mov    %rdi,%rbp
     60e:	53                   	push   %rbx
     60f:	89 f3                	mov    %esi,%ebx
     611:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
     616:	83 fe 1d             	cmp    $0x1d,%esi
     619:	0f 87 e8 00 00 00    	ja     707 <_ZN4tomo23command_metadata_lookupENS_5SliceE+0x107>
     61f:	41 ba 05 00 00 00    	mov    $0x5,%r10d
     625:	41 bc 76 01 00 00    	mov    $0x176,%r12d
     62b:	45 31 db             	xor    %r11d,%r11d
     62e:	4c 8d 2d 00 00 00 00 	lea    0x0(%rip),%r13        # 635 <_ZN4tomo23command_metadata_lookupENS_5SliceE+0x35>
     635:	4c 8d 35 00 00 00 00 	lea    0x0(%rip),%r14        # 63c <_ZN4tomo23command_metadata_lookupENS_5SliceE+0x3c>
     63c:	0f 1f 40 00          	nopl   0x0(%rax)
     640:	4d 89 e1             	mov    %r12,%r9
     643:	89 df                	mov    %ebx,%edi
     645:	4d 29 d9             	sub    %r11,%r9
     648:	49 d1 e9             	shr    $1,%r9
     64b:	4d 01 d9             	add    %r11,%r9
     64e:	41 39 da             	cmp    %ebx,%r10d
     651:	41 0f 46 fa          	cmovbe %r10d,%edi
     655:	85 ff                	test   %edi,%edi
     657:	0f 84 c3 00 00 00    	je     720 <_ZN4tomo23command_metadata_lookupENS_5SliceE+0x120>
     65d:	4b 8d 04 49          	lea    (%r9,%r9,2),%rax
     661:	89 ff                	mov    %edi,%edi
     663:	31 d2                	xor    %edx,%edx
     665:	48 c1 e0 04          	shl    $0x4,%rax
     669:	4d 8b 44 05 00       	mov    0x0(%r13,%rax,1),%r8
     66e:	eb 0c                	jmp    67c <_ZN4tomo23command_metadata_lookupENS_5SliceE+0x7c>
     670:	48 ff c2             	inc    %rdx
     673:	48 39 d7             	cmp    %rdx,%rdi
     676:	0f 84 a4 00 00 00    	je     720 <_ZN4tomo23command_metadata_lookupENS_5SliceE+0x120>
     67c:	0f b6 44 15 00       	movzbl 0x0(%rbp,%rdx,1),%eax
     681:	8d 70 bf             	lea    -0x41(%rax),%esi
     684:	8d 48 20             	lea    0x20(%rax),%ecx
     687:	40 80 fe 1a          	cmp    $0x1a,%sil
     68b:	0f 42 c1             	cmovb  %ecx,%eax
     68e:	41 0f b6 0c 10       	movzbl (%r8,%rdx,1),%ecx
     693:	0f b6 c0             	movzbl %al,%eax
     696:	29 c8                	sub    %ecx,%eax
     698:	74 d6                	je     670 <_ZN4tomo23command_metadata_lookupENS_5SliceE+0x70>
     69a:	85 c0                	test   %eax,%eax
     69c:	0f 88 ae 00 00 00    	js     750 <_ZN4tomo23command_metadata_lookupENS_5SliceE+0x150>
     6a2:	4d 8d 59 01          	lea    0x1(%r9),%r11
     6a6:	4d 39 e3             	cmp    %r12,%r11
     6a9:	73 5c                	jae    707 <_ZN4tomo23command_metadata_lookupENS_5SliceE+0x107>
     6ab:	4c 89 e0             	mov    %r12,%rax
     6ae:	4c 29 d8             	sub    %r11,%rax
     6b1:	48 d1 e8             	shr    $1,%rax
     6b4:	4c 01 d8             	add    %r11,%rax
     6b7:	45 0f b7 14 86       	movzwl (%r14,%rax,4),%r10d
     6bc:	eb 82                	jmp    640 <_ZN4tomo23command_metadata_lookupENS_5SliceE+0x40>
     6be:	66 90                	xchg   %ax,%ax
     6c0:	4c 8d 25 00 00 00 00 	lea    0x0(%rip),%r12        # 6c7 <_ZN4tomo23command_metadata_lookupENS_5SliceE+0xc7>
     6c7:	4d 8d ac 24 20 46 00 00 	lea    0x4620(%r12),%r13
     6cf:	eb 18                	jmp    6e9 <_ZN4tomo23command_metadata_lookupENS_5SliceE+0xe9>
     6d1:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
     6dc:	0f 1f 40 00          	nopl   0x0(%rax)
     6e0:	49 83 c4 30          	add    $0x30,%r12
     6e4:	4d 39 e5             	cmp    %r12,%r13
     6e7:	74 1e                	je     707 <_ZN4tomo23command_metadata_lookupENS_5SliceE+0x107>
     6e9:	49 8b 14 24          	mov    (%r12),%rdx
     6ed:	89 de                	mov    %ebx,%esi
     6ef:	48 89 ef             	mov    %rbp,%rdi
     6f2:	e8 79 f9 ff ff       	call   70 <_ZN4tomo12_GLOBAL__N_117ascii_equal_icaseENS_5SliceEPKc.isra.0>
     6f7:	84 c0                	test   %al,%al
     6f9:	74 e5                	je     6e0 <_ZN4tomo23command_metadata_lookupENS_5SliceE+0xe0>
     6fb:	5b                   	pop    %rbx
     6fc:	4c 89 e0             	mov    %r12,%rax
     6ff:	5d                   	pop    %rbp
     700:	41 5c                	pop    %r12
     702:	41 5d                	pop    %r13
     704:	41 5e                	pop    %r14
     706:	c3                   	ret
     707:	45 31 e4             	xor    %r12d,%r12d
     70a:	5b                   	pop    %rbx
     70b:	5d                   	pop    %rbp
     70c:	4c 89 e0             	mov    %r12,%rax
     70f:	41 5c                	pop    %r12
     711:	41 5d                	pop    %r13
     713:	41 5e                	pop    %r14
     715:	c3                   	ret
     716:	66 2e 0f 1f 84 00 00 00 00 00 	cs nopw 0x0(%rax,%rax,1)
     720:	89 d8                	mov    %ebx,%eax
     722:	44 29 d0             	sub    %r10d,%eax
     725:	0f 85 6f ff ff ff    	jne    69a <_ZN4tomo23command_metadata_lookupENS_5SliceE+0x9a>
     72b:	4f 8d 24 49          	lea    (%r9,%r9,2),%r12
     72f:	48 8d 05 00 00 00 00 	lea    0x0(%rip),%rax        # 736 <_ZN4tomo23command_metadata_lookupENS_5SliceE+0x136>
     736:	5b                   	pop    %rbx
     737:	5d                   	pop    %rbp
     738:	49 c1 e4 04          	shl    $0x4,%r12
     73c:	49 01 c4             	add    %rax,%r12
     73f:	4c 89 e0             	mov    %r12,%rax
     742:	41 5c                	pop    %r12
     744:	41 5d                	pop    %r13
     746:	41 5e                	pop    %r14
     748:	c3                   	ret
     749:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
     750:	4d 89 cc             	mov    %r9,%r12
     753:	e9 4e ff ff ff       	jmp    6a6 <_ZN4tomo23command_metadata_lookupENS_5SliceE+0xa6>

Disassembly of section .text._ZNSt6vectorIPKN4tomo15CommandMetadataESaIS3_EED2Ev:

Disassembly of section .text._ZN4tomo2Op4Sink6appendEPKcm:

Disassembly of section .text.unlikely:

Disassembly of section .text._ZN4tomo16reply_map_headerIRNS_2Op4SinkEEEvOT_mb:

Disassembly of section .text._ZN4tomo18reply_array_headerIRNS_2Op4SinkEEEvOT_m:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE9_M_mutateEmmPKcm:

Disassembly of section .text.startup:
