"""Start the eBook translator: python run.py  (then open http://<this-computer's-IP>:8000 on your phone)."""
import logging
import os
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from server.config import settings


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def listen_sockets(host: str, port: int) -> list[socket.socket]:
    """IPv4 on HOST plus IPv6 loopback, so http://localhost works on machines where localhost resolves to ::1."""
    socks = []
    s4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s4.bind((host, port))
    socks.append(s4)
    if socket.has_ipv6 and host in ("0.0.0.0", "127.0.0.1"):
        try:
            s6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s6.bind(("::1", port))
            socks.append(s6)
        except OSError:
            pass  # no IPv6 loopback; 127.0.0.1 still works
    return socks


def open_browser_when_ready(server: uvicorn.Server, url: str) -> None:
    for _ in range(300):
        if server.started:
            webbrowser.open(url)
            return
        time.sleep(0.2)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        socks = listen_sockets(settings.host, settings.port)
    except OSError as e:
        print(f"\n  Port {settings.port} is busy ({e}). Is the app already running in another window?\n")
        sys.exit(1)
    local = f"http://127.0.0.1:{settings.port}"
    print(f"\n  eBook translator  ·  LLM: {settings.llm_provider} ({settings.model_label})  ·  TTS: {settings.gemini_tts_model}")
    print(f"  On this computer:  {local}   (or http://localhost:{settings.port})")
    if settings.host in ("0.0.0.0", "::"):
        print(f"  On the network:    http://{lan_ip()}:{settings.port}\n")
    else:
        print("  LAN access is Off. Set HOST=0.0.0.0 in .env and restart to enable it on a trusted network.\n")
    server = uvicorn.Server(uvicorn.Config("server.api:app", log_level="warning"))
    if os.environ.get("OPEN_BROWSER", "1") != "0":
        threading.Thread(target=open_browser_when_ready, args=(server, local), daemon=True).start()
    server.run(sockets=socks)
