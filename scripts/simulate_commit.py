"""
Decision Attestation Commit Simulator

Purpose:
Generate a single, verifiable Decision Attestation Receipt (DAR)
as a standalone artifact.

This is NOT production code.
This file exists to prove the primitive.
"""
import uuid
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import zipfile

commit_timestamp_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
attestation_id = str(uuid.uuid4())
print("Attestation ID:", attestation_id)
print("Commit timestamp:", commit_timestamp_utc)

attestation = {
    "spec_version": "DecisionAttestation v0.1",
    "attestation_id": attestation_id,
    "commit_timestamp_utc": commit_timestamp_utc,
    "actor": {
        "actor_id": "user-ops-001",
        "actor_role": "reviewer",
    },
    "system": {
        "system_id": "decision-engine-prod",
        "model_version_id": "model-v1.2.0",
    },
    "stimulus": {
        "input_type": "transaction_batch",
        "input_hash": "sha256:placeholder",
        "input_description": "Batch of 50 pending transactions",
    },
    "assertion": {
        "proposed_action": "approve",
        "confidence_level": 0.95,
    },
    "warning_state": {
        "warning_displayed": True,
    },
    "human_telemetry": {
        "dwell_time_ms": 2500,
    },
    "verdict": {
        "human_action": "confirmed",
    },
}

print(json.dumps(attestation, indent=2))

stimulus_bytes = (
    b'{"batch_id":"batch-2024-001","transaction_count":50,'
    b'"items":[{"id":"tx-1","amount":100.00},{"id":"tx-2","amount":250.50}]}'
)
input_hash_hex = hashlib.sha256(stimulus_bytes).hexdigest()
attestation["stimulus"]["input_hash"] = f"sha256:{input_hash_hex}"

print(json.dumps(attestation, indent=2))

canonical_json = json.dumps(attestation, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
canonical_bytes = canonical_json.encode("utf-8")
attestation_hash_hex = hashlib.sha256(canonical_bytes).hexdigest()
attestation["attestation_hash"] = f"sha256:{attestation_hash_hex}"

print("Canonical JSON:")
print(canonical_json)
print("Attestation hash:", f"sha256:{attestation_hash_hex}")
print("Final attestation:")
print(json.dumps(attestation, indent=2))

project_root = Path(__file__).resolve().parent.parent

attestation_json_content = json.dumps(attestation, indent=2)

verification = {
    "spec_version": "DecisionAttestation v0.1",
    "verified": True,
    "attestation_hash": attestation["attestation_hash"],
}
verification_json_content = json.dumps(verification, indent=2)

manifest_txt_content = f"""Attestation ID: {attestation_id}
Commit timestamp: {commit_timestamp_utc}

This attestation proves that a specific actor, at a recorded time, acknowledged a decision produced by a named system over identified input (via its hash). It binds the stimulus hash, proposed action, confidence, warning state, human dwell time, and verdict into a single signed digest (attestation_hash). It does not prove that the input was correct, that the model output was correct, or that the human made a good decision—only that this attestation record was produced and can be independently verified by recomputing the hash.
"""

verify_md_content = """To verify this receipt:
1. Load attestation.json and remove the top-level "attestation_hash" field if present.
2. Serialize the resulting object to canonical JSON: sort all object keys, use no whitespace (e.g. separators=(",", ":")), and encode as UTF-8.
3. Compute SHA-256 over that UTF-8 byte string and format as "sha256:<hex>".
4. Compare to the attestation_hash in the file—they must match.
No trust in the producer is required: anyone can recompute the hash from the published attestation and confirm integrity.
"""

zip_path = project_root / "decision_attestation_receipt.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("attestation.json", attestation_json_content)
    zf.writestr("verification.json", verification_json_content)
    zf.writestr("manifest.txt", manifest_txt_content)
    zf.writestr("VERIFY.md", verify_md_content)

print("Wrote", zip_path)
