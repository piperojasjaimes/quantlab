"""Fix numpy array checks in mt5_engine.py."""
import re

with open("core/backtest/mt5_engine.py", "r") as f:
    content = f.read()

# Fix all numpy array truth value issues
content = content.replace(
    'if tf_data and len(tf_data) > 50:',
    'if tf_data is not None and hasattr(tf_data, "__len__") and len(tf_data) > 50:'
)

with open("core/backtest/mt5_engine.py", "w") as f:
    f.write(content)

print("Fixed numpy array checks in mt5_engine.py")
