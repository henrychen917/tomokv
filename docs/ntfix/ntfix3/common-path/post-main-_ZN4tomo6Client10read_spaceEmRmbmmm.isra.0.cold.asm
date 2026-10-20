000000000000019e <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0] [clone .cold]>:
     19e:	0f b6 ca             	movzbl %dl,%ecx
     1a1:	48 83 c4 28          	add    $0x28,%rsp
     1a5:	4c 89 fa             	mov    %r15,%rdx
     1a8:	4c 89 f6             	mov    %r14,%rsi
     1ab:	4c 89 e7             	mov    %r12,%rdi
     1ae:	5b                   	pop    %rbx
     1af:	5d                   	pop    %rbp
     1b0:	41 5c                	pop    %r12
     1b2:	41 5d                	pop    %r13
     1b4:	41 5e                	pop    %r14
     1b6:	41 5f                	pop    %r15
     1b8:	e9 00 00 00 00       	jmp    1bd <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0] [clone .cold]+0x1f>	1b9: R_X86_64_PLT32	tomo::Client::read_space_refined(unsigned long, unsigned long&, bool, unsigned long, unsigned long)-0x4
     1bd:	b9 01 00 00 00       	mov    $0x1,%ecx
     1c2:	eb dd                	jmp    1a1 <tomo::Client::read_space(unsigned long, unsigned long&, bool, unsigned long, unsigned long, unsigned long) [clone .isra.0] [clone .cold]+0x3>
