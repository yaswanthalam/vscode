# HealthLens

An end-to-end **educational research application** based on the supplied multi-disease prediction / Adaptive RAG presentation and architecture diagram.

**Not a medical device, diagnostic tool, or clinically validated risk estimator.** The included models use artificial data and labels. Their outputs and evaluation metrics have **no established clinical meaning**. CSV-trained models also remain unvalidated. Use fictional data for demonstrations. Do not make treatment decisions from this application.

## Start locally in VS Code (Windows)

The application and three demo models have already been created locally. **No certificate installation is required with private VS Code tunnel mode.** Open this folder as its own VS Code workspace, select `.venv\Scripts\python.exe`, and run:

```powershell
cd "C:\Users\v-yaalam\Downloads\vscode_Dell_17-1\Final year project"
.\.venv\Scripts\python.exe -m app.serve --private-tunnel
```

This first process listens on port 8000 for initial port-forward setup, but deliberately blocks application access until your exact external URL is configured.

1. In VS Code, open **View > Command Palette > Ports: Focus on Ports View**.
2. Select **Forward a Port**, enter **8000**, and sign in when prompted.
3. Keep **Port Visibility > Private**. Do not select Public. The local backend protocol is **HTTP**, while the forwarded browser address must start with **HTTPS**.
4. Copy the full **Forwarded Address**, such as `https://YOUR-TUNNEL-8000.REGION.devtunnels.ms` (the example is not a real working address).
5. Stop the initial process with Ctrl+C, then restart with your actual address:

```powershell
.\.venv\Scripts\python.exe -m app.serve --private-tunnel --tunnel-origin "https://YOUR-ACTUAL-FORWARDED-ADDRESS"
```

Open the **forwarded HTTPS address**, not `https://127.0.0.1:8000`. VS Code's private tunnel requires the same account used to start the port forward. Then choose **Create an account** in HealthLens; there is no default app password. Usernames are 3-50 letters/numbers/`_.-`; passwords must be 12-128 characters.

The browser-to-tunnel connection is HTTPS; only the backend connection on your computer's **loopback interface** uses HTTP. Secure cookies and origin checks stay enabled. The app accepts forwarding headers only from loopback and only for the configured tunnel host/protocol. If the tunnel rewrites a mutation's Origin to its local HTTP backend, it is accepted only for the actual backend port with the browser's `Sec-Fetch-Site: same-origin` and the application's custom request marker; cross-site requests remain rejected. This is development-only, not end-to-end TLS and not production hosting. Keep VS Code and the server terminal open; closing either can stop access. If the forwarded address changes, restart with the new exact address.

Tunnel traffic passes through Microsoft's service: use fictional data only, and use this approach only if your organization's policy permits Dev Tunnels. If your organization blocks tunnels, do not bypass that restriction. Use approved managed hosting instead. Reference: `https://code.visualstudio.com/docs/debugtest/port-forwarding`.

**Connection refused** means nothing is listening at the requested address/port; changing the URL scheme does not start the server. In private-tunnel mode the backend is intentionally not a direct local HTTPS endpoint.

On the sign-in form, enter the exact username and select **Check account** to see whether that account exists in this local database. The check sends no password, returns no profile information, uses the same origin protections, and is rate-limited. It is disabled in production to avoid public account enumeration. A failed lookup due to network/tunnel trouble is shown as **not confirmed**, never as "account missing."

Normal API requests time out after 20 seconds and re-enable their buttons rather than waiting indefinitely. NVIDIA chat retains a 100-second browser timeout for its bounded 90-second fallback budget. A browser **504 Gateway Timeout** is a tunnel/backend reachability problem, not an account-existence response; the GUI gives a clear gateway message when it can receive that error. If the entire page gets a tunnel error, the GUI cannot load: check the private port forward for 8000 in VS Code. If recreating it changes the forwarded URL, update `APP_ORIGIN` and restart with the new address.

For a fresh clone, use Python 3.12-3.14:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m app.train --demo
.\.venv\Scripts\python.exe -m app.serve --private-tunnel
```

Then follow the port-forward steps above. Alternatively, `.\setup.ps1` performs installation and first-time demo training when your existing PowerShell policy permits scripts. It does not install certificates, modify your policy or overwrite a partial model set. No Node.js, npm, database server or paid API is needed. `--private-tunnel` configures transport and origin for that process only; `.env` remains usable for optional direct TLS. The primary VS Code debug configuration also prompts for the private forwarded address; leave it blank only during first-time setup.

### Optional direct local TLS (only on devices where certificate trust is permitted)

Skip this section on devices that prohibit certificate installation. Private-tunnel mode above does not need it. The separate `python -m app.serve` command (without `--private-tunnel`) and optional direct-TLS debug configuration serve TLS only. All sessions use Secure cookies and `APP_ORIGIN` must use HTTPS. Direct TLS does not accept forwarded headers as a substitute for encryption.

`python -m app.tls` creates a 90-day localhost certificate and a project-specific development root in `.certs`. Names are limited to `localhost`, `127.0.0.1` and `::1`. The root signing key is never written to disk; only the server's private key is saved. These files are ignored by Git and excluded from Docker builds. They are for this computer's development use, not public hosting.

**Browser trust has not been installed automatically.** Windows blocked trust installation in the non-interactive agent session. To avoid a browser certificate warning, open `.certs\root-ca.cer` in Explorer and select **Install Certificate > Current User > Place all certificates in the following store > Trusted Root Certification Authorities > Finish**, then approve the HealthLens certificate prompt. Restart the browser if necessary. Only approve the certificate you generated for this project. Do not ignore certificate errors or disable TLS verification.

Alternatively, run this from your own interactive PowerShell terminal and approve the Windows prompt:

```powershell
Import-Certificate -FilePath ".certs\root-ca.cer" -CertStoreLocation "Cert:\CurrentUser\Root"
```

Never import or share `server-key.pem`. Do not commit `.certs`, even for sharing with classmates: each clone should generate its own local certificate.

To remove this project's trust entry (only after you have installed it):

```powershell
$certificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new(
    (Resolve-Path ".certs\root-ca.cer").Path
)
Remove-Item "Cert:\CurrentUser\Root\$($certificate.Thumbprint)"
```

Before certificate expiry, remove the old trust entry, run `.\.venv\Scripts\python.exe -m app.tls --renew`, then trust the new public certificate and restart the app. For a public hostname use a valid certificate for that hostname, setting `TLS_CERT_FILE` and `TLS_KEY_FILE` to administrator-managed files; do not use the development root.

## Included workflows

- Register, sign in/out, server-side expiring sessions and password-confirmed account deletion.
- Diabetes, heart disease and chronic kidney disease research modules with validated numeric inputs.
- Structured TXT/CSV/text-PDF import, explicit user review, and manual entry. No images, scans, OCR, DICOM or arbitrary clinical-report interpretation.
- Prediction history, owner-only access, record deletion, and downloadable PDFs containing confirmed inputs, model provenance and cited educational information.
- Offline adaptive retrieval with relevance gating, topic-aware reranking, broader retrieval for weak matches, and abstention when no relevant source is available.
- Optional NVIDIA or Azure OpenAI explanations with explicit **per-question consent** and offline fallback. This is a question/answer assistant, not a conversational medical record system.
- Training-only model selection with held-out evaluation, model manifests, feature schemas, integrity hashes and deployment startup checks.
- Responsive browser UI, automated API/model tests, optional real-browser checks, Docker configuration and GitHub CI template.

## Architecture

```text
CSV datasets / synthetic demo generation
    -> schema, units, range and duplicate checks
    -> stratified 80/20 split
    -> median imputation + scaling (logistic regression)
       or median imputation + random forest
    -> 4-fold training-only CV selection by F1
    -> held-out metrics + versioned artifact and manifest

Browser -> register/login -> manual inputs or report extraction
    -> review/confirm -> model inference -> private assessment history
    -> adaptive retrieval of curated public-health excerpts
    -> offline cited guidance / optional consented Azure OpenAI explanation
    -> downloadable PDF
```

The three classifiers use separate feature subsets rather than an unrestricted symptom-to-disease predictor. No feature selection is learned on the test partition. The small knowledge collection uses local TF-IDF retrieval, **not** embeddings, a live medical search engine, a vector database, or a clinically validated Adaptive RAG framework. Reports contain reviewed offline excerpts rather than unverified generated treatment advice. Retrieved guidance is topic-specific, not a prescribed personalized diet or exercise plan.

## Project layout

```text
app\
  main.py                 API, authorization and request safeguards
  security.py             Argon2 hashes, opaque sessions and throttling
  serve.py / tls.py        Private HTTPS tunnel / optional direct TLS startup
  db.py                   SQLite schema and connections
  catalog.py              Supported disease features, units and bounds
  ml.py                   Training, evaluation and trusted artifact loading
  train.py                Reproducible CLI
  reports.py              Structured extraction and PDF export
  extract_worker.py       Time-bounded subprocess for PDF parsing
  middleware.py           Bounded request bodies, including chunked uploads
  rag.py                  Adaptive local retrieval / optional Azure explanation
  knowledge.json          Paraphrased public-health excerpts and source links
  static\                 HTML, CSS and JavaScript frontend
tests\                    API, model and browser checks
samples\                  Fictional reports
models\                   Generated models; ignored by Git
data\                     Local database; ignored by Git
.env.example              Non-secret configuration template
setup.ps1                 Windows setup helper
Dockerfile / compose.yaml Optional single-instance container
.github\workflows\ci.yml   CI when published as a standalone repository
```

## Upload format and units

Imports are **drafts**. Confirm values, units, measurement dates and fasting/exercise context. The app does not infer context or convert units. For TXT or PDF, use canonical `key: number` lines **without unit suffixes**, e.g. `samples\diabetes-report.txt`. Other prose is ignored. For CSV, use canonical column headers and exactly one data row, as in `samples\heart-report.csv`. Missing fields must be entered manually. Unsupported or ambiguous values are rejected. Original files are not retained by the application; operating-system multipart temporary storage may be used.

| Module | Required fields (units) |
|---|---|
| Diabetes | `age` (years), `glucose` (fasting plasma mg/dL), `bmi` (kg/m2), `systolic_bp` (mmHg) |
| Heart | `age`, `systolic_bp`, `cholesterol` (total, mg/dL), `max_heart_rate` (measured exercise bpm), `exercise_angina` (0=no, 1=yes) |
| Kidney | `age`, `systolic_bp`, `creatinine` (serum mg/dL), `blood_urea` (mg/dL, **not BUN**), `hemoglobin` (g/dL) |

These are custom research schemas, not drop-in UCI/Kaggle schemas. For example, a dataset's diastolic `bp` must not be renamed to `systolic_bp`, random glucose must not be relabeled fasting glucose, and BUN must not be silently relabeled blood urea. A creatinine reading alone cannot establish CKD. Do not conduct exercise testing simply to obtain an input.

## Train with real CSV data

No real patient dataset is bundled or downloaded. Obtain appropriately licensed, de-identified data with permission; document its provenance, population, units, label definition and intended use before training.

Each training CSV must contain **exactly** its module's canonical feature columns plus `target` (`0`=label absent, `1`=label present). Minimum: 100 rows and 20 examples of each class. Feature missing values are permitted and imputed within each training fold; missing targets, entirely missing features, out-of-range values and duplicate feature rows are rejected. Do not include names, record IDs or free-text reports.

```powershell
.\.venv\Scripts\python.exe -m app.train --csv "C:\datasets\diabetes.csv" --disease diabetes
.\.venv\Scripts\python.exe -m app.train --csv "C:\datasets\heart.csv" --disease heart
.\.venv\Scripts\python.exe -m app.train --csv "C:\datasets\kidney.csv" --disease kidney
```

Restart the app after training. Each manifest records source (`synthetic` or `local_csv`), features, library version, seed, row counts, candidate CV F1 scores, held-out accuracy/precision/recall/F1/confusion matrix, version and artifact SHA-256. Confusion matrices use true rows / predicted columns in `[0, 1]` order. The classification threshold is 0.5; the displayed output is a **model score**, not a calibrated clinical probability.

The data split assumes independent rows. Repeated patients, sites or temporal data require a scientifically appropriate grouped/external split before this pipeline is suitable. The code does not perform calibration, clinical threshold selection, fairness assessment, uncertainty estimation or prospective validation. CV/held-out scores cannot substitute for these. Dataset quality and the validity of `target` remain the researcher's responsibility.

Models load only at startup. Training writes uniquely named artifacts and replaces each manifest atomically. Old artifacts are retained for manual rollback and must be pruned by an administrator. **Joblib can execute code:** load only administrator-owned artifacts created by your trusted training process. Hash checks detect accidental corruption; they do not establish trust when an attacker can change both artifact and manifest.

## NVIDIA AI connection (existing setup unchanged)

Add your NVIDIA-hosted API key in the **local, Git-ignored** file:

```text
C:\Users\v-yaalam\Downloads\vscode_Dell_17-1\Final year project\.env
```

Only edit these lines; do not replace the file or change its tunnel, data or model settings:

```dotenv
NVIDIA_API_KEY=YOUR-KEY-HERE
NVIDIA_MODEL=nvidia/nemotron-3-ultra-550b-a55b
NVIDIA_MODELS=nvidia/nemotron-3-ultra-550b-a55b,nvidia/nemotron-3.5-lightning-30b-a3b,nvidia/nemotron-3.5-super-vl-120b-a12b
```

The model ID can be changed to a chat model available to your NVIDIA account. The integration uses NVIDIA's hosted `https://integrate.api.nvidia.com/v1/chat/completions` endpoint with Bearer authentication, not an OpenAI account or SDK. Check the selected model's current availability and account permissions on NVIDIA's API catalog. Reference: `https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b`.

Restart the backend using the same existing command (`.\.venv\Scripts\python.exe -m app.serve --private-tunnel`) and refresh the browser. Open **Knowledge assistant**, enter your question, and tick the per-question **NVIDIA** consent checkbox before submitting. No layout, tunnel, login, prediction model, uploaded-report or database behavior is changed. Disease assessments and their offline source excerpts are not replaced by LLM-generated diagnoses or treatment advice.

Without the checkbox, guidance stays offline. With consent, only the question and retrieved public source excerpts are sent to NVIDIA; stored assessments and uploaded reports are not sent. Use fictional data without identifiers, and review NVIDIA's terms and privacy practices. Provider processing is separate from this app's storage.

When `NVIDIA_API_KEY` is set, NVIDIA takes priority. If it is blank, existing Azure configuration still works; otherwise the app remains offline. The three listed models were checked against NVIDIA's catalog and successfully answered tiny synthetic verification prompts on October 30, 2026; future availability and permissions can change.

### Automatic multi-model fallback

`NVIDIA_MODELS` is a comma-separated priority list that overrides `NVIDIA_MODEL` when nonempty. Duplicate entries are removed; at most five models are tried. Without a list, the legacy `NVIDIA_MODEL` remains primary with Lightning and Super as backups.

The assistant tries the next model for model-specific rate/token limits, context overflow, truncated output, unavailable models, transient server failures, timeouts or invalid/empty responses. Model-specific 429 responses put that model on cooldown using `Retry-After` (60 seconds if absent). The next question skips models still cooling down. Cooldowns are scoped to the API key and live in this single server process; restarting clears them.

Explicit account/organization quota errors stop the request and cool down the whole key. **Model switching cannot replenish shared account credits or bypass account-wide limits.** NVIDIA does not always identify quota scope; an unscoped 429 permits bounded model fallback, not a promise that another model has separate allowance. All attempts share a 90-second request budget with a 30-second cap per model.

Authorization failures, invalid requests and provider safety refusals do not cause model rotation. If no eligible model succeeds, reviewed offline guidance remains available. The chat displays the model used and whether a backup was selected; responses include attempted model IDs but never the key or raw provider error. No prompts, patient values or provider payloads are logged by the fallback router.

All selected models receive the same reviewed sources and healthcare limitations. The three built-in Nemotron models request non-reasoning output; custom models use a standard chat payload. Fallback still requires the existing per-question consent checkbox and sends no saved assessments or uploaded documents.

Keep the key only in `.env` or approved secret storage. Never paste it into chat, screenshots, frontend code, GitHub or logs. No new package installation is required.

## Optional Azure OpenAI (preserved)

Offline mode works without credentials. If you already have an Azure OpenAI resource and deployed compatible chat model, set:

```dotenv
AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE.openai.azure.com
AZURE_OPENAI_API_KEY=YOUR-SECRET
AZURE_OPENAI_DEPLOYMENT=YOUR-DEPLOYMENT-NAME
```

Restart and explicitly opt in for each question. Only that question and retrieved public excerpts are sent, **not** stored assessments or uploaded documents. Questions themselves may contain health data: use fictional data and no identifiers. Chat messages are not saved by this app; provider processing/retention is separate. API errors fall back to offline excerpts. An LLM can hallucinate despite grounding instructions; source links are not evidence that every generated statement is correct. Emergency-keyword handling is a limited safeguard, not triage.

The integration calls Azure's `/openai/v1/chat/completions` endpoint; the model parameter is your deployment name. Keep keys out of Git and browsers. For real deployments, replace test API-key authentication with managed identity/approved secret management and review provider privacy controls. No Azure resource or agent has been provisioned.

## Tests and development

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m ruff format --check app tests
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pip_audit --path .venv\Lib\site-packages
```

Run the browser smoke check separately; it starts and stops its own isolated server and uses temporary fictional records:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m tests.browser_smoke
.\.venv\Scripts\python.exe -m tests.browser_auth_smoke
```

On this Windows machine, the check can use installed Edge without downloading Chromium. **The development root must already be trusted by the browser**; the test does not disable certificate checks or install trust. The browser test covers registration, all disease forms, report extraction, prediction, history, PDF download, chat, mobile overflow and deletion. API documentation is available at `/docs`; mutations require `X-Requested-With: HealthLens` and a matching Origin when supplied. API clients must keep the Secure session cookie over HTTPS. No CORS access is enabled. The automated test suite also verifies a real TLS handshake using the exact test CA, Secure-cookie authentication, rejection of a wrong CA and refusal of plaintext traffic.

## GitHub sharing (nothing has been pushed)

This folder currently lives **inside another Git repository**. To share it as a separate project, copy the source to a new folder **outside** that parent repository first. Do not copy `.venv`, `.env`, `.certs`, `data`, `models`, caches, original patient files or datasets. A fresh clone regenerates demo models and localhost certificates with setup; do not commit model binaries or private keys.

From the standalone source folder, after reviewing `.gitignore` and every staged file:

```powershell
git init -b main
git add .
git diff --cached --stat
git diff --cached
git commit -m "Initial HealthLens research application"
gh auth login
gh repo create healthlens --public --source . --remote origin --push
```

Use `--private` instead of `--public` if appropriate. Choose a distribution license you have authority to grant before public publication; none is silently assumed here. The CI template activates only when `.github` is at the repository root.

## Optional Docker / later Azure Web App

Train models locally and generate/trust the development certificate before building; the image copies `models` but never your `.env`, certificates or database. Compose mounts `.certs` read-only at runtime, serves HTTPS and verifies its health probe against that exact root. Models must use the same pinned scikit-learn version as the image.

```powershell
docker compose up --build
```

The included Compose setup is a **local HTTPS demo**, binds only to localhost, and uses a persistent named database volume. Open `https://127.0.0.1:8000`. Docker itself must be installed. The image uses a non-root user and TLS port 8000. On Linux, arrange read access to the mounted server key for that container user without making the key world-readable. This environment has not provisioned Azure or built the image.

Before deploying an actual service:

1. Replace all synthetic artifacts with reviewed CSV-trained models; perform independent clinical validation before patient-facing use. `APP_ENV=production` refuses demo models and requires all three modules.
2. Set `APP_ENV=production`, `ALLOW_DEMO_MODELS=false`, and `APP_ORIGIN=https://YOUR-HOST`. Supply valid hostname-matching TLS certificates using `TLS_CERT_FILE` and `TLS_KEY_FILE`. Cookies are always Secure; production also enables HSTS.
3. This container now expects HTTPS on port 8000. Before choosing Azure Web App, verify the platform's backend protocol and probe requirements: a TLS-terminating edge with plaintext upstream traffic is not an end-to-end TLS configuration and will be rejected by this app. Choose a TLS-capable upstream architecture or explicitly design/review a trusted TLS-termination configuration when deployment is requested. Use persistent storage mounted at `DATA_DIR`; image-local files are not a durable database.
4. This SQLite design targets **one application instance**, a small local persistent filesystem and modest traffic. Do not put its WAL database on an unverified network share or scale out. For Azure multi-instance use, implement a managed database migration and shared session/rate-limit storage first.
5. Apply storage/backup encryption, private access, documented retention, verified restore procedures, audit events without patient values, secret rotation, account recovery/verification and abuse protections. Database backups must include a consistent WAL checkpoint or SQLite backup API snapshot; a live file copy is insufficient.
6. Put upload/body/time/concurrency limits and distributed throttling at the trusted edge. Current throttling keys off the direct connection's IP and intentionally ignores forwarding headers: reverse proxies may make all clients share one quota. Configure trusted-proxy-aware identity at deployment, not by accepting arbitrary forwarded IPs.
7. PDF extraction runs in a separate process with an eight-second timeout; Unix workers also have CPU/address-space limits. Windows has no equivalent memory limit in this implementation. Apply container/OS limits and a dedicated parsing service before public untrusted uploads. A subprocess is not a complete security sandbox.
8. Complete security, privacy, accessibility, load and regulatory reviews. Do not advertise this code as HIPAA compliant, certified, clinically validated, or ready to process real patients merely because it runs in Azure.

This delivery is a complete **locally runnable research project with deployment foundations**, not a certified production healthcare product. No GitHub push, cloud deployment, clinical validation, real-dataset performance measurement or compliance attestation is claimed.

## Public reference material

The knowledge file contains short original paraphrases, not copied articles. Review and update it regularly:

- NIDDK: `https://www.niddk.nih.gov/health-information/diabetes/overview/healthy-living-with-diabetes`
- CDC: `https://www.cdc.gov/diabetes/healthy-eating/diabetes-and-kidney-disease-food.html`
- CDC: `https://www.cdc.gov/kidney-disease/risk-factors/link-between-diabetes-and-heart-disease.html`
- NIDDK: `https://www.niddk.nih.gov/health-information/kidney-disease/chronic-kidney-disease-ckd/prevention/`
- FastAPI containers: `https://fastapi.tiangolo.com/deployment/docker/`
- Azure endpoint reference: `https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/switching-endpoints`
