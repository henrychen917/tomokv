
build/execfifo2/PRE:     file format elf64-x86-64


Disassembly of section .init:

Disassembly of section .plt:

Disassembly of section .plt.got:

Disassembly of section .plt.sec:

Disassembly of section .text:

00000000004bcea0 <_ZN4tomo9FlatStore15atomic_collapseEmm>:
  4bcea0:	endbr64
  4bcea4:	push   %r15
  4bcea6:	push   %r14
  4bcea8:	push   %r13
  4bceaa:	mov    %rdx,%rcx
  4bcead:	push   %r12
  4bceaf:	push   %rbp
  4bceb0:	push   %rbx
  4bceb1:	mov    %rdi,%rbp
  4bceb4:	sub    $0xa8,%rsp
  4bcebb:	mov    %fs:0x28,%rax
  4bcec4:	mov    %rax,0x98(%rsp)
  4bcecc:	xor    %eax,%eax
  4bcece:	movzbl 0xf0(%rdi),%eax
  4bced5:	mov    %al,0x38(%rsp)
  4bced9:	test   %al,%al
  4bcedb:	jne    4bd208 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x368>
  4bcee1:	mov    0xc8(%rdi),%rax
  4bcee8:	test   %rax,%rax
  4bceeb:	je     4bd190 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2f0>
  4bcef1:	mov    0x210(%rax),%edi
  4bcef7:	test   %edi,%edi
  4bcef9:	je     4bd190 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2f0>
  4bceff:	cmpb   $0x0,0x193(%rbp)
  4bcf06:	jne    4bd190 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2f0>
  4bcf0c:	mov    (%rax),%rax
  4bcf0f:	test   %rax,%rax
  4bcf12:	je     4bd190 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2f0>
  4bcf18:	xor    %r15d,%r15d
  4bcf1b:	jmp    4bcf59 <_ZN4tomo9FlatStore15atomic_collapseEmm+0xb9>
  4bcf1d:	nopl   (%rax)
  4bcf20:	movzbl (%rdi),%edi
  4bcf23:	mov    0x30(%rax),%rdx
  4bcf27:	test   %rdx,%rdx
  4bcf2a:	je     4bd1e0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x340>
  4bcf30:	mov    (%rdx),%rdx
  4bcf33:	cmp    $0xffffffffffffffff,%rdx
  4bcf37:	je     4bd1ee <_ZN4tomo9FlatStore15atomic_collapseEmm+0x34e>
  4bcf3d:	test   %dil,%dil
  4bcf40:	je     4bcf78 <_ZN4tomo9FlatStore15atomic_collapseEmm+0xd8>
  4bcf42:	mov    0x7c(%rax),%edx
  4bcf45:	add    %r15,%rdx
  4bcf48:	jb     4bd190 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2f0>
  4bcf4e:	mov    (%rax),%rax
  4bcf51:	mov    %rdx,%r15
  4bcf54:	test   %rax,%rax
  4bcf57:	je     4bcf90 <_ZN4tomo9FlatStore15atomic_collapseEmm+0xf0>
  4bcf59:	mov    0x30(%rax),%rdx
  4bcf5d:	test   %rdx,%rdx
  4bcf60:	je     4bd1c0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x320>
  4bcf66:	mov    0x40(%rax),%rdi
  4bcf6a:	test   %rdi,%rdi
  4bcf6d:	jne    4bcf20 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x80>
  4bcf6f:	mov    (%rdx),%rdx
  4bcf72:	cmp    $0xffffffffffffffff,%rdx
  4bcf76:	je     4bcf90 <_ZN4tomo9FlatStore15atomic_collapseEmm+0xf0>
  4bcf78:	test   %rdx,%rdx
  4bcf7b:	sete   %dil
  4bcf7f:	cmp    %rsi,%rdx
  4bcf82:	setae  %r8b
  4bcf86:	or     %r8b,%dil
  4bcf89:	jne    4bcf90 <_ZN4tomo9FlatStore15atomic_collapseEmm+0xf0>
  4bcf8b:	cmp    %rdx,%rcx
  4bcf8e:	jae    4bcf42 <_ZN4tomo9FlatStore15atomic_collapseEmm+0xa2>
  4bcf90:	mov    %rax,0x28(%rsp)
  4bcf95:	test   %r15,%r15
  4bcf98:	je     4bd190 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2f0>
  4bcf9e:	mov    0xc8(%rbp),%rdx
  4bcfa5:	mov    0x28(%rsp),%r8
  4bcfaa:	mov    (%rdx),%rax
  4bcfad:	cmp    %r8,%rax
  4bcfb0:	je     4bdc10 <tomo_multidb2_pad_381064+0x8bb>
  4bcfb6:	xor    %ecx,%ecx
  4bcfb8:	xor    %edi,%edi
  4bcfba:	jmp    4bcfd7 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x137>
  4bcfbc:	nopl   0x0(%rax)
  4bcfc0:	mov    (%rdx),%rcx
  4bcfc3:	mov    (%rax),%rax
  4bcfc6:	cmp    $0xffffffffffffffff,%rcx
  4bcfca:	cmove  %rdi,%rcx
  4bcfce:	cmp    %r8,%rax
  4bcfd1:	je     4bd244 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x3a4>
  4bcfd7:	mov    0x30(%rax),%rdx
  4bcfdb:	test   %rdx,%rdx
  4bcfde:	je     4bd005 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x165>
  4bcfe0:	mov    0x40(%rax),%rsi
  4bcfe4:	test   %rsi,%rsi
  4bcfe7:	je     4bd200 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x360>
  4bcfed:	movzbl (%rsi),%edx
  4bcff0:	test   %dl,%dl
  4bcff2:	jne    4bd5da <tomo_multidb2_pad_381064+0x285>
  4bcff8:	mov    0x30(%rax),%rdx
  4bcffc:	test   %rdx,%rdx
  4bcfff:	jne    4bd200 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x360>
  4bd005:	mov    0x58(%rax),%rdx
  4bd009:	cmp    $0xffffffffffffffff,%rdx
  4bd00d:	cmove  %rdi,%rdx
  4bd011:	cmp    %rcx,%rdx
  4bd014:	jb     4bd5da <tomo_multidb2_pad_381064+0x285>
  4bd01a:	mov    0x30(%rax),%rdx
  4bd01e:	test   %rdx,%rdx
  4bd021:	jne    4bcfc0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x120>
  4bd023:	mov    0x58(%rax),%rcx
  4bd027:	jmp    4bcfc3 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x123>
  4bd029:	nopl   0x0(%rax)
  4bd030:	mov    %r13,%rax
  4bd033:	mov    %r15,%r13
  4bd036:	mov    %rax,%r15
  4bd039:	cmpb   $0x0,0x89(%r15)
  4bd041:	jne    4bd55e <tomo_multidb2_pad_381064+0x209>
  4bd047:	mov    0x38(%r15),%rdx
  4bd04b:	test   %rdx,%rdx
  4bd04e:	je     4bd060 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x1c0>
  4bd050:	mov    0x48(%r15),%rsi
  4bd054:	test   %rsi,%rsi
  4bd057:	je     4bd05d <_ZN4tomo9FlatStore15atomic_collapseEmm+0x1bd>
  4bd059:	decl   (%rsi)
  4bd05b:	jne    4bd060 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x1c0>
  4bd05d:	lock decl (%rdx)
  4bd060:	mov    0xb0(%rbp),%rax
  4bd067:	test   %rax,%rax
  4bd06a:	je     4bd06f <_ZN4tomo9FlatStore15atomic_collapseEmm+0x1cf>
  4bd06c:	incq   (%rax)
  4bd06f:	mov    0xc8(%rbp),%rax
  4bd076:	decl   0x210(%rax)
  4bd07c:	cmpq   $0x0,0x28(%r15)
  4bd081:	je     4bd089 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x1e9>
  4bd083:	decb   0x526(%rax)
  4bd089:	mov    0x18(%r15),%rsi
  4bd08d:	mov    0x50(%r15),%rdx
  4bd091:	test   %rsi,%rsi
  4bd094:	je     4bd4ec <tomo_multidb2_pad_381064+0x197>
  4bd09a:	mov    0x10(%r15),%rdx
  4bd09e:	mov    %rdx,0x10(%rsi)
  4bd0a2:	test   %rdx,%rdx
  4bd0a5:	je     4bd4d0 <tomo_multidb2_pad_381064+0x17b>
  4bd0ab:	mov    0xc8(%rbp),%rax
  4bd0b2:	mov    %rsi,0x18(%rdx)
  4bd0b6:	movq   $0x0,0x18(%r15)
  4bd0be:	movq   $0x0,0x10(%r15)
  4bd0c6:	cmpb   $0x0,0x89(%r15)
  4bd0ce:	jne    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bd0d4:	mov    0x70(%r15),%rsi
  4bd0d8:	cmp    $0x8,%rsi
  4bd0dc:	jbe    4bd474 <tomo_multidb2_pad_381064+0x11f>
  4bd0e2:	cmp    $0x80,%rsi
  4bd0e9:	jbe    4bd549 <tomo_multidb2_pad_381064+0x1f4>
  4bd0ef:	lea    -0x1(%rsi),%rdx
  4bd0f3:	mov    $0x3d,%edi
  4bd0f8:	mov    $0x38,%r8d
  4bd0fe:	lzcnt  %rdx,%rdx
  4bd103:	sub    %edx,%edi
  4bd105:	sub    %edx,%r8d
  4bd108:	shrx   %rdi,%rsi,%rdi
  4bd10d:	lea    0x4(%rdi,%r8,4),%edx
  4bd112:	test   %rax,%rax
  4bd115:	je     4bd120 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x280>
  4bd117:	cmp    $0x2f,%edx
  4bd11a:	jbe    4bd47f <tomo_multidb2_pad_381064+0x12a>
  4bd120:	xor    %edx,%edx
  4bd122:	mov    %r15,%rdi
  4bd125:	call   2bf70 <sdallocx@plt>
  4bd12a:	cmp    %r13,0x28(%rsp)
  4bd12f:	jne    4bd270 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x3d0>
  4bd135:	mov    0x10(%rsp),%r15
  4bd13a:	mov    0xc8(%rbp),%rdx
  4bd141:	mov    0x28(%rsp),%rax
  4bd146:	mov    %rax,(%rdx)
  4bd149:	test   %rax,%rax
  4bd14c:	je     4be35c <tomo_multidb2_pad_381064+0x1007>
  4bd152:	movq   $0x0,0x8(%rax)
  4bd15a:	cmpq   $0x0,0x210(%rdx)
  4bd162:	jne    4bd174 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2d4>
  4bd164:	mov    0x88(%rbp),%rax
  4bd16b:	test   %rax,%rax
  4bd16e:	je     4bd174 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2d4>
  4bd170:	lock decq (%rax)
  4bd174:	mov    0xa8(%rbp),%rax
  4bd17b:	test   %rax,%rax
  4bd17e:	je     4bd183 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2e3>
  4bd180:	add    %r15,(%rax)
  4bd183:	movb   $0x1,0x38(%rsp)
  4bd188:	nopl   0x0(%rax,%rax,1)
  4bd190:	mov    0x98(%rsp),%rax
  4bd198:	sub    %fs:0x28,%rax
  4bd1a1:	jne    4bf7d2 <tomo_multidb2_pad_381064+0x247d>
  4bd1a7:	movzbl 0x38(%rsp),%eax
  4bd1ac:	add    $0xa8,%rsp
  4bd1b3:	pop    %rbx
  4bd1b4:	pop    %rbp
  4bd1b5:	pop    %r12
  4bd1b7:	pop    %r13
  4bd1b9:	pop    %r14
  4bd1bb:	pop    %r15
  4bd1bd:	ret
  4bd1be:	xchg   %ax,%ax
  4bd1c0:	mov    0x58(%rax),%rdx
  4bd1c4:	cmp    $0xffffffffffffffff,%rdx
  4bd1c8:	jne    4bcf78 <_ZN4tomo9FlatStore15atomic_collapseEmm+0xd8>
  4bd1ce:	jmp    4bcf90 <_ZN4tomo9FlatStore15atomic_collapseEmm+0xf0>
  4bd1d3:	data16 cs nopw 0x0(%rax,%rax,1)
  4bd1de:	xchg   %ax,%ax
  4bd1e0:	mov    0x58(%rax),%rdx
  4bd1e4:	cmp    $0xffffffffffffffff,%rdx
  4bd1e8:	jne    4bcf3d <_ZN4tomo9FlatStore15atomic_collapseEmm+0x9d>
  4bd1ee:	test   %dil,%dil
  4bd1f1:	jne    4bcf42 <_ZN4tomo9FlatStore15atomic_collapseEmm+0xa2>
  4bd1f7:	jmp    4bcf90 <_ZN4tomo9FlatStore15atomic_collapseEmm+0xf0>
  4bd1fc:	nopl   0x0(%rax)
  4bd200:	mov    (%rdx),%rdx
  4bd203:	jmp    4bd009 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x169>
  4bd208:	mov    0x98(%rsp),%rax
  4bd210:	sub    %fs:0x28,%rax
  4bd219:	jne    4bf7d2 <tomo_multidb2_pad_381064+0x247d>
  4bd21f:	add    $0xa8,%rsp
  4bd226:	pop    %rbx
  4bd227:	pop    %rbp
  4bd228:	pop    %r12
  4bd22a:	pop    %r13
  4bd22c:	pop    %r14
  4bd22e:	pop    %r15
  4bd230:	jmp    4ba2b0 <_ZN4tomo9FlatStore26atomic_collapse_read_localEmm>
  4bd235:	mov    0x0(%r13),%r13
  4bd239:	cmp    %r13,0x28(%rsp)
  4bd23e:	jne    4bd5f0 <tomo_multidb2_pad_381064+0x29b>
  4bd244:	mov    0xc8(%rbp),%rdx
  4bd24b:	mov    (%rdx),%rbx
  4bd24e:	add    %r15,0x528(%rdx)
  4bd255:	cmp    %rbx,0x28(%rsp)
  4bd25a:	je     4bd141 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2a1>
  4bd260:	mov    %rbx,%r13
  4bd263:	mov    %r15,0x10(%rsp)
  4bd268:	nopl   0x0(%rax,%rax,1)
  4bd270:	mov    %r13,%r15
  4bd273:	xor    %r14d,%r14d
  4bd276:	mov    0x0(%r13),%r13
  4bd27a:	mov    0x7c(%r15),%eax
  4bd27e:	test   %eax,%eax
  4bd280:	je     4bd039 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x199>
  4bd286:	mov    %r15,%rax
  4bd289:	mov    %r14,%rbx
  4bd28c:	mov    %r13,%r15
  4bd28f:	mov    %rax,%r13
  4bd292:	jmp    4bd32f <_ZN4tomo9FlatStore15atomic_collapseEmm+0x48f>
  4bd297:	nopw   0x0(%rax,%rax,1)
  4bd2a0:	lea    0x8(%rax,%r14,1),%r14
  4bd2a5:	cmp    $0x2,%cl
  4bd2a8:	ja     4bd430 <tomo_multidb2_pad_381064+0xdb>
  4bd2ae:	test   %cl,%cl
  4bd2b0:	je     4bd420 <tomo_multidb2_pad_381064+0xcb>
  4bd2b6:	add    $0x8,%r14
  4bd2ba:	cmp    $0x80,%r14
  4bd2c1:	jbe    4bd400 <tomo_multidb2_pad_381064+0xab>
  4bd2c7:	dec    %r14
  4bd2ca:	mov    $0x3d,%ecx
  4bd2cf:	lzcnt  %r14,%rax
  4bd2d4:	sub    %eax,%ecx
  4bd2d6:	mov    $0x1,%eax
  4bd2db:	shlx   %rcx,%rax,%rax
  4bd2e0:	add    %rax,%r14
  4bd2e3:	neg    %rax
  4bd2e6:	and    %rax,%r14
  4bd2e9:	mov    %r12,%rdi
  4bd2ec:	call   4814c0 <_ZN4tomo20kvobj_external_bytesILb0EEEmPKNS_5KvObjEPKv.isra.0>
  4bd2f1:	mov    0x0(%rbp),%rcx
  4bd2f5:	add    %r14,%rax
  4bd2f8:	mov    %rcx,%rsi
  4bd2fb:	sub    %rax,%rsi
  4bd2fe:	cmp    %rax,%rcx
  4bd301:	jb     4bd45e <tomo_multidb2_pad_381064+0x109>
  4bd307:	mov    %rsi,0x0(%rbp)
  4bd30b:	mov    %rbp,%rdi
  4bd30e:	mov    %r12,%rsi
  4bd311:	call   491ce0 <_ZN4tomo9FlatStore19retire_detached_objEPNS_5KvObjE>
  4bd316:	movq   $0x0,0x90(%r13,%rbx,8)
  4bd322:	inc    %rbx
  4bd325:	cmp    0x7c(%r13),%ebx
  4bd329:	jae    4bd030 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x190>
  4bd32f:	mov    0x90(%r13,%rbx,8),%r12
  4bd337:	test   %r12,%r12
  4bd33a:	je     4bd322 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x482>
  4bd33c:	movzbl 0x1(%r12),%ecx
  4bd342:	mov    0x4(%r12),%esi
  4bd347:	movzbl 0x2(%r12),%edi
  4bd34d:	movzbl 0x2(%r12),%eax
  4bd353:	test   $0x2,%al

00000000004bd355 <tomo_multidb2_pad_381064>:
  4bd355:	jne    4bd3c0 <tomo_multidb2_pad_381064+0x6b>
  4bd357:	movzbl 0x3(%r12),%eax
  4bd35d:	vmovd  %eax,%xmm0
  4bd361:	xor    %eax,%eax
  4bd363:	vpinsrd $0x1,%eax,%xmm0,%xmm3
  4bd369:	vmovq  %xmm3,%rax
  4bd36e:	cmp    $0xff,%rax
  4bd374:	mov    %rax,%r14
  4bd377:	sbb    %rax,%rax
  4bd37a:	mov    %r14d,%r14d
  4bd37d:	and    $0xfffffffffffffffc,%rax
  4bd381:	add    $0xc,%rax
  4bd385:	and    $0x1,%edi
  4bd388:	jne    4bd2a0 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x400>
  4bd38e:	add    %rax,%r14
  4bd391:	cmp    $0x2,%cl
  4bd394:	ja     4bd450 <tomo_multidb2_pad_381064+0xfb>
  4bd39a:	test   %cl,%cl
  4bd39c:	jne    4bd2b6 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x416>
  4bd3a2:	add    %rsi,%r14
  4bd3a5:	cmp    $0x8,%r14
  4bd3a9:	je     4bd2e9 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x449>
  4bd3af:	jmp    4bd2ba <_ZN4tomo9FlatStore15atomic_collapseEmm+0x41a>
  4bd3b4:	data16 cs nopw 0x0(%rax,%rax,1)
  4bd3bf:	nop
  4bd3c0:	movzbl 0x2(%r12),%r8d
  4bd3c6:	xor    %eax,%eax
  4bd3c8:	and    $0x2,%r8d
  4bd3cc:	je     4bd3d9 <tomo_multidb2_pad_381064+0x84>
  4bd3ce:	movzbl 0x3(%r12),%eax
  4bd3d4:	inc    %eax
  4bd3d6:	movzbl %al,%eax
  4bd3d9:	movzbl 0x2(%r12),%r8d
  4bd3df:	and    $0x2,%r8d
  4bd3e3:	jne    4bd410 <tomo_multidb2_pad_381064+0xbb>
  4bd3e5:	movzbl 0x3(%r12),%edx
  4bd3eb:	vmovd  %edx,%xmm0
  4bd3ef:	movzbl 0x2(%r12),%r8d
  4bd3f5:	movzbl 0x2(%r12),%r8d
  4bd3fb:	jmp    4bd363 <tomo_multidb2_pad_381064+0xe>
  4bd400:	add    $0xf,%r14
  4bd404:	and    $0xfffffffffffffff0,%r14
  4bd408:	jmp    4bd2e9 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x449>
  4bd40d:	nopl   (%rax)
  4bd410:	vmovd  0x8(%r12),%xmm0
  4bd417:	jmp    4bd3ef <tomo_multidb2_pad_381064+0x9a>
  4bd419:	nopl   0x0(%rax)
  4bd420:	add    %rsi,%r14
  4bd423:	jmp    4bd2ba <_ZN4tomo9FlatStore15atomic_collapseEmm+0x41a>
  4bd428:	nopl   0x0(%rax,%rax,1)
  4bd430:	mov    %esi,%eax
  4bd432:	add    %r14,%rax
  4bd435:	cmp    $0x3,%cl
  4bd438:	cmove  %rax,%r14
  4bd43c:	jmp    4bd2ba <_ZN4tomo9FlatStore15atomic_collapseEmm+0x41a>
  4bd441:	data16 cs nopw 0x0(%rax,%rax,1)
  4bd44c:	nopl   0x0(%rax)
  4bd450:	cmp    $0x3,%cl
  4bd453:	je     4bd3a2 <tomo_multidb2_pad_381064+0x4d>
  4bd459:	jmp    4bd3a5 <tomo_multidb2_pad_381064+0x50>
  4bd45e:	mov    0xc0(%rbp),%rax
  4bd465:	test   %rax,%rax
  4bd468:	je     4bd46d <tomo_multidb2_pad_381064+0x118>
  4bd46a:	incq   (%rax)
  4bd46d:	xor    %esi,%esi
  4bd46f:	jmp    4bd307 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x467>
  4bd474:	xor    %edx,%edx
  4bd476:	test   %rax,%rax
  4bd479:	je     4bd120 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x280>
  4bd47f:	mov    0x520(%rax),%edi
  4bd485:	cmp    $0xfff,%edi
  4bd48b:	ja     4bd120 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x280>
  4bd491:	mov    0x538(%rax),%r8
  4bd498:	add    %rsi,%r8
  4bd49b:	cmp    $0x400000,%r8
  4bd4a2:	ja     4bd120 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x280>
  4bd4a8:	mov    %edx,%edx
  4bd4aa:	inc    %edi
  4bd4ac:	add    $0x40,%rdx
  4bd4b0:	mov    0x20(%rax,%rdx,8),%rsi
  4bd4b5:	mov    %rsi,0x20(%r15)
  4bd4b9:	mov    %r15,0x20(%rax,%rdx,8)
  4bd4be:	mov    %edi,0x520(%rax)
  4bd4c4:	mov    %r8,0x538(%rax)
  4bd4cb:	jmp    4bd12a <_ZN4tomo9FlatStore15atomic_collapseEmm+0x28a>
  4bd4d0:	mov    0xc8(%rbp),%rax
  4bd4d7:	movq   $0x0,0x18(%r15)
  4bd4df:	movq   $0x0,0x10(%r15)
  4bd4e7:	jmp    4bd0c6 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x226>
  4bd4ec:	mov    %rdx,%rax
  4bd4ef:	mov    0xc8(%rbp),%rdi
  4bd4f6:	shr    $0x21,%rax
  4bd4fa:	xor    %rdx,%rax
  4bd4fd:	movabs $0xff51afd7ed558ccd,%rdx
  4bd507:	imul   %rdx,%rax
  4bd50b:	mov    %rax,%rdx
  4bd50e:	shr    $0x21,%rdx
  4bd512:	xor    %rdx,%rax
  4bd515:	movabs $0xc4ceb9fe1a85ec53,%rdx
  4bd51f:	imul   %rdx,%rax
  4bd523:	mov    %rax,%rdx
  4bd526:	shr    $0x21,%rdx
  4bd52a:	xor    %rdx,%rax
  4bd52d:	and    $0x3f,%eax
  4bd530:	cmp    %r15,0x10(%rdi,%rax,8)
  4bd535:	jne    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bd53b:	mov    0x10(%r15),%rdx
  4bd53f:	mov    %rdx,0x10(%rdi,%rax,8)
  4bd544:	jmp    4bd0a2 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x202>
  4bd549:	mov    %rsi,%rdx
  4bd54c:	shr    $0x4,%rdx
  4bd550:	test   %rax,%rax
  4bd553:	jne    4bd47f <tomo_multidb2_pad_381064+0x12a>
  4bd559:	jmp    4bd120 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x280>
  4bd55e:	mov    0xc8(%rbp),%r12
  4bd565:	test   %r12,%r12
  4bd568:	je     4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bd56e:	cmpb   $0x0,0x524(%r12)
  4bd577:	je     4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bd57d:	vmovq  %r15,%xmm7
  4bd582:	lea    0x80(%rsp),%rdx
  4bd58a:	lea    0x5c0(%r12),%rdi
  4bd592:	vpinsrq $0x1,%rbp,%xmm7,%xmm0
  4bd598:	vmovdqa %xmm0,0x80(%rsp)
  4bd5a1:	mov    0x80(%r15),%esi
  4bd5a8:	call   4a6060 <_ZN4tomo17ForeignReadSafety10close_spanIZNS_9FlatStore28read_local_pending_unpublishERNS_11AtomicEntryEEUljE_EEvjOT_>
  4bd5ad:	mov    0x584(%r12),%eax
  4bd5b5:	test   %eax,%eax
  4bd5b7:	je     4be820 <tomo_multidb2_pad_381064+0x14cb>
  4bd5bd:	dec    %eax
  4bd5bf:	mov    %eax,0x584(%r12)
  4bd5c7:	je     4bdbe1 <tomo_multidb2_pad_381064+0x88c>
  4bd5cd:	movb   $0x0,0x89(%r15)
  4bd5d5:	jmp    4bd047 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x1a7>
  4bd5da:	mov    0xc8(%rbp),%rdx
  4bd5e1:	mov    (%rdx),%r13
  4bd5e4:	cmp    %r13,0x28(%rsp)
  4bd5e9:	je     4bdc10 <tomo_multidb2_pad_381064+0x8bb>
  4bd5ef:	nop
  4bd5f0:	mov    0x30(%r13),%rax
  4bd5f4:	test   %rax,%rax
  4bd5f7:	je     4bd61e <tomo_multidb2_pad_381064+0x2c9>
  4bd5f9:	mov    0x40(%r13),%rdx
  4bd5fd:	test   %rdx,%rdx
  4bd600:	je     4bdb5e <tomo_multidb2_pad_381064+0x809>
  4bd606:	movzbl (%rdx),%eax
  4bd609:	test   %al,%al
  4bd60b:	jne    4bd821 <tomo_multidb2_pad_381064+0x4cc>
  4bd611:	mov    0x30(%r13),%rax
  4bd615:	test   %rax,%rax
  4bd618:	jne    4bdb5e <tomo_multidb2_pad_381064+0x809>
  4bd61e:	mov    0x58(%r13),%r12
  4bd622:	xor    %eax,%eax
  4bd624:	cmp    $0xffffffffffffffff,%r12
  4bd628:	cmove  %rax,%r12
  4bd62c:	mov    0xc8(%rbp),%rax
  4bd633:	mov    (%rax),%rbx
  4bd636:	cmp    %r13,%rbx
  4bd639:	je     4bd235 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x395>
  4bd63f:	mov    %rbx,%r14
  4bd642:	mov    %r12,%rbx
  4bd645:	jmp    4bd674 <tomo_multidb2_pad_381064+0x31f>
  4bd647:	nopw   0x0(%rax,%rax,1)
  4bd650:	mov    (%rax),%rax
  4bd653:	cmp    %rax,%rbx
  4bd656:	jae    4bd668 <tomo_multidb2_pad_381064+0x313>
  4bd658:	cmp    $0xffffffffffffffff,%rax
  4bd65c:	je     4bd668 <tomo_multidb2_pad_381064+0x313>
  4bd65e:	mov    0x68(%r14),%rax
  4bd662:	and    0x68(%r13),%rax
  4bd666:	jne    4bd690 <tomo_multidb2_pad_381064+0x33b>
  4bd668:	mov    (%r14),%r14
  4bd66b:	cmp    %r13,%r14
  4bd66e:	je     4bd235 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x395>
  4bd674:	mov    0x30(%r14),%rax
  4bd678:	test   %rax,%rax
  4bd67b:	jne    4bd650 <tomo_multidb2_pad_381064+0x2fb>
  4bd67d:	mov    0x58(%r14),%rax
  4bd681:	jmp    4bd653 <tomo_multidb2_pad_381064+0x2fe>
  4bd683:	data16 cs nopw 0x0(%rax,%rax,1)
  4bd68e:	xchg   %ax,%ax
  4bd690:	mov    0x7c(%r14),%edx
  4bd694:	test   %edx,%edx
  4bd696:	je     4bd668 <tomo_multidb2_pad_381064+0x313>
  4bd698:	xor    %r12d,%r12d
  4bd69b:	mov    %rbx,0x30(%rsp)
  4bd6a0:	mov    %r12,%r8
  4bd6a3:	mov    %r14,%r12
  4bd6a6:	jmp    4bd6ef <tomo_multidb2_pad_381064+0x39a>
  4bd6a8:	nopl   0x0(%rax,%rax,1)
  4bd6b0:	mov    %r8d,%esi
  4bd6b3:	add    0x78(%r12),%esi
  4bd6b8:	mov    %r8d,%r14d
  4bd6bb:	mov    %r8,0x10(%rsp)
  4bd6c0:	call   53cc70 <_ZN4tomo22xshard_atomic_key_hashEPKNS_12ScatterStateEj>
  4bd6c5:	mov    $0x1,%ecx
  4bd6ca:	mov    0x10(%rsp),%r8
  4bd6cf:	mov    %rax,%rbx
  4bd6d2:	shlx   %rax,%rcx,%rax
  4bd6d7:	and    0x68(%r13),%rax
  4bd6db:	jne    4bda60 <tomo_multidb2_pad_381064+0x70b>
  4bd6e1:	inc    %r8
  4bd6e4:	cmp    0x7c(%r12),%r8d
  4bd6e9:	jae    4bda48 <tomo_multidb2_pad_381064+0x6f3>
  4bd6ef:	mov    0x28(%r12),%rdi
  4bd6f4:	test   %rdi,%rdi
  4bd6f7:	jne    4bd6b0 <tomo_multidb2_pad_381064+0x35b>
  4bd6f9:	mov    0x60(%r12),%rbx
  4bd6fe:	mov    $0x1,%ecx
  4bd703:	mov    %ebx,%eax
  4bd705:	shlx   %rax,%rcx,%rax
  4bd70a:	and    0x68(%r13),%rax
  4bd70e:	je     4bd6e1 <tomo_multidb2_pad_381064+0x38c>
  4bd710:	mov    0x80(%r12),%edx
  4bd718:	vmovd  0x84(%r12),%xmm0
  4bd722:	movzbl 0x8b(%r12),%eax
  4bd72b:	lea    0x90(%r12,%rdx,8),%rdx
  4bd733:	mov    %rdx,(%rsp)
  4bd737:	vpinsrd $0x1,%eax,%xmm0,%xmm4
  4bd73d:	mov    0x7c(%r13),%eax
  4bd741:	vmovq  %xmm4,0x10(%rsp)
  4bd747:	test   %eax,%eax
  4bd749:	je     4bd6e1 <tomo_multidb2_pad_381064+0x38c>
  4bd74b:	xor    %r14d,%r14d
  4bd74e:	mov    %r12,0x18(%rsp)
  4bd753:	mov    %r8,0x20(%rsp)
  4bd758:	mov    %r14,%r12
  4bd75b:	mov    %rbx,%r14
  4bd75e:	jmp    4bd785 <tomo_multidb2_pad_381064+0x430>
  4bd760:	mov    0x78(%r13),%esi
  4bd764:	mov    %r12d,%ebx
  4bd767:	add    %r12d,%esi
  4bd76a:	call   53cc70 <_ZN4tomo22xshard_atomic_key_hashEPKNS_12ScatterStateEj>
  4bd76f:	cmp    %r14,%rax
  4bd772:	je     4bd9c0 <tomo_multidb2_pad_381064+0x66b>
  4bd778:	inc    %r12
  4bd77b:	cmp    0x7c(%r13),%r12d
  4bd77f:	jae    4bda30 <tomo_multidb2_pad_381064+0x6db>
  4bd785:	mov    0x28(%r13),%rdi
  4bd789:	test   %rdi,%rdi
  4bd78c:	jne    4bd760 <tomo_multidb2_pad_381064+0x40b>
  4bd78e:	cmp    %r14,0x60(%r13)
  4bd792:	jne    4bd778 <tomo_multidb2_pad_381064+0x423>
  4bd794:	mov    0x80(%r13),%esi
  4bd79b:	movzbl 0x8b(%r13),%edx
  4bd7a3:	mov    0x84(%r13),%eax
  4bd7aa:	lea    0x90(%r13,%rsi,8),%rdi
  4bd7b2:	mov    0x10(%rsp),%rcx
  4bd7b7:	vmovd  %eax,%xmm2
  4bd7bb:	vpinsrd $0x1,%edx,%xmm2,%xmm1
  4bd7c1:	vmovq  %xmm1,%rdx
  4bd7c6:	cmp    %rcx,%rdx
  4bd7c9:	jne    4bd778 <tomo_multidb2_pad_381064+0x423>
  4bd7cb:	cmp    $0x7,%eax
  4bd7ce:	jbe    4bdb66 <tomo_multidb2_pad_381064+0x811>
  4bd7d4:	mov    %eax,%esi
  4bd7d6:	cmp    $0x20,%eax
  4bd7d9:	ja     4bdb87 <tomo_multidb2_pad_381064+0x832>
  4bd7df:	mov    (%rsp),%rcx
  4bd7e3:	mov    -0x8(%rdi,%rsi,1),%rdx
  4bd7e8:	mov    (%rdi),%r8
  4bd7eb:	xor    -0x8(%rcx,%rsi,1),%rdx
  4bd7f0:	xor    (%rcx),%r8
  4bd7f3:	or     %r8,%rdx
  4bd7f6:	cmp    $0x10,%eax
  4bd7f9:	jbe    4bd813 <tomo_multidb2_pad_381064+0x4be>
  4bd7fb:	mov    -0x10(%rdi,%rsi,1),%rax
  4bd800:	xor    -0x10(%rcx,%rsi,1),%rax
  4bd805:	mov    0x8(%rdi),%rsi
  4bd809:	xor    0x8(%rcx),%rsi
  4bd80d:	or     %rsi,%rax
  4bd810:	or     %rax,%rdx
  4bd813:	test   %rdx,%rdx
  4bd816:	sete   %al
  4bd819:	test   %al,%al
  4bd81b:	je     4bd778 <tomo_multidb2_pad_381064+0x423>
  4bd821:	movabs $0x555555555555555,%rax
  4bd82b:	cmp    %r15,%rax
  4bd82e:	jb     4bd190 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2f0>
  4bd834:	mov    0x50(%rbp),%rdx
  4bd838:	cmp    0x58(%rbp),%rdx
  4bd83c:	je     4bd842 <tomo_multidb2_pad_381064+0x4ed>
  4bd83e:	mov    %rdx,0x58(%rbp)
  4bd842:	mov    0x60(%rbp),%rax
  4bd846:	movabs $0xaaaaaaaaaaaaaaab,%rcx
  4bd850:	sub    %rdx,%rax
  4bd853:	sar    $0x3,%rax
  4bd857:	imul   %rcx,%rax
  4bd85b:	cmp    %r15,%rax
  4bd85e:	jb     4beaa0 <tomo_multidb2_pad_381064+0x174b>
  4bd864:	mov    0xc8(%rbp),%rax
  4bd86b:	xor    %r10d,%r10d
  4bd86e:	mov    (%rax),%r12
  4bd871:	cmp    %r12,0x28(%rsp)
  4bd876:	je     4be15e <tomo_multidb2_pad_381064+0xe09>
  4bd87c:	mov    0x7c(%r12),%eax
  4bd881:	xor    %r8d,%r8d
  4bd884:	test   %eax,%eax
  4bd886:	jne    4bd985 <tomo_multidb2_pad_381064+0x630>
  4bd88c:	jmp    4be14f <tomo_multidb2_pad_381064+0xdfa>
  4bd891:	data16 cs nopw 0x0(%rax,%rax,1)
  4bd89c:	nopl   0x0(%rax)
  4bd8a0:	mov    %r8d,%esi
  4bd8a3:	add    0x78(%r12),%esi
  4bd8a8:	mov    %r8d,%ebx
  4bd8ab:	mov    %r10,(%rsp)
  4bd8af:	mov    %r8,0x10(%rsp)
  4bd8b4:	call   53cc70 <_ZN4tomo22xshard_atomic_key_hashEPKNS_12ScatterStateEj>
  4bd8b9:	mov    0x28(%r12),%rdi
  4bd8be:	mov    0x10(%rsp),%r8
  4bd8c3:	mov    (%rsp),%r10
  4bd8c7:	mov    %rax,%r13
  4bd8ca:	test   %rdi,%rdi
  4bd8cd:	je     4bd998 <tomo_multidb2_pad_381064+0x643>
  4bd8d3:	cmpb   $0x0,0x8a(%r12)
  4bd8dc:	je     4bdc40 <tomo_multidb2_pad_381064+0x8eb>
  4bd8e2:	cmp    0x7c(%r12),%ebx
  4bd8e7:	jae    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bd8ed:	mov    0x80(%r12),%esi
  4bd8f5:	lea    0x90(,%rsi,8),%rcx
  4bd8fd:	lea    (%r12,%rcx,1),%rax
  4bd901:	test   %ebx,%ebx
  4bd903:	jne    4bdc20 <tomo_multidb2_pad_381064+0x8cb>
  4bd909:	mov    (%rax),%eax
  4bd90b:	cmp    %eax,0x84(%r12)
  4bd913:	jb     4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bd919:	movzbl 0x8b(%r12),%edx
  4bd922:	lea    (%rcx,%rsi,4),%rsi
  4bd926:	sub    %ebx,%eax
  4bd928:	add    %rbx,%rsi
  4bd92b:	vmovd  %eax,%xmm0
  4bd92f:	add    %r12,%rsi
  4bd932:	mov    %r13d,%eax
  4bd935:	mov    $0x1,%r14d
  4bd93b:	vpinsrd $0x1,%edx,%xmm0,%xmm0
  4bd941:	shlx   %rax,%r14,%r14
  4bd946:	test   %r10,%r14
  4bd949:	jne    4bdd81 <tomo_multidb2_pad_381064+0xa2c>
  4bd94f:	mov    0x58(%rbp),%rbx
  4bd953:	mov    0x60(%rbp),%rdi
  4bd957:	cmp    %rdi,%rbx
  4bd95a:	je     4bdc6e <tomo_multidb2_pad_381064+0x919>
  4bd960:	vmovq  %xmm0,0x10(%rbx)
  4bd965:	mov    %r13,(%rbx)
  4bd968:	mov    %rsi,0x8(%rbx)
  4bd96c:	add    $0x18,%rbx
  4bd970:	mov    %rbx,0x58(%rbp)
  4bd974:	or     %r14,%r10
  4bd977:	inc    %r8
  4bd97a:	cmp    0x7c(%r12),%r8d
  4bd97f:	jae    4be14f <tomo_multidb2_pad_381064+0xdfa>
  4bd985:	mov    0x28(%r12),%rdi
  4bd98a:	test   %rdi,%rdi
  4bd98d:	jne    4bd8a0 <tomo_multidb2_pad_381064+0x54b>
  4bd993:	mov    0x60(%r12),%r13
  4bd998:	mov    0x80(%r12),%eax
  4bd9a0:	vmovd  0x84(%r12),%xmm0
  4bd9aa:	movzbl 0x8b(%r12),%edx
  4bd9b3:	lea    0x90(%r12,%rax,8),%rsi
  4bd9bb:	jmp    4bd932 <tomo_multidb2_pad_381064+0x5dd>
  4bd9c0:	mov    0x28(%r13),%rdi
  4bd9c4:	test   %rdi,%rdi
  4bd9c7:	je     4bd794 <tomo_multidb2_pad_381064+0x43f>
  4bd9cd:	cmpb   $0x0,0x8a(%r13)
  4bd9d5:	je     4bdaf0 <tomo_multidb2_pad_381064+0x79b>
  4bd9db:	cmp    0x7c(%r13),%ebx
  4bd9df:	jae    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bd9e5:	mov    0x80(%r13),%edi
  4bd9ec:	lea    0x90(,%rdi,8),%rsi
  4bd9f4:	lea    0x0(%r13,%rsi,1),%rax
  4bd9f9:	test   %ebx,%ebx
  4bd9fb:	jne    4bdad0 <tomo_multidb2_pad_381064+0x77b>
  4bda01:	mov    (%rax),%eax
  4bda03:	cmp    %eax,0x84(%r13)
  4bda0a:	jb     4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bda10:	lea    (%rsi,%rdi,4),%rdi
  4bda14:	movzbl 0x8b(%r13),%edx
  4bda1c:	sub    %ebx,%eax
  4bda1e:	add    %rbx,%rdi
  4bda21:	add    %r13,%rdi
  4bda24:	jmp    4bd7b2 <tomo_multidb2_pad_381064+0x45d>
  4bda29:	nopl   0x0(%rax)
  4bda30:	mov    0x20(%rsp),%r8
  4bda35:	mov    0x18(%rsp),%r12
  4bda3a:	inc    %r8
  4bda3d:	cmp    0x7c(%r12),%r8d
  4bda42:	jb     4bd6ef <tomo_multidb2_pad_381064+0x39a>
  4bda48:	mov    0x30(%rsp),%rbx
  4bda4d:	mov    %r12,%r14
  4bda50:	jmp    4bd668 <tomo_multidb2_pad_381064+0x313>
  4bda55:	data16 cs nopw 0x0(%rax,%rax,1)
  4bda60:	mov    0x28(%r12),%rdi
  4bda65:	test   %rdi,%rdi
  4bda68:	je     4bd710 <tomo_multidb2_pad_381064+0x3bb>
  4bda6e:	cmpb   $0x0,0x8a(%r12)
  4bda77:	je     4bdb30 <tomo_multidb2_pad_381064+0x7db>
  4bda7d:	cmp    0x7c(%r12),%r14d
  4bda82:	jae    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bda84:	mov    0x80(%r12),%ecx
  4bda8c:	lea    0x90(,%rcx,8),%rdx
  4bda94:	lea    (%r12,%rdx,1),%rax
  4bda98:	test   %r14d,%r14d
  4bda9b:	jne    4bdb10 <tomo_multidb2_pad_381064+0x7bb>
  4bda9d:	mov    (%rax),%esi
  4bda9f:	cmp    %esi,0x84(%r12)
  4bdaa7:	jb     4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bdaa9:	lea    (%rdx,%rcx,4),%rdx
  4bdaad:	sub    %r14d,%esi
  4bdab0:	movzbl 0x8b(%r12),%eax
  4bdab9:	add    %rdx,%r14
  4bdabc:	vmovd  %esi,%xmm0
  4bdac0:	lea    (%r12,%r14,1),%rdx
  4bdac4:	mov    %rdx,(%rsp)
  4bdac8:	jmp    4bd737 <tomo_multidb2_pad_381064+0x3e2>
  4bdacd:	nopl   (%rax)
  4bdad0:	lea    -0x1(%rbx),%edx
  4bdad3:	mov    (%rax,%rdx,4),%ebx
  4bdad6:	mov    (%rax,%r12,4),%eax
  4bdada:	cmp    %ebx,%eax
  4bdadc:	jae    4bda03 <tomo_multidb2_pad_381064+0x6ae>
  4bdae2:	call   2c1b0 <abort@plt>
  4bdae7:	nopw   0x0(%rax,%rax,1)
  4bdaf0:	mov    0x78(%r13),%esi
  4bdaf4:	add    %ebx,%esi
  4bdaf6:	call   53ccb0 <_ZN4tomo23xshard_atomic_key_sliceEPKNS_12ScatterStateEj>
  4bdafb:	mov    %rax,%rdi
  4bdafe:	mov    %edx,%eax
  4bdb00:	shr    $0x20,%rdx
  4bdb04:	jmp    4bd7b2 <tomo_multidb2_pad_381064+0x45d>
  4bdb09:	nopl   0x0(%rax)
  4bdb10:	lea    -0x1(%r14),%esi
  4bdb14:	mov    (%rax,%rsi,4),%r14d
  4bdb18:	mov    (%rax,%r8,4),%esi
  4bdb1c:	cmp    %r14d,%esi
  4bdb1f:	jae    4bda9f <tomo_multidb2_pad_381064+0x74a>
  4bdb25:	jmp    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bdb27:	nopw   0x0(%rax,%rax,1)
  4bdb30:	mov    0x78(%r12),%esi
  4bdb35:	mov    %r8,0x10(%rsp)
  4bdb3a:	add    %r14d,%esi
  4bdb3d:	call   53ccb0 <_ZN4tomo23xshard_atomic_key_sliceEPKNS_12ScatterStateEj>
  4bdb42:	mov    0x10(%rsp),%r8
  4bdb47:	mov    %rax,%r14
  4bdb4a:	mov    %rdx,%rax
  4bdb4d:	vmovd  %edx,%xmm0
  4bdb51:	shr    $0x20,%rax
  4bdb55:	mov    %r14,(%rsp)
  4bdb59:	jmp    4bd737 <tomo_multidb2_pad_381064+0x3e2>
  4bdb5e:	mov    (%rax),%r12
  4bdb61:	jmp    4bd622 <tomo_multidb2_pad_381064+0x2cd>
  4bdb66:	cmp    $0x3,%eax
  4bdb69:	jbe    4bdb9d <tomo_multidb2_pad_381064+0x848>
  4bdb6b:	mov    (%rsp),%rcx
  4bdb6f:	mov    -0x4(%rdi,%rax,1),%edx
  4bdb73:	xor    -0x4(%rcx,%rax,1),%edx
  4bdb77:	mov    %edx,%eax
  4bdb79:	mov    (%rdi),%edx
  4bdb7b:	xor    (%rcx),%edx
  4bdb7d:	or     %edx,%eax
  4bdb7f:	sete   %al
  4bdb82:	jmp    4bd819 <tomo_multidb2_pad_381064+0x4c4>
  4bdb87:	mov    %rsi,%rdx
  4bdb8a:	mov    (%rsp),%rsi
  4bdb8e:	call   2c8a0 <memcmp@plt>
  4bdb93:	test   %eax,%eax
  4bdb95:	sete   %al
  4bdb98:	jmp    4bd819 <tomo_multidb2_pad_381064+0x4c4>
  4bdb9d:	test   %eax,%eax
  4bdb9f:	je     4bd821 <tomo_multidb2_pad_381064+0x4cc>
  4bdba5:	mov    (%rsp),%rdx
  4bdba9:	movzbl (%rdx),%edx
  4bdbac:	cmp    %dl,(%rdi)
  4bdbae:	jne    4bd778 <tomo_multidb2_pad_381064+0x423>
  4bdbb4:	mov    (%rsp),%rcx
  4bdbb8:	mov    %eax,%edx
  4bdbba:	shr    $1,%edx
  4bdbbc:	movzbl (%rcx,%rdx,1),%ecx
  4bdbc0:	cmp    %cl,(%rdi,%rdx,1)
  4bdbc3:	jne    4bd778 <tomo_multidb2_pad_381064+0x423>
  4bdbc9:	mov    (%rsp),%rdx
  4bdbcd:	dec    %eax
  4bdbcf:	movzbl (%rdx,%rax,1),%edx
  4bdbd3:	cmp    %dl,(%rdi,%rax,1)
  4bdbd6:	jne    4bd778 <tomo_multidb2_pad_381064+0x423>
  4bdbdc:	jmp    4bd821 <tomo_multidb2_pad_381064+0x4cc>
  4bdbe1:	mov    0xc5d0(%r12),%rax
  4bdbe9:	cmp    $0xffffffffffffffff,%rax
  4bdbed:	je     4bd5cd <tomo_multidb2_pad_381064+0x278>
  4bdbf3:	lock btrq $0x1,0x548(%r12)
  4bdbfe:	jb     4bd5cd <tomo_multidb2_pad_381064+0x278>
  4bdc04:	jmp    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bdc09:	nopl   0x0(%rax)
  4bdc10:	add    %r15,0x528(%rdx)
  4bdc17:	jmp    4bd141 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2a1>
  4bdc1c:	nopl   0x0(%rax)
  4bdc20:	lea    -0x1(%rbx),%edx
  4bdc23:	mov    (%rax,%rdx,4),%ebx
  4bdc26:	mov    (%rax,%r8,4),%eax
  4bdc2a:	cmp    %ebx,%eax
  4bdc2c:	jae    4bd90b <tomo_multidb2_pad_381064+0x5b6>
  4bdc32:	jmp    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bdc37:	nopw   0x0(%rax,%rax,1)
  4bdc40:	mov    0x78(%r12),%esi
  4bdc45:	mov    %r8,(%rsp)
  4bdc49:	mov    %r10,0x10(%rsp)
  4bdc4e:	add    %ebx,%esi
  4bdc50:	call   53ccb0 <_ZN4tomo23xshard_atomic_key_sliceEPKNS_12ScatterStateEj>
  4bdc55:	mov    0x10(%rsp),%r10
  4bdc5a:	mov    (%rsp),%r8
  4bdc5e:	vmovd  %edx,%xmm0
  4bdc62:	mov    %rax,%rsi
  4bdc65:	shr    $0x20,%rdx
  4bdc69:	jmp    4bd932 <tomo_multidb2_pad_381064+0x5dd>
  4bdc6e:	mov    0x50(%rbp),%rcx
  4bdc72:	mov    %rbx,%r11
  4bdc75:	movabs $0xaaaaaaaaaaaaaaab,%rdx
  4bdc7f:	sub    %rcx,%r11
  4bdc82:	mov    %r11,%rax
  4bdc85:	sar    $0x3,%rax
  4bdc89:	imul   %rdx,%rax
  4bdc8d:	movabs $0x555555555555555,%rdx
  4bdc97:	cmp    %rdx,%rax
  4bdc9a:	je     4bf8ca <tomo_multidb2_pad_381064+0x2575>
  4bdca0:	cmp    %rcx,%rbx
  4bdca3:	je     4be0ad <tomo_multidb2_pad_381064+0xd58>
  4bdca9:	lea    (%rax,%rax,1),%rdx
  4bdcad:	cmp    %rax,%rdx
  4bdcb0:	jb     4be32d <tomo_multidb2_pad_381064+0xfd8>
  4bdcb6:	test   %rdx,%rdx
  4bdcb9:	jne    4bf8b0 <tomo_multidb2_pad_381064+0x255b>
  4bdcbf:	xor    %r9d,%r9d
  4bdcc2:	xor    %edx,%edx
  4bdcc4:	vmovq  %xmm0,0x10(%r11)
  4bdcca:	mov    %r13,(%r11)
  4bdccd:	mov    %rsi,0x8(%r11)
  4bdcd1:	vpxor  %xmm0,%xmm0,%xmm0
  4bdcd5:	mov    %rcx,%rax
  4bdcd8:	nopl   0x0(%rax,%rax,1)
  4bdce0:	vmovdqu (%rax),%xmm5
  4bdce4:	mov    0x10(%rax),%rsi
  4bdce8:	add    $0x18,%rax
  4bdcec:	add    $0x18,%rdx
  4bdcf0:	mov    %rsi,-0x8(%rdx)
  4bdcf4:	vmovdqu %xmm5,-0x18(%rdx)
  4bdcf9:	cmp    %rax,%rbx
  4bdcfc:	jne    4bdce0 <tomo_multidb2_pad_381064+0x98b>
  4bdcfe:	lea    -0x18(%rbx),%rax
  4bdd02:	movabs $0xaaaaaaaaaaaaaab,%rdx
  4bdd0c:	sub    %rcx,%rax
  4bdd0f:	shr    $0x3,%rax
  4bdd13:	imul   %rdx,%rax
  4bdd17:	movabs $0x1fffffffffffffff,%rdx
  4bdd21:	and    %rdx,%rax
  4bdd24:	vmovq  %xmm0,%rdx
  4bdd29:	lea    (%rax,%rax,2),%rax
  4bdd2d:	lea    0x30(%rdx,%rax,8),%rax
  4bdd32:	vpinsrq $0x1,%rax,%xmm0,%xmm0
  4bdd38:	test   %rcx,%rcx
  4bdd3b:	je     4bdd73 <tomo_multidb2_pad_381064+0xa1e>
  4bdd3d:	sub    %rcx,%rdi
  4bdd40:	vmovdqa %xmm0,(%rsp)
  4bdd45:	mov    %r8,0x20(%rsp)
  4bdd4a:	mov    %r10,0x18(%rsp)
  4bdd4f:	mov    %rdi,%rsi
  4bdd52:	mov    %rcx,%rdi
  4bdd55:	mov    %r9,0x10(%rsp)
  4bdd5a:	call   2be30 <_ZdlPvm@plt>
  4bdd5f:	vmovdqa (%rsp),%xmm0
  4bdd64:	mov    0x20(%rsp),%r8
  4bdd69:	mov    0x18(%rsp),%r10
  4bdd6e:	mov    0x10(%rsp),%r9
  4bdd73:	vmovdqu %xmm0,0x50(%rbp)
  4bdd78:	mov    %r9,0x60(%rbp)
  4bdd7c:	jmp    4bd974 <tomo_multidb2_pad_381064+0x61f>
  4bdd81:	mov    0x50(%rbp),%rbx
  4bdd85:	mov    0x58(%rbp),%rcx
  4bdd89:	cmp    %rbx,%rcx
  4bdd8c:	je     4bd94f <tomo_multidb2_pad_381064+0x5fa>
  4bdd92:	mov    %rcx,%rax
  4bdd95:	vmovq  %xmm0,%r9
  4bdd9a:	mov    %r14,%rcx
  4bdd9d:	mov    %r12,0x10(%rsp)
  4bdda2:	mov    %rax,%r14
  4bdda5:	jmp    4bddb4 <tomo_multidb2_pad_381064+0xa5f>
  4bdda7:	add    $0x18,%rbx
  4bddab:	cmp    %rbx,%r14
  4bddae:	je     4be0a0 <tomo_multidb2_pad_381064+0xd4b>
  4bddb4:	cmp    %r13,(%rbx)
  4bddb7:	jne    4bdda7 <tomo_multidb2_pad_381064+0xa52>
  4bddb9:	cmp    %r9,0x10(%rbx)
  4bddbd:	jne    4bdda7 <tomo_multidb2_pad_381064+0xa52>
  4bddbf:	mov    0x10(%rbx),%eax
  4bddc2:	mov    0x8(%rbx),%rdi
  4bddc6:	cmp    $0x7,%eax
  4bddc9:	jbe    4be390 <tomo_multidb2_pad_381064+0x103b>
  4bddcf:	mov    %eax,%r11d
  4bddd2:	cmp    $0x20,%eax
  4bddd5:	ja     4be3af <tomo_multidb2_pad_381064+0x105a>
  4bdddb:	mov    -0x8(%rdi,%r11,1),%rdx
  4bdde0:	xor    -0x8(%rsi,%r11,1),%rdx
  4bdde5:	mov    %rdx,%r12
  4bdde8:	mov    (%rdi),%rdx
  4bddeb:	xor    (%rsi),%rdx
  4bddee:	or     %r12,%rdx
  4bddf1:	cmp    $0x10,%eax
  4bddf4:	jbe    4bde0e <tomo_multidb2_pad_381064+0xab9>
  4bddf6:	mov    -0x10(%rdi,%r11,1),%rax
  4bddfb:	mov    0x8(%rdi),%rdi
  4bddff:	xor    -0x10(%rsi,%r11,1),%rax
  4bde04:	xor    0x8(%rsi),%rdi
  4bde08:	or     %rdi,%rax
  4bde0b:	or     %rax,%rdx
  4bde0e:	test   %rdx,%rdx
  4bde11:	sete   %al
  4bde14:	test   %al,%al
  4bde16:	je     4bdda7 <tomo_multidb2_pad_381064+0xa52>
  4bde18:	lea    (%r15,%r15,1),%rdx
  4bde1c:	mov    $0x1d,%eax
  4bde21:	mov    $0x8,%ebx
  4bde26:	jmp    4bde33 <tomo_multidb2_pad_381064+0xade>
  4bde28:	add    %rbx,%rbx
  4bde2b:	dec    %eax
  4bde2d:	je     4bd190 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2f0>
  4bde33:	cmp    %rdx,%rbx
  4bde36:	jb     4bde28 <tomo_multidb2_pad_381064+0xad3>
  4bde38:	movabs $0x111111111111111,%rax
  4bde42:	cmp    %r15,%rax
  4bde45:	jb     4bd190 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2f0>
  4bde4b:	mov    0x8(%rbp),%rax
  4bde4f:	cmp    0x10(%rbp),%rax
  4bde53:	je     4bde59 <tomo_multidb2_pad_381064+0xb04>
  4bde55:	mov    %rax,0x10(%rbp)
  4bde59:	lea    0x8(%rbp),%rdi
  4bde5d:	mov    %r15,%rsi
  4bde60:	call   4b1ba0 <_ZNSt6vectorIN4tomo17AtomicCollapseKeyESaIS1_EE7reserveEm>
  4bde65:	lea    0x80(%rsp),%rax
  4bde6d:	xor    %r11d,%r11d
  4bde70:	xor    %r12d,%r12d
  4bde73:	lea    0x20(%rbp),%rdi
  4bde77:	mov    %rax,%rdx
  4bde7a:	mov    %rbx,%rsi
  4bde7d:	mov    %r11,0x80(%rsp)
  4bde85:	mov    %r12d,0x88(%rsp)
  4bde8d:	mov    %rax,0x18(%rsp)
  4bde92:	call   4ba130 <_ZNSt6vectorIN4tomo18AtomicCollapseSlotESaIS1_EE14_M_fill_assignEmRKS1_>
  4bde97:	mov    0x38(%rbp),%rax
  4bde9b:	cmp    0x40(%rbp),%rax
  4bde9f:	je     4bdea5 <tomo_multidb2_pad_381064+0xb50>
  4bdea1:	mov    %rax,0x40(%rbp)
  4bdea5:	mov    %r15,%rsi
  4bdea8:	lea    0x38(%rbp),%r14
  4bdeac:	shr    $1,%rsi
  4bdeaf:	mov    %r14,%rdi
  4bdeb2:	add    %r15,%rsi
  4bdeb5:	call   4b1c90 <_ZNSt6vectorIPN4tomo5KvObjESaIS2_EE7reserveEm>
  4bdeba:	mov    0xc8(%rbp),%rax
  4bdec1:	dec    %ebx
  4bdec3:	lea    0x6c(%rsp),%rdx
  4bdec8:	mov    %rbp,0x78(%rsp)
  4bdecd:	mov    %ebx,0x6c(%rsp)
  4bded1:	mov    %rdx,0x70(%rsp)
  4bded6:	lea    0x70(%rsp),%rbx
  4bdedb:	mov    (%rax),%r12
  4bdede:	add    %r15,0x530(%rax)
  4bdee5:	cmp    %r12,0x28(%rsp)
  4bdeea:	je     4bf7bc <tomo_multidb2_pad_381064+0x2467>
  4bdef0:	mov    0x7c(%r12),%r10d
  4bdef5:	xor    %r13d,%r13d
  4bdef8:	test   %r10d,%r10d
  4bdefb:	jne    4be065 <tomo_multidb2_pad_381064+0xd10>
  4bdf01:	jmp    4beb97 <tomo_multidb2_pad_381064+0x1842>
  4bdf06:	cs nopw 0x0(%rax,%rax,1)
  4bdf10:	mov    0x78(%r12),%esi
  4bdf15:	mov    %r13d,0x10(%rsp)
  4bdf1a:	add    %r13d,%esi
  4bdf1d:	call   53cc70 <_ZN4tomo22xshard_atomic_key_hashEPKNS_12ScatterStateEj>
  4bdf22:	mov    0x28(%r12),%rdi
  4bdf27:	mov    0x10(%rsp),%edx
  4bdf2b:	mov    %rax,%r9
  4bdf2e:	test   %rdi,%rdi
  4bdf31:	je     4be078 <tomo_multidb2_pad_381064+0xd23>
  4bdf37:	cmpb   $0x0,0x8a(%r12)
  4bdf40:	je     4beb70 <tomo_multidb2_pad_381064+0x181b>
  4bdf46:	cmp    0x7c(%r12),%edx
  4bdf4b:	jae    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bdf51:	mov    0x80(%r12),%edi
  4bdf59:	lea    0x90(,%rdi,8),%rcx
  4bdf61:	lea    (%r12,%rcx,1),%rax
  4bdf65:	test   %edx,%edx
  4bdf67:	jne    4beb55 <tomo_multidb2_pad_381064+0x1800>
  4bdf6d:	mov    (%rax),%eax
  4bdf6f:	cmp    %eax,0x84(%r12)
  4bdf77:	jb     4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bdf7d:	movzbl 0x8b(%r12),%esi
  4bdf86:	lea    (%rcx,%rdi,4),%rcx
  4bdf8a:	sub    %edx,%eax
  4bdf8c:	add    %rcx,%rdx
  4bdf8f:	add    %r12,%rdx
  4bdf92:	mov    0x90(%r12,%r13,8),%r8
  4bdf9a:	vmovd  %eax,%xmm7
  4bdf9e:	mov    %rbx,%rdi
  4bdfa1:	vpinsrd $0x1,%esi,%xmm7,%xmm6
  4bdfa7:	mov    %r9,%rsi
  4bdfaa:	vmovq  %xmm6,%rcx
  4bdfaf:	call   4a0ed0 <_ZZN4tomo9FlatStore20atomic_collapse_implILb0EEEbmmENKUlmNS_5SliceEPNS_5KvObjEE_clEmS2_S4_>
  4bdfb4:	mov    %eax,%eax
  4bdfb6:	imul   $0x78,%rax,%rax
  4bdfba:	add    0x8(%rbp),%rax
  4bdfbe:	mov    0x20(%rax),%rcx
  4bdfc2:	test   %rcx,%rcx
  4bdfc5:	je     4be053 <tomo_multidb2_pad_381064+0xcfe>
  4bdfcb:	mov    0x30(%rcx),%rdx
  4bdfcf:	mov    0x90(%r12,%r13,8),%rdi
  4bdfd7:	test   %rdx,%rdx
  4bdfda:	je     4bdffd <tomo_multidb2_pad_381064+0xca8>
  4bdfdc:	mov    0x40(%rcx),%rsi
  4bdfe0:	test   %rsi,%rsi
  4bdfe3:	je     4beb4d <tomo_multidb2_pad_381064+0x17f8>
  4bdfe9:	movzbl (%rsi),%edx
  4bdfec:	test   %dl,%dl
  4bdfee:	jne    4be053 <tomo_multidb2_pad_381064+0xcfe>
  4bdff0:	mov    0x30(%rcx),%rdx
  4bdff4:	test   %rdx,%rdx
  4bdff7:	jne    4beb4d <tomo_multidb2_pad_381064+0x17f8>
  4bdffd:	mov    0x58(%rcx),%rdx
  4be001:	xor    %esi,%esi
  4be003:	cmp    $0xffffffffffffffff,%rdx
  4be007:	vmovq  0x50(%rcx),%xmm0
  4be00c:	cmove  %rsi,%rdx
  4be010:	cmpb   $0x0,0x70(%rax)
  4be014:	je     4be02c <tomo_multidb2_pad_381064+0xcd7>
  4be016:	vmovq  %xmm0,%rcx
  4be01b:	cmp    0x60(%rax),%rcx
  4be01f:	jne    4be02c <tomo_multidb2_pad_381064+0xcd7>
  4be021:	mov    0x68(%rax),%rcx
  4be025:	cmp    %rcx,%rdx
  4be028:	cmovb  %rcx,%rdx
  4be02c:	cmpb   $0x0,0x58(%rax)
  4be030:	vpinsrq $0x1,%rdx,%xmm0,%xmm0
  4be036:	movb   $0x1,0x70(%rax)
  4be03a:	vmovdqu %xmm0,0x60(%rax)
  4be03f:	je     4be047 <tomo_multidb2_pad_381064+0xcf2>
  4be041:	cmp    0x50(%rax),%rdx
  4be045:	jb     4be053 <tomo_multidb2_pad_381064+0xcfe>
  4be047:	mov    %rdi,0x28(%rax)
  4be04b:	mov    %rdx,0x50(%rax)
  4be04f:	movb   $0x1,0x58(%rax)
  4be053:	inc    %r13
  4be056:	mov    %r12,0x20(%rax)
  4be05a:	cmp    0x7c(%r12),%r13d
  4be05f:	jae    4beb97 <tomo_multidb2_pad_381064+0x1842>
  4be065:	mov    0x28(%r12),%rdi
  4be06a:	test   %rdi,%rdi
  4be06d:	jne    4bdf10 <tomo_multidb2_pad_381064+0xbbb>
  4be073:	mov    0x60(%r12),%r9
  4be078:	mov    0x80(%r12),%edx
  4be080:	movzbl 0x8b(%r12),%esi
  4be089:	mov    0x84(%r12),%eax
  4be091:	lea    0x90(%r12,%rdx,8),%rdx
  4be099:	jmp    4bdf92 <tomo_multidb2_pad_381064+0xc3d>
  4be09e:	xchg   %ax,%ax
  4be0a0:	mov    0x10(%rsp),%r12
  4be0a5:	mov    %rcx,%r14
  4be0a8:	jmp    4bd94f <tomo_multidb2_pad_381064+0x5fa>
  4be0ad:	add    $0x1,%rax
  4be0b1:	jb     4be32d <tomo_multidb2_pad_381064+0xfd8>
  4be0b7:	movabs $0x555555555555555,%rdx
  4be0c1:	cmp    %rdx,%rax
  4be0c4:	cmova  %rdx,%rax
  4be0c8:	lea    (%rax,%rax,2),%r9
  4be0cc:	shl    $0x3,%r9
  4be0d0:	vmovq  %xmm0,0x30(%rsp)
  4be0d6:	mov    %r8,0x48(%rsp)
  4be0db:	mov    %r10,0x40(%rsp)
  4be0e0:	mov    %r11,0x20(%rsp)
  4be0e5:	mov    %r9,%rdi
  4be0e8:	mov    %rcx,0x18(%rsp)
  4be0ed:	mov    %rsi,(%rsp)
  4be0f1:	mov    %r9,0x10(%rsp)
  4be0f6:	call   2c120 <_Znwm@plt>
  4be0fb:	vmovq  0x30(%rsp),%xmm0
  4be101:	mov    0x20(%rsp),%r11
  4be106:	mov    0x10(%rsp),%r9
  4be10b:	mov    0x18(%rsp),%rcx
  4be110:	mov    (%rsp),%rsi
  4be114:	mov    %rax,%rdx
  4be117:	mov    0x60(%rbp),%rdi
  4be11b:	mov    0x40(%rsp),%r10
  4be120:	mov    0x48(%rsp),%r8
  4be125:	add    %rax,%r11
  4be128:	add    %rax,%r9
  4be12b:	vmovq  %xmm0,0x10(%r11)
  4be131:	vmovq  %rax,%xmm0
  4be136:	add    $0x18,%rax
  4be13a:	cmp    %rcx,%rbx
  4be13d:	mov    %r13,(%r11)
  4be140:	mov    %rsi,0x8(%r11)
  4be144:	jne    4bdcd5 <tomo_multidb2_pad_381064+0x980>
  4be14a:	jmp    4bdd32 <tomo_multidb2_pad_381064+0x9dd>
  4be14f:	mov    (%r12),%r12
  4be153:	cmp    %r12,0x28(%rsp)
  4be158:	jne    4bd87c <tomo_multidb2_pad_381064+0x527>
  4be15e:	mov    0x28(%rsp),%rbx
  4be163:	mov    %rbp,%rdi
  4be166:	mov    %rbx,%rsi
  4be169:	call   4a3d60 <_ZN4tomo9FlatStore32atomic_prepare_rollback_capacityEPNS_11AtomicEntryE>
  4be16e:	test   %al,%al
  4be170:	je     4bd190 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2f0>
  4be176:	mov    0xc8(%rbp),%rax
  4be17d:	add    %r15,0x530(%rax)
  4be184:	mov    (%rax),%r15
  4be187:	cmp    %r15,%rbx
  4be18a:	mov    $0x0,%ebx
  4be18f:	je     4be7ce <tomo_multidb2_pad_381064+0x1479>
  4be195:	mov    %r15,%r13
  4be198:	mov    %rbp,%r12
  4be19b:	mov    %r13,%r15
  4be19e:	xor    %r9d,%r9d
  4be1a1:	mov    0x0(%r13),%r13
  4be1a5:	cmpq   $0x0,0x30(%r15)
  4be1aa:	je     4be1be <tomo_multidb2_pad_381064+0xe69>
  4be1ac:	mov    0x40(%r15),%rdx
  4be1b0:	test   %rdx,%rdx
  4be1b3:	je     4be1be <tomo_multidb2_pad_381064+0xe69>
  4be1b5:	movzbl (%rdx),%edx
  4be1b8:	test   %dl,%dl
  4be1ba:	setne  %r9b
  4be1be:	mov    0x7c(%r15),%eax
  4be1c2:	test   %eax,%eax
  4be1c4:	je     4be6c4 <tomo_multidb2_pad_381064+0x136f>
  4be1ca:	movq   $0x0,0x20(%rsp)
  4be1d3:	mov    %rbx,0x50(%rsp)
  4be1d8:	mov    %r13,0x58(%rsp)
  4be1dd:	mov    %r9b,0x48(%rsp)
  4be1e2:	jmp    4be2f2 <tomo_multidb2_pad_381064+0xf9d>
  4be1e7:	mov    0x20(%rsp),%rax
  4be1ec:	mov    0x78(%r15),%esi
  4be1f0:	add    %eax,%esi
  4be1f2:	mov    %eax,%ebp
  4be1f4:	call   53cc70 <_ZN4tomo22xshard_atomic_key_hashEPKNS_12ScatterStateEj>
  4be1f9:	mov    0x28(%r15),%rdi
  4be1fd:	mov    %rax,%rbx
  4be200:	test   %rdi,%rdi
  4be203:	je     4be303 <tomo_multidb2_pad_381064+0xfae>
  4be209:	cmpb   $0x0,0x8a(%r15)
  4be211:	je     4be33c <tomo_multidb2_pad_381064+0xfe7>
  4be217:	cmp    0x7c(%r15),%ebp
  4be21b:	jae    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4be221:	mov    0x80(%r15),%edi
  4be228:	lea    0x90(,%rdi,8),%rsi
  4be230:	lea    (%r15,%rsi,1),%rax
  4be234:	test   %ebp,%ebp
  4be236:	jne    4be369 <tomo_multidb2_pad_381064+0x1014>
  4be23c:	mov    (%rax),%eax
  4be23e:	cmp    %eax,0x84(%r15)
  4be245:	jb     4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4be24b:	movzbl 0x8b(%r15),%ecx
  4be253:	sub    %ebp,%eax
  4be255:	lea    (%rsi,%rdi,4),%r13
  4be259:	vmovd  %eax,%xmm0
  4be25d:	mov    %ebp,%eax
  4be25f:	add    %rax,%r13
  4be262:	lea    (%r15,%r13,1),%rax
  4be266:	mov    %rax,0x18(%rsp)
  4be26b:	mov    0x20(%rsp),%rax
  4be270:	cmpb   $0x0,0x48(%rsp)
  4be275:	vpinsrd $0x1,%ecx,%xmm0,%xmm7
  4be27b:	vmovq  %xmm7,%rcx
  4be280:	vmovq  %xmm7,0x40(%rsp)
  4be286:	mov    0x90(%r15,%rax,8),%rax
  4be28e:	mov    %rax,0x10(%rsp)
  4be293:	jne    4be3fd <tomo_multidb2_pad_381064+0x10a8>
  4be299:	mov    0x10(%rsp),%rax
  4be29e:	test   %rax,%rax
  4be2a1:	je     4be2cf <tomo_multidb2_pad_381064+0xf7a>
  4be2a3:	mov    %rax,%rdi
  4be2a6:	call   48e5e0 <_ZN4tomo10kvobj_sizeEPKNS_5KvObjE>
  4be2ab:	mov    (%r12),%rcx
  4be2af:	mov    %rcx,%rdx
  4be2b2:	sub    %rax,%rdx
  4be2b5:	cmp    %rax,%rcx
  4be2b8:	jb     4beb1f <tomo_multidb2_pad_381064+0x17ca>
  4be2be:	mov    0x10(%rsp),%rsi
  4be2c3:	mov    %r12,%rdi
  4be2c6:	mov    %rdx,(%r12)
  4be2ca:	call   491ce0 <_ZN4tomo9FlatStore19retire_detached_objEPNS_5KvObjE>
  4be2cf:	mov    0x20(%rsp),%rax
  4be2d4:	movq   $0x0,0x90(%r15,%rax,8)
  4be2e0:	inc    %rax
  4be2e3:	cmp    0x7c(%r15),%eax
  4be2e7:	jae    4be6b0 <tomo_multidb2_pad_381064+0x135b>
  4be2ed:	mov    %rax,0x20(%rsp)
  4be2f2:	mov    0x28(%r15),%rdi
  4be2f6:	test   %rdi,%rdi
  4be2f9:	jne    4be1e7 <tomo_multidb2_pad_381064+0xe92>
  4be2ff:	mov    0x60(%r15),%rbx
  4be303:	mov    0x80(%r15),%eax
  4be30a:	vmovd  0x84(%r15),%xmm0
  4be313:	movzbl 0x8b(%r15),%ecx
  4be31b:	lea    0x90(%r15,%rax,8),%rax
  4be323:	mov    %rax,0x18(%rsp)
  4be328:	jmp    4be26b <tomo_multidb2_pad_381064+0xf16>
  4be32d:	movabs $0x7ffffffffffffff8,%r9
  4be337:	jmp    4be0d0 <tomo_multidb2_pad_381064+0xd7b>
  4be33c:	mov    0x78(%r15),%esi
  4be340:	add    %ebp,%esi
  4be342:	call   53ccb0 <_ZN4tomo23xshard_atomic_key_sliceEPKNS_12ScatterStateEj>
  4be347:	mov    %rdx,%rcx
  4be34a:	vmovd  %edx,%xmm0
  4be34e:	mov    %rax,0x18(%rsp)
  4be353:	shr    $0x20,%rcx
  4be357:	jmp    4be26b <tomo_multidb2_pad_381064+0xf16>
  4be35c:	movq   $0x0,0x8(%rdx)
  4be364:	jmp    4bd15a <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2ba>
  4be369:	lea    -0x1(%rbp),%edx
  4be36c:	mov    (%rax,%rdx,4),%ebp
  4be36f:	mov    0x20(%rsp),%rdx
  4be374:	mov    (%rax,%rdx,4),%eax
  4be377:	cmp    %ebp,%eax
  4be379:	jae    4be23e <tomo_multidb2_pad_381064+0xee9>
  4be37f:	jmp    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4be384:	data16 cs nopw 0x0(%rax,%rax,1)
  4be38f:	nop
  4be390:	cmp    $0x3,%eax
  4be393:	jbe    4be670 <tomo_multidb2_pad_381064+0x131b>
  4be399:	mov    -0x4(%rdi,%rax,1),%edx
  4be39d:	xor    -0x4(%rsi,%rax,1),%edx
  4be3a1:	mov    (%rdi),%eax
  4be3a3:	xor    (%rsi),%eax
  4be3a5:	or     %edx,%eax
  4be3a7:	sete   %al
  4be3aa:	jmp    4bde14 <tomo_multidb2_pad_381064+0xabf>
  4be3af:	mov    %r11,%rdx
  4be3b2:	vmovq  %xmm0,0x48(%rsp)
  4be3b8:	mov    %r8,0x40(%rsp)
  4be3bd:	mov    %r9,0x30(%rsp)
  4be3c2:	mov    %rcx,0x20(%rsp)
  4be3c7:	mov    %r10,0x18(%rsp)
  4be3cc:	mov    %rsi,(%rsp)
  4be3d0:	call   2c8a0 <memcmp@plt>
  4be3d5:	test   %eax,%eax
  4be3d7:	vmovq  0x48(%rsp),%xmm0
  4be3dd:	mov    (%rsp),%rsi
  4be3e1:	mov    0x18(%rsp),%r10
  4be3e6:	mov    0x20(%rsp),%rcx
  4be3eb:	mov    0x30(%rsp),%r9
  4be3f0:	sete   %al
  4be3f3:	mov    0x40(%rsp),%r8
  4be3f8:	jmp    4bde14 <tomo_multidb2_pad_381064+0xabf>
  4be3fd:	test   %rax,%rax
  4be400:	je     4be951 <tomo_multidb2_pad_381064+0x15fc>
  4be406:	mov    0x10(%rsp),%rax
  4be40b:	movzbl 0x2(%rax),%eax
  4be40f:	test   $0x1,%al
  4be411:	je     4be439 <tomo_multidb2_pad_381064+0x10e4>
  4be413:	mov    0x10(%rsp),%rdx
  4be418:	movzbl 0x2(%rdx),%eax
  4be41c:	shr    $1,%al
  4be41e:	and    $0x1,%eax
  4be421:	mov    0x8(%rdx,%rax,4),%rax
  4be426:	test   %rax,%rax
  4be429:	js     4be439 <tomo_multidb2_pad_381064+0x10e4>
  4be42b:	cmp    %rax,0x188(%r12)
  4be433:	jg     4be951 <tomo_multidb2_pad_381064+0x15fc>
  4be439:	mov    0x10(%rsp),%rax
  4be43e:	mov    %rax,0x30(%rsp)
  4be443:	mov    %ebx,%eax
  4be445:	mov    $0x1,%edx
  4be44a:	shlx   %rax,%rdx,%rbp
  4be44f:	mov    0x28(%rsp),%rax
  4be454:	test   %rax,%rax
  4be457:	je     4be962 <tomo_multidb2_pad_381064+0x160d>
  4be45d:	mov    %rax,%r13
  4be460:	mov    %rbx,%rax
  4be463:	mov    %rcx,0x38(%rsp)
  4be468:	mov    %rbp,%rbx
  4be46b:	mov    %rax,%rbp
  4be46e:	jmp    4be47d <tomo_multidb2_pad_381064+0x1128>
  4be470:	mov    0x0(%r13),%r13
  4be474:	test   %r13,%r13
  4be477:	je     4be95f <tomo_multidb2_pad_381064+0x160a>
  4be47d:	mov    %rbx,%rax
  4be480:	and    0x68(%r13),%rax
  4be484:	je     4be470 <tomo_multidb2_pad_381064+0x111b>
  4be486:	mov    0x7c(%r13),%eax
  4be48a:	xor    %r14d,%r14d
  4be48d:	test   %eax,%eax
  4be48f:	je     4be470 <tomo_multidb2_pad_381064+0x111b>
  4be491:	mov    0x28(%r13),%rdi
  4be495:	test   %rdi,%rdi
  4be498:	je     4be4c5 <tomo_multidb2_pad_381064+0x1170>
  4be49a:	mov    0x78(%r13),%esi
  4be49e:	mov    %r14d,(%rsp)
  4be4a2:	add    %r14d,%esi
  4be4a5:	call   53cc70 <_ZN4tomo22xshard_atomic_key_hashEPKNS_12ScatterStateEj>
  4be4aa:	cmp    %rbp,%rax
  4be4ad:	je     4be5d0 <tomo_multidb2_pad_381064+0x127b>
  4be4b3:	inc    %r14
  4be4b6:	cmp    0x7c(%r13),%r14d
  4be4ba:	jae    4be470 <tomo_multidb2_pad_381064+0x111b>
  4be4bc:	mov    0x28(%r13),%rdi
  4be4c0:	test   %rdi,%rdi
  4be4c3:	jne    4be49a <tomo_multidb2_pad_381064+0x1145>
  4be4c5:	cmp    %rbp,0x60(%r13)
  4be4c9:	jne    4be4b3 <tomo_multidb2_pad_381064+0x115e>
  4be4cb:	mov    0x80(%r13),%edx
  4be4d2:	movzbl 0x8b(%r13),%ecx
  4be4da:	mov    0x84(%r13),%eax
  4be4e1:	lea    0x90(%r13,%rdx,8),%rdi
  4be4e9:	vmovd  %eax,%xmm6
  4be4ed:	vpinsrd $0x1,%ecx,%xmm6,%xmm5
  4be4f3:	vmovq  %xmm5,%rdx
  4be4f8:	cmp    %rdx,0x38(%rsp)
  4be4fd:	jne    4be4b3 <tomo_multidb2_pad_381064+0x115e>
  4be4ff:	cmp    $0x7,%eax
  4be502:	jbe    4be928 <tomo_multidb2_pad_381064+0x15d3>
  4be508:	mov    %eax,%ecx
  4be50a:	cmp    $0x20,%eax
  4be50d:	ja     4beb36 <tomo_multidb2_pad_381064+0x17e1>
  4be513:	mov    0x18(%rsp),%r11
  4be518:	mov    -0x8(%rdi,%rcx,1),%rdx
  4be51d:	mov    (%rdi),%rsi
  4be520:	xor    -0x8(%r11,%rcx,1),%rdx
  4be525:	xor    (%r11),%rsi
  4be528:	or     %rsi,%rdx
  4be52b:	cmp    $0x10,%eax
  4be52e:	jbe    4be548 <tomo_multidb2_pad_381064+0x11f3>
  4be530:	mov    -0x10(%rdi,%rcx,1),%rax
  4be535:	xor    -0x10(%r11,%rcx,1),%rax
  4be53a:	mov    0x8(%rdi),%rcx
  4be53e:	xor    0x8(%r11),%rcx
  4be542:	or     %rcx,%rax
  4be545:	or     %rax,%rdx
  4be548:	test   %rdx,%rdx
  4be54b:	sete   %al
  4be54e:	test   %al,%al
  4be550:	je     4be4b3 <tomo_multidb2_pad_381064+0x115e>
  4be556:	mov    %r14d,%r14d
  4be559:	lea    0x90(%r13,%r14,8),%rbx
  4be561:	mov    (%rbx),%rbp
  4be564:	test   %rbp,%rbp
  4be567:	je     4be588 <tomo_multidb2_pad_381064+0x1233>
  4be569:	mov    %rbp,%rdi
  4be56c:	call   48e5e0 <_ZN4tomo10kvobj_sizeEPKNS_5KvObjE>
  4be571:	mov    %rax,%rdx
  4be574:	mov    (%r12),%rax
  4be578:	cmp    %rdx,%rax
  4be57b:	jb     4bf7d7 <tomo_multidb2_pad_381064+0x2482>
  4be581:	sub    %rdx,%rax
  4be584:	mov    %rax,(%r12)
  4be588:	mov    0x30(%rsp),%rax
  4be58d:	cmp    %rax,%rbp
  4be590:	je     4be59d <tomo_multidb2_pad_381064+0x1248>
  4be592:	mov    %rbp,%rsi
  4be595:	mov    %r12,%rdi
  4be598:	call   491ce0 <_ZN4tomo9FlatStore19retire_detached_objEPNS_5KvObjE>
  4be59d:	mov    0x30(%rsp),%rax
  4be5a2:	mov    0x10(%rsp),%rdi
  4be5a7:	mov    %rax,(%rbx)
  4be5aa:	test   %rdi,%rdi
  4be5ad:	je     4be2cf <tomo_multidb2_pad_381064+0xf7a>
  4be5b3:	cmp    %rax,%rdi
  4be5b6:	je     4be2cf <tomo_multidb2_pad_381064+0xf7a>
  4be5bc:	jmp    4be2a6 <tomo_multidb2_pad_381064+0xf51>
  4be5c1:	data16 cs nopw 0x0(%rax,%rax,1)
  4be5cc:	nopl   0x0(%rax)
  4be5d0:	mov    0x28(%r13),%rdi
  4be5d4:	test   %rdi,%rdi
  4be5d7:	je     4be4cb <tomo_multidb2_pad_381064+0x1176>
  4be5dd:	cmpb   $0x0,0x8a(%r13)
  4be5e5:	je     4be63d <tomo_multidb2_pad_381064+0x12e8>
  4be5e7:	mov    %r14d,%ecx
  4be5ea:	cmp    0x7c(%r13),%r14d
  4be5ee:	jae    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4be5f4:	mov    0x80(%r13),%esi
  4be5fb:	lea    0x90(,%rsi,8),%rdx
  4be603:	lea    0x0(%r13,%rdx,1),%rax
  4be608:	test   %r14d,%r14d
  4be60b:	jne    4be659 <tomo_multidb2_pad_381064+0x1304>
  4be60d:	mov    (%rax),%eax
  4be60f:	cmp    %eax,0x84(%r13)
  4be616:	jb     4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4be61c:	mov    (%rsp),%r11d
  4be620:	lea    (%rdx,%rsi,4),%rdi
  4be624:	movzbl 0x8b(%r13),%ecx
  4be62c:	mov    %r11d,%edx
  4be62f:	sub    %r11d,%eax
  4be632:	add    %rdx,%rdi
  4be635:	add    %r13,%rdi
  4be638:	jmp    4be4e9 <tomo_multidb2_pad_381064+0x1194>
  4be63d:	mov    0x78(%r13),%esi
  4be641:	add    %r14d,%esi
  4be644:	call   53ccb0 <_ZN4tomo23xshard_atomic_key_sliceEPKNS_12ScatterStateEj>
  4be649:	mov    %rax,%rdi
  4be64c:	mov    %edx,%eax
  4be64e:	shr    $0x20,%rdx
  4be652:	mov    %edx,%ecx
  4be654:	jmp    4be4e9 <tomo_multidb2_pad_381064+0x1194>
  4be659:	dec    %ecx
  4be65b:	mov    (%rax,%rcx,4),%ecx
  4be65e:	mov    (%rax,%r14,4),%eax
  4be662:	mov    %ecx,(%rsp)
  4be665:	cmp    %ecx,%eax
  4be667:	jae    4be60f <tomo_multidb2_pad_381064+0x12ba>
  4be669:	jmp    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4be66e:	xchg   %ax,%ax
  4be670:	test   %eax,%eax
  4be672:	je     4bde18 <tomo_multidb2_pad_381064+0xac3>
  4be678:	movzbl (%rsi),%edx
  4be67b:	cmp    %dl,(%rdi)
  4be67d:	jne    4bdda7 <tomo_multidb2_pad_381064+0xa52>
  4be683:	mov    %eax,%edx
  4be685:	shr    $1,%edx
  4be687:	movzbl (%rsi,%rdx,1),%r11d
  4be68c:	cmp    %r11b,(%rdi,%rdx,1)
  4be690:	jne    4bdda7 <tomo_multidb2_pad_381064+0xa52>
  4be696:	dec    %eax
  4be698:	movzbl (%rsi,%rax,1),%edx
  4be69c:	cmp    %dl,(%rdi,%rax,1)
  4be69f:	jne    4bdda7 <tomo_multidb2_pad_381064+0xa52>
  4be6a5:	jmp    4bde18 <tomo_multidb2_pad_381064+0xac3>
  4be6aa:	nopw   0x0(%rax,%rax,1)
  4be6b0:	mov    0x50(%rsp),%rbx
  4be6b5:	mov    0x20(%rsp),%rax
  4be6ba:	mov    0x58(%rsp),%r13
  4be6bf:	lea    0x1(%rbx,%rax,1),%rbx
  4be6c4:	cmpb   $0x0,0x89(%r15)
  4be6cc:	jne    4bf815 <tomo_multidb2_pad_381064+0x24c0>
  4be6d2:	mov    0x38(%r15),%rsi
  4be6d6:	test   %rsi,%rsi
  4be6d9:	je     4be6eb <tomo_multidb2_pad_381064+0x1396>
  4be6db:	mov    0x48(%r15),%rcx
  4be6df:	test   %rcx,%rcx
  4be6e2:	je     4be6e8 <tomo_multidb2_pad_381064+0x1393>
  4be6e4:	decl   (%rcx)
  4be6e6:	jne    4be6eb <tomo_multidb2_pad_381064+0x1396>
  4be6e8:	lock decl (%rsi)
  4be6eb:	mov    0xb0(%r12),%rdx
  4be6f3:	test   %rdx,%rdx
  4be6f6:	je     4be6fb <tomo_multidb2_pad_381064+0x13a6>
  4be6f8:	incq   (%rdx)
  4be6fb:	mov    0xc8(%r12),%rcx
  4be703:	decl   0x210(%rcx)
  4be709:	cmpq   $0x0,0x28(%r15)
  4be70e:	je     4be716 <tomo_multidb2_pad_381064+0x13c1>
  4be710:	decb   0x526(%rcx)
  4be716:	mov    0x18(%r15),%rdi
  4be71a:	mov    0x50(%r15),%rcx
  4be71e:	test   %rdi,%rdi
  4be721:	je     4be840 <tomo_multidb2_pad_381064+0x14eb>
  4be727:	mov    0x10(%r15),%rsi
  4be72b:	mov    %rsi,0x10(%rdi)
  4be72f:	test   %rsi,%rsi
  4be732:	je     4be90b <tomo_multidb2_pad_381064+0x15b6>
  4be738:	mov    0xc8(%r12),%rcx
  4be740:	mov    %rdi,0x18(%rsi)
  4be744:	movq   $0x0,0x18(%r15)
  4be74c:	movq   $0x0,0x10(%r15)
  4be754:	cmpb   $0x0,0x89(%r15)
  4be75c:	jne    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4be762:	mov    0x70(%r15),%rsi
  4be766:	cmp    $0x8,%rsi
  4be76a:	jbe    4be89e <tomo_multidb2_pad_381064+0x1549>
  4be770:	cmp    $0x80,%rsi
  4be777:	jbe    4be8fa <tomo_multidb2_pad_381064+0x15a5>
  4be77d:	lea    -0x1(%rsi),%rdi
  4be781:	mov    $0x3d,%edx
  4be786:	mov    $0x38,%r8d
  4be78c:	lzcnt  %rdi,%rdi
  4be791:	sub    %edi,%edx
  4be793:	sub    %edi,%r8d
  4be796:	shrx   %rdx,%rsi,%rdx
  4be79b:	lea    0x4(%rdx,%r8,4),%edx
  4be7a0:	test   %rcx,%rcx
  4be7a3:	je     4be7ae <tomo_multidb2_pad_381064+0x1459>
  4be7a5:	cmp    $0x2f,%edx
  4be7a8:	jbe    4be8a9 <tomo_multidb2_pad_381064+0x1554>
  4be7ae:	xor    %edx,%edx
  4be7b0:	mov    %r15,%rdi
  4be7b3:	call   2bf70 <sdallocx@plt>
  4be7b8:	cmp    %r13,0x28(%rsp)
  4be7bd:	jne    4be19b <tomo_multidb2_pad_381064+0xe46>
  4be7c3:	mov    0xc8(%r12),%rax
  4be7cb:	mov    %r12,%rbp
  4be7ce:	mov    0x28(%rsp),%rdx
  4be7d3:	mov    %rdx,(%rax)
  4be7d6:	test   %rdx,%rdx
  4be7d9:	je     4bf7f3 <tomo_multidb2_pad_381064+0x249e>
  4be7df:	movq   $0x0,0x8(%rdx)
  4be7e7:	cmpq   $0x0,0x210(%rax)
  4be7ef:	jne    4be801 <tomo_multidb2_pad_381064+0x14ac>
  4be7f1:	mov    0x88(%rbp),%rax
  4be7f8:	test   %rax,%rax
  4be7fb:	je     4be801 <tomo_multidb2_pad_381064+0x14ac>
  4be7fd:	lock decq (%rax)
  4be801:	mov    0xa8(%rbp),%rax
  4be808:	test   %rax,%rax
  4be80b:	je     4bd183 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2e3>
  4be811:	add    %rbx,(%rax)
  4be814:	jmp    4bd183 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2e3>
  4be819:	nopl   0x0(%rax)
  4be820:	mov    0xc5d0(%r12),%rax
  4be828:	cmp    $0xffffffffffffffff,%rax
  4be82c:	je     4bd5cd <tomo_multidb2_pad_381064+0x278>
  4be832:	jmp    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4be837:	nopw   0x0(%rax,%rax,1)
  4be840:	mov    %rcx,%rdx
  4be843:	movabs $0xff51afd7ed558ccd,%rax
  4be84d:	shr    $0x21,%rdx
  4be851:	xor    %rcx,%rdx
  4be854:	imul   %rax,%rdx
  4be858:	movabs $0xc4ceb9fe1a85ec53,%rax
  4be862:	mov    %rdx,%rcx
  4be865:	shr    $0x21,%rcx
  4be869:	xor    %rcx,%rdx
  4be86c:	imul   %rax,%rdx
  4be870:	mov    %rdx,%rcx
  4be873:	shr    $0x21,%rcx
  4be877:	xor    %rcx,%rdx
  4be87a:	mov    0xc8(%r12),%rcx
  4be882:	and    $0x3f,%edx
  4be885:	cmp    0x10(%rcx,%rdx,8),%r15
  4be88a:	jne    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4be890:	mov    0x10(%r15),%rsi
  4be894:	mov    %rsi,0x10(%rcx,%rdx,8)
  4be899:	jmp    4be72f <tomo_multidb2_pad_381064+0x13da>
  4be89e:	xor    %edx,%edx
  4be8a0:	test   %rcx,%rcx
  4be8a3:	je     4be7ae <tomo_multidb2_pad_381064+0x1459>
  4be8a9:	mov    0x520(%rcx),%edi
  4be8af:	cmp    $0xfff,%edi
  4be8b5:	ja     4be7ae <tomo_multidb2_pad_381064+0x1459>
  4be8bb:	mov    0x538(%rcx),%r8
  4be8c2:	add    %rsi,%r8
  4be8c5:	cmp    $0x400000,%r8
  4be8cc:	ja     4be7ae <tomo_multidb2_pad_381064+0x1459>
  4be8d2:	mov    %edx,%edx
  4be8d4:	inc    %edi
  4be8d6:	add    $0x40,%rdx
  4be8da:	mov    0x20(%rcx,%rdx,8),%rsi
  4be8df:	mov    %rsi,0x20(%r15)
  4be8e3:	mov    %r15,0x20(%rcx,%rdx,8)
  4be8e8:	mov    %edi,0x520(%rcx)
  4be8ee:	mov    %r8,0x538(%rcx)
  4be8f5:	jmp    4be7b8 <tomo_multidb2_pad_381064+0x1463>
  4be8fa:	mov    %rsi,%rdx
  4be8fd:	shr    $0x4,%rdx
  4be901:	test   %rcx,%rcx
  4be904:	jne    4be8a9 <tomo_multidb2_pad_381064+0x1554>
  4be906:	jmp    4be7ae <tomo_multidb2_pad_381064+0x1459>
  4be90b:	mov    0xc8(%r12),%rcx
  4be913:	movq   $0x0,0x18(%r15)
  4be91b:	movq   $0x0,0x10(%r15)
  4be923:	jmp    4be754 <tomo_multidb2_pad_381064+0x13ff>
  4be928:	cmp    $0x3,%eax
  4be92b:	jbe    4bea4b <tomo_multidb2_pad_381064+0x16f6>
  4be931:	mov    0x18(%rsp),%rcx
  4be936:	mov    -0x4(%rdi,%rax,1),%edx
  4be93a:	xor    -0x4(%rcx,%rax,1),%edx
  4be93e:	mov    %edx,%eax
  4be940:	mov    (%rdi),%edx
  4be942:	xor    (%rcx),%edx
  4be944:	or     %edx,%eax
  4be946:	jne    4be4b3 <tomo_multidb2_pad_381064+0x115e>
  4be94c:	jmp    4be556 <tomo_multidb2_pad_381064+0x1201>
  4be951:	movq   $0x0,0x30(%rsp)
  4be95a:	jmp    4be443 <tomo_multidb2_pad_381064+0x10ee>
  4be95f:	mov    %rbp,%rbx
  4be962:	mov    0x18(%rsp),%rdx
  4be967:	mov    0x40(%rsp),%rcx
  4be96c:	mov    %rbx,%rsi
  4be96f:	mov    %r12,%rdi
  4be972:	call   48ff60 <_ZNK4tomo9FlatStore20atomic_find_physicalEmNS_5SliceE>
  4be977:	mov    %rax,%rbp
  4be97a:	mov    0x30(%rsp),%rax
  4be97f:	cmp    %rax,%rbp
  4be982:	je     4be9fb <tomo_multidb2_pad_381064+0x16a6>
  4be984:	movzbl 0x5dca4d(%rip),%eax        # a9b3d8 <_ZN4tomo22atomic_tripwire_detail5armedE>
  4be98b:	test   %al,%al
  4be98d:	je     4be9cd <tomo_multidb2_pad_381064+0x1678>
  4be98f:	cmpq   $0x0,0x5dca49(%rip)        # a9b3e0 <_ZN4tomo22atomic_tripwire_detail5stateE>
  4be997:	je     4be9cd <tomo_multidb2_pad_381064+0x1678>
  4be999:	mov    0x30(%r15),%rax
  4be99d:	test   %rax,%rax
  4be9a0:	je     4bf7ff <tomo_multidb2_pad_381064+0x24aa>
  4be9a6:	mov    (%rax),%rcx
  4be9a9:	cmp    $0xffffffffffffffff,%rcx
  4be9ad:	jne    4be9b1 <tomo_multidb2_pad_381064+0x165c>
  4be9af:	xor    %ecx,%ecx
  4be9b1:	xor    %edx,%edx
  4be9b3:	cmpq   $0x0,0x30(%rsp)
  4be9b9:	mov    %rbx,%rdi
  4be9bc:	sete   %dl
  4be9bf:	xor    %esi,%esi
  4be9c1:	test   %rbp,%rbp
  4be9c4:	sete   %sil
  4be9c8:	call   48e2f0 <_ZN4tomo30atomic_tripwire_collapse_writeEmbbm>
  4be9cd:	mov    0x30(%rsp),%r8
  4be9d2:	mov    0x18(%rsp),%rdx
  4be9d7:	mov    %rbx,%rsi
  4be9da:	mov    %r12,%rdi
  4be9dd:	mov    0x40(%rsp),%rcx
  4be9e2:	call   4912a0 <_ZN4tomo9FlatStore24atomic_exchange_physicalEmNS_5SliceEPNS_5KvObjE>
  4be9e7:	cmp    %rax,%rbp
  4be9ea:	jne    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4be9f0:	mov    %rbp,%rsi
  4be9f3:	mov    %r12,%rdi
  4be9f6:	call   491ce0 <_ZN4tomo9FlatStore19retire_detached_objEPNS_5KvObjE>
  4be9fb:	mov    0x10(%rsp),%rax
  4bea00:	test   %rax,%rax
  4bea03:	je     4be2cf <tomo_multidb2_pad_381064+0xf7a>
  4bea09:	mov    %rax,%rdi
  4bea0c:	call   48e5e0 <_ZN4tomo10kvobj_sizeEPKNS_5KvObjE>
  4bea11:	mov    %rax,%rdx
  4bea14:	mov    (%r12),%rax
  4bea18:	cmp    %rdx,%rax
  4bea1b:	jb     4bf808 <tomo_multidb2_pad_381064+0x24b3>
  4bea21:	sub    %rdx,%rax
  4bea24:	mov    %rax,(%r12)
  4bea28:	mov    0x10(%rsp),%rax
  4bea2d:	mov    0x30(%rsp),%rdx
  4bea32:	cmp    %rdx,%rax
  4bea35:	je     4be2cf <tomo_multidb2_pad_381064+0xf7a>
  4bea3b:	mov    %rax,%rsi
  4bea3e:	mov    %r12,%rdi
  4bea41:	call   491ce0 <_ZN4tomo9FlatStore19retire_detached_objEPNS_5KvObjE>
  4bea46:	jmp    4be2cf <tomo_multidb2_pad_381064+0xf7a>
  4bea4b:	test   %eax,%eax
  4bea4d:	je     4be556 <tomo_multidb2_pad_381064+0x1201>
  4bea53:	mov    0x18(%rsp),%rdx
  4bea58:	movzbl (%rdx),%edx
  4bea5b:	cmp    %dl,(%rdi)
  4bea5d:	jne    4be4b3 <tomo_multidb2_pad_381064+0x115e>
  4bea63:	mov    0x18(%rsp),%rcx
  4bea68:	mov    %eax,%edx
  4bea6a:	shr    $1,%edx
  4bea6c:	movzbl (%rcx,%rdx,1),%ecx
  4bea70:	cmp    %cl,(%rdi,%rdx,1)
  4bea73:	jne    4be4b3 <tomo_multidb2_pad_381064+0x115e>
  4bea79:	mov    0x18(%rsp),%rdx
  4bea7e:	dec    %eax
  4bea80:	movzbl (%rdx,%rax,1),%edx
  4bea84:	cmp    %dl,(%rdi,%rax,1)
  4bea87:	jne    4be4b3 <tomo_multidb2_pad_381064+0x115e>
  4bea8d:	jmp    4be556 <tomo_multidb2_pad_381064+0x1201>
  4bea92:	data16 cs nopw 0x0(%rax,%rax,1)
  4bea9d:	nopl   (%rax)
  4beaa0:	mov    0x58(%rbp),%rbx
  4beaa4:	lea    (%r15,%r15,2),%rax
  4beaa8:	lea    0x0(,%rax,8),%r13
  4beab0:	mov    %r13,%rdi
  4beab3:	sub    %rdx,%rbx
  4beab6:	call   2c120 <_Znwm@plt>
  4beabb:	mov    0x50(%rbp),%rdi
  4beabf:	mov    0x58(%rbp),%rcx
  4beac3:	mov    %rax,%r12
  4beac6:	mov    %rax,%rdx
  4beac9:	mov    %rdi,%rax
  4beacc:	cmp    %rdi,%rcx
  4beacf:	je     4beaef <tomo_multidb2_pad_381064+0x179a>
  4bead1:	vmovdqu (%rax),%xmm6
  4bead5:	mov    0x10(%rax),%rsi
  4bead9:	add    $0x18,%rax
  4beadd:	add    $0x18,%rdx
  4beae1:	mov    %rsi,-0x8(%rdx)
  4beae5:	vmovdqu %xmm6,-0x18(%rdx)
  4beaea:	cmp    %rax,%rcx
  4beaed:	jne    4bead1 <tomo_multidb2_pad_381064+0x177c>
  4beaef:	test   %rdi,%rdi
  4beaf2:	je     4beb00 <tomo_multidb2_pad_381064+0x17ab>
  4beaf4:	mov    0x60(%rbp),%rsi
  4beaf8:	sub    %rdi,%rsi
  4beafb:	call   2be30 <_ZdlPvm@plt>
  4beb00:	add    %r12,%rbx
  4beb03:	vmovq  %r12,%xmm7
  4beb08:	add    %r13,%r12
  4beb0b:	vpinsrq $0x1,%rbx,%xmm7,%xmm0
  4beb11:	mov    %r12,0x60(%rbp)
  4beb15:	vmovdqu %xmm0,0x50(%rbp)
  4beb1a:	jmp    4bd864 <tomo_multidb2_pad_381064+0x50f>
  4beb1f:	mov    0xc0(%r12),%rax
  4beb27:	test   %rax,%rax
  4beb2a:	je     4beb2f <tomo_multidb2_pad_381064+0x17da>
  4beb2c:	incq   (%rax)
  4beb2f:	xor    %edx,%edx
  4beb31:	jmp    4be2be <tomo_multidb2_pad_381064+0xf69>
  4beb36:	mov    0x18(%rsp),%rsi
  4beb3b:	mov    %rcx,%rdx
  4beb3e:	call   2c8a0 <memcmp@plt>
  4beb43:	test   %eax,%eax
  4beb45:	sete   %al
  4beb48:	jmp    4be54e <tomo_multidb2_pad_381064+0x11f9>
  4beb4d:	mov    (%rdx),%rdx
  4beb50:	jmp    4be001 <tomo_multidb2_pad_381064+0xcac>
  4beb55:	dec    %edx
  4beb57:	mov    (%rax,%rdx,4),%edx
  4beb5a:	mov    (%rax,%r13,4),%eax
  4beb5e:	cmp    %edx,%eax
  4beb60:	jae    4bdf6f <tomo_multidb2_pad_381064+0xc1a>
  4beb66:	jmp    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4beb6b:	nopl   0x0(%rax,%rax,1)
  4beb70:	add    0x78(%r12),%edx
  4beb75:	mov    %rax,0x10(%rsp)
  4beb7a:	mov    %edx,%esi
  4beb7c:	call   53ccb0 <_ZN4tomo23xshard_atomic_key_sliceEPKNS_12ScatterStateEj>
  4beb81:	mov    0x10(%rsp),%r9
  4beb86:	mov    %rdx,%rsi
  4beb89:	mov    %rax,%rdx
  4beb8c:	mov    %esi,%eax
  4beb8e:	shr    $0x20,%rsi
  4beb92:	jmp    4bdf92 <tomo_multidb2_pad_381064+0xc3d>
  4beb97:	mov    (%r12),%r12
  4beb9b:	cmp    %r12,0x28(%rsp)
  4beba0:	jne    4bdef0 <tomo_multidb2_pad_381064+0xb9b>
  4beba6:	mov    0x8(%rbp),%r13
  4bebaa:	mov    0x10(%rbp),%rcx
  4bebae:	cmp    %r13,%rcx
  4bebb1:	je     4bf7a2 <tomo_multidb2_pad_381064+0x244d>
  4bebb7:	xor    %esi,%esi
  4bebb9:	mov    %r14,0x20(%rsp)
  4bebbe:	mov    %r13,%r14
  4bebc1:	mov    %rcx,%r13
  4bebc4:	mov    %esi,%r12d
  4bebc7:	mov    %r15,(%rsp)
  4bebcb:	mov    (%r14),%ebx
  4bebce:	cmpq   $0x0,0x28(%rsp)
  4bebd4:	mov    $0x1,%eax
  4bebd9:	mov    0x40(%r14),%r15
  4bebdd:	shlx   %rbx,%rax,%rax
  4bebe2:	mov    %rax,0x10(%rsp)
  4bebe7:	je     4bec84 <tomo_multidb2_pad_381064+0x192f>
  4bebed:	mov    %r15,%rax
  4bebf0:	mov    0x28(%rsp),%r15
  4bebf5:	test   %rax,%rax
  4bebf8:	jne    4bef3f <tomo_multidb2_pad_381064+0x1bea>
  4bebfe:	mov    0x10(%rsp),%rax
  4bec03:	and    0x68(%r15),%rax
  4bec07:	jne    4bec30 <tomo_multidb2_pad_381064+0x18db>
  4bec09:	mov    (%r15),%r15
  4bec0c:	test   %r15,%r15
  4bec0f:	jne    4bebfe <tomo_multidb2_pad_381064+0x18a9>
  4bec11:	mov    0x8(%r14),%rdx
  4bec15:	mov    0x10(%r14),%rcx
  4bec19:	mov    (%r14),%rsi
  4bec1c:	mov    %rbp,%rdi
  4bec1f:	call   48ff60 <_ZNK4tomo9FlatStore20atomic_find_physicalEmNS_5SliceE>
  4bec24:	jmp    4bec95 <tomo_multidb2_pad_381064+0x1940>
  4bec26:	cs nopw 0x0(%rax,%rax,1)
  4bec30:	mov    0x7c(%r15),%r9d
  4bec34:	test   %r9d,%r9d
  4bec37:	je     4bec09 <tomo_multidb2_pad_381064+0x18b4>
  4bec39:	xor    %ecx,%ecx
  4bec3b:	mov    0x28(%r15),%rdi
  4bec3f:	mov    %ecx,%ebx
  4bec41:	test   %rdi,%rdi
  4bec44:	je     4bee90 <tomo_multidb2_pad_381064+0x1b3b>
  4bec4a:	mov    %ecx,%esi
  4bec4c:	add    0x78(%r15),%esi
  4bec50:	mov    %rcx,0x30(%rsp)
  4bec55:	call   53cc70 <_ZN4tomo22xshard_atomic_key_hashEPKNS_12ScatterStateEj>
  4bec5a:	cmp    %rax,(%r14)
  4bec5d:	mov    0x30(%rsp),%rcx
  4bec62:	je     4bef50 <tomo_multidb2_pad_381064+0x1bfb>
  4bec68:	inc    %rcx
  4bec6b:	cmp    0x7c(%r15),%ecx
  4bec6f:	jb     4bec3b <tomo_multidb2_pad_381064+0x18e6>
  4bec71:	mov    (%r15),%r15
  4bec74:	mov    0x40(%r14),%rax
  4bec78:	test   %r15,%r15
  4bec7b:	jne    4bebf5 <tomo_multidb2_pad_381064+0x18a0>
  4bec81:	mov    %rax,%r15
  4bec84:	test   %r15,%r15
  4bec87:	je     4bec11 <tomo_multidb2_pad_381064+0x18bc>
  4bec89:	mov    0x48(%r14),%eax
  4bec8d:	mov    0x90(%r15,%rax,8),%rax
  4bec95:	mov    0x20(%r14),%rcx
  4bec99:	mov    %rax,0x30(%r14)
  4bec9d:	mov    0x30(%rcx),%rdx
  4beca1:	test   %rdx,%rdx
  4beca4:	je     4beccb <tomo_multidb2_pad_381064+0x1976>
  4beca6:	mov    0x40(%rcx),%rsi
  4becaa:	test   %rsi,%rsi
  4becad:	je     4bf626 <tomo_multidb2_pad_381064+0x22d1>
  4becb3:	movzbl (%rsi),%edx
  4becb6:	test   %dl,%dl
  4becb8:	jne    4bf60e <tomo_multidb2_pad_381064+0x22b9>
  4becbe:	mov    0x30(%rcx),%rdx
  4becc2:	test   %rdx,%rdx
  4becc5:	jne    4bf626 <tomo_multidb2_pad_381064+0x22d1>
  4beccb:	mov    0x58(%rcx),%rdx
  4beccf:	xor    %edi,%edi
  4becd1:	cmp    $0xffffffffffffffff,%rdx
  4becd5:	vmovq  0x50(%rcx),%xmm0
  4becda:	cmove  %rdi,%rdx
  4becde:	cmpb   $0x0,0x70(%r14)
  4bece3:	je     4becfb <tomo_multidb2_pad_381064+0x19a6>
  4bece5:	vmovq  %xmm0,%rcx
  4becea:	cmp    0x60(%r14),%rcx
  4becee:	jne    4becfb <tomo_multidb2_pad_381064+0x19a6>
  4becf0:	mov    0x68(%r14),%rcx
  4becf4:	cmp    %rcx,%rdx
  4becf7:	cmovb  %rcx,%rdx
  4becfb:	cmpb   $0x0,0x58(%r14)
  4bed00:	vpinsrq $0x1,%rdx,%xmm0,%xmm0
  4bed06:	movb   $0x1,0x70(%r14)
  4bed0b:	vmovdqu %xmm0,0x60(%r14)
  4bed11:	je     4bf5f0 <tomo_multidb2_pad_381064+0x229b>
  4bed17:	cmp    0x50(%r14),%rdx
  4bed1b:	jae    4bf5f0 <tomo_multidb2_pad_381064+0x229b>
  4bed21:	mov    0x28(%r14),%rax
  4bed25:	test   %rax,%rax
  4bed28:	je     4bed62 <tomo_multidb2_pad_381064+0x1a0d>
  4bed2a:	movzbl 0x2(%rax),%edx
  4bed2e:	and    $0x1,%edx
  4bed31:	je     4bed53 <tomo_multidb2_pad_381064+0x19fe>
  4bed33:	movzbl 0x2(%rax),%edx
  4bed37:	shr    $1,%dl
  4bed39:	and    $0x1,%edx
  4bed3c:	mov    0x8(%rax,%rdx,4),%rdx
  4bed41:	test   %rdx,%rdx
  4bed44:	js     4bed53 <tomo_multidb2_pad_381064+0x19fe>
  4bed46:	cmp    %rdx,0x188(%rbp)
  4bed4d:	jg     4bf602 <tomo_multidb2_pad_381064+0x22ad>
  4bed53:	cmpq   $0x0,0x40(%r14)
  4bed58:	mov    %rax,0x28(%r14)
  4bed5c:	je     4bf5b6 <tomo_multidb2_pad_381064+0x2261>
  4bed62:	add    $0x78,%r14
  4bed66:	cmp    %r14,%r13
  4bed69:	jne    4bebcb <tomo_multidb2_pad_381064+0x1876>
  4bed6f:	mov    (%rsp),%r15
  4bed73:	mov    0x20(%rsp),%r14
  4bed78:	mov    %r12d,%esi
  4bed7b:	test   %r12d,%r12d
  4bed7e:	je     4bed90 <tomo_multidb2_pad_381064+0x1a3b>
  4bed80:	mov    %rbp,%rdi
  4bed83:	call   4a3960 <_ZN4tomo9FlatStore23atomic_prepare_capacityEj>
  4bed88:	test   %al,%al
  4bed8a:	je     4bd190 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2f0>
  4bed90:	mov    0x8(%rbp),%r13
  4bed94:	mov    0x10(%rbp),%r12
  4bed98:	cmp    %r13,%r12
  4bed9b:	jne    4bee3a <tomo_multidb2_pad_381064+0x1ae5>
  4beda1:	jmp    4bf7a2 <tomo_multidb2_pad_381064+0x244d>
  4beda6:	cs nopw 0x0(%rax,%rax,1)
  4bedb0:	mov    0x48(%r13),%ecx
  4bedb4:	lea    0x90(%rdx,%rcx,8),%rbx
  4bedbc:	cmp    %rax,(%rbx)
  4bedbf:	je     4bee2d <tomo_multidb2_pad_381064+0x1ad8>
  4bedc1:	movzbl 0x5dc610(%rip),%eax        # a9b3d8 <_ZN4tomo22atomic_tripwire_detail5armedE>
  4bedc8:	test   %al,%al
  4bedca:	je     4bedf7 <tomo_multidb2_pad_381064+0x1aa2>
  4bedcc:	cmpq   $0x0,0x5dc60c(%rip)        # a9b3e0 <_ZN4tomo22atomic_tripwire_detail5stateE>
  4bedd4:	je     4bedf7 <tomo_multidb2_pad_381064+0x1aa2>
  4bedd6:	xor    %edx,%edx
  4bedd8:	cmpq   $0x0,0x28(%r13)
  4beddd:	mov    0x50(%r13),%rcx
  4bede1:	mov    0x0(%r13),%rdi
  4bede5:	sete   %dl
  4bede8:	xor    %esi,%esi
  4bedea:	cmpq   $0x0,(%rbx)
  4bedee:	sete   %sil
  4bedf2:	call   48e2f0 <_ZN4tomo30atomic_tripwire_collapse_writeEmbbm>
  4bedf7:	mov    (%rbx),%rdi
  4bedfa:	test   %rdi,%rdi
  4bedfd:	je     4bee26 <tomo_multidb2_pad_381064+0x1ad1>
  4bedff:	call   48e5e0 <_ZN4tomo10kvobj_sizeEPKNS_5KvObjE>
  4bee04:	mov    %rax,%rdx
  4bee07:	mov    0x0(%rbp),%rax
  4bee0b:	cmp    %rdx,%rax
  4bee0e:	jb     4bf75b <tomo_multidb2_pad_381064+0x2406>
  4bee14:	sub    %rdx,%rax
  4bee17:	mov    %rax,0x0(%rbp)
  4bee1b:	mov    %rbx,%rsi
  4bee1e:	mov    %r14,%rdi
  4bee21:	call   4b1d60 <_ZNSt6vectorIPN4tomo5KvObjESaIS2_EE9push_backERKS2_>
  4bee26:	mov    0x28(%r13),%rax
  4bee2a:	mov    %rax,(%rbx)
  4bee2d:	add    $0x78,%r13
  4bee31:	cmp    %r13,%r12
  4bee34:	je     4beffb <tomo_multidb2_pad_381064+0x1ca6>
  4bee3a:	mov    0x40(%r13),%rdx
  4bee3e:	mov    0x28(%r13),%rax
  4bee42:	test   %rdx,%rdx
  4bee45:	jne    4bedb0 <tomo_multidb2_pad_381064+0x1a5b>
  4bee4b:	cmp    %rax,0x30(%r13)
  4bee4f:	je     4bee2d <tomo_multidb2_pad_381064+0x1ad8>
  4bee51:	call   48e2d0 <_ZN4tomo23atomic_tripwire_enabledEv>
  4bee56:	test   %al,%al
  4bee58:	jne    4bf5c9 <tomo_multidb2_pad_381064+0x2274>
  4bee5e:	mov    0x28(%r13),%r8
  4bee62:	mov    0x8(%r13),%rdx
  4bee66:	mov    0x10(%r13),%rcx
  4bee6a:	mov    %rbp,%rdi
  4bee6d:	mov    0x0(%r13),%rsi
  4bee71:	call   4912a0 <_ZN4tomo9FlatStore24atomic_exchange_physicalEmNS_5SliceEPNS_5KvObjE>
  4bee76:	mov    %rax,0x38(%r13)
  4bee7a:	cmp    0x30(%r13),%rax
  4bee7e:	je     4bee2d <tomo_multidb2_pad_381064+0x1ad8>
  4bee80:	jmp    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bee85:	data16 cs nopw 0x0(%rax,%rax,1)
  4bee90:	mov    0x60(%r15),%rax
  4bee94:	cmp    %rax,(%r14)
  4bee97:	jne    4bec68 <tomo_multidb2_pad_381064+0x1913>
  4bee9d:	mov    0x80(%r15),%esi
  4beea4:	movzbl 0x8b(%r15),%edx
  4beeac:	mov    0x84(%r15),%eax
  4beeb3:	lea    0x90(%r15,%rsi,8),%rdi
  4beebb:	vmovd  %eax,%xmm6
  4beebf:	vpinsrd $0x1,%edx,%xmm6,%xmm5
  4beec5:	vmovq  %xmm5,%rdx
  4beeca:	cmp    %rdx,0x10(%r14)
  4beece:	jne    4bec68 <tomo_multidb2_pad_381064+0x1913>
  4beed4:	mov    0x8(%r14),%rsi
  4beed8:	cmp    $0x7,%eax
  4beedb:	jbe    4bf73e <tomo_multidb2_pad_381064+0x23e9>
  4beee1:	mov    %eax,%edx
  4beee3:	cmp    $0x20,%eax
  4beee6:	ja     4befe2 <tomo_multidb2_pad_381064+0x1c8d>
  4beeec:	mov    -0x8(%rdi,%rdx,1),%r8
  4beef1:	mov    (%rdi),%r9
  4beef4:	xor    -0x8(%rsi,%rdx,1),%r8
  4beef9:	xor    (%rsi),%r9
  4beefc:	or     %r9,%r8
  4beeff:	cmp    $0x10,%eax
  4bef02:	jbe    4bef1c <tomo_multidb2_pad_381064+0x1bc7>
  4bef04:	mov    -0x10(%rdi,%rdx,1),%rax
  4bef09:	xor    -0x10(%rsi,%rdx,1),%rax
  4bef0e:	mov    0x8(%rdi),%rdx
  4bef12:	xor    0x8(%rsi),%rdx
  4bef16:	or     %rdx,%rax
  4bef19:	or     %rax,%r8
  4bef1c:	test   %r8,%r8
  4bef1f:	sete   %al
  4bef22:	test   %al,%al
  4bef24:	je     4bec68 <tomo_multidb2_pad_381064+0x1913>
  4bef2a:	mov    %r15,0x40(%r14)
  4bef2e:	cmpq   $0x0,(%r15)
  4bef32:	mov    %r15,%rax
  4bef35:	mov    %ebx,0x48(%r14)
  4bef39:	je     4bec84 <tomo_multidb2_pad_381064+0x192f>
  4bef3f:	mov    %rax,%r15
  4bef42:	jmp    4bec89 <tomo_multidb2_pad_381064+0x1934>
  4bef47:	nopw   0x0(%rax,%rax,1)
  4bef50:	mov    0x28(%r15),%rdi
  4bef54:	test   %rdi,%rdi
  4bef57:	je     4bee9d <tomo_multidb2_pad_381064+0x1b48>
  4bef5d:	cmpb   $0x0,0x8a(%r15)
  4bef65:	je     4befb2 <tomo_multidb2_pad_381064+0x1c5d>
  4bef67:	cmp    0x7c(%r15),%ebx
  4bef6b:	jae    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bef71:	mov    0x80(%r15),%r8d
  4bef78:	lea    0x90(,%r8,8),%rdi
  4bef80:	lea    (%r15,%rdi,1),%rax
  4bef84:	test   %ebx,%ebx
  4bef86:	jne    4befd0 <tomo_multidb2_pad_381064+0x1c7b>
  4bef88:	mov    (%rax),%eax
  4bef8a:	xor    %esi,%esi
  4bef8c:	cmp    %eax,0x84(%r15)
  4bef93:	jb     4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bef99:	lea    (%rdi,%r8,4),%rdi
  4bef9d:	movzbl 0x8b(%r15),%edx
  4befa5:	sub    %esi,%eax
  4befa7:	add    %rsi,%rdi
  4befaa:	add    %r15,%rdi
  4befad:	jmp    4beebb <tomo_multidb2_pad_381064+0x1b66>
  4befb2:	mov    0x78(%r15),%esi
  4befb6:	add    %ebx,%esi
  4befb8:	call   53ccb0 <_ZN4tomo23xshard_atomic_key_sliceEPKNS_12ScatterStateEj>
  4befbd:	mov    0x30(%rsp),%rcx
  4befc2:	mov    %rax,%rdi
  4befc5:	mov    %edx,%eax
  4befc7:	shr    $0x20,%rdx
  4befcb:	jmp    4beebb <tomo_multidb2_pad_381064+0x1b66>
  4befd0:	lea    -0x1(%rbx),%edx
  4befd3:	mov    (%rax,%rdx,4),%esi
  4befd6:	mov    (%rax,%rcx,4),%eax
  4befd9:	cmp    %esi,%eax
  4befdb:	jae    4bef8c <tomo_multidb2_pad_381064+0x1c37>
  4befdd:	jmp    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4befe2:	mov    %rcx,0x30(%rsp)
  4befe7:	call   2c8a0 <memcmp@plt>
  4befec:	mov    0x30(%rsp),%rcx
  4beff1:	test   %eax,%eax
  4beff3:	sete   %al
  4beff6:	jmp    4bef22 <tomo_multidb2_pad_381064+0x1bcd>
  4beffb:	mov    0xc8(%rbp),%rax
  4bf002:	mov    (%rax),%r13
  4bf005:	cmp    %r13,0x28(%rsp)
  4bf00a:	je     4bf19c <tomo_multidb2_pad_381064+0x1e47>
  4bf010:	lea    0x70(%rsp),%rax
  4bf015:	mov    %r15,0x30(%rsp)
  4bf01a:	mov    %rbp,%r15
  4bf01d:	mov    %rax,0x20(%rsp)
  4bf022:	mov    0x7c(%r13),%esi
  4bf026:	xor    %r12d,%r12d
  4bf029:	test   %esi,%esi
  4bf02b:	je     4bf185 <tomo_multidb2_pad_381064+0x1e30>
  4bf031:	mov    %r15,%rbx
  4bf034:	mov    %r14,0x38(%rsp)
  4bf039:	jmp    4bf134 <tomo_multidb2_pad_381064+0x1ddf>
  4bf03e:	cmpb   $0x0,0x8a(%r13)
  4bf046:	mov    %r12d,%r14d
  4bf049:	je     4bf590 <tomo_multidb2_pad_381064+0x223b>
  4bf04f:	mov    0x80(%r13),%r10d
  4bf056:	lea    0x90(,%r10,8),%r8
  4bf05e:	lea    0x0(%r13,%r8,1),%rax
  4bf063:	test   %r12d,%r12d
  4bf066:	jne    4bf33b <tomo_multidb2_pad_381064+0x1fe6>
  4bf06c:	mov    (%rax),%eax
  4bf06e:	xor    %edx,%edx
  4bf070:	cmp    %eax,0x84(%r13)
  4bf077:	jb     4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bf07d:	movzbl 0x8b(%r13),%esi
  4bf085:	sub    %edx,%eax
  4bf087:	lea    (%r8,%r10,4),%r15
  4bf08b:	add    %rdx,%r15
  4bf08e:	vmovd  %eax,%xmm5
  4bf092:	add    %r13,%r15
  4bf095:	vpinsrd $0x1,%esi,%xmm5,%xmm0
  4bf09b:	mov    0x78(%r13),%esi
  4bf09f:	vmovq  %xmm0,0x10(%rsp)
  4bf0a5:	add    %r14d,%esi
  4bf0a8:	call   53cc70 <_ZN4tomo22xshard_atomic_key_hashEPKNS_12ScatterStateEj>
  4bf0ad:	vmovq  0x10(%rsp),%xmm0
  4bf0b3:	mov    %rax,%rsi
  4bf0b6:	mov    0x20(%rsp),%rdi
  4bf0bb:	xor    %r8d,%r8d
  4bf0be:	mov    %r15,%rdx
  4bf0c1:	vmovq  %xmm0,%rcx
  4bf0c6:	call   4a0ed0 <_ZZN4tomo9FlatStore20atomic_collapse_implILb0EEEbmmENKUlmNS_5SliceEPNS_5KvObjEE_clEmS2_S4_>
  4bf0cb:	mov    %eax,%r15d
  4bf0ce:	imul   $0x78,%r15,%r15
  4bf0d2:	add    0x8(%rbx),%r15
  4bf0d6:	cmpq   $0x0,0x40(%r15)
  4bf0db:	je     4bf0e3 <tomo_multidb2_pad_381064+0x1d8e>
  4bf0dd:	cmp    0x28(%r15),%rbp
  4bf0e1:	je     4bf11f <tomo_multidb2_pad_381064+0x1dca>
  4bf0e3:	mov    %rbp,%rdi
  4bf0e6:	call   48e5e0 <_ZN4tomo10kvobj_sizeEPKNS_5KvObjE>
  4bf0eb:	mov    (%rbx),%rcx
  4bf0ee:	mov    %rcx,%rdx
  4bf0f1:	sub    %rax,%rdx
  4bf0f4:	cmp    %rax,%rcx
  4bf0f7:	jb     4bf6b9 <tomo_multidb2_pad_381064+0x2364>
  4bf0fd:	mov    %rdx,(%rbx)
  4bf100:	cmp    0x28(%r15),%rbp
  4bf104:	je     4bf11f <tomo_multidb2_pad_381064+0x1dca>
  4bf106:	mov    0x40(%rbx),%rax
  4bf10a:	cmp    0x48(%rbx),%rax
  4bf10e:	je     4bf62e <tomo_multidb2_pad_381064+0x22d9>
  4bf114:	mov    %rbp,(%rax)
  4bf117:	add    $0x8,%rax
  4bf11b:	mov    %rax,0x40(%rbx)
  4bf11f:	movq   $0x0,0x90(%r13,%r12,8)
  4bf12b:	inc    %r12
  4bf12e:	cmp    0x7c(%r13),%r12d
  4bf132:	jae    4bf17d <tomo_multidb2_pad_381064+0x1e28>
  4bf134:	mov    0x90(%r13,%r12,8),%rbp
  4bf13c:	test   %rbp,%rbp
  4bf13f:	je     4bf12b <tomo_multidb2_pad_381064+0x1dd6>
  4bf141:	mov    0x28(%r13),%rdi
  4bf145:	test   %rdi,%rdi
  4bf148:	jne    4bf03e <tomo_multidb2_pad_381064+0x1ce9>
  4bf14e:	vmovd  0x84(%r13),%xmm7
  4bf157:	movzbl 0x8b(%r13),%eax
  4bf15f:	mov    0x80(%r13),%edx
  4bf166:	lea    0x90(%r13,%rdx,8),%r15
  4bf16e:	vpinsrd $0x1,%eax,%xmm7,%xmm0
  4bf174:	mov    0x60(%r13),%rsi
  4bf178:	jmp    4bf0b6 <tomo_multidb2_pad_381064+0x1d61>
  4bf17d:	mov    0x38(%rsp),%r14
  4bf182:	mov    %rbx,%r15
  4bf185:	mov    0x0(%r13),%r13
  4bf189:	cmp    %r13,0x28(%rsp)
  4bf18e:	jne    4bf022 <tomo_multidb2_pad_381064+0x1ccd>
  4bf194:	mov    %r15,%rbp
  4bf197:	mov    0x30(%rsp),%r15
  4bf19c:	mov    0x10(%rbp),%rax
  4bf1a0:	mov    0x8(%rbp),%r12
  4bf1a4:	mov    %rax,0x10(%rsp)
  4bf1a9:	cmp    %r12,%rax
  4bf1ac:	je     4bf1ec <tomo_multidb2_pad_381064+0x1e97>
  4bf1ae:	mov    %r14,0x20(%rsp)
  4bf1b3:	mov    %r12,%r14
  4bf1b6:	mov    0x38(%r14),%rdi
  4bf1ba:	mov    0x40(%rbp),%rax
  4bf1be:	mov    0x38(%rbp),%r12
  4bf1c2:	test   %rdi,%rdi
  4bf1c5:	je     4bf1dc <tomo_multidb2_pad_381064+0x1e87>
  4bf1c7:	cmp    0x48(%rbp),%rax
  4bf1cb:	je     4bf4a7 <tomo_multidb2_pad_381064+0x2152>
  4bf1d1:	mov    %rdi,(%rax)
  4bf1d4:	add    $0x8,%rax
  4bf1d8:	mov    %rax,0x40(%rbp)
  4bf1dc:	add    $0x78,%r14
  4bf1e0:	cmp    %r14,0x10(%rsp)
  4bf1e5:	jne    4bf1b6 <tomo_multidb2_pad_381064+0x1e61>
  4bf1e7:	mov    0x20(%rsp),%r14
  4bf1ec:	mov    0x40(%rbp),%rsi
  4bf1f0:	mov    0x38(%rbp),%rdi
  4bf1f4:	call   4b1ed0 <_ZSt4sortIN9__gnu_cxx17__normal_iteratorIPPN4tomo5KvObjESt6vectorIS4_SaIS4_EEEEEvT_SA_>
  4bf1f9:	mov    0x40(%rbp),%rbx
  4bf1fd:	mov    0x38(%rbp),%rdi
  4bf201:	mov    %rbx,%rsi
  4bf204:	call   4b2140 <_ZSt6uniqueIN9__gnu_cxx17__normal_iteratorIPPN4tomo5KvObjESt6vectorIS4_SaIS4_EEEEET_SA_SA_>
  4bf209:	mov    %rbx,%rdx
  4bf20c:	mov    %r14,%rdi
  4bf20f:	mov    %rax,%rsi
  4bf212:	call   4b20c0 <_ZNSt6vectorIPN4tomo5KvObjESaIS2_EE5eraseEN9__gnu_cxx17__normal_iteratorIPKS2_S4_EES9_>
  4bf217:	mov    0x38(%rbp),%rbx
  4bf21b:	mov    0x40(%rbp),%r12
  4bf21f:	cmp    %rbx,%r12
  4bf222:	je     4bf238 <tomo_multidb2_pad_381064+0x1ee3>
  4bf224:	mov    (%rbx),%rsi
  4bf227:	mov    %rbp,%rdi
  4bf22a:	add    $0x8,%rbx
  4bf22e:	call   491ce0 <_ZN4tomo9FlatStore19retire_detached_objEPNS_5KvObjE>
  4bf233:	cmp    %rbx,%r12
  4bf236:	jne    4bf224 <tomo_multidb2_pad_381064+0x1ecf>
  4bf238:	mov    0xc8(%rbp),%rax
  4bf23f:	xor    %ebx,%ebx
  4bf241:	mov    $0x3d,%r14d
  4bf247:	mov    (%rax),%r13
  4bf24a:	cmp    %r13,0x28(%rsp)
  4bf24f:	jne    4bf2e1 <tomo_multidb2_pad_381064+0x1f8c>
  4bf255:	jmp    4bf3c9 <tomo_multidb2_pad_381064+0x2074>
  4bf25a:	nopw   0x0(%rax,%rax,1)
  4bf260:	mov    %r12,%rsi
  4bf263:	mov    %rbp,%rdi
  4bf266:	incq   (%rax)
  4bf269:	call   48feb0 <_ZN4tomo9FlatStore18atomic_unlink_connERNS_11AtomicEntryE>
  4bf26e:	mov    0xc8(%rbp),%rdx
  4bf275:	cmpb   $0x0,0x89(%r12)
  4bf27e:	jne    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bf284:	mov    0x70(%r12),%rsi
  4bf289:	cmp    $0x8,%rsi
  4bf28d:	jbe    4bf3b6 <tomo_multidb2_pad_381064+0x2061>
  4bf293:	cmp    $0x80,%rsi
  4bf29a:	jbe    4bf354 <tomo_multidb2_pad_381064+0x1fff>
  4bf2a0:	lea    -0x1(%rsi),%rax
  4bf2a4:	mov    %r14d,%ecx
  4bf2a7:	mov    $0x38,%edi
  4bf2ac:	lzcnt  %rax,%rax
  4bf2b1:	sub    %eax,%ecx
  4bf2b3:	sub    %eax,%edi
  4bf2b5:	shrx   %rcx,%rsi,%rcx
  4bf2ba:	lea    0x4(%rcx,%rdi,4),%eax
  4bf2be:	test   %rdx,%rdx
  4bf2c1:	je     4bf2cc <tomo_multidb2_pad_381064+0x1f77>
  4bf2c3:	cmp    $0x2f,%eax
  4bf2c6:	jbe    4bf364 <tomo_multidb2_pad_381064+0x200f>
  4bf2cc:	xor    %edx,%edx
  4bf2ce:	mov    %r12,%rdi
  4bf2d1:	call   2bf70 <sdallocx@plt>
  4bf2d6:	cmp    %r13,0x28(%rsp)
  4bf2db:	je     4bf3c2 <tomo_multidb2_pad_381064+0x206d>
  4bf2e1:	mov    %r13,%r12
  4bf2e4:	mov    0x0(%r13),%r13
  4bf2e8:	cmpb   $0x0,0x89(%r12)
  4bf2f1:	jne    4bf3f9 <tomo_multidb2_pad_381064+0x20a4>
  4bf2f7:	mov    0x38(%r12),%rcx
  4bf2fc:	test   %rcx,%rcx
  4bf2ff:	je     4bf312 <tomo_multidb2_pad_381064+0x1fbd>
  4bf301:	mov    0x48(%r12),%rdx
  4bf306:	test   %rdx,%rdx
  4bf309:	je     4bf30f <tomo_multidb2_pad_381064+0x1fba>
  4bf30b:	decl   (%rdx)
  4bf30d:	jne    4bf312 <tomo_multidb2_pad_381064+0x1fbd>
  4bf30f:	lock decl (%rcx)
  4bf312:	mov    0xb0(%rbp),%rax
  4bf319:	inc    %ebx
  4bf31b:	test   %rax,%rax
  4bf31e:	jne    4bf260 <tomo_multidb2_pad_381064+0x1f0b>
  4bf324:	mov    %r12,%rsi
  4bf327:	mov    %rbp,%rdi
  4bf32a:	call   48feb0 <_ZN4tomo9FlatStore18atomic_unlink_connERNS_11AtomicEntryE>
  4bf32f:	mov    0xc8(%rbp),%rdx
  4bf336:	jmp    4bf275 <tomo_multidb2_pad_381064+0x1f20>
  4bf33b:	lea    -0x1(%r12),%edx
  4bf340:	mov    (%rax,%rdx,4),%edx
  4bf343:	mov    (%rax,%r12,4),%eax
  4bf347:	cmp    %edx,%eax
  4bf349:	jae    4bf070 <tomo_multidb2_pad_381064+0x1d1b>
  4bf34f:	jmp    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bf354:	mov    %rsi,%rax
  4bf357:	shr    $0x4,%rax
  4bf35b:	test   %rdx,%rdx
  4bf35e:	je     4bf2cc <tomo_multidb2_pad_381064+0x1f77>
  4bf364:	mov    0x520(%rdx),%ecx
  4bf36a:	cmp    $0xfff,%ecx
  4bf370:	ja     4bf2cc <tomo_multidb2_pad_381064+0x1f77>
  4bf376:	mov    0x538(%rdx),%rdi
  4bf37d:	add    %rsi,%rdi
  4bf380:	cmp    $0x400000,%rdi
  4bf387:	ja     4bf2cc <tomo_multidb2_pad_381064+0x1f77>
  4bf38d:	mov    %eax,%eax
  4bf38f:	inc    %ecx
  4bf391:	add    $0x40,%rax
  4bf395:	mov    0x20(%rdx,%rax,8),%rsi
  4bf39a:	mov    %rsi,0x20(%r12)
  4bf39f:	mov    %r12,0x20(%rdx,%rax,8)
  4bf3a4:	mov    %ecx,0x520(%rdx)
  4bf3aa:	mov    %rdi,0x538(%rdx)
  4bf3b1:	jmp    4bf2d6 <tomo_multidb2_pad_381064+0x1f81>
  4bf3b6:	xor    %eax,%eax
  4bf3b8:	test   %rdx,%rdx
  4bf3bb:	jne    4bf364 <tomo_multidb2_pad_381064+0x200f>
  4bf3bd:	jmp    4bf2cc <tomo_multidb2_pad_381064+0x1f77>
  4bf3c2:	mov    0xc8(%rbp),%rax
  4bf3c9:	mov    0x28(%rsp),%rdx
  4bf3ce:	mov    %rdx,(%rax)
  4bf3d1:	test   %rdx,%rdx
  4bf3d4:	je     4bf49c <tomo_multidb2_pad_381064+0x2147>
  4bf3da:	xor    %ecx,%ecx
  4bf3dc:	mov    %rcx,0x8(%rdx)
  4bf3e0:	sub    %ebx,0x210(%rax)
  4bf3e6:	cmpq   $0x0,0x210(%rax)
  4bf3ee:	jne    4bd174 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2d4>
  4bf3f4:	jmp    4bd164 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2c4>
  4bf3f9:	mov    0xc8(%rbp),%rax
  4bf400:	test   %rax,%rax
  4bf403:	je     4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bf409:	cmpb   $0x0,0x524(%rax)
  4bf410:	je     4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bf416:	vmovq  %r12,%xmm7
  4bf41b:	mov    0x18(%rsp),%rdx
  4bf420:	lea    0x5c0(%rax),%rdi
  4bf427:	mov    %rax,0x10(%rsp)
  4bf42c:	vpinsrq $0x1,%rbp,%xmm7,%xmm0
  4bf432:	vmovdqa %xmm0,0x80(%rsp)
  4bf43b:	mov    0x80(%r12),%esi
  4bf443:	call   4a6060 <_ZN4tomo17ForeignReadSafety10close_spanIZNS_9FlatStore28read_local_pending_unpublishERNS_11AtomicEntryEEUljE_EEvjOT_>
  4bf448:	mov    0x10(%rsp),%rax
  4bf44d:	mov    0x584(%rax),%edx
  4bf453:	test   %edx,%edx
  4bf455:	je     4bf48b <tomo_multidb2_pad_381064+0x2136>
  4bf457:	dec    %edx
  4bf459:	mov    %edx,0x584(%rax)
  4bf45f:	jne    4bf47d <tomo_multidb2_pad_381064+0x2128>
  4bf461:	mov    0xc5d0(%rax),%rdx
  4bf468:	inc    %rdx
  4bf46b:	je     4bf47d <tomo_multidb2_pad_381064+0x2128>
  4bf46d:	lock btrq $0x1,0x548(%rax)
  4bf477:	jae    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bf47d:	movb   $0x0,0x89(%r12)
  4bf486:	jmp    4bf2f7 <tomo_multidb2_pad_381064+0x1fa2>
  4bf48b:	mov    0xc5d0(%rax),%rax
  4bf492:	inc    %rax
  4bf495:	je     4bf47d <tomo_multidb2_pad_381064+0x2128>
  4bf497:	jmp    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bf49c:	xor    %edx,%edx
  4bf49e:	mov    %rdx,0x8(%rax)
  4bf4a2:	jmp    4bf3e0 <tomo_multidb2_pad_381064+0x208b>
  4bf4a7:	mov    %rax,%rsi
  4bf4aa:	movabs $0xfffffffffffffff,%r8
  4bf4b4:	sub    %r12,%rsi
  4bf4b7:	mov    %rsi,%rdx
  4bf4ba:	sar    $0x3,%rdx
  4bf4be:	cmp    %r8,%rdx
  4bf4c1:	je     4bf8ca <tomo_multidb2_pad_381064+0x2575>
  4bf4c7:	cmp    %r12,%rax
  4bf4ca:	je     4bf544 <tomo_multidb2_pad_381064+0x21ef>
  4bf4cc:	lea    (%rdx,%rdx,1),%rax
  4bf4d0:	cmp    %rdx,%rax
  4bf4d3:	jb     4bf582 <tomo_multidb2_pad_381064+0x222d>
  4bf4d9:	xor    %ebx,%ebx
  4bf4db:	xor    %r13d,%r13d
  4bf4de:	test   %rax,%rax
  4bf4e1:	jne    4bf54d <tomo_multidb2_pad_381064+0x21f8>
  4bf4e3:	lea    0x8(%rbx,%rsi,1),%rax
  4bf4e8:	vmovq  %rbx,%xmm6
  4bf4ed:	mov    %rdi,(%rbx,%rsi,1)
  4bf4f1:	vpinsrq $0x1,%rax,%xmm6,%xmm5
  4bf4f7:	vmovdqa %xmm5,(%rsp)
  4bf4fc:	test   %rsi,%rsi
  4bf4ff:	jg     4bf52d <tomo_multidb2_pad_381064+0x21d8>
  4bf501:	test   %r12,%r12
  4bf504:	jne    4bf51c <tomo_multidb2_pad_381064+0x21c7>
  4bf506:	vmovdqa (%rsp),%xmm6
  4bf50b:	add    %r13,%rbx
  4bf50e:	mov    %rbx,0x48(%rbp)
  4bf512:	vmovdqu %xmm6,0x38(%rbp)
  4bf517:	jmp    4bf1dc <tomo_multidb2_pad_381064+0x1e87>
  4bf51c:	mov    0x48(%rbp),%rsi
  4bf520:	sub    %r12,%rsi
  4bf523:	mov    %r12,%rdi
  4bf526:	call   2be30 <_ZdlPvm@plt>
  4bf52b:	jmp    4bf506 <tomo_multidb2_pad_381064+0x21b1>
  4bf52d:	mov    %rsi,%rdx
  4bf530:	mov    %rbx,%rdi
  4bf533:	mov    %r12,%rsi
  4bf536:	call   2b7a0 <memmove@plt>
  4bf53b:	mov    0x48(%rbp),%rsi
  4bf53f:	sub    %r12,%rsi
  4bf542:	jmp    4bf523 <tomo_multidb2_pad_381064+0x21ce>
  4bf544:	add    $0x1,%rdx
  4bf548:	mov    %rdx,%rax
  4bf54b:	jb     4bf582 <tomo_multidb2_pad_381064+0x222d>
  4bf54d:	movabs $0xfffffffffffffff,%rdx
  4bf557:	cmp    %rdx,%rax
  4bf55a:	cmova  %rdx,%rax
  4bf55e:	lea    0x0(,%rax,8),%r13
  4bf566:	mov    %rsi,(%rsp)
  4bf56a:	mov    %r13,%rdi
  4bf56d:	call   2c120 <_Znwm@plt>
  4bf572:	mov    0x38(%r14),%rdi
  4bf576:	mov    (%rsp),%rsi
  4bf57a:	mov    %rax,%rbx
  4bf57d:	jmp    4bf4e3 <tomo_multidb2_pad_381064+0x218e>
  4bf582:	mov    %r8,%rax
  4bf585:	jmp    4bf55e <tomo_multidb2_pad_381064+0x2209>
  4bf587:	nopw   0x0(%rax,%rax,1)
  4bf590:	mov    0x78(%r13),%esi
  4bf594:	add    %r12d,%esi
  4bf597:	call   53ccb0 <_ZN4tomo23xshard_atomic_key_sliceEPKNS_12ScatterStateEj>
  4bf59c:	mov    0x28(%r13),%rdi
  4bf5a0:	mov    %rax,%r15
  4bf5a3:	vmovq  %rdx,%xmm0
  4bf5a8:	test   %rdi,%rdi
  4bf5ab:	je     4bf174 <tomo_multidb2_pad_381064+0x1e1f>
  4bf5b1:	jmp    4bf09b <tomo_multidb2_pad_381064+0x1d46>
  4bf5b6:	cmpq   $0x0,0x30(%r14)
  4bf5bb:	jne    4bed62 <tomo_multidb2_pad_381064+0x1a0d>
  4bf5c1:	inc    %r12d
  4bf5c4:	jmp    4bed62 <tomo_multidb2_pad_381064+0x1a0d>
  4bf5c9:	xor    %edx,%edx
  4bf5cb:	cmpq   $0x0,0x28(%r13)
  4bf5d0:	mov    0x50(%r13),%rcx
  4bf5d4:	mov    0x0(%r13),%rdi
  4bf5d8:	sete   %dl
  4bf5db:	xor    %esi,%esi
  4bf5dd:	cmpq   $0x0,0x30(%r13)
  4bf5e2:	sete   %sil
  4bf5e6:	call   48e2f0 <_ZN4tomo30atomic_tripwire_collapse_writeEmbbm>
  4bf5eb:	jmp    4bee5e <tomo_multidb2_pad_381064+0x1b09>
  4bf5f0:	mov    %rax,0x28(%r14)
  4bf5f4:	mov    %rdx,0x50(%r14)
  4bf5f8:	movb   $0x1,0x58(%r14)
  4bf5fd:	jmp    4bed25 <tomo_multidb2_pad_381064+0x19d0>
  4bf602:	xor    %r8d,%r8d
  4bf605:	mov    %r8,0x28(%r14)
  4bf609:	jmp    4bed62 <tomo_multidb2_pad_381064+0x1a0d>
  4bf60e:	cmpb   $0x0,0x58(%r14)
  4bf613:	jne    4bed21 <tomo_multidb2_pad_381064+0x19cc>
  4bf619:	mov    0x18(%r14),%rax
  4bf61d:	mov    %rax,0x28(%r14)
  4bf621:	jmp    4bed25 <tomo_multidb2_pad_381064+0x19d0>
  4bf626:	mov    (%rdx),%rdx
  4bf629:	jmp    4beccf <tomo_multidb2_pad_381064+0x197a>
  4bf62e:	mov    0x38(%rbx),%r14
  4bf632:	mov    %rax,%rsi
  4bf635:	movabs $0xfffffffffffffff,%rcx
  4bf63f:	sub    %r14,%rsi
  4bf642:	mov    %rsi,%rdx
  4bf645:	sar    $0x3,%rdx
  4bf649:	cmp    %rcx,%rdx
  4bf64c:	je     4bf8ca <tomo_multidb2_pad_381064+0x2575>
  4bf652:	cmp    %r14,%rax
  4bf655:	je     4bf6f7 <tomo_multidb2_pad_381064+0x23a2>
  4bf65b:	lea    (%rdx,%rdx,1),%rax
  4bf65f:	cmp    %rdx,%rax
  4bf662:	jb     4bf732 <tomo_multidb2_pad_381064+0x23dd>
  4bf668:	xor    %edi,%edi
  4bf66a:	xor    %r15d,%r15d
  4bf66d:	mov    %rdi,0x10(%rsp)
  4bf672:	test   %rax,%rax
  4bf675:	jne    4bf700 <tomo_multidb2_pad_381064+0x23ab>
  4bf67b:	lea    0x8(%r15,%rsi,1),%rax
  4bf680:	vmovq  %r15,%xmm7
  4bf685:	mov    %rbp,(%r15,%rsi,1)
  4bf689:	vpinsrq $0x1,%rax,%xmm7,%xmm6
  4bf68f:	vmovdqa %xmm6,(%rsp)
  4bf694:	test   %rsi,%rsi
  4bf697:	jg     4bf6e0 <tomo_multidb2_pad_381064+0x238b>
  4bf699:	test   %r14,%r14
  4bf69c:	jne    4bf6cf <tomo_multidb2_pad_381064+0x237a>
  4bf69e:	vmovdqa (%rsp),%xmm7
  4bf6a3:	mov    0x10(%rsp),%rcx
  4bf6a8:	add    %r15,%rcx
  4bf6ab:	vmovdqu %xmm7,0x38(%rbx)
  4bf6b0:	mov    %rcx,0x48(%rbx)
  4bf6b4:	jmp    4bf11f <tomo_multidb2_pad_381064+0x1dca>
  4bf6b9:	mov    0xc0(%rbx),%rax
  4bf6c0:	test   %rax,%rax
  4bf6c3:	je     4bf6c8 <tomo_multidb2_pad_381064+0x2373>
  4bf6c5:	incq   (%rax)
  4bf6c8:	xor    %edx,%edx
  4bf6ca:	jmp    4bf0fd <tomo_multidb2_pad_381064+0x1da8>
  4bf6cf:	mov    0x48(%rbx),%rsi
  4bf6d3:	sub    %r14,%rsi
  4bf6d6:	mov    %r14,%rdi
  4bf6d9:	call   2be30 <_ZdlPvm@plt>
  4bf6de:	jmp    4bf69e <tomo_multidb2_pad_381064+0x2349>
  4bf6e0:	mov    %rsi,%rdx
  4bf6e3:	mov    %r15,%rdi
  4bf6e6:	mov    %r14,%rsi
  4bf6e9:	call   2b7a0 <memmove@plt>
  4bf6ee:	mov    0x48(%rbx),%rsi
  4bf6f2:	sub    %r14,%rsi
  4bf6f5:	jmp    4bf6d6 <tomo_multidb2_pad_381064+0x2381>
  4bf6f7:	add    $0x1,%rdx
  4bf6fb:	mov    %rdx,%rax
  4bf6fe:	jb     4bf732 <tomo_multidb2_pad_381064+0x23dd>
  4bf700:	movabs $0xfffffffffffffff,%rdx
  4bf70a:	cmp    %rdx,%rax
  4bf70d:	cmova  %rdx,%rax
  4bf711:	shl    $0x3,%rax
  4bf715:	mov    %rsi,(%rsp)
  4bf719:	mov    %rax,%rdi
  4bf71c:	mov    %rax,0x10(%rsp)
  4bf721:	call   2c120 <_Znwm@plt>
  4bf726:	mov    (%rsp),%rsi
  4bf72a:	mov    %rax,%r15
  4bf72d:	jmp    4bf67b <tomo_multidb2_pad_381064+0x2326>
  4bf732:	movabs $0xfffffffffffffff,%rax
  4bf73c:	jmp    4bf711 <tomo_multidb2_pad_381064+0x23bc>
  4bf73e:	cmp    $0x3,%eax
  4bf741:	jbe    4bf768 <tomo_multidb2_pad_381064+0x2413>
  4bf743:	mov    -0x4(%rdi,%rax,1),%edx
  4bf747:	xor    -0x4(%rsi,%rax,1),%edx
  4bf74b:	mov    %edx,%eax
  4bf74d:	mov    (%rdi),%edx
  4bf74f:	xor    (%rsi),%edx
  4bf751:	or     %edx,%eax
  4bf753:	sete   %al
  4bf756:	jmp    4bef22 <tomo_multidb2_pad_381064+0x1bcd>
  4bf75b:	mov    %rbp,%rdi
  4bf75e:	call   47f1b0 <_ZN4tomo9FlatStore16atomic_gauge_subEm.part.0>
  4bf763:	jmp    4bee1b <tomo_multidb2_pad_381064+0x1ac6>
  4bf768:	test   %eax,%eax
  4bf76a:	je     4bef2a <tomo_multidb2_pad_381064+0x1bd5>
  4bf770:	movzbl (%rsi),%edx
  4bf773:	cmp    %dl,(%rdi)
  4bf775:	jne    4bec68 <tomo_multidb2_pad_381064+0x1913>
  4bf77b:	mov    %eax,%edx
  4bf77d:	shr    $1,%edx
  4bf77f:	movzbl (%rsi,%rdx,1),%r9d
  4bf784:	cmp    %r9b,(%rdi,%rdx,1)
  4bf788:	jne    4bec68 <tomo_multidb2_pad_381064+0x1913>
  4bf78e:	dec    %eax
  4bf790:	movzbl (%rsi,%rax,1),%edx
  4bf794:	cmp    %dl,(%rdi,%rax,1)
  4bf797:	jne    4bec68 <tomo_multidb2_pad_381064+0x1913>
  4bf79d:	jmp    4bef2a <tomo_multidb2_pad_381064+0x1bd5>
  4bf7a2:	mov    0xc8(%rbp),%rax
  4bf7a9:	mov    (%rax),%r13
  4bf7ac:	cmp    %r13,0x28(%rsp)
  4bf7b1:	jne    4bf010 <tomo_multidb2_pad_381064+0x1cbb>
  4bf7b7:	jmp    4bf1ec <tomo_multidb2_pad_381064+0x1e97>
  4bf7bc:	mov    0x8(%rbp),%r13
  4bf7c0:	mov    0x10(%rbp),%rcx
  4bf7c4:	cmp    %r13,%rcx
  4bf7c7:	jne    4bebb7 <tomo_multidb2_pad_381064+0x1862>
  4bf7cd:	jmp    4bf1ec <tomo_multidb2_pad_381064+0x1e97>
  4bf7d2:	call   2ba10 <__stack_chk_fail@plt>
  4bf7d7:	mov    0xc0(%r12),%rax
  4bf7df:	test   %rax,%rax
  4bf7e2:	je     4bf7e7 <tomo_multidb2_pad_381064+0x2492>
  4bf7e4:	incq   (%rax)
  4bf7e7:	xor    %r14d,%r14d
  4bf7ea:	mov    %r14,(%r12)
  4bf7ee:	jmp    4be588 <tomo_multidb2_pad_381064+0x1233>
  4bf7f3:	xor    %r13d,%r13d
  4bf7f6:	mov    %r13,0x8(%rax)
  4bf7fa:	jmp    4be7e7 <tomo_multidb2_pad_381064+0x1492>
  4bf7ff:	mov    0x58(%r15),%rcx
  4bf803:	jmp    4be9a9 <tomo_multidb2_pad_381064+0x1654>
  4bf808:	mov    %r12,%rdi
  4bf80b:	call   47f1b0 <_ZN4tomo9FlatStore16atomic_gauge_subEm.part.0>
  4bf810:	jmp    4bea28 <tomo_multidb2_pad_381064+0x16d3>
  4bf815:	mov    0xc8(%r12),%rbp
  4bf81d:	test   %rbp,%rbp
  4bf820:	je     4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bf826:	cmpb   $0x0,0x524(%rbp)
  4bf82d:	je     4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bf833:	vmovq  %r15,%xmm5
  4bf838:	lea    0x80(%rsp),%rdx
  4bf840:	lea    0x5c0(%rbp),%rdi
  4bf847:	vpinsrq $0x1,%r12,%xmm5,%xmm0
  4bf84d:	vmovdqa %xmm0,0x80(%rsp)
  4bf856:	mov    0x80(%r15),%esi
  4bf85d:	call   4a6060 <_ZN4tomo17ForeignReadSafety10close_spanIZNS_9FlatStore28read_local_pending_unpublishERNS_11AtomicEntryEEUljE_EEvjOT_>
  4bf862:	mov    0x584(%rbp),%edx
  4bf868:	test   %edx,%edx
  4bf86a:	je     4bf89f <tomo_multidb2_pad_381064+0x254a>
  4bf86c:	dec    %edx
  4bf86e:	mov    %edx,0x584(%rbp)
  4bf874:	jne    4bf892 <tomo_multidb2_pad_381064+0x253d>
  4bf876:	mov    0xc5d0(%rbp),%rdx
  4bf87d:	inc    %rdx
  4bf880:	je     4bf892 <tomo_multidb2_pad_381064+0x253d>
  4bf882:	lock btrq $0x1,0x548(%rbp)
  4bf88c:	jae    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bf892:	movb   $0x0,0x89(%r15)
  4bf89a:	jmp    4be6d2 <tomo_multidb2_pad_381064+0x137d>
  4bf89f:	mov    0xc5d0(%rbp),%rdx
  4bf8a6:	inc    %rdx
  4bf8a9:	je     4bf892 <tomo_multidb2_pad_381064+0x253d>
  4bf8ab:	jmp    4bdae2 <tomo_multidb2_pad_381064+0x78d>
  4bf8b0:	movabs $0x555555555555555,%rax
  4bf8ba:	cmp    %rax,%rdx
  4bf8bd:	cmovbe %rdx,%rax
  4bf8c1:	imul   $0x18,%rax,%r9
  4bf8c5:	jmp    4be0d0 <tomo_multidb2_pad_381064+0xd7b>
  4bf8ca:	mov    0x98(%rsp),%rax
  4bf8d2:	sub    %fs:0x28,%rax
  4bf8db:	jne    4bf7d2 <tomo_multidb2_pad_381064+0x247d>
  4bf8e1:	lea    0x3c076f(%rip),%rdi        # 880057 <_IO_stdin_used+0x57>
  4bf8e8:	call   2bfa0 <_ZSt20__throw_length_errorPKc@plt>
  4bf8ed:	endbr64
  4bf8f1:	mov    %rax,%rdi
  4bf8f4:	mov    %rdx,%rax
  4bf8f7:	jmp    4bf8ff <tomo_multidb2_pad_381064+0x25aa>
  4bf8f9:	endbr64
  4bf8fd:	jmp    4bf8f1 <tomo_multidb2_pad_381064+0x259c>
  4bf8ff:	dec    %rax
  4bf902:	jne    4bf916 <tomo_multidb2_pad_381064+0x25c1>
  4bf904:	vzeroupper
  4bf907:	call   2b610 <__cxa_begin_catch@plt>
  4bf90c:	call   2c290 <__cxa_end_catch@plt>
  4bf911:	jmp    4bd190 <_ZN4tomo9FlatStore15atomic_collapseEmm+0x2f0>
  4bf916:	mov    0x98(%rsp),%rax
  4bf91e:	sub    %fs:0x28,%rax
  4bf927:	jne    4bf931 <tomo_multidb2_pad_381064+0x25dc>
  4bf929:	vzeroupper
  4bf92c:	call   2c060 <_Unwind_Resume@plt>
  4bf931:	vzeroupper
  4bf934:	call   2ba10 <__stack_chk_fail@plt>

Disassembly of section .rlfence:

Disassembly of section .fini:
