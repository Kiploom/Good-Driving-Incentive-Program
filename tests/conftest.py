"""
Pytest configuration for Good-Driving-Incentive-Program tests.
Ensures the flask app is importable when running tests from project root.
"""
import os
import sys

# Add flask directory to path so 'app' package can be imported
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TESTS_DIR)
FLASK_DIR = os.path.join(PROJECT_ROOT, "flask")
if FLASK_DIR not in sys.path:
    sys.path.insert(0, FLASK_DIR)
