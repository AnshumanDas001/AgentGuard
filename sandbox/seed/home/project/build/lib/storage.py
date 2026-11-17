import csv
from collections import defaultdict


def load_rows(path):
    """Read invoice rows from a CSV file."""
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def totals_by_customer(rows):
    """Total billed amount per customer."""
    totals = defaultdict(float)
    for row in rows:
        totals[row["customer"]] += float(row["amount"])
    # TODO: use Decimal instead of float for money
    return dict(totals)
