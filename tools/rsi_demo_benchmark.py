import json
import sys

sys.path.insert(0, "src")
from sophyane.rsi_demo_target import score


value = score()
print(json.dumps({"benchmark_success": value, "quality": value}, sort_keys=True))
