# Publishing taf-decoder to PyPI

Releases are published by GitHub Actions (`.github/workflows/publish.yml`) using
PyPI *trusted publishing*, so no password or API token is stored anywhere.

## One-time setup

1. Create accounts on <https://pypi.org> and <https://test.pypi.org> (enable 2FA).
2. On each site go to **Account → Publishing → Add a new pending publisher** and enter:
   - PyPI project name: `taf-decoder`
   - Owner: `Sladekd`
   - Repository: `Terminal-Forecast-Python-Processing`
   - Workflow: `publish.yml`
   - Environment: `pypi` (on test.pypi.org: `testpypi`)
3. In the GitHub repository, **Settings → Environments**, create environments `pypi` and
   `testpypi` (optionally require your approval for `pypi`).

## Releasing a version

1. Update `version` in `pyproject.toml`, `CITATION.cff` and add a section to `CHANGELOG.md`.
2. Commit and push to `main`; wait for CI to pass.
3. Optional dry run: **Actions → Publish → Run workflow → `testpypi`**, then
   `pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ taf-decoder`.
4. Create a GitHub release with tag `v<version>` (e.g. `v0.1.0`). The workflow checks that the tag
   matches `pyproject.toml`, builds, tests the wheel and uploads it to PyPI.

## Manual alternative

```bash
pip install build twine
python -m build
twine check dist/*
twine upload dist/*          # asks for a PyPI API token
```
