"""Curated scan universe for the day trader.

Organized by category for maintainability. Combined into SCAN_UNIVERSE
which is the single import used by scanner.py. ~250 liquid symbols
covering mega-caps, high-volume S&P/Nasdaq names, popular volatile
small/mid-caps, and liquid ETFs.
"""

# Mega-cap tech — always liquid, gap on earnings/news
_MEGA_TECH = [
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
    "AVGO", "ORCL", "CRM", "ADBE", "AMD", "INTC", "NFLX", "CSCO",
    "QCOM", "TXN", "MU", "AMAT", "LRCX", "KLAC", "SNPS", "CDNS",
]

# S&P 500 high-volume — most liquid large caps
_SP500_LIQUID = [
    "JPM", "BAC", "WFC", "GS", "MS", "C", "USB", "BK", "SCHW",
    "V", "MA", "PYPL", "AXP",
    "UNH", "LLY", "JNJ", "PFE", "ABBV", "MRK", "BMY", "AMGN", "GILD",
    "MRNA", "BIIB",
    "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "VLO", "PSX", "OXY",
    "WMT", "COST", "HD", "LOW", "TGT", "AMZN", "SBUX", "MCD", "NKE",
    "DIS", "CMCSA", "T", "VZ", "TMUS",
    "BA", "RTX", "LMT", "GD", "NOC", "GE", "CAT", "DE", "HON", "MMM",
    "UPS", "FDX",
    "BRK.B", "PG", "KO", "PEP",
    "ABNB", "MAR", "HLT",
    "F", "GM", "TM",
    "AAL", "DAL", "UAL", "LUV",
    "CCL", "RCL", "NCLH",
]

# Nasdaq-100 additions — high-beta tech/growth
_NASDAQ_ADDITIONS = [
    "PANW", "FTNT", "CRWD", "ZS", "NET", "DDOG", "SNOW", "MDB",
    "MRVL", "ON", "MCHP", "NXPI",
    "ISRG", "DXCM", "ILMN", "REGN",
    "DASH", "ABNB", "TTD", "ZM", "DOCU", "OKTA",
    "TEAM", "WDAY", "SPLK", "VEEV", "ANSS",
    "MELI", "BKNG", "CPRT", "CTAS", "ODFL",
    "ADP", "PAYX", "FAST", "VRSK",
    "PDD", "JD", "BIDU", "BABA",
]

# Popular volatile mid/small-caps — high retail interest, big movers
_POPULAR_VOLATILE = [
    "PLTR", "SOFI", "HOOD", "RIVN", "LCID", "NIO", "XPEV", "LI",
    "COIN", "MARA", "RIOT", "CLSK", "HUT",
    "DKNG", "PENN", "MGM",
    "SNAP", "PINS", "RBLX",
    "SQ", "SHOP", "ROKU", "LYFT", "UBER",
    "SMCI", "ARM", "IONQ", "RGTI", "QUBT",
    "GME", "AMC", "BBBY",
    "CLOV", "WISH", "OPEN",
    "UPST", "AFRM", "NU",
    "ENPH", "FSLR", "RUN",
    "CVNA", "W", "ETSY",
    "CRSP", "EDIT", "NTLA", "BEAM",
    "LAZR", "LIDR", "MVIS",
    "CHPT", "BLNK", "EVGO",
    "SPCE", "RKLB",
    "BILI", "SE", "GRAB",
    "HIMS", "CELH",
    "AI", "BBAI", "SOUN", "PALR",
]

# Liquid ETFs — sector plays, always liquid
_ETFS = [
    "SPY", "QQQ", "IWM", "DIA",
    "ARKK", "ARKG", "ARKF",
    "XLF", "XLE", "XLK", "XLV", "XLI", "XLU", "XLP", "XLY", "XLC",
    "GLD", "SLV", "USO", "UNG",
    "TLT", "HYG", "LQD",
    "SOXL", "TQQQ", "SQQQ", "UVXY", "VXX",
    "EEM", "FXI", "EWZ", "EWJ",
    "SMH", "XBI", "IBB", "KRE", "KWEB",
]

# Deduplicated master list
SCAN_UNIVERSE = sorted(set(
    _MEGA_TECH + _SP500_LIQUID + _NASDAQ_ADDITIONS
    + _POPULAR_VOLATILE + _ETFS
))
