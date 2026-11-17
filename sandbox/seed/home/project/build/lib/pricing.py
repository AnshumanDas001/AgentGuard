TAX_RATE = 0.08


def line_total(qty, unit_price):
    return round(qty * unit_price, 2)


def subtotal(items):
    """Sum of line totals before tax."""
    return sum(line_total(item["qty"], item["unit_price"]) for item in items)


def apply_discount(amount, percent):
    # TODO: reject percentages outside 0-100
    return amount - amount * percent / 100


def total_with_tax(items, tax_rate=TAX_RATE):
    # TODO: items marked tax_exempt should not be taxed
    return round(subtotal(items) * (1 + tax_rate), 2)
