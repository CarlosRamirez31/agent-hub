"""Bounded, read-only requests over the installed Codex app-server's stdio."""

import json
import os
import select
import shutil
import subprocess
import time


class CodexReader:
    def __init__(self, home, timeout=30):
        executable = shutil.which("codex")
        if not executable:
            raise ValueError("Se necesita Codex para exportar su historial paginado.")
        self.process = subprocess.Popen([executable, "app-server", "--listen", "stdio://"],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        env={**os.environ, "CODEX_HOME": str(home)})
        self.timeout, self.sequence, self.buffer = timeout, 0, b""

    def send(self, value):
        self.process.stdin.write(json.dumps(value).encode()+b"\n")
        self.process.stdin.flush()

    def call(self, method, params):
        self.sequence += 1
        ident = self.sequence
        self.send({"id": ident, "method": method, "params": params})
        deadline = time.monotonic()+self.timeout
        while time.monotonic() < deadline:
            if b"\n" not in self.buffer:
                if not select.select([self.process.stdout], [], [], max(0, deadline-time.monotonic()))[0]:
                    break
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise ValueError("Codex cerró la lectura del historial.")
                self.buffer += chunk
                if len(self.buffer) > 32*1024*1024:
                    raise ValueError("La respuesta del historial excede el límite local de 32 MiB.")
                continue
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if response.get("id") == ident and "method" not in response:
                if "error" in response:
                    raise ValueError("Codex: " + str(response["error"].get("message", "Error al leer historial")))
                return response.get("result", {})
            if "id" in response and "method" in response:
                self.send({"id": response["id"], "error": {"code": -32601, "message": "Read-only client"}})
        raise ValueError("Codex no respondió a tiempo al leer el historial.")

    def close(self):
        self.process.stdin.close()
        self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdout.close()


def codex_messages(home, ident):
    reader = CodexReader(home)
    try:
        reader.call("initialize", {"clientInfo": {"name": "agent_hub", "title": "Agent Hub", "version": "0.4.0"},
                                   "capabilities": {"experimentalApi": True}})
        reader.send({"method": "initialized", "params": {}})
        messages, cursor, seen = [], None, set()
        while True:
            result = reader.call("thread/turns/list", {"threadId": ident, "cursor": cursor,
                                                       "limit": 25, "sortDirection": "asc", "itemsView": "full"})
            for turn in result.get("data", []):
                for item in turn.get("items", []):
                    if item.get("type") == "userMessage":
                        text = "\n".join(c.get("text", "") for c in item.get("content", []) if c.get("type") == "text")
                        if text:
                            messages.append({"role": "user", "text": text})
                    elif item.get("type") == "agentMessage" and item.get("text"):
                        messages.append({"role": "assistant", "text": item["text"]})
            if sum(len(m["text"]) for m in messages) > 16*1024*1024:
                raise ValueError("Conversación demasiado grande para exportar localmente (16 MiB).")
            cursor = result.get("nextCursor")
            if not cursor:
                return messages
            if cursor in seen:
                raise ValueError("Codex repitió un cursor de historial; exportación cancelada.")
            seen.add(cursor)
    finally:
        reader.close()
