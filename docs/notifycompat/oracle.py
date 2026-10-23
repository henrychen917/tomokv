#!/usr/bin/env python3
"""Reproduction only. Acceptance runs use gate.sh's whole-job interface."""
import argparse
from pathlib import Path
import socket
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('case')
args = parser.parse_args()
root = Path('build/notifycompat-oracle')
root.mkdir(exist_ok=True)
with (root / 'server.log').open('w') as log:
    process = subprocess.Popen([
        'taskset', '-c', '60-63', '/home/user/Projects/redis74/src/redis-server',
        '--port', '32890', '--bind', '127.0.0.1', '--save', '', '--appendonly', 'no',
        '--enable-debug-command', 'yes', '--dir', str(root.resolve())],
        stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            assert process.poll() is None, 'oracle exited'
            try:
                with socket.create_connection(('127.0.0.1', 32890), .1):
                    break
            except OSError:
                time.sleep(.05)
        subprocess.run(['taskset', '-c', '56-59', 'python3', 'tests/notifycompat.py',
                        '127.0.0.1', '32890', '--case', args.case], check=True)
    finally:
        process.terminate()
        process.wait(timeout=10)
