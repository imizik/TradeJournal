"""Optional trial upgrade proof inside the existing disposable native smoke.

Never invoke this on a retained server: it generates fixture sessions and owns
temporary services. The operator uses advisor_trial_control, not this harness.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import time

import advisor_mcp_control as old
import advisor_mcp_stage as staging
import advisor_trial_control as control
import advisor_trial_stage as trial

FIXTURE = Path("/opt/tradejournal-advisor-ci-owner-transition")
API = "tradejournal-advisor-ci-owner-api.service"


def exercise(archive, scratch, run, *, context, token, identity, keys, resource, proxy):
    if os.geteuid() != 0 or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("TJ_DISPOSABLE_RUNNER") != "1":
        raise ValueError("Owner transition proof requires explicitly disposable CI")
    import httpx
    import uuid
    from sqlmodel import Session, create_engine
    from app.engine import advisor_shadow as service
    from cloud_mcp_advisor_common import fixture_acl
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
    run("groupdel", trial.READER_ACCOUNT)
    old.stop()
    FIXTURE.mkdir(mode=0o755)
    control.OWNER_ENV.parent.mkdir(mode=0o700)
    access_db = FIXTURE / "access.db"
    shutil.copyfile(old.STATE / "fixture.db", access_db)
    access_db.chmod(0o600)
    env = {"PATH": old.ADMIN_PATH, "PYTHON_DOTENV_DISABLED": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "DATABASE_URL": "sqlite:///" + str(access_db), "TJ_ACCESS_ENABLED": "true", "TJ_ACCESS_SAMPLE_DATA": "true",
        "TJ_ACCESS_ALLOW_LOCAL_HTTP": "true", "TJ_OWNER_GATEWAY_KEY": "o" * 43, "TJ_ASSISTANT_GATEWAY_KEY": "a" * 43,
        "TJ_OWNER_ORIGIN": "http://127.0.0.1:18860", "TJ_ASSISTANT_ORIGIN": "http://127.0.0.1:18862"}
    seed = ('from sqlmodel import Session; from app.database import engine; from app.models import AccessPrincipal; '
        'from app.engine import access; '
        'db=Session(engine); p=AccessPrincipal(id="owner"); db.add(p); db.flush(); '
        'token,row=access.issue_session(db,p,"owner"); db.commit(); print(token)')
    python = old.ROOT / "backend/.venv/bin/python"
    # The generated fixture cookie stays in memory; no credential/log output.
    cookie = run(python, "-B", "-c", seed, env=env).stdout.decode().strip()
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
        def authenticated():
            deadline = time.monotonic() + 20
            while True:
                try:
                    response = client.get("/api/backend/access/me", cookies={"tj_session": cookie})
                    if response.status_code == 200:
                        return response.json()
                except httpx.TransportError:
                    pass
                if time.monotonic() >= deadline:
                    raise AssertionError("Native owner frontend did not become authenticated")
                time.sleep(.1)  # Bounded readiness, never assertion retry.
        before = authenticated()
        assert before["owner"] is True and before["identifier"] == "owner" and before["grants"] == {}
        assert client.get("/api/backend/access/me").status_code == 401
        dynamic = run("systemctl", "show", trial.FRONTEND, "--property=DynamicUser", "--value").stdout.decode().strip()
        assert dynamic == "yes"
        guards = {"old_record_sha256": staging.digest(old.RECORD), "frontend_unit_sha256": staging.digest(old.UNIT_DIR / trial.FRONTEND),
            "owner_env_sha256": staging.digest(control.OWNER_ENV), "api_env_sha256": staging.digest(control.API_ENV)}
        bundle = scratch / "trial-disabled"
        trial.prepare(bundle, archive=archive, archive_sha256=staging.digest(archive), wheels=scratch / "wheels", guards=guards)
        old_ledger = staging.digest(old.STATE / "fixture.db")
        record = control.install(bundle, staging.digest(bundle / "manifest.json"))
        assert staging.digest(old.STATE / "fixture.db") == old_ledger
        assert all(run("systemctl", "is-active", "--quiet", name, check=False).returncode != 0 for name in control.UNITS)
        # Explicit disposable-only restart, absent from the retained installer.
        run("systemctl", "restart", trial.FRONTEND)
        assert authenticated() == before  # Same cookie, principal, CSRF, roles.
        assert client.get("/api/backend/access/me").status_code == 401
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
            assert client.get("/api/advisor-owner").status_code == 401
            run("systemctl", "restart", *[u for u in control.UNITS if u.endswith(".service")])
            assert rpc("get_advisor_request")["receipt"] == receipt
            assert client.get("/api/advisor-owner", cookies={"tj_session": cookie}).json()["receipt"] == receipt
        engine.dispose()
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
        print("Trial upgrade native passed: disabled side-by-side install, old ledger/runtime/auth preservation, existing owner DynamicUser to dedicated UID with same session/roles/CSRF, v2 HTTPS metadata/read/cited save/uncertain recovery/exact retries, real owner BFF equality/reopen/restart, anonymous/dormant denial, executable drift refusal, six-unit stop, receipt-preserving rollback and explicit frontend identity restoration")
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
