"""Instrument catalog. USD cash-only arcade trading remains intentionally restricted.

The catalog is a search namespace, not a guarantee that a provider supports
every ticker/date. Actual OHLCV availability is checked before any round starts.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Instrument:
    id: str
    ticker: str
    kind: str
    currency: str = "USD"
    tradable: bool = True
    decimals: int = 2
    spread_bps: float = 5.0
    name: str = ""

INSTRUMENTS: dict[str, Instrument] = {}

def add(identifier: str, ticker: str, category: str, name: str,
        currency: str = "USD", tradable: bool = True,
        decimals: int = 2, spread_bps: float = 5.0) -> None:
    INSTRUMENTS[identifier] = Instrument(identifier, ticker, category, currency,
                                          tradable, decimals, spread_bps, name)

add("aapl", "AAPL", "Stocks", "Apple", spread_bps=5)
add("msft", "MSFT", "Stocks", "Microsoft", spread_bps=5)
add("nvda", "NVDA", "Stocks", "Nvidia", spread_bps=10)
add("googl", "GOOGL", "Stocks", "Alphabet Class A", spread_bps=5)
add("goog", "GOOG", "Stocks", "Alphabet Class C", spread_bps=5)
add("amzn", "AMZN", "Stocks", "Amazon", spread_bps=5)
add("meta", "META", "Stocks", "Meta Platforms", spread_bps=5)
add("tsla", "TSLA", "Stocks", "Tesla", spread_bps=10)
add("amd", "AMD", "Stocks", "Advanced Micro Devices", spread_bps=10)
add("intc", "INTC", "Stocks", "Intel", spread_bps=5)
add("avgo", "AVGO", "Stocks", "Broadcom", spread_bps=5)
add("qcom", "QCOM", "Stocks", "Qualcomm", spread_bps=5)
add("mu", "MU", "Stocks", "Micron Technology", spread_bps=5)
add("orcl", "ORCL", "Stocks", "Oracle", spread_bps=5)
add("crm", "CRM", "Stocks", "Salesforce", spread_bps=5)
add("adbe", "ADBE", "Stocks", "Adobe", spread_bps=5)
add("nflx", "NFLX", "Stocks", "Netflix", spread_bps=5)
add("pltr", "PLTR", "Stocks", "Palantir", spread_bps=10)
add("snow", "SNOW", "Stocks", "Snowflake", spread_bps=10)
add("uber", "UBER", "Stocks", "Uber", spread_bps=5)
add("coin", "COIN", "Stocks", "Coinbase Global", spread_bps=10)
add("hood", "HOOD", "Stocks", "Robinhood Markets", spread_bps=10)
add("pypl", "PYPL", "Stocks", "PayPal", spread_bps=5)
add("sq", "SQ", "Stocks", "Block", spread_bps=5)
add("jpm", "JPM", "Stocks", "JPMorgan Chase", spread_bps=5)
add("bac", "BAC", "Stocks", "Bank of America", spread_bps=5)
add("gs", "GS", "Stocks", "Goldman Sachs", spread_bps=5)
add("ms", "MS", "Stocks", "Morgan Stanley", spread_bps=5)
add("c", "C", "Stocks", "Citigroup", spread_bps=5)
add("wfc", "WFC", "Stocks", "Wells Fargo", spread_bps=5)
add("v", "V", "Stocks", "Visa", spread_bps=5)
add("ma", "MA", "Stocks", "Mastercard", spread_bps=5)
add("brkb", "BRK-B", "Stocks", "Berkshire Hathaway B", spread_bps=5)
add("unh", "UNH", "Stocks", "UnitedHealth", spread_bps=5)
add("jnj", "JNJ", "Stocks", "Johnson & Johnson", spread_bps=5)
add("lly", "LLY", "Stocks", "Eli Lilly", spread_bps=5)
add("abbv", "ABBV", "Stocks", "AbbVie", spread_bps=5)
add("pfe", "PFE", "Stocks", "Pfizer", spread_bps=5)
add("wmt", "WMT", "Stocks", "Walmart", spread_bps=5)
add("cost", "COST", "Stocks", "Costco", spread_bps=5)
add("hd", "HD", "Stocks", "Home Depot", spread_bps=5)
add("dis", "DIS", "Stocks", "Walt Disney", spread_bps=5)
add("nke", "NKE", "Stocks", "Nike", spread_bps=5)
add("ba", "BA", "Stocks", "Boeing", spread_bps=5)
add("cat", "CAT", "Stocks", "Caterpillar", spread_bps=5)
add("ge", "GE", "Stocks", "GE Aerospace", spread_bps=5)
add("f", "F", "Stocks", "Ford", spread_bps=5)
add("gm", "GM", "Stocks", "General Motors", spread_bps=5)
add("xom", "XOM", "Stocks", "Exxon Mobil", spread_bps=5)
add("cvx", "CVX", "Stocks", "Chevron", spread_bps=5)
add("ko", "KO", "Stocks", "Coca-Cola", spread_bps=5)
add("pep", "PEP", "Stocks", "PepsiCo", spread_bps=5)
add("mcd", "MCD", "Stocks", "McDonald's", spread_bps=5)
add("baba", "BABA", "Stocks", "Alibaba ADR", spread_bps=10)
add("tsm", "TSM", "Stocks", "TSMC ADR", spread_bps=5)
add("nvo", "NVO", "Stocks", "Novo Nordisk ADR", spread_bps=5)
add("spy", "SPY", "ETFs", "SPDR S&P 500 ETF", spread_bps=4)
add("qqq", "QQQ", "ETFs", "Invesco QQQ Trust", spread_bps=4)
add("voo", "VOO", "ETFs", "Vanguard S&P 500 ETF", spread_bps=4)
add("vti", "VTI", "ETFs", "Vanguard Total Stock Market", spread_bps=4)
add("iwm", "IWM", "ETFs", "iShares Russell 2000", spread_bps=4)
add("dia", "DIA", "ETFs", "SPDR Dow Jones", spread_bps=4)
add("xlk", "XLK", "ETFs", "Technology Select SPDR", spread_bps=4)
add("xlf", "XLF", "ETFs", "Financial Select SPDR", spread_bps=4)
add("xle", "XLE", "ETFs", "Energy Select SPDR", spread_bps=4)
add("xlv", "XLV", "ETFs", "Health Care Select SPDR", spread_bps=4)
add("soxx", "SOXX", "ETFs", "iShares Semiconductor", spread_bps=4)
add("smh", "SMH", "ETFs", "VanEck Semiconductor", spread_bps=4)
add("arkk", "ARKK", "ETFs", "ARK Innovation", spread_bps=4)
add("tlt", "TLT", "ETFs", "iShares 20+ Year Treasuries", spread_bps=4)
add("ief", "IEF", "ETFs", "iShares 7-10 Year Treasuries", spread_bps=4)
add("shy", "SHY", "ETFs", "iShares 1-3 Year Treasuries", spread_bps=4)
add("gld", "GLD", "ETFs", "SPDR Gold", spread_bps=4)
add("slv", "SLV", "ETFs", "iShares Silver", spread_bps=4)
add("uso", "USO", "ETFs", "United States Oil", spread_bps=4)
add("eem", "EEM", "ETFs", "iShares Emerging Markets", spread_bps=4)
add("efa", "EFA", "ETFs", "iShares EAFE", spread_bps=4)
add("vea", "VEA", "ETFs", "Vanguard Developed Markets", spread_bps=4)
add("vwo", "VWO", "ETFs", "Vanguard Emerging Markets", spread_bps=4)
add("hyg", "HYG", "ETFs", "iShares High Yield Bonds", spread_bps=4)
add("lqd", "LQD", "ETFs", "iShares Investment Grade Bonds", spread_bps=4)
add("schd", "SCHD", "ETFs", "Schwab Dividend Equity", spread_bps=4)
add("vym", "VYM", "ETFs", "Vanguard High Dividend Yield", spread_bps=4)
add("vnq", "VNQ", "ETFs", "Vanguard Real Estate", spread_bps=4)
add("bnd", "BND", "ETFs", "Vanguard Total Bond", spread_bps=4)
add("ibit", "IBIT", "ETFs", "iShares Bitcoin Trust", spread_bps=4)
add("btcusd", "BTC-USD", "Crypto", "Bitcoin / US Dollar", spread_bps=12)
add("ethusd", "ETH-USD", "Crypto", "Ethereum / US Dollar", spread_bps=12)
add("solusd", "SOL-USD", "Crypto", "Solana / US Dollar", spread_bps=12)
add("xrpusd", "XRP-USD", "Crypto", "XRP / US Dollar", spread_bps=12)
add("adausd", "ADA-USD", "Crypto", "Cardano / US Dollar", spread_bps=12)
add("dogeusd", "DOGE-USD", "Crypto", "Dogecoin / US Dollar", spread_bps=12)
add("ltcusd", "LTC-USD", "Crypto", "Litecoin / US Dollar", spread_bps=12)
add("bchusd", "BCH-USD", "Crypto", "Bitcoin Cash / US Dollar", spread_bps=12)
add("linkusd", "LINK-USD", "Crypto", "Chainlink / US Dollar", spread_bps=12)
add("avaxusd", "AVAX-USD", "Crypto", "Avalanche / US Dollar", spread_bps=12)
add("uniusd", "UNI-USD", "Crypto", "Uniswap / US Dollar", spread_bps=12)
add("aaveusd", "AAVE-USD", "Crypto", "Aave / US Dollar", spread_bps=12)
add("dotusd", "DOT-USD", "Crypto", "Polkadot / US Dollar", spread_bps=12)
add("atomusd", "ATOM-USD", "Crypto", "Cosmos / US Dollar", spread_bps=12)
add("shibusd", "SHIB-USD", "Crypto", "Shiba Inu / US Dollar", spread_bps=12)
add("nearusd", "NEAR-USD", "Crypto", "NEAR Protocol / US Dollar", spread_bps=12)
add("filusd", "FIL-USD", "Crypto", "Filecoin / US Dollar", spread_bps=12)
add("etcusd", "ETC-USD", "Crypto", "Ethereum Classic / US Dollar", spread_bps=12)
add("algousd", "ALGO-USD", "Crypto", "Algorand / US Dollar", spread_bps=12)
add("xlmusd", "XLM-USD", "Crypto", "Stellar / US Dollar", spread_bps=12)
add("eurusd", "EURUSD=X", "Forex", "Euro / US Dollar", currency="USD", tradable=True, decimals=5, spread_bps=2)
add("gbpusd", "GBPUSD=X", "Forex", "British Pound / US Dollar", currency="USD", tradable=True, decimals=5, spread_bps=2)
add("usdjpy", "USDJPY=X", "Forex", "US Dollar / Japanese Yen", currency="JPY", tradable=False, decimals=3, spread_bps=2)
add("usdchf", "USDCHF=X", "Forex", "US Dollar / Swiss Franc", currency="CHF", tradable=False, decimals=5, spread_bps=2)
add("usdcad", "USDCAD=X", "Forex", "US Dollar / Canadian Dollar", currency="CAD", tradable=False, decimals=5, spread_bps=2)
add("audusd", "AUDUSD=X", "Forex", "Australian Dollar / US Dollar", currency="USD", tradable=True, decimals=5, spread_bps=2)
add("nzdusd", "NZDUSD=X", "Forex", "New Zealand Dollar / US Dollar", currency="USD", tradable=True, decimals=5, spread_bps=2)
add("eurgbp", "EURGBP=X", "Forex", "Euro / British Pound", currency="GBP", tradable=False, decimals=5, spread_bps=2)
add("eurjpy", "EURJPY=X", "Forex", "Euro / Japanese Yen", currency="JPY", tradable=False, decimals=3, spread_bps=2)
add("gbpjpy", "GBPJPY=X", "Forex", "British Pound / Japanese Yen", currency="JPY", tradable=False, decimals=3, spread_bps=2)
add("vfv", "VFV.TO", "ETFs", "Vanguard S&P 500 CAD", currency="CAD", tradable=False)
add("xiu", "XIU.TO", "ETFs", "iShares S&P TSX 60", currency="CAD", tradable=False)
add("xeqt", "XEQT.TO", "ETFs", "iShares All Equity", currency="CAD", tradable=False)
add("vgro", "VGRO.TO", "ETFs", "Vanguard Growth ETF", currency="CAD", tradable=False)
add("vdy", "VDY.TO", "ETFs", "Vanguard FTSE Canadian Dividend", currency="CAD", tradable=False)
add("xqq", "XQQ.TO", "ETFs", "iShares NASDAQ 100 CAD", currency="CAD", tradable=False)
add("ry", "RY.TO", "Stocks", "Royal Bank of Canada", currency="CAD", tradable=False)
add("td", "TD.TO", "Stocks", "Toronto Dominion Bank", currency="CAD", tradable=False)
add("shop", "SHOP.TO", "Stocks", "Shopify TSX", currency="CAD", tradable=False)
add("cnr", "CNR.TO", "Stocks", "Canadian National Railway", currency="CAD", tradable=False)
add("es", "ES=F", "Futures", "E-mini S&P 500 continuous", tradable=False)
add("nq", "NQ=F", "Futures", "E-mini Nasdaq 100 continuous", tradable=False)
add("ym", "YM=F", "Futures", "E-mini Dow continuous", tradable=False)
add("rty", "RTY=F", "Futures", "E-mini Russell 2000 continuous", tradable=False)
add("cl", "CL=F", "Futures", "WTI Crude Oil continuous", tradable=False)
add("gc", "GC=F", "Futures", "COMEX Gold continuous", tradable=False)
add("si", "SI=F", "Futures", "COMEX Silver continuous", tradable=False)
add("ng", "NG=F", "Futures", "Natural Gas continuous", tradable=False)
add("zb", "ZB=F", "Futures", "US Treasury Bond continuous", tradable=False)
add("zn", "ZN=F", "Futures", "10-Year Treasury Note continuous", tradable=False)
# Contract-less placeholders are chart-disabled until an actual option chain exists.
add("aapl-opt", "", "Options", "AAPL option placeholder", tradable=False)
add("spy-opt", "", "Options", "SPY option placeholder", tradable=False)

def get_instrument(asset_id: str) -> Instrument:
    from fastapi import HTTPException
    instrument = INSTRUMENTS.get(asset_id)
    if instrument is None:
        raise HTTPException(404, detail="Unknown instrument.")
    return instrument

def list_instruments(search: str = "", category: str = "", limit: int = 150) -> list[dict]:
    needle = search.strip().lower()
    result = []
    for instrument in INSTRUMENTS.values():
        if category and instrument.kind.lower() != category.lower():
            continue
        if needle and needle not in (instrument.id + " " + instrument.ticker + " " + instrument.name).lower():
            continue
        result.append({
            "id": instrument.id, "symbol": instrument.ticker,
            "name": instrument.name, "asset_class": instrument.kind,
            "currency": instrument.currency, "tradable": instrument.tradable,
            "decimals": instrument.decimals,
        })
        if len(result) >= min(max(1, limit), 250):
            break
    return result
