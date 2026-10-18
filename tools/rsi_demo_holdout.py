import sys

sys.path.insert(0, "src")
from sophyane.rsi_demo_target import score


assert score() >= 2
