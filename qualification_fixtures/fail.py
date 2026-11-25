import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    print(json.dumps({"value": 0}, separators=(",", ":")))
