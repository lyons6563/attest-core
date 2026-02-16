"""
Minimal Streamlit app to record AI decision attestations into the custody ledger.
Run from project root: streamlit run streamlit_decision_demo.py
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone

import streamlit as st
from sqlalchemy import text

from app.db import get_engine
from app.crypto.event_hash import compute_event_hash, format_occurred_at_utc

st.set_page_config(page_title="Decision Attestation Demo", layout="centered")
st.title("Decision Attestation Demo")

stimulus = st.text_area("Stimulus Description", height=120)
model_output = st.text_area("Model Output", height=120)
model_version = st.text_input("Model Version", value="")
human_action = st.radio("Human Action", options=["approve", "override"], horizontal=True)
record_clicked = st.button("Record Decision")

if record_clicked:
    if not stimulus.strip() or not model_output.strip():
        st.error("Please fill in Stimulus Description and Model Output.")
    else:
        try:
            # 1. Hashes
            stimulus_hash = hashlib.sha256(stimulus.strip().encode("utf-8")).hexdigest()
            model_output_hash = hashlib.sha256(model_output.strip().encode("utf-8")).hexdigest()

            # 2. Payload and payload_hash
            recorded_at = datetime.now(timezone.utc).isoformat()
            payload = {
                "stimulus_hash": stimulus_hash,
                "stimulus_description": stimulus.strip(),
                "model_version": model_version.strip(),
                "model_output_hash": model_output_hash,
                "model_output_excerpt": (model_output.strip() or "")[:200],
                "human_action": human_action,
                "recorded_at": recorded_at,
            }
            payload_json = json.dumps(payload, sort_keys=True)
            payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

            engine = get_engine()
            with engine.connect() as conn:
                # 3. Chain: use latest or create new
                latest = conn.execute(
                    text(
                        "SELECT chain_id FROM custody_chains ORDER BY created_at_utc DESC LIMIT 1"
                    )
                ).fetchone()

                if latest:
                    chain_id = str(latest.chain_id)
                else:
                    # New chain; use stimulus_hash as root_file_hash
                    row = conn.execute(
                        text(
                            "INSERT INTO custody_chains (root_file_hash, status) "
                            "VALUES (:root, 'OPEN') RETURNING chain_id"
                        ),
                        {"root": stimulus_hash},
                    ).fetchone()
                    chain_id = str(row.chain_id)

                # 4. Last event hash for this chain
                prev = conn.execute(
                    text(
                        "SELECT event_hash FROM custody_events "
                        "WHERE chain_id = :cid ORDER BY occurred_at_utc DESC, event_id DESC LIMIT 1"
                    ),
                    {"cid": chain_id},
                ).fetchone()
                previous_event_hash = prev.event_hash if prev else None

                # 5. Event hash and timestamp
                occurred_at_utc_dt = datetime.now(timezone.utc)
                occurred_at_utc_str = format_occurred_at_utc(occurred_at_utc_dt)
                session_id = str(uuid.uuid4())
                model_excerpt = (model_output.strip() or "")[:200]

                event_hash = compute_event_hash(
                    chain_id=chain_id,
                    event_type="AI_DECISION_ATTESTED",
                    actor="user",
                    occurred_at_utc=occurred_at_utc_str,
                    payload_hash=payload_hash,
                    previous_event_hash=previous_event_hash,
                    actor_id="streamlit_demo",
                    session_id=session_id,
                    source_system="streamlit",
                    system_suggestion=model_excerpt,
                    options_presented="approve,override",
                    human_selection=human_action,
                    decision_timestamp=occurred_at_utc_dt,
                )

                # 6. Insert
                conn.execute(
                    text(
                        """
                        INSERT INTO custody_events (
                            chain_id, event_type, actor, payload_hash,
                            previous_event_hash, event_hash, occurred_at_utc,
                            actor_id, session_id, source_system,
                            system_suggestion, options_presented, human_selection, decision_timestamp
                        )
                        VALUES (
                            :cid, 'AI_DECISION_ATTESTED', 'user', :payload_hash,
                            :prev_hash, :event_hash, :occurred_at_utc,
                            :actor_id, :session_id, :source_system,
                            :system_suggestion, :options_presented, :human_selection, :decision_timestamp
                        )
                        """
                    ),
                    {
                        "cid": chain_id,
                        "payload_hash": payload_hash,
                        "prev_hash": previous_event_hash,
                        "event_hash": event_hash,
                        "occurred_at_utc": occurred_at_utc_dt,
                        "actor_id": "streamlit_demo",
                        "session_id": session_id,
                        "source_system": "streamlit",
                        "system_suggestion": model_excerpt,
                        "options_presented": "approve,override",
                        "human_selection": human_action,
                        "decision_timestamp": occurred_at_utc_dt,
                    },
                )
                conn.commit()

            st.success("Decision recorded successfully.")
            st.write("**Chain ID:**", chain_id)
            st.write("**Event hash:**", event_hash)
        except Exception as e:
            st.error(f"Failed to record decision: {e}")
