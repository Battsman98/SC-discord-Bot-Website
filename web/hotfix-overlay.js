(() => {
  const DISPLAY_MS = 20_000;
  const USER_ATTEMPT_MS = 60_000;
  const originalFetch = fetch.bind(globalThis);
  let userAttemptUntil = 0;
  let closeTimer = null;
  let overlay = null;
  let previouslyFocused = null;

  function markUserAttempt(event) {
    const target = event.target instanceof Element ? event.target : null;
    if (event.type === "submit" || target?.closest("button, [role='button'], .button-link")) userAttemptUntil = Date.now() + USER_ATTEMPT_MS;
  }

  function buildOverlay() {
    if (overlay) return overlay;
    overlay = document.createElement("div");
    overlay.className = "hotfix-overlay";
    overlay.hidden = true;
    overlay.innerHTML = `
      <section class="hotfix-dialog" role="dialog" aria-modal="true" aria-labelledby="hotfixMessage">
        <button class="hotfix-close" type="button" aria-label="Close potential hot-fix notice">&times;</button>
        <div class="hotfix-wheel-stage" role="img" aria-label="System recovery in progress">
          <div class="hotfix-wheel" aria-hidden="true"><span></span></div>
          <p>Re-routing services</p>
        </div>
        <p class="hotfix-message" id="hotfixMessage">Potential Hot-Fix coming</p>
        <p class="hotfix-dismiss-note">Closes automatically in 20 seconds. Click outside to dismiss.</p>
      </section>`;
    document.body.append(overlay);
    overlay.querySelector(".hotfix-close").addEventListener("click", hidePotentialHotfix);
    overlay.addEventListener("click", (event) => { if (event.target === overlay) hidePotentialHotfix(); });
    return overlay;
  }

  function showPotentialHotfix() {
    const element = buildOverlay();
    previouslyFocused = document.activeElement;
    window.clearTimeout(closeTimer);
    element.hidden = false;
    element.querySelector(".hotfix-close").focus();
    closeTimer = window.setTimeout(hidePotentialHotfix, DISPLAY_MS);
  }

  function hidePotentialHotfix() {
    if (!overlay || overlay.hidden) return;
    window.clearTimeout(closeTimer);
    closeTimer = null;
    overlay.hidden = true;
    previouslyFocused?.focus?.();
  }

  document.addEventListener("submit", markUserAttempt, true);
  document.addEventListener("click", markUserAttempt, true);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") hidePotentialHotfix(); });
  document.addEventListener("hotfix:show", showPotentialHotfix);
  document.addEventListener("hotfix:hide", hidePotentialHotfix);
  window.SCCompanionHotfix = Object.freeze({ show: showPotentialHotfix, hide: hidePotentialHotfix });
  window.fetch = async (...args) => {
    try {
      const response = await originalFetch(...args);
      if (Date.now() <= userAttemptUntil && !response.ok) showPotentialHotfix();
      return response;
    } catch (error) {
      if (Date.now() <= userAttemptUntil) showPotentialHotfix();
      throw error;
    }
  };
})();
