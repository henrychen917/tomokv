#!/usr/bin/env python3
"""Compile/run throwaway SERVERLESS boot-helper controls; never start a server."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/cleanup-boot/serverless-controls')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = out / 'source'
    shutil.copytree(ROOT / 'src', source / 'src', dirs_exist_ok=True)
    header = source / 'src/core/boot_support.h'
    gate = source / 'src/core/fused_boot_gate.h'
    original, original_gate = header.read_text(), gate.read_text()
    controls = [
        ('read-local-forced-zero', header, 'const bool read_local = srv.read_local_enabled();',
         'const bool read_local = false;', 'enabled/disabled resolved banner field'),
        ('read-local-from-request', header, 'const bool read_local = srv.read_local_enabled();',
         'const bool read_local = cfg.read_local;', 'enabled/disabled resolved banner field'),
        ('read-local-omitted', header, 'read-local=%u', 'local-read=%u', 'enabled/disabled resolved banner field'),
        ('wrong-worker-count', header, 'srv.nthreads()', 'srv.nthreads() + 1', 'resolved worker counts'),
        ('requested-shard-count', header, 'srv.nshards()', 'cfg.shards', 'resolved shard count'),
        ('wrong-mode', header, 'const bool fused = cfg.thread_mode == ThreadMode::Fused;',
         'const bool fused = false;', 'resolved worker counts'),
        ('wrong-overlap', header, 'cfg.overlap', '0u', 'resolved overlap'),
        ('wrong-send-owner', header, 'send=self', 'send=other', 'mode-specific placement'),
        ('wrong-cpu', header, 'p.cpu', 'p.cpu + 1', 'mode-specific placement'),
        ('wrong-domain', header, 'p.domain', 'p.domain + 1', 'mode-specific placement'),
        ('missing-thread-row', header, '    for (const ThreadPlacement& p',
         '    if (false) for (const ThreadPlacement& p', 'eight placement rows'),
        ('hide-live-reorder', header, 'static_cast<int32_t>(cfg.reorder)', '0', 'live fused reorder'),
        ('wrong-network', header, 'cfg.net_io == NetIoEngine::Epoll', 'false', 'selected network engine'),
        ('wrong-allocator', header, 'alloc_backend()', '"incorrect"', 'compiled allocator'),
        ('unix-before-bound', header, 'if (unix_bound)', 'if (cfg.unixsocket)', 'actually bound Unix'),
        ('tls-not-announced', header, 'if (cfg.tls_port)', 'if (false)', 'configured TCP/TLS'),
        ('probe-bypassed', header, 'if (!port) return true;', 'if (port || !port) return true;', 'configured probe fired'),
        ('probe-close-omitted', header, 'close_listener(fd);', '(void)close_listener;', 'success closes once'),
        ('probe-wrong-fd', header, 'close_listener(fd);', 'close_listener(fd + 1);', 'acquired probe fd'),
        ('probe-failure-hidden', header, 'if (fd < 0) return false;', 'if (fd < 0) return true;', 'probe failure returned'),
        ('gate-stop-bypassed', gate,
         'return phase_ != Phase::Stopping && !stop.load(std::memory_order_relaxed) &&',
         'return phase_ == Phase::Stopping ||', 'joins all arrivals'),
    ]
    results = []
    for name, path, before, after, diagnostic in controls:
        header.write_text(original)
        gate.write_text(original_gate)
        text = path.read_text()
        assert before in text, (name, 'missing mutation anchor')
        path.write_text(text.replace(before, after))
        binary = out / name
        with (out / (name + '.build.log')).open('w') as log:
            subprocess.run(['g++', '-std=c++20', '-O2', '-pthread', '-I' + str(source),
                            '-I' + str(ROOT), str(ROOT / 'tests/config_parser_test.cc'),
                            '-o', str(binary)], stdout=log, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
        (out / (name + '.log')).write_text(result.stdout + result.stderr)
        assert result.returncode == 1 and diagnostic in result.stderr, (name, result)
        results.append(dict(control=name, exit=result.returncode, required_failure=diagnostic,
                            rejected=True))
        print(name + ': rejected by ' + diagnostic, flush=True)
    # The gate's existing rows must also reject omitted/zero boot fields.
    pattern = '^tomokv-cpp: .*thread-mode=1s,.*read-local=1([,[:space:]]|$)'
    for suffix, expected in [('read-local=1', 0), ('read-local=0', 1), ('', 1)]:
        result = subprocess.run(['grep', '-Eq', pattern], input='tomokv-cpp: 8 unified threads, '
                                'thread-mode=1s, ' + suffix + '\n', text=True)
        assert result.returncode == expected
    results.append(dict(control='existing-gate-banner-grep', positive=True,
                        zero_rejected=True, omitted_rejected=True))
    (out / 'results.json').write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
