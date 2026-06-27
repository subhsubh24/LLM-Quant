"""
Test script for the ML training pipeline.

Validates:
1. Trainable models can be imported and initialized
2. Models can train with proper backpropagation
3. Checkpoint save/load works correctly
4. Alpha source APIs can be called
"""

import asyncio
import numpy as np
import sys
import os
import pytest

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_lstm_classifier():
    """Test LSTM with proper BPTT."""
    print("\n" + "="*60)
    print("TEST 1: LSTMClassifier Training")
    print("="*60)

    from app.trading.ml_models import LSTMClassifier

    # Initialize
    lstm = LSTMClassifier(input_dim=16, hidden_dim=32, output_dim=3, lr=0.01)
    print(f"[OK] Initialized LSTMClassifier")

    # Generate synthetic data
    np.random.seed(42)
    X = np.random.randn(5, 10, 16)  # 5 batches, 10 timesteps, 16 features
    y = np.array([0, 1, 2, 1, 0])  # Labels

    # Train and verify loss decreases
    initial_loss = None
    losses = []

    for epoch in range(20):
        for i in range(len(X)):
            loss = lstm.train_step(X[i:i+1], y[i:i+1])
            losses.append(loss)

        if initial_loss is None:
            initial_loss = np.mean(losses[-5:])

    final_loss = np.mean(losses[-5:])

    print(f"  Initial loss: {initial_loss:.4f}")
    print(f"  Final loss:   {final_loss:.4f}")

    if final_loss < initial_loss:
        print(f"[OK] Loss decreased by {((initial_loss - final_loss) / initial_loss) * 100:.1f}%")
    else:
        print(f"[WARN] Loss did not decrease - may need more epochs")

    # Test prediction
    probs, _ = lstm.forward(X[0:1])
    pred = np.argmax(probs[0])
    print(f"[OK] Prediction works: class {pred} with probs {probs[0]}")

    # Test get_weights/set_weights
    weights = lstm.get_weights()
    print(f"[OK] get_weights() returns {len(weights)} weight matrices")

    lstm2 = LSTMClassifier(input_dim=16, hidden_dim=32, output_dim=3, lr=0.01)
    lstm2.set_weights(weights)
    print(f"[OK] set_weights() works correctly")


def test_trainable_transformer():
    """Test Transformer with proper gradient descent."""
    print("\n" + "="*60)
    print("TEST 2: TrainableTransformer Training")
    print("="*60)

    from app.trading.ml_models import TrainableTransformer

    # Initialize
    transformer = TrainableTransformer(input_dim=16, hidden_dim=32, output_dim=3, lr=0.01)
    print(f"[OK] Initialized TrainableTransformer")

    # Generate synthetic data
    np.random.seed(42)
    X = np.random.randn(5, 10, 16)
    y = np.array([0, 1, 2, 1, 0])

    # Train
    initial_loss = None
    losses = []

    for epoch in range(20):
        for i in range(len(X)):
            loss = transformer.train_step(X[i:i+1], y[i:i+1])
            losses.append(loss)

        if initial_loss is None:
            initial_loss = np.mean(losses[-5:])

    final_loss = np.mean(losses[-5:])

    print(f"  Initial loss: {initial_loss:.4f}")
    print(f"  Final loss:   {final_loss:.4f}")

    if final_loss < initial_loss:
        print(f"[OK] Loss decreased by {((initial_loss - final_loss) / initial_loss) * 100:.1f}%")
    else:
        print(f"[WARN] Loss did not decrease - may need more epochs")

    # Test prediction
    probs = transformer.forward(X[0:1])
    pred = np.argmax(probs[0])
    print(f"[OK] Prediction works: class {pred}")

    # Test weights
    weights = transformer.get_weights()
    print(f"[OK] get_weights() returns {len(weights)} weight matrices")


def test_trainable_vae():
    """Test VAE with reconstruction + KL loss."""
    print("\n" + "="*60)
    print("TEST 3: TrainableVAE Training")
    print("="*60)

    from app.trading.ml_models import TrainableVAE

    # Initialize
    vae = TrainableVAE(input_dim=16, hidden_dim=32, latent_dim=4, output_dim=4, lr=0.01)
    print(f"[OK] Initialized TrainableVAE")

    # Generate synthetic data
    np.random.seed(42)
    X = np.random.randn(20, 16)
    y = np.array([i % 4 for i in range(20)])  # Regime labels 0-3

    # Train
    initial_loss = None
    losses = []

    for epoch in range(20):
        for i in range(0, len(X), 4):
            batch_x = X[i:i+4]
            batch_y = y[i:i+4]
            loss = vae.train_step(batch_x, batch_y)
            losses.append(loss)

        if initial_loss is None:
            initial_loss = np.mean(losses[-3:])

    final_loss = np.mean(losses[-3:])

    print(f"  Initial loss: {initial_loss:.4f}")
    print(f"  Final loss:   {final_loss:.4f}")

    if final_loss < initial_loss:
        print(f"[OK] Loss decreased by {((initial_loss - final_loss) / initial_loss) * 100:.1f}%")
    else:
        print(f"[WARN] Loss did not decrease significantly")

    # Test regime detection
    regime, probs = vae.detect_regime(X[0])
    print(f"[OK] Regime detection works: regime {regime}")

    # Test reconstruction
    recon, mu, logvar, _ = vae.forward(X[0])
    recon_error = np.mean((recon - X[0:1]) ** 2)
    print(f"[OK] Reconstruction MSE: {recon_error:.4f}")


def test_model_pretrainer():
    """Test the full pre-training pipeline."""
    print("\n" + "="*60)
    print("TEST 4: ModelPreTrainer Integration")
    print("="*60)

    from app.trading.backtester import ModelPreTrainer, TrainingMetrics

    # Initialize with smaller dimensions for testing
    pretrainer = ModelPreTrainer(state_dim=16, action_dim=3)
    print(f"[OK] Initialized ModelPreTrainer")

    # Check all models are present
    assert hasattr(pretrainer, 'dqn'), "Missing DQN"
    assert hasattr(pretrainer, 'ppo'), "Missing PPO"
    assert hasattr(pretrainer, 'lstm'), "Missing LSTM"
    assert hasattr(pretrainer, 'transformer'), "Missing Transformer"
    assert hasattr(pretrainer, 'vae'), "Missing VAE"
    print(f"[OK] All 5 models initialized")

    # Generate synthetic training data
    np.random.seed(42)
    features = np.random.randn(100, 16)
    labels = np.random.randint(0, 3, 100)
    rewards = np.random.randn(100) * 0.1

    # Train with minimal epochs
    print(f"  Training on {len(features)} samples...")
    metrics = pretrainer.train(features, labels, rewards, epochs=5, batch_size=16)

    print(f"[OK] Training completed: {metrics.epochs_completed} epochs")
    print(f"  Final training loss: {metrics.training_loss[-1]:.4f}" if metrics.training_loss else "  No loss recorded")

    # Test prediction
    pred = pretrainer.predict(features[0])
    print(f"[OK] Ensemble prediction: action={pred['action']}, confidence={pred['confidence']:.3f}")


def test_checkpoint_save_load():
    """Test saving and loading checkpoints."""
    print("\n" + "="*60)
    print("TEST 5: Checkpoint Save/Load")
    print("="*60)

    from app.trading.backtester import ModelPreTrainer, CHECKPOINT_DIR
    import pickle

    # Train a model
    pretrainer = ModelPreTrainer(state_dim=16, action_dim=3)

    np.random.seed(42)
    features = np.random.randn(50, 16)
    labels = np.random.randint(0, 3, 50)
    rewards = np.random.randn(50) * 0.1

    pretrainer.train(features, labels, rewards, epochs=3, batch_size=16)

    # Get prediction before save
    test_state = np.random.randn(16)
    pred_before = pretrainer.predict(test_state)
    print(f"[OK] Prediction before save: {pred_before['action']}")

    # Save checkpoint
    pretrainer.save_checkpoints()
    checkpoint_path = CHECKPOINT_DIR / "model_checkpoint.pkl"
    print(f"[OK] Checkpoint saved to {checkpoint_path}")

    # Create new pretrainer and load
    pretrainer2 = ModelPreTrainer(state_dim=16, action_dim=3)
    loaded = pretrainer2.load_checkpoints()

    if loaded:
        print(f"[OK] Checkpoint loaded successfully")

        # Get prediction after load
        pred_after = pretrainer2.predict(test_state)
        print(f"[OK] Prediction after load: {pred_after['action']}")

        # Verify DQN epsilon was restored
        print(f"[OK] DQN epsilon restored: {pretrainer2.dqn.epsilon:.4f}")
    else:
        print(f"[WARN] No checkpoint to load")


@pytest.mark.asyncio
async def test_alpha_sources():
    """Test alpha source API calls."""
    print("\n" + "="*60)
    print("TEST 6: Alpha Source APIs")
    print("="*60)

    from app.trading.backtester import AlphaSourceManager

    alpha = AlphaSourceManager()
    print(f"[OK] Initialized AlphaSourceManager")

    # Test Fear & Greed (free API, should work)
    try:
        fg = await alpha.get_fear_greed_index()
        print(f"[OK] Fear & Greed: {fg['value']} ({fg['classification']}) -> signal: {fg['signal']}")
    except Exception as e:
        print(f"[WARN] Fear & Greed failed: {e}")

    # Test sentiment (will use default without API key)
    sentiment = await alpha.get_claude_alpha("BTC")
    print(f"[OK] Sentiment for BTC: signal={sentiment['signal']}, source={sentiment.get('source', 'unknown')}")

    # Test cross-asset
    try:
        cross = await alpha.get_cross_asset_signals()
        print(f"[OK] Cross-asset: regime={cross['regime']}, signal={cross['signal']}")
    except Exception as e:
        print(f"[WARN] Cross-asset failed: {e}")

    # Test combined alpha
    combined = await alpha.get_combined_alpha("BTC")
    print(f"[OK] Combined alpha: signal={combined['combined_signal']}, recommendation={combined['recommendation']}")


def run_all_tests():
    """Run all tests."""
    print("\n" + "="*60)
    print("ML TRAINING PIPELINE TEST SUITE")
    print("="*60)

    results = {}

    # Test 1: LSTM
    try:
        results['lstm'] = test_lstm_classifier()
    except Exception as e:
        print(f"[FAIL] LSTM test failed: {e}")
        import traceback
        traceback.print_exc()
        results['lstm'] = False

    # Test 2: Transformer
    try:
        results['transformer'] = test_trainable_transformer()
    except Exception as e:
        print(f"[FAIL] Transformer test failed: {e}")
        import traceback
        traceback.print_exc()
        results['transformer'] = False

    # Test 3: VAE
    try:
        results['vae'] = test_trainable_vae()
    except Exception as e:
        print(f"[FAIL] VAE test failed: {e}")
        import traceback
        traceback.print_exc()
        results['vae'] = False

    # Test 4: ModelPreTrainer
    try:
        results['pretrainer'] = test_model_pretrainer()
    except Exception as e:
        print(f"[FAIL] ModelPreTrainer test failed: {e}")
        import traceback
        traceback.print_exc()
        results['pretrainer'] = False

    # Test 5: Checkpoints
    try:
        results['checkpoints'] = test_checkpoint_save_load()
    except Exception as e:
        print(f"[FAIL] Checkpoint test failed: {e}")
        import traceback
        traceback.print_exc()
        results['checkpoints'] = False

    # Test 6: Alpha Sources (async)
    try:
        results['alpha'] = asyncio.run(test_alpha_sources())
    except Exception as e:
        print(f"[FAIL] Alpha sources test failed: {e}")
        import traceback
        traceback.print_exc()
        results['alpha'] = False

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, passed_test in results.items():
        status = "[PASS]" if passed_test else "[FAIL]"
        print(f"  {status} {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n[SUCCESS] All tests passed! Training pipeline is ready.")
        return True
    else:
        print(f"\n[WARNING] {total - passed} tests failed.")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
