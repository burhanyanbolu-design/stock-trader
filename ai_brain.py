"""
AI Trading Brain — connects NewsAPI + OpenAI GPT-4o
Runs every morning before market open to generate the day's strategy.
"""
import os, json, logging, requests, threading
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openai import OpenAI
from macro import get_watchlist, get_morning_briefing  # pure data layer — safe to import at top

load_dotenv()
log = logging.getLogger('ai_brain')

NEWS_API_KEY   = os.getenv('NEWS_API_KEY', '')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')

# _cache_lock guards all reads and writes.
# Flask request threads and the APScheduler thread can all call
# run_morning_briefing() concurrently.
_cache_lock = threading.Lock()
_cache = {
    'briefing':     None,
    'generated_at': None,
    'watchlist':    [],
    'sentiment':    'neutral',
    'risk_level':   'moderate',
    'headlines':    [],
    'reasoning':    '',
    'sectors':      [],
    'avoid':        [],
}

SYSTEM_PROMPT = """You are an expert quantitative trading analyst and macro economist.
You analyse financial news and market conditions to generate day trading strategies.

Your response must be valid JSON with this exact structure:
{
  "sentiment": "bullish" | "bearish" | "neutral",
  "risk_level": "aggressive" | "moderate" | "conservative",
  "market_mode": "risk_on" | "risk_off" | "neutral",
  "sectors_to_buy": ["list of sectors or ETF names to favour today"],
  "sectors_to_avoid": ["list of sectors to avoid today"],
  "stocks_to_watch": ["up to 15 specific stock tickers to focus on"],
  "stocks_to_avoid": ["specific tickers to avoid today"],
  "reasoning": "2-3 sentence explanation of your analysis",
  "key_risks": ["list of 2-3 key risks to watch today"],
  "confidence": 1-10
}

Focus on day trading opportunities — momentum, breakouts, sector rotation.
Consider: geopolitical events, Fed policy, earnings, oil/gold/dollar moves.
Be specific with tickers. Think about what will MOVE today, not long-term holds."""


def fetch_headlines() -> list:
    if not NEWS_API_KEY:
        log.warning("No NEWS_API_KEY set — skipping headlines")
        return []
    try:
        r = requests.get(
            "https://newsapi.org/v2/top-headlines",
            params={'category': 'business', 'language': 'en',
                    'pageSize': 20, 'apiKey': NEWS_API_KEY},
            timeout=10
        )
        articles = r.json().get('articles', [])

        r2 = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                'q': 'stock market OR Fed OR oil price OR earnings OR S&P 500',
                'language': 'en', 'sortBy': 'publishedAt', 'pageSize': 20,
                'from': (datetime.now() - timedelta(hours=12)).strftime('%Y-%m-%dT%H:%M:%S'),
                'apiKey': NEWS_API_KEY
            },
            timeout=10
        )
        articles2 = r2.json().get('articles', [])

        return [
            f"{a['title']} — {a.get('description','')[:100]}"
            for a in (articles + articles2)
            if a.get('title') and '[Removed]' not in a.get('title', '')
        ][:30]
    except Exception as e:
        log.error(f"NewsAPI error: {e}")
        return []


def generate_strategy(headlines: list) -> dict:
    if not OPENAI_API_KEY:
        log.warning("No OPENAI_API_KEY — skipping AI strategy")
        return None
    try:
        client    = OpenAI(api_key=OPENAI_API_KEY)
        today     = datetime.now().strftime('%A %B %d, %Y')
        news_text = '\n'.join([f"• {h}" for h in headlines]) if headlines else "No headlines available."
        response  = client.chat.completions.create(
            model='gpt-4o',
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user',   'content': f"Today is {today}.\n\n{news_text}\n\nGenerate a day trading strategy brief in JSON format."}
            ],
            max_tokens=800,
            temperature=0.3,
            response_format={'type': 'json_object'}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        log.error(f"OpenAI error: {e}")
        return None


def build_watchlist_from_strategy(strategy: dict) -> list:
    stocks = set()
    for ticker in strategy.get('stocks_to_watch', []):
        stocks.add(ticker.upper().strip())

    sector_map = {
        'technology': ['AAPL','MSFT','GOOGL','NVDA','AMD','META'],
        'energy':     ['XOM','CVX','COP','XLE'],
        'finance':    ['JPM','BAC','GS','XLF'],
        'healthcare': ['JNJ','PFE','UNH','XLV'],
        'consumer':   ['AMZN','WMT','NFLX','XLY'],
        'defence':    ['LMT','RTX','NOC'],
        'gold':       ['GLD','GDX','NEM'],
        'airlines':   ['DAL','UAL','AAL'],
        'crypto':     ['MSTR'],
        'etf':        ['SPY','QQQ','IWM'],
    }
    for sector in strategy.get('sectors_to_buy', []):
        for key, tickers in sector_map.items():
            if key in sector.lower():
                stocks.update(tickers)

    for ticker in strategy.get('stocks_to_avoid', []):
        stocks.discard(ticker.upper().strip())

    stocks.update(['SPY', 'QQQ', 'IWM'])
    return list(stocks)


def run_morning_briefing() -> dict:
    """
    Thread-safe double-checked locking pattern:
    1. Acquire lock → check cache → release (fast path, no API calls).
    2. Fetch news + call OpenAI with NO lock held (slow network I/O).
    3. Acquire lock → double-check nobody else wrote → update → release.
    """
    global _cache
    now = datetime.now()

    # ── Fast path ─────────────────────────────────────────────────────────────
    with _cache_lock:
        if (_cache['generated_at'] and
                _cache['generated_at'].date() == now.date() and
                _cache['briefing']):
            return _cache.copy()

    # ── Slow path: network I/O without lock ───────────────────────────────────
    log.info("Running AI morning briefing...")
    headlines = fetch_headlines()
    log.info(f"Fetched {len(headlines)} headlines")
    strategy  = generate_strategy(headlines)

    if strategy:
        watchlist = build_watchlist_from_strategy(strategy)
        new_data  = {
            'briefing':     strategy,
            'generated_at': now,
            'watchlist':    watchlist,
            'sentiment':    strategy.get('sentiment', 'neutral'),
            'risk_level':   strategy.get('risk_level', 'moderate'),
            'market_mode':  strategy.get('market_mode', 'neutral'),
            'headlines':    headlines[:10],
            'reasoning':    strategy.get('reasoning', ''),
            'sectors':      strategy.get('sectors_to_buy', []),
            'avoid':        strategy.get('stocks_to_avoid', []),
            'key_risks':    strategy.get('key_risks', []),
            'confidence':   strategy.get('confidence', 5),
        }
        log.info(f"AI strategy: {strategy.get('sentiment')} | {len(watchlist)} stocks")
    else:
        fallback = get_morning_briefing()
        new_data = {
            'briefing':     None,
            'generated_at': now,
            'watchlist':    get_watchlist(),
            'sentiment':    'neutral',
            'risk_level':   'moderate',
            'market_mode':  fallback.get('market_mode', 'neutral'),
            'headlines':    headlines[:10],
            'reasoning':    'AI unavailable — using macro rules',
            'sectors':      fallback.get('conditions', []),
            'avoid':        [],
            'key_risks':    [],
            'confidence':   3,
        }

    # ── Write path: re-acquire, double-check, update ──────────────────────────
    with _cache_lock:
        if (_cache['generated_at'] and
                _cache['generated_at'].date() == now.date() and
                _cache['briefing']):
            log.info("Briefing written by another thread while fetching — discarding duplicate")
            return _cache.copy()
        _cache.update(new_data)
        return _cache.copy()


def get_current_watchlist() -> list:
    try:
        return run_morning_briefing().get('watchlist', [])
    except Exception as e:
        log.warning(f"get_current_watchlist failed: {e}")
        return []


def get_dashboard_data() -> dict:
    b = run_morning_briefing()
    return {
        'sentiment':    b.get('sentiment', 'neutral'),
        'risk_level':   b.get('risk_level', 'moderate'),
        'market_mode':  b.get('market_mode', 'neutral'),
        'reasoning':    b.get('reasoning', ''),
        'sectors':      b.get('sectors', []),
        'avoid':        b.get('avoid', []),
        'key_risks':    b.get('key_risks', []),
        'confidence':   b.get('confidence', 5),
        'headlines':    b.get('headlines', []),
        'watchlist':    b.get('watchlist', []),
        'generated_at': b['generated_at'].strftime('%H:%M') if b.get('generated_at') else 'Not yet',
        'ai_powered':   b.get('briefing') is not None,
    }
