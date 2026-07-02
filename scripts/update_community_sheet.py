"""
Met à jour l'onglet 'community management' du Google Sheet ECV
avec les stats du mois précédent.

Secrets GitHub requis:
  GOOGLE_CREDENTIALS_JSON  — contenu de credentials.json
  GOOGLE_TOKENS_JSON       — contenu de tokens.json (compte emilecoachvocal)

Usage local  : python scripts/update_community_sheet.py
GitHub Actions : déclenché via workflow_dispatch ou cron
"""
import json
import os
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SHEET_ID = "1OReCrVznxOtrxTzSRqpsKEu0lvR0cwdPoCixFKhgyxs"
TAB      = "community management"

# Ligne de base : row = base + numero_mois (1=jan … 12=dec)
ROW_BASE = {"tiktok": 4, "instagram": 21, "youtube": 38}

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


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


def update_month(month_num: int, tiktok: list, instagram: list, youtube: list):
    """
    month_num  : 1=jan, 2=fev, … 12=dec
    tiktok / instagram / youtube : [abonnes, vues, commentaires, partages, likes]
    """
    creds   = get_credentials()
    service = build("sheets", "v4", credentials=creds)

    row_tt = ROW_BASE["tiktok"]    + month_num
    row_ig = ROW_BASE["instagram"] + month_num
    row_yt = ROW_BASE["youtube"]   + month_num

    updates = [
        {"range": f"'{TAB}'!C{row_tt}:G{row_tt}", "values": [tiktok]},
        {"range": f"'{TAB}'!C{row_ig}:G{row_ig}", "values": [instagram]},
        {"range": f"'{TAB}'!C{row_yt}:G{row_yt}", "values": [youtube]},
    ]

    result = service.spreadsheets().values().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"valueInputOption": "USER_ENTERED", "data": updates},
    ).execute()

    print(f"OK — {result.get('totalUpdatedCells')} cellules mises à jour (mois {month_num})")


if __name__ == "__main__":
    # ── À renseigner chaque mois ────────────────────────────────────
    # Format : [abonnés, vues, commentaires, partages, likes]
    update_month(
        month_num  = 6,
        tiktok     = [0, 0, 0, 0, 0],
        instagram  = [0, 0, 0, 0, 0],
        youtube    = [0, 0, 0, 0, 0],
    )
