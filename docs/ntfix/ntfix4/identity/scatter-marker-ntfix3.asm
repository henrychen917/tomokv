# Complete-section disassembly, selected at existing instruction boundaries.
# tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*)
    3794:	4c 8b 95 40 f8 ff ff 	mov    -0x7c0(%rbp),%r10
    379b:	49 83 ba a8 00 00 00 00 	cmpq   $0x0,0xa8(%r10)
    37a3:	74 0e                	je     37b3 <tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*)+0x37b3>
    37a5:	41 83 ba b4 00 00 00 fe 	cmpl   $0xfffffffe,0xb4(%r10)
    37ad:	0f 84 38 0b 00 00    	je     42eb <tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*)+0x42eb>
    37b3:	41 8b 47 10          	mov    0x10(%r15),%eax
    37b7:	a9 10 08 00 00       	test   $0x810,%eax
    37bc:	0f 85 29 0b 00 00    	jne    42eb <tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*)+0x42eb>
    37c2:	81 bd 54 f7 ff ff 00 02 00 04 	cmpl   $0x4000200,-0x8ac(%rbp)
    37cc:	0f 84 76 0d 00 00    	je     4548 <tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*)+0x4548>
    37d2:	f6 c4 02             	test   $0x2,%ah
    37d5:	0f 84 6d 0d 00 00    	je     4548 <tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*)+0x4548>
    37db:	48 8b bd d8 f7 ff ff 	mov    -0x828(%rbp),%rdi
    37e2:	e8 00 00 00 00       	call   37e7 <tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*)+0x37e7>	37e3: R_X86_64_PLT32	tomo_db0::Rob<64u>::extend_current_read_local_owner()-0x4
    37e7:	c6 85 d0 f7 ff ff 05 	movb   $0x5,-0x830(%rbp)
    37ee:	e9 8d f6 ff ff       	jmp    2e80 <tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*)+0x2e80>
    37f3:	66 66 2e 0f 1f 84 00 00 00 00 00 	data16 cs nopw 0x0(%rax,%rax,1)
    37fe:	66 90                	xchg   %ax,%ax
