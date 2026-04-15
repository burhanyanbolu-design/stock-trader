from dotenv import load_dotenv
load_dotenv()
import trader
from datetime import datetime
import pytz

api = trader.get_api()

# Account
acct = api.get_account()
equity    = float(acct.equity)
cash      = float(acct.cash)
pnl       = equity - float(acct.last_equity)
buying_pw = float(acct.buying_power)

print("=" * 50)
print("  ACCOUNT SUMMARY")
print("=" * 50)
print(f"  Portfolio Value : ${equity:,.2f}")
print(f"  Cash            : ${cash:,.2f}")
print(f"  Today P&L       : ${pnl:+,.2f}")
print(f"  Buying Power    : ${buying_pw:,.2f}")

# Positions
positions = api.list_positions()
print(f"\n{'='*50}")
print(f"  OPEN POSITIONS ({len(positions)})")
print(f"{'='*50}")
if positions:
    for p in positions:
        entry   = float(p.avg_entry_price)
        current = float(p.current_price)
        pl      = float(p.unrealized_pl)
        plpct   = float(p.unrealized_plpc) * 100
        arrow   = "▲" if pl >= 0 else "▼"
        print(f"  {p.symbol:6} | Qty:{p.qty:4} | Entry:${entry:.2f} | Now:${current:.2f} | {arrow} ${pl:+.2f} ({plpct:+.2f}%)")
else:
    print("  No open positions")

# Today's orders
today = datetime.now(pytz.UTC).strftime('%Y-%m-%d')
orders = api.list_orders(status='all', after=today + 'T00:00:00Z', limit=100)
print(f"\n{'='*50}")
print(f"  TODAY'S TRADES ({len(orders)})")
print(f"{'='*50}")
if orders:
    buys  = [o for o in orders if o.side == 'buy'  and o.status == 'filled']
    sells = [o for o in orders if o.side == 'sell' and o.status == 'filled']
    print(f"  Filled BUYs : {len(buys)}")
    print(f"  Filled SELLs: {len(sells)}")
    print()
    for o in sorted(orders, key=lambda x: x.submitted_at):
        t = o.submitted_at.strftime('%H:%M:%S')
        filled = f"filled @ ${float(o.filled_avg_price):.2f}" if o.filled_avg_price else o.status
        print(f"  {t} | {o.side.upper():4} | {o.symbol:6} | Qty:{o.qty:3} | {filled}")
else:
    print("  No orders today")
