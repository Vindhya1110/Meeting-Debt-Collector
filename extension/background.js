// background.js — service worker
let state = {
  isCapturing: false,
  meetingId: null,
  platform: null,
  chunksSent: 0,
  commitments: 0,
};

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "CAPTURE_STARTED") {
    state.isCapturing = true;
    state.meetingId = msg.meetingId;
    state.platform = msg.platform;
    state.chunksSent = 0;
    state.commitments = 0;
    chrome.action.setBadgeText({ text: "●" });
    chrome.action.setBadgeBackgroundColor({ color: "#1D9E75" });
  }

  if (msg.type === "CAPTURE_STOPPED") {
    state.isCapturing = false;
    chrome.action.setBadgeText({ text: "" });
  }

  if (msg.type === "CHUNK_SENT") {
    state.chunksSent++;
    state.commitments += msg.result?.commitments_this_chunk || 0;
    chrome.action.setBadgeText({ text: String(state.commitments) || "●" });
  }

  if (msg.type === "NEW_CAPTION") {
    chrome.storage.session.get("captions", d => {
      const list = (d.captions || []).slice(-10);
      list.push(msg.entry);
      chrome.storage.session.set({ captions: list });
    });
  }

  if (msg.type === "GET_STATE") {
    sendResponse(state);
  }
});
