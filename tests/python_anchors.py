"""Stable comments identify Python statements for disposable test controls."""
import ast
import io
import tokenize


def statement(source, tree, role):
    wanted = '# TOMO_TOOL_ANCHOR ' + role
    marks = [token for token in tokenize.generate_tokens(io.StringIO(source).readline)
             if token.type == tokenize.COMMENT and token.string.strip() == wanted]
    if len(marks) != 1:
        raise ValueError(f'{role}: expected one Python anchor, found {len(marks)}')
    following = [node for node in ast.walk(tree)
                 if isinstance(node, ast.stmt) and node.lineno > marks[0].end[0]]
    if not following:
        raise ValueError(f'{role}: missing anchored statement')
    return min(following, key=lambda node: (node.lineno, node.col_offset))


class Insert(ast.NodeTransformer):
    def __init__(self, changes):
        self.changes = changes
        self.seen = set()

    def visit(self, node):
        result = super().visit(node)
        if node in self.changes:
            self.seen.add(node)
            before, after = self.changes[node]
            return [*before, result, *after]
        return result


def insert(tree, changes):
    transform = Insert(changes)
    result = transform.visit(tree)
    if transform.seen != changes.keys():
        raise ValueError('Python control did not visit every anchor')
    return ast.fix_missing_locations(result)
