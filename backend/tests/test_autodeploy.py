"""Unattended deployment decisions, against fakes of GitHub and the controller.

deploy/autodeploy.py runs on the VPS as root and switches the live release, so
every refusal here is a guard against an outage: installing onto a busy or
unhealthy server, moving backwards, undoing an operator's rollback, applying a
schema change nobody watched. The real download, install and activation path
runs under systemd in the Ubuntu CI smoke (deploy/smoke.py).
"""

from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest

OLD = "a" * 40
NEW = "b" * 40
THURSDAY_10AM_NEW_YORK = datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc)
THURSDAY_5PM_NEW_YORK = datetime(2026, 9, 24, 21, 0, tzinfo=timezone.utc)
SATURDAY_10AM_NEW_YORK = datetime(2026, 9, 26, 14, 0, tzinfo=timezone.utc)


DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


def load():
    path = DEPLOY / "autodeploy.py"
    spec = importlib.util.spec_from_file_location("deployment_autodeploy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_release(root, name, commit, revisions=("001_initial.py",)):
    release = root / "releases" / name
    versions = release / "backend/alembic/versions"
    versions.mkdir(parents=True)
    for revision in revisions:
        (versions / revision).write_text("")
    (release / "release.json").write_text(json.dumps({"release_id": name, "commit": commit}))
    return release


def published(commit, release_id, published_at="2026-09-24T20:00:00Z", **overrides):
    names = ["SHA256SUMS", "tradejournal-deploy.py", f"{release_id}.tar.gz"]
    release = {
        "tag_name": f"build-{commit[:12]}",
        "draft": False,
        "published_at": published_at,
        "target_commitish": commit,
        "body": "Refresh signals while visible\n\nCommit passed CI.",
        "assets": [{"name": name, "browser_download_url": f"https://downloads.test/{name}"} for name in names],
    }
    release.update(overrides)
    return release


class Server:
    """A fake of everything deploy() reaches: GitHub, the controller, the API."""

    def __init__(self, autodeploy, root, monkeypatch):
        self.autodeploy = autodeploy
        self.root = root
        self.releases = [published(NEW, "new")]
        self.relation = "ahead"
        self.labels = []
        self.busy = False
        self.healthy = True
        self.fail = None
        self.calls = []
        self.notes = []
        monkeypatch.setattr(autodeploy, "github", self.github)
        monkeypatch.setattr(autodeploy, "download", self.download)
        monkeypatch.setattr(autodeploy, "install_controller", lambda source: self.calls.append(("install-controller",)))
        monkeypatch.setattr(autodeploy, "controller", self.controller)
        monkeypatch.setattr(autodeploy, "job_running", lambda: self.busy)
        monkeypatch.setattr(autodeploy, "api_healthy", lambda: self.healthy)
        monkeypatch.setattr(autodeploy, "backup", lambda current: self.calls.append(("backup",)))
        monkeypatch.setattr(autodeploy, "notify", lambda settings, title, message, **_: self.notes.append((title, message)))

    def github(self, settings, path, *, missing=None):
        self.calls.append(("github", path.split("?")[0]))
        if path.startswith("/releases"):
            return self.releases
        if path.startswith("/compare/"):
            return {"status": self.relation}
        if path.endswith("/pulls"):
            return [{"labels": [{"name": label} for label in self.labels]}]
        raise AssertionError(path)

    def download(self, build, directory):
        self.calls.append(("download", build.release_id))
        return directory / f"{build.release_id}.tar.gz", directory / "tradejournal-deploy.py", "f" * 64

    def controller(self, *args):
        self.calls.append(tuple(str(arg) for arg in args))
        if args[0] == self.fail:
            raise self.autodeploy.Failed(f"tradejournal-deploy {args[0]} failed")
        if args[0] == "install":
            make_release(self.root, "new", NEW, getattr(self, "new_revisions", ("001_initial.py",)))
        if args[0] == "activate":
            (self.root / "current").unlink()
            (self.root / "current").symlink_to(self.root / "releases" / args[1])
        return ""

    def steps(self):
        return [call for call in self.calls if call[0] != "github"]


@pytest.fixture
def autodeploy(tmp_path, monkeypatch):
    # It imports its phone-notification sender from deploy/alerts.py.
    monkeypatch.syspath_prepend(str(DEPLOY))
    module = load()
    monkeypatch.setattr(module, "ROOT", tmp_path / "opt")
    monkeypatch.setattr(module, "STATE", tmp_path / "state")
    old = make_release(module.ROOT, "old", OLD)
    (module.ROOT / "current").symlink_to(old)
    return module


@pytest.fixture
def server(autodeploy, monkeypatch):
    return Server(autodeploy, autodeploy.ROOT, monkeypatch)


def settings(autodeploy, hold="09:25-16:15"):
    return autodeploy.Settings(
        enabled=True,
        repository="owner/repo",
        confirm_database="127.0.0.1:5432/tradejournal",
        hold=autodeploy.parse_hold(hold),
        keep=3,
        api_url="https://api.github.test",
        ntfy={"NTFY_URL": "https://ntfy.test/topic"},
    )


def test_deploys_the_newest_verified_build_through_the_controller(autodeploy, server):
    result = autodeploy.deploy(settings(autodeploy), now=THURSDAY_5PM_NEW_YORK)
    assert result == "Deployed new"
    steps = server.steps()
    assert [step[0] for step in steps] == ["download", "install-controller", "install", "activate", "prune"]
    assert steps[2][1].endswith("/new.tar.gz") and steps[2][2:] == ("--sha256", "f" * 64)
    assert steps[3] == ("activate", "new", "--confirm-database", "127.0.0.1:5432/tradejournal")
    assert steps[4] == ("prune", "--keep", "3")
    assert (autodeploy.ROOT / "current").resolve().name == "new"
    assert server.notes == [("TradeJournal updated", "Refresh signals while visible\nNow running bbbbbbbbbbbb.")]
    state = json.loads((autodeploy.STATE / "state.json").read_text())
    assert (state["outcome"], state["deployed"]) == ("deployed", NEW)


def test_up_to_date_server_touches_nothing(autodeploy, server):
    server.releases = [published(OLD, "old")]
    assert autodeploy.deploy(settings(autodeploy), now=THURSDAY_5PM_NEW_YORK) == "Up to date with aaaaaaaaaaaa"
    assert server.steps() == []


def test_newest_build_skips_drafts_foreign_tags_and_incomplete_uploads(autodeploy):
    newest = published(NEW, "new", "2026-09-24T20:00:00Z")
    releases = [
        published(OLD, "old", "2026-09-23T20:00:00Z"),
        newest,
        published("c" * 40, "draft", "2026-09-25T20:00:00Z", draft=True),
        published("d" * 40, "tagged", "2026-09-25T20:00:00Z", tag_name="v1.0.0"),
        published("e" * 40, "partial", "2026-09-25T20:00:00Z", assets=newest["assets"][:2]),
        published("f" * 40, "branch", "2026-09-25T20:00:00Z", target_commitish="main"),
    ]
    build = autodeploy.newest_build(releases)
    assert (build.commit, build.release_id, build.title) == (NEW, "new", "Refresh signals while visible")
    assert autodeploy.newest_build([]) is None


@pytest.mark.parametrize(
    ("now", "held"),
    [
        (datetime(2026, 9, 24, 13, 24, tzinfo=timezone.utc), False),  # 09:24 New York
        (datetime(2026, 9, 24, 13, 25, tzinfo=timezone.utc), True),  # 09:25
        (THURSDAY_10AM_NEW_YORK, True),
        (datetime(2026, 9, 24, 20, 14, tzinfo=timezone.utc), True),  # 16:14
        (datetime(2026, 9, 24, 20, 15, tzinfo=timezone.utc), False),  # 16:15
        (SATURDAY_10AM_NEW_YORK, False),
        (datetime(2026, 12, 3, 15, 0, tzinfo=timezone.utc), True),  # 10:00 EST, no daylight saving
    ],
)
def test_market_hours_window_is_new_york_weekday_time(autodeploy, now, held):
    assert autodeploy.in_hold(now, autodeploy.parse_hold(None)) is held


def test_hold_window_setting(autodeploy):
    assert autodeploy.parse_hold("off") is None
    assert autodeploy.in_hold(THURSDAY_10AM_NEW_YORK, None) is False
    with pytest.raises(ValueError):
        autodeploy.parse_hold("16:15-09:25")


def test_market_hours_hold_the_build_unless_its_pull_request_says_deploy_now(autodeploy, server):
    assert autodeploy.deploy(settings(autodeploy), now=THURSDAY_10AM_NEW_YORK) == "Holding bbbbbbbbbbbb until the market closes"
    assert server.steps() == []
    assert server.notes == []

    server.labels = ["deploy-now"]
    assert autodeploy.deploy(settings(autodeploy), now=THURSDAY_10AM_NEW_YORK) == "Deployed new"


def test_run_now_ignores_the_hold(autodeploy, server):
    assert autodeploy.deploy(settings(autodeploy), now=THURSDAY_10AM_NEW_YORK, ignore_hold=True) == "Deployed new"


@pytest.mark.parametrize("relation", ["behind", "identical"])
def test_never_moves_the_server_backwards(autodeploy, server, relation):
    server.relation = relation
    assert "already runs" in autodeploy.deploy(settings(autodeploy), now=THURSDAY_5PM_NEW_YORK)
    assert server.steps() == []


def test_a_hand_deployed_branch_build_is_not_replaced(autodeploy, server):
    # "unknown" is what a commit GitHub has never seen compares as.
    for relation in ("diverged", "unknown"):
        server.relation = relation
        assert "not an ancestor" in autodeploy.deploy(settings(autodeploy), now=THURSDAY_5PM_NEW_YORK)
    assert server.steps() == []
    assert [title for title, _ in server.notes] == ["TradeJournal update waiting"]


def test_waits_while_a_job_runs_or_the_api_is_down(autodeploy, server):
    server.busy = True
    with pytest.raises(autodeploy.Waiting, match="running"):
        autodeploy.deploy(settings(autodeploy), now=THURSDAY_5PM_NEW_YORK)
    assert server.steps() == []


def test_api_that_does_not_answer_counts_as_not_ready(autodeploy, monkeypatch):
    def refused(*_args, **_kwargs):
        raise autodeploy.URLError("connection refused")

    monkeypatch.setattr(autodeploy, "urlopen", refused)
    with pytest.raises(autodeploy.Waiting, match="not answering"):
        autodeploy.job_running()
    assert autodeploy.api_healthy() is False


def test_schema_change_is_installed_but_waits_for_a_person(autodeploy, server):
    server.new_revisions = ("001_initial.py", "002_add_column.py")
    for _ in range(2):
        assert autodeploy.deploy(settings(autodeploy), now=THURSDAY_5PM_NEW_YORK) == "Holding bbbbbbbbbbbb: it changes the database schema"
    # Downloaded and installed once; never migrated or activated.
    assert [step[0] for step in server.steps()] == ["download", "install-controller", "install"]
    assert [title for title, _ in server.notes] == ["TradeJournal update waiting"]


def test_allow_migration_backs_up_before_migrating(autodeploy, server):
    server.new_revisions = ("001_initial.py", "002_add_column.py")
    autodeploy.deploy(settings(autodeploy), now=THURSDAY_5PM_NEW_YORK, allow_migration=True)
    assert [step[0] for step in server.steps()] == ["download", "install-controller", "install", "backup", "migrate", "activate", "prune"]


@pytest.mark.parametrize(("healthy", "title"), [(True, "TradeJournal update failed"), (False, "TradeJournal is DOWN")])
def test_failed_migration_says_whether_the_app_is_still_up(autodeploy, server, healthy, title):
    server.new_revisions = ("001_initial.py", "002_add_column.py")
    server.fail = "migrate"
    server.healthy = healthy
    with pytest.raises(autodeploy.Failed):
        autodeploy.deploy(settings(autodeploy), now=THURSDAY_5PM_NEW_YORK, allow_migration=True)
    assert "activate" not in [step[0] for step in server.steps()]
    assert [note_title for note_title, _ in server.notes] == [title]


def test_failed_activation_is_reported_once_and_not_retried(autodeploy, server):
    server.fail = "activate"
    with pytest.raises(autodeploy.Failed):
        autodeploy.deploy(settings(autodeploy), now=THURSDAY_5PM_NEW_YORK)
    assert [title for title, _ in server.notes] == ["TradeJournal update failed"]

    server.calls.clear()
    assert "Not retrying" in autodeploy.deploy(settings(autodeploy), now=THURSDAY_5PM_NEW_YORK)
    assert server.steps() == []
    assert len(server.notes) == 1


def test_failed_activation_that_leaves_the_api_down_is_urgent(autodeploy, server):
    server.fail = "activate"
    server.healthy = False
    with pytest.raises(autodeploy.Failed):
        autodeploy.deploy(settings(autodeploy), now=THURSDAY_5PM_NEW_YORK)
    assert [title for title, _ in server.notes] == ["TradeJournal is DOWN"]


def test_failed_install_is_reported_and_not_retried(autodeploy, server):
    server.fail = "install"
    with pytest.raises(autodeploy.Failed):
        autodeploy.deploy(settings(autodeploy), now=THURSDAY_5PM_NEW_YORK)
    assert "Not retrying" in autodeploy.deploy(settings(autodeploy), now=THURSDAY_5PM_NEW_YORK)
    assert [title for title, _ in server.notes] == ["TradeJournal update failed"]


def test_an_operator_rollback_is_not_undone(autodeploy, server):
    autodeploy.deploy(settings(autodeploy), now=THURSDAY_5PM_NEW_YORK)
    # The operator rolls back to the old release; the same build stays newest.
    (autodeploy.ROOT / "current").unlink()
    (autodeploy.ROOT / "current").symlink_to(autodeploy.ROOT / "releases/old")
    server.calls.clear()
    for _ in range(2):
        assert "rolled it back" in autodeploy.deploy(settings(autodeploy), now=THURSDAY_5PM_NEW_YORK)
    assert server.steps() == []
    assert [title for title, _ in server.notes] == ["TradeJournal updated", "TradeJournal update paused"]


def test_a_rollback_from_a_hand_deployed_build_is_not_undone(autodeploy, server):
    # The controller's rollback leaves current on the old release and previous
    # on the one it left; this deployer never ran.
    make_release(autodeploy.ROOT, "new", NEW)
    (autodeploy.ROOT / "previous").symlink_to(autodeploy.ROOT / "releases/new")
    assert "rolled it back" in autodeploy.deploy(settings(autodeploy), now=THURSDAY_5PM_NEW_YORK)
    assert server.steps() == []


def test_controller_lock_contention_means_try_later(autodeploy, tmp_path, monkeypatch):
    fake = tmp_path / "tradejournal-deploy"
    fake.write_text("#!/bin/sh\necho 'Another deployment operation is running' >&2\nexit 75\n")
    fake.chmod(0o755)
    monkeypatch.setattr(autodeploy, "CONTROLLER", fake)
    with pytest.raises(autodeploy.Waiting):
        autodeploy.controller("activate", "new")
    fake.write_text("#!/bin/sh\necho 'Deployment health checks did not pass' >&2\nexit 1\n")
    with pytest.raises(autodeploy.Failed, match="health checks"):
        autodeploy.controller("activate", "new")


def test_download_accepts_only_files_matching_the_published_checksums(autodeploy, tmp_path, monkeypatch):
    archive, controller = b"release archive", b"controller"
    files = {"new.tar.gz": archive, "tradejournal-deploy.py": controller}
    sums = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in files.items())
    served = {"SHA256SUMS": sums.encode(), **files}
    monkeypatch.setattr(autodeploy, "fetch", lambda url, **_: io.BytesIO(served[url.rsplit("/", 1)[1]]))
    build = autodeploy.newest_build([published(NEW, "new")])

    path, source, digest = autodeploy.download(build, tmp_path)
    assert (path.read_bytes(), source.read_bytes()) == (archive, controller)
    assert digest == hashlib.sha256(archive).hexdigest()

    served["new.tar.gz"] = b"tampered archive"
    with pytest.raises(autodeploy.Failed, match="does not match"):
        autodeploy.download(build, tmp_path)
    served["SHA256SUMS"] = sums.splitlines()[1].encode()
    with pytest.raises(autodeploy.Failed, match="does not list"):
        autodeploy.download(build, tmp_path)


def test_settings_come_from_a_root_only_file(autodeploy, tmp_path, monkeypatch):
    monkeypatch.setattr(autodeploy, "ALERTS_CONFIG", tmp_path / "alerts.env")
    config = tmp_path / "autodeploy.env"
    assert autodeploy.load_settings(config) is None
    config.write_text("AUTODEPLOY_ENABLED=true\n")
    config.chmod(0o600)
    with pytest.raises(RuntimeError, match="root-owned"):
        autodeploy.load_settings(config)  # owned by the test user, not root

    monkeypatch.setattr(autodeploy, "_root_only", lambda path: None)
    with pytest.raises(RuntimeError, match="AUTODEPLOY_REPOSITORY"):
        autodeploy.load_settings(config)
    config.write_text(
        "AUTODEPLOY_ENABLED=true\nAUTODEPLOY_REPOSITORY=owner/repo\n"
        "AUTODEPLOY_CONFIRM_DATABASE=127.0.0.1:5432/tradejournal\nAUTODEPLOY_HOLD_WINDOW=off\nNTFY_URL=\n"
    )
    loaded = autodeploy.load_settings(config)
    assert (loaded.enabled, loaded.hold, loaded.keep, loaded.api_url, loaded.ntfy) == (True, None, 3, "https://api.github.com", {})

    # With no topic of its own it reports on the phone alerts' topic...
    (tmp_path / "alerts.env").write_text("NTFY_URL=https://ntfy.sh/alerts-topic\nNTFY_TOKEN=tk_secret\nALERT_APP_URL=https://server.ts.net\n")
    assert autodeploy.load_settings(config).ntfy == {
        "NTFY_URL": "https://ntfy.sh/alerts-topic", "NTFY_TOKEN": "tk_secret", "ALERT_APP_URL": "https://server.ts.net",
    }
    # ...and a topic of its own wins, without mixing in the alerts' token.
    config.write_text(config.read_text().replace("NTFY_URL=\n", "NTFY_URL=https://ntfy.sh/deploys\n"))
    assert autodeploy.load_settings(config).ntfy == {"NTFY_URL": "https://ntfy.sh/deploys"}


def test_notifications_use_the_alert_sender_and_never_break_a_deploy(autodeploy, monkeypatch):
    sent = []
    monkeypatch.setattr(autodeploy, "publish", lambda config, title, message, recovered: sent.append((config["NTFY_URL"], title, recovered)))
    autodeploy.notify(settings(autodeploy), "TradeJournal updated", "Now running", good_news=True)
    autodeploy.notify(settings(autodeploy), "TradeJournal update failed", "Rolled back")
    assert sent == [("https://ntfy.test/topic", "TradeJournal updated", True), ("https://ntfy.test/topic", "TradeJournal update failed", False)]

    def unreachable(*_args, **_kwargs):
        raise autodeploy.URLError("ntfy.sh unreachable")

    monkeypatch.setattr(autodeploy, "publish", unreachable)
    autodeploy.notify(settings(autodeploy), "TradeJournal updated", "Now running", good_news=True)
    no_topic = autodeploy.Settings(**{**settings(autodeploy).__dict__, "ntfy": {}})
    autodeploy.notify(no_topic, "TradeJournal updated", "Now running")  # no topic: silently nothing
