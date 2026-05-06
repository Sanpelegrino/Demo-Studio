"""Manifest builder for Demo Studio upload flow.

Detects the upload scenario (single CSV, Excel, multi-CSV, or existing manifest),
inspects table structures, generates a valid JUJU_RELATIONAL_SCHEMA_MANIFEST_V1
manifest, and prepares CSVs from Excel files as needed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pandas as pd


class Scenario(Enum):
    HAS_MANIFEST = "has_manifest"
    SINGLE_CSV = "single_csv"
    SINGLE_SHEET_XLS = "single_sheet_xls"
    MULTI_SHEET_XLS = "multi_sheet_xls"
    MULTI_CSV_NO_MANIFEST = "multi_csv_no_manifest"


@dataclass
class TableInfo:
    name: str
    columns: list[str]
    row_count: int


@dataclass
class JoinDef:
    from_table: str
    from_field: str
    to_table: str
    to_field: str


def _excel_files(folder: Path) -> list[Path]:
    return list(folder.glob("*.xls")) + list(folder.glob("*.xlsx"))


def detect_scenario(folder: Path) -> Scenario:
    """Determine what kind of upload is present in the given folder."""
    if (folder / "manifest.json").exists():
        return Scenario.HAS_MANIFEST

    csv_files = list(folder.glob("*.csv"))
    xls_files = _excel_files(folder)

    if len(xls_files) == 1 and len(csv_files) == 0:
        with pd.ExcelFile(xls_files[0]) as xf:
            if len(xf.sheet_names) == 1:
                return Scenario.SINGLE_SHEET_XLS
            else:
                return Scenario.MULTI_SHEET_XLS

    if len(csv_files) == 1 and len(xls_files) == 0:
        return Scenario.SINGLE_CSV

    if len(csv_files) > 1 and len(xls_files) == 0:
        return Scenario.MULTI_CSV_NO_MANIFEST

    raise ValueError(
        f"Unable to detect upload scenario in {folder}. "
        f"Found {len(csv_files)} CSV file(s) and {len(xls_files)} XLS file(s)."
    )


def inspect_tables(
    folder: Path, scenario: Scenario, sheets: list[str] | None = None
) -> list[TableInfo]:
    """Inspect tables in the folder based on the detected scenario.

    Returns a list of TableInfo describing each table's name, columns, and row count.
    """
    if scenario == Scenario.SINGLE_CSV:
        csv_files = list(folder.glob("*.csv"))
        csv_path = csv_files[0]
        columns = list(pd.read_csv(csv_path, nrows=0).columns)
        with open(csv_path, encoding="utf-8") as fh:
            row_count = max(0, sum(1 for _ in fh) - 1)
        return [TableInfo(
            name=csv_path.stem,
            columns=columns,
            row_count=row_count,
        )]

    elif scenario == Scenario.SINGLE_SHEET_XLS:
        with pd.ExcelFile(_excel_files(folder)[0]) as xf:
            sheet_name = xf.sheet_names[0]
            df = xf.parse(sheet_name)
            return [TableInfo(
                name=sheet_name,
                columns=list(df.columns),
                row_count=len(df),
            )]

    elif scenario == Scenario.MULTI_SHEET_XLS:
        with pd.ExcelFile(_excel_files(folder)[0]) as xf:
            target_sheets = sheets if sheets is not None else xf.sheet_names
            results = []
            for sheet_name in target_sheets:
                df = xf.parse(sheet_name)
                results.append(TableInfo(
                    name=sheet_name,
                    columns=list(df.columns),
                    row_count=len(df),
                ))
            return results

    elif scenario == Scenario.MULTI_CSV_NO_MANIFEST:
        csv_files = sorted(folder.glob("*.csv"))
        results = []
        for csv_path in csv_files:
            columns = list(pd.read_csv(csv_path, nrows=0).columns)
            with open(csv_path, encoding="utf-8") as fh:
                row_count = max(0, sum(1 for _ in fh) - 1)
            results.append(TableInfo(
                name=csv_path.stem,
                columns=columns,
                row_count=row_count,
            ))
        return results

    elif scenario == Scenario.HAS_MANIFEST:
        manifest_path = folder / "manifest.json"
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        results = []
        for table_def in manifest.get("tables", []):
            table_name = table_def["tableName"]
            csv_path = folder / f"{table_name}.csv"
            if csv_path.exists():
                columns = list(pd.read_csv(csv_path, nrows=0).columns)
                with open(csv_path, encoding="utf-8") as fh:
                    row_count = max(0, sum(1 for _ in fh) - 1)
            else:
                columns = []
                row_count = 0
            results.append(TableInfo(
                name=table_name,
                columns=columns,
                row_count=row_count,
            ))
        return results

    raise ValueError(f"Unsupported scenario: {scenario}")


def generate_manifest(
    dataset_name: str,
    tables: list[TableInfo],
    joins: list[JoinDef] | None = None,
) -> dict:
    """Generate a manifest dict in JUJU_RELATIONAL_SCHEMA_MANIFEST_V1 format."""
    joins = joins or []

    # Determine fact table: the table with the most outbound FK references.
    # Ties broken by row count (largest wins).
    if len(tables) == 1 or not joins:
        fact_table_name = tables[0].name if tables else None
    else:
        from_counts: dict[str, int] = {}
        for j in joins:
            from_counts[j.from_table] = from_counts.get(j.from_table, 0) + 1

        row_count_map = {t.name: t.row_count for t in tables}
        max_from_count = max(from_counts.values()) if from_counts else 0

        candidates = [
            name for name, count in from_counts.items() if count == max_from_count
        ]
        if len(candidates) == 1:
            fact_table_name = candidates[0]
        else:
            # Tie-break by row count
            fact_table_name = max(
                candidates, key=lambda n: row_count_map.get(n, 0)
            )

    # Build table entries
    table_entries = []
    for t in tables:
        role = "fact" if t.name == fact_table_name else "dimension"
        table_entries.append({
            "tableName": t.name,
            "tableRole": role,
            "entityName": t.name,
            "grain": f"One row per {t.name} record",
            "primaryKey": [],
        })

    # Build join paths
    join_paths = []
    for j in joins:
        join_paths.append({
            "fromTable": j.from_table,
            "fromField": j.from_field,
            "toTable": j.to_table,
            "toField": j.to_field,
            "cardinality": "many_to_one",
            "required": True,
        })

    # Build generated files list
    generated_files = [f"{t.name}.csv" for t in tables]

    shape = "star" if joins else "single_table"

    manifest = {
        "schemaVersion": "JUJU_RELATIONAL_SCHEMA_MANIFEST_V1",
        "datasetName": dataset_name,
        "topology": {"shape": shape},
        "generatedFiles": generated_files,
        "warnings": [],
        "tables": table_entries,
        "joinPaths": join_paths,
    }

    return manifest


def write_manifest(folder: Path, manifest: dict) -> Path:
    """Write manifest.json to the folder, pretty-printed with indent=2.

    Returns the path to the written file.
    """
    manifest_path = folder / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest_path


def prepare_csvs(
    folder: Path, scenario: Scenario, sheets: list[str] | None = None
) -> list[str]:
    """Export Excel sheets to CSV or return existing CSV filenames.

    For XLS scenarios, exports each selected sheet (or all if sheets is None)
    to <SheetName>.csv in the same folder. For CSV scenarios, returns the list
    of existing CSV filenames.

    Returns a list of CSV filenames (not full paths).
    """
    if scenario in (Scenario.SINGLE_SHEET_XLS, Scenario.MULTI_SHEET_XLS):
        with pd.ExcelFile(_excel_files(folder)[0]) as xf:
            target_sheets = sheets if sheets is not None else xf.sheet_names
            csv_filenames = []
            for sheet_name in target_sheets:
                df = xf.parse(sheet_name)
                csv_name = f"{sheet_name}.csv"
                df.to_csv(folder / csv_name, index=False)
                csv_filenames.append(csv_name)
            return csv_filenames

    # CSV scenarios: return existing CSV filenames
    csv_files = sorted(folder.glob("*.csv"))
    return [f.name for f in csv_files]
