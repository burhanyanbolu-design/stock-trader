"""
Macro Intelligence Layer — NO external imports allowed here.
Dependency order: macro.py → strategies.py → ai_brain.py → trader.py → app.py
macro.py must stay at the bottom of the import chain.
"""

# ── Current Macro Context (update this daily) ─────────────────────────────────
MACRO = {
    'oil':        'falling',    # rising / falling / stable
    'gold':       'high',       # high / falling / stable
    'dollar':     'weak',       # strong / weak / stable
    'market':     'risk_on',    # risk_on / risk_off / neutral
    'geopolitical': 'easing',   # tension / easing / stable
    'notes': 'US-Iran ceasefire announced. Oil crashed 15%. S&P rallying. Relief rally in progress.'
}

# ── Sector watchlists by macro condition ──────────────────────────────────────

# Risk-on: buy growth, tech, consumer discretionary
RISK_ON = [
    'AAPL','MSFT','GOOGL','AMZN','NVDA','META','TSLA','AMD',
    'NFLX','DIS','SHOP','PLTR','UBER',
    'SPY','QQQ','IWM',
]

# Risk-off: buy defensives, gold, bonds
RISK_OFF = [
    'GLD','SLV',        # gold/silver ETFs
    'XOM','CVX',        # energy
    'LMT','RTX','NOC',  # defence
    'JNJ','PFE','UNH',  # healthcare
    'WMT','PG','KO',    # consumer staples
]

# Oil falling: airlines, transport, consumer benefit
OIL_FALLING = [
    'DAL','UAL','AAL',  # airlines
    'FDX','UPS',        # logistics
    'AMZN','WMT',       # retail (lower shipping costs)
    'TSLA',             # EV (less oil competition)
]

# Oil rising: energy stocks
OIL_RISING = [
    'XOM','CVX','COP','SLB','HAL',
    'XLE',  # energy ETF
]

# Gold high: miners, safe havens
GOLD_HIGH = [
    'GLD','GDX','GDXJ',  # gold ETFs and miners
    'NEM','GOLD','AEM',
]

# Weak dollar: multinationals, commodities
WEAK_DOLLAR = [
    'AAPL','MSFT','GOOGL','AMZN',  # big multinationals earn more abroad
    'GLD','SLV','USO',              # commodities priced in USD go up
]


def get_watchlist() -> list:
    """
    Build today's watchlist based on current macro conditions.
    Returns ranked list — best opportunities first.
    """
    stocks = set()

    if MACRO['market'] == 'risk_on':
        stocks.update(RISK_ON)
    elif MACRO['market'] == 'risk_off':
        stocks.update(RISK_OFF)
    else:
        stocks.update(RISK_ON[:10])
        stocks.update(RISK_OFF[:5])

    if MACRO['oil'] == 'falling':
        stocks.update(OIL_FALLING)
        # Remove pure energy plays when oil falling
        for s in ['XOM','CVX','COP','SLB','HAL','XLE']:
            stocks.discard(s)
    elif MACRO['oil'] == 'rising':
        stocks.update(OIL_RISING)

    if MACRO['gold'] == 'high':
        stocks.update(GOLD_HIGH)

    if MACRO['dollar'] == 'weak':
        stocks.update(WEAK_DOLLAR)

    # Always include broad market ETFs
    stocks.update(['SPY','QQQ','IWM'])

    return list(stocks)


def get_morning_briefing() -> dict:
    """Returns macro summary for dashboard display."""
    watchlist = get_watchlist()
    
    conditions = []
    if MACRO['oil'] == 'falling':
        conditions.append('🛢️ Oil falling → Airlines & transport favoured')
    elif MACRO['oil'] == 'rising':
        conditions.append('🛢️ Oil rising → Energy stocks favoured')
    
    if MACRO['gold'] == 'high':
        conditions.append('🥇 Gold elevated → Safe haven demand')
    
    if MACRO['dollar'] == 'weak':
        conditions.append('💵 Weak dollar → Multinationals & commodities benefit')
    
    if MACRO['market'] == 'risk_on':
        conditions.append('📈 Risk-on → Growth & tech favoured')
    elif MACRO['market'] == 'risk_off':
        conditions.append('🛡️ Risk-off → Defensives & safe havens favoured')
    
    if MACRO['geopolitical'] == 'easing':
        conditions.append('🕊️ Geopolitical easing → Relief rally in progress')
    elif MACRO['geopolitical'] == 'tension':
        conditions.append('⚠️ Geopolitical tension → Caution advised')

    return {
        'conditions': conditions,
        'notes': MACRO['notes'],
        'watchlist_count': len(watchlist),
        'market_mode': MACRO['market'],
    }
