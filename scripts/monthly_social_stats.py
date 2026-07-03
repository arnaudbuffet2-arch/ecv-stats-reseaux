"""
monthly_social_stats.py — Fetch mensuel des stats sociales ECV + écriture Sheet.

Plateformes :
  Instagram  : Meta Graph API (token long-lived, auto-refresh)
  TikTok     : Windsor.ai REST API
  YouTube    : YouTube Analytics API (OAuth Google)

Fonctionnement :
  - Détermine automatiquement le mois précédent
  - Lit les cumulatifs du mois n-1 dans le Sheet
  - Calcule les cumulatifs du mois n
  - Écrit dans le Sheet
  - Si le token Instagram est rafraîchi, l'écrit dans GITHUB_OUTPUT

Secrets GitHub requis (ecv-stats-reseaux repo) :
  IG_ACCESS_TOKEN          Instagram long-lived token (auto-rafraîchi)
  IG_USER_ID               17841478684062202
  WINDSOR_API_KEY          Clé API Windsor.ai
  WINDSOR_TIKTOK_ACCOUNT_ID  _000oB0WQoiB3lc6DPT71YnmS_hkex9HZ6hJ
  GOOGLE_CREDENTIALS_JSON  Contenu de ~/.ecv/credentials.json
  GOOGLE_TOKENS_JSON       Contenu de ~/.ecv/tokens.json (avec yt-analytics scope)
  FB_APP_ID                ID app Meta ECV (2316368072184834)
  FB_APP_SECRET            Secret app Meta ECV (dans Meta for Developers → ECV → Paramètres)
  GH_PAT                   PAT GitHub avec permission secrets:write (renouvellement auto token IG)

Usage local : python scripts/monthly_social_stats.py
GitHub Actions : appelé par le workflow "Stats mensuelles ECV"
"""

import json
import os
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

IG_USER_ID            = _env("IG_USER_ID", "17841478684062202")
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
    return creds


def get_google_creds() -> Credentials:
    creds_env  = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    tokens_env = os.environ.get("GOOGLE_TOKENS_JSON")

    ecv_dir = Path.home() / ".ecv"

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
    return creds


# ── Instagram ───────────────────────────────────────────────────────────

def _update_github_secret(name: str, value: str):
    """Chiffre et pousse un secret dans le repo GitHub via l'API."""
    gh_pat = _env("GH_PAT")
    if not gh_pat:
        return
    try:
        import base64
        from nacl import encoding, public as nacl_public

        headers = {
            "Authorization": f"Bearer {gh_pat}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        pk = requests.get(
            f"https://api.github.com/repos/{GH_REPO}/actions/secrets/public-key",
            headers=headers, timeout=10,
        ).json()
        pub_key   = nacl_public.PublicKey(pk["key"].encode(), encoding.Base64Encoder)
        encrypted = base64.b64encode(
            nacl_public.SealedBox(pub_key).encrypt(value.encode())
        ).decode()
        requests.put(
            f"https://api.github.com/repos/{GH_REPO}/actions/secrets/{name}",
            headers=headers,
            json={"encrypted_value": encrypted, "key_id": pk["key_id"]},
            timeout=10,
        ).raise_for_status()
        print(f"Secret GitHub '{name}' mis à jour.")
    except Exception as e:
        print(f"Avertissement : mise à jour secret GitHub échouée : {e}")


def ig_refresh_token(token: str) -> str:
    """Échange le token EAAL contre un nouveau token 60 jours via fb_exchange_token.
    Met à jour le secret GitHub IG_ACCESS_TOKEN automatiquement si GH_PAT est présent."""
    app_secret = _env("FB_APP_SECRET")
    if not app_secret:
        print("Avertissement : FB_APP_SECRET manquant — skip refresh token.")
        return token
    try:
        resp = requests.get(
            "https://graph.facebook.com/oauth/access_token",
            params={
                "grant_type":        "fb_exchange_token",
                "client_id":         FB_APP_ID,
                "client_secret":     app_secret,
                "fb_exchange_token": token,
            },
            timeout=15,
        )
        data = resp.json()
        if "access_token" in data:
            new_token = data["access_token"]
            expires   = data.get("expires_in", "?")
            print(f"Token Instagram renouvelé (expire dans {expires}s ≈ 60 jours).")
            _update_github_secret("IG_ACCESS_TOKEN", new_token)
            return new_token
        print(f"Avertissement : fb_exchange_token a répondu : {data}")
    except Exception as e:
        print(f"Avertissement : refresh token exception : {e}")
    return token


def fetch_instagram(token: str, year: int, month: int) -> dict:
    """Retourne vues, likes, comments, shares, followers pour le mois."""
    since, until = instagram_bounds(year, month)

    # Abonnés actuels
    me = requests.get(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}",
        params={"fields": "followers_count", "access_token": token},
        timeout=15,
    ).json()
    followers = me.get("followers_count", 0)

    # Insights : metric_type=total_value requis depuis API v22+ pour ces métriques
    metrics = ["views", "likes", "comments", "shares"]
    insights = requests.get(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}/insights",
        params={
            "metric":      ",".join(metrics),
            "period":      "day",
            "metric_type": "total_value",
            "since":       since,
            "until":       until,
            "access_token": token,
        },
        timeout=30,
    ).json()

    if "error" in insights:
        raise RuntimeError(f"Instagram API error: {insights['error']}")

    totals = {m: 0 for m in metrics}
    for item in insights.get("data", []):
        m_name = item["name"]
        tv = item.get("total_value", {})
        if "value" in tv:
            totals[m_name] = tv["value"]
        else:
            for val in item.get("values", []):
                totals[m_name] = totals.get(m_name, 0) + val.get("value", 0)

    print(f"Instagram : followers={followers}, vues={totals['views']}, "
          f"likes={totals['likes']}, comments={totals['comments']}, shares={totals['shares']}")
    return {
        "followers":    followers,
        "views":        totals["views"],
        "likes":        totals["likes"],
        "comments":     totals["comments"],
        "shares":       totals["shares"],
    }


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
        "── Consolidé ───────────────────────────────",
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
        parsed = [int(str(v).replace(" ", "").replace(" ", "").replace(" ", "").replace(",", "") or 0) for v in vals]
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
    ig_token = os.environ.get("IG_ACCESS_TOKEN", "")
    if not ig_token:
        # Lecture locale pour dev
        cfg_path = Path(__file__).parent / "social_config.json"
        if cfg_path.exists():
            ig_token = json.loads(cfg_path.read_text()).get("instagram", {}).get("access_token", "")
    if not ig_token:
        raise ValueError("IG_ACCESS_TOKEN manquant")
    ig_token = ig_refresh_token(ig_token)
    ig = fetch_instagram(ig_token, year, month)

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

    # Abonnés YouTube = snapshot précédent + gain net du mois (pas de scope youtube.readonly nécessaire)
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
