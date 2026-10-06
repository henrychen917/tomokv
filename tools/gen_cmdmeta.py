#!/usr/bin/env python3
"""Generate cold metadata from pinned Redis 7.4.10 JSON or its public COMMAND reply.

The JSON path is offline: it never starts or connects to a server. Normal builds consume the
checked-in include; --check regenerates it and reports any drift.
"""

import argparse
import difflib
import json
import pathlib
import re
import socket
import sys


COMMAND_SOURCES = [
    "src/cmd/t_string.cc", "src/cmd/t_hash.cc", "src/cmd/t_hash_ttl.cc",
    "src/cmd/t_list.cc", "src/cmd/t_set.cc", "src/cmd/t_zset.cc",
    "src/cmd/t_zset_ops.cc", "src/cmd/geo.cc", "src/cmd/t_stream.cc",
    "src/cmd/t_stream_groups.cc", "src/cmd/t_server.cc", "src/cmd/scripting.cc",
    "src/cmd/functions.cc", "src/cmd/server_tail.cc", "src/cmd/slowlog.cc",
    "src/cmd/lcs.cc", "src/cmd/cmdgap.cc", "src/cmd/pfdebug.cc",
]

ACL_CATEGORIES = [
    "keyspace", "read", "write", "set", "sortedset", "list", "hash", "string",
    "bitmap", "hyperloglog", "geo", "stream", "pubsub", "admin", "fast", "slow",
    "blocking", "dangerous", "connection", "transaction", "scripting",
]

REDIS_VERSION = "7.4.10"
REDIS_REVISION = "f103d127b9747965e28f20615ef790332661fc68"
# Public reply order in Redis 7.4.10 server.c, addReplyFlagsForCommand/KeyArgs.
COMMAND_FLAG_ORDER = """write readonly denyoom module admin pubsub noscript blocking loading
stale skip_monitor skip_slowlog asking fast no_auth no_mandatory_keys no_async_loading
no_multi movablekeys allow_busy""".split()
KEY_FLAG_ORDER = "RO RW OW RM access update insert delete not_key incomplete variable_flags".split()


def legacy_keys(specs):
    """Redis's legacy first/last/step projection, including movablekeys detection."""
    if not specs:
        return (0, 0, 0), False
    if len(specs) == 1 and "index" in specs[0]["begin_search"] and "range" in specs[0]["find_keys"]:
        spec = specs[0]
        first = spec["begin_search"]["index"]["pos"]
        find = spec["find_keys"]["range"]
        last = find["lastkey"]
        return (first, last + first if last >= 0 else last, find["step"]), "INCOMPLETE" in spec["flags"]
    first, last, previous, movable = None, 0, 0, False
    for spec in specs:
        begin, find = spec["begin_search"], spec["find_keys"]
        if "index" not in begin or "range" not in find:
            movable = True
            continue
        pos, span = begin["index"]["pos"], find["range"]
        if span["step"] != 1 or (previous and previous != pos - 1):
            movable = True
            continue
        movable |= "INCOMPLETE" in spec["flags"]
        first = min(first, pos) if first is not None else pos
        end = span["lastkey"] + pos if span["lastkey"] >= 0 else span["lastkey"]
        last = max((last, end), key=lambda value: value & 0xffffffff)
        previous = last
    return ((first, last, 1), movable) if first is not None else ((0, 0, 0), True)


def json_key_spec(spec):
    result = []
    if "notes" in spec:
        result += [b"notes", spec["notes"].encode()]
    flags = {flag if flag in ("RO", "RW", "OW", "RM") else flag.lower()
             for flag in spec["flags"]}
    if flags - set(KEY_FLAG_ORDER):
        raise ValueError("unknown key flags: %r" % (flags - set(KEY_FLAG_ORDER)))
    result += [b"flags", [flag.encode() for flag in KEY_FLAG_ORDER if flag in flags]]
    # JSON uses pos/step, while COMMAND uses index/keystep.
    fields = {"index": [("pos", "index")],
              "keyword": [("keyword", "keyword"), ("startfrom", "startfrom")],
              "range": [("lastkey", "lastkey"), ("step", "keystep"), ("limit", "limit")],
              "keynum": [("keynumidx", "keynumidx"), ("firstkey", "firstkey"), ("step", "keystep")],
              "unknown": []}
    for part in ("begin_search", "find_keys"):
        kind, values = next(iter(spec[part].items()))
        payload = []
        for source, target in fields[kind]:
            value = values[source]
            payload += [target.encode(), value.encode() if isinstance(value, str) else value]
        result += [part.encode(), [b"type", kind.encode(), b"spec", payload]]
    return result


def redis_json_commands(redis_root):
    """Build the public ten-field COMMAND schema from the pinned command JSON.

    Category defaults and legacy keys follow server.c's metadata initialization. Sentinel-only
    commands are absent from a normal Redis server, just as in its live COMMAND reply.
    """
    version = (redis_root / "src/version.h").read_text()
    if '#define REDIS_VERSION "%s"' % REDIS_VERSION not in version:
        raise ValueError("expected pinned Redis %s JSON checkout" % REDIS_VERSION)
    rows, children = {}, {}
    files = sorted((redis_root / "src/commands").glob("*.json"))
    if not files:
        raise ValueError("no Redis command JSON under %s" % redis_root)
    for path in files:
        for name, definition in json.loads(path.read_text()).items():
            raw_flags = set(definition.get("command_flags", []))
            if "ONLY_SENTINEL" in raw_flags:
                continue
            parent = definition.get("container", "").lower()
            full = (parent + "|" if parent else "") + name.lower()
            flags = {flag.lower() for flag in raw_flags}
            specs = definition.get("key_specs", [])
            legacy, movable = legacy_keys(specs)
            if movable:
                flags.add("movablekeys")
            categories = {category.lower() for category in definition.get("acl_categories", [])}
            if "write" in flags:
                categories.add("write")
            if "readonly" in flags and "scripting" not in categories:
                categories.add("read")
            if "admin" in flags:
                categories.update(("admin", "dangerous"))
            categories.update(flags & {"pubsub", "fast", "blocking"})
            if "fast" not in categories:
                categories.add("slow")
            if categories - set(ACL_CATEGORIES):
                raise ValueError("unknown ACL categories: %r" % categories)
            row = [full.encode(), definition["arity"],
                   [flag.encode() for flag in COMMAND_FLAG_ORDER if flag in flags], *legacy,
                   [("@" + category).encode() for category in ACL_CATEGORIES if category in categories],
                   [tip.lower().encode() for tip in definition.get("command_tips", [])],
                   [json_key_spec(spec) for spec in specs], []]
            if full in rows:
                raise ValueError("duplicate Redis command %s" % full)
            rows[full] = row
            if parent:
                children.setdefault(parent, []).append(row)
    for parent, subcommands in children.items():
        rows[parent][9] = subcommands
    return [row for name, row in rows.items() if "|" not in name]


def local_commands():
    # Existing TomoKV-only FLIP contract (3ca2c450e); never infer it from the generated artifact.
    return [[b"flip", -2, [b"write", b"admin", b"noscript", b"no_async_loading", b"no_multi"],
             0, 0, 0, [b"@write", b"@admin", b"@slow", b"@dangerous"], [], [], []]]


def encode(argv):
    result = b"*%d\r\n" % len(argv)
    for argument in argv:
        value = argument.encode() if isinstance(argument, str) else argument
        result += b"$%d\r\n" % len(value) + value + b"\r\n"
    return result


def read_reply(stream):
    line = stream.readline()
    if not line:
        raise EOFError("oracle closed while reading COMMAND metadata")
    marker, payload = line[:1], line[1:-2]
    if marker == b"+":
        return payload
    if marker == b":":
        return int(payload)
    if marker == b"$":
        length = int(payload)
        return None if length < 0 else stream.read(length + 2)[:-2]
    if marker in (b"*", b"~"):
        count = int(payload)
        return None if count < 0 else [read_reply(stream) for _ in range(count)]
    if marker == b"-":
        raise ValueError("oracle returned error: %s" % payload.decode(errors="replace"))
    raise ValueError("unsupported oracle RESP marker %r" % marker)


def oracle_command(host, port):
    with socket.create_connection((host, port), timeout=10) as connection:
        stream = connection.makefile("rb")
        connection.sendall(encode(["COMMAND"]))
        return read_reply(stream)


def tomo_commands(repo_root):
    names = []
    for relative in COMMAND_SOURCES:
        source = (repo_root / relative).read_text()
        match = re.search(r"static const CommandSpec kTable\[\] = \{(.*?)\n\};",
                          source, re.DOTALL)
        if not match:
            raise ValueError("cannot find CommandSpec table in %s" % relative)
        names.extend(re.findall(r'^\s*\{"([A-Z][A-Z0-9_-]*)"\s*,',
                                match.group(1), re.MULTILINE))
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError("duplicate TomoKV commands: %s" % ", ".join(duplicates))
    return set(name.lower() for name in names)


def key_value_array(value):
    if not isinstance(value, list) or len(value) % 2:
        raise ValueError("expected flat key/value array, found %r" % (value,))
    return {value[index]: value[index + 1] for index in range(0, len(value), 2)}


def frozen(value):
    if isinstance(value, list):
        return tuple(frozen(item) for item in value)
    return value


def c_string(value):
    if value is None:
        return "nullptr"
    text = value.decode() if isinstance(value, bytes) else str(value)
    escaped = (text.replace("\\", "\\\\").replace('"', '\\"')
                    .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"))
    return '"%s"' % escaped


def ordered_union(rows, field):
    first_seen = []
    edges = {}
    indegree = {}
    for row in rows:
        values = field(row)
        for name in values:
            if name not in first_seen:
                first_seen.append(name)
                edges[name] = set()
                indegree[name] = 0
        for left, right in zip(values, values[1:]):
            if right not in edges[left]:
                edges[left].add(right)
                indegree[right] += 1
    order = []
    while len(order) != len(first_seen):
        ready = [name for name in first_seen if not indegree[name] and name not in order]
        if not ready:
            raise ValueError("metadata flags have conflicting observed orders")
        name = ready[0]
        order.append(name)
        for right in edges[name]:
            indegree[right] -= 1
    # Redis renders each set in a consistent partial order. Assert the compact bit-mask renderer
    # preserves every observed row byte-for-byte.
    rank = {name: index for index, name in enumerate(order)}
    for row in rows:
        values = field(row)
        if values != sorted(values, key=rank.get):
            raise ValueError("metadata flags have no stable global order on %r" % row[0])
    return order


def mask_for(values, order):
    result = 0
    for value in values:
        result |= 1 << order.index(value)
    return result


def generated_text(repo_root, host=None, port=None, *, redis_root=None):
    implemented = tomo_commands(repo_root)
    top_rows = (redis_json_commands(redis_root) if redis_root is not None
                else oracle_command(host, port))
    top_rows += [row for row in local_commands() if row[0].decode() in implemented]
    redis_top = {row[0].decode(): row for row in top_rows}
    missing = sorted(implemented - set(redis_top))
    if missing:
        raise ValueError("TomoKV commands absent from oracle metadata: %s" % ", ".join(missing))

    # Pack auxiliary tables in the historical order so retained rows keep exactly their flag
    # masks and tip/key-spec offsets. Filter the advertised rows below, after packing: children
    # of unimplemented containers must never become standalone command metadata.
    rows = []
    for top in top_rows:
        if top[0].decode() in implemented:
            rows.append(top)
        rows.extend(top[9])
    # Redis dictionaries intentionally randomize traversal order. COMMAND LIST/ACL CAT are set
    # contracts and populated container child order is likewise not stable across oracle boots;
    # sort the generated rows so this checked-in artifact is reproducible.
    rows.sort(key=lambda row: row[0])

    # Local rows were added after the original Redis mask layout was frozen.
    local_names = {row[0] for row in local_commands()}
    command_flags = ordered_union([row for row in rows if row[0] not in local_names],
                                  lambda row: [item.decode() for item in row[2]])
    all_specs = []
    for row in rows:
        all_specs.extend(row[8])
    key_flags = ordered_union(all_specs, lambda spec: [item.decode()
                                                       for item in key_value_array(spec)[b"flags"]])

    unique_specs = []
    spec_index = {}
    for spec in all_specs:
        identity = frozen(spec)
        if identity not in spec_index:
            spec_index[identity] = len(unique_specs)
            unique_specs.append(spec)

    tip_refs = []
    key_spec_refs = []
    metadata_rows = []
    acl_rank = {"@" + name: index for index, name in enumerate(ACL_CATEGORIES)}
    for row in rows:
        name = row[0].decode()
        flags = [item.decode() for item in row[2]]
        categories = [item.decode() for item in row[6]]
        unknown_categories = sorted(set(categories) - set(acl_rank))
        if unknown_categories:
            raise ValueError("unknown ACL categories on %s: %r" % (name, unknown_categories))
        tips_offset = len(tip_refs)
        tip_refs.extend(item.decode() for item in row[7])
        specs_offset = len(key_spec_refs)
        key_spec_refs.extend(spec_index[frozen(spec)] for spec in row[8])
        if name.split("|", 1)[0] in implemented:
            metadata_rows.append((
                name, row[1], mask_for(flags, command_flags), row[3], row[4], row[5],
                sum(1 << acl_rank[item] for item in categories),
                tips_offset, len(row[7]), specs_offset, len(row[8]),
            ))

    lines = [
        "// Generated by tools/gen_cmdmeta.py from pinned Redis 7.4.10 metadata and the registry.",
        "// Do not edit; regenerate with --redis-root <Redis 7.4.10 checkout>.",
        "",
        "static constexpr const char* kGeneratedCommandFlagNames[] = {",
    ]
    lines.extend("    %s," % c_string(name) for name in command_flags)
    lines.extend(["};", "", "static constexpr const char* kGeneratedKeyFlagNames[] = {"])
    lines.extend("    %s," % c_string(name) for name in key_flags)
    lines.extend(["};", "", "static constexpr const char* kGeneratedTipRefs[] = {"])
    lines.extend("    %s," % c_string(name) for name in tip_refs)
    lines.extend(["};", "", "static constexpr uint8_t kGeneratedKeySpecRefs[] = {"])
    for start in range(0, len(key_spec_refs), 20):
        lines.append("    " + ", ".join(str(item) for item in key_spec_refs[start:start + 20]) + ",")
    lines.extend(["};", "", "static constexpr GeneratedKeySpec kGeneratedKeySpecs[] = {"])

    for spec in unique_specs:
        fields = key_value_array(spec)
        notes = fields.get(b"notes")
        flags = [item.decode() for item in fields[b"flags"]]
        begin = key_value_array(fields[b"begin_search"])
        begin_type = begin[b"type"].decode()
        begin_spec = key_value_array(begin[b"spec"])
        find = key_value_array(fields[b"find_keys"])
        find_type = find[b"type"].decode()
        find_spec = key_value_array(find[b"spec"])
        begin_enum = {"index": "BeginType::Index", "keyword": "BeginType::Keyword",
                      "unknown": "BeginType::Unknown"}[begin_type]
        find_enum = {"range": "FindType::Range", "keynum": "FindType::Keynum",
                     "unknown": "FindType::Unknown"}[find_type]
        lines.append(
            "    {%s, 0x%04x, %s, %d, %s, %d, %s, %d, %d, %d, %d, %d}," % (
                c_string(notes), mask_for(flags, key_flags), begin_enum,
                begin_spec.get(b"index", 0), c_string(begin_spec.get(b"keyword")),
                begin_spec.get(b"startfrom", 0), find_enum,
                find_spec.get(b"lastkey", 0), find_spec.get(b"keystep", 0),
                find_spec.get(b"limit", 0), find_spec.get(b"keynumidx", 0),
                find_spec.get(b"firstkey", 0)))

    lines.extend(["};", "", "static constexpr CommandMetadata kGeneratedMetadata[] = {"])
    for row in metadata_rows:
        name, arity, flags, first, last, step, categories, tips_at, tip_count, specs_at, spec_count = row
        lines.append(
            "    {%s, %d, 0x%016xULL, %d, %d, %d, 0x%016xULL, %d, %d, %d, %d}," % (
                c_string(name), arity, flags, first, last, step, categories,
                tips_at, tip_count, specs_at, spec_count))
    lines.extend(["};", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(pathlib.Path(__file__).resolve().parents[1]))
    parser.add_argument("--host", default="127.0.0.1")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--port", type=int, help="query an already running Redis oracle")
    source.add_argument("--redis-root", type=pathlib.Path, help="offline pinned Redis 7.4.10 checkout")
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output")
    destination.add_argument("--check")
    args = parser.parse_args()
    root = pathlib.Path(args.repo_root)
    generated = generated_text(root, args.host, args.port, redis_root=args.redis_root)
    if args.output:
        pathlib.Path(args.output).write_text(generated)
        return
    actual = pathlib.Path(args.check).read_text() if pathlib.Path(args.check).exists() else ""
    if actual != generated:
        sys.stderr.writelines(difflib.unified_diff(
            actual.splitlines(True), generated.splitlines(True),
            fromfile=args.check, tofile="regenerated Redis metadata"))
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit("gen_cmdmeta.py: %s" % error)
