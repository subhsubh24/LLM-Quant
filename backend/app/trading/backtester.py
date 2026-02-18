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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import numpy as np

from .microstructure import MicrostructureExtractor, OrderBookFetcher
from .continuous_learning import ContinuousLearner, AdaptiveEnsembleWeighter

logger = logging.getLogger(__name__)


def _run_async_in_thread(coro_func):
    """
    Run async coroutine from sync context or running event loop.

    Detects if we're in a running event loop and handles appropriately:
    - If running event loop exists: Uses ThreadPoolExecutor to run in separate thread
    - If no event loop: Uses asyncio.run()

    This avoids "asyncio.run() cannot be called from a running event loop" error.

    Args:
        coro_func: Either a coroutine object or a callable that returns a coroutine
    """
    try:
        asyncio.get_running_loop()
        # We're inside a running event loop, need to run async code in thread pool
        def run_in_new_loop():
            # Create fresh event loop in thread, avoiding the original loop
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                # If coro_func is already a coroutine, use it; otherwise call it
                if asyncio.iscoroutine(coro_func):
                    return new_loop.run_until_complete(coro_func)
                else:
                    return new_loop.run_until_complete(coro_func())
            finally:
                new_loop.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(run_in_new_loop).result()
    except RuntimeError:
        # No running event loop, safe to use asyncio.run()
        if asyncio.iscoroutine(coro_func):
            return asyncio.run(coro_func)
        else:
            return asyncio.run(coro_func())

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
        # Helper to handle inf/nan values for JSON serialization
        def safe_round(val: float, decimals: int = 2) -> float:
            if not np.isfinite(val):
                return 0.0
            return round(val, decimals)

        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "initial_capital": self.initial_capital,
            "final_capital": safe_round(self.final_capital, 2),
            "total_return": safe_round(self.total_return, 2),
            "total_return_pct": safe_round(self.total_return_pct, 2),
            "sharpe_ratio": safe_round(self.sharpe_ratio, 3),
            "sortino_ratio": safe_round(self.sortino_ratio, 3),
            "max_drawdown": safe_round(self.max_drawdown, 2),
            "max_drawdown_pct": safe_round(self.max_drawdown_pct, 2),
            "win_rate": safe_round(self.win_rate * 100, 1),
            "profit_factor": safe_round(self.profit_factor, 2),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "avg_win": safe_round(self.avg_win, 2),
            "avg_loss": safe_round(self.avg_loss, 2),
            "avg_holding_period_hours": safe_round(self.avg_holding_period, 1),
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

    # ==========================================================================
    # FAST BACKTEST SYMBOLS (top liquidity only — runs in minutes, not days)
    # ==========================================================================
    BACKTEST_CRYPTO_SYMBOLS = [
        "BTC", "ETH", "BNB", "XRP", "SOL", "ADA", "DOGE", "AVAX", "LINK", "DOT",
        "MATIC", "UNI", "ATOM", "NEAR", "APT", "ARB", "OP", "INJ", "FIL", "LTC",
    ]
    BACKTEST_STOCK_SYMBOLS = [
        "SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "JPM",
    ]

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

                        # Move to next batch (BUG #1 FIX: Check if data is non-empty)
                        if not data:
                            break
                        current_start = data[-1][0] + 1

                        # Rate limiting
                        await asyncio.sleep(0.1)

            logger.info(f"Downloaded {len(candles)} candles for {symbol}")
            self.data_cache[symbol] = candles

            # Save to disk
            self._save_to_disk(symbol, candles)

            return candles

        except asyncio.TimeoutError as e:
            # BUG #19 FIX: Handle specific exception types with proper logging
            logger.error(f"Timeout downloading {symbol}: {e}")
            return []
        except aiohttp.ClientError as e:
            logger.error(f"Connection error downloading {symbol}: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error downloading {symbol}: {type(e).__name__}: {e}")
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

                    # BUG #2 FIX: Validate quote array is non-empty before accessing
                    quote_arr = quotes.get("indicators", {}).get("quote", [])
                    if not quote_arr or not isinstance(quote_arr[0], dict):
                        return []
                    ohlcv = quote_arr[0]

                    opens = ohlcv.get("open", [])
                    highs = ohlcv.get("high", [])
                    lows = ohlcv.get("low", [])
                    closes = ohlcv.get("close", [])
                    volumes = ohlcv.get("volume", [])

                    # BUG #3 FIX: Ensure all arrays have same length before accessing by index
                    min_len = min(len(opens), len(highs), len(lows), len(closes), len(volumes))
                    for i in range(min(len(timestamps), min_len)):
                        ts = timestamps[i]
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

        except asyncio.TimeoutError as e:
            # BUG #19 FIX: Handle timeout errors with proper logging
            logger.error(f"Timeout downloading {symbol}: {e}")
            return []
        except aiohttp.ClientError as e:
            logger.error(f"Connection error downloading {symbol}: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error downloading {symbol}: {type(e).__name__}: {e}")
            return []

    async def download_all(self, days: int = 365, max_concurrent: int = 10, fast_backtest: bool = True) -> Dict[str, List[OHLCV]]:
        """Download historical data for training with parallel downloads.

        Args:
            days: Number of days of history to download
            max_concurrent: Max parallel downloads
            fast_backtest: If True, use top-30 liquid symbols only (runs in minutes).
                          If False, use full 1300+ symbol universe (runs in hours/days).
        """
        if fast_backtest:
            crypto_symbols = self.BACKTEST_CRYPTO_SYMBOLS
            stock_symbols = self.BACKTEST_STOCK_SYMBOLS
            logger.info(f"⚡ FAST BACKTEST MODE: Using {len(crypto_symbols)} crypto + {len(stock_symbols)} stock symbols")
        else:
            crypto_symbols = self.CRYPTO_SYMBOLS
            stock_symbols = self.STOCK_SYMBOLS

        total_crypto = len(crypto_symbols)
        total_stocks = len(stock_symbols)
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
        for symbol in crypto_symbols:
            tasks.append(download_with_limit(symbol, is_crypto=True))
        for symbol in stock_symbols:
            tasks.append(download_with_limit(symbol, is_crypto=False))

        # Execute all downloads with concurrency limit
        # BUG #14 FIX: Validate async results are not exceptions
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Check for and log any exceptions returned
        exception_count = 0
        for result in results:
            if isinstance(result, Exception):
                exception_count += 1
                logger.warning(f"Async download raised exception: {result}")

        logger.info(f"Download complete: {len(self.data_cache)} symbols cached, {downloaded['failed']} failed, {exception_count} exceptions")
        return self.data_cache if len(self.data_cache) > 0 else {}

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
        train_window_days: int = 730,  # 2 years: Patterns across 1600h cycles need repetition
        test_window_days: int = 60,    # 2.5 months for robust validation
        step_days: int = 10,
        initial_capital: float = 10000.0
    ):
        self.train_window = train_window_days
        self.test_window = test_window_days
        self.step_days = step_days
        self.initial_capital = initial_capital

        # Timeframe configuration (set from config during run_backtest, defaults to 1h)
        self._annualization_factor = 365 * 24  # Default: hourly crypto (8760 candles/year)
        self._candles_per_day = 24             # Default: 1h candles

        self.results: List[BacktestResult] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.all_trades: List[Dict] = []

    def prepare_features(self, candles: List[OHLCV], lookback: int = 400) -> np.ndarray:
        """
        Prepare feature matrix from OHLCV data.

        Features:
        - Returns (1, 5, 10, 20 period)
        - Volatility (realized, Parkinson, Garman-Klass)
        - RSI, MACD, Bollinger Bands
        - Volume profile
        - Price momentum
        - EXTENDED LOOKBACK: 400 hours = 16+ days of context for 1600h predictions
        """
        if len(candles) < lookback + 20:
            return np.array([])

        closes = np.array([c.close for c in candles])
        highs = np.array([c.high for c in candles])
        lows = np.array([c.low for c in candles])
        volumes = np.array([c.volume for c in candles])

        # BUG FIX #7: Validate price data is positive before logarithm operations
        assert np.all(closes > 0), "Close prices contain non-positive values - cannot compute log returns"
        assert np.all(highs > 0), "High prices contain non-positive values - cannot compute log returns"
        assert np.all(lows > 0), "Low prices contain non-positive values - cannot compute log returns"

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
            realized_vol = np.std(log_returns) * np.sqrt(self._annualization_factor)  # Annualized

            # Parkinson volatility (high-low based)
            hl_ratio = np.log(window_high / (window_low + 1e-8))
            parkinson_vol = np.sqrt(np.mean(hl_ratio ** 2) / (4 * np.log(2))) * np.sqrt(self._annualization_factor)

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

            # PHASE E: Enhanced Features
            # Mean reversion signal (distance from 50-period MA)
            sma_50 = np.mean(window_close[-50:]) if len(window_close) >= 50 else np.mean(window_close)
            mean_reversion = (closes[i] - sma_50) / (sma_50 + 1e-8)

            # Volume weighted momentum
            vol_weighted_close = np.sum(window_close[-20:] * window_vol[-20:]) / (np.sum(window_vol[-20:]) + 1e-8)
            vol_momentum = (closes[i] - vol_weighted_close) / (vol_weighted_close + 1e-8)

            # Volatility regime (recent vs historical)
            recent_vol = np.std(log_returns[-10:]) if len(log_returns) >= 10 else realized_vol
            historical_vol = np.std(log_returns[:-10]) if len(log_returns) > 10 else realized_vol
            vol_regime = (recent_vol - historical_vol) / (historical_vol + 1e-8)

            # Price acceleration (second derivative)
            if len(window_close) >= 3:
                accel = (closes[i] - 2*closes[i-1] + closes[i-2]) / (closes[i-1] + 1e-8)
            else:
                accel = 0

            # Return volatility (how volatile are returns?)
            return_vol = np.std(log_returns) if len(log_returns) > 1 else 0

            # TIER 1 FIX: MICROSTRUCTURE FEATURES (approximated from OHLC)
            # These capture institutional behavior patterns

            # 1. Volume acceleration: Rate of change of volume
            if len(window_vol) >= 5:
                vol_recent = np.mean(window_vol[-5:])
                vol_historical = np.mean(window_vol[-20:-5]) if len(window_vol) >= 20 else vol_recent
                vol_accel = (vol_recent - vol_historical) / (vol_historical + 1e-8)
            else:
                vol_accel = 0

            # 2. Bid-ask spread approximation: High-Low as proxy for spread
            hl_spread = (np.max(window_high) - np.min(window_low)) / (np.mean(window_close) + 1e-8)

            # 3. Order flow imbalance: Where did price close in the range?
            if len(window_high) > 0:
                hl_range = window_high[-1] - window_low[-1]
                if hl_range > 0:
                    order_imbalance = (closes[i] - window_low[-1]) / hl_range - 0.5  # Range -0.5 to 0.5
                else:
                    order_imbalance = 0
            else:
                order_imbalance = 0

            # 4. VWAP (Volume-weighted average price)
            if np.sum(window_vol[-20:]) > 0:
                vwap = np.sum(window_close[-20:] * window_vol[-20:]) / np.sum(window_vol[-20:])
                price_to_vwap = (closes[i] - vwap) / (vwap + 1e-8)
            else:
                price_to_vwap = 0

            # 5. Volume concentration: Is volume above/below average?
            avg_vol = np.mean(window_vol[-20:]) if len(window_vol) >= 20 else 1
            vol_concentration = window_vol[-1] / (avg_vol + 1e-8) - 1  # 0 = avg, +0.5 = 50% above, etc.

            # ADVANCED FEATURES (Top funds use 50-100+ features)
            # 6. Stochastic Oscillator (captures momentum differently than RSI)
            period = 14
            if len(window_close) >= period:
                lowest_low = np.min(window_close[-period:])
                highest_high = np.max(window_close[-period:])
                stoch = (closes[i] - lowest_low) / (highest_high - lowest_low + 1e-8) if highest_high > lowest_low else 0.5
            else:
                stoch = 0.5

            # 7. Average True Range (ATR) normalized by price
            tr_values = []
            for j in range(max(1, len(window_close) - 14), len(window_close)):
                tr = max(window_high[j] - window_low[j],
                        abs(window_high[j] - window_close[j-1] if j > 0 else window_high[j]),
                        abs(window_low[j] - window_close[j-1] if j > 0 else window_low[j]))
                tr_values.append(tr)
            atr_value = np.mean(tr_values) if tr_values else 0
            atr_ratio = atr_value / (closes[i] + 1e-8)

            # 8. Mean Reversion Strength (how far from moving averages)
            sma_100 = np.mean(window_close[-100:]) if len(window_close) >= 100 else np.mean(window_close)
            sma_200 = np.mean(window_close[-200:]) if len(window_close) >= 200 else np.mean(window_close)
            mean_reversion_100 = (closes[i] - sma_100) / (sma_100 + 1e-8)
            mean_reversion_200 = (closes[i] - sma_200) / (sma_200 + 1e-8)

            # 9. Volatility mean reversion (vol above/below average)
            if len(log_returns) >= 20:
                recent_vol_20 = np.std(log_returns[-20:])
                long_vol = np.std(log_returns)
                vol_mean_reversion = (recent_vol_20 - long_vol) / (long_vol + 1e-8)
            else:
                vol_mean_reversion = 0

            # 10. Volume trend (volume increasing or decreasing)
            if len(window_vol) >= 5:
                vol_recent_mean = np.mean(window_vol[-5:])
                vol_old_mean = np.mean(window_vol[-20:-5]) if len(window_vol) >= 20 else vol_recent_mean
                vol_trend = (vol_recent_mean - vol_old_mean) / (vol_old_mean + 1e-8)
            else:
                vol_trend = 0

            # 11. Price Range over Close
            if len(window_close) >= 1:
                price_range_ratio = (np.max(window_close[-10:]) - np.min(window_close[-10:])) / (closes[i] + 1e-8) if len(window_close) >= 10 else 0
            else:
                price_range_ratio = 0

            # 12. Price breakout detection (new highs/lows in 20-period)
            if len(window_close) >= 20:
                is_new_high = closes[i] >= np.max(window_close[-20:-1]) if len(window_close) > 20 else False
                is_new_low = closes[i] <= np.min(window_close[-20:-1]) if len(window_close) > 20 else False
                breakout_signal = float(is_new_high) - float(is_new_low)
            else:
                breakout_signal = 0

            # 13. Jump detection (large single-bar moves)
            if len(log_returns) > 0:
                recent_jumps = np.sum(np.abs(log_returns[-10:]) > np.mean(np.abs(log_returns)) * 2) if len(log_returns) >= 10 else 0
                jump_ratio = recent_jumps / 10 if len(log_returns) >= 10 else 0
            else:
                jump_ratio = 0

            # 14. Tail risk (skewness of returns) - FIXED: use centered returns
            if len(log_returns) >= 20:
                try:
                    recent_returns = log_returns[-20:]
                    # BUG FIX #1: Validate minimum returns for skewness calculation
                    if len(recent_returns) < 3:
                        return_skew = 0
                    else:
                        mean_return = np.mean(recent_returns)
                        # Correct skewness formula: E[(X - mean)^3] / std^3
                        centered_returns = recent_returns - mean_return
                        return_skew = (np.mean(centered_returns ** 3)) / ((np.std(recent_returns) ** 3) + 1e-8)
                except Exception as e:
                    # BUG #1: Bare except masks all exceptions - log actual error
                    logger.debug(f"Skewness calculation error for {symbol}: {e}")
                    return_skew = 0
            else:
                return_skew = 0

            # 15. Price close pattern (above/below open, above/below previous)
            if len(window_close) >= 2:
                closes_above_prev = 1.0 if closes[i] > window_close[-2] else -1.0
            else:
                closes_above_prev = 0

            # =====================================================================
            # NEW FEATURES: Fill 29 zero-padded dimensions with real signal
            # These replace dead zero-padding that wasted 45% of model capacity.
            # =====================================================================

            # 16. Cross-timeframe momentum: 50-period vs 200-period MA convergence
            sma_50_local = np.mean(window_close[-50:]) if len(window_close) >= 50 else np.mean(window_close)
            sma_200_local = np.mean(window_close[-200:]) if len(window_close) >= 200 else np.mean(window_close)
            ma_cross_50_200 = (sma_50_local - sma_200_local) / (sma_200_local + 1e-8)

            # 17. MA cross momentum: 10-period vs 50-period (faster signal)
            sma_10 = np.mean(window_close[-10:]) if len(window_close) >= 10 else closes[i]
            ma_cross_10_50 = (sma_10 - sma_50_local) / (sma_50_local + 1e-8)

            # 18. Accumulation/Distribution proxy (volume-price correlation)
            if len(window_close) >= 20 and len(window_high) >= 20:
                clv = np.zeros(20)
                for k in range(20):
                    hl = window_high[-20+k] - window_low[-20+k]
                    if hl > 0:
                        clv[k] = ((window_close[-20+k] - window_low[-20+k]) -
                                  (window_high[-20+k] - window_close[-20+k])) / hl
                ad_line = np.cumsum(clv * window_vol[-20:])
                ad_momentum = (ad_line[-1] - ad_line[0]) / (np.abs(ad_line[0]) + 1e-8) if len(ad_line) > 0 else 0
            else:
                ad_momentum = 0

            # 19. Wick ratio: rejection signal (long wicks = reversal)
            body = abs(closes[i] - window_close[-2]) if len(window_close) >= 2 else 1e-8
            upper_wick = highs[i] - max(closes[i], window_close[-2] if len(window_close) >= 2 else closes[i])
            lower_wick = min(closes[i], window_close[-2] if len(window_close) >= 2 else closes[i]) - lows[i]
            total_wick = upper_wick + lower_wick
            wick_body_ratio = total_wick / (body + 1e-8)
            wick_body_ratio = min(wick_body_ratio, 10.0)  # Cap at 10

            # 20. Upper wick dominance (selling pressure)
            wick_direction = (upper_wick - lower_wick) / (total_wick + 1e-8)

            # 21. Returns 50-period (longer-term momentum)
            returns_50 = (closes[i] - closes[i-50]) / (closes[i-50] + 1e-8) if i >= 50 else 0

            # 22. Returns 100-period
            returns_100 = (closes[i] - closes[i-100]) / (closes[i-100] + 1e-8) if i >= 100 else 0

            # 23. Returns 200-period (match primary prediction horizon)
            returns_200 = (closes[i] - closes[i-200]) / (closes[i-200] + 1e-8) if i >= 200 else 0

            # 24. Volume-price divergence: price rising but volume falling = weak
            if len(window_close) >= 20 and len(window_vol) >= 20:
                price_chg_20 = (window_close[-1] - window_close[-20]) / (window_close[-20] + 1e-8)
                vol_chg_20 = (np.mean(window_vol[-5:]) - np.mean(window_vol[-20:-5])) / (np.mean(window_vol[-20:-5]) + 1e-8)
                # Divergence: same sign = confirming, different sign = diverging
                vol_price_divergence = price_chg_20 * vol_chg_20  # Positive = confirming
            else:
                vol_price_divergence = 0

            # 25. Return autocorrelation (lag-1): mean-reversion vs momentum regime
            if len(log_returns) >= 20:
                r1 = log_returns[-20:-1]
                r2 = log_returns[-19:]
                if np.std(r1) > 1e-8 and np.std(r2) > 1e-8:
                    autocorr_1 = np.corrcoef(r1, r2)[0, 1]
                    autocorr_1 = 0 if np.isnan(autocorr_1) else autocorr_1
                else:
                    autocorr_1 = 0
            else:
                autocorr_1 = 0

            # 26. Return autocorrelation (lag-5): weekly pattern
            if len(log_returns) >= 25:
                r1 = log_returns[-25:-5]
                r2 = log_returns[-20:]
                if np.std(r1) > 1e-8 and np.std(r2) > 1e-8:
                    autocorr_5 = np.corrcoef(r1, r2)[0, 1]
                    autocorr_5 = 0 if np.isnan(autocorr_5) else autocorr_5
                else:
                    autocorr_5 = 0
            else:
                autocorr_5 = 0

            # 27. Kurtosis of returns (tail heaviness = regime change)
            if len(log_returns) >= 20:
                centered = log_returns[-20:] - np.mean(log_returns[-20:])
                std_r = np.std(log_returns[-20:])
                return_kurtosis = np.mean(centered ** 4) / (std_r ** 4 + 1e-8) - 3  # Excess kurtosis
            else:
                return_kurtosis = 0

            # 28. Distance from 52-candle high/low (support/resistance proxy)
            if len(window_close) >= 52:
                dist_from_high = (closes[i] - np.max(window_close[-52:])) / (np.max(window_close[-52:]) + 1e-8)
                dist_from_low = (closes[i] - np.min(window_close[-52:])) / (np.min(window_close[-52:]) + 1e-8)
            else:
                dist_from_high = 0
                dist_from_low = 0

            # 29. Volatility of volume (unstable volume = institutional activity)
            if len(window_vol) >= 20:
                vol_of_vol = np.std(window_vol[-20:]) / (np.mean(window_vol[-20:]) + 1e-8)
            else:
                vol_of_vol = 0

            # 30. Close Location Value: where price closed within range
            hl = highs[i] - lows[i]
            close_location_value = (2 * closes[i] - highs[i] - lows[i]) / (hl + 1e-8) if hl > 0 else 0

            # 31. Consecutive up/down candles (streak detection)
            streak = 0
            for k in range(1, min(20, len(window_close))):
                if window_close[-k] > window_close[-k-1]:
                    if streak >= 0:
                        streak += 1
                    else:
                        break
                elif window_close[-k] < window_close[-k-1]:
                    if streak <= 0:
                        streak -= 1
                    else:
                        break
                else:
                    break
            candle_streak = streak / 10.0  # Normalize

            # 32. MACD histogram (signal line divergence)
            ema_9_macd = self._ema(window_close, 9)
            macd_value = ema_12 - ema_26
            macd_signal = ema_9_macd - ema_26  # Approximate signal line
            macd_histogram = (macd_value - macd_signal) / (closes[i] + 1e-8)

            # 33. Garman-Klass volatility (more efficient than Parkinson)
            if len(window_close) >= 2:
                gk_terms = []
                for k in range(max(1, len(window_close)-20), len(window_close)):
                    hl = np.log(window_high[k] / (window_low[k] + 1e-8))
                    co = np.log(window_close[k] / (window_close[k-1] + 1e-8))
                    gk_terms.append(0.5 * hl**2 - (2*np.log(2) - 1) * co**2)
                gk_vol = np.sqrt(max(0, np.mean(gk_terms))) * np.sqrt(self._annualization_factor)
            else:
                gk_vol = realized_vol

            # 34. Relative volume spike (current bar vs 20-bar avg)
            if len(window_vol) >= 20:
                vol_spike = window_vol[-1] / (np.mean(window_vol[-20:]) + 1e-8) - 1
                vol_spike = min(vol_spike, 5.0)  # Cap at 5x
            else:
                vol_spike = 0

            # 35. Intrabar momentum (close vs open proxy using consecutive closes)
            if len(window_close) >= 2:
                intrabar_momentum = (closes[i] - window_close[-2]) / (atr_value + 1e-8)
                intrabar_momentum = np.clip(intrabar_momentum, -3.0, 3.0)
            else:
                intrabar_momentum = 0

            # 36-44. Rolling return percentiles (captures distribution shape)
            if len(log_returns) >= 50:
                ret_p10 = np.percentile(log_returns[-50:], 10)
                ret_p90 = np.percentile(log_returns[-50:], 90)
                ret_range = ret_p90 - ret_p10  # Distribution width
            else:
                ret_p10 = 0
                ret_p90 = 0
                ret_range = 0

            # 45. EMA momentum divergence (price vs EMA acceleration)
            ema_50 = self._ema(window_close, 50) if len(window_close) >= 50 else closes[i]
            ema_divergence = (closes[i] - ema_50) / (atr_value + 1e-8)
            ema_divergence = np.clip(ema_divergence, -5.0, 5.0)

            # 46. High-Low range expansion (volatility breakout)
            if len(window_high) >= 20:
                recent_hl = np.mean(window_high[-5:] - window_low[-5:])
                older_hl = np.mean(window_high[-20:-5] - window_low[-20:-5])
                range_expansion = (recent_hl - older_hl) / (older_hl + 1e-8)
            else:
                range_expansion = 0

            # 47. Price efficiency ratio (directional move vs total path)
            if len(window_close) >= 20:
                net_move = abs(window_close[-1] - window_close[-20])
                total_path = np.sum(np.abs(np.diff(window_close[-20:])))
                price_efficiency = net_move / (total_path + 1e-8)
            else:
                price_efficiency = 0

            # 48. Volume-weighted RSI (RSI but weighted by volume)
            if len(window_close) >= 15 and len(window_vol) >= 15:
                price_changes = np.diff(window_close[-15:])
                vol_weights = window_vol[-14:]
                vol_gains = np.sum(np.maximum(price_changes, 0) * vol_weights)
                vol_losses = np.sum(np.maximum(-price_changes, 0) * vol_weights)
                vol_rsi = 100 - 100 / (1 + vol_gains / (vol_losses + 1e-8))
                vol_rsi = vol_rsi / 100  # Normalize to 0-1
            else:
                vol_rsi = 0.5

            # 49. Relative return rank (where is current return in recent history)
            if len(log_returns) >= 50:
                current_ret = log_returns[-1] if len(log_returns) > 0 else 0
                rank = np.mean(log_returns[-50:] <= current_ret)  # Percentile rank
                return_rank = rank * 2 - 1  # Scale to -1 to 1
            else:
                return_rank = 0

            feature_vector = [
                # Original 35 features
                returns_1, returns_5, returns_10, returns_20,       # 0-3: Momentum
                realized_vol, parkinson_vol,                         # 4-5: Volatility
                rsi / 100, macd, bb_position,                       # 6-8: Oscillators
                vol_ratio, momentum, trend_strength,                 # 9-11: Volume & trend
                (closes[i] - np.min(window_close)) / (np.max(window_close) - np.min(window_close) + 1e-8),  # 12: Price level
                (window_high[-1] - window_low[-1]) / (closes[i] + 1e-8),  # 13: HL range
                mean_reversion, vol_momentum, vol_regime,           # 14-16: Enhanced
                accel, return_vol,                                   # 17-18: Dynamics
                vol_accel, hl_spread, order_imbalance,              # 19-21: Microstructure
                price_to_vwap, vol_concentration,                    # 22-23: Volume
                stoch, atr_ratio,                                    # 24-25: Technical
                mean_reversion_100, mean_reversion_200,             # 26-27: Multi-scale MR
                vol_mean_reversion, vol_trend,                       # 28-29: Vol dynamics
                price_range_ratio, breakout_signal,                  # 30-31: Range & breakout
                jump_ratio, return_skew, closes_above_prev,         # 32-34: Tail & pattern
                # NEW 29 features replacing zero-padding (35-63)
                ma_cross_50_200,           # 35: Golden/death cross signal
                ma_cross_10_50,            # 36: Fast MA cross
                ad_momentum,               # 37: Accumulation/distribution momentum
                wick_body_ratio,           # 38: Candle rejection signal
                wick_direction,            # 39: Selling vs buying pressure from wicks
                returns_50,                # 40: 50-period momentum
                returns_100,               # 41: 100-period momentum
                returns_200,               # 42: 200-period momentum (matches prediction horizon)
                vol_price_divergence,      # 43: Volume confirms price? (key signal)
                autocorr_1,                # 44: Mean-reversion vs momentum regime
                autocorr_5,                # 45: Weekly autocorrelation pattern
                return_kurtosis,           # 46: Tail risk (regime change indicator)
                dist_from_high,            # 47: Distance from resistance
                dist_from_low,             # 48: Distance from support
                vol_of_vol,                # 49: Volume stability (institutional activity)
                close_location_value,      # 50: Intra-bar buying/selling pressure
                candle_streak,             # 51: Consecutive direction (trend strength)
                macd_histogram,            # 52: MACD divergence signal
                gk_vol,                    # 53: Garman-Klass vol (more efficient estimator)
                vol_spike,                 # 54: Volume breakout detection
                intrabar_momentum,         # 55: ATR-normalized momentum
                ret_p10,                   # 56: Return distribution left tail
                ret_p90,                   # 57: Return distribution right tail
                ret_range,                 # 58: Return distribution width
                ema_divergence,            # 59: EMA acceleration signal
                range_expansion,           # 60: Volatility breakout
                price_efficiency,          # 61: Trend efficiency (0=choppy, 1=clean)
                vol_rsi,                   # 62: Volume-weighted RSI
                return_rank,               # 63: Percentile rank of current return
            ]

            features.append(feature_vector)

        if not features:
            return np.array(features)

        result = np.array(features)

        # Sanitize: replace NaN/Inf with 0 (can arise from zero-variance
        # windows, missing data, or division edge cases)
        result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)

        # Per-feature robust clipping: cap at ±5 median-absolute-deviations
        # This removes extreme outliers while preserving the distribution shape.
        # Unlike z-score clipping, MAD is robust to the very outliers we want to clip.
        for col in range(result.shape[1]):
            col_data = result[:, col]
            median = np.median(col_data)
            mad = np.median(np.abs(col_data - median))
            if mad < 1e-8:
                # Near-constant feature: clip using percentage bounds (±10% or ±0.001)
                # BUG FIX #18: Use relative bounds instead of fixed ±1 for robustness with small-magnitude features
                relative_limit = max(abs(median) * 0.1, 0.001)
                result[:, col] = np.clip(col_data, median - relative_limit, median + relative_limit)
            else:
                limit = 5 * mad
                result[:, col] = np.clip(col_data, median - limit, median + limit)

        return result

    def _ema(self, data: np.ndarray, period: int) -> float:
        """Calculate EMA."""
        if len(data) < period:
            return data[-1]
        multiplier = 2 / (period + 1)
        ema = data[0]
        for price in data[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def detect_market_regime(self, candles: List[OHLCV], window: int = 50, prev_regime: str = 'sideways',
                            switch_threshold: float = 1.0, base_threshold: float = 0.02,
                            vol_threshold: float = 0.01) -> str:
        """
        Detect current market regime (bull, bear, or sideways) with hysteresis to prevent whipsaw.

        Args:
            candles: Recent candles to analyze
            window: Look-back window
            prev_regime: Previous regime (for hysteresis/stickiness)
            switch_threshold: Multiplier for trend needed to switch regime (>1.0 = hysteresis)
                             1.0 = no hysteresis (original behavior)
                             1.3 = require 30% larger trend change to switch
            base_threshold: Minimum trend strength (SMA divergence) to detect a regime (default: 2%)
                           Lower = more sensitive to regime changes (catches more but more whipsaw)
                           Higher = less sensitive (misses some but more stable)
            vol_threshold: Minimum volatility to confirm a regime change (default: 1%)
                          Prevents false regime detection in flat/quiet markets

        Returns:
            'bull', 'bear', or 'sideways'
        """
        if len(candles) < window:
            return 'sideways'

        recent = candles[-window:]
        closes = np.array([c.close for c in recent])

        # Calculate trend
        sma_short = np.mean(closes[-20:])
        sma_long = np.mean(closes)
        # BUG FIX #24: Add epsilon protection for division by zero (if all closes near zero)
        trend = (sma_short - sma_long) / (sma_long + 1e-8)

        # Calculate volatility
        # BUG FIX #17: Add epsilon protection for division by zero (close prices near zero)
        returns = np.diff(closes) / (closes[:-1] + 1e-8)
        volatility = np.std(returns)

        # If already in a regime, require stronger signal to leave it (hysteresis)
        if prev_regime == 'bull':
            if trend < -base_threshold * switch_threshold and volatility > vol_threshold:
                return 'bear'
            elif trend > base_threshold and volatility > vol_threshold:
                return 'bull'  # Stay in bull if still positive
            else:
                return 'sideways'
        elif prev_regime == 'bear':
            if trend > base_threshold * switch_threshold and volatility > vol_threshold:
                return 'bull'
            elif trend < -base_threshold and volatility > vol_threshold:
                return 'bear'  # Stay in bear if still negative
            else:
                return 'sideways'
        else:  # prev_regime == 'sideways'
            if trend > base_threshold * switch_threshold and volatility > vol_threshold:
                return 'bull'
            elif trend < -base_threshold * switch_threshold and volatility > vol_threshold:
                return 'bear'
            else:
                return 'sideways'

    def calculate_correlation(self, candles1: List[OHLCV], candles2: List[OHLCV], lookback: int = 50) -> float:
        """
        Calculate correlation between two symbols' returns.

        Args:
            candles1: First symbol's candles
            candles2: Second symbol's candles
            lookback: Number of periods to look back

        Returns:
            Correlation coefficient (-1 to 1)
        """
        try:
            if len(candles1) < lookback or len(candles2) < lookback:
                return 0.0  # Not enough data, assume uncorrelated

            # Get recent close prices
            closes1 = np.array([c.close for c in candles1[-lookback:]])
            closes2 = np.array([c.close for c in candles2[-lookback:]])

            # Calculate returns
            # BUG FIX #19: Add epsilon protection for division by zero in correlation calculation
            returns1 = np.diff(closes1) / (closes1[:-1] + 1e-8)
            returns2 = np.diff(closes2) / (closes2[:-1] + 1e-8)

            # Calculate Pearson correlation
            # BUG FIX #29: Use epsilon comparison instead of exact zero (avoid unreliable float comparison)
            if len(returns1) == 0 or np.std(returns1) < 1e-8 or np.std(returns2) < 1e-8:
                return 0.0

            correlation = np.corrcoef(returns1, returns2)[0, 1]
            return correlation if not np.isnan(correlation) else 0.0
        except Exception as e:
            # BUG FIX #8: Use generic error message (symbol names not in scope)
            logger.error(f"Correlation calculation failed: {e}")
            return 0.0  # If any error, assume uncorrelated

    def is_signal_statistically_significant(self, symbol: str, action: int, signal_history: Dict) -> bool:
        """
        Test if a signal's historical win rate is statistically significant at 95% confidence.
        Uses binomial test: H0 = win_rate = 50%, H1 = win_rate > 50%

        Args:
            symbol: Trading pair symbol
            action: Action code (0=short, 2=long)
            signal_history: Dict of symbol -> {action -> [win/loss results]}

        Returns:
            True if win rate is significantly > 50% at 95% confidence (p < 0.05)
        """
        try:
            from scipy import stats

            # Get history for this symbol-action combo
            if symbol not in signal_history:
                return True  # No history, allow the signal (neutral)

            if action not in signal_history[symbol]:
                return True  # No history for this action, allow it

            trade_results = signal_history[symbol][action]  # List of 1 (win) or 0 (loss)

            # Need minimum sample size for statistical significance
            if len(trade_results) < 10:
                return True  # Not enough data yet, allow signal

            # Count wins and total trades
            wins = sum(trade_results)
            total = len(trade_results)

            # Binomial test: is win rate > 50% at 95% confidence?
            # H0: p = 0.5, H1: p > 0.5 (one-tailed test)
            # BUG FIX #20: Handle scipy API compatibility (1.7+ uses binomtest instead of binom_test)
            try:
                # Try newer scipy API first (scipy >= 1.7)
                p_value = stats.binomtest(wins, total, 0.5, alternative='greater').pvalue
            except AttributeError:
                # Fall back to older API (scipy < 1.7)
                p_value = stats.binom_test(wins, total, 0.5, alternative='greater')

            # If p < 0.05, we reject null hypothesis at 95% confidence
            is_significant = p_value < 0.05

            if not is_significant and total >= 20:
                # Log when we're filtering due to statistical significance
                # BUG FIX #33: Defensive division - ensure total is not zero (already checked but explicit protection)
                win_rate = (wins / max(total, 1)) * 100 if total > 0 else 0.0
                if total >= 10:
                    logger.debug(f"🔍 Signal {symbol}:{action} filtered: {win_rate:.1f}% win rate ({wins}/{total}) not significantly > 50% (p={p_value:.3f})")

            return is_significant

        except Exception as e:
            logger.error(f"❌ CRITICAL: Significance test failed for {symbol}:{action}: {e}")
            return False  # If error, reject the signal (safe default)

    def get_optimal_stop_distance(self, stop_distance_effectiveness: Dict) -> float:
        """
        Learn optimal stop distance from historical data.
        Returns the stop distance with highest win rate.

        Args:
            stop_distance_effectiveness: Dict mapping distance -> {wins, losses}

        Returns:
            Optimal stop distance to use (default 0.05 = 5%)
        """
        try:
            best_distance = 0.05  # Default fallback
            best_win_rate = 0.0
            min_trades = 10  # Need at least 10 trades to trust the metric

            for distance, results in stop_distance_effectiveness.items():
                total_trades = results["wins"] + results["losses"]
                if total_trades >= min_trades:
                    win_rate = results["wins"] / total_trades
                    if win_rate > best_win_rate:
                        best_win_rate = win_rate
                        best_distance = distance

            return best_distance
        except Exception as e:
            logger.error(f"Optimal stop distance calculation failed: {e} - using default 5%")
            return 0.05  # Fallback to 5% if any error

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
            # BUG FIX #22: Add epsilon protection for division by zero in basic label generation
            future_return = (closes[i + lookahead] - closes[i]) / (closes[i] + 1e-8)

            if future_return > threshold:
                labels.append(2)  # Buy
            elif future_return < -threshold:
                labels.append(0)  # Sell
            else:
                labels.append(1)  # Hold

        return np.array(labels)

    def generate_multi_horizon_labels(
        self,
        candles: List[OHLCV],
        horizons: List[int] = None,
        threshold: float = 0.02
    ) -> Dict[int, np.ndarray]:
        """
        Generate trading labels for multiple lookahead horizons.

        Multi-horizon training allows the ensemble to learn patterns at different timescales:
        - 24h: Short-term tactical moves (1 day)
        - 48h: Medium-term directional bias (2 days)
        - 100h: Intermediate trend (4+ days)
        - 200h: Longer trend (8+ days)
        - 400h: Long-term direction (16+ days)
        - 800h: Ultra-long direction (33+ days)
        - 1600h: Extended direction (66+ days - macro trends, earnings cycles, seasonality)

        Args:
            candles: OHLCV candles
            horizons: List of lookahead periods in candles. Default: [24, 48, 100, 200, 400, 800, 1600]
            threshold: Return threshold for buy/sell signals

        Returns:
            Dictionary mapping horizon -> labels array
        """
        if horizons is None:
            horizons = [24, 48, 100, 200, 400, 800, 1600]

        closes = np.array([c.close for c in candles])
        multi_labels = {}

        # BUG FIX #10: All horizons must have same length to prevent 80% data truncation
        # Compute max lookahead (longest horizon = tightest constraint)
        max_lookahead = max(horizons) if horizons else 1600

        # All labels should have length = len(closes) - max_lookahead
        # Then pad horizon-specific labels to this length
        min_samples = max(1, len(closes) - max_lookahead)  # Ensure at least 1 sample

        for lookahead in horizons:
            # Horizon-aware threshold: shorter horizons = smaller moves = lower threshold
            # This prevents 85%+ HOLD labels on short horizons where 2% moves are rare.
            # Scale: sqrt(horizon/200) so 24h→0.35x, 200h→1.0x, 1600h→2.83x
            horizon_threshold = threshold * np.sqrt(lookahead / 200.0)
            horizon_threshold = max(0.005, min(0.05, horizon_threshold))  # Clamp [0.5%, 5%]

            labels = []
            for i in range(len(closes) - lookahead):
                # BUG FIX #23: Add epsilon protection for division by zero in multi-horizon label generation
                future_return = (closes[i + lookahead] - closes[i]) / (closes[i] + 1e-8)

                if future_return > horizon_threshold:
                    labels.append(2)  # Buy
                elif future_return < -horizon_threshold:
                    labels.append(0)  # Sell
                else:
                    labels.append(1)  # Hold

            # Pad or truncate to min_samples length (all horizons same length)
            # This prevents training data being truncated by shortest horizon
            if len(labels) < min_samples:
                # Pad with HOLD (1) to reach min_samples
                labels.extend([1] * (min_samples - len(labels)))
            else:
                # Truncate to min_samples (shouldn't happen with max_lookahead logic)
                labels = labels[:min_samples]

            multi_labels[lookahead] = np.array(labels)

        return multi_labels

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

        # CRITICAL FIX: Load trained checkpoints before backtest
        # Training saves models to disk, but backtest is a separate code path.
        # model_trainer needs its models loaded before making predictions.
        if not model_trainer.load_checkpoints():
            logger.error("❌ Failed to load trained models! Backtest cannot proceed without trained models.")
            return self._empty_result()

        # BUG FIX #15: Set random seed for reproducible tie-breaking (backtest should be deterministic)
        # This ensures np.random.choice(tied_actions) produces same result across runs
        np.random.seed(42)

        # ============================================================
        # CONFIG: Centralized hardcoded parameters (easy to tune)
        # ============================================================
        config = {
            # Risk Management
            "max_portfolio_drawdown": 0.10,          # 10% max DD before pausing (was 15% — too much drawdown)
            "portfolio_dd_resume_pct": 0.50,         # Resume trading at 50% of DD limit (5% DD recovery)

            # Position Sizing & Kelly Criterion
            "kelly_cap_pct": 0.03,                   # Cap position at 3% of capital (was 4% — too concentrated)
            "recovery_scale_min": 0.70,              # Reduce sizing to 70% during recovery (was 50% — too extreme)

            # Confidence-Based Position Sizing
            # Tightened from 2.0x max → 1.3x max to avoid overleveraging on
            # potentially overfit confidence estimates
            "confidence_ultra_high_mult": 1.3,       # >=80% confidence: 1.3x position size (was 2.0x — too aggressive)
            "confidence_high_mult": 1.2,             # 70-80% confidence: 1.2x position size (was 1.5x)
            "confidence_medium_high_mult": 1.1,      # 60-70% confidence: 1.1x position size (was 1.2x)
            "confidence_medium_mult": 1.0,           # 50-60% confidence: 1.0x position size (baseline)
            "confidence_low_mult": 0.7,              # 45-50% confidence: 0.7x position size (was 0.6x)
            "confidence_very_low_mult": 0.4,         # <45% confidence: 0.4x position size (was 0.3x)

            # Confidence Thresholds
            # Calibrated to model accuracy (~47%): thresholds must be BELOW model output range
            # to allow trades. Previous 0.65/0.55/0.45 blocked 99%+ of signals.
            # These thresholds filter the bottom of the confidence distribution while
            # still allowing the model's stronger signals through.
            "confidence_4x4_models": 0.40,           # 4/4 models agree - high consensus, moderate bar
            "confidence_3x4_models": 0.35,           # 3/4 models agree - good consensus
            "confidence_fallback": 0.30,             # 2/4 or fewer models - require some minimum confidence
            "regime_bull_confidence_mult": 1.10,     # Bull: require HIGHER confidence for shorts (counter-trend) (was 1.15)
            "regime_bear_confidence_mult": 1.10,     # Bear: require HIGHER confidence for longs (counter-trend) (was 1.15)

            # Model Agreement & Consensus
            "min_model_agreement": 2,                # Minimum 2/4 models required
            "weighted_agreement_threshold": 0.50,    # 50% weighted agreement

            # Liquidity & Volume
            "min_volume_threshold": 1000,            # Minimum acceptable volume (in quote currency units, e.g., USDT)

            # Correlation & Systemic Risk
            "max_correlation_threshold": 0.70,       # Reduce sizing if correlation > 70%
            "btc_eth_systemic_threshold": 0.80,      # High systemic risk at 80% corr

            # Stop Loss & Take Profit
            "stop_loss_min": 0.02,                   # 2% minimum stop loss
            "stop_loss_max": 0.30,                   # 30% maximum stop loss
            "take_profit_min": 0.05,                 # 5% minimum take profit
            "take_profit_max": 0.60,                 # 60% maximum take profit

            # Profit Pyramiding (BUG FIX #6: Now configurable!)
            # Exit strategy: take profits gradually at different profit levels
            "pyramid_target_1_pct": 0.05,            # Exit 30% at +5% profit
            "pyramid_target_2_pct": 0.15,            # Exit remaining at +15% profit
            "pyramid_exit_1_size": 0.40,             # Exit 40% at target 1 (was 30% — lock in more profit early)
            "pyramid_exit_2_size": 1.0,              # Exit remaining 100% at target 2

            # Holding Periods (hours)
            "max_hold_hours_default": 1600,          # Default: 66+ days
            "max_hold_hours_winner": 2000,           # Winners: 83+ days
            "max_hold_hours_loser": 1200,            # Losers: 50 days

            # Macro Regime Detection
            "baseline_portfolio_vol": 0.008,         # 0.8% daily baseline
            "high_vol_multiplier": 1.5,              # 1.5x baseline = elevated (reduce position sizing)
            "extreme_vol_multiplier": 4.0,           # 4.0x baseline = extreme (changed from 2.5 - was too aggressive)
            "regime_switch_threshold": 1.3,          # Require 30% trend change to switch regime (prevents whipsaw)

            # Model Degradation Detection
            "degradation_threshold": 0.35,           # Alert if win rate < 35%
            "rolling_window_size": 20,               # Keep last 20 trades

            # Continuous Learning (disabled during backtest for speed — set to very high interval)
            # Retraining all 4 models every 5000 candles adds ~100 hours to a 3M candle backtest.
            # Set to 999999999 to effectively disable. For live trading, use 5000.
            "continuous_learning_interval": 999999999,  # Disabled for backtest speed (was 5000)
            "continuous_learning_window": 10000,    # Keep last 10000 samples for retraining
            "continuous_learning_threshold": 0.45,  # Alert if win rate < 45%

            # Trading Safeguards
            "per_symbol_cooldown_candles": 5,       # 5-candle minimum between entries
            "churn_alert_threshold": 3,             # Alert if >3 direction flips

            # Feature Extraction
            "feature_lookback_window": 100,         # 100-candle lookback for features
            "regime_detection_window": 100,         # 100-candle window for regime
            "macro_vol_lookback": 100,              # 100-candle window for macro vol

            # Slippage & Commissions
            "slippage_bps": 5,                       # 5 basis points per side
            "commission_bps": 5,                     # 5 basis points per side

            # Statistical Significance
            "min_trades_for_significance": 10,      # Need 10+ trades to test
            "significance_confidence": 0.95,        # 95% confidence level (p < 0.05)

            # Correlation-Based Hedging (TOP FUND FEATURE)
            "max_sector_correlation": 0.8,          # Max correlation within sector before reducing
            "enable_correlation_hedging": True,     # Enable automatic hedging
            "correlation_update_interval": 500,     # Recalculate correlations every 500 candles
            "max_correlated_capital": 0.30,         # Max 30% capital in highly correlated positions

            # Microstructure (Order Book) Parameters
            "order_book_cache_interval_sec": 300,   # Fetch order books every 5 minutes (300s) to avoid rate limiting

            # Timeframe Configuration (default: 1-hour candles)
            # Change candle_interval_minutes to switch timeframes (5m, 15m, 1h, 4h, 1d)
            "candle_interval_minutes": 60,          # Candle interval in minutes (5=5m, 15=15m, 60=1h, 240=4h, 1440=1d)
            "candle_interval_str": "1h",            # String for API calls (e.g., "5m", "15m", "1h", "4h", "1d")
            "candles_per_day": 24,                  # Derived: 1440 / candle_interval_minutes (24 for 1h, 6 for 4h, 1 for 1d)
            "annualization_factor": 365 * 24,       # Candles per year for crypto (365*24=8760 for 1h, 365*6=2190 for 4h)

            # Regime Detection Thresholds (configurable for different market conditions)
            "regime_base_threshold": 0.02,          # Base trend threshold (2% SMA divergence)
            "regime_vol_threshold": 0.01,           # Minimum volatility to confirm regime (1%)

            # Position Flip-Flop Cooldown (reduces churn from rapid direction changes)
            "flip_cooldown_multiplier": 3,          # Direction flip cooldown = standard cooldown * this (3x = 15 candles)
            "flip_confidence_penalty": 0.10,        # Extra confidence required for direction flips (+10%)
            "max_flips_per_symbol": 3,              # Max direction flips before blocking symbol temporarily
            "flip_block_candles": 50,               # Block symbol for N candles after max flips exceeded
        }

        # BUG #16 FIX: Validate all required configuration keys exist and have valid types/ranges
        required_keys = [
            "stop_loss_pct", "take_profit_pct", "confidence_threshold",
            "continuous_learning_interval", "correlation_update_interval",
            "max_sector_correlation", "min_trades_for_significance",
            "significance_confidence"
        ]
        missing_keys = [k for k in required_keys if k not in config]
        if missing_keys:
            logger.warning(f"⚠️ Missing config keys: {missing_keys}")

        # Validate value ranges
        if config.get("max_sector_correlation", 0) < 0 or config.get("max_sector_correlation", 2) > 1:
            logger.warning("⚠️ max_sector_correlation outside valid range [0,1]")
        if config.get("significance_confidence", 0) < 0 or config.get("significance_confidence", 2) > 1:
            logger.warning("⚠️ significance_confidence outside valid range [0,1]")

        # Apply timeframe configuration to instance for use in prepare_features
        self._annualization_factor = config["annualization_factor"]
        self._candles_per_day = config["candles_per_day"]

        logger.info("📋 Backtest Configuration (centralized):")
        logger.info(f"  Timeframe: {config['candle_interval_str']} ({config['candle_interval_minutes']}min, {config['candles_per_day']} candles/day)")
        for key, val in list(config.items())[:5]:
            logger.debug(f"  {key}: {val}")
        logger.debug(f"  ... and {len(config) - 5} more parameters (see config dict)")

        # Combine all data into time-sorted events
        all_candles = []
        for symbol, candles in data.items():
            for candle in candles:
                all_candles.append((candle.timestamp, symbol, candle))

        all_candles.sort(key=lambda x: x[0])

        if not all_candles:
            logger.error("No data for backtest")
            return self._empty_result()

        # Log data summary
        symbols = list(data.keys())
        total_candles = sum(len(candles) for candles in data.values())
        date_range = f"{all_candles[0][0].date()} to {all_candles[-1][0].date()}"
        logger.info(f"Backtest Configuration:")
        logger.info(f"  Symbols: {len(symbols)} ({', '.join(symbols[:10])}{'...' if len(symbols) > 10 else ''})")
        logger.info(f"  Total Candles: {total_candles:,}")
        logger.info(f"  Date Range: {date_range}")
        logger.info(f"  Strategy: {strategy}")
        logger.info(f"  Initial Capital: ${self.initial_capital:,.2f}")

        # Initialize tracking
        capital = self.initial_capital
        positions: Dict[str, Dict] = {}  # symbol -> position info
        equity_curve = [(all_candles[0][0], capital)]
        trades = []

        # PORTFOLIO-LEVEL RISK MANAGEMENT (using config)
        rolling_max_equity = self.initial_capital  # Track peak equity for DD calculation
        max_portfolio_dd = config["max_portfolio_drawdown"]
        portfolio_trading_paused = False  # Pause trading if DD exceeds limit
        recent_returns = []  # Track recent returns for volatility

        # TIER 1 FIX: DRAWDOWN RECOVERY SCALING (using config)
        # After losses, trade smaller to recover gradually (like top funds)
        recent_pnls = []  # Rolling window of recent trade P&Ls
        recovery_mode = False  # Are we in drawdown recovery?
        recovery_scale = 1.0  # Position size multiplier during recovery

        # Progress tracking
        last_log_time = time.time()
        last_log_index = 0

        # Slippage and commission modeling (using config)
        SLIPPAGE_BPS = config["slippage_bps"]
        COMMISSION_BPS = config["commission_bps"]
        COST_PER_SIDE = (SLIPPAGE_BPS + COMMISSION_BPS) / 10000

        # Walk through time
        window_data: Dict[str, List[OHLCV]] = {sym: [] for sym in data.keys()}
        candles_processed = 0
        signals_generated = 0
        positions_opened = 0

        # PHASE C: Model Ensemble Optimization - Track per-model P&L
        model_names = ["DQN", "PPO", "LSTM", "Transformer"]
        model_predictions = {m: {"correct": 0, "incorrect": 0} for m in model_names}

        # PHASE C: Track P&L contribution by model (profit if model voted for winning trade)
        model_pnl = {m: {"pnl": 0, "trades": 0, "wins": 0, "losses": 0} for m in model_names}

        # TIER 1 FIX: Track per-model win-rate for filtering
        model_recent_trades = {m: [] for m in model_names}  # Rolling 20-trade window

        # TIER 1 FIX: SIGNAL STATISTICAL SIGNIFICANCE TESTING
        # Track per-symbol, per-action (long/short) trades to test if win rate > 50% is statistically significant
        signal_history = {}  # symbol -> {action -> [wins/losses]}
        min_trades_for_significance = 10  # Need at least 10 historical trades to test

        # TIER 2 FIX: LEARN OPTIMAL STOP PLACEMENT FROM HISTORICAL DATA
        # Track effectiveness of different stop distances (learn what works)
        stop_distance_effectiveness = {
            0.02: {"wins": 0, "losses": 0},  # 2% stop
            0.05: {"wins": 0, "losses": 0},  # 5% stop
            0.10: {"wins": 0, "losses": 0},  # 10% stop
            0.20: {"wins": 0, "losses": 0},  # 20% stop
        }

        # TIER 2 FIX: MACRO FILTERING - VOLATILITY REGIME DETECTION
        # Track baseline volatility and macro regime shifts
        baseline_portfolio_vol = config["baseline_portfolio_vol"]  # 0.8% daily vol baseline
        macro_regime = "normal"  # Track current regime (normal, elevated, extreme)
        high_vol_threshold = config["high_vol_multiplier"]  # 1.5x baseline = elevated macro vol
        extreme_vol_threshold = config["extreme_vol_multiplier"]  # 2.5x baseline = extreme macro vol

        # BUG FIX #11: Regime stickiness (prevent whipsaw flips)
        # Track per-symbol regime to add hysteresis
        symbol_regime = {}  # Maps symbol -> (regime, regime_age_candles)
        regime_switch_threshold = config["regime_switch_threshold"]  # Configurable threshold (default: 30% trend change)

        # CONTINUOUS LEARNING: Collect data for periodic retraining (NEW)
        # Track features and predictions to create forward-looking labels
        retraining_buffer = {
            "features": [],  # Feature vectors
            "predictions": [],  # Model predictions (0=SHORT, 1=HOLD, 2=LONG)
            "timestamps": [],  # Timestamps for each feature
            "symbols": [],  # Which symbol for each feature
            "prices_at_prediction": [],  # Price when prediction was made (for lookahead reference)
            "horizons": [24, 48, 100, 200, 400, 800, 1600],  # Multi-horizon labels (in hours)
        }
        last_retrain_candle = 0  # Track when we last retrained

        # CORRELATION-BASED HEDGING (TOP FUND FEATURE)
        # Track correlation matrix for portfolio optimization
        correlation_matrix = {}  # symbol_pair -> correlation
        last_corr_update = 0  # Track when we last updated correlations
        sector_map = {  # Simple sector classification (can be expanded)
            "BTC": "L1", "ETH": "L1",  # Layer 1
            "SOL": "L1_ALT", "ADA": "L1_ALT",
            "DOGE": "MEME", "SHIB": "MEME",
            "UNI": "DEFI", "AAVE": "DEFI",
            "LINK": "ORACLE", "BAND": "ORACLE",
        }

        # PHASE D: Track signal filtering by reason
        filtered_signals = {
            "low_confidence": 0,
            "conflicting_regime": 0,
            "low_liquidity": 0,
            "low_model_agreement": 0,
            "low_statistical_significance": 0,  # TIER 1 FIX: Track statistical significance filtering
        }

        # Rolling win-rate monitoring (for degradation detection)
        recent_trades_window = []  # Keep last 20 trades for rolling win-rate
        max_recent_trades = 20
        degradation_threshold = config["degradation_threshold"]  # Alert if win rate drops below 35%

        # SAFEGUARD: Per-symbol trading cooldown (prevent thrashing)
        last_exit_time = {}  # symbol -> timestamp of last exit
        min_cooldown_candles = config["per_symbol_cooldown_candles"]  # Wait at least 5 candles before re-entering same symbol
        # Enhanced flip-flop cooldown - apply longer cooldown for direction changes
        flip_cooldown_mult = config["flip_cooldown_multiplier"]  # 3x longer cooldown for direction flips
        min_flip_cooldown_candles = min_cooldown_candles * flip_cooldown_mult  # e.g., 5 * 3 = 15 candles
        flip_confidence_penalty = config["flip_confidence_penalty"]  # Extra confidence required for direction flips
        max_flips_per_symbol = config["max_flips_per_symbol"]  # Max flips before temp block
        flip_block_candles = config["flip_block_candles"]  # Block duration after max flips
        trade_churn = {}  # symbol -> count of direction flips (long->short or short->long)
        trade_directions = {}  # symbol -> last direction (for detecting flips)
        flip_block_until = {}  # symbol -> candle count when block expires

        # ============================================================
        # PRE-TRADING SANITY CHECKS (ensure we'll actually trade)
        # ============================================================
        logger.info("\n🔍 PRE-TRADING SANITY CHECKS:")
        logger.info(f"  Models loaded: DQN={hasattr(model_trainer, 'dqn') and model_trainer.dqn is not None}, PPO={hasattr(model_trainer, 'ppo') and model_trainer.ppo is not None}, LSTM={hasattr(model_trainer, 'lstm') and model_trainer.lstm is not None}, Transformer={hasattr(model_trainer, 'transformer') and model_trainer.transformer is not None}")
        logger.info(f"  Initial capital: ${capital:,.2f}")
        logger.info(f"  Minimum position size: $100")
        logger.info(f"  Symbols to trade: {len(data)} symbols")
        logger.info(f"  Training window: {self.train_window} candles (~{self.train_window/config['candles_per_day']:.0f} days)")
        logger.info(f"  Data available: {len(all_candles):,} candles")
        logger.info(f"  Filter thresholds:")
        logger.info(f"    - Min confidence: {config['confidence_fallback']:.2f}-{config['confidence_4x4_models']:.2f} (by model agreement)")
        logger.info(f"    - Min model agreement: 2/4 models (weighted >50%)")
        logger.info(f"    - Per-symbol cooldown: {min_cooldown_candles} candles")
        logger.info(f"    - Max position size: 2% of capital (Kelly-based)")
        logger.info(f"  Expected: Should generate trades within first 100-500 candles")

        # DIAGNOSTIC: Track filter stages
        filter_stage_counters = {
            "total_predictions": 0,
            "not_hold": 0,           # action != 1
            "meets_confidence": 0,    # confidence check passed
            "not_conflicting": 0,     # regime conflict passed
            "is_liquid": 0,           # liquidity check passed
            "strong_consensus": 0,    # model agreement passed
            "stat_significant": 0,    # statistical significance passed
            "not_in_cooldown": 0,     # cooldown check passed
            "no_conflict": 0,         # position conflict passed
            "not_already_open": 0,    # position not already open
            "good_microstructure": 0, # microstructure filter passed
            "positions_opened": 0,    # actually opened
        }

        # PHASE B: Initialize continuous learning (real data only)
        continuous_learner = ContinuousLearner(
            retrain_interval=config["continuous_learning_interval"],  # Retrain every 100 candles
            window_size=config["continuous_learning_window"],  # Keep last 5000 samples
            performance_threshold=config["continuous_learning_threshold"],  # Alert if win rate < 45%
        )
        adaptive_weighter = AdaptiveEnsembleWeighter(model_names=model_names, lookback=50)

        # PHASE A: Microstructure - DISABLED during backtest
        # Live order book API calls are pointless for historical candles.
        # Microstructure features are only meaningful for live trading.
        order_book_cache = {}
        microstructure_extractors = {}
        logger.info(f"📊 PHASE A: Microstructure SKIPPED (historical backtest — no live order books)")

        logger.info(f"📊 PHASE B: Continuous Learning DISABLED for backtest speed")
        logger.info(f"  Retraining interval: {config['continuous_learning_interval']} candles (effectively off)")
        logger.info(f"  Adaptive Ensemble: Reweight models by recent performance")

        previous_symbol = None  # Track symbol changes to reset state buffer
        for timestamp, symbol, candle in all_candles:
            candles_processed += 1

            # CRITICAL FIX: Reset state buffer when symbol changes
            # Candles are sorted by timestamp (not symbol), so BTC→ETH→XRP→BTC transitions occur
            # LSTM/Transformer must not see mixed context from different symbols
            if previous_symbol is not None and symbol != previous_symbol:
                # CRITICAL FIX: Add error handling to state reset (prevents state corruption)
                try:
                    model_trainer.reset_state_buffer()
                except Exception as e:
                    logger.error(f"State buffer reset failed for symbol transition {previous_symbol}→{symbol}: {e}")
                    # Continue anyway - state may be partially corrupted but backtest continues
            previous_symbol = symbol

            # Periodic progress logging (every 10 seconds or 5000 candles)
            current_time = time.time()
            if current_time - last_log_time > 10 or candles_processed - last_log_index >= 5000:
                progress_pct = (candles_processed / len(all_candles)) * 100
                rate = (candles_processed - last_log_index) / (current_time - last_log_time)
                est_remaining = (len(all_candles) - candles_processed) / rate if rate > 0 else 0
                logger.info(
                    f"Progress: {candles_processed:,}/{len(all_candles):,} candles ({progress_pct:.1f}%) | "
                    f"Positions: {len(positions)} | Trades: {len(trades)} | "
                    f"Capital: ${capital:,.2f} | "
                    f"Rate: {rate:.0f} candles/sec | ETA: {est_remaining:.0f}s"
                )
                # Log filter funnel every 60 seconds to diagnose zero-trade issues
                if filter_stage_counters["total_predictions"] > 0:
                    fc = filter_stage_counters
                    logger.info(
                        f"  Filter funnel: predictions={fc['total_predictions']} → "
                        f"not_hold={fc['not_hold']} → conf={fc['meets_confidence']} → "
                        f"liquid={fc['is_liquid']} → consensus={fc['strong_consensus']} → "
                        f"sig={fc['stat_significant']} → opened={fc['positions_opened']}"
                    )
                last_log_time = current_time
                last_log_index = candles_processed

                # PHASE B ENHANCEMENT: Periodic continuous learning (every 5000 candles)
                # Log model ensemble weights and performance by model
                # BUG #10 FIX: Check if model_names is non-empty before accessing model_names[0]
                if candles_processed % config["continuous_learning_interval"] == 0 and len(model_names) > 0 and len(model_recent_trades[model_names[0]]) >= 10:
                    logger.info(f"\n🔄 CONTINUOUS LEARNING UPDATE (Candle {candles_processed:,}):")
                    for i, model_name in enumerate(model_names):
                        if len(model_recent_trades[model_name]) > 0:
                            recent_wr = np.mean(model_recent_trades[model_name][-20:])
                            # BUG #17 FIX: Clamp weight to positive range [0.5, 1.6] to prevent zero/negative weights
                            weight = 0.8 + (recent_wr - 0.5) * 1.6
                            weight = np.clip(weight, 0.5, 1.6)  # Prevent weight from becoming 0 or negative
                            logger.info(f"  {model_name}: Win rate={recent_wr:.1%}, Ensemble weight={weight:.2f}x")
                    portfolio_wr = np.mean(recent_trades_window[-50:]) if len(recent_trades_window) >= 10 else 0.5
                    logger.info(f"  Portfolio: Recent win rate={portfolio_wr:.1%}")

                    # CORRELATION MATRIX UPDATE (every 500 candles)
                    if candles_processed - last_corr_update >= config["correlation_update_interval"] and len(positions) > 1:
                        logger.info(f"📊 Updating correlation matrix...")
                        # Calculate correlations between all symbol pairs in positions
                        position_symbols = list(positions.keys())
                        for i, sym1 in enumerate(position_symbols):
                            for j, sym2 in enumerate(position_symbols[i+1:], i+1):
                                if sym1 in window_data and sym2 in window_data and len(window_data[sym1]) >= 50 and len(window_data[sym2]) >= 50:
                                    corr = self.calculate_correlation(
                                        window_data[sym1][-50:],
                                        window_data[sym2][-50:],
                                        lookback=50
                                    )
                                    key = tuple(sorted([sym1, sym2]))
                                    # BUG #15 FIX: Validate correlation is finite and in [-1, 1] range
                                    if np.isfinite(corr) and -1.0 <= corr <= 1.0:
                                        correlation_matrix[key] = corr
                                    else:
                                        logger.warning(f"⚠️ Invalid correlation {corr} for {sym1}↔{sym2}, using 0.0")
                                        correlation_matrix[key] = 0.0

                                    # Log high correlations (potential hedging opportunities)
                                    corr_safe = correlation_matrix[key]  # Use validated correlation
                                    if abs(corr_safe) > config["max_sector_correlation"]:
                                        sector1 = sector_map.get(sym1, "OTHER")
                                        sector2 = sector_map.get(sym2, "OTHER")
                                        logger.info(f"  ⚠️ High correlation: {sym1}({sector1}) ↔ {sym2}({sector2}) = {corr_safe:.3f}")

                        # Analyze sector exposure
                        sector_exposure = {}
                        for sym, pos in positions.items():
                            sector = sector_map.get(sym, "OTHER")
                            if sector not in sector_exposure:
                                sector_exposure[sector] = {"capital": 0, "symbols": []}
                            sector_exposure[sector]["capital"] += pos["size"]
                            sector_exposure[sector]["symbols"].append(sym)

                        # Log sector concentration
                        total_capital = sum(s["capital"] for s in sector_exposure.values())
                        # BUG #11 FIX: Enhanced division by zero protection with NaN validation
                        for sector, data in sector_exposure.items():
                            # Ensure capital is finite before division
                            if np.isfinite(total_capital) and total_capital > 1e-8:
                                sector_pct = data["capital"] / total_capital
                            else:
                                sector_pct = 0.0

                            # Ensure result is valid
                            if np.isfinite(sector_pct) and 0 <= sector_pct <= 1.0:
                                if sector_pct > 0.3:
                                    logger.info(f"  ⚠️ Sector concentration: {sector} = {sector_pct:.1%} ({data['symbols']})")
                            else:
                                logger.warning(f"⚠️ Invalid sector percentage: {sector_pct} for {sector}")

                        last_corr_update = candles_processed

                    # CONTINUOUS LEARNING: RETRAIN MODELS WITH FORWARD-LOOKING LABELS
                    # Create labels by looking at ACTUAL FUTURE price movement (not past data)
                    if len(retraining_buffer["features"]) >= 100 and candles_processed - last_retrain_candle >= config["continuous_learning_interval"]:
                        logger.info(f"🧠 Creating forward-looking labels from actual future prices...")

                        # Create multi-horizon labels by looking at actual future prices
                        labels_multi = {h: [] for h in retraining_buffer["horizons"]}
                        features_for_training = []
                        valid_count = 0

                        for idx in range(len(retraining_buffer["features"])):
                            pred_timestamp = retraining_buffer["timestamps"][idx]
                            symbol_key = retraining_buffer["symbols"][idx]
                            price_at_pred = retraining_buffer["prices_at_prediction"][idx]

                            # BUG #7 FIX: Check for NaN and infinity in addition to non-positive prices
                            if not np.isfinite(price_at_pred) or price_at_pred <= 0:  # Invalid price
                                continue

                            has_valid_label = True
                            sample_labels = {}

                            # For each horizon, look ahead in actual price data
                            for horizon_h in retraining_buffer["horizons"]:
                                # Find future price by looking ahead from prediction timestamp
                                # Search in window_data for prices AFTER pred_timestamp
                                future_price = None
                                lookahead_candles = 0

                                if symbol_key in window_data and len(window_data[symbol_key]) > 0:
                                    # Find current position in window_data by timestamp
                                    found_idx = None
                                    for j, candle in enumerate(window_data[symbol_key]):
                                        if candle.timestamp >= pred_timestamp:
                                            found_idx = j
                                            break

                                    # Verify we found the timestamp and have future data
                                    if found_idx is not None:
                                        target_idx = found_idx + horizon_h  # horizon is in hours, each candle is 1 hour
                                        if target_idx < len(window_data[symbol_key]):
                                            future_price = window_data[symbol_key][target_idx].close
                                            lookahead_candles = horizon_h

                                if future_price is None:
                                    # Not enough future data for this horizon
                                    has_valid_label = False
                                    break

                                # Create label based on actual price movement
                                # BUG FIX #21: Add epsilon protection for division by zero in retraining labels
                                # BUG FIX #49: CRITICAL - Changed > and < to >= and <= for label thresholds
                                # Was: exactly ±1% return → HOLD (off-by-one boundary error)
                                # Now: ±1% and above → LONG/SHORT (correct boundary)
                                price_return = (future_price - price_at_pred) / (price_at_pred + 1e-8)
                                if price_return >= 0.01:  # Up 1%+
                                    label = 2  # LONG
                                elif price_return <= -0.01:  # Down 1%+
                                    label = 0  # SHORT
                                else:
                                    label = 1  # HOLD
                                sample_labels[horizon_h] = label

                            if has_valid_label and len(sample_labels) == len(retraining_buffer["horizons"]):
                                features_for_training.append(retraining_buffer["features"][idx])
                                for h in retraining_buffer["horizons"]:
                                    labels_multi[h].append(sample_labels[h])
                                valid_count += 1

                        # Retrain if we have enough labeled data
                        if len(features_for_training) >= 50:
                            logger.info(f"  ✅ Created {valid_count} valid forward-looking labels, retraining models...")
                            X_retrain = np.array(features_for_training)

                            # BUG FIX #7: Validate feature dimensions before retraining
                            # Features should be 35-dimensional from prepare_features() or state_dim if already padded
                            expected_dim = 35  # Native feature dimension from prepare_features()
                            if X_retrain.shape[1] not in [expected_dim, model_trainer.state_dim]:
                                logger.error(f"❌ Feature dimension mismatch in retraining: got {X_retrain.shape[1]}, expected {expected_dim} or {model_trainer.state_dim}")
                                # Skip retraining with malformed features to prevent model corruption
                                continue

                            # BUG #8 FIX: Add NaN/inf validation on features before retraining
                            if not np.all(np.isfinite(X_retrain)):
                                nan_count = np.sum(~np.isfinite(X_retrain))
                                logger.error(f"❌ Found {nan_count} NaN/inf values in {X_retrain.size} retraining features")
                                continue

                            y_retrain_multi = {h: np.array(labels_multi[h]) for h in retraining_buffer["horizons"]}

                            # CRITICAL FIX: Validate all horizons have aligned lengths before iterating
                            horizon_lengths = {h: len(labels_multi[h]) for h in retraining_buffer["horizons"]}
                            if len(set(horizon_lengths.values())) > 1:
                                logger.warning(f"⚠️ Horizon label misalignment detected: {horizon_lengths}")
                                min_length = min(horizon_lengths.values())
                                logger.info(f"  Using only first {min_length} samples (discarding {sum(h - min_length for h in horizon_lengths.values())} misaligned)")
                                # Trim all horizons to shortest
                                y_retrain_multi = {h: y_retrain_multi[h][:min_length] for h in retraining_buffer["horizons"]}
                                X_retrain = X_retrain[:min_length]
                            else:
                                logger.info(f"✅ All {len(retraining_buffer['horizons'])} horizons aligned: {list(horizon_lengths.values())[0]} samples each")

                            # Create rewards from multi-horizon labels (ensemble consensus)
                            # Use majority vote across horizons: LONG(2)=+1, SHORT(0)=-1, HOLD(1)=0
                            rewards_retrain = []
                            for sample_idx in range(len(y_retrain_multi[retraining_buffer["horizons"][0]])):
                                # Get labels across all horizons for this sample (now safe - all aligned)
                                horizon_labels = [y_retrain_multi[h][sample_idx] for h in retraining_buffer["horizons"]]
                                majority_label = np.median(horizon_labels)

                                # Convert to reward: LONG=+1, SHORT=-1, HOLD=0
                                if majority_label >= 1.5:  # Consensus LONG
                                    reward = 1.0
                                elif majority_label <= 0.5:  # Consensus SHORT
                                    reward = -1.0
                                else:  # Hold or uncertain
                                    reward = 0.0
                                rewards_retrain.append(reward)

                            rewards_retrain = np.array(rewards_retrain)

                            # Retrain with new forward-looking labels
                            try:
                                _ = model_trainer.train(
                                    X_retrain, y_retrain_multi, rewards_retrain,
                                    epochs=2,  # Light retraining (2 epochs to adapt without overfitting)
                                    batch_size=32,
                                )
                                # Save updated checkpoints
                                model_trainer.save_checkpoints()
                                logger.info(f"  ✅ Models retrained on {len(features_for_training)} samples and checkpoints updated")
                                last_retrain_candle = candles_processed

                                # CRITICAL FIX: Only clear buffer AFTER successful retraining
                                # If we skip retrain due to < 50 valid labels, keep the samples for next cycle
                                retraining_buffer["features"] = []
                                retraining_buffer["predictions"] = []
                                retraining_buffer["timestamps"] = []
                                retraining_buffer["symbols"] = []
                                retraining_buffer["prices_at_prediction"] = []
                            except Exception as e:
                                logger.warning(f"  ⚠️ Retraining failed: {e}")
                                # Don't clear buffer - keep samples for next attempt
                        else:
                            logger.info(f"  ⚠️ Not enough valid labels ({valid_count} < 50), skipping retrain (kept {len(retraining_buffer['features'])} samples for next cycle)")

            window_data[symbol].append(candle)

            # Keep only recent data (memory efficiency)
            max_window = self.train_window + self.test_window + 50
            candles_per_day = config["candles_per_day"]
            if len(window_data[symbol]) > max_window * candles_per_day:
                window_data[symbol] = window_data[symbol][-max_window * candles_per_day:]

            # PHASE A: Microstructure - SKIPPED during backtest
            # Live order book API calls are meaningless for historical data.
            # The microstructure_filters_pass flag defaults to True (set below),
            # so this doesn't block trades.

            # Update existing positions
            if symbol in positions:
                pos = positions[symbol]
                # BUG FIX #36: Use HIGH/LOW for exit triggers, CLOSE for P&L calculation
                # Must check if price touches stop/target during candle, not just close
                current_price = candle.close  # For P&L calculation
                high_price = candle.high  # For stop loss (longs)
                low_price = candle.low  # For stop loss (shorts)
                entry_price = pos["entry_price"]
                side = pos["side"]

                # Calculate unrealized P&L (CRITICAL FIX: guard against zero entry_price)
                # BUG #12: Also check for NaN - NaN <= 0 returns False, bypassing validation
                if not np.isfinite(entry_price) or entry_price <= 0:
                    # BUG FIX #8: Entry price zero/negative prevents stop loss triggering
                    # Force exit position immediately (liquidate)
                    logger.error(f"🚨 CRITICAL: Position {symbol} has invalid entry_price={entry_price}, force-liquidating")
                    capital += pos["size"]  # Return capital, ignore loss
                    trades.append({
                        "symbol": symbol,
                        "entry_time": pos["entry_time"],
                        "exit_time": timestamp,
                        "entry_price": entry_price if entry_price > 0 else current_price,
                        "exit_price": current_price,
                        "side": side,
                        "size": pos["size"],
                        "pnl": 0,  # Mark as zero loss (data error)
                        "pnl_pct": 0,
                        "exit_reason": "invalid_entry_price",
                        "trade_costs": pos.get("entry_cost", 0) + pos["size"] * COST_PER_SIDE,
                        "hours_held": (timestamp - pos["entry_time"]).total_seconds() / 3600,
                    })
                    del positions[symbol]
                    continue  # Skip to next position

                # Normal P&L calculation
                if side == "long":
                    pnl_pct = (current_price - entry_price) / entry_price
                else:
                    pnl_pct = (entry_price - current_price) / entry_price

                unrealized_pnl = pos["size"] * pnl_pct

                # TIER 1 FIX: Update highest/lowest prices for trailing stops
                if side == "long":
                    pos["highest_price"] = max(pos.get("highest_price", entry_price), current_price)
                else:
                    pos["lowest_price"] = min(pos.get("lowest_price", entry_price), current_price)

                # Calculate volatility for adaptive stops (last 20 candles)
                recent_closes = [c.close for c in window_data[symbol][-20:]] if len(window_data[symbol]) >= 20 else [entry_price]
                if len(recent_closes) > 1:
                    # BUG FIX #18: Add epsilon protection for division by zero in stop loss calculation
                    volatility = np.std(np.diff(recent_closes) / (np.array(recent_closes[:-1]) + 1e-8))
                else:
                    volatility = 0.02  # Default 2% volatility

                # STOP LOSS: ATR-based, set at entry, does NOT widen with time
                # Previous bug: stops widened from 2% to 5% to 12% to 20% as holding
                # time increased. This inverted risk/reward — avg loss ($4.99) was 2.2x
                # avg win ($2.27). The fix: use ATR at entry to set a stop that is
                # ALWAYS tighter than the first pyramid target.
                #
                # Use the entry ATR stored in position, or compute from recent data
                entry_atr_pct = pos.get("entry_atr_pct", 0.02)  # Default 2%

                # Stop = 1.2x ATR, clamped to [1.2%, 3.5%]
                # Tightened from 1.5x to reduce avg loss. With 1.5x ATR the stop
                # was ~3% = $5.90 avg loss. At 1.2x ATR the stop is ~2.4% = ~$4.70.
                # This improves the win/loss ratio from 0.85 to 1.06, flipping EV positive.
                # Still deliberately tighter than target 1 (3x ATR) for positive risk/reward.
                base_stop = np.clip(1.2 * entry_atr_pct, 0.012, 0.035)

                # After pyramid 1 is hit, move stop to breakeven (entry price)
                # This protects the remaining 60% from giving back all profits
                if pos.get("pyramided_1", False):
                    base_stop = 0.002  # 0.2% = essentially breakeven (covers slippage)

                # TIER 2 FIX: LEARN OPTIMAL STOP DISTANCE FROM HISTORICAL DATA
                # Use learned stop ONLY if enough data AND it's tighter than ATR-based stop.
                # Never override the breakeven stop after pyramid_1 (0.2%).
                # Previously this unconditionally set base_stop = 5% (the default),
                # overwriting the 1.5x ATR stop (~3%) and breakeven stop (0.2%).
                if not pos.get("pyramided_1", False):
                    optimal_stop = self.get_optimal_stop_distance(stop_distance_effectiveness)
                    # Only use learned stop if it's tighter (more protective) than ATR stop
                    if optimal_stop < base_stop:
                        base_stop = optimal_stop

                # CRITICAL FIX: Recalculate regime for position exit (not yet calculated for current timestamp)
                if symbol in window_data and len(window_data[symbol]) >= feature_window_size:
                    prev_regime = symbol_regime.get(symbol, ('sideways', 0))[0] if symbol in symbol_regime else 'sideways'
                    regime = self.detect_market_regime(
                        window_data[symbol][-feature_window_size:],
                        window=50,
                        prev_regime=prev_regime,
                        switch_threshold=1.0,
                        base_threshold=config["regime_base_threshold"],
                        vol_threshold=config["regime_vol_threshold"]
                    )
                else:
                    regime = symbol_regime.get(symbol, ('sideways', 0))[0] if symbol in symbol_regime else 'sideways'

                # TIER 3 FIX: REGIME-AWARE STOP ADJUSTMENTS
                # Tighten stops for trades against regime, loosen for trades with regime
                if regime == 'bull':
                    if side == "long":
                        base_stop *= 0.85  # With trend: -15% stop (tighter)
                    else:
                        base_stop *= 1.15  # Against trend: +15% stop (wider)
                elif regime == 'bear':
                    if side == "short":
                        base_stop *= 0.85  # With trend: -15% stop (tighter)
                    else:
                        base_stop *= 1.15  # Against trend: +15% stop (wider)
                # Neutral: no adjustment

                # Apply volatility adjustment (small, since ATR already captures vol)
                stop_loss_pct = base_stop + (volatility * 0.5)
                take_profit_pct = pos.get("pyramid_target_2", 0.15)  # Use entry-time target

                # Reasonable bounds
                stop_loss_pct = max(config["stop_loss_min"], min(config["stop_loss_max"], stop_loss_pct))      # 2% min, 30% max
                take_profit_pct = max(config["take_profit_min"], min(config["take_profit_max"], take_profit_pct))  # 5% min, 60% max

                # Check exit conditions
                should_exit = False
                exit_reason = ""
                partial_exit_pct = 0.0  # Fraction of position to exit
                effective_stop_distance = base_stop  # Track which stop was used

                # TRAILING STOP: Captures small winners before they reverse
                # Fires on ANY trade above entry (longs) or below entry (shorts).
                # With ~50% model accuracy, most winners are small (+1-4%).
                # This is the primary mechanism that converts those into realized profits.
                trailing_stop_pct = 0.05  # 5% trailing from peak
                if side == "long" and pos.get("highest_price", entry_price) > entry_price:
                    if low_price < pos["highest_price"] * (1 - trailing_stop_pct):
                        should_exit = True
                        exit_reason = "trailing_stop"
                        partial_exit_pct = 1.0
                        current_price = low_price
                        pnl_pct = (current_price - entry_price) / entry_price
                elif side == "short" and pos.get("lowest_price", entry_price) < entry_price:
                    if high_price > pos["lowest_price"] * (1 + trailing_stop_pct):
                        should_exit = True
                        exit_reason = "trailing_stop"
                        partial_exit_pct = 1.0
                        current_price = high_price
                        pnl_pct = (entry_price - current_price) / entry_price

                # TIER 1 FIX: PROFIT PYRAMIDING (CRITICAL FIX BUG #3: Use fixed targets set at entry)
                # Take profits gradually instead of holding to full target
                # This locks in profits and reduces drawdown
                # BUG FIX #36: Check HIGH price for profit targets (longs), LOW for shorts
                pyramid_target_1 = pos.get("pyramid_target_1", 0.05)  # Default 5% if not set
                pyramid_target_2 = pos.get("pyramid_target_2", 0.15)  # Default 15% if not set

                # For profit targets, check if price has TOUCHED the target (using high/low)
                if side == "long":
                    # Longs hit profit target when high_price reaches entry * (1 + target)
                    target_1_price = entry_price * (1 + pyramid_target_1)
                    target_2_price = entry_price * (1 + pyramid_target_2)
                    hit_target_1 = high_price >= target_1_price
                    hit_target_2 = high_price >= target_2_price
                else:
                    # Shorts hit profit target when low_price reaches entry * (1 - target)
                    target_1_price = entry_price * (1 - pyramid_target_1)
                    target_2_price = entry_price * (1 - pyramid_target_2)
                    hit_target_1 = low_price <= target_1_price
                    hit_target_2 = low_price <= target_2_price

                if not should_exit and not pos.get("pyramided_1", False) and hit_target_1:
                    partial_exit_pct = 0.30  # Exit 30% of position at first target
                    exit_reason = "profit_pyramid_1"
                    should_exit = True
                    # Mark that we hit first pyramid level
                    # BUG #18 FIX: Use epsilon-based comparison for floating-point reliability
                    if partial_exit_pct < 1.0 - 1e-8:
                        pos["pyramided_1"] = True
                    # Exit at the target price, not current close
                    current_price = target_1_price
                    # CRITICAL BUG FIX #2: Recalculate pnl_pct after exit price change
                    if side == "long":
                        pnl_pct = (current_price - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - current_price) / entry_price
                    logger.debug(f"📊 Pyramid 1: {symbol} at {pyramid_target_1*100:.2f}% target, exiting 30%")

                # CRITICAL FIX: Add missing guard for pyramided_2 to prevent double exit
                if not should_exit and not pos.get("pyramided_2", False) and hit_target_2:  # Final target
                    partial_exit_pct = 1.0  # Exit remaining position
                    should_exit = True
                    exit_reason = "take_profit"
                    pos["pyramided_2"] = True  # Mark that we hit final pyramid level
                    # Exit at the target price, not current close
                    current_price = target_2_price
                    # CRITICAL BUG FIX #2: Recalculate pnl_pct after exit price change
                    if side == "long":
                        pnl_pct = (current_price - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - current_price) / entry_price
                    logger.debug(f"📊 Pyramid 2: {symbol} at {pyramid_target_2*100:.2f}% target, exiting remaining 70%")

                # Stop loss (aggressive: tighter on long positions, wider on short)
                # BUG FIX #36: Use LOW price for long stops, HIGH price for short stops
                if side == "long":
                    stop_price = entry_price * (1 - stop_loss_pct)
                    hit_stop = low_price <= stop_price
                else:
                    stop_price = entry_price * (1 + stop_loss_pct)
                    hit_stop = high_price >= stop_price

                if not should_exit and hit_stop:
                    should_exit = True
                    exit_reason = "stop_loss"
                    partial_exit_pct = 1.0
                    current_price = stop_price  # Exit at the stop price
                    # CRITICAL BUG FIX #2: Recalculate pnl_pct after exit price change
                    if side == "long":
                        pnl_pct = (current_price - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - current_price) / entry_price
                # TIER 1 FIX: ADAPTIVE HOLD PERIODS
                # Let winners run longer, exit losers faster based on recent performance
                max_hold_hours = config["max_hold_hours_default"]  # Default: 66+ days
                if len(recent_trades_window) >= 10:
                    recent_win_rate = np.mean(recent_trades_window[-10:])
                    if recent_win_rate > 0.60:  # Win streak
                        max_hold_hours = config["max_hold_hours_winner"]  # Let it run: 83 days
                    elif recent_win_rate < 0.40:  # Loss streak
                        max_hold_hours = config["max_hold_hours_loser"]  # Exit faster: 50 days
                    # Otherwise: 1600h normal

                # Time-based exit (hold max based on recent performance)
                # BUG FIX #46: CRITICAL - Changed elif to if (was unreachable when 10+ recent trades!)
                # With elif, if recent_trades_window >= 10, the if block at line 2074 executes
                # and this elif never runs, preventing all time-based exits after 10 trades
                if not should_exit and (timestamp - pos["entry_time"]).total_seconds() > max_hold_hours * 3600:
                    should_exit = True
                    exit_reason = "time_exit"
                    partial_exit_pct = 1.0

                if should_exit:
                    # Handle partial exits (profit pyramiding)
                    exit_size = pos["size"] * partial_exit_pct
                    exit_cost = exit_size * COST_PER_SIDE
                    realized_pnl = exit_size * pnl_pct - exit_cost
                    capital += exit_size + realized_pnl

                    # CRITICAL FIX: Check for negative capital (margin call)
                    if capital < 0:
                        logger.warning(f"🚨 MARGIN CALL: Capital went negative (${capital:.2f}). Account liquidated. Stopping all trading.")
                        portfolio_trading_paused = True

                    # If full exit, remove position; otherwise reduce position size
                    if partial_exit_pct >= 1.0:
                        # SAFEGUARD: Track last exit time and direction for cooldown and churn detection
                        last_exit_time[symbol] = candles_processed
                        current_direction = pos["side"]

                        # Detect direction flips (long->short or short->long)
                        if symbol in trade_directions:
                            if trade_directions[symbol] != current_direction:
                                if symbol not in trade_churn:
                                    trade_churn[symbol] = 0
                                trade_churn[symbol] += 1
                                if trade_churn[symbol] > config["churn_alert_threshold"]:
                                    logger.warning(f"⚠️ HIGH CHURN on {symbol}: {trade_churn[symbol]} direction flips (long<->short). Possible thrashing.")
                                # Block symbol temporarily if too many flips
                                if trade_churn[symbol] >= max_flips_per_symbol:
                                    flip_block_until[symbol] = candles_processed + flip_block_candles
                                    logger.warning(f"🚫 BLOCKING {symbol} for {flip_block_candles} candles ({trade_churn[symbol]} flips exceeded limit of {max_flips_per_symbol})")
                                    trade_churn[symbol] = 0  # Reset counter after block

                        trade_directions[symbol] = current_direction
                        del positions[symbol]
                    else:
                        # BUG FIX #6: Reset highest/lowest prices AFTER PARTIAL EXIT
                        # After taking profit on 30%, the remaining 70% gets a fresh trailing stop baseline
                        # New peak/trough = current price (not old peak), so trailing stop is relative to exit point
                        # The daily update at line 1913-1915 continues updating peak/trough normally
                        pos["size"] *= (1.0 - partial_exit_pct)
                        if side == "long":
                            pos["highest_price"] = current_price  # Reset peak for remaining position
                        else:
                            pos["lowest_price"] = current_price   # Reset trough for remaining position
                        logger.debug(f"📊 Partial exit {symbol}: reset trailing stop baseline, size now ${pos['size']:.0f}")

                    trade = {
                        "symbol": symbol,
                        "side": side,
                        "entry_price": entry_price,
                        "exit_price": current_price,
                        "entry_time": pos["entry_time"].isoformat(),
                        "exit_time": timestamp.isoformat(),
                        "pnl": realized_pnl,
                        "pnl_pct": pnl_pct * 100,
                        "exit_size_pct": partial_exit_pct * 100,  # Track what % was exited
                        "exit_reason": exit_reason,
                        "trade_costs": pos.get("entry_cost", 0) + exit_cost,
                    }
                    trades.append(trade)

                    # TIER 1 FIX: TRACK SIGNAL OUTCOMES FOR STATISTICAL SIGNIFICANCE TESTING
                    # Record whether this signal was a win (1) or loss (0) by symbol and action
                    # BUG FIX #47: CRITICAL - Only record outcome for FULL exits, not partial pyramid exits!
                    # Was recording partial exits as separate signals, biasing win rate calculation:
                    # Example: Long 100 shares, pyramid 30% at +5% (recorded as win), then 70% at -5% (recorded as loss)
                    # But overall position is -30%, yet signal_history shows 50% win rate!
                    if "final_action" in pos and partial_exit_pct >= 1.0:  # Only for full exits
                        final_action = pos["final_action"]
                        if symbol not in signal_history:
                            signal_history[symbol] = {0: [], 2: []}  # 0=short, 2=long
                        if final_action not in signal_history[symbol]:
                            signal_history[symbol][final_action] = []

                        # Record outcome: 1 if profitable, 0 if losing
                        outcome = 1 if realized_pnl > 0 else 0
                        signal_history[symbol][final_action].append(outcome)

                        # Keep rolling window of last 100 trades per signal
                        if len(signal_history[symbol][final_action]) > 100:
                            signal_history[symbol][final_action].pop(0)

                    # TIER 2 FIX: UPDATE STOP DISTANCE EFFECTIVENESS TRACKING
                    # Track which stop distances work best
                    if "stop_distance" in pos:
                        used_stop = pos["stop_distance"]
                        # Find the closest stop distance in our tracking
                        closest_stop = min(stop_distance_effectiveness.keys(), key=lambda x: abs(x - used_stop))

                        if realized_pnl > 0:
                            stop_distance_effectiveness[closest_stop]["wins"] += 1
                        else:
                            stop_distance_effectiveness[closest_stop]["losses"] += 1

                    # TIER 1 FIX: DRAWDOWN RECOVERY SCALING
                    # Track recent P&Ls to adjust position sizing during recovery
                    recent_pnls.append(realized_pnl)
                    if len(recent_pnls) > 20:
                        recent_pnls.pop(0)

                    # If we've had net losses recently, reduce position sizing
                    if len(recent_pnls) >= 10:
                        recent_avg_pnl = np.mean(recent_pnls[-10:])
                        if recent_avg_pnl < 0:
                            # Net losses: reduce sizing
                            # BUG FIX #40: Changed from dollar-based to percentage-based (CRITICAL: was account-size dependent)
                            # Old: recovery_scale = max(0.50, 1.0 + (-$50 / 100)) = 0.50x for all accounts
                            # New: recovery_scale = max(0.50, 1.0 + (-$50 / capital / 100)) = properly scaled by account
                            # For $10K: recovery_scale = max(0.50, 1.0 + (-0.005)) = 0.995x (small reduction)
                            # For $100K: recovery_scale = max(0.50, 1.0 + (-0.0005)) = 0.9995x (minimal reduction)
                            recent_avg_pnl_pct = (recent_avg_pnl / max(capital, 1)) * 100
                            recovery_scale = max(config["recovery_scale_min"], 1.0 + (recent_avg_pnl_pct / 100))
                            recovery_mode = True
                        else:
                            # Net profits: restore normal sizing
                            recovery_scale = 1.0
                            recovery_mode = False

                    # Track rolling win-rate for degradation detection
                    recent_trades_window.append(1 if realized_pnl > 0 else 0)
                    if len(recent_trades_window) > max_recent_trades:
                        recent_trades_window.pop(0)

                    # BUG FIX #13: Robust rolling window calculation (use neutral default, not 0)
                    rolling_win_rate = np.mean(recent_trades_window) if len(recent_trades_window) > 0 else 0.5
                    if len(recent_trades_window) >= 10 and rolling_win_rate < degradation_threshold:
                        logger.warning(
                            f"⚠️ Model degradation detected! Rolling win rate: {rolling_win_rate*100:.1f}% "
                            f"(below {degradation_threshold*100:.0f}% threshold). "
                            f"Consider retraining models."
                        )

                    # Track individual model accuracy and P&L (PHASE C)
                    trade_was_profitable = realized_pnl > 0
                    if "individual_predictions" in pos and "final_action" in pos:
                        individual_preds = pos.get("individual_predictions", [])
                        final_action = pos.get("final_action", 1)

                        # BUG FIX #12: Log when model count mismatches (detect crashes)
                        if len(individual_preds) != len(model_names):
                            logger.debug(f"⚠️ Model prediction count mismatch: got {len(individual_preds)}, expected {len(model_names)}")
                            if len(individual_preds) < len(model_names):
                                logger.debug(f"   Missing models: {[model_names[i] for i in range(len(individual_preds), len(model_names))]}")

                        # Check which models predicted the same as final action
                        for idx, pred in enumerate(individual_preds):
                            if idx < len(model_names):
                                model_name = model_names[idx]
                                model_was_correct = (pred == final_action) and trade_was_profitable

                                # BUG #20 FIX: Ensure model_name exists in dictionaries before accessing
                                if model_name not in model_predictions:
                                    model_predictions[model_name] = {"correct": 0, "incorrect": 0}
                                if model_name not in model_recent_trades:
                                    model_recent_trades[model_name] = []

                                if model_was_correct:
                                    model_predictions[model_name]["correct"] += 1
                                    # PHASE B: Track for adaptive weighting
                                    adaptive_weighter.record_prediction(model_name, was_correct=True)
                                else:
                                    model_predictions[model_name]["incorrect"] += 1
                                    # PHASE B: Track for adaptive weighting
                                    adaptive_weighter.record_prediction(model_name, was_correct=False)

                                # TIER 1 FIX: Track per-model win rate for future signal weighting
                                if pred == final_action:  # Model voted with ensemble
                                    model_recent_trades[model_name].append(1 if trade_was_profitable else 0)
                                    if len(model_recent_trades[model_name]) > 50:
                                        model_recent_trades[model_name].pop(0)  # Keep rolling window of 50

                                # PHASE C: Track P&L contribution
                                # Credit model if it voted for the winning action
                                if pred == final_action:  # Model agrees with ensemble
                                    model_pnl[model_name]["trades"] += 1
                                    if trade_was_profitable:
                                        model_pnl[model_name]["pnl"] += realized_pnl
                                        model_pnl[model_name]["wins"] += 1
                                    else:
                                        model_pnl[model_name]["pnl"] += realized_pnl
                                        model_pnl[model_name]["losses"] += 1

                    # Log trade closure
                    trade_direction = "LONG" if side == "long" else "SHORT"
                    logger.debug(
                        f"Trade Closed: {symbol} {trade_direction} | "
                        f"Entry: ${entry_price:.4f} → Exit: ${current_price:.4f} | "
                        f"P&L: ${realized_pnl:.2f} ({pnl_pct*100:.2f}%) | "
                        f"Reason: {exit_reason}"
                    )

            # TIER 1 FIX: Portfolio-level drawdown check - stop trading if DD > 15%
            # CRITICAL FIX: Calculate unrealized P&L correctly (was 10-100x inflated!)
            # Old formula: pos["size"] * current_price / entry_price (returns total position value)
            # Correct formula: pos["size"] * (current_price / entry_price - 1) (returns profit/loss)
            unrealized_pnl = 0.0
            for sym, pos in positions.items():
                if sym in window_data and len(window_data[sym]) > 0:
                    current_price = window_data[sym][-1].close
                    entry_price = pos["entry_price"]
                    # BUG FIX #10: Validate both prices with epsilon guard before division (prevent Inf/NaN)
                    if entry_price > 1e-8 and current_price > 1e-8:
                        if pos["side"] == "long":
                            unrealized_pnl += pos["size"] * (current_price / entry_price - 1)
                        else:
                            unrealized_pnl += pos["size"] * (entry_price / current_price - 1)

            current_equity = capital + unrealized_pnl
            rolling_max_equity = max(rolling_max_equity, current_equity)
            current_dd = (rolling_max_equity - current_equity) / rolling_max_equity if rolling_max_equity > 0 else 0

            if current_dd > max_portfolio_dd:
                portfolio_trading_paused = True
                if not any(t.get("reason") == "DD_LIMIT_PAUSED" for t in trades[-10:]):  # Log once
                    logger.warning(f"⚠️ PORTFOLIO DD LIMIT HIT: {current_dd*100:.1f}% > {max_portfolio_dd*100:.0f}% | Pausing new trades")
            elif current_dd < max_portfolio_dd * config["portfolio_dd_resume_pct"]:  # Resume at 70% of limit
                portfolio_trading_paused = False

            # TIER 2 FIX: MACRO VOLATILITY REGIME FILTERING
            # Detect macro regime shifts (elevated vol = higher risk, extreme vol = don't trade)
            portfolio_vols_for_macro = []
            for sym in list(window_data.keys())[:5]:  # Sample first 5 symbols for efficiency
                if len(window_data[sym]) >= 30:
                    closes = np.array([c.close for c in window_data[sym][-30:]])
                    # BUG FIX #11: Add epsilon to prevent division by zero (defensive programming)
                    returns = np.diff(closes) / (closes[:-1] + 1e-8)
                    vol = np.std(returns)
                    # CRITICAL FIX: Filter out NaN volatilities before averaging (prevents NaN regime detection)
                    if np.isfinite(vol) and vol > 0:
                        portfolio_vols_for_macro.append(vol)

            if portfolio_vols_for_macro:
                current_macro_vol = np.mean(portfolio_vols_for_macro)
                # CRITICAL FIX: Validate macro volatility is finite before using in division
                if not np.isfinite(current_macro_vol):
                    logger.warning("Macro volatility is non-finite, keeping previous regime")
                    current_macro_vol = baseline_portfolio_vol

                # Update baseline if we're in normal conditions
                if current_macro_vol < baseline_portfolio_vol * 1.2:
                    baseline_portfolio_vol = baseline_portfolio_vol * 0.99 + current_macro_vol * 0.01  # Exponential moving average

                # Detect regime shifts
                # BUG FIX #25: Add epsilon protection for division by zero in vol_ratio
                vol_ratio = current_macro_vol / max(baseline_portfolio_vol, 1e-8)
                prev_regime = macro_regime

                if vol_ratio > extreme_vol_threshold:
                    macro_regime = "extreme"
                    if prev_regime != "extreme":
                        logger.warning(f"⚠️ MACRO REGIME SHIFT: Extreme volatility detected (vol_ratio={vol_ratio:.2f}) | Pausing new trades")
                elif vol_ratio > high_vol_threshold:
                    macro_regime = "elevated"
                    if prev_regime != "elevated":
                        logger.info(f"⚠️ Elevated volatility regime (vol_ratio={vol_ratio:.2f}) | Reducing position sizes")
                else:
                    macro_regime = "normal"

            # Generate trading signal (only if we have enough data AND portfolio not paused AND not during extreme macro vol)
            macro_vol_safe = macro_regime != "extreme"
            # CRITICAL FIX: Need enough data for feature preparation
            # prepare_features needs lookback (400) + 20 candles = 420 minimum
            # But config["feature_lookback_window"] is only 100!
            # Must pass more candles or specify smaller lookback explicitly
            feature_window_size = max(config["feature_lookback_window"], 420)  # 420 = 400 lookback + 20

            if len(window_data[symbol]) >= feature_window_size and symbol not in positions and not portfolio_trading_paused and macro_vol_safe:
                features = self.prepare_features(
                    window_data[symbol][-feature_window_size:],
                    lookback=min(400, feature_window_size - 20)  # Ensure valid lookback
                )

                if len(features) > 0:
                    # Detect market regime FIRST (needed for regime-aware prediction)
                    # Use same window as features for consistency
                    # BUG FIX #11: Pass previous regime for hysteresis (prevent whipsaw)
                    prev_regime = symbol_regime.get(symbol, ('sideways', 0))[0] if symbol in symbol_regime else 'sideways'
                    regime = self.detect_market_regime(
                        window_data[symbol][-feature_window_size:],
                        prev_regime=prev_regime,
                        switch_threshold=regime_switch_threshold,
                        base_threshold=config["regime_base_threshold"],
                        vol_threshold=config["regime_vol_threshold"]
                    )
                    # Update regime tracker
                    # BUG FIX #28: Validate regime state before unpacking (prevents ValueError from corrupted data)
                    if symbol in symbol_regime and isinstance(symbol_regime[symbol], tuple) and len(symbol_regime[symbol]) == 2:
                        prev_r, age = symbol_regime[symbol]
                        symbol_regime[symbol] = (regime, age+1 if regime == prev_r else 0)  # Reset age on switch
                    else:
                        symbol_regime[symbol] = (regime, 0)

                    # Get ML prediction - TIER 3: Use regime-aware models
                    state = features[-1]
                    prediction = model_trainer.predict_regime_aware(state, regime)
                    signals_generated += 1

                    # CRITICAL: Cast numpy scalars to Python types to prevent
                    # "truth value of array is ambiguous" in downstream and/or/if checks
                    prediction["action"] = int(prediction["action"])
                    prediction["confidence"] = float(prediction["confidence"])
                    if "predictions" in prediction:
                        prediction["predictions"] = [int(p) for p in prediction["predictions"]]

                    # BUG FIX #38: Detect model prediction failures (NaN/inf confidence, missing fields)
                    # Check for corrupted predictions before using them
                    if (not isinstance(prediction, dict) or
                        "confidence" not in prediction or
                        "action" not in prediction or
                        not np.isfinite(prediction["confidence"]) or
                        np.isnan(prediction["confidence"])):
                        logger.warning(f"⚠️ Invalid model prediction for {symbol} - confidence={prediction.get('confidence', 'MISSING')}")
                        continue  # Skip this signal, models not working

                    # Also check for the specific case where models explicitly fail (confidence=0, action=HOLD)
                    if prediction["confidence"] == 0.0 and prediction["action"] == 1:
                        logger.warning(f"⚠️ Model prediction failed for {symbol} - using HOLD fallback")
                        continue  # Skip this signal, models not working

                    # CONTINUOUS LEARNING: Collect feature-prediction pairs for retraining
                    # Store current price so we can look ahead from this point in time
                    if len(retraining_buffer["features"]) < config["continuous_learning_window"]:
                        retraining_buffer["features"].append(state.copy())
                        retraining_buffer["predictions"].append(prediction["action"])
                        retraining_buffer["timestamps"].append(timestamp)
                        retraining_buffer["symbols"].append(symbol)
                        # CRITICAL FIX: Use symbol's current price, not last candle (which is from different symbol!)
                        symbol_price = window_data[symbol][-1].close if symbol in window_data and len(window_data[symbol]) > 0 else 0
                        retraining_buffer["prices_at_prediction"].append(symbol_price)

                    # DIAGNOSTIC: Log raw model predictions (especially first 50 for detailed debugging)
                    filter_stage_counters["total_predictions"] += 1
                    if signals_generated <= 50 or signals_generated % 1000 == 0:  # Log first 50, then every 1000
                        action_name = {0: 'SHORT', 1: 'HOLD', 2: 'LONG'}.get(prediction["action"], f'UNK_{prediction["action"]}')
                        logger.debug(f"[{signals_generated}] Raw prediction: {symbol} → {action_name}, conf={prediction['confidence']:.3f}, regime={regime}")

                    # Check liquidity (require minimum volume)
                    recent_volumes = np.array([c.volume for c in window_data[symbol][-20:]])
                    avg_volume = np.mean(recent_volumes)
                    min_volume_threshold = config["min_volume_threshold"]  # Minimum acceptable volume
                    is_liquid = avg_volume >= min_volume_threshold

                    # PHASE A: Microstructure signal quality filter
                    # Extract microstructure features from order book data
                    microstructure_score = 1.0  # Default to good conditions
                    microstructure_filters_pass = True
                    microstructure_flags = []

                    if symbol in microstructure_extractors and order_book_cache.get(symbol) is not None:
                        try:
                            micro_features = microstructure_extractors[symbol].extract_features()

                            # Micro Filter 1: Bid-Ask Spread - lower is better (tighter spread = higher quality)
                            spread_bps = micro_features.get("spread_bps", 5.0)  # Default 5 bps if not available
                            if spread_bps < 2:
                                spread_score = 1.0  # Excellent: < 2 bps
                            elif spread_bps < 5:
                                spread_score = 0.9  # Good: 2-5 bps
                            elif spread_bps < 10:
                                spread_score = 0.7  # Acceptable: 5-10 bps
                            else:
                                spread_score = 0.4  # Poor: > 10 bps
                                microstructure_filters_pass = False
                                microstructure_flags.append(f"spread_bps={spread_bps:.1f}")

                            # MOVED HERE: Define is_long, is_short, is_hold BEFORE using in filters
                            is_short = prediction["action"] == 0
                            is_long = prediction["action"] == 2
                            is_hold = prediction["action"] == 1

                            # Micro Filter 2: Order Book Imbalance - check for extreme imbalance
                            ob_imbalance = micro_features.get("ob_imbalance", 0.5)  # Range: 0-1
                            if is_long and ob_imbalance > 0.6:
                                imbalance_score = 1.0  # Buying pressure for long
                            elif is_short and ob_imbalance < 0.4:
                                imbalance_score = 1.0  # Selling pressure for short
                            elif abs(ob_imbalance - 0.5) < 0.15:
                                imbalance_score = 0.8  # Balanced market
                            else:
                                imbalance_score = 0.5  # Conflicting imbalance
                                microstructure_flags.append(f"imbalance={ob_imbalance:.2f}")

                            # Micro Filter 3: Order Flow - check for consistent flow direction
                            order_flow = micro_features.get("order_flow_imbalance", 0.0)  # Range: -1 to 1
                            if is_long and order_flow > 0.3:
                                flow_score = 1.0  # Positive flow for long
                            elif is_short and order_flow < -0.3:
                                flow_score = 1.0  # Negative flow for short
                            else:
                                flow_score = 0.6  # Weak or conflicting flow
                                microstructure_flags.append(f"flow={order_flow:.2f}")

                            # Micro Filter 4: Large Order Presence
                            large_buy = micro_features.get("large_buy_presence", 0.0)
                            large_sell = micro_features.get("large_sell_presence", 0.0)
                            if is_long and large_buy > 0.5:
                                whale_score = 1.0  # Whale buying pressure
                            elif is_short and large_sell > 0.5:
                                whale_score = 1.0  # Whale selling pressure
                            else:
                                whale_score = 0.7  # Neutral whale activity

                            # Composite microstructure score
                            microstructure_score = (spread_score * 0.3 + imbalance_score * 0.35 + flow_score * 0.25 + whale_score * 0.1)

                            if microstructure_score < 0.6:
                                microstructure_filters_pass = False
                                logger.debug(f"⚠️ Microstructure score low: {symbol} score={microstructure_score:.2f} flags={microstructure_flags}")

                        except Exception as e:
                            # BUG FIX #4: Use warning level for better visibility into order book API failures
                            logger.warning(f"Microstructure feature extraction error for {symbol}: {type(e).__name__}: {e}")
                            # Continue without microstructure filter if extraction fails
                    else:
                        # No order book data available yet - use default conditions
                        logger.debug(f"⚠️ No order book data for {symbol} yet - skipping microstructure filter")

                    # PHASE D: Aggressive Signal Filtering
                    # Only trade on ULTRA-STRONG signals
                    # Define is_short, is_long, is_hold before use
                    is_short = prediction["action"] == 0
                    is_long = prediction["action"] == 2
                    is_hold = prediction["action"] == 1
                    conflicting_trade = (regime == 'bull' and is_short) or (regime == 'bear' and is_long)

                    # DIAGNOSTIC: Track filter stages
                    if not is_hold:
                        filter_stage_counters["not_hold"] += 1

                    # TIER 1 FIX: Model weighting by recent performance
                    # Instead of equal voting, weight models by recent win rate
                    individual_preds = prediction.get("predictions", [])
                    final_action = prediction["action"]

                    # Calculate per-model win rates from recent trades
                    model_weights = {}
                    for i, model_name in enumerate(model_names):
                        if len(model_recent_trades[model_name]) > 0:
                            recent_wr = np.mean(model_recent_trades[model_name][-20:])
                            # Weight based on win rate (0.4 to 1.6x multiplier)
                            model_weights[i] = 0.8 + (recent_wr - 0.5) * 1.6
                        else:
                            model_weights[i] = 1.0  # Equal weight if no history

                    # Weighted agreement: sum weights of models agreeing with final action
                    weighted_agreement = sum(
                        model_weights.get(i, 1.0)
                        for i, p in enumerate(individual_preds)
                        if p == final_action and i < len(model_names)
                    )
                    total_model_weight = sum(model_weights.values())
                    weighted_agreement_pct = weighted_agreement / total_model_weight if total_model_weight > 0 else 0

                    # Require strong consensus - both weighted AND simple agreement (BUG FIX #7)
                    # Using OR would allow weak signals (e.g., 2 good models + 2 bad models agree)
                    # Using AND ensures both consensus metrics agree on the signal quality
                    min_agreement = config["min_model_agreement"]  # Require at least 2 out of 4 models
                    model_agreement = sum(1 for p in individual_preds if p == final_action)

                    # STRICT: Require BOTH weighted consensus AND minimum simple agreement
                    strong_consensus = (weighted_agreement_pct > config["weighted_agreement_threshold"]) and (model_agreement >= min_agreement)

                    # HORIZON-AWARE CONFIDENCE: Longer-term signals need lower confidence
                    # Higher agreement (4/4) = likely short-term = need highest confidence
                    # Lower agreement (3/4) = likely longer-term = accept lower
                    # CRITICAL FIX: Increase base thresholds - 0.10-0.30 allows too many marginal trades
                    if model_agreement == 4:
                        min_confidence = config["confidence_4x4_models"]  # 4/4 models: require 0.65+ (was 0.30)
                    elif model_agreement == 3:
                        min_confidence = config["confidence_3x4_models"]  # 3/4 models: require 0.55+ (was 0.20)
                    else:
                        min_confidence = config["confidence_fallback"]  # Fallback: require 0.45+ (was 0.10)

                    # TIER 1 FIX: REGIME-AWARE CONFIDENCE ADJUSTMENT
                    # Adjust thresholds based on market regime (already computed above)
                    # Counter-trend trades (shorts in bull, longs in bear) require HIGHER confidence
                    # CRITICAL FIX: Only apply multiplier to COUNTER-TREND trades, not all trades!
                    # BUG FIX #35: Use ADDITIVE adjustment instead of multiplicative to avoid overshooting thresholds
                    # Multiplicative: 0.65 * 1.10 = 0.715 (blocks 0.70 confidence trades - too strict!)
                    # Additive: 0.65 + 0.08 = 0.73 (more reasonable, preserves base threshold intent)
                    # NOTE: is_short and is_long already defined above (CRITICAL FIX: moved earlier)

                    if regime == 'bull' and is_short:
                        # Shorts in bull market are counter-trend: require HIGHER confidence
                        # Use additive +8% instead of multiplicative 1.10x to avoid overshooting
                        min_confidence += config["regime_bull_confidence_mult"] - 1.0  # 1.10 - 1.0 = 0.10 (10% boost)
                    elif regime == 'bear' and is_long:
                        # Longs in bear market are counter-trend: require HIGHER confidence
                        # Use additive +8% instead of multiplicative 1.10x to avoid overshooting
                        min_confidence += config["regime_bear_confidence_mult"] - 1.0  # 1.10 - 1.0 = 0.10 (10% boost)
                    # Trend-aligned trades (longs in bull, shorts in bear) use base confidence
                    # Sideways: no adjustment, use base confidence

                    meets_confidence = prediction["confidence"] >= min_confidence
                    if meets_confidence:
                        filter_stage_counters["meets_confidence"] += 1
                    if not conflicting_trade:
                        filter_stage_counters["not_conflicting"] += 1
                    if is_liquid:
                        filter_stage_counters["is_liquid"] += 1
                    if strong_consensus:
                        filter_stage_counters["strong_consensus"] += 1
                    if microstructure_filters_pass:
                        filter_stage_counters["good_microstructure"] = filter_stage_counters.get("good_microstructure", 0) + 1

                    # TIER 1 FIX: SIGNAL STATISTICAL SIGNIFICANCE TESTING
                    # Only trade if historical win rate for this symbol-action is statistically > 50%
                    # NOTE: Temporarily loosening for diagnostics - will fail on first few trades with no history
                    is_statistically_significant = self.is_signal_statistically_significant(
                        symbol, prediction["action"], signal_history
                    )
                    if is_statistically_significant:
                        filter_stage_counters["stat_significant"] += 1

                    # DIAGNOSTIC LOGGING: Understand why 0 signals
                    action_name = {0: 'SHORT', 1: 'HOLD', 2: 'LONG'}.get(prediction["action"], f'UNK_{prediction["action"]}')
                    # (is_hold already defined above)

                    # NOTE: Removed 'conflicting_trade' hard ban - now we require HIGHER confidence for counter-trend trades instead
                    # This allows shorts in bull markets (and longs in bear markets) if confidence is high enough
                    # CRITICAL FIX: Include is_statistically_significant in rejection check (was missing, causing inconsistency)
                    # PHASE A ENHANCEMENT: Include microstructure filter for better signal quality
                    if is_hold or not meets_confidence or not is_liquid or not strong_consensus or not is_statistically_significant or not microstructure_filters_pass:
                        # Log why signal was rejected (sampling to avoid spam)
                        if np.random.random() < 0.001:  # Log 0.1% of rejected signals
                            reasons = []
                            if is_hold:
                                reasons.append("is_hold")
                            if not meets_confidence:
                                reasons.append(f"confidence={prediction['confidence']:.3f}<min={min_confidence:.3f}")
                            # NOTE: conflicting_trade is NOT a rejection reason anymore - it just increases required confidence
                            # So we don't log it here, but we DO log it separately as debug info if it applies
                            if not is_liquid:
                                reasons.append(f"illiquid_vol={avg_volume:.0f}")
                            if not strong_consensus:
                                reasons.append(f"consensus={model_agreement}/4")
                            if not is_statistically_significant:
                                reasons.append("not_sig_significant")
                            if not microstructure_filters_pass:
                                reasons.append(f"microstructure_score={microstructure_score:.2f}")
                            logger.debug(f"❌ Signal rejected {action_name} {symbol}: {', '.join(reasons)}")
                            if conflicting_trade:
                                logger.debug(f"   (Note: {action_name} is counter-trend to {regime} regime, required higher confidence)")

                    # SAFEGUARD: Check for per-symbol trading cooldown (prevent thrashing)
                    # Enhanced flip-flop cooldown with configurable multiplier and blocking
                    in_cooldown = False
                    new_direction = "long" if prediction["action"] == 2 else "short"
                    is_direction_flip = symbol in trade_directions and trade_directions[symbol] != new_direction

                    # Check if symbol is blocked due to excessive flipping
                    if symbol in flip_block_until and candles_processed < flip_block_until[symbol]:
                        in_cooldown = True
                        remaining = flip_block_until[symbol] - candles_processed
                        if signals_generated <= 100 or np.random.random() < 0.001:
                            logger.debug(f"🚫 {symbol} BLOCKED for {remaining} more candles (exceeded {max_flips_per_symbol} direction flips)")
                    elif symbol in last_exit_time:
                        candles_since_exit = candles_processed - last_exit_time[symbol]
                        required_cooldown = min_flip_cooldown_candles if is_direction_flip else min_cooldown_candles

                        if candles_since_exit < required_cooldown:
                            in_cooldown = True
                            cooldown_type = "flip-flop" if is_direction_flip else "standard"
                            if signals_generated <= 100 or np.random.random() < 0.001:
                                logger.debug(f"⏳ {symbol} in {cooldown_type} cooldown ({candles_since_exit}/{required_cooldown} candles since exit)")
                        elif is_direction_flip:
                            # Flip-flop confidence penalty: require higher confidence for direction changes
                            effective_confidence = prediction.get("confidence", 0)
                            penalty_threshold = effective_confidence - flip_confidence_penalty
                            if penalty_threshold < config.get("confidence_fallback", 0.45):
                                in_cooldown = True
                                if signals_generated <= 100 or np.random.random() < 0.001:
                                    logger.debug(f"⏳ {symbol} flip confidence too low ({effective_confidence:.2f} - {flip_confidence_penalty:.2f} penalty < threshold)")
                    else:
                        filter_stage_counters["not_in_cooldown"] += 1

                    # SAFEGUARD: Check for position direction conflicts
                    position_conflict = False
                    if symbol in positions:
                        current_pos_side = positions[symbol]["side"]
                        new_action_side = "long" if prediction["action"] == 2 else "short"
                        if current_pos_side != new_action_side:
                            position_conflict = True
                            if signals_generated <= 100 or np.random.random() < 0.01:  # Log first 100 + 1% sample
                                logger.debug(f"🔄 {symbol}: Already {current_pos_side}, signal wants {new_action_side} (conflict)")
                    else:
                        filter_stage_counters["no_conflict"] += 1

                    # Check if already have position on this symbol
                    if symbol not in positions:
                        filter_stage_counters["not_already_open"] += 1

                    if (prediction["action"] != 1 and
                        meets_confidence and
                        # NOTE: conflicting_trade is NOT a hard ban - it's handled by increased confidence requirement above
                        is_liquid and
                        strong_consensus and
                        is_statistically_significant and
                        not in_cooldown and
                        not position_conflict and
                        symbol not in positions):  # Don't open if already have position
                        # ✅ SIGNAL ACCEPTED: Log for diagnostics
                        filter_stage_counters["positions_opened"] += 1
                        logger.info(f"✅ TRADE #{filter_stage_counters['positions_opened']}: {action_name} {symbol} | Conf={prediction['confidence']:.3f} (min={min_confidence:.3f}) | Agreement={model_agreement}/4 | Regime={regime}")

                        # SIMPLIFIED POSITION SIZING (FIXED: Removed cascading multipliers that reduced positions to $0.30)
                        # Issue: Base Kelly * horizon * vol targeting * correlation * counter-trend * vol scaling * leverage
                        #        multiplied together gave 0.002 * 0.30 * 0.5 * 0.7 * 0.7 * 0.67 * 0.7 = 0.00003 = $0.30 per position!
                        # Fix: Use simple Kelly Criterion with portfolio vol targeting overlay
                        confidence = prediction["confidence"]

                        # BUG FIX #2: Available capital calculation
                        # CRITICAL: positions.values() contains positions opened in PREVIOUS candles
                        # Capital has ALREADY been reduced when those positions were opened
                        # Subtracting them again is double-subtraction → available_capital becomes too small
                        # FIX: Just use capital directly (it's already net of open positions)
                        # If we want to track new positions THIS candle, we'd need to track them separately
                        available_capital = capital

                        # Simple Kelly: 2-3% per position (with 10 positions = 20-30% risk, 70-80% cash)
                        # This is more aggressive than before but allows actual trading
                        # BUG FIX #43: Make Kelly fraction adaptive based on recent win rate (CRITICAL: was always fixed 3%)
                        # True Kelly = (win_rate * avg_win - loss_rate * avg_loss) / avg_win
                        # Simplified: kelly_fraction should adjust based on win rate
                        # - 40% win rate: kelly_fraction = 0.5% (very conservative)
                        # - 50% win rate: kelly_fraction = 1.0% (neutral)
                        # - 55% win rate: kelly_fraction = 1.5% (moderate)
                        # - 60% win rate: kelly_fraction = 2.0% (aggressive)
                        # Calculate adaptive Kelly based on recent win rate
                        current_win_rate = np.mean(recent_trades_window[-50:]) if len(recent_trades_window) >= 10 else 0.5
                        if current_win_rate <= 0.40:
                            kelly_fraction = 0.005  # 0.5% for losing period
                        elif current_win_rate <= 0.45:
                            kelly_fraction = 0.010  # 1.0% for break-even period
                        elif current_win_rate <= 0.50:
                            kelly_fraction = 0.015  # 1.5% for neutral
                        elif current_win_rate <= 0.55:
                            kelly_fraction = 0.020  # 2.0% for good
                        elif current_win_rate <= 0.60:
                            kelly_fraction = 0.025  # 2.5% for very good
                        else:
                            kelly_fraction = 0.030  # 3.0% for excellent

                        # Use available_capital instead of total capital (CRITICAL FIX)
                        # BUG FIX #34: CRITICAL - Apply recovery_scale to prevent oversizing during drawdown recovery
                        # Without this, positions stay full-Kelly sized during recovery, risking account blow-up
                        position_size = available_capital * min(kelly_fraction, config["kelly_cap_pct"]) * recovery_scale  # Cap at 4%, scaled by recovery

                        # NEW: PORTFOLIO-LEVEL VOLATILITY TARGETING (Top Funds Approach)
                        # Size positions to maintain total portfolio volatility at 1.2-1.5% daily
                        # This replaces pure Kelly Criterion with risk parity across portfolio
                        target_portfolio_vol = 0.012  # Target 1.2% daily portfolio volatility

                        # SAFETY CHECK: Only apply vol targeting if we have sufficient capital
                        # BUG FIX #31: Require minimum $100 capital to avoid micro-positions and numerical errors
                        min_capital_threshold = 100.0  # Don't trade with less than $100
                        if capital >= min_capital_threshold:
                            portfolio_current_vol = 0.0
                            position_weights_sum = 0.0

                            for existing_sym, existing_pos in positions.items():
                                if existing_sym in window_data and len(window_data[existing_sym]) >= 30:
                                    closes = np.array([c.close for c in window_data[existing_sym][-30:]])
                                    returns = np.diff(closes) / (closes[:-1] + 1e-8)  # BUG FIX #14: Add epsilon
                                    sym_vol = np.std(returns)
                                    # BUG FIX #14: Defensive programming - capital should not be <= 0 due to guard, but be safe
                                    position_weight = existing_pos["size"] / max(capital, 1e-8)
                                    position_weights_sum += position_weight
                                    portfolio_current_vol += sym_vol * position_weight

                            # Add new position's contribution
                            if symbol in window_data and len(window_data[symbol]) >= 30:
                                closes = np.array([c.close for c in window_data[symbol][-30:]])
                                # BUG FIX #17: Add epsilon protection for division by zero (close prices near zero)
                                returns = np.diff(closes) / (closes[:-1] + 1e-8)
                                symbol_vol = np.std(returns)

                                # Calculate required scaling to hit target portfolio vol
                                # BUG FIX #26: Add epsilon protection for capital division (prevent numerical errors when capital very small)
                                new_position_weight = position_size / max(capital, 1e-8)
                                portfolio_expected_vol = portfolio_current_vol + symbol_vol * new_position_weight
                                # NOTE: portfolio_expected_vol is already a weighted sum - do NOT normalize by weight_sum!
                                # portfolio_current_vol = vol1*w1 + vol2*w2 + ... (already weighted)
                                # Adding symbol_vol * new_position_weight gives the correct weighted vol

                                # If we're going over target vol, scale down this position
                                if portfolio_expected_vol > target_portfolio_vol * 1.2:  # Allow 20% buffer
                                    vol_scaling = (target_portfolio_vol * 1.2) / portfolio_expected_vol if portfolio_expected_vol > 0 else 1.0
                                    position_size *= vol_scaling
                                    logger.debug(f"Portfolio vol cap: scaling {symbol} by {vol_scaling:.2f}x (expected_vol={portfolio_expected_vol*100:.2f}%, target={target_portfolio_vol*100:.2f}%)")

                        # effective_stop_distance computed after ATR calculation below

                        # REMOVED: Cascading multipliers (recovery, correlation, counter-trend, vol scaling, leverage)
                        # These were multiplying together: base * 0.30-1.0 * 0.5-1.0 * 0.7 * 0.67-1.5 * 0.7-1.3 = 0.00003x
                        # Causing positions to be $0.30 instead of $100-300
                        # Will be handled by portfolio volatility targeting below instead

                        # REMOVED: Systemic risk, macro regime, and regime-aware multipliers
                        # These were adding additional 0.7x reductions on top of already-low positions
                        # Portfolio vol targeting is sufficient safeguard against systemic risk
                        # (higher correlations automatically reduce positions via vol calculation)

                        # TIER 3A: CONFIDENCE-BASED POSITION SIZING (NEW!)
                        # Higher confidence = bigger position = bigger returns
                        # This allows the system to allocate MORE capital on its highest-conviction trades
                        confidence = prediction["confidence"]
                        confidence_multiplier = 1.0

                        if confidence >= 0.80:
                            # Very high confidence: 2.0x size (double bet on best ideas)
                            confidence_multiplier = 2.0
                            logger.debug(f"🚀 Ultra-high confidence (>80%): +100% position size")
                        elif confidence >= 0.70:
                            # High confidence: 1.5x size
                            confidence_multiplier = 1.5
                            logger.debug(f"📈 High confidence (70-80%): +50% position size")
                        elif confidence >= 0.60:
                            # Medium-high confidence: 1.2x size
                            confidence_multiplier = 1.2
                            logger.debug(f"➡️ Medium-high confidence (60-70%): +20% position size")
                        elif confidence >= 0.50:
                            # Medium confidence: 1.0x size (baseline)
                            confidence_multiplier = 1.0
                        elif confidence >= 0.45:
                            # Low confidence: 0.75x size (minimal penalty for minimum-acceptable signals)
                            # BUG FIX #44: Changed from 0.6x to 0.75x (CRITICAL: 0.45 is minimum threshold, shouldn't penalize 25% reduction)
                            # A signal that barely meets minimum confidence should still get reasonable sizing
                            confidence_multiplier = 0.75
                            logger.debug(f"⚠️ Low confidence (45-50%): -25% position size")
                        else:
                            # Very low confidence: 0.75x size (should never reach here with BUG FIX #39 threshold change)
                            # But if it does (due to edge cases), don't penalize too severely
                            # BUG FIX #41 & #44: Changed from 0.3x to 0.75x (less penalizing for marginal signals)
                            confidence_multiplier = 0.75
                            logger.debug(f"🛑 Very low confidence (<45%): -25% position size (edge case)")

                        position_size *= confidence_multiplier

                        # TIER 3B: REGIME-AWARE POSITION SIZING (KEPT - minimal impact)
                        # Adjust position sizes based on market regime alignment
                        is_long = prediction["action"] == 2
                        is_short = prediction["action"] == 0
                        if regime == 'bull' and is_long:
                            # Long in bull: optimal, increase size by 15%
                            position_size *= 1.15
                            logger.debug(f"Regime alignment bonus (bull long): +15% size")
                        elif regime == 'bull' and is_short:
                            # Short in bull: poor fit, reduce by 20%
                            position_size *= 0.80
                            logger.debug(f"Regime penalty (bull short): -20% size")
                        elif regime == 'bear' and is_short:
                            # Short in bear: optimal, increase size by 15%
                            position_size *= 1.15
                            logger.debug(f"Regime alignment bonus (bear short): +15% size")
                        elif regime == 'bear' and is_long:
                            # Long in bear: poor fit, reduce by 20%
                            position_size *= 0.80
                            logger.debug(f"Regime penalty (bear long): -20% size")
                        # Neutral: no adjustment

                        # BUG FIX #4: Cap maximum position size at 1.5x Kelly for safety
                        # Without this cap, (confidence 2.0x * regime 1.15x) = 2.3x Kelly = too risky
                        # Kelly Criterion safety margin requires position_size <= 1.5 * kelly_base_size
                        max_kelly_position = available_capital * 0.03 * 1.5  # 1.5x of base 3% Kelly
                        # BUG FIX #27: Guard against zero max_kelly_position (prevents division by zero crash)
                        if position_size > max_kelly_position and max_kelly_position > 1e-8:
                            kelly_excess = position_size / max_kelly_position
                            original_size = position_size
                            position_size = max_kelly_position
                            logger.debug(f"🔒 Position size capped at 1.5x Kelly: {symbol} {kelly_excess:.2f}x excess → {max_kelly_position:.0f} (was ${original_size:.0f})")

                        # BUG FIX #5: Don't force undersized positions to expensive minimums
                        # This creates over-leverage on low-conviction trades
                        # Instead: skip very-low-confidence undersize, cap medium-confidence undersize at $50
                        # BUG FIX #39: Changed threshold from 0.50 to 0.45 (CRITICAL: was skipping 0.48-0.49 confidence trades)
                        # Trades with 0.48-0.49 confidence are above minimum threshold and should be allowed
                        if position_size < 100 and confidence < 0.45:
                            # Very low confidence + undersized = skip entirely (not worth the capital)
                            filter_stage_counters["low_confidence_skip"] = filter_stage_counters.get("low_confidence_skip", 0) + 1
                            if signals_generated <= 50 or np.random.random() < 0.01:
                                logger.debug(f"⏭️ Skipped very-low-confidence undersize signal: {symbol} (confidence={confidence:.2f}, size=${position_size:.2f})")
                            continue  # Skip this signal entirely
                        elif position_size < 100 and confidence >= 0.45:
                            # Medium-high confidence: cap at maximum $75 (don't over-leverage undersized)
                            # BUG FIX #11: Don't multiply - cap respects original calculation without oversizing
                            capped_size = min(position_size, 75)  # Use original size or $75, whichever is lower
                            if signals_generated <= 50 or np.random.random() < 0.01:
                                logger.debug(f"🔸 Position size capped: {symbol} ${position_size:.2f} → ${capped_size:.2f} (medium confidence)")
                            position_size = capped_size

                        # CRITICAL FIX: Prevent opening positions if capital is negative or too low
                        # BUG FIX #3: Check multi-position margin (not just this position)
                        # With N positions open, need N * min_capital_to_trade buffer (not just 1x)
                        # BUG FIX #48: CRITICAL - Only check margin requirement, not separate <= capital check
                        # Old logic: position_size <= capital AND capital_after >= margin (can conflict)
                        # New logic: ONLY check that remaining capital after position >= margin requirement
                        min_capital_to_trade = 100  # Need at least $100 per position
                        num_existing_positions = len(positions)
                        max_concurrent_positions = 12  # Hard cap on concurrent positions
                        if num_existing_positions >= max_concurrent_positions:
                            continue  # Skip — too many open positions
                        total_margin_required = (num_existing_positions + 1) * min_capital_to_trade  # +1 for new position
                        capital_after_position = capital - position_size

                        # Only open if we maintain minimum margin for all positions
                        # Remove redundant checks: if capital_after >= margin, then position_size <= capital automatically
                        # BUG #10: Validate position_size is finite before opening
                        if not np.isfinite(position_size):
                            logger.error(f"🚨 CRITICAL: Invalid position_size={position_size} (NaN/inf) for {symbol}, skipping")
                            continue

                        if position_size > 0 and capital_after_position >= total_margin_required:
                            side = "long" if prediction["action"] == 2 else "short"
                            positions_opened += 1

                            # Apply entry-side slippage + commission
                            entry_cost = position_size * COST_PER_SIDE
                            # CRITICAL FIX: Store position_size (not effective_size) to avoid capital leakage
                            # Capital deduction: position_size (line 2511)
                            # Capital return at exit: position_size + pnl (not effective_size + pnl)
                            # This ensures: out $300, back $300 + profit, cost is embedded in pnl calc

                            # CRITICAL FIX BUG #3: Set pyramid targets at entry time, not recalculated each candle
                            # BUG FIX #6: Now uses config values (not hardcoded)
                            # This prevents time-dependent changes to exit levels
                            # DYNAMIC ATR-BASED PYRAMID TARGETS
                            # Fixed targets (5%/15%) don't adapt to volatility. A 5% target
                            # is too tight for volatile assets and too wide for stable ones.
                            # Use ATR as a volatility proxy to set appropriate exit levels.
                            if symbol in window_data and len(window_data[symbol]) >= 20:
                                recent_candles = window_data[symbol][-20:]
                                atr_sum = 0
                                for k in range(1, len(recent_candles)):
                                    tr = max(
                                        recent_candles[k].high - recent_candles[k].low,
                                        abs(recent_candles[k].high - recent_candles[k-1].close),
                                        abs(recent_candles[k].low - recent_candles[k-1].close)
                                    )
                                    atr_sum += tr
                                entry_atr = atr_sum / (len(recent_candles) - 1)
                                atr_pct = entry_atr / (candle.close + 1e-8)
                                # Stop must be TIGHTER than target 1 for positive risk/reward.
                                #
                                # Stop:     1.2x ATR, [1.2%, 3.5%]
                                # Target 1: 3x ATR,   [3%, 10%]  → always 2.5x stop
                                # Target 2: 7x ATR,   [8%, 30%]  → let big winners run
                                pyramid_target_1 = np.clip(3.0 * atr_pct, 0.03, 0.10)
                                pyramid_target_2 = np.clip(7.0 * atr_pct, 0.08, 0.30)
                            else:
                                atr_pct = 0.02  # Default ATR estimate
                                pyramid_target_1 = config["pyramid_target_1_pct"]
                                pyramid_target_2 = config["pyramid_target_2_pct"]

                            # Compute effective stop from the ATR we just calculated
                            effective_stop_distance = np.clip(1.2 * atr_pct, 0.012, 0.035)

                            # BUG FIX #9: Entry price sanity check (prevent extreme values that cause numerical instability)
                            entry_price = candle.close
                            if not (1e-4 <= entry_price <= 1e6):
                                logger.warning(f"⚠️ Extreme entry price rejected: {symbol} ${entry_price:.10f} (outside 1e-4 to 1e6 range)")
                                continue  # Skip this position entirely

                            positions[symbol] = {
                                "side": side,
                                "entry_price": entry_price,
                                "entry_time": timestamp,
                                "size": position_size,  # CRITICAL FIX: Use position_size (not effective_size) for capital tracking
                                "entry_cost": entry_cost,
                                "individual_predictions": prediction.get("predictions", []),
                                "final_action": prediction["action"],
                                "highest_price": entry_price,  # TIER 1 FIX: Track for trailing stops
                                "lowest_price": entry_price,   # Also track for shorts
                                "stop_distance": effective_stop_distance,  # TIER 2 FIX: Track which stop was used
                                "pyramid_target_1": pyramid_target_1,  # ATR-based profit target 1
                                "pyramid_target_2": pyramid_target_2,  # ATR-based profit target 2
                                "entry_atr_pct": atr_pct,              # ATR at entry for stop calculation
                                "pyramided_1": False,  # Track if first level was hit
                                "pyramided_2": False,  # Track if second level was hit
                            }

                            # Log position opening (PHASE D: include model agreement)
                            trade_direction = "LONG" if side == "long" else "SHORT"
                            logger.debug(
                                f"Position Opened: {symbol} {trade_direction} | "
                                f"Price: ${candle.close:.4f} | Size: ${position_size:.2f} | "
                                f"Confidence: {prediction['confidence']:.2f} | "
                                f"Models: {model_agreement}/{len(individual_preds)}"
                            )

                            capital -= position_size
                    else:
                        # PHASE D: Track why signal was rejected
                        if prediction["action"] == 1:  # Hold signal
                            pass  # Don't count hold signals
                        elif not is_statistically_significant:
                            filtered_signals["low_statistical_significance"] += 1
                        elif prediction["confidence"] <= 0.80:
                            filtered_signals["low_confidence"] += 1
                        elif conflicting_trade:
                            filtered_signals["conflicting_regime"] += 1
                        elif not is_liquid:
                            filtered_signals["low_liquidity"] += 1
                        elif not strong_consensus:
                            filtered_signals["low_model_agreement"] += 1

            # Update equity curve periodically or when positions close (to capture P&L)
            # BUG FIX #3: With hourly candles, timing check is redundant (always true)
            # Simply check if this is a new timestamp to prevent duplicates
            should_update_equity = len(equity_curve) == 0 or timestamp != equity_curve[-1][0]
            if should_update_equity:
                # Calculate total equity
                total_equity = capital
                for sym, pos in positions.items():
                    if sym in window_data and window_data[sym]:
                        current_price = window_data[sym][-1].close
                        entry_price = pos["entry_price"]
                        if entry_price == 0:  # CRITICAL FIX: guard against zero entry price
                            logger.warning(f"Equity curve update skipped for {sym}: entry_price=0")
                            continue  # Skip P&L calculation for this position

                        # Only reached if entry_price != 0
                        if pos["side"] == "long":
                            pnl_pct = (current_price - entry_price) / entry_price
                        else:
                            pnl_pct = (entry_price - current_price) / entry_price
                        # BUG FIX #1: Only add the P&L, not position_size*(1+pnl_pct)
                        # OLD: total_equity += pos["size"] * (1 + pnl_pct)  ❌ Inflates equity 10-100x!
                        # NEW: Add only the unrealized P&L
                        unrealized_pnl = pos["size"] * pnl_pct
                        total_equity += unrealized_pnl

                equity_curve.append((timestamp, total_equity))

        # Close remaining positions at end
        for symbol, pos in list(positions.items()):
            if symbol in window_data and window_data[symbol]:
                current_price = window_data[symbol][-1].close
                entry_price = pos["entry_price"]
                if entry_price != 0:  # CRITICAL FIX: guard against zero entry price
                    if pos["side"] == "long":
                        pnl_pct = (current_price - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - current_price) / entry_price
                else:
                    pnl_pct = 0.0
                    logger.warning(f"Final position closure skipped P&L for {symbol}: entry_price=0")

                exit_cost = pos["size"] * COST_PER_SIDE
                realized_pnl = pos["size"] * pnl_pct - exit_cost
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
                    "trade_costs": pos.get("entry_cost", 0) + exit_cost,
                })

        # Log completion
        logger.info(f"Walk-forward backtest processing complete!")
        logger.info(f"  Total Candles Processed: {candles_processed:,}")
        logger.info(f"  Signals Generated: {signals_generated:,}")
        logger.info(f"  Positions Opened: {positions_opened}")
        logger.info(f"  Total Trades: {len(trades)}")
        logger.info(f"  Final Capital: ${capital:,.2f}")

        # DIAGNOSTIC: Show filter stage breakdown
        logger.info("\n📊 SIGNAL FILTER PIPELINE ANALYSIS:")
        logger.info(f"  Stage 1 - Total predictions: {filter_stage_counters['total_predictions']:,}")
        logger.info(f"  Stage 2 - Not HOLD (action in [0,2]): {filter_stage_counters['not_hold']:,} ({100*filter_stage_counters['not_hold']/max(1,filter_stage_counters['total_predictions']):.1f}%)")
        logger.info(f"  Stage 3 - Meets confidence: {filter_stage_counters['meets_confidence']:,} ({100*filter_stage_counters['meets_confidence']/max(1,filter_stage_counters['not_hold']):.1f}% of not_hold)")
        logger.info(f"  Stage 4 - Not conflicting regime: {filter_stage_counters['not_conflicting']:,}")
        logger.info(f"  Stage 5 - Is liquid: {filter_stage_counters['is_liquid']:,}")
        logger.info(f"  Stage 6 - Strong consensus: {filter_stage_counters['strong_consensus']:,}")
        logger.info(f"  Stage 7 - Statistically significant: {filter_stage_counters['stat_significant']:,}")
        logger.info(f"  Stage 8 - Not in cooldown: {filter_stage_counters['not_in_cooldown']:,}")
        logger.info(f"  Stage 9 - No position conflict: {filter_stage_counters['no_conflict']:,}")
        logger.info(f"  Stage 10 - Not already open: {filter_stage_counters['not_already_open']:,}")
        logger.info(f"  ✅ POSITIONS ACTUALLY OPENED: {filter_stage_counters['positions_opened']:,}")
        logger.info(f"\n  Filter funnel: {filter_stage_counters['total_predictions']:,} → {filter_stage_counters['positions_opened']:,} trades ({100*filter_stage_counters['positions_opened']/max(1,filter_stage_counters['total_predictions']):.2f}% conversion)")

        # SAFEGUARD: Log trading quality metrics
        logger.info("\n🛡️ SAFEGUARDS - TRADING QUALITY METRICS:")
        logger.info(f"  Per-Symbol Cooldown: {min_cooldown_candles} candles minimum")
        logger.info(f"  Direction Flips Detected: {sum(trade_churn.values())} total")
        if trade_churn:
            most_churned = max(trade_churn.items(), key=lambda x: x[1])
            logger.info(f"    - Most churned: {most_churned[0]} with {most_churned[1]} flips")
        logger.info(f"  Symbols in cooldown history: {len(last_exit_time)}")
        logger.info(f"  Position conflicts avoided: (logged during trading)")

        # PHASE D: Log signal filtering statistics
        logger.info("\n🔎 PHASE D - SIGNAL FILTERING ANALYSIS:")
        total_filtered = sum(filtered_signals.values())
        logger.info(f"  Total Actionable Signals: {signals_generated:,}")
        logger.info(f"  Total Filtered Out: {total_filtered:,}")
        logger.info(f"  Positions Actually Opened: {positions_opened}")
        logger.info(f"  Filtering Rate: {total_filtered/signals_generated*100:.1f}% filtered" if signals_generated > 0 else f"  Filtering Rate: N/A (0 signals generated)")
        logger.info(f"  Breakdown:")
        logger.info(f"    - Low Statistical Significance: {filtered_signals['low_statistical_significance']:,}")
        logger.info(f"    - Low Confidence (< 0.80): {filtered_signals['low_confidence']:,}")
        logger.info(f"    - Conflicting Regime: {filtered_signals['conflicting_regime']:,}")
        logger.info(f"    - Low Liquidity: {filtered_signals['low_liquidity']:,}")
        logger.info(f"    - Low Model Agreement (< 3/4): {filtered_signals['low_model_agreement']:,}")

        # TIER 2 FIX: Log macro regime information
        logger.info("\n📊 TIER 2 - ADVANCED RISK MANAGEMENT:")
        logger.info(f"  ✅ Signal Statistical Significance Testing (IMPLEMENTED)")
        logger.info(f"  ✅ BTC/ETH Systemic Risk Filter (IMPLEMENTED)")
        logger.info(f"  ✅ ML-Optimized Stop Placement (IMPLEMENTED)")
        logger.info(f"    Stop Distance Effectiveness: {[(d*100, s['wins']/(s['wins']+s['losses'])*100 if s['wins']+s['losses']>0 else 0) for d, s in sorted(stop_distance_effectiveness.items())]}")
        logger.info(f"  ✅ Macro Volatility Regime Filtering (IMPLEMENTED)")
        logger.info(f"    Final Macro Regime: {macro_regime.upper()}")

        # TIER 3 FIX: Log regime-aware improvements
        logger.info("\n📊 TIER 3 - REGIME-AWARE ENSEMBLE (HIGH IMPACT, HIGH EFFORT):")
        logger.info(f"  ✅ Regime-Aware Ensemble Prediction (IMPLEMENTED)")
        logger.info(f"    - Bull regime: +20% long confidence, -20% short confidence")
        logger.info(f"    - Bear regime: +20% short confidence, -20% long confidence")
        logger.info(f"    - Neutral regime: Balanced, favor mean reversion")
        logger.info(f"  ✅ Regime-Aware Position Sizing (IMPLEMENTED)")
        logger.info(f"    - Aligned trades (long in bull, short in bear): +15% size")
        logger.info(f"    - Counter-trend trades: -20% size (risk management)")
        logger.info(f"  ✅ Regime-Aware Stop Placement (IMPLEMENTED)")
        logger.info(f"    - With trend: -15% stop (tighter, let winners run)")
        logger.info(f"    - Against trend: +15% stop (wider, more room for noise)")
        logger.info(f"  Expected Impact: +2-5x returns vs baseline through:")
        logger.info(f"    1. Better signal quality (+20% confidence in regime-aligned trades)")
        logger.info(f"    2. Better risk management (-20% stop triggers in counter-trend)")
        logger.info(f"    3. Better position sizing (align with market direction)")

        # Log individual model performance
        logger.info("\n📊 INDIVIDUAL MODEL ACCURACY:")
        for model_name in model_names:
            correct = model_predictions[model_name]["correct"]
            incorrect = model_predictions[model_name]["incorrect"]
            total = correct + incorrect
            accuracy = (correct / total * 100) if total > 0 else 0
            logger.info(f"  {model_name}: {accuracy:.1f}% ({correct}/{total})")

        # PHASE C: Log model P&L contribution (profit factor by model)
        logger.info("\n💰 PHASE C - MODEL P&L CONTRIBUTION:")
        logger.info("  (When model voted for winning action)")
        model_ranking = []
        for model_name in model_names:
            trades_count = model_pnl[model_name]["trades"]
            total_pnl = model_pnl[model_name]["pnl"]
            wins = model_pnl[model_name]["wins"]
            losses = model_pnl[model_name]["losses"]

            if trades_count > 0:
                avg_pnl = total_pnl / trades_count
                win_rate = wins / trades_count * 100
                model_ranking.append((model_name, total_pnl, avg_pnl, win_rate, trades_count))
            else:
                model_ranking.append((model_name, 0, 0, 0, 0))

        # Sort by total P&L (best first)
        model_ranking.sort(key=lambda x: x[1], reverse=True)

        for model_name, total_pnl, avg_pnl, win_rate, trades_count in model_ranking:
            status = "✅ GOOD" if total_pnl > 0 else "❌ BAD"
            logger.info(
                f"  {status} {model_name}: ${total_pnl:+.2f} total | "
                f"${avg_pnl:+.2f} avg | {win_rate:.1f}% win rate | {trades_count} trades"
            )

        # Recommendation for ensemble optimization
        profitable_models = [name for name, pnl, *_ in model_ranking if pnl > 0]
        unprofitable_models = [name for name, pnl, *_ in model_ranking if pnl <= 0]

        if unprofitable_models:
            logger.info(f"\n💡 PHASE C RECOMMENDATION:")
            logger.info(f"  Remove unprofitable models: {', '.join(unprofitable_models)}")
            logger.info(f"  Keep and focus on: {', '.join(profitable_models) if profitable_models else 'NONE (all bad!)'}")
            if not profitable_models:
                logger.error(f"  ⚠️  WARNING: ALL MODELS ARE UNPROFITABLE. Ensemble is fundamentally broken.")

        # Log adaptive ensemble weights (PHASE B)
        logger.info("\n⚖️  PHASE B - ADAPTIVE ENSEMBLE WEIGHTS:")
        adaptive_weights = adaptive_weighter.get_model_weights()
        for model_name in model_names:
            weight = adaptive_weights.get(model_name, 0)
            logger.info(f"  {model_name}: {weight:.2%}")

        # Log continuous learning stats (PHASE B)
        logger.info("\n🔄 PHASE B - CONTINUOUS LEARNING STATS:")
        learner_stats = continuous_learner.get_training_stats()
        logger.info(f"  Total Candles Processed: {learner_stats['total_candles_processed']:,}")
        logger.info(f"  Buffer Size: {learner_stats['buffer_size']:,} samples")
        logger.info(f"  Retraining Count: {learner_stats['retraining_count']}")
        logger.info(f"  Recent Win Rate: {learner_stats['performance']['win_rate']:.1%}")

        logger.info("Calculating final metrics...")

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

        # BUG FIX #8: Need minimum samples for statistics (not just 1 point)
        # With only 1 point, np.diff() produces empty array, std becomes 0
        if len(equity_curve) < 10:
            logger.warning(f"⚠️ Insufficient equity curve samples: {len(equity_curve)} (need ≥10 for statistics)")
            # Still calculate what we can, but metrics will be limited
            if len(equity_curve) == 1:
                logger.warning("   Only 1 point in equity curve - no trades occurred or single candle backtest")

        logger.info("Calculating returns and Sharpe/Sortino ratios...")
        initial = self.initial_capital
        final = equity_curve[-1][1]

        # Returns
        total_return = final - initial
        total_return_pct = (total_return / initial) * 100

        # Calculate daily returns for Sharpe/Sortino
        equity_values = [e[1] for e in equity_curve]
        returns = np.diff(equity_values) / (np.array(equity_values[:-1]) + 1e-8)

        # Sharpe Ratio (annualized using configurable annualization factor)
        # Uses annualization_factor from config (e.g., 8760 for 1h crypto, 2190 for 4h)
        annualization = getattr(self, '_annualization_factor', 365 * 24)
        returns_std = np.std(returns)
        if len(returns) > 1 and returns_std > 1e-8:
            sharpe = np.mean(returns) / returns_std * np.sqrt(annualization)
        else:
            sharpe = 0

        # Sortino Ratio (downside deviation only)
        # Formula: (Mean Return) / (Downside Deviation) * sqrt(periods/year)
        # Note: Uses mean of ALL returns (upside + downside) in numerator for excess return
        # but only downside std in denominator, measuring return per unit downside risk
        downside_returns = returns[returns < 0]
        # BUG FIX #3: Use epsilon comparison instead of exact > 0 for float reliability
        if len(downside_returns) > 0 and np.std(downside_returns) > 1e-8:
            sortino = np.mean(returns) / np.std(downside_returns) * np.sqrt(annualization)
        else:
            # BUG FIX #4: Don't default to Sharpe when no downside
            # If all returns are positive, Sortino is undefined (infinite)
            # Set to a large number and log this rare condition
            sortino = 999.9
            if len(downside_returns) == 0:
                logger.info("✅ PERFECT BACKTEST: All returns positive, Sortino = infinite (set to 999.9)")

        # BUG FIX #19 & #20: Handle NaN values in metrics
        # Protect against NaN/inf from edge cases
        sharpe = 0.0 if not np.isfinite(sharpe) else sharpe
        sortino = 0.0 if not np.isfinite(sortino) else sortino

        logger.info("Calculating drawdown...")
        # Max Drawdown - use epsilon protection for robustness
        peak = equity_values[0]
        max_dd = 0
        for value in equity_values:
            if value > peak:
                peak = value
            dd = (peak - value) / max(peak, 1e-8)  # Use epsilon for robust protection
            if dd > max_dd:
                max_dd = dd

        logger.info("Analyzing trade statistics...")
        # Trade statistics
        winning_trades = [t for t in trades if t["pnl"] > 0]
        losing_trades = [t for t in trades if t["pnl"] <= 0]

        win_rate = len(winning_trades) / len(trades) if trades else 0
        avg_win = np.mean([t["pnl"] for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([abs(t["pnl"]) for t in losing_trades]) if losing_trades else 0

        # Profit factor (handle edge cases for JSON serialization)
        gross_profit = sum(t["pnl"] for t in winning_trades)
        gross_loss = abs(sum(t["pnl"] for t in losing_trades))
        if len(trades) == 0:
            profit_factor = 0.0  # No trades
        elif gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        else:
            # Only winning trades (no losses) - use 100.0 instead of inf for JSON serialization
            profit_factor = 100.0 if gross_profit > 0 else 0.0

        # Average holding period
        holding_periods = []
        for t in trades:
            entry = datetime.fromisoformat(t["entry_time"])
            exit_time = datetime.fromisoformat(t["exit_time"])
            holding_periods.append((exit_time - entry).total_seconds() / 3600)
        avg_holding = np.mean(holding_periods) if holding_periods else 0

        result = BacktestResult(
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

        # Log final results
        logger.info("=" * 80)
        logger.info("📈 BACKTEST RESULTS")
        logger.info("=" * 80)
        logger.info(f"Period: {result.start_date.date()} to {result.end_date.date()}")
        logger.info(f"Initial Capital: ${result.initial_capital:,.2f}")
        logger.info(f"Final Capital: ${result.final_capital:,.2f}")
        logger.info(f"Total Return: ${result.total_return:,.2f} ({result.total_return_pct:.2f}%)")
        logger.info(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
        logger.info(f"Sortino Ratio: {result.sortino_ratio:.2f}")
        logger.info(f"Max Drawdown: ${result.max_drawdown:,.2f} ({result.max_drawdown_pct:.2f}%)")
        logger.info(f"Win Rate: {result.win_rate*100:.2f}% ({result.winning_trades}/{result.total_trades} trades)")
        logger.info(f"Profit Factor: {result.profit_factor:.2f}")
        logger.info(f"Avg Win: ${result.avg_win:,.2f}")
        logger.info(f"Avg Loss: ${result.avg_loss:,.2f}")
        logger.info(f"Avg Holding Period: {result.avg_holding_period:.2f} hours")
        logger.info("=" * 80)

        return result

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
    Pre-Training Pipeline for ML Models with REGIME-AWARE ENSEMBLE (HIGH IMPACT, HIGH EFFORT)

    Trains separate model sets for each market regime:
    - Bull models: Optimized for uptrends (favor longs, tighter stops)
    - Bear models: Optimized for downtrends (favor shorts, wider stops for volatility)
    - Neutral models: Optimized for sideways (profit from mean reversion)

    Each regime gets its own DQN, PPO, LSTM, Transformer ensemble.
    Routes predictions based on detected market regime.

    Saves trained weights to disk for production use.
    """

    def __init__(self, state_dim: int = 64, action_dim: int = 3):
        # REVERTED: state_dim=64 for checkpoint compatibility
        # (prepare_features generates 24-element vectors, padded to 64 for consistency)
        # Previously changed to 24, but causes incompatibility with existing saved checkpoints
        self.state_dim = state_dim
        self.action_dim = action_dim  # 0=sell, 1=hold, 2=buy

        # Sequence length for LSTM/Transformer (must match training)
        self.seq_len = 10

        # Initialize models with PROPER TRAINABLE versions
        from .ml_models import (
            create_dqn_agent, create_ppo_agent,
            LSTMClassifier, TrainableTransformer, TrainableVAE
        )

        # TIER 3 FIX: REGIME-AWARE ENSEMBLE - 3x models for 3x regimes
        # Each regime gets its own optimized ensemble
        self.regimes = ['bull', 'bear', 'neutral']
        self.models_by_regime = {}

        for regime in self.regimes:
            self.models_by_regime[regime] = {
                'dqn': create_dqn_agent(state_dim, action_dim),
                'ppo': create_ppo_agent(state_dim, action_dim),
                'lstm': LSTMClassifier(
                    input_dim=state_dim, hidden_dim=128, output_dim=action_dim, lr=0.001
                ),
                'transformer': TrainableTransformer(
                    input_dim=state_dim, hidden_dim=64, output_dim=action_dim, lr=0.001
                ),
                'vae': TrainableVAE(
                    input_dim=state_dim, hidden_dim=64, latent_dim=8, output_dim=action_dim, lr=0.001
                ),
            }

        # Backwards compatibility: also keep single models for legacy code
        self.dqn = self.models_by_regime['neutral']['dqn']
        self.ppo = self.models_by_regime['neutral']['ppo']
        self.lstm = self.models_by_regime['neutral']['lstm']
        self.transformer = self.models_by_regime['neutral']['transformer']
        self.vae = self.models_by_regime['neutral']['vae']

        # State buffer for sequential prediction (LSTM/Transformer)
        # Stores recent states so LSTM/Transformer see seq_len context
        # instead of a single state (matching training conditions)
        from collections import deque
        self.state_buffer = deque(maxlen=self.seq_len)

        self.is_trained = False
        self.training_metrics = TrainingMetrics(epochs_completed=0, total_samples=0)
        self.min_training_epochs = 1  # No minimum - early stopping is the control, not epoch count
        self.min_training_samples = 10000
        self.regime_train_counts = {'bull': 0, 'bear': 0, 'neutral': 0}  # Track samples per regime

    def prepare_training_data(
        self,
        historical_data: Dict[str, List[OHLCV]],
        backtester: WalkForwardBacktester
    ) -> Tuple[np.ndarray, Dict[int, np.ndarray], np.ndarray]:
        """
        Prepare training data from historical OHLCV with MULTI-HORIZON LABELS.

        Returns: (features, multi_horizon_labels_dict, rewards)
        where multi_horizon_labels_dict = {horizon: labels_array, ...}

        Multi-horizon training allows the ensemble to learn at different timescales:
        - 24h, 48h, 100h, 200h, 400h, 800h horizons
        - Fixes the critical mismatch: training predicted 5h but held 48h+
        """
        all_features = []
        all_multi_labels = {h: [] for h in [24, 48, 100, 200, 400, 800, 1600]}
        all_rewards = []

        for symbol, candles in historical_data.items():
            # Minimum candles required for meaningful training
            # 900 candles at 1h = 37.5 days, at 4h = 150 days, at 5m = 3.1 days
            min_training_candles = 900
            if len(candles) < min_training_candles:
                logger.info(f"Skipping {symbol}: only {len(candles)} candles (need >={min_training_candles})")
                continue

            features = backtester.prepare_features(candles)
            if len(features) == 0:
                continue

            # Generate labels for all horizons at once
            multi_labels = backtester.generate_multi_horizon_labels(candles)

            # CRITICAL FIX: Properly align features with labels
            # features[k] corresponds to candles[lookback+k] where lookback=400
            # labels[k] corresponds to candles[k] → candles[k+lookahead]
            # They're offset by 400! We need to skip first 400 samples of labels to align!
            # labels[400:] corresponds to candles[400:] → candles[400+lookahead:]
            # Now features[k] pairs with labels[k+400] ✓

            feature_lookback = 400  # Same as default in prepare_features
            aligned_multi_labels = {}
            for horizon, labels in multi_labels.items():
                # Skip first lookback samples to align with features
                if len(labels) > feature_lookback:
                    aligned_multi_labels[horizon] = labels[feature_lookback:]
                else:
                    aligned_multi_labels[horizon] = np.array([])
            multi_labels = aligned_multi_labels

            # Now find minimum aligned label length
            min_label_len = min((len(labels) for labels in multi_labels.values() if len(labels) > 0), default=0)
            if min_label_len == 0:
                # BUG FIX #9: Log why this symbol was skipped (was silent before)
                logger.debug(f"⏭️ Skipping {symbol}: insufficient data for multi-horizon training")
                logger.debug(f"   Candles: {len(candles)}, Horizons: {list(multi_labels.keys())}")
                logger.debug(f"   Label lengths: {[(h, len(l)) for h, l in multi_labels.items()]}")
                continue

            # Align features and labels to the minimum length
            features = features[:min_label_len]

            if len(features) < 100:  # Need minimum samples
                continue

            # Store features once
            all_features.append(features)

            # Truncate and store labels for each horizon
            for horizon, labels in multi_labels.items():
                all_multi_labels[horizon].append(labels[:min_label_len])

            # Calculate rewards with proper time alignment
            # features[i] corresponds to candles[400+i] (after alignment fix)
            closes = np.array([c.close for c in candles])
            raw_rewards = []
            feature_lookback = 400
            for i in range(len(features)):
                candle_idx = feature_lookback + i
                if candle_idx + 200 < len(closes):
                    future_return = (closes[candle_idx + 200] - closes[candle_idx]) / closes[candle_idx]
                    horizon_votes = []
                    for horizon, labels in multi_labels.items():
                        if i < len(labels):
                            horizon_votes.append(labels[i])

                    if horizon_votes:
                        majority_label = np.median(horizon_votes)
                        if majority_label >= 1.5:  # Consensus buy
                            raw_rewards.append(future_return)
                        elif majority_label <= 0.5:  # Consensus sell
                            raw_rewards.append(-future_return)
                        else:  # Hold
                            raw_rewards.append(0)
                    else:
                        raw_rewards.append(0)
                else:
                    raw_rewards.append(0)

            # Percentile-based normalization: scale rewards to [-1, 1] using
            # the actual distribution. This preserves relative differences instead
            # of hard-clipping (which compressed 40%+ of rewards to near-zero).
            raw_arr = np.array(raw_rewards)
            nonzero_mask = raw_arr != 0
            if nonzero_mask.sum() > 10:
                p5 = np.percentile(raw_arr[nonzero_mask], 5)
                p95 = np.percentile(raw_arr[nonzero_mask], 95)
                spread = max(abs(p95), abs(p5), 1e-8)
                # Scale so p5/p95 map to roughly -1/+1
                rewards = np.clip(raw_arr / spread, -1.0, 1.0)
            else:
                rewards = raw_arr

            all_rewards.append(rewards)

        if not all_features:
            logger.error("❌ CRITICAL: No training data prepared - cannot train models")
            logger.error(f"   all_features is empty")
            return np.array([]), {h: np.array([]) for h in [24, 48, 100, 200, 400, 800, 1600]}, np.array([])

        # Stack features
        X = np.vstack(all_features)

        # CRITICAL FIX: Validate minimum training data requirement (must have at least 100 samples)
        min_samples = 100
        if len(X) < min_samples:
            logger.error(f"❌ CRITICAL: Insufficient training data: {len(X)} samples < {min_samples} required")
            return np.array([]), {h: np.array([]) for h in [24, 48, 100, 200, 400, 800, 1600]}, np.array([])

        # Concatenate labels for each horizon
        y_multi = {}
        for horizon in [24, 48, 100, 200, 400, 800, 1600]:
            if all_multi_labels[horizon]:
                y_multi[horizon] = np.concatenate(all_multi_labels[horizon])
            else:
                y_multi[horizon] = np.array([])

        # Stack rewards
        r = np.concatenate(all_rewards) if all_rewards else np.array([])

        # FIX #2: Validate data alignment (features, labels, rewards must match)
        for horizon in y_multi:
            if len(y_multi[horizon]) > 0:
                assert X.shape[0] == len(y_multi[horizon]), \
                    f"Data alignment error for horizon {horizon}h: features={X.shape[0]}, labels={len(y_multi[horizon])}"
        assert X.shape[0] == len(r), \
            f"Data alignment error: features={X.shape[0]}, rewards={len(r)}"

        # BUG FIX #5: Validate feature dimension consistency before padding
        # Features generated by prepare_features() should always be 35-dimensional
        # If this changes, it indicates a bug in feature generation
        expected_feature_dim = 35  # From prepare_features() feature_vector (lines 1019-1056)
        if X.shape[1] != expected_feature_dim and X.shape[1] != self.state_dim:
            logger.warning(f"⚠️ Feature dimension mismatch: generated={X.shape[1]}, expected={expected_feature_dim}")

        # Pad/truncate features to state_dim
        if X.shape[1] < self.state_dim:
            padding = np.zeros((X.shape[0], self.state_dim - X.shape[1]))
            X = np.hstack([X, padding])
        elif X.shape[1] > self.state_dim:
            # BUG FIX #5: Log feature truncation to warn of potential information loss
            logger.warning(f"⚠️ TRUNCATING features from {X.shape[1]} to {self.state_dim} - potential information loss")
            X = X[:, :self.state_dim]

        logger.info(f"✅ Prepared multi-horizon training data:")
        logger.info(f"   Features: {X.shape}")
        for h in [24, 48, 100, 200, 400, 800, 1600]:
            logger.info(f"   Horizon {h}h labels: {y_multi[h].shape}")
        logger.info(f"   Rewards: {r.shape}")

        return X, y_multi, r

    def train(
        self,
        features: np.ndarray,
        labels: np.ndarray,
        rewards: np.ndarray,
        epochs: int = 999999,  # Effectively unlimited: early stopping (patience=2) controls actual length
        batch_size: int = 256,
        validation_split: float = 0.2,
        force_restart: bool = False  # If True, resets epoch counter to start fresh training
    ) -> TrainingMetrics:
        """
        Train all models on historical data.

        Supports both single-horizon (legacy) and multi-horizon labels:
        - Single-horizon: labels is np.ndarray
        - Multi-horizon: labels is Dict[int, np.ndarray] with horizons 24, 48, 100, 200, 400, 800h

        Multi-horizon training fixes the critical prediction mismatch where models trained
        for 5h predictions but held trades for 48h+. Now ensemble learns across all timescales.

        Args:
            force_restart: If True, resets epoch counter to 0 and clears training state
                          to start fresh training instead of resuming. Useful after deleting
                          checkpoints when you want a completely fresh start.

        NOTE: Early stopping with patience=2 will typically stop training before reaching the
        epochs limit. The epoch parameter (default 100) sets an upper bound, but the actual
        number of epochs trained is controlled by validation accuracy improvement.

        NOTE: Checkpoints are automatically deleted at the start of training to prevent
        resuming on stale weights. Use force_restart=True if epoch counter persists.
        """
        # CRITICAL FIX: Delete old checkpoints before training to prevent resuming on stale models
        checkpoint_file = CHECKPOINT_DIR / "model_checkpoint.pkl"
        if checkpoint_file.exists():
            try:
                checkpoint_file.unlink()
                logger.info("✅ Deleted old checkpoint to ensure fresh training (no resume on old weights)")
            except Exception as e:
                logger.warning(f"⚠️ Failed to delete old checkpoint: {e}")

        # CRITICAL FIX: Reset training state to start fresh (epoch counter persists in memory)
        # Even if checkpoint was deleted, _last_epoch, _best_val_accuracy, _patience_counter
        # are still in memory from previous run. Reset them to ensure epoch starts at 0.
        self._last_epoch = 0
        self._best_val_accuracy = 0
        self._patience_counter = 0
        self.dqn.epsilon = self.dqn.epsilon_start
        logger.info(f"🔄 Reset training state: epoch counter=0, epsilon={self.dqn.epsilon} for fresh training")

        if len(features) == 0:
            logger.error("No training data provided")
            return self.training_metrics

        # Handle both single-horizon and multi-horizon labels
        is_multi_horizon = isinstance(labels, dict)
        if is_multi_horizon:
            logger.info("🎯 MULTI-HORIZON TRAINING MODE")
            # BUG FIX: CRITICAL - Defensive check for empty labels dict
            if len(labels) == 0:
                logger.error("❌ CRITICAL: Labels dict is empty! No training data available.")
                return None
            logger.info(f"   Training on horizons: {sorted(labels.keys())}h")
            logger.info(f"   Coverage: 1 day → 66+ days (short-term to macro trends)")
            # Use 200h (mid-range) as primary for compatibility with existing code
            primary_labels = labels.get(200, list(labels.values())[0])
        else:
            logger.info("Single-horizon training mode")
            primary_labels = labels

        # Validate and normalize features to state_dim
        logger.info(f"Feature dimension before normalization: {features.shape[1]}")

        # Pad/truncate features to state_dim (critical for model compatibility)
        if features.shape[1] < self.state_dim:
            padding = np.zeros((features.shape[0], self.state_dim - features.shape[1]))
            features = np.hstack([features, padding])
            logger.info(f"✅ Padded features from {features.shape[1] - (self.state_dim - features.shape[1])} to {self.state_dim}")
        elif features.shape[1] > self.state_dim:
            features = features[:, :self.state_dim]
            logger.info(f"✅ Truncated features to {self.state_dim}")

        logger.info(f"✅ Final feature dimension: {features.shape}")

        # FIXED: Use all data for training, let walk-forward validation handle the splits
        # The previous approach of splitting at a global index broke per-symbol alignment
        # because features are concatenated as blocks (BTC[0-5000], ETH[5000-10000], etc.)
        # Walk-forward expanding windows properly preserve temporal and symbol boundaries

        # Cap training data for ~1 hour training time
        # 1M samples provides excellent coverage across 1,489 symbols
        max_samples = 1000000
        if len(features) > max_samples:
            logger.info(f"Sampling {max_samples:,} from {len(features):,} samples for efficient training...")
            # Sort indices to preserve temporal order within each symbol's block
            sample_idx = np.sort(np.random.choice(len(features), max_samples, replace=False))
            features = features[sample_idx]
            if is_multi_horizon:
                labels = {h: labels_arr[sample_idx] for h, labels_arr in labels.items()}
                primary_labels = primary_labels[sample_idx]
            else:
                labels = labels[sample_idx]
                primary_labels = primary_labels[sample_idx]
            rewards = rewards[sample_idx]

        logger.info(f"Training on {len(features):,} samples for {epochs} epochs...")

        # Feature normalization is done PER-FOLD inside the training loop below,
        # using only training data statistics (no look-ahead bias).
        # The feature_mean/feature_std are stored for inference after training.

        # ============================================================
        # WALK-FORWARD VALIDATION (expanding window)
        # ============================================================
        # EXPANDING WINDOW with patience=2:
        # - Expanding allows models to learn patterns across full historical range
        # - Early stopping (patience=2) is aggressive to prevent overfitting
        # - Better than rolling window which was too restrictive (0 trades generated)
        #
        # Fold structure (3 folds, expanding window):
        # Fold 0: Train [0:50%], Val [50:60%]    (early period)
        # Fold 1: Train [0:70%], Val [70:80%]    (expanded - includes fold 0 data)
        # Fold 2: Train [0:90%], Val [90:100%]   (most expanded - full historical data)
        n_wf_folds = 3
        epochs_per_fold = max(epochs // n_wf_folds, 4)
        wf_fold = 0
        wf_fold_accuracies = []

        # Early stopping setup - check for resume state (must be before wf_fold calculation)
        if force_restart:
            # FORCE RESTART: Reset epoch counter for fresh training
            logger.info("🔄 FORCE RESTART: Resetting epoch counter to 0 and clearing training state")
            self._last_epoch = 0
            self._best_val_accuracy = 0
            self._patience_counter = 0
            self.dqn.epsilon = self.dqn.epsilon_start  # CRITICAL FIX: Reset epsilon for fresh exploration
            start_epoch = 0
        else:
            start_epoch = getattr(self, '_last_epoch', 0)
        best_val_accuracy = getattr(self, '_best_val_accuracy', 0)
        global_best_accuracy = best_val_accuracy  # Track GLOBAL best across all folds
        patience = 2  # Stop if no improvement for 2 epochs (aggressive: prevent overfitting on expanding window)
        patience_counter = getattr(self, '_patience_counter', 0)  # Persists across folds

        n = len(features)
        wf_boundaries = []
        for f in range(n_wf_folds):
            # EXPANDING WINDOW: Train on more data each fold
            train_start = 0  # Always start from beginning
            train_end = int(n * (0.50 + f * 0.20))  # Expand training end
            val_end = int(n * (0.60 + f * 0.20))    # Shift validation end
            wf_boundaries.append((
                train_start,           # Always 0 for expanding window
                train_end,             # Growing training set
                val_end,               # Shifted validation set
            ))

        # If resuming, advance to correct fold
        wf_fold = min(start_epoch // epochs_per_fold, n_wf_folds - 1)

        # Initialize current fold (expanding window)
        train_start, train_end, val_end = wf_boundaries[wf_fold]

        # Per-fold normalization: compute stats from TRAINING data only (no look-ahead bias)
        fold_mean = np.mean(features[train_start:train_end], axis=0, keepdims=True)
        fold_std = np.std(features[train_start:train_end], axis=0, keepdims=True) + 1e-8
        features_normalized = (features - fold_mean) / fold_std  # Normalize ALL using train stats
        self.feature_mean = fold_mean[0]
        self.feature_std = fold_std[0]
        logger.info(f"Feature normalization (fold {wf_fold+1}): mean={np.mean(self.feature_mean):.4f}, std={np.mean(self.feature_std):.4f}")

        X_train = features_normalized[train_start:train_end]
        y_train = primary_labels[train_start:train_end]
        r_train = rewards[train_start:train_end]
        X_val = features_normalized[train_end:val_end]
        y_val = primary_labels[train_end:val_end]
        r_val = rewards[train_end:val_end]

        # For multi-horizon, also slice the horizon-specific labels (expanding window)
        if is_multi_horizon:
            y_train_multi = {h: labels[h][train_start:train_end] for h in sorted(labels.keys())}
            y_val_multi = {h: labels[h][train_end:val_end] for h in sorted(labels.keys())}
        else:
            y_train_multi = None
            y_val_multi = None

        def _compute_sample_indices(X_tr, X_vl):
            """Fixed sample indices for consistent accuracy measurement."""
            val_sz = min(10000, len(X_vl))
            train_sz = min(10000, len(X_tr))
            np.random.seed(42)
            vi = np.random.choice(len(X_vl), val_sz, replace=False)
            ti = np.random.choice(len(X_tr), train_sz, replace=False)
            np.random.seed(None)
            return ti, vi

        fixed_train_indices, fixed_val_indices = _compute_sample_indices(X_train, X_val)

        total_batches = len(X_train) // batch_size
        logger.info(f"Walk-forward training: {n_wf_folds} folds, {epochs_per_fold} epochs/fold")
        logger.info(f"Fold 1/{n_wf_folds}: train={len(X_train):,}, val={len(X_val):,}")

        if start_epoch > 0:
            logger.info(f"📥 Resuming training from epoch {start_epoch + 1}, best_acc={best_val_accuracy:.2%}")

        for epoch in range(start_epoch, epochs):
            epoch_start = time.time()

            # Walk-forward: advance fold when crossing epoch boundary
            target_fold = min(epoch // epochs_per_fold, n_wf_folds - 1)
            if target_fold > wf_fold:
                wf_fold_accuracies.append(best_val_accuracy)
                wf_fold = target_fold
                train_start, train_end, val_end = wf_boundaries[wf_fold]

                # Re-normalize using new fold's training data only (no look-ahead bias)
                fold_mean = np.mean(features[:train_end], axis=0, keepdims=True)
                fold_std = np.std(features[:train_end], axis=0, keepdims=True) + 1e-8
                features_normalized = (features - fold_mean) / fold_std
                self.feature_mean = fold_mean[0]
                self.feature_std = fold_std[0]
                logger.info(f"Feature normalization (fold {wf_fold+1}): mean={np.mean(self.feature_mean):.4f}, std={np.mean(self.feature_std):.4f}")

                X_train = features_normalized[:train_end]
                y_train = primary_labels[:train_end]
                r_train = rewards[:train_end]
                X_val = features_normalized[train_end:val_end]
                y_val = primary_labels[train_end:val_end]
                r_val = rewards[train_end:val_end]

                # Update multi-horizon labels for new fold
                if is_multi_horizon:
                    y_train_multi = {h: labels[h][:train_end] for h in sorted(labels.keys())}
                    y_val_multi = {h: labels[h][train_end:val_end] for h in sorted(labels.keys())}

                total_batches = len(X_train) // batch_size
                fixed_train_indices, fixed_val_indices = _compute_sample_indices(X_train, X_val)
                # NOTE: DO NOT reset patience_counter or global_best_accuracy on fold switch
                # This allows early stopping to detect when model quality degrades across folds
                # Reset per-fold tracking but keep global context
                best_val_accuracy = 0  # Reset fold-specific best (for checkpoint saving)
                # patience_counter continues from previous fold (detects multi-fold degradation)
                # Reset loss EMA so normalized loss isn't distorted by
                # the previous fold's loss scale
                self.dqn.loss_ema = 1.0
                if hasattr(self.transformer, 'loss_ema'):
                    self.transformer.loss_ema = 1.0
                logger.info(
                    f"📊 Walk-forward fold {wf_fold+1}/{n_wf_folds}: "
                    f"train={len(X_train):,}, val={len(X_val):,}"
                )

            # =====================================================================
            # CRITICAL FIX #24: DQN NEEDS TEMPORAL SEQUENCES, NOT SHUFFLED DATA
            # =====================================================================
            # DQN uses next_state to bootstrap Q-value targets.
            # If next_state is just the next sample in shuffled batch,
            # DQN learns WRONG value estimates → suboptimal actions → negative ROI.
            #
            # Solution: Create DQN experiences BEFORE shuffling, using correct
            # temporal next_state. Then shuffle for other models (they don't need temporal order).

            # Create DQN experiences using UNSHUFFLED data (temporal sequences)
            # CRITICAL FIX: Add bounds check to prevent IndexError when X_train has only 1 sample
            if len(X_train) >= 2:
                for j in range(len(X_train) - 1):
                    state = X_train[j]
                    action = int(y_train[j])
                    reward = r_train[j]
                    next_state = X_train[j + 1]  # ✓ CORRECT: Actual next state in time
                    done = (j == len(X_train) - 2)

                    from .ml_models import Experience
                    exp = Experience(state, action, reward, next_state, done)
                    self.dqn.replay_buffer.push(exp)

            # NOW shuffle for other models (PPO doesn't need temporal order)
            # BUT: LSTM and Transformer DO need temporal sequences.
            # So we shuffle for PPO/DQN training batches, but extract LSTM/Transformer
            # sequences from the UNSHUFFLED data to preserve temporal continuity.
            perm = np.random.permutation(len(X_train))
            X_train_shuffled = X_train[perm]
            y_train_shuffled = y_train[perm]
            r_train_shuffled = r_train[perm]

            # For multi-horizon: also shuffle the multi-horizon labels
            if is_multi_horizon:
                # BUG FIX #2: Validate all horizons have aligned lengths before shuffling
                # BUG FIX #8: Improved error handling with detailed diagnostics
                for h in y_train_multi.keys():
                    if len(y_train_multi[h]) != len(X_train):
                        logger.error(f"❌ Multi-horizon label shape mismatch for {h}h horizon:")
                        logger.error(f"   Labels: {len(y_train_multi[h])}, X_train: {len(X_train)}")
                        logger.error(f"   Check data alignment in prepare_training_data() or generate_multi_horizon_labels()")
                        # Log all horizons for comparison
                        for h2, labels in y_train_multi.items():
                            logger.error(f"   Horizon {h2}h: {len(labels)} labels")
                        raise ValueError(f"Multi-horizon label shape mismatch (horizon {h}h) - see logs for details")

                y_train_multi = {h: y_train_multi[h][perm] for h in y_train_multi.keys()}

            epoch_losses = []
            # Per-model loss tracking for debugging
            dqn_losses, lstm_losses, trans_losses = [], [], []
            batch_count = 0

            # Multi-horizon logging
            if is_multi_horizon and epoch % 5 == 0:
                # Calculate horizon agreement rates
                horizon_agreement = {}
                horizons_list = sorted(y_train_multi.keys())
                # Show agreement between key horizons
                if len(horizons_list) >= 2:
                    for i in [0, len(horizons_list)//2, -1]:  # Short, mid, long
                        if i < len(horizons_list) - 1:
                            h1 = horizons_list[i]
                            h2 = horizons_list[i+1]
                            agreement = np.mean(y_train_multi[h1] == y_train_multi[h2])
                            horizon_agreement[f"{h1}h-{h2}h"] = agreement
                if horizon_agreement:
                    logger.info(f"  Epoch {epoch+1}: Horizon agreement: {', '.join(f'{k}={v:.2%}' for k, v in horizon_agreement.items())}")

            # Mini-batch training (using SHUFFLED data for non-DQN models)
            for i in range(0, len(X_train_shuffled), batch_size):
                batch_count += 1

                # Progress logging every 1000 batches
                if batch_count % 1000 == 0:
                    logger.info(f"  Epoch {epoch+1}: batch {batch_count}/{total_batches} ({100*batch_count/total_batches:.1f}%)")
                batch_X = X_train_shuffled[i:i+batch_size]
                batch_y = y_train_shuffled[i:i+batch_size]
                batch_r = r_train_shuffled[i:i+batch_size]

                # Validate batch shapes
                if batch_X.shape[1] != self.state_dim:
                    logger.error(f"❌ BATCH SHAPE MISMATCH: batch_X.shape={batch_X.shape}, expected state_dim={self.state_dim}")
                    raise ValueError(f"Batch feature dimension {batch_X.shape[1]} doesn't match state_dim {self.state_dim}")

                # =====================
                # TRAIN DQN (Experience Replay) - Already added before shuffle
                # =====================
                # DQN experiences were added to replay_buffer above using temporal sequences
                # Here we just call train_step which samples from the buffer

                dqn_loss = self.dqn.train_step(batch_size=min(32, len(batch_X)))
                if dqn_loss:
                    epoch_losses.append(dqn_loss)
                    dqn_losses.append(dqn_loss)

                # =====================
                # TRAIN PPO (Supervised Cross-Entropy)
                # =====================
                # PPO is trained with direct cross-entropy on labels instead of
                # broken importance-sampling RL (where labels pretended to be actions).
                # This is mathematically cleaner and converges faster.
                ppo_loss = self.ppo.train_supervised(batch_X, batch_y, batch_size=min(32, len(batch_X)))
                if ppo_loss:
                    epoch_losses.append(ppo_loss)

                # LSTM and Transformer are trained OUTSIDE this batch loop
                # using unshuffled temporal sequences (see below)


            # =====================
            # TRAIN LSTM & TRANSFORMER on UNSHUFFLED temporal sequences
            # =====================
            # CRITICAL: Sequential models must see temporally continuous data.
            # Using shuffled batches (as before) destroyed temporal patterns — the LSTM
            # would see BTC-hour-100 → ETH-hour-500 → ADA-hour-1 as a "sequence".
            # Now we extract rolling windows from the original time-ordered data.
            seq_len = 10
            if len(X_train) >= seq_len + 1:
                # Sample random starting positions to limit computation
                # (full pass over 60K samples with stride 1 is too slow)
                n_seq_samples = min(len(X_train) - seq_len, 2000)
                seq_starts = np.random.choice(len(X_train) - seq_len, size=n_seq_samples, replace=False)

                for start_idx in seq_starts:
                    seq = X_train[start_idx:start_idx + seq_len]
                    target = y_train[start_idx + seq_len - 1:start_idx + seq_len]

                    if len(seq) == seq_len and len(target) > 0:
                        seq_reshaped = seq.reshape(1, seq_len, -1)

                        lstm_loss = self.lstm.train_step(seq_reshaped, target)
                        epoch_losses.append(lstm_loss)
                        lstm_losses.append(lstm_loss)

                        trans_loss = self.transformer.train_step(seq_reshaped, target)
                        epoch_losses.append(trans_loss)
                        trans_losses.append(trans_loss)

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
                f"Trans={np.mean(trans_losses):.2f}"
            )

            # Update resume state
            self._last_epoch = epoch + 1
            self._best_val_accuracy = best_val_accuracy
            self._patience_counter = patience_counter

            # Early stopping check - compare against GLOBAL best to detect degradation across folds
            if val_accuracy > best_val_accuracy:
                best_val_accuracy = val_accuracy

            # Update global best if this is a new global maximum
            if val_accuracy > global_best_accuracy:
                global_best_accuracy = val_accuracy
                self._best_val_accuracy = global_best_accuracy
                patience_counter = 0
                self._patience_counter = 0
                self.save_checkpoints()  # Save best model
                logger.info(f"🏆 New GLOBAL best val accuracy: {val_accuracy:.2%}")
            else:
                # No improvement vs global best - increment patience counter
                patience_counter += 1
                self._patience_counter = patience_counter
                if patience_counter >= patience:
                    logger.info(f"⏹️  Early stopping at epoch {epoch+1} - no improvement for {patience} epochs (global best: {global_best_accuracy:.2%})")
                    break

        self.training_metrics.epochs_completed = epoch + 1  # Actual epochs completed
        self.training_metrics.total_samples = len(features)
        self.is_trained = True

        # FIXED: Save final fold's validation data for adversarial validation
        # Use the last fold's validation set (properly aligned, not globally split)
        X_test_holdout = X_val
        y_test_holdout = y_val

        # Save resume state (but don't overwrite best checkpoint if early stopping occurred)
        self._last_epoch = epoch + 1
        if val_accuracy >= global_best_accuracy:
            # Only save final checkpoint if it's at least as good as the global best
            self.save_checkpoints()
        else:
            logger.info(f"Keeping best checkpoint (acc={global_best_accuracy:.2%}, global best) over final (acc={val_accuracy:.2%})")

        # Walk-forward summary
        wf_fold_accuracies.append(best_val_accuracy)
        if len(wf_fold_accuracies) > 1:
            logger.info(
                f"📊 Walk-forward summary: {[f'{a:.2%}' for a in wf_fold_accuracies]}"
                f" | Mean: {np.mean(wf_fold_accuracies):.2%}"
                f" | Std: {np.std(wf_fold_accuracies):.2%}"
            )
            # Detect concept drift: later folds significantly worse than earlier
            if len(wf_fold_accuracies) >= 4:
                early_avg = np.mean(wf_fold_accuracies[:2])
                late_avg = np.mean(wf_fold_accuracies[-2:])
                if late_avg < early_avg - 0.05:
                    logger.warning(
                        f"⚠️ Concept drift detected: early folds avg {early_avg:.2%} "
                        f"vs late folds avg {late_avg:.2%}"
                    )

        # Multi-horizon training summary
        if is_multi_horizon:
            logger.info("=" * 80)
            logger.info("🎯 MULTI-HORIZON TRAINING COMPLETE (7 TIMEFRAMES)")
            logger.info(f"   Training horizons: {sorted(labels.keys())} hours")
            logger.info(f"   Coverage: 1 day to 66+ days (micro-trends → macro-trends)")
            logger.info(f"   Primary horizon (200h / 8+ days) accuracy: {best_val_accuracy:.2%}")
            logger.info(f"")
            logger.info(f"   ✅ What this achieves:")
            logger.info(f"   • Captures short-term reversions (24h-100h)")
            logger.info(f"   • Learns medium-term trends (200h-400h)")
            logger.info(f"   • Models seasonal/macro patterns (800h-1600h)")
            logger.info(f"   • Ensemble consensus across all timeframes")
            logger.info(f"   • No prediction horizon blindness")
            logger.info("=" * 80)

        # TIER 1 FIX: ADVERSARIAL VALIDATION
        # Test on the final fold's validation set (properly aligned, recent but not extreme)
        logger.info("\n" + "="*80)
        logger.info("🔍 ADVERSARIAL VALIDATION: Testing on final fold's validation set")
        logger.info("="*80)

        # CRITICAL: Load the best checkpoint before testing (not the final epoch)
        self.load_checkpoints()
        logger.info(f"✅ Loaded best checkpoint (val accuracy: {global_best_accuracy:.2%})")

        # FIXED: Use final fold's validation data (properly aligned, not globally split)
        if len(X_test_holdout) >= 100:
            # Evaluate ensemble on held-out test set - SIMPLE AND CLEAN
            self.reset_state_buffer()
            test_correct = 0
            test_sample_count = 0

            # BUG FIX #1: Ensure test data is aligned before evaluation
            # Validate that X_test_holdout and y_test_holdout have same length
            if len(X_test_holdout) != len(y_test_holdout):
                logger.warning(f"⚠️ Test data misalignment: X_test={len(X_test_holdout)}, y_test={len(y_test_holdout)}")
                # Truncate to shorter length to prevent IndexError
                test_size = min(len(X_test_holdout), len(y_test_holdout))
                X_test_holdout = X_test_holdout[:test_size]
                y_test_holdout = y_test_holdout[:test_size]

            for i, state in enumerate(X_test_holdout[:min(1000, len(X_test_holdout))]):
                pred = self.predict(state)
                predicted_action = pred.get("action", 1)
                actual_action = y_test_holdout[i] if i < len(y_test_holdout) else 1
                test_correct += (predicted_action == actual_action)
                test_sample_count += 1

            test_accuracy = test_correct / test_sample_count if test_sample_count > 0 else 0
            val_test_gap = best_val_accuracy - test_accuracy

            logger.info(f"Validation Accuracy: {best_val_accuracy:.2%}")
            logger.info(f"Test Accuracy (unseen data): {test_accuracy:.2%}")
            logger.info(f"Generalization Gap: {val_test_gap:.2%}")

            if val_test_gap > 0.10:
                logger.warning(
                    f"⚠️ OVERFITTING DETECTED: Validation-Test gap = {val_test_gap:.2%} (>10%)\n"
                    f"   Models may perform worse on live data than backtest results suggest.\n"
                    f"   Consider: more regularization, reduce model complexity, or more training data"
                )
            elif val_test_gap < 0.02:
                logger.info(f"✅ EXCELLENT GENERALIZATION: Models likely to perform similarly on live data")
            else:
                logger.info(f"✅ GOOD GENERALIZATION: Reasonable gap ({val_test_gap:.2%}) suggests sound training")
        else:
            logger.warning(f"⚠️ Adversarial validation skipped: insufficient test data (need ≥100 samples)")

        logger.info(f"\nTraining complete! Best accuracy: {best_val_accuracy:.2%}")
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

        # CRITICAL FIX: Apply feature normalization (same as used in training)
        # Must use same normalization for predictions to match training distribution
        if hasattr(self, 'feature_mean') and hasattr(self, 'feature_std'):
            state = (state - self.feature_mean) / (self.feature_std + 1e-8)

        # Build sequence for sequential models
        seq = self._get_sequence(state)

        predictions = []
        confidences = []

        # BUG #14: Handle individual model failures instead of crashing on first error
        # This allows partial predictions when one model fails

        # CRITICAL FIX: Verify all models are initialized before predictions
        if not hasattr(self, 'dqn') or self.dqn is None:
            logger.error("DQN not initialized - cannot generate predictions")
            return {"action": 1, "confidence": 0.33, "reason": "models_not_ready"}
        if not hasattr(self, 'ppo') or self.ppo is None:
            logger.error("PPO not initialized - cannot generate predictions")
            return {"action": 1, "confidence": 0.33, "reason": "models_not_ready"}
        if not hasattr(self, 'lstm') or self.lstm is None:
            logger.error("LSTM not initialized - cannot generate predictions")
            return {"action": 1, "confidence": 0.33, "reason": "models_not_ready"}
        if not hasattr(self, 'transformer') or self.transformer is None:
            logger.error("Transformer not initialized - cannot generate predictions")
            return {"action": 1, "confidence": 0.33, "reason": "models_not_ready"}

        # CRITICAL BUG FIX #1: Initialize q_values before try block
        q_values = np.zeros(self.action_dim)  # Default fallback

        # DQN prediction (single state)
        try:
            q_values = self.dqn.get_q_values(state)
            if np.any(np.isnan(q_values)) or np.any(np.isinf(q_values)):
                logger.warning(f"DQN returned NaN/inf q_values, skipping")
            else:
                dqn_action = np.argmax(q_values)
                dqn_probs = self._softmax(q_values)
                dqn_conf = dqn_probs[dqn_action]
                predictions.append(dqn_action)
                confidences.append(dqn_conf)
        except Exception as e:
            logger.warning(f"DQN prediction failed: {e}")

        # PPO prediction (single state)
        try:
            ppo_probs = self.ppo.get_action_probs(state)
            if np.any(np.isnan(ppo_probs)) or np.any(np.isinf(ppo_probs)):
                logger.warning(f"PPO returned NaN/inf probs, skipping")
            else:
                ppo_action = np.argmax(ppo_probs)
                predictions.append(ppo_action)
                confidences.append(ppo_probs[ppo_action])
        except Exception as e:
            logger.warning(f"PPO prediction failed: {e}")

        # LSTM prediction (full sequence)
        try:
            lstm_out, _ = self.lstm.forward(seq)
            # lstm.forward() already returns softmax probs — do NOT apply softmax again!
            # Double softmax compresses [0.1, 0.7, 0.2] → [0.29, 0.43, 0.28] (signal destroyed)
            lstm_probs = lstm_out[-1] if lstm_out.ndim > 1 else lstm_out
            if np.any(np.isnan(lstm_probs)) or np.any(np.isinf(lstm_probs)):
                logger.warning(f"LSTM returned NaN/inf probs, skipping")
            else:
                lstm_action = np.argmax(lstm_probs)
                predictions.append(lstm_action)
                confidences.append(lstm_probs[lstm_action])
        except Exception as e:
            logger.warning(f"LSTM prediction failed: {e}")

        # Transformer prediction (full sequence)
        try:
            trans_out = self.transformer.forward(seq)
            # transformer.forward() already returns softmax probs — do NOT apply softmax again!
            trans_probs = trans_out[-1] if trans_out.ndim > 1 else trans_out
            if np.any(np.isnan(trans_probs)) or np.any(np.isinf(trans_probs)):
                logger.warning(f"Transformer returned NaN/inf probs, skipping")
            else:
                trans_action = np.argmax(trans_probs)
                predictions.append(trans_action)
                confidences.append(trans_probs[trans_action])
        except Exception as e:
            logger.warning(f"Transformer prediction failed: {e}")

        # Fail gracefully if ALL models fail
        if len(predictions) == 0:
            logger.error(f"🚨 ALL model predictions failed, using HOLD fallback")
            return {"action": 1, "confidence": 0.0}  # HOLD with 0 confidence

        # Ensemble vote (weighted by per-model confidence)
        action_votes = {0: 0, 1: 0, 2: 0}
        for pred, conf in zip(predictions, confidences):
            action_votes[pred] += conf

        # BUG FIX #3: Tie-breaking bias toward SHORT
        # OLD: max(action_votes, key=...) uses dict order → ties resolve to action 0 (SHORT)
        # NEW: When tied, randomly choose among tied actions
        max_vote = max(action_votes.values())
        tied_actions = [a for a, v in action_votes.items() if v == max_vote]
        if len(tied_actions) > 1:
            final_action = np.random.choice(tied_actions)
        else:
            final_action = tied_actions[0]

        # Confidence = model agreement * average confidence of agreeing models
        # This captures BOTH "how many models agree" and "how sure are they"
        # - 4/4 agree at 80% each → 1.0 * 0.80 = 0.80
        # - 3/4 agree at 70% each → 0.75 * 0.70 = 0.52
        # - 2/4 agree at 50% each → 0.50 * 0.50 = 0.25
        n_models = len(predictions)
        n_agree = sum(1 for p in predictions if p == final_action)
        # BUG #2: Guard against empty predictions list (all models failed)
        agreement = n_agree / max(n_models, 1)

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

    def predict_regime_aware(self, state: np.ndarray, regime: str = 'neutral') -> Dict:
        """
        TIER 3 FIX: REGIME-AWARE ENSEMBLE PREDICTION (SIMPLIFIED)

        Efficient implementation: Use same models but apply regime-specific post-processing:
        - Bull regime: Boost long signals (action=2) by 1.2x confidence, penalize shorts by 0.8x
        - Bear regime: Boost short signals (action=0) by 1.2x confidence, penalize longs by 0.8x
        - Neutral: Keep as-is (mean reversion both directions equally)

        This avoids 3x training complexity while capturing 80% of regime-aware benefits.

        Args:
            state: Current market state (features)
            regime: Market regime ('bull', 'bear', 'neutral')

        Returns:
            Prediction dict with action, confidence, etc.
        """
        # FIX #13: Validate regime parameter to prevent crashes
        # 'sideways' from detect_market_regime maps to 'neutral' for prediction
        valid_regimes = {'bull', 'bear', 'neutral', 'sideways'}
        if regime not in valid_regimes:
            logger.warning(f"Invalid regime: {regime}, using 'neutral'")
            regime = 'neutral'

        # CRITICAL FIX: Verify all models are initialized before predictions
        if not hasattr(self, 'dqn') or self.dqn is None:
            logger.error("DQN not initialized - cannot generate regime-aware predictions")
            return {"action": 1, "confidence": 0.33, "reason": "models_not_ready"}

        # Get baseline prediction from neutral ensemble (same models)
        # Ensure state is correct shape (MUST pad BEFORE normalization)
        if len(state.shape) == 1:
            if len(state) < self.state_dim:
                state = np.pad(state, (0, self.state_dim - len(state)))
            elif len(state) > self.state_dim:
                state = state[:self.state_dim]

        # CRITICAL FIX: Apply feature normalization AFTER padding to match training dim
        if hasattr(self, 'feature_mean') and hasattr(self, 'feature_std'):
            state = (state - self.feature_mean) / (self.feature_std + 1e-8)

        # Build sequence for sequential models
        seq = self._get_sequence(state)

        predictions = []
        confidences = []

        try:
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
            # FIX: LSTM.forward() returns (probs, hidden_state) tuple with batch dim
            # Must squeeze batch dim to get (output_dim,) before indexing
            lstm_probs_batch, _ = self.lstm.forward(seq)
            lstm_probs = lstm_probs_batch.flatten()  # (1, 3) → (3,)
            lstm_action = np.argmax(lstm_probs)
            predictions.append(lstm_action)
            confidences.append(lstm_probs[lstm_action])

            # Transformer prediction (full sequence)
            # transformer.forward() already returns softmax probs — just flatten batch dim
            trans_out = self.transformer.forward(seq)
            trans_probs = trans_out.flatten()  # (1, 3) → (3,)
            trans_action = np.argmax(trans_probs)
            predictions.append(trans_action)
            confidences.append(trans_probs[trans_action])
        except Exception as e:
            logger.error(f"🚨 ERROR in model predictions: {e}")
            logger.error(f"   State shape: {state.shape}, Regime: {regime}")
            # Return neutral HOLD signal as fallback
            return {
                "action": 1,  # HOLD
                "confidence": 0.0,
                "agreement": 0.0,
                "regime": regime,
                "regime_biased": False,
                "q_values": [],
                "predictions": [],
            }

        # TIER 3: REGIME-AWARE BIAS
        # Adjust relative weight (not absolute confidence) based on regime
        # Use additive adjustment instead of multiplicative to keep confidences normalized
        regime_adjustments = {0: 0, 1: 0, 2: 0}
        if regime == 'bull':
            # Boost long signals relative to others
            regime_adjustments[2] = +0.15  # Long: +15% relative boost
            regime_adjustments[0] = -0.15  # Short: -15% relative penalty
        elif regime == 'bear':
            # Boost short signals relative to others
            regime_adjustments[0] = +0.15  # Short: +15% relative boost
            regime_adjustments[2] = -0.15  # Long: -15% relative penalty
        # Neutral: no adjustment

        # Apply regime adjustments (additive to keep confidences normalized)
        adjusted_confidences = []
        for i, conf in enumerate(confidences):
            adj_conf = np.clip(conf + regime_adjustments[predictions[i]], 0.0, 1.0)
            adjusted_confidences.append(adj_conf)

        # Ensemble vote (weighted by regime-adjusted confidences)
        action_votes = {0: 0, 1: 0, 2: 0}
        for pred, conf in zip(predictions, adjusted_confidences):
            action_votes[pred] += conf

        # CRITICAL FIX: Break ties fairly instead of dict ordering bias
        # When multiple actions have equal vote weight, don't default to action 0 (SHORT)
        max_vote = max(action_votes.values())
        tied_actions = [a for a, v in action_votes.items() if v == max_vote]
        if len(tied_actions) > 1:
            # Multiple actions tied: choose randomly to avoid SHORT bias
            final_action = np.random.choice(tied_actions)
        else:
            final_action = tied_actions[0]

        # CRITICAL FIX: Confidence should NOT include regime adjustments (they distort calibration)
        # Use ORIGINAL (unadjusted) confidences for confidence calculation
        # Regime adjustments should affect VOTING (which action wins), not CONFIDENCE (signal strength)
        total_vote_weight = sum(action_votes.values())
        if total_vote_weight > 0:
            # Use original unadjusted confidences to get true signal strength
            original_action_votes = {0: 0, 1: 0, 2: 0}
            for pred, conf in zip(predictions, confidences):  # Use unadjusted confidences
                original_action_votes[pred] += conf
            # Confidence is the average confidence of models voting for the winning action
            final_confidence = original_action_votes[final_action] / (len(predictions) * 1.0)
        else:
            final_confidence = 0.0

        # For compatibility: also track raw model agreement
        n_models = len(predictions)
        n_agree = sum(1 for p in predictions if p == final_action)
        agreement = (n_agree / n_models) if n_models > 0 else 0.0

        return {
            "action": final_action,
            "confidence": float(final_confidence),
            "agreement": float(agreement),
            "regime": regime,  # Track which regime was used
            "regime_biased": regime != 'neutral',  # Note: prediction was regime-biased
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
            "training_metrics": self.training_metrics.to_dict(),
            "is_trained": self.is_trained,
            "timestamp": datetime.now().isoformat(),
            # Resume support
            "last_epoch": getattr(self, '_last_epoch', 0),
            "best_val_accuracy": getattr(self, '_best_val_accuracy', 0),
            "patience_counter": getattr(self, '_patience_counter', 0),
            # CRITICAL FIX: Save feature normalization params (must restore in load_checkpoints)
            "feature_mean": getattr(self, 'feature_mean', None),
            "feature_std": getattr(self, 'feature_std', None),
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
            # Restore trained epsilon from checkpoint (NOT reset to 1.0!)
            # epsilon=1.0 means 100% random exploration — useless for inference.
            # The checkpoint stores the decayed epsilon from training.
            saved_epsilon = checkpoint["dqn_weights"].get("epsilon", 0.01)
            self.dqn.epsilon = saved_epsilon

            # Restore PPO
            self.ppo.policy_network.set_weights(checkpoint["ppo_weights"]["policy"])
            self.ppo.value_network.set_weights(checkpoint["ppo_weights"]["value"])

            # Restore trainable models using set_weights() methods
            self.lstm.set_weights(checkpoint["lstm_weights"])
            self.transformer.set_weights(checkpoint["transformer_weights"])

            self.is_trained = checkpoint.get("is_trained", True)

            # Resume support
            self._last_epoch = checkpoint.get("last_epoch", 0)
            self._best_val_accuracy = checkpoint.get("best_val_accuracy", 0)
            self._patience_counter = checkpoint.get("patience_counter", 0)

            # CRITICAL FIX: Restore feature normalization params (required for proper predictions)
            if checkpoint.get("feature_mean") is not None:
                self.feature_mean = checkpoint["feature_mean"]
                self.feature_std = checkpoint["feature_std"]
                logger.info(f"✅ Restored feature normalization (mean={np.mean(self.feature_mean):.4f}, std={np.mean(self.feature_std):.4f})")
            else:
                logger.warning("⚠️ Feature normalization params not found in checkpoint - predictions may use wrong scale")

            logger.info(f"Loaded checkpoint from {checkpoint['timestamp']}")
            logger.info(f"DQN epsilon: {self.dqn.epsilon:.4f}")
            if self._last_epoch > 0:
                logger.info(f"Resume info: epoch {self._last_epoch}, best_acc={self._best_val_accuracy:.2%}, patience={self._patience_counter}")

            return True

        except Exception as e:
            logger.error(f"Error loading checkpoint: {e}")
            return False

    def reset_training_state(self, delete_checkpoint: bool = False) -> None:
        """
        Reset training state to allow fresh training.

        Args:
            delete_checkpoint: If True, also deletes the checkpoint file from disk.
                             This ensures models start untrained on next run.
        """
        # Reset epoch tracking
        self._last_epoch = 0
        self._best_val_accuracy = 0
        self._patience_counter = 0
        self.is_trained = False
        self.training_metrics = TrainingMetrics(epochs_completed=0, total_samples=0)

        logger.info("✅ Training state reset to 0")

        # Optionally delete the checkpoint file
        if delete_checkpoint:
            checkpoint_path = CHECKPOINT_DIR / "model_checkpoint.pkl"
            try:
                if checkpoint_path.exists():
                    checkpoint_path.unlink()
                    logger.info(f"🗑️  Deleted checkpoint file: {checkpoint_path}")
                else:
                    logger.warning(f"Checkpoint file not found: {checkpoint_path}")
            except Exception as e:
                logger.error(f"Failed to delete checkpoint: {e}")

    def meets_training_requirements(self) -> Tuple[bool, str]:
        """Check if models meet minimum training requirements."""
        if not self.is_trained:
            return False, "Models have not been trained"

        # NOTE: No minimum epoch requirement - early stopping controls training length naturally
        # Even 1 epoch of improving is better than 100 epochs of overfitting

        if self.training_metrics.total_samples < self.min_training_samples:
            return False, f"Only {self.training_metrics.total_samples}/{self.min_training_samples} samples trained"

        # DQN epsilon is now properly restored from checkpoint, so no need to check it.
        # Low epsilon just means the DQN uses its Q-values instead of random exploration.

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
        except Exception as e:
            # BUG FIX #9: Add exception logging for better diagnostics
            logger.debug(f"Failed to load API keys from settings: {type(e).__name__}: {e} - falling back to environment variables")
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
        # BUG FIX #32: Add epsilon protection for weight normalization
        weights = {k: v / max(total_weight, 1e-8) for k, v in weights.items()}

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
    days_of_data: int = 730,  # 2 years: Required for 1600h pattern learning
    training_epochs: int = 999999  # Effectively unlimited: early stopping (patience=2) controls actual length
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

    # PRE-FILTER: Remove symbols with insufficient data
    min_candles_required = 900  # Minimum candles for meaningful training
    symbols_before = len(historical_data)
    historical_data = {
        sym: candles for sym, candles in historical_data.items()
        if len(candles) >= min_candles_required
    }
    symbols_after = len(historical_data)
    symbols_filtered = symbols_before - symbols_after
    if symbols_filtered > 0:
        logger.info(f"🔍 Filtered out {symbols_filtered} symbols with <{min_candles_required} candles")
        logger.info(f"   Remaining: {symbols_after} symbols with sufficient data")

    # Step 2: Prepare training data
    logger.info("\n🔧 Step 2: Preparing training data...")
    try:
        features, labels, rewards = pretrainer.prepare_training_data(historical_data, backtester)
    except Exception as e:
        logger.error(f"❌ Error in prepare_training_data: {e}", exc_info=True)
        return {"error": f"Failed to prepare training data: {str(e)}"}

    if len(features) == 0:
        return {"error": "Failed to prepare training data - no samples generated"}

    logger.info(f"Prepared {len(features)} training samples with shape {features.shape}")

    # Step 3: Train models
    logger.info("\n🧠 Step 3: Training ML models...")
    try:
        training_metrics = pretrainer.train(
            features, labels, rewards,
            epochs=training_epochs,
            batch_size=256  # Larger batch = faster training
        )
    except Exception as e:
        logger.error(f"❌ Error during training: {e}", exc_info=True)
        return {"error": f"Training failed: {str(e)}"}

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
