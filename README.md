# Excel to Workiva JSON Demo

A beginner-friendly FastAPI app for converting an Excel trial balance into JSON and optionally sending the payload to a Workiva API endpoint.

## Flow

Excel upload → FastAPI → pandas transformation → JSON preview → optional Workiva API POST

## Expected Excel columns

- `entity`
- `account`
- `amount`
- `period`

## Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8080
```

Open `http://localhost:8080`.

## Build container locally

```bash
docker build -t excel-to-workiva-demo .
docker run -p 8080:8080 excel-to-workiva-demo
```

## Deploy to OpenShift from GitHub

In the OpenShift Developer Sandbox console:

1. Create a new project.
2. Select **Add → Import from Git**.
3. Paste your GitHub repository URL.
4. Select the Dockerfile build strategy if detected.
5. Create the app.
6. Open the generated route.

## Updating the application in GitHub

After replacing/editing files on your computer, open a terminal inside the repository folder.

### 1. Check what changed

```bash
git status
```

### 2. Stage the changes

```bash
git add .
```

### 3. Commit the changes

```bash
git commit -m "Improve application interface"
```

### 4. Push to GitHub

```bash
git push
```

For later changes, the usual workflow is:

```bash
git pull
git status
git add .
git commit -m "Describe your change"
git push
```

If this is the first push for a new branch, Git may ask you to set the upstream branch. For example:

```bash
git push -u origin main
```

Use your actual branch name if it is not `main`.

## OpenShift after a GitHub push

Whether the app redeploys automatically depends on how the OpenShift build was configured. If a webhook/build trigger is configured, a GitHub push can start a new build automatically. Otherwise, start a new build from the OpenShift console or CLI.

Example CLI command:

```bash
oc start-build excel-to-workiva-demo --follow
```

## Deploy with `oc` CLI

```bash
oc new-project excel-to-workiva-demo
oc new-app https://github.com/YOUR-USER/YOUR-REPO.git --name=excel-to-workiva-demo
oc expose svc/excel-to-workiva-demo
oc get route
```

## Workiva integration

The `/send-to-workiva` endpoint is intentionally generic. Set these environment variables in OpenShift when you are ready to test a real Workiva endpoint:

- `WORKIVA_API_URL`
- `WORKIVA_BEARER_TOKEN`

Never commit real API tokens to GitHub.
