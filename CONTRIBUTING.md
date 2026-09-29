# Contributing to dnp3py

Thanks for looking at dnp3py. This file covers how to set up a dev
environment, run the checks CI runs, and the conventions pull requests
follow.

## Setting up

dnp3py uses [pixi](https://pixi.sh) to manage the dev environment.

```bash
pixi install
pixi run dev-install
```

Plain `pixi install` sets up `pixi.toml`'s `default` environment, which is
Python 3.14. CI tests Python 3.11 through 3.13 only, not 3.14, so build and
test against a CI-tested environment instead:

```bash
pixi run -e py313 dev-install
```

`dev-install` runs `pip install -e .` inside the pixi environment. Run every
check below through `pixi run -e py313 <command>`, or open a shell in that
environment first with `pixi shell -e py313`; a bare command uses whatever
Python is first on your PATH, not pixi's.

## Running the checks CI runs

`CI Check` is the required status check on `main`. It is the aggregate of
the `test`, `quality`, and `build` jobs, and a pull request merges only once
it passes. Review is expected on every pull request; it is a project
practice, not a required approval enforced by GitHub. Run the same commands
`test`, `quality`, and `build` run, through `pixi run -e py313` or inside
`pixi shell -e py313`:

```bash
pytest tests/ -v --tb=short
```

```bash
ruff format --check src/ tests/
ruff check src/ tests/
```

```bash
mypy src/
```

`build` also runs:

```bash
python -m build
twine check dist/*
```

Neither `build` nor `twine` is in the pixi environment. Install them into a
scratch environment to run this step locally (`pip install build twine`),
or skip it and let CI check the package build.

CI's `quality` job pins `ruff==0.15.18` to match `.pre-commit-config.yaml`;
`pixi.toml` allows a newer ruff, so a locally newer ruff can format or flag
code differently than CI. Run `pip install "ruff==0.15.18"` in a scratch
environment if your formatting disagrees with CI, or trust CI as the final
answer. Installing the pre-commit hooks (`pixi run pre-commit-install`)
catches most of this before you push.

## Conventions

- Commit subjects: `type(scope): description (#NNN)`, ending with the
  issue number when there is one, conventional-commits style. The release
  tooling parses these to compute the next version and the changelog, so
  the type (`feat`, `fix`, `docs`, and so on) matters.
- Branches: `type/NNN-slug`.
- One property per pull request. A pull request that closes part of a
  larger issue, and says so, is normal.
- Pull requests land by merge commit or rebase merge, never squash: the
  commit trail is kept.
- Security vulnerabilities go through [SECURITY.md](SECURITY.md), never a
  public issue, pull request, or discussion.

## Standards text

IEEE 1815 and IEEE 1815.2 are copyrighted standards. Cite a clause or
table number (for example "1815.2 clause 5.6.3") in code, comments,
commits, and pull requests; never paste text from the standard itself.

## Where to start

Issues labeled `good first issue` are scoped for a first contribution.
For larger work, [ROADMAP.md](ROADMAP.md) lays out the path to IEEE 1815.2
conformance; issues labeled `1815.2-conformance` are that body of work,
and each roadmap milestone links to its own epic issue.
