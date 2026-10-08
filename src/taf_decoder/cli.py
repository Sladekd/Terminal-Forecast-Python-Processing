"""Command line interface: ``taf-decoder``.

Examples::

    taf-decoder "TAF LKTB 030500Z 0306/0406 17007KT 9999 SCT025=" --reference-time 2023-08-03
    taf-decoder -f TAF202007.txt -o decoded.csv --kind timeline
    cat tafs.txt | taf-decoder --format json
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import __version__
from .api import KINDS, decode_many
from .frames import BECMG_MODES
from .ogimet import split_reports


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="taf-decoder",
        description="Decode aviation TAF forecasts into tables (CSV, JSON or text).",
    )
    p.add_argument("taf", nargs="*", help="TAF report(s); omit to read --file or stdin")
    p.add_argument("-f", "--file", help="Text file with TAFs (Ogimet export or one TAF per '=')")
    p.add_argument("-o", "--output", help="Write to this file instead of stdout")
    p.add_argument("-k", "--kind", choices=KINDS, default="groups", help="Table layout (default: groups)")
    p.add_argument(
        "--format",
        choices=("csv", "json", "table"),
        help="Output format (default: csv for files/pipes, table for a terminal)",
    )
    p.add_argument("--becmg", choices=BECMG_MODES, default="overlap", help="BECMG timing (timeline/hourly)")
    p.add_argument("--reference-time", help="Date near issue time when TAFs lack a YYYYMMDDHHMM stamp")
    p.add_argument("--strict", action="store_true", help="Treat any unparsed token as an error")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.taf:
        reports = [r for t in args.taf for r in split_reports(t)]
    elif args.file:
        with open(args.file, encoding="utf-8", errors="replace") as fh:
            reports = split_reports(fh.read())
    elif not sys.stdin.isatty():
        reports = split_reports(sys.stdin.read())
    else:
        build_parser().print_usage(sys.stderr)
        return 2

    if not reports:
        print("taf-decoder: no reports found", file=sys.stderr)
        return 1

    df = decode_many(
        reports,
        kind=args.kind,
        reference_time=args.reference_time,
        strict=args.strict,
        becmg=args.becmg,
    )
    fmt = args.format or ("table" if args.output is None and sys.stdout.isatty() else "csv")
    if fmt == "csv":
        out = df.to_csv(index=False)
    elif fmt == "json":
        out = df.to_json(orient="records", date_format="iso", indent=1)
    else:
        shown = df.dropna(axis=1, how="all")
        out = shown.to_string(index=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as fh:
            fh.write(out)
    else:
        sys.stdout.write(out if out.endswith("\n") else out + "\n")

    n_err = int(df.drop_duplicates("taf_index")["error"].notna().sum())
    if n_err:
        print(f"taf-decoder: {n_err} of {len(reports)} report(s) could not be decoded", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
