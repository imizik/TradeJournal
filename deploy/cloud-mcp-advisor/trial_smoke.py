"""Optional trial upgrade proof inside the existing disposable native smoke.

Never invoke this on a retained server: it generates fixture sessions and owns
temporary services. The operator uses advisor_trial_control, not this harness.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import advisor_mcp_control as old
import advisor_mcp_stage as staging
import advisor_trial_control as control
import advisor_trial_stage as trial

FIXTURE = Path("/opt/tradejournal-advisor-ci-owner-transition")
API = "tradejournal-advisor-ci-owner-api.service"
SESSION_PATH = "/api/access/me"
GENERIC_SESSION_PATH = "/api/backend/access/me"


def diagnosis(run, *, path, status=None, transport=None, detail=None):
    """Public status/categories only: never cookies, keys, env or raw logs."""
    allowed = {"Not found", "Authentication request rejected", "Backend unavailable", "Authentication required"}
    print(json.dumps({"native_owner_probe": {"path": path, "status": status, "transport": transport,
        "body_category": detail if isinstance(detail, str) and detail in allowed else "redacted"}}), flush=True)
    for unit in (API, trial.FRONTEND):
        state = run("systemctl", "show", unit, "--property=ActiveState", "--property=SubState",
            "--property=Result", "--property=MainPID", "--property=ExecMainStatus", check=False).stdout.decode()
        values = dict(line.split("=", 1) for line in state.splitlines() if "=" in line)
        print(json.dumps({"unit": unit, "public_state": {k: values.get(k) for k in
            ("ActiveState", "SubState", "Result", "MainPID", "ExecMainStatus")}}), flush=True)
        journal = run("journalctl", "-u", unit, "--no-pager", "-n", "30", "-o", "json", check=False).stdout.decode()
        categories = []
        for line in journal.splitlines():
            try:
                message = json.loads(line).get("MESSAGE", "")
            except (ValueError, TypeError):
                continue
            categories.extend(name for name in ("Traceback", "EACCES", "ENOENT", "ECONNREFUSED", "Permission denied",
                "Application startup failed", "Application startup complete", "address already in use", "Failed", "Ready in")
                if name in message)
        print(json.dumps({"unit": unit, "journal_categories": categories}), flush=True)


def exercise(archive, scratch, run, *, context, token, identity, keys, resource, proxy):
    if os.geteuid() != 0 or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("TJ_DISPOSABLE_RUNNER") != "1":
        raise ValueError("Owner transition proof requires explicitly disposable CI")
    import uuid

    import httpx
    from app.engine import advisor_shadow as service
    from cloud_mcp_advisor_common import fixture_acl
    from sqlmodel import Session, create_engine
    for path in (FIXTURE, control.ROOT, control.CONFIG, control.STATE, control.OWNER_ENV.parent,
            old.UNIT_DIR / trial.FRONTEND, old.UNIT_DIR / API, control.DROPIN.parent):
        if path.exists() or path.is_symlink():
            raise ValueError("Refuse pre-existing native owner transition resource")
    for unit in (trial.FRONTEND, API):
        if run("systemctl", "cat", unit, check=False).returncode == 0:
            raise ValueError("Refuse existing loaded owner transition service")
    # The earlier native reader proof owned this disposable account. Its units
    # are already removed; remove only that fixture identity before installing
    # the independently guarded retained-safe optional installer.
    run("userdel", trial.READER_ACCOUNT)
    if run("getent", "group", trial.READER_ACCOUNT, check=False).returncode == 0:
        run("groupdel", trial.READER_ACCOUNT)
    assert run("getent", "group", trial.READER_ACCOUNT, check=False).returncode != 0
    old.stop()
    FIXTURE.mkdir(mode=0o755)
    control.OWNER_ENV.parent.mkdir(mode=0o700)
    access_db = FIXTURE / "access.db"
    shutil.copyfile(old.STATE / "fixture.db", access_db)
    access_db.chmod(0o600)
    backend_source = old.ROOT / "backend"
    # Use the inventoried source, whose empty data directory already exists.
    # Importing app from the dependency wheel creates site-packages/data and
    # correctly trips the immutable-runtime guard, even with DATABASE_URL set.
    env = {"PATH": old.ADMIN_PATH, "PYTHONPATH": str(backend_source),
        "PYTHON_DOTENV_DISABLED": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "DATABASE_URL": "sqlite:///" + str(access_db), "TJ_ACCESS_ENABLED": "true", "TJ_ACCESS_SAMPLE_DATA": "true",
        "TJ_ACCESS_ALLOW_LOCAL_HTTP": "true", "TJ_OWNER_GATEWAY_KEY": "o" * 43, "TJ_ASSISTANT_GATEWAY_KEY": "a" * 43,
        "TJ_OWNER_ORIGIN": "http://127.0.0.1:18860", "TJ_ASSISTANT_ORIGIN": "http://127.0.0.1:18862"}
    seed = ('from sqlmodel import Session; from app.database import engine; from app.models import AccessPrincipal; '
        'from app.engine import access; '
        'db=Session(engine); p=AccessPrincipal(id="owner"); db.add(p); db.flush(); '
        'token,row=access.issue_session(db,p,"owner"); db.commit(); print(token)')
    python = old.ROOT / "backend/.venv/bin/python"
    # The generated fixture cookie stays in memory; no credential/log output.
    old.installed()
    cookie = run(python, "-B", "-c", seed, env=env, cwd=backend_source).stdout.decode().strip()
    old.installed()
    (FIXTURE / "fixture_api.py").write_text('''from fastapi import FastAPI
from app.routers.access import router
from app.access_middleware import AccessMiddleware
app=FastAPI()
app.include_router(router,prefix="/access")
app.add_middleware(AccessMiddleware,routes=app.router.routes)
''')
    for path, text in ((control.API_ENV, "\n".join(k + "=" + v for k, v in env.items()) + "\n"),
            (control.OWNER_ENV, "TJ_ACCESS_PROFILE=owner\nTJ_GATEWAY_KEY=" + "o" * 43 +
                "\nTJ_WEB_ORIGIN=http://127.0.0.1:18860\nTJ_ACCESS_ALLOW_LOCAL_HTTP=true\nNEXT_PUBLIC_API_URL=/api/backend\n")):
        path.write_text(text)
        path.chmod(0o600)
    (old.UNIT_DIR / API).write_text(f"[Service]\nType=exec\nEnvironmentFile={control.API_ENV}\nWorkingDirectory={FIXTURE}\nExecStart={python} -B -m uvicorn fixture_api:app --host 127.0.0.1 --port 18861 --no-access-log\n")
    before_unit = (f"[Unit]\nRequires={API}\nAfter={API}\n[Service]\nType=exec\nDynamicUser=yes\n"
        f"EnvironmentFile={control.OWNER_ENV}\nEnvironment=HOSTNAME=127.0.0.1 PORT=18860 API_INTERNAL_URL=http://127.0.0.1:18861 API_PROXY_TARGET=http://127.0.0.1:18861\n"
        "WorkingDirectory=/opt/tradejournal/current/frontend\nExecStart=/opt/tradejournal/current/bin/node /opt/tradejournal/current/frontend/server.js\n"
        "ProtectSystem=strict\nProtectHome=true\nNoNewPrivileges=true\n")
    (old.UNIT_DIR / trial.FRONTEND).write_text(before_unit)
    for unit in (API, trial.FRONTEND):
        (old.UNIT_DIR / unit).chmod(0o644)
    try:
        run("systemctl", "daemon-reload")
        run("systemctl", "start", API, trial.FRONTEND)
        client = httpx.Client(base_url="http://127.0.0.1:18860", trust_env=False, timeout=5)
        private_client = httpx.Client(base_url="http://127.0.0.1:18860", trust_env=False, timeout=5)
        bootstrap_access = None
        def authenticated():
            deadline = time.monotonic() + 20
            last_status, last_transport, last_detail = None, None, None
            while True:
                try:
                    response = client.get(SESSION_PATH, cookies={"tj_session": cookie})
                    last_status, last_transport = response.status_code, None
                    if response.status_code == 200:
                        return response.json()
                    try:
                        last_detail = response.json().get("detail")
                    except (ValueError, AttributeError):
                        last_detail = None
                    if response.status_code in (401, 403, 404):
                        diagnosis(run, path=SESSION_PATH, status=last_status, detail=last_detail)
                        raise AssertionError("Native owner session route refused fixture authentication")
                except httpx.TransportError as error:
                    last_transport = type(error).__name__
                if time.monotonic() >= deadline:
                    diagnosis(run, path=SESSION_PATH, status=last_status, transport=last_transport, detail=last_detail)
                    raise AssertionError("Native owner frontend did not become authenticated")
                time.sleep(.1)  # Bounded readiness, never assertion retry.
        before = authenticated()
        assert before["owner"] is True and before["identifier"] == "owner" and before["grants"] == {}
        old.installed()  # The separate API must not mutate the old runtime either.
        def access_boundaries():
            nonlocal bootstrap_access
            # The trusted PRIVATE owner entrance intentionally bootstraps its
            # owner session. Anonymous denial belongs to the API without that
            # gateway, not to a request already admitted to the private app.
            with httpx.Client(trust_env=False, timeout=5) as fresh:
                assert fresh.get("http://127.0.0.1:18861/access/me").status_code == 401
                wrong = fresh.get("http://127.0.0.1:18861/access/me", headers={"x-tj-gateway": "a" * 43},
                    cookies={"tj_session": cookie})
                assert wrong.status_code == 401  # Owner cookie is not assistant authority.
            # Reuse the separately bootstrapped cookie. Repeated fresh sessions
            # would legitimately prune the original cookie under the existing
            # owner-session cap, invalidating the identity-preservation probe.
            private = private_client.get(SESSION_PATH)
            assert private.status_code == 200
            assert private.json()["owner"] is True and private.json()["identifier"] == before["identifier"]
            assert private.json()["grants"] == before["grants"]
            if bootstrap_access is None:
                bootstrap_access = private.json()
            else:
                assert private.json() == bootstrap_access
        access_boundaries()
        assert client.get(GENERIC_SESSION_PATH, cookies={"tj_session": cookie}).status_code == 404
        dynamic = run("systemctl", "show", trial.FRONTEND, "--property=DynamicUser", "--value").stdout.decode().strip()
        assert dynamic == "yes"
        guards = {"old_record_sha256": staging.digest(old.RECORD), "frontend_unit_sha256": staging.digest(old.UNIT_DIR / trial.FRONTEND),
            "owner_env_sha256": staging.digest(control.OWNER_ENV), "api_env_sha256": staging.digest(control.API_ENV)}
        bundle = scratch / "trial-disabled"
        trial.prepare(bundle, archive=archive, archive_sha256=staging.digest(archive), wheels=scratch / "wheels", guards=guards)
        old_ledger = staging.digest(old.STATE / "fixture.db")
        runtime_override = Path("/run/systemd/system") / (staging.UNITS[1] + ".d")
        if runtime_override.exists():
            raise ValueError("Refuse existing native runtime override")
        runtime_override.mkdir()
        (runtime_override / "fixture.conf").write_text("[Service]\nEnvironment=UNREVIEWED_FIXTURE=true\n")
        try:
            run("systemctl", "daemon-reload")
            try:
                control.preflight(bundle, staging.digest(bundle / "manifest.json"))
            except ValueError as error:
                assert "effective systemd" in str(error)
            else:
                raise AssertionError("Runtime systemd override accepted before install")
            assert not control.ROOT.exists()
        finally:
            (runtime_override / "fixture.conf").unlink()
            runtime_override.rmdir()
            run("systemctl", "daemon-reload")
        interrupted_install(bundle, run)
        record = control.install(bundle, staging.digest(bundle / "manifest.json"))
        assert staging.digest(old.STATE / "fixture.db") == old_ledger
        assert all(run("systemctl", "is-active", "--quiet", name, check=False).returncode != 0 for name in control.UNITS)
        # Explicit disposable-only restart, absent from the retained installer.
        run("systemctl", "restart", trial.FRONTEND)
        assert authenticated() == before  # Same cookie, principal, CSRF, roles.
        access_boundaries()
        assert client.get(GENERIC_SESSION_PATH, cookies={"tj_session": cookie}).status_code == 404
        assert client.get("/api/advisor-owner", cookies={"tj_session": cookie}).status_code == 503
        pid = int(run("systemctl", "show", trial.FRONTEND, "--property=MainPID", "--value").stdout)
        observed = Path(f"/proc/{pid}").stat().st_uid
        assert observed == record["new_accounts"][trial.WEB_ACCOUNT]["uid"], f"Static frontend expected={record['new_accounts'][trial.WEB_ACCOUNT]['uid']} PID={pid} observed={observed}"
        advisor_config = json.loads((control.CONFIG / "advisor/config.json").read_text())
        advisor_config.update({k: identity[k] for k in ("issuer_url", "jwks_url", "resource_url", "client_id")})
        advisor_config["enabled"] = True
        advisor_config["profiles"][0].update(enabled=True, subject=identity["profiles"][0]["subject"])
        reader_config = json.loads((control.CONFIG / "owner/config.json").read_text())
        reader_config.update(enabled=True, binding=advisor_config["profiles"][0])
        for path, value in ((control.CONFIG / "advisor/config.json", advisor_config),
                (control.CONFIG / "owner/config.json", reader_config), (control.CONFIG / "advisor/public-keys.json", keys)):
            path.write_text(json.dumps(value))  # Existing root-owned readonly modes retained.
        reader_uid = record["new_accounts"][trial.READER_ACCOUNT]["uid"]
        os.setxattr(control.STATE, "system.posix_acl_access", fixture_acl(reader_uid, directory=True))
        os.setxattr(control.STATE / "fixture.db", "system.posix_acl_access", fixture_acl(reader_uid))
        engine = create_engine("sqlite:///" + str(control.STATE / "fixture.db"))
        assignment = uuid.UUID(advisor_config["profiles"][0]["assignment_id"])
        with Session(engine) as db:
            service.set_enabled(db, assignment, True)
        owner_env = control.CONFIG / "frontend.env"
        owner_env.write_text(owner_env.read_text().replace("TJ_ADVISOR_OWNER_ENABLED=false", "TJ_ADVISOR_OWNER_ENABLED=true"))
        caddyfile = scratch / "Caddyfile"
        caddyfile.write_text(caddyfile.read_text().replace("/run/tradejournal-advisor/mcp.sock", trial.RUN + "/mcp.sock"))
        run("caddy", "validate", "--config", caddyfile, "--adapter", "caddyfile")
        run("systemctl", "restart", proxy)
        run("systemctl", "start", *[u for u in control.UNITS if u.endswith(".socket")])
        run("systemctl", "start", *[u for u in control.UNITS if u.endswith(".service")])
        run("systemctl", "restart", trial.FRONTEND)
        assert authenticated() == before
        with httpx.Client(verify=context, trust_env=False, timeout=10) as cloud:
            def rpc(name, arguments=None):
                response = cloud.post(resource, headers={"Authorization": "Bearer " + token(), "Accept": "application/json"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}})
                assert response.status_code == 200
                return response.json()["result"]["structuredContent"]
            metadata = cloud.get(resource.replace("/advisor/mcp", "/.well-known/oauth-protected-resource/advisor/mcp"))
            assert metadata.status_code == 200 and metadata.json()["resource"] == resource
            assert cloud.post(resource, json={}).status_code == 401
            catalog = cloud.post(resource, headers={"Authorization": "Bearer " + token(), "Accept": "application/json"},
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            assert catalog.status_code == 200
            tools = catalog.json()["result"]["tools"]
            assert sorted(t["name"] for t in tools) == ["get_advisor_request", "get_profile", "save_advisor_answer"]
            assert len(tools) == 3
            read = rpc("get_advisor_request")
            opp = read["request"]["packet"]["opportunities"][0]
            fact = opp["price_facts"][0]
            answer = {k: "Invented missing-input evidence; wait." for k in ("summary", "interpretation", "risks", "conditions", "gaps")}
            answer["references"] = [{"opportunity_id": opp["opportunity_id"], "fact_name": fact["name"]}]
            body = {"packet_sha256": read["request"]["packet_sha256"], "request_sha256": read["request"]["request_sha256"], "answer": answer}
            receipt = rpc("save_advisor_answer", body)["receipt"]
            assert rpc("get_advisor_request")["receipt"] == receipt and rpc("save_advisor_answer", body)["receipt"] == receipt
            for _ in range(2):
                owner = client.get("/api/advisor-owner", cookies={"tj_session": cookie})
                assert owner.status_code == 200 and owner.json()["receipt"] == receipt and owner.json()["request"] == read["request"]
            bootstrapped = private_client.get("/api/advisor-owner")
            assert bootstrapped.status_code == 200 and bootstrapped.json()["receipt"] == receipt
            with httpx.Client(transport=httpx.HTTPTransport(uds=trial.OWNER_RUN + "/owner.sock"), timeout=5) as wrong_peer:
                assert wrong_peer.get("http://owner/owner/advisor").status_code == 403
            access_boundaries()
            run("systemctl", "restart", *[u for u in control.UNITS if u.endswith(".service")])
            assert rpc("get_advisor_request")["receipt"] == receipt
            assert client.get("/api/advisor-owner", cookies={"tj_session": cookie}).json()["receipt"] == receipt
            managed_questions(run, advisor_config, record, rpc, answer)
            assert client.get("/api/advisor-owner", cookies={"tj_session": cookie}).json()["receipt"] == receipt
        engine.dispose()
        runtime_override.mkdir()
        (runtime_override / "fixture.conf").write_text("[Service]\nEnvironment=UNREVIEWED_FIXTURE=true\n")
        try:
            run("systemctl", "daemon-reload")
            try:
                control.installed()
            except ValueError as error:
                assert "effective systemd" in str(error)
            else:
                raise AssertionError("Runtime systemd override accepted after install")
        finally:
            (runtime_override / "fixture.conf").unlink()
            runtime_override.rmdir()
            run("systemctl", "daemon-reload")
        dependency = control.ROOT / "frontend/server.js"
        original = dependency.read_bytes()
        dependency.write_bytes(original + b"\n// controlled drift\n")
        try:
            control.installed()
        except ValueError:
            pass
        else:
            raise AssertionError("Native executable drift accepted")
        dependency.write_bytes(original)
        control.installed()
        new_ledger = staging.digest(control.STATE / "fixture.db")
        control.rollback()
        # Rollback restores the unit definition; the operator must separately
        # restart this one approved frontend to restore its running identity.
        run("systemctl", "restart", trial.FRONTEND)
        assert authenticated() == before
        assert run("systemctl", "show", trial.FRONTEND, "--property=DynamicUser", "--value").stdout.decode().strip() == "yes"
        assert (old.UNIT_DIR / trial.FRONTEND).read_text() == before_unit
        assert staging.digest(old.STATE / "fixture.db") == old_ledger and staging.digest(control.STATE / "fixture.db") == new_ledger
        old.installed()
        client.close()
        private_client.close()
        print("Trial upgrade native passed: disabled side-by-side install, old ledger/runtime/auth preservation, existing private owner DynamicUser to dedicated UID with same session/roles/CSRF and existing bootstrap behavior, direct API anonymous/wrong-audience and reader wrong-peer denial, v2 HTTPS metadata/read/cited save/uncertain recovery/exact retries, real owner BFF equality/reopen/restart, dormant denial, executable drift refusal, six-unit stop, receipt-preserving rollback and explicit frontend identity restoration")
    finally:
        run("systemctl", "stop", trial.FRONTEND, API, *control.UNITS, check=False)
        for unit in (trial.FRONTEND, API, *trial.OWNER_UNITS):
            (old.UNIT_DIR / unit).unlink(missing_ok=True)
        shutil.rmtree(control.DROPIN.parent, ignore_errors=True)
        run("systemctl", "daemon-reload", check=False)
        for path in (FIXTURE, control.ROOT, control.CONFIG, control.STATE, control.OWNER_ENV.parent, Path(trial.RUN), Path(trial.OWNER_RUN)):
            shutil.rmtree(path, ignore_errors=True)
        for account in (trial.READER_ACCOUNT, trial.WEB_ACCOUNT):
            run("userdel", account, check=False)
            run("groupdel", account, check=False)


def interrupted_install(bundle, run):
    """Actual root installer, actual prefix-write failure; disposable cleanup."""
    before = {name: (old.UNIT_DIR / name).read_bytes() for name in staging.UNITS}
    preserved = {path: staging.digest(path) for path in (old.RECORD, old.STATE / "fixture.db",
        old.ROOT / "recovery/request.json", control.OWNER_ENV, control.API_ENV)}
    copy = control.shutil.copyfile
    fired = False
    def interrupted(source, target, **kwargs):
        nonlocal fired
        target = Path(target)
        if not fired and target.parent == old.UNIT_DIR and target.name.startswith("." + staging.UNITS[1] + "."):
            target.write_bytes(Path(source).read_bytes()[:12])
            fired = True
            raise OSError("Disposable native interrupted unit-prefix copy")
        return copy(source, target, **kwargs)
    control.shutil.copyfile = interrupted
    try:
        try:
            control.install(bundle, staging.digest(bundle / "manifest.json"))
        except OSError as error:
            assert "interrupted unit-prefix" in str(error)
        else:
            raise AssertionError("Native interrupted install did not fail")
    finally:
        control.shutil.copyfile = copy
    assert fired and all((old.UNIT_DIR / name).read_bytes() == data for name, data in before.items())
    assert not control.DROPIN.exists() and not control.DROPIN.parent.exists()
    assert all(staging.digest(path) == digest for path, digest in preserved.items())
    assert (control.STATE / "fixture.db").is_file() and (control.ROOT / "recovery/request.json").is_file()
    assert json.loads((control.CONFIG / "advisor/config.json").read_text())["enabled"] is False
    assert json.loads((control.CONFIG / "owner/config.json").read_text())["enabled"] is False
    assert all(run("systemctl", "is-active", "--quiet", unit, check=False).returncode != 0 for unit in control.UNITS)
    old.installed()
    try:
        control.install(bundle, staging.digest(bundle / "manifest.json"))
    except ValueError as error:
        assert "collision" in str(error)
    else:
        raise AssertionError("Native partial install permitted overwrite/retry")
    print("Trial interrupted install native passed: actual prefix-write failure, exact old units/runtime/auth/ledger/recovery preserved, no frontend drop-in, new disabled resources retained and overwrite/retry refused")
    # Explicit disposal of only resources this fixture just created. Retained
    # installer deliberately does NOT perform this destructive cleanup.
    for path in (control.ROOT, control.CONFIG, control.STATE):
        shutil.rmtree(path)
    for account in (trial.READER_ACCOUNT, trial.WEB_ACCOUNT):
        run("userdel", account)
        if run("getent", "group", account, check=False).returncode == 0:
            run("groupdel", account)


def managed_questions(run, original_config, record, rpc, answer):
    """Disposable native UID proof; never an activation/install procedure."""
    import struct
    import uuid
    config_path = control.CONFIG / "advisor/config.json"
    original_bytes = config_path.read_bytes()
    web_uid = record["new_accounts"][trial.WEB_ACCOUNT]["uid"]
    socket_path = Path(trial.RUN) / "backend.sock"
    config_path.write_text(json.dumps({**original_config, "assignment_management": True, "owner_peer_uid": web_uid}))
    services = [u for u in control.UNITS if u.endswith(".service") and "owner" not in u]
    run("systemctl", "restart", *services)
    # Preserve existing owner/group rw, adding only this named frontend UID.
    undefined = 0xFFFFFFFF
    entries = ((1, 6, undefined), (2, 6, web_uid), (4, 6, undefined), (16, 6, undefined), (32, 0, undefined))
    acl = struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *entry) for entry in entries)
    os.setxattr(socket_path, "system.posix_acl_access", acl)
    script = """import http.client,json,socket,sys
class Unix(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect(sys.argv[1])
c=Unix('fixture'); c.request(sys.argv[2],'/owner/advisor/assignments',body=sys.argv[3],headers={'Content-Type':'application/json'})
r=c.getresponse(); print(json.dumps({'status':r.status,'body':json.loads(r.read())}))
"""
    def owner(method="GET", body=None, account=trial.WEB_ACCOUNT):
        result = run("runuser", "-u", account, "--", "/usr/bin/python3", "-I", "-c", script,
            socket_path, method, "" if body is None else json.dumps(body))
        return json.loads(result.stdout)
    try:
        assert owner(account=old.ACCOUNT)["status"] == 403
        assert owner(account=old.BACKEND_ACCOUNT)["status"] == 403
        first = owner("POST", {"operation_id": str(uuid.uuid4()), "question": "First invented question?", "user_plan": "Wait", "invented_only": True})
        assert first["status"] == 200
        request = first["body"]["record"]["request"]
        assert rpc("get_advisor_request")["request"] == request
        body = {"packet_sha256": request["packet_sha256"], "request_sha256": request["request_sha256"], "answer": answer}
        saved = rpc("save_advisor_answer", body)["receipt"]
        # Owner GET list and create retry recover exact bytes, without selectors in MCP.
        second = owner("POST", {"operation_id": str(uuid.uuid4()), "question": "Second invented question?", "user_plan": "Wait", "invented_only": True})
        assert second["status"] == 200
        next_request = second["body"]["record"]["request"]
        assert next_request["assignment_id"] != request["assignment_id"]
        assert rpc("get_advisor_request")["request"] == next_request
        revoked = owner("POST", {"revoke": request["assignment_id"]})
        assert revoked["status"] == 200 and revoked["body"]["record"]["receipt"] == saved
        assert owner("POST", {"revoke": next_request["assignment_id"]})["status"] == 200
        run("systemctl", "restart", *services)
        assert owner()["status"] == 200
        assert owner("POST", {"revoke": request["assignment_id"]})["body"]["record"]["receipt"] == saved
        assert owner(account=old.ACCOUNT)["status"] == 403
        print("Managed advisor native passed: distinct frontend/adapter/backend UIDs, named socket grant, two immutable assignments without OAuth edits/restart, cited receipt preserved across revoke and process replacement")
    finally:
        os.removexattr(socket_path, "system.posix_acl_access")
        socket_path.chmod(0o660)
        config_path.write_bytes(original_bytes)
        run("systemctl", "restart", *services)
