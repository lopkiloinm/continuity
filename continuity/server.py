"""Loopback-only, single-process demo server. Not a production authentication boundary."""
import csv
import io
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from continuity.engine import Job, Rejected

STATIC = Path(__file__).resolve().parent.parent / "static"
job = Job()


class Handler(BaseHTTPRequestHandler):
    def send(self, status, data, content_type="application/json"):
        body = json.dumps(data).encode() if content_type == "application/json" else data
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/api/job", "/api/receipt"):
            return self.send(200, job.snapshot())
        if path == "/api/result.csv":
            if job.state != "completed":
                return self.send(409, {"error": "Complete the job before exporting."})
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=["record_id", "source", "description", "worker"])
            writer.writeheader()
            writer.writerows(job.rows)
            return self.send(200, buffer.getvalue().encode(), "text/csv; charset=utf-8")
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                 "/style.css": ("style.css", "text/css; charset=utf-8")}
        if path in files:
            name, mime = files[path]
            return self.send(200, (STATIC / name).read_bytes(), mime)
        self.send(404, {"error": "Not found"})

    def do_POST(self):
        global job
        # JSON-only, same-origin mutations prevent cross-site form submissions.
        expected_host = "127.0.0.1:%d" % self.server.server_port
        if self.headers.get("Host") != expected_host or self.headers.get("Origin", "http://" + expected_host) != "http://" + expected_host:
            return self.send(403, {"error": "Use the local demo origin."})
        if self.headers.get("Content-Type") != "application/json":
            return self.send(415, {"error": "JSON required"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096:
                raise ValueError("Expected a small JSON object")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            if self.path == "/api/reset":
                job = Job()
            elif self.path == "/api/start":
                job.start()
            elif self.path == "/api/fail":
                job.fail()
            elif self.path == "/api/evaluate":
                job.evaluate(data.get("scenario"))
            elif self.path == "/api/decide":
                if type(data.get("approved")) is not bool:
                    raise ValueError("approved must be a boolean")
                job.decide(data["approved"], data.get("approval_hash"))
            elif self.path == "/api/resume":
                job.resume()
            else:
                return self.send(404, {"error": "Unknown action"})
            self.send(200, job.snapshot())
        except Rejected as error:
            self.send(409, {"error": str(error)})
        except (ValueError, TypeError) as error:
            self.send(400, {"error": str(error)})


def main():
    server = HTTPServer(("127.0.0.1", 8000), Handler)
    print("Continuity simulation: http://127.0.0.1:8000", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
