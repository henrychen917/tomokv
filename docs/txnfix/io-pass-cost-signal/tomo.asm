<_ZN4tomo22multi_owner_pass_entryERNS_6IoLoopE>:
   41e90:	endbr64
   41e94:	push   %rbp
   41e95:	push   %rbx
   41e96:	mov    %rdi,%rbx
   41e99:	add    $0x1978,%rdi
   41ea0:	sub    $0x8,%rsp
   41ea4:	call   41ea9 <_ZN4tomo22multi_owner_pass_entryERNS_6IoLoopE+0x19>
			41ea5: R_X86_64_PLT32	_ZN4tomo19multi_reap_deferredERSt6vectorIPNS_14MultiExecStateESaIS2_EE-0x4
   41ea9:	mov    %eax,%ebp
   41eab:	movzbl %fs:0x0,%eax
			41eb0: R_X86_64_TPOFF32	_ZN4tomo12_GLOBAL__N_118multi_retry_signalE
   41eb4:	test   %al,%al
   41eb6:	jne    41ec8 <_ZN4tomo22multi_owner_pass_entryERNS_6IoLoopE+0x38>
   41eb8:	mov    0x19a0(%rbx),%rax
   41ebf:	cmp    %rax,0x19c0(%rbx)
   41ec6:	je     41ed2 <_ZN4tomo22multi_owner_pass_entryERNS_6IoLoopE+0x42>
   41ec8:	mov    %rbx,%rdi
   41ecb:	call   41ed0 <_ZN4tomo22multi_owner_pass_entryERNS_6IoLoopE+0x40>
			41ecc: R_X86_64_PLT32	_ZN4tomo27multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE-0x4
   41ed0:	add    %eax,%ebp
   41ed2:	add    $0x8,%rsp
   41ed6:	mov    %ebp,%eax
   41ed8:	pop    %rbx
   41ed9:	pop    %rbp
   41eda:	ret
