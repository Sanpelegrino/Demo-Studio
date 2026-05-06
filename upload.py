"""CLI script for uploading datasets into Demo Studio.

Orchestrates: detect scenario -> prepare CSVs -> generate manifest -> load into Postgres.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from manifest_builder import (
    Scenario,
    JoinDef,
    detect_scenario,
    inspect_tables,
    generate_manifest,
    write_manifest,
    prepare_csvs,
)
from seed_manifest import load_manifest


DATASETS_DIR = Path(__file__).parent / "datasets"


def parse_join(raw: str) -> JoinDef:
    """Parse a join string like 'FromTable.FromField -> ToTable.ToField' into a JoinDef."""
    parts = raw.split(" -> ")
    if len(parts) != 2:
        print(
            f"Error: Invalid join format: {raw!r}\n"
            f"Expected format: FromTable.FromField -> ToTable.ToField\n"
            f"Example: Orders.Product ID -> Products.Product ID",
            file=sys.stderr,
        )
        sys.exit(1)

    left, right = parts[0].strip(), parts[1].strip()

    dot_pos = left.find(".")
    if dot_pos == -1:
        print(
            f"Error: Left side of join missing dot separator: {left!r}\n"
            f"Expected format: FromTable.FromField -> ToTable.ToField\n"
            f"Example: Orders.Product ID -> Products.Product ID",
            file=sys.stderr,
        )
        sys.exit(1)
    from_table = left[:dot_pos]
    from_field = left[dot_pos + 1:]

    dot_pos = right.find(".")
    if dot_pos == -1:
        print(
            f"Error: Right side of join missing dot separator: {right!r}\n"
            f"Expected format: FromTable.FromField -> ToTable.ToField\n"
            f"Example: Orders.Product ID -> Products.Product ID",
            file=sys.stderr,
        )
        sys.exit(1)
    to_table = right[:dot_pos]
    to_field = right[dot_pos + 1:]

    return JoinDef(
        from_table=from_table,
        from_field=from_field,
        to_table=to_table,
        to_field=to_field,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload datasets into Demo Studio Postgres.",
        epilog=(
            "Examples:\n"
            '  python upload.py --folder "datasets/Enterprise Superstore"\n'
            "  python upload.py --file data.csv\n"
            '  python upload.py --file report.xlsx --sheet "Orders"\n'
            '  python upload.py --file report.xlsx --sheets "Orders,Products" '
            '--join "Orders.Product ID -> Products.Product ID"\n'
            '  python upload.py --folder my_data/ --join "Sales.cust_id -> Customers.cust_id"\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--folder", type=str, help="Path to folder containing dataset files")
    parser.add_argument("--file", type=str, help="Path to a single file (.csv, .xls, .xlsx)")
    parser.add_argument("--sheet", type=str, help="For XLS: load only this one sheet")
    parser.add_argument("--sheets", type=str, help="For XLS: comma-separated list of sheets to include")
    parser.add_argument(
        "--join", type=str, action="append", dest="joins", default=[],
        help='Define a join: "FromTable.FromField -> ToTable.ToField" (repeatable)',
    )
    parser.add_argument("--name", type=str, help="Dataset name override (defaults to folder name or file stem)")

    args = parser.parse_args()

    # ── Validate: must have --file or --folder (not both, not neither) ──
    if args.file and args.folder:
        print("Error: Provide --file or --folder, not both.", file=sys.stderr)
        sys.exit(1)
    if not args.file and not args.folder:
        print("Error: Provide either --file or --folder.", file=sys.stderr)
        sys.exit(1)

    # ── Determine target folder ──
    if args.file:
        file_path = Path(args.file).resolve()
        if not file_path.exists():
            print(f"Error: File not found: {file_path}", file=sys.stderr)
            sys.exit(1)

        stem = file_path.stem
        target = DATASETS_DIR / stem
        if target.exists():
            print(f"Replacing existing dataset: {target.name}")
            shutil.rmtree(target)
        target.mkdir(parents=True)
        shutil.copy2(file_path, target / file_path.name)
    else:
        target = Path(args.folder).resolve()
        if not target.is_dir():
            print(f"Error: Folder not found: {target}", file=sys.stderr)
            sys.exit(1)

    # ── Dataset name ──
    dataset_name = args.name or target.name

    # ── Detect scenario ──
    try:
        scenario = detect_scenario(target)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # ── If manifest exists and no --join overrides, just load directly ──
    if scenario == Scenario.HAS_MANIFEST and not args.joins:
        try:
            result = load_manifest(target)
        except Exception as e:
            print(f"Database error: {e}", file=sys.stderr)
            sys.exit(1)
        _print_summary(result)
        return

    # ── Determine sheets list ──
    sheets: list[str] | None = None
    if args.sheet:
        sheets = [args.sheet]
    elif args.sheets:
        sheets = [s.strip() for s in args.sheets.split(",")]

    # ── Prepare CSVs (for XLS scenarios) ──
    if scenario in (Scenario.SINGLE_SHEET_XLS, Scenario.MULTI_SHEET_XLS):
        prepare_csvs(target, scenario, sheets)

    # ── Inspect tables ──
    tables = inspect_tables(target, scenario, sheets)

    # ── Parse join definitions ──
    joins: list[JoinDef] = []
    for raw_join in args.joins:
        joins.append(parse_join(raw_join))

    # ── Generate and write manifest ──
    manifest = generate_manifest(dataset_name, tables, joins)
    write_manifest(target, manifest)

    # ── Load into Postgres ──
    try:
        result = load_manifest(target)
    except Exception as e:
        print(f"Database error: {e}", file=sys.stderr)
        sys.exit(1)

    _print_summary(result)


def _print_summary(result: dict) -> None:
    """Print a human-readable load summary."""
    print(f"\nDataset: {result['dataset']}")
    print(f"Tables:  {len(result['tables'])}")
    total_rows = sum(result["tables"].values())
    print(f"Rows:    {total_rows:,}")
    print("Views:")
    for view in result["views"]:
        print(f"  - {view}")
    print()


if __name__ == "__main__":
    main()
