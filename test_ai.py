from dotenv import load_dotenv
load_dotenv()
import os

print("=== API KEY CHECK ===")
print(f"OpenAI:  {'SET ✓' if os.getenv('OPENAI_API_KEY') else 'MISSING ✗'}")
print(f"NewsAPI: {'SET ✓' if os.getenv('NEWS_API_KEY') else 'MISSING ✗'}")
print(f"Alpaca:  {'SET ✓' if os.getenv('ALPACA_API_KEY') else 'MISSING ✗'}")

print("\n=== FETCHING HEADLINES ===")
from ai_brain import fetch_headlines
headlines = fetch_headlines()
print(f"Got {len(headlines)} headlines")
for h in headlines[:5]:
    print(f"  • {h[:100]}")

print("\n=== GENERATING AI STRATEGY ===")
from ai_brain import generate_strategy
strategy = generate_strategy(headlines)
if strategy:
    print(f"Sentiment:   {strategy.get('sentiment')}")
    print(f"Risk level:  {strategy.get('risk_level')}")
    print(f"Market mode: {strategy.get('market_mode')}")
    print(f"Confidence:  {strategy.get('confidence')}/10")
    print(f"Reasoning:   {strategy.get('reasoning')}")
    print(f"Watch:       {strategy.get('stocks_to_watch')}")
    print(f"Avoid:       {strategy.get('stocks_to_avoid')}")
    print(f"Key risks:   {strategy.get('key_risks')}")
else:
    print("Strategy generation failed")

print("\n=== FINAL WATCHLIST ===")
from ai_brain import get_current_watchlist
watchlist = get_current_watchlist()
print(f"Trading {len(watchlist)} stocks today: {watchlist}")
