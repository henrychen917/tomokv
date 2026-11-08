#!/usr/bin/env python3
"""C++ source anchors for offline checks and disposable control builders.

Match preprocessing tokens, retaining source offsets and literal spelling. Comments
are not syntax. TOMO_TOOL_BIND comments give a declaration a stable tool identity;
renames must preserve these comments. They are never emitted into a binary.
"""
from dataclasses import dataclass
from functools import lru_cache
import re


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int


LEXER = re.compile(
    r'(?P<space>\s+|\\\r?\n)|(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)|'
    r'(?P<raw>(?:u8|u|U|L)?R"(?P<delimiter>[^ ()\\\t\n]{0,16})\([\s\S]*?\)(?P=delimiter)")|'
    r'(?P<string>(?:u8|u|U|L)?"(?:\\[\s\S]|[^"\\])*"|(?:u8|u|U|L)?\'(?:\\[\s\S]|[^\'\\])*\')|'
    r'(?P<number>[0-9][a-zA-Z0-9_\'.]*)|(?P<word>[a-zA-Z_$][a-zA-Z0-9_$]*)|'
    r'(?P<punct>%:%:|%:|##|::|&&|\|\||<=|>=|==|!=|->\*|->|<<|>>|\+\+|--|\+=|-=|\*=|/=|%=|&=|\|=|\^=|\.\.\.|.)')
BIND = re.compile(r'/\*\s*TOMO_TOOL_BIND\s+(\w+)\s*\*/\s*([a-zA-Z_]\w*)')


@lru_cache(maxsize=128)
def lex(text):
    return tuple(Token(m[0], m.start(), m.end()) for m in LEXER.finditer(text)
                 if m.lastgroup not in ('space', 'comment'))


def bindings(text):
    aliases = {}
    for old, new in BIND.findall(text):
        if old in aliases:
            raise ValueError(f'duplicate TOMO_TOOL_BIND {old}')
        aliases[old] = new
    if len(set(aliases.values())) != len(aliases):
        raise ValueError('ambiguous TOMO_TOOL_BIND rename')
    return aliases


def tokens(text):
    aliases = {new: old for old, new in bindings(str(text)).items()}
    aliases.update(getattr(text, 'aliases', {}))
    return tuple(aliases.get(t.text, t.text) for t in lex(str(text)))


def normalized(text):
    return ' '.join(tokens(text))


def rename(text, names):
    out, end = [], 0
    for token in lex(str(text)):
        out.extend((str(text)[end:token.start], names.get(token.text, token.text)))
        end = token.end
    out.append(str(text)[end:])
    return ''.join(out)


class Source(str):
    """Source with token-based search/edit operations and original byte offsets.

    A replacement requires a nonzero match count. An explicit count requires
    exactly that count, never the first match of an ambiguous anchor. Use plain
    strings for logs, protocol data and Makefiles; this is only C++ syntax.
    """
    def __new__(cls, text, aliases=None):
        obj = super().__new__(cls, text)
        obj.aliases = {new: old for old, new in bindings(str(text)).items()}
        obj.aliases.update(aliases or {})
        return obj

    def __getitem__(self, key):
        value = super().__getitem__(key)
        return Source(value, self.aliases) if isinstance(key, slice) else value

    def __add__(self, other):
        return Source(str(self) + str(other), self.aliases)

    def __radd__(self, other):
        return Source(str(other) + str(self), self.aliases)

    def strip(self, chars=None):
        return Source(str(self).strip(chars), self.aliases)

    def rstrip(self, chars=None):
        return Source(str(self).rstrip(chars), self.aliases)

    def split(self, sep=None, maxsplit=-1):
        if sep is None or not tokens(sep):
            return [Source(x, self.aliases) for x in str(self).split(sep, maxsplit)]
        hits = self.spans(sep)
        if maxsplit >= 0:
            hits = hits[:maxsplit]
        parts, start = [], 0
        for begin, end in hits:
            parts.append(self[start:begin])
            start = end
        parts.append(self[start:])
        return parts

    def spans(self, needle, start=0, end=None):
        part = tokens(needle)
        if not part:
            if not needle:
                raise ValueError('empty source anchor')
            limit = len(self) if end is None else end
            return [(m.start(), m.end()) for m in re.finditer(re.escape(needle), str(self))
                    if m.start() >= start and m.end() <= limit]
        code = lex(str(self))
        values = tuple(self.aliases.get(t.text, t.text) for t in code)
        end = len(self) if end is None else end
        return [(code[i].start, code[i+len(part)-1].end)
                for i in range(len(code)-len(part)+1)
                if code[i].start >= start and code[i+len(part)-1].end <= end
                and values[i:i+len(part)] == part]

    def count(self, needle, start=0, end=None):
        return len(self.spans(needle, start, end))

    def __contains__(self, needle):
        return bool(self.spans(needle)) if tokens(needle) else str.__contains__(self, needle)

    def index(self, needle, start=0, end=None):
        hits = self.spans(needle, start, end)
        if not hits:
            raise ValueError(f'missing token anchor: {needle[:100]}')
        return hits[0][0]

    def find(self, needle, start=0, end=None):
        hits = self.spans(needle, start, end)
        return hits[0][0] if hits else -1

    def replace(self, old, new, count=-1):
        hits = self.spans(old)
        if not hits or (count >= 0 and len(hits) != count):
            raise ValueError(f'token anchor expected {count if count >= 0 else "at least one"}, found {len(hits)}: {old[:100]}')
        replacement = rename(new, {old: new for new, old in self.aliases.items()})
        result = str(self)
        for start, end in reversed(hits):
            result = result[:start] + replacement + result[end:]
        return Source(result, self.aliases)


def read(path):
    return Source(path.read_text())


def function_span(source, name):
    """Unique definition, including its template/attribute prefix when marked."""
    marker = re.compile(r'/\*\s*TOMO_TOOL_FUNCTION\s+' + re.escape(name) + r'\s*\*/')
    marks = list(marker.finditer(str(source)))
    if len(marks) > 1:
        raise ValueError(f'duplicate function marker: {name}')
    if marks:
        mark = marks[0]
        code = [t for t in lex(str(source)) if t.start >= mark.end()]
        opening = next((i for i, t in enumerate(code) if t.text == '{'), None)
        if opening is None:
            raise ValueError(f'missing function body: {name}')
        depth = 0
        for token in code[opening:]:
            depth += (token.text == '{') - (token.text == '}')
            if not depth:
                return mark.end(), code[opening].start, token.end
        raise ValueError(f'unclosed function: {name}')
    code = lex(str(source))
    values = tokens(source)
    candidates = []
    for i, value in enumerate(values):
        if value != name.split('::')[-1] or values[i+1:i+2] != ('(',):
            continue
        j, depth = i+2, 1
        while j < len(code) and depth:
            depth += (values[j] == '(') - (values[j] == ')')
            j += 1
        while j < len(code) and values[j] in ('const', 'noexcept', 'override', 'final'):
            j += 1
        if j >= len(code) or values[j] != '{':
            continue
        opening, depth, k = j, 1, j+1
        while k < len(code) and depth:
            depth += (values[k] == '{') - (values[k] == '}')
            k += 1
        if depth:
            raise ValueError(f'unclosed function: {name}')
        start = i
        while start and values[start-1] not in (';', '}', '{'):
            start -= 1
        candidates.append((code[start].start, code[opening].start, code[k-1].end))
    if marks:
        mark = marks[0]
        candidates = [(mark.end(), opening, end) for start, opening, end in candidates
                      if mark.end() <= opening and not str(source)[mark.end():opening].count(';')]
    if len(candidates) != 1:
        raise ValueError(f'{name}: expected one definition, found {len(candidates)}')
    return candidates[0]


def function(source, name):
    start, _, end = function_span(source, name)
    return Source(source[start:end], getattr(source, 'aliases', None))


def body(source, name):
    _, start, end = function_span(source, name)
    return Source(source[start:end], getattr(source, 'aliases', None))


def command_names(source):
    code = Source(source)
    anchor = 'static const CommandSpec kTable[] = {'
    hits = code.spans(anchor)
    if len(hits) != 1:
        raise ValueError(f'expected one command table, found {len(hits)}')
    start = hits[0][1] - 1
    stream = lex(str(code[start:]))
    depth, names = 0, []
    for i, token in enumerate(stream):
        if token.text == '{':
            if depth == 1:
                name = stream[i+1].text
                if not re.fullmatch(r'"[A-Z][A-Z0-9_-]*"', name):
                    raise ValueError(f'unrecognized command row: {name}')
                names.append(name[1:-1])
            depth += 1
        elif token.text == '}':
            depth -= 1
            if depth == 0:
                if not names:
                    raise ValueError('empty command table')
                return names
    raise ValueError('unclosed command table')
