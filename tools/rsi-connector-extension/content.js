window.addEventListener("message", (event) => {
  if (event.source !== window || event.data?.direction !== "from-game-assist-rsi") return;
  let message = {};
  try {
    message = JSON.parse(event.data.message || "{}");
  } catch (_error) {}
  message.requestId = event.data.requestId;
  chrome.runtime.sendMessage(JSON.stringify(message), (response) => {
    window.postMessage({
      direction: "from-game-assist-rsi-connect",
      requestId: event.data.requestId,
      message: response,
    }, window.location.origin);
  });
});

chrome.runtime.onMessage.addListener((message) => {
  if (message?.direction !== "from-game-assist-rsi-progress") return;
  window.postMessage(message, window.location.origin);
});
