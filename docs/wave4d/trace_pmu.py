"""Pinned per-TID user-only instruction/cycle counters for debugger scopes."""
import ctypes,os
class Attr(ctypes.Structure):
    _fields_ = [('type',ctypes.c_uint32),('size',ctypes.c_uint32),('config',ctypes.c_uint64),
                ('sample_period',ctypes.c_uint64),('sample_type',ctypes.c_uint64),
                ('read_format',ctypes.c_uint64),('flags',ctypes.c_uint64),
                ('wakeup',ctypes.c_uint32),('bp_type',ctypes.c_uint32),('config1',ctypes.c_uint64)]
libc=ctypes.CDLL(None,use_errno=True)
libc.syscall.restype=ctypes.c_long
fds={}
def counters(tid):
    if tid not in fds:
        group=[]
        for event in (1,0):
            attr=Attr(type=0,size=64,config=event,read_format=1|2|8,
                      flags=(1|4|32|64) if not group else (32|64))
            fd=libc.syscall(ctypes.c_long(298),ctypes.byref(attr),ctypes.c_int(tid),
                            ctypes.c_int(-1),ctypes.c_int(group[0] if group else -1),ctypes.c_ulong(8))
            if fd<0: raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))
            group.append(fd)
        fds[tid]=group
    return fds[tid][0]
