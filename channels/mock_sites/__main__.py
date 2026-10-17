"""python -m channels.mock_sites [--port 8765] [--host 127.0.0.1]"""
import argparse

import uvicorn

ap = argparse.ArgumentParser()
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=8765)
a = ap.parse_args()
uvicorn.run("channels.mock_sites.app:app", host=a.host, port=a.port, log_level="warning")
