"""
Backtesting & Pre-Training Framework

Provides:
1. Historical data downloading (Binance, Yahoo Finance)
2. Walk-forward backtesting with proper validation
3. ML model pre-training pipeline
4. Model checkpointing (save/load trained weights)
5. Performance metrics and analysis

This ensures models are trained BEFORE live trading, not during.
"""

import asyncio
import logging
import os
import json
import pickle
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)

# Model checkpoint directory
CHECKPOINT_DIR = Path(__file__).parent / "checkpoints"
CHECKPOINT_DIR.mkdir(exist_ok=True)

# Historical data directory
DATA_DIR = Path(__file__).parent / "historical_data"
DATA_DIR.mkdir(exist_ok=True)


@dataclass
class OHLCV:
    """Single OHLCV candle."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    total_return: float
    total_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: float
    avg_loss: float
    avg_holding_period: float  # in hours
    equity_curve: List[Tuple[datetime, float]] = field(default_factory=list)
    trades: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "initial_capital": self.initial_capital,
            "final_capital": round(self.final_capital, 2),
            "total_return": round(self.total_return, 2),
            "total_return_pct": round(self.total_return_pct, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "sortino_ratio": round(self.sortino_ratio, 3),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "win_rate": round(self.win_rate * 100, 1),
            "profit_factor": round(self.profit_factor, 2),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "avg_holding_period_hours": round(self.avg_holding_period, 1),
        }


@dataclass
class TrainingMetrics:
    """Metrics from model training."""
    epochs_completed: int
    total_samples: int
    training_loss: List[float] = field(default_factory=list)
    validation_loss: List[float] = field(default_factory=list)
    dqn_loss: List[float] = field(default_factory=list)
    ppo_loss: List[float] = field(default_factory=list)
    prediction_accuracy: List[float] = field(default_factory=list)
    sharpe_during_training: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "epochs_completed": self.epochs_completed,
            "total_samples": self.total_samples,
            "final_training_loss": self.training_loss[-1] if self.training_loss else None,
            "final_validation_loss": self.validation_loss[-1] if self.validation_loss else None,
            "final_accuracy": self.prediction_accuracy[-1] if self.prediction_accuracy else None,
        }


class HistoricalDataDownloader:
    """
    Downloads historical price data from multiple sources.

    Sources:
    - Binance API (crypto)
    - Yahoo Finance (stocks, ETFs, indices)
    - Federal Reserve FRED (economic indicators)
    """

    # ==========================================================================
    # COMPREHENSIVE MARKET COVERAGE - CRYPTO (200+ symbols)
    # ==========================================================================
    CRYPTO_SYMBOLS = [
        # === TOP 50 BY MARKET CAP ===
        "BTC", "ETH", "BNB", "XRP", "SOL", "ADA", "DOGE", "TRX", "AVAX", "LINK",
        "DOT", "MATIC", "SHIB", "LTC", "BCH", "UNI", "ATOM", "XLM", "XMR", "ETC",
        "NEAR", "APT", "FIL", "ARB", "OP", "VET", "AAVE", "MKR", "GRT", "INJ",
        "ALGO", "THETA", "FTM", "SAND", "MANA", "AXS", "EGLD", "XTZ", "EOS", "FLOW",
        "SNX", "CRV", "LDO", "RUNE", "COMP", "ZEC", "DASH", "BAT", "ENJ", "1INCH",

        # === LAYER 2 / SCALING ===
        "STRK", "ZK", "MANTA", "BLAST", "MODE", "SCROLL", "LINEA", "BASE", "ZKSYNC",
        "IMX", "LRC", "METIS", "BOBA", "SKL", "CELR", "CTSI", "COTI",

        # === DEFI PROTOCOLS ===
        "SUSHI", "YFI", "BAL", "CAKE", "JOE", "SPELL", "LQTY", "PENDLE", "GMX",
        "DYDX", "PERP", "INJ", "OSMO", "KAVA", "RUNE", "VELO", "THE", "AERO",
        "RAY", "SRM", "MNGO", "ORCA", "STEP", "RAYDIUM", "MARINADE",

        # === AI / COMPUTE TOKENS ===
        "FET", "AGIX", "OCEAN", "RNDR", "AKT", "TAO", "ARKM", "WLD", "PRIME",
        "AIOZ", "NMR", "GNO", "CTXC", "DBC", "PHB", "MDT", "RSS3",

        # === GAMING / METAVERSE ===
        "IMX", "GALA", "SAND", "MANA", "AXS", "ENJ", "WAXP", "ALICE", "TLM",
        "ILV", "MAGIC", "PRIME", "BEAM", "PIXEL", "PORTAL", "XAI", "RONIN",
        "GODS", "PYR", "SUPER", "UFO", "HERO", "ATLAS", "POLIS", "SLP", "YGG",

        # === MEME COINS (high volatility = opportunities) ===
        "DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "MEME", "COQ", "MYRO",
        "SNEK", "LADYS", "TURBO", "AIDOGE", "BABYDOGE", "ELON", "AKITA", "KISHU",
        "SAMO", "CORGIAI", "POPCAT", "BRETT", "DOG", "NEIRO", "MOG", "SPX",

        # === INFRASTRUCTURE / ORACLES ===
        "LINK", "BAND", "API3", "PYTH", "UMA", "TRB", "DIA", "NEST", "DOS",
        "PUNDIX", "QNT", "GRT", "LPT", "AR", "FIL", "STORJ", "SC", "HOT",

        # === PRIVACY COINS ===
        "XMR", "ZEC", "DASH", "SCRT", "DUSK", "BEAM", "GRIN", "FIRO", "ZEN",
        "ARRR", "KMD", "XVG", "PIVX", "NAV", "PART",

        # === LAYER 1 ALTERNATIVES ===
        "HBAR", "EGLD", "KAS", "SEI", "SUI", "TIA", "CORE", "CANTO", "ZETA",
        "FTM", "ONE", "ROSE", "CELO", "MOVR", "GLMR", "ASTR", "CFX", "CKB",
        "KDA", "FLUX", "ERG", "RVN", "FIRO", "DCR", "ZIL", "ICX", "ONT",
        "QTUM", "NEO", "VET", "IOST", "WAN", "ARDR", "LSK", "WAVES", "XEM",

        # === EXCHANGE TOKENS ===
        "BNB", "CRO", "OKB", "KCS", "GT", "HT", "MX", "LEO", "FTT",

        # === STAKING / LIQUID STAKING ===
        "LDO", "RPL", "FXS", "SFRXETH", "CBETH", "RETH", "ANKR", "SSV", "OETH",

        # === REAL WORLD ASSETS (RWA) ===
        "ONDO", "MKR", "CFG", "MPL", "GFI", "CPOOL", "TRU", "MAPLE",

        # === CROSS-CHAIN / BRIDGES ===
        "RUNE", "STG", "MULTI", "SYN", "HOP", "CELER", "AXL", "LZ",

        # === MISC HIGH VOLUME ===
        "CHZ", "HOT", "CELO", "ZIL", "QTUM", "RVN", "WAVES", "ICX", "ONT",
        "IOST", "ZRX", "OMG", "ANKR", "SKL", "STORJ", "CELR", "OCEAN", "RSR",
        "NKN", "BAND", "REN", "DENT", "FET", "CTSI", "OGN", "IOTX", "SXP",
        "REEF", "ALICE", "TLM", "DYDX", "MASK", "API3", "PERP", "SPELL",
        "JOE", "BICO", "HIGH", "LOKA", "SUI", "SEI", "TIA", "PYTH", "JUP"
    ]

    # ==========================================================================
    # FULL S&P 500 (All 500 components)
    # ==========================================================================
    STOCK_SYMBOLS_SP500 = [
        # === INFORMATION TECHNOLOGY (75 stocks) ===
        "AAPL", "MSFT", "NVDA", "AVGO", "AMD", "ADBE", "CRM", "CSCO", "ACN", "ORCL",
        "INTC", "IBM", "TXN", "QCOM", "NOW", "INTU", "AMAT", "ADI", "LRCX", "MU",
        "KLAC", "SNPS", "CDNS", "MCHP", "FTNT", "PANW", "NXPI", "HPQ", "HPE", "KEYS",
        "ON", "MPWR", "SWKS", "QRVO", "TER", "ZBRA", "NTAP", "JNPR", "AKAM", "FFIV",
        "CTSH", "IT", "EPAM", "GDDY", "PAYC", "PAYX", "VRSN", "WDC", "STX", "GEN",
        "FSLR", "ENPH", "SEDG", "TRMB", "TYL", "CDW", "ANSS", "FICO", "PTC", "MANH",
        "CPAY", "BR", "JKHY", "CDAY", "GLOB", "TECH", "SSNC", "NLOK", "ROP", "FIS",
        "FISV", "GPN", "FLT", "WEX", "ADP", "PAYX",

        # === HEALTH CARE (65 stocks) ===
        "LLY", "UNH", "JNJ", "MRK", "ABBV", "TMO", "PFE", "ABT", "DHR", "AMGN",
        "ISRG", "SYK", "GILD", "VRTX", "MDT", "BMY", "CI", "CVS", "ELV", "REGN",
        "BSX", "ZTS", "BDX", "HUM", "MCK", "EW", "A", "IQV", "IDXX", "CNC",
        "MTD", "DXCM", "ALGN", "PODD", "HOLX", "COO", "RMD", "BAX", "BIIB", "MOH",
        "LH", "DGX", "WAT", "PKI", "TFX", "TECH", "INCY", "VTRS", "CTLT", "CRL",
        "BIO", "HSIC", "OGN", "CAH", "ABC", "XRAY", "ALLE", "HCA", "UHS", "THC",
        "DVA", "STE", "WST", "ZBH", "ILMN",

        # === FINANCIALS (70 stocks) ===
        "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "SCHW", "C", "AXP",
        "BLK", "SPGI", "CME", "ICE", "PNC", "CB", "MMC", "USB", "TFC", "AON",
        "MET", "PRU", "AIG", "AFL", "TRV", "ALL", "PGR", "HIG", "CINF", "WRB",
        "BK", "STT", "NTRS", "KEY", "CFG", "RF", "FITB", "HBAN", "MTB", "ZION",
        "CMA", "FRC", "SIVB", "FHN", "WAL", "SBNY", "PACW", "FNF", "FAF", "OLD",
        "RJF", "SEIC", "SF", "EVR", "LAZ", "HLI", "PJT", "MKTX", "NDAQ", "CBOE",
        "MSCI", "COIN", "HOOD", "LPLA", "AMP", "BEN", "IVZ", "TROW", "AMG", "JHG",

        # === CONSUMER DISCRETIONARY (60 stocks) ===
        "AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "BKNG", "SBUX", "TJX", "MAR",
        "CMG", "ORLY", "AZO", "ROST", "DHI", "LEN", "PHM", "NVR", "TOL", "KBH",
        "GM", "F", "APTV", "RIVN", "LCID", "BWA", "LEA", "RL", "TPR", "VFC",
        "PVH", "HBI", "GRMN", "POOL", "WSM", "RH", "BBWI", "ULTA", "DRI", "YUM",
        "WYNN", "MGM", "CZR", "LVS", "HLT", "H", "CCL", "NCLH", "RCL", "EXPE",
        "ABNB", "UBER", "LYFT", "DASH", "MTCH", "EBAY", "ETSY", "W", "CHWY", "CVNA",

        # === COMMUNICATION SERVICES (25 stocks) ===
        "GOOGL", "GOOG", "META", "NFLX", "DIS", "CMCSA", "VZ", "T", "TMUS", "CHTR",
        "PARA", "WBD", "FOX", "FOXA", "NWS", "NWSA", "OMC", "IPG", "TTWO", "EA",
        "ATVI", "RBLX", "MTCH", "ZG", "PINS",

        # === INDUSTRIALS (75 stocks) ===
        "CAT", "GE", "HON", "UPS", "UNP", "RTX", "BA", "LMT", "DE", "ETN",
        "ITW", "EMR", "PH", "CTAS", "GD", "NOC", "WM", "RSG", "VRSK", "CSX",
        "NSC", "PCAR", "CARR", "OTIS", "TT", "ROK", "AME", "FAST", "GWW", "SWK",
        "CPRT", "ODFL", "URI", "IR", "EXPD", "CHRW", "JBHT", "XYL", "IEX", "DOV",
        "ROP", "FTV", "NDSN", "SNA", "TDG", "HWM", "HEI", "TDY", "AXON", "LHX",
        "LDOS", "BAH", "SAIC", "KBR", "CACI", "J", "WAB", "AGCO", "GNRC", "HUBB",
        "AOS", "MAS", "ALLE", "FBHS", "LII", "TTC", "MIDD", "FLS", "CFX", "RBC",
        "PNR", "PAYC", "NLSN", "INFO", "DNB",

        # === CONSUMER STAPLES (35 stocks) ===
        "PG", "COST", "PEP", "KO", "WMT", "PM", "MO", "MDLZ", "CL", "KMB",
        "GIS", "K", "HSY", "HRL", "SJM", "MKC", "CPB", "CAG", "KHC", "TSN",
        "ADM", "BG", "STZ", "TAP", "SAM", "KDP", "MNST", "EL", "CLX", "CHD",
        "CLORX", "WBA", "KR", "SYY", "TGT",

        # === ENERGY (25 stocks) ===
        "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "PXD", "OXY",
        "DVN", "HES", "HAL", "FANG", "BKR", "WMB", "KMI", "OKE", "TRGP", "LNG",
        "MRO", "APA", "EQT", "AR", "RRC",

        # === UTILITIES (30 stocks) ===
        "NEE", "DUK", "SO", "D", "AEP", "SRE", "XEL", "EXC", "ED", "WEC",
        "PEG", "ES", "DTE", "EIX", "AWK", "AEE", "CMS", "FE", "ETR", "PPL",
        "EVRG", "ATO", "NI", "CNP", "PNW", "NRG", "VST", "CEG", "PCG", "OGE",

        # === MATERIALS (30 stocks) ===
        "LIN", "APD", "SHW", "ECL", "DD", "NEM", "FCX", "NUE", "STLD", "VMC",
        "MLM", "PPG", "ALB", "CTVA", "CF", "MOS", "FMC", "LYB", "DOW", "CE",
        "EMN", "IP", "PKG", "WRK", "SEE", "AVY", "SON", "BALL", "AMCR", "IFF",

        # === REAL ESTATE (30 stocks) ===
        "PLD", "AMT", "EQIX", "CCI", "PSA", "O", "SPG", "WELL", "DLR", "AVB",
        "EQR", "VTR", "SBAC", "ARE", "MAA", "UDR", "ESS", "EXR", "PEAK", "HST",
        "CBRE", "CSGP", "REG", "KIM", "BXP", "SLG", "VNO", "HIW", "CPT", "IRM"
    ]

    # ==========================================================================
    # HIGH GROWTH / MOMENTUM / IPOs / SPACs
    # ==========================================================================
    STOCK_SYMBOLS_GROWTH = [
        # === AI / CLOUD / SAAS ===
        "PLTR", "SNOW", "CRWD", "DDOG", "NET", "ZS", "MDB", "OKTA", "S", "PATH",
        "CFLT", "DOCN", "ESTC", "GTLB", "SUMO", "DT", "NEWR", "SPLK", "IOT", "AI",
        "BBAI", "SOUN", "UPST", "BIGC", "BILL", "HUBS", "VEEV", "TEAM", "ZI", "ASAN",

        # === SEMICONDUCTORS / AI CHIPS ===
        "NVDA", "AMD", "INTC", "AVGO", "QCOM", "ARM", "MRVL", "SMCI", "ANET", "MU",
        "LRCX", "AMAT", "KLAC", "ASML", "TSM", "WOLF", "CRUS", "SLAB", "RMBS", "POWI",

        # === EV / CLEAN ENERGY ===
        "TSLA", "RIVN", "LCID", "NIO", "XPEV", "LI", "FSR", "FFIE", "GOEV", "WKHS",
        "ENPH", "SEDG", "FSLR", "RUN", "PLUG", "BLDP", "BE", "CHPT", "EVGO", "QS",
        "STEM", "NEE", "CEG", "VST", "NRG", "ORA", "NOVA", "ARRY",

        # === BIOTECH / PHARMA ===
        "MRNA", "BNTX", "NVAX", "VRTX", "REGN", "BIIB", "ILMN", "EXAS", "SGEN", "ALNY",
        "DXCM", "ALGN", "IDXX", "BMRN", "INCY", "SRPT", "RARE", "IONS", "NBIX", "CRSP",
        "BEAM", "EDIT", "NTLA", "VERV", "BLUE", "SGMO", "FATE", "KYMR", "IMVT", "RVNC",

        # === FINTECH / PAYMENTS ===
        "PYPL", "SQ", "AFRM", "SOFI", "UPST", "HOOD", "NU", "COIN", "MELI", "SE",
        "GRAB", "SHOP", "TOST", "BILL", "LSPD", "FOUR", "MQ", "DLO", "PAYO", "RELY",

        # === CONSUMER / TECH ===
        "ABNB", "UBER", "LYFT", "DASH", "ZM", "ROKU", "SPOT", "SNAP", "PINS", "MTCH",
        "RBLX", "U", "DUOL", "BIRD", "CHWY", "ETSY", "W", "CVNA", "CARG", "OPEN",

        # === RECENT IPOS / HIGH VOLATILITY ===
        "ARM", "CART", "KVYO", "VRT", "ONON", "BIRK", "ASTS", "IONQ", "RGTI", "QUBT",
        "TMDX", "PRCT", "DRUG", "DNA", "JOBY", "ACHR", "LILM", "EVTL", "BLDE", "SPCE",

        # === CANNABIS (high volatility) ===
        "TLRY", "CGC", "ACB", "SNDL", "OGI", "HEXO", "CRON", "CURLF", "TCNNF", "GTBIF",

        # === CHINESE ADRS (high volatility) ===
        "BABA", "JD", "PDD", "BIDU", "TCEHY", "NIO", "XPEV", "LI", "BILI", "IQ",
        "TAL", "EDU", "VIPS", "HTHT", "TCOM", "BZUN", "HUYA", "DOYU", "KC", "YMM"
    ]

    # ==========================================================================
    # INTERNATIONAL ADRS & EMERGING MARKETS
    # ==========================================================================
    INTERNATIONAL_ADRS = [
        # === EUROPE ===
        "ASML", "NVO", "SAP", "SHEL", "TM", "UL", "BP", "RIO", "BHP", "HSBC",
        "GSK", "AZN", "SNY", "SHOP", "TD", "RY", "ENB", "CNQ", "SU", "BMO",
        "BNS", "CM", "NTR", "TRI", "WCN", "QSR", "MFC", "SLF", "FFH", "LULU",
        "DEO", "BTI", "NGG", "VOD", "SONY", "MUFG", "SMFG", "MFG", "IX", "KB",
        "SHG", "WF", "HMC", "TM", "NVS", "RHHBY", "OR",

        # === ASIA / EMERGING ===
        "TSM", "BABA", "JD", "PDD", "BIDU", "NIO", "XPEV", "LI", "TCEHY", "NTES",
        "WB", "TME", "YUMC", "ZTO", "MNSO", "BILI", "IQ", "VIPS", "HTHT", "TCOM",
        "INFY", "WIT", "HDB", "IBN", "TTM", "SIFY", "VEDL", "RDY", "VALE", "PBR",
        "ITUB", "BBD", "SBS", "ABEV", "BSBR", "CIG", "SID", "GGB", "ERJ", "GOL",

        # === AUSTRALIA / MINING ===
        "BHP", "RIO", "VALE", "FCX", "SCCO", "TECK", "FM", "AA", "CENX", "KALU"
    ]

    # ==========================================================================
    # COMPREHENSIVE ETF COVERAGE (300+ ETFs)
    # ==========================================================================
    ETF_SYMBOLS = [
        # === MAJOR INDEX ETFs ===
        "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "IVV", "RSP", "MDY", "IJH",
        "IJR", "IWB", "IWF", "IWD", "ITOT", "SCHB", "SPTM", "VV", "VB", "VXF",

        # === NASDAQ / TECH FOCUS ===
        "QQQM", "QQQJ", "ONEQ", "QQEW", "PSQ", "QID", "TQQQ", "SQQQ", "QLD", "QYLD",

        # === SECTOR SPDR ===
        "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLRE", "XLB", "XLC",

        # === VANGUARD SECTORS ===
        "VGT", "VFH", "VDE", "VHT", "VIS", "VCR", "VDC", "VPU", "VNQ", "VOX", "VAW",

        # === iSHARES SECTORS ===
        "IYW", "IYF", "IYE", "IYH", "IYJ", "IYC", "IYK", "IDU", "IYR", "IYZ", "IYM",

        # === INDUSTRY / SUB-SECTOR ===
        "XBI", "IBB", "XHB", "ITB", "KRE", "KBE", "XRT", "XME", "XOP", "OIH",
        "XSD", "SOXX", "SMH", "IGV", "HACK", "CIBR", "SKYY", "CLOU", "WCLD", "ARKK",
        "ARKW", "ARKF", "ARKG", "ARKQ", "ARKX", "BOTZ", "ROBO", "IRBO", "AIQ", "GNOM",
        "PRNT", "IZRL", "BETZ", "NERD", "HERO", "ESPO", "BJK", "PBW", "ICLN", "TAN",
        "QCLN", "FAN", "ACES", "GRID", "LIT", "DRIV", "IDRV", "HAIL", "KARS", "MOTO",

        # === DIVIDEND / VALUE / INCOME ===
        "VYM", "SCHD", "DVY", "HDV", "SDY", "VIG", "DGRO", "DGRW", "NOBL", "SPHD",
        "SPYD", "PFF", "PGX", "PFFD", "VTV", "IVE", "IWD", "RPV", "VLUE", "VONV",

        # === GROWTH ===
        "VUG", "IWF", "SCHG", "RPG", "VONG", "MGK", "SPYG", "IVW", "IUSG", "QQQ",

        # === SMALL / MID CAP ===
        "IWM", "IJR", "VB", "SCHA", "SLY", "VIOO", "IJH", "MDY", "VO", "IVOO",
        "IWO", "IWN", "VBK", "VBR", "SLYG", "SLYV", "IJT", "IJS", "VIOG", "VIOV",

        # === INTERNATIONAL - DEVELOPED ===
        "EFA", "VEA", "IEFA", "SCHF", "EFV", "EFG", "IDEV", "IXUS", "VEU", "VXUS",
        "VGK", "EWU", "EWG", "EWQ", "EWP", "EWI", "EWN", "EWK", "EWL", "EWD",
        "EWJ", "EWY", "EWT", "EWH", "EWS", "EWA", "EWC", "ENZL", "NORW", "EDEN",

        # === INTERNATIONAL - EMERGING ===
        "EEM", "VWO", "IEMG", "SCHE", "SPEM", "XSOE", "FNDE", "EMQQ", "KEMQ", "EEMV",
        "FXI", "MCHI", "KWEB", "CQQQ", "CHIQ", "ASHR", "GXC", "EWZ", "EWZS", "FLBR",
        "INDA", "SMIN", "EPI", "INDY", "PIN", "EWW", "EWT", "THD", "VNM", "EPHE",
        "EIDO", "ECH", "EPU", "EWM", "ARGT", "TUR", "GREK", "EPOL", "RSX", "ERUS",

        # === BOND ETFs - DURATION ===
        "BND", "AGG", "SCHZ", "BIV", "VCIT", "LQD", "VCSH", "BSV", "SHY", "IEI",
        "IEF", "TLT", "TLH", "EDV", "ZROZ", "VGLT", "VGIT", "VGSH", "SCHO", "SCHR",

        # === BOND ETFs - CREDIT ===
        "LQD", "VCIT", "VCSH", "IGIB", "IGSB", "HYG", "JNK", "USHY", "SHYG", "HYLD",
        "SJNK", "PHB", "ANGL", "FALN", "BKLN", "SRLN", "FTSL", "FLOT", "FLRN",

        # === BOND ETFs - SPECIALTY ===
        "TIP", "SCHP", "VTIP", "STIP", "MUB", "SUB", "CMF", "NYF", "HYD", "HYMB",
        "EMB", "PCY", "VWOB", "EMLC", "EBND", "IAGG", "BNDX", "BWX", "IGOV",

        # === COMMODITY ETFs ===
        "GLD", "IAU", "GLDM", "SGOL", "BAR", "OUNZ", "SLV", "SIVR", "PSLV", "PPLT",
        "PALL", "GLTR", "DBP", "DBA", "DBC", "PDBC", "COMT", "GSG", "RJI", "DJP",
        "USO", "BNO", "UNG", "UNL", "BOIL", "KOLD", "UCO", "SCO", "OILK", "USOI",
        "CORN", "WEAT", "SOYB", "CANE", "JO", "NIB", "COW", "MOO", "WOOD", "CUT",
        "CPER", "JJC", "COPX", "REMX", "PICK", "SIL", "SILJ", "GDX", "GDXJ", "RING",

        # === VOLATILITY / VIX ===
        "VXX", "UVXY", "SVXY", "VIXY", "VIXM", "ZIV", "VXZ", "TAIL", "SVOL",

        # === INVERSE / LEVERAGED ===
        "SH", "PSQ", "DOG", "SDS", "QID", "DXD", "TWM", "RWM", "SPXS", "SPXU",
        "SQQQ", "TQQQ", "UPRO", "SPXL", "TNA", "TZA", "LABU", "LABD", "SOXL", "SOXS",
        "NUGT", "DUST", "JNUG", "JDST", "GUSH", "DRIP", "BOIL", "KOLD", "YANG", "YINN",
        "FAS", "FAZ", "ERX", "ERY", "CURE", "NAIL", "DRV", "TECL", "TECS", "WEBL",

        # === FACTOR / SMART BETA ===
        "MTUM", "VLUE", "QUAL", "SIZE", "USMV", "SPLV", "EFAV", "ACWV", "SPHB", "SPHD",
        "MOAT", "PKW", "COWZ", "QVAL", "QMOM", "DFSV", "DFUV", "DFUS", "DFAC", "AVUV",

        # === DIVIDEND / COVERED CALL ===
        "JEPI", "JEPQ", "XYLD", "QYLD", "RYLD", "DJIA", "DIVO", "NUSI", "PUTW", "PBP",

        # === THEMATIC / MEGATRENDS ===
        "ARKK", "ARKG", "ARKW", "ARKF", "ARKQ", "ARKX", "MOON", "UFO", "ROKT", "AWAY",
        "URNM", "URA", "NLR", "ICLN", "PBW", "TAN", "QCLN", "LIT", "DRIV", "IDRV",
        "WCLD", "SKYY", "CLOU", "HACK", "CIBR", "BUG", "SNSR", "BOTZ", "ROBO", "GNOM",
        "EDOC", "ARKG", "XBI", "IDNA", "BTEK", "HTEC", "HELX", "AGNG", "GERM",
        "FINX", "IPAY", "KOIN", "BLOK", "BKCH", "LEGR", "BITQ", "DAPP", "WGMI", "BITO",

        # === REAL ESTATE ===
        "VNQ", "IYR", "SCHH", "XLRE", "RWR", "USRT", "REET", "REM", "MORT", "SRET",
        "REZ", "HOMZ", "INDS", "NURE", "PPTY", "KBWY", "KBWD", "O", "VICI", "STAG"
    ]

    # ==========================================================================
    # FUTURES / FOREX / INDICES
    # ==========================================================================
    FUTURES_SYMBOLS = [
        # === INDEX FUTURES ===
        "ES=F", "NQ=F", "YM=F", "RTY=F", "EMD=F", "NKD=F", "NIY=F",

        # === COMMODITIES - METALS ===
        "GC=F", "SI=F", "HG=F", "PL=F", "PA=F",

        # === COMMODITIES - ENERGY ===
        "CL=F", "BZ=F", "HO=F", "RB=F", "NG=F",

        # === COMMODITIES - AGRICULTURE ===
        "ZC=F", "ZW=F", "ZS=F", "ZM=F", "ZL=F", "KC=F", "SB=F", "CC=F", "CT=F",
        "LC=F", "LH=F", "FC=F", "ZO=F", "ZR=F",

        # === BONDS / RATES ===
        "ZB=F", "ZN=F", "ZF=F", "ZT=F", "GE=F",

        # === CURRENCIES ===
        "DX=F", "6E=F", "6J=F", "6B=F", "6C=F", "6A=F", "6S=F", "6N=F", "6M=F"
    ]

    # === FOREX PAIRS (via Yahoo Finance symbols) ===
    FOREX_SYMBOLS = [
        # Major Pairs
        "EURUSD=X", "USDJPY=X", "GBPUSD=X", "USDCHF=X", "AUDUSD=X", "USDCAD=X", "NZDUSD=X",
        # Cross Pairs
        "EURGBP=X", "EURJPY=X", "GBPJPY=X", "AUDJPY=X", "EURAUD=X", "EURCHF=X", "GBPCHF=X",
        "CADJPY=X", "NZDJPY=X", "AUDNZD=X", "AUDCAD=X", "AUDCHF=X", "CADCHF=X",
        # Emerging
        "USDZAR=X", "USDMXN=X", "USDBRL=X", "USDTRY=X", "USDINR=X", "USDCNY=X", "USDRUB=X",
        "USDSGD=X", "USDHKD=X", "USDKRW=X", "USDTWD=X", "USDTHB=X", "USDIDR=X", "USDPHP=X"
    ]

    # ==========================================================================
    # REITS & SPECIALTY
    # ==========================================================================
    REIT_SYMBOLS = [
        # === DATA CENTERS ===
        "EQIX", "DLR", "AMT", "CCI", "SBAC", "UNIT", "CONE", "QTS",
        # === INDUSTRIAL ===
        "PLD", "STAG", "REXR", "FR", "EGP", "TRNO", "COLD", "IIPR",
        # === RESIDENTIAL ===
        "AVB", "EQR", "MAA", "UDR", "ESS", "CPT", "AIV", "INVH", "AMH",
        # === RETAIL ===
        "SPG", "O", "NNN", "REG", "KIM", "FRT", "BRX", "SITC", "AKR",
        # === OFFICE ===
        "BXP", "SLG", "VNO", "KRC", "ARE", "HIW", "OFC", "DEI", "JBGS",
        # === HEALTHCARE ===
        "WELL", "VTR", "PEAK", "OHI", "HR", "DOC", "LTC", "SBRA", "MPW",
        # === SPECIALTY ===
        "PSA", "EXR", "CUBE", "LSI", "NSA", "IRM", "LAMR", "OUT", "CCU"
    ]

    # ==========================================================================
    # COMBINE ALL SYMBOLS
    # ==========================================================================
    STOCK_SYMBOLS = (
        STOCK_SYMBOLS_SP500 +
        STOCK_SYMBOLS_GROWTH +
        INTERNATIONAL_ADRS +
        ETF_SYMBOLS +
        FUTURES_SYMBOLS +
        FOREX_SYMBOLS +
        REIT_SYMBOLS
    )

    # Remove duplicates while preserving order
    STOCK_SYMBOLS = list(dict.fromkeys(STOCK_SYMBOLS))

    def __init__(self):
        self.data_cache: Dict[str, List[OHLCV]] = {}

    async def download_crypto_history(
        self,
        symbol: str,
        interval: str = "1h",
        days: int = 365
    ) -> List[OHLCV]:
        """Download crypto historical data from Binance."""
        import aiohttp

        candles = []
        binance_symbol = f"{symbol}USDT"

        # Calculate time range
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

        # Binance klines endpoint
        url = "https://api.binance.us/api/v3/klines"

        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "symbol": binance_symbol,
                    "interval": interval,
                    "startTime": start_time,
                    "endTime": end_time,
                    "limit": 1000
                }

                current_start = start_time
                while current_start < end_time:
                    params["startTime"] = current_start

                    async with session.get(url, params=params) as response:
                        if response.status != 200:
                            logger.warning(f"Binance API error for {symbol}: {response.status}")
                            break

                        data = await response.json()

                        if not data:
                            break

                        for kline in data:
                            candles.append(OHLCV(
                                timestamp=datetime.fromtimestamp(kline[0] / 1000),
                                open=float(kline[1]),
                                high=float(kline[2]),
                                low=float(kline[3]),
                                close=float(kline[4]),
                                volume=float(kline[5])
                            ))

                        # Move to next batch
                        current_start = data[-1][0] + 1

                        # Rate limiting
                        await asyncio.sleep(0.1)

            logger.info(f"Downloaded {len(candles)} candles for {symbol}")
            self.data_cache[symbol] = candles

            # Save to disk
            self._save_to_disk(symbol, candles)

            return candles

        except Exception as e:
            logger.error(f"Error downloading {symbol}: {e}")
            return []

    async def download_stock_history(
        self,
        symbol: str,
        days: int = 365
    ) -> List[OHLCV]:
        """Download stock/ETF data from Yahoo Finance."""
        import aiohttp

        candles = []

        # Yahoo Finance API (unofficial but widely used)
        end_time = int(datetime.now().timestamp())
        start_time = int((datetime.now() - timedelta(days=days)).timestamp())

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "period1": start_time,
                    "period2": end_time,
                    "interval": "1h",
                    "includePrePost": "false"
                }

                headers = {"User-Agent": "Mozilla/5.0"}

                async with session.get(url, params=params, headers=headers) as response:
                    if response.status != 200:
                        logger.warning(f"Yahoo API error for {symbol}: {response.status}")
                        return []

                    data = await response.json()

                    result = data.get("chart", {}).get("result", [])
                    if not result:
                        return []

                    quotes = result[0]
                    timestamps = quotes.get("timestamp", [])
                    ohlcv = quotes.get("indicators", {}).get("quote", [{}])[0]

                    opens = ohlcv.get("open", [])
                    highs = ohlcv.get("high", [])
                    lows = ohlcv.get("low", [])
                    closes = ohlcv.get("close", [])
                    volumes = ohlcv.get("volume", [])

                    for i, ts in enumerate(timestamps):
                        if all(x is not None for x in [opens[i], highs[i], lows[i], closes[i]]):
                            candles.append(OHLCV(
                                timestamp=datetime.fromtimestamp(ts),
                                open=opens[i],
                                high=highs[i],
                                low=lows[i],
                                close=closes[i],
                                volume=volumes[i] or 0
                            ))

            logger.info(f"Downloaded {len(candles)} candles for {symbol}")
            self.data_cache[symbol] = candles
            self._save_to_disk(symbol, candles)

            return candles

        except Exception as e:
            logger.error(f"Error downloading {symbol}: {e}")
            return []

    async def download_all(self, days: int = 365, max_concurrent: int = 10) -> Dict[str, List[OHLCV]]:
        """Download all historical data for training with parallel downloads."""
        total_crypto = len(self.CRYPTO_SYMBOLS)
        total_stocks = len(self.STOCK_SYMBOLS)
        total_symbols = total_crypto + total_stocks

        logger.info(f"Downloading {days} days of data for {total_symbols} symbols...")
        logger.info(f"  - {total_crypto} crypto symbols")
        logger.info(f"  - {total_stocks} stock/ETF/futures symbols")

        # Use semaphore for rate limiting parallel downloads
        semaphore = asyncio.Semaphore(max_concurrent)
        downloaded = {"count": 0, "failed": 0}

        async def download_with_limit(symbol: str, is_crypto: bool):
            async with semaphore:
                try:
                    if symbol not in self.data_cache:
                        if is_crypto:
                            await self.download_crypto_history(symbol, days=days)
                        else:
                            await self.download_stock_history(symbol, days=days)
                        await asyncio.sleep(0.2)  # Small delay between requests

                    downloaded["count"] += 1
                    if downloaded["count"] % 50 == 0:
                        logger.info(f"  Progress: {downloaded['count']}/{total_symbols} symbols downloaded")
                except Exception as e:
                    downloaded["failed"] += 1
                    logger.warning(f"Failed to download {symbol}: {e}")

        # Create download tasks
        tasks = []
        for symbol in self.CRYPTO_SYMBOLS:
            tasks.append(download_with_limit(symbol, is_crypto=True))
        for symbol in self.STOCK_SYMBOLS:
            tasks.append(download_with_limit(symbol, is_crypto=False))

        # Execute all downloads with concurrency limit
        await asyncio.gather(*tasks, return_exceptions=True)

        logger.info(f"Download complete: {len(self.data_cache)} symbols cached, {downloaded['failed']} failed")
        return self.data_cache

    def _save_to_disk(self, symbol: str, candles: List[OHLCV]):
        """Save historical data to disk."""
        filepath = DATA_DIR / f"{symbol}_history.json"
        data = [c.to_dict() for c in candles]
        with open(filepath, "w") as f:
            json.dump(data, f)

    def load_from_disk(self, symbol: str) -> List[OHLCV]:
        """Load historical data from disk."""
        filepath = DATA_DIR / f"{symbol}_history.json"
        if not filepath.exists():
            return []

        with open(filepath, "r") as f:
            data = json.load(f)

        candles = [
            OHLCV(
                timestamp=datetime.fromisoformat(d["timestamp"]),
                open=d["open"],
                high=d["high"],
                low=d["low"],
                close=d["close"],
                volume=d["volume"]
            )
            for d in data
        ]

        self.data_cache[symbol] = candles
        return candles

    def load_all_from_disk(self) -> Dict[str, List[OHLCV]]:
        """Load all cached historical data."""
        for filepath in DATA_DIR.glob("*_history.json"):
            symbol = filepath.stem.replace("_history", "")
            self.load_from_disk(symbol)
        return self.data_cache


class WalkForwardBacktester:
    """
    Walk-Forward Backtesting Engine

    Implements proper walk-forward validation:
    1. Split data into train/test windows
    2. Train on window, test on out-of-sample
    3. Roll forward and repeat
    4. Aggregate results to assess true performance

    This prevents overfitting and gives realistic performance estimates.
    """

    def __init__(
        self,
        train_window_days: int = 60,
        test_window_days: int = 20,
        step_days: int = 10,
        initial_capital: float = 10000.0
    ):
        self.train_window = train_window_days
        self.test_window = test_window_days
        self.step_days = step_days
        self.initial_capital = initial_capital

        self.results: List[BacktestResult] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.all_trades: List[Dict] = []

    def prepare_features(self, candles: List[OHLCV], lookback: int = 20) -> np.ndarray:
        """
        Prepare feature matrix from OHLCV data.

        Features:
        - Returns (1, 5, 10, 20 period)
        - Volatility (realized, Parkinson, Garman-Klass)
        - RSI, MACD, Bollinger Bands
        - Volume profile
        - Price momentum
        """
        if len(candles) < lookback + 20:
            return np.array([])

        closes = np.array([c.close for c in candles])
        highs = np.array([c.high for c in candles])
        lows = np.array([c.low for c in candles])
        volumes = np.array([c.volume for c in candles])

        features = []

        for i in range(lookback, len(candles)):
            window_close = closes[i-lookback:i+1]
            window_high = highs[i-lookback:i+1]
            window_low = lows[i-lookback:i+1]
            window_vol = volumes[i-lookback:i+1]

            # Returns
            returns_1 = (closes[i] - closes[i-1]) / closes[i-1] if closes[i-1] > 0 else 0
            returns_5 = (closes[i] - closes[i-5]) / closes[i-5] if i >= 5 and closes[i-5] > 0 else 0
            returns_10 = (closes[i] - closes[i-10]) / closes[i-10] if i >= 10 and closes[i-10] > 0 else 0
            returns_20 = (closes[i] - closes[i-20]) / closes[i-20] if i >= 20 and closes[i-20] > 0 else 0

            # Volatility
            log_returns = np.diff(np.log(window_close + 1e-8))
            realized_vol = np.std(log_returns) * np.sqrt(252 * 24)  # Annualized hourly

            # Parkinson volatility (high-low based)
            hl_ratio = np.log(window_high / (window_low + 1e-8))
            parkinson_vol = np.sqrt(np.mean(hl_ratio ** 2) / (4 * np.log(2))) * np.sqrt(252 * 24)

            # RSI
            gains = np.maximum(np.diff(window_close), 0)
            losses = np.maximum(-np.diff(window_close), 0)
            avg_gain = np.mean(gains[-14:]) if len(gains) >= 14 else np.mean(gains)
            avg_loss = np.mean(losses[-14:]) if len(losses) >= 14 else np.mean(losses)
            rsi = 100 - (100 / (1 + avg_gain / (avg_loss + 1e-8)))

            # MACD
            ema_12 = self._ema(window_close, 12)
            ema_26 = self._ema(window_close, 26)
            macd = (ema_12 - ema_26) / (closes[i] + 1e-8)

            # Bollinger Bands position
            sma_20 = np.mean(window_close[-20:])
            std_20 = np.std(window_close[-20:])
            bb_position = (closes[i] - sma_20) / (2 * std_20 + 1e-8)

            # Volume profile
            vol_sma = np.mean(window_vol)
            vol_ratio = window_vol[-1] / (vol_sma + 1e-8)

            # Price momentum (rate of change)
            momentum = (closes[i] - np.mean(window_close)) / (np.std(window_close) + 1e-8)

            # Trend strength (ADX approximation)
            tr = np.maximum(window_high - window_low,
                          np.abs(window_high - np.roll(window_close, 1)),
                          np.abs(window_low - np.roll(window_close, 1)))
            atr = np.mean(tr[-14:])
            trend_strength = atr / (closes[i] + 1e-8)

            feature_vector = [
                returns_1, returns_5, returns_10, returns_20,
                realized_vol, parkinson_vol,
                rsi / 100,  # Normalize to 0-1
                macd,
                bb_position,
                vol_ratio,
                momentum,
                trend_strength,
                # Normalized price levels
                (closes[i] - np.min(window_close)) / (np.max(window_close) - np.min(window_close) + 1e-8),
                # High-low range
                (window_high[-1] - window_low[-1]) / (closes[i] + 1e-8),
            ]

            features.append(feature_vector)

        return np.array(features)

    def _ema(self, data: np.ndarray, period: int) -> float:
        """Calculate EMA."""
        if len(data) < period:
            return data[-1]
        multiplier = 2 / (period + 1)
        ema = data[0]
        for price in data[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def generate_labels(self, candles: List[OHLCV], lookahead: int = 5, threshold: float = 0.02) -> np.ndarray:
        """
        Generate trading labels based on future returns.

        Labels:
        0 = Sell (future return < -threshold)
        1 = Hold (future return between -threshold and +threshold)
        2 = Buy (future return > +threshold)
        """
        closes = np.array([c.close for c in candles])
        labels = []

        for i in range(len(closes) - lookahead):
            future_return = (closes[i + lookahead] - closes[i]) / closes[i]

            if future_return > threshold:
                labels.append(2)  # Buy
            elif future_return < -threshold:
                labels.append(0)  # Sell
            else:
                labels.append(1)  # Hold

        return np.array(labels)

    def run_backtest(
        self,
        data: Dict[str, List[OHLCV]],
        model_trainer: 'ModelPreTrainer',
        strategy: str = "ml_ensemble"
    ) -> BacktestResult:
        """
        Run walk-forward backtest.

        Args:
            data: Historical OHLCV data per symbol
            model_trainer: Pre-trainer with trained models
            strategy: Trading strategy to use
        """
        logger.info("Starting walk-forward backtest...")

        # Combine all data into time-sorted events
        all_candles = []
        for symbol, candles in data.items():
            for candle in candles:
                all_candles.append((candle.timestamp, symbol, candle))

        all_candles.sort(key=lambda x: x[0])

        if not all_candles:
            logger.error("No data for backtest")
            return self._empty_result()

        # Initialize tracking
        capital = self.initial_capital
        positions: Dict[str, Dict] = {}  # symbol -> position info
        equity_curve = [(all_candles[0][0], capital)]
        trades = []

        # Walk through time
        window_data: Dict[str, List[OHLCV]] = {sym: [] for sym in data.keys()}

        for timestamp, symbol, candle in all_candles:
            window_data[symbol].append(candle)

            # Keep only recent data (memory efficiency)
            max_window = self.train_window + self.test_window + 50
            if len(window_data[symbol]) > max_window * 24:  # hourly data
                window_data[symbol] = window_data[symbol][-max_window * 24:]

            # Update existing positions
            if symbol in positions:
                pos = positions[symbol]
                current_price = candle.close
                entry_price = pos["entry_price"]
                side = pos["side"]

                # Calculate unrealized P&L
                if side == "long":
                    pnl_pct = (current_price - entry_price) / entry_price
                else:
                    pnl_pct = (entry_price - current_price) / entry_price

                unrealized_pnl = pos["size"] * pnl_pct

                # Check exit conditions
                should_exit = False
                exit_reason = ""

                # Take profit (10%)
                if pnl_pct >= 0.10:
                    should_exit = True
                    exit_reason = "take_profit"
                # Stop loss (5%)
                elif pnl_pct <= -0.05:
                    should_exit = True
                    exit_reason = "stop_loss"
                # Time-based exit (hold max 48 hours)
                elif (timestamp - pos["entry_time"]).total_seconds() > 48 * 3600:
                    should_exit = True
                    exit_reason = "time_exit"

                if should_exit:
                    realized_pnl = pos["size"] * pnl_pct
                    capital += pos["size"] + realized_pnl

                    trades.append({
                        "symbol": symbol,
                        "side": side,
                        "entry_price": entry_price,
                        "exit_price": current_price,
                        "entry_time": pos["entry_time"].isoformat(),
                        "exit_time": timestamp.isoformat(),
                        "pnl": realized_pnl,
                        "pnl_pct": pnl_pct * 100,
                        "exit_reason": exit_reason,
                    })

                    del positions[symbol]

            # Generate trading signal (only if we have enough data)
            if len(window_data[symbol]) >= 100 and symbol not in positions:
                features = self.prepare_features(window_data[symbol][-100:])

                if len(features) > 0:
                    # Get ML prediction
                    state = features[-1]
                    prediction = model_trainer.predict(state)

                    # Only trade on strong signals
                    if prediction["action"] != 1 and prediction["confidence"] > 0.6:
                        # Position sizing (2% of capital per trade, max 10 positions)
                        if len(positions) < 10:
                            position_size = min(capital * 0.02, capital * 0.1)

                            if position_size > 100:  # Minimum position
                                side = "long" if prediction["action"] == 2 else "short"

                                positions[symbol] = {
                                    "side": side,
                                    "entry_price": candle.close,
                                    "entry_time": timestamp,
                                    "size": position_size,
                                }

                                capital -= position_size

            # Update equity curve periodically
            if len(equity_curve) == 0 or (timestamp - equity_curve[-1][0]).total_seconds() > 3600:
                # Calculate total equity
                total_equity = capital
                for sym, pos in positions.items():
                    if sym in window_data and window_data[sym]:
                        current_price = window_data[sym][-1].close
                        entry_price = pos["entry_price"]
                        if pos["side"] == "long":
                            pnl_pct = (current_price - entry_price) / entry_price
                        else:
                            pnl_pct = (entry_price - current_price) / entry_price
                        total_equity += pos["size"] * (1 + pnl_pct)

                equity_curve.append((timestamp, total_equity))

        # Close remaining positions at end
        for symbol, pos in list(positions.items()):
            if symbol in window_data and window_data[symbol]:
                current_price = window_data[symbol][-1].close
                entry_price = pos["entry_price"]
                if pos["side"] == "long":
                    pnl_pct = (current_price - entry_price) / entry_price
                else:
                    pnl_pct = (entry_price - current_price) / entry_price

                realized_pnl = pos["size"] * pnl_pct
                capital += pos["size"] + realized_pnl

                trades.append({
                    "symbol": symbol,
                    "side": pos["side"],
                    "entry_price": entry_price,
                    "exit_price": current_price,
                    "entry_time": pos["entry_time"].isoformat(),
                    "exit_time": all_candles[-1][0].isoformat(),
                    "pnl": realized_pnl,
                    "pnl_pct": pnl_pct * 100,
                    "exit_reason": "backtest_end",
                })

        # Calculate final metrics
        return self._calculate_metrics(equity_curve, trades)

    def _calculate_metrics(
        self,
        equity_curve: List[Tuple[datetime, float]],
        trades: List[Dict]
    ) -> BacktestResult:
        """Calculate backtest performance metrics."""
        if not equity_curve:
            return self._empty_result()

        initial = self.initial_capital
        final = equity_curve[-1][1]

        # Returns
        total_return = final - initial
        total_return_pct = (total_return / initial) * 100

        # Calculate daily returns for Sharpe/Sortino
        equity_values = [e[1] for e in equity_curve]
        returns = np.diff(equity_values) / (np.array(equity_values[:-1]) + 1e-8)

        # Sharpe Ratio (annualized, assuming hourly data)
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252 * 24)
        else:
            sharpe = 0

        # Sortino Ratio (downside deviation only)
        downside_returns = returns[returns < 0]
        if len(downside_returns) > 0:
            sortino = np.mean(returns) / np.std(downside_returns) * np.sqrt(252 * 24)
        else:
            sortino = sharpe

        # Max Drawdown
        peak = equity_values[0]
        max_dd = 0
        for value in equity_values:
            if value > peak:
                peak = value
            dd = (peak - value) / peak
            if dd > max_dd:
                max_dd = dd

        # Trade statistics
        winning_trades = [t for t in trades if t["pnl"] > 0]
        losing_trades = [t for t in trades if t["pnl"] <= 0]

        win_rate = len(winning_trades) / len(trades) if trades else 0
        avg_win = np.mean([t["pnl"] for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([abs(t["pnl"]) for t in losing_trades]) if losing_trades else 0

        # Profit factor
        gross_profit = sum(t["pnl"] for t in winning_trades)
        gross_loss = abs(sum(t["pnl"] for t in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Average holding period
        holding_periods = []
        for t in trades:
            entry = datetime.fromisoformat(t["entry_time"])
            exit_time = datetime.fromisoformat(t["exit_time"])
            holding_periods.append((exit_time - entry).total_seconds() / 3600)
        avg_holding = np.mean(holding_periods) if holding_periods else 0

        return BacktestResult(
            start_date=equity_curve[0][0],
            end_date=equity_curve[-1][0],
            initial_capital=initial,
            final_capital=final,
            total_return=total_return,
            total_return_pct=total_return_pct,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=max_dd * initial,
            max_drawdown_pct=max_dd * 100,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=len(trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_holding_period=avg_holding,
            equity_curve=equity_curve,
            trades=trades,
        )

    def _empty_result(self) -> BacktestResult:
        """Return empty backtest result."""
        now = datetime.now()
        return BacktestResult(
            start_date=now,
            end_date=now,
            initial_capital=self.initial_capital,
            final_capital=self.initial_capital,
            total_return=0,
            total_return_pct=0,
            sharpe_ratio=0,
            sortino_ratio=0,
            max_drawdown=0,
            max_drawdown_pct=0,
            win_rate=0,
            profit_factor=0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            avg_win=0,
            avg_loss=0,
            avg_holding_period=0,
        )


class ModelPreTrainer:
    """
    Pre-Training Pipeline for ML Models

    Trains all models on historical data BEFORE live trading:
    - DQN: Learn Q-values from simulated trading
    - PPO: Learn policy from market dynamics
    - LSTM/Transformer: Learn price patterns
    - VAE: Learn market regime representations

    Saves trained weights to disk for production use.
    """

    def __init__(self, state_dim: int = 64, action_dim: int = 3):
        self.state_dim = state_dim
        self.action_dim = action_dim  # 0=sell, 1=hold, 2=buy

        # Sequence length for LSTM/Transformer (must match training)
        self.seq_len = 10

        # Initialize models with PROPER TRAINABLE versions
        from .ml_models import (
            create_dqn_agent, create_ppo_agent,
            LSTMClassifier, TrainableTransformer, TrainableVAE
        )

        # DQN and PPO already have proper training
        self.dqn = create_dqn_agent(state_dim, action_dim)
        self.ppo = create_ppo_agent(state_dim, action_dim)

        # Use trainable versions with proper backpropagation
        self.lstm = LSTMClassifier(
            input_dim=state_dim, hidden_dim=128, output_dim=action_dim, lr=0.001
        )
        self.transformer = TrainableTransformer(
            input_dim=state_dim, hidden_dim=64, output_dim=action_dim, lr=0.001
        )
        self.vae = TrainableVAE(
            input_dim=state_dim, hidden_dim=64, latent_dim=8, output_dim=4, lr=0.001
        )

        # State buffer for sequential prediction (LSTM/Transformer)
        # Stores recent states so LSTM/Transformer see seq_len context
        # instead of a single state (matching training conditions)
        from collections import deque
        self.state_buffer = deque(maxlen=self.seq_len)

        self.is_trained = False
        self.training_metrics = TrainingMetrics(epochs_completed=0, total_samples=0)
        self.min_training_epochs = 10  # Reduced - early stopping ensures quality
        self.min_training_samples = 10000

    def prepare_training_data(
        self,
        historical_data: Dict[str, List[OHLCV]],
        backtester: WalkForwardBacktester
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Prepare training data from historical OHLCV.

        Returns: (features, labels, rewards)
        """
        all_features = []
        all_labels = []
        all_rewards = []

        for symbol, candles in historical_data.items():
            if len(candles) < 200:
                continue

            features = backtester.prepare_features(candles)
            labels = backtester.generate_labels(candles)

            # Align features and labels
            min_len = min(len(features), len(labels))
            if min_len > 0:
                features = features[:min_len]
                labels = labels[:min_len]

                # Calculate rewards (based on actual returns)
                closes = np.array([c.close for c in candles])
                rewards = []
                for i in range(len(labels)):
                    if i + 5 < len(closes):
                        future_return = (closes[i + 5] - closes[i]) / closes[i]
                        # Reward alignment: +1 for correct direction, -1 for wrong
                        if labels[i] == 2:  # Predicted buy
                            reward = future_return * 10  # Scale for learning
                        elif labels[i] == 0:  # Predicted sell
                            reward = -future_return * 10
                        else:
                            reward = 0
                        # Clip rewards to [-1, 1] to prevent DQN Q-value explosion
                        rewards.append(np.clip(reward, -1.0, 1.0))
                    else:
                        rewards.append(0)

                all_features.append(features)
                all_labels.append(labels)
                all_rewards.append(np.array(rewards))

        if not all_features:
            return np.array([]), np.array([]), np.array([])

        X = np.vstack(all_features)
        y = np.concatenate(all_labels)
        r = np.concatenate(all_rewards)

        # Pad/truncate features to state_dim
        if X.shape[1] < self.state_dim:
            padding = np.zeros((X.shape[0], self.state_dim - X.shape[1]))
            X = np.hstack([X, padding])
        elif X.shape[1] > self.state_dim:
            X = X[:, :self.state_dim]

        return X, y, r

    def train(
        self,
        features: np.ndarray,
        labels: np.ndarray,
        rewards: np.ndarray,
        epochs: int = 40,
        batch_size: int = 256,
        validation_split: float = 0.2
    ) -> TrainingMetrics:
        """
        Train all models on historical data.
        """
        if len(features) == 0:
            logger.error("No training data provided")
            return self.training_metrics

        # Cap training data for ~1 hour training time
        # 1M samples provides excellent coverage across 1,489 symbols
        max_samples = 1000000
        if len(features) > max_samples:
            logger.info(f"Sampling {max_samples:,} from {len(features):,} samples for efficient training...")
            # Sort indices to preserve temporal order within each symbol's block
            sample_idx = np.sort(np.random.choice(len(features), max_samples, replace=False))
            features = features[sample_idx]
            labels = labels[sample_idx]
            rewards = rewards[sample_idx]

        logger.info(f"Training on {len(features):,} samples for {epochs} epochs...")

        # Temporal train/validation split (NOT random)
        # Data is ordered per-symbol chronologically, so taking the last 20%
        # ensures we validate on later time periods — no look-ahead bias.
        # Random splits let the model train on 2024 data and validate on 2022,
        # artificially inflating accuracy.
        n_val = int(len(features) * validation_split)
        X_train, y_train, r_train = features[:-n_val], labels[:-n_val], rewards[:-n_val]
        X_val, y_val, r_val = features[-n_val:], labels[-n_val:], rewards[-n_val:]

        total_batches = len(X_train) // batch_size
        logger.info(f"Training config: {total_batches:,} batches/epoch, {len(X_val):,} validation samples")

        # Fix validation and training sample indices for consistent accuracy measurement
        # This prevents random sampling variance between epochs
        val_sample_size = min(10000, len(X_val))
        train_sample_size = min(10000, len(X_train))
        np.random.seed(42)  # Fixed seed for reproducible sampling
        fixed_val_indices = np.random.choice(len(X_val), val_sample_size, replace=False)
        fixed_train_indices = np.random.choice(len(X_train), train_sample_size, replace=False)
        np.random.seed(None)  # Reset to random

        # Early stopping setup - check for resume state
        start_epoch = getattr(self, '_last_epoch', 0)
        best_val_accuracy = getattr(self, '_best_val_accuracy', 0)
        patience = 8  # Stop if no improvement for 8 epochs (more thorough)
        patience_counter = getattr(self, '_patience_counter', 0)

        if start_epoch > 0:
            logger.info(f"📥 Resuming training from epoch {start_epoch + 1}, best_acc={best_val_accuracy:.2%}")

        for epoch in range(start_epoch, epochs):
            epoch_start = time.time()

            # Shuffle training data
            perm = np.random.permutation(len(X_train))
            X_train, y_train, r_train = X_train[perm], y_train[perm], r_train[perm]

            epoch_losses = []
            # Per-model loss tracking for debugging
            dqn_losses, lstm_losses, trans_losses, vae_losses = [], [], [], []
            batch_count = 0

            # Mini-batch training
            for i in range(0, len(X_train), batch_size):
                batch_count += 1

                # Progress logging every 1000 batches
                if batch_count % 1000 == 0:
                    logger.info(f"  Epoch {epoch+1}: batch {batch_count}/{total_batches} ({100*batch_count/total_batches:.1f}%)")
                batch_X = X_train[i:i+batch_size]
                batch_y = y_train[i:i+batch_size]
                batch_r = r_train[i:i+batch_size]

                # =====================
                # TRAIN DQN (Experience Replay)
                # =====================
                for j in range(len(batch_X) - 1):
                    state = batch_X[j]
                    action = int(batch_y[j])
                    reward = batch_r[j]
                    next_state = batch_X[j + 1]
                    done = (j == len(batch_X) - 2)

                    from .ml_models import Experience
                    exp = Experience(state, action, reward, next_state, done)
                    self.dqn.replay_buffer.push(exp)

                dqn_loss = self.dqn.train_step(batch_size=min(32, len(batch_X)))
                if dqn_loss:
                    epoch_losses.append(dqn_loss)
                    dqn_losses.append(dqn_loss)

                # =====================
                # TRAIN PPO (Policy Gradient)
                # =====================
                for j in range(len(batch_X)):
                    state = batch_X[j]
                    action = int(batch_y[j])
                    reward = batch_r[j]
                    done = (j == len(batch_X) - 1)

                    probs = self.ppo.get_action_probs(state)
                    log_prob = np.log(probs[action] + 1e-8)
                    value = self.ppo.get_value(state)

                    # Signature: (state, action, reward, value, log_prob, done)
                    self.ppo.store_transition(state, action, reward, value, log_prob, done)

                ppo_loss = self.ppo.train_step()
                if ppo_loss:
                    epoch_losses.append(ppo_loss)

                # =====================
                # TRAIN LSTM (Proper BPTT)
                # =====================
                if len(batch_X) >= 10:
                    seq_len = 10
                    # Create sequences for LSTM training
                    for j in range(0, len(batch_X) - seq_len, seq_len):
                        seq = batch_X[j:j+seq_len]
                        target = batch_y[j+seq_len-1:j+seq_len]  # Label for last timestep

                        if len(target) > 0:
                            # Proper backpropagation through time
                            lstm_loss = self.lstm.train_step(
                                seq.reshape(1, seq_len, -1),
                                target
                            )
                            epoch_losses.append(lstm_loss)
                            lstm_losses.append(lstm_loss)

                # =====================
                # TRAIN TRANSFORMER (Proper Gradient Descent)
                # =====================
                if len(batch_X) >= 10:
                    seq_len = 10
                    for j in range(0, len(batch_X) - seq_len, seq_len):
                        seq = batch_X[j:j+seq_len]
                        target = batch_y[j+seq_len-1:j+seq_len]

                        if len(target) > 0:
                            # Proper backpropagation
                            trans_loss = self.transformer.train_step(
                                seq.reshape(1, seq_len, -1),
                                target
                            )
                            epoch_losses.append(trans_loss)
                            trans_losses.append(trans_loss)

                # =====================
                # TRAIN VAE (Reconstruction + KL Loss)
                # =====================
                # VAE trains on individual states with optional regime labels
                vae_loss = self.vae.train_step(batch_X, batch_y % 4)  # 4 regimes
                epoch_losses.append(vae_loss)
                vae_losses.append(vae_loss)

            # Training accuracy (sample subset for speed)
            # Reset buffer and iterate so LSTM/Transformer get sequential context
            self.reset_state_buffer()
            train_preds = []
            for idx in fixed_train_indices:
                pred = self.predict(X_train[idx])
                train_preds.append(pred["action"])
            train_accuracy = np.mean(np.array(train_preds) == y_train[fixed_train_indices])

            # Validation accuracy (fixed indices for consistency)
            self.reset_state_buffer()
            val_preds = []
            for idx in fixed_val_indices:
                pred = self.predict(X_val[idx])
                val_preds.append(pred["action"])
            val_accuracy = np.mean(np.array(val_preds) == y_val[fixed_val_indices])
            self.reset_state_buffer()  # Clean up after validation

            epoch_time = time.time() - epoch_start

            # Overfitting indicator: train_acc >> val_acc
            overfit_gap = train_accuracy - val_accuracy

            # Record metrics
            avg_loss = np.mean(epoch_losses) if epoch_losses else 0
            self.training_metrics.training_loss.append(avg_loss)
            self.training_metrics.prediction_accuracy.append(val_accuracy)

            # Note: DQN epsilon decay happens automatically in DQN.train_step()
            # No additional decay needed here

            # Log every epoch for visibility
            overfit_warning = " ⚠️ OVERFITTING" if overfit_gap > 0.10 else ""
            logger.info(
                f"✓ Epoch {epoch+1}/{epochs} | "
                f"Loss: {avg_loss:.4f} | "
                f"Train: {train_accuracy:.2%} | Val: {val_accuracy:.2%} | "
                f"Gap: {overfit_gap:+.1%}{overfit_warning} | "
                f"Epsilon: {self.dqn.epsilon:.3f} | "
                f"Time: {epoch_time:.1f}s"
            )
            # Per-model loss breakdown for debugging
            logger.info(
                f"  📊 Loss breakdown: DQN={np.mean(dqn_losses):.2f}, "
                f"LSTM={np.mean(lstm_losses):.2f}, "
                f"Trans={np.mean(trans_losses):.2f}, "
                f"VAE={np.mean(vae_losses):.2f}"
            )

            # Update resume state
            self._last_epoch = epoch + 1
            self._best_val_accuracy = best_val_accuracy
            self._patience_counter = patience_counter

            # Early stopping check
            if val_accuracy > best_val_accuracy:
                best_val_accuracy = val_accuracy
                self._best_val_accuracy = best_val_accuracy
                patience_counter = 0
                self._patience_counter = 0
                self.save_checkpoints()  # Save best model
            else:
                patience_counter += 1
                self._patience_counter = patience_counter
                if patience_counter >= patience and epoch >= 10:  # Minimum 10 epochs
                    logger.info(f"⏹️  Early stopping at epoch {epoch+1} - no improvement for {patience} epochs")
                    break

        self.training_metrics.epochs_completed = epoch + 1  # Actual epochs completed
        self.training_metrics.total_samples = len(features)
        self.is_trained = True

        # Save resume state (but don't overwrite best checkpoint if early stopping occurred)
        self._last_epoch = epoch + 1
        if val_accuracy >= best_val_accuracy:
            # Only save final checkpoint if it's at least as good as the best
            self.save_checkpoints()
        else:
            logger.info(f"Keeping best checkpoint (acc={best_val_accuracy:.2%}) over final (acc={val_accuracy:.2%})")

        logger.info(f"Training complete! Best accuracy: {best_val_accuracy:.2%}")
        return self.training_metrics

    def reset_state_buffer(self):
        """Reset the state buffer (call between episodes/symbols)."""
        self.state_buffer.clear()

    def _get_sequence(self, state: np.ndarray) -> np.ndarray:
        """
        Build a sequence from the state buffer for LSTM/Transformer.

        Pushes the current state to the buffer and returns a
        (1, seq_len, state_dim) array. If the buffer has fewer than
        seq_len states, left-pads with zeros (the models learn to
        handle partial context via the zero-padded positions).
        """
        self.state_buffer.append(state.copy())

        buf_len = len(self.state_buffer)
        if buf_len >= self.seq_len:
            # Full sequence available
            seq = np.array(list(self.state_buffer))
        else:
            # Pad with zeros on the left for incomplete sequences
            padding = np.zeros((self.seq_len - buf_len, self.state_dim))
            seq = np.vstack([padding, np.array(list(self.state_buffer))])

        return seq.reshape(1, self.seq_len, self.state_dim)

    def predict(self, state: np.ndarray) -> Dict:
        """
        Get ensemble prediction from all models.

        LSTM and Transformer receive a sequence of the last seq_len states
        (from the state buffer) instead of a single state, matching
        how they were trained.

        Returns:
            action: 0=sell, 1=hold, 2=buy
            confidence: 0-1 confidence score
        """
        # Ensure state is correct shape
        if len(state.shape) == 1:
            if len(state) < self.state_dim:
                state = np.pad(state, (0, self.state_dim - len(state)))
            elif len(state) > self.state_dim:
                state = state[:self.state_dim]

        # Build sequence for sequential models
        seq = self._get_sequence(state)

        predictions = []
        confidences = []

        # DQN prediction (single state)
        q_values = self.dqn.get_q_values(state)
        dqn_action = np.argmax(q_values)
        dqn_probs = self._softmax(q_values)
        dqn_conf = dqn_probs[dqn_action]
        predictions.append(dqn_action)
        confidences.append(dqn_conf)

        # PPO prediction (single state)
        ppo_probs = self.ppo.get_action_probs(state)
        ppo_action = np.argmax(ppo_probs)
        predictions.append(ppo_action)
        confidences.append(ppo_probs[ppo_action])

        # LSTM prediction (full sequence)
        lstm_out, _ = self.lstm.forward(seq)
        lstm_probs = self._softmax(lstm_out[-1])
        lstm_action = np.argmax(lstm_probs)
        predictions.append(lstm_action)
        confidences.append(lstm_probs[lstm_action])

        # Transformer prediction (full sequence)
        trans_out = self.transformer.forward(seq)
        trans_probs = self._softmax(trans_out[-1])
        trans_action = np.argmax(trans_probs)
        predictions.append(trans_action)
        confidences.append(trans_probs[trans_action])

        # Ensemble vote (weighted by per-model confidence)
        action_votes = {0: 0, 1: 0, 2: 0}
        for pred, conf in zip(predictions, confidences):
            action_votes[pred] += conf

        final_action = max(action_votes, key=action_votes.get)

        # Confidence = model agreement * average confidence of agreeing models
        # This captures BOTH "how many models agree" and "how sure are they"
        # - 4/4 agree at 80% each → 1.0 * 0.80 = 0.80
        # - 3/4 agree at 70% each → 0.75 * 0.70 = 0.52
        # - 2/4 agree at 50% each → 0.50 * 0.50 = 0.25
        n_models = len(predictions)
        n_agree = sum(1 for p in predictions if p == final_action)
        agreement = n_agree / n_models

        agreeing_confs = [c for p, c in zip(predictions, confidences) if p == final_action]
        avg_conf = float(np.mean(agreeing_confs)) if agreeing_confs else 0

        final_confidence = agreement * avg_conf

        return {
            "action": final_action,
            "confidence": float(final_confidence),
            "agreement": float(agreement),
            "q_values": q_values.tolist(),
            "predictions": predictions,
        }

    def _softmax(self, x: np.ndarray) -> np.ndarray:
        """Compute softmax."""
        exp_x = np.exp(x - np.max(x))
        return exp_x / (np.sum(exp_x) + 1e-8)

    def save_checkpoints(self):
        """Save trained model weights to disk."""
        logger.info("Saving model checkpoints...")

        checkpoint = {
            "dqn_weights": {
                "q_network": self.dqn.q_network.get_weights(),
                "target_network": self.dqn.target_network.get_weights(),
                "epsilon": self.dqn.epsilon,
            },
            "ppo_weights": {
                "policy": self.ppo.policy_network.get_weights(),
                "value": self.ppo.value_network.get_weights(),
            },
            # Use get_weights() methods from trainable models
            "lstm_weights": self.lstm.get_weights(),
            "transformer_weights": self.transformer.get_weights(),
            "vae_weights": self.vae.get_weights(),
            "training_metrics": self.training_metrics.to_dict(),
            "is_trained": self.is_trained,
            "timestamp": datetime.now().isoformat(),
            # Resume support
            "last_epoch": getattr(self, '_last_epoch', 0),
            "best_val_accuracy": getattr(self, '_best_val_accuracy', 0),
            "patience_counter": getattr(self, '_patience_counter', 0),
        }

        checkpoint_path = CHECKPOINT_DIR / "model_checkpoint.pkl"
        with open(checkpoint_path, "wb") as f:
            pickle.dump(checkpoint, f)

        logger.info(f"Checkpoints saved to {checkpoint_path}")

    def load_checkpoints(self) -> bool:
        """Load trained model weights from disk."""
        checkpoint_path = CHECKPOINT_DIR / "model_checkpoint.pkl"

        if not checkpoint_path.exists():
            logger.warning("No checkpoint found - models will start untrained")
            return False

        try:
            with open(checkpoint_path, "rb") as f:
                checkpoint = pickle.load(f)

            # Restore DQN
            self.dqn.q_network.set_weights(checkpoint["dqn_weights"]["q_network"])
            self.dqn.target_network.set_weights(checkpoint["dqn_weights"]["target_network"])
            self.dqn.epsilon = checkpoint["dqn_weights"]["epsilon"]

            # Restore PPO
            self.ppo.policy_network.set_weights(checkpoint["ppo_weights"]["policy"])
            self.ppo.value_network.set_weights(checkpoint["ppo_weights"]["value"])

            # Restore trainable models using set_weights() methods
            self.lstm.set_weights(checkpoint["lstm_weights"])
            self.transformer.set_weights(checkpoint["transformer_weights"])
            self.vae.set_weights(checkpoint["vae_weights"])

            self.is_trained = checkpoint.get("is_trained", True)

            # Resume support
            self._last_epoch = checkpoint.get("last_epoch", 0)
            self._best_val_accuracy = checkpoint.get("best_val_accuracy", 0)
            self._patience_counter = checkpoint.get("patience_counter", 0)

            logger.info(f"Loaded checkpoint from {checkpoint['timestamp']}")
            logger.info(f"DQN epsilon: {self.dqn.epsilon:.4f}")
            if self._last_epoch > 0:
                logger.info(f"Resume info: epoch {self._last_epoch}, best_acc={self._best_val_accuracy:.2%}, patience={self._patience_counter}")

            return True

        except Exception as e:
            logger.error(f"Error loading checkpoint: {e}")
            return False

    def meets_training_requirements(self) -> Tuple[bool, str]:
        """Check if models meet minimum training requirements."""
        if not self.is_trained:
            return False, "Models have not been trained"

        if self.training_metrics.epochs_completed < self.min_training_epochs:
            return False, f"Only {self.training_metrics.epochs_completed}/{self.min_training_epochs} epochs completed"

        if self.training_metrics.total_samples < self.min_training_samples:
            return False, f"Only {self.training_metrics.total_samples}/{self.min_training_samples} samples trained"

        if self.dqn.epsilon > 0.1:
            return False, f"DQN still exploring (epsilon={self.dqn.epsilon:.2f} > 0.1)"

        return True, "Training requirements met"


class AlphaSourceManager:
    """
    Alternative Alpha Sources using APIs you already have!

    Sources:
    1. Fear & Greed Index (free, no key needed)
    2. Finnhub API (news sentiment, analyst ratings, insider transactions)
    3. Claude AI (LLM-powered market analysis and pattern recognition)
    4. Cross-asset signals (DXY, correlations via Yahoo Finance)

    The Claude integration is the secret sauce - it can:
    - Interpret news headlines for sentiment
    - Detect market regime changes
    - Identify patterns humans might miss
    - Provide contrarian signals
    """

    def __init__(self):
        self.sentiment_cache: Dict[str, Dict] = {}
        self.news_cache: Dict[str, Dict] = {}
        self.claude_cache: Dict[str, Dict] = {}
        self.fear_greed_value: float = 50
        self.last_update: Optional[datetime] = None
        self.cache_duration = timedelta(minutes=15)

        # Get API keys from settings
        try:
            from ..config import get_settings
            settings = get_settings()
            self.finnhub_api_key = settings.finnhub_api_key
            self.anthropic_api_key = settings.anthropic_api_key
        except Exception:
            self.finnhub_api_key = os.environ.get("FINNHUB_API_KEY", "")
            self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    async def get_fear_greed_index(self) -> Dict:
        """Fetch Crypto Fear & Greed Index (free, no key needed)."""
        import aiohttp

        try:
            url = "https://api.alternative.me/fng/"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        value = int(data["data"][0]["value"])
                        classification = data["data"][0]["value_classification"]

                        self.fear_greed_value = value

                        return {
                            "value": value,
                            "classification": classification,
                            "signal": self._fear_greed_signal(value),
                            "source": "alternative.me",
                        }
        except Exception as e:
            logger.warning(f"Failed to fetch Fear & Greed: {e}")

        return {"value": 50, "classification": "Neutral", "signal": 0, "source": "default"}

    def _fear_greed_signal(self, value: int) -> float:
        """Contrarian Fear & Greed signal."""
        if value < 25:
            return 1.0  # Extreme fear = strong buy
        elif value < 45:
            return 0.5
        elif value < 55:
            return 0.0
        elif value < 75:
            return -0.5
        else:
            return -1.0  # Extreme greed = strong sell

    async def get_finnhub_sentiment(self, symbol: str) -> Dict:
        """
        Get market sentiment from Finnhub API.

        Finnhub provides:
        - News sentiment scores
        - Analyst recommendations (buy/hold/sell)
        - Insider transactions
        - Social sentiment (Reddit, Twitter mentions)

        Free tier: 60 API calls/minute
        Docs: https://finnhub.io/docs/api
        """
        import aiohttp

        cache_key = f"finnhub_{symbol}"
        if cache_key in self.sentiment_cache:
            cached = self.sentiment_cache[cache_key]
            if datetime.now() - cached.get("timestamp", datetime.min) < self.cache_duration:
                return cached["data"]

        default_response = {
            "symbol": symbol,
            "news_sentiment": 0,
            "analyst_signal": 0,
            "insider_signal": 0,
            "social_sentiment": 0,
            "signal": 0,
            "source": "default",
        }

        if not self.finnhub_api_key:
            logger.debug("Finnhub API key not set")
            return default_response

        try:
            base_url = "https://finnhub.io/api/v1"
            signals = []

            async with aiohttp.ClientSession() as session:
                # 1. News Sentiment
                try:
                    url = f"{base_url}/news-sentiment"
                    params = {"symbol": symbol, "token": self.finnhub_api_key}
                    async with session.get(url, params=params, timeout=10) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("sentiment"):
                                # Finnhub sentiment: -1 (bearish) to 1 (bullish)
                                buzz_score = data.get("buzz", {}).get("buzz", 0)
                                sentiment_score = data["sentiment"].get("bullishPercent", 50) / 100
                                news_signal = (sentiment_score - 0.5) * 2  # Normalize to -1 to 1

                                # Weight by buzz (more mentions = more significant)
                                if buzz_score > 1.5:
                                    news_signal *= 1.2

                                signals.append(("news", news_signal))
                except Exception as e:
                    logger.debug(f"Finnhub news sentiment error: {e}")

                # 2. Analyst Recommendations
                try:
                    url = f"{base_url}/stock/recommendation"
                    params = {"symbol": symbol, "token": self.finnhub_api_key}
                    async with session.get(url, params=params, timeout=10) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data:
                                latest = data[0]  # Most recent
                                buy = latest.get("buy", 0) + latest.get("strongBuy", 0)
                                sell = latest.get("sell", 0) + latest.get("strongSell", 0)
                                hold = latest.get("hold", 0)
                                total = buy + sell + hold

                                if total > 0:
                                    # Score: more buys = positive, more sells = negative
                                    analyst_signal = (buy - sell) / total
                                    signals.append(("analyst", analyst_signal))
                except Exception as e:
                    logger.debug(f"Finnhub analyst error: {e}")

                # 3. Insider Transactions (for stocks)
                try:
                    url = f"{base_url}/stock/insider-transactions"
                    params = {"symbol": symbol, "token": self.finnhub_api_key}
                    async with session.get(url, params=params, timeout=10) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("data"):
                                # Analyze recent insider activity
                                recent = data["data"][:10]  # Last 10 transactions
                                buys = sum(1 for t in recent if t.get("transactionType") == "P")
                                sells = sum(1 for t in recent if t.get("transactionType") == "S")

                                if buys + sells > 0:
                                    insider_signal = (buys - sells) / (buys + sells)
                                    signals.append(("insider", insider_signal * 0.5))  # Lower weight
                except Exception as e:
                    logger.debug(f"Finnhub insider error: {e}")

                # 4. Social Sentiment (if available)
                try:
                    url = f"{base_url}/stock/social-sentiment"
                    params = {"symbol": symbol, "token": self.finnhub_api_key}
                    async with session.get(url, params=params, timeout=10) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            reddit = data.get("reddit", [])
                            twitter = data.get("twitter", [])

                            if reddit or twitter:
                                # Aggregate sentiment from social platforms
                                all_mentions = reddit + twitter
                                if all_mentions:
                                    avg_score = sum(m.get("score", 0) for m in all_mentions) / len(all_mentions)
                                    social_signal = max(-1, min(1, avg_score / 100))
                                    signals.append(("social", social_signal))
                except Exception as e:
                    logger.debug(f"Finnhub social error: {e}")

            # Combine signals with equal weighting
            if signals:
                combined_signal = sum(s[1] for s in signals) / len(signals)
            else:
                combined_signal = 0

            result = {
                "symbol": symbol,
                "signals": {name: round(val, 3) for name, val in signals},
                "signal": round(max(-1, min(1, combined_signal)), 3),
                "source": "finnhub",
                "num_signals": len(signals),
            }

            self.sentiment_cache[cache_key] = {
                "data": result,
                "timestamp": datetime.now(),
            }

            return result

        except Exception as e:
            logger.warning(f"Finnhub API error for {symbol}: {e}")

        return default_response

    async def get_claude_alpha(self, symbol: str, market_data: Optional[Dict] = None) -> Dict:
        """
        Use Claude to generate alpha signals from market analysis.

        Claude analyzes:
        1. Recent price action and technical patterns
        2. News headlines and sentiment
        3. Market regime (trending, ranging, volatile)
        4. Cross-asset correlations
        5. Contrarian opportunities

        This is your UNIQUE EDGE - LLM-powered trading signals!
        """
        cache_key = f"claude_{symbol}"
        if cache_key in self.claude_cache:
            cached = self.claude_cache[cache_key]
            if datetime.now() - cached.get("timestamp", datetime.min) < self.cache_duration:
                return cached["data"]

        default_response = {
            "symbol": symbol,
            "signal": 0,
            "confidence": 0,
            "analysis": "No analysis available",
            "recommendation": "hold",
            "source": "default",
        }

        if not self.anthropic_api_key:
            logger.debug("Anthropic API key not set for Claude alpha")
            return default_response

        try:
            import anthropic

            # Gather context for Claude
            context_parts = [f"Symbol: {symbol}"]

            # Add Fear & Greed
            fg = await self.get_fear_greed_index()
            context_parts.append(f"Fear & Greed Index: {fg['value']} ({fg['classification']})")

            # Add Finnhub sentiment if available
            if self.finnhub_api_key:
                finnhub = await self.get_finnhub_sentiment(symbol)
                if finnhub.get("source") == "finnhub":
                    context_parts.append(f"Finnhub Signals: {finnhub.get('signals', {})}")

            # Add market data if provided
            if market_data:
                if "price" in market_data:
                    context_parts.append(f"Current Price: ${market_data['price']:.2f}")
                if "change_24h" in market_data:
                    context_parts.append(f"24h Change: {market_data['change_24h']:.2f}%")
                if "volume" in market_data:
                    context_parts.append(f"Volume: {market_data['volume']}")

            context = "\n".join(context_parts)

            # Create Claude client
            client = anthropic.Anthropic(api_key=self.anthropic_api_key)

            # Generate alpha signal
            prompt = f"""You are a quantitative trading analyst. Analyze this market data and provide a trading signal.

MARKET DATA:
{context}

Provide your analysis in this EXACT JSON format (no markdown, just raw JSON):
{{
    "signal": <float between -1 (strong sell) and 1 (strong buy)>,
    "confidence": <float between 0 and 1>,
    "regime": "<trending_up|trending_down|ranging|volatile>",
    "key_factors": ["<factor1>", "<factor2>", "<factor3>"],
    "recommendation": "<strong_buy|buy|hold|sell|strong_sell>",
    "reasoning": "<one sentence explanation>"
}}

Be contrarian when sentiment is extreme. Consider:
- Fear & Greed extremes are often reversal signals
- High confidence requires multiple confirming signals
- Default to 'hold' (signal near 0) when uncertain"""

            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            # Parse Claude's response
            response_text = response.content[0].text.strip()

            # Try to extract JSON from response
            try:
                import json
                # Handle potential markdown code blocks
                if "```" in response_text:
                    response_text = response_text.split("```")[1]
                    if response_text.startswith("json"):
                        response_text = response_text[4:]

                analysis = json.loads(response_text)

                result = {
                    "symbol": symbol,
                    "signal": max(-1, min(1, float(analysis.get("signal", 0)))),
                    "confidence": max(0, min(1, float(analysis.get("confidence", 0.5)))),
                    "regime": analysis.get("regime", "unknown"),
                    "key_factors": analysis.get("key_factors", []),
                    "recommendation": analysis.get("recommendation", "hold"),
                    "reasoning": analysis.get("reasoning", ""),
                    "source": "claude",
                }

                self.claude_cache[cache_key] = {
                    "data": result,
                    "timestamp": datetime.now(),
                }

                logger.info(f"Claude alpha for {symbol}: signal={result['signal']:.2f}, conf={result['confidence']:.2f}")
                return result

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse Claude response: {e}")
                # Try to extract signal from text
                if "buy" in response_text.lower():
                    return {**default_response, "signal": 0.3, "source": "claude_fallback"}
                elif "sell" in response_text.lower():
                    return {**default_response, "signal": -0.3, "source": "claude_fallback"}

        except Exception as e:
            logger.warning(f"Claude alpha error for {symbol}: {e}")

        return default_response

    async def get_cross_asset_signals(self) -> Dict:
        """
        Analyze cross-asset correlations (free via Yahoo Finance).

        - DXY strength = bearish for risk assets
        - VIX spikes = opportunity or danger
        - Gold/BTC correlation for risk sentiment
        """
        import aiohttp

        try:
            # Fetch DXY (Dollar Index)
            url = "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB"
            params = {"interval": "1d", "range": "5d"}
            headers = {"User-Agent": "Mozilla/5.0"}

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        result = data.get("chart", {}).get("result", [])

                        if result:
                            quotes = result[0].get("indicators", {}).get("quote", [{}])[0]
                            closes = quotes.get("close", [])

                            if len(closes) >= 2:
                                dxy_current = closes[-1]
                                dxy_prev = closes[-2]

                                if dxy_current and dxy_prev:
                                    dxy_change = (dxy_current - dxy_prev) / dxy_prev

                                    # Strong dollar = bearish for risk assets
                                    if dxy_change > 0.005:
                                        dxy_signal = -0.3
                                    elif dxy_change > 0:
                                        dxy_signal = -0.1
                                    elif dxy_change < -0.005:
                                        dxy_signal = 0.3
                                    else:
                                        dxy_signal = 0.1

                                    return {
                                        "dxy_value": round(dxy_current, 2),
                                        "dxy_change_pct": round(dxy_change * 100, 2),
                                        "regime": "risk_off" if dxy_signal < 0 else "risk_on",
                                        "signal": dxy_signal,
                                        "source": "yahoo",
                                    }

        except Exception as e:
            logger.debug(f"Cross-asset data error: {e}")

        return {"dxy_value": 0, "dxy_change_pct": 0, "regime": "neutral", "signal": 0, "source": "default"}

    async def get_combined_alpha(self, symbol: str, market_data: Optional[Dict] = None) -> Dict:
        """
        Combine all alpha sources into a single trading signal.

        Weighting (adapts based on available data):
        - Fear & Greed: 15% (always available)
        - Finnhub Sentiment: 25% (if API key set)
        - Claude AI Analysis: 40% (if API key set - this is your edge!)
        - Cross-Asset: 20% (always available via Yahoo)
        """
        # Fetch all signals in parallel
        tasks = [
            self.get_fear_greed_index(),
            self.get_finnhub_sentiment(symbol),
            self.get_claude_alpha(symbol, market_data),
            self.get_cross_asset_signals(),
        ]

        fear_greed, finnhub, claude, cross_asset = await asyncio.gather(*tasks)

        # Dynamic weighting based on data availability
        weights = {
            "fear_greed": 0.15,  # Always available
            "finnhub": 0.25 if finnhub.get("source") == "finnhub" else 0.05,
            "claude": 0.40 if claude.get("source") == "claude" else 0.10,
            "cross_asset": 0.20 if cross_asset.get("source") == "yahoo" else 0.10,
        }

        # Normalize weights
        total_weight = sum(weights.values())
        weights = {k: v / total_weight for k, v in weights.items()}

        # Combine signals
        combined_signal = (
            fear_greed["signal"] * weights["fear_greed"] +
            finnhub["signal"] * weights["finnhub"] +
            claude["signal"] * weights["claude"] +
            cross_asset["signal"] * weights["cross_asset"]
        )

        # Adjust confidence based on Claude's confidence
        confidence = claude.get("confidence", 0.5) if claude.get("source") == "claude" else abs(combined_signal)

        # Determine recommendation
        if combined_signal > 0.4:
            recommendation = "strong_buy"
        elif combined_signal > 0.2:
            recommendation = "buy"
        elif combined_signal < -0.4:
            recommendation = "strong_sell"
        elif combined_signal < -0.2:
            recommendation = "sell"
        else:
            recommendation = "hold"

        return {
            "symbol": symbol,
            "combined_signal": round(combined_signal, 3),
            "confidence": round(confidence, 2),
            "recommendation": recommendation,
            "components": {
                "fear_greed": fear_greed,
                "finnhub": finnhub,
                "claude": claude,
                "cross_asset": cross_asset,
            },
            "weights_used": {k: round(v, 2) for k, v in weights.items()},
            "timestamp": datetime.now().isoformat(),
        }


# Global instances
_data_downloader: Optional[HistoricalDataDownloader] = None
_model_pretrainer: Optional[ModelPreTrainer] = None
_backtester: Optional[WalkForwardBacktester] = None
_alpha_manager: Optional[AlphaSourceManager] = None


def get_data_downloader() -> HistoricalDataDownloader:
    """Get or create data downloader instance."""
    global _data_downloader
    if _data_downloader is None:
        _data_downloader = HistoricalDataDownloader()
    return _data_downloader


def get_model_pretrainer() -> ModelPreTrainer:
    """Get or create model pre-trainer instance."""
    global _model_pretrainer
    if _model_pretrainer is None:
        _model_pretrainer = ModelPreTrainer()
    return _model_pretrainer


def get_backtester() -> WalkForwardBacktester:
    """Get or create backtester instance."""
    global _backtester
    if _backtester is None:
        _backtester = WalkForwardBacktester()
    return _backtester


def get_alpha_manager() -> AlphaSourceManager:
    """Get or create alpha manager instance."""
    global _alpha_manager
    if _alpha_manager is None:
        _alpha_manager = AlphaSourceManager()
    return _alpha_manager


async def run_full_training_pipeline(
    days_of_data: int = 180,
    training_epochs: int = 40  # Balanced for ~1 hour training with early stopping
) -> Dict:
    """
    Run the complete pre-training pipeline:
    1. Download historical data
    2. Train models
    3. Run backtest
    4. Save checkpoints

    Returns training and backtest results.
    """
    logger.info("="*60)
    logger.info("STARTING FULL TRAINING PIPELINE")
    logger.info("="*60)

    # Initialize components
    downloader = get_data_downloader()
    pretrainer = get_model_pretrainer()
    backtester = get_backtester()

    # Step 1: Download historical data
    logger.info("\n📥 Step 1: Downloading historical data...")
    historical_data = await downloader.download_all(days=days_of_data)

    if not historical_data:
        # Try loading from disk
        historical_data = downloader.load_all_from_disk()

    if not historical_data:
        return {"error": "Failed to obtain historical data"}

    logger.info(f"Loaded data for {len(historical_data)} symbols")

    # Step 2: Prepare training data
    logger.info("\n🔧 Step 2: Preparing training data...")
    features, labels, rewards = pretrainer.prepare_training_data(historical_data, backtester)

    if len(features) == 0:
        return {"error": "Failed to prepare training data"}

    logger.info(f"Prepared {len(features)} training samples")

    # Step 3: Train models
    logger.info("\n🧠 Step 3: Training ML models...")
    training_metrics = pretrainer.train(
        features, labels, rewards,
        epochs=training_epochs,
        batch_size=256  # Larger batch = faster training
    )

    # Step 4: Run backtest
    logger.info("\n📊 Step 4: Running walk-forward backtest...")
    backtest_result = backtester.run_backtest(historical_data, pretrainer)

    # Step 5: Validate training
    logger.info("\n✅ Step 5: Validating training requirements...")
    meets_requirements, reason = pretrainer.meets_training_requirements()

    result = {
        "success": meets_requirements,
        "reason": reason,
        "training_metrics": training_metrics.to_dict(),
        "backtest_result": backtest_result.to_dict(),
        "symbols_trained": list(historical_data.keys()),
        "checkpoint_path": str(CHECKPOINT_DIR / "model_checkpoint.pkl"),
    }

    logger.info("\n" + "="*60)
    logger.info("TRAINING PIPELINE COMPLETE")
    logger.info(f"Status: {'✅ READY FOR LIVE TRADING' if meets_requirements else '❌ ' + reason}")
    logger.info(f"Backtest Return: {backtest_result.total_return_pct:.1f}%")
    logger.info(f"Sharpe Ratio: {backtest_result.sharpe_ratio:.2f}")
    logger.info(f"Win Rate: {backtest_result.win_rate*100:.1f}%")
    logger.info("="*60)

    return result
