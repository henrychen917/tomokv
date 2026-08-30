#!/usr/bin/env python3
"""Validate TomoKV reply shapes against Redis 7.4's command JSON schemas.

Usage: python3 tests/replyschema.py HOST PORT [REDIS_ROOT]

This is deliberately a raw RESP client: decoding maps, sets, doubles, big numbers, pushes, and
verbatim strings to ordinary Python values would erase exactly the distinctions this test is
meant to exercise.  The validator implements only the vocabulary present in Redis 7.4's
src/commands/*.json and has no third-party dependencies.
"""

import glob
import hashlib
import json
import os
import re
import socket
import sys
import time
from dataclasses import dataclass, field


HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 6379
REDIS_ROOT = (sys.argv[3] if len(sys.argv) > 3 else
              os.environ.get("REDIS74_ROOT", "/tmp/claude-1000/redis74"))
SCHEMA_GLOB = os.path.join(REDIS_ROOT, "src", "commands", "*.json")
PREFIX = "replyschema:%d" % os.getpid()


@dataclass
class Reply:
    kind: str
    value: object = None

    def shape(self, depth=0):
        if self.kind in ("null",):
            return "null"
        if self.kind in ("integer", "double", "boolean"):
            return "%s(%s)" % (self.kind, self.value)
        if self.kind in ("simple", "bulk", "verbatim", "bignum", "error", "blob-error"):
            data = self.value
            if isinstance(data, bytes):
                data = data[:48]
            return "%s(%r)" % (self.kind, data)
        if self.kind in ("array", "set", "push"):
            if depth >= 2:
                return "%s[%d]" % (self.kind, len(self.value))
            children = ", ".join(x.shape(depth + 1) for x in self.value[:4])
            if len(self.value) > 4:
                children += ", ..."
            return "%s[%d](%s)" % (self.kind, len(self.value), children)
        if self.kind == "map":
            if depth >= 2:
                return "map{%d}" % len(self.value)
            children = ", ".join("%s:%s" % (k.shape(depth + 1), v.shape(depth + 1))
                                 for k, v in self.value[:3])
            if len(self.value) > 3:
                children += ", ..."
            return "map{%d}(%s)" % (len(self.value), children)
        return "%s(%r)" % (self.kind, self.value)


def frame(*arguments):
    values = [x if isinstance(x, bytes) else str(x).encode() for x in arguments]
    return (b"*%d\r\n" % len(values) +
            b"".join(b"$%d\r\n" % len(x) + x + b"\r\n" for x in values))


class Connection:
    def __init__(self, protocol=2):
        self.protocol = protocol
        self.socket = socket.create_connection((HOST, PORT), timeout=20)
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.socket.makefile("rb")
        if protocol == 3:
            hello = self.command("HELLO", "3")
            if hello.kind != "map":
                raise AssertionError("HELLO 3 returned %s" % hello.shape())

    def close(self):
        try:
            self.file.close()
        finally:
            self.socket.close()

    def command(self, *arguments):
        self.socket.sendall(frame(*arguments))
        return self.read()

    def read(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed connection")
        if not line.endswith(b"\r\n"):
            raise ValueError("truncated RESP header %r" % line)
        marker, payload = line[:1], line[1:-2]
        if marker == b"+":
            return Reply("simple", payload)
        if marker == b"-":
            return Reply("error", payload)
        if marker == b":":
            return Reply("integer", int(payload))
        if marker == b",":
            return Reply("double", float(payload))
        if marker == b"#":
            return Reply("boolean", payload == b"t")
        if marker == b"(":
            return Reply("bignum", payload)
        if marker == b"_":
            return Reply("null")
        if marker in (b"$", b"=", b"!"):
            size = int(payload)
            if size == -1:
                return Reply("null")
            body = self.file.read(size)
            if len(body) != size or self.file.read(2) != b"\r\n":
                raise ValueError("truncated RESP body")
            kind = {b"$": "bulk", b"=": "verbatim", b"!": "blob-error"}[marker]
            if kind == "verbatim" and len(body) >= 4 and body[3:4] == b":":
                body = body[4:]
            return Reply(kind, body)
        if marker in (b"*", b"~", b">"):
            count = int(payload)
            if count == -1:
                return Reply("null")
            kind = {b"*": "array", b"~": "set", b">": "push"}[marker]
            return Reply(kind, [self.read() for _ in range(count)])
        if marker in (b"%", b"|"):
            pairs = [(self.read(), self.read()) for _ in range(int(payload))]
            if marker == b"|":
                # Attributes annotate, rather than replace, the following reply.
                return self.read()
            return Reply("map", pairs)
        raise ValueError("unsupported RESP marker %r" % marker)


SUPPORTED_SCHEMA_KEYS = {
    "$ref", "additionalItems", "additionalProperties", "anyOf", "const", "description",
    "items", "maxItems", "minItems", "minimum", "oneOf", "pattern", "patternProperties",
    "properties", "type", "uniqueItems",
}


def load_schemas():
    paths = sorted(glob.glob(SCHEMA_GLOB))
    if not paths:
        raise SystemExit("replyschema: no schema files matched %s" % SCHEMA_GLOB)
    schemas = {}
    top_names = set()
    containers = {}
    unknown = set()
    records = 0
    for path in paths:
        with open(path, "r", encoding="utf-8") as source:
            document = json.load(source)
        for name, metadata in document.items():
            records += 1
            container = metadata.get("container")
            endpoint = (container + "|" + name if container else name).lower()
            if not container:
                top_names.add(name.lower())
            else:
                containers[endpoint] = container.lower()
            if "reply_schema" in metadata:
                schemas[endpoint] = metadata["reply_schema"]
                for obj in walk_schemas(metadata["reply_schema"]):
                    unknown.update(set(obj) - SUPPORTED_SCHEMA_KEYS)
    if len(paths) != 401 or records != 401:
        raise SystemExit("replyschema: expected 401 Redis command records, got %d files/%d records" %
                         (len(paths), records))
    if unknown:
        raise SystemExit("replyschema: unsupported schema keywords: %s" %
                         ", ".join(sorted(unknown)))

    # Redis 7.4.2 live-oracle overrides.  These three shipped schemas disagree with the replies
    # from the matching /tmp/claude-1000/redis74 build (verified in both RESP2 and RESP3):
    # WAITAOF's replica count is an integer, and GEOHASH uses null for a missing requested member.
    schemas["waitaof"]["items"][1]["type"] = "integer"
    geohash_item = schemas["geohash"]["items"]
    schemas["geohash"]["items"] = {"oneOf": [geohash_item, {"type": "null"}]}
    return schemas, top_names, containers


def walk_schemas(schema):
    """Yield schema objects without mistaking property names for schema keywords."""
    yield schema
    for keyword in ("oneOf", "anyOf"):
        for child in schema.get(keyword, []):
            yield from walk_schemas(child)
    items = schema.get("items")
    if isinstance(items, dict):
        yield from walk_schemas(items)
    elif isinstance(items, list):
        for child in items:
            yield from walk_schemas(child)
    additional_items = schema.get("additionalItems")
    if isinstance(additional_items, dict):
        yield from walk_schemas(additional_items)
    additional_properties = schema.get("additionalProperties")
    if isinstance(additional_properties, dict):
        yield from walk_schemas(additional_properties)
    for keyword in ("properties", "patternProperties"):
        for child in schema.get(keyword, {}).values():
            yield from walk_schemas(child)


def scalar(reply):
    if reply.kind in ("simple", "bulk", "verbatim", "bignum"):
        return reply.value
    if reply.kind in ("integer", "double", "boolean"):
        return reply.value
    if reply.kind == "null":
        return None
    return object()


def as_text(value):
    if isinstance(value, bytes):
        return value.decode("latin-1")
    return str(value)


def schema_types(schema):
    if "type" in schema:
        return {schema["type"]}
    out = set()
    for option in schema.get("oneOf", schema.get("anyOf", [])):
        out.update(schema_types(option))
    return out


def fixed_tuple_size(schema):
    if not isinstance(schema, dict) or schema_types(schema) != {"array"}:
        return None
    items = schema.get("items")
    if isinstance(items, list):
        low = schema.get("minItems", len(items))
        high = schema.get("maxItems", len(items))
        if low == high == len(items):
            return len(items)
    return None


def array_children(reply, schema, protocol):
    if reply.kind not in ("array", "set", "push"):
        return None
    children = reply.value
    # RESP2 flattens an array of fixed-size tuples (sorted-set WITHSCORES and HRANDFIELD
    # WITHVALUES are the common cases).  This is schema-driven rather than command-specific.
    if protocol == 2 and isinstance(schema.get("items"), dict):
        width = fixed_tuple_size(schema["items"])
        if width and children and all(x.kind not in ("array", "set", "push") for x in children):
            if len(children) % width == 0:
                children = [Reply("array", children[i:i + width])
                            for i in range(0, len(children), width)]
    return children


def object_pairs(reply, protocol):
    if reply.kind == "map":
        return reply.value
    if protocol != 2 or reply.kind != "array":
        return None
    children = reply.value
    # XREAD[GROUP] is the RESP2 exception: maps are arrays of 2-tuples rather than one flat
    # alternating array.  Both projections are standard and unambiguous on the wire.
    if children and all(x.kind == "array" and len(x.value) == 2 for x in children):
        return [(x.value[0], x.value[1]) for x in children]
    if len(children) % 2:
        return None
    return list(zip(children[0::2], children[1::2]))


def validate(reply, schema, protocol, root=None, path="$"):
    root = schema if root is None else root
    if "$ref" in schema:
        if schema["$ref"] != "#":
            return ["%s unsupported ref %r" % (path, schema["$ref"])]
        return validate(reply, root, protocol, root, path)

    union_key = "oneOf" if "oneOf" in schema else "anyOf" if "anyOf" in schema else None
    if union_key:
        results = [validate(reply, option, protocol, root, path)
                   for option in schema[union_key]]
        matched = [i for i, errors in enumerate(results) if not errors]
        needed = len(matched) == 1 if union_key == "oneOf" else bool(matched)
        if not needed:
            detail = "; ".join("arm %d: %s" % (i, errors[0] if errors else "matched")
                               for i, errors in enumerate(results))
            return ["%s %s matched arms %s (%s)" % (path, union_key, matched, detail)]
        return []

    errors = []
    value = scalar(reply)
    if "const" in schema:
        wanted = schema["const"]
        actual = as_text(value) if isinstance(wanted, str) and value is not None else value
        if actual != wanted:
            errors.append("%s const %r, got %r" % (path, wanted, actual))
            return errors

    expected = schema.get("type")
    if expected == "null":
        if reply.kind != "null":
            errors.append("%s expected null, got %s" % (path, reply.kind))
    elif expected == "string":
        if reply.kind not in ("simple", "bulk", "verbatim", "bignum"):
            errors.append("%s expected string, got %s" % (path, reply.kind))
        elif "pattern" in schema and re.search(schema["pattern"], as_text(value)) is None:
            errors.append("%s string %r misses /%s/" % (path, value, schema["pattern"]))
    elif expected == "integer":
        if reply.kind != "integer":
            errors.append("%s expected integer, got %s" % (path, reply.kind))
        elif "minimum" in schema and value < schema["minimum"]:
            errors.append("%s integer %d below minimum %s" %
                          (path, value, schema["minimum"]))
    elif expected == "number":
        numeric = None
        if protocol == 3:
            # Every Redis 7.4 number-typed command schema denotes a RESP3 double.  Requiring the
            # marker here is what catches an integer/bulk-string reply that JSON decoding hides.
            if reply.kind != "double":
                errors.append("%s expected RESP3 double, got %s" % (path, reply.kind))
            else:
                numeric = value
        elif reply.kind not in ("bulk", "simple"):
            errors.append("%s expected RESP2 bulk double, got %s" % (path, reply.kind))
        else:
            try:
                numeric = float(as_text(value))
            except ValueError:
                errors.append("%s invalid RESP2 double %r" % (path, value))
        if numeric is not None and "minimum" in schema and numeric < schema["minimum"]:
            errors.append("%s number %s below minimum %s" %
                          (path, numeric, schema["minimum"]))
    elif expected == "array":
        children = array_children(reply, schema, protocol)
        if children is None:
            errors.append("%s expected array, got %s" % (path, reply.kind))
        else:
            if len(children) < schema.get("minItems", 0):
                errors.append("%s has %d items, minimum %d" %
                              (path, len(children), schema["minItems"]))
            if "maxItems" in schema and len(children) > schema["maxItems"]:
                errors.append("%s has %d items, maximum %d" %
                              (path, len(children), schema["maxItems"]))
            items = schema.get("items")
            if isinstance(items, dict):
                for i, child in enumerate(children):
                    errors.extend(validate(child, items, protocol, root,
                                           "%s[%d]" % (path, i)))
            elif isinstance(items, list):
                for i, child in enumerate(children[:len(items)]):
                    errors.extend(validate(child, items[i], protocol, root,
                                           "%s[%d]" % (path, i)))
                if len(children) > len(items):
                    extra = schema.get("additionalItems", {})
                    if extra is False:
                        errors.append("%s has forbidden additional items" % path)
                    elif isinstance(extra, dict):
                        for i, child in enumerate(children[len(items):], len(items)):
                            errors.extend(validate(child, extra, protocol, root,
                                                   "%s[%d]" % (path, i)))
            if schema.get("uniqueItems"):
                rendered = [x.shape() for x in children]
                if len(rendered) != len(set(rendered)):
                    errors.append("%s items are not unique" % path)
    elif expected == "object":
        pairs = object_pairs(reply, protocol)
        if pairs is None:
            errors.append("%s expected %s map, got %s" %
                          (path, "RESP3" if protocol == 3 else "RESP2-projected", reply.kind))
        else:
            properties = schema.get("properties", {})
            patterns = schema.get("patternProperties", {})
            additional = schema.get("additionalProperties", True)
            seen = set()
            for key_reply, child in pairs:
                key_value = scalar(key_reply)
                if not isinstance(key_value, bytes):
                    errors.append("%s map key is %s, not string" % (path, key_reply.kind))
                    continue
                key = as_text(key_value)
                if key in seen:
                    errors.append("%s duplicate map key %r" % (path, key))
                seen.add(key)
                candidates = []
                if key in properties:
                    candidates.append(properties[key])
                candidates.extend(rule for pattern, rule in patterns.items()
                                  if re.search(pattern, key))
                if not candidates:
                    if additional is False:
                        errors.append("%s unexpected property %r" % (path, key))
                    elif isinstance(additional, dict):
                        candidates.append(additional)
                for candidate in candidates:
                    errors.extend(validate(child, candidate, protocol, root,
                                           "%s.%s" % (path, key)))
    elif expected is not None:
        errors.append("%s unsupported type %r" % (path, expected))
    return errors


@dataclass
class Case:
    endpoint: str
    argv: tuple
    setup: tuple = field(default_factory=tuple)
    arm: int = None
    note: str = ""
    special: object = None


CASES = []


def add(endpoint, *argv, setup=(), arm=None, note="", special=None):
    CASES.append(Case(endpoint.lower(), tuple(argv), tuple(setup), arm, note, special))


def subst(value, prefix):
    if isinstance(value, str):
        return value.replace("{p}", prefix)
    return value


def argv_for(values, prefix):
    return tuple(subst(x, prefix) for x in values)


def arm_schema(schema, arm):
    if arm is None:
        return schema
    options = schema.get("oneOf", schema.get("anyOf"))
    if options is None or arm >= len(options):
        raise AssertionError("invalid schema arm %r" % arm)
    return options[arm]


def arm_label(schema, arm):
    selected = arm_schema(schema, arm)
    if arm is None:
        options = schema.get("oneOf", schema.get("anyOf"))
        if options:
            kinds = [option.get("description") or
                     ("const %r" % option["const"] if "const" in option else
                      option.get("type", "unconstrained")) for option in options]
            return ("documented arm: " + " | ".join(kinds))[:100]
    if "description" in selected and selected["description"]:
        return selected["description"].replace("\n", " ")[:100]
    if "const" in selected:
        return "const %r" % selected["const"]
    return selected.get("type", "unconstrained")


# --------------------------------------------------------------------------------------------
# Canonical invocations.  Fixtures are repeated independently on the RESP2 and RESP3 connection
# so a mutating command cannot accidentally select a different arm in the second protocol.

EMPTY = (("DEL", "{p}:k"),)
STRING = (("SET", "{p}:k", "value"),)
HASH = (("DEL", "{p}:h"), ("HSET", "{p}:h", "a", "1", "b", "2"))
LIST = (("DEL", "{p}:l"), ("RPUSH", "{p}:l", "a", "b", "c"))
SETFIX = (("DEL", "{p}:s"), ("SADD", "{p}:s", "a", "b", "c"))
ZSET = (("DEL", "{p}:z"), ("ZADD", "{p}:z", "1", "a", "2", "b", "3", "c"))
STREAM = (("DEL", "{p}:x"), ("XADD", "{p}:x", "1-0", "f", "v"),
          ("XADD", "{p}:x", "2-0", "g", "w"))


def restore_special(connection, prefix):
    connection.command("DEL", prefix + ":restore-src", prefix + ":restore-dst")
    connection.command("SET", prefix + ":restore-src", "payload")
    payload = connection.command("DUMP", prefix + ":restore-src")
    if payload.kind != "bulk":
        return ("RESTORE", prefix + ":restore-dst", "0", b""), payload
    argv = ("RESTORE", prefix + ":restore-dst", "0", payload.value)
    return argv, connection.command(*argv)


def restore_asking_special(connection, prefix):
    connection.command("DEL", prefix + ":ra-src", prefix + ":ra-dst")
    connection.command("SET", prefix + ":ra-src", "payload")
    payload = connection.command("DUMP", prefix + ":ra-src")
    if payload.kind != "bulk":
        return ("RESTORE-ASKING", prefix + ":ra-dst", "0", b""), payload
    argv = ("RESTORE-ASKING", prefix + ":ra-dst", "0", payload.value)
    return argv, connection.command(*argv)


def aborted_exec_special(connection, prefix):
    connection.command("SET", prefix + ":watched", "old")
    connection.command("WATCH", prefix + ":watched")
    other = Connection(connection.protocol)
    try:
        other.command("SET", prefix + ":watched", "new")
    finally:
        other.close()
    connection.command("MULTI")
    connection.command("GET", prefix + ":watched")
    return ("EXEC",), connection.command("EXEC")


def function_restore_special(connection, prefix):
    code = ("#!lua name=replyschema_restore\n"
            "redis.register_function('replyschema_restore_fn', function() return 9 end)\n")
    connection.command("FUNCTION", "FLUSH")
    connection.command("FUNCTION", "LOAD", code)
    payload = connection.command("FUNCTION", "DUMP")
    connection.command("FUNCTION", "FLUSH")
    if payload.kind != "bulk":
        return ("FUNCTION", "RESTORE", b""), payload
    argv = ("FUNCTION", "RESTORE", payload.value)
    return argv, connection.command(*argv)


def bgsave_special(connection, prefix):
    argv = ("BGSAVE", "SCHEDULE")
    reply = connection.command(*argv)
    # The RESP2 and RESP3 captures necessarily run in sequence.  A background save started by the
    # first can still be active at the second; wait for the same canonical success arm instead of
    # treating that transient administrative state as the reply under test.
    deadline = time.monotonic() + 5
    while reply.kind == "error" and b"already in progress" in reply.value and time.monotonic() < deadline:
        time.sleep(0.01)
        reply = connection.command(*argv)
    return argv, reply


def bgsave_scheduled_special(connection, prefix):
    # First reach an idle persistence state, then make the second command select the documented
    # "scheduled" arm while a save is active.
    bgsave_special(connection, prefix)
    argv = ("BGSAVE", "SCHEDULE")
    return argv, connection.command(*argv)


def acl_log_special(connection, prefix):
    username = prefix + ":loguser"
    connection.command("ACL", "LOG", "RESET")
    connection.command("ACL", "SETUSER", username, "reset", "on", ">pw", "+get", "~allowed:*")
    denied = Connection(connection.protocol)
    try:
        denied.command("AUTH", username, "pw")
        denied.command("GET", "denied:key")
    finally:
        denied.close()
    argv = ("ACL", "LOG", "1")
    return argv, connection.command(*argv)


def client_getredir_special(connection, prefix):
    redirect = Connection(connection.protocol)
    try:
        client_id = redirect.command("CLIENT", "ID")
        if client_id.kind != "integer":
            return ("CLIENT", "GETREDIR"), client_id
        connection.command("CLIENT", "TRACKING", "ON", "REDIRECT", str(client_id.value))
        argv = ("CLIENT", "GETREDIR")
        return argv, connection.command(*argv)
    finally:
        redirect.close()


def client_kill_legacy_special(connection, prefix):
    victim = Connection(connection.protocol)
    try:
        info = victim.command("CLIENT", "INFO")
        if info.kind not in ("bulk", "verbatim"):
            return ("CLIENT", "KILL", "invalid"), info
        match = re.search(br"(?:^| )addr=([^ ]+)", info.value)
        if not match:
            return ("CLIENT", "KILL", "invalid"), info
        argv = ("CLIENT", "KILL", match.group(1))
        return argv, connection.command(*argv)
    finally:
        victim.close()


def client_unblock_special(connection, prefix):
    blocked = Connection(connection.protocol)
    try:
        client_id = blocked.command("CLIENT", "ID")
        if client_id.kind != "integer":
            return ("CLIENT", "UNBLOCK", "0"), client_id
        blocked.socket.sendall(frame("BLPOP", prefix + ":never", "0"))
        time.sleep(0.01)
        argv = ("CLIENT", "UNBLOCK", str(client_id.value))
        return argv, connection.command(*argv)
    finally:
        blocked.close()


# Generic, connection, scripting, and server commands.
add("append", "APPEND", "{p}:k", "abc", setup=EMPTY)
add("auth", "AUTH", "{p}:user", "pw",
    setup=(("ACL", "SETUSER", "{p}:user", "reset", "on", ">pw", "+@all", "~*", "&*"),))
add("bgsave", arm=0, special=bgsave_special)
add("bgsave", arm=1, special=bgsave_scheduled_special)
add("copy", "COPY", "{p}:src", "{p}:dst", setup=(("DEL", "{p}:src", "{p}:dst"),), arm=1)
add("copy", "COPY", "{p}:src", "{p}:dst",
    setup=(("DEL", "{p}:src", "{p}:dst"), ("SET", "{p}:src", "v")), arm=0)
add("dbsize", "DBSIZE")
add("decr", "DECR", "{p}:n", setup=(("SET", "{p}:n", "3"),))
add("decrby", "DECRBY", "{p}:n", "2", setup=(("SET", "{p}:n", "3"),))
add("del", "DEL", "{p}:a", "{p}:b", setup=(("SET", "{p}:a", "v"),))
add("discard", "DISCARD", setup=(("MULTI",),))
add("dump", "DUMP", "{p}:missing", setup=(("DEL", "{p}:missing"),), arm=1)
add("dump", "DUMP", "{p}:k", setup=STRING, arm=0)
add("echo", "ECHO", "hello")
add("eval", "EVAL", "return {KEYS[1],ARGV[1],7}", "1", "{p}:k", "arg")
LUA_BODY = "return {KEYS[1],ARGV[1],7}"
LUA_SHA = hashlib.sha1(LUA_BODY.encode()).hexdigest()
add("evalsha", "EVALSHA", LUA_SHA, "1", "{p}:k", "arg",
    setup=(("SCRIPT", "LOAD", LUA_BODY),))
add("eval_ro", "EVAL_RO", "return redis.call('GET',KEYS[1])", "1", "{p}:k", setup=STRING)
add("evalsha_ro", "EVALSHA_RO", LUA_SHA, "1", "{p}:k", "arg",
    setup=(("SCRIPT", "LOAD", LUA_BODY),))
add("exec", "EXEC", setup=(("MULTI",), ("GET", "{p}:missing")), arm=0)
add("exec", "EXEC", arm=1, special=aborted_exec_special)
add("exists", "EXISTS", "{p}:k", "{p}:missing", setup=STRING)
for name, command, unit in (("expire", "EXPIRE", "10"), ("pexpire", "PEXPIRE", "10000")):
    add(name, command, "{p}:missing", unit, setup=(("DEL", "{p}:missing"),), arm=0)
    add(name, command, "{p}:k", unit, setup=STRING, arm=1)
for name, command, when in (("expireat", "EXPIREAT", "4102444800"),
                            ("pexpireat", "PEXPIREAT", "4102444800000")):
    add(name, command, "{p}:k", when, setup=STRING, arm=0)
    add(name, command, "{p}:missing", when, setup=(("DEL", "{p}:missing"),), arm=1)
for name, command, expiry in (("expiretime", "EXPIRETIME", "4102444800"),
                              ("pexpiretime", "PEXPIRETIME", "4102444800000")):
    setter = "EXPIREAT" if name == "expiretime" else "PEXPIREAT"
    add(name, command, "{p}:k", setup=(("SET", "{p}:k", "v"),
                                       (setter, "{p}:k", expiry)), arm=0)
    add(name, command, "{p}:persistent", setup=(("SET", "{p}:persistent", "v"),), arm=1)
    add(name, command, "{p}:missing", setup=(("DEL", "{p}:missing"),), arm=2)
add("fcall", "FCALL", "replyschema_fn", "0",
    setup=(("FUNCTION", "LOAD", "REPLACE", "#!lua name=replyschema\n"
            "redis.register_function('replyschema_fn', function() return 7 end)\n"
            "redis.register_function{function_name='replyschema_ro', callback=function() return 8 end, flags={'no-writes'}}\n"),))
add("fcall_ro", "FCALL_RO", "replyschema_ro", "0",
    setup=(("FUNCTION", "LOAD", "REPLACE", "#!lua name=replyschema\n"
            "redis.register_function('replyschema_fn', function() return 7 end)\n"
            "redis.register_function{function_name='replyschema_ro', callback=function() return 8 end, flags={'no-writes'}}\n"),))
add("flushall", "FLUSHALL")
add("flushdb", "FLUSHDB")
add("hello", "HELLO")
add("incr", "INCR", "{p}:n", setup=(("SET", "{p}:n", "3"),))
add("incrby", "INCRBY", "{p}:n", "2", setup=(("SET", "{p}:n", "3"),))
add("incrbyfloat", "INCRBYFLOAT", "{p}:n", "0.5", setup=(("SET", "{p}:n", "1"),))
add("info", "INFO", "SERVER")
add("keys", "KEYS", "{p}:*", setup=STRING)
add("lastsave", "LASTSAVE")
add("lolwut", "LOLWUT", "VERSION", "5")
add("mget", "MGET", "{p}:a", "{p}:missing", setup=(("SET", "{p}:a", "v"),))
add("mset", "MSET", "{p}:a", "1", "{p}:b", "2")
add("msetnx", "MSETNX", "{p}:a", "1", "{p}:b", "2",
    setup=(("DEL", "{p}:a", "{p}:b"),), arm=1)
add("msetnx", "MSETNX", "{p}:a", "1", "{p}:b", "2",
    setup=(("SET", "{p}:a", "old"),), arm=0)
add("multi", "MULTI")
for name, command in (("persist", "PERSIST"),):
    add(name, command, "{p}:missing", setup=(("DEL", "{p}:missing"),), arm=0)
    add(name, command, "{p}:k", setup=(("SET", "{p}:k", "v"),
                                       ("EXPIRE", "{p}:k", "60")), arm=1)
add("pfadd", "PFADD", "{p}:pf", "a", "b", setup=(("DEL", "{p}:pf"),), arm=0)
add("pfadd", "PFADD", "{p}:pf", "a", setup=(("DEL", "{p}:pf"),
                                                ("PFADD", "{p}:pf", "a")), arm=1)
add("pfcount", "PFCOUNT", "{p}:pf", setup=(("DEL", "{p}:pf"),
                                              ("PFADD", "{p}:pf", "a", "b")))
add("pfmerge", "PFMERGE", "{p}:out", "{p}:pf", setup=(("DEL", "{p}:out", "{p}:pf"),
                                                         ("PFADD", "{p}:pf", "a")))
add("pfselftest", "PFSELFTEST")
add("ping", "PING", arm=0)
add("ping", "PING", "hello", arm=1)
add("psetex", "PSETEX", "{p}:k", "10000", "v")
add("publish", "PUBLISH", "{p}:channel", "message")
add("quit", "QUIT")
add("randomkey", "RANDOMKEY", setup=(("FLUSHDB",),), arm=0)
add("randomkey", "RANDOMKEY", setup=(("FLUSHDB",), ("SET", "{p}:k", "v")), arm=1)
add("rename", "RENAME", "{p}:src", "{p}:dst", setup=(("DEL", "{p}:src", "{p}:dst"),
                                                       ("SET", "{p}:src", "v")))
add("renamenx", "RENAMENX", "{p}:src", "{p}:dst",
    setup=(("DEL", "{p}:src", "{p}:dst"), ("SET", "{p}:src", "v")), arm=0)
add("renamenx", "RENAMENX", "{p}:src", "{p}:dst",
    setup=(("SET", "{p}:src", "v"), ("SET", "{p}:dst", "x")), arm=1)
add("replicaof", "REPLICAOF", "NO", "ONE")
add("reset", "RESET")
add("restore", special=restore_special)
add("restore-asking", special=restore_asking_special)
add("role", "ROLE")
add("save", "SAVE")
add("select", "SELECT", "0")
add("set", "SET", "{p}:k", "v", "NX", setup=STRING, arm=0)
add("set", "SET", "{p}:k", "v", setup=EMPTY, arm=1)
add("set", "SET", "{p}:k", "v", "GET", setup=EMPTY, arm=2)
add("set", "SET", "{p}:k", "new", "GET", setup=STRING, arm=3)
add("setex", "SETEX", "{p}:k", "60", "v")
add("setnx", "SETNX", "{p}:k", "v", setup=EMPTY, arm=1)
add("setnx", "SETNX", "{p}:k", "new", setup=STRING, arm=0)
add("slaveof", "SLAVEOF", "NO", "ONE")
add("spublish", "SPUBLISH", "{p}:channel", "message")
add("time", "TIME")
add("touch", "TOUCH", "{p}:k", "{p}:missing", setup=STRING)
for name, command, unit in (("ttl", "TTL", "60"), ("pttl", "PTTL", "60000")):
    setter = "EXPIRE" if name == "ttl" else "PEXPIRE"
    add(name, command, "{p}:k", setup=(("SET", "{p}:k", "v"),
                                       (setter, "{p}:k", unit)), arm=0)
    add(name, command, "{p}:persistent", setup=(("SET", "{p}:persistent", "v"),), arm=1)
    add(name, command, "{p}:missing", setup=(("DEL", "{p}:missing"),), arm=2)
add("type", "TYPE", "{p}:missing", setup=(("DEL", "{p}:missing"),), arm=1)
add("type", "TYPE", "{p}:k", setup=STRING, arm=1)
add("unlink", "UNLINK", "{p}:k", setup=STRING)
add("unwatch", "UNWATCH")
add("wait", "WAIT", "0", "1")
add("waitaof", "WAITAOF", "0", "0", "1")
add("watch", "WATCH", "{p}:k")

# Success needs a cluster-enabled server, an active rewrite/failover/shutdown, or a configured
# persistence file.  Their error replies are deliberately outside reply_schema.
UNREACHABLE = {"asking", "bgrewriteaof", "failover", "readonly", "readwrite", "shutdown"}


# Strings and bitmaps.
add("bitcount", "BITCOUNT", "{p}:bits", setup=(("SET", "{p}:bits", b"\xff\x00"),))
add("bitfield", "BITFIELD", "{p}:bits", "SET", "u8", "0", "7", "GET", "u8", "0",
    setup=(("DEL", "{p}:bits"),))
add("bitfield_ro", "BITFIELD_RO", "{p}:bits", "GET", "u8", "0",
    setup=(("SET", "{p}:bits", b"\x07"),))
add("bitop", "BITOP", "XOR", "{p}:out", "{p}:a", "{p}:b",
    setup=(("SET", "{p}:a", b"\xff"), ("SET", "{p}:b", b"\x0f")))
add("bitpos", "BITPOS", "{p}:bits", "1", setup=(("SET", "{p}:bits", b"\x00\x01"),), arm=0)
add("bitpos", "BITPOS", "{p}:bits", "1", setup=(("SET", "{p}:bits", b"\x00"),), arm=1)
add("get", "GET", "{p}:missing", setup=(("DEL", "{p}:missing"),), arm=1)
add("get", "GET", "{p}:k", setup=STRING, arm=0)
add("getbit", "GETBIT", "{p}:bits", "0", setup=(("SET", "{p}:bits", b"\x80"),), arm=1)
add("getbit", "GETBIT", "{p}:missing", "0", setup=(("DEL", "{p}:missing"),), arm=0)
add("getdel", "GETDEL", "{p}:missing", setup=(("DEL", "{p}:missing"),), arm=1)
add("getdel", "GETDEL", "{p}:k", setup=STRING, arm=0)
add("getex", "GETEX", "{p}:missing", setup=(("DEL", "{p}:missing"),), arm=1)
add("getex", "GETEX", "{p}:k", "EX", "60", setup=STRING, arm=0)
add("getrange", "GETRANGE", "{p}:k", "1", "3", setup=STRING)
add("getset", "GETSET", "{p}:missing", "new", setup=(("DEL", "{p}:missing"),), arm=1)
add("getset", "GETSET", "{p}:k", "new", setup=STRING, arm=0)
add("setbit", "SETBIT", "{p}:bits", "0", "1", setup=(("DEL", "{p}:bits"),), arm=0)
add("setbit", "SETBIT", "{p}:bits", "0", "0", setup=(("SETBIT", "{p}:bits", "0", "1"),), arm=1)
add("setrange", "SETRANGE", "{p}:k", "2", "xy", setup=STRING)
add("strlen", "STRLEN", "{p}:k", setup=STRING)
add("substr", "SUBSTR", "{p}:k", "1", "3", setup=STRING)


# Hashes, including Redis 7.4 hash-field expiry replies.
add("hdel", "HDEL", "{p}:h", "a", "missing", setup=HASH)
add("hexists", "HEXISTS", "{p}:h", "a", setup=HASH, arm=1)
add("hexists", "HEXISTS", "{p}:h", "missing", setup=HASH, arm=0)
for name, command, amount in (("hexpire", "HEXPIRE", "60"),
                              ("hpexpire", "HPEXPIRE", "60000"),
                              ("hexpireat", "HEXPIREAT", "4102444800"),
                              ("hpexpireat", "HPEXPIREAT", "4102444800000")):
    add(name, command, "{p}:h", amount, "FIELDS", "2", "a", "missing", setup=HASH)
for name, command, setter, amount in (
        ("hexpiretime", "HEXPIRETIME", "HEXPIRE", "60"),
        ("hpexpiretime", "HPEXPIRETIME", "HPEXPIRE", "60000"),
        ("httl", "HTTL", "HEXPIRE", "60"),
        ("hpttl", "HPTTL", "HPEXPIRE", "60000")):
    add(name, command, "{p}:h", "FIELDS", "3", "a", "b", "missing",
        setup=HASH + ((setter, "{p}:h", amount, "FIELDS", "1", "a"),))
add("hpersist", "HPERSIST", "{p}:h", "FIELDS", "3", "a", "b", "missing",
    setup=HASH + (("HEXPIRE", "{p}:h", "60", "FIELDS", "1", "a"),))
add("hget", "HGET", "{p}:h", "missing", setup=HASH, arm=1)
add("hget", "HGET", "{p}:h", "a", setup=HASH, arm=0)
add("hgetall", "HGETALL", "{p}:h", setup=HASH)
add("hincrby", "HINCRBY", "{p}:h", "n", "2", setup=(("HSET", "{p}:h", "n", "3"),))
add("hincrbyfloat", "HINCRBYFLOAT", "{p}:h", "n", "0.5",
    setup=(("HSET", "{p}:h", "n", "1"),))
add("hkeys", "HKEYS", "{p}:h", setup=HASH)
add("hlen", "HLEN", "{p}:h", setup=HASH)
add("hmget", "HMGET", "{p}:h", "a", "missing", setup=HASH)
add("hmset", "HMSET", "{p}:h", "a", "1", "b", "2")
add("hrandfield", "HRANDFIELD", "{p}:missing", setup=(("DEL", "{p}:missing"),), arm=0)
add("hrandfield", "HRANDFIELD", "{p}:h", setup=HASH, arm=1)
add("hrandfield", "HRANDFIELD", "{p}:h", "2", setup=HASH, arm=2)
add("hrandfield", "HRANDFIELD", "{p}:h", "2", "WITHVALUES", setup=HASH, arm=3)
add("hscan", "HSCAN", "{p}:h", "0", setup=HASH)
add("hset", "HSET", "{p}:h", "a", "1", "b", "2", setup=(("DEL", "{p}:h"),))
add("hsetnx", "HSETNX", "{p}:h", "new", "v", setup=HASH, arm=1)
add("hsetnx", "HSETNX", "{p}:h", "a", "v", setup=HASH, arm=0)
add("hstrlen", "HSTRLEN", "{p}:h", "a", setup=HASH)
add("hvals", "HVALS", "{p}:h", setup=HASH)


# Lists and blocking list commands.  Millisecond-scale timeouts make the miss arms deterministic
# without leaving a blocked client behind.
add("blmove", "BLMOVE", "{p}:missing", "{p}:dst", "LEFT", "RIGHT", "0.001",
    setup=(("DEL", "{p}:missing", "{p}:dst"),), arm=1)
add("blmove", "BLMOVE", "{p}:l", "{p}:dst", "LEFT", "RIGHT", "0.001",
    setup=LIST + (("DEL", "{p}:dst"),), arm=0)
add("blmpop", "BLMPOP", "0.001", "1", "{p}:missing", "LEFT",
    setup=(("DEL", "{p}:missing"),), arm=0)
add("blmpop", "BLMPOP", "0.001", "1", "{p}:l", "LEFT", "COUNT", "2", setup=LIST, arm=1)
add("blpop", "BLPOP", "{p}:missing", "0.001", setup=(("DEL", "{p}:missing"),), arm=0)
add("blpop", "BLPOP", "{p}:l", "0.001", setup=LIST, arm=1)
add("brpop", "BRPOP", "{p}:missing", "0.001", setup=(("DEL", "{p}:missing"),), arm=0)
add("brpop", "BRPOP", "{p}:l", "0.001", setup=LIST, arm=1)
add("brpoplpush", "BRPOPLPUSH", "{p}:missing", "{p}:dst", "0.001",
    setup=(("DEL", "{p}:missing", "{p}:dst"),), arm=1)
add("brpoplpush", "BRPOPLPUSH", "{p}:l", "{p}:dst", "0.001",
    setup=LIST + (("DEL", "{p}:dst"),), arm=0)
add("lindex", "LINDEX", "{p}:l", "99", setup=LIST, arm=0)
add("lindex", "LINDEX", "{p}:l", "1", setup=LIST, arm=1)
add("linsert", "LINSERT", "{p}:l", "BEFORE", "b", "x", setup=LIST, arm=0)
add("linsert", "LINSERT", "{p}:missing", "BEFORE", "b", "x",
    setup=(("DEL", "{p}:missing"),), arm=1)
add("linsert", "LINSERT", "{p}:l", "BEFORE", "missing", "x", setup=LIST, arm=2)
add("llen", "LLEN", "{p}:l", setup=LIST)
add("lmove", "LMOVE", "{p}:l", "{p}:dst", "LEFT", "RIGHT",
    setup=LIST + (("DEL", "{p}:dst"),))
add("lmpop", "LMPOP", "1", "{p}:missing", "LEFT", setup=(("DEL", "{p}:missing"),), arm=0)
add("lmpop", "LMPOP", "1", "{p}:l", "LEFT", "COUNT", "2", setup=LIST, arm=1)
add("lpop", "LPOP", "{p}:missing", setup=(("DEL", "{p}:missing"),), arm=0)
add("lpop", "LPOP", "{p}:l", setup=LIST, arm=1)
add("lpop", "LPOP", "{p}:l", "2", setup=LIST, arm=2)
add("lpos", "LPOS", "{p}:l", "missing", setup=LIST, arm=0)
add("lpos", "LPOS", "{p}:l", "b", setup=LIST, arm=1)
add("lpos", "LPOS", "{p}:l", "b", "COUNT", "2", setup=LIST, arm=2)
add("lpush", "LPUSH", "{p}:l", "a", "b", setup=(("DEL", "{p}:l"),))
add("lpushx", "LPUSHX", "{p}:l", "x", setup=LIST)
add("lrange", "LRANGE", "{p}:l", "0", "-1", setup=LIST)
add("lrem", "LREM", "{p}:l", "0", "b", setup=LIST)
add("lset", "LSET", "{p}:l", "1", "x", setup=LIST)
add("ltrim", "LTRIM", "{p}:l", "0", "1", setup=LIST)
add("rpop", "RPOP", "{p}:missing", setup=(("DEL", "{p}:missing"),), arm=0)
add("rpop", "RPOP", "{p}:l", setup=LIST, arm=1)
add("rpop", "RPOP", "{p}:l", "2", setup=LIST, arm=2)
add("rpoplpush", "RPOPLPUSH", "{p}:missing", "{p}:dst",
    setup=(("DEL", "{p}:missing", "{p}:dst"),), arm=1)
add("rpoplpush", "RPOPLPUSH", "{p}:l", "{p}:dst", setup=LIST, arm=0)
add("rpush", "RPUSH", "{p}:l", "a", "b", setup=(("DEL", "{p}:l"),))
add("rpushx", "RPUSHX", "{p}:l", "x", setup=LIST)


# Sets.
add("sadd", "SADD", "{p}:s", "a", "b", setup=(("DEL", "{p}:s"),))
add("scard", "SCARD", "{p}:s", setup=SETFIX)
add("sdiff", "SDIFF", "{p}:s", "{p}:s2",
    setup=SETFIX + (("DEL", "{p}:s2"), ("SADD", "{p}:s2", "b", "d")))
add("sdiffstore", "SDIFFSTORE", "{p}:out", "{p}:s", "{p}:s2",
    setup=SETFIX + (("DEL", "{p}:s2", "{p}:out"), ("SADD", "{p}:s2", "b", "d")))
add("sinter", "SINTER", "{p}:s", "{p}:s2",
    setup=SETFIX + (("DEL", "{p}:s2"), ("SADD", "{p}:s2", "b", "c", "d")))
add("sintercard", "SINTERCARD", "2", "{p}:s", "{p}:s2",
    setup=SETFIX + (("DEL", "{p}:s2"), ("SADD", "{p}:s2", "b", "c", "d")))
add("sinterstore", "SINTERSTORE", "{p}:out", "{p}:s", "{p}:s2",
    setup=SETFIX + (("DEL", "{p}:s2", "{p}:out"), ("SADD", "{p}:s2", "b", "c")))
add("sismember", "SISMEMBER", "{p}:s", "missing", setup=SETFIX, arm=0)
add("sismember", "SISMEMBER", "{p}:s", "a", setup=SETFIX, arm=1)
add("smembers", "SMEMBERS", "{p}:s", setup=SETFIX)
add("smismember", "SMISMEMBER", "{p}:s", "a", "missing", setup=SETFIX)
add("smove", "SMOVE", "{p}:s", "{p}:s2", "missing",
    setup=SETFIX + (("DEL", "{p}:s2"),), arm=1)
add("smove", "SMOVE", "{p}:s", "{p}:s2", "a",
    setup=SETFIX + (("DEL", "{p}:s2"),), arm=0)
add("spop", "SPOP", "{p}:missing", setup=(("DEL", "{p}:missing"),), arm=0)
add("spop", "SPOP", "{p}:s", setup=SETFIX, arm=1)
add("spop", "SPOP", "{p}:s", "2", setup=SETFIX, arm=2)
add("srandmember", "SRANDMEMBER", "{p}:missing", setup=(("DEL", "{p}:missing"),), arm=0)
add("srandmember", "SRANDMEMBER", "{p}:s", setup=SETFIX, arm=1)
add("srandmember", "SRANDMEMBER", "{p}:s", "2", setup=SETFIX, arm=2)
add("srandmember", "SRANDMEMBER", "{p}:missing", "2",
    setup=(("DEL", "{p}:missing"),), arm=3)
add("srem", "SREM", "{p}:s", "a", "missing", setup=SETFIX)
add("sscan", "SSCAN", "{p}:s", "0", setup=SETFIX)
add("sunion", "SUNION", "{p}:s", "{p}:s2",
    setup=SETFIX + (("DEL", "{p}:s2"), ("SADD", "{p}:s2", "c", "d")))
add("sunionstore", "SUNIONSTORE", "{p}:out", "{p}:s", "{p}:s2",
    setup=SETFIX + (("DEL", "{p}:s2", "{p}:out"), ("SADD", "{p}:s2", "c", "d")))


# Sorted sets, including every cheap null/scalar/scored-pair arm.
add("bzmpop", "BZMPOP", "0.001", "1", "{p}:missing", "MIN",
    setup=(("DEL", "{p}:missing"),), arm=0)
add("bzmpop", "BZMPOP", "0.001", "1", "{p}:z", "MIN", "COUNT", "2", setup=ZSET, arm=1)
for name, command in (("bzpopmax", "BZPOPMAX"), ("bzpopmin", "BZPOPMIN")):
    add(name, command, "{p}:missing", "0.001", setup=(("DEL", "{p}:missing"),), arm=0)
    add(name, command, "{p}:z", "0.001", setup=ZSET, arm=1)
add("zadd", "ZADD", "{p}:z", "NX", "INCR", "1", "a", setup=ZSET, arm=0)
add("zadd", "ZADD", "{p}:z", "4", "d", setup=ZSET, arm=1)
add("zadd", "ZADD", "{p}:z", "CH", "4", "a", setup=ZSET, arm=2)
add("zadd", "ZADD", "{p}:z", "INCR", "0.5", "a", setup=ZSET, arm=3)
add("zcard", "ZCARD", "{p}:z", setup=ZSET)
add("zcount", "ZCOUNT", "{p}:z", "-inf", "+inf", setup=ZSET)
add("zdiff", "ZDIFF", "2", "{p}:z", "{p}:z2",
    setup=ZSET + (("DEL", "{p}:z2"), ("ZADD", "{p}:z2", "2", "b")), arm=0)
add("zdiff", "ZDIFF", "2", "{p}:z", "{p}:z2", "WITHSCORES",
    setup=ZSET + (("DEL", "{p}:z2"), ("ZADD", "{p}:z2", "2", "b")), arm=1)
add("zdiffstore", "ZDIFFSTORE", "{p}:out", "2", "{p}:z", "{p}:z2",
    setup=ZSET + (("DEL", "{p}:z2", "{p}:out"), ("ZADD", "{p}:z2", "2", "b")))
add("zincrby", "ZINCRBY", "{p}:z", "0.5", "a", setup=ZSET)
add("zinter", "ZINTER", "2", "{p}:z", "{p}:z2",
    setup=ZSET + (("DEL", "{p}:z2"), ("ZADD", "{p}:z2", "2", "b", "3", "c")), arm=0)
add("zinter", "ZINTER", "2", "{p}:z", "{p}:z2", "WITHSCORES",
    setup=ZSET + (("DEL", "{p}:z2"), ("ZADD", "{p}:z2", "2", "b", "3", "c")), arm=1)
add("zintercard", "ZINTERCARD", "2", "{p}:z", "{p}:z2",
    setup=ZSET + (("DEL", "{p}:z2"), ("ZADD", "{p}:z2", "2", "b")))
add("zinterstore", "ZINTERSTORE", "{p}:out", "2", "{p}:z", "{p}:z2",
    setup=ZSET + (("DEL", "{p}:z2", "{p}:out"), ("ZADD", "{p}:z2", "2", "b")))
add("zlexcount", "ZLEXCOUNT", "{p}:lex", "-", "+",
    setup=(("DEL", "{p}:lex"), ("ZADD", "{p}:lex", "0", "a", "0", "b")))
add("zmpop", "ZMPOP", "1", "{p}:missing", "MIN", setup=(("DEL", "{p}:missing"),), arm=0)
add("zmpop", "ZMPOP", "1", "{p}:z", "MIN", "COUNT", "2", setup=ZSET, arm=1)
add("zmscore", "ZMSCORE", "{p}:z", "a", "missing", setup=ZSET)
for name, command in (("zpopmax", "ZPOPMAX"), ("zpopmin", "ZPOPMIN")):
    add(name, command, "{p}:z", setup=ZSET, arm=0)
    add(name, command, "{p}:z", "2", setup=ZSET, arm=1)
add("zrandmember", "ZRANDMEMBER", "{p}:missing", setup=(("DEL", "{p}:missing"),), arm=0)
add("zrandmember", "ZRANDMEMBER", "{p}:z", setup=ZSET, arm=1)
add("zrandmember", "ZRANDMEMBER", "{p}:z", "2", setup=ZSET, arm=2)
add("zrandmember", "ZRANDMEMBER", "{p}:z", "2", "WITHSCORES", setup=ZSET, arm=3)
for name, command, lo, hi in (
        ("zrange", "ZRANGE", "0", "-1"),
        ("zrevrange", "ZREVRANGE", "0", "-1"),
        ("zrangebyscore", "ZRANGEBYSCORE", "-inf", "+inf"),
        ("zrevrangebyscore", "ZREVRANGEBYSCORE", "+inf", "-inf")):
    add(name, command, "{p}:z", lo, hi, setup=ZSET, arm=0)
    add(name, command, "{p}:z", lo, hi, "WITHSCORES", setup=ZSET, arm=1)
for name, command, lo, hi in (("zrangebylex", "ZRANGEBYLEX", "-", "+"),
                              ("zrevrangebylex", "ZREVRANGEBYLEX", "+", "-")):
    add(name, command, "{p}:lex", lo, hi,
        setup=(("DEL", "{p}:lex"), ("ZADD", "{p}:lex", "0", "a", "0", "b")))
add("zrangestore", "ZRANGESTORE", "{p}:out", "{p}:z", "0", "-1", setup=ZSET)
add("zrank", "ZRANK", "{p}:z", "missing", setup=ZSET, arm=0)
add("zrank", "ZRANK", "{p}:z", "a", setup=ZSET, arm=1)
add("zrank", "ZRANK", "{p}:z", "a", "WITHSCORE", setup=ZSET, arm=2)
add("zrem", "ZREM", "{p}:z", "a", "missing", setup=ZSET)
add("zremrangebylex", "ZREMRANGEBYLEX", "{p}:lex", "[a", "[a",
    setup=(("DEL", "{p}:lex"), ("ZADD", "{p}:lex", "0", "a", "0", "b")))
add("zremrangebyrank", "ZREMRANGEBYRANK", "{p}:z", "0", "0", setup=ZSET)
add("zremrangebyscore", "ZREMRANGEBYSCORE", "{p}:z", "1", "1", setup=ZSET)
add("zrevrank", "ZREVRANK", "{p}:z", "missing", setup=ZSET, arm=0)
add("zrevrank", "ZREVRANK", "{p}:z", "a", setup=ZSET, arm=1)
add("zrevrank", "ZREVRANK", "{p}:z", "a", "WITHSCORE", setup=ZSET, arm=2)
add("zscan", "ZSCAN", "{p}:z", "0", setup=ZSET)
add("zscore", "ZSCORE", "{p}:z", "a", setup=ZSET, arm=0)
add("zscore", "ZSCORE", "{p}:z", "missing", setup=ZSET, arm=1)
add("zunion", "ZUNION", "2", "{p}:z", "{p}:z2",
    setup=ZSET + (("DEL", "{p}:z2"), ("ZADD", "{p}:z2", "4", "d")), arm=0)
add("zunion", "ZUNION", "2", "{p}:z", "{p}:z2", "WITHSCORES",
    setup=ZSET + (("DEL", "{p}:z2"), ("ZADD", "{p}:z2", "4", "d")), arm=1)
add("zunionstore", "ZUNIONSTORE", "{p}:out", "2", "{p}:z", "{p}:z2",
    setup=ZSET + (("DEL", "{p}:z2", "{p}:out"), ("ZADD", "{p}:z2", "4", "d")))


# GEO commands.
GEO = (("DEL", "{p}:geo"),
       ("GEOADD", "{p}:geo", "13.361389", "38.115556", "Palermo",
        "15.087269", "37.502669", "Catania"))
add("geoadd", "GEOADD", "{p}:geo", "13", "38", "place", setup=(("DEL", "{p}:geo"),))
add("geodist", "GEODIST", "{p}:geo", "Palermo", "missing", "km", setup=GEO, arm=0)
add("geodist", "GEODIST", "{p}:geo", "Palermo", "Catania", "km", setup=GEO, arm=1)
add("geohash", "GEOHASH", "{p}:geo", "Palermo", "missing", setup=GEO)
add("geopos", "GEOPOS", "{p}:geo", "Palermo", "missing", setup=GEO)
for name, command, center in (
        ("georadius", "GEORADIUS", ("15", "37", "200", "km")),
        ("georadius_ro", "GEORADIUS_RO", ("15", "37", "200", "km")),
        ("georadiusbymember", "GEORADIUSBYMEMBER", ("Palermo", "200", "km")),
        ("georadiusbymember_ro", "GEORADIUSBYMEMBER_RO", ("Palermo", "200", "km"))):
    add(name, command, "{p}:geo", *center, setup=GEO, arm=0)
    add(name, command, "{p}:geo", *center, "WITHDIST", "WITHHASH", "WITHCOORD",
        setup=GEO, arm=1)
add("georadius", "GEORADIUS", "{p}:geo", "15", "37", "200", "km", "STORE", "{p}:geoout",
    setup=GEO + (("DEL", "{p}:geoout"),), arm=2)
add("georadiusbymember", "GEORADIUSBYMEMBER", "{p}:geo", "Palermo", "200", "km",
    "STORE", "{p}:geoout", setup=GEO + (("DEL", "{p}:geoout"),), arm=2)
add("geosearch", "GEOSEARCH", "{p}:geo", "FROMLONLAT", "15", "37", "BYRADIUS", "200", "km",
    setup=GEO, arm=0)
add("geosearch", "GEOSEARCH", "{p}:geo", "FROMMEMBER", "Palermo", "BYRADIUS", "200", "km",
    "WITHDIST", "WITHHASH", "WITHCOORD", setup=GEO, arm=1)
add("geosearchstore", "GEOSEARCHSTORE", "{p}:geoout", "{p}:geo", "FROMMEMBER", "Palermo",
    "BYRADIUS", "200", "km", setup=GEO + (("DEL", "{p}:geoout"),))


# Streams and consumer groups.
GROUP = STREAM + (("XGROUP", "CREATE", "{p}:x", "g", "0-0"),)
PENDING = GROUP + (("XREADGROUP", "GROUP", "g", "c1", "COUNT", "1", "STREAMS", "{p}:x", ">"),)
add("xack", "XACK", "{p}:x", "g", "1-0", setup=PENDING)
add("xadd", "XADD", "{p}:x", "*", "f", "v", setup=(("DEL", "{p}:x"),), arm=0)
add("xadd", "XADD", "{p}:missing", "NOMKSTREAM", "*", "f", "v",
    setup=(("DEL", "{p}:missing"),), arm=1)
add("xautoclaim", "XAUTOCLAIM", "{p}:x", "g", "c2", "0", "0-0", "COUNT", "1",
    setup=PENDING, arm=0)
add("xautoclaim", "XAUTOCLAIM", "{p}:x", "g", "c2", "0", "0-0", "COUNT", "1", "JUSTID",
    setup=PENDING, arm=1)
add("xclaim", "XCLAIM", "{p}:x", "g", "c2", "0", "1-0", "JUSTID", setup=PENDING, arm=0)
add("xclaim", "XCLAIM", "{p}:x", "g", "c2", "0", "1-0", setup=PENDING, arm=1)
add("xdel", "XDEL", "{p}:x", "1-0", setup=STREAM)
add("xlen", "XLEN", "{p}:x", setup=STREAM)
add("xpending", "XPENDING", "{p}:x", "g", "-", "+", "10", setup=PENDING, arm=0)
add("xpending", "XPENDING", "{p}:x", "g", setup=PENDING, arm=1)
add("xrange", "XRANGE", "{p}:x", "-", "+", setup=STREAM)
add("xread", "XREAD", "STREAMS", "{p}:x", "0-0", setup=STREAM, arm=0)
add("xread", "XREAD", "BLOCK", "1", "STREAMS", "{p}:missing", "$",
    setup=(("DEL", "{p}:missing"),), arm=1)
add("xreadgroup", "XREADGROUP", "GROUP", "g", "c1", "STREAMS", "{p}:x", ">",
    setup=GROUP, arm=1)
add("xreadgroup", "XREADGROUP", "GROUP", "g", "c1", "BLOCK", "1", "STREAMS", "{p}:x", ">",
    setup=GROUP + (("XREADGROUP", "GROUP", "g", "c1", "STREAMS", "{p}:x", ">"),), arm=0)
add("xrevrange", "XREVRANGE", "{p}:x", "+", "-", setup=STREAM)
add("xsetid", "XSETID", "{p}:x", "3-0", setup=STREAM)
add("xtrim", "XTRIM", "{p}:x", "MAXLEN", "=", "1", setup=STREAM)

add("xgroup|create", "XGROUP", "CREATE", "{p}:newstream", "g", "$", "MKSTREAM",
    setup=(("DEL", "{p}:newstream"),))
add("xgroup|createconsumer", "XGROUP", "CREATECONSUMER", "{p}:x", "g", "c1", setup=GROUP, arm=0)
add("xgroup|createconsumer", "XGROUP", "CREATECONSUMER", "{p}:x", "g", "c1",
    setup=GROUP + (("XGROUP", "CREATECONSUMER", "{p}:x", "g", "c1"),), arm=1)
add("xgroup|delconsumer", "XGROUP", "DELCONSUMER", "{p}:x", "g", "c1", setup=PENDING)
add("xgroup|destroy", "XGROUP", "DESTROY", "{p}:x", "g", setup=GROUP, arm=0)
add("xgroup|destroy", "XGROUP", "DESTROY", "{p}:x", "missing", setup=GROUP, arm=1)
add("xgroup|help", "XGROUP", "HELP")
add("xgroup|setid", "XGROUP", "SETID", "{p}:x", "g", "1-0", setup=GROUP)
add("xinfo|consumers", "XINFO", "CONSUMERS", "{p}:x", "g", setup=PENDING)
add("xinfo|groups", "XINFO", "GROUPS", "{p}:x", setup=GROUP)
add("xinfo|help", "XINFO", "HELP")
add("xinfo|stream", "XINFO", "STREAM", "{p}:x", setup=STREAM, arm=0)
add("xinfo|stream", "XINFO", "STREAM", "{p}:x", "FULL", "COUNT", "10", setup=PENDING, arm=1)


# Remaining generic algorithms.
add("lcs", "LCS", "{p}:a", "{p}:b",
    setup=(("SET", "{p}:a", "ohmytext"), ("SET", "{p}:b", "mynewtext")), arm=0)
add("lcs", "LCS", "{p}:a", "{p}:b", "LEN",
    setup=(("SET", "{p}:a", "ohmytext"), ("SET", "{p}:b", "mynewtext")), arm=1)
add("lcs", "LCS", "{p}:a", "{p}:b", "IDX", "WITHMATCHLEN",
    setup=(("SET", "{p}:a", "ohmytext"), ("SET", "{p}:b", "mynewtext")), arm=2)
add("scan", "SCAN", "0", "MATCH", "{p}:*", "COUNT", "100", setup=STRING)
add("sort", "SORT", "{p}:l", setup=(("DEL", "{p}:l"), ("RPUSH", "{p}:l", "3", "1", "2")), arm=1)
add("sort", "SORT", "{p}:l", "STORE", "{p}:out",
    setup=(("DEL", "{p}:l", "{p}:out"), ("RPUSH", "{p}:l", "3", "1", "2")), arm=0)
add("sort_ro", "SORT_RO", "{p}:l", setup=(("DEL", "{p}:l"),
                                              ("RPUSH", "{p}:l", "3", "1", "2")))


# ACL subcommands.
add("acl|cat", "ACL", "CAT", arm=0)
add("acl|cat", "ACL", "CAT", "string", arm=1)
add("acl|deluser", "ACL", "DELUSER", "{p}:gone",
    setup=(("ACL", "SETUSER", "{p}:gone", "on", "nopass"),))
add("acl|dryrun", "ACL", "DRYRUN", "default", "GET", "{p}:k", arm=0)
add("acl|dryrun", "ACL", "DRYRUN", "{p}:dryuser", "SET", "{p}:k", "v", arm=1,
    setup=(("ACL", "SETUSER", "{p}:dryuser", "reset", "on", "nopass", "+get", "~*"),))
add("acl|genpass", "ACL", "GENPASS", "16")
add("acl|getuser", "ACL", "GETUSER", "default", arm=0)
add("acl|getuser", "ACL", "GETUSER", "{p}:missing", arm=1)
add("acl|help", "ACL", "HELP")
add("acl|list", "ACL", "LIST")
add("acl|log", "ACL", "LOG", "0", arm=0)
add("acl|log", arm=0, special=acl_log_special)
add("acl|log", "ACL", "LOG", "RESET", arm=1)
add("acl|setuser", "ACL", "SETUSER", "{p}:user2", "reset", "on", "nopass", "+get", "~*")
add("acl|users", "ACL", "USERS")
add("acl|whoami", "ACL", "WHOAMI")


# CLIENT subcommands.  Per-case connections keep tracking/name/reply state local.
add("client|caching", "CLIENT", "CACHING", "YES",
    setup=(("CLIENT", "TRACKING", "ON", "OPTIN"),))
add("client|getname", "CLIENT", "GETNAME", arm=1)
add("client|getname", "CLIENT", "GETNAME", setup=(("CLIENT", "SETNAME", "replyschema"),), arm=0)
add("client|getredir", "CLIENT", "GETREDIR", arm=1)
add("client|getredir", "CLIENT", "GETREDIR", arm=0,
    setup=(("CLIENT", "TRACKING", "ON"),))
add("client|getredir", arm=2, special=client_getredir_special)
add("client|help", "CLIENT", "HELP")
add("client|id", "CLIENT", "ID")
add("client|info", "CLIENT", "INFO")
add("client|kill", "CLIENT", "KILL", "ID", "999999999", arm=1)
add("client|kill", arm=0, special=client_kill_legacy_special)
add("client|list", "CLIENT", "LIST")
add("client|no-evict", "CLIENT", "NO-EVICT", "ON")
add("client|no-touch", "CLIENT", "NO-TOUCH", "ON")
add("client|pause", "CLIENT", "PAUSE", "1", "WRITE")
add("client|reply", "CLIENT", "REPLY", "ON")
add("client|setinfo", "CLIENT", "SETINFO", "LIB-NAME", "replyschema")
add("client|setname", "CLIENT", "SETNAME", "replyschema")
add("client|tracking", "CLIENT", "TRACKING", "ON")
add("client|trackinginfo", "CLIENT", "TRACKINGINFO")
add("client|unblock", "CLIENT", "UNBLOCK", "999999999", arm=0)
add("client|unblock", arm=1, special=client_unblock_special)
add("client|unpause", "CLIENT", "UNPAUSE")


# COMMAND and CONFIG metadata maps are especially useful RESP2-map projection probes.
add("command|count", "COMMAND", "COUNT")
add("command|docs", "COMMAND", "DOCS", "GET")
add("command|getkeys", "COMMAND", "GETKEYS", "MSET", "{p}:a", "1", "{p}:b", "2")
add("command|getkeysandflags", "COMMAND", "GETKEYSANDFLAGS", "MSET", "{p}:a", "1", "{p}:b", "2")
add("command|help", "COMMAND", "HELP")
add("command|info", "COMMAND", "INFO", "GET", "replyschema-no-such")
add("command|list", "COMMAND", "LIST")
add("config|get", "CONFIG", "GET", "maxmemory")
add("config|help", "CONFIG", "HELP")
add("config|resetstat", "CONFIG", "RESETSTAT")
add("config|set", "CONFIG", "SET", "notify-keyspace-events", "")


# FUNCTION lifecycle.
FUNCTION_CODE = ("#!lua name=replyschema_sub\n"
                 "redis.register_function{function_name='replyschema_sub_fn', "
                 "callback=function() return 11 end, description='shape', flags={'no-writes'}}\n")
add("function|delete", "FUNCTION", "DELETE", "replyschema_sub",
    setup=(("FUNCTION", "LOAD", "REPLACE", FUNCTION_CODE),))
add("function|dump", "FUNCTION", "DUMP", setup=(("FUNCTION", "LOAD", "REPLACE", FUNCTION_CODE),))
add("function|flush", "FUNCTION", "FLUSH")
add("function|help", "FUNCTION", "HELP")
add("function|list", "FUNCTION", "LIST", "LIBRARYNAME", "replyschema_sub", "WITHCODE",
    setup=(("FUNCTION", "LOAD", "REPLACE", FUNCTION_CODE),))
add("function|load", "FUNCTION", "LOAD", "REPLACE", FUNCTION_CODE)
add("function|restore", special=function_restore_special)
add("function|stats", "FUNCTION", "STATS",
    setup=(("FUNCTION", "LOAD", "REPLACE", FUNCTION_CODE),))


# LATENCY, MEMORY, OBJECT, PUBSUB, SCRIPT, and SLOWLOG subcommands.
add("latency|doctor", "LATENCY", "DOCTOR")
add("latency|help", "LATENCY", "HELP")
add("latency|histogram", "LATENCY", "HISTOGRAM", "GET")
add("latency|history", "LATENCY", "HISTORY", "replyschema-event")
add("latency|latest", "LATENCY", "LATEST")
add("latency|reset", "LATENCY", "RESET", "replyschema-event")
add("memory|doctor", "MEMORY", "DOCTOR")
add("memory|help", "MEMORY", "HELP")
add("memory|malloc-stats", "MEMORY", "MALLOC-STATS")
add("memory|purge", "MEMORY", "PURGE")
add("memory|stats", "MEMORY", "STATS")
add("memory|usage", "MEMORY", "USAGE", "{p}:missing", arm=1)
add("memory|usage", "MEMORY", "USAGE", "{p}:k", setup=STRING, arm=0)
add("object|encoding", "OBJECT", "ENCODING", "{p}:missing", arm=0)
add("object|encoding", "OBJECT", "ENCODING", "{p}:k", setup=STRING, arm=1)
add("object|freq", "OBJECT", "FREQ", "{p}:k",
    setup=(("CONFIG", "SET", "maxmemory-policy", "allkeys-lfu"), ("SET", "{p}:k", "v")))
add("object|help", "OBJECT", "HELP")
add("object|idletime", "OBJECT", "IDLETIME", "{p}:k",
    setup=(("CONFIG", "SET", "maxmemory-policy", "noeviction"), ("SET", "{p}:k", "v")))
add("object|refcount", "OBJECT", "REFCOUNT", "{p}:k", setup=STRING)
add("pubsub|channels", "PUBSUB", "CHANNELS", "{p}:*")
add("pubsub|help", "PUBSUB", "HELP")
add("pubsub|numpat", "PUBSUB", "NUMPAT")
add("pubsub|numsub", "PUBSUB", "NUMSUB", "{p}:channel")
add("pubsub|shardchannels", "PUBSUB", "SHARDCHANNELS", "{p}:*")
add("pubsub|shardnumsub", "PUBSUB", "SHARDNUMSUB", "{p}:channel")
add("script|debug", "SCRIPT", "DEBUG", "NO")
add("script|exists", "SCRIPT", "EXISTS", "0" * 40)
add("script|flush", "SCRIPT", "FLUSH", "SYNC")
add("script|help", "SCRIPT", "HELP")
add("script|load", "SCRIPT", "LOAD", "return 1")
add("slowlog|get", "SLOWLOG", "GET", "1")
add("slowlog|help", "SLOWLOG", "HELP")
add("slowlog|len", "SLOWLOG", "LEN")
add("slowlog|reset", "SLOWLOG", "RESET")

UNREACHABLE.update({"acl|load", "acl|save", "config|rewrite", "function|kill",
                    "latency|graph", "script|kill"})


EXPECTED_ABSENT = {
    "cluster", "migrate", "module", "move", "psync", "replconf", "sentinel", "swapdb", "sync",
}


def command_inventory(top_names):
    connection = Connection(2)
    present = set()
    try:
        for start in range(0, len(top_names), 64):
            names = sorted(top_names)[start:start + 64]
            reply = connection.command("COMMAND", "INFO", *names)
            if reply.kind != "array" or len(reply.value) != len(names):
                raise AssertionError("COMMAND INFO inventory returned %s" % reply.shape())
            present.update(name for name, row in zip(names, reply.value) if row.kind != "null")
        count = connection.command("COMMAND", "COUNT")
        if count.kind != "integer":
            raise AssertionError("COMMAND COUNT returned %s" % count.shape())
        return present, count.value
    finally:
        connection.close()


def invocation_text(argv):
    def show(value):
        if isinstance(value, bytes):
            return repr(value)
        value = str(value)
        return value if re.fullmatch(r"[-+A-Za-z0-9_.*:@]+", value) else repr(value)
    return " ".join(show(x) for x in argv)


def owner_of(endpoint, containers):
    return containers.get(endpoint, endpoint)


def protocol_schema(endpoint, schema, protocol):
    if endpoint != "hello" or protocol != 2:
        return schema
    # Verified against the live Redis 7.4.2 oracle: bare HELLO on a RESP2 connection reports
    # proto=2 in its flattened map.  The shipped schema hard-codes 3 because its normal schema
    # capture invokes HELLO 3; that cannot describe the command's RESP2 projection.
    projected = json.loads(json.dumps(schema))
    projected["properties"]["proto"]["const"] = 2
    return projected


def run():
    schemas, top_names, containers = load_schemas()
    present, command_count = command_inventory(top_names)
    absent = top_names - present
    mismatches = []

    if absent != EXPECTED_ABSENT:
        mismatches.append(("inventory", "COMMAND INFO <all Redis commands>",
                           "the 9 deliberate absences", "absent=%s" % sorted(absent),
                           "expected=%s" % sorted(EXPECTED_ABSENT)))

    print("replyschema: skipped %d absent commands: %s" %
          (len(absent), ", ".join(sorted(absent))))

    covered = {case.endpoint for case in CASES}
    applicable = {endpoint for endpoint in schemas
                  if owner_of(endpoint, containers) in present}
    missing_cases = sorted(applicable - covered - UNREACHABLE)
    extra_cases = sorted(covered - set(schemas))
    for endpoint in missing_cases:
        mismatches.append((endpoint, "<no canonical invocation>", "reply_schema",
                           "missing invocation", "schema endpoint is implemented"))
    for endpoint in extra_cases:
        mismatches.append((endpoint, "<invalid canonical invocation>", "reply_schema",
                           "no schema", "case names an unknown schema endpoint"))

    cases = [case for case in CASES
             if owner_of(case.endpoint, containers) in present and case.endpoint in schemas]
    for index, case in enumerate(cases):
        schema = schemas[case.endpoint]
        expected = arm_label(schema, case.arm)
        for protocol in (2, 3):
            selected = protocol_schema(case.endpoint, arm_schema(schema, case.arm), protocol)
            prefix = "%s:%d:r%d" % (PREFIX, index, protocol)
            connection = None
            argv = argv_for(case.argv, prefix)
            try:
                connection = Connection(protocol)
                setup_error = None
                for setup in case.setup:
                    setup_argv = argv_for(setup, prefix)
                    setup_reply = connection.command(*setup_argv)
                    if setup_reply.kind in ("error", "blob-error"):
                        setup_error = (setup_argv, setup_reply)
                        break
                if setup_error:
                    setup_argv, reply = setup_error
                    mismatches.append((case.endpoint,
                                       "RESP%d setup %s" %
                                       (protocol, invocation_text(setup_argv)), expected,
                                       reply.shape(), "fixture setup returned an error"))
                    continue
                if case.special:
                    argv, reply = case.special(connection, prefix)
                else:
                    reply = connection.command(*argv)
                if reply.kind in ("error", "blob-error"):
                    errors = ["canonical success invocation returned an error"]
                else:
                    errors = validate(reply, selected, protocol)
                if errors:
                    mismatches.append((case.endpoint,
                                       "RESP%d %s" % (protocol, invocation_text(argv)),
                                       expected, reply.shape(), errors[0]))
            except Exception as error:  # Make a broken arm one mismatch, not a truncated battery.
                mismatches.append((case.endpoint,
                                   "RESP%d %s" % (protocol, invocation_text(argv)),
                                   expected, "client exception", repr(error)))
            finally:
                if connection:
                    try:
                        connection.close()
                    except Exception:
                        pass

    for endpoint, invocation, expected, got, reason in mismatches:
        print("replyschema mismatch: command=%s invocation=%s expected=%r got=%s (%s)" %
              (endpoint, invocation, expected, got, reason))
    print("replyschema: %d commands, %d invocations, %d mismatches" %
          (command_count, len(cases), len(mismatches)))
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(run())
