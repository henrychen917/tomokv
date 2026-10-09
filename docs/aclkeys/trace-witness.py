#!/usr/bin/env python3
"""Record the existing ACL battery's strict witness without changing its assertions."""
from datetime import datetime, timezone
from pathlib import Path
import runpy
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import _client_wait


def stamp(message):
    print(datetime.now(timezone.utc).isoformat(), message, flush=True)


original_call = _client_wait.call


def observed_call(observer, *args):
    value = original_call(observer, *args)
    if args[:2] == ("CLIENT", "LIST"):
        stamp("CLIENT LIST observation: " + repr(value))
    return value


_client_wait.call = observed_call
labels = {"allow blocking key", "blocking key clean slate", "blocking AUTH",
          "revoke blocked key", "wake blocked command", "blocking recheck"}


def trace(frame, event, value):
    if frame.f_code.co_filename != str(ROOT / "tests/acl.py"):
        return None
    if frame.f_code.co_name == "expect" and frame.f_locals.get("label") in labels:
        if event == "return":
            stamp("assertion %s: actual=%r expected=%r" % (
                frame.f_locals["label"], frame.f_locals["actual"], frame.f_locals["wanted"]))
        return trace
    if frame.f_code.co_name == "read":
        if (event == "return" and frame.f_locals.get("kind") == b"-" and
                frame.f_locals.get("self") is frame.f_globals.get("blocked")):
            stamp("blocked-client wire reply: " + repr(b"-" + frame.f_locals["line"]))
        return trace
    return None


sys.settrace(trace)
threading.settrace(trace)
sys.argv[0] = str(ROOT / "tests/acl.py")
stamp("running the unchanged tests/acl.py battery")
runpy.run_path(sys.argv[0], run_name="__main__")
stamp("strict witness and ACL battery PASS")
