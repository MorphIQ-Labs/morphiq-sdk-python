# SDK v0.1 delivery

[Milestone: MorphIQ SDK for Python — v0.1 and cookbook](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/milestones/8)

The initial backlog lives with the API project in GitLab. SDK implementation is
reviewed in this GitHub repository; contract publication and website integration
are reviewed in the API repository. Link PRs/MRs and evidence back to their work
items. All items below are planned until their acceptance is demonstrated.

| Work item | Owner | Dependencies |
| --- | --- | --- |
| [#105 Repository and development foundation](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/105) | SDK | — |
| [#106 Versioned OpenAPI handoff](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/106) | API + SDK | — |
| [#107 Typed models and operation coverage](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/107) | SDK | #105, #106 |
| [#108 Sync/async transport and safe retries](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/108) | SDK | #105 |
| [#109 Batches and optional DataFrames](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/109) | SDK | #107, #108 |
| [#110 Contract and compatibility CI](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/110) | SDK + API | #107–#109 |
| [#111 Eight tested cookbook recipes](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/111) | SDK | #107–#109 |
| [#112 Website quickstart and cookbook integration](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/112) | API web | #111 |
| [#113 Releases and public distribution](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/113) | SDK | #105 |
| [#114 Clean-environment launch acceptance](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/114) | SDK + API | #106, #110–#113 |

Public release requires contract coverage, accurate error/charge semantics,
clean installation, executable examples and a measured five-minute first-use
journey. No delivery date is assumed.

## Hosted notebook follow-on

[#115 Interactive hosted notebook exploration](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/115)
evaluates a browser experience built from the cookbook, including runtime choice,
credentials, CU visibility, session isolation, costs and download/local-run support.
It is outside the initial SDK milestone. A prototype and a decision come before
an implementation/hosting commitment.
