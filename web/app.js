const userPanel = document.querySelector("#userPanel");
const loadingTemplate = document.querySelector("#loadingTemplate");

const outputs = {
  lookup: document.querySelector("#lookupOutput"),
  savedShips: document.querySelector("#savedShipsOutput"),
  trade: document.querySelector("#tradeOutput"),
  mining: document.querySelector("#miningOutput"),
  crafting: document.querySelector("#craftingOutput"),
  blueprintImport: document.querySelector("#blueprintImportOutput"),
  savedBlueprints: document.querySelector("#savedBlueprintsOutput"),
  items: document.querySelector("#itemsOutput"),
  inventory: document.querySelector("#inventoryOutput"),
  inventoryImport: document.querySelector("#inventoryImportOutput"),
  exec: document.querySelector("#execOutput"),
  cz: document.querySelector("#czOutput"),
  commands: document.querySelector("#commandsOutput"),
  audit: document.querySelector("#auditOutput"),
};

const appShell = document.querySelector(".app-shell");
const mfdThemes = {
  overview: { theme: "overview", label: "RSI HOME SYSTEM" },
  lookup: { theme: "drake", label: "DRAKE INTERPLANETARY" },
  trade: { theme: "grey-market", label: "GREY MARKET EXCHANGE" },
  mining: { theme: "argo", label: "ARGO ASTRONAUTICS" },
  crafting: { theme: "anvil", label: "ANVIL AEROSPACE" },
  items: { theme: "origin", label: "ORIGIN JUMPWORKS" },
  inventory: { theme: "crusader", label: "CRUSADER INDUSTRIES" },
  timers: { theme: "misc", label: "MISC INDUSTRIAL" },
  commands: { theme: "aegis", label: "AEGIS DYNAMICS" },
  admin: { theme: "security", label: "SECURITY AUDIT" },
};

function activateTab(tabId) {
  const panel = document.querySelector(`#${tabId}`);
  const tabButton = document.querySelector(`.tabs button[data-tab="${tabId}"]`);
  if (!panel || !tabButton) return;
  document.querySelectorAll(".tabs button").forEach((item) => item.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach((item) => item.classList.remove("active"));
  tabButton.classList.add("active");
  panel.classList.add("active");
  appShell.classList.toggle("overview-mode", tabId === "overview");
  const mfdTheme = mfdThemes[tabId] || mfdThemes.overview;
  document.body.dataset.mfdTheme = mfdTheme.theme;
  panel.dataset.mfdLabel = mfdTheme.label;
}

document.querySelectorAll(".tabs button").forEach((button) => {
  button.addEventListener("click", () => activateTab(button.dataset.tab));
});

document.querySelectorAll("[data-overview-tab]").forEach((button) => {
  button.addEventListener("click", () => activateTab(button.dataset.overviewTab));
});

const homeBackgrounds = [
  "25", "29", "30", "32", "34", "36",
  "user-01", "user-04", "user-05", "user-06", "user-07", "user-08", "user-09",
  "gallery-01", "gallery-02", "gallery-03", "gallery-04", "gallery-05", "gallery-06", "gallery-07",
];
const homeBackgroundLayers = Array.from(document.querySelectorAll(".home-background-layer"));
const homeSlideButtons = Array.from(document.querySelectorAll("[data-home-slide]"));
const homeCarouselToggle = document.querySelector("[data-home-carousel-toggle]");
const reduceMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
let homeSlideIndex = Math.floor(Math.random() * homeBackgrounds.length);
let homeLayerIndex = 0;
let homeCarouselTimer = null;
let homeCarouselPaused = reduceMotionQuery.matches;

function homeBackgroundSize() {
  if (window.matchMedia("(max-width: 680px)").matches) return "mobile";
  if (window.matchMedia("(max-width: 1200px)").matches) return "tablet";
  return "wide";
}

function homeBackgroundUrl(index) {
  const background = homeBackgrounds[index];
  if (background.startsWith("user-") || background.startsWith("gallery-")) return `/assets/media/home/${background}.webp`;
  return `/assets/media/home/sc-${background}-${homeBackgroundSize()}.jpg`;
}

function updateHomeSlideControls() {
  homeSlideButtons.forEach((button, index) => {
    const active = index === homeSlideIndex;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  if (!homeCarouselToggle) return;
  homeCarouselToggle.textContent = homeCarouselPaused ? "Play" : "Pause";
  homeCarouselToggle.setAttribute("aria-label", `${homeCarouselPaused ? "Resume" : "Pause"} background rotation`);
}

function showHomeBackground(index, immediate = false) {
  if (!homeBackgroundLayers.length) return;
  homeSlideIndex = (index + homeBackgrounds.length) % homeBackgrounds.length;
  const nextLayerIndex = immediate ? homeLayerIndex : 1 - homeLayerIndex;
  const nextLayer = homeBackgroundLayers[nextLayerIndex];
  const image = new Image();
  image.addEventListener("load", () => {
    nextLayer.style.backgroundImage = `url("${image.src}")`;
    homeBackgroundLayers.forEach((layer, layerIndex) => layer.classList.toggle("active", layerIndex === nextLayerIndex));
    homeLayerIndex = nextLayerIndex;
    updateHomeSlideControls();
  }, { once: true });
  image.src = homeBackgroundUrl(homeSlideIndex);
}

function restartHomeCarousel() {
  window.clearInterval(homeCarouselTimer);
  homeCarouselTimer = null;
  if (homeCarouselPaused || reduceMotionQuery.matches) return;
  homeCarouselTimer = window.setInterval(() => showHomeBackground(homeSlideIndex + 1), 10000);
}

homeSlideButtons.forEach((button) => {
  button.addEventListener("click", () => {
    showHomeBackground(Number(button.dataset.homeSlide));
    restartHomeCarousel();
  });
});

homeCarouselToggle?.addEventListener("click", () => {
  homeCarouselPaused = !homeCarouselPaused;
  updateHomeSlideControls();
  restartHomeCarousel();
});

let homeResizeTimer = null;
window.addEventListener("resize", () => {
  window.clearTimeout(homeResizeTimer);
  homeResizeTimer = window.setTimeout(() => showHomeBackground(homeSlideIndex, true), 150);
});

showHomeBackground(homeSlideIndex, true);
updateHomeSlideControls();
restartHomeCarousel();

initToolMenus();

document.querySelectorAll("form[data-action]").forEach((form) => {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await handleForm(form.dataset.action, form);
  });
});

document.querySelector("[data-action-button='clearExec']").addEventListener("click", async () => {
  await api("/api/exec/override", { method: "DELETE", admin: true });
  await loadTimers();
});

document.querySelector("[data-action-button='refreshAudit']").addEventListener("click", loadAudit);
document.querySelector("[data-action-button='refreshBlueprints']").addEventListener("click", loadSavedBlueprints);
document.querySelector("[data-action-button='refreshShips']").addEventListener("click", loadSavedShips);
document.querySelector("[data-action-button='backToOverview']").addEventListener("click", () => activateTab("overview"));
document.querySelector("[data-action-button='refreshInventory']").addEventListener("click", loadInventory);
document.querySelector("[data-action-button='exportInventory']").addEventListener("click", exportInventory);
document.querySelector("[data-action-button='clearStationInventory']").addEventListener("click", clearStationInventory);
document.querySelector("[data-action-button='clearAllInventory']").addEventListener("click", clearAllInventory);
document.querySelector("[data-action-button='matchInventoryText']").addEventListener("click", importInventoryText);
document.querySelector("[data-action-button='startInventoryScanner']").addEventListener("click", startInventoryScanner);
document.querySelector("[data-action-button='startInventoryAutoScan']").addEventListener("click", startInventoryAutoScan);
document.querySelector("[data-action-button='stopInventoryScanner']").addEventListener("click", stopInventoryScanner);
document.querySelector("[data-action-button='importRsiPledges']").addEventListener("click", importRsiPledgesFromBrowser);
document.querySelector("#rsiPledgeImport").addEventListener("change", importRsiPledgeFiles);
document.querySelector("#blueprintImageImport").addEventListener("change", importBlueprintImages);
document.querySelector("[data-action-button='matchBlueprintText']").addEventListener("click", importBlueprintText);
document.querySelector("[data-action-button='captureBlueprintScreen']").addEventListener("click", captureBlueprintScreen);
window.addEventListener("beforeunload", () => stopInventoryScanner(false));
window.addEventListener("pagehide", () => stopInventoryScanner(false));

let currentUser = { authenticated: false };
let savedBlueprintNames = new Set();
let savedShipTypes = new Map();
let inventoryScannerStream = null;
let inventoryScannerCrop = null;
let inventoryScannerDrag = null;
let inventoryScannerTimer = null;
let inventoryImportItems = [];
let inventoryScannerHistory = [];
let inventoryScannerStatus = "";
let inventoryScannerBusy = false;
let inventoryScannerLastHash = "";
const inventoryScannerCropKey = "gameAssist.inventoryScannerCrop.readableWide.v3";
const inventoryCategoryTypes = {
  "Personal Weapons": ["Primary", "Sidearm", "Melee", "Attachments", "Ammunition"],
  Armor: ["Helmet", "Torso Armor", "Arm Armor", "Leg Armor", "Backpack", "Undersuit"],
  Clothing: ["Hat", "Jacket", "Shirt", "Pants", "Footwear", "Gloves"],
  Utility: ["Medical", "Multitool", "Tool", "Mining", "Salvage", "Container"],
  Consumables: ["Food", "Drink", "Medical"],
  Commodities: ["Harvestable", "Ore", "Refined Material", "Commodity"],
  Components: ["Power Plant", "Cooler", "Shield Generator", "Quantum Drive", "Jump Drive"],
  "Ship Weapons": ["Repeater", "Cannon", "Missile Rack", "Missile", "Turret"],
  Paints: ["Ship Paint", "Vehicle Paint"],
  Misc: ["Flair", "Collectible", "Contract Item", "Other"],
};
const inventoryCategories = Object.keys(inventoryCategoryTypes);
const shipDisplayPrefixes = [
  "Aegis ",
  "Anvil ",
  "Argo ",
  "Banu ",
  "Crusader ",
  "Drake ",
  "Esperia ",
  "Gatac ",
  "Greycat ",
  "Kruger ",
  "MISC ",
  "Mirai ",
  "Origin ",
  "RSI ",
  "Roberts Space Industries ",
  "Tumbril ",
];

setupInventoryScannerOverlay();
setupStaticInventorySelects();

function initToolMenus() {
  document.querySelectorAll(".tab-panel").forEach((tab) => {
    if (tab.id === "overview") return;
    const tools = Array.from(tab.querySelectorAll(":scope > .panel, :scope > form.panel, :scope > .two-column > .panel, :scope > .two-column > form.panel"));
    if (!tools.length) return;
    const menu = document.createElement("div");
    menu.className = "tool-menu";
    tools.forEach((tool, index) => {
      const title = tool.querySelector("h2")?.textContent?.trim() || `Section ${index + 1}`;
      const id = `${tab.id}-tool-${index}`;
      tool.classList.add("tool-panel");
      tool.dataset.toolId = id;
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.toolTarget = id;
      button.textContent = title;
      button.addEventListener("click", () => toggleToolPanel(tab, id));
      menu.append(button);
    });
    tab.prepend(menu);
    updateToolContainers(tab);
  });
}

function toggleToolPanel(tab, id) {
  const target = tab.querySelector(`[data-tool-id="${cssEscape(id)}"]`);
  const shouldOpen = target && !target.classList.contains("active");
  tab.querySelectorAll(".tool-panel").forEach((panel) => panel.classList.remove("active"));
  tab.querySelectorAll("[data-tool-target]").forEach((button) => button.classList.remove("active"));
  if (shouldOpen) {
    target.classList.add("active");
    tab.querySelector(`[data-tool-target="${cssEscape(id)}"]`)?.classList.add("active");
  }
  updateToolContainers(tab);
}

function updateToolContainers(tab) {
  tab.querySelectorAll(":scope > .two-column").forEach((container) => {
    container.classList.toggle("has-active-tool", Boolean(container.querySelector(".tool-panel.active")));
  });
}

async function handleForm(action, form) {
  const data = Object.fromEntries(new FormData(form).entries());
  try {
    if (action === "ship") {
      setLoading(outputs.lookup);
      await loadSavedShips({ quiet: true });
      const params = shipSearchParams(data);
      renderCards(outputs.lookup, await api(`/api/ships?${params}`), renderShip);
    }
    if (action === "commodity") {
      setLoading(outputs.trade);
      const params = queryParams(data, ["purchase_system", "sell_system"]);
      renderCards(outputs.trade, [await api(`/api/commodities/${encodeURIComponent(data.name)}?${params}`)], renderCommodity);
    }
    if (action === "trade") {
      setLoading(outputs.trade);
      const params = queryParams(data, ["starting_point", "ship", "investment", "max_stops", "stay_system"]);
      renderCards(outputs.trade, [await api(`/api/trade/routes?${params}`)], renderTrade);
    }
    if (action === "mining") {
      setLoading(outputs.mining);
      const params = queryParams(data, ["system", "planet"]);
      renderCards(outputs.mining, [await api(`/api/mining/${encodeURIComponent(data.material)}?${params}`)], renderMining);
    }
    if (action === "miningCommunity") {
      await api("/api/mining/community", { method: "POST", body: data, admin: true });
      outputs.mining.innerHTML = stateMessage("Community location saved.");
    }
    if (action === "blueprints") {
      setLoading(outputs.crafting);
      const params = queryParams(data, ["query", "category", "material", "mission_type", "contractor", "location"]);
      await loadSavedBlueprints({ quiet: true });
      renderCards(outputs.crafting, await api(`/api/blueprints?${params}`), renderBlueprint);
    }
    if (action === "items") {
      setLoading(outputs.items);
      const params = queryParams(data, ["query", "category", "section", "size"]);
      renderCards(outputs.items, await api(`/api/items?${params}`), renderItem);
    }
    if (action === "inventorySearch") {
      await loadInventory();
    }
    if (action === "inventoryAdd") {
      await api("/api/me/inventory", { method: "POST", body: cleanInventoryForm(data) });
      form.reset();
      form.querySelector('[name="quantity"]').value = "1";
      await loadInventory();
    }
    if (action === "execOverride") {
      await api("/api/exec/override", { method: "POST", body: data, admin: true });
      await loadTimers();
    }
  } catch (error) {
    outputForAction(action).innerHTML = errorMessage(error.message);
  }
}

async function api(path, options = {}) {
  const headers = {};
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method: options.method || "GET",
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `Request failed with ${response.status}`);
  }
  return payload;
}

function queryParams(data, keys) {
  const params = new URLSearchParams();
  keys.forEach((key) => {
    const value = data[key];
    if (value !== undefined && String(value).trim()) params.set(key, value);
  });
  return params.toString();
}

function setLoading(target) {
  target.replaceChildren(loadingTemplate.content.cloneNode(true));
}

function renderCards(target, items, renderer) {
  if (!items.length) {
    target.innerHTML = stateMessage("No results found.");
    return;
  }
  target.innerHTML = items.map(renderer).join("");
  bindSectionToggles(target);
  bindBlueprintButtons(target);
  bindShipButtons(target);
}

function card(title, rows, footer = "") {
  const body = definitionList(rows);
  return `<article class="result-card"><h3>${escapeHtml(title)}</h3>${body}${footer}</article>`;
}

function definitionList(rows) {
  const body = rows
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${formatValue(value)}</dd>`)
    .join("");
  return `<dl>${body}</dl>`;
}

function renderShip(ship) {
  const displayName = shipDisplayName(ship.name);
  const ownershipType = savedShipTypes.get(displayName) || savedShipTypes.get(ship.name);
  const action = currentUser.authenticated
    ? `<div class="ship-actions" data-ship-actions="${escapeAttribute(displayName)}">
        ${shipOwnershipButton(ship, "pledged", ownershipType, displayName)}
        ${shipOwnershipButton(ship, "loaner", ownershipType, displayName)}
        ${shipOwnershipButton(ship, "in_game", ownershipType, displayName)}
      </div>`
    : `<span class="state">Log in with Discord to save this ship.</span>`;
  const summary = [
    ["Manufacturer", ship.manufacturer],
    ["Role", [ship.career, ship.role].filter(Boolean).join(" / ")],
    ["Type", ship.vehicle_type],
    ["Size", ship.size],
    ["Status", ship.status],
    ["Cargo", ship.cargo_capacity ? `${ship.cargo_capacity} SCU` : null],
  ];
  const details = [
    ["Crew", ship.crew],
    ["Dimensions", [ship.length && `${ship.length}m L`, ship.beam && `${ship.beam}m W`, ship.height && `${ship.height}m H`].filter(Boolean).join(" / ")],
    ["Description", ship.description],
  ];
  const pledge = [
    ["Availability", pledgeAvailability(ship.pledge)],
    ["Pledge price", ship.pledge ? `${ship.pledge.price || "Unknown"} ${ship.pledge.currency}` : "No pledge data"],
    ["Warbond", ship.pledge?.warbond_price ? `${ship.pledge.warbond_price} ${ship.pledge.currency}` : null],
    ["Package", ship.pledge?.package_price ? `${ship.pledge.package_price} ${ship.pledge.currency}` : null],
    ["Pledge link", ship.pledge?.pledge_url ? link(ship.pledge.pledge_url, "Open pledge page") : null],
    ["Availability check", "Updates daily from UEX pledge-store price data"],
  ];
  const purchases = [
    ["In-game purchase", ship.purchases?.map((item) => `${number(item.price)} aUEC at ${escapeHtml(item.terminal_name)}`).join("<br>")],
    ["Source", link(ship.source_url, ship.source_name)],
  ];
  return `<article class="result-card" data-ship-card="${escapeAttribute(displayName)}">
    <div class="ship-card-layout">
      <div class="ship-card-main">
        <h3>${escapeHtml(displayName)}</h3>
        ${definitionList(summary)}
        <div class="section-toggle">
          <button type="button" data-section-target="details">Details</button>
          <button type="button" data-section-target="pledge">Pledge</button>
          <button type="button" data-section-target="purchase">In-game</button>
          <button type="button" data-section-target="ownership">Ownership</button>
        </div>
        <div class="detail-section" data-section="details">${definitionList(details)}</div>
        <div class="detail-section" data-section="pledge">${definitionList(pledge)}</div>
        <div class="detail-section" data-section="purchase">${definitionList(purchases)}</div>
        <div class="detail-section" data-section="ownership"><div class="card-actions">${action}</div></div>
      </div>
      <div class="ship-image-frame">
        ${ship.image_url ? `<img src="${escapeAttribute(ship.image_url)}" alt="${escapeAttribute(displayName)}">` : `<span class="ship-image-placeholder">No image</span>`}
      </div>
    </div>
  </article>`;
}

function shipOwnershipButton(ship, type, currentType, displayName = shipDisplayName(ship.name)) {
  const label = {
    pledged: "Pledged",
    loaner: "Loaner",
    in_game: "In-game",
  }[type];
  const prefix = currentType === type ? "Saved: " : "";
  return `<button type="button" data-ship-save="${escapeAttribute(type)}" data-ship='${escapeAttribute(JSON.stringify({
    name: displayName,
    ownership_type: type,
    manufacturer: ship.manufacturer,
    role: [ship.career, ship.role].filter(Boolean).join(" / "),
    vehicle_type: ship.vehicle_type,
    size: ship.size,
    status: ship.status,
    cargo_capacity: ship.cargo_capacity,
    source_name: ship.source_name,
    source_url: ship.source_url,
    image_url: ship.image_url,
  }))}'>${prefix}${label}</button>`;
}

function shipDisplayName(name) {
  const value = String(name || "").replace(/\s+/g, " ").trim();
  const prefix = shipDisplayPrefixes.find((item) => value.startsWith(item));
  return prefix ? value.slice(prefix.length).trim() : value;
}

function renderCommodity(item) {
  return card(item.name, [
    ["Code", item.code],
    ["Type", item.kind],
    ["Average buy", money(item.average_buy_price)],
    ["Average sell", money(item.average_sell_price)],
    ["Flags", ["illegal", "mineral", "raw", "refined", "harvestable"].filter((key) => item[`is_${key}`]).join(", ")],
    ["Buy from", marketList(item.buy_from)],
    ["Sell to", marketList(item.sell_to)],
  ]);
}

function renderMining(item) {
  if (item.result_type === "multi_mining_signatures") {
    return renderMiningSignatureMatch(item);
  }
  return card(item.material_name, [
    ["Code", item.code],
    ["Type", item.kind],
    ["Refined sell", money(item.refined_sell_price)],
    ["Raw sell", money(item.raw_sell_price)],
    ["Flags", [
      item.is_harvestable && "Harvestable",
      item.is_volatile_qt && "QT sensitive",
      item.is_volatile_time && "Time sensitive",
      item.is_explosive && "Explosive",
    ].filter(Boolean).join(", ")],
    ["Rock signatures", rockSignatureClusters(item.rock_signatures)],
    ["Locations", locationGroups(item.location_groups)],
    ["Source", link(item.source_url, item.source_name)],
  ]);
}

function renderMiningSignatureMatch(item) {
  return card(item.material_name, [
    ["Search", item.query],
    ["Materials", item.materials?.join(", ")],
    ["Rock signatures", rockSignatureClusters(item.rock_signatures)],
    ["Not found", item.missing?.join(", ")],
    ["Source", item.source_name],
  ]);
}

function rockSignatureClusters(signatures) {
  if (!signatures?.length) return "";
  return signatures.slice(0, 10).map((signature) => {
    const clusters = [1, 2, 3, 4, 5, 6].map((count) => `${count}x ${number(signature * count)}`);
    return `${number(signature)}: ${clusters.join(" | ")}`;
  }).join("<br>");
}

function renderBlueprint(item) {
  const isOwned = savedBlueprintNames.has(item.name);
  const action = currentUser.authenticated
    ? `<button type="button" data-blueprint-toggle="${escapeAttribute(item.name)}" data-blueprint='${escapeAttribute(JSON.stringify({
      name: item.name,
      category: item.category,
      source_name: item.source_name,
      source_url: item.source_url,
    }))}'>${isOwned ? "Remove from Mine" : "Save to Mine"}</button>`
    : `<span class="state">Log in with Discord to save this blueprint.</span>`;
  return card(item.name, [
    ["Category", item.category],
    ["Size", item.component_size],
    ["Craft time", item.craft_time_seconds ? `${Math.round(item.craft_time_seconds / 60)} min` : null],
    ["Tiers", item.tiers],
    ["Ingredients", item.ingredients?.map((ing) => escapeHtml(`${ing.quantity || ""} ${ing.unit || ""} ${ing.name}`.trim())).join("<br>")],
    ["Missions", item.missions?.slice(0, 8).map((mission) => `${escapeHtml(mission.contractor || "Unknown")}: ${escapeHtml(mission.name)}`).join("<br>")],
    ["Source", link(item.source_url, item.source_name)],
  ], `<div class="card-actions">${action}</div>`);
}

function renderBlueprintImportMatches(payload) {
  const matches = payload.matches || [];
  const ocrWarning = payload.ocr_available === false
    ? `<div class="error">${escapeHtml(payload.ocr_error || "OCR is not available.")}</div>`
    : "";
  const textPreview = payload.ocr_text
    ? `<details class="ocr-preview"><summary>Recognized text</summary><pre>${escapeHtml(payload.ocr_text.slice(0, 4000))}</pre></details>`
    : "";
  if (!matches.length) {
    outputs.blueprintImport.innerHTML = `${ocrWarning}${stateMessage("No blueprint matches found. Try a clearer screenshot or paste copied text.")}${textPreview}`;
    return;
  }
  outputs.blueprintImport.innerHTML = `${ocrWarning}<div class="import-review">
    <div class="panel-heading">
      <h3>${matches.length} possible blueprint${matches.length === 1 ? "" : "s"}</h3>
      <button type="button" data-blueprint-save-all>Save All</button>
    </div>
    ${matches.map((item) => `<article class="import-match">
      <div>
        <strong>${escapeHtml(item.name)}</strong>
        <span>${escapeHtml([item.category, item.component_size, `${Math.round(Number(item.confidence || 0) * 100)}% match`].filter(Boolean).join(" | "))}</span>
        <small>Matched: ${escapeHtml(item.matched_text || "")}</small>
      </div>
      <button type="button" data-blueprint-import-save='${escapeAttribute(JSON.stringify({
        name: item.name,
        category: item.category,
        source_name: item.source_name,
        source_url: item.source_url,
      }))}'>Save</button>
    </article>`).join("")}
  </div>${textPreview}`;
  bindBlueprintImportButtons(outputs.blueprintImport);
}

function renderItem(item) {
  return card(item.name, [
    ["Section", item.section],
    ["Category", item.category],
    ["Company", item.company_name],
    ["Size", item.size],
    ["Purchases", item.purchases?.map((purchase) => `${money(purchase.price)} at ${escapeHtml(purchase.terminal_name)}`).join("<br>")],
    ["Source", link(item.source_url, item.source_name)],
  ]);
}

function renderTrade(route) {
  const profit = route.legs.reduce((sum, leg) => sum + Number(leg.profit || 0), 0);
  return card("Circular Route", [
    ["Ship", route.ship],
    ["Cargo", `${route.cargo_capacity_scu} SCU`],
    ["Investment", money(route.investment)],
    ["Estimated profit", money(profit)],
    ["Legs", route.legs.map((leg) => `${escapeHtml(leg.commodity_name)}: ${escapeHtml(leg.buy_terminal)} to ${escapeHtml(leg.sell_terminal)}, ${money(leg.profit)} profit`).join("<br>")],
    ["Empty return", route.requires_empty_return_to_start ? "Required" : "No"],
  ]);
}

async function loadMe() {
  try {
    currentUser = await api("/api/me");
    setAdminVisibility(Boolean(currentUser.authenticated && currentUser.can_manage_admin));
    if (!currentUser.authenticated) {
      userPanel.innerHTML = `<div class="user-row">
        <span>${currentUser.discord_auth_enabled ? "Not signed in" : "Discord OAuth needs setup"}</span>
        <a class="button-link" href="/auth/discord/login">Log in with Discord</a>
      </div>`;
      outputs.savedShips.innerHTML = stateMessage("Log in with Discord to save ships to your account.");
      outputs.savedBlueprints.innerHTML = stateMessage("Log in with Discord to save blueprints to your account.");
      outputs.inventory.innerHTML = stateMessage("Log in with Discord to track station inventory.");
      return;
    }
    const badges = [
      currentUser.can_manage_changes && "Change admin",
      currentUser.can_manage_admin && "Bot admin",
    ].filter(Boolean).join(" / ") || "Viewer";
    userPanel.innerHTML = `<div class="user-row">
      ${currentUser.avatar_url ? `<img src="${escapeAttribute(currentUser.avatar_url)}" alt="">` : ""}
      <span><strong>${escapeHtml(currentUser.display_name || currentUser.username)}</strong><br>${escapeHtml(badges)}</span>
      <form method="post" action="/auth/logout"><button type="submit">Log out</button></form>
    </div>`;
    await loadSavedShips();
    await loadSavedBlueprints();
    await loadInventory();
    if (currentUser.can_manage_admin) await loadAudit();
  } catch (error) {
    setAdminVisibility(false);
    userPanel.innerHTML = `<span>${escapeHtml(error.message)}</span>`;
  }
}

function setAdminVisibility(canManageAdmin) {
  document.querySelectorAll("[data-admin-only]").forEach((element) => element.remove());
  document.querySelector(".tabs")?.classList.toggle("without-audit", !canManageAdmin);
  if (!canManageAdmin) {
    if (document.querySelector("#admin.tab-panel.active")) activateTab("overview");
    return;
  }

  const tabButton = document.querySelector("#auditTabTemplate")?.content.firstElementChild.cloneNode(true);
  const overviewButton = document.querySelector("#auditOverviewTemplate")?.content.firstElementChild.cloneNode(true);
  if (tabButton) {
    tabButton.addEventListener("click", () => activateTab("admin"));
    document.querySelector(".tabs")?.append(tabButton);
  }
  if (overviewButton) {
    overviewButton.addEventListener("click", () => activateTab("admin"));
    document.querySelector(".overview-options")?.append(overviewButton);
  }
}

async function loadSavedShips(options = {}) {
  closeHangarModal();
  if (!currentUser.authenticated) {
    savedShipTypes = new Map();
    outputs.savedShips.innerHTML = stateMessage("Log in with Discord to save ships to your account.");
    return;
  }
  if (!options.quiet) outputs.savedShips.innerHTML = stateMessage("Loading saved ships...");
  try {
    const ships = await api("/api/me/ships");
    savedShipTypes = new Map(ships.map((item) => [item.name, item.ownership_type]));
    if (!ships.length) {
      outputs.savedShips.innerHTML = stateMessage("No saved ships yet.");
      return;
    }
    outputs.savedShips.innerHTML = ships.map((item) => {
      const displayName = shipDisplayName(item.name);
      const displayLoanerFor = item.loaner_for ? shipDisplayName(item.loaner_for) : "";
      const specs = hangarSpecs(item);
      const ownership = `${shipOwnershipLabel(item.ownership_type)}${displayLoanerFor ? ` for ${displayLoanerFor}` : ""}`;
      return `<article class="hangar-card" data-hangar-card="${escapeAttribute(item.name)}">
      <button type="button" class="hangar-image-button" data-hangar-expand="${escapeAttribute(item.name)}" aria-expanded="false" aria-label="Show details for ${escapeAttribute(displayName)}">
      <div class="ship-image-frame">
        ${item.image_url ? `<img src="${escapeAttribute(item.image_url)}" alt="${escapeAttribute(displayName)}">` : `<span class="ship-image-placeholder">No image</span>`}
      </div>
      </button>
      <div class="hangar-name">
        <strong>${escapeHtml(displayName)}</strong>
        <span>${escapeHtml(ownership)}</span>
      </div>
      <div class="hangar-card-details">
        <div class="hangar-detail-heading">
          <div><strong>${escapeHtml(displayName)}</strong><span>${escapeHtml(ownership)}</span></div>
          <button type="button" data-hangar-collapse="${escapeAttribute(item.name)}">Back</button>
        </div>
        <div class="hangar-card-body">
        ${specs.length ? `<dl class="hangar-specs">${specs.map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl>` : ""}
        ${item.notes ? `<p class="hangar-notes">${escapeHtml(item.notes)}</p>` : ""}
        </div>
        <div class="hangar-actions">
          <button type="button" data-ship-manage="${escapeAttribute(item.name)}">Manage</button>
        </div>
        <div class="ship-manage-menu" data-ship-menu="${escapeAttribute(item.name)}">
        <label class="manage-ownership">
          <span>Ownership</span>
          <select data-ship-update-type="${escapeAttribute(item.name)}">
            <option value="pledged" ${item.ownership_type === "pledged" ? "selected" : ""}>Pledged</option>
            <option value="loaner" ${item.ownership_type === "loaner" ? "selected" : ""}>Loaner</option>
            <option value="in_game" ${item.ownership_type === "in_game" ? "selected" : ""}>In-game</option>
          </select>
        </label>
        <label class="manage-notes">
          <span>Info / comments</span>
          <textarea data-ship-notes="${escapeAttribute(item.name)}" placeholder="Loadout notes, insurance, paints, pledge details, or anything else you want attached to this ship">${escapeHtml(item.notes || "")}</textarea>
        </label>
        <div class="manage-actions">
          <button type="button" data-ship-update="${escapeAttribute(item.name)}">Update</button>
          <button type="button" data-ship-remove="${escapeAttribute(item.name)}">Remove</button>
        </div>
        </div>
      </div>
    </article>`;
    }).join("");
    bindShipManageButtons(outputs.savedShips, ships);
  } catch (error) {
    outputs.savedShips.innerHTML = errorMessage(error.message);
  }
}

async function importRsiPledgeFiles(event) {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (!files.length) return;
  if (!currentUser.authenticated) {
    outputs.savedShips.innerHTML = stateMessage("Log in with Discord before updating pledged ships.");
    return;
  }
  outputs.savedShips.innerHTML = stateMessage("Reading RSI pledge pages...");
  try {
    const pages = await Promise.all(files.map((file) => file.text()));
    outputs.savedShips.innerHTML = stateMessage("Updating pledged ships...");
    const result = await api("/api/me/ships/import/rsi", { method: "POST", body: { pages } });
    await loadSavedShips({ quiet: true });
    showRsiImportResult(result);
  } catch (error) {
    outputs.savedShips.innerHTML = errorMessage(error.message);
  }
}

async function importRsiPledgesFromBrowser() {
  if (!currentUser.authenticated) {
    outputs.savedShips.innerHTML = stateMessage("Log in with Discord before updating pledged ships.");
    return;
  }
  outputs.savedShips.innerHTML = stateMessage("Connecting to RSI through your browser...");
  try {
    const connected = await rsiConnect({ action: "connect" }, 1200);
    if (connected.code !== 200) throw new Error("RSI browser connector is not available.");
    outputs.savedShips.innerHTML = stateMessage("Reading ships and vehicles from RSI...");
    const response = await rsiConnect({ action: "importHangar" }, 60000);
    if (response.code !== 200) throw new Error(response.error || "RSI hangar import failed.");
    const candidates = Array.isArray(response.candidates) ? response.candidates : [];
    if (!candidates.length) throw new Error("No ships or vehicles were found. Make sure you are signed into RSI in this browser.");
    outputs.savedShips.innerHTML = stateMessage("Updating pledged ships...");
    const result = await api("/api/me/ships/import/rsi", { method: "POST", body: { candidates } });
    await loadSavedShips({ quiet: true });
    showRsiImportResult(result);
  } catch (error) {
    outputs.savedShips.innerHTML = connectorInstallPrompt(error.message);
    bindConnectorPromptButtons(outputs.savedShips);
  }
}

function connectorInstallPrompt(message) {
  return `<div class="connector-prompt">
    <div>
      <strong>RSI Hangar Importer needed</strong>
      <p>${escapeHtml(message)} Install the local importer once, then click Import RSI Hangar again.</p>
    </div>
    <div class="connector-actions">
      <a class="button-link" href="https://github.com/Battsman98/SC-discord-Bot-Website/raw/main/web/rsi-connector-extension-v0.4.4.zip">Download connector v0.4.4</a>
      <button type="button" data-open-extension-help>Install steps</button>
      <button type="button" data-import-rsi-files>Use saved HTML</button>
    </div>
    <ol class="connector-steps" hidden>
      <li>Unzip the downloaded connector folder.</li>
      <li>Open <a href="chrome://extensions">chrome://extensions</a> or <a href="edge://extensions">edge://extensions</a>. If your browser blocks internal links, copy and paste the address.</li>
      <li>Turn on Developer mode.</li>
      <li>Choose <strong>Load unpacked</strong> and select the unzipped folder.</li>
      <li>Sign into RSI in this browser, then click <strong>Import RSI Hangar</strong> again.</li>
    </ol>
  </div>`;
}

function showRsiImportResult(result) {
  const details = [
    `${result.imported.length} pledged ship${result.imported.length === 1 ? "" : "s"} updated`,
    result.candidates?.length ? `${result.candidates.length} candidate${result.candidates.length === 1 ? "" : "s"} found` : "No ship candidates found",
    result.skipped.length ? `${result.skipped.length} item${result.skipped.length === 1 ? "" : "s"} skipped` : "",
  ].filter(Boolean).join(". ");
  outputs.lookup.innerHTML = `<div class="state">
    <strong>${escapeHtml(details || "Pledged ship update complete.")}</strong>
    ${result.imported.length ? `<p>Updated: ${escapeHtml(result.imported.join(", "))}</p>` : ""}
    ${result.skipped.length ? `<p>Skipped: ${escapeHtml(result.skipped.slice(0, 20).join(", "))}</p>` : ""}
  </div>`;
}

function rsiConnect(message, timeoutMs) {
  return new Promise((resolve, reject) => {
    const requestId = Math.random().toString(36).slice(2);
    const timer = setTimeout(() => {
      window.removeEventListener("message", onMessage);
      reject(new Error("RSI browser connector did not respond."));
    }, timeoutMs);
    function onMessage(event) {
      if (event.source !== window || event.data?.direction !== "from-game-assist-rsi-connect") return;
      if (event.data.requestId !== requestId) return;
      clearTimeout(timer);
      window.removeEventListener("message", onMessage);
      try {
        resolve(JSON.parse(event.data.message || "{}"));
      } catch {
        reject(new Error("RSI browser connector returned an unreadable response."));
      }
    }
    window.addEventListener("message", onMessage);
    window.postMessage({
      direction: "from-game-assist-rsi",
      requestId,
      message: JSON.stringify(message),
    }, window.location.origin);
  });
}

function rsiPledgePageHasNext(pageHtml, page) {
  const marker = `page=${page + 1}`;
  return String(pageHtml || "").includes(marker) || String(pageHtml || "").includes(`>${page + 1}<`);
}

function hangarSpecs(item) {
  const specs = [];
  if (item.manufacturer) specs.push(["Maker", item.manufacturer]);
  String(item.role || "")
    .split("|")
    .map((value) => value.trim())
    .filter(Boolean)
    .slice(0, 5)
    .forEach((value, index) => {
      const labels = ["Role", "Type", "Size", "Status", "Cargo"];
      specs.push([labels[index] || "Spec", value]);
    });
  return specs;
}

async function loadSavedBlueprints(options = {}) {
  if (!currentUser.authenticated) {
    savedBlueprintNames = new Set();
    outputs.savedBlueprints.innerHTML = stateMessage("Log in with Discord to save blueprints to your account.");
    return;
  }
  if (!options.quiet) outputs.savedBlueprints.innerHTML = stateMessage("Loading saved blueprints...");
  try {
    const blueprints = await api("/api/me/blueprints");
    savedBlueprintNames = new Set(blueprints.map((item) => item.name));
    if (!blueprints.length) {
      outputs.savedBlueprints.innerHTML = stateMessage("No saved blueprints yet.");
      return;
    }
    outputs.savedBlueprints.innerHTML = blueprints.map((item) => `<span class="saved-pill">
      <span>${escapeHtml(item.name)}</span>
      <button type="button" data-blueprint-remove="${escapeAttribute(item.name)}">Remove</button>
    </span>`).join("");
    outputs.savedBlueprints.querySelectorAll("[data-blueprint-remove]").forEach((button) => {
      button.addEventListener("click", async () => {
        await removeBlueprint(button.dataset.blueprintRemove);
      });
    });
  } catch (error) {
    outputs.savedBlueprints.innerHTML = errorMessage(error.message);
  }
}

async function loadInventory() {
  if (!currentUser.authenticated) {
    outputs.inventory.innerHTML = stateMessage("Log in with Discord to track station inventory.");
    return;
  }
  outputs.inventory.innerHTML = stateMessage("Loading inventory...");
  try {
    await api("/api/me/inventory/merge-duplicates", { method: "POST" });
    await loadInventoryFacets();
    const params = inventoryFilterParams();
    const items = await api(`/api/me/inventory?${params}`);
    if (!items.length) {
      outputs.inventory.innerHTML = stateMessage("No inventory items found.");
      return;
    }
    outputs.inventory.innerHTML = `<div class="inventory-table">
      ${items.map(renderInventoryItem).join("")}
    </div>`;
    bindInventoryButtons(outputs.inventory);
  } catch (error) {
    outputs.inventory.innerHTML = errorMessage(error.message);
  }
}

async function loadInventoryFacets() {
  const facets = await api("/api/me/inventory/facets");
  syncSelectOptions(document.querySelector("#inventoryLocationFilter"), facets.locations || []);
  syncSelectOptions(document.querySelector("#inventoryCategoryFilter"), facets.categories || []);
}

function syncSelectOptions(select, values) {
  if (!select) return;
  const current = select.value;
  const first = select.querySelector("option");
  select.innerHTML = "";
  if (first) select.append(first);
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  });
  select.value = values.includes(current) ? current : "";
}

function setupStaticInventorySelects() {
  document.querySelectorAll("[data-inventory-category-select]").forEach((select) => {
    populateInventoryCategorySelect(select, select.value);
    select.addEventListener("change", () => syncInventoryTypeSelectForCategory(select));
    syncInventoryTypeSelectForCategory(select);
  });
}

function inventoryCategorySelect(attribute, value, placeholder = "Category") {
  return `<select ${attribute} data-inventory-category-select>
    ${inventoryCategoryOptions(value, placeholder)}
  </select>`;
}

function inventoryTypeSelect(attribute, category, value, placeholder = "Item type") {
  return `<select ${attribute} data-inventory-type-select data-category="${escapeAttribute(category || "")}">
    ${inventoryTypeOptions(category, value, placeholder)}
  </select>`;
}

function populateInventoryCategorySelect(select, selectedValue = "") {
  if (!select) return;
  select.innerHTML = inventoryCategoryOptions(selectedValue, select.dataset.placeholder || "Category");
  select.value = selectedValue && inventoryCategories.includes(selectedValue) ? selectedValue : "";
}

function syncInventoryTypeSelectForCategory(categorySelect) {
  const category = categorySelect.value;
  const container = categorySelect.closest(".inventory-row, .inventory-import-row, .field-row, .panel") || document;
  const typeSelect = container.querySelector("[data-inventory-type-select]");
  if (!typeSelect) return;
  const current = typeSelect.value;
  typeSelect.innerHTML = inventoryTypeOptions(category, current, typeSelect.dataset.placeholder || "Item type");
  const allowed = inventoryCategoryTypes[category] || [];
  typeSelect.value = current && (allowed.includes(current) || !allowed.length) ? current : "";
}

function bindInventoryCategoryMenus(target) {
  target.querySelectorAll("[data-inventory-category-select]").forEach((select) => {
    select.addEventListener("change", () => syncInventoryTypeSelectForCategory(select));
    syncInventoryTypeSelectForCategory(select);
  });
}

function inventoryCategoryOptions(selectedValue = "", placeholder = "Category") {
  const values = selectedValue && !inventoryCategories.includes(selectedValue)
    ? [selectedValue, ...inventoryCategories]
    : inventoryCategories;
  return [
    `<option value="">${escapeHtml(placeholder)}</option>`,
    ...values.map((value) => `<option value="${escapeAttribute(value)}" ${value === selectedValue ? "selected" : ""}>${escapeHtml(value)}</option>`),
  ].join("");
}

function inventoryTypeOptions(category, selectedValue = "", placeholder = "Item type") {
  const baseValues = inventoryCategoryTypes[category] || [];
  const values = selectedValue && !baseValues.includes(selectedValue)
    ? [selectedValue, ...baseValues]
    : baseValues;
  return [
    `<option value="">${escapeHtml(placeholder)}</option>`,
    ...values.map((value) => `<option value="${escapeAttribute(value)}" ${value === selectedValue ? "selected" : ""}>${escapeHtml(value)}</option>`),
  ].join("");
}

function renderInventoryItem(item) {
  const id = String(item.id);
  return `<article class="inventory-row" data-inventory-id="${escapeAttribute(id)}">
    <div class="inventory-card-main">
      <label class="inventory-name-field">
      <span>Name</span>
      <input data-inventory-name="${escapeAttribute(id)}" value="${escapeAttribute(item.name)}">
      </label>
      <label>
      <span>Category</span>
      ${inventoryCategorySelect(`data-inventory-category="${escapeAttribute(id)}"`, item.category || "")}
      </label>
      <label>
      <span>Type</span>
      ${inventoryTypeSelect(`data-inventory-type="${escapeAttribute(id)}"`, item.category || "", item.item_type || "")}
      </label>
      <label>
      <span>Size</span>
      <input data-inventory-size="${escapeAttribute(id)}" value="${escapeAttribute(item.item_size || "")}">
      </label>
      <label>
      <span>Station / location</span>
      <input data-inventory-location="${escapeAttribute(id)}" value="${escapeAttribute(item.location)}">
      </label>
      <label>
      <span>Found/Crafted Qty</span>
      <input data-inventory-quantity="${escapeAttribute(id)}" type="number" min="0" step="0.01" value="${escapeAttribute(item.quantity)}">
      </label>
      <label>
      <span>Quality</span>
      <input data-inventory-quality="${escapeAttribute(id)}" type="number" min="0" step="0.01" value="${escapeAttribute(item.quality ?? "")}">
      </label>
      <label>
      <span>SCU</span>
      <input data-inventory-volume="${escapeAttribute(id)}" type="number" min="0" step="0.000001" value="${escapeAttribute(item.volume_scu ?? "")}">
      </label>
    </div>
    <label class="inventory-notes-field">
      <span>Notes</span>
      <textarea data-inventory-notes="${escapeAttribute(id)}">${escapeHtml(item.notes || "")}</textarea>
    </label>
    <div class="inventory-actions">
      <input data-inventory-transfer-location="${escapeAttribute(id)}" placeholder="Move to station">
      <button type="button" data-inventory-transfer="${escapeAttribute(id)}">Transfer</button>
      <button type="button" data-inventory-update="${escapeAttribute(id)}">Update</button>
      <button type="button" data-inventory-remove="${escapeAttribute(id)}">Remove</button>
    </div>
  </article>`;
}

function bindInventoryButtons(target) {
  bindInventoryCategoryMenus(target);
  target.querySelectorAll("[data-inventory-update]").forEach((button) => {
    button.addEventListener("click", async () => {
      const original = button.textContent;
      button.disabled = true;
      button.textContent = "Saving...";
      try {
        await updateInventoryItem(button.dataset.inventoryUpdate);
        button.textContent = "Saved";
      } catch (error) {
        outputs.inventory.innerHTML = errorMessage(error.message);
      } finally {
        button.disabled = false;
        setTimeout(() => {
          if (button.isConnected) button.textContent = original;
        }, 1200);
      }
    });
  });
  target.querySelectorAll("[data-inventory-transfer]").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.dataset.inventoryTransfer;
      const location = target.querySelector(`[data-inventory-transfer-location="${cssEscape(id)}"]`)?.value.trim();
      if (!location) return;
      await api(`/api/me/inventory/${encodeURIComponent(id)}/transfer`, { method: "POST", body: { location } });
      await loadInventory();
    });
  });
  target.querySelectorAll("[data-inventory-remove]").forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      button.textContent = "Removing...";
      try {
        await api(`/api/me/inventory/${encodeURIComponent(button.dataset.inventoryRemove)}`, { method: "DELETE" });
        await loadInventory();
      } catch (error) {
        outputs.inventory.innerHTML = errorMessage(error.message);
      }
    });
  });
}

async function updateInventoryItem(id) {
  const row = document.querySelector(`[data-inventory-id="${cssEscape(id)}"]`);
  if (!row) throw new Error("Inventory row was not found.");
  await api(`/api/me/inventory/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: {
      name: row.querySelector(`[data-inventory-name="${cssEscape(id)}"]`)?.value || "",
      category: row.querySelector(`[data-inventory-category="${cssEscape(id)}"]`)?.value || "",
      item_type: row.querySelector(`[data-inventory-type="${cssEscape(id)}"]`)?.value || "",
      item_size: row.querySelector(`[data-inventory-size="${cssEscape(id)}"]`)?.value || "",
      location: row.querySelector(`[data-inventory-location="${cssEscape(id)}"]`)?.value || "",
      quantity: Number(row.querySelector(`[data-inventory-quantity="${cssEscape(id)}"]`)?.value || 0),
      quality: nullableNumber(row.querySelector(`[data-inventory-quality="${cssEscape(id)}"]`)?.value),
      volume_scu: nullableNumber(row.querySelector(`[data-inventory-volume="${cssEscape(id)}"]`)?.value),
      notes: row.querySelector(`[data-inventory-notes="${cssEscape(id)}"]`)?.value || "",
    },
  });
  await loadInventory();
}

function cleanInventoryForm(data) {
  return {
    name: data.name,
    category: data.category || null,
    location: data.location,
    quantity: Number(data.quantity || 1),
    quality: nullableNumber(data.quality),
    item_type: data.item_type || null,
    item_size: data.item_size || null,
    volume_scu: nullableNumber(data.volume_scu),
    notes: data.notes || null,
  };
}

function nullableNumber(value) {
  return value === undefined || value === null || String(value).trim() === "" ? null : Number(value);
}

function inventoryFilterParams() {
  const form = document.querySelector('form[data-action="inventorySearch"]');
  return form ? queryParams(Object.fromEntries(new FormData(form).entries()), ["query", "location", "category", "sort_by"]) : "";
}

function exportInventory() {
  if (!currentUser.authenticated) {
    outputs.inventory.innerHTML = stateMessage("Log in with Discord before exporting inventory.");
    return;
  }
  const params = inventoryFilterParams();
  window.location.href = `/api/me/inventory/export?${params}`;
}

async function clearStationInventory() {
  if (!currentUser.authenticated) {
    outputs.inventory.innerHTML = stateMessage("Log in with Discord before clearing inventory.");
    return;
  }
  const location = document.querySelector("#inventoryLocationFilter")?.value.trim();
  if (!location) {
    outputs.inventory.innerHTML = stateMessage("Choose a station/location filter first, then press Clear Station.");
    return;
  }
  const accepted = window.confirm(`Are you sure you want to clear every inventory item at "${location}"? This cannot be undone.`);
  if (!accepted) return;
  await clearInventory({ location, label: `"${location}"` });
}

async function clearAllInventory() {
  if (!currentUser.authenticated) {
    outputs.inventory.innerHTML = stateMessage("Log in with Discord before clearing inventory.");
    return;
  }
  const accepted = window.confirm("Are you sure you want to clear your full inventory? This deletes every station/location and cannot be undone.");
  if (!accepted) return;
  await clearInventory({ location: null, label: "your full inventory" });
}

async function clearInventory({ location, label }) {
  outputs.inventory.innerHTML = stateMessage(`Clearing ${label}...`);
  try {
    const payload = await api("/api/me/inventory/clear", { method: "POST", body: { location } });
    await loadInventoryFacets();
    await loadInventory();
    outputs.inventory.insertAdjacentHTML(
      "afterbegin",
      stateMessage(`Cleared ${payload.removed || 0} item${payload.removed === 1 ? "" : "s"} from ${label}.`)
    );
  } catch (error) {
    outputs.inventory.innerHTML = errorMessage(error.message);
  }
}

function renderInventoryImportItems(payload, options = {}) {
  const incomingItems = payload.items || [];
  if (options.append) {
    const seen = new Set(inventoryImportItems.map(inventoryImportKey));
    incomingItems.forEach((item) => {
      const key = inventoryImportKey(item);
      if (!seen.has(key)) {
        inventoryImportItems.push(item);
        seen.add(key);
      }
    });
  } else {
    inventoryImportItems = incomingItems;
  }
  const items = inventoryImportItems;
  if (options.scannerMode) {
    inventoryScannerStatus = payload.scan_status || inventoryScannerStatus || "Scanning hover tooltip.";
    if (options.recordHistory !== false) addInventoryScannerHistory(payload);
  }
  const ocrWarning = payload.ocr_available === false
    ? `<div class="state warning">${escapeHtml(payload.ocr_error || "OCR was not available.")}</div>`
    : "";
  const scanProgress = renderInventoryScanProgress();
  const diagnostics = renderInventoryScannerDiagnostics(payload.diagnostics);
  const textPreview = options.scannerMode ? "" : renderOcrTextPreview(payload.ocr_text);
  if (options.liveScan) {
    const liveMessage = items.length
      ? stateMessage(`${items.length} item${items.length === 1 ? "" : "s"} found. Keep scanning, then Stop to review and save.`)
      : stateMessage("Scanning. Hover the next item and wait a few seconds.");
    outputs.inventoryImport.innerHTML = `${ocrWarning}${liveMessage}${scanProgress}${diagnostics}`;
    return;
  }
  if (!items.length) {
    const emptyMessage = options.scannerMode && inventoryScannerHistory.length
      ? stateMessage("Still scanning. Hover the next item and wait a few seconds.")
      : stateMessage("No inventory items found. Try a clearer screenshot or paste copied rows.");
    outputs.inventoryImport.innerHTML = `${ocrWarning}${emptyMessage}${scanProgress}${diagnostics}${textPreview}`;
    return;
  }
  outputs.inventoryImport.innerHTML = `${ocrWarning}<div class="import-review">
    <div class="import-review-heading">
      <h3>Found item${items.length === 1 ? "" : "s"} to review (${items.length})</h3>
      <button type="button" data-inventory-save-all>Save All</button>
    </div>
    ${items.map((item) => `<div class="inventory-import-row">
      <input data-import-name value="${escapeAttribute(item.name)}">
      ${inventoryCategorySelect("data-import-category", item.category || "")}
      ${inventoryTypeSelect("data-import-type", item.category || "", item.item_type || "")}
      <input data-import-size value="${escapeAttribute(item.item_size || "")}" placeholder="Size">
      <input data-import-location value="${escapeAttribute(item.location)}" placeholder="Station/location">
      <input data-import-quantity type="number" min="0" step="0.01" value="${escapeAttribute(item.quantity || 1)}" placeholder="Found/Crafted Qty">
      <input data-import-quality type="number" min="0" step="0.01" value="${escapeAttribute(item.quality ?? "")}" placeholder="Quality">
      <input data-import-volume type="number" min="0" step="0.000001" value="${escapeAttribute(item.volume_scu ?? "")}" placeholder="SCU">
      <textarea data-import-notes>${escapeHtml(scannerCandidateNotes(item))}</textarea>
      <div class="import-row-actions">
        <small data-import-existing-status>Checking station...</small>
        <button type="button" data-inventory-import-save>Save</button>
        <button type="button" data-inventory-import-remove>Remove</button>
      </div>
    </div>`).join("")}
  </div>${scanProgress}${diagnostics}${textPreview}`;
  bindInventoryCategoryMenus(outputs.inventoryImport);
  bindInventoryImportButtons(outputs.inventoryImport);
  annotateImportedInventoryRows(outputs.inventoryImport);
}

function addInventoryScannerHistory(payload) {
  const timestamp = new Date().toLocaleTimeString();
  const items = payload.items || [];
  if (items.length) {
    items.forEach((item) => {
      const existingIndex = inventoryScannerHistory.findIndex((entry) =>
        entry.status === "accepted" && normalizeInventoryMergeKey(entry.text) === normalizeInventoryMergeKey(item.name)
      );
      const entry = {
        timestamp,
        status: "accepted",
        text: item.name,
        detail: [item.category, item.item_type, item.item_size].filter(Boolean).join(" / "),
      };
      if (existingIndex >= 0) {
        inventoryScannerHistory.splice(existingIndex, 1);
      }
      inventoryScannerHistory.unshift(entry);
    });
  } else {
    const candidates = payload.diagnostics?.candidates || [];
    const best = candidates.find((candidate) => candidate.matches?.length) || candidates[0];
    inventoryScannerHistory.unshift({
      timestamp,
      status: "review",
      text: best?.text || "No item read yet",
      detail: "Needs review",
    });
  }
  inventoryScannerHistory = inventoryScannerHistory.slice(0, 24);
}

function renderInventoryScanProgress() {
  if (!inventoryScannerHistory.length) return "";
  const acceptedCount = inventoryScannerHistory.filter((entry) => entry.status === "accepted").length;
  const reviewCount = inventoryScannerHistory.filter((entry) => entry.status === "review").length;
  return `<section class="scanner-progress">
    <div class="scanner-progress-heading">
      <h3>Scanner Results</h3>
      <span>${acceptedCount} found${reviewCount ? ` / ${reviewCount} needs review` : ""}</span>
    </div>
    <ul>
      ${inventoryScannerHistory.filter((entry) => entry.status === "accepted").map((entry) => `<li class="${entry.status}">
        <span>${escapeHtml(entry.timestamp)}</span>
        <strong>${escapeHtml(entry.text)}</strong>
        <small>${escapeHtml(entry.detail || entry.status)}</small>
      </li>`).join("") || `<li class="waiting"><strong>No confirmed items yet</strong><small>Keep hovering items. Questionable reads are hidden under Scanner diagnostics.</small></li>`}
    </ul>
  </section>`;
}

function renderInventoryScannerDiagnostics(diagnostics) {
  if (!diagnostics) return "";
  const candidates = diagnostics.candidates || [];
  const rejectedLines = diagnostics.rejected_lines || [];
  const candidateRows = candidates.length
    ? candidates.map((candidate) => {
        const matches = (candidate.matches || []).slice(0, 3);
        const matchMarkup = matches.length
          ? matches.map((match) => `<li class="${match.accepted ? "accepted" : "rejected"}">
              <strong>${escapeHtml(match.name)}</strong>
              <span>${Math.round(Number(match.score || 0) * 100)}%</span>
              <small>${escapeHtml([match.category, match.item_type, match.size].filter(Boolean).join(" / ") || "No category")}</small>
            </li>`).join("")
          : `<li class="rejected"><strong>No catalog hits</strong><span>0%</span><small>Not available in the item lookup</small></li>`;
        return `<article class="scanner-diagnostic-row ${candidate.status === "accepted" ? "accepted" : "rejected"}">
          <div>
            <strong>${escapeHtml(candidate.text)}</strong>
            <span>${escapeHtml(candidate.status || "checked")}</span>
            <small>${escapeHtml(candidate.reason || "")}</small>
          </div>
          <ul>${matchMarkup}</ul>
        </article>`;
      }).join("")
    : `<div class="state">No OCR candidates were selected.</div>`;
  const rejectedMarkup = rejectedLines.length
    ? `<details class="scanner-rejected-lines"><summary>Ignored OCR lines (${rejectedLines.length})</summary>
        <ul>${rejectedLines.map((line) => `<li><span>${escapeHtml(line.text)}</span><small>${escapeHtml(line.reason)}</small></li>`).join("")}</ul>
      </details>`
    : "";
  return `<details class="scanner-diagnostics">
    <summary>Scanner diagnostics (${candidates.length} OCR candidate${candidates.length === 1 ? "" : "s"})</summary>
    <div class="scanner-diagnostic-list">${candidateRows}</div>
    ${rejectedMarkup}
  </details>`;
}

function renderOcrTextPreview(text) {
  return text
    ? `<details class="ocr-preview"><summary>Raw OCR text</summary><pre>${escapeHtml(text)}</pre></details>`
    : "";
}

function inventoryImportKey(item) {
  return `${item.name}|${item.location}|${item.category || ""}|${item.item_size || ""}|${item.quality ?? ""}|${item.volume_scu ?? ""}`.toLowerCase();
}

function scannerCandidateNotes(item) {
  const notes = item.notes || "";
  if (notes.includes("Match:")) return notes;
  const match = item.confidence
    ? `Matched ${Math.round(Number(item.confidence) * 100)}%${item.matched_text ? ` from "${item.matched_text}"` : ""}`
    : "";
  return [notes, match].filter(Boolean).join("\n");
}

function setupInventoryScannerOverlay() {
  const overlay = document.querySelector("#inventoryScannerOverlay");
  if (!overlay) return;
  overlay.addEventListener("pointerdown", (event) => {
    const rect = overlay.getBoundingClientRect();
    inventoryScannerDrag = {
      startX: event.clientX - rect.left,
      startY: event.clientY - rect.top,
      currentX: event.clientX - rect.left,
      currentY: event.clientY - rect.top,
    };
    overlay.setPointerCapture(event.pointerId);
    drawInventoryScannerOverlay();
  });
  overlay.addEventListener("pointermove", (event) => {
    if (!inventoryScannerDrag) return;
    const rect = overlay.getBoundingClientRect();
    inventoryScannerDrag.currentX = event.clientX - rect.left;
    inventoryScannerDrag.currentY = event.clientY - rect.top;
    drawInventoryScannerOverlay();
  });
  overlay.addEventListener("pointerup", (event) => {
    if (!inventoryScannerDrag) return;
    const rect = overlay.getBoundingClientRect();
    const x = Math.min(inventoryScannerDrag.startX, inventoryScannerDrag.currentX);
    const y = Math.min(inventoryScannerDrag.startY, inventoryScannerDrag.currentY);
    const width = Math.abs(inventoryScannerDrag.currentX - inventoryScannerDrag.startX);
    const height = Math.abs(inventoryScannerDrag.currentY - inventoryScannerDrag.startY);
    inventoryScannerCrop = width > 20 && height > 20 ? { x: x / rect.width, y: y / rect.height, width: width / rect.width, height: height / rect.height } : null;
    saveInventoryScannerCrop();
    inventoryScannerDrag = null;
    overlay.releasePointerCapture(event.pointerId);
    drawInventoryScannerOverlay();
  });
}

async function startInventoryScanner() {
  if (!navigator.mediaDevices?.getDisplayMedia) {
    outputs.inventoryImport.innerHTML = errorMessage("Screen sharing is not available in this browser.");
    return;
  }
  stopInventoryScanner(false);
  inventoryImportItems = [];
  inventoryScannerHistory = [];
  inventoryScannerStatus = "Scanner ready.";
  inventoryScannerBusy = false;
  inventoryScannerLastHash = "";
  inventoryScannerStream = await navigator.mediaDevices.getDisplayMedia({
    video: {
      frameRate: { ideal: 1, max: 2 },
      width: { ideal: 960, max: 1280 },
      height: { ideal: 540, max: 720 },
    },
    audio: false,
  });
  inventoryScannerStream.getTracks().forEach((track) => {
    track.addEventListener("ended", () => stopInventoryScanner(true), { once: true });
  });
  const video = document.querySelector("#inventoryScannerVideo");
  video.srcObject = inventoryScannerStream;
  await new Promise((resolve) => {
    video.onloadedmetadata = resolve;
  });
  await video.play();
  document.querySelector(".scanner-preview")?.classList.add("active");
  inventoryScannerCrop = loadInventoryScannerCrop() || defaultInventoryTooltipCrop();
  sizeInventoryScannerOverlay();
  drawInventoryScannerOverlay();
  const empty = document.querySelector(".scanner-empty");
  if (empty) empty.textContent = "Scanner ready. Click Start Scan, then hover each item for a few seconds.";
  outputs.inventoryImport.innerHTML = stateMessage("Scanner ready. Click Start Scan, then hover each item for a few seconds.");
}

function stopInventoryScanner(clearOutput = true) {
  if (inventoryScannerTimer) {
    clearInterval(inventoryScannerTimer);
    inventoryScannerTimer = null;
  }
  inventoryScannerStream?.getTracks().forEach((track) => {
    if (track.readyState !== "ended") track.stop();
  });
  inventoryScannerStream = null;
  const video = document.querySelector("#inventoryScannerVideo");
  if (video) {
    video.pause();
    video.srcObject = null;
  }
  document.querySelector(".scanner-preview")?.classList.remove("active");
  const empty = document.querySelector(".scanner-empty");
  if (empty) empty.textContent = "Low-impact scanner mode. Share Star Citizen, start scan, then hover each item for a few seconds.";
  if (clearOutput) {
    inventoryScannerStatus = "Scanner stopped.";
    renderInventoryImportItems(
      { items: inventoryImportItems, scan_status: "Scanner stopped." },
      { scannerMode: true, recordHistory: false, reviewMode: true },
    );
  }
}

async function scanInventoryHover() {
  if (inventoryScannerBusy) return;
  if (!inventoryScannerStream) {
    outputs.inventoryImport.innerHTML = stateMessage("Share the Star Citizen window first.");
    return;
  }
  if (!inventoryScannerCrop) {
    inventoryScannerCrop = defaultInventoryTooltipCrop();
    drawInventoryScannerOverlay();
  }
  inventoryScannerBusy = true;
  try {
    const capture = await captureInventoryScannerCrop();
    if (inventoryScannerLastHash && imageHashDistance(inventoryScannerLastHash, capture.hash) <= 6) {
      outputs.inventoryImport.innerHTML = `${stateMessage("Waiting for the next item hover...")}${renderInventoryScanProgress()}`;
      return;
    }
    inventoryScannerLastHash = capture.hash;
    await submitInventoryImages([capture.file], { scannerMode: true, append: true, liveScan: true });
  } finally {
    inventoryScannerBusy = false;
  }
}

async function startInventoryAutoScan() {
  if (!inventoryScannerStream) {
    await startInventoryScanner();
  }
  if (!inventoryScannerCrop) {
    inventoryScannerCrop = defaultInventoryTooltipCrop();
    drawInventoryScannerOverlay();
  }
  inventoryScannerStatus = "Scanning. Hover one item at a time and wait for it to appear below.";
  const empty = document.querySelector(".scanner-empty");
  if (empty) empty.textContent = inventoryScannerStatus;
  outputs.inventoryImport.innerHTML = `${stateMessage(inventoryScannerStatus)}${renderInventoryScanProgress()}`;
  await scanInventoryHover();
  const spacing = Math.max(5000, Number(document.querySelector("#inventoryScannerSpacing")?.value || 6500));
  if (inventoryScannerTimer) clearInterval(inventoryScannerTimer);
  inventoryScannerTimer = setInterval(() => {
    scanInventoryHover().catch((error) => {
      outputs.inventoryImport.innerHTML = errorMessage(error.message);
    });
  }, spacing);
}

function defaultInventoryTooltipCrop() {
  return { x: 0.23, y: 0.18, width: 0.54, height: 0.62 };
}

function loadInventoryScannerCrop() {
  try {
    const crop = JSON.parse(localStorage.getItem(inventoryScannerCropKey) || "null");
    if (!crop || typeof crop !== "object") return null;
    const values = ["x", "y", "width", "height"].map((key) => Number(crop[key]));
    if (values.some((value) => !Number.isFinite(value))) return null;
    if (values[2] <= 0 || values[3] <= 0) return null;
    return { x: values[0], y: values[1], width: values[2], height: values[3] };
  } catch {
    return null;
  }
}

function saveInventoryScannerCrop() {
  if (!inventoryScannerCrop) {
    localStorage.removeItem(inventoryScannerCropKey);
    return;
  }
  localStorage.setItem(inventoryScannerCropKey, JSON.stringify(inventoryScannerCrop));
}

function sizeInventoryScannerOverlay() {
  const video = document.querySelector("#inventoryScannerVideo");
  const overlay = document.querySelector("#inventoryScannerOverlay");
  const rect = video.getBoundingClientRect();
  overlay.width = Math.max(1, Math.round(rect.width));
  overlay.height = Math.max(1, Math.round(rect.height));
}

function drawInventoryScannerOverlay() {
  const overlay = document.querySelector("#inventoryScannerOverlay");
  if (!overlay) return;
  sizeInventoryScannerOverlay();
  const context = overlay.getContext("2d");
  context.clearRect(0, 0, overlay.width, overlay.height);
  const box = inventoryScannerDrag
    ? {
        x: Math.min(inventoryScannerDrag.startX, inventoryScannerDrag.currentX),
        y: Math.min(inventoryScannerDrag.startY, inventoryScannerDrag.currentY),
        width: Math.abs(inventoryScannerDrag.currentX - inventoryScannerDrag.startX),
        height: Math.abs(inventoryScannerDrag.currentY - inventoryScannerDrag.startY),
      }
    : inventoryScannerCrop && {
        x: inventoryScannerCrop.x * overlay.width,
        y: inventoryScannerCrop.y * overlay.height,
        width: inventoryScannerCrop.width * overlay.width,
        height: inventoryScannerCrop.height * overlay.height,
      };
  if (!box) return;
  context.strokeStyle = "#43d2b5";
  context.lineWidth = 2;
  context.fillStyle = "rgba(67, 210, 181, 0.14)";
  context.fillRect(box.x, box.y, box.width, box.height);
  context.strokeRect(box.x, box.y, box.width, box.height);
  const textHeightRatio = inventoryScannerTextHeightRatio();
  const dividerY = box.y + (box.height * textHeightRatio);
  context.setLineDash([8, 6]);
  context.strokeStyle = "#ffd166";
  context.beginPath();
  context.moveTo(box.x, dividerY);
  context.lineTo(box.x + box.width, dividerY);
  context.stroke();
  context.setLineDash([]);
}

document.querySelector("#inventoryScannerTextHeight")?.addEventListener("input", drawInventoryScannerOverlay);

async function captureInventoryScannerCrop() {
  const video = document.querySelector("#inventoryScannerVideo");
  const sourceWidth = video.videoWidth;
  const sourceHeight = video.videoHeight;
  const crop = inventoryScannerCrop || { x: 0, y: 0, width: 1, height: 1 };
  const sx = Math.round(crop.x * sourceWidth);
  const sy = Math.round(crop.y * sourceHeight);
  const sw = Math.round(crop.width * sourceWidth);
  const sh = Math.round(crop.height * sourceHeight);
  const maxWidth = 640;
  const scale = Math.min(1, maxWidth / Math.max(1, sw));
  const targetWidth = Math.max(1, Math.round(sw * scale));
  const targetHeight = Math.max(1, Math.round(sh * scale));
  const canvas = document.createElement("canvas");
  canvas.width = targetWidth;
  canvas.height = targetHeight;
  const context = canvas.getContext("2d");
  context.drawImage(video, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
  const hash = imageAverageHash(canvas);
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/webp", 0.82));
  if (!blob) throw new Error("Could not encode the inventory capture.");
  return { file: new File([blob], "inventory-tooltip.webp", { type: "image/webp" }), hash };
}

function inventoryScannerTextHeightRatio() {
  const value = Number(document.querySelector("#inventoryScannerTextHeight")?.value || 55);
  return Math.min(0.85, Math.max(0.25, value / 100));
}

function imageAverageHash(sourceCanvas) {
  const size = 16;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d");
  context.drawImage(sourceCanvas, 0, 0, size, size);
  const data = context.getImageData(0, 0, size, size).data;
  const values = [];
  for (let index = 0; index < data.length; index += 4) {
    values.push((data[index] * 0.299) + (data[index + 1] * 0.587) + (data[index + 2] * 0.114));
  }
  const average = values.reduce((sum, value) => sum + value, 0) / values.length;
  return values.map((value) => (value >= average ? "1" : "0")).join("");
}

function imageHashDistance(left, right) {
  if (!left || !right || left.length !== right.length) return Number.POSITIVE_INFINITY;
  let distance = 0;
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) distance += 1;
  }
  return distance;
}

async function importInventoryText() {
  const text = document.querySelector("#inventoryOcrText").value.trim();
  if (!text) {
    outputs.inventoryImport.innerHTML = stateMessage("Paste inventory text first, or upload/capture a screenshot.");
    return;
  }
  outputs.inventoryImport.innerHTML = stateMessage("Reading inventory text...");
  try {
    renderInventoryImportItems(await api("/api/me/inventory/import/text", {
      method: "POST",
      body: {
        text,
        default_location: document.querySelector("#inventoryImportLocation").value,
        default_category: document.querySelector("#inventoryImportCategory").value,
        scanner_mode: true,
        min_score: Number(document.querySelector("#inventoryScannerMinScore")?.value || 0.72),
        exclude_words: document.querySelector("#inventoryScannerExcludeWords")?.value || null,
      },
    }), { scannerMode: true });
  } catch (error) {
    outputs.inventoryImport.innerHTML = errorMessage(error.message);
  }
}

async function importInventoryImages(event) {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (!files.length) return;
  await submitInventoryImages(files);
}

async function captureInventoryScreen() {
  if (!navigator.mediaDevices?.getDisplayMedia) {
    outputs.inventoryImport.innerHTML = errorMessage("Screen capture is not available in this browser.");
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    const video = document.createElement("video");
    video.srcObject = stream;
    await new Promise((resolve) => {
      video.onloadedmetadata = resolve;
    });
    await video.play();
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    await submitInventoryImages([new File([blob], "inventory-screen.png", { type: "image/png" })]);
  } catch (error) {
    outputs.inventoryImport.innerHTML = errorMessage(error.message);
  } finally {
    stream?.getTracks().forEach((track) => track.stop());
  }
}

async function submitInventoryImages(files, options = {}) {
  if (options.scannerMode) {
    outputs.inventoryImport.innerHTML = `${stateMessage("Running OCR and reading inventory...")}${renderInventoryScanProgress()}`;
  } else {
    outputs.inventoryImport.innerHTML = stateMessage("Running OCR and reading inventory...");
  }
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  const params = new URLSearchParams();
  const location = document.querySelector("#inventoryImportLocation").value.trim();
  const category = document.querySelector("#inventoryImportCategory").value.trim();
  if (location) params.set("default_location", location);
  if (category) params.set("default_category", category);
  if (options.scannerMode) {
    params.set("scanner_mode", "true");
    if (options.liveScan) params.set("live_scan", "true");
    params.set("min_score", String(Number(document.querySelector("#inventoryScannerMinScore")?.value || 0.72)));
    const excludeWords = document.querySelector("#inventoryScannerExcludeWords")?.value.trim();
    if (excludeWords) params.set("exclude_words", excludeWords);
  }
  try {
    const response = await fetch(`/api/me/inventory/import/images?${params}`, { method: "POST", body: formData });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `Request failed with ${response.status}`);
    if (payload.ocr_text && document.querySelector(".scanner-manual")?.open) {
      document.querySelector("#inventoryOcrText").value = payload.ocr_text;
    }
    renderInventoryImportItems(payload, {
      append: Boolean(options.append),
      scannerMode: Boolean(options.scannerMode),
      liveScan: Boolean(options.liveScan),
    });
  } catch (error) {
    outputs.inventoryImport.innerHTML = errorMessage(error.message);
  }
}

function bindInventoryImportButtons(target) {
  target.querySelectorAll("[data-inventory-import-remove]").forEach((button) => {
    button.addEventListener("click", () => {
      const row = button.closest(".inventory-import-row");
      if (!row) return;
      const index = Array.from(target.querySelectorAll(".inventory-import-row")).indexOf(row);
      if (index >= 0) inventoryImportItems.splice(index, 1);
      renderInventoryImportItems({ items: inventoryImportItems });
    });
  });
  target.querySelectorAll("[data-inventory-import-save]").forEach((button) => {
    button.addEventListener("click", async () => {
      await saveImportedInventoryRow(button.closest(".inventory-import-row"));
      button.textContent = "Saved";
      button.disabled = true;
    });
  });
  target.querySelector("[data-inventory-save-all]")?.addEventListener("click", async () => {
    const buttons = Array.from(target.querySelectorAll("[data-inventory-import-save]"));
    for (const button of buttons) {
      if (button.disabled) continue;
      await saveImportedInventoryRow(button.closest(".inventory-import-row"));
      button.textContent = "Saved";
      button.disabled = true;
    }
  });
}

async function annotateImportedInventoryRows(target) {
  if (!currentUser.authenticated) return;
  const rows = Array.from(target.querySelectorAll(".inventory-import-row"));
  for (const row of rows) {
    const status = row.querySelector("[data-import-existing-status]");
    if (!status) continue;
    try {
      const item = inventoryItemFromImportRow(row);
      const existing = await findExistingInventoryItem(item);
      if (existing) {
        status.textContent = `Existing at station: ${existing.quantity ?? 0}. Save updates if higher.`;
        status.className = "merge";
      } else {
        status.textContent = "New at this station";
        status.className = "new";
      }
    } catch {
      status.textContent = "Could not compare station";
      status.className = "warning";
    }
  }
}

async function saveImportedInventoryRow(row) {
  if (!row) return;
  const item = inventoryItemFromImportRow(row);
  const existing = await findExistingInventoryItem(item);
  if (existing) {
    await api(`/api/me/inventory/${encodeURIComponent(existing.id)}`, {
      method: "PUT",
      body: {
        ...existing,
        name: existing.name,
        category: item.category || existing.category,
        item_type: item.item_type || existing.item_type,
        item_size: item.item_size || existing.item_size,
        location: existing.location,
        quantity: Math.max(Number(existing.quantity || 0), Number(item.quantity || 0)),
        quality: item.quality ?? existing.quality,
        volume_scu: item.volume_scu ?? existing.volume_scu,
        notes: mergeInventoryNotes(existing.notes, item.notes),
      },
    });
  } else {
    await api("/api/me/inventory", { method: "POST", body: item });
  }
  await loadInventory();
}

function inventoryItemFromImportRow(row) {
  return {
    name: row.querySelector("[data-import-name]")?.value || "",
    category: row.querySelector("[data-import-category]")?.value || null,
    item_type: row.querySelector("[data-import-type]")?.value || null,
    item_size: row.querySelector("[data-import-size]")?.value || null,
    location: row.querySelector("[data-import-location]")?.value || "",
    quantity: Number(row.querySelector("[data-import-quantity]")?.value || 1),
    quality: nullableNumber(row.querySelector("[data-import-quality]")?.value),
    volume_scu: nullableNumber(row.querySelector("[data-import-volume]")?.value),
    notes: row.querySelector("[data-import-notes]")?.value || null,
  };
}

async function findExistingInventoryItem(item) {
  const params = new URLSearchParams();
  if (item.location) params.set("location", item.location);
  if (item.name) params.set("query", item.name);
  const items = await api(`/api/me/inventory?${params}`);
  const targetName = normalizeInventoryMergeKey(item.name);
  const targetLocation = normalizeInventoryMergeKey(item.location);
  return (items || []).find((existing) =>
    normalizeInventoryMergeKey(existing.name) === targetName
    && normalizeInventoryMergeKey(existing.location) === targetLocation
  );
}

function normalizeInventoryMergeKey(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function mergeInventoryNotes(existing, incoming) {
  const existingText = String(existing || "").trim();
  const incomingText = String(incoming || "").trim();
  if (!incomingText) return existingText || null;
  if (!existingText || existingText.includes(incomingText)) return existingText || incomingText;
  return `${existingText}\n${incomingText}`;
}

async function importBlueprintText() {
  const text = document.querySelector("#blueprintOcrText").value.trim();
  if (!text) {
    outputs.blueprintImport.innerHTML = stateMessage("Paste blueprint text first, or upload/capture a screenshot.");
    return;
  }
  outputs.blueprintImport.innerHTML = stateMessage("Matching blueprints...");
  try {
    renderBlueprintImportMatches(await api("/api/blueprints/import/text", { method: "POST", body: { text } }));
  } catch (error) {
    outputs.blueprintImport.innerHTML = errorMessage(error.message);
  }
}

async function importBlueprintImages(event) {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (!files.length) return;
  await submitBlueprintImages(files);
}

async function captureBlueprintScreen() {
  if (!navigator.mediaDevices?.getDisplayMedia) {
    outputs.blueprintImport.innerHTML = errorMessage("Screen capture is not available in this browser.");
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    const video = document.createElement("video");
    video.srcObject = stream;
    await new Promise((resolve) => {
      video.onloadedmetadata = resolve;
    });
    await video.play();
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    await submitBlueprintImages([new File([blob], "blueprint-screen.png", { type: "image/png" })]);
  } catch (error) {
    outputs.blueprintImport.innerHTML = errorMessage(error.message);
  } finally {
    stream?.getTracks().forEach((track) => track.stop());
  }
}

async function submitBlueprintImages(files) {
  outputs.blueprintImport.innerHTML = stateMessage("Running OCR and matching blueprints...");
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  try {
    const response = await fetch("/api/blueprints/import/images", { method: "POST", body: formData });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `Request failed with ${response.status}`);
    if (payload.ocr_text) document.querySelector("#blueprintOcrText").value = payload.ocr_text;
    renderBlueprintImportMatches(payload);
  } catch (error) {
    outputs.blueprintImport.innerHTML = errorMessage(error.message);
  }
}

function bindBlueprintImportButtons(target) {
  target.querySelectorAll("[data-blueprint-import-save]").forEach((button) => {
    button.addEventListener("click", async () => {
      await saveImportedBlueprint(JSON.parse(button.dataset.blueprintImportSave));
      button.textContent = "Saved";
      button.disabled = true;
    });
  });
  target.querySelector("[data-blueprint-save-all]")?.addEventListener("click", async () => {
    const buttons = Array.from(target.querySelectorAll("[data-blueprint-import-save]"));
    for (const button of buttons) {
      if (button.disabled) continue;
      await saveImportedBlueprint(JSON.parse(button.dataset.blueprintImportSave));
      button.textContent = "Saved";
      button.disabled = true;
    }
  });
}

async function saveImportedBlueprint(blueprint) {
  if (!currentUser.authenticated) throw new Error("Log in with Discord before saving blueprints.");
  await api("/api/me/blueprints", { method: "PUT", body: blueprint });
  await loadSavedBlueprints({ quiet: true });
}

function bindBlueprintButtons(target) {
  target.querySelectorAll("[data-blueprint-toggle]").forEach((button) => {
    button.addEventListener("click", async () => {
      const blueprint = JSON.parse(button.dataset.blueprint);
      if (savedBlueprintNames.has(blueprint.name)) {
        await removeBlueprint(blueprint.name);
      } else {
        await api("/api/me/blueprints", { method: "PUT", body: blueprint });
        await loadSavedBlueprints();
      }
      const searchForm = document.querySelector('form[data-action="blueprints"]');
      if (searchForm) {
        const data = Object.fromEntries(new FormData(searchForm).entries());
        const params = queryParams(data, ["query", "category", "material", "mission_type", "contractor", "location"]);
        renderCards(outputs.crafting, await api(`/api/blueprints?${params}`), renderBlueprint);
      }
    });
  });
}

function bindShipButtons(target) {
  bindConnectorPromptButtons(target);
  target.querySelectorAll("[data-ship-save]").forEach((button) => {
    button.addEventListener("click", async () => {
      const ship = JSON.parse(button.dataset.ship);
      await api("/api/me/ships", { method: "PUT", body: ship });
      await loadSavedShips();
      const searchForm = document.querySelector('form[data-action="ship"]');
      if (searchForm) {
        const data = Object.fromEntries(new FormData(searchForm).entries());
        const params = shipSearchParams(data);
        renderCards(outputs.lookup, await api(`/api/ships?${params}`), renderShip);
      }
    });
  });
  bindShipRemoveButtons(target);
}

function bindConnectorPromptButtons(target) {
  target.querySelectorAll("[data-import-rsi-files]").forEach((button) => {
    button.addEventListener("click", () => document.querySelector("#rsiPledgeImport").click());
  });
  target.querySelectorAll("[data-open-extension-help]").forEach((button) => {
    button.addEventListener("click", () => {
      const steps = button.closest(".connector-prompt")?.querySelector(".connector-steps");
      if (steps) steps.hidden = !steps.hidden;
    });
  });
}

function bindSectionToggles(target) {
  target.querySelectorAll("[data-section-target]").forEach((button) => {
    button.addEventListener("click", () => {
      const card = button.closest("[data-ship-card]");
      if (!card) return;
      const section = card.querySelector(`[data-section="${button.dataset.sectionTarget}"]`);
      if (!section) return;
      const wasActive = section.classList.contains("active");
      card.querySelectorAll(".detail-section").forEach((item) => item.classList.remove("active"));
      if (!wasActive) section.classList.add("active");
    });
  });
}

function bindShipManageButtons(target, ships) {
  const shipByName = new Map(ships.map((ship) => [ship.name, ship]));
  target.querySelectorAll("[data-hangar-expand]").forEach((button) => {
    button.addEventListener("click", () => toggleHangarCard(target, button.dataset.hangarExpand));
  });
  target.querySelectorAll("[data-hangar-collapse]").forEach((button) => {
    button.addEventListener("click", () => collapseHangarCard(target, button.dataset.hangarCollapse));
  });
  target.querySelectorAll("[data-ship-manage]").forEach((button) => {
    button.addEventListener("click", () => {
      const menu = target.querySelector(`[data-ship-menu="${cssEscape(button.dataset.shipManage)}"]`);
      if (menu) menu.classList.toggle("active");
    });
  });
  target.querySelectorAll("[data-ship-update]").forEach((button) => {
    button.addEventListener("click", async () => {
      const name = button.dataset.shipUpdate;
      const existing = shipByName.get(name) || { name };
      await api("/api/me/ships", {
        method: "PUT",
        body: {
          name,
          ownership_type: target.querySelector(`[data-ship-update-type="${cssEscape(name)}"]`)?.value || existing.ownership_type,
          manufacturer: existing.manufacturer,
          role: existing.role,
          source_name: existing.source_name,
          source_url: existing.source_url,
          image_url: existing.image_url,
          notes: target.querySelector(`[data-ship-notes="${cssEscape(name)}"]`)?.value || "",
        },
      });
      await loadSavedShips();
    });
  });
  bindShipRemoveButtons(target);
}

function toggleHangarCard(target, name) {
  const card = target.querySelector(`[data-hangar-card="${cssEscape(name)}"]`);
  if (!card) return;
  const willExpand = !card.classList.contains("expanded");
  closeHangarModal();
  setHangarCardExpanded(card, willExpand);
  if (willExpand) {
    const backdrop = document.createElement("button");
    backdrop.type = "button";
    backdrop.className = "hangar-modal-backdrop";
    backdrop.setAttribute("aria-label", "Close ship details");
    backdrop.addEventListener("click", closeHangarModal);
    document.body.append(backdrop);
    document.body.classList.add("hangar-modal-open");
  }
}

function collapseHangarCard(target, name) {
  const card = target.querySelector(`[data-hangar-card="${cssEscape(name)}"]`);
  if (card) setHangarCardExpanded(card, false);
  closeHangarModal();
}

function closeHangarModal() {
  document.querySelectorAll(".hangar-card.expanded").forEach((card) => setHangarCardExpanded(card, false));
  document.querySelectorAll(".hangar-modal-backdrop").forEach((backdrop) => backdrop.remove());
  document.body.classList.remove("hangar-modal-open");
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && document.querySelector(".hangar-card.expanded")) closeHangarModal();
});

function setHangarCardExpanded(card, expanded) {
  card.classList.toggle("expanded", expanded);
  if (expanded) {
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-modal", "true");
  } else {
    card.removeAttribute("role");
    card.removeAttribute("aria-modal");
  }
  card.querySelector("[data-hangar-expand]")?.setAttribute("aria-expanded", String(expanded));
  if (!expanded) card.querySelector(".ship-manage-menu")?.classList.remove("active");
}

function bindShipRemoveButtons(target) {
  target.querySelectorAll("[data-ship-remove]").forEach((button) => {
    button.addEventListener("click", async () => {
      await removeShip(button.dataset.shipRemove);
    });
  });
}

async function removeShip(name) {
  await api(`/api/me/ships/${encodeURIComponent(name)}`, { method: "DELETE" });
  await loadSavedShips();
  const searchForm = document.querySelector('form[data-action="ship"]');
  if (searchForm) {
    const data = Object.fromEntries(new FormData(searchForm).entries());
    const params = shipSearchParams(data);
    renderCards(outputs.lookup, await api(`/api/ships?${params}`), renderShip);
  }
}

function shipSearchParams(data) {
  return queryParams(data, [
    "query",
    "manufacturer",
    "vehicle_type",
    "size",
    "status",
    "sort_by",
  ]);
}

function shipOwnershipLabel(type) {
  return {
    pledged: "Pledged",
    loaner: "Loaner",
    in_game: "In-game",
  }[type] || type;
}

function pledgeAvailability(pledge) {
  if (!pledge) return "Unknown";
  if (pledge.is_on_sale === true) return "Available on pledge store";
  if (pledge.is_on_sale === false) return "Not currently available on pledge store";
  return "Unknown";
}

async function removeBlueprint(name) {
  await api(`/api/me/blueprints/${encodeURIComponent(name)}`, { method: "DELETE" });
  await loadSavedBlueprints();
}

async function loadTimers() {
  try {
    const exec = await api("/api/exec/status");
    outputs.exec.innerHTML = card(exec.active.status, [
      ["Detail", exec.active.status_detail],
      ["Lights", exec.active.lights],
      ["Remaining", seconds(exec.active.phase_remaining_seconds)],
      ["Next change", dateTime(exec.active.next_change_unix)],
      ["Override", exec.override ? `Set by ${exec.override.corrected_by || "unknown"}` : "None"],
    ]);
  } catch (error) {
    outputs.exec.innerHTML = errorMessage(error.message);
  }

  try {
    const cz = await api("/api/cz/timers");
    outputs.cz.innerHTML = Object.entries(cz.definitions).map(([id, definition]) => {
      const timer = cz.timers[id];
      const label = definition[0];
      return `<div class="timer-row">
        <strong>${escapeHtml(label)}</strong>
        <span>${timer ? dateTime(timer.ends_at) : "Idle"}</span>
        <button data-start-cz="${id}">Start</button>
        <button data-reset-cz="${id}">Reset</button>
      </div>`;
    }).join("") + `<button data-reset-cz="all">Reset All</button>`;
    outputs.cz.querySelectorAll("[data-start-cz]").forEach((button) => {
      button.addEventListener("click", async () => {
        await api("/api/cz/timers", { method: "POST", admin: true, body: { timer: button.dataset.startCz } });
        await loadTimers();
      });
    });
    outputs.cz.querySelectorAll("[data-reset-cz]").forEach((button) => {
      button.addEventListener("click", async () => {
        await api(`/api/cz/timers/${button.dataset.resetCz}`, { method: "DELETE", admin: true });
        await loadTimers();
      });
    });
  } catch (error) {
    outputs.cz.innerHTML = errorMessage(error.message);
  }
}

async function loadCommands() {
  try {
    const data = await api("/api/commands");
    outputs.commands.innerHTML = markdownLite(data.markdown);
  } catch (error) {
    outputs.commands.innerHTML = errorMessage(error.message);
  }
}

async function loadAudit() {
  try {
    renderCards(outputs.audit, await api("/api/audit/recent?limit=20"), (event) => card(event.title, [
      ["When", dateTime(event.created_at)],
      ["Fields", Object.entries(event.fields || {}).map(([key, value]) => `${key}: ${value}`).join("<br>")],
    ]));
  } catch (error) {
    outputs.audit.innerHTML = errorMessage(error.message);
  }
}

function outputForAction(action) {
  if (action === "ship") return outputs.lookup;
  if (action === "commodity") return outputs.trade;
  if (action === "trade") return outputs.trade;
  if (action.startsWith("mining")) return outputs.mining;
  if (action === "blueprints") return outputs.crafting;
  if (action === "items") return outputs.items;
  if (action.startsWith("inventory")) return outputs.inventory;
  return outputs.exec;
}

function marketList(markets = []) {
  return markets.slice(0, 8).map((market) => `${money(market.price)}/SCU at ${escapeHtml([market.system, market.planet, market.location || market.terminal_name].filter(Boolean).join(" / "))}`).join("<br>");
}

function locationGroups(groups = []) {
  return groups.map((group) => {
    const details = [
      group.lagrange_points?.length && `L-points: ${group.lagrange_points.join(", ")}`,
      group.planets?.length && `Planets: ${group.planets.join(", ")}`,
      group.moons?.length && `Moons: ${group.moons.join(", ")}`,
      group.points_of_interest?.length && `POIs: ${group.points_of_interest.join(", ")}`,
    ].filter(Boolean).join("<br>");
    return `<strong>${escapeHtml(group.system)}</strong><br>${escapeHtml(details).replaceAll("&lt;br&gt;", "<br>")}`;
  }).join("<br><br>");
}

function metric(label, value) {
  return `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function money(value) {
  return value === null || value === undefined ? "" : `${number(value)} aUEC`;
}

function number(value) {
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function seconds(value) {
  if (value === null || value === undefined) return "";
  const minutes = Math.floor(value / 60);
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return hours ? `${hours} hr ${remainder} min` : `${minutes} min`;
}

function dateTime(unix) {
  return unix ? new Date(unix * 1000).toLocaleString() : "";
}

function link(url, text) {
  return url ? `<a href="${escapeAttribute(url)}" target="_blank" rel="noreferrer">${escapeHtml(text || url)}</a>` : text;
}

function formatValue(value) {
  if (Array.isArray(value)) return value.map(formatValue).join("<br>");
  return String(value);
}

function markdownLite(markdown) {
  return escapeHtml(markdown)
    .replace(/^# (.*)$/gm, "<h2>$1</h2>")
    .replace(/^## (.*)$/gm, "<h3>$1</h3>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\n\n/g, "</p><p>")
    .replace(/\n/g, "<br>")
    .replace(/^/, "<p>")
    .replace(/$/, "</p>");
}

function stateMessage(message) {
  return `<div class="state">${escapeHtml(message)}</div>`;
}

function errorMessage(message) {
  return `<div class="error">${escapeHtml(message)}</div>`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

function cssEscape(value) {
  if (window.CSS?.escape) return CSS.escape(value);
  return String(value).replace(/["\\]/g, "\\$&");
}

loadMe();
loadShipFacets();
loadTimers();
loadCommands();
setInterval(loadTimers, 60_000);

async function loadShipFacets() {
  try {
    const facets = await api("/api/ships/facets");
    document.querySelectorAll("[data-ship-facet]").forEach((select) => {
      const key = select.dataset.shipFacet;
      const firstOption = select.querySelector("option");
      select.innerHTML = "";
      if (firstOption) select.append(firstOption);
      (facets[key] || []).forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        select.append(option);
      });
    });
  } catch (error) {
    outputs.lookup.innerHTML = errorMessage(`Could not load ship filters: ${error.message}`);
  }
}
