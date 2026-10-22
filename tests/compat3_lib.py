"""Shared endpoint/receipt helpers; no listener or load generator."""
import argparse
import json
from _lib import Conn, RespError, info, topology


def wire(value):
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, RespError):
        return {"error": value.message.hex()}
    if isinstance(value, (list, tuple)):
        return [wire(v) for v in value]
    if isinstance(value, dict):
        return {str(k): wire(v) for k, v in value.items()}
    return value


def equal(got, want, label):
    assert got == want, f"{label}: {got!r} != {want!r}"


def run(probe, cases, prepare=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("host")
    p.add_argument("port", type=int)
    p.add_argument("--oracle", nargs=2, required=True)
    p.add_argument("--case", choices=cases, required=True)
    p.add_argument("--mode", choices=("1s", "2s"), required=True)
    p.add_argument("--engine", choices=("epoll", "uring"), required=True)
    p.add_argument("--atomic", type=int, required=True)
    p.add_argument("--read-local", type=int, required=True)
    args = p.parse_args()
    if prepare:
        prepare(args)
    outputs = []
    for name, host, port in (("oracle", *args.oracle), ("target", args.host, args.port)):
        c = Conn(host, port, timeout=8, buffering=0)
        try:
            if name == "oracle":
                version = info(c, "server")["redis_version"]
                assert version.startswith("7.4."), version
                print("ORACLE " + version, flush=True)
            else:
                observed = info(c, "server")
                wanted = dict(thread_mode=args.mode, net_io=args.engine,
                              atomic=str(args.atomic), read_local=str(args.read_local), shards="16")
                for key, value in wanted.items():
                    equal(observed[key], value, "geometry " + key)
                topo = topology(c)
                equal(len(topo.roles), 8, "eight threads")
                roles = {r: list(topo.roles.values()).count(r) for r in ("io", "ex", "fused")}
                equal(roles, dict(io=6, ex=2, fused=0) if args.mode == "2s" else dict(io=0, ex=0, fused=8), "roles")
                print("GEOMETRY " + json.dumps(wanted), flush=True)
            equal(c.cmd("CONFIG", "SET", "maxmemory", 0), b"OK", "clear cap")
            equal(c.cmd("FLUSHALL"), b"OK", "fresh keys")
            result = probe(c, args.case)
            outputs.append(result)
            print(name.upper() + " " + json.dumps(wire(result), sort_keys=True), flush=True)
        finally:
            c.cmd("CONFIG", "SET", "maxmemory", 0)
            c.close()
    equal(outputs[1], outputs[0], args.case + " exact oracle observations")
    print("PASS " + args.case, flush=True)
