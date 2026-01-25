"""
Universe management for stock selection.

A universe defines the investable set of stocks.
We provide a default liquid universe for demo purposes.
"""

from typing import List, Optional, Dict
from dataclasses import dataclass
from sqlmodel import Session, select
from loguru import logger

from ..db.models import Universe, UniverseTicker


# Default universe: 50 liquid US large-cap stocks
# Selected for: liquidity, data availability, sector diversity
DEFAULT_UNIVERSE = {
    "name": "liquid_50",
    "description": "50 liquid US large-cap stocks for demo/research",
    "tickers": [
        # Technology
        {"ticker": "AAPL", "sector": "Technology", "industry": "Consumer Electronics"},
        {"ticker": "MSFT", "sector": "Technology", "industry": "Software"},
        {"ticker": "GOOGL", "sector": "Technology", "industry": "Internet"},
        {"ticker": "META", "sector": "Technology", "industry": "Internet"},
        {"ticker": "NVDA", "sector": "Technology", "industry": "Semiconductors"},
        {"ticker": "AVGO", "sector": "Technology", "industry": "Semiconductors"},
        {"ticker": "ORCL", "sector": "Technology", "industry": "Software"},
        {"ticker": "CRM", "sector": "Technology", "industry": "Software"},
        {"ticker": "ADBE", "sector": "Technology", "industry": "Software"},
        {"ticker": "INTC", "sector": "Technology", "industry": "Semiconductors"},

        # Healthcare
        {"ticker": "UNH", "sector": "Healthcare", "industry": "Health Insurance"},
        {"ticker": "JNJ", "sector": "Healthcare", "industry": "Pharmaceuticals"},
        {"ticker": "PFE", "sector": "Healthcare", "industry": "Pharmaceuticals"},
        {"ticker": "ABBV", "sector": "Healthcare", "industry": "Pharmaceuticals"},
        {"ticker": "MRK", "sector": "Healthcare", "industry": "Pharmaceuticals"},
        {"ticker": "LLY", "sector": "Healthcare", "industry": "Pharmaceuticals"},

        # Financials
        {"ticker": "JPM", "sector": "Financials", "industry": "Banks"},
        {"ticker": "BAC", "sector": "Financials", "industry": "Banks"},
        {"ticker": "WFC", "sector": "Financials", "industry": "Banks"},
        {"ticker": "GS", "sector": "Financials", "industry": "Investment Banking"},
        {"ticker": "MS", "sector": "Financials", "industry": "Investment Banking"},
        {"ticker": "BRK-B", "sector": "Financials", "industry": "Diversified"},
        {"ticker": "V", "sector": "Financials", "industry": "Payments"},
        {"ticker": "MA", "sector": "Financials", "industry": "Payments"},

        # Consumer
        {"ticker": "AMZN", "sector": "Consumer", "industry": "E-commerce"},
        {"ticker": "TSLA", "sector": "Consumer", "industry": "Automotive"},
        {"ticker": "HD", "sector": "Consumer", "industry": "Retail"},
        {"ticker": "MCD", "sector": "Consumer", "industry": "Restaurants"},
        {"ticker": "NKE", "sector": "Consumer", "industry": "Apparel"},
        {"ticker": "SBUX", "sector": "Consumer", "industry": "Restaurants"},
        {"ticker": "KO", "sector": "Consumer", "industry": "Beverages"},
        {"ticker": "PEP", "sector": "Consumer", "industry": "Beverages"},
        {"ticker": "PG", "sector": "Consumer", "industry": "Consumer Products"},
        {"ticker": "COST", "sector": "Consumer", "industry": "Retail"},
        {"ticker": "WMT", "sector": "Consumer", "industry": "Retail"},

        # Industrials
        {"ticker": "CAT", "sector": "Industrials", "industry": "Machinery"},
        {"ticker": "BA", "sector": "Industrials", "industry": "Aerospace"},
        {"ticker": "HON", "sector": "Industrials", "industry": "Conglomerate"},
        {"ticker": "UPS", "sector": "Industrials", "industry": "Logistics"},
        {"ticker": "RTX", "sector": "Industrials", "industry": "Aerospace"},

        # Energy
        {"ticker": "XOM", "sector": "Energy", "industry": "Oil & Gas"},
        {"ticker": "CVX", "sector": "Energy", "industry": "Oil & Gas"},
        {"ticker": "COP", "sector": "Energy", "industry": "Oil & Gas"},

        # Utilities & Real Estate
        {"ticker": "NEE", "sector": "Utilities", "industry": "Electric Utilities"},
        {"ticker": "DUK", "sector": "Utilities", "industry": "Electric Utilities"},

        # Materials
        {"ticker": "LIN", "sector": "Materials", "industry": "Chemicals"},

        # Communication
        {"ticker": "DIS", "sector": "Communication", "industry": "Entertainment"},
        {"ticker": "NFLX", "sector": "Communication", "industry": "Streaming"},
        {"ticker": "T", "sector": "Communication", "industry": "Telecom"},
        {"ticker": "VZ", "sector": "Communication", "industry": "Telecom"},
    ]
}


@dataclass
class UniverseInfo:
    """Universe information."""
    id: int
    name: str
    description: str
    tickers: List[str]
    sectors: Dict[str, List[str]]  # sector -> list of tickers


class UniverseManager:
    """Manages stock universes."""

    def __init__(self, session: Session):
        self.session = session

    def get_or_create_default(self) -> UniverseInfo:
        """Get or create the default universe."""
        # Check if exists
        statement = select(Universe).where(Universe.name == DEFAULT_UNIVERSE["name"])
        universe = self.session.exec(statement).first()

        if universe is None:
            universe = self._create_universe(
                name=DEFAULT_UNIVERSE["name"],
                description=DEFAULT_UNIVERSE["description"],
                tickers=DEFAULT_UNIVERSE["tickers"]
            )

        return self._to_info(universe)

    def create_custom(
        self,
        name: str,
        description: str,
        tickers: List[str]
    ) -> UniverseInfo:
        """Create a custom universe from ticker list."""
        # Convert simple ticker list to full format
        ticker_data = [{"ticker": t, "sector": None, "industry": None} for t in tickers]
        universe = self._create_universe(name, description, ticker_data)
        return self._to_info(universe)

    def get_by_name(self, name: str) -> Optional[UniverseInfo]:
        """Get universe by name."""
        statement = select(Universe).where(Universe.name == name)
        universe = self.session.exec(statement).first()

        if universe is None:
            return None

        return self._to_info(universe)

    def list_universes(self) -> List[UniverseInfo]:
        """List all universes."""
        statement = select(Universe)
        universes = self.session.exec(statement).all()
        return [self._to_info(u) for u in universes]

    def get_tickers(self, universe_name: str) -> List[str]:
        """Get ticker list for a universe."""
        info = self.get_by_name(universe_name)
        if info is None:
            logger.warning(f"Universe {universe_name} not found, using default")
            info = self.get_or_create_default()
        return info.tickers

    def _create_universe(
        self,
        name: str,
        description: str,
        tickers: List[Dict]
    ) -> Universe:
        """Create a new universe with tickers."""
        universe = Universe(
            name=name,
            description=description,
            is_default=(name == DEFAULT_UNIVERSE["name"])
        )
        self.session.add(universe)
        self.session.flush()  # Get the ID

        for ticker_data in tickers:
            ticker = UniverseTicker(
                universe_id=universe.id,
                ticker=ticker_data["ticker"],
                sector=ticker_data.get("sector"),
                industry=ticker_data.get("industry")
            )
            self.session.add(ticker)

        self.session.commit()
        self.session.refresh(universe)

        return universe

    def _to_info(self, universe: Universe) -> UniverseInfo:
        """Convert Universe model to UniverseInfo."""
        # Reload tickers
        statement = select(UniverseTicker).where(UniverseTicker.universe_id == universe.id)
        ticker_models = self.session.exec(statement).all()

        tickers = [t.ticker for t in ticker_models]
        sectors: Dict[str, List[str]] = {}

        for t in ticker_models:
            if t.sector:
                if t.sector not in sectors:
                    sectors[t.sector] = []
                sectors[t.sector].append(t.ticker)

        return UniverseInfo(
            id=universe.id,
            name=universe.name,
            description=universe.description or "",
            tickers=tickers,
            sectors=sectors
        )
