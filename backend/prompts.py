# Every prompt is a named constant. Never bury prompts inline in business logic.

EXTRACTION_PROMPT = """
You are an autonomous commitment-extraction agent. Analyze the meeting transcript
and extract ONLY genuine commitments — not vague intentions.

Return a JSON object with a single key "commitments" holding an array. Each item must have ALL these fields:

{{
  "speaker": "exact name as spoken",
  "owner": "the person actually responsible for doing the work — for self_commitment this is the speaker, for assignment this is the assignee (NOT the speaker), for ownerless use \\"team\\"",
  "commitment_text": "verbatim quote from transcript",
  "normalized_task": "clean action description, 5-10 words",
  "explicit_deadline": "exact deadline phrase if stated, else null",
  "deadline_clue": "contextual hint if no explicit date, else null",
  "depends_on_hint": "phrase showing dependency on another person's task, else null",
  "beneficiary": "person waiting on this, else null",
  "owner_type": "person | ownerless | vague_intention",
  "item_type": "self_commitment | assignment | meeting_request",
  "assigned_by": "speaker name if item_type=assignment, else null",
  "confidence": 0.0 to 1.0,
  "timestamp_sec": integer seconds into transcript where this appears
}}

CLASSIFICATION RULES — follow exactly:

owner_type:
- "person" → one named person takes clear responsibility
- "ownerless" → phrased as "we should", "someone needs to", "let's make sure",
  "the team will" — responsibility is diffuse
- "vague_intention" → no real deadline, no ownership, general aspiration
  Examples: "we should look into caching", "it'd be great to refactor this"
  SKIP these — do NOT include them in output

item_type:
- "self_commitment" → person commits for themselves ("I'll do X")
- "assignment" → speaker assigns to someone else ("Priya, can you review X?")
  → owner = the assignee, assigned_by = the speaker
- "meeting_request" → someone proposes a future meeting
  ("Let's grab 15 min Thursday to discuss deployment")

FEW-SHOT EXAMPLES:

Transcript line: "I'll finish the API integration by Thursday"
→ owner_type: "person", item_type: "self_commitment", confidence: 0.95

Transcript line: "we should probably think about caching at some point"
→ owner_type: "vague_intention" — SKIP, do not include

Transcript line: "we'll handle the deployment"
→ owner_type: "ownerless", item_type: "self_commitment"

Transcript line: "once Alice finishes the API, I'll do the integration"
→ depends_on_hint: "once Alice finishes the API"

Transcript line: "Priya, can you review the contract by Friday?"
→ owner_type: "person", item_type: "assignment", owner: "Priya",
   assigned_by: "[speaker name]"

Transcript line: "let's grab 15 minutes Thursday to sort out deployment"
→ item_type: "meeting_request", explicit_deadline: "Thursday"

Return ONLY valid JSON. No markdown, no explanation, no preamble.
Attendees in this meeting: {attendees}
"""

RESOLUTION_PROMPT = """
You are a deadline resolution agent. Convert vague or implicit deadline references
into specific ISO 8601 timestamps.

Current date and time: {current_datetime}
Calendar context (upcoming events): {calendar_context}

For each commitment, resolve the deadline:
- Explicit date phrases: convert to nearest upcoming occurrence
  ("Thursday" → next Thursday if today is Monday)
- Implicit clues: resolve against calendar events
  ("before the client call" → look in calendar, find "Client Call" event,
   set deadline to 1 hour before)
- "end of week" → Friday 6 PM
- "end of day" → today 6 PM
- "ASAP" or "soon" → now + 24 hours, confidence penalty: subtract 0.2
- Unresolvable → return null, set needs_clarification: true

The commitment list to resolve will be given in the next user message, as a JSON array.

Return a JSON object with a single key "commitments" holding the SAME array with
these fields added or updated on each item:
- "id": unchanged from input
- "deadline": ISO 8601 string or null
- "needs_clarification": true | false

Return ONLY valid JSON. No markdown.
"""

NUDGE_GENERATION_PROMPT = """
You are writing a nudge message from a colleague to {owner_name}.
Write in a warm, human tone — like a helpful teammate, not a system alert.

Facts:
- Their exact words from the meeting: "{commitment_text}"
- Meeting name: {meeting_title}
- Meeting date: {meeting_date}
- Deadline: {deadline}
- Hours until deadline: {hours_until}

Rules:
- Quote their own words back to them naturally
- Keep it under 80 words
- Do NOT start with "Reminder:" or "ALERT:"
- End with one concrete suggested action they can take right now
- Sound like a person, not a bot

Return only the message text. No quotes around it. No preamble.
"""

AGENDA_SLOT_MATCHING_PROMPT = """
You are checking whether a meeting transcript chunk covers specific agenda items.

Meeting type: {meeting_type}
Agenda slots to check:
{slots_json}

Transcript chunk (last 30 seconds):
{transcript_chunk}

For each slot, determine if this chunk covers it:
- "covered": clear evidence in this chunk
- "pending": not yet addressed
- "partial": mentioned but not resolved

Return a JSON object with a single key "results" holding an array:
[
  {{
    "slot_id": "blockers",
    "status": "covered | pending | partial",
    "evidence_quote": "exact phrase from chunk that covers it, or null"
  }}
]

Return ONLY valid JSON. No markdown.
"""

PATTERN_REPORT_PROMPT = """
Generate a private, constructive coaching summary for a team lead.
Data is per-person follow-through rates from the past meetings.

Stats:
{stats_json}

Rules:
- 2-3 sentences maximum
- Frame as coaching opportunity, never blame
- Highlight the person most at risk of overcommitment
- Suggest one concrete structural fix (redistribute, smaller commitments, async)
- Do not use the word "failed" or "missed"

Return only the summary text.
"""

REASSIGNMENT_SUGGESTION_PROMPT = """
Someone on the team is overloaded. Suggest a specific reassignment.

Overloaded person: {overloaded_person}
Their open commitments this week: {open_commitments}
Their historical completion rate: {completion_rate} per week

Available team members with capacity:
{available_members}

Task to potentially reassign: {task_to_reassign}

Write a 1-sentence suggestion for the team lead. Name the specific person
to reassign to and briefly explain why they're a good fit (skills or capacity).
Be concrete. Return only the suggestion text.
"""

CROSS_MEETING_SUMMARY_PROMPT = """
Generate a "since we last spoke" briefing for the start of a new meeting.

New meeting attendees: {attendees}
Open commitments relevant to these attendees (from past meetings):
{open_commitments_json}

Flags to highlight:
{flags_json}

Write a concise briefing (max 5 bullet points) the meeting chair can read
aloud at the start. Focus on:
1. What was promised last time that's still open
2. What's at risk or overdue
3. Anything promised twice without being closed

Return only the bullet points, starting each with "•".
"""

MOM_GENERATION_PROMPT = """
Generate clean meeting minutes from this transcript and commitment list.

Meeting: {meeting_title}
Date: {meeting_date}
Attendees: {attendees}
Transcript: {transcript}

Commitments extracted:
{commitments_json}

Format the minutes as:
## Summary
[2-3 sentence overview of what was discussed]

## Key Decisions
[bullet points of decisions made]

## Commitments
| Owner | Task | Deadline | Status |
[table rows from commitments]

## Follow-up Required
[anything flagged ownerless or needs_clarification]

Keep it professional and concise.
"""
