import sys
from dotenv import load_dotenv
load_dotenv()
import trader
from strategies import combined_signal, get_signal_detail

watchlist = ['AAPL','MSFT','GOOGL','AMZN','NVDA','TSLA','META','AMD','SPY','QQQ']

print(f"{'SYMBOL':7} | {'SIGNAL':4} | {'SCORE':5} | {'PRICE':8} | {'RSI':5} | {'MACD':4} | {'VWAP':4} | {'EMA':4} | PATTERNS")
print('-' * 90)
for sym in watchlist:
    try:
        bars = trader.get_bars(sym, '1Min', 60)
        if bars.empty:
            print(f'{sym:7} | NO DATA')
            continue
        price = bars['close'].iloc[-1]
        d = get_signal_detail(bars)
        patterns = ', '.join(d['patterns'])
        print(f"{sym:7} | {d['signal']:4} | {d['score']:+5} | ${price:7.2f} | {d['rsi']:5.1f} | {d['macd']:4} | {d['vwap']:4} | {d['ema']:4} | {patterns}")
    except Exception as e:
        print(f'{sym:7} | ERROR: {e}')
