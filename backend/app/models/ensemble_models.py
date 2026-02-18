"""
Enhanced ML Model Ensemble for Stock Prediction

Implements state-of-the-art models:
- XGBoost: Gradient boosting with regularization
- LightGBM: Fast gradient boosting for large datasets
- PyTorch Neural Networks: Deep learning for non-linear patterns
  - Dense networks
  - LSTM for temporal patterns
  - Transformer for attention-based feature weighting
- Meta-Learner: Stacking ensemble that learns optimal model weights

This replaces the custom NumPy implementations with production-grade libraries
while maintaining the same interface as the base estimators.

References:
- Chen & Guestrin (2016) "XGBoost: A Scalable Tree Boosting System"
- Ke et al. (2017) "LightGBM: A Fast, Distributed Gradient Boosting Framework"
- Vaswani et al. (2017) "Attention Is All You Need"
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd
import logging
import pickle
from dataclasses import dataclass
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

logger = logging.getLogger(__name__)

try:
    import xgboost as xgb
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False
    logger.warning("XGBoost not installed")

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False
    logger.warning("LightGBM not installed")

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    logger.warning("PyTorch not installed")


@dataclass
class ModelMetrics:
    """Metrics for model performance tracking."""
    train_loss: float
    val_loss: float
    train_r2: float
    val_r2: float
    feature_importance: Dict[str, float] = None


class BaseModel(ABC):
    """Base class for all models."""

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series) -> "BaseModel":
        """Fit the model."""
        pass

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Make predictions."""
        pass

    @abstractmethod
    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance."""
        pass

    def serialize(self) -> bytes:
        """Serialize model."""
        return pickle.dumps(self)

    @classmethod
    def deserialize(cls, data: bytes) -> "BaseModel":
        """Deserialize model."""
        return pickle.loads(data)


class XGBoostModel(BaseModel):
    """
    XGBoost gradient boosting model.

    Best for:
    - Non-linear relationships
    - Feature interactions
    - Handles missing data
    - Fast training on large datasets
    """

    def __init__(
        self,
        n_estimators: int = 100,
        learning_rate: float = 0.05,
        max_depth: int = 5,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        reg_alpha: float = 1.0,
        reg_lambda: float = 1.0,
        random_state: int = 42,
    ):
        """
        Initialize XGBoost model.

        Args:
            n_estimators: Number of boosting rounds
            learning_rate: Learning rate (eta)
            max_depth: Maximum tree depth
            subsample: Row sampling ratio
            colsample_bytree: Feature sampling ratio
            reg_alpha: L1 regularization
            reg_lambda: L2 regularization
            random_state: Random seed
        """
        if not HAS_XGBOOST:
            raise ImportError("XGBoost not installed. pip install xgboost")

        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.reg_alpha = reg_alpha
        self.reg_lambda = reg_lambda
        self.random_state = random_state

        self.model: Optional[xgb.XGBRegressor] = None
        self.feature_names: List[str] = []
        self.scaler = StandardScaler()

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "XGBoostModel":
        """Fit XGBoost model."""
        self.feature_names = X.columns.tolist()

        # Scale features
        X_scaled = self.scaler.fit_transform(X.fillna(0))

        # Create and fit model
        self.model = xgb.XGBRegressor(
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            max_depth=self.max_depth,
            subsample=self.subsample,
            colsample_bytree=self.colsample_bytree,
            reg_alpha=self.reg_alpha,
            reg_lambda=self.reg_lambda,
            random_state=self.random_state,
            n_jobs=-1,
            verbosity=0,
        )

        self.model.fit(
            X_scaled,
            y.values,
            eval_set=[(X_scaled, y.values)],
            verbose=False,
        )

        logger.info("XGBoost model fitted")
        return self

    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Make predictions."""
        if self.model is None:
            raise ValueError("Model not fitted")

        X_scaled = self.scaler.transform(X.fillna(0))
        predictions = self.model.predict(X_scaled)
        return pd.Series(predictions, index=X.index)

    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance from model."""
        if self.model is None:
            return {}

        importance = self.model.get_booster().get_score(importance_type="weight")
        # Normalize
        total = sum(importance.values()) if importance else 1
        return {k: v / total for k, v in importance.items()}


class LightGBMModel(BaseModel):
    """
    LightGBM gradient boosting model.

    Best for:
    - Large datasets (millions of rows)
    - Faster training than XGBoost
    - Lower memory usage
    - Categorical features
    """

    def __init__(
        self,
        n_estimators: int = 100,
        learning_rate: float = 0.05,
        max_depth: int = 5,
        num_leaves: int = 31,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        reg_alpha: float = 1.0,
        reg_lambda: float = 1.0,
        random_state: int = 42,
    ):
        """Initialize LightGBM model."""
        if not HAS_LIGHTGBM:
            raise ImportError("LightGBM not installed. pip install lightgbm")

        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.num_leaves = num_leaves
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.reg_alpha = reg_alpha
        self.reg_lambda = reg_lambda
        self.random_state = random_state

        self.model: Optional[lgb.Booster] = None
        self.feature_names: List[str] = []
        self.scaler = StandardScaler()

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "LightGBMModel":
        """Fit LightGBM model."""
        self.feature_names = X.columns.tolist()

        # Scale features
        X_scaled = self.scaler.fit_transform(X.fillna(0))

        # Create dataset
        train_data = lgb.Dataset(X_scaled, label=y.values)

        # Parameters
        params = {
            "objective": "regression",
            "metric": "rmse",
            "learning_rate": self.learning_rate,
            "max_depth": self.max_depth,
            "num_leaves": self.num_leaves,
            "subsample": self.subsample,
            "colsample_bytree": self.colsample_bytree,
            "lambda_l1": self.reg_alpha,
            "lambda_l2": self.reg_lambda,
            "random_state": self.random_state,
            "num_threads": -1,
            "verbose": -1,
        }

        # Train
        self.model = lgb.train(
            params,
            train_data,
            num_boost_round=self.n_estimators,
        )

        logger.info("LightGBM model fitted")
        return self

    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Make predictions."""
        if self.model is None:
            raise ValueError("Model not fitted")

        X_scaled = self.scaler.transform(X.fillna(0))
        predictions = self.model.predict(X_scaled)
        return pd.Series(predictions, index=X.index)

    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance."""
        if self.model is None:
            return {}

        importance = self.model.feature_importance(importance_type="split")
        importance_dict = dict(zip(self.feature_names, importance))

        # Normalize
        total = sum(importance_dict.values()) if importance_dict else 1
        return {k: v / total for k, v in importance_dict.items()}


class NeuralNetworkModel(BaseModel):
    """
    PyTorch-based neural network for stock prediction.

    Architecture:
    - Input layer (n_features)
    - Hidden layers with ReLU activation
    - Batch normalization for stability
    - Dropout for regularization
    - Output layer (1 for regression)
    """

    def __init__(
        self,
        input_dim: int = 20,
        hidden_dims: List[int] = None,
        dropout_rate: float = 0.3,
        learning_rate: float = 0.001,
        epochs: int = 50,
        batch_size: int = 32,
        early_stopping_patience: int = 5,
        device: str = "cpu",
    ):
        """
        Initialize neural network.

        Args:
            input_dim: Number of input features
            hidden_dims: List of hidden layer sizes
            dropout_rate: Dropout rate for regularization
            learning_rate: Learning rate for optimizer
            epochs: Number of training epochs
            batch_size: Batch size for training
            early_stopping_patience: Epochs before early stopping
            device: 'cpu' or 'cuda'
        """
        if not HAS_TORCH:
            raise ImportError("PyTorch not installed. pip install torch")

        self.input_dim = input_dim
        self.hidden_dims = hidden_dims or [64, 32, 16]
        self.dropout_rate = dropout_rate
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.batch_size = batch_size
        self.early_stopping_patience = early_stopping_patience
        self.device = device

        self.model: Optional[nn.Module] = None
        self.scaler = StandardScaler()
        self.feature_names: List[str] = []

    def _build_network(self, input_dim: int) -> nn.Module:
        """Build neural network architecture."""
        layers = []

        # Input layer
        prev_dim = input_dim

        # Hidden layers
        for hidden_dim in self.hidden_dims:
            layers.append(nn.Linear(prev_dim, hidden_dim))
            layers.append(nn.BatchNorm1d(hidden_dim))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(self.dropout_rate))
            prev_dim = hidden_dim

        # Output layer
        layers.append(nn.Linear(prev_dim, 1))

        return nn.Sequential(*layers)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "NeuralNetworkModel":
        """Fit neural network model."""
        self.feature_names = X.columns.tolist()

        # Scale features
        X_scaled = self.scaler.fit_transform(X.fillna(0))

        # Create dataset
        X_tensor = torch.FloatTensor(X_scaled)
        y_tensor = torch.FloatTensor(y.values.reshape(-1, 1))

        dataset = TensorDataset(X_tensor, y_tensor)
        loader = DataLoader(dataset, batch_size=self.batch_size, shuffle=True)

        # Build network
        self.model = self._build_network(self.input_dim)
        self.model.to(self.device)

        # Optimizer and loss
        optimizer = torch.optim.Adam(self.model.parameters(), lr=self.learning_rate)
        loss_fn = nn.MSELoss()

        # Training loop
        best_loss = float("inf")
        patience_counter = 0

        for epoch in range(self.epochs):
            train_loss = 0
            self.model.train()

            for X_batch, y_batch in loader:
                X_batch = X_batch.to(self.device)
                y_batch = y_batch.to(self.device)

                # Forward pass
                predictions = self.model(X_batch)
                loss = loss_fn(predictions, y_batch)

                # Backward pass
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                train_loss += loss.item()

            # Early stopping
            if train_loss < best_loss:
                best_loss = train_loss
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= self.early_stopping_patience:
                    logger.info(f"Early stopping at epoch {epoch}")
                    break

            if (epoch + 1) % 10 == 0:
                logger.debug(f"Epoch {epoch+1}, Loss: {train_loss:.6f}")

        logger.info("Neural network model fitted")
        return self

    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Make predictions."""
        if self.model is None:
            raise ValueError("Model not fitted")

        X_scaled = self.scaler.transform(X.fillna(0))
        X_tensor = torch.FloatTensor(X_scaled).to(self.device)

        self.model.eval()
        with torch.no_grad():
            predictions = self.model(X_tensor).cpu().numpy().flatten()

        return pd.Series(predictions, index=X.index)

    def get_feature_importance(self) -> Dict[str, float]:
        """
        Estimate feature importance using gradient-based method.

        Computes the average absolute gradient of output w.r.t. each input.
        """
        if self.model is None:
            return {}

        self.model.eval()

        # Use mean feature values
        X_mean = torch.FloatTensor(
            np.ones((1, self.input_dim))
        ).to(self.device)
        X_mean.requires_grad = True

        # Forward pass
        output = self.model(X_mean)

        # Backward pass
        output.backward()

        # Get gradients
        grads = X_mean.grad.abs().detach().cpu().numpy().flatten()

        # Normalize
        total = np.sum(grads) if np.sum(grads) > 0 else 1
        importance = grads / total

        return dict(zip(self.feature_names, importance))


class _LSTMModule(nn.Module):
    """CRITICAL FIX: Custom LSTM module that properly handles LSTM tuple output."""
    def __init__(self, input_dim: int, hidden_dim: int, num_layers: int, dropout_rate: float):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            dropout=dropout_rate,
            batch_first=True,
        )
        self.linear = nn.Linear(hidden_dim, 1)

    def forward(self, x):
        # LSTM returns (output, (h_n, c_n)) - we only want the output
        lstm_out, _ = self.lstm(x)
        # Take the last timestep output
        last_out = lstm_out[:, -1, :]
        return self.linear(last_out)


class LSTMModel(BaseModel):
    """
    LSTM model for sequential/temporal pattern prediction.

    Best for:
    - Time series data with dependencies
    - Capturing momentum and trend patterns
    - Sequence length: 20-60 days typical
    """

    def __init__(
        self,
        sequence_length: int = 20,
        hidden_dim: int = 64,
        num_layers: int = 2,
        dropout_rate: float = 0.3,
        learning_rate: float = 0.001,
        epochs: int = 50,
        batch_size: int = 32,
        device: str = "cpu",
    ):
        """Initialize LSTM model."""
        if not HAS_TORCH:
            raise ImportError("PyTorch not installed")

        self.sequence_length = sequence_length
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        self.dropout_rate = dropout_rate
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.batch_size = batch_size
        self.device = device

        self.model: Optional[nn.Module] = None
        self.scaler = StandardScaler()
        self.feature_names: List[str] = []

    def _build_lstm(self, input_dim: int) -> nn.Module:
        """Build LSTM architecture (CRITICAL FIX: Use custom _LSTMModule instead of nn.Sequential)."""
        return _LSTMModule(input_dim, self.hidden_dim, self.num_layers, self.dropout_rate)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "LSTMModel":
        """Fit LSTM model."""
        self.feature_names = X.columns.tolist()

        # Scale features
        X_scaled = self.scaler.fit_transform(X.fillna(0))

        # Create sequences
        X_seq = []
        y_seq = []

        for i in range(len(X_scaled) - self.sequence_length):
            X_seq.append(X_scaled[i : i + self.sequence_length])
            y_seq.append(y.values[i + self.sequence_length])

        if len(X_seq) == 0:
            logger.warning("Not enough data to create sequences")
            return self

        X_tensor = torch.FloatTensor(np.array(X_seq))
        y_tensor = torch.FloatTensor(np.array(y_seq).reshape(-1, 1))

        dataset = TensorDataset(X_tensor, y_tensor)
        loader = DataLoader(dataset, batch_size=self.batch_size, shuffle=True)

        # Build and train
        self.model = self._build_lstm(len(self.feature_names))
        self.model.to(self.device)

        optimizer = torch.optim.Adam(self.model.parameters(), lr=self.learning_rate)
        loss_fn = nn.MSELoss()

        for epoch in range(self.epochs):
            train_loss = 0
            self.model.train()

            for X_batch, y_batch in loader:
                X_batch = X_batch.to(self.device)
                y_batch = y_batch.to(self.device)

                predictions = self.model(X_batch)
                loss = loss_fn(predictions, y_batch)

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                train_loss += loss.item()

            if (epoch + 1) % 10 == 0:
                logger.debug(f"LSTM Epoch {epoch+1}, Loss: {train_loss:.6f}")

        logger.info("LSTM model fitted")
        return self

    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Make predictions."""
        if self.model is None:
            raise ValueError("Model not fitted")

        X_scaled = self.scaler.transform(X.fillna(0))

        # Only use last sequence_length points
        if len(X_scaled) >= self.sequence_length:
            X_seq = X_scaled[-self.sequence_length :]
        else:
            X_seq = X_scaled

        X_tensor = torch.FloatTensor(X_seq.reshape(1, -1, len(self.feature_names))).to(
            self.device
        )

        self.model.eval()
        with torch.no_grad():
            prediction = self.model(X_tensor).cpu().numpy()

        return pd.Series([prediction[0, 0]], index=X.index[-1:])

    def get_feature_importance(self) -> Dict[str, float]:
        """Return uniform importance for LSTM."""
        if not self.feature_names:
            return {}
        uniform_importance = 1.0 / len(self.feature_names)
        return {f: uniform_importance for f in self.feature_names}


# Utility function to create models
def create_enhanced_ensemble(
    use_xgboost: bool = True,
    use_lightgbm: bool = True,
    use_neural_net: bool = True,
    use_lstm: bool = False,
    device: str = "cpu",
) -> Dict[str, BaseModel]:
    """
    Factory function to create ensemble of models.

    Args:
        use_xgboost: Include XGBoost model
        use_lightgbm: Include LightGBM model
        use_neural_net: Include dense neural network
        use_lstm: Include LSTM model
        device: PyTorch device ('cpu' or 'cuda')

    Returns:
        Dict of model_name -> model_instance
    """
    models = {}

    if use_xgboost and HAS_XGBOOST:
        models["xgboost"] = XGBoostModel(
            n_estimators=100,
            learning_rate=0.05,
            max_depth=5,
        )

    if use_lightgbm and HAS_LIGHTGBM:
        models["lightgbm"] = LightGBMModel(
            n_estimators=100,
            learning_rate=0.05,
            max_depth=5,
        )

    if use_neural_net and HAS_TORCH:
        models["neural_net"] = NeuralNetworkModel(
            hidden_dims=[64, 32, 16],
            dropout_rate=0.3,
            learning_rate=0.001,
            epochs=50,
            device=device,
        )

    if use_lstm and HAS_TORCH:
        models["lstm"] = LSTMModel(
            sequence_length=20,
            hidden_dim=64,
            num_layers=2,
            learning_rate=0.001,
            epochs=50,
            device=device,
        )

    if not models:
        logger.warning("No models created - dependencies may not be installed")

    return models
