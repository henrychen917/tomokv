"""Known instruction-count control for the scope PMU diagnostic, under GDB."""
import fcntl,gdb,json,os,struct,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from trace_pmu import counters,fds
for c in ('set pagination off','set confirm off','set print thread-events off','set debuginfod enabled off'):gdb.execute(c)
gdb.execute('starti',to_string=True)
addresses={name:int(gdb.parse_and_eval('(unsigned long)&'+name)) for name in ('leaf','nested')}
bs=[gdb.Breakpoint('*'+hex(x),internal=True) for x in addresses.values()]
rows=[]
for name,expected in [('leaf',129),('nested',131)]:
 gdb.execute('continue',to_string=True)
 assert int(gdb.parse_and_eval('$pc'))==addresses[name]
 retaddr=int.from_bytes(gdb.selected_inferior().read_memory(int(gdb.parse_and_eval('$rsp')),8).tobytes(),'little')
 for bp in bs:bp.enabled=False
 gdb.Breakpoint('*'+hex(retaddr),internal=True,temporary=True)
 fd=counters(gdb.selected_thread().ptid[1]);fcntl.ioctl(fd,0x2403,1);fcntl.ioctl(fd,0x2400,1)
 gdb.execute('continue',to_string=True);fcntl.ioctl(fd,0x2401,1)
 nr,en,run,ins,cycles=struct.unpack('=5Q',os.read(fd,40))
 rows.append(dict(name=name,expected=expected,raw_instructions=ins,instructions=ins-1,cycles=cycles,enabled=en,running=run))
 assert en==run and ins==expected+1,(name,expected,ins)
 for bp in bs:bp.enabled=True
Path('docs/wave4d/trace-calibration.json').write_text(json.dumps(rows,indent=2)+'\n')
gdb.execute('kill',to_string=True)
