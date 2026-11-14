"""Command line: `python -m case_sensor` (run from sensor-node/receiver).

python -m case_sensor --csv case.csv              listen until Ctrl+C
python -m case_sensor --csv case.csv --duration 600
python -m case_sensor --simulate --loss 0.05      pretend to be a node
"""

from __future__ import annotations

import argparse
import sys

from . import receiver, simulate
from .packet import DEFAULT_PORT


def fraction(text: str) -> float:
    value = float(text)
    if not 0.0 <= value < 1.0:
        raise argparse.ArgumentTypeError("must be from 0 up to (not including) 1, e.g. 0.05")
    return value


def positive(text: str) -> float:
    value = float(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be above 0")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m case_sensor",
        description="Receive PC Doctor case-sensor packets over UDP, or simulate a node.",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="UDP port (default %(default)s)"
    )
    parser.add_argument(
        "--host",
        default=None,
        help="listen: address to bind (default 0.0.0.0, every network); "
        "--simulate: where to send (default 127.0.0.1)",
    )
    parser.add_argument("--quiet", action="store_true", help="print only the summary")

    listen = parser.add_argument_group("listening (the default)")
    listen.add_argument(
        "--csv", metavar="PATH", help="write elapsed_s,case_temp_c,case_humidity_pct here"
    )
    listen.add_argument("--duration", type=positive, metavar="SECONDS", help="stop after this long")

    sim = parser.add_argument_group("simulating a node")
    sim.add_argument(
        "--simulate", action="store_true", help="send made-up packets instead of listening"
    )
    sim.add_argument(
        "--rate", type=positive, default=1.0, metavar="HZ", help="samples per second (default 1)"
    )
    sim.add_argument(
        "--count", type=int, metavar="N", help="stop after N samples (default: run until Ctrl+C)"
    )
    sim.add_argument(
        "--loss",
        type=fraction,
        default=0.0,
        help="fraction of packets to drop on purpose, e.g. 0.05",
    )
    sim.add_argument(
        "--start-seq",
        type=int,
        default=0,
        metavar="N",
        help="first sequence number (try 4294967290 to see the wrap)",
    )
    sim.add_argument("--seed", type=int, help="random seed, for a repeatable run")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.simulate:
        simulate.run(
            host=args.host or "127.0.0.1",
            port=args.port,
            rate_hz=args.rate,
            count=args.count,
            loss=args.loss,
            start_seq=args.start_seq,
            seed=args.seed,
            quiet=args.quiet,
        )
        return 0

    host = args.host or "0.0.0.0"
    if args.csv:
        # newline="" is what the csv module wants: it writes its own line ends.
        with open(args.csv, "w", newline="", encoding="utf-8") as csv_file:
            summary = receiver.listen(host, args.port, csv_file, args.duration, args.quiet)
    else:
        summary = receiver.listen(host, args.port, None, args.duration, args.quiet)
    print()
    print(summary.format())
    return 0


if __name__ == "__main__":
    sys.exit(main())
