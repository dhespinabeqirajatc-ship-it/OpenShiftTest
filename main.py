import os
from typing import Dict, Any, List

import pandas as pd
import requests
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Excel to Workiva JSON Demo")

WORKIVA_API_URL = os.getenv("WORKIVA_API_URL", "")
WORKIVA_BEARER_TOKEN = os.getenv("WORKIVA_BEARER_TOKEN", "")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    return df


def transform_excel_to_json(df: pd.DataFrame) -> Dict[str, Any]:
    df = normalize_columns(df)

    required = {"entity", "account", "amount", "period"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)

    records: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        records.append(
            {
                "entity": str(row["entity"]).strip(),
                "account": str(row["account"]).strip(),
                "period": str(row["period"]).strip(),
                "value": float(row["amount"]),
                "source": "client_excel_upload",
            }
        )

    return {
        "recordCount": len(records),
        "records": records,
    }


@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <html>
      <head><title>Excel to Workiva JSON Demo</title></head>
      <body style="font-family: Arial; max-width: 760px; margin: 40px auto;">
        <h1>Excel to Workiva JSON Demo</h1>
        <p>Upload an Excel file with columns: entity, account, amount, period.</p>
        <form action="/upload" enctype="multipart/form-data" method="post">
          <input name="file" type="file" accept=".xlsx" />
          <button type="submit">Upload and transform</button>
        </form>
      </body>
    </html>
    """


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Please upload an .xlsx file")

    try:
        df = pd.read_excel(file.file, engine="openpyxl")
        payload = transform_excel_to_json(df)
        return JSONResponse(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Transformation failed: {exc}")


@app.post("/send-to-workiva")
async def send_to_workiva(file: UploadFile = File(...)):
    if not WORKIVA_API_URL or not WORKIVA_BEARER_TOKEN:
        raise HTTPException(
            status_code=400,
            detail="Set WORKIVA_API_URL and WORKIVA_BEARER_TOKEN environment variables first.",
        )

    df = pd.read_excel(file.file, engine="openpyxl")
    payload = transform_excel_to_json(df)

    response = requests.post(
        WORKIVA_API_URL,
        json=payload,
        headers={
            "Authorization": f"Bearer {WORKIVA_BEARER_TOKEN}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )

    return {
        "workivaStatusCode": response.status_code,
        "workivaResponse": response.text,
        "sentPayload": payload,
    }
