import sys

sys.path.insert(0, "src")
from sophyane.rsi_demo_target import score


assert score() == 3, "RSI_WEAKNESS_demo_score_v3"
