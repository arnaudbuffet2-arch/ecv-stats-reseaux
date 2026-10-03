"""
monthly_social_stats.py — Fetch mensuel des stats sociales ECV + écriture Sheet.

Plateformes :
  Instagram  : Windsor.ai REST API (compte emilecoachvocal)
  TikTok     : Windsor.ai REST API
  YouTube    : YouTube Analytics API (OAuth Google)
  Facebook   : saisie manuelle dans le Sheet (profil personnel, pas d'API)

Fonctionnement :
  - Détermine automatiquement le mois précédent
  - Lit les cumulatifs du mois n-1 dans le Sheet
  - Calcule les cumulatifs du mois n
  - Écrit dans le Sheet
  - Si le token Instagram est rafraîchi, l'écrit dans GITHUB_OUTPUT

Secrets GitHub requis (ecv-stats-reseaux repo) :
  WINDSOR_IG_API_KEY       Clé API Windsor.ai du compte emilecoachvocal (Instagram)
  WINDSOR_API_KEY          Clé API Windsor.ai
  WINDSOR_TIKTOK_ACCOUNT_ID  _000oB0WQoiB3lc6DPT71YnmS_hkex9HZ6hJ
  GOOGLE_CREDENTIALS_JSON  Contenu de ~/.ecv/credentials.json
  GOOGLE_TOKENS_JSON       Contenu de ~/.ecv/tokens.json (avec yt-analytics scope)
  FB_APP_ID                ID app Meta ECV (2316368072184834)
  FB_APP_SECRET            Secret app Meta ECV (dans Meta for Developers → ECV → Paramètres)
  GH_PAT                  PAT GitHub avec permission secrets:write (renouvellement auto token IG)

Usage local : python scripts/monthly_social_stats.py
GitHub Actions : appelé par le workflow "Stats mensuelles ECV"
"""

import json
import os
import re
import sys
import requests
from datetime import date, timedelta
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ── Config ─────────────────────────────────────────────────────────────
SHEET_ID = "1OReCrVznxOtrxTzSRqpsKEu0lvR0cwdPoCixFKhgyxs"
TAB      = "community management"
ROW_BASE = {"tiktok": 4, "instagram": 21, "youtube": 38}

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).lstrip("﻿").strip()

WINDSOR_IG_API_KEY    = _env("WINDSOR_IG_API_KEY")
WINDSOR_IG_ACCOUNT_ID = _env("WINDSOR_IG_ACCOUNT_ID", "17841478684062202")
WINDSOR_API_KEY       = _env("WINDSOR_API_KEY", "43f9bb233ba077e6487ec87ae59ef8223db8")
WINDSOR_TIKTOK_ID     = _env("WINDSOR_TIKTOK_ACCOUNT_ID", "_000oB0WQoiB3lc6DPT71YnmS_hkex9HZ6hJ")

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

FB_APP_ID  = _env("FB_APP_ID", "1791342518942491")
GH_REPO    = _env("GH_REPO", "arnaudbuffet2-arch/ecv-stats-reseaux")


# ── Périodes ────────────────────────────────────────────────────────────

def prev_month(today: date) -> tuple[int, int]:
    first = today.replace(day=1)
    last_month = first - timedelta(days=1)
    return last_month.year, last_month.month


def month_bounds(year: int, month: int) -> tuple[str, str]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def tiktok_bounds(year: int, month: int) -> tuple[str, str]:
    """TikTok : du 2 du mois au 1er du mois suivant."""
    start = date(year, month, 2)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start.isoformat(), end.isoformat()


def instagram_bounds(year: int, month: int) -> tuple[str, str]:
    """Instagram : du 2 du mois au 1er du mois suivant."""
    return tiktok_bounds(year, month)


# ── Auth Google ─────────────────────────────────────────────────────────

def get_gmail_creds() -> Credentials:
    """Credentials avec scope gmail.compose (GOOGLE_TOKENS_SITE_JSON)."""
    creds_env  = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    tokens_env = os.environ.get("GOOGLE_TOKENS_SITE_JSON")

    ecv_dir = Path.home() / ".ecv"
    ecv_dir.mkdir(exist_ok=True)

    if creds_env and tokens_env:
        cred_data = json.loads(creds_env.lstrip("﻿"))
        tokens    = json.loads(tokens_env.lstrip("﻿"))
    else:
        cred_data = json.loads((ecv_dir / "credentials.json").read_text())
        tokens    = json.loads((ecv_dir / "tokens_site.json").read_text())

    client_info = cred_data.get("installed") or cred_data.get("web")
    creds = Credentials(
        token         = None,
        refresh_token = tokens.get("refresh_token"),
        token_uri     = "https://oauth2.googleapis.com/token",
        client_id     = client_info["client_id"],
        client_secret = client_info["client_secret"],
        scopes        = ["https://www.googleapis.com/auth/gmail.compose"],
    )
    creds.refresh(Request())
    # Sauvegarder le token rafraîchi pour autonomie du système
    tokens["access_token"] = creds.token
    (ecv_dir / "tokens_site.json").write_text(json.dumps(tokens, indent=2))
    return creds


def get_google_creds() -> Credentials:
    creds_env  = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    tokens_env = os.environ.get("GOOGLE_TOKENS_JSON")

    ecv_dir = Path.home() / ".ecv"
    ecv_dir.mkdir(exist_ok=True)

    if creds_env and tokens_env:
        cred_data = json.loads(creds_env.lstrip("﻿"))
        tokens    = json.loads(tokens_env.lstrip("﻿"))
    else:
        cred_data = json.loads((ecv_dir / "credentials.json").read_text())
        tokens    = json.loads((ecv_dir / "tokens.json").read_text())

    client_info = cred_data.get("installed") or cred_data.get("web")
    creds = Credentials(
        token         = tokens.get("access_token"),
        refresh_token = tokens.get("refresh_token"),
        token_uri     = "https://oauth2.googleapis.com/token",
        client_id     = client_info["client_id"],
        client_secret = client_info["client_secret"],
        scopes        = GOOGLE_SCOPES,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        tokens["access_token"] = creds.token
    # Sauvegarder le token rafraîchi pour autonomie du système
    (ecv_dir / "tokens.json").write_text(json.dumps(tokens, indent=2))
    return creds


# ── Instagram (Windsor.ai) ─────────────────────────────────────────────

def fetch_instagram(year: int, month: int) -> dict:
    """Vues, likes, comments, shares sur la période ; abonnés = dernier followers_count connu."""
    since, until = instagram_bounds(year, month)
    resp = requests.get(
        "https://connectors.windsor.ai/instagram",
        params={
            "api_key":    WINDSOR_IG_API_KEY,
            "account_id": WINDSOR_IG_ACCOUNT_ID,
            "date_from":  since,
            "date_to":    until,
            "fields":     "date,views,likes,comments,shares",
        },
        timeout=30,
    ).json()
    if "error" in resp:
        raise RuntimeError(f"Windsor.ai Instagram : {resp['error']}")

    rows = [r for r in resp.get("data", []) if since <= r.get("date", "") < until]
    if not rows:
        raise ValueError(f"Windsor.ai Instagram : aucune donnée pour {since}→{until}")

    views    = sum(int(r.get("views") or 0)    for r in rows)
    likes    = sum(int(r.get("likes") or 0)    for r in rows)
    comments = sum(int(r.get("comments") or 0) for r in rows)
    shares   = sum(int(r.get("shares") or 0)   for r in rows)

    snap = requests.get(
        "https://connectors.windsor.ai/instagram",
        params={
            "api_key":    WINDSOR_IG_API_KEY,
            "account_id": WINDSOR_IG_ACCOUNT_ID,
            "date_from":  until,
            "date_to":    date.today().isoformat(),
            "fields":     "date,followers_count",
        },
        timeout=30,
    ).json()
    snapshots = [r for r in snap.get("data", []) if r.get("followers_count") is not None]
    if not snapshots:
        raise ValueError("Windsor.ai Instagram : aucun followers_count disponible")
    followers = int(snapshots[-1]["followers_count"])

    print(f"Instagram : followers={followers}, vues={views}, "
          f"likes={likes}, comments={comments}, shares={shares}")
    return {"followers": followers, "views": views, "likes": likes,
            "comments": comments, "shares": shares}


# ── TikTok (Windsor.ai) ─────────────────────────────────────────────────

def fetch_tiktok(year: int, month: int) -> dict:
    since, until = tiktok_bounds(year, month)
    resp = requests.get(
        "https://connectors.windsor.ai/tiktok_organic",
        params={
            "api_key":    WINDSOR_API_KEY,
            "account_id": WINDSOR_TIKTOK_ID,
            "date_from":  since,
            "date_to":    until,
            "fields":     "date,video_views,likes,comments,shares,total_followers_count",
        },
        timeout=30,
    ).json()

    rows = [r for r in resp.get("data", []) if since <= r.get("date", "") <= until]
    if not rows:
        raise ValueError(f"Windsor.ai TikTok : aucune donnée pour {since}→{until}")

    views    = sum(int(r.get("video_views", 0)) for r in rows)
    likes    = sum(int(r.get("likes", 0))       for r in rows)
    comments = sum(int(r.get("comments", 0)) for r in rows)
    shares   = sum(int(r.get("shares", 0))      for r in rows)
    followers = int(rows[-1].get("total_followers_count", 0))

    print(f"TikTok : followers={followers}, vues={views}, likes={likes}, "
          f"comments={comments}, shares={shares}")
    return {"followers": followers, "views": views, "likes": likes,
            "comments": comments, "shares": shares}


# ── YouTube Analytics ───────────────────────────────────────────────────

def fetch_youtube(creds: Credentials, year: int, month: int) -> dict:
    since, until = month_bounds(year, month)
    yta = build("youtubeAnalytics", "v2", credentials=creds)

    resp = yta.reports().query(
        ids="channel==MINE",
        startDate=since,
        endDate=until,
        metrics="views,likes,comments,shares,subscribersGained,subscribersLost",
    ).execute()

    row = resp.get("rows", [[0] * 6])[0]
    views, likes, comments, shares, gained, lost = [int(v) for v in row]
    net_subs = gained - lost

    print(f"YouTube : gain_abonnés={net_subs:+d}, vues={views}, "
          f"likes={likes}, comments={comments}, shares={shares}")
    return {"net_subs": net_subs, "views": views, "likes": likes,
            "comments": comments, "shares": shares}


# ── Email stats ─────────────────────────────────────────────────────────

import base64
from email.mime.text import MIMEText

MONTHS_FR = ["Janvier","Février","Mars","Avril","Mai","Juin",
             "Juillet","Août","Septembre","Octobre","Novembre","Décembre"]


def _pct(new, old):
    if not old:
        return "—"
    p = (new - old) / old * 100
    sign = "+" if p >= 0 else ""
    return f"{sign}{p:.1f}%"


def _fmt(n):
    return f"{int(n):,}".replace(",", " ")


def build_stats_email(year: int, month: int, tt: list, ig: list, yt: list,
                      p_tt: list, p_ig: list, p_yt: list) -> tuple[str, str]:
    """Retourne (subject, body). Listes format : [abo, vues, com, shares, likes]."""
    period = f"{MONTHS_FR[month - 1]} {year}"

    cons_abo    = tt[0] + ig[0] + yt[0]
    cons_vues   = tt[1] + ig[1] + yt[1]
    cons_com    = tt[2] + ig[2] + yt[2]
    cons_shares = tt[3] + ig[3] + yt[3]
    cons_likes  = tt[4] + ig[4] + yt[4]
    pcons_abo    = p_tt[0] + p_ig[0] + p_yt[0]
    pcons_vues   = p_tt[1] + p_ig[1] + p_yt[1]
    pcons_com    = p_tt[2] + p_ig[2] + p_yt[2]
    pcons_shares = p_tt[3] + p_ig[3] + p_yt[3]
    pcons_likes  = p_tt[4] + p_ig[4] + p_yt[4]

    lines = [
        "Bonjour,",
        "",
        f"Voici le récapitulatif des statistiques community management — {period} :",
        "(Les pourcentages d'évolution sont calculés par rapport au mois précédent.)",
        "",
        "── TikTok ──────────────────────────────────",
        f"  Abonnés     : {_fmt(tt[0])}  ({_pct(tt[0], p_tt[0])})",
        f"  Vues        : {_fmt(tt[1])}  ({_pct(tt[1], p_tt[1])})",
        f"  Commentaires: {_fmt(tt[2])}  ({_pct(tt[2], p_tt[2])})",
        f"  Partages    : {_fmt(tt[3])}  ({_pct(tt[3], p_tt[3])})",
        f"  J'aime      : {_fmt(tt[4])}  ({_pct(tt[4], p_tt[4])})",
        "",
        "── Instagram ───────────────────────────────",
        f"  Abonnés     : {_fmt(ig[0])}  ({_pct(ig[0], p_ig[0])})",
        f"  Vues        : {_fmt(ig[1])}  ({_pct(ig[1], p_ig[1])})",
        f"  Commentaires: {_fmt(ig[2])}  ({_pct(ig[2], p_ig[2])})",
        f"  Partages    : {_fmt(ig[3])}  ({_pct(ig[3], p_ig[3])})",
        f"  J'aime      : {_fmt(ig[4])}  ({_pct(ig[4], p_ig[4])})",
        "",
        "── YouTube ─────────────────────────────────",
        f"  Abonnés     : {_fmt(yt[0])}  ({_pct(yt[0], p_yt[0])})",
        f"  Vues        : {_fmt(yt[1])}  ({_pct(yt[1], p_yt[1])})",
        f"  Commentaires: {_fmt(yt[2])}  ({_pct(yt[2], p_yt[2])})",
        f"  Partages    : {_fmt(yt[3])}  ({_pct(yt[3], p_yt[3])})",
        f"  J'aime      : {_fmt(yt[4])}  ({_pct(yt[4], p_yt[4])})",
        "",
        "",
        "── Consolidé (TikTok + Instagram + YouTube) ──",
        f"  Abonnés     : {_fmt(cons_abo)}  ({_pct(cons_abo, pcons_abo)})",
        f"  Vues        : {_fmt(cons_vues)}  ({_pct(cons_vues, pcons_vues)})",
        f"  Commentaires: {_fmt(cons_com)}  ({_pct(cons_com, pcons_com)})",
        f"  Partages    : {_fmt(cons_shares)}  ({_pct(cons_shares, pcons_shares)})",
        f"  J'aime      : {_fmt(cons_likes)}  ({_pct(cons_likes, pcons_likes)})",
        "",
        "Cordialement,",
        "de la part de Arno CM Management - Arnaud Buffet",
    ]
    subject = f"Stats Community Management — {period}"
    return subject, "\n".join(lines)


def send_stats_email(year: int, month: int, tt: list, ig: list, yt: list,
                     p_tt: list, p_ig: list, p_yt: list):
    subject, body = build_stats_email(year, month, tt, ig, yt, p_tt, p_ig, p_yt)
    creds = get_gmail_creds()
    svc   = build("gmail", "v1", credentials=creds)
    msg   = MIMEText(body, "plain", "utf-8")
    msg["From"]    = "emilecoachvocal@gmail.com"
    msg["To"]      = "emilecoachvocal@gmail.com"
    msg["Cc"]      = "arnaud.buffet2@gmail.com, benedictemoyat.rp@gmail.com"
    msg["Subject"] = subject
    raw    = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"Email stats envoyé : {result['id']}")


# ── Sheet : lecture cumulatif précédent ─────────────────────────────────

def read_prev_cumul(service, month_num: int) -> dict:
    """Lit les valeurs cumulatives du mois précédent pour chaque plateforme."""
    prev = month_num - 1
    if prev == 0:
        return {"tiktok": [0]*5, "instagram": [0]*5, "youtube": [0]*5}

    result = {}
    for platform, base in ROW_BASE.items():
        row = base + prev
        rng = f"{TAB}!C{row}:G{row}"
        data = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID, range=rng
        ).execute()
        vals = data.get("values", [[0]*5])[0]
        parsed = [int(re.sub(r"[^\d]", "", str(v)) or 0) for v in vals]
        result[platform] = parsed + [0] * (5 - len(parsed))

    return result


# ── Sheet : écriture ────────────────────────────────────────────────────

def write_month(service, month_num: int, tiktok: list, instagram: list, youtube: list):
    updates = [
        {"range": f"{TAB}!C{ROW_BASE['tiktok'] + month_num}:G{ROW_BASE['tiktok'] + month_num}",
         "values": [tiktok]},
        {"range": f"{TAB}!C{ROW_BASE['instagram'] + month_num}:G{ROW_BASE['instagram'] + month_num}",
         "values": [instagram]},
        {"range": f"{TAB}!C{ROW_BASE['youtube'] + month_num}:G{ROW_BASE['youtube'] + month_num}",
         "values": [youtube]},
    ]
    result = service.spreadsheets().values().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"valueInputOption": "USER_ENTERED", "data": updates},
    ).execute()
    print(f"Sheet mis à jour : {result.get('totalUpdatedCells')} cellules (mois {month_num})")


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    target_year  = os.environ.get("TARGET_YEAR")
    target_month = os.environ.get("TARGET_MONTH")
    if target_year and target_month:
        year, month = int(target_year), int(target_month)
    else:
        year, month = prev_month(date.today())
    print(f"Traitement : {year}-{month:02d}")

    # Auth Google
    gcreds  = get_google_creds()
    sheets  = build("sheets", "v4", credentials=gcreds)

    # Lecture cumulatif n-1
    prev = read_prev_cumul(sheets, month)
    print(f"Cumulatif mois précédent : {prev}")

    # Instagram
    ig = fetch_instagram(year, month)

    # TikTok
    tt = fetch_tiktok(year, month)

    # YouTube
    yt = fetch_youtube(gcreds, year, month)

    # Cumulatifs  format sheet : [abonnés, vues, commentaires, partages, likes]
    p_tt = prev["tiktok"]
    p_ig = prev["instagram"]
    p_yt = prev["youtube"]

    tiktok_row    = [tt["followers"],
                     p_tt[1] + tt["views"],
                     p_tt[2] + tt["comments"],
                     p_tt[3] + tt["shares"],
                     p_tt[4] + tt["likes"]]

    instagram_row = [ig["followers"],
                     p_ig[1] + ig["views"],
                     p_ig[2] + ig["comments"],
                     p_ig[3] + ig["shares"],
                     p_ig[4] + ig["likes"]]

    # Abonnés YouTube = snapshot précédent + gain net du mois
    yt_subs = p_yt[0] + yt["net_subs"]
    youtube_row   = [yt_subs,
                     p_yt[1] + yt["views"],
                     p_yt[2] + yt["comments"],
                     p_yt[3] + yt["shares"],
                     p_yt[4] + yt["likes"]]

    print(f"TikTok  cumulatif : {tiktok_row}")
    print(f"Instagram cumulatif: {instagram_row}")
    print(f"YouTube cumulatif : {youtube_row}")

    write_month(sheets, month, tiktok_row, instagram_row, youtube_row)

    print("Envoi email stats...")
    send_stats_email(year, month, tiktok_row, instagram_row, youtube_row,
                     p_tt, p_ig, p_yt)


if __name__ == "__main__":
    main()