# Publishing to PyPI

One-time setup:

1. Create a PyPI account (pypi.org).
2. Generate an API token (Account settings → API tokens). The `auditrails`
   project doesn't exist yet, so the first token must be account-scoped
   ("Entire account"); once the first release lands, narrow it to a
   project-scoped token for `auditrails` and rotate the secret.
3. Add it as a repo secret: `gh secret set PYPI_API_TOKEN --repo auditrails/auditrails-python`.

Releasing a new version:

1. Bump `version` in `pyproject.toml`, commit.
2. `git tag v<new-version> && git push && git push --tags`.

Pushing a `v*` tag runs `.github/workflows/publish.yml`, which tests, builds
sdist+wheel, and uploads via `pypa/gh-action-pypi-publish` using
`PYPI_API_TOKEN`. The workflow fails closed if the tag doesn't match
`pyproject.toml`'s version.
