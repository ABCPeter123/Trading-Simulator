"""Instrument catalog. USD cash-only arcade trading remains intentionally restricted.

The catalog is a search namespace, not a guarantee that a provider supports
every ticker/date. Actual OHLCV availability is checked before any round starts.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from threading import RLock

import yfinance as yf

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
# Expanded public reference universe for cross-asset research. Symbols are
# provider identifiers, not guarantees of active listings or full OHLCV history.
# Leveraged ETFs and continuous futures have path/roll risks and are research
# references; no derivative or multi-currency broker execution is enabled.
add("spym", "SPYM", "ETFs", "State Street SPDR Portfolio S&P 500")
add("ivv", "IVV", "ETFs", "iShares Core S&P 500")
add("schb", "SCHB", "ETFs", "Schwab Broad US Market")
add("itot", "ITOT", "ETFs", "iShares Core S&P Total US Stock")
add("vug", "VUG", "ETFs", "Vanguard Growth")
add("vtv", "VTV", "ETFs", "Vanguard Value")
add("iwd", "IWD", "ETFs", "Russell 1000 Value")
add("iwf", "IWF", "ETFs", "Russell 1000 Growth")
add("ijh", "IJH", "ETFs", "S&P Mid-Cap 400")
add("ijr", "IJR", "ETFs", "S&P Small-Cap 600")
add("vb", "VB", "ETFs", "Vanguard Small-Cap")
add("vxus", "VXUS", "ETFs", "Vanguard Total International Stock")
add("vt", "VT", "ETFs", "Vanguard Total World Stock")
add("vgt", "VGT", "ETFs", "Vanguard Information Technology")
add("xli", "XLI", "ETFs", "Industrial Select Sector SPDR")
add("xlb", "XLB", "ETFs", "Materials Select Sector SPDR")
add("xlp", "XLP", "ETFs", "Consumer Staples Select Sector SPDR")
add("xly", "XLY", "ETFs", "Consumer Discretionary Select Sector SPDR")
add("xlu", "XLU", "ETFs", "Utilities Select Sector SPDR")
add("xlre", "XLRE", "ETFs", "Real Estate Select Sector SPDR")
add("xlc", "XLC", "ETFs", "Communication Services Select Sector SPDR")
add("vht", "VHT", "ETFs", "Vanguard Health Care")
add("ita", "ITA", "ETFs", "iShares US Aerospace and Defense")
add("xbi", "XBI", "ETFs", "SPDR S&P Biotech")
add("kbe", "KBE", "ETFs", "SPDR S&P Bank")
add("kre", "KRE", "ETFs", "SPDR S&P Regional Banking")
add("tan", "TAN", "ETFs", "Invesco Solar")
add("icln", "ICLN", "ETFs", "iShares Global Clean Energy")
add("pdbc", "PDBC", "ETFs", "Invesco Optimum Yield Diversified Commodity")
add("dbc", "DBC", "ETFs", "Invesco DB Commodity Index")
add("dba", "DBA", "ETFs", "Invesco DB Agriculture")
add("ung", "UNG", "ETFs", "United States Natural Gas")
add("gdx", "GDX", "ETFs", "VanEck Gold Miners")
add("gdxj", "GDXJ", "ETFs", "VanEck Junior Gold Miners")
add("sgol", "SGOL", "ETFs", "abrdn Physical Gold")
add("tip", "TIP", "ETFs", "iShares TIPS Bond")
add("vtip", "VTIP", "ETFs", "Vanguard Short-Term Inflation-Protected Securities")
add("sgov", "SGOV", "ETFs", "iShares 0-3 Month US Treasury Bond")
add("bil", "BIL", "ETFs", "SPDR Bloomberg 1-3 Month T-Bill")
add("bils", "BILS", "ETFs", "SPDR Bloomberg 3-12 Month T-Bill")
add("usfr", "USFR", "ETFs", "WisdomTree Floating Rate Treasury")
add("tflo", "TFLO", "ETFs", "iShares Treasury Floating Rate Bond")
add("vgsh", "VGSH", "ETFs", "Vanguard Short-Term Treasury")
add("vgit", "VGIT", "ETFs", "Vanguard Intermediate-Term Treasury")
add("vclt", "VCLT", "ETFs", "Vanguard Long-Term Corporate Bond")
add("vcit", "VCIT", "ETFs", "Vanguard Intermediate-Term Corporate Bond")
add("emb", "EMB", "ETFs", "iShares JP Morgan USD Emerging Markets Bond")
add("bndx", "BNDX", "ETFs", "Vanguard Total International Bond")
add("agg", "AGG", "ETFs", "iShares Core US Aggregate Bond")
add("tqqq", "TQQQ", "ETFs", "ProShares UltraPro QQQ")
add("sqqq", "SQQQ", "ETFs", "ProShares UltraPro Short QQQ")
add("upro", "UPRO", "ETFs", "ProShares UltraPro S&P 500")
add("spxu", "SPXU", "ETFs", "ProShares UltraPro Short S&P 500")
add("vixy", "VIXY", "ETFs", "ProShares VIX Short-Term Futures")
add("schh", "SCHH", "ETFs", "Schwab US REIT")
add("vnqi", "VNQI", "ETFs", "Vanguard Global ex-US Real Estate")
add("dgro", "DGRO", "ETFs", "iShares Core Dividend Growth")
add("nobl", "NOBL", "ETFs", "ProShares S&P 500 Dividend Aristocrats")
add("dvy", "DVY", "ETFs", "iShares Select Dividend")
add("jepi", "JEPI", "ETFs", "JPMorgan Equity Premium Income")
add("jepq", "JEPQ", "ETFs", "JPMorgan Nasdaq Equity Premium Income")
add("qqqm", "QQQM", "ETFs", "Invesco Nasdaq 100")
add("qual", "QUAL", "ETFs", "iShares MSCI USA Quality")
add("usmv", "USMV", "ETFs", "iShares MSCI USA Min Vol")
add("mtum", "MTUM", "ETFs", "iShares MSCI USA Momentum")
add("acwi", "ACWI", "ETFs", "iShares MSCI ACWI")
add("ewj", "EWJ", "ETFs", "iShares MSCI Japan")
add("ewc", "EWC", "ETFs", "iShares MSCI Canada")
add("ewg", "EWG", "ETFs", "iShares MSCI Germany")
add("ewz", "EWZ", "ETFs", "iShares MSCI Brazil")
add("fxi", "FXI", "ETFs", "iShares China Large-Cap")
add("kweb", "KWEB", "ETFs", "KraneShares China Internet")
add("cweb", "CWEB", "ETFs", "Direxion Daily CSI China Internet 2X")
add("vbr", "VBR", "ETFs", "Vanguard Small-Cap Value")
add("vo", "VO", "ETFs", "Vanguard Mid-Cap")
add("xbal", "XBAL.TO", "ETFs", "iShares Core Balanced", currency="CAD", tradable=False)
add("xgro", "XGRO.TO", "ETFs", "iShares Core Growth", currency="CAD", tradable=False)
add("xcns", "XCNS.TO", "ETFs", "iShares Core Conservative", currency="CAD", tradable=False)
add("xinc", "XINC.TO", "ETFs", "iShares Core Income Balanced", currency="CAD", tradable=False)
add("zbal", "ZBAL.TO", "ETFs", "BMO Balanced ETF", currency="CAD", tradable=False)
add("zgro", "ZGRO.TO", "ETFs", "BMO Growth ETF", currency="CAD", tradable=False)
add("vbal", "VBAL.TO", "ETFs", "Vanguard Balanced ETF", currency="CAD", tradable=False)
add("vcns", "VCNS.TO", "ETFs", "Vanguard Conservative ETF", currency="CAD", tradable=False)
add("veqt", "VEQT.TO", "ETFs", "Vanguard All-Equity ETF", currency="CAD", tradable=False)
add("vcn", "VCN.TO", "ETFs", "Vanguard FTSE Canada All Cap", currency="CAD", tradable=False)
add("xcn", "XCN.TO", "ETFs", "iShares Core S&P/TSX Capped Composite", currency="CAD", tradable=False)
add("zcn", "ZCN.TO", "ETFs", "BMO S&P/TSX Capped Composite", currency="CAD", tradable=False)
add("xaw", "XAW.TO", "ETFs", "iShares Core MSCI All Country ex Canada", currency="CAD", tradable=False)
add("vxc", "VXC.TO", "ETFs", "Vanguard FTSE Global All Cap ex Canada", currency="CAD", tradable=False)
add("vab", "VAB.TO", "ETFs", "Vanguard Canadian Aggregate Bond", currency="CAD", tradable=False)
add("zag", "ZAG.TO", "ETFs", "BMO Aggregate Bond", currency="CAD", tradable=False)
add("zdb", "ZDB.TO", "ETFs", "BMO Discount Bond", currency="CAD", tradable=False)
add("zst", "ZST.TO", "ETFs", "BMO Ultra Short-Term Bond", currency="CAD", tradable=False)
add("xsb", "XSB.TO", "ETFs", "iShares Core Canadian Short Term Bond", currency="CAD", tradable=False)
add("xgb", "XGB.TO", "ETFs", "iShares Canadian Government Bond", currency="CAD", tradable=False)
add("hdiv", "HDIV.TO", "ETFs", "Hamilton Enhanced Canadian Covered Call", currency="CAD", tradable=False)
add("hyld", "HYLD.TO", "ETFs", "Hamilton Enhanced US Covered Call", currency="CAD", tradable=False)
add("zeb", "ZEB.TO", "ETFs", "BMO Equal Weight Banks", currency="CAD", tradable=False)
add("xre", "XRE.TO", "ETFs", "iShares S&P/TSX Capped REIT", currency="CAD", tradable=False)
add("zre", "ZRE.TO", "ETFs", "BMO Equal Weight REITs", currency="CAD", tradable=False)
add("xeg", "XEG.TO", "ETFs", "iShares S&P/TSX Capped Energy", currency="CAD", tradable=False)
add("xfn", "XFN.TO", "ETFs", "iShares S&P/TSX Capped Financials", currency="CAD", tradable=False)
add("zsp", "ZSP.TO", "ETFs", "BMO S&P 500 Index", currency="CAD", tradable=False)
add("xus", "XUS.TO", "ETFs", "iShares Core S&P 500", currency="CAD", tradable=False)
add("vgg", "VGG.TO", "ETFs", "Vanguard US Dividend Appreciation", currency="CAD", tradable=False)
add("xef", "XEF.TO", "ETFs", "iShares Core MSCI EAFE IMI", currency="CAD", tradable=False)
add("xem", "XEM.TO", "ETFs", "iShares MSCI Emerging Markets", currency="CAD", tradable=False)
add("zqq", "ZQQ.TO", "ETFs", "BMO Nasdaq 100 Equity Hedged", currency="CAD", tradable=False)
add("hxq", "HXQ.TO", "ETFs", "Global X Nasdaq 100 Index", currency="CAD", tradable=False)
add("hxs", "HXS.TO", "ETFs", "Global X S&P 500 Index", currency="CAD", tradable=False)
add("cgl", "CGL.TO", "ETFs", "iShares Gold Bullion", currency="CAD", tradable=False)
add("xgd", "XGD.TO", "ETFs", "iShares S&P/TSX Global Gold", currency="CAD", tradable=False)
add("xdiv", "XDIV.TO", "ETFs", "iShares Core MSCI Canadian Quality Dividend", currency="CAD", tradable=False)
add("xdu", "XDU.TO", "ETFs", "iShares Core MSCI US Quality Dividend", currency="CAD", tradable=False)
add("xsu", "XSU.TO", "ETFs", "iShares US Small Cap Index", currency="CAD", tradable=False)
add("asml", "ASML", "Stocks", "ASML ADR")
add("arm", "ARM", "Stocks", "Arm Holdings ADR")
add("amat", "AMAT", "Stocks", "Applied Materials")
add("lrcx", "LRCX", "Stocks", "Lam Research")
add("klac", "KLAC", "Stocks", "KLA Corporation")
add("txn", "TXN", "Stocks", "Texas Instruments")
add("adi", "ADI", "Stocks", "Analog Devices")
add("mrvl", "MRVL", "Stocks", "Marvell Technology")
add("cdns", "CDNS", "Stocks", "Cadence Design Systems")
add("snps", "SNPS", "Stocks", "Synopsys")
add("now", "NOW", "Stocks", "ServiceNow")
add("intuit", "INTU", "Stocks", "Intuit")
add("ibm", "IBM", "Stocks", "IBM")
add("sap", "SAP", "Stocks", "SAP ADR")
add("csco", "CSCO", "Stocks", "Cisco Systems")
add("crwd", "CRWD", "Stocks", "CrowdStrike")
add("panw", "PANW", "Stocks", "Palo Alto Networks")
add("net", "NET", "Stocks", "Cloudflare")
add("ddog", "DDOG", "Stocks", "Datadog")
add("mdb", "MDB", "Stocks", "MongoDB")
add("abnb", "ABNB", "Stocks", "Airbnb")
add("bkng", "BKNG", "Stocks", "Booking Holdings")
add("spot", "SPOT", "Stocks", "Spotify")
add("duol", "DUOL", "Stocks", "Duolingo")
add("rblx", "RBLX", "Stocks", "Roblox")
add("se", "SE", "Stocks", "Sea ADR")
add("pdd", "PDD", "Stocks", "PDD Holdings ADR")
add("jd", "JD", "Stocks", "JD.com ADR")
add("bidu", "BIDU", "Stocks", "Baidu ADR")
add("bmo", "BMO.TO", "Stocks", "Bank of Montreal", currency="CAD", tradable=False)
add("bns", "BNS.TO", "Stocks", "Bank of Nova Scotia", currency="CAD", tradable=False)
add("cm", "CM.TO", "Stocks", "CIBC", currency="CAD", tradable=False)
add("na", "NA.TO", "Stocks", "National Bank of Canada", currency="CAD", tradable=False)
add("bce", "BCE.TO", "Stocks", "BCE", currency="CAD", tradable=False)
add("t", "T.TO", "Stocks", "TELUS", currency="CAD", tradable=False)
add("enb", "ENB.TO", "Stocks", "Enbridge", currency="CAD", tradable=False)
add("trp", "TRP.TO", "Stocks", "TC Energy", currency="CAD", tradable=False)
add("su", "SU.TO", "Stocks", "Suncor Energy", currency="CAD", tradable=False)
add("cnq", "CNQ.TO", "Stocks", "Canadian Natural Resources", currency="CAD", tradable=False)
add("cve", "CVE.TO", "Stocks", "Cenovus Energy", currency="CAD", tradable=False)
add("cp", "CP.TO", "Stocks", "Canadian Pacific Kansas City", currency="CAD", tradable=False)
add("atd", "ATD.TO", "Stocks", "Alimentation Couche-Tard", currency="CAD", tradable=False)
add("l", "L.TO", "Stocks", "Loblaw Companies", currency="CAD", tradable=False)
add("wcn", "WCN.TO", "Stocks", "Waste Connections", currency="CAD", tradable=False)
add("wsp", "WSP.TO", "Stocks", "WSP Global", currency="CAD", tradable=False)
add("dol", "DOL.TO", "Stocks", "Dollarama", currency="CAD", tradable=False)
add("gib", "GIB-A.TO", "Stocks", "CGI", currency="CAD", tradable=False)
add("dsg", "DSG.TO", "Stocks", "Descartes Systems Group", currency="CAD", tradable=False)
add("csu", "CSU.TO", "Stocks", "Constellation Software", currency="CAD", tradable=False)
add("mg", "MG.TO", "Stocks", "Magna International", currency="CAD", tradable=False)
add("teck", "TECK-B.TO", "Stocks", "Teck Resources", currency="CAD", tradable=False)
add("aem", "AEM.TO", "Stocks", "Agnico Eagle Mines", currency="CAD", tradable=False)
add("abx", "ABX.TO", "Stocks", "Barrick Mining", currency="CAD", tradable=False)
add("wpm", "WPM.TO", "Stocks", "Wheaton Precious Metals", currency="CAD", tradable=False)
add("fnv", "FNV.TO", "Stocks", "Franco-Nevada", currency="CAD", tradable=False)
add("pow", "POW.TO", "Stocks", "Power Corporation of Canada", currency="CAD", tradable=False)
add("mfc", "MFC.TO", "Stocks", "Manulife Financial", currency="CAD", tradable=False)
add("slf", "SLF.TO", "Stocks", "Sun Life Financial", currency="CAD", tradable=False)
add("gwo", "GWO.TO", "Stocks", "Great-West Lifeco", currency="CAD", tradable=False)
add("spx", "^GSPC", "Indices", "S&P 500 Index", tradable=False)
add("nasdaq", "^IXIC", "Indices", "Nasdaq Composite", tradable=False)
add("dji", "^DJI", "Indices", "Dow Jones Industrial Average", tradable=False)
add("russell2000", "^RUT", "Indices", "Russell 2000 Index", tradable=False)
add("vix", "^VIX", "Indices", "Cboe Volatility Index", tradable=False)
add("tsx", "^GSPTSE", "Indices", "S&P/TSX Composite", currency="CAD", tradable=False)
add("nikkei", "^N225", "Indices", "Nikkei 225", currency="JPY", tradable=False)
add("ftse100", "^FTSE", "Indices", "FTSE 100", currency="GBP", tradable=False)
add("dax", "^GDAXI", "Indices", "DAX Index", currency="EUR", tradable=False)
add("hsi", "^HSI", "Indices", "Hang Seng Index", currency="HKD", tradable=False)
add("tnx", "^TNX", "Indices", "Cboe 10Y Treasury Yield Index", tradable=False)
add("dxy", "DX-Y.NYB", "Indices", "US Dollar Index", tradable=False)
add("hg", "HG=F", "Futures", "COMEX Copper continuous", tradable=False)
add("pl", "PL=F", "Futures", "NYMEX Platinum continuous", tradable=False)
add("pa", "PA=F", "Futures", "NYMEX Palladium continuous", tradable=False)
add("zw", "ZW=F", "Futures", "CBOT Wheat continuous", tradable=False)
add("zc", "ZC=F", "Futures", "CBOT Corn continuous", tradable=False)
add("zs", "ZS=F", "Futures", "CBOT Soybeans continuous", tradable=False)
add("zq", "ZQ=F", "Futures", "30-Day Federal Funds continuous", tradable=False)
add("6e", "6E=F", "Futures", "EUR FX Futures continuous", tradable=False)
add("usdsek", "USDSEK=X", "Forex", "USD / Swedish Krona", currency="SEK", tradable=False, decimals=5, spread_bps=2)
add("usdnok", "USDNOK=X", "Forex", "USD / Norwegian Krone", currency="NOK", tradable=False, decimals=5, spread_bps=2)
add("usdcny", "USDCNY=X", "Forex", "USD / Chinese Yuan", currency="CNY", tradable=False, decimals=5, spread_bps=2)
add("usdhkd", "USDHKD=X", "Forex", "USD / Hong Kong Dollar", currency="HKD", tradable=False, decimals=5, spread_bps=2)
add("usdmxn", "USDMXN=X", "Forex", "USD / Mexican Peso", currency="MXN", tradable=False, decimals=5, spread_bps=2)
add("usdsgd", "USDSGD=X", "Forex", "USD / Singapore Dollar", currency="SGD", tradable=False, decimals=5, spread_bps=2)
add("eurchf", "EURCHF=X", "Forex", "EUR / Swiss Franc", currency="CHF", tradable=False, decimals=5, spread_bps=2)
add("eurcad", "EURCAD=X", "Forex", "EUR / Canadian Dollar", currency="CAD", tradable=False, decimals=5, spread_bps=2)

# Contract-less placeholders are chart-disabled until an actual option chain exists.
add("aapl-opt", "", "Options", "AAPL option placeholder", tradable=False)
add("spy-opt", "", "Options", "SPY option placeholder", tradable=False)

def get_instrument(asset_id: str) -> Instrument:
    from fastapi import HTTPException
    instrument = INSTRUMENTS.get(asset_id)
    if instrument is None:
        raise HTTPException(404, detail="Unknown instrument.")
    return instrument

def list_instruments(search: str = "", category: str = "", limit: int = 2000) -> list[dict]:
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
        if len(result) >= min(max(1, limit), 2000):
            break
    return result

# Optional user-imported securities live locally, never in Git. No wildcard
# remote fetch on import: Yahoo search must confirm the exact symbol.
_CUSTOM_PATH = Path(os.environ.get("TRADING_SIM_CUSTOM_INSTRUMENTS",
                 Path(__file__).resolve().parent.parent / "data" / "custom_instruments.json"))
_CUSTOM_LOCK = RLock()
_SYMBOL_PATTERN = re.compile(r"[A-Z0-9^][A-Z0-9.\-^=]{0,19}")
_ALLOWED_QUOTE_TYPES = {
    "EQUITY": "Stocks", "ETF": "ETFs",
    "FUTURE": "Futures", "INDEX": "Indices",
    "MUTUALFUND": "Funds",
}


def _restore_custom():
    try:
        stored = json.loads(_CUSTOM_PATH.read_text(encoding="utf-8"))
        for item in stored:
            symbol = str(item["ticker"])
            kind = str(item["kind"])
            if not _SYMBOL_PATTERN.fullmatch(symbol) or kind not in _ALLOWED_QUOTE_TYPES.values():
                continue
            add(str(item["id"]), symbol, kind, str(item["name"])[:120],
                currency=str(item["currency"]), tradable=bool(item["tradable"]),
                decimals=int(item.get("decimals", 2)))
    except (OSError, ValueError, KeyError, TypeError):
        return


_restore_custom()


def search_yahoo(query: str, limit: int = 12) -> list[dict]:
    from fastapi import HTTPException
    query = query.strip()
    if not 2 <= len(query) <= 60:
        raise HTTPException(422, detail="Search query must be 2-60 characters.")
    try:
        candidates = yf.Search(query, max_results=min(limit, 15),
                               news_count=0, lists_count=0, timeout=12).quotes
    except Exception as exc:
        raise HTTPException(503, detail=f"Yahoo instrument lookup unavailable: {type(exc).__name__}") from exc
    results = []
    for row in candidates:
        symbol = str(row.get("symbol") or "").upper()
        quote_type = str(row.get("quoteType") or "").upper()
        if not _SYMBOL_PATTERN.fullmatch(symbol) or quote_type not in _ALLOWED_QUOTE_TYPES:
            continue
        results.append({
            "symbol": symbol,
            "name": str(row.get("shortname") or row.get("longname") or symbol)[:120],
            "asset_class": _ALLOWED_QUOTE_TYPES[quote_type],
            "exchange": str(row.get("exchange") or "")[:30],
            "currency": str(row.get("currency") or "UNVERIFIED").upper()[:8],
        })
    return results


def import_yahoo(symbol: str) -> dict:
    from fastapi import HTTPException
    symbol = symbol.strip().upper()
    if not _SYMBOL_PATTERN.fullmatch(symbol):
        raise HTTPException(422, detail="Invalid market ticker format.")
    with _CUSTOM_LOCK:
        existing = next((i for i in INSTRUMENTS.values() if i.ticker == symbol), None)
        if existing:
            return list_instruments(existing.id, limit=1)[0]
    # Verify exact ticker in authoritative provider search. Metadata can be
    # missing, in which case the instrument is chart-only rather than guessing.
    matches = search_yahoo(symbol, 15)
    match = next((i for i in matches if i["symbol"] == symbol), None)
    if match is None:
        raise HTTPException(404, detail="Provider did not confirm this exact ticker.")
    currency = match["currency"]
    if currency == "UNVERIFIED":
        try:
            fast = yf.Ticker(symbol).fast_info
            currency = str(fast["currency"]).upper()
        except Exception:
            pass
    kind = match["asset_class"]
    tradable = kind in ("Stocks", "ETFs") and currency == "USD"
    identifier = "custom_" + sha256(symbol.encode()).hexdigest()[:12]
    item = {
        "id": identifier, "ticker": symbol, "kind": kind,
        "name": match["name"], "currency": currency,
        "tradable": tradable, "decimals": 2,
    }
    with _CUSTOM_LOCK:
        old = []
        if _CUSTOM_PATH.exists():
            try:
                old = json.loads(_CUSTOM_PATH.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                old = []
        if len(old) >= 1000:
            raise HTTPException(409, detail="Maximum 1000 imported tickers.")
        old.append(item)
        _CUSTOM_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = _CUSTOM_PATH.with_suffix(".json.tmp")
        temp.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, _CUSTOM_PATH)
        add(identifier, symbol, kind, match["name"], currency=currency, tradable=tradable)
    return list_instruments(identifier, limit=1)[0]
