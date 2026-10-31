# NetOps Read-Only Agent

A web GUI and AI agent that answers network questions **from Kusto first** and
only falls back to **read-only `show` commands on the device** when Kusto can't answer.

- **Ask the agent** – e.g. "When was the OS on rtr-01 downgraded and who did it?"
- **Run a show command** – type a command; it is checked by safety rules, then by AI, then run.
- **Audit log** – every question, check and command, with the user and the time.

## How a command is protected (4 layers)

| Layer | Where | What it does | Can the AI bypass it? |
|---|---|---|---|
| 0. Device role | TACACS/RADIUS | Service account is read-only (`network-operator`, priv 1, `read-only` class) | No |
| 1. Safety rules | `app/guardrails.py` + `config/allowed_commands.yaml` | Must start with `show`, match the approved list, safe pipes only, no `; & $ \``, blocked words | No – checked again right before SSH |
| 2. AI review | `app/ai.py` | Checks platform syntax and fit, explains the command, flags heavy commands. Can only **block or warn**, never approve something layer 1 blocked. If the AI service is down, the command is blocked. | n/a |
| 3. Output | `guardrails.redact_output` | Masks secrets/keys/communities in output | No |

> Do not rely on AI alone to validate commands. AI can be fooled by prompt
> injection or make mistakes. Layers 0 and 1 are the real controls; the AI
> is a helpful second opinion and explainer.

## How the agent investigates

1. Picks an approved **Kusto template** (`config/kusto_templates.yaml`). It never writes free-form KQL,
   and parameters are passed as Kusto query parameters, so they cannot be used to inject KQL.
2. If Kusto has no rows, is stale or lacks a field, it runs **show commands** on the device.
   The code refuses device access until Kusto has been tried.
3. Answers with timestamps and a **Sources** list. Every step is shown in the GUI.

"Who downgraded the OS" works best from **TACACS command accounting in Kusto**
(`who_ran_commands`). Device log buffers wrap and are cleared on reload.

## Run it in demo mode (no devices, Kusto or OpenAI needed)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # NETOPS_MOCK=true by default
set -a && source .env && set +a                         # or set the variables another way
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Open http://127.0.0.1:8000. Run the tests with `python -m unittest -v`.

## Go live

1. **Kusto:** edit table and column names in `config/kusto_templates.yaml` to match your cluster
   (`Syslog`, `TacacsAccounting`, `DeviceInventory` are placeholders). Give the service identity
   **Viewer** on the database only.
2. **Devices:** list them in `config/inventory.yaml` (Netmiko `device_type` per platform).
3. **Credentials:** create a **read-only** TACACS account, store it in **Key Vault**, and set
   `KEYVAULT_URL`. The app reads it with its managed identity / `az login` (DefaultAzureCredential).
4. **Azure OpenAI:** set `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT` (use Entra ID auth
   instead of a key where possible). The AI only receives the question, the commands and the output,
   never the device credentials.
5. Set `NETOPS_MOCK=false`. Pilot on **lab devices** first.

### Hosting and sign-in
Run it on a **jump host / management VM** that can SSH to the devices. Put it behind
**Entra ID sign-in**: App Service / Container Apps "Easy Auth" (sets `X-MS-CLIENT-PRINCIPAL-NAME`),
or a reverse proxy that sets `X-Forwarded-User`. Bind uvicorn to `127.0.0.1` so the identity
headers can't be spoofed by calling the app directly. Use `ALLOWED_USERS` to restrict who can use it.

Ship `audit.jsonl` to Kusto so the agent's own actions can be queried.

Get a security review and follow your org's device-access policy before connecting to production.

## Extending
- **New show command:** add a regex to `config/allowed_commands.yaml` (through code review) and a test.
- **New Kusto question:** add a template to `config/kusto_templates.yaml`; the agent sees it automatically.
- **Structured output:** swap `_ssh` in `app/device_tool.py` for eAPI / NX-API / NETCONF / gNMI.

## Files
```
app/main.py          FastAPI routes + sign-in header handling
app/api.py           request handlers (validate, run, ask, audit)
app/agent.py         Kusto-first investigation agent (Azure OpenAI tool calling)
app/ai.py            AI command review (fails closed)
app/guardrails.py    hard command rules + output redaction
app/kusto_tool.py    approved, parameterised Kusto templates
app/device_tool.py   read-only SSH (Netmiko), concurrency limits, Key Vault creds
app/audit.py         JSONL audit trail
app/mock_data.py     demo scenario
static/              GUI (HTML/CSS/JS, no build step)
config/              allowlist, Kusto templates, inventory
tests/               guardrail, Kusto, device, API and agent tests
```
