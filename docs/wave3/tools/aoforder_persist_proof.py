#!/usr/bin/env python3
"""Lane-local replay of existing persistence batteries; no gate/benchmark runner.

wave3 copy of docs/aoforder/persist_proof.py: only CPUs (servers 80-87, drivers 89-95) and the
port (22870) differ. Run from the worktree root."""
import argparse, contextlib, hashlib, json, os, pathlib, signal, subprocess, sys, time, traceback
sys.path.insert(0, str(pathlib.Path.cwd() / 'tests'))
import aoffix2 as h

parser=argparse.ArgumentParser()
parser.add_argument('--binary',type=pathlib.Path,required=True)
parser.add_argument('--output',type=pathlib.Path,required=True)
parser.add_argument('--part',choices=('primary','drivers','rewrite','snapshot','supplementary'),required=True)
args=parser.parse_args()
root=args.output.resolve(); root.mkdir(parents=True,exist_ok=False)
binary=args.binary.resolve(); results=[]
env=dict(os.environ,TMPDIR=str(root),TOMO_GATE_STRICT='1',GATE_CANDIDATE_BINARY=str(binary),GATE_CORES='80-87',GATE_LOAD_CORES='89-95',GATE_PORT='22870',NET_IO='uring')

def command(argv, log, extra=None):
    argv=['taskset','-c','89-95',*map(str,argv)]
    with pathlib.Path(log).open('a') as f:
        f.write(json.dumps(dict(command=argv))+'\n'); f.flush()
        r=subprocess.run(argv,env=env|dict(extra or {}),stdout=f,stderr=subprocess.STDOUT)
    if r.returncode: raise AssertionError(f'{argv}: exit {r.returncode}; see {log}')

def cell(label, fn):
    folder=root/label; folder.mkdir(); start=time.monotonic()
    try:
        with (folder/'console.log').open('w') as log,contextlib.redirect_stdout(log): fn(folder)
        status='PASS'; error=None
    except Exception as exc:
        status='FAIL'; error=str(exc); (folder/'failure.txt').write_text(traceback.format_exc())
    results.append(dict(label=label,status=status,error=error,seconds=time.monotonic()-start))
    (root/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
    print(label,status,error or '',flush=True)

def setup(folder,mode,db,engine='uring'):
    h.ARGS=argparse.Namespace(binary=binary,artifacts=folder,mode=mode,databases=db,engine=engine,cores='80-87',ratio='6:2',port=22870,oracle=False,policy='everysec')

def primary(folder, mode, atomic, db, engine):
    setup(folder,mode,db,engine)
    options=h.aof('no')+['--atomic',str(atomic),'--databases',str(db)]
    state=folder/'data/state.json'
    with h.Server(options) as server:
        for phase in ('populate','loadaof'):
            command(['python3','tests/aof.py','127.0.0.1','22870',phase,state],folder/'battery.log')
        assert int(server.client().info()['aof_records_written'])>0
        server.stop(signal.SIGKILL)
    with h.Server(options) as server:
        command(['python3','tests/aof.py','127.0.0.1','22870','verify',state],folder/'battery.log')
        assert int(server.client().info()['aof_replayed_records'])>0
    for policy,count in [('everysec',512),('always',512),('no',128)]:
        data=folder/('sync-'+policy); syncstate=data/'state.json'
        opt=h.aof(policy)+['--atomic',str(atomic),'--databases',str(db)]
        with h.Server(opt,data=data) as server:
            command(['python3','tests/aof_fsync.py','127.0.0.1','22870','populate',syncstate,policy,count],folder/'sync.log')
            if policy!='no': server.stop(signal.SIGKILL)
        if policy=='no': continue
        if policy=='everysec':
            file=data/'appendonlydir/appendonly.aof.1.incr.tomo'
            with file.open('r+b') as f: f.truncate(file.stat().st_size-7)
        with h.Server(opt,data=data) as server:
            command(['python3','tests/aof_fsync.py','127.0.0.1','22870','verify',syncstate,policy,count],folder/'sync.log')
            if policy=='everysec': assert 'AOF warning: truncated AOF tail' in server.logpath.read_text()
    if atomic:
        data=folder/'torn'; state=data/'state.json'
        with h.Server(options,data=data) as server:
            command(['python3','tests/aof_torn_group.py','127.0.0.1','22870','prepare',state],folder/'torn.log')
            server.p.wait(timeout=10)
        with h.Server(options,data=data) as server:
            command(['python3','tests/aof_torn_group.py','127.0.0.1','22870','verify',state],folder/'torn.log')
            command(['python3','tests/aof_torn_group.py','127.0.0.1','22870','scan',data/'appendonlydir/appendonly.aof.1.incr.tomo'],folder/'torn.log')
    if db == 16:
        with h.Server(options,data=folder/'multidb') as server:
            command(['python3','tests/multidb.py','127.0.0.1','22870','--read-local','0','--persistence'],folder/'multidb.log')
    setup(folder,mode,db,'epoll')
    with h.Server(h.aof('no')+['--atomic',str(atomic),'--databases',str(db),'--aof-timestamp-enabled','no'],data=folder/'frame') as server:
        command(['python3','tests/aof_frame_order.py','127.0.0.1','22870',server.data/'appendonlydir'],folder/'frame.log')

def snapshot(folder,mode,db,atomic,engine):
    setup(folder,mode,db,engine)
    options=['--atomic',str(atomic),'--databases',str(db),'--appendonly','no']
    with h.Server(options+['--dbfilename','cut.tomo'],data=folder/'cut') as server:
        command(['python3','tests/snap_cut_battery.py','22870','save'],folder/'cut.log')
    with h.Server(options+['--dbfilename','cut.tomo'],data=folder/'cut') as server:
        command(['python3','tests/snap_cut_battery.py','22870','verify_cut'],folder/'cut.log')
    with h.Server(options+['--dbfilename','groups.tomo'],data=folder/'groups') as server:
        shape,count=('mset',5) if atomic else ('exec',3)
        command(['python3','tests/snap_cut_battery.py','22870','atomic_groups',server.data/'groups.tomo',shape,count],folder/'groups.log')
        assert 'ATOMIC_GROUP_CUT PASS' in (folder/'groups.log').read_text()
    with h.Server(options+['--dbfilename','typed.tomo'],data=folder/'typed') as server:
        command(['python3','tests/snap_typed_roundtrip.py','22870','build_save'],folder/'typed.log')
    with h.Server(options+['--dbfilename','typed.tomo'],data=folder/'typed') as server:
        command(['python3','tests/snap_typed_roundtrip.py','22870','verify'],folder/'typed.log')
    # This gate oracle explicitly requires atomic=0: it tests forced EXEC admission.
    # Atomic=1 is covered above by the MSET cut and typed snapshot batteries.
    if atomic:
        print('Typed race oracle has its gate purpose boot at atomic=0; covered by the atomic=0 cells.')
        return
    with h.Server(options+['--dbfilename','race.tomo'],data=folder/'race') as server:
        command(['python3','tests/snap_typed_race.py','22870','race',server.data/'race.tomo'],folder/'race.log')
        log=(folder/'race.log').read_text(); assert 'PREIMAGE-FIRED PASS' in log and 'SNAPSHOT-TICKET-ORACLE PASS' in log
    with h.Server(options+['--dbfilename','race.tomo.cut'],data=folder/'race') as server:
        command(['python3','tests/snap_typed_race.py','22870','verify',server.data/'race.tomo.oracle.json'],folder/'race.log')

def supplementary(folder,mode,db,atomic,engine):
    setup(folder,mode,db,engine)
    options=h.aof('no')+['--atomic',str(atomic),'--databases',str(db),'--dbfilename','dump.tomo']
    state=folder/'data/state.json'
    with h.Server(options) as server:
        command(['python3','tests/aof.py','127.0.0.1','22870','populate',state],folder/'populate.log')
        command(['python3','tests/aof.py','127.0.0.1','22870','loadaof',state],folder/'populate.log')
        command(['python3','tests/aof.py','127.0.0.1','22870','snapshot',server.data/'dump.tomo'],folder/'pre-model.log')
        assert int(server.client().info()['aof_records_written'])>0
        server.stop(signal.SIGKILL)
    with h.Server(options) as server:
        command(['python3','tests/aof.py','127.0.0.1','22870','verify',state],folder/'verify.log')
        command(['python3','tests/aof.py','127.0.0.1','22870','snapshot',server.data/'dump.tomo'],folder/'post-model.log')
        info=server.client().info();assert int(info['aof_replayed_records'])>0 and 'aof_groups_skipped_on_replay' in info
    models=[]
    for name in ('pre-model.log','post-model.log'):
        rows=[line for line in (folder/name).read_text().splitlines() if line.startswith('SNAPSHOT BYTE MODEL: ')]
        assert len(rows)==1;models.append(rows[0])
    assert models[0]==models[1], 'native snapshot byte model differs after AOF replay'
    options=['--appendonly','no','--atomic',str(atomic),'--databases',str(db)]
    with h.Server(options,data=folder/'aof-off') as server:
        client=server.client();assert client.cmd('SET','aof-negative-control','must-disappear')==b'OK'
        assert client.cmd('DBSIZE')==1;server.stop(signal.SIGKILL)
    with h.Server(options,data=folder/'aof-off') as server:
        assert server.client().cmd('DBSIZE')==0
        assert not (server.data/'appendonlydir').exists()
    if mode=='2s':
        # knobs.py asserts the gate's split/default-LB purpose boot by design.
        with h.Server(h.aof('no')+['--atomic',str(atomic),'--databases',str(db),'--key-lb','1','--client-lb','1'],data=folder/'knobs') as server:
            command(['python3','tests/knobs.py','127.0.0.1','22870',engine,atomic],folder/'knobs.log')
    print('Native snapshot byte model, AOF-off negative control, and applicable configuration purpose boot PASS')

if args.part=='supplementary':
    for mode in ('1s','2s'):
        for db in (1,16):
            for atomic in (0,1):
                for engine in ('uring','epoll'):
                    cell(f'{mode}-db{db}-a{atomic}-{engine}',lambda f,m=mode,d=db,a=atomic,e=engine:supplementary(f,m,d,a,e))
elif args.part=='primary':
    for mode in ('1s','2s'):
        for db in (1,16):
            for atomic in (0,1):
                for engine in ('uring','epoll'):
                    cell(f'{mode}-db{db}-a{atomic}-{engine}',lambda f,m=mode,d=db,a=atomic,e=engine:primary(f,m,a,d,e))
elif args.part=='drivers':
    for engine in ('uring','epoll'):
        for mode in ('1s','2s'):
            for case in ('snapshot','filename','error','tickets','exec_tickets','resurrection','rewrite_fail2','manifest_missing','large'):
                cell(f'aoffix2-{engine}-{mode}-{case}',lambda f,e=engine,m=mode,c=case:command(['python3','tests/aoffix2.py',c,'--binary',binary,'--mode',m,'--engine',e,'--cores','80-87','--ratio','6:2','--port','22870','--artifacts',f/'run'],f/'battery.log'))
            for case in ('kill','term'):
                cell(f'persistfix-{engine}-{mode}-{case}',lambda f,e=engine,m=mode,c=case:command(['python3','tests/persistfix.py','--case',c,'--binary',binary,'--mode',m,'--net-io',e,'--cores','80-87','--ratio','6:2','--port','22870','--artifacts',f/'run'],f/'battery.log'))
            for policy in ('everysec','always'):
                cell(f'ack-{engine}-{mode}-{policy}',lambda f,e=engine,m=mode,p=policy:command(['python3','tests/aoffix2.py','latency','--policy',p,'--binary',binary,'--mode',m,'--engine',e,'--cores','80-87','--ratio','6:2','--port','22870','--artifacts',f/'run'],f/'battery.log'))
            for db in (1,16):
                for atomic in (0,1):
                    cell(f'savefix-{engine}-{mode}-db{db}-a{atomic}',lambda f,e=engine,m=mode,d=db,a=atomic:command(['python3','tests/savefix.py','--case','rewrite','--binary',binary,'--mode',m,'--atomic',a,'--databases',d,'--net-io',e,'--cores','80-87','--ratio','6:2','--port','22870','--output',f/'run'],f/'battery.log'))
        cell(f'large-placed-{engine}',lambda f,e=engine:command(['python3','tests/aoffix2.py','large_placed','--binary',binary,'--mode','1s','--engine',e,'--cores','80-87','--port','22870','--artifacts',f/'run'],f/'battery.log'))
elif args.part=='rewrite':
    # The gate's shell matrices derive 4:4. A transparent argv wrapper supplies this task's
    # required 6:2 or fused shape and database count; every battery/assertion remains untouched.
    wrapper=root/'server-wrapper'; wrapper.write_text('#!/usr/bin/env python3\nimport os,sys\na=sys.argv[1:]\nwhile "--ratio" in a:\n i=a.index("--ratio");del a[i:i+2]\na += ["--thread-mode",os.environ["AOFORDER_MODE"],"--databases",os.environ["AOFORDER_DATABASES"]]\nif os.environ["AOFORDER_MODE"]=="2s":a += ["--ratio","6:2"]\nos.execv(os.environ["AOFORDER_BINARY"],[os.environ["AOFORDER_BINARY"],*a])\n'); wrapper.chmod(0o755)
    for engine in ('uring','epoll'):
        for mode in ('1s','2s'):
            for db in (1,16):
                for battery in ('aof_rewrite_matrix.sh','aof_rewrite_trigger_matrix.sh'):
                    cell(f'{engine}-{mode}-db{db}-{battery}',lambda f,e=engine,m=mode,d=db,b=battery:command(['bash','tests/'+b],f/'battery.log',dict(TMPDIR=str(f),NET_IO=e,GATE_CANDIDATE_BINARY=str(wrapper),AOFORDER_MODE=m,AOFORDER_DATABASES=str(d),AOFORDER_BINARY=str(binary))))
else:
    for mode in ('1s','2s'):
        for db in (1,16):
            for atomic in (0,1):
                for engine in ('uring','epoll'):
                    cell(f'{mode}-db{db}-a{atomic}-{engine}',lambda f,m=mode,d=db,a=atomic,e=engine:snapshot(f,m,d,a,e))
    for mode in ('1s','2s'):
        cell(f'shutdown-{mode}',lambda f,m=mode:command(['python3','tests/shutdown_persist.py','--binary',binary,'--cores','80-87','--port','22870','--mode',m,'--case','all','--ratio','6:2','--output',f/'run'],f/'battery.log'))
        for action in ('sigterm','command'):
            cell(f'savefix-acks-{mode}-{action}',lambda f,m=mode,a=action:command(['python3','tests/savefix.py','--binary',binary,'--cores','80-87','--port','22870','--mode',m,'--case','acks','--action',a,'--ratio','6:2','--output',f/'run'],f/'battery.log'))
        for atomic in (0,1):
            cell(f'savefix-bgsave-{mode}-{atomic}',lambda f,m=mode,a=atomic:command(['python3','tests/savefix.py','--binary',binary,'--cores','80-87','--port','22870','--mode',m,'--case','bgsave','--atomic',a,'--ratio','6:2','--output',f/'run'],f/'battery.log'))
(root/'binary.json').write_text(json.dumps(dict(binary=str(binary),sha256=hashlib.sha256(binary.read_bytes()).hexdigest()),indent=2)+'\n')
raise SystemExit(any(r['status']!='PASS' for r in results))
