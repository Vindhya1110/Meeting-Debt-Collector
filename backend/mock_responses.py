# When MOCK_MODE=true, these replace all real API calls.
# The pipeline still runs end-to-end — just with canned responses.

MOCK_EXTRACTION = [
    {
        "speaker": "Alice",
        "commitment_text": "I'll finish the API integration by Thursday",
        "normalized_task": "Finish API integration",
        "explicit_deadline": "Thursday",
        "deadline_clue": None,
        "depends_on_hint": None,
        "beneficiary": "Bob",
        "owner_type": "person",
        "item_type": "self_commitment",
        "assigned_by": None,
        "confidence": 0.95,
        "timestamp_sec": 45
    },
    {
        "speaker": "Bob",
        "commitment_text": "Once Alice finishes, I'll do the integration testing",
        "normalized_task": "Complete integration testing",
        "explicit_deadline": None,
        "deadline_clue": "once Alice finishes",
        "depends_on_hint": "once Alice finishes",
        "beneficiary": None,
        "owner_type": "person",
        "item_type": "self_commitment",
        "assigned_by": None,
        "confidence": 0.88,
        "timestamp_sec": 62
    },
    {
        "speaker": "Rohith",
        "commitment_text": "we'll handle the deployment, don't worry",
        "normalized_task": "Handle production deployment",
        "explicit_deadline": None,
        "deadline_clue": "before the client call",
        "depends_on_hint": None,
        "beneficiary": None,
        "owner_type": "ownerless",
        "item_type": "self_commitment",
        "assigned_by": None,
        "confidence": 0.91,
        "timestamp_sec": 89
    },
    {
        "speaker": "Priya",
        "commitment_text": "I'll review the API contract by Friday",
        "normalized_task": "Review API contract",
        "explicit_deadline": "Friday",
        "deadline_clue": None,
        "depends_on_hint": None,
        "beneficiary": "Rohith",
        "owner_type": "person",
        "item_type": "self_commitment",
        "assigned_by": None,
        "confidence": 0.97,
        "timestamp_sec": 120
    }
]

MOCK_RESOLUTION = MOCK_EXTRACTION  # Deadlines added by main pipeline in mock mode

MOCK_NUDGE_TEXT = (
    "Hey Alice — in Thursday's Sprint Review you said you'd finish the API "
    "integration. That deadline is tomorrow. Want to send a quick status "
    "update to Bob now?"
)
