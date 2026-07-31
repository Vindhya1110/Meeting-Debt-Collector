// content_common.js
// Shared caption processing logic for all meeting platforms.
// Each platform-specific file sets window.MDC_PLATFORM and window.MDC_SELECTORS,
// then calls MDC.init()

window.MDC = window.MDC || {};

MDC.AGENT_URL = "http://localhost:8000";
MDC.CHUNK_EVERY = 30000;    // ms
MDC.POLL_MS = 500;

MDC.state = {
  meetingId: null,
  isCapturing: false,
  buffer: [],
  lastSeen: "",
  chunkIndex: 0,
  chunkTimer: null,
  pollTimer: null,
};

MDC.init = function () {
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === "START_CAPTURE") {
      MDC.startCapture(msg.meetTitle, msg.meetType, msg.preBrief)
        .then(r => sendResponse(r));
      return true;
    }
    if (msg.type === "STOP_CAPTURE") {
      MDC.stopCapture().then(r => sendResponse(r));
      return true;
    }
    if (msg.type === "GET_STATUS") {
      sendResponse({
        isCapturing: MDC.state.isCapturing,
        meetingId: MDC.state.meetingId,
        bufferSize: MDC.state.buffer.length,
        chunksSent: MDC.state.chunkIndex,
      });
    }
  });

  window.addEventListener("beforeunload", () => {
    if (MDC.state.isCapturing) MDC.stopCapture();
  });

  console.log(`[MDC] Loaded on ${window.MDC_PLATFORM || "unknown"}`);
};

MDC.startCapture = async function (meetTitle, meetType, preBrief) {
  if (MDC.enableCaptions) MDC.enableCaptions();

  const attendees = MDC.detectAttendees ? MDC.detectAttendees() : [];

  try {
    const resp = await fetch(`${MDC.AGENT_URL}/meetings/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: meetTitle || document.title || "Meeting",
        type: meetType || "club_meeting",
        platform: window.MDC_PLATFORM || "unknown",
        owner: attendees[0]?.name || "Unknown",
        attendees: attendees,
        pre_brief: preBrief || ""
      })
    });
    const data = await resp.json();
    MDC.state.meetingId = data.meeting_id;
  } catch (e) {
    console.error("[MDC] Failed to start meeting:", e);
    return { ok: false, error: e.message };
  }

  MDC.state.isCapturing = true;
  MDC.state.buffer = [];
  MDC.state.lastSeen = "";
  MDC.state.chunkIndex = 0;

  MDC.state.pollTimer = setInterval(MDC.poll, MDC.POLL_MS);
  MDC.state.chunkTimer = setInterval(MDC.sendChunk, MDC.CHUNK_EVERY);

  chrome.runtime.sendMessage({
    type: "CAPTURE_STARTED",
    meetingId: MDC.state.meetingId,
    platform: window.MDC_PLATFORM
  });

  return { ok: true, meetingId: MDC.state.meetingId };
};

MDC.stopCapture = async function () {
  MDC.state.isCapturing = false;
  clearInterval(MDC.state.pollTimer);
  clearInterval(MDC.state.chunkTimer);

  await MDC.sendChunk();  // flush remaining buffer

  if (!MDC.state.meetingId) {
    chrome.runtime.sendMessage({ type: "CAPTURE_STOPPED" });
    return { ok: false, error: "No active meeting ID — nothing to finalize." };
  }

  // IMPORTANT: this must complete BEFORE you leave the Meet call or close the
  // tab — if the page navigates away mid-request, the fetch is killed and
  // /end never reaches the server, leaving the meeting stuck as "active"
  // with no MoM ever generated. Stay on the call until this resolves.
  try {
    const resp = await fetch(`${MDC.AGENT_URL}/meetings/${MDC.state.meetingId}/end`,
      { method: "POST" });
    if (!resp.ok) {
      const body = await resp.text().catch(() => "");
      console.error(`[MDC] Finalize failed: HTTP ${resp.status} ${body}`);
      chrome.runtime.sendMessage({ type: "CAPTURE_STOPPED" });
      return { ok: false, error: `Agent returned HTTP ${resp.status}` };
    }
  } catch (e) {
    console.error("[MDC] Finalize failed (network/interrupted):", e);
    chrome.runtime.sendMessage({ type: "CAPTURE_STOPPED" });
    return { ok: false, error: "Request failed or was interrupted (e.g. tab closed too soon): " + e.message };
  }

  chrome.runtime.sendMessage({ type: "CAPTURE_STOPPED" });
  return { ok: true };
};

MDC.poll = function () {
  if (!MDC.state.isCapturing) return;

  let text = "";
  let speaker = "Unknown";
  let matchedSelector = null;

  for (const sel of (window.MDC_SELECTORS?.caption || [])) {
    const el = document.querySelector(sel);
    if (el?.textContent?.trim()) { text = el.textContent.trim(); matchedSelector = sel; break; }
  }
  for (const sel of (window.MDC_SELECTORS?.speaker || [])) {
    const el = document.querySelector(sel);
    if (el?.textContent?.trim()) { speaker = el.textContent.trim(); break; }
  }

  // Every ~10s (roughly 20 polls at 500ms), log whether ANY caption selector
  // is matching anything at all — the single most useful signal for
  // diagnosing "nothing got captured" without spamming the console every poll.
  MDC._pollCount = (MDC._pollCount || 0) + 1;
  if (MDC._pollCount % 20 === 0) {
    if (matchedSelector) {
      console.log(`[MDC] caption selector "${matchedSelector}" is matching text on the page.`);
    } else {
      console.warn("[MDC] no caption selector matched anything. Are Meet's captions (CC) turned on? " +
                   "If yes, Meet's DOM has likely changed — inspect the caption text on screen and update content_meet.js's MDC_SELECTORS.caption list.");
    }
  }

  // Real captions are phrases, not single words. The generic aria-live
  // fallback selectors can match unrelated UI (toasts, date/time widgets,
  // etc.) that happens to share the same accessibility pattern — reject
  // anything implausibly short rather than polluting the transcript with
  // noise like a stray "July".
  const MIN_CAPTION_LENGTH = 8;
  if (text && text.length < MIN_CAPTION_LENGTH) {
    console.warn(`[MDC] rejected short match from "${matchedSelector}": "${text}" ` +
                 `(likely not real captions — probably matched the wrong element)`);
    return;
  }

  if (!text || text === MDC.state.lastSeen) return;
  MDC.state.lastSeen = text;

  const entry = { speaker, text, ts: Date.now() };
  MDC.state.buffer.push(entry);

  chrome.runtime.sendMessage({
    type: "NEW_CAPTION", entry,
    meetingId: MDC.state.meetingId
  });
};

MDC.sendChunk = async function () {
  if (!MDC.state.buffer.length || !MDC.state.meetingId) return;

  const chunk = MDC.state.buffer
    .map(e => `[${new Date(e.ts).toLocaleTimeString()}] ${e.speaker}: ${e.text}`)
    .join("\n");
  MDC.state.buffer = [];

  try {
    const resp = await fetch(
      `${MDC.AGENT_URL}/meetings/${MDC.state.meetingId}/chunk`,
      {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chunk, chunk_index: MDC.state.chunkIndex++ })
      }
    );
    const data = await resp.json();
    chrome.runtime.sendMessage({ type: "CHUNK_SENT", result: data });
  } catch (e) {
    console.error("[MDC] Chunk send failed:", e);
  }
};
