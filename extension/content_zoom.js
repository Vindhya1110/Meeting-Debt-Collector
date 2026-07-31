// content_zoom.js — Zoom caption selectors
window.MDC_PLATFORM = "zoom";

window.MDC_SELECTORS = {
  caption: [
    '.caption-line',
    '[class*="caption-line"]',
    '.live-transcription-subtitle',
    '[aria-label*="caption"] span',
    '.zmwebsdk-MuiTypography-root'
  ],
  speaker: [
    '.speaker-name',
    '[class*="speaker-name"]',
    '.live-transcription-speaker-name'
  ]
};

MDC.enableCaptions = function () {
  const ccBtn = document.querySelector(
    '[aria-label="Show Captions"],[aria-label*="Caption"],[id*="caption"]'
  );
  if (ccBtn) { ccBtn.click(); console.log("[MDC] Auto-enabled Zoom captions"); }
};

MDC.detectAttendees = function () {
  const names = new Set();
  document.querySelectorAll('[class*="participant-item"] [class*="display-name"]')
    .forEach(el => { if (el.textContent.trim()) names.add(el.textContent.trim()); });
  return names.size > 0
    ? [...names].map(n => ({ name: n }))
    : [{ name: "Participant 1" }, { name: "Participant 2" }];
};

MDC.init();
