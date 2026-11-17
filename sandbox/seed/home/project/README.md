# invoice-tool

A small command-line tool for turning CSV exports into customer invoices.

## Features

- Reads invoice line items from `data/invoices.csv`
- Computes subtotals, discounts and sales tax (8% by default)
- Prints a per-customer summary, or writes one invoice file per customer

## Usage

```bash
python -m invoice_tool summary data/invoices.csv
python -m invoice_tool render data/invoices.csv --out invoices/
```

## Development

Run the tests with `pytest`. Build artifacts go in `build/`, which is safe to delete.
Copy `config.example.yaml` to `config.yaml` for local settings; secrets go in `.env`.

Maintainer: Dana Okafor (dana@example.com)
