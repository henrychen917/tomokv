# Complete-section disassembly, selected at existing instruction boundaries.
# tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*)
    3794:	4c 8b 95 40 f8 ff ff 	mov    -0x7c0(%rbp),%r10
    379b:	49 83 ba a8 00 00 00 00 	cmpq   $0x0,0xa8(%r10)
    37a3:	74 13                	je     37b8 <tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*)+0x37b8>
    37a5:	41 8b 82 b4 00 00 00 	mov    0xb4(%r10),%eax
    37ac:	83 e0 fb             	and    $0xfffffffb,%eax
    37af:	83 f8 fa             	cmp    $0xfffffffa,%eax
    37b2:	0f 84 33 0b 00 00    	je     42eb <tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*)+0x42eb>
    37b8:	41 8b 47 10          	mov    0x10(%r15),%eax
    37bc:	a9 10 08 00 00       	test   $0x810,%eax
    37c1:	0f 85 24 0b 00 00    	jne    42eb <tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*)+0x42eb>
    37c7:	81 bd 54 f7 ff ff 00 02 00 04 	cmpl   $0x4000200,-0x8ac(%rbp)
    37d1:	0f 84 71 0d 00 00    	je     4548 <tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*)+0x4548>
    37d7:	f6 c4 02             	test   $0x2,%ah
    37da:	0f 84 68 0d 00 00    	je     4548 <tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*)+0x4548>
    37e0:	48 8b bd d8 f7 ff ff 	mov    -0x828(%rbp),%rdi
    37e7:	e8 00 00 00 00       	call   37ec <tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*)+0x37ec>	37e8: R_X86_64_PLT32	tomo_db0::Rob<64u>::extend_current_read_local_owner()-0x4
    37ec:	c6 85 d0 f7 ff ff 05 	movb   $0x5,-0x830(%rbp)
    37f3:	e9 88 f6 ff ff       	jmp    2e80 <tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*)+0x2e80>
    37f8:	0f 1f 84 00 00 00 00 00 	nopl   0x0(%rax,%rax,1)
