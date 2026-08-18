"""Use a temporary local Edge session to read JSON from TLS-incompatible sites.

The requested URL is sent over the local Chrome DevTools Protocol after Edge
starts.  It is deliberately not included in the process command line, logs, or
error messages because the Beijing open-data API embeds the user's access token
in the URL path.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

import websocket


class EdgeJSONTransportError(RuntimeError):
    """A sanitized Edge transport error which never contains the requested URL."""


class EdgeJSONTransport:
    def __init__(self, *, startup_timeout: float = 15.0, request_timeout: float = 30.0):
        self.startup_timeout = startup_timeout
        self.request_timeout = request_timeout
        self._profile: tempfile.TemporaryDirectory[str] | None = None
        self._process: subprocess.Popen | None = None
        self._socket = None
        self._message_id = 0
        self._document_status: int | None = None

    @staticmethod
    def find_edge() -> Path | None:
        candidates = []
        for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if root:
                candidates.append(Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
        return next((path for path in candidates if path.is_file()), None)

    def start(self) -> None:
        if self._socket is not None:
            return
        edge = self.find_edge()
        if edge is None:
            raise EdgeJSONTransportError("未找到 Microsoft Edge，无法启用站点兼容模式")

        self._profile = tempfile.TemporaryDirectory(
            prefix="jobguard-beijing-api-",
            ignore_cleanup_errors=True,
        )
        profile_path = Path(self._profile.name)
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        command = [
            str(edge),
            "--headless=new",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-crash-reporter",
            "--disable-logging",
            "--disable-sync",
            "--incognito",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-allow-origins=*",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile_path}",
            "about:blank",
        ]
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            port = self._wait_for_debug_port(profile_path)
            target = self._find_page_target(port)
            self._socket = websocket.create_connection(
                target["webSocketDebuggerUrl"],
                timeout=self.request_timeout,
                suppress_origin=True,
                http_proxy_host=None,
                https_proxy_host=None,
            )
            self._command("Page.enable")
            self._command("Network.enable")
            self._command("Runtime.enable")
        except EdgeJSONTransportError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise EdgeJSONTransportError("Microsoft Edge 兼容模式启动失败") from exc

    def get_json(self, url: str) -> tuple[int | None, Any]:
        """Navigate to *url* and return (HTTP status, parsed JSON).

        The URL must never be included in exceptions or logs by callers.
        """
        if self._socket is None:
            self.start()
        self._document_status = None
        try:
            result = self._command("Page.navigate", {"url": url})
            if result.get("errorText"):
                raise EdgeJSONTransportError("Edge 无法打开北京市公共数据接口")

            deadline = time.monotonic() + self.request_timeout
            while time.monotonic() < deadline:
                state = self._evaluate("document.readyState")
                if state == "complete":
                    break
                time.sleep(0.1)
            else:
                raise EdgeJSONTransportError("Edge 等待接口响应超时")

            body = self._evaluate(
                "document.querySelector('pre')?.innerText || "
                "document.body?.innerText || document.documentElement?.innerText || ''"
            )
            if not isinstance(body, str) or not body.strip():
                raise EdgeJSONTransportError("接口未返回可读取内容")
            try:
                payload = json.loads(body.strip())
            except json.JSONDecodeError as exc:
                raise EdgeJSONTransportError("接口没有返回有效 JSON，可能需要重新登录确认权限") from exc
            return self._document_status, payload
        except EdgeJSONTransportError:
            raise
        except Exception as exc:
            raise EdgeJSONTransportError("Edge 读取北京市公共数据接口失败") from exc

    def close(self) -> None:
        socket = self._socket
        self._socket = None
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=3)
                except Exception:
                    pass
        profile = self._profile
        self._profile = None
        if profile is not None:
            try:
                profile.cleanup()
            except Exception:
                pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def _wait_for_debug_port(self, profile_path: Path) -> int:
        active_port_file = profile_path / "DevToolsActivePort"
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                raise EdgeJSONTransportError("Microsoft Edge 兼容模式意外退出")
            try:
                lines = active_port_file.read_text(encoding="utf-8").splitlines()
                if lines:
                    return int(lines[0])
            except (FileNotFoundError, OSError, ValueError):
                pass
            time.sleep(0.1)
        raise EdgeJSONTransportError("Microsoft Edge 兼容模式启动超时")

    def _find_page_target(self, port: int) -> dict:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/list",
                timeout=5,
            ) as response:
                targets = json.load(response)
        except Exception as exc:
            raise EdgeJSONTransportError("无法连接 Microsoft Edge 本机调试通道") from exc
        for target in targets:
            if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                return target
        raise EdgeJSONTransportError("Microsoft Edge 未创建可用的临时页面")

    def _command(self, method: str, params: dict | None = None) -> dict:
        if self._socket is None:
            raise EdgeJSONTransportError("Microsoft Edge 兼容模式尚未启动")
        self._message_id += 1
        message_id = self._message_id
        self._socket.send(json.dumps({
            "id": message_id,
            "method": method,
            "params": params or {},
        }))
        while True:
            message = json.loads(self._socket.recv())
            self._observe(message)
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise EdgeJSONTransportError("Microsoft Edge 本机调试命令执行失败")
            return message.get("result") or {}

    def _evaluate(self, expression: str):
        result = self._command("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
        })
        return (result.get("result") or {}).get("value")

    def _observe(self, message: dict) -> None:
        if message.get("method") != "Network.responseReceived":
            return
        params = message.get("params") or {}
        if params.get("type") != "Document":
            return
        status = (params.get("response") or {}).get("status")
        try:
            self._document_status = int(status)
        except (TypeError, ValueError):
            pass
