from invoice_tool.pricing import apply_discount, line_total, subtotal, total_with_tax

ITEMS = [{"qty": 2, "unit_price": 10.0}, {"qty": 1, "unit_price": 5.5}]


def test_line_total():
    assert line_total(3, 1.1) == 3.3


def test_subtotal():
    assert subtotal(ITEMS) == 25.5


def test_total_with_tax():
    assert total_with_tax(ITEMS) == 27.54


def test_apply_discount_rounds_to_cents():
    assert apply_discount(37.03, 10) == 33.33
