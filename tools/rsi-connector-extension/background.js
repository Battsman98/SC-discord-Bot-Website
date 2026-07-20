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
  return { code: response.status, payload: await response.text() };
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
    return { code: 200, version: "0.3.1", scope: "ships-and-vehicles-only" };
  }
  if (message.action === "getPledgesPage") {
    const page = Number(message.page || 1);
    if (!Number.isInteger(page) || page < 1 || page > 25) {
      return { code: 400, error: "Invalid pledge page." };
    }
    return await rsiHTMLGet(`https://robertsspaceindustries.com/en/account/pledges?page=${page}&product-type=`);
  }
  return { code: 400, error: "Unknown action." };
}
