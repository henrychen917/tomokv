<_ZN8tomo_db022multi_owner_pass_entryERNS_6IoLoopE>:
   42b40:	endbr64
   42b44:	push   %rbp
   42b45:	push   %rbx
   42b46:	mov    %rdi,%rbx
   42b49:	add    $0x1978,%rdi
   42b50:	sub    $0x8,%rsp
   42b54:	call   42b59 <_ZN8tomo_db022multi_owner_pass_entryERNS_6IoLoopE+0x19>
			42b55: R_X86_64_PLT32	_ZN8tomo_db019multi_reap_deferredERSt6vectorIPNS_14MultiExecStateESaIS2_EE-0x4
   42b59:	mov    %eax,%ebp
   42b5b:	movzbl %fs:0x0,%eax
			42b60: R_X86_64_TPOFF32	_ZN8tomo_db012_GLOBAL__N_118multi_retry_signalE
   42b64:	test   %al,%al
   42b66:	jne    42b78 <_ZN8tomo_db022multi_owner_pass_entryERNS_6IoLoopE+0x38>
   42b68:	mov    0x19a0(%rbx),%rax
   42b6f:	cmp    %rax,0x19c0(%rbx)
   42b76:	je     42b82 <_ZN8tomo_db022multi_owner_pass_entryERNS_6IoLoopE+0x42>
   42b78:	mov    %rbx,%rdi
   42b7b:	call   42b80 <_ZN8tomo_db022multi_owner_pass_entryERNS_6IoLoopE+0x40>
			42b7c: R_X86_64_PLT32	_ZN8tomo_db027multi_owner_pass_entry_implILb0EEEjRNS_6IoLoopE-0x4
   42b80:	add    %eax,%ebp
   42b82:	add    $0x8,%rsp
   42b86:	mov    %ebp,%eax
   42b88:	pop    %rbx
   42b89:	pop    %rbp
   42b8a:	ret
