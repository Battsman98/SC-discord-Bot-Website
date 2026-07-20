async function rsiHTMLGet(url) {
  const response = await fetch(url, {
    method: "GET",
    credentials: "include",
    headers: {
      "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "accept-language": "en-US,en;q=0.9",
      "cache-control": "max-age=0"
    }
  });
  return { code: response.status, payload: await response.text(), url: response.url };
}

function cleanShipName(value) {
  let name = String(value || "").replace(/[-_]+/g, " ").replace(/\s+/g, " ").trim();
  name = name.replace(/^(?:Standalone Ship|Game Package|Package|Ship)\s*[-:]?\s*/i, "");
  name = name.replace(/\b(?:with Lifetime Insurance|Lifetime Insurance|Warbond|Best In Show|BIS|ILW|IAE|LTI)\b.*$/i, "").trim();
  if (name.length < 2 || name.length > 72 || name.split(" ").length > 10) return null;
  const blocked = /\b(?:upgrade|paint|skin|flair|poster|plushie|figurine|gift card|coupon|currency|insurance|hangar|downloadable|weapon|armor)\b/i;
  return blocked.test(name) ? null : name;
}

function extractShipCandidates(pageHTML) {
  const candidates = new Set();
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
  const containedShips = /(?:Contains|Also Contains)\s+([^$<>]{2,120}?)(?=\s+(?:Also Contains|Attributed|Created|Serial|Insurance|Starting Money|Hangar|Downloadable|Contains|$))/gi;
  for (const match of plainText.matchAll(containedShips)) {
    const cleaned = cleanShipName(match[1]);
    if (cleaned) candidates.add(cleaned);
  }
  return [...candidates];
}

function pledgePageHasNext(pageHTML, page) {
  return pageHTML.includes(`page=${page + 1}`) || pageHTML.includes(`>${page + 1}<`);
}

async function importHangar() {
  const candidates = new Set();
  let finalURL = "";
  let firstPageHTML = "";
  for (let page = 1; page <= 25; page += 1) {
    const suffix = page > 1 ? `?page=${page}` : "";
    const response = await rsiHTMLGet(`https://robertsspaceindustries.com/account/pledges${suffix}`);
    finalURL = response.url || finalURL;
    if (page === 1) firstPageHTML = response.payload;
    if (response.code !== 200) {
      return { code: response.code, error: "RSI did not return the pledge page. Confirm that you are signed in." };
    }
    for (const name of extractShipCandidates(response.payload)) candidates.add(name);
    if (!pledgePageHasNext(response.payload, page)) break;
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
  handleMessage(rawMessage).then((response) => {
    sendResponse(JSON.stringify(response));
  }).catch((error) => {
    sendResponse(JSON.stringify({ code: 500, error: String(error?.message || error) }));
  });
  return true;
});

async function handleMessage(rawMessage) {
  const message = JSON.parse(rawMessage || "{}");
  if (message.action === "connect") {
    return { code: 200, version: "0.4.1", scope: "ships-and-vehicles-only" };
  }
  if (message.action === "importHangar") {
    return await importHangar();
  }
  return { code: 400, error: "Unknown action." };
}
