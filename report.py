import os, sys
import stripe
from collections import defaultdict
from datetime import datetime, timedelta
import argparse
from prettytable import PrettyTable
from cache import StripeKVCache
from warnings import warn

# Set up Stripe API key
stripe.api_version = "2023-10-16"
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')


cache = StripeKVCache()

def get_product(product_id):
    if cache.get(product_id) == None:
        product = stripe.Product.retrieve(product_id)
        cache.set(product_id, product)
    else:
        product = cache.get(product_id)
    if "id" not in product or product.id != product_id:
        warn(f"Product ID mismatch: {product} != {product_id}")
        raise ValueError(f"Product ID mismatch: {product} != {product_id}")
    return product

def get_invoice(invoice_id):
    if cache.get(invoice_id) == None:
        invoice = stripe.Invoice.retrieve(invoice_id)
        cache.set(invoice_id, invoice)
    else:
        invoice = cache.get(invoice_id)
    if "id" not in invoice or invoice.id != invoice_id:
        warn(f"Invoice ID mismatch: {invoice} != {invoice_id}")
        raise ValueError(f"Invoice ID mismatch: {invoice} != {invoice_id}")
    return invoice

def get_pi(id):
    if cache.get(id) == None:
        pi = stripe.PaymentIntent.retrieve(id)
        cache.set(id, pi)
    else:
        pi = cache.get(id)
    if "id" not in pi or pi.id != id:
        warn(f"PaymentIntent ID mismatch: {pi} != {id}")
        raise ValueError(f"PaymentIntent ID mismatch: {pi} != {id}")
    return pi

def get_charge(id):
    if cache.get(id) == None:
        charge = stripe.Charge.retrieve(id)
        cache.set(id, charge)
    else:
        charge = cache.get(id)
    if "id" not in charge or charge.id != id:
        warn(f"Charge ID mismatch: {charge} != {id}")
        raise ValueError(f"Charge ID mismatch: {charge} != {id}")
    return charge

def get_refund(id):
    if cache.get(id) == None:
        refund = stripe.Refund.retrieve(id)
        cache.set(id, refund)
    else:
        refund = cache.get(id)
    if "id" not in refund or refund.id != id:
        warn(f"Refund ID mismatch: {refund} != {id}")
        raise ValueError(f"Refund ID mismatch: {refund} != {id}")
    return refund

def get_dispute(id):
    if cache.get(id) == None:
        dispute = stripe.Dispute.retrieve(id)
        cache.set(id, dispute)
    else:
        dispute = cache.get(id)
    if "id" not in dispute or dispute.id != id:
        warn(f"Dispute ID mismatch: {dispute} != {id}")
        raise ValueError(f"Dispute ID mismatch: {dispute} != {id}")
    return dispute

class ProductRevenue:
    def __init__(self):
        self.prods = {}
        self.prod_revenue = defaultdict(float)

    def add(self, prod, amount):
        assert "id" in prod, prod
        assert "name" in prod, prod
        prod_id = prod["id"]
        if prod_id in self.prod_revenue:
            self.prod_revenue[prod_id] += amount
            assert self.prods[prod_id]["name"] == prod["name"], f'id={prod_id}: {self.prods[prod_id]["id"]} v.s. {prod["name"]}'
        else:
            self.prods[prod_id] = prod
            self.prod_revenue[prod_id] = amount

    def revenue(self):
        revenue = []
        for prod_id,rev in self.prod_revenue.items():
            prod = self.prods[prod_id]
            revenue.append((prod, rev))
        return revenue


def month_start_end(year, month):
    start_date = datetime(year, month, 1)
    import calendar
    _, last_day = calendar.monthrange(year, month)
    end_date = start_date + timedelta(days=last_day)
    end_date = end_date.replace(day=1)
    return start_date, end_date


def get_payouts(start_date, end_date):
    # 获取每个月银行到账记录
    print(f"getting payouts from {start_date} to {end_date}")
    payouts = stripe.Payout.list(
        created={
            'gte': int(start_date.timestamp()),
            'lt': int(end_date.timestamp())
        },
        limit=100
    )
    all_payouts = []
    while payouts.has_more:
        all_payouts.extend(payouts.data)
        payouts = stripe.Payout.list(
            created={
                'gte': int(start_date.timestamp()),
                'lt': int(end_date.timestamp())
            },
            limit=100,
            starting_after=payouts.data[-1].id
        )
    all_payouts.extend(payouts.data)

    return all_payouts


def get_transactions(payout_id):
    # 获取每一个 payouts 对应的所有交易记录
    transactions = stripe.BalanceTransaction.list(limit=100, payout=payout_id)
    all_transactions = []
    while transactions.has_more:
        all_transactions.extend(transactions.data)
        transactions = stripe.BalanceTransaction.list(
            limit=100, payout=payout_id,
            starting_after=transactions.data[-1].id
        )
    all_transactions.extend(transactions.data)

    return all_transactions


def main():
    parser = argparse.ArgumentParser(description='Calculate Stripe revenue for a specific month.')
    parser.add_argument('--year', type=int, default=datetime.now().year, help='Year of the invoices')
    parser.add_argument('--month', type=int, default=datetime.now().month, help='Month of the invoices')
    args = parser.parse_args()

    total_revenue = 0
    prod_revenue = ProductRevenue()

    start_date, end_date = month_start_end(args.year, args.month)
    payouts = get_payouts(start_date, end_date)

    print(f"{len(payouts)} total amount {sum([po.amount for po in payouts])/ 100:.2f} from {start_date} to {end_date}.")

    accumulated_nets = {po.id: 0 for po in payouts}

    transactions = []
    ts2po = {} # transaction to payout mapping
    for payout in payouts:
        ts = get_transactions(payout.id)
        transactions.extend(ts)
        assert sum([t.net for t in ts if t.type != 'payout']) == payout.amount, f"Total net of transactions {sum([t.net for t in ts if t.type != 'payout'])} does not match payout amount {payout.amount} for payout {payout.id}."
        for t in ts:
            ts2po[t.id] = payout

    for t in transactions:
        if t.type == 'payout':
            continue

        if t.reporting_category.startswith("payout_minimum_balance_"):
            # 这部分是 stripe 预扣的，如果账户余额不足100，扣留
            # 这部分总体加起来是 0
            prod_revenue.add({ "id": t.reporting_category, "name": t.reporting_category }, t.net)
        elif t.reporting_category == "fee":
            prod_revenue.add({ "id": t.reporting_category, "name": t.reporting_category }, t.net)

        elif t.reporting_category == "refund":
            assert t.source != None, t
            refund = get_refund(t.source)
            pi = get_pi(refund.payment_intent)
            assert pi.invoice != None, payment_intent
            invoice = get_invoice(pi.invoice)

            assert len(invoice.lines.data) == 1, invoice
            for line in invoice.lines.data:
                price = line.price
                product = get_product(price.product)
                assert len(product.id) > 0, product
                prod_revenue.add(product, t.net)

        elif t.reporting_category == "charge":
            assert t.source != None, t
            charge = get_charge(t.source)
            assert charge.payment_intent != None, charge
            pi = get_pi(charge.payment_intent)
            session = stripe.checkout.Session.list(payment_intent=pi["id"])
            # 通过 checkout session 支付的，直接获取产品信息
            # 适用于一次性支付
            if len(session.data) > 0:
                line_items = stripe.checkout.Session.list_line_items(session["data"][0]["id"])
                assert len(line_items.data) == 1
                for item in line_items.data:
                    product = get_product(item.price.product)
                    prod_revenue.add(product, t.net)
            # 如果有invoice，则通过 invoice 获取产品信息
            # 适用于订阅
            elif "invoice" in pi:
                invoice = get_invoice(pi.invoice)
                assert len(invoice.lines.data) == 1, invoice
                line = invoice.lines.data[0]
                product = get_product(line.price.product)
                prod_revenue.add(product, t.net)
            else:
                print(f"Couldn't get product from transaction:\n", t, "\n\ncharge:\n", charge, "\n\npayment intent:\n", pi)
                raise RuntimeError("Couldn't get product from transaction")
        elif t.reporting_category == "dispute":
            # 争议退款
            assert t.source != None, t
            dispute = get_dispute(t.source)
            charge = get_charge(dispute.charge)
            invoice = get_invoice(charge.invoice)
            assert len(invoice.lines.data) == 1, invoice
            line = invoice.lines.data[0]
            product = get_product(line.price.product)
            prod_revenue.add(product, t.net)
        else:
            print(f"Unknown transaction type \"{t.reporting_category}\":\n", t)
            raise RuntimeError(f"Unknown transaction type {t.reporting_category} for {t.id}.")

        po = ts2po[t.id]
        accumulated_nets[po.id] += t.net
        print(f"Payout {po.id}: transaction {t.id} type={t.reporting_category}, amount={t.amount}, fee={t.fee}, net={t.net}, accumulated_net={accumulated_nets[po.id]}/{po.amount}.")

    total_revenue = 0.0
    total_adjusted_revenue = 0.0
    total_adjusted_fee = 0.0

    # 计算 Billing - Usage Fee
    # 并按比例分摊到各个 product
    fee = 0
    for prod, rev in prod_revenue.revenue():
        if prod["name"].startswith("payout_minimum_balance_"):
            continue
        elif prod["name"] == "fee":
            fee = rev
        else:
            total_revenue += rev

    print(f"{len(payouts)} payouts with total amount {sum([po.amount for po in payouts]) / 100:.2f}. Total revenue before fee adjustment: {total_revenue/100:.2f}, total fee: {fee/100:.2f}.")

    table = PrettyTable([
        "Product",
        "Revenue ($)",
        "Adjusted Fee ($)",
        "Adjusted Revenue ($)",
        "Email",
        "Rate (%)",
        "Net Payout ($)"
    ])

    table.title = f"Stripe Revenue Report for {args.year}-{args.month:02d} (generated by https://github.com/batchfy/stripe-revenue-report)"

    for prod, rev in prod_revenue.revenue():
        adjusted_fee = 0
        adjusted_revenue = 0
        if prod["name"].startswith("payout_minimum_balance_"):
            continue
        if prod["name"] == "fee":
            pass
        else:
            adjusted_fee = fee * (rev / total_revenue)
            adjusted_revenue = (rev + adjusted_fee)
            # 总费后营收只算产品的
        total_adjusted_revenue += adjusted_revenue
        total_adjusted_fee += adjusted_fee

        email = prod.get("metadata", {}).get("email", "")
        rate_raw = prod.get("metadata", {}).get("rate")

        rate = None
        if rate_raw is not None:
            try:
                rate = float(rate_raw)
            except ValueError:
                rate = None

        if rate is not None:
            net_payout = adjusted_revenue * (1 - rate)
            rate_display = f"{rate * 100:.1f}"
        else:
            net_payout = adjusted_revenue
            rate_display = ""

        table.add_row([
            prod["name"],
            f"{rev/100:.2f}",
            f"{adjusted_fee / 100:.2f}",
            f"{adjusted_revenue / 100:.2f}",
            email,
            rate_display,
            f"{net_payout / 100:.2f}",
        ])

    table.add_row([
        "Total",
        f"{total_revenue / 100:.2f}",
        f"{total_adjusted_fee / 100:.2f}",
        f"{total_adjusted_revenue / 100:.2f}",
        "",
        "",
        ""
    ])
    print(table)

    with open(f"{args.year}-{args.month}.csv", "w", newline="", encoding="utf-8") as f:
        f.write(table.get_csv_string())

if __name__ == "__main__":
    main()
