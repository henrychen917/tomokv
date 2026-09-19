#!/usr/bin/env python3
"""Prepare serverless LB negative controls, TSan build, and a type-A text-size control.

This script only writes build inputs. It never runs a server, test, or measurement.
All mutations live under build/lbfix-controls; production sources remain untouched.
"""
from pathlib import Path
import json
import shutil

from lbstall_artifacts import Elf


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'


def replace_once(text, before, after):
    assert text.count(before) == 1, f'mutation anchor is not unique: {before!r}'
    return text.replace(before, after, 1)


def mutate(name, source):
    if name == 'no-floor':
        source['weighted_lb.h'] = replace_once(
            source['weighted_lb.h'],
            'return std::max(2 * jitter, sampling_floor(owners));', 'return 2 * jitter;')
    elif name == 'no-hot':
        source['server.h'] = replace_once(
            source['server.h'], 'bool lb_controller_tick(uint32_t coordinator, uint64_t now_ms) {',
            'bool lb_controller_tick(uint32_t coordinator, uint64_t now_ms) {\n'
            '        if (key_lb_signals_enabled()) return false; // negative control')
    elif name == 'eager-gather':
        source['server.h'] = replace_once(
            source['server.h'], '                lb_fold_signals(now_ms * 1000000);',
            '                lb_fold_signals(now_ms * 1000000);\n'
            '                std::vector<WeightedLbItem> eager;\n'
            '                lb_gather_key_evidence(eager, now_ms, 0);')
    elif name == 'no-reset':
        source['server.h'] = replace_once(
            source['server.h'],
            '                    lb_bucket_hot_streak_ = 0;\n'
            '                    std::vector<WeightedLbItem> shard_items;',
            '                    std::vector<WeightedLbItem> shard_items;')
    elif name == 'step-no-floor':
        text = source['server.h']
        start = text.index('                        for (uint32_t step = 0;')
        end = text.index('                            if (!demand_hot && !memory_hot)', start)
        body = text[start:end]
        assert body.count('band;') == 2
        source['server.h'] = text[:start] + body.replace(
            'band;', '2 * lb_policy_->key_jitter.jitter;') + text[end:]
    elif name == 'census-expiry':
        source['shard.h'] = replace_once(source['shard.h'],
                                        '/*expire_on_visit=*/false', '/*expire_on_visit=*/true')
    elif name == 'fold-expiry':
        text = source['server.h']
        start = text.index('    bool lb_gather_key_evidence(')
        end = text.index('    double lb_thread_occupancy(', start)
        body = replace_once(text[start:end],
                            'const Shard& physical = shard(static_cast<int32_t>(sid));',
                            'Shard& physical = shard(static_cast<int32_t>(sid));\n'
                            '            physical.store().scan(0, 1 << 20, [](KvObj*) {});')
        source['server.h'] = text[:start] + body + text[end:]
    else:
        raise AssertionError(name)


def main():
    controls = {
        'no-floor': ['lbfix-floor', 'lbfix-stationary'],
        'no-hot': ['lbfix-hot'],
        'eager-gather': ['lbfix-gather'],
        'no-reset': ['lbfix-no-move'],
        'step-no-floor': ['lbfix-step'],
        'census-expiry': ['lbfix-read-only'],
        'fold-expiry': ['lbfix-read-only'],
    }
    BUILD.mkdir(exist_ok=True)
    manifest = []
    make = ['include Makefile', '', 'LB_CONTROL_BINS := ' + ' '.join(
        f'build/lbfix-controls/{name}/unit' for name in controls),
        '.PHONY: lbfix-controls lbfix-tsan lbfix-pad',
        'lbfix-controls: $(LB_CONTROL_BINS)', '']
    for name, rows in controls.items():
        dest = BUILD / 'lbfix-controls' / name
        # All nested quoted includes must find this same mutated header tree. Release
        # libraries are linked after the unit TU, as in the existing core unit target.
        for path in (ROOT / 'src').rglob('*'):
            if path.is_file() and path.suffix in ('.h', '.inc'):
                target = dest / path.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        source = {n: (dest / 'src/core' / n).read_text()
                  for n in ('weighted_lb.h', 'server.h', 'shard.h')}
        mutate(name, source)
        for filename, text in source.items():
            (dest / 'src/core' / filename).write_text(text)
        target = dest.relative_to(ROOT)
        make.extend([
            f'{target}/unit: tests/core_concurrency_unit.cc $(CORE_TEST_OBJ) '
            f'{target}/src/core/server.h {target}/src/core/weighted_lb.h {target}/src/core/shard.h',
            '\t$(CXX) $(CXXFLAGS) $(JEFLAGS) -O1 -fsanitize=address,undefined '
            '-fno-omit-frame-pointer -DTOMO_CORE_CONCURRENCY_TEST '
            f'-I{target} -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm', ''])
        manifest.append({'control': name, 'binary': f'{target}/unit', 'rows': rows,
                         'expected_exit': 1, 'actual_result': 'NOT RUN: mainline owns proof runs'})

    make.extend([
        'LB_TSAN_FLAGS := -std=c++20 -O1 -g -march=native -pthread -fsanitize=thread '
        '-fno-omit-frame-pointer -no-pie -DTOMO_CORE_CONCURRENCY_TEST',
        'LB_TSAN_SRC := $(filter-out src/main.cc,$(SRC))',
        'LB_TSAN_OBJ := $(LB_TSAN_SRC:%.cc=build/lbfix-tsan/%.o)',
        'lbfix-tsan: build/lbfix-tsan/unit',
        'build/lbfix-tsan/%.o: %.cc $(wildcard src/*/*.h) $(wildcard src/*/*.inc)',
        '\t@mkdir -p $(dir $@)',
        '\t$(CXX) $(LB_TSAN_FLAGS) -I. -c $< -o $@',
        'build/lbfix-tsan/unit: tests/core_concurrency_unit.cc $(LB_TSAN_OBJ)',
        '\t$(CXX) $(LB_TSAN_FLAGS) -I. $< $(LB_TSAN_OBJ) -o $@ $(LDLIBS) -lm', ''])

    pre, post = Elf(BUILD / 'lbfix-pre/tomokv'), Elf(BUILD / 'tomokv')
    pre_text = len(pre.section_data(pre.names.index('.text')))
    post_text = len(post.section_data(post.names.index('.text')))
    pad = post_text - pre_text
    assert pad >= 0, 'candidate shrank: use an explicitly labelled inverse control instead'
    # An unannotated assembly object clears CET's IBT/SHSTK property at link time,
    # which changes the entire PLT and text base. Preserve the compiler's exact note.
    pre_object = Elf(BUILD / 'lbfix-pre/src/main.o')
    properties = ''
    if '.note.gnu.property' in pre_object.names:
        note = pre_object.section_data(pre_object.names.index('.note.gnu.property'))
        properties = '.section .note.gnu.property,"a",@note\n.p2align 3\n.byte ' + \
            ','.join(str(byte) for byte in note) + '\n'
    (BUILD / 'lbfix-pad.S').write_text(
        '.text\n.globl lbfix_text_size_control\nlbfix_text_size_control:\n'
        f'.fill {pad},1,0x90\n.section .note.GNU-stack,"",@progbits\n' + properties)
    make.extend([
        'LB_PRE_OBJ := $(SRC:%.cc=build/lbfix-pre/%.o)',
        'LB_PRE_DB0_OBJ := $(SRC:%.cc=build/lbfix-pre/db0/%.o)',
        'lbfix-pad: build/tomokv-lbfix-pad',
        'build/lbfix-pad.o: build/lbfix-pad.S',
        '\t$(CXX) -c $< -o $@',
        'build/tomokv-lbfix-pad: $(LB_PRE_OBJ) $(LB_PRE_DB0_OBJ) build/lbfix-pad.o',
        '\t$(CXX) $(CXXFLAGS) $(LB_PRE_DB0_OBJ) $(LB_PRE_OBJ) build/lbfix-pad.o '
        '-o $@ $(JELIBS) $(LDLIBS) -lm', ''])
    (BUILD / 'lbfix-artifacts.mk').write_text('\n'.join(make))
    (BUILD / 'lbfix-controls.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (BUILD / 'lbfix-pad.json').write_text(json.dumps({
        'kind': 'A: PRE behaviour with POST .text size', 'padding_bytes': pad,
        'pre_text_bytes': pre_text, 'post_text_bytes': post_text,
        'limitation': 'Matches text extent, not internal function addresses or cold heap allocations.'
    }, indent=2) + '\n')
    print('Prepared controls, full TSan unit, and type-A text-size twin; ran nothing.')


if __name__ == '__main__':
    main()
