import json
import socket
import sys

for line in sys.stdin:
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=1)
        blocked = False
    except OSError:
        blocked = True
    print(json.dumps({"network": "blocked" if blocked else "available"}))
