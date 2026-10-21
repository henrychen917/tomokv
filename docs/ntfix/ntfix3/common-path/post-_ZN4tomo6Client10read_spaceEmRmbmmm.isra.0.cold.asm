000000000000025c <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0] [clone .cold]>:
     25c:	0f b6 ca             	movzbl %dl,%ecx
     25f:	48 83 c4 28          	add    $0x28,%rsp
     263:	4c 89 fa             	mov    %r15,%rdx
     266:	4c 89 f6             	mov    %r14,%rsi
     269:	4c 89 e7             	mov    %r12,%rdi
     26c:	5b                   	pop    %rbx
     26d:	5d                   	pop    %rbp
     26e:	41 5c                	pop    %r12
     270:	41 5d                	pop    %r13
     272:	41 5e                	pop    %r14
     274:	41 5f                	pop    %r15
     276:	e9 00 00 00 00       	jmp    27b <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0] [clone .cold]+0x1f>	277: R_X86_64_PLT32	tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)-0x4
     27b:	b9 01 00 00 00       	mov    $0x1,%ecx
     280:	eb dd                	jmp    25f <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0] [clone .cold]+0x3>
