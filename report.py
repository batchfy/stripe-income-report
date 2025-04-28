import os, sys
import stripe
from collections import defaultdict
from datetime import datetime, timedelta
import argparse
from prettytable import PrettyTable


# Set up Stripe API key
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')


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

    # 商品营收
    total_revenue = 0
    prod_revenue = ProductRevenue()

    start_date, end_date = month_start_end(args.year, args.month)

    # 获取银行到账记录
    payouts = get_payouts(start_date, end_date)

    for payout in payouts:
        payout_total = 0

        transactions = get_transactions(payout.id)
        for t in transactions:

            if t.type == 'payout':
                continue

            if t.type == "refund":
                # 退款
                assert t.source != None, t
                refund = stripe.Refund.retrieve(t.source)
                payment_intent = stripe.PaymentIntent.retrieve(refund.payment_intent)
                assert payment_intent.invoice != None, payment_intent
                invoice = stripe.Invoice.retrieve(payment_intent.invoice)

                assert len(invoice.lines.data) == 1, invoice
                for line in invoice.lines.data:
                    price = line.price
                    product = stripe.Product.retrieve(price.product)
                    assert len(product.id) > 0, product
                    prod_revenue.add(product, t.net)


            elif t.type == "payment_refund":
                # 退款，这两个退款我没搞懂有什么区别
                assert t.source != None, t
                refund = stripe.Refund.retrieve(t.source)
                payment_intent = stripe.PaymentIntent.retrieve(refund.payment_intent)
                assert payment_intent.invoice != None, payment_intent
                invoice = stripe.Invoice.retrieve(payment_intent.invoice)

                for line in invoice.lines.data:
                    price = line.price
                    product = stripe.Product.retrieve(price.product)
                    assert len(product.id) > 0, product
                    prod_revenue.add(product, t.net)

            elif t.type == "charge" or t.type == "payment":
                # 这是主要：收款
                assert t.source != None, t

                # how can I get the associated items/products?
                try:
                    charge = stripe.Charge.retrieve(t.source)
                except:
                    print("Error retrieving charge")
                    print(t)
                    sys.exit(1)
                assert charge.payment_intent != None, charge  

                payment_intent = stripe.PaymentIntent.retrieve(charge.payment_intent)

                session = stripe.checkout.Session.list(payment_intent=payment_intent["id"])
                if len(session.data) > 0:
                    # print(f"Found session data with type={t.type}")
                    line_items = stripe.checkout.Session.list_line_items(session["data"][0]["id"])
                    assert len(line_items.data) == 1
                    for item in line_items.data:
                        product = stripe.Product.retrieve(item.price.product)
                        prod_revenue.add(product, t.net)
                else:
                    invoice = stripe.Invoice.retrieve(payment_intent.invoice)
                    assert len(invoice.lines.data) == 1, invoice
                    # print(f"Found invoice data with type={t.type}")
                    line = invoice.lines.data[0]
                    product = stripe.Product.retrieve(line.price.product)
                    prod_revenue.add(product, t.net)

            elif t.type.startswith("payout_minimum_balance"):
                # 这部分是 stripe 预扣的，如果账户余额不足100，扣留
                # 这部分总体加起来是 0
                prod_revenue.add({ "id": t.type, "name": t.type }, t.net)
            elif t.type == "stripe_fee":
                prod_revenue.add({ "id": t.type, "name": t.type }, t.net)
            else:
                print("Unknown transaction type")
                print("payout", payout)
                print("transaction:", t)
                sys.exit(1)
            payout_total += t.amount - t.fee

            subtotal = sum([r[-1] for r in prod_revenue.revenue()])
            print(f"Payout {payout.id}: payout.amount={payout.amount}, payout_total={payout_total}, total={subtotal}")

        total_revenue += payout_total

        if total_revenue != subtotal:
            print(f"Error: payout_total != subtotal: {total_revenue}!= {subtotal}")
            print(f"Payout {payout.id}: payout.amount={payout.amount}, total={payout_total}, subtotal={subtotal}")
            print(t)
            sys.exit(1)

    table = PrettyTable(["Product name", "Product ID", "Revenue", "Email", "Rate (%)"])
    total_revenue = 0
    for prod, rev in prod_revenue.revenue():
        total_revenue += rev / 100
        email = ""
        rate = ""
        try:
            email = prod["metadata"]["email"]
            rate = prod["metadata"]["rate"]
            rate = f"{float(rate)*100:.1f}"
        except Exception as e:
            pass
        table.add_row([prod["name"], prod["id"], rev/100, email, rate])
    table.add_row(["Total", "-", f"{total_revenue:.2f}", "", ""])
    print(table)


if __name__ == "__main__":
    main()
