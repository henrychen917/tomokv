
build/cmdmeta/POST/src/cmd/cmdmeta.o:     file format elf64-x86-64


Disassembly of section .text:

00000000000000f0 <_ZN4tomo12_GLOBAL__N_111child_countERKNS_15CommandMetadataE>:
      f0:	41 57                	push   %r15
      f2:	41 56                	push   %r14
      f4:	41 55                	push   %r13
      f6:	41 54                	push   %r12
      f8:	55                   	push   %rbp
      f9:	53                   	push   %rbx
      fa:	48 83 ec 08          	sub    $0x8,%rsp
      fe:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
     103:	48 8d 05 00 00 00 00 	lea    0x0(%rip),%rax        # 10a <_ZN4tomo12_GLOBAL__N_111child_countERKNS_15CommandMetadataE+0x1a>
     10a:	48 29 c7             	sub    %rax,%rdi
     10d:	48 b8 ab aa aa aa aa aa aa aa 	movabs $0xaaaaaaaaaaaaaaab,%rax
     117:	48 c1 ff 04          	sar    $0x4,%rdi
     11b:	48 0f af f8          	imul   %rax,%rdi
     11f:	48 8d 05 00 00 00 00 	lea    0x0(%rip),%rax        # 126 <_ZN4tomo12_GLOBAL__N_111child_countERKNS_15CommandMetadataE+0x36>
     126:	44 0f b7 6c b8 02    	movzwl 0x2(%rax,%rdi,4),%r13d
     12c:	48 83 c4 08          	add    $0x8,%rsp
     130:	44 89 e8             	mov    %r13d,%eax
     133:	5b                   	pop    %rbx
     134:	5d                   	pop    %rbp
     135:	41 5c                	pop    %r12
     137:	41 5d                	pop    %r13
     139:	41 5e                	pop    %r14
     13b:	41 5f                	pop    %r15
     13d:	c3                   	ret
     13e:	4c 8b 37             	mov    (%rdi),%r14
     141:	48 8d 1d 00 00 00 00 	lea    0x0(%rip),%rbx        # 148 <_ZN4tomo12_GLOBAL__N_111child_countERKNS_15CommandMetadataE+0x58>
     148:	45 31 ed             	xor    %r13d,%r13d
     14b:	4c 8d bb f0 3f 00 00 	lea    0x3ff0(%rbx),%r15
     152:	4c 89 f7             	mov    %r14,%rdi
     155:	e8 00 00 00 00       	call   15a <_ZN4tomo12_GLOBAL__N_111child_countERKNS_15CommandMetadataE+0x6a>
     15a:	49 89 c4             	mov    %rax,%r12
     15d:	0f 1f 00             	nopl   (%rax)
     160:	48 8b 2b             	mov    (%rbx),%rbp
     163:	4c 89 e2             	mov    %r12,%rdx
     166:	4c 89 f6             	mov    %r14,%rsi
     169:	48 89 ef             	mov    %rbp,%rdi
     16c:	e8 00 00 00 00       	call   171 <_ZN4tomo12_GLOBAL__N_111child_countERKNS_15CommandMetadataE+0x81>
     171:	85 c0                	test   %eax,%eax
     173:	75 0b                	jne    180 <_ZN4tomo12_GLOBAL__N_111child_countERKNS_15CommandMetadataE+0x90>
     175:	42 80 7c 25 00 7c    	cmpb   $0x7c,0x0(%rbp,%r12,1)
     17b:	75 03                	jne    180 <_ZN4tomo12_GLOBAL__N_111child_countERKNS_15CommandMetadataE+0x90>
     17d:	41 ff c5             	inc    %r13d
     180:	48 83 c3 30          	add    $0x30,%rbx
     184:	49 39 df             	cmp    %rbx,%r15
     187:	75 d7                	jne    160 <_ZN4tomo12_GLOBAL__N_111child_countERKNS_15CommandMetadataE+0x70>
     189:	eb a1                	jmp    12c <_ZN4tomo12_GLOBAL__N_111child_countERKNS_15CommandMetadataE+0x3c>

Disassembly of section .text._ZNSt6vectorIPKN4tomo15CommandMetadataESaIS3_EED2Ev:

Disassembly of section .text._ZN4tomo2Op4Sink6appendEPKcm:

Disassembly of section .text.unlikely:

Disassembly of section .text._ZN4tomo16reply_map_headerIRNS_2Op4SinkEEEvOT_mb:

Disassembly of section .text._ZN4tomo18reply_array_headerIRNS_2Op4SinkEEEvOT_m:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE9_M_mutateEmmPKcm:

Disassembly of section .text.startup:
