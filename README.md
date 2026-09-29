# ci-result-publisher

A generic result handoff for jobs running on private self-hosted GitHub
Actions runners. It uploads arbitrary project files as a workflow artifact,
writes a human-readable step summary, generates (or augments) a
machine-readable `result.json`, and can maintain one stable pull-request
comment. It contains no repository-, language-, or model-specific logic --
the project supplies its own files and metadata; this action only moves
them through GitHub's own repository-scoped facilities (artifacts, step
summaries, PR comments via the workflow's own `GITHUB_TOKEN`).

Why this exists: a private runner job often has no credentials to write
results anywhere else -- no PAT, no SSH key, no cross-repository access.
This action never needs any of that. It only uses what the workflow's
default `GITHUB_TOKEN` already grants.

## Usage

```yaml
- name: Run project task
  id: task
  continue-on-error: true
  run: |
    mkdir -p ci-result
    ./project-specific-command \
      >ci-result/stdout.log \
      2>ci-result/stderr.log

- name: Publish CI result
  if: always()
  uses: ahojukka5/ci-result-publisher@v1
  with:
    artifact-name: project-result-${{ github.run_id }}-${{ github.run_attempt }}
    paths: |
      ci-result/
      generated/
      reports/
    status: ${{ steps.task.outcome }}
    summary-file: ci-result/summary.md
    metadata-file: ci-result/result.json
    retention-days: 30
    pull-request-number: ${{ github.event.pull_request.number }}
```

`continue-on-error: true` on the task step plus `if: always()` on the
publish step is the pattern that makes this work for failed and
partially-successful jobs, not just successful ones: the publish step still
runs and still has real files to upload even when `project-specific-command`
exited non-zero.

See `examples/` for two workflows to copy (source generation and
test/benchmark). They are templates: `./run-generator.sh` and
`./run-benchmarks.sh` belong to the project that copies them, not to this
repository.

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `artifact-name` | yes | | Name for the uploaded artifact. |
| `paths` | yes | | Newline-separated files/directories to upload. Not interpreted. |
| `status` | yes | | Final status of the preceding task, e.g. `${{ steps.task.outcome }}`. |
| `summary-file` | no | `''` | Project-provided Markdown summary. A generic fallback is used if omitted or missing. |
| `metadata-file` | no | `''` | Project-provided `result.json`. A default envelope is generated if omitted, missing, invalid, or not a JSON object. |
| `retention-days` | no | `30` | Artifact retention. |
| `pull-request-number` | no | `''` | PR to maintain a stable comment on. Omit for push/schedule/dispatch runs. |
| `redact` | no | `''` | Newline-separated literal secret values, or env var *names* holding them, to redact from the summary/comment. |
| `comment-marker` | no | `<!-- private-ci-result -->` | Marker identifying this action's stable comment. |

## Outputs

| Output | Description |
|---|---|
| `artifact-name` | Echoes the `artifact-name` input. |
| `result-json-path` | Path to the (possibly generated) `result.json` that was bundled into the artifact. |

## The `result.json` envelope

A project may optionally write its own `result.json` and point
`metadata-file` at it. This action merges it with the fields it always
knows to be true from the run itself -- those always win over anything the
project put in the same keys, so an automated consumer can trust them
regardless of what the project script did:

```json
{
  "schema": "private-ci-result-v1",
  "status": "failure",
  "exit_code": 1,
  "source_repository": "owner/repository",
  "source_sha": "abcdef123456",
  "workflow_run_id": 123456789,
  "workflow_run_attempt": 1,
  "job": "generate",
  "artifact_name": "project-result-123456789-1",
  "run_url": "https://github.com/owner/repository/actions/runs/123456789",
  "summary": "The task produced output but validation failed.",
  "outputs": [
    { "path": "generated/", "kind": "generated-files" },
    { "path": "reports/", "kind": "reports" }
  ],
  "details": {}
}
```

`details` is intentionally project-defined and opaque to this action -- a
compiler workflow might record diagnostics there, a benchmark workflow
performance metrics, a code-generation workflow pending repairs, and so on.
If a project doesn't supply `outputs`, a minimal one is derived from the
`paths` input (`kind: "unspecified"` for each entry); if it doesn't supply
`exit_code` or `details`, those are simply absent/`{}`.

## Consuming a result

An external, automated reviewer (or a human) can retrieve a result purely
through GitHub's own APIs, without any access to the runner itself:

1. Find the workflow run for a commit or pull request
   (`GET /repos/{owner}/{repo}/actions/runs`).
2. Read the job conclusion and step summary.
3. Download the named artifact
   (`GET /repos/{owner}/{repo}/actions/artifacts`, then the ZIP).
4. Read `result.json` from it.
5. Inspect the project-specific files only when needed.

## Promotion is a separate concern

This action only publishes a result as an artifact/comment -- it never
writes to another repository, and never needs a credential that could. If a
project wants to *promote* selected output somewhere else (a package
registry, another repository, a release), that's a distinct, separately
triggered workflow that:

1. downloads the artifact,
2. verifies its source commit and manifest (the `result.json` envelope),
3. validates its contents,
4. publishes selected files elsewhere.

That promotion workflow can use stronger credentials since a human or a
separate trust boundary decides when it runs; the private execution job
that produced the result never needs them.

```text
project-specific task
    -> generic result bundle
    -> GitHub Actions artifact
    -> automated or human review
    -> optional project-specific promotion
```

## Security

- **No cross-repository credential is ever required or accepted.** This
  action only uses the calling workflow's own `GITHUB_TOKEN` and the
  standard Actions artifact/summary/comment APIs.
- **Redaction is text-substitution over the summary and PR comment only**,
  not a general secret scanner over arbitrary uploaded files -- scanning
  binaries or large generated trees for secrets is out of scope for a
  generic action. Pass `redact` (literal values or env var names) for
  anything the project's own summary text might otherwise leak.
- **Symlinks are rejected, not silently followed**, if they resolve outside
  the `paths` root that contains them (`scripts/check_symlinks.py`). An
  artifact that may become visible to a reviewer (or, for a public
  repository, to anyone) should never silently gain files from outside what
  the project asked to publish.
- **The PR-comment search only checks the most recent 100 comments** on the
  target PR (`actions/github-script`'s single-page `listComments` call). A
  PR that already has more than 100 comments before this action's first run
  on it could get a duplicate comment on that first run rather than an
  update; every run after that finds it normally.

## Recommended permissions

```yaml
permissions:
  contents: read
  actions: read
  issues: write
  pull-requests: write
```

`issues: write` / `pull-requests: write` are only needed when
`pull-request-number` is set.

## Versioning

Pin a release tag or an immutable commit SHA:

```yaml
uses: ahojukka5/ci-result-publisher@v1
```

`v1` moves to the latest compatible `v1.x.y` release; pin a full SHA instead
if you want a fully immutable reference.
