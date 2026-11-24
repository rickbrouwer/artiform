# Changelog

This changelog follows industry-standard best practices. Each release includes the version, date, and a list of categorized changes: `Breaking Changes`, `Features`, `Bug Fixes`, `Documentation`, `Refactors`, `Dependencies`, and `Chores`.

---

## 0.2.0

### Features

* manage Xray retention and index patterns per repository [#13](https://github.com/rickbrouwer/artiform/pull/13). ([rickbrouwer](https://github.com/rickbrouwer))

### Bug Fixes

* default share read_only to false for remote repositories [#12](https://github.com/rickbrouwer/artiform/pull/12). ([rickbrouwer](https://github.com/rickbrouwer))

### Tests

* acceptance tests against Artifactory OSS [#9](https://github.com/rickbrouwer/artiform/pull/9). ([rickbrouwer](https://github.com/rickbrouwer))

### Dependencies

* Update various dependencies to newer versions.

Thanks to all the contributors of this release!

## 0.1.1

### Documentation

* restructure CONTRIBUTING around issues and pull requests [#5](https://github.com/rickbrouwer/artiform/pull/5). ([rickbrouwer](https://github.com/rickbrouwer))

### Refactors

* drop redundant error handling and share the change recorder in the engine [#6](https://github.com/rickbrouwer/artiform/pull/6). ([rickbrouwer](https://github.com/rickbrouwer))

Thanks to all the contributors of this release!

## 0.1.0

### Features

* Initial release: reconcile JFrog Artifactory projects, repositories, project members and package cleanup policies against one YAML file.
