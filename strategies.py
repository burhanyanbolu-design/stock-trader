"""
Day Trading Strategies — Candlestick patterns + technical indicators
Timeframes: 1min, 3min, 5min
All return 'BUY', 'SELL', or 'HOLD'
"""
import pandas as pd
import numpy as np


# ─── 3-Candle Momentum Confirmation (5-min focused) ──────────────────────────

def three_candle_bull(bars: pd.DataFrame) -> bool:
    """
    3 consecutive bullish 5-min candles — each close higher than previous close.
    Each candle must be green (close > open).
    Bodies must be meaningful (not tiny doji-like candles).
    This confirms sustained buying momentum before entry.
    """
    if len(bars) < 3:
        return False
    c1, c2, c3 = bars.iloc[-3], bars.iloc[-2], bars.iloc[-1]

    # All 3 must be green candles
    all_green = (c1['close'] > c1['open'] and
                 c2['close'] > c2['open'] and
                 c3['close'] > c3['open'])

    # Each close must be higher than the previous close — ascending momentum
    ascending = c2['close'] > c1['close'] and c3['close'] > c2['close']

    # Each body must be at least 0.05% of price — filters out tiny doji candles
    min_body = c3['close'] * 0.0005
    bodies_solid = (abs(c1['close'] - c1['open']) >= min_body and
                    abs(c2['close'] - c2['open']) >= min_body and
                    abs(c3['close'] - c3['open']) >= min_body)

    return all_green and ascending and bodies_solid


def three_candle_bear(bars: pd.DataFrame) -> bool:
    """
    3 consecutive bearish 5-min candles — each close lower than previous close.
    Each candle must be red (close < open).
    Bodies must be meaningful.
    This confirms sustained selling momentum before short/sell entry.
    """
    if len(bars) < 3:
        return False
    c1, c2, c3 = bars.iloc[-3], bars.iloc[-2], bars.iloc[-1]

    # All 3 must be red candles
    all_red = (c1['close'] < c1['open'] and
               c2['close'] < c2['open'] and
               c3['close'] < c3['open'])

    # Each close must be lower than the previous close — descending momentum
    descending = c2['close'] < c1['close'] and c3['close'] < c2['close']

    # Bodies must be solid
    min_body = c3['close'] * 0.0005
    bodies_solid = (abs(c1['close'] - c1['open']) >= min_body and
                    abs(c2['close'] - c2['open']) >= min_body and
                    abs(c3['close'] - c3['open']) >= min_body)

    return all_red and descending and bodies_solid


def candle_momentum_score(bars: pd.DataFrame) -> int:
    """
    Score based on 3-candle momentum patterns.
    +3 for 3-candle bull run, -3 for 3-candle bear run.
    +1/-1 for 2-candle partial confirmation.
    """
    score = 0

    if three_candle_bull(bars):
        score += 3
    elif (len(bars) >= 2 and
          bars.iloc[-2]['close'] > bars.iloc[-2]['open'] and
          bars.iloc[-1]['close'] > bars.iloc[-1]['open'] and
          bars.iloc[-1]['close'] > bars.iloc[-2]['close']):
        score += 1  # 2-candle partial bull

    if three_candle_bear(bars):
        score -= 3
    elif (len(bars) >= 2 and
          bars.iloc[-2]['close'] < bars.iloc[-2]['open'] and
          bars.iloc[-1]['close'] < bars.iloc[-1]['open'] and
          bars.iloc[-1]['close'] < bars.iloc[-2]['close']):
        score -= 1  # 2-candle partial bear

    return score



def is_bullish_engulfing(bars: pd.DataFrame) -> bool:
    """Previous candle red, current candle green and body fully engulfs previous"""
    if len(bars) < 2:
        return False
    prev = bars.iloc[-2]
    curr = bars.iloc[-1]
    prev_bearish = prev['close'] < prev['open']
    curr_bullish = curr['close'] > curr['open']
    engulfs = curr['open'] <= prev['close'] and curr['close'] >= prev['open']
    return prev_bearish and curr_bullish and engulfs


def is_bearish_engulfing(bars: pd.DataFrame) -> bool:
    """Previous candle green, current candle red and body fully engulfs previous"""
    if len(bars) < 2:
        return False
    prev = bars.iloc[-2]
    curr = bars.iloc[-1]
    prev_bullish = prev['close'] > prev['open']
    curr_bearish = curr['close'] < curr['open']
    engulfs = curr['open'] >= prev['close'] and curr['close'] <= prev['open']
    return prev_bullish and curr_bearish and engulfs


def is_hammer(bars: pd.DataFrame) -> bool:
    """Long lower wick, small body at top — bullish reversal"""
    if len(bars) < 1:
        return False
    c = bars.iloc[-1]
    body = abs(c['close'] - c['open'])
    lower_wick = min(c['open'], c['close']) - c['low']
    upper_wick = c['high'] - max(c['open'], c['close'])
    if body == 0:
        return False
    return lower_wick >= 2 * body and upper_wick <= 0.3 * body


def is_shooting_star(bars: pd.DataFrame) -> bool:
    """Long upper wick, small body at bottom — bearish reversal"""
    if len(bars) < 1:
        return False
    c = bars.iloc[-1]
    body = abs(c['close'] - c['open'])
    upper_wick = c['high'] - max(c['open'], c['close'])
    lower_wick = min(c['open'], c['close']) - c['low']
    if body == 0:
        return False
    return upper_wick >= 2 * body and lower_wick <= 0.3 * body


def is_doji(bars: pd.DataFrame) -> bool:
    """Open ≈ Close — indecision candle"""
    if len(bars) < 1:
        return False
    c = bars.iloc[-1]
    body = abs(c['close'] - c['open'])
    total_range = c['high'] - c['low']
    if total_range == 0:
        return False
    return body / total_range < 0.1


def is_morning_star(bars: pd.DataFrame) -> bool:
    """3-candle bullish reversal: big red, small doji/body, big green"""
    if len(bars) < 3:
        return False
    c1, c2, c3 = bars.iloc[-3], bars.iloc[-2], bars.iloc[-1]
    big_red   = c1['close'] < c1['open'] and abs(c1['close']-c1['open']) > 0.5 * (c1['high']-c1['low'])
    small_mid = abs(c2['close']-c2['open']) < abs(c1['close']-c1['open']) * 0.3
    big_green = c3['close'] > c3['open'] and c3['close'] > (c1['open']+c1['close'])/2
    return big_red and small_mid and big_green


def is_evening_star(bars: pd.DataFrame) -> bool:
    """3-candle bearish reversal: big green, small doji/body, big red"""
    if len(bars) < 3:
        return False
    c1, c2, c3 = bars.iloc[-3], bars.iloc[-2], bars.iloc[-1]
    big_green = c1['close'] > c1['open'] and abs(c1['close']-c1['open']) > 0.5 * (c1['high']-c1['low'])
    small_mid = abs(c2['close']-c2['open']) < abs(c1['close']-c1['open']) * 0.3
    big_red   = c3['close'] < c3['open'] and c3['close'] < (c1['open']+c1['close'])/2
    return big_green and small_mid and big_red


# ─── Technical Indicators ─────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period=14) -> float:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).iloc[-1]


def macd_signal(bars: pd.DataFrame):
    """MACD line crosses signal line"""
    close = bars['close']
    macd_line = ema(close, 12) - ema(close, 26)
    signal_line = ema(macd_line, 9)
    macd_now  = macd_line.iloc[-1]
    macd_prev = macd_line.iloc[-2]
    sig_now   = signal_line.iloc[-1]
    sig_prev  = signal_line.iloc[-2]
    if macd_now > sig_now and macd_prev <= sig_prev:
        return 'BUY'
    if macd_now < sig_now and macd_prev >= sig_prev:
        return 'SELL'
    return 'HOLD'


def vwap_signal(bars: pd.DataFrame) -> str:
    """Price vs VWAP — institutional benchmark"""
    if 'volume' not in bars.columns or bars['volume'].sum() == 0:
        return 'HOLD'
    typical = (bars['high'] + bars['low'] + bars['close']) / 3
    vwap = (typical * bars['volume']).cumsum() / bars['volume'].cumsum()
    price = bars['close'].iloc[-1]
    vwap_now = vwap.iloc[-1]
    if price > vwap_now * 1.001:
        return 'BUY'
    if price < vwap_now * 0.999:
        return 'SELL'
    return 'HOLD'


def bollinger_signal(bars: pd.DataFrame, period=20) -> str:
    """Price touches lower band → BUY, upper band → SELL"""
    if len(bars) < period:
        return 'HOLD'
    close = bars['close']
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + 2 * std
    lower = mid - 2 * std
    price = close.iloc[-1]
    if price <= lower.iloc[-1]:
        return 'BUY'
    if price >= upper.iloc[-1]:
        return 'SELL'
    return 'HOLD'


def ema_trend(bars: pd.DataFrame) -> str:
    """EMA 9 vs EMA 21 trend direction"""
    if len(bars) < 21:
        return 'HOLD'
    close = bars['close']
    e9  = ema(close, 9).iloc[-1]
    e21 = ema(close, 21).iloc[-1]
    if e9 > e21:
        return 'BUY'
    if e9 < e21:
        return 'SELL'
    return 'HOLD'


# ─── Candlestick Score ────────────────────────────────────────────────────────

def candlestick_score(bars: pd.DataFrame) -> int:
    """
    Returns positive score for bullish patterns, negative for bearish.
    +2 for strong patterns, +1 for weak.
    """
    score = 0
    if is_bullish_engulfing(bars):  score += 2
    if is_hammer(bars):             score += 2
    if is_morning_star(bars):       score += 2
    if is_bearish_engulfing(bars):  score -= 2
    if is_shooting_star(bars):      score -= 2
    if is_evening_star(bars):       score -= 2
    if is_doji(bars):               score += 0  # neutral
    return score


# ─── Combined Day Trading Signal ─────────────────────────────────────────────

def combined_signal(bars: pd.DataFrame) -> str:
    """
    Weighted voting system with stricter filters for higher win rate.
    Requires score >= 4 (was 3) AND volume confirmation AND trend alignment.
    """
    if len(bars) < 26:
        return 'HOLD'

    score = 0

    # ── Volume confirmation ───────────────────────────────────────────────────
    # Only trade when volume is 30% above 20-bar average (strong confirmation)
    if 'volume' in bars.columns:
        avg_vol = bars['volume'].rolling(20).mean().iloc[-1]
        curr_vol = bars['volume'].iloc[-1]
        vol_confirmed = curr_vol > avg_vol * 1.3  # must be 30% above average
    else:
        vol_confirmed = True  # skip if no volume data

    # ── Overall trend filter (50-bar EMA) ────────────────────────────────────
    # Only buy in uptrend, only sell in downtrend
    close = bars['close']
    if len(bars) >= 50:
        ema50 = ema(close, 50).iloc[-1]
        price = close.iloc[-1]
        in_uptrend   = price > ema50
        in_downtrend = price < ema50
    else:
        in_uptrend   = True
        in_downtrend = True

    # ── 3-Candle momentum confirmation (weight 3) — primary day trade trigger ─
    # This is the core entry filter — requires 3 consecutive 5-min candles
    # confirming direction before any signal is acted on
    momentum = candle_momentum_score(bars)
    score += momentum * 2  # double weight — this is the most important filter

    # ── Candlestick patterns (weight 2) ──────────────────────────────────────
    cs = candlestick_score(bars)
    score += cs * 2

    # ── MACD (weight 2) ──────────────────────────────────────────────────────
    m = macd_signal(bars)
    if m == 'BUY':  score += 2
    if m == 'SELL': score -= 2

    # ── VWAP (weight 1) ──────────────────────────────────────────────────────
    v = vwap_signal(bars)
    if v == 'BUY':  score += 1
    if v == 'SELL': score -= 1

    # ── Bollinger (weight 1) ─────────────────────────────────────────────────
    b = bollinger_signal(bars)
    if b == 'BUY':  score += 1
    if b == 'SELL': score -= 1

    # ── EMA trend (weight 1) ─────────────────────────────────────────────────
    e = ema_trend(bars)
    if e == 'BUY':  score += 1
    if e == 'SELL': score -= 1

    # ── RSI confirmation (weight 2) ──────────────────────────────────────────
    # Tighter RSI bands — only trade genuinely oversold/overbought
    try:
        r = rsi(bars['close'])
        if r < 35:   score += 2   # genuinely oversold — strong buy signal
        elif r < 45: score += 1   # mildly oversold
        elif r > 65: score -= 2   # genuinely overbought — strong sell signal
        elif r > 55: score -= 1   # mildly overbought
    except:
        pass

    # ── Final decision — score 5+ AND 3-candle momentum must confirm ─────────
    # For BUY: need bullish 3-candle run OR at least 2-candle partial + high score
    # For SELL: need bearish 3-candle run OR at least 2-candle partial + high score
    bull_confirmed = momentum >= 1  # at least 2-candle partial bull
    bear_confirmed = momentum <= -1  # at least 2-candle partial bear

    if score >= 5 and vol_confirmed and in_uptrend and bull_confirmed:
        return 'BUY'
    if score <= -5 and vol_confirmed and in_downtrend and bear_confirmed:
        return 'SELL'
    return 'HOLD'


def get_signal_detail(bars: pd.DataFrame) -> dict:
    """Returns full breakdown for dashboard display"""
    if len(bars) < 26:
        return {'signal': 'HOLD', 'score': 0, 'details': {}}

    cs    = candlestick_score(bars)
    mom   = candle_momentum_score(bars)
    m     = macd_signal(bars)
    v     = vwap_signal(bars)
    b     = bollinger_signal(bars)
    e     = ema_trend(bars)
    r_val = 50
    try:
        r_val = round(rsi(bars['close']), 1)
    except:
        pass

    patterns = []
    if three_candle_bull(bars):  patterns.append('3-Candle Bull Run ▲▲▲')
    if three_candle_bear(bars):  patterns.append('3-Candle Bear Run ▼▼▼')
    if is_bullish_engulfing(bars):  patterns.append('Bullish Engulfing')
    if is_bearish_engulfing(bars):  patterns.append('Bearish Engulfing')
    if is_hammer(bars):             patterns.append('Hammer')
    if is_shooting_star(bars):      patterns.append('Shooting Star')
    if is_morning_star(bars):       patterns.append('Morning Star')
    if is_evening_star(bars):       patterns.append('Evening Star')
    if is_doji(bars):               patterns.append('Doji')

    score = mom*2 + cs*2
    if m=='BUY': score+=2
    elif m=='SELL': score-=2
    if v=='BUY': score+=1
    elif v=='SELL': score-=1
    if b=='BUY': score+=1
    elif b=='SELL': score-=1
    if e=='BUY': score+=1
    elif e=='SELL': score-=1
    if r_val < 40: score+=1
    elif r_val > 60: score-=1

    signal = 'BUY' if score >= 3 else 'SELL' if score <= -3 else 'HOLD'

    return {
        'signal':   signal,
        'score':    score,
        'rsi':      r_val,
        'macd':     m,
        'vwap':     v,
        'bollinger':b,
        'ema':      e,
        'patterns': patterns if patterns else ['None'],
    }


# ─── SLC Strategy (Structure + Level + Confirmation) ─────────────────────────

def stochastic(bars: pd.DataFrame, k_period=14, d_period=3):
    """Stochastic oscillator — returns %K and %D"""
    low_min  = bars['low'].rolling(k_period).min()
    high_max = bars['high'].rolling(k_period).max()
    k = 100 * (bars['close'] - low_min) / (high_max - low_min).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k, d


def htf_structure(bars_htf: pd.DataFrame) -> str:
    """
    Determine higher timeframe trend structure.
    Higher highs + higher lows = uptrend (bullish).
    Lower highs + lower lows = downtrend (bearish).
    Uses last 3 swing points on the HTF bars.
    """
    if len(bars_htf) < 10:
        return 'neutral'

    highs = bars_htf['high'].values
    lows  = bars_htf['low'].values

    # Compare last 3 highs and lows
    hh = highs[-1] > highs[-5] > highs[-10]  # higher highs
    hl = lows[-1]  > lows[-5]  > lows[-10]   # higher lows
    lh = highs[-1] < highs[-5] < highs[-10]  # lower highs
    ll = lows[-1]  < lows[-5]  < lows[-10]   # lower lows

    if hh and hl:
        return 'bullish'
    if lh and ll:
        return 'bearish'
    return 'neutral'


def find_supply_demand_zones(bars: pd.DataFrame, lookback=50) -> dict:
    """
    Identify supply and demand zones from aggressive price moves.
    Supply zone: origin of a sharp aggressive drop (strong sell pressure).
    Demand zone: origin of a sharp aggressive rally (strong buy pressure).
    Returns the most recent valid zones.
    """
    if len(bars) < lookback:
        lookback = len(bars)

    recent = bars.tail(lookback).copy()
    recent['body'] = abs(recent['close'] - recent['open'])
    recent['range'] = recent['high'] - recent['low']
    avg_body = recent['body'].mean()

    supply_zones = []
    demand_zones = []

    for i in range(2, len(recent) - 1):
        row  = recent.iloc[i]
        body = row['body']
        # Aggressive bearish candle = supply zone
        if row['close'] < row['open'] and body > avg_body * 1.5:
            supply_zones.append({
                'top':    row['high'],
                'bottom': row['open'],  # top of bearish candle body
                'index':  i,
            })
        # Aggressive bullish candle = demand zone
        if row['close'] > row['open'] and body > avg_body * 1.5:
            demand_zones.append({
                'top':    row['close'],
                'bottom': row['low'],
                'index':  i,
            })

    # Return most recent untested zones
    return {
        'supply': supply_zones[-3:] if supply_zones else [],
        'demand': demand_zones[-3:] if demand_zones else [],
    }


def stoch_confirmation(bars: pd.DataFrame, side: str) -> bool:
    """
    SLC confirmation using Stochastic crossover at supply/demand zone.
    BUY confirmation:  stoch was oversold (<20) and %K crosses back above %D
    SELL confirmation: stoch was overbought (>80) and %K crosses back below %D
    """
    if len(bars) < 20:
        return False

    k, d = stochastic(bars)
    k_now  = k.iloc[-1]
    k_prev = k.iloc[-2]
    d_now  = d.iloc[-1]
    d_prev = d.iloc[-2]

    if side == 'BUY':
        # Was oversold, now crossing back up
        was_oversold = k.iloc[-4:-1].min() < 25
        cross_up     = k_prev <= d_prev and k_now > d_now
        return bool(was_oversold and cross_up)

    if side == 'SELL':
        # Was overbought, now crossing back down
        was_overbought = k.iloc[-4:-1].max() > 75
        cross_down     = k_prev >= d_prev and k_now < d_now
        return bool(was_overbought and cross_down)

    return False


def price_at_zone(price: float, zones: list, tolerance: float = 0.003) -> bool:
    """Check if current price is within tolerance % of any zone."""
    for z in zones:
        zone_mid = (z['top'] + z['bottom']) / 2
        if abs(price - zone_mid) / zone_mid <= tolerance:
            return True
        if z['bottom'] <= price <= z['top']:
            return True
    return False


def slc_signal(bars_5m: pd.DataFrame, bars_htf: pd.DataFrame) -> str:
    """
    Full SLC strategy signal.
    S — Structure:    HTF trend direction
    L — Level:        Price at supply or demand zone
    C — Confirmation: Stochastic crossover confirming rejection
    Returns BUY, SELL, or HOLD.
    """
    if bars_5m.empty or len(bars_5m) < 20:
        return 'HOLD'

    structure = htf_structure(bars_htf if not bars_htf.empty else bars_5m)
    if structure == 'neutral':
        return 'HOLD'  # no clear trend — don't trade

    price = float(bars_5m['close'].iloc[-1])
    zones = find_supply_demand_zones(bars_5m)

    if structure == 'bullish':
        # Only look for BUY setups at demand zones
        if price_at_zone(price, zones['demand']):
            if stoch_confirmation(bars_5m, 'BUY'):
                return 'BUY'

    if structure == 'bearish':
        # Only look for SELL setups at supply zones
        if price_at_zone(price, zones['supply']):
            if stoch_confirmation(bars_5m, 'SELL'):
                return 'SELL'

    return 'HOLD'
