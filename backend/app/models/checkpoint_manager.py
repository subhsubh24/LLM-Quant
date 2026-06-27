"""
Model Checkpoint Manager — Versioned persistence and rollback.

Provides:
- Save model + metadata (config, validation scores, feature list)
- Version management with automatic naming
- Rollback to any previous version
- Pruning of old checkpoints (keep last N)
- Integrity validation on load

This is the disaster recovery layer: if a newly trained model degrades,
the system can instantly roll back to the last known-good version.
"""

import os
import json
import pickle
import logging
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_CHECKPOINT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "trading", "checkpoints", "versioned"
)


@dataclass
class CheckpointMetadata:
    """Metadata stored alongside each model checkpoint."""
    version: str
    created_at: str
    model_type: str
    config_hash: str
    validation_score: float
    oos_score: float
    n_features: int
    feature_names: List[str]
    training_samples: int
    train_start: str
    train_end: str
    is_production: bool = False
    notes: str = ""
    checksum: str = ""  # SHA256 of model bytes


class ModelCheckpointManager:
    """
    Version-controlled model checkpoint persistence.

    Directory structure:
        checkpoints/versioned/
            v001_20240115_143022/
                model.pkl
                metadata.json
            v002_20240201_091534/
                model.pkl
                metadata.json
            production.json  (pointer to current production version)
    """

    def __init__(
        self,
        checkpoint_dir: Optional[str] = None,
        max_versions: int = 10,
    ):
        self.checkpoint_dir = checkpoint_dir or _DEFAULT_CHECKPOINT_DIR
        os.makedirs(self.checkpoint_dir, exist_ok=True)
        self.max_versions = max_versions
        self._version_counter = self._detect_latest_version()

    def _detect_latest_version(self) -> int:
        """Find the latest version number from existing checkpoints."""
        max_ver = 0
        try:
            for entry in os.listdir(self.checkpoint_dir):
                if entry.startswith("v") and "_" in entry:
                    try:
                        ver = int(entry.split("_")[0][1:])
                        max_ver = max(max_ver, ver)
                    except (ValueError, IndexError):
                        pass
        except FileNotFoundError:
            pass
        return max_ver

    def save(
        self,
        model: Any,
        model_type: str,
        config_hash: str,
        validation_score: float,
        oos_score: float = 0.0,
        feature_names: Optional[List[str]] = None,
        training_samples: int = 0,
        train_start: str = "",
        train_end: str = "",
        notes: str = "",
        promote_to_production: bool = False,
    ) -> str:
        """
        Save a model checkpoint with metadata.

        Args:
            model: The trained model object
            model_type: Model type string (e.g., "ensemble")
            config_hash: Hash of the model config
            validation_score: Walk-forward validation score
            oos_score: Out-of-sample test score
            feature_names: List of feature names used
            training_samples: Number of training samples
            train_start: Training data start date
            train_end: Training data end date
            notes: Human-readable notes
            promote_to_production: If True, set as production model

        Returns:
            Version string (e.g., "v003")
        """
        self._version_counter += 1
        version = f"v{self._version_counter:03d}"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dir_name = f"{version}_{timestamp}"
        version_dir = os.path.join(self.checkpoint_dir, dir_name)
        os.makedirs(version_dir, exist_ok=True)

        # Serialize model
        model_bytes = pickle.dumps(model)
        checksum = hashlib.sha256(model_bytes).hexdigest()

        # Save model
        model_path = os.path.join(version_dir, "model.pkl")
        with open(model_path, "wb") as f:
            f.write(model_bytes)

        # Save metadata
        metadata = CheckpointMetadata(
            version=version,
            created_at=datetime.now().isoformat(),
            model_type=model_type,
            config_hash=config_hash,
            validation_score=validation_score,
            oos_score=oos_score,
            n_features=len(feature_names) if feature_names else 0,
            feature_names=feature_names or [],
            training_samples=training_samples,
            train_start=train_start,
            train_end=train_end,
            is_production=promote_to_production,
            notes=notes,
            checksum=checksum,
        )

        meta_path = os.path.join(version_dir, "metadata.json")
        with open(meta_path, "w") as f:
            json.dump(asdict(metadata), f, indent=2)

        if promote_to_production:
            self._set_production(version, dir_name)

        # Prune old versions
        self._prune_old_versions()

        logger.info(
            f"Saved checkpoint {version}: val={validation_score:.4f}, "
            f"oos={oos_score:.4f}, features={metadata.n_features}"
        )
        return version

    def load(self, version: Optional[str] = None) -> Tuple[Any, CheckpointMetadata]:
        """
        Load a model checkpoint.

        Args:
            version: Version to load (e.g., "v003"). If None, loads production model.

        Returns:
            Tuple of (model, metadata)

        Raises:
            FileNotFoundError: If version not found
            ValueError: If checkpoint is corrupted
        """
        if version is None:
            version = self._get_production_version()
            if version is None:
                raise FileNotFoundError("No production model set")

        # Find the directory for this version
        version_dir = self._find_version_dir(version)
        if version_dir is None:
            raise FileNotFoundError(f"Checkpoint {version} not found")

        # Load metadata
        meta_path = os.path.join(version_dir, "metadata.json")
        with open(meta_path, "r") as f:
            meta_dict = json.load(f)
        metadata = CheckpointMetadata(**meta_dict)

        # Load model
        model_path = os.path.join(version_dir, "model.pkl")
        with open(model_path, "rb") as f:
            model_bytes = f.read()

        # Verify integrity
        actual_checksum = hashlib.sha256(model_bytes).hexdigest()
        if metadata.checksum and actual_checksum != metadata.checksum:
            raise ValueError(
                f"Checkpoint {version} corrupted: "
                f"expected checksum {metadata.checksum[:16]}..., "
                f"got {actual_checksum[:16]}..."
            )

        model = pickle.loads(model_bytes)
        logger.info(f"Loaded checkpoint {version} (val={metadata.validation_score:.4f})")
        return model, metadata

    def rollback(self, version: str) -> Tuple[Any, CheckpointMetadata]:
        """
        Roll back to a specific version and promote it to production.

        Args:
            version: Version to roll back to

        Returns:
            Tuple of (model, metadata)
        """
        model, metadata = self.load(version)
        dir_name = self._find_version_dir(version)
        if dir_name:
            self._set_production(version, os.path.basename(dir_name))
        logger.warning(f"ROLLBACK to {version}")
        return model, metadata

    def list_versions(self) -> List[Dict[str, Any]]:
        """List all available checkpoint versions."""
        versions = []
        prod_version = self._get_production_version()

        try:
            for entry in sorted(os.listdir(self.checkpoint_dir)):
                if not entry.startswith("v"):
                    continue
                meta_path = os.path.join(self.checkpoint_dir, entry, "metadata.json")
                if os.path.exists(meta_path):
                    with open(meta_path, "r") as f:
                        meta = json.load(f)
                    meta["is_production"] = meta.get("version") == prod_version
                    versions.append(meta)
        except FileNotFoundError:
            pass

        return versions

    def get_production_metadata(self) -> Optional[Dict[str, Any]]:
        """Get metadata for the current production model."""
        prod_version = self._get_production_version()
        if prod_version is None:
            return None

        version_dir = self._find_version_dir(prod_version)
        if version_dir is None:
            return None

        meta_path = os.path.join(version_dir, "metadata.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r") as f:
                return json.load(f)
        return None

    def _set_production(self, version: str, dir_name: str) -> None:
        """Set a version as the production model."""
        prod_path = os.path.join(self.checkpoint_dir, "production.json")
        with open(prod_path, "w") as f:
            json.dump({
                "version": version,
                "dir_name": dir_name,
                "promoted_at": datetime.now().isoformat(),
            }, f)
        logger.info(f"Promoted {version} to production")

    def _get_production_version(self) -> Optional[str]:
        """Get the current production version string."""
        prod_path = os.path.join(self.checkpoint_dir, "production.json")
        if not os.path.exists(prod_path):
            return None
        try:
            with open(prod_path, "r") as f:
                data = json.load(f)
            return data.get("version")
        except Exception:
            return None

    def _find_version_dir(self, version: str) -> Optional[str]:
        """Find the directory path for a version."""
        try:
            for entry in os.listdir(self.checkpoint_dir):
                if entry.startswith(version + "_"):
                    full_path = os.path.join(self.checkpoint_dir, entry)
                    if os.path.isdir(full_path):
                        return full_path
        except FileNotFoundError:
            pass
        return None

    def _prune_old_versions(self) -> None:
        """Remove old versions beyond max_versions, keeping production."""
        prod_version = self._get_production_version()

        # Get all version dirs sorted by name (chronological)
        try:
            dirs = sorted([
                d for d in os.listdir(self.checkpoint_dir)
                if d.startswith("v") and os.path.isdir(
                    os.path.join(self.checkpoint_dir, d)
                )
            ])
        except FileNotFoundError:
            return

        if len(dirs) <= self.max_versions:
            return

        # Remove oldest, but never remove production
        to_remove = dirs[:len(dirs) - self.max_versions]
        for d in to_remove:
            version = d.split("_")[0]
            if version == prod_version:
                continue
            dir_path = os.path.join(self.checkpoint_dir, d)
            try:
                import shutil
                shutil.rmtree(dir_path)
                logger.info(f"Pruned old checkpoint: {d}")
            except Exception as e:
                logger.warning(f"Failed to prune {d}: {e}")
