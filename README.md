# pypi-verify-action

Verify a freshly published PyPI release end-to-end, fail-closed.

`twine upload` succeeding does **not** mean the release is usable. Broken
builds reach users when nobody verifies what the index actually serves: a
schema file that was never packaged, a stale hardcoded `__version__`, a
stale build uploaded over the intended one. This action closes that gap
between "uploaded" and "verified":

1. **Waits for PyPI index propagation** (the JSON API lags the upload).
2. **Installs the exact published version** (`pkg==version`) into a clean
   venv with `--no-cache-dir` from `https://pypi.org/simple` — what users actually get.
3. **Asserts the installed version** matches the one you intended to publish.
4. **Checks expected files** under site-packages (e.g. bundled schemas).
5. **Runs your smoke commands** inside that venv.

Any failure turns the workflow red.

## Usage

```yaml
steps:
  - uses: holdout-labs/pypi-verify-action@v1.1.0
    with:
      package: falsification-ledger
      version: 0.1.4            # the version you just uploaded
      expected-files: |
        falsification_ledger/schema/*.json
      smoke-commands: |
        fl version
        fl --help
```

Place it in the same workflow right after the separate upload step, or invoke it
manually with an exact version. It does not upload a release. Pin `uses` to an
immutable commit SHA for reproducibility; a moving `v1` tag may change.

Holdout package repositories use `verify-pypi.yml`, triggered by a published
GitHub release or an explicit manual version. Pin the reviewed action commit,
rather than `main`, when wiring the verifier. A GitHub release published before
uploading to PyPI fails verification until the exact version appears; rerun
after upload. The existing `v1` tag is retained; use `v1.1.0` or its commit SHA
to select this update explicitly.

Version `v1.1.0` uses a unique disposable venv on Windows and Linux,
pins the public PyPI index, runs smoke commands outside the source checkout and
removes the temporary directory after success or failure. It ignores host Python
path overrides and rejects expected-file globs that escape site-packages.
Smoke commands are trusted workflow code, executed via
Bash; do not populate them from pull-request text or other untrusted input.

## Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `package` | yes | — | PyPI project name |
| `version` | yes | — | The version that was just published |
| `python-version` | no | `3.11` | Python for the verification venv |
| `timeout-seconds` | no | `300` | Max wait for index propagation |
| `poll-seconds` | no | `10` | Poll interval while waiting |
| `expected-files` | no | — | Newline-separated globs under site-packages that must exist |
| `smoke-commands` | no | — | Newline-separated shell commands run inside the fresh venv |

## Why this exists

This org publishes seven PyPI packages. In September 2026 alone, real
incidents motivated every check in this action:

- a schema file resolved relative to the repo layout was never bundled —
  `fl submit` crashed for anyone who `pip install`ed the package;
- a build carried a stale hardcoded `__version__` (package said 0.1.2, CLI
  said 0.1.1);
- a stale parallel build reached PyPI first and was only caught by manually
  comparing hashes and installing into a scratch venv.

All three were caught by hand. This action automates that hand-check so a
broken publish announces itself instead of waiting for users to find it.

## License

MIT
