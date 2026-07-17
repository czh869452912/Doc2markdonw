from __future__ import annotations

import argparse
import queue
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.docx_fixture import minimal_docx_bytes


def _free_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return candidate.getsockname()[1]


def _multipart(
    fields: list[tuple[str, str]],
    filename: str,
    content: bytes,
) -> tuple[bytes, str]:
    boundary = f"offline-smoke-{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        )
        body.extend(value.encode())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        (
            'Content-Disposition: form-data; name="files"; '
            f'filename="{filename}"\r\n'
        ).encode()
    )
    body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
    body.extend(content)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _post(
    port: int,
    path: str,
    fields: list[tuple[str, str]],
    content: bytes,
) -> int:
    body, content_type = _multipart(fields, "report.docx", content)
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        response.read()
        return response.status


def _wait_for_health(port: int) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=2
            ) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.HTTPError):
            time.sleep(0.5)
    raise RuntimeError("Office gateway did not become healthy")


def run(image: str) -> None:
    captured: queue.Queue[tuple[str, bytes]] = queue.Queue()

    class RouterHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self._respond(200, b'{"status":"ok"}')
            else:
                self._respond(404, b'{}')

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            captured.put((self.path, self.rfile.read(length)))
            status = 202 if self.path == "/tasks" else 200
            self._respond(status, b'{"task_id":"smoke-task"}')

        def _respond(self, status: int, body: bytes):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    router = ThreadingHTTPServer(("0.0.0.0", 0), RouterHandler)
    router_port = router.server_address[1]
    router_thread = threading.Thread(target=router.serve_forever, daemon=True)
    router_thread.start()

    gateway_port = _free_port()
    container = f"mineru-office-smoke-{uuid.uuid4().hex[:8]}"
    docker_run = [
        "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        container,
        "--read-only",
        "--tmpfs",
        "/tmp:size=512m,mode=1777",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--add-host",
        "host.docker.internal:host-gateway",
        "-e",
        f"MINERU_UPSTREAM_URL=http://host.docker.internal:{router_port}",
        "-p",
        f"127.0.0.1:{gateway_port}:8081",
        image,
    ]

    try:
        subprocess.run(docker_run, check=True, capture_output=True, text=True)
        _wait_for_health(gateway_port)
        docx = minimal_docx_bytes()

        if _post(gateway_port, "/tasks", [("return_md", "true")], docx) != 202:
            raise AssertionError("pdf_ocr request did not return 202")
        path, body = captured.get(timeout=10)
        if path != "/tasks" or b'filename="report.pdf"' not in body:
            raise AssertionError("pdf_ocr request did not upload report.pdf")
        if b"%PDF" not in body:
            raise AssertionError("pdf_ocr request did not contain PDF bytes")

        if _post(
            gateway_port,
            "/file_parse",
            [("office_mode", "native")],
            docx,
        ) != 200:
            raise AssertionError("native request did not return 200")
        path, body = captured.get(timeout=10)
        if path != "/file_parse" or b'filename="report.docx"' not in body:
            raise AssertionError("native request did not upload report.docx")
        if docx not in body:
            raise AssertionError("native request changed the DOCX bytes")

        cleanup = subprocess.run(
            [
                "docker",
                "exec",
                container,
                "find",
                "/tmp/mineru-office",
                "-mindepth",
                "1",
                "-print",
                "-quit",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        if cleanup.stdout.strip():
            raise AssertionError("request temporary files were not cleaned")
    except Exception:
        subprocess.run(["docker", "logs", container], check=False)
        raise
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container],
            check=False,
            capture_output=True,
        )
        router.shutdown()
        router.server_close()
        router_thread.join(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="mineru-office-gateway:test")
    arguments = parser.parse_args()
    run(arguments.image)
    print("Office gateway integration smoke test passed.")
