"""
Base strategy protocol.

Every strategy implements:
  async def scan(store: FeatureStore) -> List[Opportunity]
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from ..feature_store import FeatureStore
    from ...master_bot import Opportunity

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """Interface that every pluggable strategy must implement."""

    # Human-readable name for logging / UI
    name: str = "BaseStrategy"

    @abstractmethod
    async def scan(self, store: "FeatureStore") -> List["Opportunity"]:
        """
        Scan the market via *store* and return scored Opportunities.

        The strategy must NOT modify store state — treat it as read-only
        (aside from calling public update helpers like update_price_history).
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"
