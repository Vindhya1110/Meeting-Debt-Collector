let isCapturing = false;

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

async function sendToContent(msg) {
  const tab = await getMeetTab();
  if (!tab) {
    setStatus("No active meeting tab found. Join a call first.");
    return null;
  }
  try {
    return await chrome.tabs.sendMessage(tab.id, msg);
  } catch (e) {
    setStatus("Cannot reach content script. Refresh the meeting tab.");
    return null;
  }
}

document.getElementById("startBtn").addEventListener("click", async () => {
  const meetTitle = document.getElementById("meetTitle").value.trim();
  const meetType = document.getElementById("meetType").value;
  const preBrief = document.getElementById("preBrief").value.trim();

  setStatus("Starting...");
  const result = await sendToContent({
    type: "START_CAPTURE", meetTitle, meetType, preBrief
  });

  if (result?.ok) {
    isCapturing = true;
    updateUI();
    setStatus("Live! Notion page created.");
  } else {
    setStatus("Failed to start. Is the agent running? (localhost:8000)");
  }
});

document.getElementById("stopBtn").addEventListener("click", async () => {
  setStatus("Saving to Notion...");
  const result = await sendToContent({ type: "STOP_CAPTURE" });
  if (result?.ok) {
    isCapturing = false;
    updateUI();
    setStatus("Saved! Check Notion for the report.");
  }
});

function updateUI() {
  document.getElementById("badge").textContent = isCapturing ? "● Capturing live" : "Not capturing";
  document.getElementById("badge").className = `badge ${isCapturing ? "on" : "off"}`;
  document.getElementById("setup-section").style.display = isCapturing ? "none" : "block";
  document.getElementById("live-section").style.display = isCapturing ? "block" : "none";
}

function setStatus(msg) {
  document.getElementById("status-msg").textContent = msg;
}

async function pollState() {
  try {
    const state = await chrome.runtime.sendMessage({ type: "GET_STATE" });
    if (state?.isCapturing !== undefined) {
      isCapturing = state.isCapturing;
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
  const state = await chrome.runtime.sendMessage({ type: "GET_STATE" }).catch(() => null);
  if (state?.isCapturing) { isCapturing = true; updateUI(); }
  setInterval(pollState, 1000);
})();
