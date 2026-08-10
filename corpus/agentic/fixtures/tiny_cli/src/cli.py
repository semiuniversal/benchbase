"""Tiny CLI entrypoint."""
from __future__ import annotations
import argparse
from .greet import greet
from .mathutil import add

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tiny-cli")
    p.add_argument("name", nargs="?", default="world")
    p.add_argument("--add", nargs=2, type=int, metavar=("A", "B"))
    # --verbose intentionally absent for a task to add
    args = p.parse_args(argv)
    if args.add:
        print(add(args.add[0], args.add[1]))
        return 0
    print(greet(args.name))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
