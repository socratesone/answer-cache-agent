"""Explicit application commands, separate from unchanged engine Event/Result contracts."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Literal
import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from answer_cache_agent.contracts import Event, Result, Constraints, parse_payload
from answer_cache_agent.config import Config, load_config
from answer_cache_agent.graph import Agent, RuntimeDeps
from answer_cache_agent.providers import Credentials, ModelRoles, ModelRef
from answer_cache_agent.repository import Repository
from answer_cache_agent.ingest import ingest, Record
from answer_cache_agent.rendering import render, check_constraints, find_leaks
from answer_cache_agent.ranking import requires_satisfied
from .private_store import PrivateStore

CONTRACT = json.loads(Path(__file__).with_name("contract.json").read_text())
SCOPE = "user-default"

class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=128)
    protocol: Literal[1]
    fingerprint: str
    operation: Literal["hello", "event", "render", "search", "ingest", "template_get", "template_update", "variables", "binding", "settings", "configure", "diagnostics"]
    data: dict = Field(default_factory=dict)

class Service:
    """Instantiate and use only on the native host's single worker thread."""
    def __init__(self, directory: Path, runtime: RuntimeDeps | None = None, store=None):
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.private = store or PrivateStore(directory / "private.dpapi")
        self.rt = runtime
        self.agent = None
        state_path = directory / "session-epochs.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        self.epoch = state.get("epoch", 0)
        self.session_epochs = state.get("sessions", {})

    def save_epochs(self):
        path = self.directory / "session-epochs.pending"
        path.write_text(json.dumps({"epoch": self.epoch, "sessions": self.session_epochs}))
        path.replace(self.directory / "session-epochs.json")

    def settings(self):
        path = self.directory / "settings.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def engine(self):
        if self.agent is None:
            rt = self.rt or RuntimeDeps(db_path=str(self.directory / "answer_cache.db"),
                config_path=str(self.directory / "engine.yaml") if (self.directory / "engine.yaml").exists() else None)
            if getattr(sys, "frozen", False) and self.rt is None:
                from .packaged_embedding import PackagedEmbedder
                rt.embedder = PackagedEmbedder(load_config(rt.config_path).retrieval.embedding_model, Path(sys._MEIPASS) / "embedding-model")
            self.agent = Agent(rt)
        if self.rt is None:
            secret = self.private.read()
            self.agent.rt.credentials = Credentials(**secret["credentials"])
            self.agent.rt.bindings = secret["bindings"]
            roles = self.settings().get("roles")
            if roles:
                self.agent.rt.model_roles = ModelRoles(**{k: ModelRef(**v) for k,v in roles.items()})
        return self.agent

    def repo(self):
        a = self.engine()
        return Repository(a.conn, SCOPE, a.embedder, a.store)

    def clean(self, data):
        # Check before engine persistence, not just before provider transmission.
        secrets = dict(self.engine().rt.bindings)
        secrets.update({k: v for k,v in vars(self.engine().rt.credentials).items() if v})
        if find_leaks(json.dumps(data), secrets):
            raise ValueError("Private text detected. Use symbolic placeholders before continuing.")

    def dispatch(self, request):
        c = Command.model_validate(request)
        if c.fingerprint != CONTRACT["fingerprint"]:
            raise ValueError("Incompatible engine contract. Update both extension and companion.")
        d = c.data
        allowed = {
            "hello": set(), "event": {"event", "authorized"}, "render": {"body", "constraints"},
            "search": {"query", "hints"}, "ingest": {"record"},
            "template_get": {"id"}, "template_update": {"id", "intent", "body", "alias", "expected_version"}, "variables": set(),
            "binding": {"id", "value"}, "settings": set(), "configure": {"roles", "budget", "provider", "key"},
            "diagnostics": set(),
        }
        if set(d) - allowed[c.operation]:
            raise ValueError("Unknown command fields")
        if c.operation in ("hello", "settings"):
            secret = self.private.read() if self.rt is None else {"credentials": {}, "bindings": {}}
            return {"version": "0.1.1", "protocol": 1, "fingerprint": CONTRACT["fingerprint"],
                    "configured": bool(secret["credentials"]), "generationReady": bool(self.settings().get("roles") and all(secret["credentials"].get(ref["provider"] + "_api_key") for ref in self.settings()["roles"].values())),
                    "settings": self.settings(), "budget": load_config(self.directory / "engine.yaml" if (self.directory / "engine.yaml").exists() else None).budget.model_dump(),
                    "capabilities": {"autofill": False, "libraryEnumeration": False, "cancellation": False, "portability": False, "modelCatalogue": False}}
        if c.operation == "diagnostics":
            return {"application": "0.1.1", "protocol": 1, "contract": CONTRACT["fingerprint"],
                    "engineLoaded": self.agent is not None, "platformProtection": "Windows DPAPI", "analytics": False}
        if c.operation == "event":
            ev = Event.model_validate(d["event"])
            parse_payload(ev)
            if ev.scope_id != SCOPE:
                raise ValueError("Unsupported scope")
            if ev.type in ("generate_initial", "regenerate_question") and d.get("authorized") is not True:
                raise ValueError("Explicit generation authorization required")
            self.clean(ev.model_dump())
            # Fresh host lifetimes must prepare before using cached sessions. Dependency changes require a new form session.
            if ev.type != "prepare_form" and self.session_epochs.get(ev.session_id) != self.epoch:
                raise ValueError("Refresh the form after reconnecting or changing local information")
            if ev.type == "prepare_form" and ev.session_id in self.session_epochs and self.session_epochs[ev.session_id] != self.epoch:
                raise ValueError("Create a new form session after changing local information")
            if ev.type == "prepare_form":
                self.session_epochs[ev.session_id] = self.epoch
                self.save_epochs()
            result = Result.model_validate(self.engine().handle_event(ev.model_dump())).model_dump()
            return result
        if c.operation == "render":
            body = str(d["body"])
            if len(body) > 100000:
                raise ValueError("Answer too large")
            try:
                text = render(body, self.engine().rt.bindings)
            except KeyError as e:
                return {"text": None, "problems": [f"Missing variable: {e.args[0]}"]}
            return {"text": text, "problems": check_constraints(text, Constraints.model_validate(d.get("constraints", {})))}
        if c.operation == "search":
            query = str(d["query"]).strip()
            if not query or len(query) > 2000:
                raise ValueError("Enter a question of at most 2000 characters")
            hints = d.get("hints", [])
            from answer_cache_agent.contracts import Hint
            context = {}
            for raw in hints:
                h = Hint.model_validate(raw)
                context.setdefault(h.dimension, set()).add(h.value)
            repo = self.repo()
            matches = []
            for identity, similarity in repo.search(query, "template", self.engine().cfg.retrieval.top_k):
                t = repo.template(identity)
                if t and t["status"] == "approved" and requires_satisfied(t["requires"], context):
                    # Local reuse allows local_only; this is not a generation bundle or a uniqueness decision.
                    matches.append({"id": t["id"], "body": t["body"], "intent": t["intent"], "version": t["version"], "status": t["status"],
                                    "applies": {k: sorted(v) for k,v in t["applies"].items()}, "similarity": similarity})
            return {"matches": matches, "complete": False, "autofillEligible": False}
        if c.operation == "ingest":
            record = TypeAdapter(Record).validate_python(d["record"])
            raw = record.model_dump()
            if raw.get("disclosure") == "model_visible" or raw["kind"] == "variable":
                self.clean(raw)
            # Create-only UI: no unsafe implicit updates until engine exposes dependency invalidation.
            if raw["kind"] == "template" and self.repo().template(raw["id"]):
                raise ValueError("Existing template editing awaits the engine edit service")
            counts = ingest(self.repo(), [json.dumps(raw)])
            self.epoch += 1
            self.save_epochs()
            return {"created": dict(counts), "refreshRequired": True}
        if c.operation == "template_get":
            identity = d.get("id")
            if not isinstance(identity, str) or not identity or len(identity) > 128:
                raise ValueError("Invalid template ID")
            t = self.repo().template(identity)
            if not t or t["status"] != "approved":
                raise ValueError("Saved answer is unavailable")
            return {"id": t["id"], "intent": t["intent"], "body": t["body"], "version": t["version"]}
        if c.operation == "template_update":
            identity = d.get("id")
            if not isinstance(identity, str) or not identity or len(identity) > 128:
                raise ValueError("Invalid template ID")
            repo = self.repo()
            old = repo.template(identity)
            if not old or old["status"] != "approved":
                raise ValueError("Saved answer is unavailable")
            if d.get("expected_version") != old["version"]:
                raise ValueError("Saved answer changed elsewhere. Refresh it before editing.")
            intent = d.get("intent", old["intent"])
            body = d.get("body", old["body"])
            alias = d.get("alias")
            if not isinstance(intent, str) or not intent.strip() or len(intent) > 2000:
                raise ValueError("Enter a label of at most 2,000 characters")
            if not isinstance(body, str) or not body.strip() or len(body) > 100000:
                raise ValueError("Enter answer wording of at most 100,000 characters")
            if alias is not None and (not isinstance(alias, str) or not alias.strip() or len(alias) > 2000):
                raise ValueError("Invalid question alias")
            # Keep the same record, disclosure, variables, evidence and context assignments.
            # Moving an intent also retains its old wording and aliases for future retrieval.
            old_aliases = [r[0] for r in repo.conn.execute(
                "SELECT text FROM intent_alias WHERE scope_id=? AND intent=?", (SCOPE, old["intent"]))]
            for text in set([old["intent"], intent, *old_aliases, *([alias] if alias else [])]):
                repo.add_intent_alias(intent, text)
            repo.add_template(identity, intent, body, old["variables"], old["evidence_ids"],
                              old["disclosure"], "user", datetime.now(timezone.utc).isoformat(), old["origin_candidate_id"])
            self.epoch += 1
            self.save_epochs()
            return {"id": identity, "version": repo.template(identity)["version"], "intent": intent, "refreshRequired": True}
        if c.operation == "variables":
            return {"variables": self.repo().variables()}
        if c.operation == "binding":
            identity, value = d["id"], d["value"]
            if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identity) or not isinstance(value, str) or len(value)>100000:
                raise ValueError("Invalid variable binding")
            if not self.repo().variables([identity]):
                raise ValueError("Create a variable description first")
            secret = self.private.read()
            secret["bindings"][identity] = value
            self.private.write(secret)
            self.epoch += 1
            self.save_epochs()
            return {"saved": True, "refreshRequired": True}
        if c.operation == "configure":
            settings = self.settings()
            if "roles" in d:
                roles = d["roles"]
                if set(roles) != {"routine", "advanced"}:
                    raise ValueError("Both model roles are required")
                for ref in roles.values():
                    if set(ref) != {"provider", "model"} or ref["provider"] not in ("openai", "anthropic") or not isinstance(ref["model"], str) or not ref["model"].strip():
                        raise ValueError("Invalid model role")
                settings["roles"] = roles
            cfg = load_config(self.directory / "engine.yaml" if (self.directory / "engine.yaml").exists() else None).model_dump()
            if "budget" in d:
                cfg["budget"]["max_session_cost_usd"] = d["budget"]
            cfg = Config.model_validate(cfg)
            if "key" in d:
                if d.get("provider") not in ("openai", "anthropic") or not isinstance(d["key"], str) or not d["key"].strip():
                    raise ValueError("Invalid provider credential")
                secret = self.private.read()
                secret["credentials"][d["provider"] + "_api_key"] = d["key"].strip()
                self.private.write(secret)
            for name, value in (("settings.json", json.dumps(settings)), ("engine.yaml", yaml.safe_dump(cfg.model_dump()))):
                temporary = self.directory / (name + ".pending")
                temporary.write_text(value)
                temporary.replace(self.directory / name)
            if self.agent:
                self.agent.cfg = cfg
            self.epoch += 1
            self.save_epochs()
            return {"saved": True, "refreshRequired": True}
        raise ValueError("Unsupported operation")
