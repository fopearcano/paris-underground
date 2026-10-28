#!/usr/bin/env python3
"""Start the Paris Underground atlas at http://127.0.0.1:8000 and open it in the browser.

    python run.py                 # serve on 127.0.0.1:8000 and open the browser
    python run.py --no-browser    # serve only
    python run.py --port 8010     # another port
    python run.py --reload        # auto-reload while editing
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import urllib.request
import webbrowser

if sys.version_info < (3, 11):
    sys.exit(f"Paris Underground needs Python 3.11 or newer (this is {sys.version.split()[0]}).")


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def atlas_already_running(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=2) as response:
            return json.load(response).get("status") == "ok"
    except (OSError, ValueError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Paris Underground atlas.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="restart on code changes")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    if port_in_use(args.host, args.port):
        if atlas_already_running(url):
            print(f"Paris Underground is already running at {url}")
            if not args.no_browser:
                webbrowser.open(url)
            return
        sys.exit(f"Port {args.port} is busy with another program. Try: python run.py --port {args.port + 1}")

    try:
        import uvicorn
    except ImportError:
        sys.exit("Dependencies are missing. Run: python -m pip install -r requirements.txt")

    print(f"\n  PARIS UNDERGROUND  ->  {url}\n  Press Ctrl+C to stop.\n")
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload, log_level="info")


if __name__ == "__main__":
    main()
