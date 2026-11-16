import pytest

from artiform.config import load_config, parse_config
from artiform.exceptions import ConfigError


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("ARTIFACTORY_URL", "https://artifactory.example.com")
    monkeypatch.setenv("ARTIFACTORY_TOKEN", "my-access-token")


MAIN = """\
config_version: 1
enforce_projects: true
include_projects: projects/*.yml
"""


def write(tmp_path, relative, content):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_projects_merged_from_included_files(tmp_path):
    main = write(tmp_path, "artiform.yml", MAIN)
    write(tmp_path, "projects/team-x.yml", "projects:\n  team-x:\n    display_name: X\n")
    write(tmp_path, "projects/team-y.yml", "projects:\n  team-y: {}\n")

    config = load_config(main)
    assert set(config.projects) == {"team-x", "team-y"}
    assert config.projects["team-x"].settings["display_name"] == "X"
    assert config.enforce_projects


def test_duplicate_project_across_files_rejected(tmp_path):
    main = write(tmp_path, "artiform.yml", MAIN)
    write(tmp_path, "projects/a.yml", "projects:\n  team-x: {}\n")
    write(tmp_path, "projects/b.yml", "projects:\n  team-x: {}\n")
    with pytest.raises(ConfigError, match="defined in both"):
        load_config(main)


def test_duplicate_with_main_file_rejected(tmp_path):
    main = write(tmp_path, "artiform.yml", MAIN + "projects:\n  team-x: {}\n")
    write(tmp_path, "projects/team-x.yml", "projects:\n  team-x: {}\n")
    with pytest.raises(ConfigError, match="defined in both"):
        load_config(main)


def test_pattern_matching_no_files_rejected(tmp_path):
    main = write(tmp_path, "artiform.yml", MAIN)
    with pytest.raises(ConfigError, match="matched no files"):
        load_config(main)


def test_broken_included_file_aborts_run(tmp_path):
    # A silently skipped team file plus enforce_projects would delete the
    # team's project, so any file error must abort the whole run.
    main = write(tmp_path, "artiform.yml", MAIN)
    write(tmp_path, "projects/team-x.yml", "projects:\n  team-x: {}\n")
    write(tmp_path, "projects/broken.yml", "projects: [not, a, mapping]\n")
    with pytest.raises(ConfigError, match="broken.yml"):
        load_config(main)


def test_included_file_may_only_define_projects(tmp_path):
    main = write(tmp_path, "artiform.yml", MAIN)
    write(
        tmp_path,
        "projects/sneaky.yml",
        "projects:\n  team-x: {}\nenforce_projects: false\n",
    )
    with pytest.raises(ConfigError, match="exactly one non-empty 'projects'"):
        load_config(main)


def test_main_file_not_swallowed_by_its_own_glob(tmp_path):
    main = write(
        tmp_path,
        "artiform.yml",
        "config_version: 1\ninclude_projects: '*.yml'\n",
    )
    write(tmp_path, "team-x.yml", "projects:\n  team-x: {}\n")
    config = load_config(main)
    assert set(config.projects) == {"team-x"}


def test_include_projects_rejected_outside_file_loading():
    with pytest.raises(ConfigError, match="only supported when loading"):
        parse_config({"config_version": 1, "include_projects": "x/*.yml", "projects": {}})


def test_env_vars_substituted_in_include_patterns(tmp_path, monkeypatch):
    monkeypatch.setenv("TEAMS_DIR", "teams")
    main = write(
        tmp_path,
        "artiform.yml",
        "config_version: 1\ninclude_projects: ${TEAMS_DIR}/*.yml\n",
    )
    write(tmp_path, "teams/team-x.yml", "projects:\n  team-x: {}\n")
    assert set(load_config(main).projects) == {"team-x"}


def test_included_projects_ordered_before_main_file_projects(tmp_path):
    # A platform project in the main file may share repos with team projects;
    # the teams must be processed (and thus created) first.
    main = write(tmp_path, "artiform.yml", MAIN + "projects:\n  shared: {}\n")
    write(tmp_path, "projects/team-x.yml", "projects:\n  team-x: {}\n")
    config = load_config(main)
    assert list(config.projects) == ["team-x", "shared"]
