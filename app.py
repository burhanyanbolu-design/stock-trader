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

# ── Startup secrets validation ────────────────────────────────────────────────
_missing = [k for k in ('ALPACA_API_KEY', 'ALPACA_SECRET_KEY')
            if not os.getenv(k)]
if _missing:
    logging.basicConfig(level=logging.ERROR)
    logging.error(f"FATAL: missing required env vars: {', '.join(_missing)}")
    logging.error("Set them in Railway → Variables before deploying.")
    sys.exit(1)

app = Flask(__name__)
bot_thread = None
scheduler  = BackgroundScheduler(timezone=pytz.timezone('America/New_York'))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def auto_start():
    """Auto-start bot at 9:29am NY (2:29pm UK) on weekdays."""
    global bot_thread
    if not trader.status['running']:
        trader.status['target_hit'] = False
        bot_thread = threading.Thread(target=trader.start_bot, daemon=True)
        bot_thread.start()
        import logging
        logging.getLogger('scheduler').info("Auto-started bot at market open")


def auto_stop():
    """Auto-stop and close all positions at 3:50pm NY."""
    if trader.status['running']:
        trader.close_all_positions()
        trader.stop_bot()
        import logging
        logging.getLogger('scheduler').info("Auto-stopped bot before market close")


# Schedule: Mon-Fri only
scheduler.add_job(auto_start, 'cron', day_of_week='mon-fri', hour=9,  minute=29, timezone='America/New_York')
scheduler.add_job(auto_stop,  'cron', day_of_week='mon-fri', hour=15, minute=50, timezone='America/New_York')
scheduler.start()


@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')


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
                    'symbol': sym,
                    'qty': p.qty,
                    'entry': float(p.avg_entry_price),
                    'current': float(p.current_price),
                    'pnl': float(p.unrealized_pl),
                    'pnl_pct': float(p.unrealized_plpc) * 100,
                })
            except:
                pass

        return jsonify({
            'running':      trader.status['running'],
            'mode':         trader.status['mode'],
            'last_run':     trader.status['last_run'],
            'error':        trader.status['error'],
            'target_hit':   trader.status.get('target_hit', False),
            'daily_target': trader.DAILY_PROFIT_TARGET,
            'equity':       float(acct.equity)  if acct else 0,
            'cash':         float(acct.cash)    if acct else 0,
            'daily_pnl':    trader.daily_pnl(),
            'positions':    pos_list,
            'trades':       trader.trade_log[-20:],
            'auto_schedule': 'Mon-Fri: Auto-start 9:29am NY · Auto-stop 3:50pm NY',
        })
    except Exception as e:
        return jsonify({
            'running': False, 'mode': 'PAPER', 'last_run': None,
            'error': str(e), 'equity': 0, 'cash': 0,
            'daily_pnl': 0, 'positions': [], 'trades': []
        })


@app.route('/api/backtest', methods=['POST'])
def run_backtest():
    try:
        import backtest as bt
        data      = request.json or {}
        days      = int(data.get('days', 90))
        timeframe = data.get('timeframe', '1Day')
        results   = bt.run_backtest(days=days, timeframe=timeframe)
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
        watchlist = trader.get_dynamic_watchlist()
        briefing['watchlist'] = watchlist
        return jsonify(briefing)
    except Exception as e:
        return jsonify({'error': str(e), 'conditions': [], 'notes': '', 'watchlist': []})


@app.route('/api/signals')
def get_signals():
    try:
        from strategies import get_signal_detail
        results = []
        for symbol in trader.WATCHLIST:
            try:
                bars = trader.get_bars(symbol)
                if bars.empty:
                    results.append({'symbol': symbol, 'signal': 'NO DATA', 'score': 0,
                                    'price': 0, 'rsi': 0, 'macd': '-', 'vwap': '-',
                                    'ema': '-', 'patterns': ['No data']})
                    continue
                d = get_signal_detail(bars)
                d['symbol'] = symbol
                d['price']  = round(float(bars['close'].iloc[-1]), 2)
                results.append(d)
            except Exception as e:
                results.append({'symbol': symbol, 'signal': 'ERROR', 'score': 0,
                                'price': 0, 'rsi': 0, 'macd': '-', 'vwap': '-',
                                'ema': '-', 'patterns': [str(e)]})
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
