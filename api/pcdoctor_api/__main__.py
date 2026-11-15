"""Start the server:  python -m pcdoctor_api   (or the pcdoctor-api command)."""

from __future__ import annotations

import argparse
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PC Doctor API (and dashboard, if built).")
    # 127.0.0.1 = this computer only. Stored data needs a sign-in, but this
    # serves plain HTTP: use 0.0.0.0 only on a network you trust.
    parser.add_argument("--host", default=os.environ.get("PCDOCTOR_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PCDOCTOR_PORT", "8000")))
    parser.add_argument("--reload", action="store_true", help="restart when the code changes")
    args = parser.parse_args()
    uvicorn.run("pcdoctor_api.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
