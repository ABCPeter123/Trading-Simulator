"""Exercise the PowerShell benchmark against a synthetic local HTTP stub.

No GGUF downloads, personal market data, credentials, or real inference.
Runs only on Windows GitHub Actions to validate PowerShell + .NET HTTP.
"""
from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class LocalStub(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path != "/models":
            self.send_error(404)
            return
        self.send_json({
            "data": [{"id": "Qwen3.5-9B-Q4_K_M", "status": {"value": "unloaded"}}]
        })

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers["Content-Length"]))
        request = json.loads(body)
        assert request["model"] == "Qwen3.5-9B-Q4_K_M"
        assert request["max_tokens"] == 32
        assert request["stream"] is False
        assert "arithmetic mean" in request["messages"][-1]["content"]
        self.send_json({
            "choices": [{"message": {"content": "4"}}],
            "usage": {"completion_tokens": 32},
            "timings": {
                "predicted_n": 32,
                "predicted_per_second": 12.5,
                "prompt_per_second": 150.0,
            },
        })

    def send_json(self, data):
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        cmd = [
            "powershell.exe", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File",
            str(ROOT / "scripts" / "benchmark-local-ai.ps1"),
            "-Model", "Qwen3.5-9B-Q4_K_M",
            "-MaxTokens", "32",
            "-TimeoutSeconds", "30",
            "-Port", str(server.server_address[1]),
        ]
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        assert run.returncode == 0, (
            "PowerShell benchmark failed:\n" + run.stdout + "\n" + run.stderr
        )
        assert "Generation: 12.5 tokens/sec" in run.stdout, run.stdout
        assert "Prompt processing: 150 tokens/sec" in run.stdout, run.stdout
        assert "Request completed in " in run.stdout, run.stdout
        print("Synthetic local benchmark HTTP test passed.")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
