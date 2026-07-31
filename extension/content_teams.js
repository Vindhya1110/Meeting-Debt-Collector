// content_teams.js — Microsoft Teams caption selectors
window.MDC_PLATFORM = "microsoft_teams";

window.MDC_SELECTORS = {
  caption: [
    '[data-tid="closed-captions-renderer"] span',
    '.ts-captions-container span',
    '[class*="caption"] span',
    '[aria-label*="caption"]',
    '.fui-Caption1'
  ],
  speaker: [
    '[data-tid="closed-captions-renderer-speaker"]',
    '.ts-captions-speaker',
    '[class*="captionSpeaker"]'
  ]
};

MDC.enableCaptions = function () {
  const ccBtn = document.querySelector(
    '[data-tid="toggle-captions"],[aria-label*="captions"],[aria-label*="Captions"]'
  );
  if (ccBtn) { ccBtn.click(); console.log("[MDC] Auto-enabled Teams captions"); }
};

MDC.detectAttendees = function () {
  const names = new Set();
  document.querySelectorAll('[data-tid*="participant"] [class*="name"]')
    .forEach(el => { if (el.textContent.trim()) names.add(el.textContent.trim()); });
  return names.size > 0
    ? [...names].map(n => ({ name: n }))
    : [{ name: "Participant 1" }, { name: "Participant 2" }];
};

MDC.init();
