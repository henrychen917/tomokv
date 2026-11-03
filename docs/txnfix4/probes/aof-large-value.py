import os, signal, subprocess, sys, tempfile, threading, time
sys.path.insert(0, '/home/user/Projects/cx-txnfix4/tests')
from _lib import Conn, wait_ready
binary, size_mb = sys.argv[1], int(sys.argv[2])
port = 21490
work = tempfile.mkdtemp(prefix='bigset-', dir='/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/hang')
flags = ['--port', str(port), '--bind', '127.0.0.1', '--dir', work, '--save', '', '--appendonly', 'yes',
         '--shards', '16', '--databases', '16', '--atomic', '0', '--read-local', '0', '--flip-auto', '0',
         '--enable-debug-command', 'yes', '--ratio', '6:2']
proc = subprocess.Popen(['taskset', '-c', '61-68', binary] + flags, stdout=open(work + '/log', 'w'),
                        stderr=subprocess.STDOUT, env=dict(os.environ, LC_ALL='C'))
pings = []
stop = threading.Event()
def pinger():
    while not stop.is_set():
        t0 = time.monotonic()
        try:
            r = Conn('127.0.0.1', port, timeout=5).cmd('PING')
        except (OSError, EOFError) as e:
            r = type(e).__name__
        pings.append((round(time.monotonic() - start, 1), r, round(time.monotonic() - t0, 2)))
        stop.wait(10)
try:
    c = wait_ready('127.0.0.1', port, timeout=60, process=proc)
    c.sock.settimeout(60)
    start = time.monotonic()
    th = threading.Thread(target=pinger, daemon=True); th.start()
    try:
        r = c.cmd('SETRANGE', 'big', size_mb * 1024 * 1024 - 1, 'x')
    except (OSError, EOFError) as e:
        r = f'no reply ({type(e).__name__})'
    el = time.monotonic() - start
    stop.set(); th.join(timeout=10)
    print(f'{size_mb} MiB SETRANGE with appendonly yes: reply={r!r} after {el:.1f}s; pings={pings}')
finally:
    proc.send_signal(signal.SIGTERM)
    try: proc.wait(timeout=30)
    except subprocess.TimeoutExpired: proc.kill(); proc.wait(); print('needed SIGKILL')
