# Stripe Revenue Report (Payout-Based)

A payout-centric revenue accounting tool for **Stripe** that calculates **actual realized revenue per product** for a given month, using **bank payouts as the single source of truth**.

This script answers the question:

> **How much money did each product actually pay out to my bank account in a given month?**

Unlike invoice-based or charge-based reports, this tool reconstructs revenue **strictly from Stripe payouts**, after accounting for **refunds, disputes, and Stripe fees**, making it suitable for reconciliation and audit-style reporting.

---

## Features

- Monthly reporting (`--year`, `--month`)
- **Payout-based** (cash-settlement) revenue calculation
- Correct handling of:
  - charges
  - refunds
  - disputes
  - Stripe processing fees
  - payout minimum balance withholding
- Product attribution for:
  - One-time payments (Checkout Sessions)
  - Subscriptions (Invoices)
- Proportional fee allocation across products
- CLI table output via PrettyTable
- **API-level cache** to reduce Stripe API calls

---

## Why payout-based?

Stripe objects such as Charge, Invoice, or PaymentIntent do **not** represent actual cash flow:

- Charges may be refunded or disputed
- Invoices may never be settled
- Balance transactions are only final once included in a payout

This script treats **Stripe payouts** (money transferred to your bank account) as the single source of truth.

---

## API-level cache

The script includes an **API-level cache** (`StripeKVCache`) that memoizes Stripe objects by ID during execution.

Cached objects include:

- Product  
- Invoice  
- PaymentIntent  
- Charge  
- Refund  
- Dispute  

Benefits:

- Fewer Stripe API requests
- Faster execution on large accounts
- Reduced rate-limit risk
- Stable object resolution across nested relationships

> This cache does **not** change financial logic — it only avoids repeated API calls.

---

## How it works (high level)

1. List payouts in `[start, end)` for the selected month.
2. For each payout, list balance transactions and verify summed net amounts.
3. For each transaction (excluding payout type):
   - charge: Checkout Session line items or Invoice lines → Product
   - refund: Refund → PaymentIntent → Invoice → Product
   - dispute: Dispute → Charge → Invoice → Product
   - fee / payout minimum balance: recorded as special categories
4. Aggregate per-product revenue using transaction net amounts.
5. Allocate total Stripe fees proportionally across products.
6. Print a summary table.

---

## How to use

1. install dependencies: `pip install -r requirements.txt`

2. Set your Stripe secret key: `export STRIPE_SECRET_KEY=sk_live_xxx`

3. Generate report: `python stripe_income_report.py --year 2024 --month 6`

## Notes and assumptions

- Assumes **one line item per invoice or checkout session**
- Intended for monthly reconciliation, not real-time dashboards
- Prioritizes correctness and auditability over performance

---

## License

MIT
