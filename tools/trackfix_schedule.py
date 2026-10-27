#!/usr/bin/env python3
"""Delay a real tracking notification until its reader is Done, before retirement.

Disposable source copy only. No scheduling hook, branch or test state is linked
into production. Rebuild only tracking.cc and climon.cc in the selected arm's two namespaces.
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
thread_local std::unordered_map<std::string, std::vector<std::pair<Client*, Op*>>> trackfix_late;
thread_local std::unordered_set<std::string> trackfix_late_released;
thread_local std::unordered_set<std::string> trackfix_overlap_primed;
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
        const bool remembering = std::any_of(climon_conn_.begin(), climon_conn_.end(),
            [](const auto& entry) { return entry.second.tracking_on && !entry.second.bcast; });
        if (key.starts_with("trackfix:overlap:") && remembering &&
            trackfix_overlap_primed.insert(key).second)
            trackfix_receipt(key, ".primed", 1);
        if (key.starts_with("trackfix:ordered:") && key.find("BCAST") == std::string::npos &&
            remembering &&
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


LATE = r'''
            for (const PubSubEventItem& item : event.items) {
                auto held = trackfix_late.find(item.value);
                if (held == trackfix_late.end()) continue;
                auto reads = std::move(held->second);
                trackfix_late.erase(held);
                trackfix_late_released.insert(item.value);
                for (auto [client, op] : reads) {
                    if (op->state.load(std::memory_order_acquire) != OpState::Done) std::abort();
                    enqueue_serve(client);
                }
                trackfix_receipt(item.value, ".overlapped", reads.size());
            }
'''

SERVE = r'''
bool trackfix_hold_read(Client* client, Op* op, const std::string& key) {
    if (!std::getenv("TOMO_TRACKFIX_SCHEDULE_DIR") ||
        !key.starts_with("trackfix:overlap:") || key.find("BCAST") != std::string::npos ||
        trackfix_late_released.count(key)) return false;
    auto& held = trackfix_late[key];
    if (op->state.load(std::memory_order_acquire) == OpState::Done &&
        std::none_of(held.begin(), held.end(), [&](auto entry) { return entry.second == op; })) {
        held.emplace_back(client, op);
        trackfix_receipt(key, ".pending", held.size());
    }
    return true;
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
    patches = [('namespace tomo {', 'namespace tomo {\n' + STATE + SERVE),
               ('void IoLoop::tracking_handle_event(PubSubEvent& event) {', HOLD),
               ('    if (read == state->tracking_reads.end()) return;', REPLAY)]
    for anchor, addition in patches:
        assert text.count(anchor) == 1, anchor
        text = text.replace(anchor, addition if anchor == 'namespace tomo {' else anchor + '\n' + addition)
    # PRE has a vector and one pending Op; POST has side-owned read receipts
    # and all readers of a key. The schedule and real consumer call stay the same.
    if 'read->second->keys' in text or 'auto& receipt = *read->second;' in text:
        text = text.replace('for (const std::string& key : read->second)',
                            'for (const std::string& key : read->second->keys)')
        text = text.replace('pending->second != &op',
            'std::find(pending->second.reads.begin(), pending->second.reads.end(), &op) == pending->second.reads.end()')
    anchor = '            tracking_forward_stale(event);'
    assert anchor in text
    text = text.replace(anchor, LATE + anchor, 1)
    path.write_text(text)
    path = source / 'src/cmd/climon.cc'
    text = path.read_text().replace('namespace tomo {',
        'namespace tomo {\nbool trackfix_hold_read(Client*, Op*, const std::string&);', 1)
    for anchor in ('uint32_t IoLoop::climon_serve_suppressed(Client* client) {',
                   'uint32_t IoLoop::climon_prepare_suppressed(Client* client, bool& submit_allowed) {'):
        assert text.count(anchor) == 1
        hold = r'''
    if (std::getenv("TOMO_TRACKFIX_SCHEDULE_DIR")) {
        bool held = false;
        if (auto* state = climon_conn_find(client->id()))
            for (const auto& read : state->tracking_reads)
                for (const std::string& key : READ_KEYS)
                    held |= trackfix_hold_read(client, read.first, key);
        if (held) return 0;
    }
'''
        keys = 'read.second->keys' if 'auto& receipt = *read->second;' in (source / 'src/cmd/tracking.cc').read_text() else 'read.second'
        text = text.replace(anchor, anchor + hold.replace('READ_KEYS', keys))
    path.write_text(text)
    dry = subprocess.check_output(['make', '-n', '-B', f'BUILD_ROOT={objects}', str(objects / 'tomokv')], cwd=source, text=True)
    commands = [shlex.split(line) for line in dry.splitlines() if line.startswith(('g++ ', 'c++ ', 'clang++ '))]
    compiles = [cmd for cmd in commands if '-c' in cmd and any(p in cmd for p in ('src/cmd/tracking.cc', 'src/cmd/climon.cc'))]
    assert len(compiles) == 4
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
