// Meeting Debt Collector — vanilla JS dashboard. No build step, no framework.
// Talks to the FastAPI backend served from the same origin.

const API = "";

const state = {
  meetings: [],       // [{id, title, type, owner, attendees}]
  chunkIndex: {},      // meeting_id -> next chunk index
};

// ---- Sample transcripts embedded directly (avoids cross-folder static serving issues) ----
const SAMPLES = {
  "transcript_1_clean.txt":
`[00:00] Alice: Good morning everyone. Let's get started with the sprint review.
[00:15] Alice: I'll finish the payments API by Thursday end of day.
[00:32] Bob: Once Alice finishes the API, I'll complete the integration testing by Friday morning.
[00:48] Priya: I'll review the API contract and send comments to Rohith by Thursday noon.
[01:05] Rohith: I'll prepare the deployment checklist by Wednesday evening.
[01:20] Alice: Great. Let's also make sure testing covers the edge cases we discussed.
[01:35] Priya: I'll update the test plan document by Thursday as well.
[01:50] Alice: Okay, anything else before we wrap up?
[02:00] Rohith: I think we're good. Talk later everyone.`,
  "transcript_2_messy.txt":
`[00:00] Rohith: Alright, quick sync. Let's go.
[00:12] Alice: So I'll get the API done before the client call.
[00:24] Bob: We should probably look into caching at some point, just a thought.
[00:38] Rohith: Yeah definitely. Anyway, we'll handle the deployment, don't worry about it.
[00:55] Alice: Who's doing the deployment exactly?
[01:02] Rohith: Like, the team. We'll sort it out.
[01:15] Priya: I'll write the test cases, I can get that done by end of week.
[01:28] Bob: Once Alice is done with the API, I'll do the front-end integration.
[01:40] Alice: Also, let's grab 15 minutes Thursday afternoon to go over the client demo flow.
[01:55] Rohith: Yeah let's do that. Okay, anything else before we close?
[02:05] Bob: I think that's it.`,
  "transcript_3_followup.txt":
`[00:00] Alice: Quick check-in from last week's sync.
[00:12] Rohith: Yeah, so about the deployment — I'll actually own that. Should be done by Monday.
[00:28] Alice: Good. I actually didn't finish the API on Thursday, I'll push that to next week.
[00:45] Bob: So my integration gets pushed too then, makes sense.
[01:00] Priya: I finished the test cases already, that's done.
[01:12] Alice: Perfect. I'll finish the API by next Wednesday, promise.
[01:28] Rohith: This is actually the second time Alice has mentioned the API.
[01:35] Alice: I know, I know. Wednesday for real this time.
[01:50] Rohith: Let's wrap up. I'll send the updated timeline to everyone by tomorrow morning.`
};

const DEFAULT_ATTENDEES = [
  { name: "Alice", email: "alice@team.com", slack_handle: "@alice" },
  { name: "Bob", email: "bob@team.com", slack_handle: "@bob" },
  { name: "Rohith", email: "rohith@team.com", slack_handle: "@rohith" },
  { name: "Priya", email: "priya@team.com", slack_handle: "@priya" },
];

// ---------------------------------------------------------------------------
// Utilities

function toast(msg, isError) {
  const wrap = document.getElementById("toast-wrap");
  const el = document.createElement("div");
  el.className = "toast";
  if (isError) el.style.borderLeftColor = "var(--red)";
  el.textContent = msg;
  wrap.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

async function api(path, options) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

function fmtDeadline(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Tabs

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "commitments") loadCommitments();
    if (btn.dataset.tab === "reports") loadReports();
  });
});

// ---------------------------------------------------------------------------
// Health polling

async function pollHealth() {
  const pill = document.getElementById("status-pill");
  try {
    const h = await api("/health");
    const mock = h.mock_mode === "true" || h.mock_mode === true;
    pill.textContent = mock ? `MOCK MODE · ${fmtDeadline(h.agent_now)}` : `live · ${fmtDeadline(h.agent_now)}`;
    pill.className = mock ? "mock" : "ok";
    document.getElementById("agent-now").textContent = h.agent_now;
  } catch (e) {
    pill.textContent = "backend unreachable";
    pill.className = "down";
  }
}
setInterval(pollHealth, 2000);
pollHealth();

// ---------------------------------------------------------------------------
// Attendees UI

function attendeeRowHtml(a) {
  return `<div class="attendee-row">
    <input class="a-name" placeholder="Name" value="${a?.name || ""}">
    <input class="a-email" placeholder="Email" value="${a?.email || ""}">
    <input class="a-slack" placeholder="@slack" value="${a?.slack_handle || ""}">
    <button class="btn ghost small remove-attendee" type="button">×</button>
  </div>`;
}

function renderAttendees(list) {
  const container = document.getElementById("attendee-list");
  container.innerHTML = list.map(attendeeRowHtml).join("");
  container.querySelectorAll(".remove-attendee").forEach(btn => {
    btn.addEventListener("click", () => btn.closest(".attendee-row").remove());
  });
}
renderAttendees(DEFAULT_ATTENDEES);

document.getElementById("add-attendee").addEventListener("click", () => {
  const container = document.getElementById("attendee-list");
  container.insertAdjacentHTML("beforeend", attendeeRowHtml({}));
  container.querySelectorAll(".remove-attendee").forEach(btn => {
    btn.onclick = () => btn.closest(".attendee-row").remove();
  });
});

function collectAttendees() {
  return [...document.querySelectorAll("#attendee-list .attendee-row")]
    .map(row => ({
      name: row.querySelector(".a-name").value.trim(),
      email: row.querySelector(".a-email").value.trim(),
      slack_handle: row.querySelector(".a-slack").value.trim(),
    }))
    .filter(a => a.name);
}

document.getElementById("sample-picker").addEventListener("change", (e) => {
  const key = e.target.value;
  if (key && SAMPLES[key]) {
    document.getElementById("m-transcript").value = SAMPLES[key];
  }
});

// ---------------------------------------------------------------------------
// Meetings

function refreshMeetingSelects() {
  const opts = state.meetings
    .map(m => `<option value="${m.id}">${m.title} (${m.type})</option>`)
    .join("");
  document.getElementById("chunk-meeting-select").innerHTML = opts || `<option value="">No meetings yet</option>`;
  document.getElementById("agenda-meeting-select").innerHTML = opts || `<option value="">No meetings yet</option>`;
}

async function loadMeetingsFromServer() {
  try {
    const data = await api("/meetings");
    state.meetings = data.meetings.map(m => ({ id: m.id, title: m.title, type: m.type, owner: m.owner, attendees: m.attendees }));
    refreshMeetingSelects();
  } catch (e) {
    // backend may not be up yet; ignore
  }
}

document.getElementById("create-meeting").addEventListener("click", async () => {
  const title = document.getElementById("m-title").value.trim();
  const type = document.getElementById("m-type").value;
  const owner = document.getElementById("m-owner").value.trim();
  const attendees = collectAttendees();
  const transcript = document.getElementById("m-transcript").value.trim();

  if (!title || !owner || attendees.length === 0) {
    toast("Title, owner, and at least one attendee are required.", true);
    return;
  }

  try {
    const data = await api("/meetings", {
      method: "POST",
      body: JSON.stringify({ title, type, owner, attendees, transcript }),
    });
    state.meetings.push({ id: data.meeting_id, title, type, owner, attendees });
    state.chunkIndex[data.meeting_id] = 0;
    refreshMeetingSelects();
    const count = data.commitments ? data.commitments.length : 0;
    toast(`Meeting created. ${count} commitment(s) extracted.`);
    document.querySelector('.tab-btn[data-tab="commitments"]').click();
  } catch (e) {
    toast("Failed to create meeting: " + e.message, true);
  }
});

document.getElementById("send-chunk").addEventListener("click", async () => {
  const meetingId = document.getElementById("chunk-meeting-select").value;
  const chunk = document.getElementById("chunk-text").value.trim();
  if (!meetingId) { toast("Create a meeting first.", true); return; }
  if (!chunk) { toast("Enter chunk text.", true); return; }

  const idx = (state.chunkIndex[meetingId] || 0) + 1;
  try {
    const data = await api(`/meetings/${meetingId}/chunk`, {
      method: "POST",
      body: JSON.stringify({ chunk, chunk_index: idx }),
    });
    state.chunkIndex[meetingId] = idx;
    document.getElementById("chunk-text").value = "";
    const alertBox = document.getElementById("chunk-alert");
    if (data.alert) {
      alertBox.innerHTML = `<div class="alert-box">${data.alert}</div>`;
    } else {
      alertBox.innerHTML = "";
    }
    toast(`${data.commitments_extracted} commitment(s) extracted from chunk.`);
  } catch (e) {
    toast("Chunk ingestion failed: " + e.message, true);
  }
});

document.getElementById("finalize-meeting").addEventListener("click", async () => {
  const meetingId = document.getElementById("chunk-meeting-select").value;
  if (!meetingId) { toast("Create a meeting first.", true); return; }
  try {
    const data = await api(`/meetings/${meetingId}/finalize`, { method: "POST" });
    const el = document.getElementById("mom-output");
    el.style.display = "block";
    el.textContent = data.mom;
  } catch (e) {
    toast("Finalize failed: " + e.message, true);
  }
});

document.getElementById("prebrief-meeting").addEventListener("click", async () => {
  const meetingId = document.getElementById("chunk-meeting-select").value;
  if (!meetingId) { toast("Create a meeting first.", true); return; }
  try {
    const data = await api(`/meetings/${meetingId}/pre-brief`);
    const el = document.getElementById("brief-output");
    el.style.display = "block";
    el.textContent = data.brief;
  } catch (e) {
    toast("Pre-brief failed: " + e.message, true);
  }
});

// ---------------------------------------------------------------------------
// Commitment feed

function actionButtonsHtml(c) {
  if (c.status === "review") {
    return `
      <button class="btn small green" data-action="approve" data-id="${c.id}">Approve</button>
      <button class="btn small danger" data-action="reject" data-id="${c.id}">Reject</button>`;
  }
  if (["open", "nudged", "escalated"].includes(c.status)) {
    return `
      <button class="btn small green" data-action="done" data-id="${c.id}">Done</button>
      <button class="btn small secondary" data-action="need_time" data-id="${c.id}">Need Time</button>
      <button class="btn small ghost" data-action="reassign" data-id="${c.id}">Reassign</button>`;
  }
  return `<span class="muted">—</span>`;
}

async function loadCommitments() {
  const status = document.getElementById("filter-status").value;
  const owner = document.getElementById("filter-owner").value.trim();
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (owner) params.set("owner", owner);

  try {
    const data = await api("/commitments" + (params.toString() ? `?${params}` : ""));
    const body = document.getElementById("commitments-body");
    const empty = document.getElementById("commitments-empty");
    if (!data.commitments.length) {
      body.innerHTML = "";
      empty.style.display = "block";
      return;
    }
    empty.style.display = "none";
    body.innerHTML = data.commitments.map(c => `
      <tr>
        <td>${c.owner}</td>
        <td>
          ${c.normalized_task}
          <div class="quote">"${c.commitment_text}"</div>
        </td>
        <td>${fmtDeadline(c.deadline)}</td>
        <td><span class="badge ${c.status}">${c.status}</span></td>
        <td class="muted">${c.meeting_title || ""}</td>
        <td><div class="actions-cell">${actionButtonsHtml(c)}</div></td>
      </tr>
    `).join("");

    body.querySelectorAll("button[data-action]").forEach(btn => {
      btn.addEventListener("click", () => handleCommitmentAction(btn.dataset.id, btn.dataset.action));
    });
  } catch (e) {
    toast("Failed to load commitments: " + e.message, true);
  }
}

async function handleCommitmentAction(id, action) {
  let body = { action };
  if (action === "need_time") {
    const hours = prompt("Push the deadline out by how many hours?", "24");
    if (hours === null) return;
    const c = (await api(`/commitments?status=`)).commitments.find(x => x.id === id);
    const base = c && c.deadline ? new Date(c.deadline) : new Date();
    base.setHours(base.getHours() + parseFloat(hours || "24"));
    body.new_deadline = base.toISOString();
  }
  if (action === "reassign") {
    const newOwner = prompt("Reassign to whom?");
    if (!newOwner) return;
    body.new_owner = newOwner.trim();
  }
  try {
    await api(`/commitments/${id}/action`, { method: "POST", body: JSON.stringify(body) });
    toast(`Action "${action}" applied.`);
    loadCommitments();
  } catch (e) {
    toast("Action failed: " + e.message, true);
  }
}

document.getElementById("refresh-commitments").addEventListener("click", loadCommitments);
document.getElementById("filter-status").addEventListener("change", loadCommitments);
document.getElementById("filter-owner").addEventListener("keyup", (e) => { if (e.key === "Enter") loadCommitments(); });

// ---------------------------------------------------------------------------
// Agenda

document.getElementById("load-agenda").addEventListener("click", async () => {
  const meetingId = document.getElementById("agenda-meeting-select").value;
  const slotsEl = document.getElementById("agenda-slots");
  const emptyEl = document.getElementById("agenda-empty");
  const alertEl = document.getElementById("agenda-alert");
  if (!meetingId) { emptyEl.style.display = "block"; slotsEl.innerHTML = ""; return; }

  try {
    const data = await api(`/agenda/${meetingId}`);
    emptyEl.style.display = "none";
    alertEl.innerHTML = data.alert_message ? `<div class="alert-box">${data.alert_message}</div>` : "";
    slotsEl.innerHTML = data.slots.map(s => `
      <li>
        <span class="dot ${s.status === 'covered' ? 'covered' : 'pending'}"></span>
        ${s.label}
        ${s.evidence_quote ? `<span class="quote"> — "${s.evidence_quote}"</span>` : ""}
        <span class="req-tag">${s.required ? "required" : "optional"}</span>
      </li>
    `).join("");
  } catch (e) {
    toast("Failed to load agenda: " + e.message, true);
  }
});

// ---------------------------------------------------------------------------
// Reports

async function loadReports() {
  try {
    const people = await api("/report/people");
    document.getElementById("people-summary").textContent = people.summary || "";
    document.getElementById("people-body").innerHTML = people.stats.map(s => `
      <tr>
        <td>${s.person}${s.at_risk ? " ⚠️" : ""}</td>
        <td>${s.committed}</td>
        <td>${s.on_time}</td>
        <td>${s.missed}</td>
        <td>${Math.round(s.follow_through_rate * 100)}%</td>
      </tr>
    `).join("");
  } catch (e) {
    toast("Failed to load people report: " + e.message, true);
  }

  try {
    const meetings = await api("/report/meetings");
    document.getElementById("meetings-body").innerHTML = meetings.meetings.map(m => `
      <tr>
        <td>${m.title}</td>
        <td>${m.total_commitments}</td>
        <td>${m.completed || 0}</td>
        <td>${m.missed || 0}</td>
        <td>${Math.round(m.debt_score * 100)}%${m.suggest_async ? " · consider async" : ""}</td>
      </tr>
    `).join("");
  } catch (e) {
    toast("Failed to load meeting report: " + e.message, true);
  }
}
document.getElementById("refresh-reports").addEventListener("click", loadReports);

// ---------------------------------------------------------------------------
// Simulate / clock

document.getElementById("advance-clock").addEventListener("click", async () => {
  const hours = parseFloat(document.getElementById("advance-hours").value || "24");
  try {
    const data = await api(`/simulate?advance_hours=${hours}`, { method: "POST" });
    document.getElementById("agent-now").textContent = data.agent_now;
    document.getElementById("simulate-log").textContent = data.message;
    toast(data.message);
    loadCommitments();
  } catch (e) {
    toast("Simulate failed: " + e.message, true);
  }
});

document.getElementById("reset-clock").addEventListener("click", async () => {
  try {
    const data = await api("/simulate/reset");
    document.getElementById("agent-now").textContent = data.reset_to;
    toast("Clock reset to real time.");
  } catch (e) {
    toast("Reset failed: " + e.message, true);
  }
});

// ---------------------------------------------------------------------------
// Init

loadMeetingsFromServer();
loadCommitments();
