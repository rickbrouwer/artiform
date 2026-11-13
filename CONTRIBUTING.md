# Contributing

All contributions are welcome:

- ask questions, report problems, request features or share how you use
  ArtiForm: open an **Issue**,
- improve the documentation or the example configurations: open a **Pull
  Request**,
- contribute bug fixes, new features, support for an Artifactory behavior we
  have not seen yet, refactoring or other code improvements: open a **Pull
  Request**.

If you want to help but do not know how, open an Issue and say so.

## Issues

The project is small and so are the rules for issues: common sense applies.

### Questions

Before asking, please check the [documentation](docs/index.md); the
reference pages list the known behaviors of each config section.

### Problems

Before reporting a problem, update to the latest ArtiForm release and check
whether it persists. If it does, describe your environment, what you did,
what you expected and what happened instead. Please include:

- the ArtiForm version (first line of every run, or `artiform --version`),
- the Artifactory version and license tier (Projects and cleanup policies
  depend on the license),
- how you run it (the container image, or Python version and operating
  system),
- the config, or the relevant fragment, with hostnames, user names and
  secrets redacted,
- for a wrong or unexpected diff, the output of `--dry-run -v`; for a failed
  change, the error summary at the end of the run.

ArtiForm talks to many Artifactory REST endpoints and several of them behave
differently from their documentation. If you hit one of those on a version we
have not seen, the request and response details that `-v` logs are the most
useful thing you can share.

Do not report security problems in a public issue. Use the repository's
private vulnerability reporting ("Report a vulnerability" under the Security
tab) instead.

### Feature requests

We accept feature requests but do not promise to implement them. An issue
still shows interest in a feature, which helps maintainers and other
contributors decide what to build next.

## Pull Requests

Open an issue first for anything beyond a small fix, so the approach can be
agreed on before you spend time on it. Then fork the repository, branch from
`main` and open a pull request against `main`. CI runs the tests on every
supported Python version and each linter as a separate job.

The articles below cover the rest:

- [Development](docs/contrib/development.md): environment setup, tests,
  static analysis, git hooks, CI and the coding guidelines.
- [How it works](docs/index.md#how-it-works): the design properties every
  change has to respect (asymmetric comparison, passthrough fields, opt-in
  deletions).
- [Releases](docs/contrib/releases.md): versioning and how a release is cut.
  Leave `docs/changelog.md` and the version in `pyproject.toml` to the
  maintainer.

By contributing you agree that your contributions are licensed under the
[MIT License](LICENSE).
