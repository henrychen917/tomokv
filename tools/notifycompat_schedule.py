#!/usr/bin/env python3
"""Hold a real REDIRECT hop until its target closes, then replay through production.

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


STATE = r"""
namespace {
thread_local std::unordered_map<std::string, PubSubEvent> notifycompat_held;
thread_local std::unordered_set<std::string> notifycompat_seen;
std::string notifycompat_path(const std::string& key, const char* suffix) {
    const char* directory = std::getenv("TOMO_NOTIFYCOMPAT_SCHEDULE_DIR");
    return directory ? std::string(directory) + "/" + key + suffix : std::string{};
}
void notifycompat_receipt(const PubSubEvent& event, const char* suffix) {
    const std::string path = notifycompat_path(event.channel, suffix);
    const std::string pending = path + ".pending";
    FILE* file = std::fopen(pending.c_str(), "w");
    if (!file) std::abort();
    std::fprintf(file, "{\"origin\":%u,\"target\":%u,\"client\":%llu}\n",
        event.origin_io, event.target_io, static_cast<unsigned long long>(event.client_id));
    std::fclose(file);
    if (std::rename(pending.c_str(), path.c_str())) std::abort();
}
}
std::unique_ptr<PubSubEvent> notifycompat_take_redirect() {
    for (auto it = notifycompat_held.begin(); it != notifycompat_held.end(); ++it) {
        const std::string path = notifycompat_path(it->first, ".release");
        FILE* release = std::fopen(path.c_str(), "r");
        if (!release) continue;
        std::fclose(release);
        auto event = std::make_unique<PubSubEvent>(std::move(it->second));
        notifycompat_held.erase(it);
        notifycompat_receipt(*event, ".replayed");
        return event;
    }
    return {};
}
"""
HOLD = r"""
    if (std::getenv("TOMO_NOTIFYCOMPAT_SCHEDULE_DIR") &&
        event.kind == PubSubEventKind::TrackingDeliver && !event.rebind &&
        event.channel.starts_with("nc:redirect:") &&
        notifycompat_seen.insert(event.channel).second) {
        notifycompat_held.emplace(event.channel, event);
        notifycompat_receipt(event, ".held");
        return;
    }
"""

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
        extras = subprocess.check_output(['git', 'ls-tree', '--name-only', args.ref,
                                          'tools/assert_map.py'], cwd=root, text=True).splitlines()
        archive = subprocess.check_output(['git', 'archive', args.ref, 'src', 'third_party', 'Makefile', *extras], cwd=root)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(source, filter='data')
    else:
        for name in ('src', 'third_party'):
            shutil.copytree(root / name, source / name, dirs_exist_ok=True)
        shutil.copy2(root / 'Makefile', source / 'Makefile')
        (source / 'tools').mkdir(exist_ok=True)
        shutil.copy2(root / 'tools/assert_map.py', source / 'tools/assert_map.py')
    path = source / 'src/cmd/tracking.cc'
    text = path.read_text()
    anchor = 'namespace tomo {'
    assert text.count(anchor) == 1
    text = text.replace(anchor, anchor + STATE)
    anchor = 'void IoLoop::tracking_handle_event(PubSubEvent& event) {'
    assert text.count(anchor) == 1
    path.write_text(text.replace(anchor, anchor + HOLD))
    path = source / 'src/cmd/climon.cc'
    text = path.read_text().replace('namespace tomo {',
        'namespace tomo {\nstd::unique_ptr<PubSubEvent> notifycompat_take_redirect();', 1)
    anchor = 'bool IoLoop::climon_handle_event(PubSubEvent& event) {'
    assert text.count(anchor) == 1
    path.write_text(text.replace(anchor, anchor +
        '\n    while (auto held = notifycompat_take_redirect()) tracking_handle_event(*held);\n'))
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
