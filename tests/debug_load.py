#!/usr/bin/env python3
"""Shell entry point for the shared, witnessed DEBUG load admission barrier."""
import argparse

from _lib import Conn, debug_load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("subcommand", choices=("RELOAD", "LOADAOF"))
    args = parser.parse_args()
    conn = Conn(args.host, args.port, timeout=30)
    try:
        debug_load(conn, args.subcommand)
        print("OK")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
