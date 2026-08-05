async function rsiHTMLGet(url) {
  const response = await fetch(url, {
    method: "GET",
    credentials: "include",
    headers: {
      "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "accept-language": "en-US,en;q=0.9",
      "cache-control": "max-age=0"
    },
    signal: AbortSignal.timeout(20000)
  });
  return { code: response.status, payload: await response.text(), url: response.url };
}

function cleanShipName(value) {
  let name = String(value || "").replace(/[-_]+/g, " ").replace(/\s+/g, " ").trim();
  name = name.replace(/^(?:Standalone Ship|Game Package|Package|Ship)\s*[-:]?\s*/i, "");
  name = name.replace(/\b(?:with Lifetime Insurance|Lifetime Insurance|Warbond|Best In Show|BIS|ILW|IAE|LTI)\b.*$/i, "").trim();
  if (name.length < 2 || name.length > 72 || name.split(" ").length > 10) return null;
  const blocked = /\b(?:upgrade|paint|skin|flair|poster|plushie|figurine|gift card|coupon|currency|insurance|hangar|downloadable|weapon|armor)\b|\bto\b.*\b(?:year|insurance)\b|\b\d+\s*year\b/i;
  return blocked.test(name) ? null : name;
}

function htmlText(value) {
  return String(value || "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#(?:39|x27);/gi, "'")
    .replace(/\s+/g, " ")
    .trim();
}

function extractTypedItemShips(pageHTML) {
  const candidates = new Set();
  const kindPattern = /class=["'][^"']*\bkind\b[^"']*["'][^>]*>([\s\S]{0,240}?)<\/[^>]+>/gi;
  const titlePattern = /class=["'][^"']*\btitle\b[^"']*["'][^>]*>([\s\S]{0,240}?)<\/[^>]+>/gi;
  for (const kind of pageHTML.matchAll(kindPattern)) {
    if (!/^\s*(?:ship|vehicle)\s*$/i.test(htmlText(kind[1]))) continue;
    const kindIndex = kind.index || 0;
    const before = pageHTML.slice(Math.max(0, kindIndex - 900), kindIndex);
    const after = pageHTML.slice(kindIndex + kind[0].length, kindIndex + kind[0].length + 900);
    const precedingTitles = [...before.matchAll(titlePattern)];
    const title = precedingTitles.at(-1) || [...after.matchAll(titlePattern)][0];
    if (!title) continue;
    const cleaned = cleanShipName(htmlText(title[1]));
    if (cleaned) candidates.add(cleaned);
  }
  return candidates;
}

function extractShipCandidates(pageHTML) {
  return [...extractTypedItemShips(pageHTML)];
}

function pledgePageCount(pageHTML) {
  let count = 1;
  for (const match of String(pageHTML || "").matchAll(/[?&]page=(\d{1,3})/gi)) {
    count = Math.max(count, Number(match[1]) || 1);
  }
  return Math.min(25, count);
}

async function importHangar(reportProgress = () => {}) {
  const candidates = new Set();
  let finalURL = "";
  let firstPageHTML = "";
  let response;
  try {
    response = await rsiHTMLGet("https://robertsspaceindustries.com/account/pledges");
  } catch (_error) {
    return { code: 504, error: "RSI pledge page 1 timed out. Reload RSI and try again." };
  }
  finalURL = response.url || finalURL;
  firstPageHTML = response.payload;
  if (response.code !== 200) {
    return { code: response.code, error: "RSI did not return pledge page 1. Confirm that you are signed in." };
  }
  for (const name of extractShipCandidates(response.payload)) candidates.add(name);
  const totalPages = Math.max(1, pledgePageCount(response.payload));
  reportProgress({ page: 1, totalPages, candidates: candidates.size });

  let completedPages = 1;
  const remainingPages = Array.from({ length: totalPages - 1 }, (_, index) => index + 2);
  const pageResults = await Promise.all(remainingPages.map(async (page) => {
    try {
      const pageResponse = await rsiHTMLGet(`https://robertsspaceindustries.com/account/pledges?page=${page}`);
      if (pageResponse.code !== 200) {
        return { page, error: `RSI returned ${pageResponse.code} for pledge page ${page}.` };
      }
      for (const name of extractShipCandidates(pageResponse.payload)) candidates.add(name);
      completedPages += 1;
      reportProgress({ page: completedPages, totalPages, candidates: candidates.size });
      return { page };
    } catch (_error) {
      return { page, error: `RSI pledge page ${page} timed out.` };
    }
  }));
  const failedPage = pageResults.find((result) => result.error);
  if (failedPage) {
    return { code: 504, error: `${failedPage.error} Reload RSI and try again.` };
  }
  if (!candidates.size) {
    const signedOut = /(?:sign in|log in|login)/i.test(finalURL) || /(?:sign in|log in to your account)/i.test(firstPageHTML);
    return {
      code: 422,
      error: signedOut
        ? "RSI redirected to sign-in. Sign into RSI in this Chrome profile, then try again."
        : "RSI returned the hangar page, but no ship records were recognized. Reload the extension and report this message so the parser can be updated."
    };
  }
  return { code: 200, candidates: [...candidates].sort((a, b) => a.localeCompare(b)) };
}

const ALLOWED_WEBSITE_ORIGINS = new Set([
  "https://sccompanion.org",
  "https://star-citizen-game-assist.onrender.com",
  "http://127.0.0.1:8000",
  "http://localhost:8000"
]);

chrome.runtime.onMessage.addListener((rawMessage, sender, sendResponse) => {
  let senderOrigin = "";
  try {
    senderOrigin = new URL(sender.url || "").origin;
  } catch (_error) {
    sendResponse(JSON.stringify({ code: 403, error: "Unrecognized website origin." }));
    return false;
  }
  if (!ALLOWED_WEBSITE_ORIGINS.has(senderOrigin)) {
    sendResponse(JSON.stringify({ code: 403, error: "Website origin is not allowed." }));
    return false;
  }
  let requestId = "";
  try {
    requestId = String(JSON.parse(rawMessage || "{}").requestId || "");
  } catch (_error) {}
  const reportProgress = (progress) => {
    if (!sender.tab?.id || !requestId) return;
    chrome.tabs.sendMessage(sender.tab.id, {
      direction: "from-game-assist-rsi-progress",
      requestId,
      progress,
    }).catch(() => {});
  };
  handleMessage(rawMessage, reportProgress).then((response) => {
    sendResponse(JSON.stringify(response));
  }).catch((error) => {
    sendResponse(JSON.stringify({ code: 500, error: String(error?.message || error) }));
  });
  return true;
});

async function handleMessage(rawMessage, reportProgress = () => {}) {
  const message = JSON.parse(rawMessage || "{}");
  if (message.action === "connect") {
    return { code: 200, version: "0.4.8", scope: "ships-and-vehicles-only" };
  }
  if (message.action === "importHangar") {
    return await importHangar(reportProgress);
  }
  return { code: 400, error: "Unknown action." };
}
