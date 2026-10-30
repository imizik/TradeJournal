"""New company routes must refuse assistants before writing or dispatching."""
from sqlmodel import Session, select

from app.company_research_models import ResearchCompany
from app.routers import company_research
from tests.test_browser_access import boundary, signin  # noqa: F401


def test_company_owner_and_assistant_boundaries(boundary, monkeypatch):  # noqa: F811
    dispatched = []
    monkeypatch.setattr(company_research, "submit_job", lambda identifier: dispatched.append(identifier))
    created = boundary.owner.post("/company-research/companies", json={"symbol": "NVDA"})
    assert created.status_code == 200
    identifier = created.json()["id"]
    assert signin(boundary).status_code == 200
    for method, path, data in (("GET", "/companies", None), ("POST", "/companies", {"symbol": "MSFT"}),
                               ("POST", f"/companies/{identifier}/refresh", None),
                               ("GET", f"/companies/{identifier}/history", None),
                               ("POST", "/assignments", {"company_id": identifier, "question": "Read private thesis"})):
        response = boundary.public.request(method, "/company-research" + path, json=data)
        assert response.status_code == 403, response.text
    assert not dispatched
    with Session(boundary.engine) as db:
        assert len(db.exec(select(ResearchCompany)).all()) == 1
    response = boundary.owner.post(f"/company-research/companies/{identifier}/refresh")
    assert response.status_code == 200 and len(dispatched) == 1
