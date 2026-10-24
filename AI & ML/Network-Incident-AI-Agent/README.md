# Local Network Incident Agent

A complete command-line learning project: a local LLM selects tools, receives
their results, and iterates toward a cited investigation report. No OpenAI key,
Python packages, SSH access, or paid API is required. Python 3.10+ is required.

## Quick start

Extract this folder, open PowerShell or a terminal in it, and run:

```powershell
python agent.py samples/mixed.log --demo --out reports/demo.json
python -m unittest -v
```

The demo is rule-based and explicitly labeled; it is not an AI inference run.

## Enable the real local AI agent

Install Ollama from https://ollama.com/download and start its desktop application
(or run `ollama serve` in another terminal if no server is already running).
Download a tool-capable local model:

```powershell
ollama pull qwen3:4b
python agent.py samples/mixed.log --model qwen3:4b --out reports/incident.json
```

Model download needs internet and disk space; inference uses your computer.
Available RAM and model/context size determine performance. You may choose a
different locally downloaded tool-capable model with `--model`.
Do not select a cloud model if logs must stay local. The application sends data
only to 127.0.0.1:11434, with HTTP proxies disabled.

## How the agent works

1. You select one UTF-8 log file, maximum 100 KB.
2. The LLM receives numbered logs and investigation instructions.
3. It chooses `inspect_logs` and `get_runbook` through Ollama tool calling.
4. The Python dispatcher validates tool names and arguments.
5. Tool results return to the model for further reasoning, up to eight rounds.
6. A final report and tool trace are saved as JSON, plus a Markdown report.

The tools read only the supplied logs and built-in guidance. There is no shell
execution, device connection, arbitrary file-reading tool, or configuration tool.
Reports contain Observations, Possible causes, Missing evidence, and Next checks.
Line citations are checked for valid bounds; this does not validate every claim.
Review diagnoses against the original logs and current device state.

The included examples are synthetic and contain documentation IP addresses.
Mixed and recovery events remain visible; the parser does not infer current state
or prove that a preceding event caused a later one. Large files should be split
into individual incidents. Keyword extraction is deliberately a simple baseline
and may miss vendor-specific syntax. Log content can contain prompt injection;
instructions treat it as data and the narrow dispatcher limits possible actions,
but model answers still need review. JSON reports preserve supplied log evidence;
keep them private if your logs are sensitive.

## Files and concepts

| File | Purpose |
|---|---|
| agent.py | Instructions, tools, validation, model client, loop, CLI, demo |
| test_agent.py | Offline functional and agent-loop tests with simulated model replies |
| samples/ | Three synthetic incidents |
| PROJECT_GUIDE.md | Assignment mapping and honest evaluation plan |

No model weights are bundled. Automated tests exercise the tool loop using
simulated responses; a successful local model run must be checked separately.

## Troubleshooting

- Connection refused: start Ollama and check its local service.
- Model not found: run `ollama pull` with the same model name.
- Tool/step-limit error: use a tool-capable model and a shorter incident.
- Timeout: try a smaller model or fewer log lines; the HTTP timeout is 180 seconds.
- Python not found: install Python 3.10+ and reopen your terminal.

## API reference

Implementation follows Ollama's documented `/api/chat` tool-call loop:
https://docs.ollama.com/capabilities/tool-calling

No training or fine-tuning is performed in this starter project.
