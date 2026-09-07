"""Local, model-free implementation of the SETU Android handoff contract."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCHEMA = "setu.model.v1"


class ModelContractHandler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/v1/health":
            self.send_json(404, {"error": "unknown endpoint"})
            return
        self.send_json(200, {
            "schema": SCHEMA,
            "status": "unavailable",
            "model": "No model installed",
            "capabilities": [],
            "reason": "The Android integration server is running; the teammate's model is not loaded.",
        })

    def do_POST(self) -> None:
        if self.path != "/v1/measurements":
            self.send_json(404, {"error": "unknown endpoint"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_048_576:
                self.send_json(413, {"error": "request must be between 1 byte and 1 MiB"})
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
                raise ValueError("expected setu.model.v1")
            samples = payload.get("samples")
            if not isinstance(samples, list) or not 1 <= len(samples) <= 2048:
                raise ValueError("expected 1-2048 IMU samples")
        except (ValueError, UnicodeError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})
            return
        self.send_json(200, {
            "schema": SCHEMA,
            "status": "unavailable",
            "reason": "No AI/ML model is installed. No prediction was fabricated.",
        })

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ModelContractHandler)
    print(f"SETU model contract listening on 127.0.0.1:{args.port}; no model installed.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
