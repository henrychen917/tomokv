#!/usr/bin/env python3
"""Search tests/ for old/new changed text, including plain and escaped literals, using grep."""
import ast
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/flakeaudit2/evidence"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/cpp")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    diff = subprocess.check_output(["git", "diff", "--unified=0", args.base, "--", "tests/"],
                                   cwd=ROOT, text=True)
    changed = {}
    path = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            changed[path] = [set(), set()]
        elif line.startswith("@@"):
            match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            for index, start, count in ((0, match[1], match[2]), (1, match[3], match[4])):
                changed[path][index].update(range(int(start), int(start) + int(count or 1)))
    patterns = set()
    for path, versions in changed.items():
        old = subprocess.check_output(["git", "show", args.base + ":" + path], cwd=ROOT, text=True)
        new = (ROOT / path).read_text()
        for source, lines in zip((old, new), versions):
            # Full changed source lines cover shell text, comments, and source spellings.
            for number, text in enumerate(source.splitlines(), 1):
                if number in lines and len(text.strip()) >= 3:
                    patterns.add(text.strip())
            if not path.endswith(".py"):
                continue
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, (str, bytes)):
                    continue
                if not lines.intersection(range(node.lineno, node.end_lineno + 1)):
                    continue
                value = node.value.decode("latin1") if isinstance(node.value, bytes) else node.value
                if len(value) < 3:
                    continue
                # Split real multiline values into nonempty exact lines; do not feed grep an
                # empty pattern (which would falsely match every source line).
                patterns.update(line for line in value.splitlines() if len(line) >= 3)
                patterns.add(value.encode("unicode_escape").decode("ascii"))
                patterns.add(json.dumps(value, ensure_ascii=True)[1:-1])
                patterns.add(repr(node.value))
    patterns = sorted(p for p in patterns if p.strip() and "\x00" not in p and "\n" not in p and "\r" not in p)
    pattern_file = args.output / "changed-text-patterns.txt"
    pattern_file.write_text("\n".join(patterns) + "\n")
    command = ["grep", "-RFnI", "--exclude-dir=__pycache__", "-f", str(pattern_file), "tests/"]
    result = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode in (0, 1), result.stderr
    by_file = Counter(line.split(b":", 1)[0].decode() for line in result.stdout.splitlines())
    (args.output / "changed-text-matches.json").write_text(json.dumps(dict(sorted(by_file.items())), indent=2) + "\n")
    (args.output / "changed-text-search.json").write_text(json.dumps(dict(command=command, base=args.base,
        rc=result.returncode, changed_files=sorted(changed), patterns=len(patterns),
        matched_source_lines=len(result.stdout.splitlines()), full_output_sha256=hashlib.sha256(result.stdout).hexdigest(),
        method="Changed source text plus decoded, unicode_escape, JSON-escaped and repr literal spellings; old and new versions."),
        indent=2) + "\n")
    print("grep text audit: %d patterns, %d matched source lines" %
          (len(patterns), len(result.stdout.splitlines())))


if __name__ == "__main__":
    main()
