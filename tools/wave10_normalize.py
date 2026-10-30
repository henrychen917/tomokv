"""Resolve actual literal bytes and bounded switch destinations for body binding.

This supplements the strict gate normalizer. It never removes instructions,
padding, register choices, immediates, member offsets, or branch destinations.
"""
import bisect
import re
import struct
import subprocess


def install(audit):
    original = audit.LiteralPools

    class Pools(original):
        def __init__(self, path, nm):
            super().__init__(path, nm)
            functions = []
            for line in nm.splitlines():
                fields = line.split(None, 3)
                if len(fields) == 4 and fields[2] in 'tTwW':
                    functions.append((int(fields[0], 16), int(fields[1], 16), fields[3]))
            names = subprocess.check_output(['c++filt'], input='\n'.join(f[2] for f in functions), text=True).splitlines()
            self.functions = sorted((at, size, audit.canonical(name))
                                    for (at, size, _), name in zip(functions, names))
            self.starts = [f[0] for f in self.functions]

        def literal(self, target, width):
            if any(a < target + width and target < b for a, b in self.named):
                return None
            for start, data in self.sections:
                offset = target - start
                if 0 <= offset <= len(data) - width:
                    return data[offset:offset + width]
            return None

        def label(self, asm):
            found = super().label(asm)
            if found:
                return found
            match = re.fullmatch(r'(fldt|vandpd)\s+-?0x[0-9a-f]+\(%rip\)(?:,%xmm\d+,%xmm\d+)?\s+#\s+([0-9a-f]+) <[^<>]+>', asm)
            if not match:
                return None
            raw = self.literal(int(match[2], 16), 10 if match[1] == 'fldt' else 16)
            return 'literal-load-' + raw.hex() if raw is not None else None

        def jump_label(self, index, body, instructions, addr, size):
            found = super().jump_label(index, body, instructions, addr, size)
            if found:
                return found
            if index < 2 or index + 3 >= len(body):
                return None
            ins = [instructions[x][1] for x in body]
            lea = re.fullmatch(r'lea\s+-?0x[0-9a-f]+\(%rip\),%(\w+)\s+#\s+([0-9a-f]+) <[^<>]+>', ins[index])
            bound = re.fullmatch(r'cmp\s+\$0x([0-9a-f]+),%(\w+)', ins[index-2])
            if not lea or not bound or not ins[index-1].startswith('ja '):
                return None
            count = int(bound[1], 16) + 1
            if not 1 <= count <= 4096:
                return None
            families = {r: family for family, names in {
                'rax': ('rax','eax','ax','al'), 'rbx': ('rbx','ebx','bx','bl'),
                'rcx': ('rcx','ecx','cx','cl'), 'rdx': ('rdx','edx','dx','dl'),
                'rsi': ('rsi','esi','si','sil'), 'rdi': ('rdi','edi','di','dil'),
                **{f'r{i}': (f'r{i}',f'r{i}d',f'r{i}w',f'r{i}b') for i in range(8,16)}
            }.items() for r in names}
            source = families.get(bound[2])
            cursor = index + 1
            extend = re.fullmatch(r'movzbl\s+%(\w+),%(\w+)', ins[cursor])
            if extend:
                if extend[1] != bound[2]:
                    return None
                source = families.get(extend[2])
                cursor += 1
            # classify_keys saves an unrelated pointer between extension/load.
            move = re.fullmatch(r'mov\s+%(\w+),%(\w+)', ins[cursor])
            if move and families.get(move[2]) not in (source, lea[1]):
                cursor += 1
            if cursor + 2 >= len(body):
                return None
            load = re.fullmatch(r'movslq\s+\(%(\w+),%(\w+),4\),%(\w+)', ins[cursor])
            if not load or (load[1], load[2]) != (lea[1], source):
                return None
            if ' '.join(ins[cursor+1].split()) != f'add %{lea[1]},%{load[3]}':
                return None
            if ' '.join(ins[cursor+2].split()) not in (f'jmp *%{load[3]}', f'notrack jmp *%{load[3]}'):
                return None
            target = int(lea[2], 16)
            raw = self.literal(target, count * 4)
            if raw is None:
                return None
            labels = []
            for (offset,) in struct.iter_unpack('<i', raw):
                destination = target + offset
                if destination not in instructions:
                    return None
                if addr <= destination < addr + size:
                    labels.append('local+' + hex(destination-addr))
                else:
                    at = bisect.bisect_right(self.starts, destination) - 1
                    if at < 0:
                        return None
                    start, length, name = self.functions[at]
                    if not start <= destination < start + length:
                        return None
                    labels.append(name + '+' + hex(destination-start))
            return 'bounded-switch-' + ','.join(labels)

    audit.LiteralPools = Pools
