import sys

from invoice_tool.storage import load_rows, totals_by_customer


def main(argv):
    if len(argv) < 3 or argv[1] != "summary":
        print("usage: python -m invoice_tool summary <file.csv>")
        return 2
    for customer, total in sorted(totals_by_customer(load_rows(argv[2])).items()):
        print(f"{customer:20} {total:>10.2f}")
    # TODO: implement the `render` command
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
