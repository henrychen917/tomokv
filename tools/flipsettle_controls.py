#!/usr/bin/env python3
"""Generate throwaway controller mutants and run the existing serverless transition checks."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess


ROOT = Path(__file__).resolve().parents[1]
FIELDS = ['shift_detector_', 'anchor_signature_samples_', 'maneuver_signature_samples_',
          'anchor_learning_rate_jitter_', 'anchor_learning_rate_sum_', 'anchor_learning_rate_min_',
          'anchor_learning_rate_max_', 'anchor_learning_rate_samples_']
SITES = ['seek', 'waiting', 'nonsettling', 'disarm']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/cleanup-flipsettle/controls')
    parser.add_argument('--arm', type=Path, default=ROOT / 'build/cleanup-flipsettle/POST')
    parser.add_argument('--positive-only', action='store_true')
    args = parser.parse_args()
    out, arm = args.out.resolve(), args.arm.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / 'src/core/flipctl.cc').read_text()
    helper_start = source.index('inline void FlipController::reset_settling_learning()')
    helper_end = source.index('\n}', helper_start) + 2
    helper = source[helper_start:helper_end]
    mutants = []

    def add(name, changed, cases):
        assert changed != source
        path = out / f'{name}.cc'
        path.write_text(changed)
        mutants.append(dict(name=name, source=str(path), cases=cases))

    def in_helper(old, new):
        assert helper.count(old) == 1, old
        return source[:helper_start] + helper.replace(old, new) + source[helper_end:]

    def append_helper(statement):
        return source[:helper_end - 1] + statement + '\n' + source[helper_end - 1:]

    for field in FIELDS:
        statement = f'{field}.reset();' if field == 'shift_detector_' else f'{field} = 0;'
        add('omit-' + field, in_helper(statement, ';'),
            [(site, field) for site in SITES if site != 'nonsettling'])
        # Independently prove each preserved shared field at the non-Settling destination.
        add('widen-' + field, source.replace('phase_ = after_flip_;',
            'phase_ = after_flip_;\n            ' + statement), [('nonsettling', field)])
    a = source.index('            phase_ = after_flip_;')
    b = source.index('            rate_window_ms_ = 0;', a)
    add('wrong-enter-settling', source[:a] + '            enter_settling();\n' + source[b:],
        [('nonsettling', 'phase')])
    a = source.index('void FlipController::enter_settling()')
    b = source.index('\n}', a)
    add('omit-enter-phase', source[:a] + source[a:b].replace('phase_ = Phase::Settling;', ';') + source[b:],
        [('seek', 'phase')])
    add('omit-waiting-phase', source.replace('phase_ = after_flip_;', ';'), [('waiting', 'phase')])
    disarm = source.index('        if (!anchor_sampling_disabled_) {')
    signal = source.index('signal_sample_rate_.store(0, std::memory_order_release);', disarm)
    statement = 'signal_sample_rate_.store(0, std::memory_order_release);'
    add('omit-signal-disarm', source[:signal] + ';' + source[signal + len(statement):],
        [('disarm', 'sampling-disarmed')])
    add('wrong-disarm-phase', source[:signal] + 'phase_ = Phase::Anchored;\n            ' + source[signal:],
        [('disarm', 'phase')])
    add('omit-disarm-latch', source.replace('anchor_sampling_disabled_ = true;', ';'),
        [('disarm', 'anchor_sampling_disabled_')])
    for field in ['rate_window_ms_', 'previous_subwindow_valid_']:
        statement = f'{field} = ' + ('0;' if field == 'rate_window_ms_' else 'false;')
        add('omit-' + field, source.replace(statement, ';'), [(s, field) for s in SITES])
    for name, statement, witness in [
            ('extra-signal', 'signal_sample_rate_.store(0, std::memory_order_release);', 'sampling-disarmed'),
            ('extra-latch', 'anchor_sampling_disabled_ = true;', 'anchor_sampling_disabled_'),
            ('extra-anchor', 'anchor_rate_ = 0;', 'unrelated-state')]:
        sites = ['seek', 'waiting', 'disarm'] if name == 'extra-anchor' else ['seek', 'waiting']
        add(name, append_helper(statement), [(s, witness) for s in sites])
        add(name + '-nonsettling', source.replace('phase_ = after_flip_;',
            'phase_ = after_flip_;\n            ' + statement), [('nonsettling', witness)])
    a = source.index('bool FlipController::seek_after_reading(')
    b = source.index('void FlipController::anchor(', a)
    add('omit-seek-record', source[:a] + source[a:b].replace('record(current, rate);', ';') + source[b:],
        [('seek', 'seek-record')])

    # Generate a thin driver from the existing fixture; no second handwritten fixture or reset.
    original = (ROOT / 'tests/core_concurrency_unit.cc').read_text()
    driver = original[:original.index('    static Op& prepare(')]
    driver += '#include "tests/flipsettle_checks.inc"\n};\n}\n'
    driver += '''int main(int argc, char** argv) {
    using T = tomo::CoreConcurrencyTest;
    T::require(argc == 2, "select flipsettle site");
    T::require(tomo::command_registry_init(false), "command registry initialization");
    if (std::strcmp(argv[1], "all") == 0) T::flipsettle_all();
    else T::flipsettle(argv[1]);
}
'''
    (out / 'driver.cc').write_text(driver)
    flags = ['-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native', '-pthread',
             '-DTOMO_JEMALLOC', '-DTOMO_CORE_CONCURRENCY_TEST', '-I' + str(ROOT)]
    objects = sorted(p for p in (arm / 'src').rglob('*.o')
                     if p not in [arm / 'src/main.o', arm / 'src/core/flipctl.o'])
    libs = ['-ljemalloc', '-luring', '-pthread', '-lssl', '-lcrypto', '-lm']
    targets = [str(out / (m['name'] + '.unit')) for m in mutants]
    lines = ['all: ' + ' '.join(targets)]
    def recipe(target, deps, command):
        lines.extend([str(target) + ': ' + ' '.join(map(str, deps)), '\t' + shlex.join(command)])
    recipe(out / 'driver.o', [out / 'driver.cc', ROOT / 'tests/flipsettle_checks.inc'],
           ['g++', *flags, '-c', str(out / 'driver.cc'), '-o', str(out / 'driver.o')])
    recipe(out / 'driver-db0.o', [out / 'driver.cc', ROOT / 'tests/flipsettle_checks.inc'],
           ['g++', *flags, '-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0',
            '-c', str(out / 'driver.cc'), '-o', str(out / 'driver-db0.o')])
    positives = []
    for label in ['PRE', 'POST', 'PAD-A']:
        directory = arm.parent / label
        normal = sorted(p for p in (directory / 'src').rglob('*.o') if p != directory / 'src/main.o')
        for ns in ['normal', 'db0']:
            driver_obj = out / ('driver.o' if ns == 'normal' else 'driver-db0.o')
            # Lua is deliberately shared and only emitted by the normal namespace objects.
            all_objects = normal if ns == 'normal' else sorted(
                p for p in (directory / 'db0/src').rglob('*.o') if p != directory / 'db0/src/main.o') + normal
            exe = directory / ('transitions-' + ns)
            recipe(exe, [driver_obj, *all_objects],
                   ['g++', '-pthread', str(driver_obj), *map(str, all_objects), '-o', str(exe), *libs])
            positives.append((label, ns, exe))
    for m in mutants:
        obj, exe = out / (m['name'] + '.o'), out / (m['name'] + '.unit')
        recipe(obj, [m['source']], ['g++', *flags, '-iquote', str(ROOT / 'src/core'),
                                  '-c', m['source'], '-o', str(obj)])
        recipe(exe, [obj, out / 'driver.o', *objects],
               ['g++', '-pthread', str(out / 'driver.o'), str(obj), *map(str, objects),
                '-o', str(exe), *libs])
    (out / 'Makefile').write_text('\n'.join(lines) + '\n')
    with (out / 'build.log').open('w') as log:
        selected = ([] if args.positive_only else targets) + [str(p) for _, _, p in positives]
        subprocess.run(['make', '-j16', '-f', str(out / 'Makefile'), *selected], cwd=ROOT,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    traces = {}
    for label, ns, exe in positives:
        p = subprocess.run([str(exe), 'all'], cwd=ROOT, capture_output=True, text=True)
        (exe.parent / (exe.name + '.log')).write_text(p.stdout + p.stderr)
        assert p.returncode == 0, (label, ns, p.stderr)
        assert p.stdout.count('TRACE flipsettle ') == (8 if ns == 'normal' else 4)
        traces[label, ns] = p.stdout
    for ns in ['normal', 'db0']:
        assert traces['PRE', ns] == traces['POST', ns] == traces['PAD-A', ns], ns
    (out / 'positive-results.json').write_text(json.dumps([
        dict(arm=label, namespace=ns, rc=0, traces_equal=True,
             sha256=__import__('hashlib').sha256(exe.read_bytes()).hexdigest())
        for label, ns, exe in positives], indent=2) + '\n')
    print('PRE/POST/PAD-A: identical transition traces in normal (databases 1/4) and db0', flush=True)
    if args.positive_only:
        return
    results = []
    for m in mutants:
        for site, field in m['cases']:
            command = [str(out / (m['name'] + '.unit')), site]
            p = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            expected = f'FAIL flipsettle {site}: {field}'
            log = out / f"{m['name']}-{site}.log"
            log.write_text(p.stdout + p.stderr)
            results.append(dict(mutant=m['name'], site=site, assertion=field,
                                command=command, rc=p.returncode, expected=expected,
                                matched=p.returncode == 1 and expected in p.stderr))
    (out / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    for r in results:
        print('PASS' if r['matched'] else 'FAIL', r['mutant'], r['site'], r['assertion'], flush=True)
    assert all(r['matched'] for r in results), 'a negative control missed its exact assertion'
    print(f"{len(mutants)} throwaway builds; {len(results)}/{len(results)} exact negative witnesses")


if __name__ == '__main__':
    main()
