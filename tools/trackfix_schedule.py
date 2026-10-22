#!/usr/bin/env python3
"""Delay a real tracking notification until its reader is Done, before retirement.

Disposable source copy only. No scheduling hook, branch or test state is linked
into production. Rebuild only tracking.cc in the selected arm's two namespaces.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile


STATE = r'''
namespace {
thread_local std::unordered_map<std::string, PubSubEvent> trackfix_held;
thread_local std::unordered_set<std::string> trackfix_seen;
void trackfix_receipt(const std::string& key, const char* suffix, unsigned state) {
    const char* directory = std::getenv("TOMO_TRACKFIX_SCHEDULE_DIR");
    if (!directory) return;
    const std::string path = std::string(directory) + "/" + key + suffix;
    FILE* f = std::fopen(path.c_str(), "w");
    if (!f) std::abort();
    std::fprintf(f, "%u\n", state);
    std::fclose(f);
}
}
'''
HOLD = r'''
    if (std::getenv("TOMO_TRACKFIX_SCHEDULE_DIR") &&
        event.kind == PubSubEventKind::TrackingInvalidate && event.items.size() == 1) {
        const std::string& key = event.items[0].value;
        if (key.starts_with("trackfix:ordered:") && key.find("BCAST") == std::string::npos &&
            trackfix_seen.insert(key).second) {
            trackfix_held.emplace(key, event);
            trackfix_receipt(key, ".held", 0);
            return;
        }
    }
'''
REPLAY = r'''
    for (const std::string& key : read->second) {
        auto held = trackfix_held.find(key);
        if (held != trackfix_held.end()) {
            // This is the unchanged writer's original transport event, replayed
            // through the real consumer. Never invent an invalidation or a reply.
            const unsigned done = static_cast<unsigned>(op.state.load(std::memory_order_acquire));
            auto pending = state->tracking_pending.find(key);
            if (pending == state->tracking_pending.end() || pending->second != &op) std::abort();
            if (op.state.load(std::memory_order_acquire) != OpState::Done) std::abort();
            PubSubEvent event = std::move(held->second);
            trackfix_held.erase(held);
            tracking_handle_event(event);
            trackfix_receipt(key, ".replayed", done);
        }
    }
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--objects', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ref')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output, objects = args.output.resolve(), args.objects.resolve()
    assert output.is_relative_to(root / 'build') and objects.is_relative_to(root / 'build')
    source = output / 'source'
    source.mkdir(parents=True, exist_ok=True)
    if args.ref:
        archive = subprocess.check_output(['git', 'archive', args.ref, 'src', 'third_party', 'Makefile'], cwd=root)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(source, filter='data')
    else:
        for name in ('src', 'third_party'):
            shutil.copytree(root / name, source / name, dirs_exist_ok=True)
        shutil.copy2(root / 'Makefile', source / 'Makefile')
    path = source / 'src/cmd/tracking.cc'
    text = path.read_text()
    patches = [('namespace tomo {', 'namespace tomo {\n' + STATE),
               ('void IoLoop::tracking_handle_event(PubSubEvent& event) {', HOLD),
               ('    if (read == state->tracking_reads.end()) return;', REPLAY)]
    for anchor, addition in patches:
        assert text.count(anchor) == 1, anchor
        text = text.replace(anchor, addition if anchor == 'namespace tomo {' else anchor + '\n' + addition)
    path.write_text(text)
    dry = subprocess.check_output(['make', '-n', '-B', f'BUILD_ROOT={objects}', 'all'], cwd=source, text=True)
    commands = [shlex.split(line) for line in dry.splitlines() if line.startswith(('g++ ', 'c++ ', 'clang++ '))]
    compiles = [cmd for cmd in commands if '-c' in cmd and 'src/cmd/tracking.cc' in cmd]
    assert len(compiles) == 2
    replacements = {}
    for index, cmd in enumerate(compiles):
        pos = cmd.index('-o') + 1
        replacements[cmd[pos]] = str(output / f'tracking-{index}.o')
        cmd[pos] = replacements[cmd[pos]]
    link, = [cmd for cmd in commands if '-c' not in cmd]
    link = [replacements.get(arg, arg) for arg in link]
    link[link.index('-o') + 1] = str(output / 'tomokv')
    def run(pair):
        index, cmd = pair
        with (output / f'compile-{index}.log').open('w') as log:
            subprocess.run(cmd, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, enumerate(compiles)))
    with (output / 'link.log').open('w') as log:
        subprocess.run(link, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
    (output / 'commands.json').write_text(json.dumps(dict(
        ref=args.ref, affinity=sorted(os.sched_getaffinity(0)), compile=compiles, link=link), indent=2) + '\n')


if __name__ == '__main__':
    main()
