"""
Hardin Trading Watchdog — Stock Trader (stock-trader-render)
Monitors the Railway-deployed stock trader app.
Watches for: crashes, trade errors, P&L thresholds, stale activity, wash trades.
"""
import os
import time
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger('watchdog')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# ── Config ────────────────────────────────────────────────────────────────────
APP_URL          = os.getenv('WATCHDOG_APP_URL', 'https://just-quietude-production-f0d1.up.railway.app')
API_KEY          = os.getenv('ALPACA_API_KEY')
SECRET_KEY       = os.getenv('ALPACA_SECRET_KEY')
PAPER            = os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets').startswith('https://paper')
MAX_DAILY_LOSS   = float(os.getenv('MAX_DAILY_LOSS', -500))
CHECK_INTERVAL   = int(os.getenv('CHECK_INTERVAL_SECS', 60))
STALE_THRESHOLD  = int(os.getenv('STALE_THRESHOLD_MINS', 10))

# ── Alpaca client ─────────────────────────────────────────────────────────────
_trading_client = None

def get_trading_client():
    global _trading_client
    if _trading_client is None:
        from alpaca.trading.client import TradingClient
        _trading_client = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)
    return _trading_client


# ── App health ────────────────────────────────────────────────────────────────
def check_app_health() -> dict | None:
    try:
        r = requests.get(f'{APP_URL}/api/status', timeout=10)
        if r.status_code != 200:
            log.error(f'❌ App returned HTTP {r.status_code}')
            return None
        log.info('✅ App is reachable')
        return r.json()
    except Exception as e:
        log.error(f'❌ App unreachable: {e}')
        return None


# ── P&L monitor ───────────────────────────────────────────────────────────────
_alert_triggered = False

def check_pnl(status: dict) -> float | None:
    global _alert_triggered

    # Use P&L from app status first (avoids extra Alpaca call)
    pnl    = status.get('daily_pnl', 0)
    equity = status.get('equity', 0)
    cash   = status.get('cash', 0)
    icon   = '📈' if pnl >= 0 else '📉'
    log.info(f'{icon} Equity: ${equity:,.2f} | Daily P&L: ${pnl:+,.2f} | Cash: ${cash:,.2f}')

    if pnl <= MAX_DAILY_LOSS and not _alert_triggered:
        log.error(f'🚨 MAX LOSS ALERT! Daily P&L ${pnl:+,.2f} hit threshold ${MAX_DAILY_LOSS:,.2f}')
        _alert_triggered = True

    if pnl > MAX_DAILY_LOSS * 0.8:
        _alert_triggered = False

    return pnl


# ── Position monitor ──────────────────────────────────────────────────────────
def check_positions(status: dict):
    positions = status.get('positions', [])
    if not positions:
        log.info('ℹ️  No open positions')
        return

    for p in positions:
        sym    = p.get('symbol', '?')
        pnl    = p.get('pnl', 0)
        pnl_pct = p.get('pnl_pct', 0)
        entry  = p.get('entry', 0)
        curr   = p.get('current', 0)
        icon   = '📈' if pnl >= 0 else '📉'
        log.info(f'{icon} Position: {sym} | Entry: ${entry:.2f} | '
                 f'Current: ${curr:.2f} | P&L: ${pnl:+.2f} ({pnl_pct:+.2f}%)')


# ── Trade log monitor ─────────────────────────────────────────────────────────
_seen_trades = set()

def check_trades(status: dict):
    trades = status.get('trades', [])
    for t in trades:
        key = f"{t.get('date')}_{t.get('time')}_{t.get('symbol')}_{t.get('action')}"
        if key in _seen_trades:
            continue
        _seen_trades.add(key)

        action = t.get('action', '?')
        sym    = t.get('symbol', '?')
        qty    = t.get('qty', 0)
        price  = t.get('price', 0)
        pnl    = t.get('pnl')
        status_str = t.get('status', '')

        if 'FAILED' in str(status_str).upper():
            log.error(f'❌ FAILED ORDER: {action} {qty}x {sym} @ ${price:.2f} — {status_str}')
        elif action == 'SELL' and pnl is not None:
            icon = '✅' if pnl >= 0 else '❌'
            log.info(f'{icon} Trade closed: {sym} | P&L: ${pnl:+.2f}')
        else:
            log.info(f'📋 Trade: {action} {qty}x {sym} @ ${price:.2f}')


# ── Daily summary ─────────────────────────────────────────────────────────────
def check_daily_summary():
    try:
        r = requests.get(f'{APP_URL}/api/daily-summary', timeout=10)
        d = r.json()
        if d.get('error'):
            return
        log.info(f'📊 Daily Summary: {d["total_trades"]} trades | '
                 f'P&L: ${d["total_pnl"]:+.2f} | '
                 f'Win rate: {d["win_rate"]}% | '
                 f'{d["wins"]}W / {d["losses"]}L')
    except Exception as e:
        log.warning(f'⚠️  Daily summary fetch failed: {e}')


# ── Stale check ───────────────────────────────────────────────────────────────
_last_activity = datetime.now()
_last_run_time = None

def check_stale(status: dict):
    global _last_activity, _last_run_time

    last_run = status.get('last_run')
    running  = status.get('running', False)

    if not running:
        log.info('ℹ️  Bot not running (outside market hours or stopped)')
        return

    if last_run and last_run != _last_run_time:
        _last_run_time = last_run
        _last_activity = datetime.now()

    silence_mins = (datetime.now() - _last_activity).total_seconds() / 60
    if silence_mins > STALE_THRESHOLD:
        log.warning(f'⚠️  Bot has been silent for {silence_mins:.0f} mins — may be stuck!')

    error = status.get('error')
    if error:
        log.warning(f'⚠️  App error: {error}')


# ── Summary ───────────────────────────────────────────────────────────────────
def print_summary(status: dict):
    running     = status.get('running', False)
    mode        = status.get('mode', '?')
    target_hit  = status.get('target_hit', False)
    log.info('─' * 50)
    log.info(f'  Status  : {"🟢 RUNNING" if running else "🔴 STOPPED"} ({mode})')
    log.info(f'  Target  : {"✅ HIT" if target_hit else "❌ Not yet"}')
    log.info('─' * 50)


# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    log.info('=' * 55)
    log.info('  🐕 HARDIN WATCHDOG — STOCK TRADER')
    log.info(f'  Monitoring : {APP_URL}')
    log.info(f'  Interval   : {CHECK_INTERVAL}s')
    log.info(f'  Max loss   : ${MAX_DAILY_LOSS:,.2f}')
    log.info('=' * 55)

    check_count = 0
    while True:
        check_count += 1
        log.info(f'── Check #{check_count} @ {datetime.now().strftime("%H:%M:%S")} ──')

        status = check_app_health()
        if status is None:
            log.error('🚨 App is DOWN!')
            time.sleep(CHECK_INTERVAL)
            continue

        check_stale(status)
        check_pnl(status)
        check_positions(status)
        check_trades(status)
        check_daily_summary()
        print_summary(status)

        time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    main()
