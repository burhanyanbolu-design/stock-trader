"""
Backtesting Engine
Tests our strategies against historical data.
Replays signals chronologically across the whole portfolio so that
MAX_OPEN is enforced at portfolio level — matching live bot behaviour.
"""
import os, logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pandas as pd
import numpy as np
import pytz
from collections import defaultdict

load_dotenv()
log = logging.getLogger('backtest')

# ── Config ────────────────────────────────────────────────────────────────────
INITIAL_CAPITAL = 100_000
POSITION_SIZE   = 4_000
MAX_OPEN        = 5
COMMISSION      = 0.005   # $0.005 per share
LOOKBACK_DAYS   = 90

SYMBOLS = [
    'AAPL','MSFT','GOOGL','AMZN','NVDA','META','AMD','TSLA',
    'SPY','QQQ','IWM','DAL','UAL','PLTR',
    'JPM','BAC','XOM','CVX','NFLX','V',
]


def fetch_historical(symbol: str, days: int = LOOKBACK_DAYS,
                     timeframe: str = '1Day') -> pd.DataFrame:
    try:
        import yfinance as yf
        end   = datetime.now(pytz.UTC)
        start = end - timedelta(days=days)
        interval = '1d' if timeframe == '1Day' else '1m'
        df = yf.download(symbol, start=start, end=end,
                         interval=interval, progress=False, auto_adjust=True)
        if df.empty:
            return pd.DataFrame()
        df.columns = [c.lower() for c in df.columns]
        return df[['open', 'high', 'low', 'close', 'volume']].copy()
    except Exception as e:
        log.warning(f"Fetch failed {symbol}: {e}")
        return pd.DataFrame()


def generate_signals(bars: pd.DataFrame) -> pd.Series:
    from strategies import (macd_signal, bollinger_signal, ema_trend,
                            candlestick_score, rsi)
    signals, dates = [], []
    for i in range(26, len(bars)):
        window = bars.iloc[:i+1]
        score  = 0
        cs = candlestick_score(window)
        score += cs * 2
        m = macd_signal(window)
        if m == 'BUY':  score += 2
        if m == 'SELL': score -= 2
        b = bollinger_signal(window)
        if b == 'BUY':  score += 1
        if b == 'SELL': score -= 1
        e = ema_trend(window)
        if e == 'BUY':  score += 1
        if e == 'SELL': score -= 1
        try:
            r = rsi(window['close'])
            if r < 40:   score += 1
            elif r > 60: score -= 1
        except:
            pass
        signals.append('BUY' if score >= 4 else 'SELL' if score <= -4 else 'HOLD')
        dates.append(bars.index[i])
    return pd.Series(signals, index=dates)


def run_backtest(symbols=None, days=LOOKBACK_DAYS, timeframe='1Day') -> dict:
    if symbols is None:
        symbols = SYMBOLS

    tf_note = "⚠️  Uses DAILY bars — directional only." if timeframe == '1Day' else "✅ Uses 1-MIN bars — matches live bot."

    print(f"\n{'='*60}")
    print(f"  BACKTEST — Last {days} days | {timeframe} bars")
    print(f"  Capital: ${INITIAL_CAPITAL:,} | Position: ${POSITION_SIZE:,}")
    print(f"  Max open: {MAX_OPEN} | Symbols: {len(symbols)}")
    print(f"  {tf_note}")
    print(f"{'='*60}\n")

    print("  Fetching data and generating signals...")
    all_bars: dict = {}
    events:   list = []

    for symbol in symbols:
        bars = fetch_historical(symbol, days, timeframe)
        if bars.empty or len(bars) < 30:
            print(f"  {symbol}: no data — skipped")
            continue
        sigs = generate_signals(bars)
        if sigs.empty:
            print(f"  {symbol}: no signals — skipped")
            continue
        all_bars[symbol] = bars
        for date, signal in sigs.items():
            if date in bars.index:
                events.append((date, symbol, signal, float(bars.loc[date, 'close'])))
        print(f"  {symbol}: {len(sigs)} signal bars")

    # Sort chronologically; ties broken alphabetically
    events.sort(key=lambda e: (e[0], e[1]))

    STOP_LOSS_PCT  = 1.5   # match live bot
    TAKE_PROFIT_PCT = 1.5  # match live bot

    # ── Phase 2: portfolio-level chronological replay ─────────────────────────
    capital         = float(INITIAL_CAPITAL)
    open_positions: dict = {}
    all_trades:     list = []
    equity_curve:   list = [capital]
    peak_equity          = capital
    max_drawdown         = 0.0

    for date, symbol, signal, price in events:

        # ── Check stop-loss and take-profit on all open positions first ──
        for sym in list(open_positions.keys()):
            pos = open_positions[sym]
            if sym not in all_bars:
                continue
            bars_sym = all_bars[sym]
            if date not in bars_sym.index:
                continue
            bar       = bars_sym.loc[date]
            entry     = pos['entry_price']
            low_pct   = (float(bar['low'])  - entry) / entry * 100
            high_pct  = (float(bar['high']) - entry) / entry * 100

            exit_price = None
            exit_reason = None

            if low_pct <= -STOP_LOSS_PCT:
                exit_price  = entry * (1 - STOP_LOSS_PCT / 100)
                exit_reason = 'stop-loss'
            elif high_pct >= TAKE_PROFIT_PCT:
                exit_price  = entry * (1 + TAKE_PROFIT_PCT / 100)
                exit_reason = 'take-profit'

            if exit_price:
                pos    = open_positions.pop(sym)
                qty    = pos['qty']
                proceeds = qty * exit_price - (qty * COMMISSION)
                pnl      = proceeds - (qty * entry)
                capital += proceeds
                all_trades.append({
                    'symbol':      sym,
                    'entry_date':  str(pos['entry_date']),
                    'exit_date':   str(date),
                    'entry_price': entry,
                    'exit_price':  round(exit_price, 2),
                    'qty':         qty,
                    'pnl':         round(pnl, 2),
                    'pnl_pct':     round(pnl / (qty * entry) * 100, 2),
                    'win':         bool(pnl > 0),
                    'exit_reason': exit_reason,
                })
                equity_curve.append(capital)
                if capital > peak_equity:
                    peak_equity = capital
                dd = (peak_equity - capital) / peak_equity * 100
                if dd > max_drawdown:
                    max_drawdown = dd

        if signal == 'SELL' and symbol in open_positions:
            pos      = open_positions.pop(symbol)
            qty      = pos['qty']
            proceeds = qty * price - (qty * COMMISSION)
            pnl      = proceeds - (qty * pos['entry_price'])
            capital += proceeds
            all_trades.append({
                'symbol':      symbol,
                'entry_date':  str(pos['entry_date']),
                'exit_date':   str(date),
                'entry_price': pos['entry_price'],
                'exit_price':  price,
                'qty':         qty,
                'pnl':         round(pnl, 2),
                'pnl_pct':     round(pnl / (qty * pos['entry_price']) * 100, 2),
                'win':         bool(pnl > 0),
            })
            equity_curve.append(capital)
            if capital > peak_equity:
                peak_equity = capital
            dd = (peak_equity - capital) / peak_equity * 100
            if dd > max_drawdown:
                max_drawdown = dd

        elif (signal == 'BUY'
              and symbol not in open_positions
              and len(open_positions) < MAX_OPEN
              and capital >= POSITION_SIZE):
            qty  = max(1, int(POSITION_SIZE / price))
            cost = qty * price + (qty * COMMISSION)
            capital -= cost
            open_positions[symbol] = {
                'entry_price': price,
                'entry_date':  date,
                'qty':         qty,
            }

    # ── Phase 3: close remaining open positions at last price ─────────────────
    for symbol, pos in open_positions.items():
        bars       = all_bars[symbol]
        last_price = float(bars['close'].iloc[-1])
        qty        = pos['qty']
        proceeds   = qty * last_price - (qty * COMMISSION)
        pnl        = proceeds - (qty * pos['entry_price'])
        capital   += proceeds
        all_trades.append({
            'symbol':      symbol,
            'entry_date':  str(pos['entry_date']),
            'exit_date':   str(bars.index[-1]),
            'entry_price': pos['entry_price'],
            'exit_price':  last_price,
            'qty':         qty,
            'pnl':         round(pnl, 2),
            'pnl_pct':     round(pnl / (qty * pos['entry_price']) * 100, 2),
            'win':         bool(pnl > 0),
        })

    # Per-symbol summary
    by_symbol: dict = defaultdict(list)
    for t in all_trades:
        by_symbol[t['symbol']].append(t)
    for sym, trades in sorted(by_symbol.items()):
        wins = sum(1 for t in trades if t['win'])
        print(f"  {sym}: {len(trades)} trades | {wins}W/{len(trades)-wins}L")

    # ── Summary ───────────────────────────────────────────────────────────────
    total_pnl     = capital - INITIAL_CAPITAL
    total_trades  = len(all_trades)
    wins          = sum(1 for t in all_trades if t['win'])
    losses        = total_trades - wins
    win_rate      = (wins / total_trades * 100) if total_trades > 0 else 0
    avg_win       = np.mean([t['pnl'] for t in all_trades if t['win']]) if wins > 0 else 0
    avg_loss      = np.mean([t['pnl'] for t in all_trades if not t['win']]) if losses > 0 else 0
    profit_factor = abs(avg_win * wins / (avg_loss * losses)) if losses > 0 and avg_loss != 0 else 0
    best_trade    = max(all_trades, key=lambda x: x['pnl']) if all_trades else None
    worst_trade   = min(all_trades, key=lambda x: x['pnl']) if all_trades else None

    results = {
        'initial_capital': INITIAL_CAPITAL,
        'final_capital':   round(capital, 2),
        'total_pnl':       round(total_pnl, 2),
        'total_pnl_pct':   round(total_pnl / INITIAL_CAPITAL * 100, 2),
        'total_trades':    total_trades,
        'wins':            wins,
        'losses':          losses,
        'win_rate':        round(win_rate, 1),
        'avg_win':         round(avg_win, 2),
        'avg_loss':        round(avg_loss, 2),
        'profit_factor':   round(profit_factor, 2),
        'max_drawdown':    round(max_drawdown, 2),
        'best_trade':      best_trade,
        'worst_trade':     worst_trade,
        'all_trades':      all_trades,
        'equity_curve':    equity_curve,
    }

    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  Final Capital  : ${capital:,.2f}")
    print(f"  Total P&L      : ${total_pnl:+,.2f} ({total_pnl/INITIAL_CAPITAL*100:+.2f}%)")
    print(f"  Total Trades   : {total_trades}")
    print(f"  Win Rate       : {win_rate:.1f}% ({wins}W / {losses}L)")
    print(f"  Avg Win        : ${avg_win:.2f}")
    print(f"  Avg Loss       : ${avg_loss:.2f}")
    print(f"  Profit Factor  : {profit_factor:.2f}")
    print(f"  Max Drawdown   : {max_drawdown:.2f}%")
    if best_trade:
        print(f"  Best Trade     : {best_trade['symbol']} +${best_trade['pnl']:.2f} ({best_trade['pnl_pct']:+.2f}%)")
    if worst_trade:
        print(f"  Worst Trade    : {worst_trade['symbol']} ${worst_trade['pnl']:.2f} ({worst_trade['pnl_pct']:+.2f}%)")
    print(f"{'='*60}\n")

    return results


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)
    run_backtest()
