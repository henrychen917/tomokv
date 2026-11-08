#!/usr/bin/env python3
"""wave16: linked-body inventory of the merged POST against PRE 8be4f68323. No server or workload.

tools/parkwake_identity.py (docs/wave9/identity.py inventory, the gate's strict normalizer
tools/wave12_normalize.py, that tool's hot selection) with the intended-body pattern widened to
the edits of all three merged lanes:
  parkwake  its own pattern (park paths, loop passes, executor control, execute's Retry arm, F10
            publications, the namespace watchdog);
  blockwake the blocking registry (cancel, strand, register/reprobe, the owner dirty re-check,
            BLMOVE resume) and its DEBUG BLOCKING-REGISTER-DEFER control;
  iowake    the TLS branch of flush_ready / r7_flush_ready (HasTls=true), the AOF and snapshot
            writers' wake edges and DEBUG LOADAOF's pumped drain.
Identity is a proxy: the command-scope census (tools/wave16_counts.py) decides zero cost.

  python3 tools/wave16_identity.py PRE POST build/wave16/identity
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import parkwake_identity as base  # noqa: E402

base.identity.OUT = ROOT / 'build/wave16/identity'
BLOCKWAKE = (r'blocking_(?:owner_dirty_pending|atomic_published|resume_move_impl|register|service|'
             r'sweep|deadline|publish_fence)|BlockingRegistry::|honour_cancel|'
             r'debug_blocking_register_defer|t_server_debug|command_debug')
IOWAKE = (r'::(?:r7_)?flush_ready<true,|AofManager::(?:writer_pass|drain_producer)\(|'
          r'AofProducer::(?:emit|record_bytes)|submit_large_frame_wake|'
          r'SnapshotManager::(?:post_chunk|writer_pass)|prepare_debug_loadaof')
base.INTENDED = re.compile(base.INTENDED.pattern + '|' + BLOCKWAKE + '|' + IOWAKE)

if __name__ == '__main__':
    base.main()
