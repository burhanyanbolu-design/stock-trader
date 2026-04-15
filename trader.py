"""
Automated trading engine — Day trading with profit target.
Scans broad market in parallel, catches momentum, stops when daily target hit.
"""
import os, time, logging, json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytz
import pandas as pd
import alpaca_trade_api as tradeapi
from dotenv import load_dotenv
from strategies import get_signal_detail
from ai_brain import get_current_watchlist, get_dashboard_data

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('trader')

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY    = os.getenv('ALPACA_API_KEY')
SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
BASE_URL   = os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
if BASE_URL and not BASE_URL.startswith('http'):
    BASE_URL = 'https://' + BASE_URL.lstrip('/')

MAX_POS             = float(os.getenv('MAX_POSITION_SIZE', 10000))
MAX_DAILY_LOSS      = float(os.getenv('MAX_DAILY_LOSS', 2000))
MAX_OPEN            = int(os.getenv('MAX_OPEN_POSITIONS', 10))
DAILY_PROFIT_TARGET = float(os.getenv('DAILY_PROFIT_TARGET', 25))
STOP_LOSS_PCT       = float(os.getenv('STOP_LOSS_PCT', 1.2))
TRAILING_STOP_PCT   = float(os.getenv('TRAILING_STOP_PCT', 0.5))
TAKE_PROFIT_PCT     = float(os.getenv('TAKE_PROFIT_PCT', 2.5))  # exit at +2.5% per trade — 2:1 R:R
TRADE_LOG_FILE      = os.getenv('TRADE_LOG_FILE', 'trade_log.jsonl')

# Broad watchlist — fallback when AI is unavailable
WATCHLIST = [
    # Mega-cap tech
    'AAPL','MSFT','GOOGL','AMZN','NVDA','META','AMD','TSLA','INTC','CRM',
    'ORCL','IBM','HPQ','DELL','ACN','ADBE','NOW','INTU','WDAY','TEAM',
    'CSCO','AMAT','MU','TXN','AVGO','QCOM','KLAC','LRCX','MRVL','MCHP',
    # Broad ETFs
    'SPY','QQQ','IWM','DIA','XLK','XLF','XLE','XLV','XLY','XLI',
    'XLP','XLU','XLB','ARKK','SMH','SOXX','VXX','TQQQ','SQQQ','UVXY',
    'TLT','GLD','SLV','USO','UNG','JETS','XBI','IBB','KWEB','EEM',
    # Finance & Banks
    'JPM','BAC','GS','MS','WFC','C','BLK','SCHW','AXP','COF','USB','PNC',
    'SPGI','MCO','ICE','CME','CBOE','NDAQ','BX','KKR','APO','ARES',
    # Energy & Oil
    'XOM','CVX','COP','SLB','HAL','OXY','MPC','VLO','PSX','DVN',
    'EOG','PXD','FANG','HES','MRO','APA','NOV','BKR','CTRA','SM',
    # Healthcare & Pharma
    'JNJ','UNH','PFE','ABBV','MRK','LLY','TMO','DHR','ISRG','REGN',
    'VRTX','MRNA','BMY','CVS','CI','HUM','ELV','MDT','SYK','BSX',
    'ZBH','BAX','BDX','IQV','CRL','DXCM','PODD','ALGN','HOLX','IDXX',
    # Consumer Discretionary
    'NFLX','DIS','NKE','SBUX','MCD','WMT','TGT','COST','HD','LOW',
    'BKNG','MAR','HLT','ABNB','EXPE','LYFT','UBER','DASH','PTON','W',
    'ETSY','EBAY','CHWY','RH','BBY','GPS','PVH','RL','TPR','VFC',
    # Consumer Staples
    'PG','KO','PEP','PM','MO','CL','GIS','K','CPB','SJM','CAG',
    'HSY','MDLZ','KHC','STZ','BF.B','TAP','SAM','CELH',
    # Growth / Momentum / Tech
    'PLTR','SHOP','SNOW','CRWD','DDOG','NET','ZS','PANW','OKTA','GTLB',
    'RBLX','HOOD','SOFI','AFRM','UPST','PATH','AI','SOUN','IONQ','RGTI',
    'SMCI','ARM','ASML','TSM','MSTR','COIN','HOOD','ACHR','JOBY','LILM',
    'RKLB','LUNR','ASTS','SPCE','MNDY','BILL','HUBS','DOCN','ESTC','MDB',
    # Fintech & Payments
    'V','MA','PYPL','SQ','FIS','FISV','GPN','WEX','FOUR','PAYO',
    # Defence / Industrial / Aerospace
    'LMT','RTX','NOC','BA','CAT','DE','GE','HON','MMM','UPS','FDX',
    'L3H','HII','LDOS','SAIC','KTOS','AXON','CACI','MANT','DRS','TDG',
    'GD','TXT','HWM','SPR','HEICO','TransDigm','WWD','CW','ESLT',
    # Gold / Commodities / Metals
    'GLD','SLV','GDX','GDXJ','NEM','GOLD','AEM','KGC','AU','AGI',
    'FCX','SCCO','AA','CLF','NUE','STLD','RS','CMC','MP','USLM',
    # Airlines / Travel / Leisure
    'DAL','UAL','AAL','LUV','CCL','RCL','ABNB','MGM','WYNN','LVS',
    'CZR','PENN','DKNG','FLUT','RSI','EVRI',
    # EV / Clean Energy / Future Tech
    'RIVN','LCID','ENPH','FSLR','PLUG','BE','CHPT','BLNK','EVGO',
    'NEE','AES','CEG','VST','NRG','ETR','PCG','EIX','XEL','WEC',
    # China / Emerging Markets
    'BABA','JD','PDD','BIDU','NIO','XPEV','LI','TCOM','TME','BILI',
    # Real Estate / REITs
    'AMT','PLD','EQIX','O','SPG','PSA','EXR','AVB','EQR','MAA',
    'VTR','WELL','HR','DOC','MPW','IIPR','COLD','STAG','REXR','FR',
    # Biotech / Life Sciences
    'BIIB','GILD','AMGN','BMRN','EXAS','ILMN','PACB','RXRX','BEAM',
    'EDIT','NTLA','CRSP','FATE','KYMR','ARVN','PRAX','ACAD','SAGE',
    # Retail & E-commerce
    'AMZN','WMT','TGT','COST','DLTR','DG','FIVE','OLLI','BJ','SFM',
    # Media & Entertainment
    'NFLX','DIS','PARA','WBD','FOXA','NYT','SPOT','TTWO','EA','ATVI',
    # Cybersecurity
    'CRWD','PANW','ZS','OKTA','NET','S','TENB','QLYS','VRNS','CYBR',
    # Cloud & SaaS
    'CRM','NOW','WDAY','TEAM','HUBS','DDOG','SNOW','MDB','ESTC','DOCN',
    'ZM','TWLO','SEND','BRZE','PCTY','PAYC','COUP','APPN','ALTR','NCNO',
]

api = None
trade_log = []
# entry_prices tracks buy prices so we can calculate realised PnL on sells
entry_prices: dict = {}
# buy_times tracks when we entered a position to enforce minimum hold time
buy_times: dict = {}
# active_orders prevents duplicate buys when Alpaca hasn't settled yet
active_orders: set = set()

status = {
    'running': False, 'mode': 'PAPER',
    'last_run': None, 'error': None,
    'target_hit': False, 'daily_pnl_peak': 0,
    'last_known_pnl': 0.0,
}


def get_macro_briefing():
    return get_dashboard_data()


def get_dynamic_watchlist():
    return get_current_watchlist() or WATCHLIST


def get_api():
    global api
    if api is None:
        api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version='v2')
    return api


def is_market_open() -> bool:
    try:
        return get_api().get_clock().is_open
    except Exception as e:
        log.warning(f"Clock check failed: {e}")
        return False


def get_bars(symbol: str, timeframe='1Min', limit=100) -> pd.DataFrame:
    """Fetch bars with exponential back-off on transient errors."""
    for attempt, delay in enumerate([0, 1, 2, 4]):
        try:
            if delay:
                time.sleep(delay)
            now   = datetime.now(pytz.UTC)
            start = now - timedelta(days=5)
            bars  = get_api().get_bars(
                symbol, timeframe,
                start=start.isoformat(),
                end=now.isoformat(),
                limit=limit,
                adjustment='raw',
                feed='iex'
            ).df
            if bars.empty:
                return pd.DataFrame()
            return bars[['open', 'high', 'low', 'close', 'volume']]
        except Exception as e:
            if attempt == 3:
                log.warning(f"Bars failed for {symbol} after retries: {e}")
                return pd.DataFrame()
            if '429' in str(e) or '503' in str(e):
                log.warning(f"Bars {symbol} attempt {attempt+1} failed ({e}) — retrying in {delay}s")
            else:
                return pd.DataFrame()
    return pd.DataFrame()


def get_bars_multi(symbol: str) -> dict:
    """Fetch 1m, 3m, 5m bars for multi-timeframe analysis with small delay to avoid pool exhaustion."""
    bars_1m = get_bars(symbol, '1Min', limit=100)
    time.sleep(0.15)  # 150ms between calls per symbol
    bars_3m = get_bars(symbol, '3Min', limit=60)
    time.sleep(0.15)
    bars_5m = get_bars(symbol, '5Min', limit=50)
    return {'1m': bars_1m, '3m': bars_3m, '5m': bars_5m}


def get_positions() -> dict:
    try:
        return {p.symbol: p for p in get_api().list_positions()}
    except:
        return {}


def get_account():
    """Fetch account with exponential back-off."""
    for attempt, delay in enumerate([0, 1, 2]):
        try:
            if delay:
                time.sleep(delay)
            return get_api().get_account()
        except Exception as e:
            if attempt == 2:
                log.warning(f"get_account failed after retries: {e}")
                return None
            if '429' in str(e) or '503' in str(e):
                log.warning(f"get_account attempt {attempt+1} failed — retrying in {delay}s")
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
    """Append trade to disk so it survives restarts."""
    try:
        with open(TRADE_LOG_FILE, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception as e:
        log.warning(f"Failed to persist trade: {e}")


def place_order(symbol: str, side: str, qty: int, price: float = 0.0):
    try:
        get_api().submit_order(
            symbol=symbol, qty=qty, side=side,
            type='market', time_in_force='day'
        )
        log.info(f"{side} {qty}x {symbol} @ ~${price:.2f}")

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

        # Calculate realised PnL on sells
        if side == 'sell' and symbol in entry_prices:
            cost_basis = entry_prices.pop(symbol)
            buy_times.pop(symbol, None)
            realised   = (price - cost_basis) * qty
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
    """Fetch 1m/3m/5m bars and compute multi-timeframe signal for one symbol."""
    try:
        tf_bars = get_bars_multi(symbol)
        bars_1m = tf_bars['1m']
        bars_3m = tf_bars['3m']
        bars_5m = tf_bars['5m']
        bars_htf = get_bars(symbol, '1Hour', limit=60)  # HTF for SLC structure

        if bars_1m.empty:
            return None

        # Get signal detail from 5m timeframe — primary for 3-candle day trade system
        d = get_signal_detail(bars_5m if not bars_5m.empty else bars_1m)
        d['symbol'] = symbol
        d['price']  = float(bars_1m['close'].iloc[-1])

        # Multi-timeframe confirmation — count how many TFs agree
        from strategies import combined_signal, slc_signal
        sig_1m = d['signal']
        sig_3m = combined_signal(bars_3m) if not bars_3m.empty else 'HOLD'
        sig_5m = combined_signal(bars_5m) if not bars_5m.empty else 'HOLD'

        # SLC strategy signal
        sig_slc = slc_signal(bars_5m, bars_htf)

        tf_signals = [sig_1m, sig_3m, sig_5m]
        buy_count  = tf_signals.count('BUY')
        sell_count = tf_signals.count('SELL')

        # Boost score when multiple timeframes agree
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

        # SLC confirmation adds extra weight — strong bonus if it agrees
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

    # ── Track peak P&L for trailing stop ──
    if pnl > status['daily_pnl_peak']:
        status['daily_pnl_peak'] = pnl

    # ── Daily profit target ──
    if pnl >= DAILY_PROFIT_TARGET:
        if not status['target_hit']:
            log.info(f"Target hit! P&L: ${pnl:.2f} — closing all")
            status['target_hit'] = True
            close_all_positions()
            status['error'] = f"Target hit! Locked in ${pnl:.2f} profit for today."
        return

    # ── Trailing stop — only kicks in if we're very close to target ──
    peak = status['daily_pnl_peak']
    if peak >= DAILY_PROFIT_TARGET * 0.85 and pnl < peak * 0.80:
        if not status['target_hit']:
            log.warning(f"Trailing stop: peak ${peak:.2f} → now ${pnl:.2f}")
            status['target_hit'] = True
            close_all_positions()
            status['error'] = f"Trailing stop. Peak: ${peak:.2f}, Now: ${pnl:.2f}"
        return

    # ── Daily loss limit ──
    if pnl < -MAX_DAILY_LOSS:
        log.warning(f"Loss limit hit (${pnl:.2f})")
        close_all_positions()
        status['error'] = f"Loss limit hit: ${pnl:.2f}"
        return

    # ── Close 15 mins before market close ──
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

    # ── Stop-loss + Take-profit sweep ──
    for sym, p in list(positions.items()):
        try:
            plpc  = float(p.unrealized_plpc) * 100
            qty   = int(float(p.qty))
            price = float(p.current_price)
            if qty <= 0:
                continue

            # Dynamic take-profit: bigger positions get more room to run
            cost  = float(p.avg_entry_price) * qty
            if cost >= MAX_POS * 0.9:
                tp = TAKE_PROFIT_PCT * 1.4   # MAX tier — target 3.5%
            elif cost >= MAX_POS * 0.65:
                tp = TAKE_PROFIT_PCT * 1.2   # HIGH tier — target 3.0%
            else:
                tp = TAKE_PROFIT_PCT          # LOW/MED — target 2.5%

            # Take profit
            if plpc >= tp:
                log.info(f"Take-profit: {sym} at +{plpc:.2f}% (target {tp:.1f}%) — locking in gains")
                place_order(sym, 'sell', qty, price)
                del positions[sym]
            # Stop loss
            elif plpc <= -STOP_LOSS_PCT:
                log.warning(f"Stop-loss: {sym} at {plpc:.2f}%")
                place_order(sym, 'sell', qty, price)
                del positions[sym]
        except Exception as e:
            log.warning(f"Stop-loss check failed {sym}: {e}")

    # ── Parallel signal scan — throttled to avoid Alpaca connection pool exhaustion ──
    watchlist = get_current_watchlist() or WATCHLIST
    signals   = []
    # Max 8 workers — keeps within Alpaca connection pool limit of 10
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_signal, sym): sym for sym in watchlist}
        for future in as_completed(futures):
            result = future.result()
            if result:
                signals.append(result)

    buy_candidates  = sorted([s for s in signals if s['signal'] == 'BUY'],
                              key=lambda x: x['score'], reverse=True)
    sell_candidates = [s for s in signals if s['signal'] == 'SELL']

    # ── SELL ──
    MIN_HOLD_SECONDS = 600  # must hold at least 10 minutes before selling on signal
    now_utc = datetime.now(pytz.UTC).replace(tzinfo=None)
    for s in sell_candidates:
        sym = s['symbol']
        if sym in positions:
            # Enforce minimum hold time — skip signal sell, stop-loss still works
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

    # ── BUY — confidence-based position sizing ──
    # Tier 1 (score 3-4):              25% of MAX_POS — weak signal, small bet
    # Tier 2 (score 5-6):              50% of MAX_POS — moderate confidence
    # Tier 3 (score 7-8):              75% of MAX_POS — strong signal
    # Tier 4 (score 9+ AND SLC fired): 100% of MAX_POS — maximum conviction, bet big
    pending_buys: set = set()
    for s in buy_candidates:
        sym   = s['symbol']
        price = s['price']
        score = s.get('score', 3)
        slc_fired = s.get('tf_slc') == 'BUY'

        if sym in positions or sym in pending_buys:
            continue
        if len(positions) + len(pending_buys) >= MAX_OPEN:
            break
        if buying_power < MAX_POS * 0.25:
            break

        # Confidence tier
        if score >= 9 and slc_fired:
            # Maximum conviction — all systems agree including SLC structure+level+confirmation
            size_ratio = 1.0
            tier = 'MAX'
        elif score >= 7:
            size_ratio = 0.75
            tier = 'HIGH'
        elif score >= 5:
            size_ratio = 0.50
            tier = 'MED'
        else:
            size_ratio = 0.25
            tier = 'LOW'

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
    log.info("Bot started — paper trading mode")
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
