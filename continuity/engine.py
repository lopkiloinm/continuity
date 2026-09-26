"""Deterministic handoff model. All amounts are integer simulated micro-USDC."""
import copy
import hashlib
import json
import time
import uuid


class Rejected(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Job:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.id = str(uuid.uuid4())
        self.state = "ready"
        self.budget = 100_000
        self.spent = 0
        self.epoch = 0
        self.agent = None
        self.expires_at = clock() + 600
        self.rows = []
        self.events = []
        self.capsule = None
        self.approval = None
        self.scenario = None
        self.record("created", "Local fixture job created; no funds deposited.")

    def record(self, kind, reason):
        event = {"sequence": len(self.events), "at": self.clock(), "kind": kind,
                 "reason": reason, "state": self.state, "epoch": self.epoch,
                 "spent_micro_usdc": self.spent,
                 "previous_hash": self.events[-1]["hash"] if self.events else None}
        event["hash"] = digest(event)
        self.events.append(event)

    def require(self, state):
        if self.state != state:
            raise Rejected("Expected %s; job is %s." % (state, self.state))

    def check_authority(self, agent, epoch):
        if self.clock() >= self.expires_at:
            raise Rejected("Authority expired; create a new job. Approval cannot extend it.")
        if self.state not in ("primary_working", "successor_working") or agent != self.agent or epoch != self.epoch:
            raise Rejected("Worker authority is inactive or revoked.")

    def commit_batch(self, agent, epoch, start, end, cost):
        self.check_authority(agent, epoch)
        expected = (0, 17, 60_000) if agent == "primary.local" else (17, 30, 40_000)
        if (start, end, cost) != expected or len(self.rows) != start:
            raise Rejected("Unexpected or duplicate batch.")
        if self.spent + cost > self.budget:
            raise Rejected("Budget exhausted.")
        self.rows.extend({"record_id": "fixture-%02d" % i,
                          "source": "synthetic://research/%02d" % i,
                          "description": "Synthetic research record %02d; not a real repository" % i,
                          "worker": agent} for i in range(start + 1, end + 1))
        self.spent += cost
        self.record("batch_committed", "%d fixture rows committed once." % (end - start))

    def start(self):
        self.require("ready")
        self.state, self.agent = "primary_working", "primary.local"
        self.commit_batch(self.agent, self.epoch, 0, 17, 60_000)

    def fail(self):
        self.require("primary_working")
        self.state, self.agent = "frozen", None
        self.epoch += 1
        self.capsule = {"version": 1, "job_id": self.id, "completed": copy.deepcopy(self.rows),
                        "next_record": 18, "remaining_micro_usdc": self.budget - self.spent,
                        "expires_at": self.expires_at, "epoch": self.epoch,
                        "allowed_action": "complete_fixture_csv"}
        self.record("authority_frozen", "Injected worker crash; previous epoch rejected by this orchestrator.")

    def evaluate(self, scenario):
        self.require("frozen")
        if scenario not in ("clean", "changed_address", "blocked", "unavailable"):
            raise Rejected("Unknown fixture scenario.")
        self.scenario = scenario
        if self.clock() >= self.expires_at:
            self.state = "expired"
            self.record("expired", "Expired authority cannot be handed off.")
        elif scenario in ("blocked", "unavailable"):
            self.state = "blocked"
            self.record("screening_blocked", "Fixture risk denied." if scenario == "blocked" else "Fixture screening unavailable; fail closed.")
        elif scenario == "changed_address":
            self.state = "awaiting_approval"
            self.approval = {"job_id": self.id, "successor": "backup.local", "payee": "fixture-payee-v2",
                             "capsule_hash": digest(self.capsule), "epoch": self.epoch,
                             "max_micro_usdc": self.budget - self.spent,
                             "action": "complete_fixture_csv", "expires_at": min(self.expires_at, self.clock() + 120)}
            self.record("approval_requested", "Fixture risk passed, but payee changed. Explicit local demo consent required.")
        else:
            self.grant()

    def grant(self):
        self.state, self.agent = "successor_working", "backup.local"
        self.record("successor_granted", "Local policy grants backup only the remaining batch and budget.")

    def decide(self, approved, approval_hash):
        self.require("awaiting_approval")
        if approval_hash != digest(self.approval):
            raise Rejected("Approval does not match the pending action.")
        if self.clock() >= self.approval["expires_at"]:
            self.state = "expired"
            self.record("approval_expired", "No successor authority granted.")
        elif not approved:
            self.state = "cancelled"
            self.record("approval_cancelled", "No successor authority granted; budget remains simulated and unused.")
        else:
            self.record("demo_consent", "Local demo consent recorded; no World verification performed.")
            self.grant()

    def resume(self):
        self.require("successor_working")
        self.commit_batch(self.agent, self.epoch, 17, 30, 40_000)
        self.state, self.agent = "completed", None
        self.epoch += 1
        self.record("completed", "30 unique fixture records; all local worker authority retired.")

    def snapshot(self):
        return copy.deepcopy({"id": self.id, "mode": "local simulation", "state": self.state,
                "budget_micro_usdc": self.budget, "spent_micro_usdc": self.spent,
                "remaining_micro_usdc": self.budget - self.spent, "epoch": self.epoch,
                "active_agent": self.agent, "expires_at": self.expires_at, "rows": self.rows,
                "capsule": self.capsule, "capsule_hash": digest(self.capsule) if self.capsule else None,
                "approval": self.approval, "approval_hash": digest(self.approval) if self.approval else None,
                "events": self.events, "artifact_hash": digest(self.rows) if self.state == "completed" else None,
                "limitations": ["Synthetic records", "Simulated spending", "No ENS, Intercepta, World or x402 calls",
                                "Unsigned hashes; not independent proof", "In-memory state; restart resets all jobs"]})
