"""Manual count-only reconciliation. Never imports bot or loads .env.

Operator usage: python reconcile_stars.py DATABASE --offset 0 --limit 100
Requires BOT_TOKEN in the runtime environment. Checks one page, not all history.
Matching/missing counts cover unique incoming user invoice-payment IDs only;
the checked count includes all transactions returned on that page.
This tool never repairs records or issues refunds. Investigate missing IDs manually.
"""

import argparse
import asyncio
import logging
import os
import sys

from telegram import Bot, TransactionPartnerUser

from db import get_payment_charge_ids


async def reconcile(database, token, *, offset=0, limit=100):
    local_ids = get_payment_charge_ids(database)
    async with Bot(token=token) as bot:
        page = await bot.get_star_transactions(offset=offset, limit=limit)
    incoming_ids = {
        transaction.id for transaction in page.transactions
        if isinstance(transaction.source, TransactionPartnerUser)
        and transaction.source.transaction_type == 'invoice_payment'
        and transaction.receiver is None
    }
    return (len(page.transactions), len(incoming_ids & local_ids),
            len(incoming_ids - local_ids))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', help='Explicit path to an existing payments database')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--limit', type=int, default=100)
    args = parser.parse_args(argv)
    if args.offset < 0 or not 1 <= args.limit <= 100:
        parser.error('offset must be nonnegative and limit must be between 1 and 100')
    token = os.environ.get('BOT_TOKEN', '').strip()
    if not token:
        print('Reconciliation failed: BOT_TOKEN is not configured.', file=sys.stderr)
        return 1
    # HTTP/client debug logs can contain the token or transaction response body.
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        counts = asyncio.run(reconcile(args.database, token, offset=args.offset, limit=args.limit))
    except Exception:
        print('Reconciliation failed: check API access and database availability/schema. '
              'No records were modified.', file=sys.stderr)
        return 1
    finally:
        logging.disable(previous_logging)
    print(f'Telegram transactions checked: {counts[0]}')
    print(f'Matching local charge IDs: {counts[1]}')
    print(f'Telegram charge IDs missing locally: {counts[2]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
