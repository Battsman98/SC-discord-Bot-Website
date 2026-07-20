window.addEventListener("message", (event) => {
  if (event.source !== window || event.data?.direction !== "from-game-assist-rsi") return;
  chrome.runtime.sendMessage(event.data.message, (response) => {
    window.postMessage({
      direction: "from-game-assist-rsi-connect",
      requestId: event.data.requestId,
      message: response,
    }, window.location.origin);
  });
});
