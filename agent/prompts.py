# Every prompt is a named constant. Never bury prompts in business logic.

EXTRACTION_PROMPT = """
You are an autonomous commitment-extraction agent for meeting transcripts.
Parse the transcript and return a JSON object with a single key "commitments"
holding an array of commitment objects.
Skip ANYTHING that is a vague intention with no owner and no real deadline.

Each object MUST have ALL these fields:
{{
  "speaker":           "name as spoken in transcript",
  "owner":             "the person actually responsible for doing the work — for self_commitment this is the speaker, for assignment this is the assignee (NOT the speaker), for ownerless use \\"team\\"",
  "commitment_text":   "verbatim quote — exact words spoken",
  "normalized_task":   "clean 5-10 word action description",
  "explicit_deadline": "exact deadline phrase if stated, else null",
  "deadline_clue":     "contextual hint if no explicit date, else null",
  "depends_on_hint":   "phrase showing dependency on another task, else null",
  "beneficiary":       "person who is waiting on this, else null",
  "owner_type":        "person | ownerless | vague_intention",
  "item_type":         "self_commitment | assignment | meeting_request",
  "assigned_by":       "speaker name if assignment else null",
  "confidence":        0.0 to 1.0,
  "timestamp_sec":     integer seconds into transcript
}}

CLASSIFICATION RULES:
owner_type "person"           → one named person takes clear responsibility
owner_type "ownerless"        → "we'll", "someone should", "the team will", "let's"
owner_type "vague_intention"  → no deadline, no owner → SKIP, do not include

item_type "self_commitment"   → person commits for themselves
item_type "assignment"        → speaker assigns TO someone else (owner = assignee)
item_type "meeting_request"   → proposing a future meeting

FEW-SHOT EXAMPLES:
"I'll finish the API by Thursday"
→ owner=speaker, person, self_commitment, confidence 0.95 ✓ INCLUDE

"we should probably look into caching sometime"
→ vague_intention → SKIP, DO NOT INCLUDE

"we'll handle deployment"
→ owner="team", ownerless, self_commitment ✓ INCLUDE (flag for owner assignment)

"once Alice finishes, I'll do the integration"
→ depends_on_hint: "once Alice finishes" ✓ INCLUDE

"Priya, can you review the contract by Friday?"
→ person, assignment, owner=Priya, assigned_by=[speaker] ✓ INCLUDE

"let's grab 15 min Thursday to sort this out"
→ meeting_request, explicit_deadline: "Thursday" ✓ INCLUDE

Attendees in this meeting: {attendees}

Return ONLY the JSON object described above. No markdown. No explanation. No preamble.
"""

RESOLUTION_PROMPT = """
Resolve implicit or vague deadline references to ISO 8601 timestamps.

Current datetime: {current_datetime}
Calendar context (upcoming events): {calendar_json}

Rules:
- "before the client call" → find that event in calendar, set deadline = 1h before
- "end of week" → Friday 6 PM
- "end of day" → today 6 PM
- "next week" → Monday 9 AM of next week
- "ASAP" or "soon" → current_datetime + 24h, confidence penalty -0.2
- "Thursday" → nearest upcoming Thursday at 6 PM
- unresolvable → deadline: null, needs_clarification: true

Input commitments: {commitments_json}

Return a JSON object with a single key "commitments" holding the SAME array,
with these fields added or updated on each object:
  "id": unchanged from input
  "deadline": "ISO 8601 or null"
  "needs_clarification": true | false

Return ONLY that JSON object. No markdown.
"""

NUDGE_PROMPT = """
Write a short nudge message from a colleague to {owner}.
Warm, human tone. Like a helpful teammate, not a system alert or bot.

Context:
- Their exact words from the meeting: "{commitment_text}"
- Meeting name: {meeting_title}
- Deadline: {deadline}
- Hours until deadline: {hours_until}

Rules:
- Quote their own words back to them naturally
- Under 80 words
- Do NOT start with "Reminder:" or "ALERT:" or "This is a notification"
- End with one concrete action they can take right now
- Sound like a person

Return ONLY the message text. Nothing else.
"""

AGENDA_MATCH_PROMPT = """
Check which agenda slots a meeting transcript chunk covers.

Meeting type: {meeting_type}
Pending agenda slots: {slots_json}
Transcript chunk (last 30 seconds): {chunk}

For each slot, return its coverage status as a JSON object with a single key
"results" holding an array:
{{
  "results": [
    {{
      "slot_id": "blockers",
      "status": "covered | pending | partial",
      "evidence_quote": "exact phrase from chunk proving coverage, or null"
    }}
  ]
}}

Return ONLY that JSON object.
"""

PATTERN_REPORT_PROMPT = """
Generate a private coaching summary for a team lead.
This is NOT public — it goes to a private Notion page.

Team stats: {stats_json}

Write 3-4 sentences:
1. Overall team follow-through health
2. Who is most at risk of overcommitment (specific name)
3. One concrete structural suggestion to improve
4. Highlight anyone with perfect follow-through (positive reinforcement)

Frame as coaching, never blame. Never use "failed" or "missed".
Use "renegotiated" instead of "broke promise".

Return only the paragraph text.
"""

REASSIGNMENT_PROMPT = """
Someone is overloaded and a task may need reassigning.

Overloaded: {owner} — {open_count} open items, completes ~{rate}/week historically
Task to reassign: {task}
Available teammates with capacity: {available_json}

Write ONE sentence for the team lead:
- Name the specific person to reassign to
- Say why they're a good fit (skills match or capacity)
- Be specific and actionable

Return only that sentence.
"""

MOM_PROMPT = """
Write professional meeting minutes from this transcript and commitment data.

Meeting: {title}
Date: {date}
Attendees: {attendees}
Transcript: {transcript}
Extracted commitments: {commitments_json}
Agenda coverage: {agenda_json}

Format exactly as:

## Summary
[2-3 sentence overview of what was discussed and decided]

## Key Decisions
[bullet points — only real decisions, not discussion]

## Action Items
| Owner | Task | Deadline | Depends On | Status |
|-------|------|----------|------------|--------|
[one row per commitment]

## Ownerless Items (Need Assignment)
[list any ownerless commitments that still need an owner]

## Missed Agenda Items
[any required agenda slots that were not covered]

## Next Meeting
[if a follow-up was proposed, state it here]

Be concise. Professional. No filler.
"""

CROSS_MEETING_BRIEF_PROMPT = """
Generate a "since we last spoke" pre-meeting briefing.

New meeting attendees: {attendees}
Their open commitments from prior meetings: {open_items_json}
Flags (repeated promises, overdue items): {flags_json}

Write exactly 5 bullet points maximum that the meeting chair reads aloud.
Focus on:
- What was promised last time and is still open
- What is overdue or at risk
- Anyone who has promised the same thing twice without delivering

Each bullet under 20 words. Start each with "•".
Return only the bullets.
"""
