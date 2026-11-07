"""Misure aggregate dell'agente; telemetria facoltativa, mai bloccante.

Inoltra SOLTANTO contatori, stato e dominio RSS. Non invia testi, articoli,
credenziali, nomi di persone o contenuti delle Issues.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

import requests


@dataclass
class RunMeter:
    mode: str = "demo"
    status: str = "completed"
    result: str = "none"
    model: str = ""
    feed_host: str = ""
    feed_items: int = 0
    new_items: int = 0
    inspections: int = 0
    groq_attempts: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    issue_number: int = 0
    duration_ms: int = 0

    def usage(self, info):
        if not isinstance(info, dict):
            return
        self.prompt_tokens += self._count(info.get("prompt_tokens"))
        self.completion_tokens += self._count(info.get("completion_tokens"))
        details = info.get("prompt_tokens_details") or {}
        if isinstance(details, dict):
            self.cached_tokens += min(
                self._count(details.get("cached_tokens")),
                self._count(info.get("prompt_tokens")),
            )

    @staticmethod
    def _count(value):
        try:
            n = int(value)
            return max(0, min(n, 100_000_000))
        except (ValueError, TypeError):
            return 0

    def to_payload(self):
        run = os.environ.get("GITHUB_RUN_ID", "").strip()
        attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1").strip()
        if not run.isdecimal() or not attempt.isdecimal():
            return None  # Non registrare un ID di prova come esecuzione reale.
        return {
            "id": f"search:{run}:{attempt}",
            "mode": self.mode,
            "status": self.status,
            "result": self.result,
            "model": self.model[:80],
            "feed_host": self.feed_host[:160],
            "feed_items": self.feed_items,
            "new_items": self.new_items,
            "inspections": self.inspections,
            "groq_attempts": self.groq_attempts,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "issue_number": self.issue_number or None,
            "duration_ms": self.duration_ms,
        }


def host_only(url):
    try:
        return (urlparse(url).hostname or "").lower()[:160]
    except ValueError:
        return ""


def send_meter(meter: RunMeter, cfg):
    """Best effort: un guasto del cruscotto non interrompe l'agente."""
    secret = os.environ.get("METRICS_INGEST_SECRET", "")
    base = str(cfg.get("approval_api_url", "") or "").strip().rstrip("/")
    payload = meter.to_payload()
    if not secret or not base.startswith("https://") or not payload:
        print("Osservatorio: non configurato; ricerca eseguita normalmente.")
        return False
    try:
        res = requests.post(
            base + "/metrics/ingest",
            headers={"Authorization": "Bearer " + secret,
                     "Content-Type": "application/json"},
            json=payload,
            timeout=(5, 12),
        )
        if res.ok:
            print("Osservatorio: misurazione acquisita (run " + payload["id"] + ").")
            return True
        print("Osservatorio: registrazione non riuscita, HTTP " + str(res.status_code))
    except requests.RequestException:
        print("Osservatorio: servizio temporaneamente non raggiungibile.")
    return False
