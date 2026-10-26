#!/usr/bin/env python3
"""Stable-id, non-vacuous abort, parser and source-identity negative controls."""
import argparse
import csv
import io
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import assert_map as amap
import source_identity as identity

ROOT = Path(__file__).resolve().parents[1]


class AssertionChecks(unittest.TestCase):
    def site(self, body):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            root = Path(directory)
            (root / 'src').mkdir()
            path = root / 'src/fixture.cc'
            path.write_text(body)
            return amap.scan(root)

    def test_hash_and_function(self):
        sites = amap.scan(ROOT)
        self.assertEqual(len(sites), 5)
        self.assertEqual({s.function for s in sites}, {
            'tomo::FlatStore::storesize_replace', 'tomo::FlatStore::storesize_deadline',
            'tomo::FlatStore::make_word', 'tomo::Shard::init'})
        amap.verify(sites, ROOT, 'g++')
        self.assertEqual(amap.fnv(' a\t +\n b '), amap.fnv('a+b'))
        self.assertNotEqual(amap.fnv('a', 0), amap.fnv('a', 1))

    def test_lexer_and_physical_lines(self):
        code = '''// TOMO_ASSERT(nope)
const char* unused = R"tag(TOMO_ASSERT(nope))tag";
#define UNUSED(x) (x)
#line 999 "pretend.cc"
namespace renamed { class Changed { void moved() {
    TOMO_ASSERT( a /* ignored */ &&
                 fn("a,b", '\\n') );
} }; }
'''
        sites = self.site(code)
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0].location, 'src/fixture.cc:6')
        self.assertEqual(sites[0].function, 'renamed::Changed::moved')
        self.assertEqual(sites[0].id, amap.fnv('a&&fn("a,b",\'\\n\')'))

    def test_duplicate_salt_and_pin(self):
        with self.assertRaisesRegex(ValueError, 'duplicate id'):
            self.site('void one(){TOMO_ASSERT(ok);} void two(){TOMO_ASSERT(ok);}')
        sites = self.site('void one(){TOMO_ASSERT(ok);} void two(){TOMO_ASSERT_SALT(ok, 3u);}')
        self.assertNotEqual(sites[0].id, sites[1].id)
        old = sites[0].id
        pinned = self.site(f'void moved(){{TOMO_ASSERT_ID(renamed, 0x{old:x}u);}}')[0]
        self.assertEqual(pinned.id, old)
        with self.assertRaisesRegex(ValueError, 'duplicate id'):
            self.site('void f(){TOMO_ASSERT_ID(a,0x80000001u); TOMO_ASSERT_ID(b,0x80000001u);}')
        with self.assertRaisesRegex(ValueError, 'wrappers hide source sites'):
            self.site('#define ALIAS(x) TOMO_ASSERT(x)\nvoid f(){ALIAS(ok);}')
        for bad in ('0', '1', '4294967296', 'some_variable'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.site(f'void f(){{TOMO_ASSERT_ID(ok,{bad});}}')

    def test_macro_semantics(self):
        # Single evaluation, explicit bool conversion, dangling else, salts,
        # pins, and NDEBUG's unevaluated condition all compile and execute.
        source = '''#include "src/base/tomo_assert.h"
struct Bool { explicit operator bool() const { return true; } };
int main() {
    int calls = 0;
    if (true) TOMO_ASSERT(++calls); else return 3;
    TOMO_ASSERT(Bool{});
    TOMO_ASSERT_SALT(true, 9u);
    TOMO_ASSERT_ID(true, 0x80000001u);
#ifdef NDEBUG
    return calls != 0;
#else
    return calls != 1;
#endif
}
'''
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            binary = Path(directory) / 'semantics'
            for flags in ([], ['-DNDEBUG'], ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']):
                subprocess.run(['g++', '-std=c++20', '-O2', '-I', str(ROOT), *flags,
                                '-x', 'c++', '-', '-o', str(binary)], input=source, text=True, check=True)
                subprocess.run([str(binary)], check=True)

    def test_lint_negative_controls(self):
        for word in identity.FORBIDDEN:
            with self.subTest(word=word):
                self.assertTrue(identity.lint_source(f'auto x = {word};', 'src/test.cc'))
                self.assertTrue(identity.lint_source(f'#define ALIAS {word}\nauto x=ALIAS;', 'src/test.cc'))
        good = '''// __FILE__ assert(x)
const char* text = R"tag(__LINE__ assert(x)
#line 99
#ifdef TOMO_BOGUS_TRACE
)tag";
/*
#line 3
#endif
*/
static_assert(sizeof(int) >= 2);
#ifdef TOMO_EXAMPLE_TRACE
#if ENABLE_OTHER
const char* diagnostic = __FILE__;
#endif
#endif
'''
        self.assertFalse(identity.lint_source(good, 'src/test.cc'))
        for source in ('#ifdef TOMO_EXAMPLE_TRACE\n#else\nauto x=__LINE__;\n#endif',
                       '#ifndef TOMO_EXAMPLE_TRACE\nauto x=__LINE__;\n#endif',
                       'auto x = __FI\\\nLE__;', '#line 17', '%:line 17',
                       '#define NAME(x) #x\nconst char* name=NAME(function);'):
            with self.subTest(source=source):
                self.assertTrue(identity.lint_source(source, 'src/test.cc'))

    def test_expanded_lint(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            root = Path(directory)
            (root / 'src').mkdir()
            path = root / 'src/fixture.cc'
            for spelling in ('CAT(__FI,LE__)', 'CAT(__builtin_,FUNCTION)()',
                             'CAT(__PRETTY_,FUNCTION__)', 'std::CAT(source_,location)::current()'):
                path.write_text('#define CAT(a,b) a##b\nauto x = ' + spelling + ';\n')
                # Proves the second pass adds coverage beyond a lexical grep.
                self.assertFalse(identity.source_check(root))
                self.assertTrue(identity.expanded_check(root, 'src/fixture.cc', 'g++', '-std=c++20', False))


def check_failure(binary, map_path):
    def no_core():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    result = subprocess.run([str(binary.resolve())], text=True, capture_output=True,
                            preexec_fn=no_core)
    if result.returncode != -signal.SIGABRT:
        raise AssertionError(f'assertion did not abort: {result.returncode}: {result.stderr}')
    match = re.search(r'tomokv:(\d+): site: Assertion .see tomokv.asserts. failed\.', result.stderr)
    if not match:
        raise AssertionError(f'unrecognized glibc assertion: {result.stderr}')
    rows = list(csv.DictReader(io.StringIO(map_path.read_text()), delimiter='\t'))
    found = [row for row in rows if row['id_decimal'] == match[1]]
    if len(found) != 1:
        raise AssertionError(f'id {match[1]} resolves to {len(found)} sites')
    row = found[0]
    if row['function'] != 'tomo::Shard::init':
        raise AssertionError(f'wrong function: {row}')
    path, line = row['file:line'].rsplit(':', 1)
    if path != 'src/core/shard.h' or 'TOMO_ASSERT(bucket_begin <=' not in (ROOT / path).read_text().splitlines()[int(line) - 1]:
        raise AssertionError(f'wrong physical source location: {row}')
    print(result.stderr.strip())
    print(f"PASS directed abort: {match[1]} -> {row['file:line']} {row['function']}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=Path('build/tomo-assert-fail'))
    parser.add_argument('--map', type=Path, default=Path('build/tomokv.asserts.tsv'))
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AssertionChecks)
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
        sys.exit(1)
    check_failure(args.binary, args.map)
