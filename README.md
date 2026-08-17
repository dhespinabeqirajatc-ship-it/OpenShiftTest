# Excel to Workiva JSON Demo

This is a beginner-friendly OpenShift demo app.

Flow:

Client uploads Excel -> FastAPI endpoint -> pandas transformation -> JSON output -> optional Workiva API POST

## Expected Excel columns

- entity
- account
- amount
- period

## Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8080
```

Open http://localhost:8080

## Build container locally

```bash
docker build -t excel-to-workiva-demo .
docker run -p 8080:8080 excel-to-workiva-demo
```

## Deploy to OpenShift from GitHub source

In the OpenShift Developer Sandbox console:

1. Create a new project.
2. Select Add -> Import from Git.
3. Paste your GitHub repository URL.
4. Select Dockerfile build strategy if detected.
5. Create the app.
6. Open the generated route.

## Deploy with oc CLI

```bash
oc new-project excel-to-workiva-demo
oc new-app https://github.com/YOUR-USER/YOUR-REPO.git --name=excel-to-workiva-demo
oc expose svc/excel-to-workiva-demo
oc get route
```

## Workiva integration note

The /send-to-workiva endpoint is intentionally generic. Set these environment variables in OpenShift when you are ready to test with a real Workiva endpoint:

- WORKIVA_API_URL
- WORKIVA_BEARER_TOKEN

Never commit real tokens to GitHub.
