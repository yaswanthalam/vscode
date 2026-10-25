# Project explanation and submission plan

## Goal

Investigate saved network logs using a local tool-using AI agent. Produce
observations with line citations, possible causes, missing evidence, and next
diagnostic checks. It is an investigation assistant, not an autonomous repair system.

## Assignment mapping

- A1 Harness: use the CLI, numbered inputs, baseline demo, structured report,
  local model configuration and trace to reproduce an incident investigation.
- A2 Evaluation: compare baseline and LLM reports on independently labeled cases.
  Include unknown events, recovery, mixed incidents, misleading order, and injected
  instructions. Do not treat the three examples as a representative benchmark.
- A3 Training: not yet implemented. A genuine training submission needs a labeled
  dataset, separate train/validation/test incidents, a trained component, and a
  held-out comparison. Prompt changes alone should not be called model training.
- Final project: demonstrate a complete local-model investigation, explain tool
  traces, compare against the baseline, and discuss limitations.

## Suggested evaluation worksheet

Create one row per independent incident: ID, expected categories, evidence lines,
baseline categories, model observations, valid/supporting citations, unsupported
claims, next-check usefulness, model name, run time and reviewer notes. Record
hardware and Ollama version. Split by incident/template, not individual log lines.

Report category precision/recall if you manually normalize report labels, evidence
support rate, unsupported-claim rate, and median elapsed time. Use a fixed rubric
and keep a separate held-out set. Confidence numbers from an LLM are not calibrated
probabilities. Do not claim accuracy or robustness from unit tests alone.

## Demonstration script

1. Run the deterministic demo on samples/mixed.log.
2. Run the real agent on the same sample with Ollama.
3. Inspect JSON tool traces and verify cited lines.
4. Check whether the report notices recovery and avoids claiming proven causality.
5. Run samples/unknown.log and inspect its uncertainty.
6. Present a failure case and explain what extra evidence is needed.

## Possible extensions

Add vendor-specific parsers, a curated topology input, a labeled classifier or
retrieval component, and a graphical interface. Any later device integration
should be designed separately; this version does not connect to devices.
