from plk_memory.settings import Settings


def make(**kw) -> Settings:
    base = dict(tokens={"t1": "claude-code"}, admin_token="adm", _env_file=None)
    base.update(kw)
    return Settings(**base)


def test_group_single_mode_folds_namespaces():
    s = make(group_mode="single")
    assert s.group_for("plk.domain.tax") == "plk-main"
    assert s.group_for("plk.shared") == "plk-main"
    assert s.group_for("plk.quarantine") == "plk-quarantine"


def test_group_per_namespace_mode():
    s = make(group_mode="per-namespace")
    assert s.group_for("plk.domain.tax") == "plk-domain-tax"
    assert s.group_for("plk.quarantine") == "plk-quarantine"


def test_all_groups_covers_both_modes():
    assert set(make(group_mode="single").all_groups()) == {"plk-main", "plk-quarantine"}
    per = make(group_mode="per-namespace").all_groups()
    assert "plk-domain-tax" in per and "plk-shared" in per and "plk-quarantine" in per


def test_path_for_namespace():
    s = make()
    assert s.path_for_namespace("plk.domain.tax") == "knowledge/domains/tax"
    assert s.path_for_namespace("plk.quarantine") == "knowledge/quarantine"
    assert s.path_for_namespace("plk.shared") == "knowledge/shared"


def test_knowledge_dir_derived_from_repo_path(tmp_path):
    s = make(data_repo_path=tmp_path / "repo")
    assert s.knowledge_dir == tmp_path / "repo" / "knowledge"


def test_domains_are_configurable_and_drive_groups():
    s = make(group_mode="per-namespace", domains=["tax", "dev"])
    groups = s.all_groups()
    assert "plk-domain-tax" in groups and "plk-domain-dev" in groups
    assert "plk-domain-legal" not in groups


def test_git_identity_defaults_and_override():
    assert make().git_author_name == "plk-memory"
    s = make(git_author_email="x@y.co")
    assert s.git_author_email == "x@y.co"


def test_repo_slug_from_ssh_and_https_urls():
    assert make(data_repo_url="git@github.com:cutsome/agent-organization.git").repo_slug == "cutsome/agent-organization"
    assert make(data_repo_url="https://github.com/cutsome/agent-organization.git").repo_slug == "cutsome/agent-organization"
