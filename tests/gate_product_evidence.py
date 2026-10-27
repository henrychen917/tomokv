"""Retain and replay every pass contributing to the full measurement verdict."""
import hashlib
import json
from pathlib import Path


def artifact(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def read_product(path):
    from gate_receipt import require
    value = json.loads(Path(path).read_text())
    require(value.get("schema") == 1 and value.get("complete") is True,
            "measurement product did not complete")
    for row in value["passes"]:
        for name in ("report", "null"):
            binding = row[name]
            raw = Path(binding["path"]).read_bytes()
            require(hashlib.sha256(raw).hexdigest() == binding["sha256"],
                    "measurement product artifact changed: " + name)
            row[name] = json.loads(raw)
    return value


def validate_product(root, product, state, report, control, candidate, ended):
    from gate_receipt import require, inventory, validate_abba
    from abba_evidence import validate_comparison
    require(isinstance(product, dict) and product.get("schema") == 1 and product.get("complete") is True,
            "missing complete measurement product evidence")
    passes = product.get("passes", [])
    require([row.get("pass_name") for row in passes] == ["headline", "epoll"] and
            all(type(row.get("exit_code")) is int and row["exit_code"] == 0 for row in passes),
            "full product requires both successful headline and epoll passes")
    require(passes[0]["report"] == report and passes[0]["null"] == control,
            "product headline evidence differs from receipt")
    companion = inventory(root, root / "tests/netio_cells.txt")
    require(companion == state.get("product_inventory"), "epoll product inventory changed or missing")
    epoll_state = {**state, "inventory": companion}
    row = passes[1]
    started, _ = validate_abba(row["report"], epoll_state, now=ended, candidate=candidate)
    require(started + 1 >= candidate["bound_at"], "epoll ABBA predates candidate binding")
    validate_abba(row["null"], epoll_state, now=ended, null=True)
    validate_comparison(row["report"], row["null"], now=ended)
