"""Piccole utilità condivise. Nessuna chiave viene salvata nei file del repository."""
from __future__ import annotations

import base64
import ipaddress
import json
import os
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests

ROOT = Path(__file__).resolve().parents[1]
MARKER = "PA_AGENT_DRAFT_V1:"
UA = "RedazionePA-Demo/1.0 (educational GitHub Actions; public RSS only)"


def config():
    data = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    for key in ("max_feed_items", "max_inspections"):
        data[key] = max(1, min(10, int(data.get(key, 4))))
    return data


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def public_url(url: str):
    """Rifiuta indirizzi privati, host locali e URL con credenziali.

    Protezione di base; la connessione finale viene sempre usata senza segreti.
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL non valido: richiesto HTTP(S) senza credenziali")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".local"):
        raise ValueError("Indirizzo interno non permesso")
    port = parsed.port
    if port is not None and port not in (80, 443):
        raise ValueError("Porta non standard non permessa")
    # Nome DNS pubblico, non solo il testo dell'URL.
    addresses = socket.getaddrinfo(host, port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(info[4][0]).is_global for info in addresses):
        raise ValueError("La risorsa deve risolvere solo verso indirizzi IP pubblici")
    return url


def fetch_public(url: str, max_bytes: int = 900_000):
    for _ in range(4):
        public_url(url)
        response = requests.get(url, headers={"User-Agent": UA, "Accept": "text/html,application/rss+xml,application/atom+xml,application/xml,*/*"},
                                timeout=(8, 18), allow_redirects=False, stream=True)
        if response.status_code in (301, 302, 303, 307, 308):
            redirect = response.headers.get("Location", "")
            response.close()
            if not redirect:
                raise ValueError("Redirect senza destinazione")
            url = urljoin(url, redirect)
            continue
        response.raise_for_status()
        total = 0
        chunks = []
        try:
            for chunk in response.iter_content(16_384):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("Risorsa RSS/articolo troppo grande")
                chunks.append(chunk)
        finally:
            response.close()
        return b"".join(chunks), url
    raise ValueError("Troppi reindirizzamenti")


def pack_meta(data):
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "<!-- " + MARKER + base64.b64encode(raw).decode("ascii") + " -->"


def unpack_meta(body):
    match = re.search(re.escape(MARKER) + r"([A-Za-z0-9+/=]+)", body or "")
    if not match:
        return None
    try:
        return json.loads(base64.b64decode(match.group(1), validate=True).decode("utf-8"))
    except Exception:
        return None


class GitHub:
    def __init__(self):
        self.repo = os.environ.get("GITHUB_REPOSITORY", "")
        self.token = os.environ.get("GH_TOKEN", "")
        if not self.repo or not self.token:
            raise RuntimeError("Mancano GITHUB_REPOSITORY o GH_TOKEN")
        self.base = "https://api.github.com/repos/" + self.repo
        self.headers = {"Accept": "application/vnd.github+json", "Authorization": "Bearer " + self.token,
                        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": UA}

    def request(self, method, path, **kwargs):
        r = requests.request(method, self.base + path, headers=self.headers, timeout=25, **kwargs)
        if not r.ok:
            raise RuntimeError(f"GitHub API {method} {path}: HTTP {r.status_code}: {r.text[:400]}")
        return r.json() if r.content else {}

    def issues(self):
        # Include anche le issue chiuse, per evitare duplicati.
        output = []
        for page in range(1, 4):
            chunk = self.request("GET", f"/issues?state=all&per_page=100&page={page}")
            output.extend(x for x in chunk if "pull_request" not in x)
            if len(chunk) < 100:
                break
        return output

    def labels(self, number):
        return {x["name"] for x in self.request("GET", f"/issues/{number}/labels")}

    def ensure_label(self, label, color="1D75BD"):
        resp = requests.post(self.base + "/labels", headers=self.headers,
                             json={"name": label, "color": color}, timeout=20)
        if resp.status_code not in (201, 422):
            raise RuntimeError(f"Creazione etichetta: HTTP {resp.status_code} {resp.text[:200]}")

    def comment(self, number, body):
        return self.request("POST", f"/issues/{number}/comments", json={"body": body})

    def add_label(self, number, name):
        return self.request("POST", f"/issues/{number}/labels", json={"labels": [name]})

    def close(self, number):
        return self.request("PATCH", f"/issues/{number}", json={"state": "closed"})


def safe_excerpt(text, max_len=800):
    return re.sub(r"\s+", " ", text or "").strip()[:max_len]
