"""Lance le studio : python -m app [--host 0.0.0.0] [--port 8000]"""

import argparse

import uvicorn

parser = argparse.ArgumentParser(description="Studio de films IA")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8000)
args = parser.parse_args()
uvicorn.run("app.main:create_app", factory=True, host=args.host, port=args.port)
