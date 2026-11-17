from invoice_tool.storage import totals_by_customer


def test_totals_by_customer():
    rows = [
        {"customer": "Acme", "amount": "10.00"},
        {"customer": "Acme", "amount": "5.00"},
        {"customer": "Globex", "amount": "7.50"},
    ]
    assert totals_by_customer(rows) == {"Acme": 15.0, "Globex": 7.5}
