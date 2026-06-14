#!/usr/bin/env python3
"""
Pre-generate KoboCollect XLSForms from the geocoder database.

Builds one cascading-select XLSForm per country into a directory served by the
app's /xlsform endpoint. Run at container startup and after a data ingest so
the forms track the boundary layers.

Usage:
    # All countries into the default dir ($XLSFORM_DIR or /data/xlsforms)
    DATABASE_URL=postgresql://... python scripts/generate_xlsforms.py

    # A single country into a custom dir
    DATABASE_URL=postgresql://... python scripts/generate_xlsforms.py --country CD --out /tmp/xlsforms
"""

import argparse
import os
import sys
from pathlib import Path

# Allow running as `python scripts/generate_xlsforms.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from scripts import xlsforms


def main():
    parser = argparse.ArgumentParser(description="Generate cascading-select XLSForms from the geocoder DB.")
    parser.add_argument("--country", help="ISO2 code to generate a single form for (default: all countries).")
    parser.add_argument("--out", default=xlsforms.XLSFORM_DIR, help="Output directory (default: $XLSFORM_DIR or /data/xlsforms).")
    args = parser.parse_args()

    if not os.getenv("DATABASE_URL"):
        sys.exit("ERROR: DATABASE_URL is not set.")

    if args.country:
        path = xlsforms.generate_one(args.country, args.out)
        print(f"Wrote {path}")
    else:
        written = xlsforms.generate_all(args.out)
        print(f"Wrote {len(written)} XLSForm(s) to {args.out}")


if __name__ == "__main__":
    main()
