"""Resolve verified literal bytes, bounded memory switches and assembly sections.

Extends wave10's strict normalizer. Opcodes, widths, registers, member offsets,
branch conditions and all local destinations still participate in comparison.
"""
import re
import struct
import subprocess
from lbstall_artifacts import Elf
from wave10_normalize import install as install_wave10


def install(audit):
    install_wave10(audit)
    original = audit.LiteralPools

    class Pools(original):
        def __init__(self, path, nm):
            super().__init__(path, nm)
            elf = Elf(path)
            self.fence = None
            if '.rlfence' in elf.names:
                section = elf.sections[elf.names.index('.rlfence')]
                listing = subprocess.check_output(['objdump', '-d', '-w', '-j', '.rlfence', str(path)], text=True)
                boundaries = {int(m[1], 16) for line in listing.splitlines()
                              if (m := audit.INSTRUCTION.match(line))}
                self.fence = section[3], section[5], boundaries

        def label(self, asm):
            found = super().label(asm)
            if found:
                return found
            # The target must be actual unnamed read-only data; compare all
            # eight loaded bytes, never the neighbouring symbol's stale label.
            m = re.fullmatch(r'mov\s+-?0x[0-9a-f]+\(%rip\),%(r(?:[abcd]x|[sd]i|[bs]p|[89]|1[0-5]))\s+#\s+([0-9a-f]+) <[^<>]+>', asm)
            if m:
                raw = self.literal(int(m[2], 16), 8)
                if raw is not None:
                    return 'literal-load-' + raw.hex()
            m = re.fullmatch(r'jmp\s+([0-9a-f]+) <[^<>]+>', asm)
            if m and self.fence:
                start, size, boundaries = self.fence
                target = int(m[1], 16)
                if start <= target < start+size and target in boundaries:
                    return 'assembly-.rlfence+' + hex(target-start)
            return None

        def jump_label(self, index, body, instructions, addr, size):
            found = super().jump_label(index, body, instructions, addr, size)
            if found:
                return found
            if index < 4 or index+3 >= len(body):
                return None
            ins = [instructions[x][1] for x in body]
            bound = re.fullmatch(r'cmpb\s+\$0x([0-9a-f]+),\(%(\w+)\)', ins[index-4])
            saved = re.fullmatch(r'mov\s+%(\w+),%(\w+)', ins[index-3])
            loaded = re.fullmatch(r'movzbl\s+\(%(\w+)\),%(e[abcd]x)', ins[index-1])
            lea = re.fullmatch(r'lea\s+-?0x[0-9a-f]+\(%rip\),%(\w+)\s+#\s+([0-9a-f]+) <[^<>]+>', ins[index])
            if not (bound and saved and loaded and lea and ins[index-2].startswith('ja ')):
                return None
            if loaded[1] != bound[2] or saved[2] == bound[2]:
                return None
            register = 'r'+loaded[2][1:]
            table = re.fullmatch(r'movslq\s+\(%(\w+),%(\w+),4\),%(\w+)', ins[index+1])
            if not table or (table[1], table[2]) != (lea[1], register):
                return None
            if ' '.join(ins[index+2].split()) != f'add %{lea[1]},%{table[3]}':
                return None
            if ' '.join(ins[index+3].split()) not in (f'jmp *%{table[3]}', f'notrack jmp *%{table[3]}'):
                return None
            count, target = int(bound[1], 16)+1, int(lea[2], 16)
            if not 1 <= count <= 256:
                return None
            raw = self.literal(target, count*4)
            if raw is None:
                return None
            destinations = [target+x[0] for x in struct.iter_unpack('<i', raw)]
            if any(not addr <= x < addr+size or x not in instructions for x in destinations):
                return None
            return 'bounded-memory-switch-' + ','.join(hex(x-addr) for x in destinations)

    audit.LiteralPools = Pools
