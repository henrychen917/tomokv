"""Exercise caller forms that a literal filename inventory cannot see."""
import unittest
from caller_inventory import Inventory


class CallerGraph(unittest.TestCase):
    def graph(self, source, files, caller='tests/entry.py'):
        graph = Inventory({caller: source, **files})
        live = graph.closure({caller})
        return graph, live

    def test_plain_from_nested_and_transitive_imports(self):
        _, live = self.graph('import first as f\ndef later():\n from second import run\n', {
            'tests/first.py': 'from third import helper', 'tests/second.py': '', 'tests/third.py': ''})
        self.assertEqual(live, {'tests/entry.py', 'tests/first.py', 'tests/second.py', 'tests/third.py'})

    def test_sys_path_selects_module(self):
        graph, live = self.graph("from pathlib import Path\nimport sys\nROOT=Path(__file__).resolve().parents[1]\nsys.path.insert(0,str(ROOT/'tools'))\nimport library\n", {
            'tools/library.py': '', 'docs/old/library.py': ''})
        self.assertIn('tools/library.py', live)
        self.assertNotIn('docs/old/library.py', live)
        self.assertIn('tools', graph.search_paths['tests/entry.py'])

    def test_sys_path_slice_and_from_import_member(self):
        _, live = self.graph("import sys\nsys.path[:0]=['tools']\nfrom package import helper\n", {
            'tools/package/helper.py': ''})
        self.assertIn('tools/package/helper.py', live)

    def test_importlib_alias_and_computed_name(self):
        _, live = self.graph("from importlib import import_module as load\nname='helper'\nload('support_'+name)\n", {'tools/support_helper.py': ''})
        self.assertIn('tools/support_helper.py', live)

    def test_importlib_spec_and_runpy(self):
        _, live = self.graph("import importlib.util as util\nimport runpy as rp\nname='child'\nutil.spec_from_file_location('dynamic','tools/'+name+'.py')\nrp.run_path(f'tests/{name}.py')\nrp.run_module('module_child')\n", {
            'tools/child.py': '', 'tests/child.py': '', 'tools/module_child.py': ''})
        self.assertTrue({'tools/child.py', 'tests/child.py', 'tools/module_child.py'} <= live)

    def test_dunder_import(self):
        _, live = self.graph("__import__('tool_'+ 'child')", {'tools/tool_child.py': ''})
        self.assertIn('tools/tool_child.py', live)

    def test_subprocess_string_argv(self):
        _, live = self.graph("import subprocess,shlex\nnames=['alpha','beta']\nfor name in names:\n command='python3 tools/'+name+'_x.py'\n subprocess.run(shlex.split(command))\n", {
            'tools/alpha_x.py': '', 'tools/beta_x.py': ''})
        self.assertTrue({'tools/alpha_x.py', 'tools/beta_x.py'} <= live)

    def test_shell_loops_and_both_variable_spellings(self):
        _, live = self.graph('CASES="alpha beta"\nfor case in $CASES; do\n python3 "tests/$case.py"\ndone\nfor name in gamma delta; do python3 tools/${name}_x.py; done\n', {
            'tests/alpha.py': '', 'tests/beta.py': '', 'tools/gamma_x.py': '', 'tools/delta_x.py': ''}, 'tests/gate.sh')
        self.assertEqual(len(live), 5)

    def test_make_variable_and_suffix(self):
        _, live = self.graph('NAME := alpha\ncheck:\n\tpython3 tools/$(NAME)_x.py\n', {'tools/alpha_x.py': ''}, 'Makefile')
        self.assertIn('tools/alpha_x.py', live)

    def test_unrelated_argv_expansions_cannot_erase_script(self):
        flags = ' '.join(f'flag{i}' for i in range(80))
        _, live = self.graph(f'FLAGS="{flags}"\nfor suite in alpha beta gamma delta; do\n'
                             ' python3 "tests/$suite.py" "$FLAGS" >"$OUT/$suite-$FLAGS.log"\ndone\n',
                             {'tests/alpha.py': '', 'tests/beta.py': '',
                              'tests/gamma.py': '', 'tests/delta.py': ''}, 'tests/gate.sh')
        self.assertEqual(len(live), 5)

    def test_comments_docstrings_and_same_stem_source_are_not_calls(self):
        _, live = self.graph('"""from old import run"""\n# import old\nfixture="tests/old.cc"\n', {'tools/old.py': '', 'tests/old.cc': ''})
        self.assertNotIn('tools/old.py', live)
        self.assertIn('tests/old.cc', live)
        _, live = self.graph('# python3 tools/old.py\n', {'tools/old.py': ''}, 'Makefile')
        self.assertNotIn('tools/old.py', live)

    def test_unresolved_path_requires_review(self):
        graph, _ = self.graph('import runpy,sys\nrunpy.run_path(sys.argv[1])\n', {'tools/child.py': ''})
        self.assertTrue(graph.review)

    def test_explicit_archive_execution_still_requires_the_file(self):
        _, live = self.graph("import runpy\nrunpy.run_path('tools/archive/tools/child.py')\n", {'tools/child.py': ''})
        self.assertIn('tools/child.py', live)

    def test_unresolved_module_keeps_candidates(self):
        graph, live = self.graph('import importlib,sys\nimportlib.import_module(sys.argv[1])\n', {'tools/child.py': ''})
        self.assertIn('tools/child.py', live)
        self.assertTrue(graph.dynamic)


if __name__ == '__main__':
    unittest.main()
