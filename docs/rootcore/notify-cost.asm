
build/rootcore/notify-cost.o:     file format elf64-x86-64


Disassembly of section .text:

0000000000000000 <pre>:
   0:	endbr64
   4:	mov    %esi,%eax
   6:	mov    %esi,%ecx
   8:	xor    %edx,%edx
   a:	shr    $0x6,%eax
   d:	and    $0x1,%eax
  10:	and    $0x3f,%ecx
  13:	lea    (%rdi,%rax,8),%rax
  17:	mov    (%rax),%rdi
  1a:	bt     %rsi,%rdi
  1e:	jb     28 <pre+0x28>
  20:	lock bts %rcx,(%rax)
  25:	setae  %dl
  28:	mov    %edx,%eax
  2a:	ret
  2b:	nopl   0x0(%rax,%rax,1)

0000000000000030 <post>:
  30:	endbr64
  34:	mov    %esi,%eax
  36:	and    $0x3f,%esi
  39:	shr    $0x6,%eax
  3c:	and    $0x1,%eax
  3f:	lock bts %rsi,(%rdi,%rax,8)
  45:	setae  %al
  48:	ret
  49:	nopl   0x0(%rax)

0000000000000050 <fenced>:
  50:	endbr64
  54:	lock orq $0x0,(%rsp)
  5a:	mov    %esi,%eax
  5c:	mov    %esi,%ecx
  5e:	xor    %edx,%edx
  60:	shr    $0x6,%eax
  63:	and    $0x1,%eax
  66:	and    $0x3f,%ecx
  69:	lea    (%rdi,%rax,8),%rax
  6d:	mov    (%rax),%rdi
  70:	bt     %rsi,%rdi
  74:	jb     7e <fenced+0x2e>
  76:	lock bts %rcx,(%rax)
  7b:	setae  %dl
  7e:	mov    %edx,%eax
  80:	ret
