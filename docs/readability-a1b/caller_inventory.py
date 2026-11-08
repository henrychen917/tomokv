#!/usr/bin/env python3
"""Conservative executable caller graph, including virtual pre-archive paths.

Never executes the scanned programs. Unresolved dynamic module imports retain
every local module; unresolved executable pathnames require review. This is a
bounded repository analysis, not a proof about arbitrary Python or shell. The
separate stem sweep is a review backstop, not evidence that a word is an import.
"""
import argparse
import ast
from collections import defaultdict, deque
import fnmatch
import itertools
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
UNKNOWN = '*'
CODE = {'.py', '.sh', '.mk', '.cc', '.h', '.inc', '.c'}
SHELL_VAR = re.compile(r'\$\{([^}]+)\}|\$\(([^()]*)\)|\$([A-Za-z_]\w*|[0-9@*])')


def combine(left, right, sep=''):
    if len(left) * len(right) > 256:
        return {UNKNOWN}
    return {a + sep + b for a in left for b in right}


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return dotted(node.value) + '.' + node.attr
    return ''


def values(node, env):
    """Finite strings, or a wildcard preserving the known path prefix/suffix."""
    if isinstance(node, ast.Constant):
        return {str(node.value)} if isinstance(node.value, (str, int)) else {UNKNOWN}
    if isinstance(node, ast.Name):
        return env.get(node.id, {UNKNOWN})
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return set().union(*(values(x, env) for x in node.elts))
    if isinstance(node, ast.IfExp):
        return values(node.body, env) | values(node.orelse, env)
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, (ast.Add, ast.Div)):
            return combine(values(node.left, env), values(node.right, env), '/' if isinstance(node.op, ast.Div) else '')
        if isinstance(node.op, ast.Mod):
            return {re.sub(r'%[-+.#0-9]*[sdr]', '*', s) for s in values(node.left, env)}
    if isinstance(node, ast.JoinedStr):
        result = {''}
        for part in node.values:
            result = combine(result, values(part.value if isinstance(part, ast.FormattedValue) else part, env))
        return result
    if isinstance(node, ast.Attribute) and node.attr == 'parent':
        return {str(PurePosixPath(s).parent) for s in values(node.value, env)}
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == 'parents':
        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, int):
            result = set()
            for s in values(node.value.value, env):
                parents = PurePosixPath(s).parents
                result.add(str(parents[node.slice.value]) if node.slice.value < len(parents) else UNKNOWN)
            return result
    if isinstance(node, ast.Call):
        name = dotted(node.func)
        if name in ('str', 'Path', 'pathlib.Path', 'PurePath') and node.args:
            return values(node.args[0], env)
        if isinstance(node.func, ast.Attribute):
            base = values(node.func.value, env)
            if node.func.attr in ('resolve', 'absolute', 'as_posix'):
                return base
            if node.func.attr == 'split':
                return {part for s in base for part in s.split()}
            if node.func.attr == 'format':
                result = set()
                args = [values(a, env) for a in node.args]
                if len(list(itertools.islice(itertools.product(*args), 257))) <= 256:
                    for s in base:
                        for arg in itertools.product(*args):
                            try:
                                result.add(s.format(*arg, **{k.arg: next(iter(values(k.value, env))) for k in node.keywords if k.arg}))
                            except (KeyError, IndexError, ValueError, AttributeError):
                                result.add(re.sub(r'\{[^}]*\}', '*', s))
                return result or {UNKNOWN}
            if node.func.attr == 'join' and node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
                result = {''}
                for i, arg in enumerate(node.args[0].elts):
                    if i:
                        result = combine(result, base)
                    result = combine(result, values(arg, env))
                return result
        if name in ('os.path.join',) and node.args:
            result = values(node.args[0], env)
            for arg in node.args[1:]:
                result = combine(result, values(arg, env), '/')
            return result
        if name in ('os.path.dirname',) and node.args:
            return {str(PurePosixPath(s).parent) for s in values(node.args[0], env)}
        if name in ('os.path.abspath', 'shlex.split') and node.args:
            return values(node.args[0], env)
    return {UNKNOWN}


def python_env(tree, path):
    env = {'__file__': {path}}
    bindings = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if node.value:
                bindings += [(t.id, node.value) for t in targets if isinstance(t, ast.Name)]
        if isinstance(node, (ast.For, ast.comprehension)) and isinstance(node.target, ast.Name):
            bindings.append((node.target.id, node.iter))
    # Starting unknown expressions only after the fixed point avoids poisoning
    # forward references. Unbounded cycles widen rather than disappear.
    for _ in range(16):
        changed = False
        for key, expression in bindings:
            result = values(expression, env)
            if result == {UNKNOWN}:
                continue
            old = env.get(key, set())
            new = old | result
            if len(new) > 256:
                new = {UNKNOWN}
            if new != old:
                env[key] = new
                changed = True
        if not changed:
            break
    return env


def shell_expand(text, env):
    result, position = {''}, 0
    for match in SHELL_VAR.finditer(text):
        result = combine(result, {text[position:match.start()]})
        key = next(x for x in match.groups() if x is not None)
        result = combine(result, env.get(key, {UNKNOWN}))
        position = match.end()
    return combine(result, {text[position:]})


def shell_code(text):
    # shlex comments respect quoted '#' unlike a line.strip/split heuristic.
    lines = []
    logical, pending, count = [], '', 0
    for physical in text.splitlines():
        count += 1
        if physical.endswith('\\'):
            pending += physical[:-1] + ' '
            continue
        logical.append(pending + physical)
        logical.extend([''] * (count - 1))
        pending, count = '', 0
    if pending:
        logical.append(pending)
        logical.extend([''] * (count - 1))
    for line in logical:
        lexer = shlex.shlex(line, posix=False)
        lexer.whitespace_split = True
        lexer.commenters = '#'
        try:
            lines.append(' '.join(lexer))
        except ValueError:
            # Here-doc contents can contain unmatched quotes. Keep the whole
            # non-comment line, never silently drop executable text.
            lines.append(line if not line.lstrip().startswith('#') else '')
    return '\n'.join(lines)


def shell_env(code):
    bindings = []
    for match in re.finditer(r'\bfor\s+(\w+)\s+in\s+([^;\n]+)', code):
        bindings.append((match[1], match[2]))
    for match in re.finditer(r'(?:^|[\s;])([A-Za-z_]\w*)\s*(?:[:+?]?=)\s*("[^"\n]*"|\'[^\'\n]*\'|[^\s;]+)', code):
        bindings.append((match[1], match[2].strip('\'"')))
    env = {}
    for _ in range(16):
        changed = False
        for key, expression in bindings:
            result = set()
            for s in shell_expand(expression, env):
                result.update(s.strip('\'"()').split())
            if UNKNOWN in result:
                result.remove(UNKNOWN)
            new = env.get(key, set()) | result
            if len(new) > 256:
                new = {UNKNOWN}
            if new != env.get(key, set()):
                env[key] = new
                changed = True
        if not changed:
            break
    return env


class Inventory:
    def __init__(self, texts):
        self.texts = texts
        self.edges = defaultdict(list)
        self.dynamic = []
        self.review = []
        self.search_paths = {}
        self.byname = defaultdict(list)
        for path in texts:
            self.byname[PurePosixPath(path).name].append(path)

    def add(self, caller, target, line, kind, expression):
        if caller != target:
            edge = dict(target=target, line=line, kind=kind, expression=expression[:240])
            if edge not in self.edges[caller]:
                self.edges[caller].append(edge)

    def paths(self, caller, candidates, line, kind, expression):
        for value in candidates:
            # Match complete path-bearing tokens, including command strings.
            for match in re.finditer(r'(?:[\w.*-]+/)*[\w.*-]+\.(?:py|sh|mk|cc|h|inc|c)\b', value):
                pattern = match[0].removeprefix('./')
                if PurePosixPath(pattern).stem.strip('*') == '':
                    # A glob/copy or generated temporary filename is not a
                    # requirement for every archived module. Execution sinks
                    # with this shape require a separately recorded review.
                    if kind != 'code-path':
                        item = dict(caller=caller, line=line, kind=kind, expression=expression, pattern=pattern)
                        if item not in self.review:
                            self.review.append(item)
                    continue
                if pattern.startswith('tools/archive/'):
                    continue
                if '/' in pattern and not pattern.startswith(('tests/', 'tools/', 'docs/')):
                    embedded = re.search(r'(?:tests|tools|docs)/.*', pattern)
                    if embedded:
                        pattern = embedded[0]
                candidates_by_name = self.byname.get(PurePosixPath(pattern).name, ()) if '*' not in pattern else self.texts
                for target in candidates_by_name:
                    if fnmatch.fnmatchcase(target if '/' in pattern else PurePosixPath(target).name, pattern):
                        self.add(caller, target, line, kind, expression)
            if '*' in value and re.search(r'(?:tests|tools)/', value):
                self.dynamic.append(dict(caller=caller, line=line, kind=kind, pattern=value[:240]))

    def module(self, caller, name, directories, line, kind):
        pattern = name.replace('.', '/')
        candidates = [p for p in self.texts if p.endswith('.py') and
                      (fnmatch.fnmatchcase(p, pattern + '.py') or
                       fnmatch.fnmatchcase(p, '*/' + pattern + '.py') or
                       fnmatch.fnmatchcase(p, pattern + '/__init__.py'))]
        directories = {str(PurePosixPath(d)) for d in directories}
        scoped = [p for p in candidates if any(p == (d.rstrip('/') + '/' if d not in ('.', '') else '') + pattern + '.py' for d in directories)]
        # Conservatively keep all matches if a runtime sys.path is not known.
        for target in scoped or candidates:
            self.add(caller, target, line, kind, name)
        if '*' in name:
            self.dynamic.append(dict(caller=caller, line=line, kind=kind, pattern=name))

    def python(self, path, text):
        tree = ast.parse(text, filename=path)
        env = python_env(tree, path)
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                aliases.update({a.asname or a.name: a.name for a in node.names})
            elif isinstance(node, ast.ImportFrom) and node.module:
                aliases.update({a.asname or a.name: node.module + '.' + a.name for a in node.names})
        directories = {str(PurePosixPath(path).parent), '.'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and dotted(node.func) in ('sys.path.insert', 'sys.path.append', 'sys.path.extend'):
                directories |= values(node.args[-1], env)
            if isinstance(node, ast.Assign) and any(dotted(t.value if isinstance(t, ast.Subscript) else t) == 'sys.path' for t in node.targets):
                directories |= values(node.value, env)
        directories = {str(PurePosixPath(d)) for d in directories}
        self.search_paths[path] = sorted(directories)
        docstrings = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.module(path, alias.name, directories, node.lineno, 'import')
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.module(path, node.module, directories, node.lineno, 'from-import')
                for alias in node.names:
                    self.module(path, ((node.module + '.') if node.module else '') + alias.name, directories, node.lineno, 'from-import-member')
            elif isinstance(node, ast.Call):
                name = dotted(node.func)
                head, _, tail = name.partition('.')
                name = aliases.get(head, head) + ('.' + tail if tail else '')
                if name in ('importlib.import_module', '__import__', 'runpy.run_module'):
                    for mod in values(node.args[0], env):
                        self.module(path, mod, directories, node.lineno, name)
                if name in ('importlib.util.spec_from_file_location', 'runpy.run_path'):
                    arg = node.args[1 if name.endswith('spec_from_file_location') else 0]
                    got = values(arg, env)
                    if got == {UNKNOWN}:
                        got = {'*.py'}
                    self.paths(path, got, node.lineno, name, ast.unparse(node))
                if name.startswith(('subprocess.', 'os.system', 'os.exec', 'os.spawn')) and node.args:
                    self.paths(path, values(node.args[0], env), node.lineno, 'process-argv', ast.unparse(node))
            if isinstance(node, ast.expr) and id(node) not in docstrings:
                # Includes strings passed through project wrappers, f-strings,
                # Path joins, command strings and generated Python/shell code.
                if isinstance(node, (ast.Constant, ast.JoinedStr, ast.BinOp, ast.Call)):
                    self.paths(path, values(node, env), node.lineno, 'code-path', ast.unparse(node))

    def scan(self, path):
        text = self.texts[path]
        if path.endswith('.py'):
            self.python(path, text)
        elif PurePosixPath(path).suffix in {'.cc', '.c', '.h', '.inc'}:
            # Source fixtures can name other fixtures in includes/strings;
            # provenance comments are not executable callers.
            text = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/',
                          lambda m: m[0] if m[0].startswith('"') else '\n' * m[0].count('\n'), text)
            for i, line in enumerate(text.splitlines(), 1):
                self.paths(path, {line}, i, 'source-path', line)
        else:
            code = shell_code(text)
            env = shell_env(code)
            for i, line in enumerate(code.splitlines(), 1):
                # Expand words independently: the Cartesian product of an
                # unrelated output filename's variables must not erase an
                # executable pathname earlier in the same argv.
                for word in line.split():
                    self.paths(path, shell_expand(word, env), i, 'shell/make-path', line)

    def closure(self, roots):
        live, queue = set(roots), deque(sorted(roots))
        while queue:
            caller = queue.popleft()
            self.scan(caller)
            for edge in self.edges[caller]:
                target = edge['target']
                if target not in live:
                    live.add(target)
                    queue.append(target)
        return live


def sources(root):
    paths = subprocess.check_output(['git', 'ls-files'], cwd=root, text=True).splitlines()
    retired = json.loads((root / 'docs/readability-a1/retired.json').read_text())
    restored = root / 'docs/readability-a1b/restored.json'
    if restored.exists():
        retired += json.loads(restored.read_text())
    archived = {r['archive']: r['original'] for r in retired}
    texts = {}
    roots = set()
    for path in paths:
        if Path(path).suffix not in CODE and Path(path).name != 'Makefile':
            continue
        if not (root / path).is_file():
            continue
        if path.startswith('tools/archive/'):
            if path not in archived:
                continue
            logical = archived[path]
        else:
            logical = path
            if path == 'Makefile' or path.startswith(('tests/', 'tools/')):
                roots.add(path)
        texts[logical] = (root / path).read_text(errors='replace')
    return texts, roots, retired


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/readability-a1b/callers.json')
    args = parser.parse_args()
    texts, roots, retired = sources(args.root)
    graph = Inventory(texts)
    live = graph.closure(roots)
    incoming = defaultdict(list)
    for caller, edges in graph.edges.items():
        for edge in edges:
            incoming[edge['target']].append(dict(caller=caller, **edge))
    reachable = {r['original']: incoming[r['original']] for r in retired if r['original'] in live}
    output = dict(roots=sorted(roots), live=sorted(live), restored_or_required=reachable,
                  edges=dict(graph.edges), dynamic=graph.dynamic, search_paths=graph.search_paths,
                  review_required=graph.review)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + '\n')
    print(json.dumps(dict(roots=len(roots), reachable=len(live), archived_reachable=sorted(reachable),
                         dynamic_sites=len(graph.dynamic)), indent=2))


if __name__ == '__main__':
    main()
