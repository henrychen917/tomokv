#!/usr/bin/env python3
"""redis-py smoke against an existing listener; never starts a server or installs packages."""
import argparse
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    args = parser.parse_args()
    try:
        import redis
    except ModuleNotFoundError as error:
        if error.name != "redis":
            raise
        print("SKIP: redis-py is absent; no package installed and no connection attempted.")
        return

    print("redis-py", redis.__version__)
    for protocol in (2, 3):
        client = redis.Redis(host=args.host, port=args.port, protocol=protocol,
                             socket_connect_timeout=3, socket_timeout=3)
        try:
            info = client.info()
            version = info["redis_version"]
            assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version), version
            assert tuple(map(int, version.split("."))) >= (7, 4, 0), version
            assert version == "7.4.10" and info["tomokv_version"] == "1.0-cpp", info
            hello = client.execute_command("HELLO", protocol)
            if isinstance(hello, list):
                hello = dict(zip(hello[::2], hello[1::2]))
            assert hello[b"version"] == b"7.4.10" and hello[b"proto"] == protocol, hello
            assert client.ping()
            print("PASS RESP%d client.info()['redis_version']=%s >= 7.4; HELLO=%r; PING=True" %
                  (protocol, version, hello))
        finally:
            client.close()


if __name__ == "__main__":
    main()
