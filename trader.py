"""
Automated trading engine — Day trading with profit target.
Scans broad market in parallel, catches momentum, stops when daily target hit.
"""
import os, time, logging, json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytz
import pandas as pd
from dotenv import load_dotenv

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from strategies import get_signal_detail
from ai_brain import get_current_watchlist, get_dashboard_data

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('trader')

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY    = os.getenv('ALPACA_API_KEY')
SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
PAPER      = os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets').startswith('https://paper')

MAX_POS             = float(os.getenv('MAX_POSITION_SIZE', 10000))
MAX_DAILY_LOSS      = float(os.getenv('MAX_DAILY_LOSS', 2000))
MAX_OPEN            = int(os.getenv('MAX_OPEN_POSITIONS', 10))
DAILY_PROFIT_TARGET = float(os.getenv('DAILY_PROFIT_TARGET', 500))
STOP_LOSS_PCT       = float(os.getenv('STOP_LOSS_PCT', 1.2))
TRAILING_STOP_PCT   = float(os.getenv('TRAILING_STOP_PCT', 0.5))
TAKE_PROFIT_PCT     = float(os.getenv('TAKE_PROFIT_PCT', 2.5))
TRADE_LOG_FILE      = os.getenv('TRADE_LOG_FILE', 'trade_log.jsonl')

WATCHLIST = [
    'AAPL','MSFT','NVDA','TSLA','META','GOOGL','AMZN','AMD',
    'SPY','QQQ','IWM','ARKK','SMH',
    'JPM','BAC','GS',
    'XOM','CVX',
    'UNH','LLY',
    'PLTR','CRWD','COIN','MSTR','SHOP','NET','PANW',
    'V','MA',
    'LMT','RTX',
    'GLD','GDX',
    'DAL','UAL',
]

# ── Clients ───────────────────────────────────────────────────────────────────
_trading_client = None
_data_client    = None

trade_log    = []
entry_prices: dict = {}
buy_times:    dict = {}
active_orders: set = set()

status = {
    'running': False, 'mode': 'PAPER' if PAPER else 'LIVE',
    'last_run': None, 'error': None,
    'target_hit': False, 'daily_pnl_peak': 0,
    'last_known_pnl': 0.0,
}


def get_trading_client() -> TradingClient:
    global _trading_client
    if _trading_client is None:
        _trading_client = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)
    return _trading_client


def get_data_client() -> StockHistoricalDataClient:
    global _data_client
    if _data_client is None:
        _data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    return _data_client


def get_macro_briefing():
    return get_dashboard_data()


def get_dynamic_watchlist():
    return get_current_watchlist() or WATCHLIST


def is_market_open() -> bool:
    try:
        return get_trading_client().get_clock().is_open
    except Exception as e:
        log.warning(f"Clock check failed: {e}")
        return False


def get_bars(symbol: str, timeframe='1Min', limit=100) -> pd.DataFrame:
    tf_map = {
        '1Min':  TimeFrame(1,  TimeFrameUnit.Minute),
        '3Min':  TimeFrame(3,  TimeFrameUnit.Minute),
        '5Min':  TimeFrame(5,  TimeFrameUnit.Minute),
        '15Min': TimeFrame(15, TimeFrameUnit.Minute),
        '1Hour': TimeFrame(1,  TimeFrameUnit.Hour),
        '1Day':  TimeFrame(1,  TimeFrameUnit.Day),
    }
    tf = tf_map.get(timeframe, TimeFrame(1, TimeFrameUnit.Minute))

    for attempt, delay in enumerate([0, 1, 2, 4]):
        try:
            if delay:
                time.sleep(delay)
            now   = datetime.now(pytz.UTC)
            start = now - timedelta(days=5)
            req = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=start,
                end=now,
                limit=limit,
                feed='iex',
            )
            bars = get_data_client().get_stock_bars(req).df
            if bars.empty:
                return pd.DataFrame()
            if isinstance(bars.index, pd.MultiIndex):
                bars = bars.droplevel(0)
            bars.index.name = 'timestamp'
            return bars[['open', 'high', 'low', 'close', 'volume']]
        except Exception as e:
            if attempt == 3:
                log.warning(f"Bars failed for {symbol}: {e}")
                return pd.DataFrame()
            if '429' in str(e) or '503' in str(e):
                log.warning(f"Bars {symbol} attempt {attempt+1} — retrying in {delay}s")
            else:
                return pd.DataFrame()
    return pd.DataFrame()


def get_bars_multi(symbol: str) -> dict:
    bars_1m = get_bars(symbol, '1Min', limit=100)
    time.sleep(0.15)
    bars_3m = get_bars(symbol, '3Min', limit=60)
    time.sleep(0.15)
    bars_5m = get_bars(symbol, '5Min', limit=50)
    return {'1m': bars_1m, '3m': bars_3m, '5m': bars_5m}


def get_positions() -> dict:
    try:
        return {p.symbol: p for p in get_trading_client().get_all_positions()}
    except Exception as e:
        log.warning(f"get_positions failed: {e}")
        return {}


def get_account():
    for attempt, delay in enumerate([0, 1, 2]):
        try:
            if delay:
                time.sleep(delay)
            return get_trading_client().get_account()
        except Exception as e:
            if attempt == 2:
                log.warning(f"get_account failed: {e}")
                return None
            if '429' in str(e) or '503' in str(e):
                log.warning(f"get_account attempt {attempt+1} — retrying")
            else:
                return None
    return None


def daily_pnl() -> float:
    acct = get_account()
    try:
        if acct:
            pnl = float(acct.equity) - float(acct.last_equity)
            status['last_known_pnl'] = pnl
            return pnl
    except Exception as e:
        log.warning(f"daily_pnl failed: {e} — using cached ${status['last_known_pnl']:.2f}")
    return status['last_known_pnl']


def _persist_trade(entry: dict):
    try:
        with open(TRADE_LOG_FILE, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception as e:
        log.warning(f"Failed to persist trade: {e}")


def place_order(symbol: str, side: str, qty: int, price: float = 0.0):
    try:
        order_side = OrderSide.BUY if side == 'buy' else OrderSide.SELL
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.DAY,
        )
        get_trading_client().submit_order(req)
        log.info(f"{side.upper()} {qty}x {symbol} @ ~${price:.2f}")

        entry = {
            'time':   datetime.now().strftime('%H:%M:%S'),
            'date':   datetime.now().strftime('%Y-%m-%d'),
            'symbol': symbol,
            'action': side.upper(),
            'qty':    qty,
            'price':  round(price, 2),
            'status': 'submitted',
            'pnl':    None,
        }

        if side == 'sell' and symbol in entry_prices:
            cost_basis = entry_prices.pop(symbol)
            buy_times.pop(symbol, None)
            realised = (price - cost_basis) * qty
            entry['pnl'] = round(realised, 2)
            log.info(f"Realised PnL {symbol}: ${realised:+.2f}")
        elif side == 'buy':
            entry_prices[symbol] = price
            buy_times[symbol] = datetime.now()

        trade_log.append(entry)
        _persist_trade(entry)

    except Exception as e:
        log.error(f"Order failed {side} {symbol}: {e}")
        entry = {
            'time': datetime.now().strftime('%H:%M:%S'),
            'date': datetime.now().strftime('%Y-%m-%d'),
            'symbol': symbol, 'action': side.upper(),
            'qty': qty, 'price': round(price, 2),
            'status': f'FAILED: {e}', 'pnl': None,
        }
        trade_log.append(entry)
        _persist_trade(entry)


def _fetch_signal(symbol: str) -> dict | None:
    try:
        tf_bars  = get_bars_multi(symbol)
        bars_1m  = tf_bars['1m']
        bars_3m  = tf_bars['3m']
        bars_5m  = tf_bars['5m']
        bars_htf = get_bars(symbol, '1Hour', limit=60)

        if bars_1m.empty:
            return None

        d = get_signal_detail(bars_5m if not bars_5m.empty else bars_1m)
        d['symbol'] = symbol
        d['price']  = float(bars_1m['close'].iloc[-1])

        from strategies import combined_signal, slc_signal
        sig_1m = d['signal']
        sig_3m = combined_signal(bars_3m) if not bars_3m.empty else 'HOLD'
        sig_5m = combined_signal(bars_5m) if not bars_5m.empty else 'HOLD'
        sig_slc = slc_signal(bars_5m, bars_htf)

        tf_signals = [sig_1m, sig_3m, sig_5m]
        buy_count  = tf_signals.count('BUY')
        sell_count = tf_signals.count('SELL')

        if buy_count >= 2:
            d['signal'] = 'BUY'
            d['score']  = d.get('score', 0) + buy_count
        elif sell_count >= 2:
            d['signal'] = 'SELL'
            d['score']  = d.get('score', 0) - sell_count
        elif buy_count == 1 and sig_1m == 'BUY':
            d['signal'] = 'BUY'
        elif sell_count == 1 and sig_1m == 'SELL':
            d['signal'] = 'SELL'

        if sig_slc == 'BUY':
            d['score'] = d.get('score', 0) + 3
            if d['signal'] != 'SELL':
                d['signal'] = 'BUY'
        elif sig_slc == 'SELL':
            d['score'] = d.get('score', 0) - 3
            if d['signal'] != 'BUY':
                d['signal'] = 'SELL'

        d['tf_1m']  = sig_1m
        d['tf_3m']  = sig_3m
        d['tf_5m']  = sig_5m
        d['tf_slc'] = sig_slc
        return d
    except Exception as e:
        log.warning(f"Signal error {symbol}: {e}")
        return None


def run_cycle():
    status['last_run'] = datetime.now().strftime('%H:%M:%S')

    if not is_market_open():
        log.info("Market closed — skipping cycle")
        return

    pnl = daily_pnl()

    if pnl > status['daily_pnl_peak']:
        status['daily_pnl_peak'] = pnl

    if pnl >= DAILY_PROFIT_TARGET:
        if not status['target_hit']:
            log.info(f"Target hit! P&L: ${pnl:.2f} — closing all")
            status['target_hit'] = True
            close_all_positions()
            status['error'] = f"Target hit! Locked in ${pnl:.2f} profit for today."
        return

    peak = status['daily_pnl_peak']
    if peak >= DAILY_PROFIT_TARGET * 0.85 and pnl < peak * 0.80:
        if not status['target_hit']:
            log.warning(f"Trailing stop: peak ${peak:.2f} → now ${pnl:.2f}")
            status['target_hit'] = True
            close_all_positions()
            status['error'] = f"Trailing stop. Peak: ${peak:.2f}, Now: ${pnl:.2f}"
        return

    if pnl < -MAX_DAILY_LOSS:
        log.warning(f"Loss limit hit (${pnl:.2f})")
        close_all_positions()
        status['error'] = f"Loss limit hit: ${pnl:.2f}"
        return

    now_ny = datetime.now(pytz.timezone('America/New_York'))
    if now_ny.hour == 15 and now_ny.minute >= 45:
        log.info("15 mins to close — selling all")
        close_all_positions()
        return

    positions    = get_positions()
    acct         = get_account()
    if not acct:
        return
    buying_power = float(acct.buying_power)

    # Stop-loss + Take-profit sweep
    for sym, p in list(positions.items()):
        try:
            plpc  = float(p.unrealized_plpc) * 100
            qty   = int(float(p.qty))
            price = float(p.current_price)
            if qty <= 0:
                continue

            cost = float(p.avg_entry_price) * qty
            if cost >= MAX_POS * 0.9:
                tp = TAKE_PROFIT_PCT * 1.4
            elif cost >= MAX_POS * 0.65:
                tp = TAKE_PROFIT_PCT * 1.2
            else:
                tp = TAKE_PROFIT_PCT

            if plpc >= tp:
                log.info(f"Take-profit: {sym} at +{plpc:.2f}%")
                place_order(sym, 'sell', qty, price)
                del positions[sym]
            elif plpc <= -STOP_LOSS_PCT:
                log.warning(f"Stop-loss: {sym} at {plpc:.2f}%")
                place_order(sym, 'sell', qty, price)
                del positions[sym]
        except Exception as e:
            log.warning(f"Stop-loss check failed {sym}: {e}")

    # Parallel signal scan
    watchlist = get_current_watchlist() or WATCHLIST
    signals   = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch_signal, sym): sym for sym in watchlist}
        for future in as_completed(futures):
            result = future.result()
            if result:
                signals.append(result)

    buy_candidates  = sorted([s for s in signals if s['signal'] == 'BUY'],
                              key=lambda x: x['score'], reverse=True)
    sell_candidates = [s for s in signals if s['signal'] == 'SELL']

    # Sell signals
    MIN_HOLD_SECONDS = 600
    for s in sell_candidates:
        sym = s['symbol']
        if sym in positions:
            bought_at = buy_times.get(sym)
            if bought_at:
                held_secs = (datetime.now() - bought_at.replace(tzinfo=None)).total_seconds()
                if held_secs < MIN_HOLD_SECONDS:
                    log.info(f"Hold time: skipping sell {sym} — only held {held_secs:.0f}s")
                    continue
            qty   = int(float(positions[sym].qty))
            price = s['price']
            if qty > 0:
                place_order(sym, 'sell', qty, price)

    # Skip buys on bearish AI sentiment
    try:
        briefing  = get_dashboard_data()
        sentiment = briefing.get('sentiment', 'neutral')
        if sentiment == 'bearish':
            log.info("AI sentiment bearish — skipping buy signals")
            buy_candidates = []
        else:
            log.info(f"AI sentiment: {sentiment} — buys allowed")
    except:
        pass

    # Buy signals with confidence-based sizing
    pending_buys: set = set()
    for s in buy_candidates:
        sym       = s['symbol']
        price     = s['price']
        score     = s.get('score', 3)
        slc_fired = s.get('tf_slc') == 'BUY'

        if sym in positions or sym in pending_buys:
            continue
        if len(positions) + len(pending_buys) >= MAX_OPEN:
            break
        if buying_power < MAX_POS * 0.25:
            break
        if score < 5:
            log.info(f"Skipping {sym} — score {score} too low (need 5+)")
            continue

        if score >= 9 and slc_fired:
            size_ratio, tier = 1.0, 'MAX'
        elif score >= 7:
            size_ratio, tier = 0.75, 'HIGH'
        elif score >= 5:
            size_ratio, tier = 0.50, 'MED'
        else:
            size_ratio, tier = 0.25, 'LOW'

        pos_size = MAX_POS * size_ratio
        if buying_power < pos_size:
            continue

        qty = max(1, int(pos_size / price))
        log.info(f"BUY {sym} — tier={tier} score={score} slc={slc_fired} size=${pos_size:.0f} qty={qty}")
        place_order(sym, 'buy', qty, price)
        buying_power -= qty * price
        pending_buys.add(sym)

    status['error'] = None


def close_all_positions():
    for sym, p in get_positions().items():
        try:
            qty   = int(float(p.qty))
            price = float(p.current_price)
            if qty > 0:
                place_order(sym, 'sell', qty, price)
        except Exception as e:
            log.error(f"Close error {sym}: {e}")


def start_bot():
    status['running']    = True
    status['target_hit'] = False
    log.info("Bot started")
    while status['running']:
        try:
            run_cycle()
        except Exception as e:
            log.error(f"Bot error: {e}")
            status['error'] = str(e)
        time.sleep(60)


def stop_bot():
    status['running'] = False
    log.info("Bot stopped")
