
build/cmdmeta/POST/src/cmd/cmdmeta.o:     file format elf64-x86-64


Disassembly of section .text:

0000000000000980 <_ZN4tomo19command_metadata_atEj>:
     980:	f3 0f 1e fa          	endbr64
     984:	31 c0                	xor    %eax,%eax
     986:	81 ff 54 01 00 00    	cmp    $0x154,%edi
     98c:	77 14                	ja     9a2 <_ZN4tomo19command_metadata_atEj+0x22>
     98e:	89 ff                	mov    %edi,%edi
     990:	48 8d 15 00 00 00 00 	lea    0x0(%rip),%rdx        # 997 <_ZN4tomo19command_metadata_atEj+0x17>
     997:	48 8d 04 7f          	lea    (%rdi,%rdi,2),%rax
     99b:	48 c1 e0 04          	shl    $0x4,%rax
     99f:	48 01 d0             	add    %rdx,%rax
     9a2:	c3                   	ret

Disassembly of section .text._ZNSt6vectorIPKN4tomo15CommandMetadataESaIS3_EED2Ev:

Disassembly of section .text._ZN4tomo2Op4Sink6appendEPKcm:

Disassembly of section .text.unlikely:

Disassembly of section .text._ZN4tomo16reply_map_headerIRNS_2Op4SinkEEEvOT_mb:

Disassembly of section .text._ZN4tomo18reply_array_headerIRNS_2Op4SinkEEEvOT_m:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE10_M_disposeEv:

Disassembly of section .text._ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE9_M_mutateEmmPKcm:

Disassembly of section .text.startup:
