"""
Flask dashboard for the stock trading bot.
"""
import threading, os, sys, logging
from flask import Flask, jsonify, send_from_directory, request
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
import trader

load_dotenv()

_missing = [k for k in ('ALPACA_API_KEY', 'ALPACA_SECRET_KEY') if not os.getenv(k)]
if _missing:
    logging.basicConfig(level=logging.ERROR)
    logging.error(f"FATAL: missing required env vars: {', '.join(_missing)}")
    sys.exit(1)

app = Flask(__name__)
bot_thread = None
scheduler  = BackgroundScheduler(timezone=pytz.timezone('America/New_York'))
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))


def auto_start():
    global bot_thread
    if not trader.status['running']:
        trader.status['target_hit'] = False
        bot_thread = threading.Thread(target=trader.start_bot, daemon=True)
        bot_thread.start()

def auto_stop():
    if trader.status['running']:
        trader.close_all_positions()
        trader.stop_bot()

scheduler.add_job(auto_start, 'cron', day_of_week='mon-fri', hour=9,  minute=29, timezone='America/New_York')
scheduler.add_job(auto_stop,  'cron', day_of_week='mon-fri', hour=15, minute=50, timezone='America/New_York')
scheduler.start()


@app.route('/')
def index():
    return send_from_directory(os.path.join(BASE_DIR, 'templates'), 'index.html')

@app.route('/live')
def live():
    return send_from_directory(os.path.join(BASE_DIR, 'templates'), 'live.html')

@app.route('/api/start', methods=['POST'])
def start():
    global bot_thread
    if not trader.status['running']:
        bot_thread = threading.Thread(target=trader.start_bot, daemon=True)
        bot_thread.start()
    return jsonify({'ok': True})

@app.route('/api/stop', methods=['POST'])
def stop():
    trader.stop_bot()
    return jsonify({'ok': True})

@app.route('/api/status')
def get_status():
    try:
        acct = trader.get_account()
        positions = trader.get_positions()
        pos_list = []
        for sym, p in positions.items():
            try:
                pos_list.append({
                    'symbol': sym, 'qty': p.qty,
                    'entry': float(p.avg_entry_price),
                    'current': float(p.current_price),
                    'pnl': float(p.unrealized_pl),
                    'pnl_pct': float(p.unrealized_plpc) * 100,
                })
            except: pass
        return jsonify({
            'running':      trader.status['running'],
            'mode':         trader.status['mode'],
            'last_run':     trader.status['last_run'],
            'error':        trader.status['error'],
            'target_hit':   trader.status.get('target_hit', False),
            'daily_target': trader.DAILY_PROFIT_TARGET,
            'equity':       float(acct.equity) if acct else 0,
            'cash':         float(acct.cash)   if acct else 0,
            'daily_pnl':    trader.daily_pnl(),
            'positions':    pos_list,
            'trades':       trader.trade_log[-20:],
            'auto_schedule': 'Mon-Fri: Auto-start 9:29am NY · Auto-stop 3:50pm NY',
        })
    except Exception as e:
        return jsonify({'running': False, 'mode': 'PAPER', 'last_run': None,
                        'error': str(e), 'equity': 0, 'cash': 0,
                        'daily_pnl': 0, 'positions': [], 'trades': []})

@app.route('/api/backtest', methods=['POST'])
def run_backtest():
    try:
        import backtest as bt
        data = request.json or {}
        days = int(data.get('days', 90))
        timeframe = data.get('timeframe', '1Day')
        results = bt.run_backtest(days=days, timeframe=timeframe)
        results.pop('equity_curve', None)
        results.pop('all_trades', None)
        if results.get('best_trade'):
            results['best_trade']['entry_date'] = str(results['best_trade']['entry_date'])
            results['best_trade']['exit_date']  = str(results['best_trade']['exit_date'])
        if results.get('worst_trade'):
            results['worst_trade']['entry_date'] = str(results['worst_trade']['entry_date'])
            results['worst_trade']['exit_date']  = str(results['worst_trade']['exit_date'])
        results['timeframe'] = timeframe
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/macro')
def get_macro():
    try:
        briefing = trader.get_macro_briefing()
        briefing['watchlist'] = trader.get_dynamic_watchlist()
        return jsonify(briefing)
    except Exception as e:
        return jsonify({'error': str(e), 'conditions': [], 'notes': '', 'watchlist': []})

@app.route('/api/bars/<symbol>')
def get_bars(symbol):
    try:
        tf    = request.args.get('tf', '5Min')
        limit = int(request.args.get('limit', 60))
        bars  = trader.get_bars(symbol.upper(), tf, limit=limit)
        if bars.empty:
            return jsonify({'error': 'No data'})
        bars = bars.reset_index()
        time_col = 'timestamp' if 'timestamp' in bars.columns else bars.columns[0]
        result = [{'time': str(row[time_col]), 'open': round(float(row['open']), 4),
                   'high': round(float(row['high']), 4), 'low': round(float(row['low']), 4),
                   'close': round(float(row['close']), 4),
                   'volume': int(row['volume']) if 'volume' in row else 0}
                  for _, row in bars.iterrows()]
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/daily-summary')
def daily_summary():
    try:
        import json
        from datetime import date
        today = date.today().strftime('%Y-%m-%d')
        trades_today = []
        if os.path.exists(trader.TRADE_LOG_FILE):
            with open(trader.TRADE_LOG_FILE, 'r') as f:
                for line in f:
                    try:
                        t = json.loads(line.strip())
                        if t.get('date') == today:
                            trades_today.append(t)
                    except: pass
        for t in trader.trade_log:
            if t.get('date') == today and t not in trades_today:
                trades_today.append(t)
        sells = [t for t in trades_today if t['action'] == 'SELL' and t.get('pnl') is not None]
        buys  = [t for t in trades_today if t['action'] == 'BUY']
        total_pnl = sum(t['pnl'] for t in sells)
        wins   = [t for t in sells if t['pnl'] > 0]
        losses = [t for t in sells if t['pnl'] <= 0]
        by_symbol = {}
        for t in sells:
            sym = t['symbol']
            if sym not in by_symbol:
                by_symbol[sym] = {'symbol': sym, 'trades': 0, 'pnl': 0, 'wins': 0}
            by_symbol[sym]['trades'] += 1
            by_symbol[sym]['pnl'] = round(by_symbol[sym]['pnl'] + t['pnl'], 2)
            if t['pnl'] > 0: by_symbol[sym]['wins'] += 1
        return jsonify({
            'date': today, 'total_trades': len(sells), 'total_buys': len(buys),
            'total_pnl': round(total_pnl, 2),
            'win_rate': round(len(wins)/len(sells)*100, 1) if sells else 0,
            'wins': len(wins), 'losses': len(losses),
            'avg_win':  round(sum(t['pnl'] for t in wins)/len(wins), 2) if wins else 0,
            'avg_loss': round(sum(t['pnl'] for t in losses)/len(losses), 2) if losses else 0,
            'best_trade':  max(sells, key=lambda x: x['pnl']) if sells else None,
            'worst_trade': min(sells, key=lambda x: x['pnl']) if sells else None,
            'by_symbol': sorted(by_symbol.values(), key=lambda x: x['pnl'], reverse=True),
            'all_trades': trades_today,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/signals')
def get_signals():
    try:
        from strategies import get_signal_detail, slc_signal
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def fetch_one(symbol):
            try:
                bars_1m  = trader.get_bars(symbol, '1Min',  limit=100)
                bars_5m  = trader.get_bars(symbol, '5Min',  limit=50)
                bars_htf = trader.get_bars(symbol, '1Hour', limit=60)
                if bars_1m.empty:
                    return {'symbol': symbol, 'signal': 'NO DATA', 'score': 0,
                            'price': 0, 'rsi': 0, 'macd': '-', 'vwap': '-',
                            'ema': '-', 'patterns': ['No data'], 'slc': '-', 'tier': '-'}
                d = get_signal_detail(bars_1m)
                d['symbol'] = symbol
                d['price']  = round(float(bars_1m['close'].iloc[-1]), 2)
                sig_slc = slc_signal(bars_5m, bars_htf)
                d['slc'] = sig_slc
                score = d.get('score', 0)
                d['tier'] = 'MAX' if score >= 9 and sig_slc == 'BUY' else \
                            'HIGH' if score >= 7 else 'MED' if score >= 5 else \
                            'LOW' if score >= 3 else '-'
                return d
            except Exception as e:
                return {'symbol': symbol, 'signal': 'ERROR', 'score': 0,
                        'price': 0, 'rsi': 0, 'macd': '-', 'vwap': '-',
                        'ema': '-', 'patterns': [str(e)], 'slc': '-', 'tier': '-'}

        results = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(fetch_one, sym): sym for sym in trader.WATCHLIST}
            for future in as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda x: (x['signal'] != 'BUY', -x.get('score', 0)))
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
