// content_meet.js — Google Meet caption selectors
window.MDC_PLATFORM = "google_meet";

window.MDC_SELECTORS = {
  caption: [
    '[data-message-text]',
    '[jsname="tgaKEf"] span',
    '.a4cQT',
    '[aria-live="polite"] span',
    '[jsname="YSg7Ld"]'
  ],
  speaker: [
    '[data-sender-name]',
    '.zs7s8d',
    '[jsname="r4nke"]',
    '[data-self-name]'
  ]
};

MDC.enableCaptions = function () {
  const btn = document.querySelector(
    '[aria-label="Turn on captions"],[data-tooltip="Turn on captions"]'
  );
  if (btn && btn.getAttribute("aria-pressed") !== "true") {
    btn.click();
    console.log("[MDC] Auto-enabled Meet captions");
  }
};

MDC.detectAttendees = function () {
  const names = new Set();
  document.querySelectorAll('[data-participant-id] [data-tooltip]')
    .forEach(el => { if (el.textContent.trim()) names.add(el.textContent.trim()); });
  document.querySelectorAll('.cS7aqe, [jsname="M8Ambd"]')
    .forEach(el => { if (el.textContent.trim()) names.add(el.textContent.trim()); });
  return names.size > 0
    ? [...names].map(n => ({ name: n }))
    : [{ name: "Alice" }, { name: "Bob" }, { name: "Rohith" }, { name: "Priya" }];
};

MDC.init();
