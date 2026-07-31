const AGENT_URL = "http://localhost:8000";

let isCapturing = false;
let captureStartedAt = null;

async function getMeetTab() {
  const patterns = [
    "https://meet.google.com/*",
    "https://*.zoom.us/wc/*",
    "https://*.zoom.us/j/*",
    "https://teams.microsoft.com/*",
    "https://teams.live.com/*"
  ];
  for (const p of patterns) {
    const tabs = await chrome.tabs.query({ url: p });
    if (tabs.length) return tabs[0];
  }
  return null;
}

async function checkAgentHealth() {
  const el = document.getElementById("agent-status");
  const startBtn = document.getElementById("startBtn");
  try {
    const resp = await fetch(`${AGENT_URL}/health`, { signal: AbortSignal.timeout(4000) });
    if (!resp.ok) throw new Error(`status ${resp.status}`);
    el.textContent = "✓ Agent connected (localhost:8000)";
    el.className = "agent-status ok";
    if (startBtn) startBtn.disabled = false;
    return true;
  } catch (e) {
    el.textContent = "✗ Agent NOT reachable — start the backend first (uvicorn main:app --port 8000)";
    el.className = "agent-status down";
    if (startBtn) startBtn.disabled = true;
    return false;
  }
}

async function sendToContent(msg) {
  const tab = await getMeetTab();
  if (!tab) {
    setStatus("No active meeting tab found. Join a call first.");
    return null;
  }
  try {
    return await chrome.tabs.sendMessage(tab.id, msg);
  } catch (e) {
    setStatus("Cannot reach content script. Refresh the meeting tab and try again.");
    return null;
  }
}

document.getElementById("startBtn").addEventListener("click", async () => {
  const agentUp = await checkAgentHealth();
  if (!agentUp) {
    setStatus("Agent is not reachable — start it before capturing.");
    return;
  }

  const meetTitle = document.getElementById("meetTitle").value.trim();
  const meetType = document.getElementById("meetType").value;
  const preBrief = document.getElementById("preBrief").value.trim();

  setStatus("Starting...");
  const result = await sendToContent({
    type: "START_CAPTURE", meetTitle, meetType, preBrief
  });

  if (result?.ok) {
    isCapturing = true;
    captureStartedAt = Date.now();
    updateUI();
    document.getElementById("meeting-id-line").textContent = `meeting: ${result.meetingId || "?"}`;
    setStatus("Live! Meeting created — check Notion for the meeting page now.");
  } else {
    setStatus(`Failed to start${result?.error ? ": " + result.error : ""}. Check the Meet tab's console (F12) for [MDC] errors.`);
  }
});

document.getElementById("stopBtn").addEventListener("click", async () => {
  setStatus("Saving to Notion — stay on this call until this finishes...");
  const result = await sendToContent({ type: "STOP_CAPTURE" });
  // Whether it succeeded or not, capture is over on the client side — don't
  // leave the UI stuck showing the live view for a meeting that already
  // stopped polling.
  isCapturing = false;
  captureStartedAt = null;
  updateUI();
  if (result?.ok) {
    setStatus("Saved! Check Notion for the report.");
  } else {
    setStatus(`Save failed${result?.error ? ": " + result.error : ""}. ` +
              `The meeting may be stuck without a summary — tell your admin the meeting ID so it can be finalized manually.`);
  }
});

function updateUI() {
  document.getElementById("badge").textContent = isCapturing ? "● Capturing live" : "Not capturing";
  document.getElementById("badge").className = `badge ${isCapturing ? "on" : "off"}`;
  document.getElementById("setup-section").style.display = isCapturing ? "none" : "block";
  document.getElementById("live-section").style.display = isCapturing ? "block" : "none";
  if (!isCapturing) {
    document.getElementById("no-captions-warning").style.display = "none";
  }
}

function setStatus(msg) {
  document.getElementById("status-msg").textContent = msg;
}

async function pollState() {
  try {
    const state = await chrome.runtime.sendMessage({ type: "GET_STATE" });
    if (state?.isCapturing !== undefined) {
      const wasCapturing = isCapturing;
      isCapturing = state.isCapturing;
      if (isCapturing && !wasCapturing) captureStartedAt = Date.now();
      updateUI();
    }
    if (state) {
      document.getElementById("chunkCount").textContent = state.chunksSent || 0;
      document.getElementById("commitCount").textContent = state.commitments || 0;
      const pb = document.getElementById("platform-badge");
      if (state.platform) {
        pb.textContent = state.platform.replace("_", " ");
        pb.style.display = "inline";
      }

      // If we've been capturing for over a chunk interval with zero chunks
      // sent, no captions have ever been detected — surface that clearly
      // instead of leaving the user staring at a silent "Listening..." feed.
      const warning = document.getElementById("no-captions-warning");
      if (isCapturing && captureStartedAt &&
          (Date.now() - captureStartedAt > 35000) &&
          (state.chunksSent || 0) === 0) {
        warning.style.display = "block";
      } else {
        warning.style.display = "none";
      }
    }

    const d = await chrome.storage.session.get("captions");
    const captions = (d.captions || []).slice(-5).reverse();
    if (captions.length) {
      document.getElementById("captionFeed").innerHTML = captions
        .map(c => `<div class="caption-line">
                     <span class="speaker">${c.speaker}:</span> ${c.text}
                   </div>`)
        .join("");
    }
  } catch (e) { }
}

(async () => {
  await checkAgentHealth();
  const state = await chrome.runtime.sendMessage({ type: "GET_STATE" }).catch(() => null);
  if (state?.isCapturing) { isCapturing = true; captureStartedAt = Date.now(); updateUI(); }
  setInterval(pollState, 1000);
  setInterval(checkAgentHealth, 5000);
})();
