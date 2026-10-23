# SDK v0.1 delivery

[Milestone: MorphIQ SDK for Python — v0.1 and cookbook](https://github.com/MorphIQ-Labs/morphiq-sdk-python/milestone/1)

The SDK backlog and implementation live in this GitHub repository. Contract
publication and website integration are implemented in the API repository and
linked from their SDK dependency issues. Link PRs/MRs and evidence back to the
issues. The first preview implements sync/async single-option pricing, introductory
European/American examples, Start Here and a local Docker launcher. The broader
issue acceptance below remains open until its full scope is demonstrated.

| Work item | Owner | Dependencies |
| --- | --- | --- |
| [#1 Repository and development foundation](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/1) | SDK | — |
| [#2 Versioned OpenAPI handoff](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/2) | API + SDK | — |
| [#3 Typed models and operation coverage](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/3) | SDK | #1, #2 |
| [#4 Sync/async transport and safe retries](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/4) | SDK | #1 |
| [#5 Batches and optional DataFrames](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/5) | SDK | #3, #4 |
| [#6 Contract and compatibility CI](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/6) | SDK + API | #3–#5 |
| [#7 Eight tested cookbook recipes](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/7) | SDK | #3–#5 |
| [#8 Website quickstart and cookbook integration](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/8) | API web | #7 |
| [#9 Releases and public distribution](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/9) | SDK | #1 |
| [#10 Clean-environment launch acceptance](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/10) | SDK + API | #2, #6–#9 |
| [#13 Local Docker notebook experience](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/13) | SDK | #1, #4, #7 |
| [#14 Notebook image checks and releases](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/14) | SDK | #6, #9, #13 |

Public release requires contract coverage, accurate error/charge semantics,
clean installation, executable examples and a measured five-minute first-use
journey. No delivery date is assumed.

## Hosted notebook follow-on

[#11 Interactive hosted notebook exploration](https://github.com/MorphIQ-Labs/morphiq-sdk-python/issues/11)
evaluates a browser experience built from the cookbook, including runtime choice,
credentials, CU visibility, session isolation, costs and download/local-run support.
It is outside the initial SDK milestone. A prototype and a decision come before
an implementation/hosting commitment.
