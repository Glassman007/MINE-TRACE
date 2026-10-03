from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.base import Base
from app.domain.enums import IncidentEvidenceRelationshipType, IncidentStatus
from app.integrations.llm.factory import build_ai_provider
from app.integrations.llm.groq_provider import GroqProvider
from app.models import EvidenceEventRecord, IncidentEvidenceLinkRecord, IncidentRecord, MachineRecord
from app.schemas.fleet_ai import FleetAIAnalysisRequest, FleetAIState
from app.services.fleet_ai_analysis import FleetAIAnalysisService

NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


class FakeCompletions:
    def __init__(self, content=None, exc=None): self.content=content; self.exc=exc; self.calls=[]
    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc: raise self.exc
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])

class FakeGroq:
    def __init__(self, completions): self.chat=SimpleNamespace(completions=completions)


@pytest.fixture
def env(tmp_path):
    engine=create_engine(f"sqlite+pysqlite:///{tmp_path/'groq.db'}")
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine,class_=Session,expire_on_commit=False)
    machine, incident, evidence=uuid4(),uuid4(),uuid4()
    with factory() as s:
        s.add(MachineRecord(id=machine,display_name="Truck A",machine_type="HAUL_TRUCK",model="MT-100",site_name="North")); s.flush()
        s.add(IncidentRecord(id=incident,machine_id=machine,status=IncidentStatus.OPEN)); s.flush()
        s.add(EvidenceEventRecord(id=evidence,machine_id=machine,source_machine_id=machine,source_type="HUMAN_OBSERVATION",original_source_record_id="obs",original_timestamp=NOW,canonical_event_type="NOTE",canonical_payload={"text":"pump noise"},raw_source_payload={},provenance={"source":"edge"})); s.flush()
        s.add(IncidentEvidenceLinkRecord(id=uuid4(),incident_id=incident,evidence_event_id=evidence,is_active=True,relationship_type=IncidentEvidenceRelationshipType.RELATED,link_reason="edge")); s.commit()
    yield factory,{"machine":machine,"incident":incident,"evidence":evidence}
    engine.dispose()


def _provider(content):
    c=FakeCompletions(content)
    return GroqProvider(model="llama-test",api_key="secret",timeout_seconds=1,client=FakeGroq(c)),c


def test_explicit_analysis_uses_canonical_context_and_preserves_citation_provenance(env):
    factory, ids=env
    content=json.dumps({"status":"UNVALIDATED","summary":"Pump noise was recorded.","claims":[{"claim_type":"OBSERVATION_RECORDED","text":"Pump noise was recorded.","evidence_ids":[str(ids["evidence"])]}],"limitations":["No root cause conclusion."]})
    provider,calls=_provider(content)
    with factory() as s:
        result=FleetAIAnalysisService(s,provider,model="llama-test").analyze(FleetAIAnalysisRequest(prompt="summarize",incident_ids=[ids["incident"]]))
    assert result.state is FleetAIState.AVAILABLE
    assert result.citations[0].evidence_id==ids["evidence"] and result.citations[0].provenance=={"source":"edge"}
    payload=json.loads(calls.calls[0]["messages"][1]["content"])
    assert payload["canonical_context"]["evidence"][0]["canonical_payload"]=={"text":"pump noise"}


def test_unknown_citation_is_rejected(env):
    factory, ids=env
    provider,_=_provider(json.dumps({"status":"UNVALIDATED","summary":"x","claims":[{"claim_type":"OBSERVATION_RECORDED","text":"x","evidence_ids":[str(uuid4())]}],"limitations":[]}))
    with factory() as s:
        result=FleetAIAnalysisService(s,provider,model="m").analyze(FleetAIAnalysisRequest(prompt="x",incident_ids=[ids["incident"]]))
    assert result.state is FleetAIState.DEGRADED and result.reason=="unknown_evidence_citation"


def test_missing_groq_key_and_provider_failure_degrade(env):
    settings=Settings(database_url="postgresql+psycopg://u:p@localhost/db",ai_enabled=True,ai_provider="groq",ai_model="m",groq_api_key=None)
    provider=build_ai_provider(settings)
    factory,ids=env
    with factory() as s:
        result=FleetAIAnalysisService(s,provider,model="m").analyze(FleetAIAnalysisRequest(prompt="x",incident_ids=[ids["incident"]]))
    assert result.state is FleetAIState.DEGRADED and result.reason=="missing_groq_api_key"

    failing=GroqProvider(model="m",api_key="x",timeout_seconds=1,client=FakeGroq(FakeCompletions(exc=RuntimeError("down"))))
    with factory() as s:
        result=FleetAIAnalysisService(s,failing,model="m").analyze(FleetAIAnalysisRequest(prompt="x",incident_ids=[ids["incident"]]))
    assert result.state is FleetAIState.DEGRADED and result.reason.startswith("groq_provider_error:")


def test_malformed_response_degrades_and_no_canonical_mutation(env):
    factory,ids=env
    provider,_=_provider("not-json")
    with factory() as s:
        before=s.scalar(select(IncidentRecord.status).where(IncidentRecord.id==ids["incident"]))
        result=FleetAIAnalysisService(s,provider,model="m").analyze(FleetAIAnalysisRequest(prompt="x",incident_ids=[ids["incident"]]))
        after=s.scalar(select(IncidentRecord.status).where(IncidentRecord.id==ids["incident"]))
    assert result.state is FleetAIState.DEGRADED and result.reason=="invalid_structured_output"
    assert before==after==IncidentStatus.OPEN
