"""
Envoie un email récapitulatif des stats community management ECV.
Expéditeur : emilecoachvocal@gmail.com
Destinataires : emilecoachvocal@gmail.com + arnaud.buffet2@gmail.com

Secrets GitHub requis:
  GOOGLE_CREDENTIALS_JSON  — contenu de credentials.json
  GOOGLE_TOKENS_JSON       — contenu de tokens.json (compte emilecoachvocal)

Usage local  : python scripts/send_community_email.py
GitHub Actions : déclenché via workflow_dispatch ou cron
"""
import json
import os
import base64
from pathlib import Path
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]


def get_credentials():
    creds_env  = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    tokens_env = os.environ.get("GOOGLE_TOKENS_JSON")

    if creds_env and tokens_env:
        cred_data = json.loads(creds_env.lstrip("﻿"))
        tokens    = json.loads(tokens_env.lstrip("﻿"))
    else:
        ecv_dir   = Path.home() / ".ecv"
        cred_data = json.loads((ecv_dir / "credentials.json").read_text())
        tokens    = json.loads((ecv_dir / "tokens.json").read_text())

    client_info = cred_data.get("installed") or cred_data.get("web")
    creds = Credentials(
        token         = tokens.get("access_token"),
        refresh_token = tokens.get("refresh_token"),
        token_uri     = "https://oauth2.googleapis.com/token",
        client_id     = client_info["client_id"],
        client_secret = client_info["client_secret"],
        scopes        = SCOPES,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        if not os.environ.get("GOOGLE_TOKENS_JSON"):
            tokens["access_token"] = creds.token
            (Path.home() / ".ecv" / "tokens.json").write_text(json.dumps(tokens, indent=2))
    return creds


def pct(new, old):
    if not old:
        return "—"
    p = (new - old) / old * 100
    sign = "+" if p >= 0 else ""
    return f"{sign}{p:.1f}%"


def build_body(period: str, stats: dict, prev_stats: dict) -> str:
    tt  = stats["tiktok"]
    ig  = stats["instagram"]
    yt  = stats["youtube"]
    ptt = prev_stats["tiktok"]
    pig = prev_stats["instagram"]
    pyt = prev_stats["youtube"]

    cons_vues   = tt["vues"]   + ig["vues"]   + yt["vues"]
    cons_likes  = tt["likes"]  + ig["likes"]  + yt["likes"]
    cons_com    = tt["com"]    + ig["com"]    + yt["com"]
    cons_shares = tt["shares"] + ig["shares"] + yt["shares"]
    cons_abo    = tt["abo"]    + ig["abo"]    + yt["abo"]

    pcons_vues   = ptt["vues"]   + pig["vues"]   + pyt["vues"]
    pcons_likes  = ptt["likes"]  + pig["likes"]  + pyt["likes"]
    pcons_com    = ptt["com"]    + pig["com"]    + pyt["com"]
    pcons_shares = ptt["shares"] + pig["shares"] + pyt["shares"]
    pcons_abo    = ptt["abo"]    + pig["abo"]    + pyt["abo"]

    def fmt(n): return f"{n:,}".replace(",", " ")

    lines = [
        "Bonjour,",
        "",
        f"Voici le récapitulatif des statistiques community management — {period} :",
        "(Évolutions par rapport au mois précédent.)",
        "",
        "── TikTok ──────────────────────────────────",
        f"  Abonnés     : {fmt(tt['abo'])}  ({pct(tt['abo'], ptt['abo'])})",
        f"  Vues        : {fmt(tt['vues'])}  ({pct(tt['vues'], ptt['vues'])})",
        f"  J'aime      : {fmt(tt['likes'])}  ({pct(tt['likes'], ptt['likes'])})",
        f"  Commentaires: {fmt(tt['com'])}  ({pct(tt['com'], ptt['com'])})",
        f"  Partages    : {fmt(tt['shares'])}  ({pct(tt['shares'], ptt['shares'])})",
        "",
        "── Instagram ───────────────────────────────",
        f"  Abonnés     : {fmt(ig['abo'])}  ({pct(ig['abo'], pig['abo'])})",
        f"  Vues        : {fmt(ig['vues'])}  ({pct(ig['vues'], pig['vues'])})",
        f"  J'aime      : {fmt(ig['likes'])}  ({pct(ig['likes'], pig['likes'])})",
        f"  Commentaires: {fmt(ig['com'])}  ({pct(ig['com'], pig['com'])})",
        f"  Partages    : {fmt(ig['shares'])}  ({pct(ig['shares'], pig['shares'])})",
        "",
        "── YouTube ─────────────────────────────────",
        f"  Abonnés     : {fmt(yt['abo'])}  ({pct(yt['abo'], pyt['abo'])})",
        f"  Vues        : {fmt(yt['vues'])}  ({pct(yt['vues'], pyt['vues'])})",
        f"  J'aime      : {fmt(yt['likes'])}  ({pct(yt['likes'], pyt['likes'])})",
        f"  Commentaires: {fmt(yt['com'])}  ({pct(yt['com'], pyt['com'])})",
        f"  Partages    : {fmt(yt['shares'])}  ({pct(yt['shares'], pyt['shares'])})",
        "",
        "── Consolidé ───────────────────────────────",
        f"  Abonnés     : {fmt(cons_abo)}  ({pct(cons_abo, pcons_abo)})",
        f"  Vues        : {fmt(cons_vues)}  ({pct(cons_vues, pcons_vues)})",
        f"  J'aime      : {fmt(cons_likes)}  ({pct(cons_likes, pcons_likes)})",
        f"  Commentaires: {fmt(cons_com)}  ({pct(cons_com, pcons_com)})",
        f"  Partages    : {fmt(cons_shares)}  ({pct(cons_shares, pcons_shares)})",
        "",
        "Cordialement,",
        "de la part de Arno CM Management - Arnaud Buffet",
    ]
    return "\n".join(lines)


def send_email(subject: str, body: str):
    creds   = get_credentials()
    service = build("gmail", "v1", credentials=creds)

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"]    = "emilecoachvocal@gmail.com"
    msg["To"]      = "emilecoachvocal@gmail.com"
    msg["Cc"]      = "arnaud.buffet2@gmail.com"
    msg["Subject"] = subject

    raw    = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(
        userId="me",
        body={"raw": raw}
    ).execute()
    print(f"Email envoyé : {result['id']}")


if __name__ == "__main__":
    # ── À renseigner chaque mois ────────────────────────────────────
    juin = {
        "tiktok":    {"abo": 0, "vues": 0, "likes": 0, "com": 0, "shares": 0},
        "instagram": {"abo": 0, "vues": 0, "likes": 0, "com": 0, "shares": 0},
        "youtube":   {"abo": 0, "vues": 0, "likes": 0, "com": 0, "shares": 0},
    }
    mai = {
        "tiktok":    {"abo": 106043, "vues": 13821878, "likes": 1145122, "com": 7679,  "shares": 59047},
        "instagram": {"abo": 40872,  "vues": 5857905,  "likes": 209504,  "com": 1604,  "shares": 28629},
        "youtube":   {"abo": 4410,   "vues": 1005269,  "likes": 31012,   "com": 310,   "shares": 853},
    }

    body = build_body("Juin 2026", juin, mai)
    send_email("Stats Community Management — Juin 2026", body)
