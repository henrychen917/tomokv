"""GDB-only schedule: loading begins after CONFIG's IO validation.

Loaded by s1pair.py into the debugger, never linked into a server. This operates
on the selected, unmodified ELF (including the frozen release). All inferior
threads are stopped while changing loading_, just as at the real admission edge.
"""
import json
import os
from pathlib import Path
import struct

import gdb


output = Path(os.environ['S1PAIR_GDB_OUTPUT'])
namespace = os.environ['S1PAIR_GDB_NAMESPACE']
state = dict(io_checks=0, owner_checks=0, assemblies=0)


def loading(value):
    server = gdb.parse_and_eval("'%s::(anonymous namespace)::g_server'" % namespace)
    flag = server.dereference()['loading_']['_M_i']
    gdb.selected_inferior().write_memory(int(flag.address), struct.pack('I', value))


class Validate(gdb.Breakpoint):
    def stop(self):
        frame = gdb.newest_frame()
        owner = False
        while frame:
            owner |= '::cmd_config' in (frame.name() or '')
            frame = frame.older()
        if owner:
            assert state['io_checks'] == 1, state
            state['owner_checks'] += 1
            loading(1)
        else:
            state['io_checks'] += 1
            server = gdb.parse_and_eval("'%s::(anonymous namespace)::g_server'" % namespace)
            assert int(server.dereference()['loading_']['_M_i']) == 0
        return False


class Assemble(gdb.Breakpoint):
    def stop(self):
        if state['owner_checks']:
            loading(0)
            state['assemblies'] += 1
            output.with_suffix('.json').write_text(json.dumps(state) + '\n')
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
