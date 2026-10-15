"""Stop tracked legacy subscriptions when migrating a deployment to free.

Defaults to read-only inspection. Does not import app.py or initialize Firebase.
"""
import argparse
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import stripe

LEGACY_PRICES = {
    'price_1TLO7KPvnGX55ydCcJxWWRlb',
    'price_1TLO81PvnGX55ydCr2hBb63p',
    'price_1TLO8dPvnGX55ydClrsqTyea',
}


def retire_subscription(row, api, apply=False):
    sub = api.Subscription.retrieve(row['stripe_subscription_id'])
    if sub.get('customer') != row['stripe_customer_id']:
        raise ValueError('Customer does not match the stored account')
    metadata = sub.get('metadata') or {}
    if metadata.get('user_id') and metadata['user_id'] != str(row['id']):
        raise ValueError('Subscription metadata belongs to a different user')
    prices = {item.get('price', {}).get('id') for item in sub.get('items', {}).get('data', [])}
    if not prices or not prices.issubset(LEGACY_PRICES):
        raise ValueError('Subscription is not one of this service\'s legacy plans')
    if sub.get('status') in ('canceled', 'incomplete_expired'):
        return 'already_ended'
    if not apply:
        return 'would_cancel'
    canceled = api.Subscription.cancel(sub['id'], invoice_now=False, prorate=False)
    if canceled.get('status') != 'canceled':
        raise RuntimeError('Stripe did not confirm cancellation')
    return 'canceled'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, help='Optional explicit environment file')
    parser.add_argument('--apply', action='store_true', help='Cancel the verified contracts and update their DB records')
    args = parser.parse_args()
    if args.env_file:
        load_dotenv(args.env_file)
    database_url = os.environ.get('DATABASE_URL')
    stripe_key = os.environ.get('STRIPE_SECRET_KEY')
    if not database_url or not stripe_key:
        parser.error('DATABASE_URL and STRIPE_SECRET_KEY are required')
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    if database_url.startswith('postgresql://') and 'sslmode=' not in database_url:
        database_url += ('&' if '?' in database_url else '?') + 'sslmode=require'
    stripe.api_key = stripe_key
    engine = create_engine(database_url)
    failures = 0
    try:
        with engine.connect() as connection:
            rows = connection.execute(text('SELECT id, stripe_customer_id, stripe_subscription_id FROM users '
                'WHERE stripe_subscription_id IS NOT NULL')).mappings().all()
        print(f'{"APPLY" if args.apply else "READ ONLY"}: {len(rows)} tracked contracts')
        for row in rows:
            try:
                result = retire_subscription(row, stripe, apply=args.apply)
                if args.apply and result in ('canceled', 'already_ended'):
                    with engine.begin() as connection:
                        connection.execute(text("UPDATE users SET plan_type='free', subscription_status='canceled', "
                            "cancel_at_period_end=false, current_period_end=NULL WHERE id=:uid AND stripe_subscription_id=:sid"),
                            {'uid':row['id'], 'sid':row['stripe_subscription_id']})
                print(f'user {row["id"]}: {result}')
            except Exception:
                # Do not print API exceptions, which may include sensitive request data.
                failures += 1
                print(f'user {row["id"]}: failed; verify customer, subscription, price and credentials')
        print(f'Checked {len(rows)} contracts; failures={failures}. No refunds or final invoices were requested.')
    finally:
        engine.dispose()
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
