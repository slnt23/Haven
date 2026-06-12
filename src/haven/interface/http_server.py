"""HTTP Interface —— 通过 HTTP API 访问 Haven。

所有请求只能通过 Runtime.execute() 处理。
禁止直接调用 Agent / Memory / Tool。

Usage: uv run haven serve-http
"""

from __future__ import annotations

import asyncio
import json
import logging
from http import HTTPStatus
from typing import Any

logger = logging.getLogger("haven.interface.http")

_HTML_PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Haven Chat</title>
<style>
  body{{font-family:monospace;max-width:800px;margin:2rem auto;padding:0 1rem;background:#1a1a2e;color:#e0e0e0}}
  h1{{color:#00d4ff}} textarea{{width:100%;height:80px;background:#16213e;color:#fff;border:1px solid #0f3460;padding:.5rem;font:inherit}}
  button{{margin-top:.5rem;padding:.5rem 1.5rem;background:#0f3460;color:#00d4ff;border:none;cursor:pointer;font:inherit}}
  #response{{margin-top:1rem;padding:1rem;background:#16213e;white-space:pre-wrap;min-height:100px}}
</style></head>
<body>
  <h1>Haven Chat</h1>
  <textarea id="input" placeholder="输入消息..."></textarea><br>
  <button onclick="send()">发送</button>
  <div id="response"></div>
<script>
async function send(){{const t=document.getElementById('input').value;document.getElementById('response').textContent='...';
const r=await fetch('/api/chat',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{task:t}})}});
const d=await r.json();document.getElementById('response').textContent=d.result||d.error}}
</script>
</body></html>"""


class HTTPServer:
    """简易 HTTP API 服务器。

    所有请求通过 Runtime.execute() 处理。
    """

    def __init__(self, runtime: Any, host: str = "127.0.0.1", port: int = 8420) -> None:
        self._runtime = runtime
        self._host = host
        self._port = port

    async def start(self) -> None:
        from asyncio import start_server

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                request = await self._read_request(reader)
                response = await self._handle(request)
                writer.write(response)
                await writer.drain()
            except Exception:
                writer.write(_http_response(500, json.dumps({"error": "internal error"})))
                await writer.drain()
            finally:
                writer.close()

        server = await start_server(handler, self._host, self._port)
        logger.info("HTTP server: http://%s:%d", self._host, self._port)
        async with server:
            await server.serve_forever()

    async def _read_request(self, reader: asyncio.StreamReader) -> dict:
        data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30)
        text = data.decode("utf-8", errors="replace")
        lines = text.split("\r\n")
        if not lines:
            return {"method": "GET", "path": "/"}

        parts = lines[0].split(" ")
        method = parts[0]
        path = parts[1] if len(parts) > 1 else "/"

        body = ""
        for i, line in enumerate(lines):
            if line.startswith("Content-Length:"):
                length = int(line.split(":")[1].strip())
                body = text[text.index("\r\n\r\n") + 4 :][:length]
                break

        return {"method": method, "path": path, "body": body}

    async def _handle(self, request: dict) -> bytes:
        method = request.get("method", "GET")
        path = request.get("path", "/")

        if path == "/" or path == "/index.html":
            return _http_response(200, _HTML_PAGE, content_type="text/html; charset=utf-8")

        if path == "/api/chat" and method == "POST":
            try:
                body = json.loads(request.get("body", "{}"))
                task = body.get("task", "")
                if not task:
                    return _http_json(400, {"error": "missing 'task' field"})

                # 所有执行通过 Runtime.execute() —— 唯一入口
                result = await self._runtime.execute(task)
                return _http_json(200, {"result": result})
            except json.JSONDecodeError:
                return _http_json(400, {"error": "invalid JSON"})
            except Exception as exc:
                logger.error("HTTP handle error: %s", exc)
                return _http_json(500, {"error": str(exc)})

        if path == "/health":
            return _http_json(200, {"status": "ok"})

        return _http_response(404, json.dumps({"error": "not found"}))


def _http_response(status: int, body: str, content_type: str = "application/json") -> bytes:
    return f"HTTP/1.1 {status} {HTTPStatus(status).phrase}\r\nContent-Type: {content_type}\r\nContent-Length: {len(body.encode())}\r\nConnection: close\r\n\r\n{body}".encode()


def _http_json(status: int, data: dict) -> bytes:
    return _http_response(status, json.dumps(data, ensure_ascii=False))
