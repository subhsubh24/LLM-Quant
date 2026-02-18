"""
Cryptocurrency market data service.
Uses multi-provider WebSocket for REAL-TIME prices (primary).
Providers: Coinbase -> Kraken -> Binance.US -> Binance Global
Falls back to CoinGecko API for symbols not available via WebSocket.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor
import httpx
import logging

from ..config import get_settings
from .crypto_ws import get_crypto_ws, LivePrice

logger = logging.getLogger(__name__)


@dataclass
class CryptoQuote:
    """Real-time cryptocurrency quote."""
    symbol: str
    name: str
    price: float
    change_24h: float
    change_percent_24h: float
    high_24h: float
    low_24h: float
    volume_24h: float
    market_cap: float
    market_cap_rank: int
    circulating_supply: float
    total_supply: Optional[float]
    ath: float  # All-time high
    ath_change_percent: float
    timestamp: datetime
    # Data source tracking
    is_live: bool = True  # True if from API, False if mock
    data_source: str = "coingecko"  # coingecko, mock
    data_age_seconds: float = 0.0  # Age since fetch

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        d['is_live'] = self.is_live
        d['data_source'] = self.data_source
        d['data_age_seconds'] = self.data_age_seconds
        return d


@dataclass
class CryptoNews:
    """Crypto news item."""
    id: str
    title: str
    description: str
    url: str
    source: str
    published: datetime
    currencies: List[str]

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['published'] = self.published.isoformat()
        return d


class CryptoMarketService:
    """Service for fetching cryptocurrency market data."""

    # 200+ cryptocurrencies to track (CoinGecko ID -> Symbol, Name)
    TOP_CRYPTOS = {
        # ===== TOP 10 - Blue Chips =====
        "bitcoin": ("BTC", "Bitcoin"),
        "ethereum": ("ETH", "Ethereum"),
        "binancecoin": ("BNB", "BNB"),
        "ripple": ("XRP", "XRP"),
        "solana": ("SOL", "Solana"),
        "cardano": ("ADA", "Cardano"),
        "dogecoin": ("DOGE", "Dogecoin"),
        "tron": ("TRX", "Tron"),
        "avalanche-2": ("AVAX", "Avalanche"),
        "chainlink": ("LINK", "Chainlink"),

        # ===== 11-25 - Major Altcoins =====
        "polkadot": ("DOT", "Polkadot"),
        "matic-network": ("MATIC", "Polygon"),
        "shiba-inu": ("SHIB", "Shiba Inu"),
        "the-open-network": ("TON", "Toncoin"),
        "litecoin": ("LTC", "Litecoin"),
        "bitcoin-cash": ("BCH", "Bitcoin Cash"),
        "uniswap": ("UNI", "Uniswap"),
        "cosmos": ("ATOM", "Cosmos"),
        "stellar": ("XLM", "Stellar"),
        "internet-computer": ("ICP", "Internet Computer"),
        "ethereum-classic": ("ETC", "Ethereum Classic"),
        "filecoin": ("FIL", "Filecoin"),
        "aptos": ("APT", "Aptos"),
        "near": ("NEAR", "NEAR Protocol"),
        "immutable-x": ("IMX", "Immutable X"),

        # ===== 26-50 - Mid-Cap Leaders =====
        "hedera-hashgraph": ("HBAR", "Hedera"),
        "optimism": ("OP", "Optimism"),
        "injective-protocol": ("INJ", "Injective"),
        "vechain": ("VET", "VeChain"),
        "maker": ("MKR", "Maker"),
        "arbitrum": ("ARB", "Arbitrum"),
        "the-graph": ("GRT", "The Graph"),
        "aave": ("AAVE", "Aave"),
        "algorand": ("ALGO", "Algorand"),
        "thorchain": ("RUNE", "THORChain"),
        "fantom": ("FTM", "Fantom"),
        "the-sandbox": ("SAND", "The Sandbox"),
        "decentraland": ("MANA", "Decentraland"),
        "axie-infinity": ("AXS", "Axie Infinity"),
        "havven": ("SNX", "Synthetix"),
        "lido-dao": ("LDO", "Lido DAO"),
        "curve-dao-token": ("CRV", "Curve DAO"),
        "elrond-erd-2": ("EGLD", "MultiversX"),
        "theta-token": ("THETA", "Theta Network"),
        "tezos": ("XTZ", "Tezos"),
        "flow": ("FLOW", "Flow"),
        "kava": ("KAVA", "Kava"),
        "neo": ("NEO", "NEO"),
        "iota": ("IOTA", "IOTA"),
        "zcash": ("ZEC", "Zcash"),

        # ===== 51-75 - Established Altcoins =====
        "pancakeswap-token": ("CAKE", "PancakeSwap"),
        "1inch": ("1INCH", "1inch"),
        "compound-governance-token": ("COMP", "Compound"),
        "enjincoin": ("ENJ", "Enjin Coin"),
        "basic-attention-token": ("BAT", "Basic Attention Token"),
        "celo": ("CELO", "Celo"),
        "0x": ("ZRX", "0x Protocol"),
        "yearn-finance": ("YFI", "yearn.finance"),
        "sushi": ("SUSHI", "SushiSwap"),
        "kusama": ("KSM", "Kusama"),
        "gmx": ("GMX", "GMX"),
        "dydx": ("DYDX", "dYdX"),
        "blockstack": ("STX", "Stacks"),
        "sui": ("SUI", "Sui"),
        "sei-network": ("SEI", "Sei"),
        "celestia": ("TIA", "Celestia"),
        "jupiter-exchange-solana": ("JUP", "Jupiter"),
        "pyth-network": ("PYTH", "Pyth Network"),
        "dogwifcoin": ("WIF", "dogwifhat"),
        "bonk": ("BONK", "Bonk"),
        "pepe": ("PEPE", "Pepe"),
        "floki": ("FLOKI", "FLOKI"),
        "render-token": ("RNDR", "Render"),
        "fetch-ai": ("FET", "Fetch.ai"),
        "singularitynet": ("AGIX", "SingularityNET"),

        # ===== 76-100 - AI & Computing =====
        "ocean-protocol": ("OCEAN", "Ocean Protocol"),
        "bittensor": ("TAO", "Bittensor"),
        "arweave": ("AR", "Arweave"),
        "helium": ("HNT", "Helium"),
        "quant-network": ("QNT", "Quant"),
        "akash-network": ("AKT", "Akash Network"),
        "oasis-network": ("ROSE", "Oasis Network"),
        "frax-share": ("FXS", "Frax Share"),
        "ssv-network": ("SSV", "SSV Network"),
        "rocket-pool": ("RPL", "Rocket Pool"),
        "pendle": ("PENDLE", "Pendle"),
        "blur": ("BLUR", "Blur"),
        "space-id": ("ID", "SPACE ID"),
        "open-campus": ("EDU", "Open Campus"),
        "magic": ("MAGIC", "Magic"),
        "liquity": ("LQTY", "Liquity"),
        "api3": ("API3", "API3"),
        "audius": ("AUDIO", "Audius"),
        "radicle": ("RAD", "Radicle"),
        "perpetual-protocol": ("PERP", "Perpetual Protocol"),
        "dodo": ("DODO", "DODO"),
        "alpha-finance": ("ALPHA", "Alpha Finance"),
        "tranchess": ("CHESS", "Tranchess"),
        "highstreet": ("HIGH", "Highstreet"),
        "voxies": ("VOXEL", "Voxies"),

        # ===== 101-125 - Gaming & Metaverse =====
        "gala": ("GALA", "Gala Games"),
        "illuvium": ("ILV", "Illuvium"),
        "superfarm": ("SUPER", "SuperVerse"),
        "yield-guild-games": ("YGG", "Yield Guild Games"),
        "vulcan-forged": ("PYR", "Vulcan Forged"),
        "wax": ("WAXP", "WAX"),
        "gods-unchained": ("GODS", "Gods Unchained"),
        "rarible": ("RARE", "Rarible"),
        "looksrare": ("LOOKS", "LooksRare"),
        "apecoin": ("APE", "ApeCoin"),
        "memecoin": ("MEME", "Memecoin"),
        "aidoge": ("AIDOGE", "ArbDoge AI"),
        "milady-meme-coin": ("LADYS", "Milady Meme"),
        "turbo": ("TURBO", "Turbo"),
        "bob": ("BOB", "BOB"),
        "toshi": ("TOSHI", "Toshi"),
        "brett": ("BRETT", "Brett"),
        "michi": ("MICHI", "Michi"),
        "popcat": ("POPCAT", "Popcat"),
        "neiro": ("NEIRO", "Neiro"),
        "goatseus-maximus": ("GOAT", "Goatseus Maximus"),
        "peanut-the-squirrel": ("PNUT", "Peanut the Squirrel"),
        "act-i-the-ai-prophecy": ("ACT", "Act I: The AI Prophecy"),
        "virtuals-protocol": ("VIRTUAL", "Virtuals Protocol"),

        # ===== 126-150 - DeFi & Infrastructure =====
        "jito-governance-token": ("JTO", "Jito"),
        "starknet": ("STRK", "Starknet"),
        "manta-network": ("MANTA", "Manta Network"),
        "dymension": ("DYM", "Dymension"),
        "altlayer": ("ALT", "AltLayer"),
        "portal-2": ("PORTAL", "Portal"),
        "pixels": ("PIXEL", "Pixels"),
        "aevo-exchange": ("AEVO", "Aevo"),
        "ethena": ("ENA", "Ethena"),
        "wormhole": ("W", "Wormhole"),
        "ondo-finance": ("ONDO", "Ondo Finance"),
        "ether-fi": ("ETHFI", "ether.fi"),
        "renzo": ("REZ", "Renzo"),
        "saga-2": ("SAGA", "Saga"),
        "omni-network": ("OMNI", "Omni Network"),
        "bouncebit": ("BB", "BounceBit"),
        "notcoin": ("NOT", "Notcoin"),
        "io-net": ("IO", "io.net"),
        "zksync": ("ZK", "zkSync"),
        "lista-dao": ("LISTA", "Lista DAO"),
        "layerzero": ("ZRO", "LayerZero"),
        "blast": ("BLAST", "Blast"),
        "scroll": ("SCR", "Scroll"),
        "eigenlayer": ("EIGEN", "EigenLayer"),
        "grass": ("GRASS", "Grass"),

        # ===== 151-175 - Emerging & High-Potential =====
        "morpho": ("MORPHO", "Morpho"),
        "magic-eden": ("ME", "Magic Eden"),
        "movement": ("MOVE", "Movement"),
        "usual": ("USUAL", "Usual"),
        "vana": ("VANA", "Vana"),
        "pudgy-penguins": ("PENGU", "Pudgy Penguins"),
        "bio-protocol": ("BIO", "BIO Protocol"),
        "anime": ("ANIME", "Anime"),
        "official-trump": ("TRUMP", "Official Trump"),
        "melania-meme": ("MELANIA", "Melania Meme"),
        "ai16z": ("AI16Z", "ai16z"),
        "fartcoin": ("FARTCOIN", "Fartcoin"),
        "griffain": ("GRIFFAIN", "Griffain"),
        "swarms": ("SWARMS", "Swarms"),
        "arc": ("ARC", "Arc"),
        "zerebro": ("ZEREBRO", "Zerebro"),
        "eliza": ("ELIZA", "Eliza"),
        "orca": ("ORCA", "Orca"),
        "max": ("MAX", "Max"),
        "moo-deng": ("MOODENG", "Moo Deng"),
        "spx6900": ("SPX", "SPX6900"),
        "gigachad-2": ("GIGACHAD", "GigaChad"),
        "giga-chad": ("GIGA", "Giga"),
        "ponke": ("PONKE", "Ponke"),
        "wen-4": ("WEN", "Wen"),

        # ===== 176-200 - Long-tail Opportunities =====
        "book-of-meme": ("BOME", "Book of Meme"),
        "slerf": ("SLERF", "Slerf"),
        "tremp": ("TREMP", "Tremp"),
        "dog-go-to-the-moon-runes": ("DOG", "DOG GO TO THE MOON"),
        "ordinals": ("ORDI", "Ordinals"),
        "sats-ordinals": ("SATS", "SATS Ordinals"),
        "rats": ("RATS", "RATS"),
        "pizza": ("PIZZA", "Pizza"),
        "wizard": ("WZRD", "Wizard"),
        "cat-in-a-dogs-world": ("MEW", "cat in a dogs world"),
        "myro": ("MYRO", "Myro"),
        "pork": ("PORK", "PiggyBank"),
        "beercoin": ("BEER", "Beercoin"),
        "jeo-boden": ("BODEN", "Jeo Boden"),
        "degen-base": ("DEGEN", "Degen"),
        "higher": ("HIGHER", "Higher"),
        "tybg": ("TYBG", "TYBG"),
        "friend-tech": ("FRIEND", "friend.tech"),
        "normie": ("NORMIE", "Normie"),
        "aerodrome-finance": ("AERO", "Aerodrome Finance"),
        "dino": ("DINO", "Dino"),
        "mog-coin": ("MOG", "Mog Coin"),
        "catgirl": ("CATGIRL", "Catgirl"),
        "happy": ("HAPPY", "Happy"),
    }

    # Symbol to CoinGecko ID mapping
    SYMBOL_TO_ID = {v[0]: k for k, v in TOP_CRYPTOS.items()}

    # Fallback mock data for 200+ coins - comprehensive price database
    MOCK_PRICES = {
        # ===== TOP 10 =====
        "BTC": {"price": 43250.50, "change": 2.5, "mcap": 847000000000, "rank": 1},
        "ETH": {"price": 2285.75, "change": 1.8, "mcap": 275000000000, "rank": 2},
        "BNB": {"price": 315.20, "change": -0.5, "mcap": 47000000000, "rank": 3},
        "XRP": {"price": 0.62, "change": 1.2, "mcap": 34000000000, "rank": 4},
        "SOL": {"price": 98.45, "change": 5.2, "mcap": 43000000000, "rank": 5},
        "ADA": {"price": 0.58, "change": -1.1, "mcap": 20000000000, "rank": 6},
        "DOGE": {"price": 0.082, "change": 3.5, "mcap": 12000000000, "rank": 7},
        "TRX": {"price": 0.11, "change": 0.8, "mcap": 10000000000, "rank": 8},
        "AVAX": {"price": 35.60, "change": 4.3, "mcap": 13000000000, "rank": 9},
        "LINK": {"price": 14.25, "change": 1.5, "mcap": 8500000000, "rank": 10},

        # ===== 11-25 =====
        "DOT": {"price": 7.85, "change": 2.1, "mcap": 10000000000, "rank": 11},
        "MATIC": {"price": 0.92, "change": -0.8, "mcap": 8500000000, "rank": 12},
        "SHIB": {"price": 0.000025, "change": 4.2, "mcap": 15000000000, "rank": 13},
        "TON": {"price": 5.45, "change": 2.3, "mcap": 13500000000, "rank": 14},
        "LTC": {"price": 72.30, "change": 0.5, "mcap": 5400000000, "rank": 15},
        "BCH": {"price": 245.80, "change": 1.2, "mcap": 4800000000, "rank": 16},
        "UNI": {"price": 6.45, "change": 2.8, "mcap": 4800000000, "rank": 17},
        "ATOM": {"price": 9.15, "change": 1.9, "mcap": 3500000000, "rank": 18},
        "XLM": {"price": 0.12, "change": 0.9, "mcap": 3400000000, "rank": 19},
        "ICP": {"price": 12.50, "change": -1.5, "mcap": 5800000000, "rank": 20},
        "ETC": {"price": 18.75, "change": 0.3, "mcap": 2700000000, "rank": 21},
        "FIL": {"price": 5.85, "change": 2.4, "mcap": 3100000000, "rank": 22},
        "APT": {"price": 9.25, "change": 3.1, "mcap": 4200000000, "rank": 23},
        "NEAR": {"price": 5.15, "change": 4.5, "mcap": 5400000000, "rank": 24},
        "IMX": {"price": 2.15, "change": 1.8, "mcap": 3200000000, "rank": 25},

        # ===== 26-50 =====
        "HBAR": {"price": 0.078, "change": 1.2, "mcap": 2800000000, "rank": 26},
        "OP": {"price": 2.85, "change": 3.2, "mcap": 3100000000, "rank": 27},
        "INJ": {"price": 28.50, "change": 5.8, "mcap": 2700000000, "rank": 28},
        "VET": {"price": 0.035, "change": 0.5, "mcap": 2500000000, "rank": 29},
        "MKR": {"price": 1450.00, "change": 1.1, "mcap": 1300000000, "rank": 30},
        "ARB": {"price": 1.25, "change": 2.2, "mcap": 2400000000, "rank": 31},
        "GRT": {"price": 0.185, "change": 3.5, "mcap": 1700000000, "rank": 32},
        "AAVE": {"price": 92.50, "change": 2.8, "mcap": 1400000000, "rank": 33},
        "ALGO": {"price": 0.185, "change": -0.8, "mcap": 1500000000, "rank": 34},
        "RUNE": {"price": 5.85, "change": 4.2, "mcap": 1950000000, "rank": 35},
        "FTM": {"price": 0.42, "change": 3.8, "mcap": 1180000000, "rank": 36},
        "SAND": {"price": 0.52, "change": 1.5, "mcap": 1100000000, "rank": 37},
        "MANA": {"price": 0.48, "change": 1.2, "mcap": 920000000, "rank": 38},
        "AXS": {"price": 7.85, "change": 2.5, "mcap": 950000000, "rank": 39},
        "SNX": {"price": 3.25, "change": 1.8, "mcap": 1050000000, "rank": 40},
        "LDO": {"price": 2.45, "change": 2.2, "mcap": 2200000000, "rank": 41},
        "CRV": {"price": 0.58, "change": 1.5, "mcap": 680000000, "rank": 42},
        "EGLD": {"price": 42.50, "change": 1.8, "mcap": 1100000000, "rank": 43},
        "THETA": {"price": 1.15, "change": 0.8, "mcap": 1150000000, "rank": 44},
        "XTZ": {"price": 0.95, "change": 0.5, "mcap": 940000000, "rank": 45},
        "FLOW": {"price": 0.85, "change": 1.2, "mcap": 900000000, "rank": 46},
        "KAVA": {"price": 0.72, "change": 1.5, "mcap": 520000000, "rank": 47},
        "NEO": {"price": 12.50, "change": 0.8, "mcap": 880000000, "rank": 48},
        "IOTA": {"price": 0.22, "change": 1.1, "mcap": 610000000, "rank": 49},
        "ZEC": {"price": 28.50, "change": 0.5, "mcap": 580000000, "rank": 50},

        # ===== 51-75 =====
        "CAKE": {"price": 2.85, "change": 2.2, "mcap": 720000000, "rank": 51},
        "1INCH": {"price": 0.38, "change": 1.8, "mcap": 420000000, "rank": 52},
        "COMP": {"price": 52.00, "change": 1.5, "mcap": 440000000, "rank": 53},
        "ENJ": {"price": 0.32, "change": 2.5, "mcap": 320000000, "rank": 54},
        "BAT": {"price": 0.25, "change": 0.8, "mcap": 375000000, "rank": 55},
        "CELO": {"price": 0.72, "change": 1.2, "mcap": 380000000, "rank": 56},
        "ZRX": {"price": 0.42, "change": 1.5, "mcap": 358000000, "rank": 57},
        "YFI": {"price": 7500.00, "change": 2.1, "mcap": 250000000, "rank": 58},
        "SUSHI": {"price": 1.15, "change": 2.8, "mcap": 280000000, "rank": 59},
        "KSM": {"price": 32.50, "change": 1.2, "mcap": 450000000, "rank": 60},
        "GMX": {"price": 35.00, "change": 3.5, "mcap": 320000000, "rank": 61},
        "DYDX": {"price": 2.85, "change": 4.2, "mcap": 580000000, "rank": 62},
        "STX": {"price": 1.85, "change": 5.2, "mcap": 2700000000, "rank": 63},
        "SUI": {"price": 1.45, "change": 6.5, "mcap": 1800000000, "rank": 64},
        "SEI": {"price": 0.65, "change": 4.8, "mcap": 1600000000, "rank": 65},
        "TIA": {"price": 12.50, "change": 7.2, "mcap": 2100000000, "rank": 66},
        "JUP": {"price": 0.95, "change": 5.5, "mcap": 1300000000, "rank": 67},
        "PYTH": {"price": 0.42, "change": 3.8, "mcap": 680000000, "rank": 68},
        "WIF": {"price": 2.85, "change": 12.5, "mcap": 2800000000, "rank": 69},
        "BONK": {"price": 0.000028, "change": 8.5, "mcap": 1900000000, "rank": 70},
        "PEPE": {"price": 0.0000012, "change": 15.2, "mcap": 5000000000, "rank": 71},
        "FLOKI": {"price": 0.00018, "change": 6.8, "mcap": 1700000000, "rank": 72},
        "RNDR": {"price": 7.85, "change": 4.5, "mcap": 3000000000, "rank": 73},
        "FET": {"price": 2.15, "change": 8.2, "mcap": 1800000000, "rank": 74},
        "AGIX": {"price": 0.85, "change": 6.5, "mcap": 1100000000, "rank": 75},

        # ===== 76-100 - AI & Computing =====
        "OCEAN": {"price": 0.92, "change": 4.2, "mcap": 520000000, "rank": 76},
        "TAO": {"price": 485.00, "change": 5.8, "mcap": 3400000000, "rank": 77},
        "AR": {"price": 28.50, "change": 3.2, "mcap": 1900000000, "rank": 78},
        "HNT": {"price": 8.50, "change": 2.5, "mcap": 1400000000, "rank": 79},
        "QNT": {"price": 105.00, "change": 1.8, "mcap": 1500000000, "rank": 80},
        "AKT": {"price": 3.85, "change": 4.5, "mcap": 850000000, "rank": 81},
        "ROSE": {"price": 0.12, "change": 2.1, "mcap": 720000000, "rank": 82},
        "FXS": {"price": 8.50, "change": 3.2, "mcap": 680000000, "rank": 83},
        "SSV": {"price": 32.00, "change": 2.8, "mcap": 320000000, "rank": 84},
        "RPL": {"price": 28.50, "change": 1.5, "mcap": 550000000, "rank": 85},
        "PENDLE": {"price": 5.25, "change": 6.2, "mcap": 820000000, "rank": 86},
        "BLUR": {"price": 0.42, "change": 3.8, "mcap": 580000000, "rank": 87},
        "ID": {"price": 0.55, "change": 2.5, "mcap": 450000000, "rank": 88},
        "EDU": {"price": 0.82, "change": 4.1, "mcap": 380000000, "rank": 89},
        "MAGIC": {"price": 0.95, "change": 5.5, "mcap": 320000000, "rank": 90},
        "LQTY": {"price": 1.25, "change": 2.2, "mcap": 120000000, "rank": 91},
        "API3": {"price": 2.15, "change": 1.8, "mcap": 280000000, "rank": 92},
        "AUDIO": {"price": 0.22, "change": 3.5, "mcap": 260000000, "rank": 93},
        "RAD": {"price": 1.85, "change": 2.8, "mcap": 180000000, "rank": 94},
        "PERP": {"price": 1.15, "change": 4.2, "mcap": 150000000, "rank": 95},
        "DODO": {"price": 0.18, "change": 2.5, "mcap": 110000000, "rank": 96},
        "ALPHA": {"price": 0.12, "change": 3.8, "mcap": 95000000, "rank": 97},
        "CHESS": {"price": 0.22, "change": 1.5, "mcap": 85000000, "rank": 98},
        "HIGH": {"price": 1.85, "change": 4.5, "mcap": 180000000, "rank": 99},
        "VOXEL": {"price": 0.25, "change": 2.2, "mcap": 75000000, "rank": 100},

        # ===== 101-125 - Gaming & Metaverse =====
        "GALA": {"price": 0.045, "change": 5.2, "mcap": 1500000000, "rank": 101},
        "ILV": {"price": 85.00, "change": 3.8, "mcap": 580000000, "rank": 102},
        "SUPER": {"price": 1.25, "change": 6.5, "mcap": 920000000, "rank": 103},
        "YGG": {"price": 0.75, "change": 4.2, "mcap": 280000000, "rank": 104},
        "PYR": {"price": 5.50, "change": 2.8, "mcap": 180000000, "rank": 105},
        "WAXP": {"price": 0.065, "change": 1.5, "mcap": 280000000, "rank": 106},
        "GODS": {"price": 0.32, "change": 3.2, "mcap": 150000000, "rank": 107},
        "RARE": {"price": 0.15, "change": 2.5, "mcap": 120000000, "rank": 108},
        "LOOKS": {"price": 0.085, "change": 4.8, "mcap": 85000000, "rank": 109},
        "APE": {"price": 1.45, "change": 3.5, "mcap": 850000000, "rank": 110},
        "MEME": {"price": 0.025, "change": 8.5, "mcap": 450000000, "rank": 111},
        "AIDOGE": {"price": 0.0000001, "change": 12.5, "mcap": 180000000, "rank": 112},
        "LADYS": {"price": 0.00000015, "change": 15.2, "mcap": 120000000, "rank": 113},
        "TURBO": {"price": 0.008, "change": 18.5, "mcap": 580000000, "rank": 114},
        "BOB": {"price": 0.00025, "change": 7.5, "mcap": 85000000, "rank": 115},
        "TOSHI": {"price": 0.00085, "change": 9.2, "mcap": 350000000, "rank": 116},
        "BRETT": {"price": 0.12, "change": 22.5, "mcap": 1200000000, "rank": 117},
        "MICHI": {"price": 0.15, "change": 11.8, "mcap": 150000000, "rank": 118},
        "POPCAT": {"price": 0.85, "change": 16.5, "mcap": 820000000, "rank": 119},
        "NEIRO": {"price": 0.0012, "change": 25.2, "mcap": 520000000, "rank": 120},
        "GOAT": {"price": 0.45, "change": 35.5, "mcap": 450000000, "rank": 121},
        "PNUT": {"price": 0.65, "change": 45.2, "mcap": 650000000, "rank": 122},
        "ACT": {"price": 0.35, "change": 28.5, "mcap": 320000000, "rank": 123},
        "VIRTUAL": {"price": 2.85, "change": 18.2, "mcap": 2800000000, "rank": 124},

        # ===== 126-150 - DeFi & Infrastructure =====
        "JTO": {"price": 3.25, "change": 4.5, "mcap": 420000000, "rank": 126},
        "STRK": {"price": 0.85, "change": 5.2, "mcap": 1200000000, "rank": 127},
        "MANTA": {"price": 1.45, "change": 3.8, "mcap": 580000000, "rank": 128},
        "DYM": {"price": 2.85, "change": 6.5, "mcap": 450000000, "rank": 129},
        "ALT": {"price": 0.18, "change": 4.2, "mcap": 280000000, "rank": 130},
        "PORTAL": {"price": 0.45, "change": 5.8, "mcap": 180000000, "rank": 131},
        "PIXEL": {"price": 0.35, "change": 7.2, "mcap": 320000000, "rank": 132},
        "AEVO": {"price": 0.85, "change": 3.5, "mcap": 420000000, "rank": 133},
        "ENA": {"price": 0.65, "change": 8.5, "mcap": 1800000000, "rank": 134},
        "W": {"price": 0.32, "change": 4.8, "mcap": 580000000, "rank": 135},
        "ONDO": {"price": 1.25, "change": 6.2, "mcap": 1500000000, "rank": 136},
        "ETHFI": {"price": 2.15, "change": 5.5, "mcap": 650000000, "rank": 137},
        "REZ": {"price": 0.085, "change": 4.2, "mcap": 85000000, "rank": 138},
        "SAGA": {"price": 1.85, "change": 3.8, "mcap": 280000000, "rank": 139},
        "OMNI": {"price": 12.50, "change": 5.2, "mcap": 180000000, "rank": 140},
        "BB": {"price": 0.45, "change": 6.8, "mcap": 220000000, "rank": 141},
        "NOT": {"price": 0.012, "change": 12.5, "mcap": 1200000000, "rank": 142},
        "IO": {"price": 2.85, "change": 8.2, "mcap": 450000000, "rank": 143},
        "ZK": {"price": 0.18, "change": 5.5, "mcap": 650000000, "rank": 144},
        "LISTA": {"price": 0.42, "change": 4.5, "mcap": 180000000, "rank": 145},
        "ZRO": {"price": 4.25, "change": 3.2, "mcap": 520000000, "rank": 146},
        "BLAST": {"price": 0.015, "change": 6.8, "mcap": 280000000, "rank": 147},
        "SCR": {"price": 0.85, "change": 7.5, "mcap": 150000000, "rank": 148},
        "EIGEN": {"price": 3.50, "change": 4.2, "mcap": 650000000, "rank": 149},
        "GRASS": {"price": 2.15, "change": 15.5, "mcap": 520000000, "rank": 150},

        # ===== 151-175 - Emerging & High-Potential =====
        "MORPHO": {"price": 2.85, "change": 8.5, "mcap": 850000000, "rank": 151},
        "ME": {"price": 3.50, "change": 12.2, "mcap": 1500000000, "rank": 152},
        "MOVE": {"price": 0.85, "change": 18.5, "mcap": 1800000000, "rank": 153},
        "USUAL": {"price": 1.25, "change": 22.5, "mcap": 450000000, "rank": 154},
        "VANA": {"price": 15.50, "change": 28.2, "mcap": 280000000, "rank": 155},
        "PENGU": {"price": 0.032, "change": 35.5, "mcap": 2100000000, "rank": 156},
        "BIO": {"price": 0.65, "change": 25.8, "mcap": 850000000, "rank": 157},
        "ANIME": {"price": 0.085, "change": 42.5, "mcap": 520000000, "rank": 158},
        "TRUMP": {"price": 35.00, "change": 55.2, "mcap": 7000000000, "rank": 159},
        "MELANIA": {"price": 4.50, "change": 125.5, "mcap": 850000000, "rank": 160},
        "AI16Z": {"price": 1.25, "change": 45.2, "mcap": 1200000000, "rank": 161},
        "FARTCOIN": {"price": 0.85, "change": 35.8, "mcap": 850000000, "rank": 162},
        "GRIFFAIN": {"price": 0.35, "change": 28.5, "mcap": 350000000, "rank": 163},
        "SWARMS": {"price": 0.25, "change": 65.2, "mcap": 250000000, "rank": 164},
        "ARC": {"price": 0.42, "change": 32.5, "mcap": 420000000, "rank": 165},
        "ZEREBRO": {"price": 0.55, "change": 48.2, "mcap": 550000000, "rank": 166},
        "ELIZA": {"price": 0.12, "change": 55.5, "mcap": 120000000, "rank": 167},
        "ORCA": {"price": 4.25, "change": 8.5, "mcap": 180000000, "rank": 168},
        "MAX": {"price": 0.0025, "change": 22.2, "mcap": 85000000, "rank": 169},
        "MOODENG": {"price": 0.25, "change": 18.5, "mcap": 250000000, "rank": 170},
        "SPX": {"price": 0.85, "change": 12.8, "mcap": 780000000, "rank": 171},
        "GIGACHAD": {"price": 0.085, "change": 35.5, "mcap": 85000000, "rank": 172},
        "GIGA": {"price": 0.045, "change": 28.2, "mcap": 45000000, "rank": 173},
        "PONKE": {"price": 0.55, "change": 15.5, "mcap": 550000000, "rank": 174},
        "WEN": {"price": 0.00012, "change": 8.5, "mcap": 120000000, "rank": 175},

        # ===== 176-200 - Long-tail Opportunities =====
        "BOME": {"price": 0.012, "change": 22.5, "mcap": 850000000, "rank": 176},
        "SLERF": {"price": 0.35, "change": 18.2, "mcap": 350000000, "rank": 177},
        "TREMP": {"price": 0.45, "change": 32.5, "mcap": 45000000, "rank": 178},
        "DOG": {"price": 0.0085, "change": 15.8, "mcap": 580000000, "rank": 179},
        "ORDI": {"price": 35.00, "change": 8.5, "mcap": 750000000, "rank": 180},
        "SATS": {"price": 0.00000045, "change": 12.2, "mcap": 850000000, "rank": 181},
        "RATS": {"price": 0.00012, "change": 25.5, "mcap": 120000000, "rank": 182},
        "PIZZA": {"price": 0.00085, "change": 18.8, "mcap": 85000000, "rank": 183},
        "WZRD": {"price": 0.15, "change": 8.5, "mcap": 15000000, "rank": 184},
        "MEW": {"price": 0.0085, "change": 35.2, "mcap": 850000000, "rank": 185},
        "MYRO": {"price": 0.12, "change": 22.5, "mcap": 120000000, "rank": 186},
        "PORK": {"price": 0.00000025, "change": 45.8, "mcap": 25000000, "rank": 187},
        "BEER": {"price": 0.00035, "change": 28.2, "mcap": 35000000, "rank": 188},
        "BODEN": {"price": 0.085, "change": 35.5, "mcap": 85000000, "rank": 189},
        "DEGEN": {"price": 0.012, "change": 18.2, "mcap": 320000000, "rank": 190},
        "HIGHER": {"price": 0.025, "change": 22.5, "mcap": 25000000, "rank": 191},
        "TYBG": {"price": 0.00015, "change": 15.8, "mcap": 15000000, "rank": 192},
        "FRIEND": {"price": 0.85, "change": 12.2, "mcap": 85000000, "rank": 193},
        "NORMIE": {"price": 0.012, "change": 8.5, "mcap": 12000000, "rank": 194},
        "AERO": {"price": 1.85, "change": 6.2, "mcap": 850000000, "rank": 195},
        "DINO": {"price": 0.0085, "change": 18.5, "mcap": 8500000, "rank": 196},
        "MOG": {"price": 0.0000025, "change": 25.2, "mcap": 580000000, "rank": 197},
        "CATGIRL": {"price": 0.0000001, "change": 35.5, "mcap": 85000000, "rank": 198},
        "HAPPY": {"price": 0.00015, "change": 12.8, "mcap": 15000000, "rank": 199},
    }

    def __init__(self):
        self.settings = get_settings()
        self.cache: Dict[str, Any] = {}
        self.cache_ttl = 120  # seconds - for CoinGecko fallback (2 min to avoid rate limits)
        self.base_url = "https://api.coingecko.com/api/v3"
        self.use_mock_fallback = False  # DISABLE mock fallback - error on API failure
        self._last_batch_fetch: Optional[datetime] = None
        self._batch_cache: Dict[str, CryptoQuote] = {}  # Cache for CoinGecko fallback
        self._batch_cache_ttl = 120  # seconds (2 min - CoinGecko free tier is ~10 req/min)
        self._min_api_interval = 10  # Minimum seconds between CoinGecko API calls
        # Multi-provider WebSocket is the PRIMARY data source for truly live prices
        # Tries: Coinbase -> Kraken -> Binance.US -> Binance Global
        self._crypto_ws = get_crypto_ws()

    async def get_quote(self, symbol: str) -> Optional[CryptoQuote]:
        """
        Get real-time quote for a cryptocurrency.

        PRIMARY: Multi-provider WebSocket (truly live, sub-second updates)
        FALLBACK: Batch cache from CoinGecko (no individual API calls)
        """
        symbol = symbol.upper()

        # PRIMARY SOURCE: Multi-provider WebSocket (truly live data)
        if self._crypto_ws.is_connected:
            live_price = self._crypto_ws.get_price(symbol)
            if live_price:
                return self._live_price_to_quote(live_price)

        # FALLBACK 1: Check batch cache (from get_quotes_batch)
        # This prevents individual API calls that cause rate limits
        if symbol in self._batch_cache and self._last_batch_fetch:
            age = (datetime.now() - self._last_batch_fetch).total_seconds()
            if age < self._batch_cache_ttl:
                quote = self._batch_cache[symbol]
                quote.data_age_seconds = age
                return quote

        # FALLBACK 2: Check individual cache
        cache_key = f"crypto_quote_{symbol}"
        cached = self._get_cached_with_age(cache_key)
        if cached:
            quote, age_seconds = cached
            quote.data_age_seconds = age_seconds
            return quote

        # FALLBACK 3: Return from batch cache even if slightly stale (up to 5 min)
        # This prevents hammering the API with individual requests
        if symbol in self._batch_cache:
            quote = self._batch_cache[symbol]
            if self._last_batch_fetch:
                age = (datetime.now() - self._last_batch_fetch).total_seconds()
                if age < 300:  # Accept up to 5 min old data
                    quote.data_age_seconds = age
                    logger.debug(f"Using stale cache for {symbol} ({age:.0f}s old)")
                    return quote

        # DON'T make individual API calls - they cause rate limits
        # The batch fetch in the scan loop will refresh the cache
        logger.debug(f"No cached data for {symbol} - waiting for next batch refresh")
        return None

    async def get_quotes_batch(self, symbols: List[str]) -> Dict[str, CryptoQuote]:
        """
        Get quotes for multiple cryptocurrencies.

        PRIMARY: Multi-provider WebSocket (truly live, sub-second updates)
        FALLBACK: CoinGecko REST API (for symbols not available from WebSocket)

        Combines both sources to maximize coverage.
        """
        quotes = {}
        symbols = [s.upper() for s in symbols]
        missing_symbols = []

        # PRIMARY SOURCE: Multi-provider WebSocket (truly live data)
        if self._crypto_ws.is_connected:
            for symbol in symbols:
                live_price = self._crypto_ws.get_price(symbol)
                if live_price:
                    quotes[symbol] = self._live_price_to_quote(live_price)
                else:
                    missing_symbols.append(symbol)

            if quotes:
                logger.debug(f"📊 LIVE prices from WebSocket: {len(quotes)}/{len(symbols)} symbols")

                # If we got all symbols, return immediately
                if not missing_symbols:
                    return quotes

                # Otherwise, fetch missing symbols from CoinGecko
                logger.debug(f"Fetching {len(missing_symbols)} missing symbols from CoinGecko")
        else:
            # WebSocket not connected - all symbols need CoinGecko
            missing_symbols = symbols
            logger.info("WebSocket not connected, using CoinGecko API for all symbols")

        # Check if we have fresh cached data for missing symbols
        if self._last_batch_fetch and missing_symbols:
            age = (datetime.now() - self._last_batch_fetch).total_seconds()
            if age < self._batch_cache_ttl:
                # Use cached data for missing symbols
                still_missing = []
                for symbol in missing_symbols:
                    if symbol in self._batch_cache:
                        quote = self._batch_cache[symbol]
                        quote.data_age_seconds = age
                        quotes[symbol] = quote
                    else:
                        still_missing.append(symbol)
                missing_symbols = still_missing

                # If we have all data now, return
                if not missing_symbols:
                    logger.debug(f"Using cached CoinGecko data ({age:.1f}s old, {len(quotes)}/{len(symbols)} coins)")
                    return quotes

        # No missing symbols to fetch? Return what we have
        if not missing_symbols:
            return quotes

        # Need to fetch fresh data from CoinGecko for missing symbols
        # Convert symbols to CoinGecko IDs
        coin_ids = []
        symbol_to_id_map = {}
        for symbol in missing_symbols:
            coin_id = self.SYMBOL_TO_ID.get(symbol)
            if coin_id:
                coin_ids.append(coin_id)
                symbol_to_id_map[coin_id] = symbol

        if not coin_ids:
            logger.error("No valid CoinGecko IDs found for symbols")
            return quotes

        # Rate limiting: Don't hit CoinGecko API too frequently
        if self._last_batch_fetch:
            seconds_since_last = (datetime.now() - self._last_batch_fetch).total_seconds()
            if seconds_since_last < self._min_api_interval:
                # Too soon - use cached data for missing symbols
                for symbol in missing_symbols:
                    if symbol in self._batch_cache:
                        quotes[symbol] = self._batch_cache[symbol]
                logger.debug(f"Rate limit protection: using cache ({seconds_since_last:.0f}s since last API call)")
                return quotes

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # CoinGecko /simple/price can handle many coins at once
                # Split into batches of 250 (CoinGecko limit)
                batch_size = 250
                for i in range(0, len(coin_ids), batch_size):
                    batch_ids = coin_ids[i:i + batch_size]
                    ids_param = ",".join(batch_ids)

                    url = f"{self.base_url}/simple/price"
                    params = {
                        "ids": ids_param,
                        "vs_currencies": "usd",
                        "include_24hr_change": "true",
                        "include_24hr_vol": "true",
                        "include_market_cap": "true",
                    }

                    response = await client.get(url, params=params)

                    if response.status_code == 429:
                        logger.warning(f"CoinGecko rate limited (429) - backing off for {self._batch_cache_ttl}s")
                        # Mark as "just fetched" to prevent immediate retry
                        self._last_batch_fetch = datetime.now()
                        # Use cached data for missing symbols
                        for symbol in missing_symbols:
                            if symbol in self._batch_cache:
                                quotes[symbol] = self._batch_cache[symbol]
                        return quotes

                    response.raise_for_status()
                    data = response.json()

                    # Process response
                    for coin_id, price_data in data.items():
                        symbol = symbol_to_id_map.get(coin_id)
                        if symbol and price_data:
                            quote = self._create_quote_from_simple_price(
                                symbol, coin_id, price_data
                            )
                            if quote:
                                quotes[symbol] = quote
                                self._batch_cache[symbol] = quote
                                cache_key = f"crypto_quote_{symbol}"
                                self._set_cached(cache_key, quote)

                    self._last_batch_fetch = datetime.now()
                    logger.info(f"✓ Batch fetched {len(data)} coins from CoinGecko /simple/price")

                    # Small delay between batches to be nice to the API
                    if i + batch_size < len(coin_ids):
                        await asyncio.sleep(0.5)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning(f"CoinGecko RATE LIMITED - backing off for {self._batch_cache_ttl}s")
                self._last_batch_fetch = datetime.now()  # Prevent immediate retry
                for symbol in missing_symbols:
                    if symbol in self._batch_cache:
                        quotes[symbol] = self._batch_cache[symbol]
            else:
                logger.error(f"❌ CoinGecko API error: {e}")
        except Exception as e:
            logger.error(f"❌ Batch fetch failed: {e}")
            # Use cached on error
            for symbol in missing_symbols:
                if symbol in self._batch_cache:
                    quotes[symbol] = self._batch_cache[symbol]

        # Log combined results
        ws_count = len([q for q in quotes.values() if hasattr(q, 'data_source') and 'websocket' in q.data_source])
        api_count = len(quotes) - ws_count
        if ws_count > 0 and api_count > 0:
            logger.info(f"📊 Combined: {ws_count} LIVE (WebSocket) + {api_count} (CoinGecko) = {len(quotes)}/{len(symbols)} coins")

        return quotes

    def _live_price_to_quote(self, live: LivePrice) -> CryptoQuote:
        """Convert WebSocket LivePrice to CryptoQuote."""
        # Get name from our mapping
        coin_id = self.SYMBOL_TO_ID.get(live.symbol)
        name = self.TOP_CRYPTOS.get(coin_id, (live.symbol, live.symbol))[1] if coin_id else live.symbol

        # Estimate market cap from volume (rough approximation)
        # Real market cap would need additional API call
        estimated_mcap = live.quote_volume_24h * 10  # Very rough estimate

        return CryptoQuote(
            symbol=live.symbol,
            name=name,
            price=live.price,
            change_24h=live.price_change_24h,
            change_percent_24h=live.price_change_percent_24h,
            high_24h=live.high_24h,
            low_24h=live.low_24h,
            volume_24h=live.quote_volume_24h,  # Use USDT volume
            market_cap=estimated_mcap,
            market_cap_rank=0,  # Not available from WebSocket
            circulating_supply=0,  # Not available from WebSocket
            total_supply=None,
            ath=live.high_24h,  # Best approximation
            ath_change_percent=0,
            timestamp=live.timestamp,
            is_live=True,
            data_source=live.data_source,  # Use actual provider (coinbase, kraken, etc.)
            data_age_seconds=live.data_age_seconds,
        )

    def _create_quote_from_simple_price(
        self, symbol: str, coin_id: str, data: Dict
    ) -> Optional[CryptoQuote]:
        """Create a CryptoQuote from /simple/price response."""
        try:
            price = data.get("usd", 0)
            if not price:
                return None

            change_24h = data.get("usd_24h_change", 0) or 0
            volume = data.get("usd_24h_vol", 0) or 0
            market_cap = data.get("usd_market_cap", 0) or 0

            # Get name from mapping
            name = self.TOP_CRYPTOS.get(coin_id, (symbol, symbol))[1]

            # Estimate rank from market cap (rough)
            if market_cap > 100_000_000_000:
                rank = 1
            elif market_cap > 10_000_000_000:
                rank = 10
            elif market_cap > 1_000_000_000:
                rank = 50
            else:
                rank = 100

            return CryptoQuote(
                symbol=symbol,
                name=name,
                price=price,
                change_24h=change_24h,  # FIX #1: Already in USD from API, don't recalculate
                change_percent_24h=(change_24h / (price - change_24h + 1e-8) * 100) if (price > 0 and abs(price - change_24h) > 1e-8) else 0,  # CRITICAL FIX: Add epsilon guard
                high_24h=price * 1.02,  # Estimate
                low_24h=price * 0.98,   # Estimate
                volume_24h=volume,
                market_cap=market_cap,
                market_cap_rank=rank,
                # FIX #14: Add epsilon guard to supply division
                circulating_supply=market_cap / max(price, 1e-8),
                total_supply=None,
                ath=price * 1.5,  # Estimate
                ath_change_percent=-30,  # Estimate
                timestamp=datetime.now(),
                is_live=True,
                data_source="coingecko_batch",
                data_age_seconds=0.0,
            )
        except Exception as e:
            logger.debug(f"Failed to create quote for {symbol}: {e}")
            return None

    async def get_market_overview(self) -> Dict[str, Any]:
        """Get crypto market overview."""
        cache_key = "crypto_market_overview"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            # Fetch top cryptos
            symbols = list(self.SYMBOL_TO_ID.keys())
            quotes = await self.get_quotes_batch(symbols)

            # Sort by market cap
            sorted_cryptos = sorted(
                quotes.values(),
                key=lambda x: x.market_cap,
                reverse=True
            )

            # Calculate market stats
            total_mcap = sum(q.market_cap for q in quotes.values())
            # CRITICAL FIX: Check None before accessing .market_cap (prevent AttributeError)
            btc_quote = quotes.get("BTC")
            btc_dominance = (btc_quote.market_cap / total_mcap * 100) if btc_quote and total_mcap > 0 else 0

            # Gainers and losers
            gainers = sorted(quotes.values(), key=lambda x: x.change_percent_24h, reverse=True)[:5]
            losers = sorted(quotes.values(), key=lambda x: x.change_percent_24h)[:5]

            overview = {
                "top_cryptos": [q.to_dict() for q in sorted_cryptos[:10]],
                "total_market_cap": total_mcap,
                "btc_dominance": round(btc_dominance, 2),
                "top_gainers": [q.to_dict() for q in gainers],
                "top_losers": [q.to_dict() for q in losers],
                "timestamp": datetime.now().isoformat(),
            }

            self._set_cached(cache_key, overview)
            return overview

        except Exception as e:
            logger.error(f"Error fetching crypto overview: {e}")
            return {"error": str(e)}

    async def get_price_history(
        self,
        symbol: str,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get historical price data."""
        symbol = symbol.upper()
        coin_id = self.SYMBOL_TO_ID.get(symbol, symbol.lower())

        try:
            async with httpx.AsyncClient() as client:
                url = f"{self.base_url}/coins/{coin_id}/market_chart"
                params = {
                    "vs_currency": "usd",
                    "days": days,
                }
                response = await client.get(url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()

                prices = [(datetime.fromtimestamp(p[0]/1000).isoformat(), p[1])
                          for p in data.get("prices", [])]
                volumes = [(datetime.fromtimestamp(v[0]/1000).isoformat(), v[1])
                           for v in data.get("total_volumes", [])]

                return {
                    "symbol": symbol,
                    "days": days,
                    "prices": prices,
                    "volumes": volumes,
                }
        except Exception as e:
            logger.error(f"Error fetching price history for {symbol}: {e}")
            return {"symbol": symbol, "error": str(e)}

    async def _fetch_coingecko_quote(
        self,
        client: httpx.AsyncClient,
        coin_id: str,
        symbol: str
    ) -> Optional[CryptoQuote]:
        """Fetch quote from CoinGecko API."""
        try:
            url = f"{self.base_url}/coins/{coin_id}"
            params = {
                "localization": "false",
                "tickers": "false",
                "community_data": "false",
                "developer_data": "false",
            }
            response = await client.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            market = data.get("market_data", {})

            return CryptoQuote(
                symbol=symbol.upper(),
                name=data.get("name", symbol),
                price=market.get("current_price", {}).get("usd", 0),
                change_24h=market.get("price_change_24h", 0) or 0,
                change_percent_24h=market.get("price_change_percentage_24h", 0) or 0,
                high_24h=market.get("high_24h", {}).get("usd", 0) or 0,
                low_24h=market.get("low_24h", {}).get("usd", 0) or 0,
                volume_24h=market.get("total_volume", {}).get("usd", 0) or 0,
                market_cap=market.get("market_cap", {}).get("usd", 0) or 0,
                market_cap_rank=data.get("market_cap_rank", 0) or 0,
                circulating_supply=market.get("circulating_supply", 0) or 0,
                total_supply=market.get("total_supply"),
                ath=market.get("ath", {}).get("usd", 0) or 0,
                ath_change_percent=market.get("ath_change_percentage", {}).get("usd", 0) or 0,
                timestamp=datetime.now(),
                is_live=True,
                data_source="coingecko",
                data_age_seconds=0.0,
            )
        except Exception as e:
            logger.debug(f"CoinGecko quote failed for {coin_id}: {e}")
            return None

    def _get_mock_quote(self, symbol: str) -> Optional[CryptoQuote]:
        """Generate mock quote when API is unavailable."""
        import random

        symbol = symbol.upper()
        mock = self.MOCK_PRICES.get(symbol)

        if mock is None:
            # Generate random data for unknown cryptos
            mock = {
                "price": random.uniform(0.5, 100),
                "change": random.uniform(-10, 10),
                "mcap": random.uniform(100000000, 10000000000),
                "rank": random.randint(50, 500),
            }

        # Add variation
        variation = random.uniform(-0.02, 0.02)
        price = mock["price"] * (1 + variation)
        name = self.TOP_CRYPTOS.get(self.SYMBOL_TO_ID.get(symbol, ""), (symbol, symbol))[1]

        return CryptoQuote(
            symbol=symbol,
            name=name,
            price=round(price, 2 if price > 1 else 6),
            change_24h=round(price * mock["change"] / 100, 4),
            change_percent_24h=round(mock["change"] + random.uniform(-1, 1), 2),
            high_24h=round(price * 1.05, 2 if price > 1 else 6),
            low_24h=round(price * 0.95, 2 if price > 1 else 6),
            volume_24h=random.uniform(100000000, 5000000000),
            market_cap=mock["mcap"],
            market_cap_rank=mock["rank"],
            circulating_supply=random.uniform(1000000, 100000000000),
            total_supply=None,
            ath=price * random.uniform(1.5, 3),
            ath_change_percent=random.uniform(-80, -10),
            timestamp=datetime.now(),
            is_live=False,  # MOCK DATA - NOT LIVE
            data_source="mock_fallback",
            data_age_seconds=0.0,
        )

    def _get_cached(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        if key in self.cache:
            entry = self.cache[key]
            if datetime.now() - entry["time"] < timedelta(seconds=self.cache_ttl):
                return entry["data"]
        return None

    def _get_cached_with_age(self, key: str) -> Optional[tuple]:
        """Get value from cache with age in seconds. Returns (data, age_seconds) or None."""
        if key in self.cache:
            entry = self.cache[key]
            age = datetime.now() - entry["time"]
            if age < timedelta(seconds=self.cache_ttl):
                return (entry["data"], age.total_seconds())
        return None

    def _set_cached(self, key: str, data: Any):
        """Set value in cache."""
        self.cache[key] = {"data": data, "time": datetime.now()}

    def get_data_source_status(self) -> Dict[str, Any]:
        """Get status of all data sources."""
        ws_status = self._crypto_ws.get_status()
        provider = ws_status.get("provider", "unknown")
        return {
            "primary_source": f"{provider.lower()}_websocket" if provider else "websocket",
            "fallback_source": "coingecko_api",
            "websocket": ws_status,
            "is_live": ws_status["connected"],
            "symbols_available": ws_status["symbols_count"],
            "last_update": ws_status["last_update"],
        }


# Singleton instance
_crypto_service: Optional[CryptoMarketService] = None


def get_crypto_service() -> CryptoMarketService:
    """Get singleton crypto market service."""
    global _crypto_service
    if _crypto_service is None:
        _crypto_service = CryptoMarketService()
    return _crypto_service
