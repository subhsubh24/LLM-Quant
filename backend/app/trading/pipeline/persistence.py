"""
Persistence layer for the pipeline orchestrator.

Provides:
  - Trade state persistence (survives restarts)
  - Model checkpoint save / load (weights + optimizer state)
  - Portfolio snapshot persistence

Uses the existing SQLite database when available, falls back to JSON
file storage for zero-dependency operation.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Default data directory (relative to project root)
_DATA_DIR = Path(os.environ.get(
    "QUANT_DATA_DIR",
    Path(__file__).resolve().parents[4] / "data" / "pipeline",
))


class TradePersistence:
    """Persist orchestrator trade_history to disk (JSON + optional SQLite)."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = Path(data_dir) if data_dir else _DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._trades_path = self.data_dir / "trade_history.json"
        self._portfolio_path = self.data_dir / "portfolio_state.json"

    # ── Trade history ─────────────────────────────────────────

    def load_trades(self) -> List[Dict]:
        """Load trade history from disk."""
        if not self._trades_path.exists():
            return []
        try:
            with open(self._trades_path) as f:
                trades = json.load(f)
            logger.info(f"Loaded {len(trades)} trades from {self._trades_path}")
            return trades
        except Exception as e:
            logger.warning(f"Failed to load trades: {e}")
            return []

    def save_trades(self, trades: List[Dict]):
        """Persist trade history to disk (atomic write via temp + rename)."""
        try:
            fd, tmp = tempfile.mkstemp(
                dir=self.data_dir, suffix=".tmp", prefix="trades_",
            )
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(trades, f, indent=2, default=str)
                os.replace(tmp, self._trades_path)
            except BaseException:
                # Clean up temp file on any failure
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except Exception as e:
            logger.error(f"Failed to save trades: {e}")

    def append_trade(self, trade: Dict):
        """Append a single trade to the persisted list."""
        trades = self.load_trades()
        trades.append(trade)
        self.save_trades(trades)

    def update_trade(self, trade_id: str, updates: Dict):
        """Update fields on a persisted trade by ID."""
        trades = self.load_trades()
        for t in trades:
            if t.get("id") == trade_id:
                t.update(updates)
                break
        self.save_trades(trades)

    # ── Portfolio state ───────────────────────────────────────

    def save_portfolio_state(self, state: Dict):
        """Snapshot portfolio state for crash recovery (atomic write)."""
        state["_saved_at"] = datetime.now().isoformat()
        try:
            fd, tmp = tempfile.mkstemp(
                dir=self.data_dir, suffix=".tmp", prefix="portfolio_",
            )
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(state, f, indent=2, default=str)
                os.replace(tmp, self._portfolio_path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except Exception as e:
            logger.error(f"Failed to save portfolio state: {e}")

    def load_portfolio_state(self) -> Optional[Dict]:
        """Load last saved portfolio state."""
        if not self._portfolio_path.exists():
            return None
        try:
            with open(self._portfolio_path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load portfolio state: {e}")
            return None


class ModelCheckpointer:
    """Save and load ML model weights for crash recovery and deployment."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = (Path(data_dir) if data_dir else _DATA_DIR) / "checkpoints"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def save(self, feature_store: Any, tag: str = "latest"):
        """Save all trainable model weights."""
        prefix = self.data_dir / tag

        try:
            # LSTMClassifier
            w = feature_store.lstm_classifier.get_weights()
            np.savez(f"{prefix}_lstm.npz", **w)

            # TrainableTransformer
            w = feature_store.transformer.get_weights()
            np.savez(f"{prefix}_transformer.npz", **w)

            # TrainableVAE
            w = feature_store.regime_vae.get_weights()
            np.savez(f"{prefix}_vae.npz", **w)

            # DQN Q-network
            params = {}
            for i, layer in enumerate(feature_store.dqn._q_network):
                for j, p in enumerate(layer.parameters()):
                    params[f"layer_{i}_param_{j}"] = p
            np.savez(f"{prefix}_dqn.npz", **params)

            logger.info(f"Model checkpoint saved: {prefix}")
        except Exception as e:
            logger.error(f"Checkpoint save failed: {e}")

    def load(self, feature_store: Any, tag: str = "latest") -> bool:
        """Load model weights if checkpoint exists."""
        prefix = self.data_dir / tag
        loaded = 0

        # LSTMClassifier
        path = f"{prefix}_lstm.npz"
        if os.path.exists(path):
            try:
                w = dict(np.load(path))
                feature_store.lstm_classifier.set_weights(w)
                loaded += 1
            except Exception as e:
                logger.warning(f"LSTM load failed: {e}")

        # TrainableTransformer
        path = f"{prefix}_transformer.npz"
        if os.path.exists(path):
            try:
                w = dict(np.load(path))
                feature_store.transformer.set_weights(w)
                loaded += 1
            except Exception as e:
                logger.warning(f"Transformer load failed: {e}")

        # TrainableVAE
        path = f"{prefix}_vae.npz"
        if os.path.exists(path):
            try:
                w = dict(np.load(path))
                feature_store.regime_vae.set_weights(w)
                loaded += 1
            except Exception as e:
                logger.warning(f"VAE load failed: {e}")

        # DQN
        path = f"{prefix}_dqn.npz"
        if os.path.exists(path):
            try:
                feature_store.dqn.load(path)
                loaded += 1
            except Exception as e:
                logger.warning(f"DQN load failed: {e}")

        if loaded:
            logger.info(f"Loaded {loaded} model checkpoints from {prefix}")
        return loaded > 0
