# Artifact Appendix

Paper title: **GapLeak: When Privacy-Preserving LLM-based Web Agents Become a Privacy Risk**

Requested Badge(s):

- [x] **Available**
- [ ] **Functional**
- [ ] **Reproduced**

## Description

This artifact accompanies the paper by Chaklam Cheong, Tiancong Cao, Qi Li,
Zelin Zhang, Jianbing Ni, Rongxing Lu, and Mohammad Zulkernine, accepted to
Proceedings on Privacy Enhancing Technologies (PoPETs) 2027, Issue 2.

The repository provides controlled web-task environments for studying how
information gaps and website guidance affect disclosure by LLM-based web
agents. It includes four scenarios: recruitment, e-commerce returns, travel
booking, and medical intake. Each scenario contains synthetic user materials
and benign/manipulated website variants. Summary and boundary documents
represent the information-access conditions studied in the paper.

The public release contains:

| Component | Location | Relation to the paper |
| --- | --- | --- |
| Scenario servers and synthetic data | `src/GapLeak/` | Implements the four controlled web-task environments. |
| Summary and boundary materials | `assets/scene1/` through `assets/scene4/`, and `src/GapLeak/candidate_vault_assets/` | Supplies the user materials and information-access conditions. |
| Task prompts | `src/GapLeak/S1_Prompt.txt` through `S4_Prompt.txt` | Defines tasks and URL placeholders for the four scenarios. |
| Automated metrics | `src/GapLeak/scene1_metrics.py`, plus `metrics.py` in `ecommerce_support/`, `travel_booking/`, and `health_intake/` | Computes task-success and privacy-disclosure measures from scenario records. |
| Agent execution helpers | `scripts/run_browseruse_once.py`, `scripts/run_agente_overlay.py`, and `scripts/common.py` | Provides BrowserUse and Agent-E experiment starters. |
| Verification and batch helpers | `scripts/stv_verifier.py`, `scripts/run_browseruse_stv.py`, and `scripts/run_batch.py` | Provides field-verification logic and experiment orchestration. |
| Example traces | `examples/` | Illustrates run configurations, recorded submissions, and agent outputs. |
| LLM-judge materials | `LLM-Judge/` and `docs/llm_judge_reference.md` | Provides judging prompts, scenario definitions, and per-episode result files. |
| Scenario and output documentation | `docs/` | Describes the released websites, metrics, and output formats. |

### Scope of the Public Release

This submission requests the **Available** badge. It does not request
certification that the complete experiments execute or that all quantitative
results in the paper can be reproduced from this release.

The repository contains selected example traces rather than the complete
experiment output logs. It excludes API credentials, browser profiles, and
the proprietary DoBrowser integration. Running live-agent experiments
requires third-party software and model access; those services and model
weights are not distributed with this artifact.

The released STV runner retrieves a completed submission, applies the
independent verifier to its fields, and recomputes metrics on the filtered
submission. It therefore supports analysis of field filtering after a run;
it does not implement a browser-level interception hook that prevents the
original submission from reaching the scenario server. Users should account
for this implementation scope when interpreting or extending the defense.

### Security/Privacy Issues and Ethical Concerns

The scenario personas, documents, and records are synthetic research
fixtures. The websites intentionally include guidance that may induce an
agent to access or disclose information outside its assigned task. They
should be used in a controlled local test environment with synthetic data,
not with real accounts, private documents, or an everyday browser profile.

The website starters bind their services to the local machine. Keep these
experimental services local: they include administrative endpoints intended
for collecting and inspecting experiment records. Do not expose them as
production services.

Live-agent and verifier execution sends prompts and task context to the
selected external model provider and may incur API charges. Use dedicated
test credentials and follow the provider's access conditions. Keep any
credentials in local configuration, and do not commit them or publish them
in experiment traces. Public inspection and downloading of this artifact
require no credentials or payment.

## Environment

### Accessibility

The artifact is publicly available at:

<https://github.com/Hunter-CCL/GapLeak_release>

The repository and its files can be viewed or downloaded without requesting
access from the authors. To obtain a working copy:

```bash
git clone https://github.com/Hunter-CCL/GapLeak_release.git
cd GapLeak_release
```

The release is licensed under the **MIT License**, provided in `LICENSE`.
No installation or model API access is necessary to inspect the source,
synthetic fixtures, documentation, or recorded example files. The README
contains optional execution instructions. The project declares Python 3.13
or later; the core scenario servers use Python's standard-library HTTP
server facilities. Live-agent execution has additional requirements as
described in the README.

This appendix follows the current development branch during evaluation so
that fixes remain available to reviewers. After evaluation, a specific
reviewed Git commit or release will be supplied as the stable artifact
reference.

## Notes on Reusability

Researchers can reuse the synthetic websites, disclosure definitions, and
prompt templates to compare other web-agent frameworks or study alternative
authorization policies. The website-only launcher
(`scripts/start_scene_site.py`) makes the scenarios available independently
of the supplied agent runners. The metrics and sample traces can also help
users understand the expected record formats before extending the code.

When modifying a scenario, update its synthetic source materials, allowed
disclosures, task-success conditions, and metric definitions together so
that the task and its evaluation remain consistent.
