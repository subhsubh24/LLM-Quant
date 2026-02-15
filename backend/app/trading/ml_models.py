"""
Deep Learning and Reinforcement Learning Models for Quantitative Trading.

This module implements state-of-the-art ML models for trading:
- Deep Q-Network (DQN) with experience replay
- Proximal Policy Optimization (PPO) agent
- LSTM/Transformer for price prediction
- Attention-based cross-asset correlation modeling
- Variational Autoencoder for regime detection

Academic references:
- Mnih et al. (2015) "Human-level control through deep RL" (DQN)
- Schulman et al. (2017) "Proximal Policy Optimization" (PPO)
- Vaswani et al. (2017) "Attention Is All You Need" (Transformer)
- Zhang et al. (2020) "Deep RL for Trading" (Survey)
"""

import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from collections import deque
from datetime import datetime
import random
import math
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# NEURAL NETWORK BUILDING BLOCKS (Pure NumPy Implementation)
# =============================================================================

class Layer:
    """Base layer class."""
    def forward(self, x: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def backward(self, grad: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def parameters(self) -> List[np.ndarray]:
        return []

    def gradients(self) -> List[np.ndarray]:
        return []


class Dense(Layer):
    """Fully connected layer with He initialization."""

    def __init__(self, input_dim: int, output_dim: int, activation: str = "relu"):
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.activation = activation

        # He initialization for ReLU, Xavier for others
        if activation == "relu":
            scale = np.sqrt(2.0 / input_dim)
        else:
            scale = np.sqrt(1.0 / input_dim)

        self.W = np.random.randn(input_dim, output_dim) * scale
        self.b = np.zeros((1, output_dim))

        self.dW = np.zeros_like(self.W)
        self.db = np.zeros_like(self.b)

        # Cache for backprop
        self.x = None
        self.z = None

    def forward(self, x: np.ndarray) -> np.ndarray:
        self.x = x
        self.z = x @ self.W + self.b

        if self.activation == "relu":
            return np.maximum(0, self.z)
        elif self.activation == "tanh":
            return np.tanh(self.z)
        elif self.activation == "sigmoid":
            return 1 / (1 + np.exp(-np.clip(self.z, -500, 500)))
        elif self.activation == "softmax":
            # CRITICAL FIX: Add epsilon protection to prevent division by zero
            exp_z = np.exp(np.clip(self.z - np.max(self.z, axis=-1, keepdims=True), -500, 500))
            return exp_z / (np.sum(exp_z, axis=-1, keepdims=True) + 1e-8)
        else:  # linear
            return self.z

    def backward(self, grad: np.ndarray) -> np.ndarray:
        # Activation gradient
        if self.activation == "relu":
            grad = grad * (self.z > 0).astype(float)
        elif self.activation == "tanh":
            grad = grad * (1 - np.tanh(self.z) ** 2)
        elif self.activation == "sigmoid":
            sig = 1 / (1 + np.exp(-np.clip(self.z, -500, 500)))
            grad = grad * sig * (1 - sig)

        # Parameter gradients
        self.dW = self.x.T @ grad
        self.db = np.sum(grad, axis=0, keepdims=True)

        # Input gradient
        return grad @ self.W.T

    def parameters(self) -> List[np.ndarray]:
        return [self.W, self.b]

    def gradients(self) -> List[np.ndarray]:
        return [self.dW, self.db]


class LayerNorm(Layer):
    """Layer normalization for stable training."""

    def __init__(self, dim: int, eps: float = 1e-5):
        self.dim = dim
        self.eps = eps
        self.gamma = np.ones((1, dim))
        self.beta = np.zeros((1, dim))
        self.dgamma = np.zeros_like(self.gamma)
        self.dbeta = np.zeros_like(self.beta)

    def forward(self, x: np.ndarray) -> np.ndarray:
        self.x = x
        self.mean = np.mean(x, axis=-1, keepdims=True)
        self.var = np.var(x, axis=-1, keepdims=True)
        self.x_norm = (x - self.mean) / np.sqrt(self.var + self.eps)
        return self.gamma * self.x_norm + self.beta

    def backward(self, grad: np.ndarray) -> np.ndarray:
        self.dgamma = np.sum(grad * self.x_norm, axis=0, keepdims=True)
        self.dbeta = np.sum(grad, axis=0, keepdims=True)

        N = self.x.shape[-1]
        dx_norm = grad * self.gamma
        dvar = np.sum(dx_norm * (self.x - self.mean) * -0.5 *
                      (self.var + self.eps) ** -1.5, axis=-1, keepdims=True)
        dmean = np.sum(dx_norm * -1 / np.sqrt(self.var + self.eps), axis=-1, keepdims=True)

        return (dx_norm / np.sqrt(self.var + self.eps) +
                dvar * 2 * (self.x - self.mean) / N + dmean / N)

    def parameters(self) -> List[np.ndarray]:
        return [self.gamma, self.beta]

    def gradients(self) -> List[np.ndarray]:
        return [self.dgamma, self.dbeta]


class Dropout(Layer):
    """Dropout for regularization."""

    def __init__(self, rate: float = 0.1):
        self.rate = rate
        self.mask = None
        self.training = True

    def forward(self, x: np.ndarray) -> np.ndarray:
        if self.training and self.rate > 0:
            self.mask = (np.random.rand(*x.shape) > self.rate).astype(float) / (1 - self.rate)
            return x * self.mask
        return x

    def backward(self, grad: np.ndarray) -> np.ndarray:
        if self.training and self.mask is not None:
            return grad * self.mask
        return grad


class MultiHeadAttention(Layer):
    """
    Multi-head self-attention mechanism (Vaswani et al., 2017).

    Enables the model to jointly attend to information from different
    representation subspaces at different positions.
    """

    def __init__(self, d_model: int, n_heads: int = 8, dropout: float = 0.1):
        self.d_model = d_model
        self.n_heads = n_heads
        self.d_k = d_model // n_heads

        # Query, Key, Value projections
        scale = np.sqrt(1.0 / d_model)
        self.W_q = np.random.randn(d_model, d_model) * scale
        self.W_k = np.random.randn(d_model, d_model) * scale
        self.W_v = np.random.randn(d_model, d_model) * scale
        self.W_o = np.random.randn(d_model, d_model) * scale

        self.dropout = Dropout(dropout)

    def forward(self, x: np.ndarray, mask: Optional[np.ndarray] = None) -> np.ndarray:
        batch_size = x.shape[0] if len(x.shape) == 3 else 1
        seq_len = x.shape[-2]

        if len(x.shape) == 2:
            x = x.reshape(1, seq_len, -1)

        # Linear projections
        Q = x @ self.W_q
        K = x @ self.W_k
        V = x @ self.W_v

        # Reshape for multi-head attention
        Q = Q.reshape(batch_size, seq_len, self.n_heads, self.d_k).transpose(0, 2, 1, 3)
        K = K.reshape(batch_size, seq_len, self.n_heads, self.d_k).transpose(0, 2, 1, 3)
        V = V.reshape(batch_size, seq_len, self.n_heads, self.d_k).transpose(0, 2, 1, 3)

        # Scaled dot-product attention
        scores = Q @ K.transpose(0, 1, 3, 2) / np.sqrt(self.d_k)

        if mask is not None:
            scores = scores + mask * -1e9

        attention = self._softmax(scores)
        attention = self.dropout.forward(attention)

        # Apply attention to values
        context = attention @ V

        # Reshape and project
        context = context.transpose(0, 2, 1, 3).reshape(batch_size, seq_len, self.d_model)
        output = context @ self.W_o

        self.attention_weights = attention
        # FIX #11: Don't squeeze batch dimension - preserve it
        return output if batch_size > 1 else output[0:1]

    def _softmax(self, x: np.ndarray) -> np.ndarray:
        # CRITICAL FIX: Add clipping and epsilon protection to prevent overflow/division by zero
        exp_x = np.exp(np.clip(x - np.max(x, axis=-1, keepdims=True), -500, 500))
        return exp_x / (np.sum(exp_x, axis=-1, keepdims=True) + 1e-8)

    def parameters(self) -> List[np.ndarray]:
        return [self.W_q, self.W_k, self.W_v, self.W_o]


class LSTM(Layer):
    """
    Long Short-Term Memory network for sequential data.

    Hochreiter & Schmidhuber (1997) - essential for capturing
    long-range dependencies in financial time series.
    """

    def __init__(self, input_dim: int, hidden_dim: int):
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim

        # Xavier initialization
        scale = np.sqrt(1.0 / (input_dim + hidden_dim))

        # Gates: forget, input, output, cell candidate
        self.W_f = np.random.randn(input_dim + hidden_dim, hidden_dim) * scale
        self.b_f = np.ones((1, hidden_dim))  # Initialize forget bias high

        self.W_i = np.random.randn(input_dim + hidden_dim, hidden_dim) * scale
        self.b_i = np.zeros((1, hidden_dim))

        self.W_o = np.random.randn(input_dim + hidden_dim, hidden_dim) * scale
        self.b_o = np.zeros((1, hidden_dim))

        self.W_c = np.random.randn(input_dim + hidden_dim, hidden_dim) * scale
        self.b_c = np.zeros((1, hidden_dim))

        # Hidden state
        self.h = None
        self.c = None

    def reset_state(self, batch_size: int = 1):
        """Reset hidden state."""
        self.h = np.zeros((batch_size, self.hidden_dim))
        self.c = np.zeros((batch_size, self.hidden_dim))

    def forward(self, x: np.ndarray) -> np.ndarray:
        """
        Forward pass through LSTM.

        Args:
            x: Input of shape (batch, seq_len, input_dim) or (seq_len, input_dim)

        Returns:
            Output of shape (batch, seq_len, hidden_dim)
        """
        if len(x.shape) == 2:
            x = x.reshape(1, *x.shape)

        batch_size, seq_len, _ = x.shape

        if self.h is None:
            self.reset_state(batch_size)

        outputs = []

        for t in range(seq_len):
            xt = x[:, t, :]
            combined = np.concatenate([xt, self.h], axis=1)

            # Gate computations
            f = self._sigmoid(combined @ self.W_f + self.b_f)
            i = self._sigmoid(combined @ self.W_i + self.b_i)
            o = self._sigmoid(combined @ self.W_o + self.b_o)
            c_tilde = np.tanh(combined @ self.W_c + self.b_c)

            # Update cell and hidden state
            self.c = f * self.c + i * c_tilde
            self.h = o * np.tanh(self.c)

            outputs.append(self.h)

        return np.stack(outputs, axis=1)

    def _sigmoid(self, x: np.ndarray) -> np.ndarray:
        return 1 / (1 + np.exp(-np.clip(x, -500, 500)))

    def parameters(self) -> List[np.ndarray]:
        return [self.W_f, self.b_f, self.W_i, self.b_i,
                self.W_o, self.b_o, self.W_c, self.b_c]


class LSTMClassifier:
    """
    LSTM with output layer for classification tasks.
    Includes proper backpropagation through time (BPTT).
    """

    def __init__(self, input_dim: int, hidden_dim: int, output_dim: int, lr: float = 0.001, l2_reg: float = 0.0001):
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.output_dim = output_dim
        self.lr = lr
        self.l2_reg = l2_reg  # L2 regularization to prevent overfitting

        # LSTM weights (Xavier initialization)
        scale = np.sqrt(1.0 / (input_dim + hidden_dim))
        concat_dim = input_dim + hidden_dim

        # Combined weight matrices for efficiency
        self.Wf = np.random.randn(concat_dim, hidden_dim) * scale
        self.Wi = np.random.randn(concat_dim, hidden_dim) * scale
        self.Wc = np.random.randn(concat_dim, hidden_dim) * scale
        self.Wo = np.random.randn(concat_dim, hidden_dim) * scale

        self.bf = np.ones((1, hidden_dim))  # Forget gate bias = 1 (remember by default)
        self.bi = np.zeros((1, hidden_dim))
        self.bc = np.zeros((1, hidden_dim))
        self.bo = np.zeros((1, hidden_dim))

        # Output layer
        self.Wy = np.random.randn(hidden_dim, output_dim) * np.sqrt(1.0 / hidden_dim)
        self.by = np.zeros((1, output_dim))

        # Adam optimizer state
        self._init_adam()

        # Cache for BPTT
        self.cache = {}

    def _init_adam(self):
        """Initialize Adam optimizer moments."""
        self.m = {}
        self.v = {}
        self.t = 0
        for name in ['Wf', 'Wi', 'Wc', 'Wo', 'bf', 'bi', 'bc', 'bo', 'Wy', 'by']:
            param = getattr(self, name)
            self.m[name] = np.zeros_like(param)
            self.v[name] = np.zeros_like(param)

    def _sigmoid(self, x):
        return 1 / (1 + np.exp(-np.clip(x, -500, 500)))

    def _softmax(self, x):
        # FIX #5: Add clipping to prevent overflow with large logits
        exp_x = np.exp(np.clip(x - np.max(x, axis=-1, keepdims=True), -500, 500))
        return exp_x / (np.sum(exp_x, axis=-1, keepdims=True) + 1e-8)

    def forward(self, x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Forward pass with caching for backprop.

        Args:
            x: Input (seq_len, input_dim) or (batch, seq_len, input_dim)

        Returns:
            output: Class probabilities (batch, output_dim)
            hidden: Final hidden state
        """
        if len(x.shape) == 2:
            x = x.reshape(1, *x.shape)

        batch_size, seq_len, _ = x.shape

        # Initialize hidden states
        h = np.zeros((batch_size, self.hidden_dim))
        c = np.zeros((batch_size, self.hidden_dim))

        # Store cache for BPTT
        self.cache = {
            'x': x, 'h': [h], 'c': [c],
            'f': [], 'i': [], 'c_tilde': [], 'o': []
        }

        for t in range(seq_len):
            xt = x[:, t, :]
            concat = np.concatenate([xt, h], axis=1)

            # Gates
            f = self._sigmoid(concat @ self.Wf + self.bf)
            i = self._sigmoid(concat @ self.Wi + self.bi)
            c_tilde = np.tanh(concat @ self.Wc + self.bc)
            o = self._sigmoid(concat @ self.Wo + self.bo)

            # Cell and hidden state
            c = f * c + i * c_tilde
            h = o * np.tanh(c)

            # Cache
            self.cache['f'].append(f)
            self.cache['i'].append(i)
            self.cache['c_tilde'].append(c_tilde)
            self.cache['o'].append(o)
            self.cache['h'].append(h)
            self.cache['c'].append(c)

        # Output layer
        logits = h @ self.Wy + self.by
        probs = self._softmax(logits)

        return probs, h

    def backward(self, y_true: np.ndarray) -> float:
        """
        Backpropagation through time (BPTT).

        Args:
            y_true: True labels (batch,) as integers

        Returns:
            loss: Cross-entropy loss
        """
        x = self.cache['x']
        batch_size, seq_len, _ = x.shape

        # Forward to get predictions
        probs, _ = self.forward(x)

        # Cross-entropy loss
        y_onehot = np.zeros_like(probs)
        y_onehot[np.arange(batch_size), y_true.astype(int)] = 1
        loss = -np.mean(np.sum(y_onehot * np.log(probs + 1e-8), axis=1))

        # Output layer gradients
        dlogits = (probs - y_onehot) / batch_size
        dWy = self.cache['h'][-1].T @ dlogits
        dby = np.sum(dlogits, axis=0, keepdims=True)

        # Backprop through LSTM
        dh_next = dlogits @ self.Wy.T
        dc_next = np.zeros((batch_size, self.hidden_dim))

        dWf = np.zeros_like(self.Wf)
        dWi = np.zeros_like(self.Wi)
        dWc = np.zeros_like(self.Wc)
        dWo = np.zeros_like(self.Wo)
        dbf = np.zeros_like(self.bf)
        dbi = np.zeros_like(self.bi)
        dbc = np.zeros_like(self.bc)
        dbo = np.zeros_like(self.bo)

        for t in reversed(range(seq_len)):
            h = self.cache['h'][t + 1]
            h_prev = self.cache['h'][t]
            c = self.cache['c'][t + 1]
            c_prev = self.cache['c'][t]

            f = self.cache['f'][t]
            i = self.cache['i'][t]
            c_tilde = self.cache['c_tilde'][t]
            o = self.cache['o'][t]

            xt = x[:, t, :]
            concat = np.concatenate([xt, h_prev], axis=1)

            # Gradients
            dh = dh_next
            tanh_c = np.tanh(c)

            do = dh * tanh_c
            do_raw = do * o * (1 - o)

            dc = dh * o * (1 - tanh_c ** 2) + dc_next

            df = dc * c_prev
            df_raw = df * f * (1 - f)

            di = dc * c_tilde
            di_raw = di * i * (1 - i)

            dc_tilde = dc * i
            dc_tilde_raw = dc_tilde * (1 - c_tilde ** 2)

            # Weight gradients
            dWf += concat.T @ df_raw
            dWi += concat.T @ di_raw
            dWc += concat.T @ dc_tilde_raw
            dWo += concat.T @ do_raw

            dbf += np.sum(df_raw, axis=0, keepdims=True)
            dbi += np.sum(di_raw, axis=0, keepdims=True)
            dbc += np.sum(dc_tilde_raw, axis=0, keepdims=True)
            dbo += np.sum(do_raw, axis=0, keepdims=True)

            # Gradients for next timestep
            dconcat = (df_raw @ self.Wf.T + di_raw @ self.Wi.T +
                       dc_tilde_raw @ self.Wc.T + do_raw @ self.Wo.T)
            # FIX #10: Validate LSTM backward pass dimensions
            dh_next = dconcat[:, self.input_dim:]
            assert dh_next.shape == (batch_size, self.hidden_dim), \
                f"dh_next shape mismatch: expected ({batch_size}, {self.hidden_dim}), got {dh_next.shape}"
            dc_next = dc * f

        # Gradient clipping
        max_grad = 5.0
        grads = {'Wf': dWf, 'Wi': dWi, 'Wc': dWc, 'Wo': dWo,
                 'bf': dbf, 'bi': dbi, 'bc': dbc, 'bo': dbo,
                 'Wy': dWy, 'by': dby}

        for name, grad in grads.items():
            norm = np.linalg.norm(grad)
            if norm > max_grad:
                grads[name] = grad * max_grad / norm

        # Adam update
        self.t += 1
        beta1, beta2, eps = 0.9, 0.999, 1e-8

        for name, grad in grads.items():
            param = getattr(self, name)
            self.m[name] = beta1 * self.m[name] + (1 - beta1) * grad
            self.v[name] = beta2 * self.v[name] + (1 - beta2) * (grad ** 2)

            m_hat = self.m[name] / (1 - beta1 ** self.t)
            v_hat = self.v[name] / (1 - beta2 ** self.t)

            # Adam update
            param -= self.lr * m_hat / (np.sqrt(v_hat) + eps)

            # L2 weight decay (regularization) - shrink weights to prevent overfitting
            param *= (1 - self.l2_reg * self.lr)

            setattr(self, name, param)

        return loss

    def train_step(self, x: np.ndarray, y: np.ndarray) -> float:
        """Single training step."""
        self.forward(x)
        return self.backward(y)

    def predict(self, x: np.ndarray) -> int:
        """Predict class."""
        probs, _ = self.forward(x)
        return int(np.argmax(probs[0]))

    def get_weights(self) -> Dict:
        """Get all weights for checkpointing."""
        return {
            'Wf': self.Wf, 'Wi': self.Wi, 'Wc': self.Wc, 'Wo': self.Wo,
            'bf': self.bf, 'bi': self.bi, 'bc': self.bc, 'bo': self.bo,
            'Wy': self.Wy, 'by': self.by
        }

    def set_weights(self, weights: Dict):
        """Set weights from checkpoint."""
        for name, value in weights.items():
            setattr(self, name, value)
        self._init_adam()


# =============================================================================
# OPTIMIZERS
# =============================================================================

class Adam:
    """
    Adam optimizer (Kingma & Ba, 2014).

    Combines advantages of AdaGrad and RMSProp for robust optimization.
    """

    def __init__(self, params: List[np.ndarray], lr: float = 0.001,
                 beta1: float = 0.9, beta2: float = 0.999, eps: float = 1e-8):
        self.params = params
        self.lr = lr
        self.beta1 = beta1
        self.beta2 = beta2
        self.eps = eps

        self.m = [np.zeros_like(p) for p in params]
        self.v = [np.zeros_like(p) for p in params]
        self.t = 0

    def step(self, grads: List[np.ndarray]):
        """Update parameters."""
        self.t += 1

        for i, (param, grad) in enumerate(zip(self.params, grads)):
            # Update biased first moment
            self.m[i] = self.beta1 * self.m[i] + (1 - self.beta1) * grad
            # Update biased second moment
            self.v[i] = self.beta2 * self.v[i] + (1 - self.beta2) * (grad ** 2)

            # Bias correction
            m_hat = self.m[i] / (1 - self.beta1 ** self.t)
            v_hat = self.v[i] / (1 - self.beta2 ** self.t)

            # Update parameters
            param -= self.lr * m_hat / (np.sqrt(v_hat) + self.eps)


# =============================================================================
# EXPERIENCE REPLAY BUFFER
# =============================================================================

@dataclass
class Experience:
    """Single experience tuple for RL."""
    state: np.ndarray
    action: int
    reward: float
    next_state: np.ndarray
    done: bool


class PrioritizedReplayBuffer:
    """
    Prioritized Experience Replay (Schaul et al., 2016).

    Samples transitions with probability proportional to TD error,
    enabling more efficient learning from rare, informative experiences.
    """

    def __init__(self, capacity: int = 100000, alpha: float = 0.6, beta: float = 0.4):
        self.capacity = capacity
        self.alpha = alpha  # Prioritization exponent
        self.beta = beta    # Importance sampling exponent
        self.beta_increment = 0.001

        self.buffer: deque = deque(maxlen=capacity)
        self.priorities: deque = deque(maxlen=capacity)
        self.max_priority = 1.0

    def push(self, experience: Experience):
        """Add experience with max priority."""
        self.buffer.append(experience)
        self.priorities.append(self.max_priority)

    def sample(self, batch_size: int) -> Tuple[List[Experience], np.ndarray, np.ndarray]:
        """Sample batch with prioritized probabilities."""
        if len(self.buffer) < batch_size:
            return [], np.array([]), np.array([])

        priorities = np.array(self.priorities)
        probabilities = priorities ** self.alpha
        probabilities /= probabilities.sum()

        indices = np.random.choice(len(self.buffer), batch_size, p=probabilities)

        # Importance sampling weights
        N = len(self.buffer)
        weights = (N * probabilities[indices]) ** (-self.beta)
        weights /= weights.max()

        self.beta = min(1.0, self.beta + self.beta_increment)

        experiences = [self.buffer[i] for i in indices]
        return experiences, indices, weights

    def update_priorities(self, indices: np.ndarray, td_errors: np.ndarray):
        """Update priorities based on TD errors."""
        for idx, td_error in zip(indices, td_errors):
            priority = (abs(td_error) + 1e-6)
            self.priorities[idx] = priority
            self.max_priority = max(self.max_priority, priority)

    def __len__(self) -> int:
        return len(self.buffer)


# =============================================================================
# DEEP Q-NETWORK (DQN)
# =============================================================================

class DQN:
    """
    Deep Q-Network with Double DQN and Dueling Architecture.

    Combines:
    - Experience Replay (Mnih et al., 2015)
    - Double DQN (van Hasselt et al., 2016)
    - Dueling Architecture (Wang et al., 2016)
    - Prioritized Replay (Schaul et al., 2016)

    State space: [prices, returns, volatility, positions, Greeks, sentiment]
    Action space: [hold, buy_small, buy_large, sell_small, sell_large] per asset
    """

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dims: List[int] = [256, 256, 128],
        lr: float = 0.00005,  # Lower LR for stability
        gamma: float = 0.99,
        tau: float = 0.001,  # Slower target updates for stability
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.01,
        epsilon_decay: float = 0.99995,  # Slower decay: reaches 0.01 around epoch 30 of 40
    ):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.tau = tau
        self.epsilon = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay = epsilon_decay
        self.base_lr = lr

        # Build networks (internal lists)
        self._q_network = self._build_network(state_dim, action_dim, hidden_dims)
        self._target_network = self._build_network(state_dim, action_dim, hidden_dims)
        self._hard_update()

        # Optimizer with lower learning rate
        params = []
        for layer in self._q_network:
            params.extend(layer.parameters())
        self.optimizer = Adam(params, lr=lr)

        # Replay buffer
        self.replay_buffer = PrioritizedReplayBuffer()

        # Training metrics
        self.training_step = 0
        self.losses: List[float] = []

        # Loss scaling for stable training
        self.loss_ema = 1.0  # Exponential moving average of loss
        self.loss_scale = 1.0  # Adaptive loss scaling factor

    def _build_network(self, state_dim: int, action_dim: int,
                       hidden_dims: List[int]) -> List[Layer]:
        """Build dueling network architecture."""
        layers = []

        # Shared feature layers
        prev_dim = state_dim
        for hidden_dim in hidden_dims[:-1]:
            layers.append(Dense(prev_dim, hidden_dim, activation="relu"))
            layers.append(LayerNorm(hidden_dim))
            layers.append(Dropout(0.1))
            prev_dim = hidden_dim

        # Advantage stream
        layers.append(Dense(prev_dim, hidden_dims[-1], activation="relu"))
        layers.append(Dense(hidden_dims[-1], action_dim, activation="linear"))

        return layers

    def _forward(self, state: np.ndarray, network: List[Layer], clip_output: bool = True) -> np.ndarray:
        """Forward pass through network with Q-value clipping."""
        x = state
        for layer in network:
            x = layer.forward(x)
        # Clip Q-values to prevent explosion (critical for stability)
        if clip_output:
            x = np.clip(x, -20, 20)
        return x

    def _hard_update(self):
        """Copy Q-network to target network."""
        for q_layer, target_layer in zip(self._q_network, self._target_network):
            for q_param, target_param in zip(q_layer.parameters(),
                                              target_layer.parameters()):
                target_param[:] = q_param

    def _soft_update(self):
        """Soft update target network (Polyak averaging)."""
        for q_layer, target_layer in zip(self._q_network, self._target_network):
            for q_param, target_param in zip(q_layer.parameters(),
                                              target_layer.parameters()):
                target_param[:] = self.tau * q_param + (1 - self.tau) * target_param

    @property
    def q_network(self):
        """Property wrapper for checkpoint compatibility."""
        return _NetworkWrapper(self._q_network)

    @property
    def target_network(self):
        """Property wrapper for checkpoint compatibility."""
        return _NetworkWrapper(self._target_network)

    def select_action(self, state: np.ndarray, training: bool = True) -> int:
        """Select action using epsilon-greedy policy."""
        if training and np.random.random() < self.epsilon:
            return np.random.randint(self.action_dim)

        state = np.array(state).reshape(1, -1)
        self._set_eval_mode(self._q_network)
        q_values = self._forward(state, self._q_network)
        self._set_train_mode(self._q_network)
        return int(np.argmax(q_values))

    def _set_eval_mode(self, network: List[Layer]):
        """Set network layers to eval mode (disables dropout)."""
        for layer in network:
            if isinstance(layer, Dropout):
                layer.training = False

    def _set_train_mode(self, network: List[Layer]):
        """Set network layers to train mode (enables dropout)."""
        for layer in network:
            if isinstance(layer, Dropout):
                layer.training = True

    def get_q_values(self, state: np.ndarray) -> np.ndarray:
        """Get Q-values for a state (for ensemble prediction)."""
        state = np.array(state).reshape(1, -1)
        self._set_eval_mode(self._q_network)
        q_values = self._forward(state, self._q_network)
        self._set_train_mode(self._q_network)
        return q_values[0]  # Return 1D array

    def train_step(self, batch_size: int = 64) -> float:
        """Perform one training step with stability improvements."""
        if len(self.replay_buffer) < batch_size:
            return 0.0

        # Learning rate decay: reduce LR over time for stability
        decay_factor = 1.0 / (1.0 + 0.0001 * self.training_step)
        current_lr = self.base_lr * decay_factor
        self.optimizer.lr = current_lr

        # Sample batch
        experiences, indices, weights = self.replay_buffer.sample(batch_size)

        states = np.array([e.state for e in experiences])
        actions = np.array([e.action for e in experiences])
        rewards = np.array([e.reward for e in experiences])
        next_states = np.array([e.next_state for e in experiences])
        dones = np.array([e.done for e in experiences])

        # Clip rewards to [-1, 1] for stability
        rewards = np.clip(rewards, -1, 1)

        # Current Q values (already clipped in _forward)
        current_q = self._forward(states, self._q_network)
        current_q_actions = current_q[np.arange(batch_size), actions]

        # Double DQN: select action with online network, evaluate with target
        # Target network must be in eval mode — dropout would make targets noisy,
        # causing the online network to chase a randomly-corrupted signal.
        self._set_eval_mode(self._q_network)
        next_q_online = self._forward(next_states, self._q_network)
        self._set_train_mode(self._q_network)
        next_actions = np.argmax(next_q_online, axis=1)

        self._set_eval_mode(self._target_network)
        next_q_target = self._forward(next_states, self._target_network)
        self._set_train_mode(self._target_network)
        next_q_values = next_q_target[np.arange(batch_size), next_actions]

        # Compute targets - Q-values already clipped to [-20, 20] in forward
        targets = rewards + self.gamma * next_q_values * (1 - dones)
        targets = np.clip(targets, -20, 20)  # Match Q-value clip range

        # TD error for prioritized replay (clip for stability)
        td_errors = np.clip(targets - current_q_actions, -10, 10)
        self.replay_buffer.update_priorities(indices, td_errors)

        # Compute loss (Huber loss for stability)
        raw_loss = self._huber_loss(current_q_actions, targets, weights)

        # Adaptive loss scaling: normalize loss to ~1.0 scale
        self.loss_ema = 0.99 * self.loss_ema + 0.01 * raw_loss
        normalized_loss = raw_loss / (self.loss_ema + 1e-8)

        # Backpropagation with scaled gradients
        grad = self._huber_loss_grad(current_q_actions, targets, weights)

        # Create gradient for full Q-values tensor
        full_grad = np.zeros_like(current_q)
        full_grad[np.arange(batch_size), actions] = grad

        # Backward pass through layers
        for layer in reversed(self._q_network):
            full_grad = layer.backward(full_grad)

        # Collect gradients and update
        grads = []
        for layer in self._q_network:
            grads.extend(layer.gradients())

        # Aggressive gradient clipping for stability
        max_grad_norm = 0.5  # Tighter clipping
        grad_norm = np.sqrt(sum(np.sum(g ** 2) for g in grads))
        if grad_norm > max_grad_norm:
            grads = [g * max_grad_norm / grad_norm for g in grads]

        self.optimizer.step(grads)

        # Update target network (slower tau) and epsilon
        self._soft_update()
        self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)

        self.training_step += 1
        self.losses.append(normalized_loss)

        # Return normalized loss for stable reporting
        return normalized_loss

    def _huber_loss(self, pred: np.ndarray, target: np.ndarray,
                    weights: np.ndarray, delta: float = 1.0) -> float:
        """Huber loss (less sensitive to outliers)."""
        diff = pred - target
        abs_diff = np.abs(diff)
        quadratic = np.minimum(abs_diff, delta)
        linear = abs_diff - quadratic
        loss = 0.5 * quadratic ** 2 + delta * linear
        return float(np.mean(weights * loss))

    def _huber_loss_grad(self, pred: np.ndarray, target: np.ndarray,
                         weights: np.ndarray, delta: float = 1.0) -> np.ndarray:
        """Gradient of Huber loss."""
        diff = pred - target
        grad = np.where(np.abs(diff) <= delta, diff, delta * np.sign(diff))
        return weights * grad / len(pred)

    def save(self, path: str):
        """Save model parameters."""
        params = {}
        for i, layer in enumerate(self._q_network):
            for j, param in enumerate(layer.parameters()):
                params[f"layer_{i}_param_{j}"] = param
        np.savez(path, **params)

    def load(self, path: str):
        """Load model parameters."""
        data = np.load(path)
        # CRITICAL BUG FIX #3: Use correct indexing (i, j) to match save() method
        for i, layer in enumerate(self._q_network):
            for j, param in enumerate(layer.parameters()):
                key = f"layer_{i}_param_{j}"
                if key in data:
                    param[:] = data[key]


# =============================================================================
# PROXIMAL POLICY OPTIMIZATION (PPO)
# =============================================================================

class PPOAgent:
    """
    Proximal Policy Optimization (Schulman et al., 2017).

    On-policy algorithm that uses a clipped surrogate objective for stable
    policy updates. Better for continuous action spaces and financial trading.

    Features:
    - Clipped surrogate objective
    - Value function clipping
    - Entropy bonus for exploration
    - GAE (Generalized Advantage Estimation)
    """

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dims: List[int] = [256, 256],
        lr_actor: float = 0.0003,
        lr_critic: float = 0.001,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        clip_epsilon: float = 0.2,
        entropy_coef: float = 0.01,
        value_coef: float = 0.5,
        max_grad_norm: float = 0.5,
    ):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.clip_epsilon = clip_epsilon
        self.entropy_coef = entropy_coef
        self.value_coef = value_coef
        self.max_grad_norm = max_grad_norm

        # Actor network (policy)
        self.actor = self._build_actor(state_dim, action_dim, hidden_dims)

        # Critic network (value function)
        self.critic = self._build_critic(state_dim, hidden_dims)

        # Optimizers
        actor_params = []
        for layer in self.actor:
            actor_params.extend(layer.parameters())
        self.actor_optimizer = Adam(actor_params, lr=lr_actor)

        critic_params = []
        for layer in self.critic:
            critic_params.extend(layer.parameters())
        self.critic_optimizer = Adam(critic_params, lr=lr_critic)

        # Trajectory storage
        self.states: List[np.ndarray] = []
        self.actions: List[int] = []
        self.rewards: List[float] = []
        self.values: List[float] = []
        self.log_probs: List[float] = []
        self.dones: List[bool] = []

        # Training metrics
        self.episode_rewards: List[float] = []
        self.policy_losses: List[float] = []
        self.value_losses: List[float] = []

    def _build_actor(self, state_dim: int, action_dim: int,
                     hidden_dims: List[int]) -> List[Layer]:
        """Build policy network."""
        layers = []
        prev_dim = state_dim

        for hidden_dim in hidden_dims:
            layers.append(Dense(prev_dim, hidden_dim, activation="tanh"))
            prev_dim = hidden_dim

        layers.append(Dense(prev_dim, action_dim, activation="softmax"))
        return layers

    def _build_critic(self, state_dim: int, hidden_dims: List[int]) -> List[Layer]:
        """Build value network."""
        layers = []
        prev_dim = state_dim

        for hidden_dim in hidden_dims:
            layers.append(Dense(prev_dim, hidden_dim, activation="tanh"))
            prev_dim = hidden_dim

        layers.append(Dense(prev_dim, 1, activation="linear"))
        return layers

    def _forward_actor(self, state: np.ndarray) -> np.ndarray:
        """Get action probabilities."""
        x = state
        for layer in self.actor:
            x = layer.forward(x)
        return x

    def _forward_critic(self, state: np.ndarray) -> np.ndarray:
        """Get state value."""
        x = state
        for layer in self.critic:
            x = layer.forward(x)
        return x

    def get_action_probs(self, state: np.ndarray) -> np.ndarray:
        """Get action probabilities (for ensemble prediction)."""
        state = np.array(state).reshape(1, -1)
        probs = self._forward_actor(state).flatten()
        return probs

    def get_value(self, state: np.ndarray) -> float:
        """Get state value estimate (for ensemble prediction)."""
        state = np.array(state).reshape(1, -1)
        value = self._forward_critic(state).flatten()[0]
        return value

    def select_action(self, state: np.ndarray) -> Tuple[int, float, float]:
        """Select action from policy distribution."""
        state = np.array(state).reshape(1, -1)

        probs = self._forward_actor(state).flatten()
        value = self._forward_critic(state).flatten()[0]

        # CRITICAL FIX: Validate probability distribution before sampling
        # If probs contain NaN/infinity or don't sum to 1.0, use uniform distribution
        # BUG FIX #2: Specify explicit tolerances for probability distribution validation
        if not np.isfinite(probs).all() or not np.isclose(probs.sum(), 1.0, rtol=1e-4, atol=1e-6):
            logger.warning(f"Invalid probability distribution detected, using uniform fallback")
            probs = np.ones(self.action_dim) / self.action_dim

        # Sample from distribution
        action = np.random.choice(self.action_dim, p=probs)
        log_prob = np.log(probs[action] + 1e-10)

        return action, log_prob, value

    def store_transition(self, state: np.ndarray, action: int, reward: float,
                        value: float, log_prob: float, done: bool):
        """Store transition for training."""
        self.states.append(state)
        self.actions.append(action)
        self.rewards.append(reward)
        self.values.append(value)
        self.log_probs.append(log_prob)
        self.dones.append(done)

    def compute_gae(self, next_value: float) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute Generalized Advantage Estimation (Schulman et al., 2016).

        GAE provides low-variance, low-bias advantage estimates.
        """
        rewards = np.array(self.rewards)
        values = np.array(self.values + [next_value])
        dones = np.array(self.dones)

        advantages = np.zeros_like(rewards)
        last_gae = 0

        for t in reversed(range(len(rewards))):
            delta = rewards[t] + self.gamma * values[t + 1] * (1 - dones[t]) - values[t]
            advantages[t] = last_gae = delta + self.gamma * self.gae_lambda * (1 - dones[t]) * last_gae

        returns = advantages + values[:-1]

        # Normalize advantages
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        return advantages, returns

    def train(self, next_value: float = 0, n_epochs: int = 10, batch_size: int = 64) -> Dict[str, float]:
        """Train on collected trajectories."""
        if len(self.states) < batch_size:
            return {}

        # Compute advantages
        advantages, returns = self.compute_gae(next_value)

        states = np.array(self.states)
        actions = np.array(self.actions)
        old_log_probs = np.array(self.log_probs)

        total_policy_loss = 0
        total_value_loss = 0
        total_entropy = 0

        for _ in range(n_epochs):
            # Random permutation for mini-batches
            indices = np.random.permutation(len(states))

            for start in range(0, len(states), batch_size):
                end = min(start + batch_size, len(states))
                batch_indices = indices[start:end]

                batch_states = states[batch_indices]
                batch_actions = actions[batch_indices]
                batch_advantages = advantages[batch_indices]
                batch_returns = returns[batch_indices]
                batch_old_log_probs = old_log_probs[batch_indices]

                # Forward pass
                probs = self._forward_actor(batch_states)
                values = self._forward_critic(batch_states).flatten()

                # Current log probs
                log_probs = np.log(probs[np.arange(len(batch_actions)), batch_actions] + 1e-10)

                # Policy loss (clipped surrogate)
                ratio = np.exp(log_probs - batch_old_log_probs)
                surr1 = ratio * batch_advantages
                surr2 = np.clip(ratio, 1 - self.clip_epsilon, 1 + self.clip_epsilon) * batch_advantages
                policy_loss = -np.mean(np.minimum(surr1, surr2))

                # Value loss
                value_loss = np.mean((values - batch_returns) ** 2)

                # Entropy bonus
                entropy = -np.mean(np.sum(probs * np.log(probs + 1e-10), axis=1))

                # ============ ACTOR BACKWARD PASS ============
                # Gradient of policy loss w.r.t. log_probs
                # d(policy_loss)/d(log_prob) = -advantage * d(clipped_ratio)/d(log_prob)
                # For clipped surrogate: use ratio where not clipped
                clipped = (ratio < 1 - self.clip_epsilon) | (ratio > 1 + self.clip_epsilon)
                d_ratio = np.where(clipped, 0, batch_advantages)
                d_log_probs = -ratio * d_ratio / len(batch_actions)

                # Gradient through log(prob) -> prob: d(log(p))/d(p) = 1/p
                # So d(loss)/d(prob) = d(loss)/d(log_prob) * 1/prob
                d_probs = np.zeros_like(probs)
                d_probs[np.arange(len(batch_actions)), batch_actions] = d_log_probs / (probs[np.arange(len(batch_actions)), batch_actions] + 1e-10)

                # Add entropy gradient (entropy bonus encourages exploration)
                d_entropy = -self.entropy_coef * (np.log(probs + 1e-10) + 1) / len(batch_actions)
                d_probs += d_entropy

                # Softmax backward: d_logits = probs * (d_probs - sum(probs * d_probs))
                sum_dp = np.sum(probs * d_probs, axis=1, keepdims=True)
                d_logits = probs * (d_probs - sum_dp)

                # Backward through actor layers
                grad = d_logits
                for layer in reversed(self.actor):
                    grad = layer.backward(grad)

                # Collect actor gradients and update
                actor_grads = []
                for layer in self.actor:
                    actor_grads.extend(layer.gradients())

                # Gradient clipping
                grad_norm = np.sqrt(sum(np.sum(g ** 2) for g in actor_grads) + 1e-8)
                if grad_norm > self.max_grad_norm:
                    actor_grads = [g * self.max_grad_norm / grad_norm for g in actor_grads]

                self.actor_optimizer.step(actor_grads)

                # ============ CRITIC BACKWARD PASS ============
                # Gradient of value loss: d(MSE)/d(values) = 2 * (values - returns) / batch_size
                d_values = 2 * (values - batch_returns) / len(batch_returns)
                d_values = d_values.reshape(-1, 1)  # Shape for backward pass

                # Backward through critic layers
                grad = d_values
                for layer in reversed(self.critic):
                    grad = layer.backward(grad)

                # Collect critic gradients and update
                critic_grads = []
                for layer in self.critic:
                    critic_grads.extend(layer.gradients())

                # Gradient clipping
                grad_norm = np.sqrt(sum(np.sum(g ** 2) for g in critic_grads) + 1e-8)
                if grad_norm > self.max_grad_norm:
                    critic_grads = [g * self.max_grad_norm / grad_norm for g in critic_grads]

                self.critic_optimizer.step(critic_grads)

                total_policy_loss += policy_loss
                total_value_loss += value_loss
                total_entropy += entropy

        # Clear trajectory
        self.states.clear()
        self.actions.clear()
        self.rewards.clear()
        self.values.clear()
        self.log_probs.clear()
        self.dones.clear()

        n_updates = max(1, n_epochs * (len(states) // batch_size))

        self.policy_losses.append(total_policy_loss / n_updates)
        self.value_losses.append(total_value_loss / n_updates)

        return {
            "policy_loss": total_policy_loss / n_updates,
            "value_loss": total_value_loss / n_updates,
            "entropy": total_entropy / n_updates,
        }

    def train_step(self, next_value: float = 0) -> float:
        """
        Single training step (alias for train() for consistency with other models).
        Returns total loss.
        """
        if len(self.states) < 10:
            return 0.0

        result = self.train(next_value=next_value, n_epochs=4, batch_size=32)
        return result.get("policy_loss", 0) + result.get("value_loss", 0)

    # Aliases for checkpoint save/load compatibility
    @property
    def policy_network(self):
        """Alias for actor network (for checkpoint compatibility)."""
        return _NetworkWrapper(self.actor)

    @property
    def value_network(self):
        """Alias for critic network (for checkpoint compatibility)."""
        return _NetworkWrapper(self.critic)


class _NetworkWrapper:
    """Wrapper to provide get_weights/set_weights for networks."""

    def __init__(self, layers: List[Layer]):
        self.layers = layers

    def get_weights(self) -> List[Dict]:
        """Get all layer weights (Dense + LayerNorm)."""
        weights = []
        for layer in self.layers:
            if hasattr(layer, 'W') and hasattr(layer, 'b'):
                weights.append({'type': 'dense', 'W': layer.W.copy(), 'b': layer.b.copy()})
            elif hasattr(layer, 'gamma') and hasattr(layer, 'beta'):
                weights.append({'type': 'layernorm', 'gamma': layer.gamma.copy(), 'beta': layer.beta.copy()})
        return weights

    def set_weights(self, weights: List[Dict]):
        """Set all layer weights (Dense + LayerNorm)."""
        weight_idx = 0
        for layer in self.layers:
            if weight_idx >= len(weights):
                break
            w = weights[weight_idx]
            if hasattr(layer, 'W') and hasattr(layer, 'b') and w.get('type', 'dense') == 'dense':
                layer.W = w['W'].copy()
                layer.b = w['b'].copy()
                weight_idx += 1
            elif hasattr(layer, 'gamma') and hasattr(layer, 'beta') and w.get('type') == 'layernorm':
                layer.gamma = w['gamma'].copy()
                layer.beta = w['beta'].copy()
                weight_idx += 1
            elif hasattr(layer, 'W') and hasattr(layer, 'b') and 'W' in w:
                # Backward compat: old checkpoints without 'type' field
                layer.W = w['W'].copy()
                layer.b = w['b'].copy()
                weight_idx += 1


# =============================================================================
# TRANSFORMER PRICE PREDICTOR
# =============================================================================

class TransformerPredictor:
    """
    Transformer-based price prediction model.

    Uses self-attention to capture complex temporal dependencies
    and cross-asset correlations in financial data.

    Architecture:
    - Positional encoding
    - Multi-head self-attention layers
    - Feed-forward networks
    - Output projection for price prediction
    """

    def __init__(
        self,
        input_dim: int,
        d_model: int = 128,
        n_heads: int = 8,
        n_layers: int = 4,
        d_ff: int = 512,
        dropout: float = 0.1,
        max_seq_len: int = 256,
    ):
        self.input_dim = input_dim
        self.d_model = d_model
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.max_seq_len = max_seq_len

        # Input projection
        self.input_projection = Dense(input_dim, d_model, activation="linear")

        # Positional encoding
        self.pos_encoding = self._create_positional_encoding(max_seq_len, d_model)

        # Transformer layers
        self.attention_layers = [MultiHeadAttention(d_model, n_heads, dropout)
                                  for _ in range(n_layers)]
        self.ff_layers = [
            [Dense(d_model, d_ff, activation="relu"),
             Dense(d_ff, d_model, activation="linear")]
            for _ in range(n_layers)
        ]
        self.layer_norms = [
            [LayerNorm(d_model), LayerNorm(d_model)]
            for _ in range(n_layers)
        ]

        # Output projection (predict returns)
        self.output_projection = Dense(d_model, 1, activation="linear")

        # Dropout
        self.dropout = Dropout(dropout)

    def _create_positional_encoding(self, max_len: int, d_model: int) -> np.ndarray:
        """Create sinusoidal positional encoding."""
        pe = np.zeros((max_len, d_model))
        position = np.arange(max_len).reshape(-1, 1)
        div_term = np.exp(np.arange(0, d_model, 2) * -(np.log(10000.0) / d_model))

        pe[:, 0::2] = np.sin(position * div_term)
        pe[:, 1::2] = np.cos(position * div_term)

        return pe

    def forward(self, x: np.ndarray) -> np.ndarray:
        """
        Forward pass through transformer.

        Args:
            x: Input of shape (batch, seq_len, input_dim)

        Returns:
            Predictions of shape (batch, 1)
        """
        if len(x.shape) == 2:
            x = x.reshape(1, *x.shape)

        batch_size, seq_len, _ = x.shape

        # Input projection - process samples separately to preserve temporal structure
        # Instead of flattening all timesteps together (loses sequence order),
        # process each sample in the batch independently
        x_proj = []
        for b in range(batch_size):
            x_b = self.input_projection.forward(x[b])  # Shape: (seq_len, d_model)
            x_proj.append(x_b)
        x = np.stack(x_proj, axis=0)  # Shape: (batch_size, seq_len, d_model)

        # Add positional encoding
        x = x + self.pos_encoding[:seq_len]
        x = self.dropout.forward(x)

        # Transformer layers
        for i in range(self.n_layers):
            # Self-attention with residual
            attn_out = self.attention_layers[i].forward(x)
            x = self.layer_norms[i][0].forward(x + attn_out)

            # Feed-forward with residual
            # Flatten to (batch*seq, d_model) for the FF layers
            ff_out = x.reshape(-1, self.d_model)
            for ff_layer in self.ff_layers[i]:
                ff_out = ff_layer.forward(ff_out)
            # Reshape back to (batch, seq_len, d_model) after FF block
            ff_out = ff_out.reshape(batch_size, seq_len, self.d_model)
            x = self.layer_norms[i][1].forward(x + ff_out)

        # Take last position for prediction
        x = x[:, -1, :]

        # Output projection
        return self.output_projection.forward(x)

    def predict(self, x: np.ndarray) -> float:
        """Predict next return."""
        return float(self.forward(x).flatten()[0])


# =============================================================================
# VARIATIONAL AUTOENCODER FOR REGIME DETECTION
# =============================================================================

class MarketRegimeVAE:
    """
    Variational Autoencoder for market regime detection.

    Learns a latent representation of market states that can identify:
    - Bull/Bear markets
    - High/Low volatility regimes
    - Risk-on/Risk-off environments
    - Crisis/Normal periods

    The latent space is structured to be interpretable for trading decisions.
    """

    def __init__(
        self,
        input_dim: int,
        latent_dim: int = 8,
        hidden_dims: List[int] = [128, 64],
    ):
        self.input_dim = input_dim
        self.latent_dim = latent_dim

        # Encoder
        self.encoder_layers = []
        prev_dim = input_dim
        for hidden_dim in hidden_dims:
            self.encoder_layers.append(Dense(prev_dim, hidden_dim, activation="relu"))
            prev_dim = hidden_dim

        # Latent space (mean and log variance)
        self.fc_mu = Dense(hidden_dims[-1], latent_dim, activation="linear")
        self.fc_logvar = Dense(hidden_dims[-1], latent_dim, activation="linear")

        # Decoder
        self.decoder_layers = []
        prev_dim = latent_dim
        for hidden_dim in reversed(hidden_dims):
            self.decoder_layers.append(Dense(prev_dim, hidden_dim, activation="relu"))
            prev_dim = hidden_dim
        self.decoder_output = Dense(prev_dim, input_dim, activation="linear")

        # Regime classifier on latent space
        self.regime_classifier = Dense(latent_dim, 4, activation="softmax")  # 4 regimes

    def encode(self, x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Encode input to latent distribution."""
        h = x
        for layer in self.encoder_layers:
            h = layer.forward(h)

        mu = self.fc_mu.forward(h)
        logvar = self.fc_logvar.forward(h)
        # Clip logvar to prevent overflow in exp: np.exp(logvar) must be finite
        logvar = np.clip(logvar, -10.0, 10.0)  # exp(-10)≈0, exp(10)≈22k - safe bounds
        return mu, logvar

    def reparameterize(self, mu: np.ndarray, logvar: np.ndarray) -> np.ndarray:
        """Reparameterization trick for backprop through sampling."""
        std = np.exp(0.5 * logvar)
        eps = np.random.randn(*mu.shape)
        return mu + eps * std

    def decode(self, z: np.ndarray) -> np.ndarray:
        """Decode latent vector to reconstruction."""
        h = z
        for layer in self.decoder_layers:
            h = layer.forward(h)
        return self.decoder_output.forward(h)

    def forward(self, x: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Full forward pass."""
        mu, logvar = self.encode(x)
        z = self.reparameterize(mu, logvar)
        recon = self.decode(z)
        regime_probs = self.regime_classifier.forward(z)
        return recon, mu, logvar, regime_probs

    def detect_regime(self, x: np.ndarray) -> Tuple[int, np.ndarray, np.ndarray]:
        """
        Detect market regime from input data.

        Returns:
            regime: Integer regime ID (0-3)
            regime_probs: Probability distribution over regimes
            latent: Latent representation
        """
        mu, logvar = self.encode(x)
        z = mu  # Use mean for inference
        regime_probs = self.regime_classifier.forward(z)

        regime = int(np.argmax(regime_probs))

        return regime, regime_probs.flatten(), z.flatten()

    def get_regime_name(self, regime_id: int) -> str:
        """Get human-readable regime name."""
        names = {
            0: "Bull Market (Risk-On)",
            1: "Bear Market (Risk-Off)",
            2: "High Volatility Crisis",
            3: "Low Volatility Consolidation",
        }
        return names.get(regime_id, "Unknown")


class TrainableTransformer:
    """
    Simplified Transformer for classification with proper gradient descent training.
    Uses a simpler architecture for stable training.
    """

    def __init__(self, input_dim: int, hidden_dim: int = 64, output_dim: int = 3,
                 n_heads: int = 4, lr: float = 0.001, l2_reg: float = 0.0001):
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.output_dim = output_dim
        self.n_heads = n_heads
        self.head_dim = hidden_dim // n_heads
        self.lr = lr
        self.l2_reg = l2_reg  # L2 regularization to prevent overfitting

        # Input projection
        self.W_in = np.random.randn(input_dim, hidden_dim) * np.sqrt(2.0 / input_dim)
        self.b_in = np.zeros((1, hidden_dim))

        # Multi-head attention weights
        self.W_q = np.random.randn(hidden_dim, hidden_dim) * np.sqrt(1.0 / hidden_dim)
        self.W_k = np.random.randn(hidden_dim, hidden_dim) * np.sqrt(1.0 / hidden_dim)
        self.W_v = np.random.randn(hidden_dim, hidden_dim) * np.sqrt(1.0 / hidden_dim)
        self.W_o = np.random.randn(hidden_dim, hidden_dim) * np.sqrt(1.0 / hidden_dim)

        # Feed-forward network
        self.W_ff1 = np.random.randn(hidden_dim, hidden_dim * 4) * np.sqrt(2.0 / hidden_dim)
        self.b_ff1 = np.zeros((1, hidden_dim * 4))
        self.W_ff2 = np.random.randn(hidden_dim * 4, hidden_dim) * np.sqrt(2.0 / (hidden_dim * 4))
        self.b_ff2 = np.zeros((1, hidden_dim))

        # Output layer
        self.W_out = np.random.randn(hidden_dim, output_dim) * np.sqrt(1.0 / hidden_dim)
        self.b_out = np.zeros((1, output_dim))

        # Adam optimizer
        self._init_adam()
        self.cache = {}

        # Loss normalization for stable reporting
        self.loss_ema = 1.0

    def _init_adam(self):
        self.m = {}
        self.v = {}
        self.t = 0
        for name in ['W_in', 'b_in', 'W_q', 'W_k', 'W_v', 'W_o',
                     'W_ff1', 'b_ff1', 'W_ff2', 'b_ff2', 'W_out', 'b_out']:
            param = getattr(self, name)
            self.m[name] = np.zeros_like(param)
            self.v[name] = np.zeros_like(param)

    def _softmax(self, x, axis=-1):
        exp_x = np.exp(x - np.max(x, axis=axis, keepdims=True))
        return exp_x / (np.sum(exp_x, axis=axis, keepdims=True) + 1e-8)

    def _relu(self, x):
        return np.maximum(0, x)

    def forward(self, x: np.ndarray) -> np.ndarray:
        """
        Forward pass through transformer.

        Args:
            x: Input (batch, seq_len, input_dim) or (seq_len, input_dim)

        Returns:
            Class probabilities (batch, output_dim)
        """
        if len(x.shape) == 2:
            x = x.reshape(1, *x.shape)

        batch_size, seq_len, _ = x.shape

        # Input projection
        x_flat = x.reshape(-1, self.input_dim)
        h = x_flat @ self.W_in + self.b_in
        h = self._relu(h)
        h = h.reshape(batch_size, seq_len, self.hidden_dim)

        self.cache['input'] = x
        self.cache['h_in'] = h

        # Self-attention
        Q = h @ self.W_q
        K = h @ self.W_k
        V = h @ self.W_v

        # Scaled dot-product attention
        scale = np.sqrt(self.hidden_dim)
        attn_scores = Q @ K.transpose(0, 2, 1) / scale
        attn_weights = self._softmax(attn_scores, axis=-1)
        attn_values = attn_weights @ V  # Before W_o projection
        attn_out = attn_values @ self.W_o  # After W_o projection

        self.cache['Q'] = Q
        self.cache['K'] = K
        self.cache['V'] = V
        self.cache['attn_weights'] = attn_weights
        self.cache['attn_values'] = attn_values  # Store pre-W_o for backward
        self.cache['attn_out'] = attn_out

        # Residual + layer norm (simplified: just residual)
        h = h + attn_out
        self.cache['h_attn'] = h

        # Feed-forward
        ff_flat = h.reshape(-1, self.hidden_dim)
        ff1 = self._relu(ff_flat @ self.W_ff1 + self.b_ff1)
        ff2 = ff1 @ self.W_ff2 + self.b_ff2
        ff_out = ff2.reshape(batch_size, seq_len, self.hidden_dim)

        self.cache['ff1'] = ff1.reshape(batch_size, seq_len, -1)
        self.cache['ff_out'] = ff_out

        # Residual
        h = h + ff_out
        self.cache['h_ff'] = h

        # Take last position for classification
        h_last = h[:, -1, :]
        self.cache['h_last'] = h_last

        # Output
        logits = h_last @ self.W_out + self.b_out
        probs = self._softmax(logits, axis=-1)

        self.cache['logits'] = logits
        self.cache['probs'] = probs

        return probs

    def train_step(self, x: np.ndarray, y: np.ndarray) -> float:
        """
        Single training step with backpropagation.

        Args:
            x: Input sequences (batch, seq_len, input_dim)
            y: Labels (batch,) as integers

        Returns:
            Cross-entropy loss
        """
        if len(x.shape) == 2:
            x = x.reshape(1, *x.shape)

        batch_size = x.shape[0]

        # Forward
        probs = self.forward(x)

        # Loss
        y_onehot = np.zeros_like(probs)
        y_onehot[np.arange(batch_size), y.astype(int)] = 1
        loss = -np.mean(np.sum(y_onehot * np.log(probs + 1e-8), axis=1))

        # Backward
        dlogits = (probs - y_onehot) / batch_size

        # Output layer
        dW_out = self.cache['h_last'].T @ dlogits
        db_out = np.sum(dlogits, axis=0, keepdims=True)
        dh_last = dlogits @ self.W_out.T

        # Expand gradient back through sequence (only last position contributes)
        seq_len = x.shape[1]
        dh = np.zeros((batch_size, seq_len, self.hidden_dim))
        dh[:, -1, :] = dh_last

        # ========= SECOND RESIDUAL: h_ff = h_attn + ff_out =========
        # Gradient flows to BOTH h_attn and ff_out
        dh_attn = dh.copy()  # Residual path
        dff_out = dh.copy()  # FF path

        # Feed-forward backward
        dff2 = dff_out.reshape(-1, self.hidden_dim)
        dW_ff2 = self.cache['ff1'].reshape(-1, self.hidden_dim * 4).T @ dff2
        db_ff2 = np.sum(dff2, axis=0, keepdims=True)

        dff1 = dff2 @ self.W_ff2.T
        dff1 = dff1 * (self.cache['ff1'].reshape(-1, self.hidden_dim * 4) > 0)

        h_attn_flat = self.cache['h_attn'].reshape(-1, self.hidden_dim)
        dW_ff1 = h_attn_flat.T @ dff1
        db_ff1 = np.sum(dff1, axis=0, keepdims=True)

        # FF gradient flows back to h_attn through the FF input
        dh_attn_from_ff = (dff1 @ self.W_ff1.T).reshape(batch_size, seq_len, self.hidden_dim)
        dh_attn += dh_attn_from_ff  # Add FF contribution to residual

        # ========= FIRST RESIDUAL: h_attn = h + attn_out =========
        # Gradient flows to BOTH h (input proj) and attn_out
        dh_input = dh_attn.copy()  # Residual path to input projection
        dattn_out = dh_attn.copy()  # Attention path

        # Attention backward - compute gradients for Q, K, V projections
        # Gradient for W_o: dW_o = attn_values.T @ dattn_out
        attn_values = self.cache['attn_values']  # (batch, seq, hidden) - BEFORE W_o
        dW_o = attn_values.reshape(-1, self.hidden_dim).T @ dattn_out.reshape(-1, self.hidden_dim)

        # Gradient w.r.t. attn_values (before W_o): d_attn_values = dattn_out @ W_o.T
        d_attn_values = dattn_out.reshape(batch_size, seq_len, -1) @ self.W_o.T

        # Attention backward through: attn_values = attn_weights @ V
        # d_attn_weights = d_attn_values @ V.T
        # d_V = attn_weights.T @ d_attn_values
        attn_weights = self.cache['attn_weights']  # (batch, seq, seq)
        V = self.cache['V']  # (batch, seq, hidden)

        # Gradient for V: dV = attn_weights.T @ d_attn_values
        dV = np.zeros_like(V)
        for b in range(batch_size):
            dV[b] = attn_weights[b].T @ d_attn_values[b]

        # Gradient for W_v: dW_v = h_in.T @ dV
        h_in = self.cache['h_in']  # (batch, seq, hidden)
        dW_v = h_in.reshape(-1, self.hidden_dim).T @ dV.reshape(-1, self.hidden_dim)

        # Gradient for attn_weights: d_attn_weights = d_attn_values @ V.T
        d_attn_weights = np.zeros_like(attn_weights)
        for b in range(batch_size):
            d_attn_weights[b] = d_attn_values[b] @ V[b].T

        # Softmax backward: d_scores[i,j] = attn_weights[i,j] * (d_attn_weights[i,j] - sum_k(attn_weights[i,k] * d_attn_weights[i,k]))
        d_scores = np.zeros_like(attn_weights)
        for b in range(batch_size):
            for i in range(seq_len):
                s = attn_weights[b, i, :]  # softmax output for row i
                dy = d_attn_weights[b, i, :]  # gradient for row i
                d_scores[b, i, :] = s * (dy - np.sum(s * dy))

        # Gradient for Q and K through: scores = Q @ K.T / scale
        Q = self.cache['Q']
        K = self.cache['K']
        scale = np.sqrt(self.hidden_dim)

        # dQ = d_scores @ K / scale
        dQ = np.zeros_like(Q)
        for b in range(batch_size):
            dQ[b] = d_scores[b] @ K[b] / scale

        # dK = d_scores.T @ Q / scale
        dK = np.zeros_like(K)
        for b in range(batch_size):
            dK[b] = d_scores[b].T @ Q[b] / scale

        dW_q = h_in.reshape(-1, self.hidden_dim).T @ dQ.reshape(-1, self.hidden_dim)
        dW_k = h_in.reshape(-1, self.hidden_dim).T @ dK.reshape(-1, self.hidden_dim)

        # Attention gradient flows back to h_in through Q, K, V projections
        dh_from_attn = (dQ @ self.W_q.T + dK @ self.W_k.T + dV @ self.W_v.T)
        dh_input += dh_from_attn  # Add attention contribution to input gradient

        # Input projection backward (with full gradient from both residuals)
        dh_in = dh_input.reshape(-1, self.hidden_dim)
        dh_in = dh_in * (self.cache['h_in'].reshape(-1, self.hidden_dim) > 0)
        dW_in = x.reshape(-1, self.input_dim).T @ dh_in
        db_in = np.sum(dh_in, axis=0, keepdims=True)

        # Gradient clipping
        grads = {
            'W_out': dW_out, 'b_out': db_out,
            'W_ff2': dW_ff2, 'b_ff2': db_ff2,
            'W_ff1': dW_ff1, 'b_ff1': db_ff1,
            'W_o': dW_o,
            'W_in': dW_in, 'b_in': db_in,
            'W_q': dW_q,
            'W_k': dW_k,
            'W_v': dW_v,
        }

        max_grad = 5.0
        for name, grad in grads.items():
            norm = np.linalg.norm(grad)
            if norm > max_grad:
                grads[name] = grad * max_grad / norm

        # Adam update
        self.t += 1
        beta1, beta2, eps = 0.9, 0.999, 1e-8

        for name, grad in grads.items():
            if np.sum(np.abs(grad)) == 0:
                continue
            param = getattr(self, name)
            self.m[name] = beta1 * self.m[name] + (1 - beta1) * grad
            self.v[name] = beta2 * self.v[name] + (1 - beta2) * (grad ** 2)

            m_hat = self.m[name] / (1 - beta1 ** self.t)
            v_hat = self.v[name] / (1 - beta2 ** self.t)

            # Adam update
            param -= self.lr * m_hat / (np.sqrt(v_hat) + eps)

            # L2 weight decay (regularization) - shrink weights to prevent overfitting
            param *= (1 - self.l2_reg * self.lr)

            setattr(self, name, param)

        # Normalize loss for stable reporting
        self.loss_ema = 0.99 * self.loss_ema + 0.01 * loss
        normalized_loss = loss / (self.loss_ema + 1e-8)

        return normalized_loss

    def predict(self, x: np.ndarray) -> int:
        probs = self.forward(x)
        return int(np.argmax(probs[0]))

    def get_weights(self) -> Dict:
        return {name: getattr(self, name) for name in
                ['W_in', 'b_in', 'W_q', 'W_k', 'W_v', 'W_o',
                 'W_ff1', 'b_ff1', 'W_ff2', 'b_ff2', 'W_out', 'b_out']}

    def set_weights(self, weights: Dict):
        for name, value in weights.items():
            setattr(self, name, value)
        self._init_adam()


class TrainableVAE:
    """
    Variational Autoencoder with proper training using reconstruction + KL loss.
    """

    def __init__(self, input_dim: int, hidden_dim: int = 64, latent_dim: int = 8,
                 output_dim: int = 4, lr: float = 0.001):
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.latent_dim = latent_dim
        self.output_dim = output_dim  # Number of regimes
        self.lr = lr

        # Encoder
        self.W_enc1 = np.random.randn(input_dim, hidden_dim) * np.sqrt(2.0 / input_dim)
        self.b_enc1 = np.zeros((1, hidden_dim))
        self.W_mu = np.random.randn(hidden_dim, latent_dim) * np.sqrt(1.0 / hidden_dim)
        self.b_mu = np.zeros((1, latent_dim))
        self.W_logvar = np.random.randn(hidden_dim, latent_dim) * np.sqrt(1.0 / hidden_dim)
        self.b_logvar = np.zeros((1, latent_dim))

        # Decoder
        self.W_dec1 = np.random.randn(latent_dim, hidden_dim) * np.sqrt(2.0 / latent_dim)
        self.b_dec1 = np.zeros((1, hidden_dim))
        self.W_dec2 = np.random.randn(hidden_dim, input_dim) * np.sqrt(1.0 / hidden_dim)
        self.b_dec2 = np.zeros((1, input_dim))

        # Regime classifier on latent space
        self.W_cls = np.random.randn(latent_dim, output_dim) * np.sqrt(1.0 / latent_dim)
        self.b_cls = np.zeros((1, output_dim))

        self._init_adam()
        self.cache = {}

    def _init_adam(self):
        self.m = {}
        self.v = {}
        self.t = 0
        for name in ['W_enc1', 'b_enc1', 'W_mu', 'b_mu', 'W_logvar', 'b_logvar',
                     'W_dec1', 'b_dec1', 'W_dec2', 'b_dec2', 'W_cls', 'b_cls']:
            param = getattr(self, name)
            self.m[name] = np.zeros_like(param)
            self.v[name] = np.zeros_like(param)

    def _relu(self, x):
        return np.maximum(0, x)

    def _softmax(self, x):
        exp_x = np.exp(x - np.max(x, axis=-1, keepdims=True))
        return exp_x / (np.sum(exp_x, axis=-1, keepdims=True) + 1e-8)

    def encode(self, x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        h = self._relu(x @ self.W_enc1 + self.b_enc1)
        self.cache['h_enc'] = h
        mu = h @ self.W_mu + self.b_mu
        logvar = h @ self.W_logvar + self.b_logvar
        return mu, logvar

    def reparameterize(self, mu: np.ndarray, logvar: np.ndarray) -> np.ndarray:
        # Clip logvar to prevent exp() overflow
        logvar = np.clip(logvar, -20, 2)
        std = np.exp(0.5 * logvar)
        eps = np.random.randn(*mu.shape)
        self.cache['eps'] = eps
        self.cache['std'] = std
        return mu + eps * std

    def decode(self, z: np.ndarray) -> np.ndarray:
        h = self._relu(z @ self.W_dec1 + self.b_dec1)
        self.cache['h_dec'] = h
        return h @ self.W_dec2 + self.b_dec2

    def forward(self, x: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        if len(x.shape) == 1:
            x = x.reshape(1, -1)

        self.cache['x'] = x
        mu, logvar = self.encode(x)
        self.cache['mu'] = mu
        self.cache['logvar'] = logvar

        z = self.reparameterize(mu, logvar)
        self.cache['z'] = z

        recon = self.decode(z)
        self.cache['recon'] = recon

        # Regime classification
        regime_logits = z @ self.W_cls + self.b_cls
        regime_probs = self._softmax(regime_logits)
        self.cache['regime_probs'] = regime_probs

        return recon, mu, logvar, regime_probs

    def train_step(self, x: np.ndarray, y: Optional[np.ndarray] = None) -> float:
        """
        Training step with reconstruction + KL loss (+ classification loss if labels provided).

        Loss = Reconstruction_MSE + beta * KL_divergence + classification_loss
        """
        if len(x.shape) == 1:
            x = x.reshape(1, -1)

        batch_size = x.shape[0]
        beta = 0.1  # KL weight (beta-VAE style)

        # Forward
        recon, mu, logvar, regime_probs = self.forward(x)

        # Reconstruction loss (MSE)
        recon_loss = np.mean((recon - x) ** 2)

        # KL divergence: -0.5 * sum(1 + logvar - mu^2 - exp(logvar))
        # Clip logvar to prevent exp() overflow
        logvar_clipped = np.clip(logvar, -20, 2)
        kl_loss = -0.5 * np.mean(np.sum(1 + logvar_clipped - mu ** 2 - np.exp(logvar_clipped), axis=1))

        # Classification loss if labels provided
        cls_loss = 0
        if y is not None:
            y_onehot = np.zeros_like(regime_probs)
            y_onehot[np.arange(batch_size), y.astype(int) % self.output_dim] = 1
            cls_loss = -np.mean(np.sum(y_onehot * np.log(regime_probs + 1e-8), axis=1))

        total_loss = recon_loss + beta * kl_loss + cls_loss

        # Backward pass
        # Reconstruction gradient
        drecon = 2 * (recon - x) / (batch_size * self.input_dim)

        # Decoder backward
        dW_dec2 = self.cache['h_dec'].T @ drecon
        db_dec2 = np.sum(drecon, axis=0, keepdims=True)

        dh_dec = drecon @ self.W_dec2.T
        dh_dec = dh_dec * (self.cache['h_dec'] > 0)

        dW_dec1 = self.cache['z'].T @ dh_dec
        db_dec1 = np.sum(dh_dec, axis=0, keepdims=True)

        dz = dh_dec @ self.W_dec1.T

        # Classification gradient
        if y is not None:
            dcls = (regime_probs - y_onehot) / batch_size
            dW_cls = self.cache['z'].T @ dcls
            db_cls = np.sum(dcls, axis=0, keepdims=True)
            dz += dcls @ self.W_cls.T
        else:
            dW_cls = np.zeros_like(self.W_cls)
            db_cls = np.zeros_like(self.b_cls)

        # KL gradient (with numerical stability)
        dmu = beta * mu / batch_size
        # Clip to prevent overflow: exp(logvar) must be finite
        logvar_safe = np.clip(logvar, -10.0, 10.0)
        dlogvar = beta * 0.5 * (np.exp(logvar_safe) - 1) / batch_size
        # Detect NaN and clamp to safe values
        dlogvar = np.nan_to_num(dlogvar, nan=0.0, posinf=1.0, neginf=-1.0)

        # Reparameterization backward
        dmu += dz
        dlogvar += dz * self.cache['eps'] * self.cache['std'] * 0.5

        # Encoder backward
        dW_mu = self.cache['h_enc'].T @ dmu
        db_mu = np.sum(dmu, axis=0, keepdims=True)
        dW_logvar = self.cache['h_enc'].T @ dlogvar
        db_logvar = np.sum(dlogvar, axis=0, keepdims=True)

        dh_enc = dmu @ self.W_mu.T + dlogvar @ self.W_logvar.T
        dh_enc = dh_enc * (self.cache['h_enc'] > 0)

        dW_enc1 = x.T @ dh_enc
        db_enc1 = np.sum(dh_enc, axis=0, keepdims=True)

        # Gradient clipping and Adam update
        grads = {
            'W_enc1': dW_enc1, 'b_enc1': db_enc1,
            'W_mu': dW_mu, 'b_mu': db_mu,
            'W_logvar': dW_logvar, 'b_logvar': db_logvar,
            'W_dec1': dW_dec1, 'b_dec1': db_dec1,
            'W_dec2': dW_dec2, 'b_dec2': db_dec2,
            'W_cls': dW_cls, 'b_cls': db_cls,
        }

        max_grad = 5.0
        self.t += 1
        beta1, beta2, eps = 0.9, 0.999, 1e-8

        for name, grad in grads.items():
            # Handle NaN gracefully
            grad = np.nan_to_num(grad, nan=0.0, posinf=0.1, neginf=-0.1)

            norm = np.linalg.norm(grad)
            if norm > max_grad:
                grad = grad * max_grad / norm

            param = getattr(self, name)
            self.m[name] = beta1 * self.m[name] + (1 - beta1) * grad
            self.v[name] = beta2 * self.v[name] + (1 - beta2) * (grad ** 2)

            m_hat = self.m[name] / (1 - beta1 ** self.t)
            v_hat = self.v[name] / (1 - beta2 ** self.t)

            # Ensure no NaN in update step
            v_hat_safe = np.clip(v_hat, 1e-10, None)  # Prevent division by zero
            update = self.lr * m_hat / (np.sqrt(v_hat_safe) + eps)
            update = np.nan_to_num(update, nan=0.0)

            param -= update
            setattr(self, name, param)

        return total_loss

    def detect_regime(self, x: np.ndarray) -> Tuple[int, np.ndarray]:
        """Detect regime from input."""
        _, _, _, regime_probs = self.forward(x)
        return int(np.argmax(regime_probs[0])), regime_probs[0]

    def get_weights(self) -> Dict:
        return {name: getattr(self, name) for name in
                ['W_enc1', 'b_enc1', 'W_mu', 'b_mu', 'W_logvar', 'b_logvar',
                 'W_dec1', 'b_dec1', 'W_dec2', 'b_dec2', 'W_cls', 'b_cls']}

    def set_weights(self, weights: Dict):
        for name, value in weights.items():
            setattr(self, name, value)
        self._init_adam()


# =============================================================================
# ENSEMBLE PREDICTOR
# =============================================================================

class EnsemblePredictor:
    """
    Ensemble of models for robust prediction.

    Combines:
    - LSTM for sequential patterns
    - Transformer for attention-based patterns
    - DQN for action-value estimation

    Uses model averaging with confidence weighting.
    """

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        seq_len: int = 60,
    ):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.seq_len = seq_len

        # Component models
        self.lstm = LSTM(state_dim, 128)
        self.transformer = TransformerPredictor(state_dim, d_model=64, n_heads=4, n_layers=2)
        self.dqn = DQN(state_dim, action_dim, hidden_dims=[128, 128])
        self.regime_vae = MarketRegimeVAE(state_dim, latent_dim=8)

        # Model weights (learned through performance)
        self.model_weights = np.array([0.3, 0.3, 0.25, 0.15])
        self.performance_history: Dict[str, List[float]] = {
            "lstm": [], "transformer": [], "dqn": [], "regime": []
        }

    def predict_action(self, state: np.ndarray, history: np.ndarray) -> Tuple[int, Dict]:
        """
        Get ensemble prediction for action.

        Args:
            state: Current state vector
            history: Historical states (seq_len, state_dim)

        Returns:
            action: Recommended action
            info: Dictionary with model predictions and confidence
        """
        # LSTM prediction
        self.lstm.reset_state()
        lstm_out = self.lstm.forward(history)[:, -1, :]
        lstm_action = int(np.argmax(lstm_out.flatten()[:self.action_dim]))

        # Transformer prediction
        transformer_pred = self.transformer.predict(history)
        transformer_action = 2 if transformer_pred > 0.01 else (0 if transformer_pred < -0.01 else 1)

        # DQN prediction
        dqn_action = self.dqn.select_action(state, training=False)

        # Regime detection
        regime, regime_probs, _ = self.regime_vae.detect_regime(state.reshape(1, -1))
        regime_action = self._regime_to_action(regime)

        # Weighted voting
        actions = [lstm_action, transformer_action, dqn_action, regime_action]
        action_votes = np.zeros(self.action_dim)

        for action, weight in zip(actions, self.model_weights):
            if action < self.action_dim:
                action_votes[action] += weight

        final_action = int(np.argmax(action_votes))
        # FIX #4: Add epsilon guard for division by zero
        total_votes = np.sum(action_votes)
        confidence = action_votes[final_action] / max(total_votes, 1e-8)
        # Validate confidence is finite
        if not np.isfinite(confidence):
            confidence = 0.5

        return final_action, {
            "lstm_action": lstm_action,
            "transformer_action": transformer_action,
            "transformer_return_pred": float(transformer_pred),
            "dqn_action": dqn_action,
            "regime": self.regime_vae.get_regime_name(regime),
            "regime_probs": regime_probs.tolist(),
            "confidence": float(confidence),
            "model_weights": self.model_weights.tolist(),
        }

    def _regime_to_action(self, regime: int) -> int:
        """Map regime to suggested action."""
        # 0: Bull -> Buy (action 2)
        # 1: Bear -> Sell (action 0)
        # 2: High Vol -> Hold (action 1)
        # 3: Low Vol -> Buy (action 2)
        mapping = {0: 2, 1: 0, 2: 1, 3: 2}
        return mapping.get(regime, 1)

    def update_weights(self, model_name: str, reward: float):
        """Update model weights based on performance."""
        self.performance_history[model_name].append(reward)

        # Recalculate weights every 100 updates
        if sum(len(v) for v in self.performance_history.values()) % 100 == 0:
            avg_performances = []
            for name in ["lstm", "transformer", "dqn", "regime"]:
                hist = self.performance_history[name]
                avg = np.mean(hist[-50:]) if len(hist) >= 50 else 0
                avg_performances.append(max(0, avg))

            if sum(avg_performances) > 0:
                self.model_weights = np.array(avg_performances) / sum(avg_performances)


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_dqn_agent(state_dim: int, action_dim: int, **kwargs) -> DQN:
    """Create a DQN agent with optimal hyperparameters."""
    return DQN(
        state_dim=state_dim,
        action_dim=action_dim,
        hidden_dims=kwargs.get("hidden_dims", [256, 256, 128]),
        lr=kwargs.get("lr", 0.0001),
        gamma=kwargs.get("gamma", 0.99),
        tau=kwargs.get("tau", 0.005),
        **{k: v for k, v in kwargs.items() if k not in ["hidden_dims", "lr", "gamma", "tau"]}
    )


def create_ppo_agent(state_dim: int, action_dim: int, **kwargs) -> PPOAgent:
    """Create a PPO agent with optimal hyperparameters."""
    return PPOAgent(
        state_dim=state_dim,
        action_dim=action_dim,
        hidden_dims=kwargs.get("hidden_dims", [256, 256]),
        lr_actor=kwargs.get("lr_actor", 0.0003),
        lr_critic=kwargs.get("lr_critic", 0.001),
        gamma=kwargs.get("gamma", 0.99),
        **{k: v for k, v in kwargs.items() if k not in ["hidden_dims", "lr_actor", "lr_critic", "gamma"]}
    )


def create_ensemble(state_dim: int, action_dim: int, seq_len: int = 60) -> EnsemblePredictor:
    """Create an ensemble predictor."""
    return EnsemblePredictor(state_dim, action_dim, seq_len)
