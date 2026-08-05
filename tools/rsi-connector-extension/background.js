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
  const itemStart = /<[^>]+class=["'][^"']*\bitem\b[^"']*["'][^>]*>/gi;
  const starts = [...pageHTML.matchAll(itemStart)].map((match) => match.index);
  for (let index = 0; index < starts.length; index += 1) {
    const block = pageHTML.slice(starts[index], Math.min(starts[index + 1] || pageHTML.length, starts[index] + 2400));
    const kind = block.match(/class=["'][^"']*\bkind\b[^"']*["'][^>]*>([\s\S]{0,240}?)<\/[^>]+>/i);
    const title = block.match(/class=["'][^"']*\btitle\b[^"']*["'][^>]*>([\s\S]{0,240}?)<\/[^>]+>/i);
    if (!kind || !title || !/\b(?:ship|vehicle)\b/i.test(htmlText(kind[1]))) continue;
    const cleaned = cleanShipName(htmlText(title[1]));
    if (cleaned) candidates.add(cleaned);
  }
  return candidates;
}

function extractShipCandidates(pageHTML) {
  const candidates = new Set();
  for (const name of extractTypedItemShips(pageHTML)) candidates.add(name);
  for (const tag of pageHTML.match(/<input\b[^>]*>/gi) || []) {
    const className = tag.match(/\bclass=["']([^"']*)["']/i)?.[1] || "";
    if (!/\bjs-pledge-name\b/i.test(className)) continue;
    const value = tag.match(/\bvalue=["']([^"']+)["']/i)?.[1];
    const cleaned = cleanShipName(htmlText(value));
    if (cleaned) candidates.add(cleaned);
  }
  const titled = /["'](?:name|title|label)["']\s*:\s*["']((?:Standalone Ship|Game Package|Package)\s*(?:[-:]|\s)[^"']{2,120})["']/gi;
  for (const match of pageHTML.matchAll(titled)) {
    const cleaned = cleanShipName(match[1]);
    if (cleaned) candidates.add(cleaned);
  }
  const shipLinks = /\/pledge\/ships\/[^"'<> ]+\/([^"'<>?#]+)/gi;
  for (const match of pageHTML.matchAll(shipLinks)) {
    const cleaned = cleanShipName(decodeURIComponent(match[1]));
    if (cleaned) candidates.add(cleaned);
  }
  const plainText = pageHTML.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ");
  const blocks = /(?:Standalone Ship|Game Package|Package)\s*[-:]?\s*([^$<>]{2,120}?)(?=\s+(?:Attributed|Created|Serial|Insurance|Contains|$))/gi;
  for (const match of plainText.matchAll(blocks)) {
    const cleaned = cleanShipName(match[1]);
    if (cleaned) candidates.add(cleaned);
  }
  const containedShips = /(?:Contains|Also Contains)\s*:?\s+([^$<>]{2,120}?)(?=\s+(?:Also Contains|Attributed|Created|Serial|Insurance|Starting Money|Hangar|Downloadable|Contains|$))/gi;
  for (const match of plainText.matchAll(containedShips)) {
    const cleaned = cleanShipName(match[1]);
    if (cleaned) candidates.add(cleaned);
  }
  return [...candidates];
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
    return { code: 200, version: "0.4.7", scope: "ships-and-vehicles-only" };
  }
  if (message.action === "importHangar") {
    return await importHangar(reportProgress);
  }
  return { code: 400, error: "Unknown action." };
}
