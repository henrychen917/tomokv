#!/usr/bin/env python3
"""Negative controls for the census's extra resolved address operands."""
import struct, sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import reorder_noop as audit
from rlfix4_normalize import install, STATE
install(audit)
class ResolvedOperands(unittest.TestCase):
 def pools(self,data):
  p=audit.LiteralPools.__new__(audit.LiteralPools);p.named=[];p.sections=[(0x2000,data)];return p
 def test_scalar_bytes_width_and_named_overlap(self):
  ins='mov 0x1000(%rip),%rax # 2000 <unrelated+0x100>'
  p=self.pools(b'12345678');label=p.label(ins)
  self.assertEqual(label,'literal-load-3132333435363738')
  self.assertNotEqual(label,self.pools(b'12345679').label(ins))
  self.assertIsNone(p.label(ins.replace('%rax','%eax')))
  p.named=[(0x2007,0x2010)];self.assertIsNone(p.label(ins))
 def test_switch_changes_and_missing_bound(self):
  words=['nop','cmpb $0x1,(%rdi)','ja 1080 <outside>','movzbl (%rdi),%eax',
         'lea 0xff0(%rip),%rdx # 2000 <unrelated>',
         'movslq (%rdx,%rax,4),%rax','add %rdx,%rax','jmp *%rax','ret','ret']
  body=[0x1000+i for i in range(len(words))];ins={a:('90',s) for a,s in zip(body,words)}
  p=self.pools(struct.pack('<ii',0x1008-0x2000,0x1009-0x2000))
  before=p.jump_label(4,body,ins,0x1000,10);self.assertEqual(before,'local-switch-0x8,0x9')
  q=self.pools(struct.pack('<ii',0x1008-0x2000,0x1008-0x2000))
  self.assertNotEqual(before,q.jump_label(4,body,ins,0x1000,10))
  q=self.pools(struct.pack('<ii',0x1008-0x2000,0x1100-0x2000))
  self.assertIsNone(q.jump_label(4,body,ins,0x1000,10))
  ins[body[1]]=('90','nop');self.assertIsNone(p.jump_label(4,body,ins,0x1000,10))
 def test_assembly_target_offset_and_opcode(self):
  STATE.regions=[(0x2000,0x2020,'.rlfence')]
  norm=lambda s:audit.normalize_asm(s,0x1000,0x100,{})
  self.assertEqual(norm('jmp 2004 <nearest+0x144>'),'jmp <.rlfence+0x4>')
  self.assertNotEqual(norm('jmp 2004 <x>'),norm('jmp 2005 <x>'))
  self.assertNotEqual(norm('jmp 2004 <x>'),norm('je 2004 <x>'))
if __name__=='__main__':unittest.main()
