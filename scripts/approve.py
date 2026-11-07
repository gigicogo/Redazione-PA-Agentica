"""Unico percorso autorizzato per la pubblicazione. Eventi GitHub autenticati.

GO non chiede mai al modello di agire e non esegue istruzioni dell'RSS.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from urllib.parse import quote

import requests

from common import GitHub, config, unpack_meta, utc_now
from research import make_issue_text


def atproto_post(issue_number: int, text: str, repo: str):
    handle = os.environ.get("BLUESKY_HANDLE", "").strip()
    pw = os.environ.get("BLUESKY_APP_PASSWORD", "").strip()
    if not handle or not pw:
        raise RuntimeError("Mancano BLUESKY_HANDLE o BLUESKY_APP_PASSWORD nei Secrets")
    session = requests.post("https://bsky.social/xrpc/com.atproto.server.createSession",
                            json={"identifier": handle, "password": pw}, timeout=25)
    if not session.ok:
        raise RuntimeError(f"Autenticazione Bluesky non riuscita (HTTP {session.status_code})")
    sess = session.json()
    did = sess["did"]
    access = sess["accessJwt"]
    digest = hashlib.sha256(repo.encode("utf-8")).hexdigest()[:10]
    rkey = f"pa-{digest}-{issue_number}"  # identità stabile: non può ripubblicare due volte la stessa Issue
    get_url = "https://bsky.social/xrpc/com.atproto.repo.getRecord"
    params = {"repo": did, "collection": "app.bsky.feed.post", "rkey": rkey}
    headers = {"Authorization": "Bearer " + access}
    try:
        existing = requests.get(get_url, params=params, headers=headers, timeout=20)
        if existing.status_code == 200:
            return f"https://bsky.app/profile/{quote(handle, safe='.')}/post/{rkey}", True
        # Altre risposte 4xx non garantiscono assenza del record; il record non esiste soltanto con errore 400 specifico.
        if existing.status_code not in (400, 404):
            raise RuntimeError(f"Verifica duplicati Bluesky non riuscita (HTTP {existing.status_code})")
        error = existing.json()
        if error.get("error") not in ("RecordNotFound", "InvalidRequest", "NotFound"):
            raise RuntimeError("Impossibile verificare l'assenza di una pubblicazione precedente")
    except requests.RequestException as exc:
        raise RuntimeError("Impossibile verificare i post esistenti; pubblicazione bloccata") from exc
    # Rendi cliccabile la fonte, usando gli offset in byte richiesti da AT Protocol.
    source_url = text.rsplit("\nFonte: ", 1)[-1]
    start = len(text.rsplit("\nFonte: ", 1)[0].encode("utf-8")) + len("\nFonte: ".encode("utf-8"))
    facet = {"index": {"byteStart": start, "byteEnd": start + len(source_url.encode("utf-8"))},
             "features": [{"$type": "app.bsky.richtext.facet#link", "uri": source_url}]}
    payload = {"repo": did, "collection": "app.bsky.feed.post", "rkey": rkey,
               "record": {"$type": "app.bsky.feed.post", "text": text, "facets": [facet],
                          "createdAt": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}}
    res = requests.post("https://bsky.social/xrpc/com.atproto.repo.createRecord", json=payload,
                        headers=headers, timeout=30)
    if not res.ok:
        # Se l'invio è riuscito ma la risposta è andata persa, non si genera un secondo record.
        retry_check = requests.get(get_url, params=params, headers=headers, timeout=20)
        if retry_check.ok:
            return f"https://bsky.app/profile/{quote(handle, safe='.')}/post/{rkey}", True
        raise RuntimeError(f"Bluesky non ha accettato il post (HTTP {res.status_code})")
    return f"https://bsky.app/profile/{quote(handle, safe='.')}/post/{rkey}", False


def approved_revision(comments, owner):
    revised = None
    for c in sorted(comments, key=lambda x: x["id"]):
        if c["user"]["login"].lower() != owner.lower():
            continue
        body = c.get("body", "").strip()
        if body.lower().startswith("/rivedi\n"):
            revised = body.split("\n", 1)[1].strip()
    return revised


def handler(event):
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        raise RuntimeError("Repository mancante")
    owner = repo.split("/")[0]
    sender = (event.get("sender") or {}).get("login", "")
    commenter = ((event.get("comment") or {}).get("user") or {}).get("login", "")
    # OWNER REALE identificato da evento autenticato GitHub; un lettore del sito non può falsificarlo.
    if sender.lower() != owner.lower() or commenter.lower() != owner.lower():
        print("Commento non autorizzato; ignorato")
        return
    issue = event.get("issue") or {}
    if "pull_request" in issue:
        print("Non sono supportati commenti sulle Pull Request")
        return
    number = issue.get("number")
    command = ((event.get("comment") or {}).get("body") or "").strip()
    if not command.lower().startswith(("/go", "/rivedi", "/scarta")):
        return
    gh = GitHub()
    issue = gh.request("GET", f"/issues/{number}")
    meta = unpack_meta(issue.get("body", ""))
    if not meta or meta.get("version") != 1:
        print("Issue priva di metadati Redazione PA. Ignorata.")
        return
    labels = gh.labels(number)
    if "pa-bozza" not in labels or "pa-scartato" in labels or "pa-pubblicato" in labels or issue["state"] != "open":
        print("Proposta già chiusa o non valida")
        return
    if command.lower() == "/scarta":
        gh.ensure_label("pa-scartato", "BF4444")
        gh.add_label(number, "pa-scartato")
        gh.comment(number, "**SCARTA eseguito.** Proposta archiviata senza pubblicazione. Decisione umana registrata.")
        gh.close(number)
        return
    if command.lower().startswith("/rivedi"):
        if not command.lower().startswith("/rivedi\n"):
            gh.comment(number, "Per rivedere il testo, usa `/rivedi` a capo e incolla il testo completo del nuovo post. Non viene pubblicato nulla.")
            return
        new_text = command.split("\n", 1)[1].strip()
        if len(new_text) < 20 or len(new_text) > 240 or re.search(r"(?i)https?://", new_text):
            gh.comment(number, "**Revisione non accettata:** usa 20–240 caratteri e nessun link (la fonte viene aggiunta automaticamente).")
            return
        gh.ensure_label("pa-rivisto", "D58E28")
        gh.add_label(number, "pa-rivisto")
        # Aggiorna anche il metadato dell'Issue: il pannello mostra sempre la versione effettiva.
        # La versione precedente resta comunque nella cronologia dei commenti GitHub.
        meta["draft"] = new_text
        meta["revised_by"] = owner
        meta["revised_at"] = utc_now()
        meta.setdefault("trace", []).append("RIVEDI umano: testo corretto da @" + owner + " (nessuna pubblicazione)")
        gh.request("PATCH", f"/issues/{number}", json={"body": make_issue_text(meta)})
        gh.comment(number, "**RIVEDI registrato.** Ho aggiornato la bozza visibile anche nel pannello. Occorre un nuovo `/go` esplicito per pubblicarla.")
        return
    go_match = re.fullmatch(r"/go(?: ([0-9a-fA-F]{64}))?", command, flags=re.IGNORECASE)
    if not go_match:
        print("Comando GO non riconosciuto; nessuna azione")
        return
    expected_digest = go_match.group(1)
    # Il pannello diretto lega ogni GO esattamente alla versione controllata.
    # Il vecchio /go manuale resta disponibile per compatibilità con la demo precedente.
    if expected_digest:
        current_digest = hashlib.sha256(meta["draft"].encode("utf-8")).hexdigest()
        if expected_digest.lower() != current_digest:
            gh.comment(number, "**GO bloccato:** la bozza è cambiata. Aggiorna il pannello, ricontrolla e dai un nuovo GO.")
            return
    settings = config()
    if meta["mode"] != "live":
        gh.comment(number, "**GO bloccato:** questa è una simulazione DEMO. Esegui Ricerca in modalità LIVE per poter pubblicare.")
        return
    if not settings.get("publishing_enabled", False):
        gh.comment(number, "**GO bloccato:** in `config.json` la pubblicazione è disabilitata (`publishing_enabled: false`).")
        return
    comments = gh.request("GET", f"/issues/{number}/comments?per_page=100")
    revision = approved_revision(comments, owner)
    # Con impronta: usa ESATTAMENTE il testo nel metadato approvato.
    # Senza impronta: conserva il vecchio comportamento per i comandi manuali.
    draft = meta["draft"] if expected_digest else (revision if revision is not None else meta["draft"])
    if len(draft) > 240 or len(draft) < 20:
        gh.comment(number, "GO bloccato: il testo è troppo lungo o troppo breve. Rivedere la bozza.")
        return
    source = meta["source_url"].strip()
    if not source.startswith("https://"):
        gh.comment(number, "GO bloccato: la fonte deve usare HTTPS e va controllata.")
        return
    text = draft + "\nFonte: " + source
    # Controllo conservativo: Bluesky accetta al massimo 300 graphemi e 3000 byte.
    if len(text) > min(300, int(settings.get("max_post_characters", 300))) or len(text.encode("utf-8")) > 2900:
        gh.comment(number, "GO bloccato: testo + link della fonte oltre i limiti di Bluesky. Riduci il testo con `/rivedi` e riprova.")
        return
    link, existed = atproto_post(number, text, repo)
    gh.ensure_label("pa-pubblicato", "1A8754")
    gh.add_label(number, "pa-pubblicato")
    gh.comment(number, "**GO eseguito** — post " + ("già presente (nessun duplicato)" if existed else "pubblicato") + ".\n\n" +
               f"**Link:** {link}\n\n**Autorizzato da:** @{owner}\n\n**Testo effettivo:**\n\n> " +
               text.replace("\n", "\n> ") + "\n\n*Le fonti e i controlli restano documentati nella Issue.*")
    gh.close(number)
    print("Pubblicazione conclusa:", link)


if __name__ == "__main__":
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        raise RuntimeError("Eseguire tramite workflow GitHub con GITHUB_EVENT_PATH")
    with open(path, encoding="utf-8") as f:
        handler(json.load(f))
