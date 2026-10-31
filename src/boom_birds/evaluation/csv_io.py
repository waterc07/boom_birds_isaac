"""CSV helpers for evaluation records with list-valued columns."""
import csv
import json
from pathlib import Path


def _cell(value):
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value)
    return value


def write_rows_csv(path, columns, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_cell(row[column]) for column in columns])


def read_rows_csv(path):
    with Path(path).open(encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))
