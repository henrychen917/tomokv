#!/usr/bin/env python3
"""Fail-closed lexical controls for production-source tooling."""
import unittest
import json
import re
from pathlib import Path
import source_tokens as cpp


class TokensTest(unittest.TestCase):
    def test_layout_and_comments(self):
        text = cpp.Source('x /* ignored */ -> y (\n 1, 2 );')
        self.assertEqual(text.count('x->y(1,2);'), 1)
        self.assertEqual(cpp.tokens(text.replace('x->y(1,2);', 'x->y(3,2);', 1)),
                         cpp.tokens('x->y(3,2);'))
        self.assertNotEqual(cpp.tokens('a + + b'), cpp.tokens('a ++ b'))

    def test_literals_are_not_code(self):
        text = cpp.Source('R"x( a->b(); { } )x"; "a->b();"; /* a->b(); */ a->b();')
        self.assertEqual(text.count('a->b();'), 1)
        self.assertNotEqual(cpp.tokens('"a b"'), cpp.tokens('"ab"'))
        self.assertEqual(text.count('R"x( a->b(); { } )x"'), 1)

    def test_missing_and_ambiguous(self):
        for text in ('nothing();', 'site(); site();'):
            with self.assertRaises(ValueError):
                cpp.Source(text).replace('site();', 'mutant();', 1)
        with self.assertRaises(ValueError):
            cpp.Source('x').replace('', 'y')

    def test_binding(self):
        source = cpp.Source('int /* TOMO_TOOL_BIND count */ renamed = 1; renamed += 2;')
        self.assertEqual(source.count('count += 2;'), 1)
        changed = source.replace('count += 2;', 'count += 3;', 1)
        self.assertIn('renamed += 3;', str(changed))
        self.assertNotEqual(cpp.tokens(changed), cpp.tokens(source))
        full = source.replace('int count = 1;', 'int count = 2;', 1)
        self.assertEqual(cpp.bindings(full), {'count': 'renamed'})
        with self.assertRaises(ValueError):
            cpp.Source('/* TOMO_TOOL_BIND x */a; /* TOMO_TOOL_BIND x */b;')

    def test_function_braces_and_marker(self):
        source = cpp.Source('/* TOMO_TOOL_FUNCTION entry */ template <bool B>\n'
                            'void renamed() { const char* s = R"({})"; if (B) {} }')
        self.assertIn('renamed', str(cpp.function(source, 'entry')))
        with self.assertRaises(ValueError):
            cpp.function(source + source, 'entry')
        with self.assertRaises(ValueError):
            cpp.function(cpp.Source('void x(); void x(){} void x(){}'), 'x')

    def test_splices_and_punctuation(self):
        self.assertEqual(cpp.tokens('fo' + '\\\n' + 'o();'), cpp.tokens('foo();'))
        self.assertEqual(cpp.tokens('// hidden ' + '\\\n' + 'site();\nreal();'), cpp.tokens('real();'))
        self.assertNotEqual(cpp.tokens('1e+3'), cpp.tokens('1e +3'))
        self.assertNotEqual(cpp.tokens('x >>= 1'), cpp.tokens('x >> = 1'))
        self.assertNotEqual(cpp.compact('x + + y'), cpp.compact('x ++ y'))
        self.assertEqual(cpp.bindings('R"(/* TOMO_TOOL_BIND x */ y)"'), {})

    def test_marker_manifest(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / 'tools/source_anchors.json').read_text())
        self.assertTrue(manifest)
        for filename in manifest:
            cpp.read(root / filename)

    def test_per_object_rules_name_real_sources(self):
        root = Path(__file__).resolve().parents[1]
        makefile = (root / 'Makefile').read_text()
        rules = re.findall(r'^([^#\n]+): (?:override )?CXXFLAGS \+=', makefile, re.M)
        sources = {match for rule in rules for match in re.findall(r'(src/[\w/]+)\.o', rule)}
        self.assertGreater(len(sources), 20)
        for source in sources:
            self.assertTrue((root / (source + '.cc')).is_file(),
                            'per-object budget lost its source: ' + source)

    def test_table_is_nonempty_and_unique(self):
        text = 'static const CommandSpec kTable [] = { {"GET", get}, {"SET", set} };'
        self.assertEqual(cpp.command_names(text), ['GET', 'SET'])
        for broken in (text + text, text.replace('kTable', 'missing'),
                       'static const CommandSpec kTable[] = {};'):
            with self.assertRaises(ValueError):
                cpp.command_names(broken)

    def test_symbol_lengths_and_digit_ending_namespace(self):
        aliases = {'function_snapshot_save': 'snapshot_image', 'ExLoopT': 'Executor', 'run': 'loop'}
        for prefix in ('_ZN4tomo', '_ZN8tomo_db0'):
            name = prefix + '22function_snapshot_saveEv'
            changed = cpp.rename_symbol(name, aliases)
            self.assertEqual(changed, prefix + '14snapshot_imageEv')
            self.assertEqual(cpp.rename_symbol(changed, {v:k for k,v in aliases.items()}), name)
        self.assertEqual(cpp.rename_symbol('_ZN4tomo7ExLoopTILb1EE3runEv', aliases),
                         '_ZN4tomo8ExecutorILb1EE4loopEv')
        # A digit sequence inside another complete identifier is not a length.
        name = '_ZN4tomo11X6IoLoopXXXEv'
        self.assertEqual(cpp.rename_symbol(name, {'IoLoop':'NetworkLoop'}), name)


if __name__ == '__main__':
    unittest.main()
