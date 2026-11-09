"""GDB-only schedule: loading begins after CONFIG's IO validation.

Loaded by s1pair.py into the debugger, never linked into a server. This operates
on the selected, unmodified ELF (including the frozen release). All inferior
threads are stopped while changing loading_, just as at the real admission edge.

Two CONFIG SETs, one phase each. Phase 1 sets loading_ before every owner
re-check; phase 2 sets it only after the first owner fragment has decided the
SET, so the remaining fragments of an already-applied SET see a reload begin.
"""
import json
import os
from pathlib import Path
import struct

import gdb


output = Path(os.environ['S1PAIR_GDB_OUTPUT'])
namespace = os.environ['S1PAIR_GDB_NAMESPACE']
# Per phase: does the first owner re-check already see loading_?
FIRST_OWNER_LOADING = (True, False)
phases = [dict(io_checks=0, owner_checks=0, assemblies=0) for _ in FIRST_OWNER_LOADING]
current = 0


def server():
    return gdb.parse_and_eval("'%s::(anonymous namespace)::g_server'" % namespace).dereference()


def loading(value):
    flag = server()['loading_']['_M_i']
    gdb.selected_inferior().write_memory(int(flag.address), struct.pack('I', value))


class Validate(gdb.Breakpoint):
    def stop(self):
        state = phases[current]
        frame = gdb.newest_frame()
        owner = False
        while frame:
            owner |= '::cmd_config' in (frame.name() or '')
            frame = frame.older()
        if owner:
            assert state['io_checks'] == 1, phases
            state['owner_checks'] += 1
            if FIRST_OWNER_LOADING[current] or state['owner_checks'] > 1:
                loading(1)
        else:
            state['io_checks'] += 1
            assert int(server()['loading_']['_M_i']) == 0
        return False


class Assemble(gdb.Breakpoint):
    def stop(self):
        global current
        if phases[current]['owner_checks']:
            loading(0)
            phases[current]['assemblies'] += 1
            current += 1
            output.with_suffix('.json').write_text(json.dumps(phases[:current]) + '\n')
            if current == len(phases):
                validate.enabled = False
                self.enabled = False
        return False


gdb.execute('set pagination off')
gdb.execute('set confirm off')
gdb.execute('handle SIGTERM nostop noprint pass')
gdb.execute('start')
output.with_suffix('.pid').write_text(str(gdb.selected_inferior().pid))
validate = Validate('%s::(anonymous namespace)::collect_config_updates' % namespace,
                    internal=True)
assemble = Assemble('%s::command_config_apply_reply' % namespace, internal=True)
gdb.execute('continue')
