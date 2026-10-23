# Releases

No SDK release or publishing workflow exists yet. The foundation is private,
has no selected open-source license, and carries `Private :: Do Not Upload`.
Local builds use `MORPHIQ_SDK_BUILD_VERSION=0.0.0.dev0`; the backend reads this
value without a hand-maintained release version in the source package.

The SDK will have an independent version stream. API contract, service and
engine versions remain separate identities; never derive an SDK release from
an engine tag.

[Release automation and public distribution (#113)](https://gitlab.com/prophetizo/morphiq-labs/sites/morphiq-api/-/work_items/113)
must deliver confirmed name ownership, licensing and public source/support
routing; conventional-commit-driven release PRs and generated changelogs/tags;
clean wheel/sdist checks and TestPyPI verification; constrained publishing
permissions (prefer trusted publishing); and compatibility/recovery guidance.
Removing the private classifier is part of that reviewed release work.

No manual version bumps, hand-edited released notes, hand-cut tags or ad hoc
package uploads. Project setup does not publish a package or deploy a service.
