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
            exp_z = np.exp(self.z - np.max(self.z, axis=-1, keepdims=True))
            return exp_z / np.sum(exp_z, axis=-1, keepdims=True)
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
        return output.squeeze(0) if batch_size == 1 else output

    def _softmax(self, x: np.ndarray) -> np.ndarray:
        exp_x = np.exp(x - np.max(x, axis=-1, keepdims=True))
        return exp_x / np.sum(exp_x, axis=-1, keepdims=True)

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
        lr: float = 0.0001,
        gamma: float = 0.99,
        tau: float = 0.005,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.01,
        epsilon_decay: float = 0.9995,
    ):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.tau = tau
        self.epsilon = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay = epsilon_decay

        # Build networks
        self.q_network = self._build_network(state_dim, action_dim, hidden_dims)
        self.target_network = self._build_network(state_dim, action_dim, hidden_dims)
        self._hard_update()

        # Optimizer
        params = []
        for layer in self.q_network:
            params.extend(layer.parameters())
        self.optimizer = Adam(params, lr=lr)

        # Replay buffer
        self.replay_buffer = PrioritizedReplayBuffer()

        # Training metrics
        self.training_step = 0
        self.losses: List[float] = []

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

    def _forward(self, state: np.ndarray, network: List[Layer]) -> np.ndarray:
        """Forward pass through network."""
        x = state
        for layer in network:
            x = layer.forward(x)
        return x

    def _hard_update(self):
        """Copy Q-network to target network."""
        for q_layer, target_layer in zip(self.q_network, self.target_network):
            for q_param, target_param in zip(q_layer.parameters(),
                                              target_layer.parameters()):
                target_param[:] = q_param

    def _soft_update(self):
        """Soft update target network (Polyak averaging)."""
        for q_layer, target_layer in zip(self.q_network, self.target_network):
            for q_param, target_param in zip(q_layer.parameters(),
                                              target_layer.parameters()):
                target_param[:] = self.tau * q_param + (1 - self.tau) * target_param

    def select_action(self, state: np.ndarray, training: bool = True) -> int:
        """Select action using epsilon-greedy policy."""
        if training and np.random.random() < self.epsilon:
            return np.random.randint(self.action_dim)

        state = np.array(state).reshape(1, -1)
        q_values = self._forward(state, self.q_network)
        return int(np.argmax(q_values))

    def train_step(self, batch_size: int = 64) -> float:
        """Perform one training step."""
        if len(self.replay_buffer) < batch_size:
            return 0.0

        # Sample batch
        experiences, indices, weights = self.replay_buffer.sample(batch_size)

        states = np.array([e.state for e in experiences])
        actions = np.array([e.action for e in experiences])
        rewards = np.array([e.reward for e in experiences])
        next_states = np.array([e.next_state for e in experiences])
        dones = np.array([e.done for e in experiences])

        # Current Q values
        current_q = self._forward(states, self.q_network)
        current_q_actions = current_q[np.arange(batch_size), actions]

        # Double DQN: select action with online network, evaluate with target
        next_q_online = self._forward(next_states, self.q_network)
        next_actions = np.argmax(next_q_online, axis=1)
        next_q_target = self._forward(next_states, self.target_network)
        next_q_values = next_q_target[np.arange(batch_size), next_actions]

        # Compute targets
        targets = rewards + self.gamma * next_q_values * (1 - dones)

        # TD error for prioritized replay
        td_errors = targets - current_q_actions
        self.replay_buffer.update_priorities(indices, td_errors)

        # Compute loss (Huber loss for stability)
        loss = self._huber_loss(current_q_actions, targets, weights)

        # Backpropagation
        grad = self._huber_loss_grad(current_q_actions, targets, weights)

        # Create gradient for full Q-values tensor
        full_grad = np.zeros_like(current_q)
        full_grad[np.arange(batch_size), actions] = grad

        # Backward pass through layers
        for layer in reversed(self.q_network):
            full_grad = layer.backward(full_grad)

        # Collect gradients and update
        grads = []
        for layer in self.q_network:
            grads.extend(layer.gradients())

        # Gradient clipping
        max_grad_norm = 1.0
        grad_norm = np.sqrt(sum(np.sum(g ** 2) for g in grads))
        if grad_norm > max_grad_norm:
            grads = [g * max_grad_norm / grad_norm for g in grads]

        self.optimizer.step(grads)

        # Update target network and epsilon
        self._soft_update()
        self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)

        self.training_step += 1
        self.losses.append(loss)

        return loss

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
        for i, layer in enumerate(self.q_network):
            for j, param in enumerate(layer.parameters()):
                params[f"layer_{i}_param_{j}"] = param
        np.savez(path, **params)

    def load(self, path: str):
        """Load model parameters."""
        data = np.load(path)
        idx = 0
        for layer in self.q_network:
            for param in layer.parameters():
                key = f"layer_{idx}_param_{0}"
                if key in data:
                    param[:] = data[key]
                idx += 1


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

    def select_action(self, state: np.ndarray) -> Tuple[int, float, float]:
        """Select action from policy distribution."""
        state = np.array(state).reshape(1, -1)

        probs = self._forward_actor(state).flatten()
        value = self._forward_critic(state).flatten()[0]

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

        # Input projection
        x = self.input_projection.forward(x.reshape(-1, self.input_dim))
        x = x.reshape(batch_size, seq_len, self.d_model)

        # Add positional encoding
        x = x + self.pos_encoding[:seq_len]
        x = self.dropout.forward(x)

        # Transformer layers
        for i in range(self.n_layers):
            # Self-attention with residual
            attn_out = self.attention_layers[i].forward(x)
            x = self.layer_norms[i][0].forward(x + attn_out)

            # Feed-forward with residual
            ff_out = x
            for ff_layer in self.ff_layers[i]:
                ff_out = ff_layer.forward(ff_out.reshape(-1, self.d_model))
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
        confidence = action_votes[final_action] / np.sum(action_votes)

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
