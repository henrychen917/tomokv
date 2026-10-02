"""Check the explicit receipt fixture against gate.sh's declared full row inventory.

This is a source inventory, never execution evidence. Only literal assignments,
finite for-lists, row_begin and collect_job declarations are interpreted in Python;
no shell, server, build, workload, or run ledger is executed/read. Unsupported label
expressions fail closed. The fixture remains independently reviewed, including
duplicate occurrences. Never regenerate it from a partial gate run.
"""
from collections import Counter
import fnmatch
import json
from pathlib import Path
import re
import shlex
import sys
import unittest

from gate_history import canonical_label


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = "tests/fixtures/nullrefresh-ledger-labels.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def expand(word, values):
    def variable(match):
        binding = re.fullmatch(r"(\w+)(?:(##|#)(.*))?", match[1] or match[2])
        require(binding is not None, f"unsupported gate label expression: {word!r}")
        name, operation, pattern = binding.groups()
        require(name in values and values[name] is not None,
                f"unsupported/unbound gate label variable: {name} in {word!r}")
        value = values[name]
        if operation:
            cuts = range(len(value) + 1)
            if operation == "##":
                cuts = reversed(cuts)
            value = next((value[i:] for i in cuts if fnmatch.fnmatchcase(value[:i], pattern)), value)
        return value

    require(not any(token in word for token in ("$(", "`", "\\")),
            f"unsupported gate label expression: {word!r}")
    result = re.sub(r"\$\{([^}]+)\}|\$(\w+)", variable, word)
    require("$" not in result, f"unsupported gate label expression: {word!r}")
    return result


def declarations(source):
    """Project data declarations only; all executable shell statements are discarded."""
    root, stack = [], []
    nodes = root
    for line in source.replace("\\\n", " ").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        # Quotes protect semicolons inside labels; do/for/done may share a line.
        pieces = re.split(r";(?=(?:[^\"']|\"[^\"]*\"|'[^']*')*$)", line)
        for piece in pieces:
            piece = piece.strip()
            if piece.startswith("do "):
                piece = piece[3:]
            loop = re.fullmatch(r"for (\w+) in (.*)", piece)
            if loop:
                children = []
                nodes.append(("for", loop[1], loop[2], children))
                stack.append(nodes)
                nodes = children
            elif piece == "done":
                require(stack, "unmatched done in gate label declarations")
                nodes = stack.pop()
            elif re.match(r"(?:row_begin|collect_job)\s", piece):
                words = shlex.split(piece)
                require(len(words) >= 2, f"missing gate label: {piece}")
                nodes.append((words[0], words[1]))
            elif piece.startswith("IFS=- read -r "):
                match = re.fullmatch(r'IFS=- read -r (.*?) <<< "(.*?)"', piece)
                require(match is not None, f"unsupported gate label split: {piece}")
                nodes.append(("split", match[1].split(), match[2]))
            elif re.match(r"(?:local )?\w+=", piece):
                # Ignore irrelevant executable values. If a label uses one, expand
                # refuses its unavailable binding instead of inventing a value.
                try:
                    words = shlex.split(piece)
                except ValueError:
                    continue
                for word in words:
                    assignment = re.fullmatch(r"(\w+)=(.*)", word)
                    if assignment:
                        nodes.append(("assign", assignment[1], assignment[2]))
            elif re.search(r"\b(?:row_begin|collect_job)\s", piece):
                raise ValueError(f"unsupported gate row declaration: {piece}")
    require(not stack, "unclosed for-list in gate label declarations")
    return root


def emits(nodes):
    return any(node[0] in ("row_begin", "collect_job") or
               node[0] == "for" and emits(node[3]) for node in nodes)


def evaluate(nodes, values, collect):
    labels = []
    for kind, *args in nodes:
        if kind == "for":
            name, words, children = args
            if emits(children):
                for word in shlex.split(expand(words, values)):
                    labels += evaluate(children, dict(values, **{name: word}), collect)
        elif kind == "assign":
            try:
                values[args[0]] = expand(args[1], values)
            except ValueError:
                values[args[0]] = None
        elif kind == "split":
            names, expression = args
            parts = expand(expression, values).split("-", len(names) - 1)
            require(len(parts) == len(names), f"gate label split changed: {expression}")
            values.update(zip(names, parts))
        elif kind == "collect_job":
            labels += collect(expand(args[0], values))
        elif kind == "row_begin":
            # This one counter is deliberately canonicalized at the declaration,
            # exactly as gate.sh canonical_label does after a real measurement.
            label = re.sub(r"suppressed=\$TLS_ZC\b", "suppressed=N", args[0])
            labels.append(canonical_label(expand(label, values)))
    return labels


def source_labels(gate):
    """Successful full, non-NIC inventory, preserving repeated row occurrences.

    collect_job's full source section determines reachability/multiplicity. The
    two differential folds contribute their public job_label, not private child
    rows. The headline ABBA reporting section and optional NIC are outside it.
    """
    starts = list(re.finditer(r"^(job_\w+|feature_\w+_job)\(\)\{", gate, re.M))
    bodies = {match[1]: gate[match.end():starts[i + 1].start() if i + 1 < len(starts)
                            else gate.index("\n# ---- 0. preflight:", match.end())]
              for i, match in enumerate(starts)}
    batteries = re.search(r'^FEATURE_BATTERIES="([^"\n]*)"$', gate, re.M)
    require(batteries is not None, "gate FEATURE_BATTERIES declaration missing")
    global_values = {"FEATURE_BATTERIES": batteries[1]}
    dispatch = re.findall(r'^    ([\w*-]+)\) (\w+) "([^"]*)";;$', bodies["job_body"], re.M)

    def public_label(name):
        for match in re.finditer(r"^    ([^\n]+?)\) (.*?);;", bodies["job_label"], re.M | re.S):
            if not fnmatch.fnmatchcase(name, match[1]):
                continue
            body = match[2]
            values = {"1": name}
            # job_label's eviction conversion is presentation grammar, not work.
            split = re.search(r'IFS=- read -r (.*?) <<< "\$1"', body)
            if split:
                values.update(zip(split[1].split(), name.split("-")))
                require('[ "$mode" != armed ] || mode=fused+armed' in body,
                        "eviction job_label conversion changed; review fixture inventory")
                if values["mode"] == "armed":
                    values["mode"] = "fused+armed"
            echoed = re.findall(r"\becho (\"[^\"]*\"|'[^']*')", body)
            require(len(echoed) == 1, f"unsupported public job_label declaration: {name}")
            return canonical_label(expand(shlex.split(echoed[0])[0], values))
        raise ValueError(f"missing public job_label declaration: {name}")

    def collect(name):
        if name in ("differ-split", "differ-armed", "flipctl") or name.startswith("evict-"):
            return [public_label(name)]
        function, argument = "job_" + name, name
        for pattern, target, expression in dispatch:
            if fnmatch.fnmatchcase(name, pattern):
                function, argument = target, expand(expression, {"name": name})
                break
        require(function in bodies, f"unknown collected gate job: {name}")
        body = bodies[function]
        if function == "job_release":
            # Source-build and external-candidate arms emit the SAME single row.
            pair = re.search(r'row_begin ("[^"\n]+")\n.*?\nelse\n  row_begin \1 external-candidate',
                             body, re.S)
            require(pair is not None, "release alternative row declaration changed")
            body = body.replace("row_begin " + pair[1] + " external-candidate", ":", 1)
        return evaluate(declarations(body), dict(global_values, **{"1": argument}), collect)

    first = gate.index("\nstart_workers\n")
    last = gate.index("\n# Every worker has reaped", first)
    return evaluate(declarations(gate[first:last]), dict(global_values), collect)


def check(gate, labels):
    matches = re.findall(r"^EXPECT_FULL=([0-9]+)\b", gate, re.M)
    require(len(matches) == 1 and int(matches[0]) > 0, "full gate count missing or invalid")
    require(isinstance(labels, list) and all(isinstance(label, str) and label for label in labels),
            f"{FIXTURE}: labels must be a nonempty-string list")
    expected = source_labels(gate)
    missing = Counter(expected) - Counter(labels)
    extra = Counter(labels) - Counter(expected)
    def names(counter):
        return "; ".join(f"{label!r} (x{count})" for label, count in sorted(counter.items())) or "none"
    require(not missing and not extra and len(labels) == len(expected) == int(matches[0]),
            f"{FIXTURE}: EXPECT_FULL={matches[0]}, fixture={len(labels)}, source declarations={len(expected)}\n"
            f"Missing fixture labels: {names(missing)}\nExtra fixture labels: {names(extra)}\n"
            "Review the gate row additions/removals and update the explicit fixture, preserving duplicate "
            "occurrences. EXPECT_QUICK/EXPECT_FULL are maintainer-owned; do not change them to hide this "
            "failure. A run ledger, including a partial run, is never this check's source of truth.")
    return labels


def validate_fixture(root):
    return check((root / "tests/gate.sh").read_text(), json.loads((root / FIXTURE).read_text())["labels"])


class FixtureControls(unittest.TestCase):
    def setUp(self):
        self.gate = (ROOT / "tests/gate.sh").read_text()
        self.labels = json.loads((ROOT / FIXTURE).read_text())["labels"]

    def test_current_inventory_and_duplicate_occurrences(self):
        self.assertEqual(check(self.gate, self.labels), self.labels)
        self.assertGreater(Counter(self.labels)["AOF writer fired (records=N)"], 1)

    def test_stale_wbland_fixture_names_both_missing_labels(self):
        missing = [f"writeback policy {group} witnesses + negative controls" for group in ("clauses", "paths")]
        with self.assertRaises(ValueError) as error:
            check(self.gate, [label for label in self.labels if label not in missing])
        for label in missing:
            self.assertIn(repr(label) + " (x1)", str(error.exception))
        self.assertIn("Extra fixture labels: none", str(error.exception))

    def test_future_literal_row_names_missing_label(self):
        gate = self.gate.replace('job_wbland_units(){', 'job_wbland_units(){\n  row_begin "new literal witness"')
        with self.assertRaisesRegex(ValueError, "Missing fixture labels: 'new literal witness' "):
            check(gate, self.labels)

    def test_future_loop_row_names_missing_label(self):
        gate = self.gate.replace("for group in clauses paths;", "for group in clauses paths new-group;")
        with self.assertRaisesRegex(ValueError, "Missing fixture labels: 'writeback policy new-group witnesses"):
            check(gate, self.labels)

    def test_retired_row_names_extra_label(self):
        gate = self.gate.replace("for group in clauses paths;", "for group in clauses;")
        with self.assertRaisesRegex(ValueError, "Extra fixture labels: 'writeback policy paths witnesses"):
            check(gate, self.labels)

    def test_same_count_substitution_and_duplicate_loss_are_rejected(self):
        for label in (self.labels[0], "AOF writer fired (records=N)"):
            labels = self.labels.copy()
            labels.remove(label)
            labels.append("fabricated replacement")
            with self.subTest(label=label), self.assertRaises(ValueError) as error:
                check(self.gate, labels)
            self.assertIn(repr(label) + " (x1)", str(error.exception))
            self.assertIn("Extra fixture labels: 'fabricated replacement' (x1)", str(error.exception))

    def test_count_only_drift_is_actionable(self):
        gate = re.sub(r"^EXPECT_FULL=\d+", f"EXPECT_FULL={len(self.labels) + 1}", self.gate, flags=re.M)
        with self.assertRaisesRegex(ValueError, "EXPECT_QUICK/EXPECT_FULL are maintainer-owned"):
            check(gate, self.labels)

    def test_partial_fixture_cannot_redefine_inventory_via_count(self):
        gate = re.sub(r"^EXPECT_FULL=\d+", "EXPECT_FULL=1", self.gate, flags=re.M)
        with self.assertRaisesRegex(ValueError, "source declarations="):
            check(gate, self.labels[:1])

    def test_unsupported_label_expression_refuses_without_evaluation(self):
        for expression in ("$UNBOUND_LABEL", "$(exit 77)", "`exit 77`"):
            gate = self.gate.replace('job_wbland_units(){', f'job_wbland_units(){{\n  row_begin "{expression}"')
            with self.subTest(expression=expression), self.assertRaisesRegex(ValueError, "unsupported"):
                check(gate, self.labels)

    def test_receipt_refuses_once_before_control_setup(self):
        import contextlib
        import io
        import tempfile
        from unittest import mock
        import gate_receipt as receipt

        with tempfile.TemporaryDirectory(prefix="ledger-fixture-", dir=ROOT / "build") as directory:
            root = Path(directory)
            (root / "tests/fixtures").mkdir(parents=True)
            (root / "tests/gate.sh").write_text(self.gate)
            (root / FIXTURE).write_text(json.dumps({"labels": self.labels[:-2]}))
            diagnostic = io.StringIO()
            with mock.patch.object(receipt, "ROOT", root), contextlib.redirect_stderr(diagnostic), \
                 mock.patch.object(receipt, "git", side_effect=AssertionError("control setup must not run")):
                self.assertEqual(receipt.self_test(), 1)
            output = diagnostic.getvalue()
            self.assertEqual(output.count("RECEIPT FIXTURE REFUSED:"), 1, output)
            self.assertIn("Missing fixture labels:", output)
            self.assertNotIn("setUp", output)


def self_test():
    return 0 if unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(FixtureControls)).wasSuccessful() else 1


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--self-test"]:
            raise SystemExit(self_test())
        require(not sys.argv[1:], "usage: gate_ledger_fixture.py [--self-test]")
        print(f"Receipt label fixture: {len(validate_fixture(ROOT))} source-declared rows agree")
    except (ValueError, OSError, KeyError) as error:
        print(f"RECEIPT FIXTURE REFUSED: {error}", file=sys.stderr)
        raise SystemExit(1)
