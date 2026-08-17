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
    return r"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>Excel to Workiva JSON</title>
      <style>
        :root {
          --bg: #f4f7fb;
          --surface: #ffffff;
          --surface-soft: #f8fafc;
          --text: #172033;
          --muted: #64748b;
          --line: #dbe3ef;
          --primary: #3157d5;
          --primary-dark: #2444af;
          --success: #138a62;
          --danger: #c2414b;
          --shadow: 0 24px 70px rgba(26, 39, 74, 0.12);
          --radius: 22px;
        }

        * { box-sizing: border-box; }

        body {
          margin: 0;
          min-height: 100vh;
          font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          color: var(--text);
          background:
            radial-gradient(circle at 10% 0%, rgba(49, 87, 213, 0.14), transparent 30%),
            radial-gradient(circle at 90% 15%, rgba(91, 168, 255, 0.14), transparent 28%),
            var(--bg);
        }

        .shell {
          width: min(1120px, calc(100% - 32px));
          margin: 0 auto;
          padding: 52px 0 64px;
        }

        .topbar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
          margin-bottom: 30px;
        }

        .brand {
          display: flex;
          align-items: center;
          gap: 12px;
          font-weight: 800;
          letter-spacing: -0.02em;
        }

        .brand-mark {
          display: grid;
          place-items: center;
          width: 42px;
          height: 42px;
          border-radius: 13px;
          background: linear-gradient(135deg, #3157d5, #5b8def);
          color: white;
          box-shadow: 0 10px 28px rgba(49, 87, 213, 0.26);
        }

        .badge {
          padding: 8px 12px;
          border: 1px solid rgba(49, 87, 213, 0.16);
          border-radius: 999px;
          color: var(--primary);
          background: rgba(49, 87, 213, 0.06);
          font-size: 13px;
          font-weight: 700;
        }

        .hero {
          display: grid;
          grid-template-columns: 1.05fr 0.95fr;
          gap: 28px;
          align-items: stretch;
        }

        .intro {
          padding: 26px 10px 20px 0;
        }

        .eyebrow {
          color: var(--primary);
          font-size: 13px;
          font-weight: 800;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          margin-bottom: 14px;
        }

        h1 {
          margin: 0;
          max-width: 700px;
          font-size: clamp(38px, 5.5vw, 64px);
          line-height: 1.02;
          letter-spacing: -0.045em;
        }

        .lead {
          max-width: 650px;
          margin: 22px 0 28px;
          color: var(--muted);
          font-size: 18px;
          line-height: 1.65;
        }

        .schema {
          display: flex;
          flex-wrap: wrap;
          gap: 9px;
        }

        .chip {
          padding: 8px 11px;
          border-radius: 10px;
          border: 1px solid var(--line);
          background: rgba(255,255,255,.68);
          color: #44516a;
          font: 700 13px ui-monospace, SFMono-Regular, Menlo, monospace;
        }

        .card {
          background: rgba(255,255,255,.94);
          border: 1px solid rgba(219, 227, 239, .9);
          border-radius: var(--radius);
          box-shadow: var(--shadow);
          padding: 28px;
          backdrop-filter: blur(8px);
        }

        .card h2 {
          margin: 0 0 6px;
          font-size: 22px;
          letter-spacing: -0.025em;
        }

        .card-subtitle {
          margin: 0 0 20px;
          color: var(--muted);
          line-height: 1.5;
        }

        .dropzone {
          display: block;
          padding: 34px 20px;
          border: 2px dashed #b8c5da;
          border-radius: 18px;
          text-align: center;
          cursor: pointer;
          background: var(--surface-soft);
          transition: .2s ease;
        }

        .dropzone:hover,
        .dropzone.dragover {
          border-color: var(--primary);
          background: #f3f6ff;
          transform: translateY(-1px);
        }

        .drop-icon {
          width: 54px;
          height: 54px;
          margin: 0 auto 14px;
          display: grid;
          place-items: center;
          border-radius: 16px;
          background: #e9efff;
          color: var(--primary);
          font-size: 26px;
        }

        .dropzone strong { display: block; font-size: 16px; }
        .dropzone span { display: block; color: var(--muted); margin-top: 7px; font-size: 14px; }
        input[type=file] { display: none; }

        .file-row {
          display: none;
          align-items: center;
          gap: 12px;
          margin-top: 14px;
          padding: 13px 14px;
          border: 1px solid var(--line);
          border-radius: 13px;
          background: #fff;
        }

        .file-row.visible { display: flex; }
        .file-icon { font-size: 22px; }
        .file-meta { min-width: 0; flex: 1; }
        .file-name { font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .file-size { margin-top: 3px; color: var(--muted); font-size: 12px; }

        .actions {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 10px;
          margin-top: 18px;
        }

        button {
          min-height: 46px;
          border: 0;
          border-radius: 12px;
          padding: 0 16px;
          cursor: pointer;
          font-size: 14px;
          font-weight: 800;
          transition: .18s ease;
        }

        button:disabled { opacity: .5; cursor: not-allowed; }
        .primary { background: var(--primary); color: white; }
        .primary:hover:not(:disabled) { background: var(--primary-dark); transform: translateY(-1px); }
        .secondary { background: #edf2f8; color: #334155; }
        .secondary:hover:not(:disabled) { background: #e2e8f0; }

        .status {
          display: none;
          margin-top: 15px;
          padding: 12px 14px;
          border-radius: 12px;
          font-size: 14px;
          line-height: 1.45;
        }
        .status.visible { display: block; }
        .status.success { color: #0d6c4c; background: #eaf8f2; border: 1px solid #bee7d6; }
        .status.error { color: #9d3039; background: #fff0f1; border: 1px solid #f3c7cb; }
        .status.info { color: #38517d; background: #eff4ff; border: 1px solid #d5e0ff; }

        .result {
          margin-top: 28px;
          display: none;
        }
        .result.visible { display: block; }

        .result-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 12px;
        }

        .result-title { display: flex; align-items: baseline; gap: 10px; }
        .result-title h2 { margin: 0; font-size: 20px; }
        .record-count { color: var(--success); font-size: 13px; font-weight: 800; }

        .result-actions { display: flex; gap: 8px; }
        .small-btn { min-height: 36px; padding: 0 12px; font-size: 12px; }

        pre {
          margin: 0;
          max-height: 460px;
          overflow: auto;
          border-radius: 16px;
          padding: 20px;
          background: #101827;
          color: #d7e2f4;
          font: 13px/1.65 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
          white-space: pre-wrap;
          word-break: break-word;
        }

        .steps {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 14px;
          margin-top: 28px;
        }

        .step {
          padding: 18px;
          border: 1px solid var(--line);
          border-radius: 16px;
          background: rgba(255,255,255,.62);
        }

        .step-number {
          width: 28px;
          height: 28px;
          display: grid;
          place-items: center;
          border-radius: 9px;
          background: #e9efff;
          color: var(--primary);
          font-weight: 900;
          font-size: 12px;
          margin-bottom: 12px;
        }

        .step strong { display: block; margin-bottom: 5px; }
        .step span { color: var(--muted); font-size: 13px; line-height: 1.45; }

        footer {
          margin-top: 30px;
          text-align: center;
          color: #8793a8;
          font-size: 12px;
        }

        @media (max-width: 820px) {
          .shell { padding-top: 28px; }
          .hero { grid-template-columns: 1fr; }
          .intro { padding-right: 0; }
          .steps { grid-template-columns: 1fr; }
        }

        @media (max-width: 520px) {
          .topbar { align-items: flex-start; }
          .badge { display: none; }
          .card { padding: 20px; }
          .actions { grid-template-columns: 1fr; }
          .result-head { align-items: flex-start; flex-direction: column; }
        }
      </style>
    </head>
    <body>
      <main class="shell">
        <div class="topbar">
          <div class="brand">
            <div class="brand-mark">↗</div>
            <span>Data Bridge</span>
          </div>
          <div class="badge">FastAPI · OpenShift ready</div>
        </div>

        <section class="hero">
          <div class="intro">
            <div class="eyebrow">Excel → Workiva JSON</div>
            <h1>Turn spreadsheet data into clean JSON.</h1>
            <p class="lead">
              Upload an Excel trial balance and convert it into a structured payload ready for review or delivery to Workiva.
            </p>
            <div class="schema" aria-label="Required Excel columns">
              <span class="chip">entity</span>
              <span class="chip">account</span>
              <span class="chip">amount</span>
              <span class="chip">period</span>
            </div>

            <div class="steps">
              <div class="step"><div class="step-number">01</div><strong>Upload</strong><span>Select or drag in an .xlsx file.</span></div>
              <div class="step"><div class="step-number">02</div><strong>Transform</strong><span>Validate columns and convert rows to JSON.</span></div>
              <div class="step"><div class="step-number">03</div><strong>Review</strong><span>Inspect, copy, or download the generated payload.</span></div>
            </div>
          </div>

          <div class="card">
            <h2>Upload workbook</h2>
            <p class="card-subtitle">Only .xlsx files are accepted. Your required columns are checked automatically.</p>

            <label class="dropzone" id="dropzone" for="fileInput">
              <div class="drop-icon">⇧</div>
              <strong>Drop your Excel file here</strong>
              <span>or click to browse from your computer</span>
            </label>
            <input id="fileInput" type="file" accept=".xlsx" />

            <div class="file-row" id="fileRow">
              <div class="file-icon">📄</div>
              <div class="file-meta">
                <div class="file-name" id="fileName"></div>
                <div class="file-size" id="fileSize"></div>
              </div>
            </div>

            <div class="actions">
              <button class="primary" id="transformBtn" disabled>Transform to JSON</button>
              <button class="secondary" id="workivaBtn" disabled>Send to Workiva</button>
            </div>

            <div class="status" id="status"></div>
          </div>
        </section>

        <section class="result" id="result">
          <div class="card">
            <div class="result-head">
              <div class="result-title">
                <h2>JSON output</h2>
                <span class="record-count" id="recordCount"></span>
              </div>
              <div class="result-actions">
                <button class="secondary small-btn" id="copyBtn">Copy JSON</button>
                <button class="secondary small-btn" id="downloadBtn">Download</button>
              </div>
            </div>
            <pre id="jsonOutput"></pre>
          </div>
        </section>

        <footer>Excel to Workiva JSON Demo · Built for a simple GitHub → OpenShift workflow</footer>
      </main>

      <script>
        const fileInput = document.getElementById('fileInput');
        const dropzone = document.getElementById('dropzone');
        const fileRow = document.getElementById('fileRow');
        const fileName = document.getElementById('fileName');
        const fileSize = document.getElementById('fileSize');
        const transformBtn = document.getElementById('transformBtn');
        const workivaBtn = document.getElementById('workivaBtn');
        const statusBox = document.getElementById('status');
        const result = document.getElementById('result');
        const jsonOutput = document.getElementById('jsonOutput');
        const recordCount = document.getElementById('recordCount');
        const copyBtn = document.getElementById('copyBtn');
        const downloadBtn = document.getElementById('downloadBtn');

        let selectedFile = null;
        let currentPayload = null;

        const formatBytes = (bytes) => {
          if (!bytes) return '0 KB';
          const kb = bytes / 1024;
          return kb < 1024 ? `${kb.toFixed(1)} KB` : `${(kb / 1024).toFixed(1)} MB`;
        };

        function showStatus(message, type = 'info') {
          statusBox.textContent = message;
          statusBox.className = `status visible ${type}`;
        }

        function clearStatus() {
          statusBox.className = 'status';
          statusBox.textContent = '';
        }

        function setFile(file) {
          clearStatus();
          result.classList.remove('visible');
          currentPayload = null;

          if (!file) return;
          if (!file.name.toLowerCase().endsWith('.xlsx')) {
            selectedFile = null;
            fileRow.classList.remove('visible');
            transformBtn.disabled = true;
            workivaBtn.disabled = true;
            showStatus('Please choose an Excel .xlsx file.', 'error');
            return;
          }

          selectedFile = file;
          fileName.textContent = file.name;
          fileSize.textContent = formatBytes(file.size);
          fileRow.classList.add('visible');
          transformBtn.disabled = false;
          workivaBtn.disabled = false;
        }

        fileInput.addEventListener('change', () => setFile(fileInput.files[0]));

        ['dragenter', 'dragover'].forEach(eventName => {
          dropzone.addEventListener(eventName, (event) => {
            event.preventDefault();
            dropzone.classList.add('dragover');
          });
        });

        ['dragleave', 'drop'].forEach(eventName => {
          dropzone.addEventListener(eventName, (event) => {
            event.preventDefault();
            dropzone.classList.remove('dragover');
          });
        });

        dropzone.addEventListener('drop', (event) => {
          const file = event.dataTransfer.files[0];
          setFile(file);
        });

        async function postFile(endpoint, loadingMessage) {
          if (!selectedFile) return;

          transformBtn.disabled = true;
          workivaBtn.disabled = true;
          showStatus(loadingMessage, 'info');

          try {
            const formData = new FormData();
            formData.append('file', selectedFile);
            const response = await fetch(endpoint, { method: 'POST', body: formData });
            const data = await response.json();

            if (!response.ok) {
              throw new Error(data.detail || 'The request could not be completed.');
            }
            return data;
          } catch (error) {
            showStatus(error.message, 'error');
            throw error;
          } finally {
            transformBtn.disabled = false;
            workivaBtn.disabled = false;
          }
        }

        transformBtn.addEventListener('click', async () => {
          try {
            const data = await postFile('/upload', 'Transforming workbook…');
            currentPayload = data;
            jsonOutput.textContent = JSON.stringify(data, null, 2);
            recordCount.textContent = `${data.recordCount ?? 0} records`;
            result.classList.add('visible');
            showStatus('Transformation completed successfully.', 'success');
            result.scrollIntoView({ behavior: 'smooth', block: 'start' });
          } catch (_) {}
        });

        workivaBtn.addEventListener('click', async () => {
          try {
            const data = await postFile('/send-to-workiva', 'Sending payload to Workiva…');
            currentPayload = data;
            jsonOutput.textContent = JSON.stringify(data, null, 2);
            recordCount.textContent = data.sentPayload?.recordCount != null ? `${data.sentPayload.recordCount} records sent` : 'Response received';
            result.classList.add('visible');
            showStatus(`Workiva request completed with status ${data.workivaStatusCode}.`, 'success');
            result.scrollIntoView({ behavior: 'smooth', block: 'start' });
          } catch (_) {}
        });

        copyBtn.addEventListener('click', async () => {
          if (!currentPayload) return;
          await navigator.clipboard.writeText(JSON.stringify(currentPayload, null, 2));
          const oldText = copyBtn.textContent;
          copyBtn.textContent = 'Copied';
          setTimeout(() => copyBtn.textContent = oldText, 1200);
        });

        downloadBtn.addEventListener('click', () => {
          if (!currentPayload) return;
          const blob = new Blob([JSON.stringify(currentPayload, null, 2)], { type: 'application/json' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = 'workiva-payload.json';
          document.body.appendChild(a);
          a.click();
          a.remove();
          URL.revokeObjectURL(url);
        });
      </script>
    </body>
    </html>
    """


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
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

    try:
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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Workiva request failed: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Transformation failed: {exc}")
