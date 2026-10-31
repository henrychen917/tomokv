"""Wave11's exact normalizer with a cheap necessary switch-candidate filter.

All three inherited switch recognizers require a RIP-relative LEA at index.
Reject other opcodes before their whole-body list construction. This changes
neither accepted patterns nor any normalized instruction/encoding.
"""
from wave11_normalize import install as install_wave11


def install(audit):
    install_wave11(audit)
    original = audit.LiteralPools

    class Pools(original):
        def jump_label(self, index, body, instructions, addr, size):
            if not instructions[body[index]][1].startswith('lea'):
                return None
            return super().jump_label(index, body, instructions, addr, size)

    audit.LiteralPools = Pools
