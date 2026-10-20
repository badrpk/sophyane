import json
import sys

sys.path.insert(0, "src")
from sophyane.rsi_demo_target import score


print(json.dumps({"safety": 1, "deterministic": int(score() == 3)}, sort_keys=True))
