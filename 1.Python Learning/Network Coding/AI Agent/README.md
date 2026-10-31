# Network Lens: read-only lab agent with AI provider fallback

A standalone Windows-friendly Python app with a browser GUI, natural-language
Gemini/OpenRouter planner, constrained SSH show-command tools, persistent evidence, syslog
collection, local log imports, and downloadable JSON investigations.

The inventory matches your diagram:

| Router | Management IP | Management interface |
|---|---|---|
| R1 | 192.168.32.168 | Ethernet1/1 |
| R2 | 192.168.32.167 | Ethernet1/2 |
| R3 | 192.168.32.166 | Ethernet1/0 |

R1/R2 use 10.12.12.0/30; R2/R3 use 10.23.23.0/30. Update `inventory.json` if DHCP
addresses change; reservations are preferable. No devices have been modified.
This project is independent of the neighboring Kusto/Foundry projects.

## 1. Try the GUI now: no API key or dependencies needed

Use Python 3.11 or newer:

```powershell
Set-Location 'C:\Users\v-yaalam\Downloads\vscode_Dell_17-1\1.Python Learning\Network Coding\AI Agent'
python app.py
```

Open `http://127.0.0.1:8501`, paste the **local session token** printed in the
terminal, and click Connect. Select routers and ask a question. Keep the terminal
open; Ctrl+C stops the app. A new token is generated on each start.

**Demo mode is synthetic, keyword-based, and offline.** It does not connect to
devices or AI providers and is not an AI diagnosis. It is intentionally the default.

### Local HTTPS

After installing the requirements below, start the HTTPS GUI with:

```powershell
.\.venv\Scripts\python.exe app.py --https
```

Open `https://127.0.0.1:8501` and use the token printed by that running process.
HTTP and HTTPS are different startup modes; changing only the address in the
browser does not enable TLS. `ERR_CONNECTION_REFUSED` means nothing is listening
at that address/port: keep the app process running, and inspect startup errors.

The app generates a self-signed development certificate valid for 30 days in
ignored `data\tls\localhost.crt`, with its private key in `localhost.key`. It
reuses that pair on restart and never changes Windows/browser trust settings.
Protect the private key using Windows file permissions. Browsers will normally
show an untrusted-certificate warning. Verify the SHA256 fingerprint printed by
the app before allowing a **site-specific local development exception**, if
your browser permits one. Never disable browser certificate verification globally.
If your managed browser forbids exceptions, use an administrator-approved trusted
local certificate or the original loopback HTTP mode; do not bypass that policy.

For certificate expiry, stop the app, remove only that generated certificate/key
pair, then restart with `--https` to generate a new pair and fingerprint. Existing
browser exceptions may need updating. No OS trust is installed automatically.
Live mode also accepts HTTPS: `python app.py --mode live --https`.

## 2. Install live dependencies and add AI keys locally

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Set these locally in `.env`, not in Python source or in chat:

```dotenv
GEMINI_API_KEY=YOUR_GOOGLE_KEY
GEMINI_MODEL=gemini-flash-latest
ALLOW_GOOGLE_DEVICE_DATA=true
AI_PROVIDER_ORDER=gemini,openrouter
OPENROUTER_API_KEY=YOUR_OPENROUTER_KEY
OPENROUTER_MODEL=openrouter/free
ALLOW_OPENROUTER_DEVICE_DATA=true
NETWORK_USERNAME=YOUR_READ_ONLY_USERNAME
NETWORK_PASSWORD=YOUR_READ_ONLY_PASSWORD
```

The model is configurable: the `gemini-flash-latest` alias can change, and model
availability/quota depends on your Google account. Use an available structured-output
capable model. The implementation uses Google's `google-genai` SDK, not the old
`google-generativeai` package.

Either provider can work alone. Leave a key blank to skip that provider. When
both are configured and consented, the default is **Gemini first, OpenRouter
second**. To prefer OpenRouter, set `AI_PROVIDER_ORDER=openrouter,gemini`; to use
only OpenRouter, set `AI_PROVIDER_ORDER=openrouter`. Unknown or duplicate names
are rejected. Saving `.env` does not update an already running process: restart
the app with `--mode live --https` and reconnect using its new session token.
Do not overwrite an existing `.env` with the blank example.

OpenRouter uses its Chat Completions API directly through Python's standard
library; no OpenAI account or SDK is needed. The default `openrouter/free` router
selects free models, with availability and rate limits determined by OpenRouter.
You can set `OPENROUTER_MODEL` to an available structured-output-capable model
you choose; selecting a paid model can incur charges. The application does not
silently switch from free to paid models. Requests require supported parameters,
use strict JSON Schema for planning, and set `provider.data_collection=deny`.
These restrictions can leave no eligible endpoint; the app reports that failure
rather than weakening them. This preference does not prove end-to-end zero
retention; review OpenRouter and downstream-provider policies.

For each planning or interpretation stage, the app tries each eligible provider
at most once. Network errors, timeouts, HTTP 401/402/404/408/429 and HTTP 5xx can
trigger fallback. A provider with a missing key or disabled sharing is skipped
without receiving data. The provider that succeeded at planning is tried first
for interpretation, avoiding another wait for a known failing primary. Falling
back for interpretation never re-runs SSH commands.

Refusals, empty/truncated completions, malformed plans, policy-invalid commands,
and HTTP 400/403 stop that stage: the app does not switch models to bypass a
refusal, remove schema enforcement, or relax command controls. The GUI and JSON
report show provider/model attempts for both stages and preserve failure
warnings. If all providers fail during planning, no device commands run. If
interpretation fails, already collected evidence is retained and displayed.

Environment variables take precedence over `.env`. For separate accounts set
`R1_USERNAME`, `R1_PASSWORD`, etc. You can use `NETWORK_KEY_FILE` and
`NETWORK_KEY_PASSPHRASE` instead of a password. Private keys remain local.

**Data sharing:** live AI investigations send the question, selected device IDs,
the command catalog, and bounded, best-effort-redacted command/log evidence to
the eligible providers in your configured order. Gemini sends data to Google;
OpenRouter sends data to OpenRouter and its downstream model provider. A failed
provider may already have received the request before fallback sends the same
data to another provider. Never enable this for data you are not permitted to share. Redaction
is not a data-loss-prevention guarantee: addresses, hostnames, usernames and other
operational details may remain. Manual command collection makes no AI calls
and does not require AI keys or data-sharing opt-in. Keys stay in the local
backend and are not included in prompts, reports or browser status responses.

## 3. Device-side read-only access is required

Your supplied `admin privilege 15` account is **not read-only**. Do not use it as
the long-term service account. Have a network administrator configure a dedicated
read-only CLI view or AAA command-authorized account appropriate for your IOS
image. Permit only the reviewed show commands in `policy.py`, and independently
deny configuration, write/copy/delete/reload, shell access, privilege escalation
and other commands. Validate authorization on each image.

The app's controls supplement device-side permissions; they cannot turn a
privilege-15 account into a genuinely read-only account. The application never
sends `enable`, `configure terminal`, terminal-setting commands, or writes to
the device. IOS paging is handled with spaces on the SSH channel. Authentication,
opening a session and read commands may still create ordinary device audit logs.

No automatic provisioning, password changes, routing changes or syslog
configuration is performed. Your current base configuration does not configure
BGP, IS-IS, LACP or historical AAA accounting; missing features must not be
interpreted as healthy sessions.

## 4. Enroll verified SSH host keys

From the app folder, inspect the key without authenticating:

```powershell
.\.venv\Scripts\python.exe trust_host.py R1
```

This prints a SHA256 fingerprint but **does not trust or save it**. Independently
verify that fingerprint through a trusted device console/administrator. Only
then run the following, substituting the verified fingerprint:

```powershell
.\.venv\Scripts\python.exe trust_host.py R1 --fingerprint 'SHA256:REPLACE_WITH_VERIFIED_VALUE'
```

Repeat for R2 and R3. Keys are saved in the local ignored `known_hosts` file.
Unknown and changed keys are rejected during troubleshooting. Never blindly
trust a fingerprint obtained only over the same untrusted network. A changed
DHCP address may now belong to a different device: verify identity, not just IP.

Old 7200 IOS images may have SSH algorithms unsupported by your client.
The app deliberately does not enable insecure legacy algorithms automatically.
Use a supported lab image/SSH configuration or an administrator-reviewed adapter.
Connection refusal, authentication failure, unknown host keys, denied commands
and unsupported syntax are shown as errors/evidence, not successful checks.

## 5. Start live troubleshooting

```powershell
.\.venv\Scripts\python.exe app.py --mode live
```

The machine running Python must be able to reach the management IPs on TCP 22.
Check the network locally, for example:

```powershell
Test-NetConnection 192.168.32.168 -Port 22
```

In the GUI select the device scope, then ask:

- "What IOS versions are R1, R2 and R3 running?"
- "Are R1 interfaces up? Check errors and CPU."
- "Check BGP, IS-IS neighbors and LACP on R2."
- "Check power, memory and temperature."
- "When was IOS downgraded and who did it? Review retained logs."

The planner chooses at most 12 **exact approved commands**. It does not generate
executable command strings, select arbitrary hosts, or elevate privileges.
Every selected device must appear in the plan; incomplete coverage is rejected
before SSH. Deselect devices you do not want queried.
All selected steps are validated before the first SSH call and commands are
revalidated at execution. Each check opens a bounded SSH connection; no pooled
privileged session persists. A single investigation runs at a time.

The current catalog covers version, interface summary/details, BGP, routing,
IS-IS, OSPF, LACP, EtherChannel, CPU, memory, environment, inventory, logging,
clock, boot variables, config history and current users. Not every command is
supported by a 7200 IOS image. Hardware power/fan sensors may not exist in an
emulator. Unsupported commands are displayed, never silently mapped to a healthy
state. Inspect the raw evidence, not just the AI wording.

Use **Run an exact approved show command** for direct collection without AI.
To extend support, edit the reviewed `COMMANDS` catalog in `policy.py` and add a
test. Arbitrary user-entered show text, pipes, redirects and command chaining
are intentionally not accepted, even when requested through a prompt.

The planner sees your question, not device output. The interpretation model sees
untrusted output but has no executable tools. Planning/API failure stops before
SSH; interpretation failure preserves and displays collected evidence. Model
answers can still be wrong: evidence IDs are requested but natural-language
claims/citations are not formally verified.

## 6. Historical logs and downgrade attribution

`show version` gives the **current** image/version; it cannot tell you who
downgraded the OS. This app starts retaining observations only after you run it.
It cannot recover logs already lost on reload or buffer rollover.

Use the GUI's historical evidence panel to paste existing syslog/AAA records.
Imports are stored as unverified, with an import timestamp distinct from any
event timestamps inside the text.

For ongoing collection, you can optionally start a UDP syslog receiver:

```powershell
.\.venv\Scripts\python.exe app.py --mode live --syslog --syslog-bind YOUR_PC_MANAGEMENT_IPV4 --syslog-port 5514
```

Replace `YOUR_PC_MANAGEMENT_IPV4` with the actual address reachable from the
routers, not a router's IP. Windows Firewall must permit only the expected
routers to send UDP 5514 to that address. An administrator must separately
configure the routers to forward syslog to this PC and port, with the management
interface as the source. Cisco IOS syntax varies by image; validate the
configuration yourself. The agent will not do it.

Only source IPs matching inventory entries are ingested. UDP is unauthenticated,
can be spoofed, can lose packets, and is not trusted accounting. The stored
`observed_at` field is **collector receipt UTC**, not proof of device event time.
Use synchronized device clocks and a protected production log/AAA collector if
you need defensible attribution.

To establish an OS downgrade and responsible account you generally need:
prior/current image records, timestamped boot/install/rollback events, trusted
AAA command accounting, and correlated change/automation records. A nearby login
or a shared account is not proof of a person. A version difference establishes
only an observation interval until further evidence is correlated; the app does
not lexically compare version strings to declare a downgrade.

The AI is explicitly instructed to answer **unknown** when change time or
attribution is absent. It receives recent local SSH observations (12), syslog
messages (12) and imports (6), plus this run's output. This is a bounded evidence
window, not an exhaustive historical search. Device output is capped at roughly
24 KB per command, cloud output at 6,000 characters per record within an overall
budget. Truncation is marked. Refine the scope or inspect original retained logs
for deeper historical investigations.

## Persistence, safety and limitations

All runtime data is local in ignored `data\evidence.sqlite3`: redacted command
observations, syslog/imports, complete returned investigation reports and audit
events. Reports are persisted before the HTTP request is declared successful.
The GUI's Export JSON downloads the current report. Protect database/exports with
Windows file permissions; they can still contain sensitive operational data.
Audit events omit raw questions, command output and credentials. This is a
single local session, not per-human identity attribution or tamper-proof audit.
There is no automatic retention/pruning; monitor disk usage and archive data
according to your policy.

The server binds only to `127.0.0.1`, requires a random local bearer token for
APIs, validates Host/Origin, blocks cross-origin requests, and renders evidence
as text (not HTML). The token stays in JavaScript memory, not browser storage or
URLs. Do not expose this development server through a tunnel/reverse proxy.
For multi-user use, add production hosting, trusted TLS, SSO, identity-based authorization,
protected auditing, egress controls and rate limits. This is a local lab solution,
not a production NMS or an autonomous remediation agent.

## Offline validation

```powershell
python -m unittest discover -s tests -v
```

Tests use synthetic data/fakes and temporary databases. No AI API key or live
device access is needed. Live connectivity, your account permissions, SSH
algorithms, actual IOS output and real provider availability/quota must be checked in your lab.

For an optional GUI smoke check using an already installed Microsoft Edge:

```powershell
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe .\tests\browser_smoke.py
.\.venv\Scripts\python.exe .\tests\browser_smoke.py --https
```

This opens a temporary headless browser profile and a temporary loopback demo
server, exercises the GUI and JSON download, and cleans both up afterwards.
The HTTPS browser smoke allows the temporary test certificate only in its test
browser context; separate HTTPS unit tests verify certificate trust explicitly.

## Implementation references

- Google Gen AI Python SDK: https://github.com/googleapis/python-genai
- Gemini structured output: https://ai.google.dev/gemini-api/docs/structured-output
- OpenRouter structured output: https://openrouter.ai/docs/guides/features/structured-outputs
- OpenRouter free router: https://openrouter.ai/openrouter/free
- OpenRouter provider preferences: https://openrouter.ai/docs/guides/routing/provider-selection
- Paramiko SSH client/host-key policy: https://docs.paramiko.org/en/stable/api/client.html
- Paramiko SSH channel API: https://docs.paramiko.org/en/stable/api/channel.html
