
build/ntfix3/query_guard.o:     file format elf64-x86-64


Disassembly of section .text:

0000000000000000 <ntfix3_query_guard>:
   0:	f3 0f 1e fa          	endbr64
   4:	b8 01 00 00 00       	mov    $0x1,%eax
   9:	48 39 d6             	cmp    %rdx,%rsi
   c:	72 13                	jb     21 <ntfix3_query_guard+0x21>
   e:	8b 4f 04             	mov    0x4(%rdi),%ecx
  11:	48 29 d6             	sub    %rdx,%rsi
  14:	31 c0                	xor    %eax,%eax
  16:	2b 4f 08             	sub    0x8(%rdi),%ecx
  19:	41 89 c8             	mov    %ecx,%r8d
  1c:	4c 39 c6             	cmp    %r8,%rsi
  1f:	72 0f                	jb     30 <ntfix3_query_guard+0x30>
  21:	c3                   	ret
  22:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
  2d:	0f 1f 00             	nopl   (%rax)
  30:	8b 47 4c             	mov    0x4c(%rdi),%eax
  33:	85 c0                	test   %eax,%eax
  35:	78 07                	js     3e <ntfix3_query_guard+0x3e>
  37:	4c 39 c6             	cmp    %r8,%rsi
  3a:	0f 92 c0             	setb   %al
  3d:	c3                   	ret
  3e:	41 89 c8             	mov    %ecx,%r8d
  41:	44 2b 47 74          	sub    0x74(%rdi),%r8d
  45:	eb f0                	jmp    37 <ntfix3_query_guard+0x37>
