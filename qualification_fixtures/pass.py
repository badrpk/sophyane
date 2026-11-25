import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    values = request["input"]["values"]
    print(json.dumps({"value": sum(values)}, separators=(",", ":")))
