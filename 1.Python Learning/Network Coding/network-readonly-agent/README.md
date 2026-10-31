# Network Evidence Agent

A complete local starter project: browser GUI, Python backend, deterministic investigation orchestration, Kusto adapter, restricted SSH adapter, optional Microsoft Foundry AI interpretation, JSON reports, and audit events. No OpenAI account key is required. Demo mode works with the Python standard library and makes no network calls to Kusto, SSH, or AI.

This is a local proof of concept, not an enterprise hosted service. No live infrastructure has been configured for you.

## Run the demo

Install Python 3.11 or newer. In the extracted project directory:

```powershell
python app.py
```

Open http://127.0.0.1:8080, paste the local session token printed in your terminal, and click Connect. Choose a device and check, then Investigate. Start and End fields use UTC. Default config is `config.example.json`.

- OS version / LACP: synthetic recent Kusto evidence; no fallback needed.
- IS-IS: deliberately empty Kusto result; fallback is disabled by default.
- History: a synthetic version-change event with no actor. The application explicitly reports missing attribution.

To exercise automatic fallback without accessing any real device, copy the configuration to `config.local.json`, keep `mode` as `demo`, set `allow_device_fallback` to `true`, and run:

```powershell
python app.py --config config.local.json
```

AI stays disabled until you configure it. In that state the app is a deterministic evidence agent, not an LLM chatbot. The question provides interpretation context; select the investigation explicitly. Natural-language command generation is intentionally excluded.

## How it works

1. GUI submits a registered device, approved investigation, time window, and optional question.
2. Backend runs a fixed, parameterized Kusto query first.
3. Deterministic checks evaluate evidence freshness, event type, and missing actor fields.
4. If evidence is insufficient and fallback is enabled, the backend runs one exact approved command over SSH. Kusto outages block fallback unless separately enabled.
5. Optional Foundry interpretation receives evidence and limitations, with no tools or credentials in its prompt.
6. GUI displays original evidence, source IDs, findings, limitations, and a downloadable JSON report.

Device observations do not become Kusto facts. If organizational policy requires Kusto as the ONLY source of truth, keep fallback disabled, or ingest device observations into a separate Kusto table and validate that pipeline before querying them. This project displays device observations as a distinct supplemental source; it does not ingest them.

## Live Kusto / devices

Install optional live dependencies in a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item config.example.json config.local.json
```

Edit `config.local.json` locally:

- Set `mode` to `live`.
- Set the ADX cluster URL, database, and normalized table name.
- Register the real device IDs, hostnames, SSH ports, and environment-variable names.
- Set `allow_device_fallback` to `true` only if direct device reads are permitted.
- Leave `fallback_on_kusto_error` false unless an outage should also trigger device reads.
- Choose the acceptable snapshot age with `freshness_seconds` (default 900).

Kusto uses `DefaultAzureCredential`. For local development sign in with Azure CLI; in Azure use a managed identity. Grant only the required database viewer permissions and verify access to sensitive tables. The Python client uses a read query, not management commands. This is ADX, not the Azure Monitor/Log Analytics query API; adapt `query_kusto` if your workspace uses the latter.

An administrator can provision the example normalized schema from `kusto/schema.kql`. Connect your actual syslog, telemetry snapshots, AAA/TACACS accounting, and change records through an ingestion pipeline. The project cannot infer your existing schema: map your tables into the supplied columns or adapt the query. No production logs are fabricated.

### SSH requirements

Provision a dedicated read-only service account. Enforce command authorization on the device/AAA server, permitting only the reviewed commands and denying configuration, privilege escalation, shell access, and file operations. The Python allowlist supplements these permissions; it cannot grant or guarantee device-side restrictions.

Populate a local `known_hosts` file with independently verified host keys. Unknown and changed host keys are rejected; do not blindly trust an unverified key scan. Nonstandard ports use OpenSSH `[hostname]:port` entries. Set device username and either password or private-key path in the environment names defined in config. Keep secrets out of configuration files and source control. Use your secret store for deployment. This app does not load `.env` automatically.

This starter uses a noninteractive SSH exec channel with no PTY and no automatic paging/configuration commands. Some network OS versions support only interactive CLI sessions; these will require a vendor-tested adapter. `show lacp summary`, `show isis neighbors`, and `show logging` are examples and are not portable across vendors. Confirm command syntax and privilege behavior for your OS. If you add commands, review and update BOTH `APPROVED` in `app.py` and the inventory mapping. No arbitrary command text is accepted from the GUI or AI. Timeouts and a 64 KiB output limit bound each device read; truncated output is marked. Some platforms report CLI errors in normal stdout; inspect source output and implement vendor parsers before automated health decisions.

The agent logs the command check ID, execution attempt, fallback outcome, run ID, and completion. The local JSONL audit file omits raw evidence and secrets. It is not tamper-proof; ship audit events to protected centralized storage for production. If audit storage is unavailable, investigation fails rather than silently bypassing audit.

## Add Microsoft Foundry later

Use a deployment that supports the Responses API. This is a direct model endpoint adapter, not Foundry Agent Service provisioning. No cloud resources are created.

In config, set `ai.provider` to `foundry`, `ai.endpoint` to the FULL model response URL, for example `https://YOUR-RESOURCE.services.ai.azure.com/openai/v1/responses`, and `ai.deployment` to your actual deployment name. Do not use the Foundry project endpoint (`/api/projects/...`). Your deployment/model must support the request fields used here.

Authentication options:

- No key: `DefaultAzureCredential` obtains an Entra token for `https://ai.azure.com/.default`. Assign the identity an appropriate model-inference role on the resource.
- Key later: supply your resource key through the server environment variable `FOUNDRY_API_KEY`. It is sent only to the administrator-configured endpoint as an `api-key` header. Never paste it in chat or the GUI.

There is no dependency on `OPENAI_API_KEY` or the OpenAI SDK. If AI fails, original evidence remains available. Enabling AI sends the question and selected raw evidence to that endpoint. Review internal data-handling requirements and implement organization-specific field redaction before enabling it with sensitive logs. The administrator owns endpoint trust; do not set an untrusted URL. For another provider, replace only `ai_interpret`, keeping all execution decisions outside the model.

## What can establish who downgraded an OS?

`show version` establishes current reported state, not historical authorship. Retain prior and current image/version records, install/boot/rollback events, NTP-synchronized timestamps, AAA command accounting, automation job identity and initiating-user records, and change ticket references. A login near the time of a change is not proof. Shared accounts and automation identities may identify an account without identifying a person. Missing retention cannot be recovered by AI. Vendor-specific version ordering is needed before calling a change a downgrade.

The starter's sufficiency checks validate the normalized evidence contract, not the authenticity of your ingestion pipeline or completeness of all history. History reports up to 100 records and marks a result-limit warning. Current device output is not used to answer a historical snapshot request; history fallback is an unfiltered local log read, clearly marked as a current supplemental observation.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests run offline with captured audit events and in-memory HTTP handlers. They verify source order, freshness, blocked commands, missing attribution, Kusto outages, AI failure behavior, historical fallback restrictions, and HTTP authorization.

## Hosting beyond a local proof of concept

The service binds to loopback and requires a local session bearer token. It is a single-user tool; the token does not identify an individual operator. Before shared hosting, replace the development HTTP server, add HTTPS and Entra SSO, authorize each user for specific devices and checks, add identity-bound audit, connection/rate limits, and network egress restrictions. Protect exported reports as operational data. Enforce read-only privileges independently in Kusto and AAA. No browser automation of device management pages is needed: the GUI controls a backend SSH connector.

## Sources

- Microsoft Foundry Responses and authentication: https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/responses
- Kusto query parameters: https://learn.microsoft.com/en-us/kusto/query/query-parameters-statement
- ADX Python client: https://learn.microsoft.com/en-us/azure/data-explorer/python-query-data
- Paramiko SSH client / host-key policy: https://docs.paramiko.org/en/stable/api/client.html
