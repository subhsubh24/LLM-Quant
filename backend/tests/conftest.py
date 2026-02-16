"""
Pytest configuration for test suite.
Sets up proper Python path for imports.
"""

import sys
import os

# Add backend root to path so imports work correctly with absolute import paths
backend_root = os.path.join(os.path.dirname(__file__), '..')
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)
