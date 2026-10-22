function makeId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    try { return crypto.randomUUID(); } catch (e) { /* fall through */ }
  }
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
    bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
  }
  return "id-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
}

const sessionId = (() => {
  let id = localStorage.getItem("voice_console_session");
  if (!id) {
    id = makeId();
    localStorage.setItem("voice_console_session", id);
  }
  return id;
})();

let currentProfileId = localStorage.getItem("voice_console_profile") || "";
let allProfiles = [];
let allVoices = [];
let sessionCredits = 0;
let editingProfileId = null;

let defaultVoiceId = "";
let defaultVoiceName = "";

// Response styles + personality presets, loaded from /api/settings once and
// reused everywhere a select needs them (Settings panel, profile modal) so
// opening the profile editor doesn't need another round trip.
let responseStyles = [];
let personalityPresets = [];

// Chat model catalog + the per-tier numbers used to estimate cost/speed in
// the UI. All loaded from /api/settings so the prices only need updating in
// one place (app.py) if OpenAI changes them.
let textModels = [];
let recommendedTextModel = "gpt-4o-mini";
let recommendedTranslationModel = "gpt-4.1-nano";
let modelTierThroughput = { nano: 110, mini: 70, standard: 40 };
let modelTierSpeedLabel = { nano: "Fastest", mini: "Fast", standard: "Moderate" };

const MISSING_ELEMENTS = [];

function $(id) {
  const el = document.getElementById(id);
  if (!el) {
    MISSING_ELEMENTS.push(id);
    const stub = document.createElement("div");
    stub.className = "missing-stub";
    return stub;
  }
  return el;
}

function reportMissingElements() {
  if (!MISSING_ELEMENTS.length) return;
  const banner = document.createElement("div");
  banner.className = "version-warning";
  banner.textContent =
    `Page is out of date: ${MISSING_ELEMENTS.length} control(s) missing ` +
    `(${MISSING_ELEMENTS.join(", ")}). Your templates/index.html doesn't match ` +
    `static/app.js — replace both with the same version, then hard-refresh with Ctrl+F5.`;
  document.body.prepend(banner);
  console.error("Missing elements:", MISSING_ELEMENTS);
}

const logEl = $("log");
// #log is the scroll box; #logBody holds the turns. Separate so the sticky
// header inside #log survives clearing the conversation.
const logBody = $("logBody");
const clearChatBtn = $("clearChatBtn");
const statusEl = $("status");
const readyLamp = $("readyLamp");
const sessionCreditsEl = $("sessionCredits");
const elevenCreditsEl = $("elevenCredits");

const messageInput = $("messageInput");
const sendBtn = $("sendBtn");
const dictateBtn = $("dictateBtn");

const settingsToggle = $("settingsToggle");
const settingsPanel = $("settingsPanel");
const saveSettingsBtn = $("saveSettings");
const closeSettingsBtn = $("closeSettings");
const refreshVoicesBtn = $("refreshVoicesBtn");
const micSelect = $("micSelect");
const refreshMicsBtn = $("refreshMicsBtn");
const micNote = $("micNote");
const dictationModeRadios = $("dictationModeRadios");
const dictationModeNote = $("dictationModeNote");
const dictationLangSelect = $("dictationLangSelect");

const openaiKeyInput = $("openaiKey");
const elevenKeyInput = $("elevenKey");
const systemPromptInput = $("systemPrompt");

const voicePicker = $("voicePicker");
const voiceTrigger = $("voiceTrigger");
const voiceTriggerName = $("voiceTriggerName");
const voiceTriggerTags = $("voiceTriggerTags");
const voicePop = $("voicePop");
const voiceSearch = $("voiceSearch");
const voiceLangFilter = $("voiceLangFilter");
const voiceGenderFilter = $("voiceGenderFilter");
const voiceTypeFilter = $("voiceTypeFilter");
const voiceFilterClear = $("voiceFilterClear");
const voiceHiddenNote = $("voiceHiddenNote");
const voiceList = $("voiceList");
const voiceFoot = $("voiceFoot");
const voiceSort = $("voiceSort");
const openaiStatus = $("openaiStatus");
const elevenStatus = $("elevenStatus");

const textModelList = $("textModelList");
const textModelCustom = $("textModelCustom");
const textModelEstimate = $("textModelEstimate");
const translationModelList = $("translationModelList");
const translationModelCustom = $("translationModelCustom");
const translationModelEstimate = $("translationModelEstimate");

const chatProviderRadios = $("chatProviderRadios");
const chatProviderNote = $("chatProviderNote");
const translationProviderRadios = $("translationProviderRadios");
const translationProviderNote = $("translationProviderNote");
const transcriptionProviderRadios = $("transcriptionProviderRadios");
const transcriptionProviderNote = $("transcriptionProviderNote");
const allowFallbackToggle = $("allowFallbackToggle");
const ollamaSettings = $("ollamaSettings");
const ollamaUrl = $("ollamaUrl");
const ollamaModel = $("ollamaModel");
const ollamaModelBalanced = $("ollamaModelBalanced");   // NEW (1.5.0)
const ollamaModelBest = $("ollamaModelBest");           // NEW (1.5.0)
const ollamaIdleUnload = $("ollamaIdleUnload");         // NEW (1.5.0)
const ollamaTranslationModel = $("ollamaTranslationModel");
const ollamaTestNote = $("ollamaTestNote");
const testOllamaBtn = $("testOllamaBtn");
const whisperSettings = $("whisperSettings");
const whisperUrl = $("whisperUrl");
const whisperTestNote = $("whisperTestNote");
const testWhisperBtn = $("testWhisperBtn");
const whisperModelSelect = $("whisperModelSelect");
const applyWhisperModelBtn = $("applyWhisperModelBtn");
const whisperModelNote = $("whisperModelNote");

const oscEnabledToggle = $("oscEnabledToggle");
const oscMuteSyncToggle = $("oscMuteSyncToggle");
const oscUnmuteOnSendToggle = $("oscUnmuteOnSendToggle");
const oscTypingToggle = $("oscTypingToggle");   // NEW (typing)
const frivoscStatusValue = $("frivoscStatusValue");
const oscToggle = $("oscToggle");
const oscSwitch = $("oscSwitch");

const speakToggle = $("speakToggle");

const responseStyleRadios = $("responseStyleRadios");
const personalityPresetSelect = $("personalityPresetSelect");

const lengthSlider = $("lengthSlider");
const lengthValue = $("lengthValue");
const lengthEcho = $("lengthEcho");
const creditEcho = $("creditEcho");
const secondsEcho = $("secondsEcho");

const masterVolumeSlider = $("masterVolumeSlider");
const masterVolumeValue = $("masterVolumeValue");

const profileSelect = $("profileSelect");
const editProfileBtn = $("editProfileBtn");
const newProfileBtn = $("newProfileBtn");
const deleteProfileBtn = $("deleteProfileBtn");

const overlay = $("profileModalOverlay");
const profileModalTitle = $("profileModalTitle");
const profileNameInput = $("profileName");
const profileVoiceNote = $("profileVoiceNote");
const profileLanguageSelect = $("profileLanguageSelect");
const profileResponseStyleRadios = $("profileResponseStyleRadios");
// NEW (1.5.0): Follow reply length
const profileFollowLength = $("profileFollowLength");
const profileFollowLengthHint = $("profileFollowLengthHint");
const profilePersonalityPresetSelect = $("profilePersonalityPresetSelect");
const profileSystemPromptInput = $("profileSystemPrompt");
const profileModalSave = $("profileModalSave");
const profileModalCancel = $("profileModalCancel");

// ---------- Status + lamp ----------

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  // CHANGED (2.0): "Ready." is not news; the line only shows when it says
  // something.
  statusEl.classList.toggle("is-quiet", !text || /^Ready\.?$/.test(text.trim()));
  // The line is a fixed single row that can't wrap, so a long message is
  // ellipsised — the full text stays available on hover rather than being
  // allowed to reflow the page.
  statusEl.title = text || "";
  statusEl.classList.toggle("is-error", isError);
}

function setLamp(state) {
  readyLamp.classList.toggle("is-lit", state === "ready");
  readyLamp.classList.toggle("is-busy", state === "busy");
  // CHANGED (2.0): the lamp lives in the status pill, which says it in a word.
  const pillText = $("statusPillText");
  if (pillText) pillText.textContent = state === "busy" ? "Working…" : "Ready";
}

function addCredits(n) {
  sessionCredits += n;
  sessionCreditsEl.textContent = `${sessionCredits.toLocaleString()} used this session`;   // CHANGED (1.5.0): shorter, fits under the label
  const line = document.getElementById("creditsSession");
  if (line) line.textContent = sessionCredits.toLocaleString();
}

// ---------- Fader ----------

masterVolumeSlider.addEventListener("input", () => {
  const pct = clampVolumePct(masterVolumeSlider.value);
  masterVolumeValue.textContent = `${pct}%`;
  setMasterVolume(pct);
});


function fillOptionList(selectEl, items, selectedId) {
  selectEl.innerHTML = "";
  items.forEach((item) => {
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = item.name;
    if (item.title) opt.title = item.title;
    if (item.id === selectedId) opt.selected = true;
    selectEl.appendChild(opt);
  });
}


function buildRadioGroup(containerEl, items, groupName, selectedId, onChange) {
  containerEl.innerHTML = "";
  items.forEach((item) => {
    const pill = document.createElement("label");
    pill.className = "radio-pill";
    if (item.id === selectedId) pill.classList.add("is-checked");

    const input = document.createElement("input");
    input.type = "radio";
    input.name = groupName;
    input.value = item.id;
    if (item.id === selectedId) input.checked = true;

    const label = document.createElement("span");
    label.className = "radio-label";
    label.textContent = item.name;

    if (item.description) pill.title = item.description;

    pill.append(input, label);
    // NEW (1.6.0): a choice that says what it is and what it runs on is a
    // card (Chat replies), not a pill.
    if (item.summary) {
      containerEl.classList.add("radio-row--cards");
      const add = (cls, text, lead) => {
        if (!text) return;
        const line = document.createElement("span");
        line.className = cls;
        if (lead) {
          const b = document.createElement("span");
          b.className = "radio-card-lead";
          b.textContent = lead;
          line.append(b, " ", text);
        } else {
          line.textContent = text;
        }
        pill.appendChild(line);
      };
      pill.dataset.id = item.id;
      if (item.compact) pill.classList.add("is-compact");
      add("radio-card-summary", item.summary);
      add("radio-card-meta", item.runs_on, "Runs on");
      add("radio-card-meta radio-card-uses", item.uses, "Uses");
    }

    input.addEventListener("change", () => {
      containerEl.querySelectorAll(".radio-pill").forEach((p) => p.classList.remove("is-checked"));
      pill.classList.add("is-checked");
      if (onChange) onChange(item.id);
    });

    containerEl.appendChild(pill);
  });
}

function getRadioValue(containerEl, fallback) {
  const checked = containerEl.querySelector("input:checked");
  return checked ? checked.value : fallback;
}


const serviceStatus = $("serviceStatus");
const LOCAL_STATUS_POLL_MS = 30000;
let localStatusTimer = null;

function serviceChipTitle(service) {
  const lines = [`${service.name}: ${service.url}`, service.message].filter(Boolean);   // CHANGED (1.6.0)
  // FrivOSC has nothing to fall back to — if it is down, VRChat just gets
  // nothing. Only the providers with an OpenAI path behind them get the
  // warning about paying for it.
  // CHANGED (1.6.0): only when it really falls back (the switch is on and
  // there's an OpenAI key); otherwise what happens meanwhile, if anything.
  if (!service.ok && service.fallback === true) {
    lines.push("Falling back to OpenAI, which costs credits.");
  } else if (!service.ok && service.fallback_note) {
    lines.push(service.fallback_note + ".");
  }
  return lines.join("\n");
}

let renderedServiceIds = "";

// CHANGED (2.0): a service is a row in the status popover — dot, name,
// state, one line of detail — with a Settings link that opens the page
// where it is set up. The chips used to expand and pull the settings card
// into themselves; in a popover that read as a second, cramped Settings.
const SERVICE_SETTINGS_TARGET = {
  whisper: { section: "providers" },
  ollama: { section: "providers" },
  builtin: { section: "providers" },   // NEW (1.6.0)
  openai: { section: "providers" },    // NEW (1.6.0)
  none: { section: "providers" },      // NEW (1.6.0)
  frivosc: { section: "vrchat" },
};

function buildServiceBlock(service) {
  const block = document.createElement("div");
  block.className = "service-block";
  block.dataset.serviceId = service.id;

  const chip = document.createElement("div");
  chip.className = "service-status";

  const name = document.createElement("span");
  name.className = "service-status-name";
  const state = document.createElement("span");
  state.className = "service-status-state";
  const detail = document.createElement("span");
  detail.className = "service-status-detail";
  const link = document.createElement("button");
  link.type = "button";
  link.className = "service-status-link";
  link.textContent = "Settings";
  link.setAttribute("aria-label", `${service.name} settings`);

  const head = document.createElement("span");
  head.className = "service-status-head";
  head.append(name, state);
  chip.append(head, detail, link);
  block.append(chip);
  return block;
}

function paintServiceBlock(block, service) {
  const chip = block.querySelector(".service-status");
  chip.className = "service-status " + (service.ok ? "is-ok" : "is-down");
  chip.title = serviceChipTitle(service);
  block.querySelector(".service-status-name").textContent = service.name;
  // CHANGED (1.6.0): "not downloaded", "for replies", "no key", say.
  block.querySelector(".service-status-state").textContent = `· ${service.state || (service.ok ? "connected" : "unreachable")}`;
  const detail = block.querySelector(".service-status-detail");
  detail.textContent = service.ok ? (service.url || "") : (service.message || "");
  if (!service.ok && service.fallback === true) detail.textContent += " · falling back to OpenAI";
  else if (!service.ok && service.fallback_note) detail.textContent += ` · ${service.fallback_note}`;
}

// What the pill says when something is down: the first service that is.
function paintStatusPill(services) {
  const pill = $("statusPillBtn");
  if (!pill) return;
  const down = services.filter((s) => !s.ok);
  pill.classList.toggle("is-down", down.length > 0);
  const text = $("statusPillText");
  if (text && down.length) text.textContent = `${down[0].name} ${down[0].state || "offline"}`;   // CHANGED (1.6.0)
  else if (text && readyLamp.classList.contains("is-lit")) text.textContent = "Ready";
}

function renderServiceChips(services) {
  const signature = services.map((s) => s.id).join(",");
  if (signature !== renderedServiceIds) {
    serviceStatus.replaceChildren(...services.map(buildServiceBlock));
    renderedServiceIds = signature;
  }
  services.forEach((service, index) => {
    const block = serviceStatus.children[index];
    if (block) paintServiceBlock(block, service);
  });
  paintStatusPill(services);
}

// Kept for the callers that still ask; nothing expands any more.
function collapseAllServicePanels() {}

async function loadLocalStatus() {
  if (!serviceStatus) return;
  try {
    const res = await fetch("/api/local-status");
    const data = await res.json();

    if (!res.ok || data.none_selected) {
      serviceStatus.replaceChildren();
      renderedServiceIds = "";
      serviceStatus.classList.add("is-hidden");
      paintStatusPill([]);
      return;
    }

    serviceStatus.classList.remove("is-hidden");
    // One chip per service rather than one chip for all of them: they go
    // down independently and for unrelated reasons, and "2 services
    // offline" made you hover to find out which.
    renderServiceChips(data.services);
  } catch (err) {
    // The app's own server is unreachable — the page has bigger problems
    // than a provider being down, and its own errors will say so.
    serviceStatus.classList.add("is-hidden");
  }
}

function startLocalStatusPolling() {
  clearInterval(localStatusTimer);
  loadLocalStatus();
  localStatusTimer = setInterval(loadLocalStatus, LOCAL_STATUS_POLL_MS);
}

if (serviceStatus) {
  // Delegated, because the blocks are rebuilt when the service set changes.
  // CHANGED (2.0): a row opens that service's settings.
  serviceStatus.addEventListener("click", (event) => {
    const block = event.target.closest(".service-block");
    if (!block) return;
    const target = SERVICE_SETTINGS_TARGET[block.dataset.serviceId];
    if (!target) return;
    if (typeof closeAllPopovers === "function") closeAllPopovers();
    setSettingsOpen(true);
    if (typeof showSettingsSection === "function") showSettingsSection(target.section);
    if (target.page && typeof openSettingsPage === "function") openSettingsPage(target.page);
  });
}


let providerCatalog = {
  chat: [],
  translation: [],
  transcription: [],
};

function providerNoteFor(list, id) {
  const match = list.find((p) => p.id === id);
  return match ? match.note || "" : "";
}

function anyProviderIs(value) {
  return [
    getRadioValue(chatProviderRadios, "openai"),
    getRadioValue(translationProviderRadios, "openai"),
  ].includes(value);
}

let whisperModelsLoaded = false;

function syncProviderVisibility() {
  if (ollamaSettings) {
    ollamaSettings.classList.toggle("is-hidden", !anyProviderIs("ollama"));
  }
  if (typeof syncAiChip === "function") syncAiChip();   // NEW (1.5.0)
  if (whisperSettings) {
    const usingLocal =
      getRadioValue(transcriptionProviderRadios, "openai") === "local_whisper";
    whisperSettings.classList.toggle("is-hidden", !usingLocal);

    // Switching to local Whisper reveals the panel — fetch the real model
    // list the moment it becomes visible rather than waiting for a Test.
    if (usingLocal && !whisperModelsLoaded) {
      whisperModelsLoaded = true;
      loadWhisperModels();
    }
  }
}

function buildProviderPickers(settings) {
  const groups = [
    {
      el: chatProviderRadios,
      noteEl: chatProviderNote,
      list: settings.chat_providers || [],
      selected: settings.chat_provider || "openai",
      name: "chat_provider",
      key: "chat",
    },
    {
      el: translationProviderRadios,
      noteEl: translationProviderNote,
      list: settings.translation_providers || [],
      selected: settings.translation_provider || "openai",
      name: "translation_provider",
      key: "translation",
    },
    {
      el: transcriptionProviderRadios,
      noteEl: transcriptionProviderNote,
      list: settings.transcription_providers || [],
      selected: settings.transcription_provider || "openai",
      name: "transcription_provider",
      key: "transcription",
    },
  ];

  groups.forEach((group) => {
    if (!group.el) return;
    providerCatalog[group.key] = group.list;
    buildRadioGroup(group.el, group.list, group.name, group.selected, (id) => {
      if (group.noteEl) group.noteEl.textContent = providerNoteFor(group.list, id);
      syncProviderVisibility();
    });
    if (group.noteEl) {
      group.noteEl.textContent = providerNoteFor(group.list, group.selected);
      // NEW (1.6.0): the cards say it themselves.
      group.noteEl.classList.toggle("is-hidden", group.list.some((p) => p.summary));
    }
  });

  if (ollamaUrl) ollamaUrl.value = settings.ollama_url || "";
  if (ollamaModel) ollamaModel.value = settings.ollama_model || "";
  if (ollamaModelBalanced) ollamaModelBalanced.value = settings.ollama_model_balanced || "";   // NEW (1.5.0)
  if (ollamaModelBest) ollamaModelBest.value = settings.ollama_model_best || "";               // NEW (1.5.0)
  if (ollamaIdleUnload) ollamaIdleUnload.value = settings.ollama_idle_unload || "1h";        // NEW (1.5.0)
  if ($("builtinIdle")) $("builtinIdle").value = settings.builtin_ai_idle || "1h";            // NEW (1.6.0)
  if ($("evoraIdleListen")) $("evoraIdleListen").value = settings.evora_idle_listen || "5m";   // NEW (1.5.0)
  if ($("evoraIdleSpeech")) $("evoraIdleSpeech").value = settings.evora_idle_speech || "1h";   // NEW (1.5.0)
  if (typeof setAiChipTier === "function") setAiChipTier(settings.ollama_tier || "fast");     // NEW (1.5.0)
  if (ollamaTranslationModel) {
    ollamaTranslationModel.value = settings.ollama_translation_model || "";
  }
  if (whisperUrl) whisperUrl.value = settings.whisper_url || "";
  if (allowFallbackToggle) allowFallbackToggle.checked = Boolean(settings.allow_openai_fallback);
  // NEW (1.6.0): only offered with an OpenAI key to fall back on.
  if ($("allowFallbackRow")) $("allowFallbackRow").classList.toggle("is-hidden", !settings.openai_key_set);

  syncProviderVisibility();
  if (typeof omCardUses === "function") omCardUses();   // NEW (1.6.0): your models' sizes, once known

  // Populate the model dropdown straight away when local Whisper is the
  // selected provider. Previously this only happened after clicking Test,
  // which left an empty control sitting there looking broken.
  if (settings.transcription_provider === "local_whisper") {
    loadWhisperModels();
  } else if (whisperModelSelect) {
    fillWhisperModelOptions(WHISPER_MODEL_FALLBACK, "medium");
  }
}

async function testProvider(kind, urlInput, noteEl, button) {
  if (!noteEl) return;
  noteEl.className = "field-note";
  noteEl.textContent = "Testing…";
  if (button) button.disabled = true;

  try {
    const res = await fetch("/api/provider-test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, url: urlInput ? urlInput.value.trim() : "" }),
    });
    const data = await res.json();
    noteEl.textContent = data.message || (data.ok ? "Connected." : "Couldn't connect.");
    noteEl.className = `field-note ${data.ok ? "test-ok" : "test-fail"}`;
  } catch (err) {
    noteEl.textContent = `Test failed: ${err.message}`;
    noteEl.className = "field-note test-fail";
  } finally {
    if (button) button.disabled = false;
  }
}

if (testOllamaBtn) {
  testOllamaBtn.addEventListener("click", () =>
    testProvider("ollama", ollamaUrl, ollamaTestNote, testOllamaBtn)
  );
}
if (testWhisperBtn) {
  testWhisperBtn.addEventListener("click", async () => {
    await testProvider("whisper", whisperUrl, whisperTestNote, testWhisperBtn);
    loadWhisperModels();
  });
}

// Shown when the server can't be reached. A dropdown with nothing in it is
// worse than a wrong one — it renders as an empty popup strip and gives no
// clue whether the feature is broken or just not loaded yet.
const WHISPER_MODEL_FALLBACK = [
  { id: "tiny", vram: "~0.4GB", note: "Fastest, least accurate." },
  { id: "base", vram: "~0.6GB", note: "Still weak for real speech." },
  { id: "small", vram: "~1GB", note: "Fast. Use if Ollama shares the card." },
  { id: "medium", vram: "~3GB", note: "Good balance of speed and accuracy." },
  { id: "large-v3", vram: "~5GB", note: "Most accurate. Needs the card to itself." },
];

function fillWhisperModelOptions(models, selected) {
  whisperModelSelect.innerHTML = "";
  models.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent = `${m.id} — ${m.vram}`;
    opt.title = m.note || "";
    whisperModelSelect.appendChild(opt);
  });
  if (selected) whisperModelSelect.value = selected;
}

async function loadWhisperModels() {
  if (!whisperModelSelect) return;

  try {
    const res = await fetch("/api/whisper-model");
    const data = await res.json();

    if (!res.ok || !data.available_models) {
      fillWhisperModelOptions(WHISPER_MODEL_FALLBACK, "medium");
      whisperModelNote.textContent =
        (data.error || "Couldn't reach Evora.") +
        " Showing the standard models — Apply will retry.";
      whisperModelNote.className = "field-note test-fail";
      return;
    }

    fillWhisperModelOptions(data.available_models, data.model);
    const current = data.available_models.find((m) => m.id === data.model);
    whisperModelNote.textContent = current
      ? `Loaded: ${data.model} on ${data.device}. ${current.note}`
      : `Loaded: ${data.model} on ${data.device}.`;
    whisperModelNote.className = "field-note";
  } catch (err) {
    fillWhisperModelOptions(WHISPER_MODEL_FALLBACK, "medium");
    whisperModelNote.textContent = `Couldn't load model list: ${err.message}`;
    whisperModelNote.className = "field-note test-fail";
  }
}

if (applyWhisperModelBtn) {
  applyWhisperModelBtn.addEventListener("click", async () => {
    const wanted = whisperModelSelect.value;
    applyWhisperModelBtn.disabled = true;
    whisperModelNote.className = "field-note";
    // A cold model has to be downloaded first, which is minutes rather than
    // seconds — say so rather than looking hung.
    whisperModelNote.textContent =
      `Loading ${wanted}… first use of a model downloads it, which can take a few minutes.`;
    try {
      const res = await fetch("/api/whisper-model", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: wanted }),
      });
      const data = await res.json();
      whisperModelNote.textContent = data.message || data.error || "Done.";
      whisperModelNote.className = `field-note ${res.ok ? "test-ok" : "test-fail"}`;
      if (res.ok) loadWhisperModels();
    } catch (err) {
      whisperModelNote.textContent = `Failed: ${err.message}`;
      whisperModelNote.className = "field-note test-fail";
    } finally {
      applyWhisperModelBtn.disabled = false;
    }
  });
}


const CUSTOM_MODEL_ID = "__custom__";

function formatModelPrice(model) {
  return `$${model.input_price.toFixed(2)} / $${model.output_price.toFixed(2)} per 1M tok`;
}

function buildModelList(containerEl, customInputEl, models, groupName, selectedId, recommendedId, onChange) {
  containerEl.innerHTML = "";
  const knownIds = new Set(models.map((m) => m.id));
  const isCustom = !knownIds.has(selectedId);

  models.forEach((model) => {
    const row = document.createElement("label");
    row.className = "model-row";
    if (model.id === selectedId) row.classList.add("is-checked");

    const input = document.createElement("input");
    input.type = "radio";
    input.name = groupName;
    input.value = model.id;
    if (model.id === selectedId) input.checked = true;

    const main = document.createElement("span");
    main.className = "model-row-main";

    const name = document.createElement("span");
    name.className = "model-row-name";
    name.textContent = model.name;
    main.appendChild(name);

    if (model.id === recommendedId) {
      const badge = document.createElement("span");
      badge.className = "model-row-badge";
      badge.textContent = "Recommended";
      main.appendChild(badge);
    }

    const meta = document.createElement("span");
    meta.className = "model-row-meta";
    meta.textContent = `${modelTierSpeedLabel[model.tier] || model.tier} · ${formatModelPrice(model)}`;

    row.title = model.note || "";
    row.append(input, main, meta);

    input.addEventListener("change", () => {
      containerEl.querySelectorAll(".model-row").forEach((r) => r.classList.remove("is-checked"));
      row.classList.add("is-checked");
      customInputEl.classList.add("is-hidden");
      if (onChange) onChange(model.id);
    });

    containerEl.appendChild(row);
  });

  // The "Custom model ID" row itself — same structure, but selecting it
  // reveals the text input instead of carrying a model in its own value.
  const customRow = document.createElement("label");
  customRow.className = "model-row";
  if (isCustom) customRow.classList.add("is-checked");

  const customInput = document.createElement("input");
  customInput.type = "radio";
  customInput.name = groupName;
  customInput.value = CUSTOM_MODEL_ID;
  if (isCustom) customInput.checked = true;

  const customMain = document.createElement("span");
  customMain.className = "model-row-main";
  const customName = document.createElement("span");
  customName.className = "model-row-name";
  customName.textContent = "Custom model ID";
  customMain.appendChild(customName);

  customRow.append(customInput, customMain);

  customInput.addEventListener("change", () => {
    containerEl.querySelectorAll(".model-row").forEach((r) => r.classList.remove("is-checked"));
    customRow.classList.add("is-checked");
    customInputEl.classList.remove("is-hidden");
    customInputEl.focus();
    if (onChange) onChange(CUSTOM_MODEL_ID);
  });

  containerEl.appendChild(customRow);

  if (isCustom) {
    customInputEl.value = selectedId;
    customInputEl.classList.remove("is-hidden");
  } else {
    customInputEl.classList.add("is-hidden");
  }
}

function getModelValue(containerEl, customInputEl, fallback) {
  const selected = getRadioValue(containerEl, fallback);
  if (selected === CUSTOM_MODEL_ID) {
    return customInputEl.value.trim() || fallback;
  }
  return selected;
}

// ---------- Cost/speed estimates for the model pickers ----------
// Approximate model cost and speed estimates for UI guidance only.

const ESTIMATED_INPUT_TOKENS = 450; // system prompt + a little history + the message
const HEAVY_LANGUAGES = new Set([
  "Japanese", "Chinese", "Korean", "Russian", "Ukrainian", "Bulgarian", "Greek", "Arabic", "Hindi", "Tamil",
]);

function estimateOutputTokens(words, language) {
  const perWord = HEAVY_LANGUAGES.has(language) ? 3.0 : 1.4;
  return Math.round(words * perWord);
}

function formatModelCost(dollars) {
  if (dollars < 0.01) return `~${(dollars * 100).toFixed(3)}¢`;
  return `~$${dollars.toFixed(4)}`;
}

function updateModelEstimate(estimateEl, models, containerEl, customInputEl, outputTokens, fallbackId) {
  const selectedId = getModelValue(containerEl, customInputEl, fallbackId);
  const model = models.find((m) => m.id === selectedId);
  if (!model) {
    estimateEl.textContent = "Custom model — no price/speed data available for it here.";
    return;
  }
  const inputCost = (ESTIMATED_INPUT_TOKENS / 1e6) * model.input_price;
  const outputCost = (outputTokens / 1e6) * model.output_price;
  const totalCost = inputCost + outputCost;
  const throughput = modelTierThroughput[model.tier] || 60;
  const seconds = 0.6 + outputTokens / throughput;
  // One line for why this model, one for the cost/speed estimate — replaces
  // repeating the reason sentence on all eight rows with just the one that's
  // actually relevant right now.
  estimateEl.innerHTML =
    `<span class="model-estimate-why">${model.note || ""}</span><br>` +
    `<strong>${formatModelCost(totalCost)}</strong> per reply · ` +
    `<strong>~${seconds.toFixed(1)}s</strong> to generate (estimates, not a bill)`;
}

function updateTextModelEstimate() {
  const words = parseInt(lengthSlider.value, 10) || 80;
  const outputTokens = estimateOutputTokens(words, currentLanguage);
  updateModelEstimate(textModelEstimate, textModels, textModelList, textModelCustom, outputTokens, recommendedTextModel);
}

function updateTranslationModelEstimate() {
  // The translation is roughly the same length as the reply it's translating.
  const words = parseInt(lengthSlider.value, 10) || 80;
  const outputTokens = estimateOutputTokens(words, "English");
  updateModelEstimate(
    translationModelEstimate, textModels, translationModelList, translationModelCustom, outputTokens, recommendedTranslationModel
  );
}

// ---------- Language ----------

const languageSelect = $("languageSelect");
const languageNote = $("languageNote");
const languageSuggestBtn = $("languageSuggestBtn");
let languages = [];
let currentLanguage = localStorage.getItem("voice_console_language") || "English";

function currentCharsPerWord() {
  const match = languages.find((l) => l.name === currentLanguage);
  return match ? match.chars : 6.0;
}

// The last few languages actually used, so the ones you switch between sit
// at the top instead of being hunted for in a list of 29 every time.
const LANGUAGE_RECENTS_KEY = "voice_console_language_recents";
const LANGUAGE_RECENTS_MAX = 4;

function languageRecents() {
  try {
    const raw = JSON.parse(localStorage.getItem(LANGUAGE_RECENTS_KEY) || "[]");
    return Array.isArray(raw) ? raw.filter((x) => typeof x === "string") : [];
  } catch (err) {
    return [];
  }
}

function noteLanguageUsed(name) {
  const next = [name, ...languageRecents().filter((x) => x !== name)].slice(0, LANGUAGE_RECENTS_MAX);
  localStorage.setItem(LANGUAGE_RECENTS_KEY, JSON.stringify(next));
}

function languageLabel(l) {
  return l.native === l.name ? l.name : `${l.name} · ${l.native}`;
}

function languageOption(l, selected) {
  const opt = document.createElement("option");
  opt.value = l.name;
  opt.textContent = languageLabel(l);
  if (l.name === selected) opt.selected = true;
  return opt;
}

// Grouped by region, with a Recent group on top. A flat 29-item list gives
// you nothing to navigate by; grouping means one glance finds the section
// and one more finds the language.
function fillLanguages(list, selected) {
  languages = list;
  languageSelect.innerHTML = "";

  const recents = languageRecents().filter((name) => list.some((l) => l.name === name));
  if (recents.length > 1) {
    const group = document.createElement("optgroup");
    group.label = "Recent";
    recents.forEach((name) => {
      const l = list.find((x) => x.name === name);
      if (l) group.appendChild(languageOption(l, selected));
    });
    languageSelect.appendChild(group);
  }

  // Regions in the order app.py lists them, not alphabetically — that keeps
  // the languages most people here will want near the top.
  const regions = [];
  list.forEach((l) => {
    const region = l.region || "All languages";
    if (!regions.includes(region)) regions.push(region);
  });

  regions.forEach((region) => {
    const group = document.createElement("optgroup");
    group.label = region;
    list
      .filter((l) => (l.region || "All languages") === region)
      .forEach((l) => group.appendChild(languageOption(l, selected)));
    languageSelect.appendChild(group);
  });

  // A language appearing twice (Recent plus its region) means the browser
  // would otherwise select whichever copy came last.
  languageSelect.value = selected;
  syncLanguageSuggestion();
  showLanguageTrigger();
}


function profileLanguage() {
  const p = activeProfile();
  return p && p.language ? p.language : "";
}

function syncLanguageSuggestion() {
  const suggested = profileLanguage();
  const show = Boolean(suggested) && suggested !== currentLanguage;
  languageSuggestBtn.classList.toggle("is-hidden", !show);
  if (!show) return;

  const match = languages.find((l) => l.name === suggested);
  languageSuggestBtn.textContent = `Use ${match ? match.native : suggested}`;
  const p = activeProfile();
  languageSuggestBtn.title = `${p ? p.name : "This profile"} is meant for ${suggested}`;
}

async function setLanguage(name, { announce = true } = {}) {
  if (!name || name === currentLanguage) return;
  currentLanguage = name;
  languageSelect.value = name;
  localStorage.setItem("voice_console_language", currentLanguage);
  noteLanguageUsed(currentLanguage);
  updateFaderReadout();
  updateTextModelEstimate();
  updateTranslationModelEstimate();
  refreshPromptIfOpen();
  syncLanguageSuggestion();
  showLanguageTrigger();
  if (announce) setStatus(`Replying in ${currentLanguage}.`);
  await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language: currentLanguage }),
  });
}

languageSuggestBtn.addEventListener("click", () => {
  const suggested = profileLanguage();
  if (suggested) setLanguage(suggested);
});

languageSelect.addEventListener("change", () => {
  setLanguage(languageSelect.value);
});

// ---------- Fader ----------

function updateFaderReadout() {
  const words = parseInt(lengthSlider.value, 10);
  // Characters per word varies a lot by language, and ElevenLabs bills per
  // character — so the same word count costs very different amounts in,
  // say, Finnish versus Chinese.
  const chars = Math.round(words * currentCharsPerWord());
  const seconds = Math.round((chars / 1000) * 60);
  // CHANGED (1.5.0): the unit is its own span, so a crowded chip row can
  // drop it ("50") and keep the voice chip's name whole. Text is unchanged.
  lengthValue.textContent = String(words);
  const lengthUnit = document.createElement("span");
  lengthUnit.className = "chip-unit";
  lengthUnit.textContent = " words";
  lengthValue.append(lengthUnit);
  if (typeof fitSessionStrip === "function") fitSessionStrip();
  const big = $("lengthValueBig");  // CHANGED (2.0): the chip and its popover both say it
  if (big) big.textContent = `${words} words`;
  lengthEcho.textContent = words;
  creditEcho.textContent = chars.toLocaleString();
  secondsEcho.textContent = seconds;
  // NEW (1.5.0): a free voice costs no credits, so don't quote any.
  const free = typeof isFreeVoiceId === "function" && isFreeVoiceId(activeVoiceId());
  const creditPart = $("creditPart");
  const freePart = $("freePart");
  if (creditPart && freePart) {
    creditPart.style.display = free ? "none" : "";
    freePart.style.display = free ? "" : "none";
  }
}

lengthSlider.addEventListener("input", () => {
  updateFaderReadout();
  updateTextModelEstimate();
  updateTranslationModelEstimate();
  refreshPromptIfOpen();
});

// Persist the fader position when the user lets go
lengthSlider.addEventListener("change", async () => {
  await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ max_words: parseInt(lengthSlider.value, 10) }),
  });
});

async function handleSettingsResponseStyleChange(value) {
  showStyleNote(responseStyleNote, value);  // NEW (1.5.0)
  refreshPromptIfOpen();
  await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ response_style: value }),
  });
}

personalityPresetSelect.addEventListener("change", async () => {
  refreshPromptIfOpen();
  await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ personality_preset: personalityPresetSelect.value }),
  });
});


const TARGET_RMS = 0.1;   // roughly -20 dBFS, a normal loudness for speech
const MIN_CLIP_GAIN = 0.6;
const MAX_CLIP_GAIN = 2.2; // capped so a near-silent clip isn't boosted into audible hiss
const CLIP_CEILING = 0.98; // headroom so normalization never causes hard-clipping

let audioCtx = null;
let masterGain = null;
let masterVolume = clampVolumePct(localStorage.getItem("voice_console_volume")) / 100;

function clampVolumePct(value) {
  const n = parseInt(value, 10);
  if (!isFinite(n)) return 100;
  return Math.min(150, Math.max(0, n));
}


function ensureAudioContext() {
  if (!audioCtx) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    audioCtx = new Ctx();
    masterGain = audioCtx.createGain();
    masterGain.gain.value = masterVolume;
    masterGain.connect(audioCtx.destination);
  }
  if (audioCtx.state === "suspended") audioCtx.resume();
  return audioCtx;
}

function computeClipGain(channelData) {
  let sumSquares = 0;
  let peak = 0;
  for (let i = 0; i < channelData.length; i++) {
    const v = channelData[i];
    sumSquares += v * v;
    const abs = Math.abs(v);
    if (abs > peak) peak = abs;
  }
  const rms = Math.sqrt(sumSquares / channelData.length);
  if (rms < 1e-6) return 1; // silent or near-silent — leave it alone

  let gain = TARGET_RMS / rms;
  gain = Math.min(MAX_CLIP_GAIN, Math.max(MIN_CLIP_GAIN, gain));

  // Never let normalization push a clip's peak into clipping, even if that
  // means falling short of the target loudness for something spiky.
  if (peak * gain > CLIP_CEILING) {
    gain = CLIP_CEILING / peak;
  }
  return gain;
}

function setMasterVolume(pct) {
  masterVolume = clampVolumePct(pct) / 100;
  localStorage.setItem("voice_console_volume", String(clampVolumePct(pct)));
  if (masterGain) masterGain.gain.value = masterVolume;
  // Clips that fell back to a plain <audio> element (decode failed) don't
  // go through the Web Audio graph, so update them directly. Native volume
  // caps at 1.0 — no boosting past 100% for these.
  document.querySelectorAll(".bubble.is-fallback audio").forEach((a) => {
    a.volume = Math.min(1, masterVolume);
  });
}

function formatTime(totalSeconds) {
  if (!isFinite(totalSeconds) || totalSeconds < 0) return "0:00";
  const m = Math.floor(totalSeconds / 60);
  const s = Math.floor(totalSeconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

// The play/pause icons went with the separate player. The bubble is the
// control now, and its state is carried by the progress line rather than by
// a glyph.

function pauseOtherPlayers(except) {
  document.querySelectorAll(".bubble.is-playing").forEach((el) => {
    if (el !== except && typeof el._pause === "function") el._pause();
  });
}

function attachBubbleAudio(wrap, url, onStart, onPlayback, extras = {}) {   // CHANGED (1.5.0): onPlayback, extras
  wrap.classList.add("has-audio", "is-loading");
  // NEW (1.5.0): the glow that follows the voice, and the word highlight.
  const visuals = typeof makeSpeechVisuals === "function" ? makeSpeechVisuals(wrap, extras.wordTimes) : null;
  wrap.setAttribute("role", "button");
  wrap.setAttribute("tabindex", "0");
  wrap.setAttribute("aria-label", "Loading audio");

  let started = false;
  function fireStart() {
    if (started) return;
    started = true;
    if (typeof onStart === "function") onStart();
  }

  // NEW (1.5.0): says when the voice starts, stops and where it is, so the
  // chatbox pages can keep up with it. A follower that throws never stops
  // the audio.
  function report(playing, offset, dur) {
    if (typeof onPlayback !== "function") return;
    try {
      onPlayback(playing, offset, dur);
    } catch (e) {
      console.warn("Chatbox pages:", e);
    }
  }

  // Sits on the bubble's bottom edge and fills as it plays. Absolutely
  // positioned so it can't change the bubble's size when it appears — the
  // message must not resize just because you pressed play.
  const track = document.createElement("span");
  track.className = "bubble-progress";
  const fill = document.createElement("span");
  fill.className = "bubble-progress-fill";
  track.appendChild(fill);
  wrap.appendChild(track);

  const time = document.createElement("span");
  time.className = "bubble-time";
  time.textContent = "";
  wrap.appendChild(time);

  // Playback state. AudioBufferSourceNode can only be started once, so
  // pausing means stopping it and creating a fresh one from the stored
  // offset — that's the standard pattern for this API.
  const state = {
    buffer: null,
    clipGain: 1,
    sourceNode: null,
    isPlaying: false,
    startedAt: 0,
    offset: 0,
    rafId: null,
    manualStop: false,
  };

  const duration = () => (state.buffer ? state.buffer.duration : 0);
  const currentTime = () =>
    state.isPlaying ? state.offset + (audioCtx.currentTime - state.startedAt) : state.offset;

  function updateUI() {
    const dur = duration();
    const cur = Math.min(currentTime(), dur);
    // The label only shows the total, and only while idle. A running
    // counter on every message is noise you can't switch off; the moving
    // progress line already says where it is.
    time.textContent = formatTime(state.isPlaying ? dur - cur : dur);
    fill.style.width = dur ? `${(cur / dur) * 100}%` : "0%";
  }

  function tick() {
    updateUI();
    if (visuals && state.isPlaying) visuals.update(currentTime());   // NEW (1.5.0)
    if (state.isPlaying) state.rafId = requestAnimationFrame(tick);
  }

  function setPlayingUI(isPlaying) {
    wrap.classList.toggle("is-playing", isPlaying);
    if (visuals && !isPlaying) visuals.stop();   // NEW (1.5.0)
    wrap.setAttribute("aria-label", isPlaying ? "Pause reply" : "Play reply");
  }

  function stopSource() {
    if (state.sourceNode) {
      state.manualStop = true;
      try { state.sourceNode.stop(); } catch (e) { /* already stopped */ }
      state.sourceNode.disconnect();
      state.sourceNode = null;
    }
  }

  function play() {
    if (!state.buffer || state.isPlaying) return;
    ensureAudioContext();
    if (state.offset >= state.buffer.duration) state.offset = 0;

    pauseOtherPlayers(wrap);

    const source = audioCtx.createBufferSource();
    source.buffer = state.buffer;
    const clipGainNode = audioCtx.createGain();
    clipGainNode.gain.value = state.clipGain;
    source.connect(clipGainNode);
    clipGainNode.connect(masterGain);

    state.manualStop = false;
    source.onended = () => {
      if (state.manualStop) return; // stopped for pause, not natural end
      state.isPlaying = false;
      state.offset = 0;
      setPlayingUI(false);
      updateUI();
      if (state.rafId) cancelAnimationFrame(state.rafId);
      report(false, state.buffer.duration, state.buffer.duration);   // NEW (1.5.0): played to the end
    };

    source.start(0, state.offset);
    state.sourceNode = source;
    state.startedAt = audioCtx.currentTime;
    state.isPlaying = true;
    setPlayingUI(true);
    tick();
    // After start(), not before: the audio is genuinely running by this
    // point, so anything keyed to "when the voice starts" is accurate
    // rather than optimistic.
    fireStart();
    report(true, state.offset, state.buffer.duration);   // NEW (1.5.0)
  }

  function pause() {
    if (!state.isPlaying) return;
    state.offset = currentTime();
    stopSource();
    state.isPlaying = false;
    report(false, state.offset, duration());   // NEW (1.5.0)
    setPlayingUI(false);
    if (state.rafId) cancelAnimationFrame(state.rafId);
    updateUI();
  }
  wrap._pause = pause;

  function toggle() {
    // Set by the fallback path when Web Audio couldn't decode the clip.
    if (typeof wrap._toggle === "function") return wrap._toggle();
    if (!state.buffer) {
      load();   // NEW (1.5.0): a restored reply loads its audio on the first click
      return;
    }
    if (state.isPlaying) pause();
    else play();
  }

  wrap.addEventListener("click", (e) => {
    // Selecting text in a message shouldn't also start playing it.
    const selection = window.getSelection();
    if (selection && String(selection).length) return;
    toggle();
  });
  wrap.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggle();
    }
  });

  // CHANGED (1.5.0): in a function, so a reply restored after a refresh can
  // wait for a click instead of fetching (and playing) every old reply at
  // once. A reply whose audio has been cleaned up (after 7 days) says so.
  let loadStarted = false;
  function load() {
  if (loadStarted) return;
  loadStarted = true;
  wrap.classList.add("is-loading");
  fetch(url)
    .then((r) => {
      if (!r.ok) {
        const gone = new Error("gone");
        gone.gone = true;
        throw gone;
      }
      return r.arrayBuffer();
    })
    .then((buf) => ensureAudioContext().decodeAudioData(buf))
    .then((decoded) => {
      state.buffer = decoded;
      state.clipGain = computeClipGain(decoded.getChannelData(0));
      if (visuals) visuals.setBuffer(decoded);   // NEW (1.5.0)
      wrap.classList.remove("is-loading");
      setPlayingUI(false);
      updateUI();
      play(); // autoplay once decoded, matching the previous behavior
    })
    .catch((err) => {
      if (err && err.gone) {   // NEW (1.5.0)
        wrap.classList.remove("is-loading", "has-audio");
        wrap.classList.add("is-audio-gone");
        wrap.removeAttribute("role");
        wrap.removeAttribute("tabindex");
        wrap.removeAttribute("aria-label");
        wrap.title = "The audio for this reply has been cleaned up (spoken replies are kept for 7 days). Save a reply to keep it.";
        setStatus("That reply's audio has been cleaned up. Spoken replies are kept 7 days unless saved.", true);
        return;
      }
      // Rare: some audio can't be decoded by the Web Audio API. Fall back
      // to a plain element so playback still works, just without
      // normalization — better than a dead player.
      wrap.classList.remove("is-loading");
      wrap.classList.add("is-fallback");

      const audio = document.createElement("audio");
      audio.src = url;
      audio.volume = Math.min(1, masterVolume);
      audio.autoplay = true;
      wrap._pause = () => audio.pause();
      audio.addEventListener("play", fireStart);
      audio.addEventListener("play", () => setPlayingUI(true));
      audio.addEventListener("pause", () => setPlayingUI(false));
      audio.addEventListener("ended", () => setPlayingUI(false));
      audio.addEventListener("play", () => pauseOtherPlayers(wrap));
      // NEW (1.5.0): the chatbox pages follow this player too.
      const audioLength = () => (Number.isFinite(audio.duration) ? audio.duration : 0);
      audio.addEventListener("playing", () => report(true, audio.currentTime, audioLength()));
      audio.addEventListener("pause", () => report(false, audio.currentTime, audioLength()));
      audio.addEventListener("ended", () => report(false, audioLength(), audioLength()));
      // Clicking the bubble drives the fallback element too, so the
      // interaction is the same whichever path a clip took.
      wrap._toggle = () => (audio.paused ? audio.play() : audio.pause());
      wrap.appendChild(audio);
    });
  }
  // NEW (1.5.0): a streamed reply ("Start speaking sooner"). It plays as
  // the audio arrives, through the same volume. Its timings (word glow,
  // chatbox pages) and its finished file come once ElevenLabs is done; after
  // it has played, the bubble plays that file like any other reply.
  function startStream() {
    const ctx = ensureAudioContext();
    const el = new Audio();
    el.preload = "auto";
    let analyser = null;
    let samples = null;
    try {
      const source = ctx.createMediaElementSource(el);
      analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      samples = new Float32Array(analyser.fftSize);
      source.connect(analyser);
      analyser.connect(masterGain);
    } catch (e) {
      el.volume = Math.min(1, masterVolume);   // straight out, without the mixer
      analyser = null;
    }
    let playing = false;
    let ended = false;
    let finalUrl = null;
    let knownDuration = null;
    let rafS = null;
    const estimate = () => {
      const words = (wrap.textContent || "").trim().split(/\s+/).length;
      return Math.max(1, words / 2.6);
    };
    const dur = () => knownDuration || (Number.isFinite(el.duration) ? el.duration : 0);
    function ui() {
      const d = dur();
      const cur = el.currentTime;
      time.textContent = d ? formatTime(playing ? Math.max(0, d - cur) : d) : "";
      fill.style.width = d ? `${Math.min(100, (cur / d) * 100)}%` : "0%";
    }
    function loop() {
      ui();
      if (visuals && playing) {
        visuals.update(el.currentTime);
        if (analyser) {
          analyser.getFloatTimeDomainData(samples);
          let sum = 0;
          for (let i = 0; i < samples.length; i += 2) sum += samples[i] * samples[i];
          visuals.liveLevel(Math.min(1, Math.sqrt(sum / (samples.length / 2)) / 0.12));
        }
      }
      if (playing) rafS = requestAnimationFrame(loop);
    }
    function becomeFile() {
      // Played to the end and the file is ready: from now on it's an
      // ordinary reply (click to play again, from the file).
      if (!ended || !finalUrl) return;
      url = finalUrl;
      delete wrap._toggle;
      wrap._pause = pause;
      loadStarted = false;
      el.removeAttribute("src");
    }
    el.addEventListener("playing", () => {
      wrap.classList.remove("is-loading");
      playing = true;
      setPlayingUI(true);
      fireStart();
      report(true, el.currentTime, dur() || estimate());
      loop();
    });
    el.addEventListener("pause", () => {
      if (ended) return;
      playing = false;
      if (rafS) cancelAnimationFrame(rafS);
      setPlayingUI(false);
      report(false, el.currentTime, dur() || estimate());
      ui();
    });
    el.addEventListener("ended", () => {
      ended = true;
      playing = false;
      if (rafS) cancelAnimationFrame(rafS);
      setPlayingUI(false);
      report(false, dur() || el.currentTime, dur() || el.currentTime);
      ui();
      becomeFile();
    });
    el.addEventListener("error", () => {
      if (ended) return;
      // The stream broke: the finished file, once there is one.
      playing = false;
      wrap.classList.remove("is-loading");
      setPlayingUI(false);
      ended = true;
      becomeFile();
    });
    wrap._pause = () => { if (!el.paused) el.pause(); };
    wrap._toggle = () => {
      if (ended) return;
      if (el.paused) { pauseOtherPlayers(wrap); el.play().catch(() => {}); } else el.pause();
    };
    pauseOtherPlayers(wrap);
    el.src = url;
    el.play().catch(() => {
      // The browser wouldn't start it on its own: a click will.
      wrap.classList.remove("is-loading");
      wrap.setAttribute("aria-label", "Play reply");
    });
    // The timings and the file, when ElevenLabs is done.
    (async function follow() {
      for (let tries = 0; tries < 30; tries++) {
        let t;
        try {
          const res = await fetch(`${extras.stream.timingUrl}?wait=8`);
          if (!res.ok) return;
          t = await res.json();
        } catch (e) {
          await new Promise((r) => setTimeout(r, 1000));
          continue;
        }
        if (!t.done) continue;
        if (t.duration) knownDuration = t.duration;
        if (t.word_times && visuals) visuals.setWordTimes(t.word_times);
        if (t.audio_url) finalUrl = t.audio_url;
        if (typeof extras.onTiming === "function") {
          try { extras.onTiming(t); } catch (e) { console.warn("Stream timing:", e); }
        }
        if (t.error && !t.audio_url) setStatus(t.error, true);
        else if (t.notice) setStatus(t.notice, true);
        becomeFile();
        return;
      }
    })();
  }

  if (extras.lazy) {
    wrap.classList.remove("is-loading");
    wrap.setAttribute("aria-label", "Play reply");
  } else if (extras.stream && extras.stream.timingUrl) {
    startStream();   // NEW (1.5.0)
  } else {
    load();
  }
}


const translationCache = new Map();
let hoverTimer = null;
let activeTooltip = null;

function closeTooltip() {
  if (activeTooltip) {
    activeTooltip.remove();
    activeTooltip = null;
  }
}

// Viewport-positioned, so anything that moves the message out from under it
// has to be answered. Scrolling the conversation while a translation is up
// would otherwise leave it stranded mid-air.
document.addEventListener(
  "scroll",
  () => {
    if (activeTooltip && activeTooltip._anchor) {
      positionTooltip(activeTooltip, activeTooltip._anchor);
    }
  },
  true
);
window.addEventListener("resize", closeTooltip);

function positionTooltip(tooltip, anchor) {
  const bubble = anchor.getBoundingClientRect();
  const turn = anchor.closest(".turn");
  // Cleared against the whole message, not just the bubble: the sender name
  // sits above it and the stats line below, and both are part of what you
  // were looking at when you hovered.
  const box = turn ? turn.getBoundingClientRect() : bubble;
  const margin = 10;
  const gap = 8;

  tooltip.style.maxWidth = `${Math.min(420, window.innerWidth - margin * 2)}px`;
  const tip = tooltip.getBoundingClientRect();

  // Above by preference: the stats line under a bubble only appears while
  // it's hovered, which is exactly when the tooltip is up, so opening
  // downward would cover the thing you just revealed.
  const roomAbove = box.top - margin;
  if (tip.height + gap <= roomAbove) {
    tooltip.style.top = `${box.top - tip.height - gap}px`;
  } else {
    tooltip.style.top = `${Math.min(box.bottom + gap, window.innerHeight - tip.height - margin)}px`;
  }

  // Hangs off whichever edge the message is aligned to, so it opens into
  // the empty half of the conversation instead of across it, then is pulled
  // back on screen if that would overflow.
  const isYou = Boolean(anchor.closest(".turn.is-you"));
  const left = isYou ? bubble.right - tip.width : bubble.left;
  tooltip.style.left = `${Math.max(margin, Math.min(left, window.innerWidth - tip.width - margin))}px`;
  tooltip.style.right = "auto";
}

async function showTranslation(bodyEl, text, preloaded) {
  closeTooltip();

  const tooltip = document.createElement("div");
  tooltip.className = "translate-tip";
  tooltip._anchor = bodyEl;
  // On <body>, not inside the message: the transcript is a scroll box and
  // clips its own overflow, which would cut the tooltip off at the top edge
  // exactly when it opens upward.
  document.body.appendChild(tooltip);
  positionTooltip(tooltip, bodyEl);
  activeTooltip = tooltip;

  // Normal path: the translation came back with the reply, so it shows
  // instantly with no request and no wait.
  if (preloaded) {
    tooltip.textContent = preloaded;
    positionTooltip(tooltip, bodyEl);
    return;
  }

  if (translationCache.has(text)) {
    tooltip.textContent = translationCache.get(text);
    positionTooltip(tooltip, bodyEl);
    return;
  }

  // Fallback only — used if the model skipped the translation line.
  tooltip.textContent = "Translating…";
  try {
    const res = await fetch("/api/translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();
    if (activeTooltip !== tooltip) return;

    if (!res.ok) {
      tooltip.textContent = data.error || "Couldn't translate.";
      tooltip.classList.add("is-error");
      return;
    }
    translationCache.set(text, data.translation);
    tooltip.textContent = data.translation;
    // "Translating…" is one line; the answer usually isn't.
    positionTooltip(tooltip, bodyEl);
  } catch (err) {
    if (activeTooltip === tooltip) {
      tooltip.textContent = "Couldn't reach the server.";
      tooltip.classList.add("is-error");
    }
  }
}

function makeHoverable(bodyEl, text, preloaded) {
  bodyEl.classList.add("is-translatable");
  bodyEl.setAttribute("tabindex", "0");
  bodyEl.setAttribute("aria-label", "Reply. Hover or focus to see English translation.");

  bodyEl.addEventListener("mouseenter", () => {
    clearTimeout(hoverTimer);
    // No delay when the translation is already in hand — the delay only
    // exists to avoid firing requests on accidental hovers.
    if (preloaded) {
      showTranslation(bodyEl, text, preloaded);
    } else {
      hoverTimer = setTimeout(() => showTranslation(bodyEl, text), 250);
    }
  });
  bodyEl.addEventListener("mouseleave", () => {
    clearTimeout(hoverTimer);
    closeTooltip();
  });
  bodyEl.addEventListener("focus", () => showTranslation(bodyEl, text, preloaded));
  bodyEl.addEventListener("blur", closeTooltip);
}

// ---------- Transcript ----------

// The two marks that sit beside a message. Inline rather than <use href>
// so a message rendered into a detached node still draws correctly.
const AVATAR_AI_SVG =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" aria-hidden="true">' +
  '<path d="M3 12h1M7 8v8M11 4v16M15 7v10M19 10v4M21 12h1"/></svg>';
const AVATAR_YOU_SVG =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<circle cx="12" cy="8" r="3.4"/><path d="M5 20v-1a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v1"/></svg>';


// NEW (1.5.0): local or cloud, for a reply's hover. Ollama runs on your own
// PC or server; OpenAI and ElevenLabs are cloud services. Frivo's voices and
// the Windows voices run on the Frivo PC.
function whereWritten(names) {
  return names.split(", ").map((part) => {
    if (/^Ollama\b/.test(part)) return `${part} (local)`;
    if (/^(OpenAI|ChatGPT)\b/.test(part)) return `${part} (cloud)`;
    return part;   // "No AI": Word for word, nothing was asked
  }).join(", ");
}

// NEW (1.5.0): "Local" or "OpenAI" for the reply's hover line. A reply
// that needed OpenAI anywhere (the fallback, say) says OpenAI.
function replySource(names) {
  if (!names || names === "No AI") return "";
  if (/OpenAI|ChatGPT/.test(names)) return "OpenAI";
  if (/Ollama/.test(names)) return "Local";
  return "";
}

function whereSpoken(engine, name) {
  const where = !engine || engine === "elevenlabs" ? "cloud" : "local";
  // "Frivo voice (free)" → "Frivo voice (free, local)": one bracket, not two.
  return /\)$/.test(name) ? name.replace(/\)$/, `, ${where})`) : `${name} (${where})`;
}

function addTurn(who, text, opts = {}) {
  // NEW (1.5.0): remembered, so a refresh brings the conversation back.
  const at = opts.at || Date.now();
  if (!opts.restoring && typeof rememberTurn === "function") rememberTurn(who, text, opts, at);
  // Query fresh each time: clearTranscript() rebuilds this node, so a
  // reference cached at page load goes stale and removing it does nothing.
  const placeholder = logBody.querySelector(".empty");
  if (placeholder) placeholder.remove();

  const isYou = who === "You";
  const turn = document.createElement("div");
  turn.className = `turn ${isYou ? "is-you" : "is-ai"}`;

  // Avatar and body. A message is a row — mark on the outside, everything
  // else stacked beside it — so the name, the bubble and the stats all
  // line up on one edge instead of each finding their own.
  const avatar = document.createElement("div");
  avatar.className = "turn-avatar";
  avatar.setAttribute("aria-hidden", "true");
  avatar.innerHTML = isYou ? AVATAR_YOU_SVG : AVATAR_AI_SVG;

  const stack = document.createElement("div");
  stack.className = "turn-body";

  turn.append(avatar, stack);

  if (!isYou) {
    const whoEl = document.createElement("span");
    whoEl.className = "turn-who";
    whoEl.textContent = who;
    stack.appendChild(whoEl);
  }

  const meta = document.createElement("span");
  meta.className = "turn-meta";

  if (opts.wordCount != null) {
    const cost = document.createElement("span");
    cost.className = "turn-cost";
    const target = opts.targetWords ? ` / ${opts.targetWords} target` : "";
    // "0 credits" reads like a failure. Saying it wasn't spoken says the
    // same thing about the bill and also explains why there's no player.
    // CHANGED (1.5.0): a free voice (built into Windows) costs nothing, so the
    // line says so instead of quoting what ElevenLabs would have charged.
    const freeVoice = opts.voiceEngine && opts.voiceEngine !== "elevenlabs";
    const spent = opts.spoke === false ? "not spoken"
      : opts.saved ? "saved · no credits"   // NEW (1.5.0): played again from Saved
      : freeVoice ? "free voice"
      : `${opts.credits != null ? opts.credits : opts.charCount} credits`;
    cost.textContent = `${opts.wordCount} words${target} · ${spent}`;
    meta.appendChild(cost);
  }

  // NEW (1.5.0): a spoken reply can be saved to play again later.
  if (opts.saveData && typeof makeSaveButton === "function") meta.appendChild(makeSaveButton(opts.saveData));
  // NEW (1.5.0): Retake, for a reply an ElevenLabs voice spoke.
  if (!isYou && opts.audioUrl && opts.voiceEngine === "elevenlabs" && !opts.saved && typeof makeRetakeButton === "function") {
    meta.appendChild(makeRetakeButton(() => ({ turn, who, text, opts, at })));
  }

  // NEW (1.5.0): where the reply was written, in a word: "Local" (Ollama,
  // on your own PC or server) or "OpenAI". Nothing when no AI was asked
  // (Word for word in English).
  const source = replySource(opts.textEngineName);
  if (source) {
    const where = document.createElement("span");
    where.className = "turn-source" + (source === "Local" ? " is-local" : "");
    where.textContent = source;
    where.title = opts.textEngineName;   // the model, for anyone who wants it
    meta.appendChild(where);
  }

  // Actual measured generation time — ChatGPT + ElevenLabs combined, with
  // the per-service split available on hover rather than cluttering the
  // line itself with two numbers all the time.
  if (opts.totalSeconds != null) {
    const time = document.createElement("span");
    time.className = "turn-time";
    time.textContent = `${opts.totalSeconds.toFixed(1)}s`;
    if (opts.textSeconds != null && opts.audioSeconds != null) {
      // No ElevenLabs line when it was never called — "ElevenLabs: 0.0s"
      // suggests it ran impossibly fast rather than not at all.
      // CHANGED (1.5.0): says which AI wrote it and which voice spoke it,
      // and whether each ran locally or in the cloud.
      const writer = whereWritten(opts.textEngineName || "ChatGPT");
      time.title =
        opts.spoke === false
          ? `${writer}: ${opts.textSeconds.toFixed(1)}s · not spoken`
          : `${writer}: ${opts.textSeconds.toFixed(1)}s · ${whereSpoken(opts.voiceEngine, opts.voiceEngineName || "ElevenLabs")}: ${opts.audioSeconds.toFixed(1)}s`
            + (opts.voiceHow ? ` · spoken as ${opts.voiceHow}` : "");   // NEW (1.5.0)
    }
    meta.appendChild(time);
  }

  const body = document.createElement("div");
  body.className = "bubble";
  const textEl = document.createElement("span");
  textEl.className = "bubble-text";
  // CHANGED (1.5.0): voice tags ([laughs], [softly]) show as small marks.
  // A reply's tags come in opts.voiced; what you typed has them in it.
  if (typeof fillBubbleText === "function") fillBubbleText(textEl, isYou ? text : (opts.voiced || text));
  else textEl.textContent = text;
  body.appendChild(textEl);

  // Wall-clock time, floated into the last line of the bubble the way every
  // messaging app does it. Floated rather than absolutely positioned so it
  // reserves its own space and can never sit on top of the final word.
  const stamp = document.createElement("span");
  stamp.className = "bubble-stamp";
  stamp.textContent = new Date(at).toLocaleTimeString([], {   // CHANGED (1.5.0): its own time, after a refresh too
    hour: "numeric",
    minute: "2-digit",
  });
  body.appendChild(stamp);

  stack.appendChild(body);

  if (!isYou && opts.language && opts.language !== "English") {
    makeHoverable(body, text, opts.english);
  }

  // The bubble itself is the play control when there's audio — a separate
  // player row underneath was a second object saying the same thing, and it
  // was the only part of a message that didn't look like a message.
  if (opts.audioUrl) {
    attachBubbleAudio(body, opts.audioUrl, opts.onAudioStart, opts.onPlayback,
      { wordTimes: opts.wordTimes, lazy: Boolean(opts.restoring),   // CHANGED (1.5.0): a restored reply waits for a click
        // NEW (1.5.0): a streamed reply, and what to do with its timings.
        stream: !opts.restoring && opts.stream ? { timingUrl: opts.stream.timing_url } : null,
        onTiming: (t) => {
          if (t.word_times) {   // kept, so it glows word by word after a refresh too
            const record = (typeof transcript !== "undefined" ? transcript : []).find((r) => r.kind === "turn" && r.at === at);
            if (record) {
              record.opts.wordTimes = t.word_times;
              if (t.audio_url) record.opts.audioUrl = t.audio_url;
              if (typeof persistTranscript === "function") persistTranscript();
            }
          }
          if (typeof opts.onStreamTiming === "function") opts.onStreamTiming(t);
        } });
  }
  // NEW (1.5.0): the chatbox page dots, under a reply that goes to VRChat
  // a page at a time.
  if (opts.footer) stack.appendChild(opts.footer);

  // CHANGED (1.7.0): what happened to a reply ("Cleaned up without AI",
  // "Auto tags"...) used to be a pill under every bubble. Now it's one quiet
  // mark by the bubble's time, and the words are in the line that appears
  // when you point at the reply, with the details on hover.
  const notes = [];
  if (opts.condensed) {
    notes.push({ text: "Shortened to fit", title: "Shortened to fit the reply length." });
  } else if (opts.repaired) {
    notes.push({ text: "Trimmed", title: "Trimmed to the last full sentence." });
  } else if (opts.ruleCleanup) {
    notes.push({ text: "No AI", title: "Cleaned up without AI: spelling, capitals and punctuation fixed by Frivo's rules"
      + (opts.ruleCleanupReason ? ` (${opts.ruleCleanupReason})` : "")
      + ". The AI does the rest: misheard words and garbled sentences." });
  } else if (opts.keptExact) {
    notes.push({ text: "Your words", title: "Kept to your words: the clean-up added things you didn't say, so Frivo used your own wording." });
  }
  if (!isYou && opts.tagShaped) {
    notes.push({ text: "Shaped for tags", title: "Clean up added voice tags and lightly adjusted the words next to them (Shape words for tags)." });
  } else if (!isYou && opts.retaken) {
    notes.push({ text: { same: "Said again", plain: "Said again, no tags", fresh: "Said again, new tags" }[opts.retaken] || "Said again",
      title: "Spoken again with Retake." });
  } else if (!isYou && opts.autoTagged) {
    notes.push({ text: "Auto tags", title: "The AI added the voice tags, because Auto tags is on." });
  }
  if (notes.length) {
    notes.forEach((n) => {
      const el = document.createElement("span");
      el.className = "turn-note";
      el.textContent = n.text;
      el.title = n.title;
      meta.insertBefore(el, meta.firstChild);
    });
    const mark = document.createElement("span");
    mark.className = "bubble-note";
    mark.setAttribute("role", "img");
    mark.setAttribute("aria-label", notes.map((n) => n.title).join(" "));
    mark.title = notes.map((n) => n.title).join("\n");
    stamp.insertBefore(mark, stamp.firstChild);
  }

  // Under the bubble, in the margin — present when you look for it, out of
  // the way when you're reading.
  if (meta.childNodes.length) stack.appendChild(meta);

  // NEW (1.5.0): Retake puts the new take where the old one was.
  if (opts.replaceTurn && opts.replaceTurn.parentNode) {
    opts.replaceTurn.replaceWith(turn);
    removeTypingBubble();
    return;
  }

  // NEW (1.5.0): a reply grows out of the typing dots it replaces.
  const typingBubble = !isYou && typingNode ? typingNode.querySelector(".bubble") : null;
  const typingRect = typingBubble ? typingBubble.getBoundingClientRect() : null;

  removeTypingBubble();
  logBody.appendChild(turn);
  if (typingRect && typeof morphFromTyping === "function") morphFromTyping(body, typingRect);
  if (opts.restoring) return;   // NEW (1.5.0): the restore scrolls once, at the end
  scrollLogToEnd();   // CHANGED (1.5.0): glides rather than jumps
}

let typingNode = null;

function showTypingBubble() {
  removeTypingBubble();
  const placeholder = logBody.querySelector(".empty");
  if (placeholder) placeholder.remove();

  const turn = document.createElement("div");
  turn.className = "turn is-ai is-typing-turn";

  const avatar = document.createElement("div");
  avatar.className = "turn-avatar";
  avatar.setAttribute("aria-hidden", "true");
  avatar.innerHTML = AVATAR_AI_SVG;
  const stack = document.createElement("div");
  stack.className = "turn-body";
  turn.append(avatar, stack);

  const bubble = document.createElement("div");
  bubble.className = "bubble is-typing";
  bubble.setAttribute("aria-label", "Generating a reply");
  for (let i = 0; i < 3; i += 1) {
    const dot = document.createElement("span");
    dot.className = "typing-dot";
    bubble.appendChild(dot);
  }

  stack.appendChild(bubble);
  logBody.appendChild(turn);
  scrollLogToEnd();   // CHANGED (1.5.0)
  typingNode = turn;
}

function removeTypingBubble() {
  if (typingNode) {
    typingNode.remove();
    typingNode = null;
  }
}

function clearTranscript() {
  logBody.innerHTML = '<div class="empty"><p>Nothing yet. Type below and the reply comes back spoken.</p></div>';
  if (typeof forgetTranscript === "function") forgetTranscript();   // NEW (1.5.0): Clear forgets it for good
}

function addProfileDivider(label, { restoring = false } = {}) {
  // Nothing to divide yet.
  if (logBody.querySelector(".empty")) return;

  // Switching back and forth without saying anything shouldn't leave a
  // stack of markers, so an unused one is replaced rather than added to.
  const last = logBody.lastElementChild;
  if (last && last.classList.contains("turn-divider")) last.remove();
  if (!restoring && typeof rememberDivider === "function") rememberDivider(label);   // NEW (1.5.0)

  const rule = document.createElement("div");
  rule.className = "turn-divider";
  const span = document.createElement("span");
  span.textContent = label;
  rule.appendChild(span);
  logBody.appendChild(rule);
  logEl.scrollTop = logEl.scrollHeight;
}

// ---------- Settings ----------

async function loadSettings() {
  const res = await fetch("/api/settings");
  const data = await res.json();
  // CHANGED (1.5.0): only replaced when it's different, so a save (which
  // reloads these) doesn't clear the personality maker's ideas mid-use.
  const incomingPrompt = data.system_prompt || "";
  if (systemPromptInput.value !== incomingPrompt) {
    systemPromptInput.value = incomingPrompt;
    if (window.frivoSettingsPersonality) window.frivoSettingsPersonality.reset({ fetch: false });   // NEW (1.5.0)
  }
  openaiStatus.classList.toggle("is-lit", data.openai_key_set);
  elevenStatus.classList.toggle("is-lit", data.elevenlabs_key_set);

  // The default voice is no longer a control in this panel — it's whatever
  // the Voice row shows while no profile is selected — so it's held in a
  // variable and written back untouched when Settings is saved.
  defaultVoiceId = data.voice_id || "";
  defaultVoiceName = data.voice_name || "";
  renderVoiceTrigger();

  if (oscEnabledToggle) oscEnabledToggle.checked = Boolean(data.osc_enabled);
  if (oscMuteSyncToggle) oscMuteSyncToggle.checked = Boolean(data.osc_mute_sync);
  if (oscUnmuteOnSendToggle) oscUnmuteOnSendToggle.checked = Boolean(data.osc_unmute_on_send);
  // NEW (typing): on unless switched off; an older app.py sends nothing.
  typingIndicatorEnabled = data.osc_typing !== false;
  if (oscTypingToggle) oscTypingToggle.checked = typingIndicatorEnabled;
  oscEnabled_setting = Boolean(data.osc_enabled);
  // "Configured" now means the feature is on and a companion is actually
  // there. There is no address left to get wrong.
  oscConfigured = oscEnabled_setting && frivoscConnected;
  // The toggle is remembered per browser, but can't be honoured before the
  // server has said whether there's anywhere to send to.
  oscToggle.checked = localStorage.getItem(OSC_ENABLED_KEY) === "1";
  syncOscSwitch();

  if (data.languages && data.languages.length) {
    // A language saved in this browser wins over the server default, so
    // switching devices doesn't silently change what you get.
    const saved = localStorage.getItem("voice_console_language");
    currentLanguage = saved || data.language || "English";
    fillLanguages(data.languages, currentLanguage);
    fillListenTargetLanguages();
  } else {
    // The server didn't send a language list — almost always means app.py
    // is an older version than the page.
    languageSelect.innerHTML =
      '<option value="English">English — update app.py for more</option>';
    console.error("No languages in /api/settings response. app.py is out of date.");
    setStatus("app.py looks out of date — it didn't send the language list.", true);
  }

  responseStyles = data.response_styles || [];
  personalityPresets = data.personality_presets || [];
  if (responseStyles.length) {
    buildRadioGroup(
      responseStyleRadios,
      responseStyles,
      "responseStyleSettings",
      data.response_style || "echo",  // CHANGED (1.5.0): Clean up is the default
      handleSettingsResponseStyleChange
    );
    showStyleNote(responseStyleNote, data.response_style || "echo");  // NEW (1.5.0)
  } else {
    responseStyleRadios.innerHTML = '<span class="readout">Update app.py for response style options</span>';
  }
  if (personalityPresets.length) {
    fillOptionList(personalityPresetSelect, personalityPresets, data.personality_preset || "neutral");
  } else {
    personalityPresetSelect.innerHTML = '<option value="neutral">Neutral — update app.py for more</option>';
  }

  textModels = data.text_models || [];
  recommendedTextModel = data.recommended_text_model || "gpt-4o-mini";
  recommendedTranslationModel = data.recommended_translation_model || "gpt-4.1-nano";
  modelTierThroughput = data.model_tier_throughput || modelTierThroughput;
  modelTierSpeedLabel = data.model_tier_speed_label || modelTierSpeedLabel;

  if (textModels.length) {
    buildModelList(
      textModelList, textModelCustom, textModels, "textModelSettings",
      data.model || recommendedTextModel, recommendedTextModel, updateTextModelEstimate
    );
    buildModelList(
      translationModelList, translationModelCustom, textModels, "translationModelSettings",
      data.translation_model || recommendedTranslationModel, recommendedTranslationModel, updateTranslationModelEstimate
    );
  } else {
    textModelList.innerHTML = '<span class="readout">Update app.py for the model picker</span>';
    translationModelList.innerHTML = '<span class="readout">Update app.py for the model picker</span>';
  }

  if (data.max_words) {
    lengthSlider.value = data.max_words;
  }
  applyServerTuning(data);
  if (typeof applyVoiceStyleSettings === "function") applyVoiceStyleSettings(data);   // NEW (1.5.0)
  updateFaderReadout();
  updateTextModelEstimate();
  updateTranslationModelEstimate();

  // Guarded: an older app.py won't send the provider lists, and the picker
  // should simply not appear rather than throwing during init.
  if (data.chat_providers) {
    try {
      buildProviderPickers(data);
    } catch (err) {
      console.error("buildProviderPickers failed:", err);
    }
  }

  return data;
}

// Typing a custom model ID should update the estimate too (it'll show
// "no price data" for anything outside the catalog, which is still useful
// feedback that it's not a recognized/estimable model).
textModelCustom.addEventListener("input", updateTextModelEstimate);
translationModelCustom.addEventListener("input", updateTranslationModelEstimate);

// Settings is a full-page sheet now, so it needs the usual ways out of one:
// its own Close button, and Escape.
function setSettingsOpen(open) {
  // Settings is where these cards live. Opening it takes them back from any
  // status chip currently borrowing one, so they are never asked to be in
  // two places at once.
  if (open && typeof collapseAllServicePanels === "function") collapseAllServicePanels();
  settingsPanel.classList.toggle("is-hidden", !open);
  settingsToggle.classList.toggle("is-active", open);
  if (open && typeof refreshAnchorStatus === "function") refreshAnchorStatus();   // NEW (1.5.0): for the voice selected now
  // CHANGED (2.0): the rail says where you are.
  const railChat = $("railChat");
  if (railChat) railChat.classList.toggle("is-active", !open);
  // Always reopens at the top level. Coming back to whichever sub-page you
  // were on last time is the kind of state that feels broken rather than
  // helpful — you asked for Settings, not for the page you left.
  if (!open && typeof closeSettingsPage === "function") closeSettingsPage();
  if (open && typeof refreshSettingsSummaries === "function") refreshSettingsSummaries();
  // NEW (1.5.0): the microphone list is always current when you look at it.
  if (open && typeof loadMicrophones === "function") loadMicrophones();
  // NEW (1.5.0)
  if (open && typeof refreshFreeVoices === "function") refreshFreeVoices();
}

settingsToggle.addEventListener("click", () => {
  setSettingsOpen(settingsPanel.classList.contains("is-hidden"));
});

closeSettingsBtn.addEventListener("click", () => setSettingsOpen(false));

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  // The profile editor sits on top of Settings, so it gets first refusal on
  // Escape — closing the sheet underneath an open dialog would be wrong.
  if (!overlay.classList.contains("is-hidden")) return;
  // NEW (updates): so does the update dialog, even when focus has wandered
  // out of it.
  if (typeof updateDialogIsOpen === "function" && updateDialogIsOpen()) {
    closeUpdateDialog();
    return;
  }
  if (settingsPanel.classList.contains("is-hidden")) return;
  // One level at a time: a sub-page closes back to the list, and only the
  // list closes Settings itself.
  if (typeof settingsPageIsOpen === "function" && settingsPageIsOpen()) {
    closeSettingsPage();
    return;
  }
  setSettingsOpen(false);
});

// CHANGED (2.0): settings save themselves as you change them (see
// autosaveSettings, at the end of this file). The button only remains for
// the API keys, which are typed and then sent on purpose. Both paths come
// through here; `close` and `quiet` are what differ.
async function saveAllSettings({ close = false, quiet = false } = {}) {
  const body = {
    // Written back as-is. The picker owns this value now; sending it
    // unchanged keeps /api/settings from clearing it.
    voice_id: defaultVoiceId,
    voice_name: defaultVoiceName,
    model: getModelValue(textModelList, textModelCustom, recommendedTextModel),
    translation_model: getModelValue(translationModelList, translationModelCustom, recommendedTranslationModel),
    system_prompt: systemPromptInput.value,
    response_style: getRadioValue(responseStyleRadios, "echo"),
    personality_preset: personalityPresetSelect.value,
    max_words: parseInt(lengthSlider.value, 10),
    speaking_speed: speakingSpeedSlider ? parseInt(speakingSpeedSlider.value, 10) / 100 : 1,
    // NEW (1.5.0): Expressive voice and Delivery, for the default profile.
    expressive_voice: $("expressiveVoiceToggle") ? $("expressiveVoiceToggle").checked : false,
    tag_shaping: $("tagShapingToggle") ? $("tagShapingToggle").checked : false,   // NEW (1.5.0)
    tag_amount: $("tagAmountRadios") ? getRadioValue($("tagAmountRadios"), "normal") : "normal",   // NEW (1.5.0)
    tag_words: Array.isArray(tagWordsState) ? tagWordsState : undefined,           // NEW (1.5.0)
    hold_accent: $("holdAccentRadios") ? getRadioValue($("holdAccentRadios"), "anchor") : "anchor",   // NEW (1.5.0)
    voice_accent: $("voiceAccentSelect") ? $("voiceAccentSelect").value : "auto",   // NEW (1.5.0)
    expressive_model: $("expressiveModelRadios") ? getRadioValue($("expressiveModelRadios"), "eleven_v4") : "eleven_v4",   // NEW (1.5.0)
    expressive_every_line: $("expressiveEveryLine") ? $("expressiveEveryLine").checked : true,   // NEW (1.5.0)
    elevenlabs_streaming: $("elevenStreamingToggle") ? $("elevenStreamingToggle").checked : true,   // NEW (1.5.0)
    voice_delivery: $("voiceDeliveryRadios") ? getRadioValue($("voiceDeliveryRadios"), "natural") : "natural",
    temperature: temperatureSlider ? parseInt(temperatureSlider.value, 10) / 100 : 0.7,
    max_tokens: readMaxTokensSetting(),
    language: currentLanguage,
    chat_provider: getRadioValue(chatProviderRadios, "openai"),
    translation_provider: getRadioValue(translationProviderRadios, "openai"),
    transcription_provider: getRadioValue(transcriptionProviderRadios, "openai"),
    ollama_url: ollamaUrl ? ollamaUrl.value.trim() : "",
    ollama_model: ollamaModel ? ollamaModel.value.trim() : "",
    ollama_model_balanced: ollamaModelBalanced ? ollamaModelBalanced.value.trim() : "",   // NEW (1.5.0)
    ollama_model_best: ollamaModelBest ? ollamaModelBest.value.trim() : "",               // NEW (1.5.0)
    ollama_idle_unload: ollamaIdleUnload ? ollamaIdleUnload.value : "1h",                  // NEW (1.5.0)
    builtin_ai_idle: $("builtinIdle") ? $("builtinIdle").value : "1h",                       // NEW (1.6.0)
    evora_idle_listen: $("evoraIdleListen") ? $("evoraIdleListen").value : "5m",           // NEW (1.5.0)
    evora_idle_speech: $("evoraIdleSpeech") ? $("evoraIdleSpeech").value : "1h",           // NEW (1.5.0)
    ollama_translation_model: ollamaTranslationModel
      ? ollamaTranslationModel.value.trim()
      : "",
    whisper_url: whisperUrl ? whisperUrl.value.trim() : "",
    allow_openai_fallback: allowFallbackToggle ? allowFallbackToggle.checked : false,
    osc_enabled: oscEnabledToggle ? oscEnabledToggle.checked : false,
    osc_mute_sync: oscMuteSyncToggle ? oscMuteSyncToggle.checked : false,
    osc_unmute_on_send: oscUnmuteOnSendToggle ? oscUnmuteOnSendToggle.checked : false,
    osc_typing: oscTypingToggle ? oscTypingToggle.checked : true,   // NEW (typing)
  };
  if (openaiKeyInput.value.trim()) body.openai_api_key = openaiKeyInput.value.trim();
  if (elevenKeyInput.value.trim()) body.elevenlabs_api_key = elevenKeyInput.value.trim();

  const res = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const hadKey = Boolean(body.openai_api_key || body.elevenlabs_api_key);
  if (res.ok) {
    openaiKeyInput.value = "";
    elevenKeyInput.value = "";
    if (!quiet) setStatus("Settings saved.");
    await loadSettings();
    // Providers may have just changed, so the indicator is stale.
    loadLocalStatus();
    // A key may have just been pasted in, which is the difference between
    // an empty picker and a full one — and between a balance and no
    // balance to show.
    if (hadKey || !quiet) {
      await loadVoices();
      loadCredits({ force: true });
    }
    refreshPromptIfOpen();
    if (typeof syncSessionStrip === "function") syncSessionStrip();
    if (close) setSettingsOpen(false);
    return true;
  }
  if (!quiet) setStatus("Settings didn't save. Try again.", true);
  return false;
}

saveSettingsBtn.addEventListener("click", () => saveAllSettings({ close: false }));


const OSC_ENABLED_KEY = "voice_console_osc_enabled";
// Whether the chatbox can actually go anywhere: the feature switched on in
// Settings, AND a companion currently connected to carry it.
let oscConfigured = false;
let oscEnabled_setting = false;
let frivoscConnected = false;


const CREDITS_POLL_MS = 60000;
let creditsTimer = null;

function formatCredits(n) {
  return n.toLocaleString();
}

function renderCredits(data) {
  elevenCreditsEl.classList.remove("is-hidden");
  elevenCreditsEl.classList.remove("is-low", "is-empty", "is-stale");

  const { used, limit, remaining, over, tier, reset_unix: resetUnix } = data;
  elevenCreditsEl.textContent = `${formatCredits(remaining)} left`;

  const parts = [`${formatCredits(used)} of ${formatCredits(limit)} used`];
  if (tier) parts.push(`${tier} plan`);
  if (over > 0) parts.push(`${formatCredits(over)} over the limit`);
  if (resetUnix) {
    // Sent as seconds; Date wants milliseconds.
    parts.push(`resets ${new Date(resetUnix * 1000).toLocaleDateString()}`);
  }
  elevenCreditsEl.title = parts.join(" · ");

  // The detail panel, filled from the same reply.
  const plan = document.getElementById("creditsPlan");
  const planLabel = document.getElementById("creditsPlanLabel");
  const reset = document.getElementById("creditsReset");
  if (plan) plan.textContent = limit ? `${formatCredits(used)} of ${formatCredits(limit)}` : "—";
  if (planLabel) planLabel.textContent = tier ? `Used on ${tier} plan` : "Used this period";
  if (reset) {
    reset.textContent = resetUnix
      ? `Resets ${new Date(resetUnix * 1000).toLocaleDateString()}.`
      : "";
  }

  // Thresholds as a share of the plan, not a fixed number — 5,000 left is
  // comfortable on a big plan and nearly nothing on a small one.
  const share = limit > 0 ? remaining / limit : 1;
  if (remaining <= 0) elevenCreditsEl.classList.add("is-empty");
  else if (share <= 0.1) elevenCreditsEl.classList.add("is-low");
}

async function loadCredits({ force = false } = {}) {
  try {
    const res = await fetch(`/api/credits${force ? "?force=1" : ""}`);
    const data = await res.json();
    // Counted by this app rather than read from the account, so it's known
    // even when the balance isn't — including on an install with no key.
    showCreditsToday(data.used_today);
    if (!res.ok) {
      // No key is the ordinary case on a fresh install, and a missing
      // readout says that better than an error sitting in the sidebar.
      elevenCreditsEl.classList.add("is-hidden");
      return;
    }
    renderCredits(data);
  } catch (err) {
    // The number that's showing is now of unknown age rather than wrong,
    // so it's dimmed instead of cleared.
    elevenCreditsEl.classList.add("is-stale");
    elevenCreditsEl.title = `Couldn't refresh: ${err.message}`;
  }
}

function startCreditsPolling() {
  if (creditsTimer) clearInterval(creditsTimer);
  creditsTimer = setInterval(() => {
    if (document.visibilityState === "visible") loadCredits();
  }, CREDITS_POLL_MS);
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") loadCredits();
});


const creditsToggle = $("creditsToggle");
const creditsPanel = $("creditsPanel");
const creditsTodayEl = $("creditsToday");

function showCreditsToday(value) {
  if (!creditsTodayEl) return;
  creditsTodayEl.textContent =
    value == null ? "—" : `${Number(value).toLocaleString()} credits`;
}

if (creditsToggle && creditsPanel) {
  creditsToggle.addEventListener("click", () => {
    const opening = creditsPanel.classList.contains("is-hidden");
    // CHANGED (1.5.0): the popover grows and shrinks to fit, not jumps.
    const pop = creditsToggle.closest(".popover");
    if (pop && typeof smoothResize === "function") smoothResize(pop, () => creditsPanel.classList.toggle("is-hidden", !opening));
    else creditsPanel.classList.toggle("is-hidden", !opening);
    creditsToggle.setAttribute("aria-expanded", opening ? "true" : "false");
    // Opening it is a request to see current numbers, so it's also when a
    // stale balance is worth a round trip.
    if (opening) loadCredits({ force: true });
  });
}

const creditsRefresh = $("creditsRefresh");
if (creditsRefresh) {
  creditsRefresh.addEventListener("click", (e) => {
    e.stopPropagation();
    loadCredits({ force: true });
  });
}


const SPEAK_ENABLED_KEY = "voice_console_speak_enabled";

function speakEnabled() {
  return speakToggle.checked;
}

speakToggle.checked = localStorage.getItem(SPEAK_ENABLED_KEY) !== "0";
speakToggle.addEventListener("change", () => {
  localStorage.setItem(SPEAK_ENABLED_KEY, speakToggle.checked ? "1" : "0");
  setStatus(
    speakToggle.checked
      ? "Replies will be spoken."
      : "Text only — no ElevenLabs credits will be used."
  );
});

function oscEnabled() {
  return oscToggle.checked;
}

function syncOscSwitch() {
  // Left usable but explained when it cannot deliver — hiding it would just
  // raise the question of where the VRChat option went.
  oscSwitch.title = oscConfigured
    ? "Show the spoken reply in your VRChat chatbox as it plays"
    : oscEnabled_setting
      ? "Waiting for FrivOSC on your VRChat PC"
      : "Turn on VRChat OSC in Settings to use this";
  oscSwitch.classList.toggle("is-unset", !oscConfigured);
  syncOscQuick();
}

// NEW (1.5.0): the FrivOSC chip above the message box. Only there while
// FrivOSC is connected — that is when its switches are worth reaching for —
// and it reads the same state the Settings → VRChat switches do.
function syncOscQuick() {
  const wrap = document.getElementById("oscChipWrap");
  if (!wrap) return;
  wrap.classList.toggle("is-hidden", !frivoscConnected);
  if (!frivoscConnected) {
    const pop = document.getElementById("oscPop");
    const btn = document.getElementById("oscChip");
    if (pop) pop.classList.add("is-hidden");
    if (btn) btn.setAttribute("aria-expanded", "false");
    return;
  }
  const set = (id, on) => { const el = document.getElementById(id); if (el) el.checked = Boolean(on); };
  set("oscQuickEnabled", oscEnabled_setting);
  set("oscQuickMuteSync", muteSyncEnabled);
  set("oscQuickUnmute", unmuteOnSendEnabled);
  set("oscQuickTyping", typingIndicatorEnabled);
  const mic = frivoscMuted === null ? "Mic unknown" : frivoscMuted ? "Muted in VRChat" : "Live in VRChat";
  const micEl = document.getElementById("oscPopMic");
  if (micEl) micEl.textContent = mic;
  const dot = document.getElementById("oscChipDot");
  if (dot) {
    dot.classList.toggle("is-live", oscEnabled_setting && frivoscMuted === false);
    dot.classList.toggle("is-muted", oscEnabled_setting && frivoscMuted === true);
    dot.classList.toggle("is-off", !oscEnabled_setting);
  }
  const text = document.getElementById("oscChipText");
  if (text) text.textContent = !oscEnabled_setting ? "VRChat off" : frivoscMuted === null ? "VRChat" : frivoscMuted ? "Muted" : "Live";
}

// Each quick switch drives the Settings switch it mirrors, so the one set of
// handlers (state, save, revert) stays the only set.
[
  ["oscQuickEnabled", "oscEnabledToggle"],
  ["oscQuickMuteSync", "oscMuteSyncToggle"],
  ["oscQuickUnmute", "oscUnmuteOnSendToggle"],
  ["oscQuickTyping", "oscTypingToggle"],
].forEach(([quickId, mainId]) => {
  const quick = document.getElementById(quickId);
  const main = document.getElementById(mainId);
  if (!quick || !main) return;
  quick.addEventListener("change", () => {
    main.checked = quick.checked;
    main.dispatchEvent(new Event("change", { bubbles: true }));
  });
});

// ---------- FrivOSC status ----------
// Frivo speaks no OSC of its own. FrivOSC runs on the VRChat PC and reports
// in; all this does is show whether it is there, and keep the composer
// switch honest about whether a message would actually arrive.

// Two rates. Showing "connected" a few seconds late is nothing; letting
// dictation start a few seconds after you unmute in VRChat is the whole
// feature arriving late, so mute sync polls harder while it is on. The
// endpoint is a small JSON read against a server on your own network.
const FRIVOSC_POLL_MS = 5000;
const FRIVOSC_SYNC_POLL_MS = 1000;
let frivoscTimer = null;
let frivoscPollRate = 0;

// Mute sync acts on *changes* in VRChat's mute state, never on the level.
// That is what lets the mic button override it: stop dictation by hand
// while still unmuted and it stays stopped, because nothing changed.
let muteSyncEnabled = false;
let unmuteOnSendEnabled = false;
let typingIndicatorEnabled = true;   // NEW (typing)
let lastSyncedMute = null;
let frivoscMuted = null;
// NEW (1.5.0): dictation never starts by itself when the page loads. The
// first mute state VRChat reports after a load (or after FrivOSC
// reconnects) is only noted, so being unmuted at that moment isn't taken as
// "you just unmuted". Unmuting after that still starts dictation, and
// switching Follow VRChat mute on still acts at once (that switch clears this).
let muteSyncNeedsBaseline = true;

function noteManualDictationOverride() {
  // The current mute state has now been "handled" by the person, so the
  // next poll has nothing new to act on.
  lastSyncedMute = frivoscMuted;
}

function applyMuteSync() {
  if (!muteSyncEnabled || !oscEnabled_setting || !frivoscConnected) {
    // Nothing is driving dictation, so forget where we were. Turning the
    // switch back on should act on the next change, not on a stale one.
    lastSyncedMute = null;
    // NEW (1.5.0): and when FrivOSC comes back, take its first report as
    // where things stand rather than as a change.
    if (!frivoscConnected) muteSyncNeedsBaseline = true;
    return;
  }
  // Before VRChat has said anything, muted is null — genuinely unknown, and
  // not the same as unmuted. Acting on it would start dictation for a mic
  // that may well be muted.
  if (frivoscMuted === null) return;
  // NEW (1.5.0): the first state after a page load is a starting point, not
  // a change. This is what stopped dictation switching itself on at load.
  if (muteSyncNeedsBaseline) {
    muteSyncNeedsBaseline = false;
    lastSyncedMute = frivoscMuted;
    return;
  }
  if (frivoscMuted === lastSyncedMute) return;

  lastSyncedMute = frivoscMuted;
  if (frivoscMuted) {
    if (isDictating) {
      endDictation();
      setStatus("Muted in VRChat — dictation stopped.");
    }
  } else if (!isDictating) {
    beginDictation();
    setStatus("Unmuted in VRChat — dictation started.");
  }
}

function setFrivoscPollRate(interval) {
  if (interval === frivoscPollRate) return;
  frivoscPollRate = interval;
  clearInterval(frivoscTimer);
  frivoscTimer = setInterval(pollFrivoscStatus, interval);
}

function describeFrivosc(data) {
  // Deliberately just "Connected". The hostname reads as "Connected — PA…"
  // at this row's width, which tells nobody anything; the machine's name is
  // visible in FrivOSC's own window, on the machine in question.
  if (!data || !data.enabled) return "Off";
  return data.connected ? "Connected" : "Not connected";
}

async function pollFrivoscStatus() {
  try {
    const res = await fetch("/api/frivosc/status");
    const data = await res.json();
    if (!res.ok) return;
    const wasConnected = frivoscConnected;
    const wasEnabled = oscEnabled_setting;
    frivoscConnected = Boolean(data.connected);
    oscEnabled_setting = Boolean(data.enabled);
    muteSyncEnabled = Boolean(data.mute_sync);
    unmuteOnSendEnabled = Boolean(data.unmute_on_send);
    typingIndicatorEnabled = data.typing_enabled !== false;   // NEW (typing)
    frivoscMuted =
      !frivoscConnected || data.muted === null || data.muted === undefined
        ? null
        : Boolean(data.muted);
    oscConfigured = frivoscConnected && oscEnabled_setting;
    setSummary("frivoscStatusValue", describeFrivosc(data));
    // Mic state is what the mute-sync acts on, so it is worth showing
    // rather than leaving people to guess why dictation did something.
    // null is not false: "unknown" and "live" are different answers.
    setSummary(
      "frivoscMicValue",
      frivoscMuted === null ? "Unknown" : frivoscMuted ? "Muted" : "Live"
    );
    syncOscSwitch();
    applyMuteSync();
    setFrivoscPollRate(
      muteSyncEnabled && oscEnabled_setting ? FRIVOSC_SYNC_POLL_MS : FRIVOSC_POLL_MS
    );
    // FrivOSC also appears in the header chip alongside Evora, which polls
    // far more slowly. Nudging it on a change keeps the two from disagreeing
    // for half a minute after FrivOSC comes up or goes away.
    if (frivoscConnected !== wasConnected || oscEnabled_setting !== wasEnabled) {
      loadLocalStatus();
    }
  } catch (err) {
    // Frivo's own server is unreachable; the page has louder problems.
  }
}

function startFrivoscPolling() {
  clearInterval(frivoscTimer);
  frivoscPollRate = FRIVOSC_POLL_MS;
  frivoscTimer = setInterval(pollFrivoscStatus, FRIVOSC_POLL_MS);
  pollFrivoscStatus();
}

// These two switches live in the FrivOSC status panel in the sidebar, which
// has no Save button — Save belongs to the Settings sheet. So they save
// themselves. Without this they flipped, were never written down, and were
// then silently flipped back by the next status poll reading the unchanged
// value off the server.
async function saveOscSwitches(patch, toggle) {
  try {
    const res = await fetch("/api/frivosc/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error("save failed");
    const saved = await res.json();
    if (oscEnabledToggle) oscEnabledToggle.checked = Boolean(saved.osc_enabled);
    if (oscMuteSyncToggle) oscMuteSyncToggle.checked = Boolean(saved.osc_mute_sync);
    if (oscUnmuteOnSendToggle) oscUnmuteOnSendToggle.checked = Boolean(saved.osc_unmute_on_send);
    oscEnabled_setting = Boolean(saved.osc_enabled);
    muteSyncEnabled = Boolean(saved.osc_mute_sync);
    unmuteOnSendEnabled = Boolean(saved.osc_unmute_on_send);
    // NEW (typing)
    typingIndicatorEnabled = saved.osc_typing !== false;
    if (oscTypingToggle) oscTypingToggle.checked = typingIndicatorEnabled;
    oscConfigured = oscEnabled_setting && frivoscConnected;
    syncOscSwitch();
    // Reflect it in the chip straight away rather than up to 30s later.
    loadLocalStatus();
    return true;
  } catch (err) {
    // Put the switch back rather than leaving it showing a state the
    // server does not have.
    if (toggle) toggle.checked = !toggle.checked;
    pollFrivoscStatus();   // NEW (1.5.0): put the chip's switches back too
    setStatus("Couldn't save that setting.", true);
    return false;
  }
}

if (oscEnabledToggle) {
  oscEnabledToggle.addEventListener("change", () => {
    oscEnabled_setting = oscEnabledToggle.checked;
    oscConfigured = oscEnabled_setting && frivoscConnected;
    syncOscSwitch();
    saveOscSwitches({ osc_enabled: oscEnabledToggle.checked }, oscEnabledToggle);
  });
}

// NEW (typing): saves itself, like the switches beside it — this card also
// lives in the FrivOSC chip's panel, where there is no Save button.
if (oscTypingToggle) {
  oscTypingToggle.addEventListener("change", () => {
    typingIndicatorEnabled = oscTypingToggle.checked;
    saveOscSwitches({ osc_typing: oscTypingToggle.checked }, oscTypingToggle);
    syncTypingIndicator();
  });
}

if (oscUnmuteOnSendToggle) {
  oscUnmuteOnSendToggle.addEventListener("change", () => {
    unmuteOnSendEnabled = oscUnmuteOnSendToggle.checked;
    saveOscSwitches(
      { osc_unmute_on_send: oscUnmuteOnSendToggle.checked },
      oscUnmuteOnSendToggle
    );
  });
}

if (oscMuteSyncToggle) {
  oscMuteSyncToggle.addEventListener("change", () => {
    muteSyncEnabled = oscMuteSyncToggle.checked;
    // Forgotten rather than remembered. Switching this on while already
    // unmuted in VRChat should start dictation — that is exactly what the
    // switch says it does. Holding on to the old value made turning it on
    // do nothing at all until the next mute/unmute cycle, which reads as
    // broken.
    lastSyncedMute = null;
    muteSyncNeedsBaseline = false;   // NEW (1.5.0): turning it on acts now, as the switch says
    saveOscSwitches({ osc_mute_sync: oscMuteSyncToggle.checked }, oscMuteSyncToggle);
  });
}

function requestVrchatUnmute() {
  // Everything here is also checked on the server; this just avoids a
  // pointless request on every single send when the feature is off.
  if (!unmuteOnSendEnabled || !oscEnabled_setting || !frivoscConnected) return;
  if (frivoscMuted === false) return;
  fetch("/api/frivosc/unmute", { method: "POST" }).catch(() => {
    // Not surfaced. It is a convenience on top of sending a message, and
    // an error toast here would interrupt the thing you actually asked for.
  });
}

// CHANGED (1.5.0): keepTyping leaves the dots up after sending, for a page
// that has more pages after it.
function sendToChatbox(text, { speaking = false, keepTyping = false } = {}) {
  // NEW (1.5.0): every way out of here ends the reply's typing dots.
  if (!text) { endReplyTyping(); return; }
  if (!oscConfigured) {
    endReplyTyping();
    setStatus(
      oscEnabled_setting
        ? "VRChat chatbox is on, but FrivOSC isn't connected."
        : "VRChat chatbox is on, but VRChat OSC is off in Settings.",
      true
    );
    return;
  }
  // OSC delivery is independent of the chat request. Speaking controls the
  // server's chatbox page duration.
  fetch("/api/osc/chatbox", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, speaking }),
  })
    .then(async (res) => {
      const data = await res.json();
      if (!res.ok) {
        setStatus(`VRChat chatbox: ${data.error}`, true);
      } else if (data.pages > 1) {
        setStatus(`Sent to VRChat in ${data.pages} pages.`);
      }
    })
    .catch((err) => setStatus(`VRChat chatbox: ${err.message}`, true))
    // NEW (1.5.0): the dots drop once the message is queued for VRChat,
    // not before — queued first, so the same FrivOSC poll that clears the
    // dots also delivers the text that replaces them.
    .finally(() => {
      if (!keepTyping) endReplyTyping();   // CHANGED (1.5.0)
    });
}

// NEW (1.5.0): chatbox pages that follow the voice.
//
// FrivOSC changes pages on a fixed timer, which ran well ahead of anyone
// talking. A spoken reply now comes back already split into pages
// (chatbox_pages). Each page says how far through the speech it starts,
// and this sends each one when the voice gets there. Pausing holds the next
// page, and playing again carries on from wherever the voice is.
//
// Each page goes a little early on purpose. FrivOSC collects twice a
// second, so a page sent right on time could show up half a second late.
const CHATBOX_PAGE_LEAD_SECONDS = 0.4;
// CHANGED (1.5.0): most replies now come with exact times ("at"): the
// second the voice finishes the last word of the page before. Those only
// need to make up for FrivOSC's half-second collection, so they go a
// little earlier than that and land just as the word ends.
const CHATBOX_PAGE_LEAD_EXACT_SECONDS = 0.15;

function makeChatboxFollower(pages, onPage) {   // CHANGED (1.5.0): onPage
  let next = 0;          // the first page not sent yet
  let timer = null;
  let clockAt = 0;       // performance.now() when playback last started
  let clockOffset = 0;   // where in the audio it started, in seconds
  let duration = 0;
  let finished = false;

  const dueAt = (i) => (typeof pages[i].at === "number"   // CHANGED (1.5.0)
    ? Math.max(0, pages[i].at - CHATBOX_PAGE_LEAD_EXACT_SECONDS)
    : Math.max(0, pages[i].start * duration - CHATBOX_PAGE_LEAD_SECONDS));
  const position = () => clockOffset + (performance.now() - clockAt) / 1000;

  function stop() {
    clearTimeout(timer);
    timer = null;
  }

  function finish() {
    stop();
    if (finished) return;
    finished = true;
    endReplyTyping();
  }

  function sendDue(at) {
    if (next >= pages.length) return;
    // Only the latest page that's due. If several are (playing again after
    // skipping ahead), the earlier ones are already behind the voice.
    let i = next;
    while (i + 1 < pages.length && dueAt(i + 1) <= at) i++;
    if (dueAt(i) > at) return;
    next = i + 1;
    const last = next >= pages.length;
    // The dots stay up between pages, as they did when FrivOSC paged the
    // reply, and each page restarts their 30-second limit.
    if (!last) beginReplyTyping();
    sendToChatbox(pages[i].text, { speaking: true, keepTyping: !last });
    if (typeof onPage === "function") { try { onPage(i); } catch (e) { /* only the dots */ } }   // NEW (1.5.0)
    if (last) {
      // The dots come down once sendToChatbox has queued the last page, not
      // before, the same as a one-page reply.
      finished = true;
      stop();
    } else if (!oscConfigured) {
      // Not connected: sendToChatbox has said so once. No need to repeat it
      // for every page.
      finish();
    }
  }

  function schedule() {
    stop();
    if (finished || next >= pages.length) return;
    const wait = Math.max(0, dueAt(next) - position());
    // setTimeout rather than animation frames. Frames stop while the tab
    // is in the background, which is where it is while you're in VRChat. A
    // tab that's playing audio isn't throttled.
    timer = setTimeout(() => {
      timer = null;
      if (!oscEnabled()) { finish(); return; }
      sendDue(position());
      schedule();
    }, wait * 1000);
  }

  return {
    update(playing, offset, dur) {
      if (finished) return;
      if (dur > 0) duration = dur;
      if (!oscEnabled()) { finish(); return; }
      if (!playing) {
        stop();
        // Played to the end: whatever isn't showing yet goes now, so the
        // chatbox finishes on the reply's last page.
        if (duration && offset >= duration - 0.05) sendDue(Infinity);
        return;
      }
      clockAt = performance.now();
      clockOffset = offset;
      sendDue(offset);
      schedule();
    },
  };
}

oscToggle.addEventListener("change", () => {
  localStorage.setItem(OSC_ENABLED_KEY, oscToggle.checked ? "1" : "0");
  if (oscToggle.checked && !oscConfigured) {
    setStatus(
      oscEnabled_setting
        ? "Waiting for FrivOSC to connect from your VRChat PC."
        : "Turn on VRChat OSC in Settings for this to do anything.",
      true
    );
  } else {
    setStatus(oscToggle.checked ? "Sending to the VRChat chatbox." : "VRChat chatbox off.");
  }
});

clearChatBtn.addEventListener("click", async () => {
  // "all" because the transcript can now span several profiles, each with
  // its own history on the server. Clearing only the current one would
  // empty the window and leave the model remembering the rest.
  await fetch("/api/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, all: true }),
  });
  clearTranscript();
  setStatus("Conversation cleared.");
});


const VOICE_FAVORITES_KEY = "voice_console_voice_favorites";
const VOICE_RECENTS_KEY = "voice_console_voice_recents";
const VOICE_RECENTS_MAX = 6;

// Anything starred before the key was respelled would otherwise silently
// vanish. Moved once, then the old key is dropped.
(() => {
  const old = localStorage.getItem("voice_console_voice_favourites");
  if (old !== null && localStorage.getItem(VOICE_FAVORITES_KEY) === null) {
    localStorage.setItem(VOICE_FAVORITES_KEY, old);
  }
  if (old !== null) localStorage.removeItem("voice_console_voice_favourites");
})();

let voiceQuery = "";

// CHANGED (1.7.0): `fav` and `free` are the All / Favorites / Free tabs; the
// rest are in the Filters menu.
const voiceFacets = { fav: false, free: false, language: "", gender: "", category: "" };
let voiceRows = [];          // rendered rows, in display order, for arrow keys
let voiceActiveIndex = -1;
let voicePreviewAudio = null;
let voicePreviewId = "";

function readStoredList(key) {
  try {
    const raw = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(raw) ? raw.filter((x) => typeof x === "string") : [];
  } catch (err) {
    return [];
  }
}

function voiceFavorites() { return readStoredList(VOICE_FAVORITES_KEY); }

const VOICE_HIDDEN_CATEGORIES_KEY = "voice_console_hidden_categories";

function hiddenVoiceCategories() { return readStoredList(VOICE_HIDDEN_CATEGORIES_KEY); }

function toggleHiddenCategory(category) {
  const key = String(category || "");
  const hidden = hiddenVoiceCategories();
  const next = hidden.includes(key) ? hidden.filter((x) => x !== key) : [key, ...hidden];
  localStorage.setItem(VOICE_HIDDEN_CATEGORIES_KEY, JSON.stringify(next));
}

function showAllVoiceCategories() {
  localStorage.setItem(VOICE_HIDDEN_CATEGORIES_KEY, "[]");
}

// Categories present in the library, in the order ElevenLabs happened to
// return them — there's no meaningful ranking between them.
function voiceCategories() {
  const seen = [];
  allVoices.forEach((v) => {
    const c = v.category || "";
    if (c && !seen.includes(c)) seen.push(c);
  });
  return seen;
}

function categoryLabel(c) {
  if (!c) return "Uncategorised";
  return c.charAt(0).toUpperCase() + c.slice(1);
}
function voiceRecents() { return readStoredList(VOICE_RECENTS_KEY); }

function toggleFavorite(id) {
  const favs = voiceFavorites();
  const next = favs.includes(id) ? favs.filter((x) => x !== id) : [id, ...favs];
  localStorage.setItem(VOICE_FAVORITES_KEY, JSON.stringify(next));
}

function noteVoiceUsed(id) {
  const next = [id, ...voiceRecents().filter((x) => x !== id)].slice(0, VOICE_RECENTS_MAX);
  localStorage.setItem(VOICE_RECENTS_KEY, JSON.stringify(next));
}

// ---- which voice is live right now ----

function activeProfile() {
  return allProfiles.find((p) => p.id === currentProfileId) || null;
}

function activeVoiceId() {
  const p = activeProfile();
  return p ? p.voice_id : defaultVoiceId;
}

function activeVoiceName() {
  const p = activeProfile();
  return p ? (p.voice_name || "") : defaultVoiceName;
}

function voiceById(id) {
  return allVoices.find((v) => v.voice_id === id) || null;
}

function voiceShortName(v) {
  const name = v.name || "";
  const match = name.split(/\s+[-–—]\s+/);
  const short = (match[0] || "").trim();
  return short || name;
}

function voiceHasMoreName(v) {
  return voiceShortName(v) !== (v.name || "").trim();
}

// The first language, plus a count when a voice covers several.
// CHANGED (1.5.0): regions shortened ("English · UK"), so the free voices'
// labels fit the column instead of being cut off.
const VOICE_REGION_SHORT = {
  "United States": "US", "United Kingdom": "UK", "Australia": "AU", "Canada": "CA",
  "India": "IN", "Ireland": "IE", "New Zealand": "NZ", "South Africa": "ZA",
  "Mexico": "MX", "Spain": "ES", "Brazil": "BR", "Portugal": "PT", "France": "FR",
  "Germany": "DE", "Austria": "AT", "Switzerland": "CH", "Belgium": "BE",
  "Netherlands": "NL", "China": "CN", "Taiwan": "TW", "Hong Kong": "HK",
};
function voiceLanguageLabel(v) {
  const langs = v.languages || [];
  if (!langs.length) return "";
  const first = String(langs[0].name || "").replace(/ · (.+)$/, (m, region) =>
    VOICE_REGION_SHORT[region] ? ` · ${VOICE_REGION_SHORT[region]}` : m);
  return langs.length > 1 ? `${first} +${langs.length - 1}` : first;
}

function renderVoiceTrigger() {
  const id = activeVoiceId();
  // NEW (1.5.0): "credits" or "free" under the length fader follows the voice.
  updateFaderReadout();
  // CHANGED (2.0): the chip shows the bare name; the full one is in the tooltip.
  const chipName = (v) => voiceShortName(v).replace(/\s*\([^)]*\)\s*$/, "");
  const v = voiceById(id);

  // Falls back to the stored name so the row still reads correctly before
  // the list has loaded, or when there's no ElevenLabs key to load it with.
  if (v) {
    voiceTriggerName.textContent = chipName(v);
    // The full name still lives in the tooltip, so nothing is lost by
    // showing the short one on the row.
    // Same two facts as the list rows, for the same reason.
    voiceTriggerTags.textContent = [voiceLanguageLabel(v), v.gender]
      .filter(Boolean)
      .join(" · ");
    // CHANGED (1.5.0): the chip shows only the name; the language and
    // gender moved into the tooltip with the full name.
    voiceTrigger.title = [v.name, voiceTriggerTags.textContent].filter(Boolean).join(" · ");
  } else if (activeVoiceName()) {
    voiceTriggerName.textContent = activeVoiceName().replace(/\s*\([^)]*\)\s*$/, "");
    voiceTriggerTags.textContent = allVoices.length ? "not in your library" : "";
    // CHANGED (1.5.0): the tags are hidden on the chip, so say it here.
    voiceTrigger.title = [activeVoiceName(), voiceTriggerTags.textContent].filter(Boolean).join(" · ");
  } else {
    voiceTriggerName.textContent = allVoices.length ? "Choose a voice" : "Loading voices…";
    voiceTriggerTags.textContent = "";
  }
}

// ---- search + filtering ----

// Built once per voice and cached on the object. Rebuilding a lowercased
// string for every voice on every keystroke is what makes naive filtering
// feel sluggish on a large library.
function voiceHaystack(v) {
  if (!v._hay) {
    // Searches the FULL name even though only the first part is displayed —
    // typing "narrator" should still find "Elena – Young, female narrator",
    // and the language should be searchable by name too.
    v._hay = [
      v.name,
      v.category,
      (v.tags || []).join(" "),
      (v.languages || []).map((l) => `${l.name} ${l.code}`).join(" "),
      v.description || "",
    ]
      .join(" ")
      .toLowerCase();
  }
  return v._hay;
}

function voiceMatchesFacets(v, favs) {
  if (voiceFacets.fav && !favs.has(v.voice_id)) return false;
  if (voiceFacets.free && voiceEngine(v) === "elevenlabs") return false;   // NEW (1.7.0)
  if (
    voiceFacets.language &&
    !(v.languages || []).some((l) => l.name === voiceFacets.language)
  ) {
    return false;
  }
  if (voiceFacets.gender && (v.gender || "") !== voiceFacets.gender) return false;
  if (voiceFacets.category && (v.category || "") !== voiceFacets.category) return false;
  return true;
}

function matchingVoices() {
  // Terms are ANDed, so "british female" narrows rather than widening.
  const terms = voiceQuery.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const favs = new Set(voiceFavorites());
  const hidden = new Set(hiddenVoiceCategories());

  return allVoices.filter((v) => {
    // Hidden categories are out of the list entirely — except when the Type
    // filter names one explicitly, which is a direct request to see it.
    if (hidden.has(v.category || "") && voiceFacets.category !== (v.category || "")) {
      return false;
    }
    if (!voiceMatchesFacets(v, favs)) return false;
    if (!terms.length) return true;
    const hay = voiceHaystack(v);
    return terms.every((t) => hay.includes(t));
  });
}

// CHANGED (1.7.0): only what's in the Filters menu; the tabs aren't filters.
function activeFilterCount() {
  return [voiceFacets.language, voiceFacets.gender, voiceFacets.category].filter(Boolean).length;
}
function anyFacetActive() {
  return activeFilterCount() > 0;
}

// Counts are of the whole library, not of what's currently showing. Live
// counts that shrink as you filter look responsive but make the dropdowns
// unstable — the option you were about to pick moves or disappears.
function fillFacetSelect(select, anyLabel, values, current) {
  select.innerHTML = "";
  const any = document.createElement("option");
  any.value = "";
  any.textContent = anyLabel;
  select.appendChild(any);

  values.forEach(([value, count]) => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = `${value} (${count})`;
    select.appendChild(opt);
  });

  // A filter for something no longer in the library would silently match
  // nothing, so it's dropped rather than kept as a dead selection.
  select.value = values.some(([v]) => v === current) ? current : "";
  return select.value;
}

function countBy(pick) {
  const counts = new Map();
  allVoices.forEach((v) => {
    pick(v).forEach((value) => {
      const key = (value || "").trim();
      if (key) counts.set(key, (counts.get(key) || 0) + 1);
    });
  });
  return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

function voiceTab() {
  return voiceFacets.fav ? "fav" : voiceFacets.free ? "free" : "all";
}

function renderVoiceFilters() {
  // NEW (1.7.0): the tabs, and how many filters are on.
  const tab = voiceTab();
  document.querySelectorAll("#voicePop .vm-tab").forEach((b) => {
    const on = b.dataset.tab === tab;
    b.classList.toggle("is-on", on);
    b.setAttribute("aria-selected", String(on));
  });

  voiceFacets.language = fillFacetSelect(
    voiceLangFilter,
    "Any language",
    countBy((v) => (v.languages || []).map((l) => l.name)),
    voiceFacets.language
  );
  voiceFacets.gender = fillFacetSelect(
    voiceGenderFilter,
    "Any gender",
    countBy((v) => [v.gender]),
    voiceFacets.gender
  );
  voiceFacets.category = fillFacetSelect(
    voiceTypeFilter,
    "Any type",
    countBy((v) => [v.category]),
    voiceFacets.category
  );

  const count = activeFilterCount();
  voiceFilterClear.disabled = !count;
  const badge = $("voiceFilterCount");
  if (badge) {
    badge.textContent = String(count);
    badge.classList.toggle("is-hidden", !count);
  }
  const fbtn = $("voiceFilterBtn");
  if (fbtn) fbtn.classList.toggle("is-on", count > 0);
}

function onFacetChange() {
  renderVoiceFilters();
  renderVoiceList();
}

// NEW (1.7.0): All / Favorites / Free.
document.querySelectorAll("#voicePop .vm-tab").forEach((b) => {
  b.addEventListener("click", () => {
    voiceFacets.fav = b.dataset.tab === "fav";
    voiceFacets.free = b.dataset.tab === "free";
    onFacetChange();
    voiceList.scrollTop = 0;
  });
});
voiceLangFilter.addEventListener("change", () => {
  voiceFacets.language = voiceLangFilter.value;
  onFacetChange();
});
voiceGenderFilter.addEventListener("change", () => {
  voiceFacets.gender = voiceGenderFilter.value;
  onFacetChange();
});
voiceTypeFilter.addEventListener("change", () => {
  voiceFacets.category = voiceTypeFilter.value;
  onFacetChange();
});
voiceFilterClear.addEventListener("click", () => {
  voiceFacets.language = "";
  voiceFacets.gender = "";
  voiceFacets.category = "";
  onFacetChange();
});

// NEW (1.7.0): the Filters menu and the sort menu, under their buttons.
function setVoicePop(pop, btn, open) {
  if (!pop || !btn) return;
  pop.classList.toggle("is-hidden", !open);
  btn.setAttribute("aria-expanded", String(open));
}

function closeVoiceSubPops() {
  const was = !$("voiceFilterPop").classList.contains("is-hidden")
    || !$("voiceSortMenu").classList.contains("is-hidden");
  setVoicePop($("voiceFilterPop"), $("voiceFilterBtn"), false);
  setVoicePop($("voiceSortMenu"), $("voiceSortBtn"), false);
  return was;
}

function renderVoiceSortMenu() {
  const menu = $("voiceSortMenu");
  menu.innerHTML = "";
  const head = document.createElement("div");
  head.className = "vm-pop-label";
  head.textContent = "Sort by";
  menu.appendChild(head);
  [...voiceSort.options].filter((o) => !o.hidden).forEach((o) => {
    const b = document.createElement("button");
    b.type = "button";
    b.setAttribute("role", "menuitemradio");
    const on = o.value === voiceSortMode;
    b.setAttribute("aria-checked", String(on));
    b.className = "vm-sort-item" + (on ? " is-on" : "");
    const tick = document.createElement("span");
    tick.className = "vm-sort-tick";
    if (on) tick.appendChild(iconNode("i-check", "icon-14"));
    b.append(tick, document.createTextNode(o.textContent));
    b.addEventListener("click", () => {
      voiceSort.value = o.value;
      voiceSort.dispatchEvent(new Event("change"));
      setVoicePop(menu, $("voiceSortBtn"), false);
    });
    menu.appendChild(b);
  });
}

$("voiceFilterBtn").addEventListener("click", (e) => {
  e.stopPropagation();
  const pop = $("voiceFilterPop");
  const open = pop.classList.contains("is-hidden");
  closeVoiceSubPops();
  closeVoiceMenu();
  setVoicePop(pop, $("voiceFilterBtn"), open);
});

$("voiceSortBtn").addEventListener("click", (e) => {
  e.stopPropagation();
  const menu = $("voiceSortMenu");
  const open = menu.classList.contains("is-hidden");
  closeVoiceSubPops();
  closeVoiceMenu();
  if (open) renderVoiceSortMenu();
  setVoicePop(menu, $("voiceSortBtn"), open);
});

document.addEventListener("click", (e) => {
  if (e.target.closest("#voiceFilterPop, #voiceSortMenu, .pretty-select-pop")) return;
  closeVoiceSubPops();
});


const VOICE_TIP_DELAY_MS = 450;
let voiceTipEl = null;
let voiceTipTimer = null;

function hideVoiceTip() {
  if (voiceTipEl) {
    voiceTipEl.remove();
    voiceTipEl = null;
  }
}

function cancelVoiceTip() {
  clearTimeout(voiceTipTimer);
  hideVoiceTip();
}

function scheduleVoiceTip(row, v) {
  clearTimeout(voiceTipTimer);
  voiceTipTimer = setTimeout(() => showVoiceTip(row, v), VOICE_TIP_DELAY_MS);
}

function showVoiceTip(row, v) {
  hideVoiceTip();

  const tip = document.createElement("div");
  tip.className = "voice-tip";

  const title = document.createElement("div");
  title.className = "voice-tip-name";
  title.textContent = v.name;
  tip.appendChild(title);

  if (v.description) {
    const desc = document.createElement("p");
    desc.className = "voice-tip-desc";
    desc.textContent = v.description;
    tip.appendChild(desc);
  }

  const meta = [];
  if ((v.languages || []).length) {
    const names = v.languages.map((l) => l.name).join(", ");
    meta.push(
      v.language_source === "accent"
        ? `Language: ${names} (from its accent — not stated by the voice)`
        : `Language: ${names}`
    );
  }
  if ((v.tags || []).length) meta.push(v.tags.join(" · "));
  if (v.category) meta.push(v.category);

  meta.forEach((line) => {
    const el = document.createElement("div");
    el.className = "voice-tip-meta";
    el.textContent = line;
    tip.appendChild(el);
  });

  document.body.appendChild(tip);
  voiceTipEl = tip;

  // Anchored to whatever asked for it — the menu button of its row — and
  // pulled back on screen at the edges.
  const rowRect = row.getBoundingClientRect();
  const tipRect = tip.getBoundingClientRect();
  const margin = 8;

  tip.style.left = `${Math.max(margin, Math.min(rowRect.right - tipRect.width, window.innerWidth - tipRect.width - margin))}px`;
  tip.style.top = `${Math.max(margin, Math.min(rowRect.bottom + 6, window.innerHeight - tipRect.height - margin))}px`;
}

function voiceGroupNode(label, note, free) {
  const el = document.createElement("div");
  el.className = "voice-group";
  el.textContent = label;
  // CHANGED (2.0): an engine group says what it costs.
  if (note) {
    const n = document.createElement("span");
    n.className = "voice-group-note" + (free ? " is-free" : "");
    n.textContent = note;
    el.appendChild(n);
  }
  return el;
}

// CHANGED (2.0): which engine speaks a voice, for grouping and the cost tag.
function voiceEngine(v) {
  const id = v.voice_id || "";
  // CHANGED (1.5.0): Kokoro is gone; "onecore:" is the newer Windows voices,
  // and "piper:" the voices included with Frivo.
  if (id.startsWith("piper:custom-")) return "custom";   // NEW (1.5.0): a voice you added
  if (id.startsWith("piper:")) return "piper";
  if (id.startsWith("windows:") || id.startsWith("onecore:")) return "windows";
  return "elevenlabs";
}
const VOICE_ENGINE_GROUPS = [
  ["custom", "Free · added by you", "no credits", true],         // NEW (1.5.0)
  ["piper", "Free · included with Frivo", "no credits", true],   // NEW (1.5.0)
  ["windows", "Free · built into Windows", "no credits", true],
  ["elevenlabs", "ElevenLabs", "uses credits", false],
];
function groupByEngine(list) {
  return VOICE_ENGINE_GROUPS
    .map(([engine, label, note, free]) => [label, list.filter((v) => voiceEngine(v) === engine).sort(byVoiceName), note, free])
    .filter(([, l]) => l.length);
}

// CHANGED (2.0): the voices you switch between, as chips at the top of the sheet.
function renderVoiceRecent() {
  const host = $("voiceRecent");
  if (!host) return;
  host.innerHTML = "";
  const seen = new Set();
  const ids = [...voiceRecents(), ...voiceFavorites()].filter((id) => !seen.has(id) && seen.add(id)).slice(0, 6);
  // NEW (1.7.0): labelled, so the chips don't read as filters.
  if (ids.some((id) => voiceById(id))) {
    const label = document.createElement("span");
    label.className = "voice-recent-label";
    label.textContent = "Recent";
    host.appendChild(label);
  }
  ids.forEach((id) => {
    const v = voiceById(id);
    if (!v) return;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.classList.toggle("is-current", id === activeVoiceId());
    b.textContent = voiceShortName(v);
    b.title = v.name;
    b.addEventListener("click", () => chooseVoice(v));
    host.appendChild(b);
  });
}

const VOICE_MARK_COLORS = [
  "#4d94ff", "#e2a13f", "#f06fa8", "#66d17a",
  "#b388ff", "#4dd0c4", "#4fc3f7", "#ffd54f",
];

function voiceColor(id) {
  let hash = 0;
  const text = String(id || "");
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash * 31 + text.charCodeAt(i)) >>> 0;
  }
  return VOICE_MARK_COLORS[hash % VOICE_MARK_COLORS.length];
}

function iconNode(name, cls) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", cls || "icon-18");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#${name}`);
  svg.appendChild(use);
  return svg;
}

// NEW (1.5.0): the voice-tag labels in the voice list.
const TAG_FIT_LABELS = {
  made: { label: "v4 ready", title: "ElevenLabs lists this voice as made for its expressive models (v3/v4). Best for voice tags." },
  clone: { label: "tags", title: "A voice clone or designed voice: the kind ElevenLabs recommends for voice tags." },
  older: { label: "older", title: "A voice from before the expressive models. Tags work, but it may drift between accents with them." },
};

// NEW (1.7.0): who speaks a voice, for its details line.
const VOICE_PROVIDER_LABELS = {
  elevenlabs: "ElevenLabs",
  piper: "Frivo",
  custom: "Added by you",
  windows: "Windows",
};

function capitalize(text) {
  const t = String(text || "");
  return t ? t[0].toUpperCase() + t.slice(1) : t;
}

// CHANGED (1.7.0): a row is the name, a green dot when it's free, a star,
// a play button and the "…" menu. The rest (language, gender, who speaks
// it, credits, how it takes tags) opens under the name on the voice in use
// and on the row picked with the arrow keys.
function voiceRowNode(v) {
  const isCurrent = v.voice_id === activeVoiceId();
  const engine = voiceEngine(v);
  const free = engine !== "elevenlabs";
  const isFav = voiceFavorites().includes(v.voice_id);

  const row = document.createElement("div");
  row.className = "voice-row vm-row";
  row.setAttribute("role", "option");
  row.setAttribute("aria-selected", String(isCurrent));
  row.classList.toggle("is-current", isCurrent);
  row.classList.toggle("is-free", free);

  const mark = document.createElement("span");
  mark.className = "voice-mark";
  mark.style.setProperty("--voice-color", voiceColor(v.voice_id));
  mark.appendChild(iconNode(isCurrent ? "i-check" : "i-wave", "icon-18"));
  if (isCurrent) mark.title = "The voice in use";

  const pick = document.createElement("button");
  pick.type = "button";
  pick.className = "voice-pick vm-pick";

  const line = document.createElement("span");
  line.className = "vm-line";
  const nameText = document.createElement("span");
  nameText.className = "voice-name voice-name-text";
  nameText.textContent = voiceShortName(v);
  nameText.title = v.name;
  line.appendChild(nameText);
  if (free) {
    const dot = document.createElement("span");
    dot.className = "vm-free-dot";
    dot.title = "Free: no credits";
    dot.setAttribute("aria-label", "Free");
    line.appendChild(dot);
  }

  const details = document.createElement("span");
  details.className = "vm-details";
  const meta = document.createElement("span");
  meta.className = "vm-meta";
  const langLabel = voiceLanguageLabel(v);
  const parts = [
    langLabel ? (v.language_source === "accent" ? `${langLabel} (from the accent)` : langLabel) : "",
    capitalize(v.gender),
    VOICE_PROVIDER_LABELS[engine] || "",
  ].filter(Boolean);
  meta.textContent = parts.join(" · ");
  const cost = document.createElement("span");
  cost.className = "vm-cost" + (free ? " is-free" : "");
  cost.textContent = free ? "Free" : "Uses credits";
  if (parts.length) meta.appendChild(document.createTextNode(" · "));
  meta.appendChild(cost);
  details.appendChild(meta);
  const fit = TAG_FIT_LABELS[v.tag_fit];
  if (fit) {
    const badge = document.createElement("span");
    badge.className = `voice-fit vm-fit is-${v.tag_fit}`;
    badge.title = fit.title;
    badge.append(iconNode("i-tag", "icon-12"), document.createTextNode(fit.label));
    details.appendChild(badge);
  }

  pick.append(line, details);
  pick.addEventListener("click", () => chooseVoice(v));

  const star = document.createElement("button");
  star.type = "button";
  star.className = "vm-star" + (isFav ? " is-on" : "");
  star.setAttribute("aria-pressed", String(isFav));
  star.setAttribute("aria-label", isFav ? `Remove ${v.name} from favorites` : `Add ${v.name} to favorites`);
  star.title = isFav ? "Remove from favorites" : "Add to favorites";
  star.appendChild(iconNode("i-star", "icon-16"));
  star.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleFavorite(v.voice_id);
    renderVoiceFilters();
    renderVoiceList();
    renderVoiceRecent();
    // The row was redrawn: keep focus on its star, so the keys still work.
    const again = voiceRows.find((r) => r.voice.voice_id === v.voice_id);
    if (again) again.row.querySelector(".vm-star").focus();
  });

  row.append(mark, pick, star);

  if (v.preview_url) {
    const play = document.createElement("button");
    play.type = "button";
    play.className = "voice-preview";
    const playing = voicePreviewId === v.voice_id;
    play.classList.toggle("is-playing", playing);
    play.appendChild(iconNode(playing ? "i-stop" : "i-play", "icon-14"));
    play.title = "Hear a sample — costs nothing";
    play.setAttribute("aria-label", playing ? "Stop sample" : "Play sample");
    play.addEventListener("click", (e) => {
      e.stopPropagation();
      playVoicePreview(v);
    });
    row.appendChild(play);
  } else {
    // A voice with no sample keeps the column, so the buttons line up.
    const spacer = document.createElement("span");
    spacer.className = "voice-preview-spacer";
    row.appendChild(spacer);
  }

  const menuBtn = document.createElement("button");
  menuBtn.type = "button";
  menuBtn.className = "voice-menu-btn";
  menuBtn.title = "Details and more";
  menuBtn.setAttribute("aria-label", `More options for ${v.name}${isCurrent ? " (selected)" : ""}`);
  menuBtn.appendChild(iconNode("i-dots", "icon-18"));
  menuBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    closeVoiceSubPops();
    openVoiceMenu(menuBtn, v);
  });
  row.appendChild(menuBtn);

  return row;
}

let voiceMenuEl = null;

function closeVoiceMenu() {
  if (voiceMenuEl) {
    // CHANGED (1.5.0): shrink back into its button before it's removed.
    const menu = voiceMenuEl;
    voiceMenuEl = null;
    menu.classList.add("is-leaving");
    setTimeout(() => menu.remove(), 200);
  }
}

function openVoiceMenu(anchor, v) {
  const wasOpen = voiceMenuEl && voiceMenuEl._for === v.voice_id;
  closeVoiceMenu();
  hideVoiceTip();
  if (wasOpen) return;

  const isFav = voiceFavorites().includes(v.voice_id);
  const menu = document.createElement("div");
  menu.className = "voice-menu";
  menu._for = v.voice_id;

  const item = (label, iconName, onClick, extraClass) => {
    const b = document.createElement("button");
    b.type = "button";
    if (iconName) {
      const ico = iconNode(iconName, "icon-16");
      if (extraClass) ico.setAttribute("class", `icon-16 ${extraClass}`);
      b.appendChild(ico);
    } else {
      const star = document.createElement("span");
      star.className = "voice-menu-star";
      star.textContent = isFav ? "★" : "☆";
      b.appendChild(star);
    }
    b.appendChild(document.createTextNode(label));
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      closeVoiceMenu();
      onClick();
    });
    menu.appendChild(b);
  };

  // CHANGED (1.7.0): favorites are the star on the row.
  item("Voice details", "i-spark", () => showVoiceTip(anchor, v));
  // NEW (1.5.0): a voice you added can be renamed or removed.
  if (voiceEngine(v) === "custom") {
    const key = v.voice_id.slice("piper:".length);
    item("Rename", "i-edit", async () => {
      const name = window.prompt("A name for this voice", v.name);
      if (!name || !name.trim()) return;
      const res = await fetch(`/api/voices/custom/${encodeURIComponent(key)}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { setStatus(data.error || "Couldn't rename it.", true); return; }
      setStatus(`Renamed to ${data.name}.`);
      await loadVoices();
    });
    item("Remove this voice", "i-trash", async () => {
      if (!window.confirm(`Remove ${v.name}? Its files are deleted from this PC.`)) return;
      const res = await fetch(`/api/voices/custom/${encodeURIComponent(key)}`, { method: "DELETE" });
      if (!res.ok) { setStatus("Couldn't remove it.", true); return; }
      setStatus(`${v.name} removed.`);
      await loadVoices();
    });
  }
  if (v.category) {
    item(`Hide all ${categoryLabel(v.category)} voices`, "i-close", () => {
      toggleHiddenCategory(v.category);
      renderVoiceFilters();
      renderVoiceList();
    });
  }
  // NEW (1.5.0): remove it from your ElevenLabs voices. Default voices
  // can't be removed, so they don't offer it.
  if (voiceEngine(v) === "elevenlabs" && v.category && v.category !== "premade") {
    item("Remove from my ElevenLabs voices", "i-trash", async () => {
      const ask = v.is_owner
        ? `Delete ${v.name} from your ElevenLabs account?\n\nIt's a voice you made, so this is permanent: it can't be brought back.`
        : `Remove ${v.name} from your ElevenLabs voices?\n\nYou can add it back from ElevenLabs' Voice Library any time.`;
      if (!window.confirm(ask)) return;
      setStatus(`Removing ${v.name}…`);
      const res = await fetch(`/api/voices/elevenlabs/${encodeURIComponent(v.voice_id)}`, { method: "DELETE" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { setStatus(data.error || "Couldn't remove it.", true); return; }
      if (voiceFavorites().includes(v.voice_id)) toggleFavorite(v.voice_id);
      setStatus(`${v.name} removed from your ElevenLabs voices.`);
      await loadVoices();
    }, "is-danger");
  }
  item("Copy voice ID", "i-db", async () => {
    try {
      await navigator.clipboard.writeText(v.voice_id);
      setStatus(`Copied the ID for ${v.name}.`);
    } catch (err) {
      // Clipboard access needs a secure context, which this app doesn't
      // always have on a LAN address — say so rather than failing silently.
      setStatus(`Couldn't copy: ${v.voice_id}`, true);
    }
  });

  document.body.appendChild(menu);
  voiceMenuEl = menu;

  const r = anchor.getBoundingClientRect();
  const m = menu.getBoundingClientRect();
  const margin = 8;
  menu.style.left = `${Math.max(margin, Math.min(r.right - m.width, window.innerWidth - m.width - margin))}px`;
  menu.style.top = `${Math.min(r.bottom + 6, window.innerHeight - m.height - margin)}px`;
  if (typeof growFrom === "function") growFrom(menu, anchor);   // NEW (1.5.0)
}

document.addEventListener("click", (e) => {
  if (voiceMenuEl && !voiceMenuEl.contains(e.target)) closeVoiceMenu();
  if (voiceTipEl && !voiceTipEl.contains(e.target)) hideVoiceTip();
});


const VOICE_SORT_KEY = "voice_console_voice_sort";
let voiceSortMode = localStorage.getItem(VOICE_SORT_KEY) || "favorites";

function byVoiceName(a, b) {
  return a.name.localeCompare(b.name);
}

function voiceSections(matches) {
  // CHANGED (1.5.0): always grouped by what a voice costs: Frivo's own,
  // Windows', then ElevenLabs. The sort decides the order inside each group
  // (it used to replace the groups, so "Recently added" mixed free voices in
  // with ElevenLabs ones under "No date from ElevenLabs"). Favorites still
  // lead when sorting by favorites.
  const query = voiceQuery.trim().toLowerCase();

  // While searching, what you typed outranks the sort: a name starting with
  // the query is almost always the one being looked for, even if the sort
  // would bury it. The chosen order still applies within each bucket.
  const order = (list) => {
    const ordered = sortVoicesFlat(list);
    if (!query) return ordered;
    const starts = ordered.filter((v) => v.name.toLowerCase().startsWith(query));
    const startIds = new Set(starts.map((v) => v.voice_id));
    return [...starts, ...ordered.filter((v) => !startIds.has(v.voice_id))];
  };

  // CHANGED (1.7.0): one list. What it costs is the green dot on the row
  // and the Free tab, instead of a heading over each group.
  return [[null, order(matches)]];
}

function sortVoicesFlat(matches) {
  const list = [...matches];
  if (voiceSortMode === "recent") {
    return list.sort((a, b) => (b.created_at || 0) - (a.created_at || 0) || byVoiceName(a, b));
  }
  if (voiceSortMode === "language") {
    return list.sort((a, b) => {
      const la = (a.languages || [])[0]?.name || "￿";
      const lb = (b.languages || [])[0]?.name || "￿";
      return la.localeCompare(lb) || byVoiceName(a, b);
    });
  }
  if (voiceSortMode === "category") {   // NEW (1.5.0): now sorts inside each group
    return list.sort((a, b) => categoryLabel(a.category).localeCompare(categoryLabel(b.category)) || byVoiceName(a, b));
  }
  if (voiceSortMode === "favorites") {
    const favs = new Set(voiceFavorites());
    return list.sort(
      (a, b) => favs.has(b.voice_id) - favs.has(a.voice_id) || byVoiceName(a, b)
    );
  }
  return list.sort(byVoiceName);
}

// Offering "Recently added" when nothing carries a date would be a sort
// that quietly does nothing, so the option is removed instead.
function syncVoiceSortOptions() {
  const anyDated = allVoices.some((v) => v.created_at);
  const option = [...voiceSort.options].find((o) => o.value === "recent");
  if (option) option.hidden = !anyDated;
  if (!anyDated && voiceSortMode === "recent") voiceSortMode = "favorites";
  voiceSort.value = voiceSortMode;
}

voiceSort.addEventListener("change", () => {
  voiceSortMode = voiceSort.value;
  localStorage.setItem(VOICE_SORT_KEY, voiceSortMode);
  renderVoiceList();
});

function renderVoiceList() {
  // The rows the tooltip was anchored to are about to be destroyed.
  cancelVoiceTip();
  const keepScroll = voiceList.scrollTop;   // NEW (1.7.0): starring a voice doesn't jump the list
  const keepActive = voiceActiveIndex >= 0 && voiceRows[voiceActiveIndex] ? voiceRows[voiceActiveIndex].voice.voice_id : "";
  voiceList.innerHTML = "";
  voiceRows = [];
  voiceActiveIndex = -1;

  if (!allVoices.length) {
    const note = document.createElement("p");
    note.className = "voice-none";
    note.textContent = "No voices loaded. Add your ElevenLabs key in Settings, or run Frivo's setup again (Repair) to add the free voices — then Reload.";
    voiceList.appendChild(note);
    voiceFoot.textContent = "";
    return;
  }

  const matches = matchingVoices();
  if (!matches.length) {
    const note = document.createElement("p");
    note.className = "voice-none";
    // NEW (1.7.0): an empty tab says how to fill it.
    note.textContent = voiceQuery.trim() || anyFacetActive()
      ? "Nothing matches that."
      : voiceFacets.fav
        ? "No favorites yet. Tap the star on a voice to keep it here."
        : voiceFacets.free
          ? "No free voices yet. Browse free to download some."
          : "Nothing matches that.";
    voiceList.appendChild(note);
    voiceFoot.textContent = `0 / ${allVoices.length}`;
    showHiddenCategoryNote();
    return;
  }

  const sections = voiceSections(matches);

  sections.forEach(([label, list, note, free]) => {
    if (!list.length) return;
    if (label) voiceList.appendChild(voiceGroupNode(label, note, free));
    list.forEach((v) => {
      const row = voiceRowNode(v);
      voiceList.appendChild(row);
      voiceRows.push({ row, voice: v });
    });
  });

  voiceFoot.classList.remove("is-error");   // NEW (1.5.0): after an "Add a voice" problem
  voiceFoot.textContent =
    matches.length === allVoices.length
      ? `${allVoices.length} voices`
      : `${matches.length} / ${allVoices.length}`;
  voiceFoot.title = `${matches.length} of ${allVoices.length} voices showing`;
  showHiddenCategoryNote();
  voiceList.scrollTop = keepScroll;
  if (keepActive) {
    const i = voiceRows.findIndex((r) => r.voice.voice_id === keepActive);
    if (i >= 0) { voiceRows[i].row.classList.add("is-active"); voiceActiveIndex = i; }
  }
}

// One quiet line in the footer rather than a banner: hidden categories are
// a setting you made on purpose, so it only needs to be findable, not
// announced.
function showHiddenCategoryNote() {
  const note = $("voiceHiddenNote");
  if (!note) return;
  const hidden = hiddenVoiceCategories().filter((c) => voiceCategories().includes(c));
  if (!hidden.length) {
    note.classList.add("is-hidden");
    return;
  }
  note.classList.remove("is-hidden");
  // CHANGED (1.7.0): one short button; what's hidden is in its tooltip.
  const label = note.querySelector("span");
  if (label) label.textContent = `Hidden (${hidden.length})`;
  else note.textContent = `Hidden (${hidden.length})`;
  note.title = `${hidden.map(categoryLabel).join(", ")} hidden. Click to show them again.`;
}

// ---- preview playback ----

function stopVoicePreview() {
  if (voicePreviewAudio) {
    voicePreviewAudio.pause();
    voicePreviewAudio = null;
  }
  voicePreviewId = "";
}

function playVoicePreview(v) {
  const wasPlaying = voicePreviewId === v.voice_id;
  stopVoicePreview();
  if (wasPlaying) {
    renderVoiceList();
    return;
  }

  const audio = new Audio(v.preview_url);
  // Previews are separate from the reply player's gain chain, so the volume
  // slider is applied directly here. Capped at 1 because HTMLAudioElement
  // throws on anything above it, while the slider goes to 150%.
  audio.volume = Math.min(1, masterVolume);
  audio.addEventListener("ended", () => {
    voicePreviewId = "";
    renderVoiceList();
  });
  audio.play().catch((err) => {
    voicePreviewId = "";
    renderVoiceList();
    setStatus(`Couldn't play that preview: ${err.message}`, true);
  });
  voicePreviewAudio = audio;
  voicePreviewId = v.voice_id;
  renderVoiceList();
}

// ---- choosing ----

async function chooseVoice(v) {
  const previous = { id: activeVoiceId(), name: activeVoiceName() };
  const profileId = currentProfileId;
  const profileName = activeProfile() ? activeProfile().name : "";

  // Applied locally first so the row updates the instant you click, then
  // rolled back if the save fails — a picker that waits on the network to
  // show what you picked feels broken even when it's working.
  applyVoiceLocally(profileId, v.voice_id, v.name);
  noteVoiceUsed(v.voice_id);
  closeVoicePop();

  try {
    const res = await fetch("/api/voice", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        voice_id: v.voice_id,
        voice_name: v.name,
        profile_id: profileId || null,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Couldn't save that voice.");
    setStatus(
      profileId ? `${profileName} now speaks as ${v.name}.` : `Default voice is now ${v.name}.`
    );
  } catch (err) {
    applyVoiceLocally(profileId, previous.id, previous.name);
    setStatus(`Voice not saved: ${err.message}`, true);
  }
}

function applyVoiceLocally(profileId, voiceId, voiceName) {
  if (profileId) {
    const p = allProfiles.find((x) => x.id === profileId);
    if (p) {
      p.voice_id = voiceId;
      p.voice_name = voiceName;
    }
    // The dropdown shows the profile name only, so nothing there needs
    // redrawing when the voice changes.
  } else {
    defaultVoiceId = voiceId;
    defaultVoiceName = voiceName;
  }
  renderVoiceTrigger();
}

// ---- open / close ----

function positionVoicePop() {}

function openVoicePop() {
  voicePop.classList.remove("is-hidden");
  // CHANGED (2.0): the sheet says whose voice this is.
  const forEl = $("voiceDialogFor");
  if (forEl) forEl.textContent = `for ${activeProfile() ? activeProfile().name : "Default"}`;
  renderVoiceRecent();
  voiceTrigger.setAttribute("aria-expanded", "true");
  // Every visit starts from a clean slate rather than resuming last time's
  // search, which is almost never what you want on reopening.
  voiceQuery = "";
  voiceSearch.value = "";
  voiceFacets.fav = false;
  voiceFacets.free = false;
  voiceFacets.language = "";
  voiceFacets.gender = "";
  voiceFacets.category = "";
  closeVoiceSubPops();
  renderVoiceFilters();
  renderVoiceList();

  // Scroll the voice in use into view, so opening the list shows you where
  // you are rather than the top of the alphabet.
  const current = voiceRows.find((r) => r.voice.voice_id === activeVoiceId());
  if (current) current.row.scrollIntoView({ block: "center" });

  voiceSearch.focus();
  if (!allVoices.length) loadVoices();
}

function closeVoicePop() {
  voicePop.classList.add("is-hidden");
  voiceTrigger.setAttribute("aria-expanded", "false");
  stopVoicePreview();
  // Both live on document.body, so closing the dialog doesn't take them
  // with it — they would be left floating over the page on their own.
  cancelVoiceTip();
  closeVoiceMenu();
  closeVoiceSubPops();
}

function voicePopIsOpen() {
  return !voicePop.classList.contains("is-hidden");
}

voiceTrigger.addEventListener("click", () => {
  if (voicePopIsOpen()) closeVoicePop();
  else openVoicePop();
});

voiceSearch.addEventListener("input", () => {
  voiceQuery = voiceSearch.value;
  renderVoiceList();
});

// Scrolling the list moves the row the tip is pointing at, so the tip stops
// meaning anything.
voiceList.addEventListener("scroll", cancelVoiceTip);

function setVoiceActiveIndex(next) {
  if (!voiceRows.length) return;
  const clamped = Math.max(0, Math.min(voiceRows.length - 1, next));
  voiceRows.forEach(({ row }, i) => row.classList.toggle("is-active", i === clamped));
  voiceActiveIndex = clamped;
  voiceRows[clamped].row.scrollIntoView({ block: "nearest" });
}

// On the dialog, not the sidebar trigger: the list moved to document.body,
// so keys pressed while the search field has focus never reach the picker.
voicePop.addEventListener("keydown", (e) => {
  if (!voicePopIsOpen()) return;
  // NEW (1.7.0): arrows inside the Filters or sort menu belong to it.
  if (e.key !== "Escape" && e.target.closest && e.target.closest("#voiceFilterPop, #voiceSortMenu")) return;
  if (e.key === "ArrowDown") {
    e.preventDefault();
    setVoiceActiveIndex(voiceActiveIndex + 1);
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    setVoiceActiveIndex(voiceActiveIndex - 1);
  } else if (e.key === "Enter") {
    // With nothing highlighted, Enter takes the top result — the usual
    // "type a few letters and commit" shortcut.
    const target = voiceActiveIndex >= 0 ? voiceRows[voiceActiveIndex] : voiceRows[0];
    if (target) {
      e.preventDefault();
      chooseVoice(target.voice);
    }
  } else if (e.key === "Escape") {
    e.preventDefault();
    // NEW (1.7.0): a menu that's open closes first.
    if (closeVoiceSubPops()) return;
    closeVoicePop();
    voiceTrigger.focus();
  }
});

voicePop.addEventListener("click", (e) => {
  if (e.target === voicePop) closeVoicePop();
});

const voiceCloseBtn = $("voiceCloseBtn");
if (voiceCloseBtn) voiceCloseBtn.addEventListener("click", closeVoicePop);

document.addEventListener(
  "scroll",
  () => {
    closeVoiceMenu();
    hideVoiceTip();
  },
  true
);

async function loadVoices() {
  try {
    const res = await fetch("/api/voices");
    const data = await res.json();
    if (!res.ok) {
      allVoices = [];
      renderVoiceFilters();
      renderVoiceList();
      renderVoiceTrigger();
      setStatus(data.error, true);
      return;
    }
    allVoices = data.voices || [];
    // NEW (1.5.0): e.g. ElevenLabs unreachable while the free voices loaded.
    // CHANGED (1.5.0): a refused key is an error, not a footnote.
    if (data.notice) setStatus(data.notice, !allVoices.length || data.eleven_problem === true);
    syncVoiceSortOptions();
    renderVoiceFilters();
    renderVoiceList();
    renderVoiceTrigger();
  } catch (err) {
    setStatus(`Couldn't load voices: ${err.message}`, true);
  }
}

refreshVoicesBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  loadVoices();
});

// ---------- Profiles ----------

function profileOptionLabel(p) {
  return p.name;
}

async function loadProfiles() {
  const res = await fetch("/api/profiles");
  const data = await res.json();
  allProfiles = data.profiles || [];

  profileSelect.innerHTML = '<option value="">Default</option>';
  allProfiles.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = profileOptionLabel(p);
    profileSelect.appendChild(opt);
  });

  if (currentProfileId && allProfiles.some((p) => p.id === currentProfileId)) {
    profileSelect.value = currentProfileId;
  } else {
    currentProfileId = "";
    profileSelect.value = "";
  }
  syncProfileButtons();
  // Which voice is live depends on the profile, so the row follows it.
  renderVoiceTrigger();
}

function syncProfileButtons() {
  const has = !!currentProfileId;
  editProfileBtn.disabled = !has;
  deleteProfileBtn.disabled = !has;
  if (typeof syncSessionStrip === "function") syncSessionStrip();  // CHANGED (2.0)
}

profileSelect.addEventListener("change", () => {
  currentProfileId = profileSelect.value;
  localStorage.setItem("voice_console_profile", currentProfileId);
  syncProfileButtons();

  const active = activeProfile();
  const name = active ? active.name : "Default";
  // Mark profile changes in the transcript while preserving the local view.
  addProfileDivider(name);
  renderVoiceTrigger();
  syncLanguageSuggestion();
  setStatus(`Switched to ${name}.`);
  refreshPromptIfOpen();
});

function openModal(profile) {
  editingProfileId = profile ? profile.id : null;
  profileModalTitle.textContent = profile ? "Edit profile" : "New profile";
  profileNameInput.value = profile ? profile.name : "";
  profileSystemPromptInput.value = profile ? profile.system_prompt : "";

  // Voice isn't edited here any more. Saying which one is attached still
  // matters, though — otherwise the editor looks like it lost a field.
  if (profile) {
    profileVoiceNote.textContent = profile.voice_name
      ? `Speaks as ${profile.voice_name}. Change it from the voice chip above the message box while this profile is selected.`
      : "Set its voice from the voice chip above the message box while this profile is selected.";
  } else {
    const current = voiceById(activeVoiceId());
    const name = current ? current.name : activeVoiceName();
    profileVoiceNote.textContent = name
      ? `Starts on the voice you have selected now (${name}), and can be changed any time from the voice chip above the message box.`
      : "Pick a voice from the chip above the message box first — a profile needs one.";
  }
  const startStyle = profile ? (profile.response_style || "echo") : getRadioValue(responseStyleRadios, "echo");
  // NEW (1.5.0): a profile saved before "Follow reply length" existed keeps
  // what it did — Response followed the slider, Echo and Mimic didn't. Until
  // you touch the switch, changing the style moves it to match.
  followLengthTouched = Boolean(profile && typeof profile.follow_length === "boolean");
  profileFollowLength.checked = followLengthTouched ? profile.follow_length : startStyle === "reply";
  updateFollowLengthHint(startStyle);
  if (typeof fillProfileVoiceStyle === "function") fillProfileVoiceStyle(profile);   // NEW (1.5.0)
  buildRadioGroup(
    profileResponseStyleRadios,
    responseStyles,
    "responseStyleProfile",
    startStyle,
    (id) => {
      if (!followLengthTouched) profileFollowLength.checked = id === "reply";
      updateFollowLengthHint(id);
      if (typeof showShapingState === "function") showShapingState();   // NEW (1.5.0)
    }
  );
  if (typeof showShapingState === "function") showShapingState();   // NEW (1.5.0): now the style is set
  fillOptionList(
    profilePersonalityPresetSelect,
    personalityPresets,
    profile ? (profile.personality_preset || "neutral") : personalityPresetSelect.value
  );

  // Blank first, because most profiles don't care what language they're
  // used in and shouldn't be made to pick one.
  profileLanguageSelect.innerHTML = "";
  const none = document.createElement("option");
  none.value = "";
  none.textContent = "No recommendation";
  profileLanguageSelect.appendChild(none);
  languages.forEach((l) => profileLanguageSelect.appendChild(languageOption(l, null)));
  // A new profile defaults to the language you're in now, which is usually
  // why you're making a profile at all.
  profileLanguageSelect.value = profile ? (profile.language || "") : currentLanguage;
  overlay.classList.remove("is-hidden");
  profileNameInput.focus();
  if (window.frivoProfilePersonality) window.frivoProfilePersonality.reset();   // NEW (1.5.0): the personality maker
}

function closeModal() {
  overlay.classList.add("is-hidden");
}

// NEW (1.5.0): the picked response style's one-line description, shown
// under the buttons rather than only as a tooltip, so the names don't have
// to explain everything on their own.
const responseStyleNote = $("responseStyleNote");
const profileResponseStyleNote = $("profileResponseStyleNote");
function showStyleNote(el, id) {
  if (!el) return;
  const style = responseStyles.find((s) => s.id === id);
  el.textContent = style ? style.description : "";
}

// NEW (1.5.0): what "Follow reply length" means for the style picked.
let followLengthTouched = false;
function updateFollowLengthHint(style) {
  if (!profileFollowLengthHint) return;
  const on = profileFollowLength.checked;
  showStyleNote(profileResponseStyleNote, style);
  profileFollowLengthHint.textContent = style === "reply"
    ? (on ? "Replies keep to the Reply length slider." : "Replies can be any length; the slider is ignored.")
    : (on ? "Messages longer than the Reply length slider are summarized to fit, in your voice."
          : "Says your whole message, however long.");
}
profileFollowLength.addEventListener("change", () => {
  followLengthTouched = true;
  updateFollowLengthHint(getRadioValue(profileResponseStyleRadios, "echo"));
});

newProfileBtn.addEventListener("click", () => openModal(null));

editProfileBtn.addEventListener("click", () => {
  const active = allProfiles.find((p) => p.id === currentProfileId);
  if (active) openModal(active);
});

deleteProfileBtn.addEventListener("click", async () => {
  const active = allProfiles.find((p) => p.id === currentProfileId);
  if (!active) return;
  if (!confirm(`Delete "${active.name}"? This can't be undone.`)) return;

  await fetch(`/api/profiles/${active.id}`, { method: "DELETE" });
  currentProfileId = "";
  localStorage.removeItem("voice_console_profile");
  // The conversation stays — what was said doesn't stop being true because
  // the profile that said it was deleted.
  addProfileDivider("Default");
  await loadProfiles();
  setStatus(`Deleted ${active.name}.`);
});

profileModalCancel.addEventListener("click", closeModal);
overlay.addEventListener("click", (e) => {
  if (e.target === overlay) closeModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !overlay.classList.contains("is-hidden")) closeModal();
});

profileModalSave.addEventListener("click", async () => {
  const name = profileNameInput.value.trim();

  // Editing keeps whatever voice the profile already has — the Voice row is
  // where that gets changed. A new profile inherits the live voice.
  const existing = editingProfileId ? allProfiles.find((p) => p.id === editingProfileId) : null;
  const voiceId = existing ? existing.voice_id : activeVoiceId();
  const voiceName = existing ? existing.voice_name || "" : activeVoiceName();

  // No longer required — leaving it blank means "use the preset selected
  // above" at reply time.
  const systemPrompt = profileSystemPromptInput.value.trim();

  if (!name) {
    setStatus("A profile needs a name.", true);
    return;
  }
  if (!voiceId) {
    setStatus("Pick a voice from the chip above the message box first — a profile needs one.", true);
    return;
  }

  const body = {
    name,
    voice_id: voiceId,
    voice_name: voiceName,
    system_prompt: systemPrompt,
    response_style: getRadioValue(profileResponseStyleRadios, "echo"),
    follow_length: profileFollowLength.checked,  // NEW (1.5.0)
    expressive_voice: $("profileExpressive") ? $("profileExpressive").checked : false,   // NEW (1.5.0)
    tag_shaping: $("profileShaping") ? $("profileShaping").checked : false,   // NEW (1.5.0)
    tag_amount: $("profileTagAmountRadios") ? getRadioValue($("profileTagAmountRadios"), "normal") : "normal",   // NEW (1.5.0)
    voice_delivery: $("profileDeliveryRadios") ? getRadioValue($("profileDeliveryRadios"), "natural") : "natural",   // NEW (1.5.0)
    personality_preset: profilePersonalityPresetSelect.value,
    language: profileLanguageSelect.value,
  };
  const res = editingProfileId
    ? await fetch(`/api/profiles/${editingProfileId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
    : await fetch("/api/profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

  const data = await res.json();
  if (!res.ok) {
    setStatus(data.error, true);
    return;
  }

  closeModal();
  const savedId = data.profile.id;
  const wasNew = !editingProfileId;
  await loadProfiles();
  currentProfileId = savedId;
  profileSelect.value = savedId;
  localStorage.setItem("voice_console_profile", savedId);
  syncProfileButtons();
  // loadProfiles() drew the trigger against the previously active profile.
  renderVoiceTrigger();
  syncLanguageSuggestion();
  if (wasNew) addProfileDivider(profileOptionLabel(data.profile));
  setStatus(`Saved ${data.profile.name}.`);
  refreshPromptIfOpen();
});

// ---------- Prompt inspector ----------

const promptToggle = $("promptToggle");
const promptPanel = $("promptPanel");
const promptSource = $("promptSource");
const promptYours = $("promptYours");
const promptAppended = $("promptAppended");
const promptMeta = $("promptMeta");

async function loadPromptPreview() {
  const params = new URLSearchParams({
    max_words: lengthSlider.value,
    language: currentLanguage,
    session_id: sessionId,
  });
  if (currentProfileId) params.set("profile_id", currentProfileId);

  const res = await fetch(`/api/preview-prompt?${params}`);
  const data = await res.json();
  if (!res.ok) {
    setStatus(data.error, true);
    return;
  }

  promptSource.textContent = `· ${data.source}`;
  promptYours.textContent = data.your_prompt;
  promptAppended.textContent = data.appended;
  // CHANGED (1.5.0): Response, Echo, Mimic.
  const styleLabels = { reply: "Reply", echo: "Clean up", mimic: "Word for word", flair: "Clean up" };
  const styleLabel = styleLabels[data.response_style] || data.response_style;
  promptMeta.textContent =
    `${data.model} · ${data.language} · ${styleLabel} · ${data.personality_source} · ` +
    `target ${data.target_words} words · ` +
    `${data.history_turns} message${data.history_turns === 1 ? "" : "s"} of history also sent`;
}

promptToggle.addEventListener("click", async () => {
  const opening = promptPanel.classList.contains("is-hidden");
  if (opening) await loadPromptPreview();
  promptPanel.classList.toggle("is-hidden");
  promptToggle.textContent = opening
    ? "Hide what's sent to the model"
    : "Show what's sent to the model";
});

// Keep the preview honest if the fader, style, preset, or profile changes
// while it's open
function refreshPromptIfOpen() {
  if (!promptPanel.classList.contains("is-hidden")) loadPromptPreview();
}


// ---------- NEW (1.5.0): the AI chip — Fast, Balanced or Best ----------
//
// With Chat replies set to Ollama, a chip above the message box picks which
// of three Ollama models writes replies (Settings → Providers names them).
// Switching tells the server, which unloads the others and loads the new
// one, so the next reply doesn't wait for it to load.
// "var", not const/let: Settings can load before this part of the script
// has run, and these must already exist (as undefined) when it does.
var aiChipWrap = $("aiChipWrap");
var aiChipText = $("aiChipText");
var aiPopNote = $("aiPopNote");
var aiTierList = $("aiTierList");
var AI_TIER_NAMES = { fast: "Fast", balanced: "Balanced", best: "Best" };
var aiTier = window.__pendingAiTier || "fast";

function setAiChipTier(tier) {
  if (!AI_TIER_NAMES) { window.__pendingAiTier = tier; return; }   // not set up yet
  aiTier = AI_TIER_NAMES[tier] ? tier : "fast";
  if (aiChipText) aiChipText.textContent = AI_TIER_NAMES[aiTier];
}

function syncAiChip() {
  if (!aiChipWrap) aiChipWrap = $("aiChipWrap");
  if (!aiChipWrap) return;
  const usingOllama = typeof chatProviderRadios !== "undefined"
    && getRadioValue(chatProviderRadios, "openai") === "ollama";
  aiChipWrap.classList.toggle("is-hidden", !usingOllama);
}

function describeTier(t) {
  // CHANGED (1.5.0): a name that's close to one that is installed says which.
  if (!t.installed && t.suggest && t.suggest.length) {
    return { text: `${t.model} · not found. Did you mean ${t.suggest.join(" or ")}? Put the full name in Settings > Ollama.`, warn: true };
  }
  if (!t.installed) return { text: `${t.model} · not downloaded — on the Ollama PC run: ollama pull ${t.model}`, warn: true };
  if (t.loaded && t.gpu_percent != null && t.gpu_percent < 100) {
    return { text: `${t.model} · ${t.gpu_percent}% on the graphics card, the rest on the CPU (slower)`, warn: true };
  }
  if (t.loaded) return { text: `${t.model} · loaded, on the graphics card`, warn: false };
  return { text: `${t.model} · ready`, warn: false };
}

async function refreshAiPop() {
  if (!aiTierList) return;
  if (aiPopNote) aiPopNote.textContent = "Checking…";
  let data;
  try {
    data = await (await fetch("/api/ollama/status")).json();
  } catch (err) {
    data = { reachable: false, error: "Couldn't reach Frivo.", tiers: [] };
  }
  setAiChipTier(data.tier || aiTier);
  if (aiPopNote) aiPopNote.textContent = data.reachable ? "" : (data.error || "Ollama isn't reachable.");
  aiTierList.innerHTML = "";
  (data.tiers || []).forEach((t) => {
    const row = document.createElement("label");
    row.className = "ai-tier" + (data.reachable && !t.installed ? " is-missing" : "");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "aiTier";
    input.value = t.id;
    input.checked = t.id === aiTier;
    const body = document.createElement("span");
    const name = document.createElement("span");
    name.className = "ai-tier-name";
    name.textContent = t.name;
    const sub = document.createElement("span");
    const info = data.reachable ? describeTier(t) : { text: t.model, warn: false };
    sub.className = "ai-tier-sub" + (info.warn ? " is-warn" : "");
    sub.textContent = info.text;
    body.append(name, sub);
    row.append(input, body);
    input.addEventListener("change", () => chooseAiTier(t.id, t.model));
    aiTierList.appendChild(row);
  });
}

// Catch up with anything Settings did before this part had run.
setAiChipTier(aiTier);
syncAiChip();

async function chooseAiTier(tier, model) {
  const previous = aiTier;
  setAiChipTier(tier);
  try {
    const res = await fetch("/api/ollama/tier", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tier }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Couldn't switch.");
    setStatus(`Replies now use ${AI_TIER_NAMES[tier]} (${data.model}). It's loading on the Ollama PC.`);
    // Look again once it's had a moment to load, to show where it landed.
    setTimeout(() => {
      const pop = $("aiPop");
      if (pop && !pop.classList.contains("is-hidden")) refreshAiPop();
    }, 4000);
  } catch (err) {
    setAiChipTier(previous);
    setStatus(`AI model not changed: ${err.message}`, true);
  }
}

// ---------- NEW (1.5.0): free voices ----------
//
// CHANGED (1.5.0): the free voices are Frivo's own six (Piper, installed by
// setup) and the ones built into Windows. They're chosen like any other
// voice, from the Voice list, and Frivo never downloads anything for them.
// Kokoro has been removed: it was heavy, and the natural-sounding AI voices
// are what ElevenLabs is for.
const freeVoicesStatus = $("freeVoicesStatus");

function isFreeVoiceId(id) {
  return /^(piper|windows|onecore):/.test(id || "");   // CHANGED (1.5.0)
}

function describeFreeVoices(data) {
  // CHANGED (1.5.0): Frivo's own voices first, then Windows'.
  const parts = [];
  const p = data.piper || {};
  if (!p.available) parts.push(p.problem || "Frivo's voices aren't available.");
  else if (p.count < p.total) parts.push(`${p.count} of Frivo's ${p.total} voices are installed. Run Frivo's setup again (Repair) to add the rest.`);
  else parts.push(`Frivo's ${p.total} voices are installed, under "Free · included with Frivo".`);
  const w = data.windows || {};
  if (!w.available) parts.push("Windows voices only work when Frivo runs on Windows.");
  else if (!w.count) parts.push(w.error ? `Couldn't list the Windows voices: ${w.error}` : "No Windows voices are installed.");
  else parts.push(`${w.count} more built into Windows; Windows Settings > Time & language > Speech adds others.`);
  return parts.join(" ");
}

async function refreshFreeVoices() {
  if (!freeVoicesStatus) return null;
  try {
    const data = await (await fetch("/api/voices/free")).json();
    freeVoicesStatus.textContent = describeFreeVoices(data);
    return data;
  } catch (err) {
    freeVoicesStatus.textContent = "Couldn't check the free voices.";
    return null;
  }
}


const MIC_STORAGE_KEY = "voice_console_mic_device_id";

// CHANGED (1.5.0): the microphone list.
//
// Until the page is allowed to use the mic, browsers hide every device's id
// and name. The old list was built from that anyway, so it showed
// "Microphone 1" instead of the one you picked — it looked reset — and
// picking from it could save a blank and really reset it. It also never
// refreshed after the mic was allowed, so the names only appeared after a
// click on Reload. Now:
//   - with ids hidden, the list shows your saved microphone and nothing else
//     (it's still the one dictation uses), and nothing is overwritten
//   - the list rebuilds itself as soon as the mic is allowed (dictation
//     starting, Reload), when a device is plugged in or out, and when the
//     Dictation settings are opened
//   - a saved microphone that isn't plugged in is shown as such, and
//     dictation falls back to the default one rather than failing
function micOption(value, text) {
  const opt = document.createElement("option");
  opt.value = value;
  opt.textContent = text;
  return opt;
}

function fillMicrophones(devices, selectedId) {
  const mics = devices.filter((d) => d.kind === "audioinput");
  const visible = mics.some((d) => d.deviceId && d.label);
  micSelect.innerHTML = "";

  if (!visible) {
    micSelect.appendChild(micOption(selectedId, selectedId ? "Your saved microphone" : "System default"));
    micSelect.value = selectedId;
    return false;
  }

  // Chrome lists the system default itself, as "default"; elsewhere it's
  // offered here, so "use whatever Windows is set to" is a real choice.
  if (!mics.some((d) => d.deviceId === "default")) micSelect.appendChild(micOption("", "System default"));
  if (selectedId && !mics.some((d) => d.deviceId === selectedId)) {
    micSelect.appendChild(micOption(selectedId, "Saved microphone (not connected)"));
  }
  mics.forEach((mic, i) => micSelect.appendChild(micOption(mic.deviceId, mic.label || `Microphone ${i + 1}`)));
  micSelect.value = selectedId;
  if (micSelect.value !== selectedId) micSelect.selectedIndex = 0;
  return true;
}

async function loadMicrophones() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
    micSelect.innerHTML = '<option value="">Not supported in this browser</option>';
    return;
  }
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const visible = fillMicrophones(devices, localStorage.getItem(MIC_STORAGE_KEY) || "");
    micNote.textContent = visible
      ? "Used by Accurate and Live (Evora) dictation."
      : "Your browser hides microphone names until it's allowed to use the mic — click Reload, or start dictation, to see them.";
  } catch (err) {
    console.error("enumerateDevices failed:", err);
  }
}

micSelect.addEventListener("change", () => {
  localStorage.setItem(MIC_STORAGE_KEY, micSelect.value);
});

// NEW (1.5.0): plugged in, unplugged, or newly allowed.
if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) {
  navigator.mediaDevices.addEventListener("devicechange", () => loadMicrophones());
}

// NEW (1.5.0): one way to open the chosen microphone, for every dictation
// mode that honours it. A saved device that's gone falls back to the
// default instead of failing; either way the list is refreshed, since
// the mic being allowed is what makes the real names available.
let micFellBack = false;
async function openMicrophone() {
  const deviceId = localStorage.getItem(MIC_STORAGE_KEY) || "";
  micFellBack = false;
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: deviceId ? { deviceId: { exact: deviceId } } : true,
    });
  } catch (err) {
    if (!deviceId || (err.name !== "OverconstrainedError" && err.name !== "NotFoundError")) throw err;
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    micFellBack = true;
  }
  loadMicrophones();
  return stream;
}

refreshMicsBtn.addEventListener("click", async () => {
  try {
    // Thrown away immediately — this call exists only to trigger the
    // permission prompt so enumerateDevices() returns real device labels
    // instead of blank ones.
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((t) => t.stop());
    setStatus("Microphone access granted.");
  } catch (err) {
    setStatus("Microphone access was denied — dictation won't work without it.", true);
  }
  await loadMicrophones();
});


const DICTATION_MODE_KEY = "voice_console_dictation_mode";

const DICTATION_MODES = [
  {
    id: "live",
    name: "Live (browser)",
    description:
      "Text appears as you speak, free, uses the browser's recogniser. Needs internet and always uses the system default microphone.",
  },
  {
    id: "live_local",
    name: "Live (Evora)",
    description:
      "Text appears as you speak, transcribed by your own Evora service about a second behind. Honours the microphone picked above and auto-detects language. Needs Evora selected under Providers.",
  },
  {
    id: "accurate",
    name: "Accurate",
    description:
      "Records first, then transcribes when you stop. The most accurate option, since the whole sentence is transcribed at once with full context.",
  },
];

// Auto-send after dictation detects the end of an utterance.
const autoSendToggle = $("autoSendToggle");
const AUTO_SEND_KEY = "voice_console_auto_send";
// Brief grace period after speech before sending.
const AUTO_SEND_DELAY_MS = 1400;
let autoSendTimer = null;

if (autoSendToggle) {
  autoSendToggle.checked = localStorage.getItem(AUTO_SEND_KEY) === "1";
  autoSendToggle.addEventListener("change", () => {
    localStorage.setItem(AUTO_SEND_KEY, autoSendToggle.checked ? "1" : "0");
    if (!autoSendToggle.checked) cancelAutoSend();
  });
}

function cancelAutoSend() {
  if (autoSendTimer) {
    clearTimeout(autoSendTimer);
    autoSendTimer = null;
  }
}

// NEW (1.5.0): auto-send is for what you SAY. Dictate a sentence, start
// fixing a word, and the timer from the dictation used to fire and send it
// mid-edit. Now any typing in the box makes that message yours: a pending
// auto-send is cancelled and only Enter sends it. Sending or clearing the
// box hands the next message back to auto-send, so dictating hands-free
// still sends by itself.
//
// The 'input' event, because it fires for the keyboard, paste and IME but
// never for the value dictation writes in code — exactly the line between
// "you typed" and "you said".
let typedByHand = false;
const autoSendSwitch = autoSendToggle ? autoSendToggle.closest(".switch") : null;
const AUTO_SEND_TITLE = autoSendSwitch ? autoSendSwitch.title : "";

function setTypedByHand(on) {
  if (typedByHand === on) return;
  typedByHand = on;
  if (!autoSendSwitch) return;
  // Shown on the switch itself — dimmed and outlined, nothing that changes
  // its size — so it cannot look as if auto-send quietly broke.
  autoSendSwitch.classList.toggle("is-paused", on);
  autoSendSwitch.title = on
    ? "Auto-send is paused for this message because you typed in it. Press Enter to send."
    : AUTO_SEND_TITLE;
}

messageInput.addEventListener("input", () => {
  // NEW (1.5.0): what you type is part of the message from now on. Dictation
  // used to keep its own copy of the box and write it back over the top on
  // the next word it heard, erasing whatever you had typed in the meantime.
  if (isDictating) takeTypedText();
  if (!messageInput.value.trim()) {
    // Emptied by hand: a clean slate again.
    setTypedByHand(false);
    return;
  }
  const wasPending = Boolean(autoSendTimer);
  cancelAutoSend();
  if (!typedByHand && autoSendToggle && autoSendToggle.checked && (wasPending || isDictating)) {
    setStatus("Auto-send paused for this message — press Enter to send.");
  }
  setTypedByHand(true);
});

// CHANGED (dictation speed): takes the delay, so Live (Evora) can count
// its grace period from when you stopped talking instead of from when the
// text arrived — which used to put the whole transcription time in front
// of the 1.4s on top of it.
function scheduleAutoSend(delayMs = AUTO_SEND_DELAY_MS) {
  if (!autoSendToggle || !autoSendToggle.checked) return;
  cancelAutoSend();
  // NEW (1.5.0): a message you have typed into is yours — only Enter sends it.
  if (typedByHand) return;
  autoSendTimer = setTimeout(() => {
    autoSendTimer = null;
    // Re-checked at fire time, not just when scheduled: you may have
    // started speaking again, cleared the box, or switched the option off
    // during the grace period.
    if (!autoSendToggle.checked) return;
    if (!messageInput.value.trim()) return;
    if (sendBtn.disabled) return;
    // CHANGED (dictation speed): actually checked now. Mid-sentence again
    // means the sentence is not finished; its own end reschedules this.
    if (liveLocal && liveLocal.speaking) return;
    send({ auto: true });   // CHANGED (1.5.0): sent hands-free, so no tag check
  }, Math.max(0, delayMs));
}

let mediaRecorder = null;
let recordedChunks = [];
let isDictating = false;
// Which engine the in-progress dictation was started with, so stopping
// always goes back to the same one even if the setting changed mid-way.
let activeDictationMode = null;

function speechRecognitionCtor() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function supportsLiveDictation() {
  return !!speechRecognitionCtor();
}

function currentDictationMode() {
  const stored = localStorage.getItem(DICTATION_MODE_KEY);
  if (stored === "live" || stored === "accurate" || stored === "live_local") return stored;
  // Default to live where it exists — it's the more pleasant experience and
  // it's free — and quietly fall back where it doesn't (Firefox, older
  // Safari).
  return supportsLiveDictation() ? "live" : "accurate";
}

function updateDictationModeNote() {
  if (!dictationModeNote) return;
  if (!supportsLiveDictation()) {
    dictationModeNote.textContent =
      "Live mode isn't available in this browser — Chrome and Edge support it. Accurate mode works everywhere.";
    return;
  }
  const notes = {
    live: "Words appear as you speak. Uses the system default microphone, not the one selected above.",
    live_local:
      "Words appear about a second behind as you speak, transcribed on your own GPU. Uses the microphone selected above.",
    accurate: "Nothing appears until you stop. Most accurate, since the whole sentence is transcribed at once.",
  };
  dictationModeNote.textContent = notes[currentDictationMode()] || "";
}

function buildDictationModeUI() {
  if (!dictationModeRadios) return;
  buildRadioGroup(
    dictationModeRadios,
    DICTATION_MODES,
    "dictation_mode",
    currentDictationMode(),
    (id) => {
      localStorage.setItem(DICTATION_MODE_KEY, id);
      updateDictationModeNote();
    }
  );
  updateDictationModeNote();
}

function pickRecorderMimeType() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
  if (window.MediaRecorder && MediaRecorder.isTypeSupported) {
    for (const type of candidates) {
      if (MediaRecorder.isTypeSupported(type)) return type;
    }
  }
  return "";
}

const IS_APPLE = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");

function appendToMessageInput(text) {
  // One joiner for everything that adds to the box, so the spacing rule
  // does not get two slightly different answers. A trailing space on the
  // existing text is respected rather than collapsed, in case someone is
  // mid-sentence and meant it.
  const addition = (text || "").trim();
  if (!addition) return;
  const existing = messageInput.value;
  if (!existing.trim()) {
    messageInput.value = addition;
    if (typeof tagIdeasState === "object" && tagIdeasState) messageBoxChanged();   // NEW (1.5.0)
    return;
  }
  messageInput.value = /\s$/.test(existing)
    ? existing + addition
    : `${existing} ${addition}`;
  if (typeof tagIdeasState === "object" && tagIdeasState) messageBoxChanged();   // NEW (1.5.0)
}

function setDictateUI(active) {
  dictateBtn.classList.toggle("is-recording", active);
  dictateBtn.setAttribute("aria-label", active ? "Stop dictation" : "Dictate");
  if (!active && typeof micRing !== "undefined") micRing.stop();   // NEW (1.5.0)
}

async function startDictation() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
    setStatus("Dictation isn't supported in this browser.", true);
    return;
  }

  let stream;
  try {
    stream = await openMicrophone();  // CHANGED (1.5.0)
  } catch (err) {
    setStatus(`Couldn't access the microphone: ${err.message}`, true);
    return;
  }

  recordedChunks = [];
  const mimeType = pickRecorderMimeType();
  try {
    // Same reasoning as the live path: the default bitrate is tuned for
    // human listeners, not speech models.
    mediaRecorder = mimeType
      ? new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 128000 })
      : new MediaRecorder(stream);
  } catch (err) {
    stream.getTracks().forEach((t) => t.stop());
    setStatus(`Couldn't start recording: ${err.message}`, true);
    return;
  }

  mediaRecorder.addEventListener("dataavailable", (e) => {
    if (e.data && e.data.size > 0) recordedChunks.push(e.data);
  });

  mediaRecorder.addEventListener("stop", () => {
    stream.getTracks().forEach((t) => t.stop());
    sendDictation(mediaRecorder.mimeType || mimeType || "audio/webm");
  });

  mediaRecorder.start();
  isDictating = true;
  setDictateUI(true);
  if (typeof micRing !== "undefined") micRing.fromStream(stream);   // NEW (1.5.0): the level ring
  setStatus(micFellBack
    ? "Listening on the default microphone — your saved one isn't connected. Click the mic again to stop."
    : "Listening… click the mic again to stop.");  // CHANGED (1.5.0)
}

function stopDictation() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
  isDictating = false;
  setDictateUI(false);
}

async function sendDictation(mimeType) {
  if (!recordedChunks.length) {
    setStatus("Didn't catch any audio — try again.", true);
    return;
  }

  setStatus("Transcribing…");
  dictateBtn.disabled = true;

  const blob = new Blob(recordedChunks, { type: mimeType });

  try {
    // Shared with the live-local path, so both modes send an identical
    // language hint. Keeping two copies of that logic is how they end up
    // disagreeing about what language you're speaking.
    const text = await transcribeBlob(blob, mimeType);
    if (!text) {
      setStatus("Didn't catch that — try again.", true);
      return;
    }

    // Appended rather than replacing, so dictating in a couple of goes
    // (or dictating on top of something already typed) doesn't clobber
    // what's already in the box.
    appendToMessageInput(text);
    messageInput.focus();
    setStatus("Ready.");
    scheduleAutoSend();
  } catch (err) {
    setStatus(`Transcription failed: ${err.message}`, true);
  } finally {
    dictateBtn.disabled = false;
  }
}

// ---------- Live dictation (browser speech recognition) ----------

let recognition = null;
let liveCommitted = "";
let liveInterim = "";
let liveStopping = false;
// NEW (1.5.0): a preview of words still being spoken that was on screen
// when you typed, and so became part of your text. When the finished
// transcription of those words arrives it takes the preview's place rather
// than being added a second time; until then no more previews are shown,
// so nothing moves around under your cursor.
let liveBakedInterim = "";

// NEW (1.5.0): one spacing rule for dictated text, and it leaves a space
// you typed at the end alone instead of doubling it.
function joinDictated(before, after) {
  if (!after) return before;
  if (!before.trim()) return after;
  return /\s$/.test(before) ? before + after : `${before} ${after}`;
}

// NEW (1.5.0): the box, exactly as you left it, is now the text dictation
// adds to.
function takeTypedText() {
  if (!messageInput.value.trim()) {
    liveCommitted = "";
    liveInterim = "";
    liveBakedInterim = "";
    return;
  }
  if (liveInterim) liveBakedInterim = liveInterim;
  liveCommitted = messageInput.value;
  liveInterim = "";
}

// NEW (1.5.0): a finished transcription goes into the text — in place of
// its preview if you typed while the preview was showing, otherwise on the
// end.
function commitDictated(text) {
  const baked = liveBakedInterim;
  liveBakedInterim = "";
  if (!text) return;
  if (baked) {
    const at = liveCommitted.lastIndexOf(baked);
    if (at >= 0) {
      liveCommitted = liveCommitted.slice(0, at) + text + liveCommitted.slice(at + baked.length);
      return;
    }
  }
  liveCommitted = joinDictated(liveCommitted, text);
}

const DICTATION_LANG_KEY = "voice_console_dictation_lang";

function speechLangTag() {
  const stored = localStorage.getItem(DICTATION_LANG_KEY);
  if (stored) {
    const match = languages.find((l) => l.name === stored);
    if (match && match.speech) return match.speech;
  }
  // Nothing chosen yet: follow the browser/OS language, which is almost
  // always the language its owner actually speaks.
  return navigator.language || "en-US";
}

function fillDictationLanguages() {
  if (!dictationLangSelect) return;

  const stored = localStorage.getItem(DICTATION_LANG_KEY) || "";
  dictationLangSelect.innerHTML = "";

  const auto = document.createElement("option");
  auto.value = "";
  auto.textContent = `Browser default (${navigator.language || "en-US"})`;
  dictationLangSelect.appendChild(auto);

  languages.forEach((lang) => {
    const opt = document.createElement("option");
    opt.value = lang.name;
    opt.textContent = lang.native && lang.native !== lang.name
      ? `${lang.name} — ${lang.native}`
      : lang.name;
    dictationLangSelect.appendChild(opt);
  });

  dictationLangSelect.value = stored;
}

if (dictationLangSelect) {
  dictationLangSelect.addEventListener("change", () => {
    if (dictationLangSelect.value) {
      localStorage.setItem(DICTATION_LANG_KEY, dictationLangSelect.value);
    } else {
      localStorage.removeItem(DICTATION_LANG_KEY);
    }
    // Takes effect on the next session; the recogniser's language is fixed
    // for the life of a running one.
    if (isDictating && activeDictationMode === "live") {
      setStatus("Dictation language changes apply next time you start the mic.");
    }
  });
}

function liveDisplayText() {
  // CHANGED (1.5.0): no longer trims, so a space you just typed survives.
  return joinDictated(liveCommitted, liveInterim);
}

function resetLiveDictation() {
  liveCommitted = "";
  liveInterim = "";
  liveBakedInterim = "";  // NEW (1.5.0)

  if (isDictating && recognition && !liveStopping) {
    try {
      recognition.abort();
    } catch (err) {
      /* nothing in flight to abort */
    }
  }
}

function syncLiveFromInput() {
  if (messageInput.value !== liveDisplayText()) {
    liveCommitted = messageInput.value.trim();
    liveInterim = "";
  }
}

function renderLiveText() {
  const next = liveDisplayText();
  if (messageInput.value === next) return;
  // NEW (1.5.0): if you're typing in the box, your cursor stays where it is
  // when dictated words are added — as long as the text before it didn't
  // change.
  const typing = document.activeElement === messageInput;
  const start = messageInput.selectionStart;
  const end = messageInput.selectionEnd;
  const keepCaret = typing && start != null &&
    next.slice(0, end) === messageInput.value.slice(0, end) && end < messageInput.value.length;
  messageInput.value = next;
  if (typeof tagIdeasState === "object" && tagIdeasState) messageBoxChanged();   // NEW (1.5.0): dictation, too
  if (keepCaret) {
    messageInput.setSelectionRange(start, end);
    return;
  }
  // Keep the view at the end so the box scrolls with the speech rather
  // than sitting on the first few words.
  messageInput.scrollLeft = messageInput.scrollWidth;
}

function startLiveDictation() {
  const Ctor = speechRecognitionCtor();
  if (!Ctor) {
    setStatus("Live dictation isn't supported here — switching to Accurate mode.", true);
    activeDictationMode = "accurate";
    startDictation();
    return;
  }

  recognition = new Ctor();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = speechLangTag();

  // Dictating on top of something already typed shouldn't wipe it.
  liveCommitted = messageInput.value.trim();
  liveInterim = "";
  liveBakedInterim = "";  // NEW (1.5.0)
  liveStopping = false;

  recognition.addEventListener("result", (event) => {
    syncLiveFromInput();

    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i];
      const chunk = result[0].transcript;
      if (result.isFinal) {
        const trimmed = chunk.trim();
        if (trimmed) commitDictated(trimmed);  // CHANGED (1.5.0)
      } else {
        interim += chunk;
      }
    }
    // CHANGED (1.5.0): no preview while one you typed over is still waiting
    // for its final words.
    liveInterim = liveBakedInterim ? "" : interim.trim();
    renderLiveText();

    // Any new speech cancels a pending auto-send and restarts the clock,
    // so pausing mid-thought doesn't fire the message early.
    scheduleAutoSend();
  });

  recognition.addEventListener("error", (event) => {
    // Routine and self-correcting: a pause with no speech, or the restart
    // below aborting the previous session.
    if (event.error === "no-speech" || event.error === "aborted") return;

    if (event.error === "not-allowed" || event.error === "service-not-allowed") {
      setStatus("Microphone access was denied — allow it for this site and try again.", true);
    } else if (event.error === "network") {
      setStatus(
        "Live dictation couldn't reach the speech service. Switch to Accurate mode in Settings to use OpenAI instead.",
        true
      );
    } else {
      setStatus(`Dictation error: ${event.error}`, true);
    }
    stopLiveDictation();
  });

  recognition.addEventListener("end", () => {
    if (isDictating && !liveStopping) {
      try {
        recognition.start();
        return;
      } catch (err) {
        // Restarting too soon after the previous session throws. Give it a
        // moment and try once more before giving up.
        setTimeout(() => {
          if (!isDictating || liveStopping) return;
          try {
            recognition.start();
          } catch (err2) {
            isDictating = false;
            setDictateUI(false);
            setStatus("Dictation stopped — click the mic to start again.");
          }
        }, 250);
        return;
      }
    }
    isDictating = false;
    setDictateUI(false);
    if (messageInput.value.trim()) {
      messageInput.focus();
      setStatus("Ready.");
    } else {
      setStatus("Didn't catch that — try again.");
    }
  });

  try {
    recognition.start();
  } catch (err) {
    setStatus(`Couldn't start dictation: ${err.message}`, true);
    return;
  }

  isDictating = true;
  setDictateUI(true);
  setStatus("Listening — speak and the text appears as you go. Click the mic to stop.");
}

function stopLiveDictation() {
  liveStopping = true;
  // Whatever the recogniser was still guessing at is now what's in the box;
  // treat it as committed so it isn't revised away after we stop.
  liveCommitted = liveDisplayText();
  liveInterim = "";
  if (recognition) {
    try {
      recognition.stop();
    } catch (err) {
      /* already stopped */
    }
  }
  isDictating = false;
  setDictateUI(false);
}


const LIVE_LOCAL = {
  // Speech-activity gate, not a noise filter.
  SPEECH_THRESHOLD: 0.012,
  // Silence needed before an utterance is considered finished.
  SILENCE_MS: 800,
  // How often to re-transcribe while speech continues. CHANGED (dictation
  // speed): 1000 -> 700. Evora now skips speaker analysis for dictation,
  // so each pass is cheap enough to show words sooner.
  INTERIM_MS: 700,
  // Don't bother sending anything shorter than this; it produces noise.
  MIN_CLIP_MS: 400,
  // NEW (dictation speed): the final transcription starts this long after
  // you go quiet — enough for the recorder to have flushed your last word —
  // instead of after SILENCE_MS and the recorder stopping. If you start
  // talking again first, it is thrown away. Usually its answer is back by
  // the time SILENCE_MS is up, so the sentence lands with no wait at all.
  FINAL_AFTER_MS: 300,
  // NEW (dictation speed): with Auto on, send once the text is in AND you
  // have been quiet this long, counted from when you stopped talking. It
  // used to be 1.4s counted from when the transcription came back.
  AUTO_SEND_QUIET_MS: 1500,
};

let liveLocal = null;

async function transcribeBlob(blob, mimeType) {
  const ext = mimeType.includes("mp4") ? "mp4" : mimeType.includes("ogg") ? "ogg" : "webm";
  const form = new FormData();
  form.append("audio", blob, `dictation.${ext}`);
  const spoken = speechLangTag().split("-")[0];
  if (spoken) form.append("language", spoken);

  const res = await fetch("/api/transcribe", { method: "POST", body: form });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Transcription failed.");
  return (data.text || "").trim();
}

async function startLocalLiveDictation() {
  if (!navigator.mediaDevices || !window.MediaRecorder || !window.AudioContext) {
    setStatus("This browser can't do live local dictation — using Accurate instead.", true);
    activeDictationMode = "accurate";
    startDictation();
    return;
  }

  let stream;
  try {
    stream = await openMicrophone();  // CHANGED (1.5.0)
  } catch (err) {
    setStatus(`Couldn't access the microphone: ${err.message}`, true);
    return;
  }

  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const source = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);

  liveLocal = {
    stream,
    ctx,
    source,             // NEW (1.5.0): for the level worklet
    workletLevel: null, // NEW (1.5.0): the latest level from it
    levelNode: null,    // NEW (1.5.0)
    analyser,
    data: new Uint8Array(analyser.fftSize),
    recorder: null,
    chunks: [],
    mimeType: pickRecorderMimeType() || "audio/webm",
    speaking: false,
    silenceSince: 0,
    speculative: null,   // NEW (dictation speed): the early final, see FINAL_AFTER_MS
    startedAt: 0,
    lastInterimAt: 0,
    inflight: false,
    timer: null,
  };

  liveCommitted = messageInput.value.trim();
  liveInterim = "";
  liveBakedInterim = "";  // NEW (1.5.0)
  liveStopping = false;
  isDictating = true;
  setDictateUI(true);
  setStatus(micFellBack
    ? "Listening on the default microphone — your saved one isn't connected."
    : "Listening — text appears as you speak.");

  liveLocal.timer = setInterval(pollLocalLevel, 50);
  // NEW (1.5.0): hand the listening over to the audio thread. A timer only
  // runs about once a second while Frivo's tab is in the background, so
  // speech was noticed late and its first words were never recorded. The
  // audio thread keeps its pace in any tab. The timer stays if this fails.
  useLevelWorklet(liveLocal);
  if (typeof micRing !== "undefined") micRing.fromAnalyser(analyser);   // NEW (1.5.0): the level ring
}

// NEW (1.5.0): measures the microphone's level on the audio thread, every
// 20 ms, and posts it back. Loaded from a string, so there's no extra file.
const LEVEL_WORKLET_SOURCE = `
class FrivoLevel extends AudioWorkletProcessor {
  constructor() { super(); this.sum = 0; this.count = 0; this.every = Math.round(sampleRate * 0.02); }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) {
      for (let i = 0; i < channel.length; i++) this.sum += channel[i] * channel[i];
      this.count += channel.length;
      if (this.count >= this.every) {
        this.port.postMessage(Math.sqrt(this.sum / this.count));
        this.sum = 0;
        this.count = 0;
      }
    }
    return true;
  }
}
registerProcessor("frivo-level", FrivoLevel);
`;

async function useLevelWorklet(s) {
  try {
    if (!s || !s.ctx.audioWorklet || typeof AudioWorkletNode !== "function") return;
    const url = URL.createObjectURL(new Blob([LEVEL_WORKLET_SOURCE], { type: "application/javascript" }));
    try {
      await s.ctx.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }
    if (liveLocal !== s || !isDictating) return;   // stopped while it loaded
    const node = new AudioWorkletNode(s.ctx, "frivo-level");
    // It only runs while connected through to the speakers; a gain of zero
    // keeps that silent.
    const mute = s.ctx.createGain();
    mute.gain.value = 0;
    s.source.connect(node);
    node.connect(mute);
    mute.connect(s.ctx.destination);
    node.port.onmessage = (event) => {
      s.workletLevel = event.data;
      if (liveLocal === s) pollLocalLevel();
    };
    s.levelNode = node;
    clearInterval(s.timer);
    s.timer = null;
  } catch (err) {
    // No worklet (an older browser): the 50 ms timer carries on as before.
  }
}

function currentRms() {
  // NEW (1.5.0): the audio thread's measurement, when it's running.
  if (liveLocal.levelNode && liveLocal.workletLevel != null) return liveLocal.workletLevel;
  const { analyser, data } = liveLocal;
  analyser.getByteTimeDomainData(data);
  let sum = 0;
  for (let i = 0; i < data.length; i += 1) {
    const v = (data[i] - 128) / 128;
    sum += v * v;
  }
  return Math.sqrt(sum / data.length);
}

function beginUtterance() {
  const s = liveLocal;
  const chunks = [];
  s.chunks = chunks;

  let recorder;
  try {
    recorder = new MediaRecorder(s.stream, {
      mimeType: s.mimeType,
      audioBitsPerSecond: 128000,
    });
  } catch (err) {
    recorder = new MediaRecorder(s.stream);
  }

  recorder.addEventListener("dataavailable", (e) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  });
  recorder.addEventListener("stop", () =>
    finishUtterance(chunks, recorder.speechMs || 0, recorder.speculative || null, recorder.endedAt || Date.now()));

  // Small timeslice so there's always recent audio available to send
  // without waiting for the recorder to stop.
  recorder.start(250);
  s.recorder = recorder;
  s.speculative = null;
  // NEW (dictation speed): talking again means the last sentence was not
  // the end of the thought; don't send it out from under you.
  cancelAutoSend();
  s.speaking = true;
  s.startedAt = Date.now();
  s.lastInterimAt = Date.now();
}

async function sendInterim() {
  const s = liveLocal;
  if (!s || s.inflight || !s.chunks.length) return;
  if (Date.now() - s.startedAt < LIVE_LOCAL.MIN_CLIP_MS) return;

  s.inflight = true;
  const blob = new Blob(s.chunks, { type: s.mimeType });
  try {
    const text = await transcribeBlob(blob, s.mimeType);
    // Only show it if dictation is still running and this utterance hasn't
    // already been finalised — a slow response arriving late shouldn't
    // resurrect text that's since been committed or cleared.
    // CHANGED (1.5.0): not while a preview you typed over is waiting.
    if (isDictating && liveLocal === s && s.speaking && !liveBakedInterim) {
      liveInterim = text;
      renderLiveText();
    }
  } catch (err) {
    console.error("interim transcription failed:", err);
  } finally {
    s.inflight = false;
  }
}

// NEW (dictation speed): the final transcription, started early — as soon
// as you have been quiet for FINAL_AFTER_MS — on everything recorded so far.
// Nothing said after this point belongs to it: speech resuming discards it.
function startSpeculativeFinal() {
  const s = liveLocal;
  if (!s || !s.chunks.length) return;
  const blob = new Blob(s.chunks, { type: s.mimeType });
  const spec = { promise: null };
  spec.promise = transcribeBlob(blob, s.mimeType);
  // A discarded one must not surface as an unhandled rejection.
  spec.promise.catch(() => {});
  s.speculative = spec;
}

async function finishUtterance(chunks, speechMs, speculative, endedAt) {
  const s = liveLocal;
  if (!s) return;

  const tooShort = speechMs < LIVE_LOCAL.MIN_CLIP_MS;

  if (!chunks.length || tooShort) {
    liveInterim = "";
    liveBakedInterim = "";  // NEW (1.5.0)
    renderLiveText();
    return;
  }

  const blob = new Blob(chunks, { type: s.mimeType });
  try {
    // CHANGED (dictation speed): the early final already covers every word
    // of this utterance (any speech after it would have discarded it), so
    // its answer is used, usually already back. Only without one — dictation
    // stopped by hand mid-word — is the whole clip sent now.
    let text;
    if (speculative) {
      try {
        text = await speculative.promise;
      } catch (err) {
        text = await transcribeBlob(blob, s.mimeType);
      }
    } else {
      text = await transcribeBlob(blob, s.mimeType);
    }
    // The final pass sees the whole utterance, so it supersedes whatever
    // the interim passes guessed. CHANGED (1.5.0): including one you typed
    // over, which it replaces where it stands.
    commitDictated(text);
  } catch (err) {
    setStatus(`Transcription failed: ${err.message}`, true);
  } finally {
    liveBakedInterim = "";  // NEW (1.5.0)
    liveInterim = "";
    renderLiveText();
    // CHANGED (dictation speed): counted from when you stopped talking.
    scheduleAutoSend(LIVE_LOCAL.AUTO_SEND_QUIET_MS - (Date.now() - endedAt));
  }
}

function pollLocalLevel() {
  const s = liveLocal;
  if (!s || !isDictating) return;

  const level = currentRms();
  const now = Date.now();

  if (level > LIVE_LOCAL.SPEECH_THRESHOLD) {
    if (s.silenceSince) {
      // NEW (dictation speed): the pause was not the end. The early final
      // is missing whatever is said now, so it is no longer the answer.
      s.speculative = null;
      cancelAutoSend();
    }
    s.silenceSince = 0;
    if (!s.speaking) beginUtterance();
    else if (now - s.lastInterimAt > LIVE_LOCAL.INTERIM_MS) {
      s.lastInterimAt = now;
      sendInterim();
    }
    return;
  }

  if (!s.speaking) return;

  if (!s.silenceSince) s.silenceSince = now;
  // NEW (dictation speed): start the final transcription early.
  if (!s.speculative && now - s.silenceSince > LIVE_LOCAL.FINAL_AFTER_MS &&
      s.silenceSince - s.startedAt >= LIVE_LOCAL.MIN_CLIP_MS) {
    startSpeculativeFinal();
  }
  if (now - s.silenceSince > LIVE_LOCAL.SILENCE_MS) {
    // Speech ran from the start of the utterance to the moment it went
    // quiet — not to now, which is SILENCE_MS later.
    s.speaking = false;
    if (s.recorder && s.recorder.state !== "inactive") {
      s.recorder.speechMs = s.silenceSince - s.startedAt;
      s.recorder.speculative = s.speculative;   // NEW (dictation speed)
      s.recorder.endedAt = s.silenceSince;      // NEW: when you stopped talking
      s.recorder.stop();
    }
    s.speculative = null;
    s.silenceSince = 0;
  }
}

function stopLocalLiveDictation() {
  const s = liveLocal;
  isDictating = false;
  liveStopping = true;
  setDictateUI(false);

  if (!s) return;
  clearInterval(s.timer);
  if (s.levelNode) s.levelNode.port.onmessage = null;   // NEW (1.5.0)

  if (s.recorder && s.recorder.state !== "inactive") {
    s.recorder.speechMs = Date.now() - s.startedAt;
    s.recorder.stop();
  }
  s.speaking = false;

  setTimeout(() => {
    try {
      s.stream.getTracks().forEach((t) => t.stop());
      s.ctx.close();
    } catch (err) {
      /* already torn down */
    }
    if (liveLocal === s) liveLocal = null;
  }, 1500);

  setStatus("Ready.");
}

// Named, because the mic button is no longer the only thing that starts and
// stops dictation — VRChat's mute button can too, when mute sync is on.
// Whichever engine is selected, both callers go through the same door.
function beginDictation() {
  if (isDictating) return;
  activeDictationMode = currentDictationMode();
  if (activeDictationMode === "live") startLiveDictation();
  else if (activeDictationMode === "live_local") startLocalLiveDictation();
  else startDictation();
}

function endDictation() {
  if (!isDictating) return;
  if (activeDictationMode === "live") stopLiveDictation();
  else if (activeDictationMode === "live_local") stopLocalLiveDictation();
  else stopDictation();
}

dictateBtn.addEventListener("click", () => {
  if (isDictating) {
    endDictation();
    return;
  }
  beginDictation();
  // Whatever VRChat's mute button says right now, this click is the newer
  // instruction. Recording it here is what stops the next poll immediately
  // undoing a manual override.
  noteManualDictationOverride();
});


const LISTEN = {
  // Pause that ends an utterance. Short, because a real conversation has
  // very little true silence in it — people answer each other before the
  // last word has landed. Waiting for a long gap means waiting forever.
  SILENCE_MS: 600,
  MIN_SPEECH_MS: 500,
  POLL_MS: 50,
  // How often to re-read an in-progress sentence when live updates are on.
  // Each pass re-sends the whole utterance so far, which is what lets the
  // text correct itself as more context arrives.
  INTERIM_MS: 1200,
};

const LISTEN_SEGMENT_KEY = "voice_console_listen_segment_seconds";

function maxUtteranceMs() {
  const select = $("listenSegmentSeconds");
  const seconds = select ? parseInt(select.value, 10) : 6;
  return (Number.isFinite(seconds) ? seconds : 6) * 1000;
}

const LISTEN_DEVICE_KEY = "voice_console_listen_device";
const LISTEN_THRESHOLD_KEY = "voice_console_listen_threshold";

const listenPanel = $("listenPanel");
const listenToggle = $("listenToggle");
const listenStartBtn = $("listenStartBtn");
const listenClearBtn = $("listenClearBtn");
const listenStatusEl = $("listenStatus");
const listenDeviceSelect = $("listenDeviceSelect");
const listenRefreshDevicesBtn = $("listenRefreshDevicesBtn");
const listenThreshold = $("listenThreshold");
const listenMeter = $("listenMeter");
const listenMeterFill = $("listenMeterFill");
const listenMeterMark = $("listenMeterMark");
const listenLog = $("listenLog");
const listenEmpty = $("listenEmpty");

const listenTargetLang = $("listenTargetLang");
const LISTEN_TARGET_KEY = "voice_console_listen_target";

function listenTargetLanguage() {
  if (listenTargetLang && listenTargetLang.value) return listenTargetLang.value;
  return localStorage.getItem(LISTEN_TARGET_KEY) || "English";
}

function fillListenTargetLanguages() {
  if (!listenTargetLang || !languages.length) return;
  const saved = localStorage.getItem(LISTEN_TARGET_KEY) || "English";
  listenTargetLang.innerHTML = "";
  languages.forEach((lang) => {
    const opt = document.createElement("option");
    opt.value = lang.name;
    opt.textContent =
      lang.native && lang.native !== lang.name ? `${lang.name} — ${lang.native}` : lang.name;
    listenTargetLang.appendChild(opt);
  });
  listenTargetLang.value = languages.some((l) => l.name === saved) ? saved : "English";
}

if (listenTargetLang) {
  listenTargetLang.addEventListener("change", () => {
    localStorage.setItem(LISTEN_TARGET_KEY, listenTargetLang.value);
    if (listening) setListenStatus(`Listening → ${listenTargetLanguage()}`);
  });
}
const listenLiveToggle = $("listenLiveToggle");

const listenSegmentSeconds = $("listenSegmentSeconds");
if (listenSegmentSeconds) {
  const saved = localStorage.getItem(LISTEN_SEGMENT_KEY);
  if (saved) listenSegmentSeconds.value = saved;
  listenSegmentSeconds.addEventListener("change", () => {
    localStorage.setItem(LISTEN_SEGMENT_KEY, listenSegmentSeconds.value);
  });
}

const LISTEN_LIVE_KEY = "voice_console_listen_live";
if (listenLiveToggle) {
  listenLiveToggle.checked = localStorage.getItem(LISTEN_LIVE_KEY) === "1";
  listenLiveToggle.addEventListener("change", () => {
    localStorage.setItem(LISTEN_LIVE_KEY, listenLiveToggle.checked ? "1" : "0");
  });
}

let listening = null;
let activeListenSession = null;
let listenEntrySeq = 0;

// The slider is 1-120; RMS in practice sits well under 0.25 even for loud
// speech, so map the slider onto that range rather than 0-1, which would
// make the useful settings all bunch up at the far left.
function thresholdFromSlider(value) {
  return (parseInt(value, 10) / 120) * 0.25;
}

function setListenStatus(text) {
  if (listenStatusEl) listenStatusEl.textContent = text;
}

// The dot beside the panel title. Green while audio is actually being
// captured — the status line already says what it's doing, but the dot is
// what gets read at a glance from across the room.
const listenLamp = $("listenLamp");
function setListenLamp(live) {
  if (listenLamp) listenLamp.classList.toggle("is-lit", Boolean(live));
  // CHANGED (2.0): the rail shows a dot while listening runs with the drawer closed.
  if (listenToggle) listenToggle.classList.toggle("is-live", Boolean(live));
}

// How many distinct voices the panel has separated so far. Counted from
// what's on screen rather than tracked in a variable, so a merge or a Clear
// corrects it without anything extra having to remember to.
const listenPeopleCount = $("listenPeopleCount");
function updateSpeakerCount() {
  if (!listenPeopleCount || !listenLog) return;
  const ids = new Set();
  listenLog.querySelectorAll(".listen-entry[data-speaker-id]").forEach((el) => {
    if (el.dataset.speakerSession === SPEAKER_NAMES_KEY) ids.add(el.dataset.speakerId);
  });
  const n = ids.size;
  listenPeopleCount.textContent = `${n} ${n === 1 ? "person" : "people"}`;
  const tracks = new Set();
  listenLog.querySelectorAll(".listen-entry[data-voice-track]").forEach(el => {
    if (el.dataset.speakerSession === SPEAKER_NAMES_KEY) tracks.add(el.dataset.voiceTrack);
  });
  if (tracks.size) listenPeopleCount.textContent += ` · ${tracks.size} unverified ${tracks.size === 1 ? "track" : "tracks"}`;
}

// The gate appears in two places — full-size in Setup, compact under the
// chat — so it can be watched and nudged without opening the panel. They're
// two views of one value, kept in step rather than being two settings.
const listenMeterMini = $("listenMeterMini");
const listenMeterFillMini = $("listenMeterFillMini");
const listenMeterMarkMini = $("listenMeterMarkMini");
const listenThresholdMini = $("listenThresholdMini");

function updateThresholdMark() {
  if (!listenThreshold) return;
  const percent = `${(parseInt(listenThreshold.value, 10) / 120) * 100}%`;
  if (listenMeterMark) listenMeterMark.style.left = percent;
  if (listenMeterMarkMini) listenMeterMarkMini.style.left = percent;
  if (listenThresholdMini) listenThresholdMini.value = listenThreshold.value;
  // Defined further down; guarded because this runs during init too.
  if (typeof showGateThreshold === "function") showGateThreshold();
  if (typeof paintRange === "function") {
    paintRange(listenThreshold);
    paintRange(listenThresholdMini);
  }
}

if (listenThresholdMini && listenThreshold) {
  listenThresholdMini.addEventListener("input", () => {
    listenThreshold.value = listenThresholdMini.value;
    localStorage.setItem(LISTEN_THRESHOLD_KEY, listenThreshold.value);
    updateThresholdMark();
  });
}

async function ensureDeviceAccess() {
  if (!navigator.mediaDevices) return false;
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const inputs = devices.filter((d) => d.kind === "audioinput");
    // A non-empty id anywhere means permission is already in hand.
    if (inputs.some((d) => d.deviceId)) return true;
  } catch (err) {
    /* fall through and ask */
  }
  try {
    const probe = await navigator.mediaDevices.getUserMedia({ audio: true });
    probe.getTracks().forEach((t) => t.stop());
    return true;
  } catch (err) {
    return false;
  }
}

async function loadListenDevices() {
  if (!listenDeviceSelect || !navigator.mediaDevices) return;
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const inputs = devices.filter((d) => d.kind === "audioinput");

    const preferred =
      listenDeviceSelect.value || localStorage.getItem(LISTEN_DEVICE_KEY) || "";

    listenDeviceSelect.innerHTML = "";
    if (!inputs.length) {
      const opt = document.createElement("option");
      opt.textContent = "No audio inputs found";
      listenDeviceSelect.appendChild(opt);
      return;
    }
    inputs.forEach((d, i) => {
      const opt = document.createElement("option");
      opt.value = d.deviceId;
      // Labels are blank until microphone permission has been granted once.
      opt.textContent = d.label || `Audio input ${i + 1}`;
      listenDeviceSelect.appendChild(opt);
    });
    if (preferred && inputs.some((d) => d.deviceId === preferred)) {
      listenDeviceSelect.value = preferred;
    }
  } catch (err) {
    console.error("loadListenDevices failed:", err);
  }
}

let SPEAKER_NAMES_KEY = "voice_console_speaker_names";

function speakerNames() {
  try {
    return JSON.parse(sessionStorage.getItem(SPEAKER_NAMES_KEY) || "{}");
  } catch (err) {
    return {};
  }
}

function speakerLabel(id) {
  return speakerNames()[id] || `Speaker ${id}`;
}

function renameSpeaker(id) {
  const current = speakerLabel(id);
  const next = prompt(`Name for ${current}:`, speakerNames()[id] || "");
  if (next === null) return;

  const names = speakerNames();
  if (next.trim()) names[id] = next.trim();
  else delete names[id];
  sessionStorage.setItem(SPEAKER_NAMES_KEY, JSON.stringify(names));

  // Applies backwards through the transcript, so naming someone halfway
  // through a conversation relabels what they already said.
  const label = speakerLabel(id);
  listenLog.querySelectorAll(`.listen-speaker[data-speaker="${id}"]`).forEach((el) => {
    if (el.closest(".listen-entry")?.dataset.speakerSession !== SPEAKER_NAMES_KEY) return;
    el.textContent = label;
  });
  listenLog.querySelectorAll(`.listen-avatar[data-speaker="${id}"]`).forEach((el) => {
    if (el.closest(".listen-entry")?.dataset.speakerSession !== SPEAKER_NAMES_KEY) return;
    el.textContent = label.startsWith("Speaker ")
      ? String(id)
      : label.trim().charAt(0).toUpperCase();
  });
}

// Distinct speaker colors avoid the app's accent and error colors.
const SPEAKER_COLORS = [
  "#4fc3f7", // cyan
  "#66d17a", // green
  "#f06fa8", // pink
  "#b388ff", // violet
  "#ffd54f", // yellow
  "#4dd0c4", // teal
  "#5c8cff", // blue
  "#e2a13f", // amber
];

function speakerColor(id) {
  return SPEAKER_COLORS[(id - 1) % SPEAKER_COLORS.length];
}


const LISTEN_BOTTOM_SLACK = 40;

function listenIsAtBottom() {
  return (
    listenLog.scrollHeight - listenLog.scrollTop - listenLog.clientHeight <
    LISTEN_BOTTOM_SLACK
  );
}

function listenScrollToBottom() {
  listenLog.scrollTop = listenLog.scrollHeight;
  if (listenJumpBtn) listenJumpBtn.classList.add("is-hidden");
}

// Call with the result of listenIsAtBottom() captured BEFORE the DOM
// changed — once content is added, "were we at the bottom" is unanswerable.
function listenKeepPinned(wasAtBottom) {
  if (wasAtBottom) {
    listenScrollToBottom();
  } else if (listenJumpBtn) {
    listenJumpBtn.classList.remove("is-hidden");
  }
}

const listenJumpBtn = $("listenJumpBtn");
if (listenJumpBtn) {
  listenJumpBtn.addEventListener("click", listenScrollToBottom);
}
if (listenLog) {
  listenLog.addEventListener("scroll", () => {
    if (listenJumpBtn && listenIsAtBottom()) {
      listenJumpBtn.classList.add("is-hidden");
    }
  });
}

function addListenEntry() {
  // Captured before anything is appended — see listenKeepPinned().
  const wasAtBottom = listenIsAtBottom();

  // Queried fresh: Clear rebuilds this node, so a reference captured at
  // page load goes stale and the placeholder would never be removed again.
  const placeholder = listenLog.querySelector(".empty-note");
  if (placeholder) placeholder.remove();

  const entry = document.createElement("div");
  entry.className = "listen-entry is-pending";
  entry.id = `listen-${(listenEntrySeq += 1)}`;
  // Ctrl on Windows and Linux, Cmd on a Mac — named for whichever this is,
  // rather than showing both and making the reader work out which is theirs.
  entry.title =
    "Click to put this message in your reply box\n" +
    `${IS_APPLE ? "Cmd" : "Ctrl"}-click to add it to what's already there`;

  const avatar = document.createElement("div");
  avatar.className = "listen-avatar is-unknown";
  avatar.textContent = "?";
  avatar.title = "Too short to identify the voice";

  const head = document.createElement("div");
  head.className = "listen-entry-head";
  const speaker = document.createElement("button");
  speaker.className = "listen-speaker is-hidden";
  speaker.type = "button";
  speaker.title = "Click to rename this speaker";
  const time = document.createElement("span");
  time.className = "listen-time";
  time.textContent = new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  const lang = document.createElement("span");
  lang.className = "listen-entry-lang";
  head.append(speaker, time, lang);

  const bubble = document.createElement("div");
  bubble.className = "listen-bubble";

  const text = document.createElement("div");
  text.className = "listen-text";
  text.textContent = "…";

  // Created once and reused. Appending a fresh one on every update is what
  // made a single sentence sprout a stack of near-identical originals as
  // the live passes came in.
  const original = document.createElement("div");
  original.className = "listen-original is-hidden";

  bubble.append(text, original);
  const stack = document.createElement("div");
  stack.className = "listen-stack";
  stack.append(head, bubble);
  entry.append(avatar, stack);

  // Click anywhere on a message to load it into the reply box. Clicking the
  // speaker name is exempt — that renames, and the two shouldn't fight.
  //
  // Ctrl (or Cmd) held appends instead of replacing, so several things
  // people said can be gathered into one reply. Replacing stays the plain
  // click because it is the common case: usually you are answering the one
  // message you just clicked.
  entry.addEventListener("click", (event) => {
    if (event.target.closest(".listen-speaker")) return;
    const spoken = text.textContent.trim();
    if (!spoken || spoken === "…") return;

    if (event.ctrlKey || event.metaKey) {
      appendToMessageInput(spoken);
    } else {
      messageInput.value = spoken;
      if (typeof tagIdeasState === "object" && tagIdeasState) messageBoxChanged();   // NEW (1.5.0)
    }
    messageInput.focus();
    // Put the caret at the end, so typing continues the sentence rather
    // than landing wherever it happened to be.
    const end = messageInput.value.length;
    messageInput.setSelectionRange(end, end);
    resetLiveDictation();
    entry.classList.add("is-copied");
    setTimeout(() => entry.classList.remove("is-copied"), 400);
  });

  listenLog.appendChild(entry);
  listenKeepPinned(wasAtBottom);

  return { entry, head, lang, text, speaker, original, bubble, avatar };
}

function applySpeakerGrouping(entry, id) {
  entry.dataset.speakerId = id;
  entry.style.setProperty("--speaker-color", speakerColor(id));

  // Consecutive lines from the same person read as one block, the way a
  // chat client groups messages — repeating the name on every line is what
  // made this hard to follow.
  let previous = entry.previousElementSibling;
  while (previous && !previous.dataset.speakerId) {
    previous = previous.previousElementSibling;
  }
  const sameAsPrevious = previous && previous.dataset.speakerId === String(id) &&
    previous.dataset.speakerSession === entry.dataset.speakerSession;
  entry.classList.toggle("is-continuation", Boolean(sameAsPrevious));
  updateSpeakerCount();
}

function applySpeakerMerges(merged) {
  if (!merged) return;
  const names = speakerNames();
  let namesChanged = false;

  Object.entries(merged).forEach(([fromId, intoId]) => {
    listenLog.querySelectorAll(`.listen-entry[data-speaker-id="${fromId}"]`).forEach((entry) => {
      entry.dataset.speakerId = intoId;
      entry.style.setProperty("--speaker-color", speakerColor(Number(intoId)));
    });
    listenLog.querySelectorAll(`[data-speaker="${fromId}"]`).forEach((el) => {
      el.dataset.speaker = intoId;
    });

    // A name given to the absorbed speaker carries over, unless the
    // surviving one is already named.
    if (names[fromId] && !names[intoId]) names[intoId] = names[fromId];
    if (names[fromId]) {
      delete names[fromId];
      namesChanged = true;
    }
  });

  if (namesChanged) sessionStorage.setItem(SPEAKER_NAMES_KEY, JSON.stringify(names));

  // Re-render the labels and re-evaluate grouping, since neighbouring rows
  // may now belong to the same person.
  listenLog.querySelectorAll(".listen-entry[data-speaker-id]").forEach((entry) => {
    const id = Number(entry.dataset.speakerId);
    const label = speakerLabel(id);
    const chip = entry.querySelector(".listen-speaker");
    if (chip) {
      chip.textContent = label;
    }
    const avatar = entry.querySelector(".listen-avatar");
    if (avatar) {
      avatar.textContent = label.startsWith("Speaker ")
        ? String(id)
        : label.trim().charAt(0).toUpperCase();
    }
    applySpeakerGrouping(entry, id);
  });
}

function fillListenEntry(node, data, interim = false) {
  const wasAtBottom = listenIsAtBottom();
  if (data.speaker && data.speaker.merged) applySpeakerMerges(data.speaker.merged);

  // Interim results stay visibly provisional, so a half-sentence isn't
  // mistaken for what someone actually finished saying.
  node.entry.classList.toggle("is-pending", interim);
  node.lang.textContent = data.detected_language || "";
  node.text.textContent = data.text || "";
  if (!interim) node.done = true;

  if (data.speaker && data.speaker.ambiguous) {
    // The server could see it was one of the known voices but not which.
    // Saying so is more useful than a bare "?", and more honest than a
    // coin-flip name.
    node.avatar.textContent = "~";
    node.avatar.title =
      `Sounded like more than one known speaker (best match ${data.speaker.similarity}). ` +
      "Raise Voice matching if this happens often.";
  } else if (data.speaker && data.speaker.id) {
    const id = data.speaker.id;
    if (data.speaker.name) {
      const names = speakerNames(); names[id] = data.speaker.name;
      sessionStorage.setItem(SPEAKER_NAMES_KEY, JSON.stringify(names));
    }
    node.entry.dataset.speakerSession = SPEAKER_NAMES_KEY;
    node.speaker.classList.remove("is-hidden");
    node.speaker.dataset.speaker = id;
    node.speaker.textContent = speakerLabel(id);
    // Colour identifies the speaker on the avatar disc; the name itself
    // stays plain, so a row isn't three coloured things in a line.
    if (node.avatar) {
      node.avatar.classList.remove("is-unknown");
      node.avatar.title = "";
      const label = speakerLabel(id);
      // First character of the name, so a renamed speaker gets a
      // recognisable initial rather than staying a number.
      node.avatar.textContent = label.startsWith("Speaker ")
        ? String(id)
        : label.trim().charAt(0).toUpperCase();
      node.avatar.dataset.speaker = id;
    }
    if (!node.speaker.dataset.bound) {
      node.speaker.dataset.bound = "1";
      node.speaker.addEventListener("click", () => {
        if (node.entry.dataset.speakerSession === SPEAKER_NAMES_KEY) renameSpeaker(id);
      });
    }
    const uncertain = Boolean(data.speaker.uncertain);
    node.entry.classList.toggle("is-uncertain", uncertain);
    if (uncertain) {
      const why = data.speaker.short
        ? "clip too short to be sure"
        : "more than one voice in this clip";
      node.speaker.title =
        `Probably ${speakerLabel(id)} — ${why} ` +
        `(best match ${data.speaker.similarity}). Click to rename.`;
    } else if (data.speaker.similarity != null && !data.speaker.new) {
      node.speaker.title = `Voice match ${data.speaker.similarity}. Click to rename.`;
    }
    applySpeakerGrouping(node.entry, id);
  }

  if (data.source === "separated") {
    node.entry.classList.add("is-uncertain");
    node.speaker.classList.remove("is-hidden");
    if (!data.speaker) {
      node.speaker.textContent = data.voice_track?.label || "Unidentified voice";
      if (data.voice_track) {
        node.entry.dataset.voiceTrack = data.voice_track.id;
        node.entry.dataset.speakerSession = SPEAKER_NAMES_KEY;
        updateSpeakerCount();
      }
    }
    node.speaker.textContent += data.overlapping ? " · overlap (unverified)" : " · unverified";
    node.speaker.title = "Estimated voice from separated audio. Words and identity may be inaccurate; this label does not pass strict speaker filters.";
  } else if (data.overlapping && !data.speaker) {
    node.speaker.classList.remove("is-hidden");
    node.speaker.textContent = "Overlapping voices · unidentified";
  } else if (data.source === "unknown" && !data.speaker) {
    node.speaker.classList.remove("is-hidden");
    node.speaker.textContent = "Unidentified voice";
    node.speaker.title = "Waiting for enough consistent, clear speech before assigning a speaker.";
  } else if (data.speaker && !data.speaker.confirmed) {
    node.speaker.textContent += " · learning";
    node.speaker.title = "Learning this voice from clear speech during this session.";
  }

  // Only show the original when it differs — for same-language speech the
  // two are identical and printing both is just noise.
  if (data.translated && data.original && data.original !== data.text) {
    node.original.textContent = data.original;
    node.original.classList.remove("is-hidden");
  } else {
    node.original.classList.add("is-hidden");
  }

  listenKeepPinned(wasAtBottom);
}

// Raw provider errors are long JSON blobs that wreck the readability of a
// transcript you're trying to follow in real time. Keep the meaning, drop
// the payload.
function friendlyListenError(message) {
  const text = String(message || "Failed.");
  if (text.includes("Invalid file format") || text.includes("invalid_request_error")) {
    return "Segment was unreadable — skipped.";
  }
  if (text.toLowerCase().includes("unreachable") || text.includes("Connection")) {
    return "Transcription server unreachable.";
  }
  if (text.length > 120) return `${text.slice(0, 117)}…`;
  return text;
}

function ensureListenNode(ref) {
  if (!ref.node) ref.node = addListenEntry();
  return ref.node;
}

function sendListenSegment(chunks, mimeType, ref, interim = false) {
  const owner = ref.owner;
  if (!owner) return deliverListenSegment(chunks, mimeType, ref, interim);
  owner.pending = owner.pending.then(() => deliverListenSegment(chunks, mimeType, ref, interim));
  return owner.pending;
}

async function deliverListenSegment(chunks, mimeType, ref, interim = false) {
  const blob = new Blob(chunks, { type: mimeType });
  const ext = mimeType.includes("mp4") ? "mp4" : mimeType.includes("ogg") ? "ogg" : "webm";

  const form = new FormData();
  form.append("audio", blob, `listen.${ext}`);
  form.append("target_language", listenTargetLanguage());
  if (interim) form.append("interim", "1");
  if (ref.owner?.sessionId) form.append("listening_session", ref.owner.sessionId);

  try {
    const res = await fetch("/api/listen", { method: "POST", body: form });
    const data = await res.json();

    // The node may have been finalised by the real result while this
    // interim pass was still in flight. Late partial text must never
    // overwrite a finished sentence.
    if (ref.owner && ref.owner !== activeListenSession) return;
    if (interim && (ref.done || (ref.node && ref.node.done))) return;
    if (!interim) ref.done = true;
    if (data.speaker_status?.state && data.speaker_status.state !== "ready") {
      setListenStatus(`Speaker recognition: ${data.speaker_status.state.replaceAll("_", " ")}. Select Speaker setup.`);
    } else if (data.speaker_status?.notice?.includes("failed for this clip")) {
      setListenStatus("Voice separation could not process this clip. Showing unidentified speech; check Speaker setup.");
    }

    if (!res.ok) {
      if (interim) return; // a failed partial isn't worth reporting
      const node = ensureListenNode(ref);
      node.text.textContent = friendlyListenError(data.error);
      node.entry.classList.remove("is-pending");
      node.done = true;
      return;
    }

    // Nothing was actually said. With no row created yet there's nothing to
    // clean up — the gate opening on a door slam now leaves no trace at all.
    if (data.empty || !(data.text || "").trim()) {
      if (!interim && ref.node) ref.node.entry.remove();
      return;
    }

    if (!interim && data.segments?.length) {
      const first = ensureListenNode(ref);
      let anchor = first.entry;
      data.segments.forEach((segment, index) => {
        const node = index === 0 ? first : addListenEntry();
        if (index) anchor.after(node.entry);
        fillListenEntry(node, segment, false);
        anchor = node.entry;
      });
    } else {
      fillListenEntry(ensureListenNode(ref), data, interim);
    }
  } catch (err) {
    if (interim) return;
    const node = ensureListenNode(ref);
    node.text.textContent = `Failed: ${err.message}`;
    node.entry.classList.remove("is-pending");
    node.done = true;
  }
}

function listenBeginUtterance() {
  const s = listening;

  const chunks = [];
  let recorder;
  try {
    recorder = new MediaRecorder(s.stream, {
      mimeType: s.mimeType,
      audioBitsPerSecond: 128000,
    });
  } catch (err) {
    recorder = new MediaRecorder(s.stream);
  }

  // A shared handle rather than a row. The row itself is built lazily, the
  // first time there's real text to show — see ensureListenNode().
  const ref = { node: null, owner: s, done: false };
  recorder.ref = ref;
  recorder.chunks = chunks;

  recorder.addEventListener("dataavailable", (e) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  });
  recorder.addEventListener("stop", () => {
    const speechMs = recorder.speechMs || 0;
    if (speechMs >= LISTEN.MIN_SPEECH_MS && chunks.length) {
      sendListenSegment(chunks, s.mimeType, ref, false);
    } else if (ref.node) {
      // Too short to be speech. Only possible to have a row here if a live
      // interim pass already produced text for it.
      ref.node.entry.remove();
    }
  });

  recorder.start(250);
  s.recorder = recorder;
  s.speaking = true;
  s.startedAt = Date.now();
  s.lastInterimAt = Date.now();
  s.silenceSince = 0;
}

function listenEndUtterance(speechMs) {
  const s = listening;
  s.speaking = false;
  s.silenceSince = 0;
  const recorder = s.recorder;
  if (recorder && recorder.state !== "inactive") {
    // Stamped on the recorder so its own stop handler reads the duration
    // that belongs to it.
    recorder.speechMs = speechMs;
    recorder.stop();
  }
}

function listenPoll() {
  const s = listening;
  if (!s) return;

  s.analyser.getByteTimeDomainData(s.data);
  let sum = 0;
  for (let i = 0; i < s.data.length; i += 1) {
    const v = (s.data[i] - 128) / 128;
    sum += v * v;
  }
  const level = Math.sqrt(sum / s.data.length);
  const gate = thresholdFromSlider(listenThreshold.value);
  const now = Date.now();

  // Meter is scaled to the same 0-0.25 range as the gate so the bar and the
  // marker are directly comparable.
  const width = `${Math.min(100, (level / 0.25) * 100)}%`;
  const open = level > gate;
  if (listenMeterFill) listenMeterFill.style.width = width;
  if (listenMeterFillMini) listenMeterFillMini.style.width = width;
  if (listenMeter) listenMeter.classList.toggle("is-open", open);
  if (listenMeterMini) listenMeterMini.classList.toggle("is-open", open);
  setGateState(open ? "Hearing speech" : "Quiet", open);

  if (level > gate) {
    s.silenceSince = 0;
    if (!s.speaking) {
      listenBeginUtterance();
    } else if (now - s.startedAt > maxUtteranceMs()) {
      // The timer fired. Cut, commit, and start the next segment in the
      // same breath so no audio is dropped at the boundary.
      listenEndUtterance(now - s.startedAt);
      listenBeginUtterance();
    } else if (
      listenLiveToggle &&
      listenLiveToggle.checked &&
      !s.interimInflight &&
      now - s.lastInterimAt > LISTEN.INTERIM_MS &&
      s.recorder &&
      s.recorder.chunks.length
    ) {
      // Send complete audio so each interim transcription has valid media and
      // full utterance context.
      s.lastInterimAt = now;
      s.interimInflight = true;
      sendListenSegment(
        s.recorder.chunks.slice(),
        s.mimeType,
        s.recorder.ref,
        true
      ).finally(() => {
        if (listening === s) s.interimInflight = false;
      });
    }
    return;
  }

  if (!s.speaking) return;
  if (!s.silenceSince) s.silenceSince = now;
  if (now - s.silenceSince > LISTEN.SILENCE_MS) {
    listenEndUtterance(s.silenceSince - s.startedAt);
  }
}

async function startListening() {
  if (!navigator.mediaDevices || !window.MediaRecorder || !window.AudioContext) {
    setListenStatus("Not supported in this browser.");
    return;
  }

  // Ask for permission and re-read the device list first. Both have to
  // happen before the id is read, or the id read is the blank one.
  const savedDevice = localStorage.getItem(LISTEN_DEVICE_KEY) || "";
  await ensureDeviceAccess();
  await loadListenDevices();
  loadMicrophones();  // NEW (1.5.0): access granted means real names for this list too

  const deviceId = listenDeviceSelect ? listenDeviceSelect.value : "";

  if (savedDevice && deviceId !== savedDevice) {
    setListenStatus("Saved audio source is gone — using the system default.");
  }

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: deviceId
        ? {
            deviceId: { exact: deviceId },
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
          }
        : true,
    });
  } catch (err) {
    setListenStatus(`Couldn't open that device: ${err.message}`);
    return;
  }

  let session;
  try {
    const response = await fetch("/api/listen-session", { method: "POST" });
    session = await response.json();
    if (!response.ok) throw new Error(session.error || "Could not start speaker memory.");
  } catch (err) {
    stream.getTracks().forEach(track => track.stop());
    setListenStatus(err.message);
    return;
  }
  SPEAKER_NAMES_KEY = "voice_console_speaker_names_" + (session.speaker_session || crypto.randomUUID());
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const source = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);

  listening = {
    sessionId: session.listening_session,
    pending: Promise.resolve(),
    stream,
    ctx,
    analyser,
    data: new Uint8Array(analyser.fftSize),
    mimeType: pickRecorderMimeType() || "audio/webm",
    recorder: null,
    chunks: [],
    speaking: false,
    startedAt: 0,
    silenceSince: 0,
    speechMs: 0,
    timer: null,
  };
  activeListenSession = listening;
  updateSpeakerCount();
  listening.timer = setInterval(listenPoll, LISTEN.POLL_MS);

  listenStartBtn.textContent = "Stop listening";
  setListenLamp(true);
  listenStartBtn.classList.add("is-live");
  // Only overwrite the warning above when there was nothing to warn about.
  if (!savedDevice || deviceId === savedDevice) {
    const state = session.speaker_status?.state;
    setListenStatus(state && state !== "ready"
      ? `Listening; speaker recognition ${state.replaceAll("_", " ")}. Select Speaker setup.`
      : `Listening → ${listenTargetLanguage()} · session voices active`);
  }
}

async function closeListenSession(s) {
  await s.pending;
  if (!s.sessionId) return;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const res = await fetch("/api/listen-session", {method: "DELETE", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({listening_session: s.sessionId})});
      if (res.ok) return;
    } catch (_) { /* retry after in-flight inference */ }
    await new Promise(resolve => setTimeout(resolve, 600));
  }
}

function stopListening() {
  const s = listening;
  listening = null;

  listenStartBtn.textContent = "Start listening";
  setListenLamp(false);
  listenStartBtn.classList.remove("is-live");
  setListenStatus("Idle");
  if (listenMeter) listenMeter.classList.remove("is-open");
  if (listenMeterFill) listenMeterFill.style.width = "0%";
  if (listenMeterMini) listenMeterMini.classList.remove("is-open");
  if (listenMeterFillMini) listenMeterFillMini.style.width = "0%";
  setGateState("Idle", false);

  if (!s) return Promise.resolve();
  const finished = s.recorder && s.recorder.state !== "inactive"
    ? new Promise(resolve => s.recorder.addEventListener("stop", () => resolve(closeListenSession(s)), {once: true}))
    : closeListenSession(s);
  clearInterval(s.timer);
  // Same as the dictation path: stamp the duration so a sentence in
  // progress when you hit Stop still gets transcribed instead of being
  // dropped for looking zero-length.
  if (s.recorder && s.recorder.state !== "inactive") {
    s.recorder.speechMs = Date.now() - s.startedAt;
    s.recorder.stop();
  }
  setTimeout(() => {
    try {
      s.stream.getTracks().forEach((t) => t.stop());
      s.ctx.close();
    } catch (err) {
      /* already gone */
    }
  }, 1200);
  return finished;
}

if (listenToggle) {
  listenToggle.addEventListener("click", async () => {
    const opening = listenPanel.classList.contains("is-hidden");
    listenPanel.classList.toggle("is-hidden");
    // Marks the button while its panel is up, the same way Settings does —
    // otherwise there's nothing to say which of the two is open.
    listenToggle.classList.toggle("is-active", opening);
    if (opening) {
      updateThresholdMark();
      await loadListenDevices();
    }
  });
}

if (listenStartBtn) {
  listenStartBtn.addEventListener("click", async () => {
    listenStartBtn.disabled = true;
    try { if (listening) await stopListening(); else await startListening(); }
    finally { listenStartBtn.disabled = false; }
  });
}

// Docking is remembered, because it's a workspace preference rather than a
// per-session choice — if you like the chat window pinned, you like it
// pinned every time.
const listenDockBtn = document.getElementById("listenDockBtn");  // CHANGED (2.0): gone; the drawer has no dock
const LISTEN_DOCK_KEY = "voice_console_listen_docked";

function applyListenDock(docked) {
  listenPanel.classList.toggle("is-docked", docked);
  if (listenDockBtn) listenDockBtn.textContent = docked ? "Undock" : "Dock";
  localStorage.setItem(LISTEN_DOCK_KEY, docked ? "1" : "0");
}

if (listenDockBtn) {
  // Docked by default on a wide screen — the side space is otherwise dead,
  // and a chat panel is only useful if it's visible while you reply. An
  // explicit choice either way is remembered.
  const savedDock = localStorage.getItem(LISTEN_DOCK_KEY);
  // Must match the CSS breakpoint that actually enables docking, or the
  // panel gets the class on a screen too narrow to honour it. Above it the
  // panel owns a column and docking is ignored entirely.
  const narrowEnough = window.matchMedia("(max-width: 1279px)").matches;
  applyListenDock(savedDock === null ? narrowEnough : savedDock === "1");
  listenDockBtn.addEventListener("click", () => {
    applyListenDock(!listenPanel.classList.contains("is-docked"));
  });
}

// Voice-matching strictness, applied live on the Whisper server. Kept as a
// slider rather than a config file because the right value can only be
// found by watching real labels appear during a real conversation.
const listenSpeakerThreshold = $("listenSpeakerThreshold");
const listenSpeakerThresholdValue = $("listenSpeakerThresholdValue");
const LISTEN_THRESHOLD_PREF_KEY = "voice_console_speaker_threshold";
let thresholdSaveTimer = null;

function showThresholdValue() {
  if (!listenSpeakerThreshold || !listenSpeakerThresholdValue) return;
  listenSpeakerThresholdValue.textContent = (
    parseInt(listenSpeakerThreshold.value, 10) / 100
  ).toFixed(2);
}

async function pushSpeakerThreshold() {
  if (!listenSpeakerThreshold) return;
  const threshold = parseInt(listenSpeakerThreshold.value, 10) / 100;
  try {
    await fetch("/api/listen-speakers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ threshold }),
    });
    localStorage.setItem(LISTEN_THRESHOLD_PREF_KEY, String(threshold));
  } catch (err) {
    console.error("couldn't set speaker threshold:", err);
  }
}

async function syncSpeakerThresholdFromServer() {
  if (!listenSpeakerThreshold) return;
  if (localStorage.getItem(LISTEN_THRESHOLD_PREF_KEY)) return; // you chose; keep it
  try {
    const res = await fetch("/api/listen-speakers");
    const data = await res.json();
    if (res.ok && Number.isFinite(data.threshold)) {
      listenSpeakerThreshold.value = Math.round(data.threshold * 100);
      showThresholdValue();
    }
  } catch (err) {
    /* server not up yet — the slider default is fine */
  }
}

if (listenSpeakerThreshold) {
  const saved = parseFloat(localStorage.getItem(LISTEN_THRESHOLD_PREF_KEY));
  if (Number.isFinite(saved)) listenSpeakerThreshold.value = Math.round(saved * 100);
  showThresholdValue();
  syncSpeakerThresholdFromServer();

  listenSpeakerThreshold.addEventListener("input", () => {
    showThresholdValue();
    // Debounced: dragging a slider would otherwise fire a request per pixel.
    clearTimeout(thresholdSaveTimer);
    thresholdSaveTimer = setTimeout(pushSpeakerThreshold, 300);
  });
}

const listenResetSpeakersBtn = $("listenResetSpeakersBtn");

if (listenResetSpeakersBtn) {
  listenResetSpeakersBtn.addEventListener("click", async () => {
    listenResetSpeakersBtn.disabled = true;
    listenStartBtn.disabled = true;
    try {
      const wasListening = Boolean(listening);
      await stopListening();
      sessionStorage.removeItem(SPEAKER_NAMES_KEY);
      if (wasListening) await startListening();
      else setListenStatus("Temporary voices cleared. Saved voices are kept.");
    } finally {
      listenResetSpeakersBtn.disabled = false;
      listenStartBtn.disabled = false;
    }
  });
}

if (listenClearBtn) {
  listenClearBtn.addEventListener("click", () => {
    listenLog.innerHTML = '<p class="empty-note" id="listenEmpty">Nothing heard yet.</p>';
    updateSpeakerCount();
  });
}

if (listenRefreshDevicesBtn) {
  listenRefreshDevicesBtn.addEventListener("click", async () => {
    // Device labels stay blank until permission has been granted once.
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((t) => t.stop());
    } catch (err) {
      setListenStatus("Audio access denied — listening needs it.");
    }
    await loadListenDevices();
  });
}

if (listenDeviceSelect) {
  listenDeviceSelect.addEventListener("change", () => {
    localStorage.setItem(LISTEN_DEVICE_KEY, listenDeviceSelect.value);
    if (listening) {
      // Reopen on the new device rather than silently carrying on with the
      // old one.
      stopListening();
      setTimeout(startListening, 300);
    }
  });
}

if (listenThreshold) {
  const saved = parseInt(localStorage.getItem(LISTEN_THRESHOLD_KEY), 10);
  if (Number.isFinite(saved)) {
    // Clamped rather than trusted: a value saved before the slider's range
    // changed would otherwise be silently rounded by the browser, leaving
    // the stored number and the displayed one disagreeing.
    const min = parseInt(listenThreshold.min, 10) || 1;
    const max = parseInt(listenThreshold.max, 10) || 120;
    listenThreshold.value = Math.min(max, Math.max(min, saved));
  }
  updateThresholdMark();

  listenThreshold.addEventListener("input", () => {
    localStorage.setItem(LISTEN_THRESHOLD_KEY, listenThreshold.value);
    updateThresholdMark();
  });
}

// ---------- Chat ----------

// CHANGED (1.5.0): opts.reviewed (the tags were checked: send as it is,
// without Auto tags), opts.auto (auto-send: never stop to check).
async function send(opts = {}) {
  const message = messageInput.value.trim();
  if (!message) return;
  // NEW (1.5.0): "Check auto tags first": the tags are shown before sending.
  if (!opts.reviewed && !opts.auto && typeof shouldCheckTags === "function" && shouldCheckTags()) {
    startTagCheck(message);
    return;
  }
  if (typeof closeTagCheck === "function") closeTagCheck();

  // Browser audio must be initialized during a direct user gesture.
  if (speakEnabled()) ensureAudioContext();

  messageInput.value = "";
  if (typeof tagIdeasState === "object" && tagIdeasState) clearTagIdeas();   // NEW (1.5.0)
  cancelAutoSend();
  setTypedByHand(false);   // NEW (1.5.0): the next message is back to auto-send
  beginReplyTyping();      // NEW (1.5.0): dots stay up until the chatbox message goes out
  // Start a fresh dictation utterance after sending.
  resetLiveDictation();
  // Open the VRChat microphone now rather than when the reply plays: the
  // tap takes a moment to land and be confirmed, and the reply is seconds
  // away. Deliberately not awaited — nothing about sending should wait on
  // VRChat, and a failure here is reported in FrivOSC's own log.
  requestVrchatUnmute();
  if (typeof reportTagTaste === "function") reportTagTaste(message);   // NEW (1.5.0)
  addTurn("You", message);
  showTypingBubble();
  setStatus("Generating…");
  setLamp("busy");
  sendBtn.disabled = true;
  // NEW (1.5.0): set when a voice is coming — the chatbox message waits for
  // it to start playing, and so do the dots.
  let replyAudioComing = false;
  // NEW (1.5.0): set once the reply has been handed to the chatbox, whose
  // own send takes the dots down when it is queued.
  let chatboxHandled = false;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        session_id: sessionId,
        profile_id: currentProfileId || null,
        max_words: parseInt(lengthSlider.value, 10),
        language: currentLanguage,
        speak: speakEnabled(),
        // NEW (1.5.0). CHANGED (1.5.0): not again for a message whose tags you checked.
        auto_tags: !opts.reviewed && typeof autoTagsOn === "function" ? autoTagsOn() : false,
      }),
    });
    const data = await res.json();

    if (!res.ok) {
      // Nothing is coming, so the dots would sit there for good.
      removeTypingBubble();
      setStatus(data.error, true);
      setLamp("ready");
      return;
    }

    const active = allProfiles.find((p) => p.id === currentProfileId);
    const speaker = active ? active.name : "Voice";
    let streamSave = null;   // NEW (1.5.0): the Save data, finished once a stream is
    // NEW (1.5.0): ElevenLabs refused the tags model, and what was used instead.
    if (data.voice_notice) setStatus(data.voice_notice, true);

    // NEW (1.5.0): a spoken reply too long for one chatbox page goes a page
    // at a time, each one as the voice reaches it. An app.py from before
    // this sends no pages and gets the old behaviour.
    // CHANGED (1.5.0): with dots under the reply that tick along as each
    // page goes to the chatbox.
    const pager = data.audio_url && Array.isArray(data.chatbox_pages) && data.chatbox_pages.length > 1
      && oscEnabled() && typeof makeChatboxPager === "function"
      ? makeChatboxPager(data.chatbox_pages.length)
      : null;
    const follower = data.audio_url && Array.isArray(data.chatbox_pages) && data.chatbox_pages.length > 1
      ? makeChatboxFollower(data.chatbox_pages, pager ? (i) => pager.show(i) : null)
      : null;

    addTurn(speaker, data.reply, {
      audioUrl: data.audio_url,
      wordCount: data.word_count,
      charCount: data.char_count,
      targetWords: data.target_words,
      language: data.language,
      english: data.english,
      condensed: data.condensed,
      repaired: data.repaired,
      keptExact: data.kept_exact,  // NEW (1.5.0)
      ruleCleanup: data.rule_cleanup,  // NEW (1.6.0): no AI, Frivo's rules
      ruleCleanupReason: data.rule_cleanup_reason || "",
      voiceEngineName: data.voice_engine_name,  // NEW (1.5.0)
      textEngineName: data.text_engine_name || (data.text_seconds ? "" : "No AI"),  // NEW (1.5.0)
      voiceEngine: data.voice_engine,  // NEW (1.5.0)
      wordTimes: data.word_times,  // NEW (1.5.0): exact word timings, or null
      voiced: data.voiced && data.voiced !== data.reply ? data.voiced : undefined,  // NEW (1.5.0): with its voice tags
      autoTagged: data.auto_tagged === true,   // NEW (1.5.0)
      tagShaped: data.tag_shaped === true,     // NEW (1.5.0)
      voiceHow: data.voice_how || "",   // NEW (1.5.0)
      profileId: currentProfileId || "",   // NEW (1.5.0): for Retake
      footer: pager ? pager.el : null,  // NEW (1.5.0)
      // NEW (1.5.0): a streamed reply. When ElevenLabs is done: the chatbox
      // pages get their exact times, Save gets the finished file, and the
      // credits are counted.
      stream: data.stream || null,
      onStreamTiming: data.stream ? (t) => {
        if (Array.isArray(t.page_ends) && Array.isArray(data.chatbox_pages) && t.page_ends.length === data.chatbox_pages.length) {
          data.chatbox_pages.forEach((page, i) => { page.at = i === 0 ? 0 : t.page_ends[i - 1]; });
        }
        if (streamSave && t.audio_url) {
          streamSave.audio_url = t.audio_url;
          streamSave.word_times = t.word_times;
          streamSave.chatbox_pages = data.chatbox_pages;
          if (typeof persistTranscript === "function") persistTranscript();
        }
        if (typeof loadCredits === "function") loadCredits({ force: true });
      } : null,
      // NEW (1.5.0): what the Save button keeps, so it can be played again.
      saveData: data.audio_url ? (streamSave = {
        audio_url: data.audio_url,
        text: data.reply,
        voiced: data.voiced || data.reply,   // NEW (1.5.0)
        english: data.english,
        language: data.language,
        voice_name: typeof activeVoiceName === "function" ? activeVoiceName() : "",
        voice_engine: data.voice_engine,
        voice_engine_name: data.voice_engine_name,
        voice_how: data.voice_how || "",   // NEW (1.5.0): which settings spoke it
        word_times: data.word_times,
        chatbox_pages: data.chatbox_pages,
        profile_id: currentProfileId || "",
        profile_name: speaker,
      }) : null,
      credits: data.credits,  // NEW (1.5.0): what was actually billed
      spoke: data.spoke,
      totalSeconds: data.total_seconds,
      textSeconds: data.text_seconds,
      audioSeconds: data.audio_seconds,
      // Send the spoken reply to OSC when audio playback begins. Checking the
      // current toggle here honors changes made while the reply was generated.
      onAudioStart: () => {
        if (!oscEnabled()) endReplyTyping();
        else if (!follower) sendToChatbox(data.reply, { speaking: true });   // CHANGED (1.5.0)
      },
      // NEW (1.5.0): the follower sends page 1 when the voice starts.
      onPlayback: follower ? (playing, offset, dur) => follower.update(playing, offset, dur) : null,
    });
    replyAudioComing = Boolean(data.audio_url);

    if (!data.audio_url && oscEnabled()) {
      chatboxHandled = true;   // NEW (1.5.0)
      sendToChatbox(data.reply, { speaking: false });
    }

    // Falls back to char_count for an app.py that predates the split.
    // They're the same number whenever a reply was actually spoken.
    addCredits(data.credits != null ? data.credits : data.char_count);
    // Only worth a round trip when something was actually spent — a
    // text-only reply can't have changed the balance.
    if (data.audio_url) loadCredits({ force: true });
    setStatus(data.audio_url ? "Ready." : "Ready — text only, no credits used.");
    setLamp("ready");
  } catch (err) {
    removeTypingBubble();
    setStatus(`Request failed: ${err.message}`, true);
    setLamp("ready");
    endReplyTyping();   // NEW (1.5.0): nothing is coming
  } finally {
    sendBtn.disabled = false;
    messageInput.focus();
    // NEW (1.5.0): every way out of a send that leaves no voice to wait for
    // and nothing handed to the chatbox — an error reply, a failed request,
    // the chatbox switched off — takes the dots down here. Covers the early
    // return on a server error, which is not an exception and skips catch.
    if (!replyAudioComing && !chatboxHandled) endReplyTyping();
  }
}

sendBtn.addEventListener("click", () => send());
// CHANGED (1.5.0): the box is several lines now. Enter sends, Shift+Enter
// starts a new line, and Enter while picking an accented letter (an IME)
// is left to the IME.
messageInput.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
  e.preventDefault();
  send();
});

// ---------- Init ----------

(async function init() {
  reportMissingElements();

  const initialVolume = clampVolumePct(localStorage.getItem("voice_console_volume"));
  masterVolumeSlider.value = initialVolume;
  masterVolumeValue.textContent = `${initialVolume}%`;
  updateFaderReadout();

  // Each step runs independently. Previously a single failing request took
  // down the whole init chain, leaving the page looking loaded but with
  // nothing populated and no indication of why.
  try {
    await loadSettings();
  } catch (err) {
    console.error("loadSettings failed:", err);
    setStatus("Couldn't load settings from the server. Is app.py running and up to date?", true);
  }

  try {
    await loadVoices();
  } catch (err) {
    console.error("loadVoices failed:", err);
  }

  // Not awaited — the balance is nice to have, and blocking the rest of
  // init on an upstream API would mean a slow ElevenLabs response delays
  // the profiles and the microphone list too.
  loadCredits();
  startCreditsPolling();

  try {
    await loadProfiles();
  } catch (err) {
    console.error("loadProfiles failed:", err);
    setStatus("Couldn't load profiles from the server.", true);
  }

  try {
    await loadMicrophones();
  } catch (err) {
    console.error("loadMicrophones failed:", err);
  }

  try {
    buildDictationModeUI();
    fillDictationLanguages();
  } catch (err) {
    console.error("buildDictationModeUI failed:", err);
  }

  try {
    startLocalStatusPolling();
  } catch (err) {
    console.error("startLocalStatusPolling failed:", err);
  }

  try {
    startFrivoscPolling();
  } catch (err) {
    console.error("startFrivoscPolling failed:", err);
  }

  setLamp("ready");
  if (!statusEl.textContent || statusEl.textContent === "") setStatus("Ready.");
})();



const THEME_KEY = "voice_console_theme";
const themeToggle = $("themeToggle");

function applyTheme(name) {
  const theme = name === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  if (themeToggle) themeToggle.checked = theme === "dark";
  try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* private mode */ }
  // Colours may cross-fade from here on. Not before: the class is added
  // after the first paint so the initial render can't animate into place.
  document.documentElement.classList.add("theme-ready");
  // The voice list is positioned against the viewport and can be open.
  if (typeof closeVoicePop === "function") closeVoicePop();
}

if (themeToggle) {
  themeToggle.checked = document.documentElement.dataset.theme !== "light";
  themeToggle.addEventListener("change", () => {
    applyTheme(themeToggle.checked ? "dark" : "light");
  });
}
requestAnimationFrame(() => document.documentElement.classList.add("theme-ready"));


// ---------- Overflow menu ----------
// Secondary workspace controls are grouped in the overflow menu.

const moreBtn = $("moreBtn");
const morePop = $("morePop");

function closeMorePop() {
  if (!morePop) return;
  morePop.classList.add("is-hidden");
  if (moreBtn) moreBtn.setAttribute("aria-expanded", "false");
}

if (moreBtn && morePop) {
  moreBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const opening = morePop.classList.contains("is-hidden");
    morePop.classList.toggle("is-hidden", !opening);
    moreBtn.setAttribute("aria-expanded", opening ? "true" : "false");
  });

  // Item handlers run normally; this closes the menu afterwards.
  morePop.addEventListener("click", () => closeMorePop());

  document.addEventListener("click", (e) => {
    if (morePop.classList.contains("is-hidden")) return;
    if (!morePop.contains(e.target) && e.target !== moreBtn) closeMorePop();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeMorePop();
  });
}


// ---------- Composer options ----------
// Composer options are remembered as a workspace preference.

const COMPOSER_OPTS_KEY = "voice_console_composer_options";
const composerMoreBtn = $("composerMoreBtn");
const composerToggles = $("composerToggles");

function applyComposerOptions(open) {
  if (composerToggles) composerToggles.classList.toggle("is-hidden", !open);
  if (composerMoreBtn) {
    composerMoreBtn.setAttribute("aria-expanded", open ? "true" : "false");
    composerMoreBtn.title = open
      ? "Hide the Speak and Chatbox switches"
      : "Show the Speak and Chatbox switches";
  }
  try { localStorage.setItem(COMPOSER_OPTS_KEY, open ? "1" : "0"); } catch (e) { /* private mode */ }
}

if (composerMoreBtn && composerToggles) {
  applyComposerOptions(localStorage.getItem(COMPOSER_OPTS_KEY) !== "0");
  composerMoreBtn.addEventListener("click", () => {
    applyComposerOptions(composerToggles.classList.contains("is-hidden"));
  });
}



const LISTEN_OPEN_KEY = "voice_console_listen_open";

if (listenPanel) {
  const savedOpen = localStorage.getItem(LISTEN_OPEN_KEY);
  // CHANGED (2.0): a drawer, closed until you open it — a third of the
  // screen saying "Nothing heard yet" was the old layout's biggest cost.
  const listenOpen = savedOpen === "1";
  listenPanel.classList.toggle("is-hidden", !listenOpen);
  if (listenToggle) listenToggle.classList.toggle("is-active", listenOpen);
}

if (listenToggle && listenPanel) {
  // Registered after the handler that does the toggling, so by the time
  // this runs the class already reflects the new state.
  listenToggle.addEventListener("click", () => {
    localStorage.setItem(
      LISTEN_OPEN_KEY,
      listenPanel.classList.contains("is-hidden") ? "0" : "1"
    );
  });
}



let openPrettySelect = null;

function closePrettySelect() {
  if (!openPrettySelect) return;
  const { pop, trigger } = openPrettySelect;
  pop.classList.add("is-hidden");
  trigger.setAttribute("aria-expanded", "false");
  openPrettySelect = null;
}

function wireSelectValueSync(select, onChange) {
  const desc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
  if (!desc || !desc.set || !desc.get) return;
  Object.defineProperty(select, "value", {
    configurable: true,
    enumerable: desc.enumerable,
    get() { return desc.get.call(select); },
    set(v) {
      desc.set.call(select, v);
      onChange();
    },
  });
}

function buildPrettySelect(select) {
  if (select.dataset.prettySelect === "1") return;
  select.dataset.prettySelect = "1";

  // The sidebar's Profile and Language pickers read as a title rather than
  // a form field on the mockup this app is built from — same borderless,
  // larger-type treatment here.
  const plain = select.classList.contains("side-pick");

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "pretty-select-trigger" + (plain ? " pretty-select-trigger--plain" : "");
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-expanded", "false");
  if (select.id) trigger.id = `${select.id}__trigger`;

  const label = document.createElement("span");
  label.className = "pretty-select-trigger-label";
  trigger.appendChild(label);
  if (!plain) {
    const caret = document.createElement("span");
    caret.className = "voice-caret";
    caret.setAttribute("aria-hidden", "true");
    trigger.appendChild(caret);
  }

  select.insertAdjacentElement("afterend", trigger);
  select.style.display = "none";
  select.tabIndex = -1;

  // A <label for="micSelect"> would otherwise click-focus a hidden,
  // unfocusable element and do nothing.
  if (select.id) {
    document.querySelectorAll(`label[for="${select.id}"]`).forEach((l) => {
      l.setAttribute("for", trigger.id);
    });
  }

  const pop = document.createElement("div");
  pop.className = "pretty-select-pop is-hidden";
  // The popover lives on <body>, so anything the source select's styling
  // implied has to be carried over explicitly rather than inherited.
  if (select.classList.contains("filter-select")) pop.classList.add("pretty-select-pop--caps");
  pop.setAttribute("role", "listbox");
  if (select.id) pop.setAttribute("aria-label", select.getAttribute("aria-label") || select.id);
  const list = document.createElement("div");
  list.className = "pretty-select-list";
  pop.appendChild(list);
  document.body.appendChild(pop);

  function selectedOption() {
    return select.options[select.selectedIndex] || null;
  }

  function syncTrigger() {
    const opt = selectedOption();
    label.textContent = opt ? opt.textContent : "";
    trigger.disabled = select.disabled;
    trigger.title = select.title || "";
  }

  function rowFor(opt) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "pretty-select-option";
    row.setAttribute("role", "option");
    row.textContent = opt.textContent;
    row.disabled = opt.disabled;
    if (opt === selectedOption()) {
      row.classList.add("is-selected");
      row.setAttribute("aria-selected", "true");
    }
    row.addEventListener("click", () => {
      select.value = opt.value;
      select.dispatchEvent(new Event("input", { bubbles: true }));
      select.dispatchEvent(new Event("change", { bubbles: true }));
      closePrettySelect();
      trigger.focus();
    });
    return row;
  }

  function renderRows() {
    list.innerHTML = "";
    if (!select.options.length) {
      const empty = document.createElement("p");
      empty.className = "pretty-select-empty";
      empty.textContent = "Nothing to choose yet.";
      list.appendChild(empty);
      return;
    }
    Array.from(select.children).forEach((child) => {
      if (child.tagName === "OPTGROUP") {
        const heading = document.createElement("div");
        heading.className = "pretty-select-group";
        heading.textContent = child.label;
        list.appendChild(heading);
        Array.from(child.children).forEach((opt) => list.appendChild(rowFor(opt)));
      } else if (child.tagName === "OPTION") {
        list.appendChild(rowFor(child));
      }
    });
  }

  // Fixed positioning, measured against the trigger — the same approach as
  // the voice popover, including the flip when there's more room above.
  function position() {
    const rect = trigger.getBoundingClientRect();
    const margin = 10;
    const width = Math.max(rect.width, 200);
    const roomBelow = window.innerHeight - rect.bottom - margin;
    const roomAbove = rect.top - margin;
    const dropDown = roomBelow >= 160 || roomBelow >= roomAbove;
    pop.style.width = `${width}px`;
    pop.style.maxHeight = `${Math.max(160, Math.min(360, dropDown ? roomBelow : roomAbove))}px`;
    pop.style.left = `${Math.max(margin, Math.min(rect.left, window.innerWidth - width - margin))}px`;
    if (dropDown) {
      pop.style.top = `${rect.bottom + 6}px`;
      pop.style.bottom = "auto";
    } else {
      pop.style.top = "auto";
      pop.style.bottom = `${window.innerHeight - rect.top + 6}px`;
    }
  }

  function openPrettySelectPop() {
    if (trigger.disabled) return;
    closePrettySelect();
    renderRows();
    pop.classList.remove("is-hidden");
    trigger.setAttribute("aria-expanded", "true");
    position();
    if (typeof growFrom === "function") growFrom(pop, trigger);   // NEW (1.5.0)
    openPrettySelect = { pop, trigger, close: closePrettySelect };
    requestAnimationFrame(() => {
      const target = list.querySelector(".pretty-select-option.is-selected")
        || list.querySelector(".pretty-select-option");
      if (target) target.focus();
    });
  }

  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    if (pop.classList.contains("is-hidden")) openPrettySelectPop();
    else closePrettySelect();
  });

  pop.addEventListener("keydown", (e) => {
    const rows = Array.from(list.querySelectorAll(".pretty-select-option:not(:disabled)"));
    const i = rows.indexOf(document.activeElement);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      (rows[i + 1] || rows[0])?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      (rows[i - 1] || rows[rows.length - 1])?.focus();
    } else if (e.key === "Escape") {
      e.preventDefault();
      closePrettySelect();
      trigger.focus();
    }
  });

  // Catches everything that repopulates the select or moves its selection
  // via option.selected instead of select.value — fillOptionList and the
  // per-feature loaders throughout this file both do this.
  new MutationObserver(() => {
    syncTrigger();
    if (!pop.classList.contains("is-hidden")) renderRows();
  }).observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ["disabled"] });

  wireSelectValueSync(select, syncTrigger);
  syncTrigger();
}

document.querySelectorAll("select:not(#languageSelect)").forEach(buildPrettySelect);

document.addEventListener("click", (e) => {
  if (!openPrettySelect) return;
  const { pop, trigger } = openPrettySelect;
  if (pop.contains(e.target) || trigger.contains(e.target)) return;
  closePrettySelect();
});
window.addEventListener("resize", () => {
  if (openPrettySelect) closePrettySelect();
});
document.addEventListener(
  "scroll",
  (e) => {
    if (!openPrettySelect) return;
    // Focusing the selected option can scroll the document, especially for
    // a picker near the bottom of a settings page. That is not an outside
    // interaction, and closing here made the list vanish before its option
    // could be clicked. Only close when the trigger itself is moved by a
    // scroll container; scrolling inside the list remains available.
    const { pop, trigger } = openPrettySelect;
    if (pop.contains(e.target) || e.target === document || e.target === document.documentElement || e.target === document.body) return;
    if (e.target.contains && e.target.contains(trigger)) closePrettySelect();
  },
  true
);



const settingsRoot = $("settingsRoot");
const settingsPages = $("settingsPages");
const settingsTitle = $("settingsTitle");
const settingsScroll = $("settingsScroll");

let openSettingsPageEl = null;

function settingsPageIsOpen() {
  return Boolean(openSettingsPageEl);
}

function closeSettingsPage() {
  if (!openSettingsPageEl) return;
  openSettingsPageEl.classList.add("is-hidden");
  openSettingsPageEl = null;
  if (settingsRoot) {
    settingsRoot.classList.remove("is-hidden");
    // NEW (1.5.0): going back, the list slides in from the left.
    if (typeof popOnce === "function") {
      settingsRoot.classList.remove("is-popping");
      void settingsRoot.offsetWidth;
      settingsRoot.classList.add("is-returning");
      settingsRoot.addEventListener("animationend", () => settingsRoot.classList.remove("is-returning"), { once: true });
    }
  }
  if (settingsTitle) settingsTitle.textContent = "Settings";
  if (settingsScroll) settingsScroll.scrollTop = 0;
  refreshSettingsSummaries();
}

function openSettingsPage(name) {
  if (!settingsPages) return;
  const page = settingsPages.querySelector(`.settings-page[data-page="${name}"]`);
  if (!page) return;
  if (openSettingsPageEl) openSettingsPageEl.classList.add("is-hidden");
  if (settingsRoot) settingsRoot.classList.add("is-hidden");
  page.classList.remove("is-hidden");
  openSettingsPageEl = page;
  if (settingsTitle) settingsTitle.textContent = page.dataset.title || "Settings";
  if (settingsScroll) settingsScroll.scrollTop = 0;
}

// One Back button per page, built rather than written eight times.
if (settingsPages) {
  settingsPages.querySelectorAll(".settings-page").forEach((page) => {
    const back = document.createElement("button");
    back.type = "button";
    back.className = "settings-back";
    back.innerHTML =
      '<svg class="icon-16" aria-hidden="true"><use href="#i-chevron"/></svg> Settings';
    back.addEventListener("click", closeSettingsPage);
    page.insertBefore(back, page.firstChild);
  });
}

if (settingsRoot) {
  settingsRoot.addEventListener("click", (e) => {
    const row = e.target.closest("[data-settings-page]");
    if (row) openSettingsPage(row.dataset.settingsPage);
  });
}

const settingsVoiceRow = $("settingsVoiceRow");
if (settingsVoiceRow) {
  settingsVoiceRow.addEventListener("click", () => {
    if (voiceTrigger) voiceTrigger.click();
  });
}


function mirrorRange(a, b, onChange) {
  if (!a || !b) return;
  const sync = (from, to) => {
    if (to.value !== from.value) to.value = from.value;
    if (typeof onChange === "function") onChange();
  };
  a.addEventListener("input", () => sync(a, b));
  b.addEventListener("input", () => sync(b, a));
}

const settingsVolumeSlider = $("settingsVolumeSlider");
const settingsVolumeValue = $("settingsVolumeValue");

function showVolumeEverywhere() {
  const pct = clampVolumePct(masterVolumeSlider.value);
  masterVolumeValue.textContent = `${pct}%`;
  if (settingsVolumeValue) settingsVolumeValue.textContent = `${pct}%`;
  setMasterVolume(pct);
}
mirrorRange(masterVolumeSlider, settingsVolumeSlider, showVolumeEverywhere);

const settingsLengthSlider = $("settingsLengthSlider");
mirrorRange(lengthSlider, settingsLengthSlider, () => {
  updateFaderReadout();
  refreshSettingsSummaries();
});


const speakingSpeedSlider = $("speakingSpeedSlider");
const speakingSpeedValue = $("speakingSpeedValue");
const temperatureSlider = $("temperatureSlider");
const temperatureValue = $("temperatureValue");
const maxTokensAutoToggle = $("maxTokensAutoToggle");
const maxTokensInput = $("maxTokensInput");
const maxTokensManual = $("maxTokensManual");

function showSpeakingSpeed() {
  if (!speakingSpeedSlider || !speakingSpeedValue) return;
  speakingSpeedValue.textContent = `${parseInt(speakingSpeedSlider.value, 10)}%`;
}
if (speakingSpeedSlider) speakingSpeedSlider.addEventListener("input", showSpeakingSpeed);

function showTemperature() {
  if (!temperatureSlider || !temperatureValue) return;
  temperatureValue.textContent = (parseInt(temperatureSlider.value, 10) / 100).toFixed(2);
}
if (temperatureSlider) temperatureSlider.addEventListener("input", showTemperature);

// 0 is the wire format for "work it out from the reply length", which is
// what this app did before the setting existed.
function readMaxTokensSetting() {
  if (!maxTokensAutoToggle || maxTokensAutoToggle.checked) return 0;
  const n = parseInt(maxTokensInput ? maxTokensInput.value : "", 10);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

function showMaxTokensState() {
  const auto = !maxTokensAutoToggle || maxTokensAutoToggle.checked;
  if (maxTokensManual) maxTokensManual.classList.toggle("is-hidden", auto);
  refreshSettingsSummaries();
}
if (maxTokensAutoToggle) maxTokensAutoToggle.addEventListener("change", showMaxTokensState);
if (maxTokensInput) maxTokensInput.addEventListener("input", refreshSettingsSummaries);

// The masked key readouts on the two API-key rows.
const openaiKeyMask = $("openaiKeyMask");
const elevenKeyMask = $("elevenKeyMask");
const openaiStatusText = $("openaiStatusText");
const elevenStatusText = $("elevenStatusText");

// Called from loadSettings() with the server's reply.
function applyServerTuning(data) {
  if (speakingSpeedSlider && data.speaking_speed != null) {
    speakingSpeedSlider.value = Math.round(Number(data.speaking_speed) * 100);
  }
  showSpeakingSpeed();

  if (temperatureSlider && data.temperature != null) {
    temperatureSlider.value = Math.round(Number(data.temperature) * 100);
  }
  showTemperature();

  const ceiling = Number(data.max_tokens || 0);
  if (maxTokensAutoToggle) maxTokensAutoToggle.checked = !ceiling;
  if (maxTokensInput && ceiling) maxTokensInput.value = ceiling;
  showMaxTokensState();

  if (settingsVolumeSlider) settingsVolumeSlider.value = masterVolumeSlider.value;
  if (settingsLengthSlider) settingsLengthSlider.value = lengthSlider.value;
  if (settingsVolumeValue) {
    settingsVolumeValue.textContent = `${clampVolumePct(masterVolumeSlider.value)}%`;
  }

  if (openaiKeyMask) {
    openaiKeyMask.textContent = data.openai_key_set ? "••••••••••••••••" : "";
  }
  if (elevenKeyMask) {
    elevenKeyMask.textContent = data.elevenlabs_key_set ? "••••••••••••••••" : "";
  }
  // The lamp and its word are one statement, so they're set together here
  // rather than the lamp being left to a different function that might not
  // have run yet.
  if (openaiStatusText) {
    openaiStatusText.textContent = data.openai_key_set ? "Connected" : "Not set";
  }
  if (elevenStatusText) {
    // CHANGED (1.5.0): "Saved" until the key has actually been tried.
    elevenStatusText.textContent = data.elevenlabs_key_set ? "Checking…" : "Not set";
    if (data.elevenlabs_key_set && typeof checkElevenKey === "function") checkElevenKey();
  }
  if (openaiStatus) openaiStatus.classList.toggle("is-lit", Boolean(data.openai_key_set));
  if (elevenStatus) elevenStatus.classList.toggle("is-lit", Boolean(data.elevenlabs_key_set));

  refreshSettingsSummaries();
  if (typeof paintAllRanges === "function") paintAllRanges();
}

const themeToggleSettings = $("themeToggleSettings");
if (themeToggleSettings && themeToggle) {
  themeToggleSettings.checked = themeToggle.checked;
  themeToggleSettings.addEventListener("change", () => {
    applyTheme(themeToggleSettings.checked ? "dark" : "light");
  });
  themeToggle.addEventListener("change", () => {
    themeToggleSettings.checked = themeToggle.checked;
  });
}

const composerOptionsToggle = $("composerOptionsToggle");
if (composerOptionsToggle && composerToggles) {
  composerOptionsToggle.checked = !composerToggles.classList.contains("is-hidden");
  composerOptionsToggle.addEventListener("change", () => {
    applyComposerOptions(composerOptionsToggle.checked);
  });
  if (composerMoreBtn) {
    composerMoreBtn.addEventListener("click", () => {
      composerOptionsToggle.checked = !composerToggles.classList.contains("is-hidden");
    });
  }
}

const listenPanelToggle = $("listenPanelToggle");
if (listenPanelToggle && listenPanel) {
  listenPanelToggle.checked = !listenPanel.classList.contains("is-hidden");
  listenPanelToggle.addEventListener("change", () => {
    listenPanel.classList.toggle("is-hidden", !listenPanelToggle.checked);
    if (listenToggle) listenToggle.classList.toggle("is-active", listenPanelToggle.checked);
    localStorage.setItem(LISTEN_OPEN_KEY, listenPanelToggle.checked ? "1" : "0");
  });
  if (listenToggle) {
    listenToggle.addEventListener("click", () => {
      listenPanelToggle.checked = !listenPanel.classList.contains("is-hidden");
    });
  }
}

// ---------- Row summaries ----------
// Every chevron row shows the value of the page behind it, so the list can
// be read without opening anything.

function providerLabel(containerEl, fallback) {
  if (!containerEl) return fallback;
  const checked = containerEl.querySelector("input:checked");
  if (!checked) return fallback;
  const pill = checked.closest(".radio-pill");
  const label = pill ? pill.querySelector(".radio-label") : null;
  return label ? label.textContent.trim() : fallback;
}

function modelLabel(listEl, customEl, fallback) {
  if (!listEl) return fallback;
  const row = listEl.querySelector(".model-row.is-checked");
  if (!row) return fallback;
  const name = row.querySelector(".model-row-name");
  const text = name ? name.textContent.trim() : fallback;
  if (text.toLowerCase().startsWith("custom") && customEl && customEl.value.trim()) {
    return customEl.value.trim();
  }
  return text;
}

function setSummary(id, text) {
  const el = $(id);
  if (el && el.textContent !== text) el.textContent = text;
}

function refreshSettingsSummaries() {
  setSummary(
    "settingsVoiceValue",
    voiceTriggerTags && voiceTriggerTags.textContent
      ? `${voiceTriggerName.textContent} (${voiceTriggerTags.textContent})`
      : (voiceTriggerName ? voiceTriggerName.textContent : "—")
  );
  setSummary("settingsLengthValue", `${lengthSlider.value} words`);
  setSummary("settingsModelValue", modelLabel(textModelList, textModelCustom, "—"));
  setSummary("settingsTranslationModelValue", modelLabel(translationModelList, translationModelCustom, "—"));
  setSummary("settingsTranslationProviderValue", providerLabel(translationProviderRadios, "OpenAI"));

  const ceiling = readMaxTokensSetting();
  setSummary("settingsMaxTokensValue", ceiling ? String(ceiling) : "Auto");

  setSummary("settingsOllamaValue", ollamaUrl && ollamaUrl.value.trim() ? ollamaUrl.value.trim() : "Not set");
  setSummary("settingsWhisperValue", whisperUrl && whisperUrl.value.trim() ? whisperUrl.value.trim() : "Not set");
}

// The summaries are derived from controls that several different code paths
// write to, so rather than finding every one of them, they're recomputed
// whenever the settings page is open and something inside it changed.
if (settingsPanel) {
  settingsPanel.addEventListener("change", refreshSettingsSummaries);
  settingsPanel.addEventListener("input", refreshSettingsSummaries);
}



function paintRange(el) {
  if (!el || el.type !== "range") return;
  const min = parseFloat(el.min) || 0;
  const max = parseFloat(el.max);
  const span = (Number.isFinite(max) ? max : 100) - min;
  const pct = span > 0 ? ((parseFloat(el.value) - min) / span) * 100 : 0;
  el.style.setProperty("--range-pct", Math.max(0, Math.min(100, pct)).toFixed(2));
}

function paintAllRanges() {
  document.querySelectorAll('input[type="range"]').forEach(paintRange);
}

// Covers both the user dragging and any code that sets .value and then
// dispatches input — which is what the mirrored sliders do.
document.addEventListener("input", (e) => paintRange(e.target), true);
document.addEventListener("change", (e) => paintRange(e.target), true);

// Values arriving from the server or from localStorage don't fire events,
// so the tracks are repainted after the settings round trip and once the
// page has settled.
paintAllRanges();
requestAnimationFrame(paintAllRanges);
setTimeout(paintAllRanges, 400);



const languagePop = $("languagePop");
const languageTrigger = $("languageTrigger");
const languageTriggerName = $("languageTriggerName");
const languageSearch = $("languageSearch");
const languageListEl = $("languageList");
const languageFootEl = $("languageFoot");

let languageQuery = "";

function showLanguageTrigger() {
  if (!languageTriggerName) return;
  const match = languages.find((l) => l.name === currentLanguage);
  // CHANGED (1.5.0): just the name ("German"); "German · Deutsch" took the
  // room the voice chip needed. The native spelling is in the tooltip and
  // the language list.
  languageTriggerName.textContent = match ? match.name : currentLanguage;
  if (languageTrigger) {
    languageTrigger.title = match && match.native !== match.name
      ? `${match.name} · ${match.native} — change the reply language`
      : "Change the reply language";
  }
}

function languagePopIsOpen() {
  return languagePop && !languagePop.classList.contains("is-hidden");
}

function matchingLanguages() {
  const q = languageQuery.trim().toLowerCase();
  if (!q) return languages;
  // Name, native spelling and region all match, so "deutsch", "german" and
  // "western" all find the same entry.
  return languages.filter((l) =>
    `${l.name} ${l.native || ""} ${l.region || ""}`.toLowerCase().includes(q)
  );
}

function languageRowNode(l) {
  const isCurrent = l.name === currentLanguage;
  const row = document.createElement("button");
  row.type = "button";
  row.className = "lang-row";
  row.setAttribute("role", "option");
  row.setAttribute("aria-selected", String(isCurrent));
  row.classList.toggle("is-current", isCurrent);

  const name = document.createElement("span");
  name.className = "lang-name";
  name.textContent = l.name;
  row.appendChild(name);

  // Only when it says something the name doesn't.
  if (l.native && l.native !== l.name) {
    const native = document.createElement("span");
    native.className = "lang-native";
    native.textContent = l.native;
    row.appendChild(native);
  } else {
    const spacer = document.createElement("span");
    spacer.className = "lang-native";
    row.appendChild(spacer);
  }

  if (isCurrent) {
    const check = document.createElement("span");
    check.className = "lang-check";
    check.title = "In use";
    check.appendChild(iconNode("i-check", "icon-16"));
    row.appendChild(check);
  }

  row.addEventListener("click", () => {
    setLanguage(l.name);
    closeLanguagePop();
  });
  return row;
}

function renderLanguageList() {
  if (!languageListEl) return;
  languageListEl.innerHTML = "";

  const matches = matchingLanguages();
  if (!matches.length) {
    const note = document.createElement("p");
    note.className = "voice-none";
    note.textContent = "Nothing matches that.";
    languageListEl.appendChild(note);
    if (languageFootEl) languageFootEl.textContent = `0 of ${languages.length}`;
    return;
  }

  // Searching flattens the grouping: with a query the regions are noise,
  // and the two or three hits should be the whole of what's on screen.
  if (languageQuery.trim()) {
    matches.forEach((l) => languageListEl.appendChild(languageRowNode(l)));
  } else {
    const recents = languageRecents().filter((name) =>
      languages.some((l) => l.name === name)
    );
    if (recents.length > 1) {
      languageListEl.appendChild(voiceGroupNode("Recent"));
      recents.forEach((name) => {
        const l = languages.find((x) => x.name === name);
        if (l) languageListEl.appendChild(languageRowNode(l));
      });
    }

    // Regions in the order app.py lists them, not alphabetically — that
    // keeps the languages most people here will want near the top.
    const regions = [];
    languages.forEach((l) => {
      const region = l.region || "All languages";
      if (!regions.includes(region)) regions.push(region);
    });
    regions.forEach((region) => {
      const inRegion = languages.filter((l) => (l.region || "All languages") === region);
      if (!inRegion.length) return;
      languageListEl.appendChild(voiceGroupNode(region));
      inRegion.forEach((l) => languageListEl.appendChild(languageRowNode(l)));
    });
  }

  if (languageFootEl) {
    languageFootEl.textContent =
      matches.length === languages.length
        ? `${languages.length} languages`
        : `${matches.length} of ${languages.length} languages`;
  }
}

function openLanguagePop() {
  if (!languagePop) return;
  languagePop.classList.remove("is-hidden");
  languageTrigger.setAttribute("aria-expanded", "true");
  // Every visit starts from a clean slate rather than resuming last time's
  // search, which is almost never what you want on reopening.
  languageQuery = "";
  if (languageSearch) languageSearch.value = "";
  renderLanguageList();

  // Show where you are rather than the top of the list.
  const current = languageListEl.querySelector(".lang-row.is-current");
  if (current) current.scrollIntoView({ block: "center" });
  if (languageSearch) languageSearch.focus();
}

function closeLanguagePop() {
  if (!languagePop) return;
  languagePop.classList.add("is-hidden");
  languageTrigger.setAttribute("aria-expanded", "false");
}

if (languageTrigger) {
  languageTrigger.addEventListener("click", () => {
    if (languagePopIsOpen()) closeLanguagePop();
    else openLanguagePop();
  });
}

const languageCloseBtn = $("languageCloseBtn");
if (languageCloseBtn) languageCloseBtn.addEventListener("click", closeLanguagePop);

if (languagePop) {
  languagePop.addEventListener("click", (e) => {
    if (e.target === languagePop) closeLanguagePop();
  });
  languagePop.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    e.preventDefault();
    closeLanguagePop();
    languageTrigger.focus();
  });
}

if (languageSearch) {
  languageSearch.addEventListener("input", () => {
    languageQuery = languageSearch.value;
    renderLanguageList();
  });
  // Enter takes the top result — the usual "type a few letters and commit".
  languageSearch.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const first = languageListEl.querySelector(".lang-row");
    if (first) {
      e.preventDefault();
      first.click();
    }
  });
}

showLanguageTrigger();


// Restoring every hidden category at once. There's no per-category undo:
// the list of what's hidden is short, and one button that plainly means
// "put everything back" beats several that each mean a little less.
if (voiceHiddenNote) {
  voiceHiddenNote.addEventListener("click", () => {
    showAllVoiceCategories();
    renderVoiceFilters();
    renderVoiceList();
  });
}



function setGateState(text, open) {
  const el = document.getElementById("listenGateState");
  if (!el) return;
  if (el.textContent !== text) el.textContent = text;
  el.classList.toggle("is-open", Boolean(open));
}

function showGateThreshold() {
  const out = document.getElementById("listenThresholdMiniValue");
  const slider = document.getElementById("listenThresholdMini");
  if (!out || !slider) return;
  out.textContent = slider.value;
}

if (listenThresholdMini) {
  listenThresholdMini.addEventListener("input", showGateThreshold);
}
if (listenThreshold) {
  // The two sliders are two views of one value, so the readout has to
  // follow whichever was moved.
  listenThreshold.addEventListener("input", showGateThreshold);
}
showGateThreshold();
setGateState("Idle", false);


// ============================================================
// NEW (updates): finding, installing and going back
// ============================================================
// The browser side of Frivo's updates, after Clearspace's:
//  - a quiet chip in the sidebar when a newer version is out (the server
//    checks shortly after it starts and every six hours, unless that is off)
//  - the update dialog: what changed, then Update now / Later / Skip this
//    version
//  - Settings > About Frivo: the version, "Check for updates", the
//    automatic-check switch, and Earlier versions, which installs an older
//    release through the same dialog
//
// Installing happens on the PC Frivo runs on, not in this browser. The
// server hands the request to its updater and this page follows along via
// /api/updates/job — including through the restart, when the server goes
// away for a while and comes back as the new version.

const updateChip = $("updateChip");
const updateChipText = $("updateChipText");
const updateOverlay = $("updateOverlay");
const updateTitle = $("updateTitle");
const updateSub = $("updateSub");
const updateNotes = $("updateNotes");
const updateWhere = $("updateWhere");
const updateProgress = $("updateProgress");
const updateProgressBar = $("updateProgressBar");
const updateStatusEl = $("updateStatus");
const updateSkipBtn = $("updateSkipBtn");
const updateLaterBtn = $("updateLaterBtn");
const updateInstallBtn = $("updateInstallBtn");
const aboutVersionValue = $("aboutVersionValue");
const checkUpdatesRow = $("checkUpdatesRow");
const checkUpdatesValue = $("checkUpdatesValue");
const updateAutoToggle = $("updateAutoToggle");
const earlierVersionsRow = $("earlierVersionsRow");
const earlierList = $("earlierList");
const earlierNote = $("earlierNote");

const UPDATE_REFRESH_MS = 15 * 60 * 1000;
const UPDATE_JOB_POLL_MS = 1000;
// The server is gone while setup replaces it. Past this, say so plainly
// rather than spinning for ever.
const UPDATE_RESTART_PATIENCE_MS = 4 * 60 * 1000;
const UPDATE_ACTIVE = new Set(["queued", "starting", "checking", "downloading", "verifying", "installing"]);

let updateInfo = null;            // the last /api/updates answer
let updateDialogRelease = null;   // what the open dialog would install
let updateDialogGoingBack = false;
let updateJob = null;             // { id, target, kind } while an install runs
let updateJobTimer = null;
let updateJobLostAt = 0;          // when the server stopped answering
let updateJobDoneAt = 0;
let checkingForUpdates = false;

function formatMegabytes(bytes) {
  return (bytes / 1048576).toFixed(bytes >= 10 * 1048576 ? 0 : 1);
}

function formatReleaseDate(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

// Release notes are Markdown. Without a Markdown view the readable thing is
// to drop the markup that only means something rendered — heading marks,
// bold and code ticks — and turn list dashes into bullets. Same as
// Clearspace's UpdateWindow.Tidy.
function tidyReleaseNotes(notes) {
  const lines = [];
  String(notes || "").replace(/\r\n/g, "\n").split("\n").forEach((raw) => {
    let line = raw.replace(/\s+$/, "").replace(/\*\*/g, "").replace(/`/g, "");
    const trimmed = line.replace(/^\s+/, "");
    if (trimmed.startsWith("#")) line = trimmed.replace(/^#+/, "").trim();
    else if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      line = line.slice(0, line.length - trimmed.length) + "• " + trimmed.slice(2);
    }
    if (!line && (!lines.length || !lines[lines.length - 1])) return;   // no doubled blank lines
    lines.push(line);
  });
  while (lines.length && !lines[lines.length - 1]) lines.pop();
  return lines.join("\n");
}

function updateIsRunning() {
  return Boolean(updateJob);
}

function renderUpdateChip() {
  if (!updateChip) return;
  if (updateJob) {
    updateChip.classList.remove("is-hidden");
    updateChip.classList.add("is-busy");
    updateChipText.textContent = updateJob.kind === "rollback"
      ? `Going back to ${updateJob.target}…`
      : `Updating to ${updateJob.target}…`;
    return;
  }
  updateChip.classList.remove("is-busy");
  const notify = updateInfo && updateInfo.notify;
  updateChip.classList.toggle("is-hidden", !notify);
  if (notify) updateChipText.textContent = `Update available · ${notify.version}`;
}

function renderAboutSection() {
  if (!updateInfo) return;
  aboutVersionValue.textContent = updateInfo.current || "unknown";
  // CHANGED (2.0)
  const pv = $("statusPillVersion");
  if (pv) {
    pv.textContent = updateInfo.current || "";
    pv.classList.toggle("is-unknown", !updateInfo.current || updateInfo.current === "unknown");
  }
  const nv = $("settingsNavVersion");
  if (nv) nv.textContent = updateInfo.current || "";
  if (updateAutoToggle) updateAutoToggle.checked = Boolean(updateInfo.auto_check);

  let value = "—";
  let accent = false;
  if (checkingForUpdates) value = "Checking…";
  else if (updateInfo.latest) { value = `${updateInfo.latest.version} available`; accent = true; }
  else if (updateInfo.error && !updateInfo.checked_at) value = "Couldn't check";
  else if (updateInfo.checked_at) value = "Up to date";
  checkUpdatesValue.textContent = value;
  checkUpdatesValue.classList.toggle("srow-value--accent", accent);

  if (earlierNote && updateInfo.oldest_rollback) {
    earlierNote.textContent =
      "Going back keeps your settings, profiles and API keys. What was added after that version " +
      "is gone until you update again, which you can do at any time from here. Versions before " +
      `${updateInfo.oldest_rollback} can't update themselves, so they aren't offered.`;
  }
}

async function loadUpdates() {
  try {
    const res = await fetch("/api/updates");
    if (!res.ok) return;
    updateInfo = await res.json();
  } catch (err) {
    return;   // the server is unreachable; its own errors will say so
  }
  // A page opened (or reloaded) while an update it did not start is
  // running still gets to follow it.
  const job = updateInfo.job;
  if (job && UPDATE_ACTIVE.has(job.state) && !updateJob) {
    followUpdateJob({ id: job.id, target: job.target, kind: job.kind || "update" });
  }
  renderUpdateChip();
  renderAboutSection();
}

// ---------- the dialog ----------

function setUpdateButtons({ skip, later, install, installText, laterText }) {
  updateSkipBtn.classList.toggle("is-hidden", !skip);
  updateLaterBtn.classList.toggle("is-hidden", !later);
  updateInstallBtn.classList.toggle("is-hidden", !install);
  if (installText) updateInstallBtn.textContent = installText;
  if (laterText) updateLaterBtn.textContent = laterText;
  updateInstallBtn.disabled = false;
}

function showUpdateStatus(text, { error = false, progress = null } = {}) {
  updateStatusEl.classList.toggle("is-hidden", !text);
  updateStatusEl.classList.toggle("is-error", error);
  updateStatusEl.textContent = text || "";
  if (progress === null) {
    updateProgress.classList.add("is-hidden");
    return;
  }
  updateProgress.classList.remove("is-hidden");
  const indeterminate = progress === "busy";
  updateProgress.classList.toggle("is-indeterminate", indeterminate);
  const pct = indeterminate ? 0 : Math.max(0, Math.min(100, progress * 100));
  updateProgressBar.style.width = indeterminate ? "" : `${pct.toFixed(1)}%`;
  if (indeterminate) updateProgress.removeAttribute("aria-valuenow");
  else updateProgress.setAttribute("aria-valuenow", pct.toFixed(0));
}

function openUpdateDialog(release, { goingBack = false } = {}) {
  updateDialogRelease = release;
  updateDialogGoingBack = goingBack;
  const current = (updateInfo && updateInfo.current) || "this version";
  updateTitle.textContent = updateDialogHeading(release, goingBack);
  updateSub.textContent = goingBack
    ? `You have ${current}. Going back keeps your settings, profiles and API keys. What was added after ` +
      `${release.version} is gone until you update again.`
    : `You have ${current}. Updating keeps your settings, profiles and API keys.`;

  // An old release's notes describe what was new then, which reads as if it
  // were coming — so going back shows none.
  const notes = goingBack ? "" : tidyReleaseNotes(release.notes);
  updateNotes.textContent = notes;
  updateNotes.classList.toggle("is-hidden", !notes);

  const support = (updateInfo && updateInfo.support) || { ok: false, reason: "" };
  let where = "";
  if (!support.ok) where = support.reason;
  else if (support.mode === "elevate") where = support.reason;
  else if (!release.verifiable) {
    where = "GitHub publishes no fingerprint for this release's installer, so it can't be checked " +
            "and won't be installed. Download it from the releases page instead.";
  }
  updateWhere.textContent = where;
  updateWhere.classList.toggle("is-hidden", !where);

  showUpdateStatus("");
  const canInstall = support.ok && release.verifiable;
  setUpdateButtons({
    skip: !goingBack && canInstall,
    later: true,
    laterText: goingBack ? "Cancel" : "Later",
    install: true,
    installText: canInstall
      ? (goingBack ? `Install ${release.version}` : "Update now")
      : "Open releases page",
  });
  if (!goingBack && !canInstall) updateSkipBtn.classList.remove("is-hidden");

  updateOverlay.classList.remove("is-hidden");
  updateInstallBtn.focus();
}

function updateDialogHeading(release, goingBack) {
  return goingBack ? `Go back to Frivo ${release.version}` : `Frivo ${release.version} is available`;
}

function closeUpdateDialog() {
  updateOverlay.classList.add("is-hidden");
}

function updateDialogIsOpen() {
  return !updateOverlay.classList.contains("is-hidden");
}

// Reopens the dialog on whatever is going on: the running install, or the
// release the chip is announcing.
function openUpdateFromChip() {
  if (updateJob) {
    updateOverlay.classList.remove("is-hidden");
    return;
  }
  const notify = updateInfo && updateInfo.notify;
  if (notify) openUpdateDialog(notify);
}

async function installRelease() {
  const release = updateDialogRelease;
  if (!release) return;
  const support = (updateInfo && updateInfo.support) || { ok: false };
  if (!support.ok || !release.verifiable) {
    window.open(release.page_url || (updateInfo && updateInfo.releases_page) || "#", "_blank", "noopener");
    return;
  }

  updateInstallBtn.disabled = true;
  updateSkipBtn.classList.add("is-hidden");
  updateNotes.classList.add("is-hidden");
  showUpdateStatus("Asking the updater…", { progress: "busy" });
  try {
    const res = await fetch("/api/updates/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version: release.version }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "The update couldn't be started.");
    followUpdateJob({ id: data.id, target: data.version, kind: data.kind });
  } catch (err) {
    showUpdateFailure(err.message);
  }
}

function showUpdateFailure(message) {
  if (updateDialogRelease) updateTitle.textContent = updateDialogHeading(updateDialogRelease, updateDialogGoingBack);
  const page = (updateDialogRelease && updateDialogRelease.page_url) ||
               (updateInfo && updateInfo.releases_page) || "";
  showUpdateStatus(
    `${updateDialogGoingBack ? "That version" : "The update"} couldn't be installed: ${message}` +
      (page ? " You can also download it yourself from Frivo's releases page on GitHub." : ""),
    { error: true }
  );
  setUpdateButtons({ skip: false, later: true, laterText: "Close", install: true, installText: "Try again" });
}

// ---------- following an install ----------

function followUpdateJob(job) {
  updateJob = job;
  updateTitle.textContent = job.kind === "rollback"
    ? `Going back to Frivo ${job.target}`
    : `Updating to Frivo ${job.target}`;
  updateJobLostAt = 0;
  updateJobDoneAt = 0;
  // The buttons that make sense while it runs: hide the dialog. The update
  // carries on without it — it is happening on the server, not here.
  setUpdateButtons({ skip: false, later: true, laterText: "Hide", install: false });
  renderUpdateChip();
  clearInterval(updateJobTimer);
  updateJobTimer = setInterval(pollUpdateJob, UPDATE_JOB_POLL_MS);
  pollUpdateJob();
}

function stopFollowingUpdate() {
  clearInterval(updateJobTimer);
  updateJobTimer = null;
  updateJob = null;
  renderUpdateChip();
}

function describeUpdateJob(job) {
  const target = updateJob ? updateJob.target : job.target;
  switch (job.state) {
    case "queued":
    case "starting":
      return { text: job.mode === "elevate"
        ? "Waiting for permission on the PC Frivo runs on…"
        : "Starting the updater…", progress: "busy" };
    case "checking":
      return { text: `Looking up Frivo ${target} on GitHub…`, progress: "busy" };
    case "downloading":
      if (job.total > 0) {
        return {
          text: `Downloading… ${formatMegabytes(job.received || 0)} of ${formatMegabytes(job.total)} MB`,
          progress: (job.received || 0) / job.total,
        };
      }
      return { text: "Downloading…", progress: "busy" };
    case "verifying":
      return { text: "Checking the download against GitHub's fingerprint…", progress: "busy" };
    case "installing":
      return { text: "Installing. Frivo restarts in a moment, and this page reconnects by itself.",
               progress: "busy" };
    default:
      return { text: job.message || "", progress: "busy" };
  }
}

async function pollUpdateJob() {
  if (!updateJob) return;
  let data = null;
  try {
    const res = await fetch("/api/updates/job", { cache: "no-store" });
    if (res.ok) data = await res.json();
  } catch (err) {
    data = null;
  }

  // Unreachable: setup has stopped the server. Expected during an install;
  // only worth a different message if it goes on far too long.
  if (!data) {
    if (!updateJobLostAt) updateJobLostAt = Date.now();
    const away = Date.now() - updateJobLostAt;
    showUpdateStatus(
      away > UPDATE_RESTART_PATIENCE_MS
        ? "Frivo hasn't come back yet. Check the PC it runs on — its tray icon says what happened."
        : "Frivo is restarting…",
      { progress: "busy" }
    );
    return;
  }
  updateJobLostAt = 0;

  // Landed: the server answering is the new version. Reload, because every
  // file this page was built from has just been replaced.
  if (data.current === updateJob.target) {
    showUpdateStatus(`Frivo ${updateJob.target} is installed. Reloading…`, { progress: 1 });
    clearInterval(updateJobTimer);
    setTimeout(() => window.location.reload(), 1200);
    return;
  }

  const job = data.job;
  if (!job || job.id !== updateJob.id) {
    // The server restarted and has forgotten the request, but is still the
    // old version: wait a little for the restart to finish, then say so.
    if (!updateJobDoneAt) updateJobDoneAt = Date.now();
    if (Date.now() - updateJobDoneAt > 60000) {
      stopFollowingUpdate();
      showUpdateFailure(`Frivo is still running ${data.current}. Its tray icon on the PC it runs on says why.`);
    }
    return;
  }

  if (job.state === "failed") {
    stopFollowingUpdate();
    showUpdateFailure(job.message || "the updater stopped.");
    loadUpdates();
    return;
  }
  if (job.state === "done") {
    // Installed, but the server answering is still the old one — it is
    // about to be replaced. Keep polling until the new one answers.
    if (!updateJobDoneAt) updateJobDoneAt = Date.now();
    showUpdateStatus("Installed. Waiting for Frivo to restart…", { progress: "busy" });
    if (Date.now() - updateJobDoneAt > 90000) {
      stopFollowingUpdate();
      showUpdateFailure(`Frivo ${updateJob.target} was installed, but this page is still talking to ` +
                        `${data.current}. Restart Frivo from its tray icon.`);
    }
    return;
  }
  const view = describeUpdateJob(job);
  showUpdateStatus(view.text, { progress: view.progress });
}

// ---------- Settings > About Frivo ----------

async function checkForUpdatesNow() {
  if (checkingForUpdates) return;
  checkingForUpdates = true;
  renderAboutSection();
  try {
    const res = await fetch("/api/updates/check", { method: "POST" });
    if (!res.ok) throw new Error("check failed");
    updateInfo = await res.json();
  } catch (err) {
    updateInfo = updateInfo || null;
  } finally {
    checkingForUpdates = false;
  }
  renderUpdateChip();
  renderAboutSection();
  if (!updateInfo) return;
  if (updateInfo.latest) {
    // Shown even when this version was skipped earlier: you asked.
    openUpdateDialog(updateInfo.latest);
  } else if (updateInfo.error) {
    setStatus("Frivo couldn't reach GitHub to look for a newer version. Check the internet connection on the PC it runs on.", true);
    checkUpdatesValue.textContent = "Couldn't check";
  } else {
    setStatus(`Frivo ${updateInfo.current} is the newest version.`);
  }
}

async function saveUpdateSettings(patch, toggle) {
  try {
    const res = await fetch("/api/updates/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error("save failed");
    updateInfo = await res.json();
    renderUpdateChip();
    renderAboutSection();
    return true;
  } catch (err) {
    // Put the switch back rather than showing a state the server lacks.
    if (toggle) toggle.checked = !toggle.checked;
    setStatus("Couldn't save that setting.", true);
    return false;
  }
}

function earlierRow(release) {
  const row = document.createElement("div");
  row.className = "srow";
  const main = document.createElement("span");
  main.className = "srow-main srow-main--flex";
  const label = document.createElement("span");
  label.className = "srow-label";
  label.textContent = `Frivo ${release.version}`;
  const sub = document.createElement("span");
  sub.className = "srow-sub";
  const date = formatReleaseDate(release.published);
  sub.textContent = date ? `Released ${date}` : "Release date unknown";
  main.append(label, sub);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn-ghost btn-sm";
  button.textContent = "Install";
  button.addEventListener("click", () => openUpdateDialog(release, { goingBack: true }));
  row.append(main, button);
  return row;
}

function earlierMessage(text) {
  const row = document.createElement("div");
  row.className = "srow";
  const main = document.createElement("span");
  main.className = "srow-main srow-main--flex";
  const sub = document.createElement("span");
  sub.className = "srow-sub";
  sub.textContent = text;
  main.append(sub);
  row.append(main);
  return row;
}

async function loadEarlierVersions() {
  earlierList.replaceChildren(earlierMessage("Loading…"));
  try {
    const res = await fetch("/api/updates/earlier");
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "GitHub couldn't be reached.");
    if (!data.releases || !data.releases.length) {
      earlierList.replaceChildren(earlierMessage(
        `There are no earlier versions to go back to. Versions before ${data.oldest_rollback} ` +
        "can't update themselves, so they aren't offered."
      ));
      return;
    }
    earlierList.replaceChildren(...data.releases.map(earlierRow));
  } catch (err) {
    earlierList.replaceChildren(earlierMessage(`${err.message} Try again in a moment.`));
  }
}

// ---------- wiring ----------

if (updateChip) updateChip.addEventListener("click", openUpdateFromChip);
if (checkUpdatesRow) checkUpdatesRow.addEventListener("click", checkForUpdatesNow);
if (earlierVersionsRow) earlierVersionsRow.addEventListener("click", loadEarlierVersions);
if (updateAutoToggle) {
  updateAutoToggle.addEventListener("change", () => {
    saveUpdateSettings({ auto_check: updateAutoToggle.checked }, updateAutoToggle);
  });
}

updateSkipBtn.addEventListener("click", async () => {
  if (updateDialogRelease) await saveUpdateSettings({ skip: updateDialogRelease.version });
  closeUpdateDialog();
});
updateLaterBtn.addEventListener("click", closeUpdateDialog);
updateInstallBtn.addEventListener("click", installRelease);

if (updateOverlay) {
  updateOverlay.addEventListener("click", (e) => {
    if (e.target === updateOverlay) closeUpdateDialog();
  });
  // First refusal on Escape, before the Settings sheet underneath sees it.
  updateOverlay.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    e.preventDefault();
    e.stopPropagation();
    closeUpdateDialog();
  });
}

loadUpdates();
setInterval(() => { if (!updateJob) loadUpdates(); }, UPDATE_REFRESH_MS);


// ============================================================
// NEW (typing): VRChat's typing dots while you respond
// ============================================================
// The person you're talking to sees "…" over your head while you are
// putting a reply together, the way VRChat's own keyboard shows it. This
// works out whether that is happening and tells Frivo; FrivOSC picks it up
// on its next outbox poll (twice a second) and sends /chatbox/typing.
//
// "Responding" means, with the Chatbox switch on and FrivOSC connected:
//   - Live (Evora): you are talking, or the end of what you said is still
//     being transcribed
//   - Accurate: recording
//   - any mode, or typing: the message box has unsent text that changed in
//     the last few seconds (so a draft left sitting there does not keep the
//     dots up forever)
// Sending clears the box, which clears the dots; the chatbox message itself
// replaces them in VRChat.

const TYPING_CHECK_MS = 250;
// Re-said this often while true. Frivo drops it after 4s without one, so a
// page closed mid-sentence does not leave the dots up.
const TYPING_REFRESH_MS = 2000;
// A box that has not changed for this long is a draft, not a reply in
// progress.
const TYPING_IDLE_MS = 4000;

let typingSent = false;
let typingSentAt = 0;
let typingLastValue = "";
let typingLastChangeAt = 0;

// NEW (1.5.0): from "send" until the reply reaches the chatbox — the
// seconds of thinking, translating and speaking that used to show nothing.
// Capped, so a request that hangs cannot leave the dots up for good.
const REPLY_TYPING_CAP_MS = 30000;
let replyTypingSince = 0;

function beginReplyTyping() {
  replyTypingSince = Date.now();
}

function endReplyTyping() {
  replyTypingSince = 0;
  syncTypingIndicator();
}

function respondingNow() {
  if (!typingIndicatorEnabled || !oscConfigured || !oscEnabled()) return false;
  const now = Date.now();
  if (replyTypingSince && now - replyTypingSince < REPLY_TYPING_CAP_MS) return true;
  if (messageInput.value !== typingLastValue) {
    typingLastValue = messageInput.value;
    typingLastChangeAt = now;
  }
  if (isDictating) {
    if (activeDictationMode === "accurate") return true;
    if (activeDictationMode === "live_local" && liveLocal &&
        (liveLocal.speaking || liveLocal.speculative)) return true;
  }
  return messageInput.value.trim() !== "" && now - typingLastChangeAt < TYPING_IDLE_MS;
}

async function postTyping(on) {
  typingSent = on;
  typingSentAt = Date.now();
  try {
    await fetch("/api/frivosc/typing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ typing: on }),
    });
  } catch (err) {
    // Nothing to do: Frivo forgets an unrefreshed "typing" by itself.
  }
}

function syncTypingIndicator() {
  const want = respondingNow();
  if (want !== typingSent) postTyping(want);
  else if (want && Date.now() - typingSentAt > TYPING_REFRESH_MS) postTyping(true);
}

setInterval(syncTypingIndicator, TYPING_CHECK_MS);
// Closing the tab mid-sentence: say so now rather than after the 4s expiry.
window.addEventListener("pagehide", () => {
  if (!typingSent) return;
  try {
    navigator.sendBeacon("/api/frivosc/typing",
      new Blob([JSON.stringify({ typing: false })], { type: "application/json" }));
  } catch (err) { /* the expiry covers it */ }
});


// ============================================================
// NEW (2.0): the shell — rail, popovers, session strip, settings nav
// ============================================================
//
// Everything above still owns its feature; this is only the new chrome
// around it: the rail buttons call what the old menu called, the chips
// above the message box open the controls the sidebar used to hold, the
// settings list shows one section at a time, and settings save themselves.

(function shell() {
  const railChat = $("railChat");
  const railVoices = $("railVoices");
  const listenCloseBtn = $("listenCloseBtn");
  const messageInputEl = $("messageInput");

  if (railChat) {
    railChat.addEventListener("click", () => {
      if (!settingsPanel.classList.contains("is-hidden")) setSettingsOpen(false);
      if (messageInputEl) messageInputEl.focus();
    });
  }
  if (railVoices && voiceTrigger) railVoices.addEventListener("click", () => voiceTrigger.click());
  if (listenCloseBtn && listenToggle) listenCloseBtn.addEventListener("click", () => listenToggle.click());

  // ---- popovers: one open at a time, closed by a click elsewhere or Escape ----
  const popovers = [
    ["lengthChip", "lengthPop"],
    ["volumeChip", "volumePop"],
    ["oscChip", "oscPop"],
    ["aiChip", "aiPop"],   // NEW (1.5.0)
    ["voiceTagBtn", "voiceTagPop"],   // NEW (1.5.0)
    ["statusPillBtn", "statusPop"],
  ].map(([b, p]) => ({ btn: $(b), pop: $(p) })).filter((x) => x.btn && x.pop);

  window.closeAllPopovers = () => closePopovers(null);
  function closePopovers(except) {
    popovers.forEach(({ btn, pop }) => {
      if (pop === except) return;
      pop.classList.add("is-hidden");
      btn.setAttribute("aria-expanded", "false");
    });
  }
  popovers.forEach(({ btn, pop }) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const opening = pop.classList.contains("is-hidden");
      closePopovers(opening ? pop : null);
      pop.classList.toggle("is-hidden", !opening);
      if (opening && typeof growFrom === "function") growFrom(pop, btn);   // NEW (1.5.0): grow out of the chip
      btn.setAttribute("aria-expanded", opening ? "true" : "false");
      if (opening && pop.id === "lengthPop" && typeof refreshPromptIfOpen === "function") refreshPromptIfOpen();
      if (opening && pop.id === "aiPop" && typeof refreshAiPop === "function") refreshAiPop();   // NEW (1.5.0)
      if (opening && pop.id === "voiceTagPop" && typeof openVoiceTags === "function") openVoiceTags();   // NEW (1.5.0)
    });
    pop.addEventListener("click", (e) => e.stopPropagation());
  });
  document.addEventListener("click", (e) => {
    // A select's popover is on <body>; clicking inside it must not close the chip's popover.
    if (e.target.closest(".pretty-select-pop")) return;
    closePopovers(null);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closePopovers(null);
  });

  // ---- the session strip ----
  const avatar = $("profileAvatar");
  const styleChip = $("styleChip");
  const styleChipText = $("styleChipText");
  const STYLE_NAMES = { reply: "Reply", echo: "Clean up", mimic: "Word for word", flair: "Clean up" };

  window.syncSessionStrip = function syncSessionStrip() {
    const active = typeof activeProfile === "function" ? activeProfile() : null;
    if (avatar) {
      const name = active ? active.name : "Default";
      const letter = (name.trim()[0] || "D").toUpperCase();
      // NEW (1.5.0): the letter pops when the profile changes.
      if (avatar.textContent && avatar.textContent !== letter && typeof popOnce === "function") popOnce(avatar);
      avatar.textContent = letter;
    }
    if (styleChipText) {
      const style = active
        ? (active.response_style || "echo")
        : (typeof responseStyleRadios !== "undefined" ? getRadioValue(responseStyleRadios, "echo") : "echo");
      styleChipText.textContent = STYLE_NAMES[style] || style;
      if (styleChip) {
        styleChip.title = active
          ? `${active.name} replies with ${STYLE_NAMES[style] || style}. Click to edit the profile.`
          : `Replies use ${STYLE_NAMES[style] || style}. Click to change it in Settings.`;
      }
    }
  };
  if (styleChip) {
    styleChip.addEventListener("click", () => {
      const active = typeof activeProfile === "function" ? activeProfile() : null;
      if (active && typeof openModal === "function") {
        openModal(active);
      } else {
        setSettingsOpen(true);
        showSettingsSection("replies");
      }
    });
  }
  if (typeof responseStyleRadios !== "undefined" && responseStyleRadios) {
    responseStyleRadios.addEventListener("change", () => window.syncSessionStrip());
  }
  window.syncSessionStrip();

  // ---- settings: one section at a time ----
  const nav = $("settingsNav");
  const stack = $("settingsRoot");
  const sections = stack ? [...stack.querySelectorAll("[data-settings-section]")] : [];
  const search = $("settingsSearch");
  const noMatch = $("settingsNoMatch");
  let currentSection = "replies";

  window.showSettingsSection = function showSettingsSection(name) {
    currentSection = name;
    if (search && search.value) {
      search.value = "";
      applySearch("");
    }
    if (typeof closeSettingsPage === "function") closeSettingsPage();
    sections.forEach((sec) => sec.classList.toggle("is-shown", sec.dataset.settingsSection === name));
    if (nav) {
      nav.querySelectorAll(".settings-nav-btn").forEach((b) => b.classList.toggle("is-active", b.dataset.settingsSection === name));
    }
    if (settingsScroll) settingsScroll.scrollTop = 0;
  };
  if (nav) {
    nav.addEventListener("click", (e) => {
      const b = e.target.closest("[data-settings-section]");
      if (b) showSettingsSection(b.dataset.settingsSection);
    });
  }

  // A key row's page lives under Accounts; a drill-in from any row keeps
  // its section lit.
  const pageToSection = {
    openai: "accounts", eleven: "accounts", "reply-length": "replies", model: "replies",
    "max-tokens": "replies", "translation-provider": "listening", "translation-model": "listening",
    "earlier-versions": "about",
  };
  if (stack) {
    stack.addEventListener("click", (e) => {
      const row = e.target.closest("[data-settings-page]");
      if (!row) return;
      const sec = pageToSection[row.dataset.settingsPage];
      if (sec && nav) nav.querySelectorAll(".settings-nav-btn").forEach((b) => b.classList.toggle("is-active", b.dataset.settingsSection === sec));
    });
  }

  // ---- settings search: every row whose words match, from every section ----
  function applySearch(q) {
    const query = q.trim().toLowerCase();
    if (!stack) return;
    stack.classList.toggle("is-searching", Boolean(query));
    if (!query) {
      sections.forEach((sec) => {
        sec.classList.toggle("is-shown", sec.dataset.settingsSection === currentSection);
        sec.querySelectorAll(".srow, .settings-section-title, .settings-section-sub").forEach((r) => r.classList.remove("is-hidden"));
      });
      if (noMatch) noMatch.classList.add("is-hidden");
      return;
    }
    if (typeof closeSettingsPage === "function") closeSettingsPage();
    let any = false;
    sections.forEach((sec) => {
      let hit = false;
      sec.querySelectorAll(".srow").forEach((row) => {
        const match = row.textContent.toLowerCase().includes(query);
        row.classList.toggle("is-hidden", !match);
        if (match) hit = true;
      });
      sec.querySelectorAll(".settings-section-sub").forEach((r) => r.classList.add("is-hidden"));
      sec.classList.toggle("is-shown", hit);
      if (hit) any = true;
    });
    if (noMatch) noMatch.classList.toggle("is-hidden", any);
    if (nav) nav.querySelectorAll(".settings-nav-btn").forEach((b) => b.classList.remove("is-active"));
  }
  if (search) search.addEventListener("input", () => applySearch(search.value));

  showSettingsSection("replies");

  // ---- settings save themselves ----
  // Every control inside Settings, except the key fields (sent on purpose
  // with the Save key button) and the ones that already save themselves or
  // are page-only preferences.
  const saved = $("settingsSaved");
  const saveBtn = $("saveSettings");
  const SELF_SAVING = new Set([
    "openaiKey", "elevenKey", "settingsSearch", "themeToggleSettings", "composerOptionsToggle",
    "micSelect", "dictationLangSelect", "listenDeviceSelect", "listenThreshold", "listenSegmentSeconds",
    "listenLiveToggle", "listenSpeakerThreshold", "updateAutoToggle", "responseStyleRadios",
    "personalityPresetSelect", "whisperModelSelect", "settingsVolumeSlider", "settingsLengthSlider",
    "omGetInput",   // NEW (1.5.0): the model manager saves nothing itself
  ]);
  let saveTimer = null;
  let savedTimer = null;
  function flashSaved(ok) {
    if (!saved) return;
    saved.textContent = ok ? "✓ Saved" : "Not saved — try again";
    saved.classList.toggle("is-error", !ok);
    saved.classList.add("is-on");
    clearTimeout(savedTimer);
    savedTimer = setTimeout(() => saved.classList.remove("is-on"), ok ? 1800 : 4000);
  }
  function scheduleSave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      const ok = await saveAllSettings({ quiet: true });
      flashSaved(ok);
    }, 500);
  }
  function wantsAutosave(target) {
    if (!target || !target.id) {
      // A radio pill's input has no id; its group does.
      const group = target && target.closest ? target.closest(".radio-row") : null;
      return group && group.id && !SELF_SAVING.has(group.id) && group.id !== "dictationModeRadios";
    }
    if (SELF_SAVING.has(target.id)) return false;
    if (target.closest("#settingsSearch")) return false;
    return true;
  }
  if (settingsPanel) {
    settingsPanel.addEventListener("change", (e) => {
      if (!wantsAutosave(e.target)) return;
      scheduleSave();
    });
    // Text fields save a moment after you stop typing; sliders as you let go.
    settingsPanel.addEventListener("input", (e) => {
      const t = e.target;
      if (!t || !wantsAutosave(t)) return;
      if (t.matches("textarea, input[type=text], input[type=number]")) scheduleSave();
    });
  }
  // The Save key button appears once a key has been typed.
  const keyInputs = ["openaiKey", "elevenKey"].map((id) => $(id)).filter(Boolean);
  keyInputs.forEach((input) => {
    input.addEventListener("input", () => {
      const any = keyInputs.some((k) => k.value.trim());
      if (saveBtn) saveBtn.classList.toggle("is-hidden", !any);
    });
  });
  if (saveBtn) saveBtn.addEventListener("click", () => setTimeout(() => flashSaved(true), 600));
})();
// ---------------------------------------------------------------------------
// NEW (1.5.0): graphics-card memory graph, in the status popover.
//
// Evora reports the card (how much memory is used, and how much of that is
// Ollama, Evora and everything else); the server keeps the last ten minutes.
// This only asks while the popover is open.
// ---------------------------------------------------------------------------
var GPU_POLL_MS = 2000;
var GPU_GAP_SECONDS = 15;   // a longer gap between readings breaks the graph (Frivo wasn't running)
var GPU_SERIES = [
  { key: "ollama", name: "Ollama" },
  { key: "evora", name: "Evora" },
  { key: "other", name: "Other" },
];
var gpuTimer = null;
var gpuData = null;
var gpuGeometry = null;
var gpuDrawIn = false;   // NEW (1.5.0)

function gpuGb(mb) {
  if (mb == null || isNaN(mb)) return "—";
  return (mb / 1024).toFixed(mb >= 10240 ? 0 : 1) + " GB";
}

function gpuAgo(seconds) {
  if (seconds < 8) return "Now";
  if (seconds < 60) return `${Math.round(seconds)} s ago`;
  return `${Math.round(seconds / 60)} min ago`;
}

function gpuCardName(name) {
  return String(name || "").replace(/^NVIDIA\s+/i, "").replace(/^GeForce\s+/i, "");
}

function gpuSeriesFor(data) {
  // Which bands the card has: Ollama only when it's on this card, Evora
  // only when Windows said how much it uses.
  const parts = (data.card && data.card.parts) || {};
  return GPU_SERIES.filter((s) => {
    if (s.key === "ollama") return data.same_card;
    if (s.key === "evora") return !parts.estimated;
    return true;
  });
}

function gpuSvgEl(tag, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs || {}).forEach(([k, v]) => el.setAttribute(k, v));
  return el;
}

function drawGpuChart(data) {
  const svg = $("gpuSvg");
  const plot = $("gpuPlot");
  if (!svg || !plot) return;
  const width = Math.max(120, Math.round(svg.getBoundingClientRect().width || plot.clientWidth || 300));
  const height = 84;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.replaceChildren();

  const now = data.now || Date.now() / 1000;
  const span = data.history_seconds || 600;
  const points = (data.history || []).filter((p) => p.total);
  const total = (data.card && data.card.total_mb) || Math.max(1, ...points.map((p) => p.total));
  const series = gpuSeriesFor(data);
  const x = (t) => Math.max(0, Math.min(width, width - ((now - t) / span) * width));
  const y = (mb) => height - Math.max(0, Math.min(1, mb / total)) * (height - 2);
  const valueOf = (p, key) => (key === "other" && !series.some((s) => s.key === "evora"))
    ? (p.other || 0) + (p.evora || 0)   // Evora's share unknown: it's inside "Other"
    : (p[key] || 0);

  // Split into runs wherever readings stopped for a while.
  const runs = [];
  points.forEach((p, i) => {
    if (!i || p.t - points[i - 1].t > GPU_GAP_SECONDS) runs.push([]);
    runs[runs.length - 1].push(p);
  });

  svg.append(gpuSvgEl("line", { class: "gpu-cap", x1: 0, x2: width, y1: y(total), y2: y(total) }));

  runs.forEach((run) => {
    const xs = run.map((p) => x(p.t));
    if (run.length === 1) { run = [run[0], run[0]]; xs.unshift(Math.max(0, xs[0] - 3)); }
    let below = run.map(() => 0);
    const tops = [];
    series.forEach((s) => {
      const above = run.map((p, i) => below[i] + valueOf(p, s.key));
      const top = xs.map((px, i) => `${px.toFixed(1)},${y(above[i]).toFixed(1)}`);
      const bottom = xs.map((px, i) => `${px.toFixed(1)},${y(below[i]).toFixed(1)}`).reverse();
      svg.append(gpuSvgEl("polygon", { class: `gpu-band is-${s.key}`, points: top.concat(bottom).join(" ") }));
      tops.push(top);
      below = above;
    });
    // The surface-coloured gap between bands (not above the top one).
    tops.slice(0, -1).forEach((top) => svg.append(gpuSvgEl("polyline", { class: "gpu-gap", points: top.join(" ") })));
  });

  svg.append(gpuSvgEl("line", { class: "gpu-base", x1: 0, x2: width, y1: height - 0.5, y2: height - 0.5 }));
  const cross = gpuSvgEl("line", { class: "gpu-cross", x1: 0, x2: 0, y1: 0, y2: height, visibility: "hidden" });
  svg.append(cross);
  gpuGeometry = { width, points, x, series, valueOf, now, cross, total };
  // NEW (1.5.0): the first draw after opening sweeps in from the left.
  if (gpuDrawIn) {
    gpuDrawIn = false;
    if (svg.animate && !reducedMotion()) {
      svg.animate([{ clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0 0 0)" }],
        { duration: 700, easing: motionEasing("smooth") });
    }
  }

  const card = data.card;
  const parts = card.parts || {};
  const label = series.map((s) => `${s.name} ${gpuGb(valueOf({ ...parts, ollama: parts.ollama_mb, evora: parts.evora_mb, other: parts.other_mb }, s.key))}`).join(", ");
  svg.setAttribute("aria-label",
    `Graphics card memory over the last 10 minutes. Now ${gpuGb(card.used_mb)} of ${gpuGb(card.total_mb)} used: ${label}.`);
}

function gpuHover(event) {
  const g = gpuGeometry;
  const tip = $("gpuTip");
  const svg = $("gpuSvg");
  if (!g || !tip || !svg || !g.points.length) return;
  const box = svg.getBoundingClientRect();
  const px = ((event.clientX - box.left) / box.width) * g.width;
  let nearest = g.points[0];
  g.points.forEach((p) => { if (Math.abs(g.x(p.t) - px) < Math.abs(g.x(nearest.t) - px)) nearest = p; });
  const at = g.x(nearest.t);
  g.cross.setAttribute("x1", at);
  g.cross.setAttribute("x2", at);
  g.cross.setAttribute("visibility", "visible");

  const rows = g.series.slice().reverse().map((s) => {
    const name = s.key === "other" && !g.series.some((x) => x.key === "evora") ? "Other + Evora" : s.name;
    return `<div class="gpu-tip-row"><span class="gpu-swatch is-${s.key}"></span>${name}<b>${gpuGb(g.valueOf(nearest, s.key))}</b></div>`;
  });
  rows.push(`<div class="gpu-tip-row"><span class="gpu-swatch is-free"></span>Free<b>${gpuGb(Math.max(0, (nearest.total || g.total) - (nearest.used || 0)))}</b></div>`);
  tip.innerHTML = `<div class="gpu-tip-when">${gpuAgo(g.now - nearest.t)}</div>${rows.join("")}`;
  tip.classList.remove("is-hidden");
  const left = (at / g.width) * box.width;
  const tipWidth = tip.offsetWidth || 140;
  tip.style.left = `${Math.max(0, Math.min(box.width - tipWidth, left - tipWidth / 2))}px`;
}

function gpuHoverEnd() {
  const tip = $("gpuTip");
  if (tip) tip.classList.add("is-hidden");
  if (gpuGeometry) gpuGeometry.cross.setAttribute("visibility", "hidden");
}

function gpuLegendRow(cls, label, value, note) {
  const li = document.createElement("li");
  const swatch = document.createElement("span");
  swatch.className = `gpu-swatch is-${cls}`;
  const text = document.createElement("span");
  text.className = "gpu-label";
  text.textContent = label;
  if (note) {
    const small = document.createElement("small");
    small.textContent = ` · ${note}`;
    text.append(small);
  }
  const val = document.createElement("span");
  val.className = "gpu-value";
  val.textContent = value;
  li.append(swatch, text, val);
  return li;
}

function ollamaModelNote(models) {
  return models.map((m) => m.name).join(", ");
}

// NEW (1.5.0): how long until Ollama frees the graphics card, from the
// soonest-leaving loaded model. "" when Ollama didn't say.
function gpuIdleText(seconds) {
  if (seconds >= 3600) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return m ? `${h} h ${m} min` : `${h} h`;
  }
  if (seconds >= 60) return `${Math.ceil(seconds / 60)} min`;
  return `${Math.max(0, Math.round(seconds))} s`;
}
function gpuIdleNote(models) {
  if (!models.length) return "";
  if (models.every((m) => m.forever)) return "Ollama keeps its model on the graphics card (idle timer: Never).";
  const timed = models.filter((m) => m.unload_in != null);
  if (!timed.length) return "";
  const soonest = Math.min(...timed.map((m) => m.unload_in));
  return soonest <= 1
    ? "Ollama is freeing the graphics card now."
    : `Ollama frees the graphics card in ${gpuIdleText(soonest)} if there are no more replies.`;   // CHANGED (1.5.0): says whose
}

// NEW (1.5.0): Evora's idle countdowns, short for the legend and in full
// for the note under the graph.
function evoraIdleShort(idle) {
  if (!idle) return "";
  const parts = [];
  if (idle.listen && idle.listen.loaded) parts.push("listening");
  if (idle.speech && idle.speech.loaded) parts.push("speech");
  if (!parts.length) return "freed while idle";
  return parts.join(" + ");
}
function evoraIdleNote(idle) {
  if (!idle) return "";
  const bits = [];
  const l = idle.listen || {};
  const sp = idle.speech || {};
  if (l.loaded && !idle.listening && l.unload_in != null) {
    bits.push(l.unload_in <= 1 ? "freeing the listening models now" : `frees the listening models in ${gpuIdleText(l.unload_in)}`);
  }
  if (sp.loaded && sp.unload_in != null) {
    bits.push(sp.unload_in <= 1 ? "freeing speech-to-text now" : `frees speech-to-text in ${gpuIdleText(sp.unload_in)} if nothing's said`);
  }
  if (!bits.length) {
    if (!l.loaded && !sp.loaded) return "Evora has freed the graphics card; it loads again on the next clip.";
    if (idle.listening && l.loaded) return "Evora keeps its listening models while listening is on.";
    return "";
  }
  return "Evora " + bits.join(", and ") + ".";
}

function renderGpu(data) {
  const box = $("gpuCard");
  if (!box) return;
  if (!data || !data.enabled) { box.classList.add("is-hidden"); return; }
  box.classList.remove("is-hidden");

  const card = data.card;
  const models = data.ollama_models || [];
  const legend = $("gpuLegend");
  const foot = $("gpuFoot");
  const plot = $("gpuPlot");
  const notes = [];
  legend.replaceChildren();

  if (card) {
    const parts = card.parts || {};
    $("gpuName").textContent = "";
    $("gpuUsed").textContent = `${gpuGb(card.used_mb)} / ${gpuGb(card.total_mb)}`;
    plot.classList.remove("is-hidden");
    drawGpuChart(data);
    gpuSeriesFor(data).slice().reverse().forEach((s) => {
      let value = parts[`${s.key}_mb`];
      let label = s.name;
      let note = "";
      if (s.key === "ollama") note = ollamaModelNote(models);
      if (s.key === "evora") note = evoraIdleShort(data.evora_idle);   // NEW (1.5.0)
      if (s.key === "other" && parts.estimated) { value = (parts.other_mb || 0) + (parts.evora_mb || 0); label = "Other"; note = "includes Evora"; }
      if (s.key === "other" && !parts.estimated) note = "desktop, games, driver";
      legend.append(gpuLegendRow(s.key, label, gpuGb(value), note));
    });
    legend.append(gpuLegendRow("free", "Free", gpuGb(Math.max(0, card.total_mb - card.used_mb))));

    const facts = [gpuCardName(card.name)];
    if (card.util_pct != null) facts.push(`${card.util_pct}% busy`);
    if (card.temp_c != null) facts.push(`${card.temp_c}°C`);
    if (facts.length) notes.push(facts.join(" · "));
    if (data.uses_ollama && !data.same_card && models.length) {
      notes.push(`Ollama is on another PC: ${models.map((m) => `${m.name} ${gpuGb(m.vram_mb)}`).join(", ")}.`);
    }
    if (data.uses_ollama && data.ollama_problem) notes.push(data.ollama_problem);
    const idle = gpuIdleNote(models);   // NEW (1.5.0): the idle countdown
    if (idle) notes.push(idle);
    const evoraIdle = evoraIdleNote(data.evora_idle);   // NEW (1.5.0): and Evora's
    if (evoraIdle) notes.push(evoraIdle);
  } else {
    // No card report: show what Ollama says about its own models.
    plot.classList.add("is-hidden");
    gpuGeometry = null;
    $("gpuName").textContent = models.length ? "Ollama" : "";
    $("gpuName").title = "";
    const vram = models.reduce((sum, m) => sum + (m.vram_mb || 0), 0);
    $("gpuUsed").textContent = models.length ? gpuGb(vram) : "";
    models.forEach((m) => {
      const partial = m.size_mb && m.vram_mb < m.size_mb * 0.97;
      legend.append(gpuLegendRow("ollama", m.name, gpuGb(m.vram_mb), partial ? "part on the CPU" : ""));
    });
    if (data.uses_ollama && !models.length && !data.ollama_problem) notes.push("No Ollama model is loaded right now.");
    const idle = gpuIdleNote(models);   // NEW (1.5.0): the idle countdown
    if (idle) notes.push(idle);
    if (data.ollama_problem) notes.push(data.ollama_problem);
    if (data.card_problem) notes.push(data.card_problem);
    else if (!data.uses_evora) {
      notes.push("To graph the whole card, run Evora on the PC with the graphics card and choose it for Transcription.");
    }
  }
  foot.textContent = notes.join("\n");   // CHANGED (1.5.0): one line each
}

async function refreshGpu() {
  try {
    const res = await fetch("/api/gpu");
    if (!res.ok) return;
    gpuData = await res.json();
  } catch (err) {
    return;   // Frivo itself is unreachable; the status rows say so
  }
  renderGpu(gpuData);
}

(function watchGpuWhileStatusOpen() {
  const pop = $("statusPop");
  const svg = $("gpuSvg");
  if (!pop) return;
  if (svg) {
    svg.addEventListener("pointermove", gpuHover);
    svg.addEventListener("pointerdown", gpuHover);
    svg.addEventListener("pointerleave", gpuHoverEnd);
  }
  const sync = () => {
    const open = !pop.classList.contains("is-hidden");
    if (open && !gpuTimer) {
      gpuDrawIn = true;   // NEW (1.5.0): the graph draws in on opening
      refreshGpu();
      gpuTimer = setInterval(refreshGpu, GPU_POLL_MS);
    } else if (!open && gpuTimer) {
      clearInterval(gpuTimer);
      gpuTimer = null;
      gpuHoverEnd();
    }
  };
  new MutationObserver(sync).observe(pop, { attributes: true, attributeFilter: ["class"] });
  sync();
})();


// ---------------------------------------------------------------------------
// NEW (1.5.0): Motion, round 1. The CSS does the animating; these only tell
// it where things grow from, and when a toggle was flipped by a person.
// ---------------------------------------------------------------------------

// Points a popover's transform-origin at the centre of the thing that opened
// it, so it scales out of that chip (and back into it when it closes).
// Measured from layout boxes rather than getBoundingClientRect on the
// popover, which a running animation would distort.
function growFrom(pop, anchor) {
  if (!pop || !anchor) return;
  const a = anchor.getBoundingClientRect();
  const parent = pop.offsetParent;
  let left = 0;
  let top = 0;
  if (parent) {
    const p = parent.getBoundingClientRect();
    left = p.left + parent.clientLeft;
    top = p.top + parent.clientTop;
  }
  const x = a.left + a.width / 2 - left - pop.offsetLeft;
  const y = a.top + a.height / 2 - top - pop.offsetTop;
  // A popover that opens upwards (the chip bar's) is anchored by its
  // bottom, and its content can still be loading, so measure from the
  // bottom: the origin stays on the chip however tall it ends up.
  const below = y > pop.offsetHeight / 2;
  const yValue = below ? `calc(100% + ${Math.round(y - pop.offsetHeight)}px)` : `${Math.round(y)}px`;
  pop.style.setProperty("--grow-origin", `${Math.round(x)}px ${yValue}`);
}

// Speak, Chatbox and Auto: a little pop when you switch one on. Listening
// for change (which only a person's click fires) keeps page loads and the
// VRChat mute sync from setting it off.
document.addEventListener("change", (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || !input.checked) return;
  const track = input.closest(".icon-switch") && input.closest(".icon-switch").querySelector(".icon-switch-track");
  if (!track) return;
  track.classList.remove("is-popping");
  void track.offsetWidth;   // restart the animation if it's flipped quickly
  track.classList.add("is-popping");
  track.addEventListener("animationend", () => track.classList.remove("is-popping"), { once: true });
});


// NEW (1.5.0): keep the chip row on one line without cutting into the voice's
// name. When everything doesn't fit at full size, the row goes compact: the
// length chip shows only its number, and if that's not enough, the style chip
// only its icon (both keep their tooltips). Checked whenever a chip's size changes.
var fitStripQueued = false;
function fitSessionStrip() {
  if (fitStripQueued) return;
  fitStripQueued = true;
  requestAnimationFrame(() => {
    fitStripQueued = false;
    const strip = document.querySelector(".session-strip");
    if (!strip || !strip.offsetWidth) return;
    // NEW (1.5.0): not while one of the chips' popovers is open. Re-fitting
    // then moved the chip, and the slider in its popover with it, under
    // the pointer: dragging the volume made it jump back and forth. It
    // re-fits once the popover closes.
    if (strip.querySelector(".popover:not(.is-hidden)")) return;
    // Two steps, the gentlest first: drop " words", then the style's name.
    strip.classList.remove("is-compact", "is-compact-more");
    strip.classList.add("is-measuring");   // every chip at its natural width
    // CHANGED (1.7.0): measured from the chips' own widths. scrollWidth also
    // counted a closed popover sticking out past the right-hand group.
    const tooWide = () => {
      const kids = Array.from(strip.children).filter((c) => c.offsetParent !== null || getComputedStyle(c).display !== "none");
      const gap = parseFloat(getComputedStyle(strip).columnGap) || 0;
      const need = kids.reduce((sum, c) => sum + c.getBoundingClientRect().width, 0) + gap * Math.max(0, kids.length - 1);
      return need > strip.clientWidth + 1;
    };
    if (tooWide()) {
      strip.classList.add("is-compact");
      if (tooWide()) strip.classList.add("is-compact-more");
    }
    strip.classList.remove("is-measuring");
    flipStrip(strip);   // NEW (1.5.0): chips glide to their new places
  });
}
(function watchSessionStrip() {
  const strip = document.querySelector(".session-strip");
  if (!strip || typeof ResizeObserver !== "function") return;
  const ro = new ResizeObserver(() => fitSessionStrip());
  ro.observe(strip);
  // A chip appearing, disappearing or changing its words.
  new MutationObserver((records) => {
    // Its own is-compact / is-measuring flips don't count.
    if (records.some((r) => r.target !== strip)) {
      flipStrip(strip);
      fitSessionStrip();
    }
  })
    .observe(strip, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["class"] });
  fitSessionStrip();
})();


// ---------------------------------------------------------------------------
// NEW (1.5.0): Motion, round 2: the chat.
// ---------------------------------------------------------------------------

// Reads a spring from the stylesheet, for animations started from script.
function motionEasing(name) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(`--spring-${name}`).trim();
  return value || "cubic-bezier(0.32, 0.72, 0, 1)";
}
function motionDuration(name, fallback) {
  const value = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(`--dur-${name}`));
  return Number.isFinite(value) ? value : fallback;
}
function reducedMotion() {
  return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

// Scrolls the conversation to the newest message: smoothly when you're
// already near the bottom, instantly when you'd scrolled far up (a long
// glide through the whole history isn't the point).
function scrollLogToEnd() {
  const distance = logEl.scrollHeight - logEl.clientHeight - logEl.scrollTop;
  if (distance <= 0) return;
  const smooth = !reducedMotion() && distance < logEl.clientHeight * 1.5;
  logEl.scrollTo({ top: logEl.scrollHeight, behavior: smooth ? "smooth" : "auto" });
}

// The reply grows out of the typing bubble: it starts clipped to the size
// the dots had and opens to its own, while the words fade up. Clip-path is
// painted by the graphics card, so nothing reflows.
function morphFromTyping(bubble, from) {
  if (reducedMotion() || !bubble.animate) return;
  const to = bubble.getBoundingClientRect();
  const right = Math.max(0, to.width - from.width);
  const bottom = Math.max(0, to.height - from.height);
  if (!right && !bottom) return;
  const radius = getComputedStyle(bubble).borderRadius || "16px";
  bubble.classList.add("is-from-typing");
  const duration = motionDuration("smooth", 560);
  bubble.animate(
    [
      { clipPath: `inset(0 ${right}px ${bottom}px 0 round ${radius})` },
      { clipPath: `inset(0 0 0 0 round ${radius})` },
    ],
    { duration, easing: motionEasing("smooth") },
  );
  const words = bubble.querySelector(".bubble-text");
  if (words) words.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 260, delay: 70, easing: "ease-out", fill: "backwards" });
}

// A one-shot pop (the profile letter, and anything else that changes in
// place). Restarts cleanly if it's triggered again mid-pop.
function popOnce(el) {
  if (!el) return;
  el.classList.remove("is-popping");
  void el.offsetWidth;
  el.classList.add("is-popping");
  el.addEventListener("animationend", () => el.classList.remove("is-popping"), { once: true });
}


// ---------------------------------------------------------------------------
// NEW (1.5.0): Motion, round 2: while a reply is spoken.
// ---------------------------------------------------------------------------

// The bubble's rim glows with the voice's loudness, and the word being said
// glows. Both are driven from the player's own clock (the same one
// the progress line uses), so pausing or replaying can't knock them out of
// step. The loudness is worked out once from the audio, not listened to
// live, so it costs nothing while playing.
//
// The highlight only appears with exact timings (ElevenLabs, or a Windows
// voice that reported its words). Without them — Frivo's own voices — the
// reply looks exactly as it always has: nothing is estimated.
const SPEECH_LEVEL_RATE = 40;   // loudness samples per second

function makeSpeechVisuals(bubble, wordTimes) {
  let envelope = null;
  let words = null;        // [{ el, start, end }], made on first play
  let current = -1;
  let level = 0;
  let shownLevel = -1;
  const textEl = bubble.querySelector(".bubble-text");

  function prepareWords() {
    if (words !== null) return;
    words = [];
    if (!Array.isArray(wordTimes) || !wordTimes.length || !textEl) return;
    // CHANGED (1.5.0): voice-tag marks stay as they are; only the words
    // around them are wrapped.
    const nodes = Array.from(textEl.childNodes);
    const pieces = nodes.map((n) => (n.nodeType === 3 ? n.textContent.split(/(\s+)/).filter((p) => p.length) : null));
    const count = pieces.reduce((sum, parts) => sum + (parts ? parts.filter((p) => !/^\s+$/.test(p)).length : 0), 0);
    if (count !== wordTimes.length) return;   // not word for word: no highlight
    const frag = document.createDocumentFragment();
    let k = 0;
    nodes.forEach((node, n) => {
      const parts = pieces[n];
      if (!parts) { frag.append(node); return; }
      parts.forEach((part) => {
        if (/^\s+$/.test(part)) { frag.append(part); return; }
        const span = document.createElement("span");
        span.className = "spoken-word";
        span.textContent = part;
        frag.append(span);
        const [start, end] = wordTimes[k++];
        words.push({ el: span, start: Number(start) || 0, end: Number(end) || 0 });
      });
    });
    textEl.replaceChildren(frag);
    bubble.classList.add("has-word-timing");
  }

  function wordAt(t) {
    // The last word that has started; held through the pause after it.
    if (current >= 0 && current < words.length && words[current].start <= t
        && (current + 1 >= words.length || words[current + 1].start > t)) return current;
    let lo = 0;
    let hi = words.length - 1;
    let found = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (words[mid].start <= t) { found = mid; lo = mid + 1; } else { hi = mid - 1; }
    }
    return found;
  }

  // CHANGED (1.5.0): the spoken word glows (Friday's pick) rather than
  // getting a highlight behind it. The glow fades from word to word.
  function moveMarker(index) {
    const prev = current;
    current = index;
    if (prev >= 0 && words[prev]) words[prev].el.classList.remove("is-spoken");
    if (index >= 0) words[index].el.classList.add("is-spoken");
  }

  return {
    setBuffer(buffer) {
      // Loudness, 40 times a second, scaled so ordinary speech reaches
      // about 1. Every 4th sample is plenty for a glow.
      try {
        const data = buffer.getChannelData(0);
        const step = Math.max(1, Math.floor(buffer.sampleRate / SPEECH_LEVEL_RATE));
        const values = [];
        for (let i = 0; i < data.length; i += step) {
          let sum = 0;
          let n = 0;
          const end = Math.min(data.length, i + step);
          for (let j = i; j < end; j += 4) { sum += data[j] * data[j]; n++; }
          values.push(Math.sqrt(sum / Math.max(1, n)));
        }
        const sorted = values.slice().sort((a, b) => a - b);
        const loud = sorted[Math.floor(sorted.length * 0.9)] || 1;
        envelope = values.map((v) => Math.min(1, v / loud));
      } catch (e) {
        envelope = null;
      }
    },
    update(t) {
      if (envelope) {
        const target = envelope[Math.min(envelope.length - 1, Math.max(0, Math.floor(t * SPEECH_LEVEL_RATE)))] || 0;
        // Quick to rise, slower to fall, like a level meter.
        level += (target - level) * (target > level ? 0.45 : 0.18);
        if (Math.abs(level - shownLevel) > 0.015) {
          shownLevel = level;
          bubble.style.setProperty("--speak", level.toFixed(3));
        }
      }
      prepareWords();
      if (!words.length) return;
      const index = wordAt(t);
      if (index !== current) moveMarker(index);
    },
    // NEW (1.5.0): a streamed reply's timings arrive once the voice is
    // made, after it may have started playing.
    setWordTimes(times) {
      wordTimes = times;
      if (words !== null && !words.length) words = null;
    },
    // NEW (1.5.0): the glow for a streamed reply, from what's playing now.
    liveLevel(target) {
      level += (target - level) * (target > level ? 0.45 : 0.18);
      if (Math.abs(level - shownLevel) > 0.015) {
        shownLevel = level;
        bubble.style.setProperty("--speak", level.toFixed(3));
      }
    },
    stop() {
      level = 0;
      shownLevel = -1;
      bubble.style.removeProperty("--speak");
      if (words && words.length && current !== -1) moveMarker(-1);
    },
  };
}

// The chatbox page dots: one per page, the current one larger and red,
// the ones already sent filled in.
function makeChatboxPager(count) {
  const el = document.createElement("div");
  el.className = "chatbox-pager";
  el.title = "VRChat chatbox pages, as the voice reaches them";
  el.appendChild(iconNode("i-chat", "icon-12"));
  const dots = [];
  for (let i = 0; i < count; i++) {
    const dot = document.createElement("span");
    dot.className = "chatbox-pager-dot";
    el.appendChild(dot);
    dots.push(dot);
  }
  return {
    el,
    show(index) {
      dots.forEach((dot, i) => {
        dot.classList.toggle("is-current", i === index);
        dot.classList.toggle("is-done", i < index);
      });
    },
  };
}


// ---------------------------------------------------------------------------
// NEW (1.5.0): Motion, round 3: sizes and places that change.
// ---------------------------------------------------------------------------

// Something inside `el` is about to change its height (`mutate`). Instead
// of jumping, `el` eases from the old height to the new one.
function smoothResize(el, mutate) {
  const before = el.offsetHeight;
  mutate();
  if (reducedMotion() || !el.animate) return;
  const after = el.offsetHeight;
  if (Math.abs(after - before) < 2) return;
  el.animate(
    [{ height: `${before}px`, overflow: "hidden" }, { height: `${after}px`, overflow: "hidden" }],
    { duration: motionDuration("snappy", 480), easing: motionEasing("snappy") },
  );
}

// The chip row: when a chip appears, disappears or changes width, the others
// glide to their new places (only transforms, measured from layout boxes).
const stripPlaces = new WeakMap();
function flipStrip(strip) {
  if (!strip) return;
  // CHANGED (1.5.0): no gliding while a popover is open (see fitSessionStrip).
  const moving = !reducedMotion() && !strip.querySelector(".popover:not(.is-hidden)");
  Array.from(strip.children).forEach((chip) => {
    if (!chip.offsetParent) { stripPlaces.delete(chip); return; }   // hidden
    const now = chip.offsetLeft;
    const was = stripPlaces.get(chip);
    stripPlaces.set(chip, now);
    if (!moving || was == null || Math.abs(was - now) < 1 || !chip.animate) return;
    chip.animate(
      [{ transform: `translateX(${was - now}px)` }, { transform: "none" }],
      { duration: motionDuration("snappy", 480), easing: motionEasing("snappy") },
    );
  });
}

// NEW (1.5.0): entrance animations that shouldn't play on page load wait for this.
requestAnimationFrame(() => requestAnimationFrame(() => document.documentElement.classList.add("motion-ready")));


// NEW (1.5.0): a ring around the mic button that follows your voice while
// dictating. It reads the microphone that dictation already opened (the
// live mode's own meter, or the recording's stream), about 30 times a
// second, and only moves a ring, never the button.
var micRing = (function makeMicRing() {
  let ctx = null;
  let analyser = null;
  let data = null;
  let frame = 0;
  let level = 0;

  function loop() {
    frame = requestAnimationFrame(loop);
    if (!analyser) return;
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i += 2) {
      const v = (data[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / (data.length / 2));
    const target = Math.min(1, rms * 6);
    level += (target - level) * (target > level ? 0.5 : 0.15);
    dictateBtn.style.setProperty("--mic-level", level.toFixed(3));
  }

  function begin(node) {
    analyser = node;
    data = new Uint8Array(analyser.fftSize);
    dictateBtn.classList.add("has-level");
    if (!frame) frame = requestAnimationFrame(loop);
  }

  return {
    fromAnalyser(node) {
      if (reducedMotion() || !node) return;
      begin(node);
    },
    fromStream(stream) {
      if (reducedMotion() || !stream) return;
      try {
        ctx = new (window.AudioContext || window.webkitAudioContext)();
        const node = ctx.createAnalyser();
        node.fftSize = 512;
        ctx.createMediaStreamSource(stream).connect(node);
        begin(node);
      } catch (e) {
        ctx = null;   // no ring; the pulse still shows it's listening
      }
    },
    stop() {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      analyser = null;
      level = 0;
      if (ctx) { try { ctx.close(); } catch (e) { /* already closed */ } ctx = null; }
      dictateBtn.classList.remove("has-level");
      dictateBtn.style.removeProperty("--mic-level");
    },
  };
})();


// ---------------------------------------------------------------------------
// NEW (1.5.0): saved replies.
//
// Save keeps a spoken reply: its audio, its chatbox pages timed to the
// voice and its word timings. Playing it from the Saved list puts it in the
// conversation and sends it to the VRChat chatbox exactly as when it was
// new. Nothing is generated, so it costs no credits.
// ---------------------------------------------------------------------------
const savedPop = $("savedPop");
const savedListEl = $("savedList");
const savedSearch = $("savedSearch");
const savedFoot = $("savedFoot");
let savedItems = [];
let savedQuery = "";

function makeSaveButton(saveData) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "turn-save";
  btn.title = "Save this reply to play again later, without credits";
  const label = document.createElement("span");
  label.textContent = saveData.saved_done ? "Saved" : "Save";
  btn.append(iconNode("i-bookmark", "icon-12"), label);
  if (saveData.saved_done) {   // saved before a refresh
    btn.classList.add("is-saved");
    btn.disabled = true;
  }
  btn.addEventListener("click", async (event) => {
    event.stopPropagation();
    if (btn.disabled) return;
    btn.disabled = true;
    try {
      const res = await fetch("/api/saved", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(saveData),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Couldn't save that reply.");
      btn.classList.add("is-saved");
      label.textContent = "Saved";
      saveData.saved_done = true;   // remembered through a refresh
      if (typeof persistTranscript === "function") persistTranscript();
      btn.title = "Saved. Find it under Saved, on the left.";
      if (typeof popOnce === "function") popOnce(btn);
      setStatus(data.already ? "Already saved." : "Saved. Play it again any time from Saved, on the left.");
      if (savedPopIsOpen()) loadSavedList();
    } catch (err) {
      btn.disabled = false;
      setStatus(err.message, true);
    }
  });
  return btn;
}

function savedPopIsOpen() {
  return savedPop && !savedPop.classList.contains("is-hidden");
}

function openSavedPop() {
  if (!savedPop) return;
  if (typeof closeAllPopovers === "function") closeAllPopovers();
  savedPop.classList.remove("is-hidden");
  savedQuery = "";
  if (savedSearch) { savedSearch.value = ""; savedSearch.focus(); }
  renderSavedList();
  loadSavedList();
}

function closeSavedPop() {
  if (savedPop) savedPop.classList.add("is-hidden");
}

async function loadSavedList() {
  try {
    const res = await fetch("/api/saved");
    const data = await res.json();
    savedItems = Array.isArray(data.items) ? data.items : [];
  } catch (err) {
    savedItems = [];
  }
  renderSavedList();
}

function savedWhen(seconds) {
  const date = new Date(seconds * 1000);
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();
  return sameDay
    ? date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function renderSavedList() {
  if (!savedListEl) return;
  const q = savedQuery.trim().toLowerCase();
  const shown = savedItems.filter((item) => !q || [item.text, item.voice_name, item.profile_name, item.english]
    .some((field) => String(field || "").toLowerCase().includes(q)));
  savedListEl.replaceChildren();
  if (!savedItems.length || !shown.length) {
    const none = document.createElement("p");
    none.className = "voice-none";
    none.textContent = savedItems.length
      ? "Nothing saved matches that."
      : "Nothing saved yet. Hover over a spoken reply and click Save to keep it.";
    savedListEl.appendChild(none);
  }
  shown.forEach((item) => savedListEl.appendChild(savedRowNode(item)));
  if (savedFoot) {
    savedFoot.textContent = savedItems.length === shown.length
      ? `${savedItems.length} saved`
      : `${shown.length} of ${savedItems.length} saved`;
  }
}

function savedRowNode(item) {
  const row = document.createElement("div");
  row.className = "voice-row saved-row";
  row.setAttribute("role", "listitem");

  const play = document.createElement("button");
  play.type = "button";
  play.className = "voice-preview saved-play";
  play.title = "Play it now: in the chat, and in your VRChat chatbox if it's on";
  play.setAttribute("aria-label", "Play this saved reply");
  play.appendChild(iconNode("i-play", "icon-16"));

  const body = document.createElement("button");
  body.type = "button";
  body.className = "saved-body";
  const text = document.createElement("span");
  text.className = "saved-text";
  text.textContent = item.text;
  const sub = document.createElement("span");
  sub.className = "saved-sub";
  sub.textContent = [item.voice_name, item.profile_name, savedWhen(item.saved_at)].filter(Boolean).join(" · ");
  if (item.voice_how) sub.title = `Spoken as: ${item.voice_how}`;   // NEW (1.5.0)
  body.append(text, sub);

  // Delete asks twice: the first click turns the button into "Delete?".
  const del = document.createElement("button");
  del.type = "button";
  del.className = "voice-menu-btn saved-delete";
  del.title = "Delete this saved reply";
  del.setAttribute("aria-label", "Delete this saved reply");
  del.appendChild(iconNode("i-trash", "icon-16"));
  let armedTimer = null;
  del.addEventListener("click", async (event) => {
    event.stopPropagation();
    if (!del.classList.contains("is-armed")) {
      del.classList.add("is-armed");
      del.replaceChildren(document.createTextNode("Delete?"));
      armedTimer = setTimeout(() => {
        del.classList.remove("is-armed");
        del.replaceChildren(iconNode("i-trash", "icon-16"));
      }, 3000);
      return;
    }
    clearTimeout(armedTimer);
    try {
      const res = await fetch(`/api/saved/${item.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Couldn't delete it.");
      savedItems = savedItems.filter((i) => i.id !== item.id);
      row.classList.add("is-leaving");
      setTimeout(renderSavedList, 220);
    } catch (err) {
      setStatus(err.message, true);
    }
  });

  // NEW (1.5.0): keep the clip as a file on your computer.
  const dl = document.createElement("a");
  dl.className = "voice-menu-btn saved-download";
  dl.href = `/api/saved/${item.id}/download`;
  dl.setAttribute("download", "");
  dl.title = "Download this clip";
  dl.setAttribute("aria-label", "Download this clip");
  dl.appendChild(iconNode("i-download", "icon-16"));
  dl.addEventListener("click", (event) => event.stopPropagation());

  const go = (event) => {
    event.stopPropagation();
    playSaved(item);
  };
  play.addEventListener("click", go);
  body.addEventListener("click", go);
  row.append(play, body, dl, del);
  return row;
}

// Plays a saved reply as if it had just been generated: the voice, the
// bubble with its glowing words, and the chatbox pages following the voice.
async function playSaved(item) {
  ensureAudioContext();   // inside the click, so the browser lets it play
  closeSavedPop();
  beginReplyTyping();
  requestVrchatUnmute();
  let data;
  try {
    const res = await fetch(`/api/saved/${item.id}/play`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, profile_id: currentProfileId || null }),
    });
    data = await res.json();
    if (!res.ok) throw new Error(data.error || "Couldn't play that saved reply.");
  } catch (err) {
    endReplyTyping();
    setStatus(err.message, true);
    return;
  }
  const saved = data.item;
  const pages = Array.isArray(saved.chatbox_pages) ? saved.chatbox_pages : [];
  const pager = pages.length > 1 && oscEnabled() ? makeChatboxPager(pages.length) : null;
  const follower = pages.length > 1 ? makeChatboxFollower(pages, pager ? (i) => pager.show(i) : null) : null;
  const active = allProfiles.find((p) => p.id === currentProfileId);
  addTurn(saved.profile_name || (active ? active.name : "Voice"), saved.text, {
    audioUrl: saved.audio_url,
    language: saved.language,
    english: saved.english,
    wordCount: saved.text.split(/\s+/).filter(Boolean).length,
    voiceEngine: saved.voice_engine,
    voiceEngineName: saved.voice_engine_name,
    wordTimes: saved.word_times,
    voiced: saved.voiced && saved.voiced !== saved.text ? saved.voiced : undefined,   // NEW (1.5.0)
    footer: pager ? pager.el : null,
    saved: true,
    spoke: true,
    credits: 0,
    onAudioStart: () => {
      if (!oscEnabled()) endReplyTyping();
      else if (!follower) sendToChatbox(saved.text, { speaking: true });
    },
    onPlayback: follower ? (playing, offset, dur) => follower.update(playing, offset, dur) : null,
  });
  setStatus("Playing a saved reply. No credits used.");
}

if (savedPop) {
  const railSaved = $("railSaved");
  if (railSaved) railSaved.addEventListener("click", openSavedPop);
  const savedClose = $("savedCloseBtn");
  if (savedClose) savedClose.addEventListener("click", closeSavedPop);
  savedPop.addEventListener("click", (event) => {
    if (event.target === savedPop) closeSavedPop();
  });
  savedPop.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { event.preventDefault(); closeSavedPop(); }
  });
  if (savedSearch) {
    savedSearch.addEventListener("input", () => {
      savedQuery = savedSearch.value;
      renderSavedList();
    });
  }
}


// ---------------------------------------------------------------------------
// NEW (1.5.0): the conversation survives a refresh. Every message (and each
// "now talking to" divider) is kept in this browser until Clear is pressed.
// Old replies come back quietly: nothing plays, and a reply's audio is only
// fetched when you click it. The AI's memory of the conversation is on the
// server, under this browser's session, so it lines up with what you see.
// ---------------------------------------------------------------------------
const TRANSCRIPT_KEY = "frivo_transcript_v1";
const TRANSCRIPT_MAX = 150;
var transcript = [];

function persistTranscript() {
  try {
    localStorage.setItem(TRANSCRIPT_KEY, JSON.stringify(transcript.slice(-TRANSCRIPT_MAX)));
  } catch (err) {
    // Full or blocked storage: the conversation just won't survive a refresh.
  }
}

function rememberTurn(who, text, opts, at) {
  const kept = {};
  Object.keys(opts || {}).forEach((key) => {
    const value = opts[key];
    if (typeof value === "function" || value instanceof Node) return;   // callbacks, the page dots
    if (key === "restoring" || key === "at" || key === "replaceTurn") return;
    kept[key] = value;
  });
  // CHANGED (1.5.0): a retake replaces the record of the take before.
  const record = { kind: "turn", who, text, opts: kept, at };
  const same = opts && opts.replaceTurn ? transcript.findIndex((r) => r.kind === "turn" && r.at === at) : -1;
  if (same >= 0) transcript[same] = record;
  else transcript.push(record);
  if (transcript.length > TRANSCRIPT_MAX) transcript = transcript.slice(-TRANSCRIPT_MAX);
  persistTranscript();
}

function rememberDivider(label) {
  if (transcript.length && transcript[transcript.length - 1].kind === "divider") transcript.pop();
  transcript.push({ kind: "divider", label, at: Date.now() });
  persistTranscript();
}

function forgetTranscript() {
  transcript = [];
  try { localStorage.removeItem(TRANSCRIPT_KEY); } catch (err) { /* nothing kept */ }
}

(function restoreTranscript() {
  let records = [];
  try {
    records = JSON.parse(localStorage.getItem(TRANSCRIPT_KEY) || "[]");
  } catch (err) {
    records = [];
  }
  if (!Array.isArray(records) || !records.length) return;
  logBody.classList.add("is-restoring");   // no entrance animations
  records.forEach((record) => {
    try {
      if (record.kind === "divider") addProfileDivider(record.label, { restoring: true });
      else if (record.kind === "turn") addTurn(record.who, record.text, { ...(record.opts || {}), restoring: true, at: record.at });
    } catch (err) {
      console.warn("Couldn't bring back a message:", err);
    }
  });
  transcript = records;
  logEl.scrollTop = logEl.scrollHeight;
  requestAnimationFrame(() => requestAnimationFrame(() => logBody.classList.remove("is-restoring")));
})();


// NEW (1.5.0): adding a Piper voice of your own, from the voice list.
// Picks the files (the .onnx and its .onnx.json, or an archive), sends them
// to Frivo, which converts, tries and keeps the voice. Nothing is run.
(function wireAddVoice() {
  const btn = $("voiceAddBtn");
  const input = $("voiceAddInput");
  if (!btn || !input) return;
  btn.addEventListener("click", () => input.click());
  input.addEventListener("change", async () => {
    const files = Array.from(input.files || []);
    input.value = "";
    if (!files.length) return;
    // The status line is behind the voice list, so say it in its footer too.
    const foot = $("voiceFoot");
    const say = (text, isError) => {
      setStatus(text, isError);
      if (foot) { foot.textContent = text; foot.classList.toggle("is-error", Boolean(isError)); }
    };
    const bad = files.find((f) => /\.(exe|vb|vbs|bat|cmd|ps1|msi|dll|js)$/i.test(f.name));
    if (bad) {
      say(`${bad.name} is a program, not a voice. A voice is an .onnx file with its .onnx.json.`, true);
      return;
    }
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    btn.disabled = true;
    const label = btn.lastChild;
    const before = label.textContent;
    label.textContent = "Adding…";
    setStatus("Adding the voice: converting it and trying it out…");
    say("Adding the voice: converting it and trying it out…");
    try {
      const res = await fetch("/api/voices/custom", { method: "POST", body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "That voice couldn't be added.");
      await loadVoices();
      say(`${data.name} added. It's under "Free · added by you".`);
      const added = typeof voiceById === "function" ? voiceById(data.voice_id) : null;
      if (added) {
        const row = voiceRows.find((r) => r.voice.voice_id === data.voice_id);
        if (row) { row.row.scrollIntoView({ block: "center" }); popOnce(row.row); }
      }
    } catch (err) {
      say(err.message, true);
    } finally {
      btn.disabled = false;
      label.textContent = before;
    }
  });
})();

// ---------------------------------------------------------------------------
// NEW (1.5.0): Voice tags and Delivery (ElevenLabs voices)
//
// A voice tag is a word or two in square brackets, like [laughs] or
// [softly], that ElevenLabs' v3 voice acts out instead of reading. The ✦
// button in the message box puts one in where the cursor is, or asks the AI
// to suggest some for what you've typed. A profile with Expressive voice on
// lets the AI add them to its own replies. In the conversation they show
// as small marks; the chatbox never sees them.
// ---------------------------------------------------------------------------

var VOICE_TAG_RE = /\[([A-Za-z][A-Za-z' \-]{0,38})\]/g;
var voiceDeliveries = [
  { id: "calm", name: "Calm", description: "Steady and even. Doesn't shout." },
  { id: "natural", name: "Natural", description: "The voice as it comes." },
  { id: "lively", name: "Lively", description: "Bigger ups and downs. Can get loud." },
];
var audioTagGroups = [
  { name: "Feeling", tags: ["happy", "excited", "sad", "nervous", "curious", "sarcastic", "annoyed", "warmly"] },
  { name: "Voice", tags: ["softly", "whispers", "calm", "slowly", "quickly", "dramatically", "shouts"] },
  { name: "Sounds", tags: ["laughs", "chuckles", "giggles", "sighs", "gasps", "clears throat", "pause"] },
];

// The bubble's text, with each tag as a mark. The mark's word is drawn by
// CSS, so the bubble's text (copying, the word highlight) is only what's said.
function fillBubbleText(el, text) {
  text = String(text || "");
  // Its own copy: a restored conversation is drawn before this file has
  // finished loading.
  const re = /\[([A-Za-z][A-Za-z' \-]{0,38})\]/g;
  if (!re.test(text)) { el.textContent = text; return; }
  re.lastIndex = 0;
  const frag = document.createDocumentFragment();
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) frag.append(text.slice(last, m.index));
    const mark = document.createElement("span");
    mark.className = "voice-tag";
    mark.dataset.tag = m[1].toLowerCase();
    mark.title = `Voice tag: ${m[1].toLowerCase()} (acted out, not said)`;
    frag.append(mark);
    last = m.index + m[0].length;
  }
  if (last < text.length) frag.append(text.slice(last));
  el.replaceChildren(frag);
}

function deliveryNoteText(id) {
  const d = voiceDeliveries.find((x) => x.id === id);
  return d ? d.description : "";
}

function applyVoiceStyleSettings(data) {
  if (Array.isArray(data.voice_deliveries) && data.voice_deliveries.length) voiceDeliveries = data.voice_deliveries;
  if (Array.isArray(data.audio_tag_groups) && data.audio_tag_groups.length) audioTagGroups = data.audio_tag_groups;
  const toggle = $("expressiveVoiceToggle");
  if (toggle) toggle.checked = data.expressive_voice === true;
  const shapingToggle = $("tagShapingToggle");
  if (shapingToggle) shapingToggle.checked = data.tag_shaping === true;   // NEW (1.5.0)
  if (Array.isArray(data.tag_words)) { tagWordsState = data.tag_words; renderTagWords(); }   // NEW (1.5.0)
  const hold = $("holdAccentRadios");
  const holdNote = $("holdAccentNote");
  if (hold && Array.isArray(data.hold_accent_modes) && data.hold_accent_modes.length) {
    const pick = data.hold_accent || "anchor";
    const describe = (id) => {
      const m = data.hold_accent_modes.find((x) => x.id === id);
      if (holdNote) holdNote.textContent = m ? m.description : "";
    };
    buildRadioGroup(hold, data.hold_accent_modes, "holdAccentSettings", pick, (id) => { describe(id); showAnchorRows(); });
    describe(pick);
  }
  const everyLine = $("expressiveEveryLine");   // NEW (1.5.0)
  if (everyLine) everyLine.checked = data.expressive_every_line !== false;
  const streaming = $("elevenStreamingToggle");   // NEW (1.5.0)
  if (streaming) streaming.checked = data.elevenlabs_streaming !== false;
  const models = $("expressiveModelRadios");
  const modelNote = $("expressiveModelNote");
  if (models && Array.isArray(data.expressive_models) && data.expressive_models.length) {
    const pickModel = data.expressive_model || "eleven_v4";
    const sayModel = (id) => {
      const m = data.expressive_models.find((x) => x.id === id);
      if (modelNote) modelNote.textContent = m ? m.description : "";
    };
    buildRadioGroup(models, data.expressive_models, "expressiveModelSettings", pickModel, sayModel);
    sayModel(pickModel);
    // NEW (1.5.0): a model ElevenLabs refused this hour, with its reason.
    const refused = Object.entries(data.expressive_refusals || {});
    if (modelNote && refused.length) {
      modelNote.replaceChildren(refused.map(([, r]) => `ElevenLabs refused ${r.label}: "${r.message}".`).join(" ")
        + " Frivo is using the next model down for an hour. ");
      const again = document.createElement("button");
      again.type = "button";
      again.className = "link-btn";
      again.textContent = "Try again now";
      again.addEventListener("click", async () => {
        await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ retry_expressive_models: true }) });
        sayModel(getRadioValue(models, pickModel));
        setStatus("The tags model will be tried again on the next message.");
      });
      modelNote.append(again);
      modelNote.classList.add("is-error");
    } else if (modelNote) {
      modelNote.classList.remove("is-error");
    }
  }
  const accent = $("voiceAccentSelect");
  if (accent && Array.isArray(data.voice_accents) && data.voice_accents.length) {
    fillOptionList(accent, data.voice_accents, data.voice_accent || "auto");
  }
  showAnchorRows();
  refreshAnchorStatus();
  const radios = $("voiceDeliveryRadios");
  const note = $("voiceDeliveryNote");
  if (radios) {
    const pick = data.voice_delivery || "natural";
    buildRadioGroup(radios, voiceDeliveries, "voiceDeliverySettings", pick, (id) => {
      if (note) note.textContent = deliveryNoteText(id);
    });
    if (note) note.textContent = deliveryNoteText(pick);
  }
  // NEW (1.5.0): Tag amount, and your tag taste.
  if (Array.isArray(data.tag_amounts) && data.tag_amounts.length) tagAmounts = data.tag_amounts;
  const amountRadios = $("tagAmountRadios");
  const amountNote = $("tagAmountNote");
  if (amountRadios) {
    const pickAmount = data.tag_amount || "normal";
    buildRadioGroup(amountRadios, tagAmounts, "tagAmountSettings", pickAmount, (id) => {
      if (amountNote) amountNote.textContent = tagAmountNote(id);
    });
    if (amountNote) amountNote.textContent = tagAmountNote(pickAmount);
  }
  loadTagTaste();
  renderVoiceTagGroups();
}

function fillProfileVoiceStyle(profile) {
  const expressive = $("profileExpressive");
  const radios = $("profileDeliveryRadios");
  const note = $("profileDeliveryNote");
  const hint = $("profileExpressiveHint");
  const defaults = {
    expressive: $("expressiveVoiceToggle") ? $("expressiveVoiceToggle").checked : false,
    delivery: $("voiceDeliveryRadios") ? getRadioValue($("voiceDeliveryRadios"), "natural") : "natural",
  };
  if (expressive) expressive.checked = profile ? profile.expressive_voice === true : defaults.expressive;
  const shaping = $("profileShaping");
  if (shaping) shaping.checked = profile ? profile.tag_shaping === true
    : ($("tagShapingToggle") ? $("tagShapingToggle").checked : false);
  showShapingState();
  const pick = profile ? (profile.voice_delivery || "natural") : defaults.delivery;
  if (radios) {
    buildRadioGroup(radios, voiceDeliveries, "voiceDeliveryProfile", pick, (id) => {
      if (note) note.textContent = deliveryNoteText(id);
    });
  }
  if (note) note.textContent = deliveryNoteText(pick);
  // NEW (1.5.0): Tag amount.
  const amountRadios = $("profileTagAmountRadios");
  const amountNote = $("profileTagAmountNote");
  const pickAmount = profile ? (profile.tag_amount || "normal")
    : ($("tagAmountRadios") ? getRadioValue($("tagAmountRadios"), "normal") : "normal");
  if (amountRadios) {
    buildRadioGroup(amountRadios, tagAmounts, "tagAmountProfile", pickAmount, (id) => {
      if (amountNote) amountNote.textContent = tagAmountNote(id);
    });
  }
  if (amountNote) amountNote.textContent = tagAmountNote(pickAmount);
  if (hint) {
    const voiceId = profile ? profile.voice_id : (typeof activeVoiceId === "function" ? activeVoiceId() : "");
    const eleven = voiceId && voiceEngine({ voice_id: voiceId }) === "elevenlabs";
    hint.textContent = eleven
      ? "The AI adds voice tags like [laughs] or [softly] where they fit, and the voice acts them out. Uses ElevenLabs' v4 model (Settings > Voices > Tags model)."
      : "For ElevenLabs voices. This profile has a free voice, so these do nothing until it has an ElevenLabs one.";
  }
}

// NEW (1.5.0): Shape words for tags only does anything with Clean up.
function showShapingState() {
  const field = $("profileShapingField");
  const box = $("profileShaping");
  const hint = $("profileShapingHint");
  if (!field || !box) return;
  const style = typeof profileResponseStyleRadios !== "undefined" ? getRadioValue(profileResponseStyleRadios, "echo") : "echo";
  const cleanUp = style === "echo";
  field.classList.toggle("is-dimmed", !cleanUp);
  if (hint) hint.textContent = cleanUp
    ? "Clean up adds voice tags and may lightly change the words right next to them so they flow: dropping a \"haha\" when [laughs] performs it, adding an \"oh\" after [gasps]. Meaning stays yours. Words like \"lol\" become tags: the list is in Settings > Voices > Tag words."
    : "Only works with Clean up. Pick Clean up above to use it.";
}

// CHANGED (1.5.0): the tags in three columns, like stage directions, each
// shown the way it looks in a message. Tags you type yourself are kept
// under "Yours".
var YOUR_TAGS_KEY = "frivo_your_tags";
function yourTags() {
  try { return JSON.parse(localStorage.getItem(YOUR_TAGS_KEY) || "[]").filter((t) => typeof t === "string"); }
  catch (e) { return []; }
}
function rememberYourTag(tag) {
  const known = new Set(audioTagGroups.flatMap((g) => g.tags || []));
  if (known.has(tag)) return;
  const list = [tag].concat(yourTags().filter((t) => t !== tag)).slice(0, 12);
  try { localStorage.setItem(YOUR_TAGS_KEY, JSON.stringify(list)); } catch (e) { /* not kept */ }
}
function forgetYourTag(tag) {
  try { localStorage.setItem(YOUR_TAGS_KEY, JSON.stringify(yourTags().filter((t) => t !== tag))); } catch (e) { /* fine */ }
}

function tagButton(tag, className) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = className;
  b.title = `Put [${tag}] in your message`;
  const word = document.createElement("span");
  word.className = "voice-tag-word";
  word.textContent = tag;
  const plus = document.createElement("span");
  plus.className = "voice-tag-plus";
  plus.setAttribute("aria-hidden", "true");
  plus.textContent = "+";
  b.append(word, plus);
  b.addEventListener("click", () => {
    insertVoiceTag(tag);
    if (typeof popOnce === "function") popOnce(b);
  });
  return b;
}

function renderVoiceTagGroups() {
  const box = $("voiceTagGroups");
  if (!box) return;
  box.replaceChildren();
  audioTagGroups.forEach((group) => {
    const col = document.createElement("div");
    col.className = "voice-tag-col";
    const name = document.createElement("span");
    name.className = "voice-tag-col-name";
    name.textContent = group.name;
    col.append(name);
    (group.tags || []).forEach((tag) => col.append(tagButton(tag, "voice-tag-item")));
    box.append(col);
  });
  renderYourTags();
}

function renderYourTags() {
  const wrap = $("voiceTagYours");
  const list = $("voiceTagYoursList");
  if (!wrap || !list) return;
  const tags = yourTags();
  list.replaceChildren();
  tags.forEach((tag) => {
    const chip = document.createElement("span");
    chip.className = "voice-tag-your";
    const b = tagButton(tag, "voice-tag-your-add");
    const x = document.createElement("button");
    x.type = "button";
    x.className = "voice-tag-your-forget";
    x.title = `Forget [${tag}]`;
    x.setAttribute("aria-label", `Forget ${tag}`);
    x.textContent = "×";
    x.addEventListener("click", (e) => { e.stopPropagation(); forgetYourTag(tag); renderYourTags(); });
    chip.append(b, x);
    list.append(chip);
  });
  wrap.classList.toggle("is-hidden", !tags.length);
}

(function wireCustomTag() {
  const form = $("voiceTagCustom");
  const input = $("voiceTagCustomInput");
  if (!form || !input) return;
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const tag = input.value.replace(/[\[\]]/g, "").replace(/\s+/g, " ").trim().toLowerCase();
    const note = $("voiceTagNote");
    if (!tag) return;
    if (!/^[a-z][a-z' \-]{0,37}$/.test(tag)) {
      if (note) { note.classList.add("is-error"); note.textContent = "A tag is letters only (spaces, ' and - are fine), like trying not to laugh."; }
      return;
    }
    if (note) { note.classList.remove("is-error"); note.textContent = ""; }
    insertVoiceTag(tag);
    rememberYourTag(tag);
    renderYourTags();
    input.value = "";
  });
})();

function insertVoiceTag(tag) {
  const input = $("messageInput");
  if (!input) return;
  const value = input.value;
  const start = Number.isInteger(input.selectionStart) ? input.selectionStart : value.length;
  const end = Number.isInteger(input.selectionEnd) ? input.selectionEnd : start;
  const before = value.slice(0, start);
  const after = value.slice(end);
  const lead = before && !/\s$/.test(before) ? " " : "";
  const trail = after && /^\s/.test(after) ? "" : " ";
  const piece = `${lead}[${tag}]${trail}`;
  input.value = before + piece + after;
  const caret = before.length + piece.length;
  input.focus();
  try { input.setSelectionRange(caret, caret); } catch (err) { /* not focusable yet */ }
  if (typeof cancelAutoSend === "function") cancelAutoSend();
  if (typeof setTypedByHand === "function") setTypedByHand(true);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function openVoiceTags() {
  if (typeof renderYourTags === "function") renderYourTags();   // NEW (1.5.0)
  const note = $("voiceTagNote");
  if (note && !note.dataset.busy) {
    note.classList.remove("is-error");
    note.textContent = "";
  }
}

function updateVoiceTagButton() {
  const wrap = $("voiceTagWrap");
  if (!wrap || typeof activeVoiceId !== "function") return;
  const id = activeVoiceId();
  const eleven = Boolean(id) && voiceEngine({ voice_id: id }) === "elevenlabs";
  wrap.classList.toggle("is-hidden", !eleven);
  if ($("tagSplit")) $("tagSplit").classList.toggle("is-hidden", !eleven);   // NEW (1.7.0): Suggest, under the box
  if (!eleven) {
    const pop = $("voiceTagPop");
    if (pop) pop.classList.add("is-hidden");
    if (typeof tagIdeasState === "object" && tagIdeasState) clearTagIdeas();   // a free voice can't use them
  } else if (typeof tagIdeasState === "object" && tagIdeasState) messageBoxChanged();
}

(function wireVoiceTags() {
  renderVoiceTagGroups();
  const suggest = $("voiceTagSuggest");
  const quick = $("voiceTagSuggestQuick");   // CHANGED (1.5.0): the same, outside the menu
  const note = $("voiceTagNote");
  const input = $("messageInput");
  if (suggest && input) {
    const buttons = [suggest, quick].filter(Boolean);
    const run = async () => {
      const before = input.value;
      if (!before.replace(VOICE_TAG_RE, "").trim()) {
        if (note) { note.classList.add("is-error"); note.textContent = "Type your message first, then Suggest adds tags to it."; }
        setStatus("Type your message first, then Suggest adds tags to it.", true);
        input.focus();
        return;
      }
      buttons.forEach((b) => { b.disabled = true; b.classList.add("is-busy"); });
      if (note) { note.classList.remove("is-error"); note.dataset.busy = "1"; note.textContent = "Finding the right places…"; }
      setStatus("Finding the right places for tags…");
      try {
        const res = await fetch("/api/voice-tags/suggest", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: before, profile_id: currentProfileId || null, session_id: sessionId }),   // CHANGED (1.5.0): with the conversation
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Couldn't suggest tags.");
        if (input.value !== before) return;   // you kept typing; don't overwrite it
        if (!data.added) {
          if (note) note.textContent = "Nothing to add: it reads fine as it is.";
          setStatus("Nothing to add: it reads fine as it is.");
          return;
        }
        input.value = data.text;
        const offered = tagsIn(data.text).filter((t) => !tagsIn(before).includes(t));   // NEW (1.5.0): for your taste
        noteTagOffers(offered);
        if (typeof cancelAutoSend === "function") cancelAutoSend();
        if (typeof setTypedByHand === "function") setTypedByHand(true);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        if (typeof tagIdeasState === "object" && tagIdeasState) { tagIdeasState.ideas = []; renderTagIdeas({ now: true }); }
        setStatus(`Added ${data.added} voice tag${data.added === 1 ? "" : "s"}. Press Suggest again for a different take, or edit them in the box.`);
        if (note) {
          note.replaceChildren(`Added ${data.added} tag${data.added === 1 ? "" : "s"}. `);
          const undo = document.createElement("button");
          undo.type = "button";
          undo.className = "link-btn";
          undo.textContent = "Undo";
          undo.addEventListener("click", () => {
            dropTagOffers(offered, true);   // NEW (1.5.0): turned down
            input.value = before;
            input.dispatchEvent(new Event("input", { bubbles: true }));
            note.textContent = "Put back as you typed it.";
            input.focus();
          });
          note.append(undo);
        }
      } catch (err) {
        if (note) { note.classList.add("is-error"); note.textContent = err.message; }
        setStatus(err.message, true);
      } finally {
        buttons.forEach((b) => { b.disabled = false; b.classList.remove("is-busy"); });
        if (note) delete note.dataset.busy;
      }
    };
    buttons.forEach((b) => b.addEventListener("click", (e) => {
      if (b === quick && typeof autoTagsOn === "function" && autoTagsOn()) {
        // With Auto tags on there's nothing to suggest: show the options.
        const more = $("voiceTagBtn");
        if (more) more.click();
        return;
      }
      run(e);
    }));
  }
  // Shown only for an ElevenLabs voice: the voice chip's name changes
  // whenever the voice or the profile does.
  const name = $("voiceTriggerName");
  if (name && typeof MutationObserver === "function") {
    new MutationObserver(updateVoiceTagButton).observe(name, { childList: true, characterData: true, subtree: true });
  }
  updateVoiceTagButton();
})();

// ---------------------------------------------------------------------------
// NEW (1.5.0): the personality maker
//
// Above each personality box (the profile editor's, and the default one in
// Settings > Replies):
//
//   * a line to describe a personality in a few words; Create has the AI
//     you've set up for replies (Ollama or OpenAI) write the whole thing
//   * ideas to add, worked out from what's written so far and from how the
//     profile has actually been talking in the conversation. Click one to
//     put it in; × turns it down and it isn't suggested again; Add all has
//     the AI weave every idea in at once
//   * Undo for anything the AI wrote
// ---------------------------------------------------------------------------

function recentTurnsFor(speakerName, limit = 6) {
  // The last few exchanges with this profile, from the kept conversation.
  const out = [];
  const records = typeof transcript !== "undefined" && Array.isArray(transcript) ? transcript : [];
  for (let i = 0; i < records.length; i++) {
    const r = records[i];
    if (!r || r.kind !== "turn" || r.who !== speakerName) continue;
    const prev = records[i - 1];
    const you = prev && prev.kind === "turn" && prev.who === "You" ? prev.text : "";
    out.push({ you, reply: (r.opts && r.opts.voiced) || r.text });
  }
  return out.slice(-limit);
}

function makePersonalityHelper(textarea, getContext, storageKey) {
  if (!textarea) return null;
  const root = document.createElement("div");
  root.className = "pm";
  root.innerHTML = `
    <div class="pm-create">
      <svg class="icon-16 pm-create-icon" aria-hidden="true"><use href="#i-sparkle"/></svg>
      <input type="text" class="pm-idea" maxlength="600" autocomplete="off"
             placeholder="Describe a personality, e.g. a sleepy pirate who loves cats" aria-label="Describe a personality">
      <button type="button" class="btn btn-sm pm-create-btn">Create</button>
    </div>
    <div class="pm-ideas is-hidden">
      <div class="pm-ideas-head">
        <span class="pm-ideas-title">Ideas to add</span>
        <span class="pm-ideas-actions">
          <button type="button" class="link-btn pm-all">Add all</button>
          <button type="button" class="pm-refresh" title="Other ideas" aria-label="Other ideas">
            <svg class="icon-14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/></svg>
          </button>
        </span>
      </div>
      <div class="pm-chips" role="list"></div>
    </div>
    <p class="pm-status" aria-live="polite"></p>`;
  textarea.parentNode.insertBefore(root, textarea);

  const idea = root.querySelector(".pm-idea");
  const createBtn = root.querySelector(".pm-create-btn");
  const ideasBox = root.querySelector(".pm-ideas");
  const chipsEl = root.querySelector(".pm-chips");
  const allBtn = root.querySelector(".pm-all");
  const refreshBtn = root.querySelector(".pm-refresh");
  const status = root.querySelector(".pm-status");

  let suggestions = [];
  let lastAsked = null;      // the text the current ideas are for
  let controller = null;
  let typingTimer = null;
  let caret = null;          // where you last were in the box
  let busy = false;

  // Turned-down and already-added ideas, remembered per profile so they
  // aren't offered again.
  function skipKey() { return "frivo_pm_skip_" + (storageKey() || "default"); }
  function loadSkip() {
    try { return JSON.parse(localStorage.getItem(skipKey()) || "[]"); } catch (e) { return []; }
  }
  function remember(label) {
    const list = loadSkip().filter((x) => x !== label);
    list.push(label);
    try { localStorage.setItem(skipKey(), JSON.stringify(list.slice(-30))); } catch (e) { /* not kept */ }
  }

  function say(text, { error = false, undo = null } = {}) {
    status.classList.toggle("is-error", error);
    status.replaceChildren(text || "");
    if (undo) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "link-btn";
      b.textContent = "Undo";
      b.addEventListener("click", () => {
        setText(undo, { quiet: true });
        say("Put back.");
        askForIdeas({ force: true });
      });
      status.append(" ", b);
    }
  }

  function setText(value, { quiet = false } = {}) {
    textarea.value = value;
    // So Settings saves it, and anything else listening hears it.
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    if (!quiet) textarea.scrollTop = textarea.scrollHeight;
  }

  function context() {
    const c = getContext() || {};
    return {
      name: c.name || "",
      response_style: c.style || "echo",
      language: c.language || "",
      recent: recentTurnsFor(c.speaker || c.name || "Voice"),
    };
  }

  function renderChips() {
    chipsEl.replaceChildren();
    suggestions.forEach((s) => {
      const chip = document.createElement("span");
      chip.className = "pm-chip";
      chip.setAttribute("role", "listitem");
      const add = document.createElement("button");
      add.type = "button";
      add.className = "pm-chip-add";
      add.title = s.text;
      add.innerHTML = '<span class="pm-chip-plus" aria-hidden="true">+</span>';
      add.append(s.label);
      add.addEventListener("click", () => insertIdea(s, chip));
      const no = document.createElement("button");
      no.type = "button";
      no.className = "pm-chip-no";
      no.title = "Not this one";
      no.setAttribute("aria-label", `Don't suggest "${s.label}"`);
      no.textContent = "×";
      no.addEventListener("click", () => {
        remember(s.label);
        dropChip(s, chip);
      });
      chip.append(add, no);
      chipsEl.append(chip);
    });
    ideasBox.classList.toggle("is-hidden", !suggestions.length && !root.classList.contains("is-thinking"));
    allBtn.disabled = suggestions.length < 2;
  }

  function dropChip(s, chip) {
    suggestions = suggestions.filter((x) => x !== s);
    chip.classList.add("is-leaving");
    setTimeout(() => {
      chip.remove();
      if (!suggestions.length) ideasBox.classList.add("is-hidden");
      allBtn.disabled = suggestions.length < 2;
    }, 180);
  }

  // Where an idea goes: at the end of the sentence your cursor is in, or
  // at the end if you haven't been in the box.
  function insertIdea(s, chip) {
    const value = textarea.value;
    let at = value.length;
    if (caret != null && caret < value.length) {
      const rest = value.slice(caret);
      const m = rest.match(/[.!?](?=\s)|\n/);
      at = m ? caret + m.index + (m[0] === "\n" ? 0 : 1) : value.length;
    }
    const before = value.slice(0, at).replace(/[ \t]+$/, "");
    const after = value.slice(at).replace(/^[ \t]+/, "");
    const lead = before ? (/\n$/.test(before) ? "" : " ") : "";
    const trail = after && !/^\s/.test(after) ? " " : "";
    const next = before + lead + s.text + trail + after;
    const previous = value;
    setText(next, { quiet: true });
    caret = (before + lead + s.text).length;
    try { textarea.setSelectionRange(caret, caret); } catch (e) { /* not focused */ }
    remember(s.label);
    lastAsked = next;   // still fresh: the rest of the ideas still apply
    dropChip(s, chip);
    say(`Added "${s.label}".`, { undo: previous });
  }

  async function askForIdeas({ force = false } = {}) {
    const text = textarea.value.trim();
    const c = context();
    if (c.response_style === "mimic") {
      suggestions = [];
      renderChips();
      if (text.length >= 15) say("Word for word says exactly what you type, so this profile doesn't use a personality.");
      return;
    }
    if (text.length < 15) {
      suggestions = [];
      lastAsked = null;
      renderChips();
      return;
    }
    if (!force && lastAsked === text) return;
    if (controller) controller.abort();
    controller = new AbortController();
    const mine = controller;
    lastAsked = text;
    root.classList.add("is-thinking");
    ideasBox.classList.remove("is-hidden");
    if (!suggestions.length) chipsEl.innerHTML = '<span class="pm-thinking">Thinking of ideas…</span>';
    try {
      const res = await fetch("/api/personality/suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, ...c, skip: loadSkip() }),
        signal: mine.signal,
      });
      const data = await res.json();
      if (mine !== controller) return;
      if (!res.ok) throw new Error(data.error || "Couldn't get ideas.");
      suggestions = data.suggestions || [];
      root.classList.remove("is-thinking");
      renderChips();
      if (!suggestions.length) say("No new ideas right now. It covers a lot already.");
      else if (data.used_conversation) root.querySelector(".pm-ideas-title").textContent = "Ideas to add, from the personality and your conversation";
      else root.querySelector(".pm-ideas-title").textContent = "Ideas to add";
    } catch (err) {
      if (err.name === "AbortError") return;
      if (mine !== controller) return;
      root.classList.remove("is-thinking");
      suggestions = [];
      renderChips();
      lastAsked = null;
      say(err.message, { error: true });
    } finally {
      if (mine === controller) controller = null;
    }
  }

  async function create() {
    const text = idea.value.trim();
    if (text.length < 3) {
      say("Describe it in a few words first, like \"a grumpy wizard who hates mornings\".", { error: true });
      idea.focus();
      return;
    }
    if (busy) return;
    busy = true;
    const previous = textarea.value;
    const c = context();
    createBtn.disabled = true;
    createBtn.textContent = "Writing…";
    root.classList.add("is-writing");
    say("");
    try {
      const res = await fetch("/api/personality/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idea: text, ...c, current: previous, build_on: Boolean(previous.trim()) }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Couldn't write it.");
      setText(data.text, { quiet: true });
      textarea.scrollTop = 0;   // read it from the start
      if (typeof popOnce === "function") popOnce(textarea);
      const by = data.engine ? ` by ${data.engine}` : "";
      say(previous.trim() ? `Rewritten${by}, keeping what fit.` : `Written${by}.`, { undo: previous });
      askForIdeas({ force: true });
    } catch (err) {
      say(err.message, { error: true });
    } finally {
      busy = false;
      createBtn.disabled = false;
      createBtn.textContent = "Create";
      root.classList.remove("is-writing");
    }
  }

  async function addAll() {
    if (busy || suggestions.length < 2) return;
    busy = true;
    const previous = textarea.value;
    const taking = suggestions.slice();
    allBtn.disabled = true;
    root.classList.add("is-writing");
    say("Working them in…");
    try {
      const res = await fetch("/api/personality/merge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: previous, additions: taking.map((s) => s.text) }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Couldn't add them.");
      setText(data.text);
      taking.forEach((s) => remember(s.label));
      suggestions = [];
      renderChips();
      say(data.woven ? `Worked in ${taking.length} ideas.` : `Added ${taking.length} ideas at the end.`, { undo: previous });
      lastAsked = null;
      askForIdeas({ force: true });
    } catch (err) {
      say(err.message, { error: true });
    } finally {
      busy = false;
      allBtn.disabled = suggestions.length < 2;
      root.classList.remove("is-writing");
    }
  }

  createBtn.addEventListener("click", create);
  idea.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); create(); }
  });
  allBtn.addEventListener("click", addAll);
  refreshBtn.addEventListener("click", () => askForIdeas({ force: true }));
  ["keyup", "click", "select", "blur"].forEach((type) =>
    textarea.addEventListener(type, () => { caret = textarea.selectionStart; }));
  // New ideas a moment after you stop typing, once you've changed enough.
  textarea.addEventListener("input", (e) => {
    if (!e.isTrusted) return;
    clearTimeout(typingTimer);
    typingTimer = setTimeout(() => {
      const now = textarea.value.trim();
      const before = lastAsked || "";
      const changed = Math.abs(now.length - before.length) >= 25
        || now.split(/\s+/).filter((w) => !before.includes(w)).length >= 6;
      if (changed) askForIdeas();
    }, 2500);
  });

  return {
    el: root,
    reset({ fetch = true } = {}) {
      if (controller) controller.abort();
      controller = null;
      clearTimeout(typingTimer);
      suggestions = [];
      lastAsked = null;
      caret = null;
      idea.value = "";
      say("");
      root.classList.remove("is-thinking", "is-writing");
      renderChips();
      if (fetch) askForIdeas();
    },
    ask: askForIdeas,
  };
}

(function wirePersonalityMakers() {
  const profileBox = $("profileSystemPrompt");
  window.frivoProfilePersonality = makePersonalityHelper(
    profileBox,
    () => {
      const editing = typeof editingProfileId !== "undefined" && editingProfileId
        ? allProfiles.find((p) => p.id === editingProfileId) : null;
      return {
        name: $("profileName") ? $("profileName").value.trim() : "",
        speaker: editing ? editing.name : "",
        style: getRadioValue(profileResponseStyleRadios, "echo"),
        language: $("profileLanguageSelect") ? $("profileLanguageSelect").value : "",
      };
    },
    () => (typeof editingProfileId !== "undefined" && editingProfileId) || "new",
  );
  const settingsBox = $("systemPrompt");
  const helper = makePersonalityHelper(
    settingsBox,
    () => ({
      name: "",
      speaker: "Voice",
      style: typeof responseStyleRadios !== "undefined" ? getRadioValue(responseStyleRadios, "echo") : "echo",
      language: typeof currentLanguage !== "undefined" ? currentLanguage : "",
    }),
    () => "default",
  );
  window.frivoSettingsPersonality = helper;
  // Settings asks for ideas when you get to the box, not on every page load
  // (with Ollama, asking loads the model onto the graphics card).
  if (helper && settingsBox && typeof IntersectionObserver === "function") {
    let asked = false;
    new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting) && !asked) {
        asked = true;
        helper.ask();
      }
    }).observe(settingsBox);
  }
})();


// ---------------------------------------------------------------------------
// NEW (1.5.0): voice-tag ideas as you type
//
// With an ElevenLabs voice, a moment after you stop typing (four words or
// more), the AI looks at the message and suggests where a tag would fit.
// The ideas show just above the message box: click one to put it in, Add
// all for every one, × to hide them for this message. Each idea knows
// which word it goes before, so it still lands in the right place if you
// typed somewhere else meanwhile, and disappears if that part changed.
// "Suggest tags as I type" in the ✦ menu turns it off.
// ---------------------------------------------------------------------------

var TAG_IDEAS_KEY = "frivo_tag_ideas";
// CHANGED (1.5.0): live. The AI is asked when a sentence ends or after a
// short pause, with the whole message in view. Every idea keeps the words
// it was made for, so it lands in the right place however late it
// arrives, goes away when you put that tag in yourself, and follows its
// word when the box scrolls.
var tagIdeasState = {
  ideas: [],            // [{ tag, at, words, key }]
  nodes: new Map(),     // key -> { pill, mark, idea }
  asked: "",            // the words last asked of the AI
  answered: "",         // the words the AI's current answer is for
  timer: null,
  inFlight: false,
  again: false,         // more was typed while asking: ask once more after
  lastAskAt: 0,
  paused: false,        // × pressed: none for this message
  hideTimer: null,
  aiDown: false,        // the AI couldn't answer: quick ideas stay
};

function tagIdeasOn() {
  try { return localStorage.getItem(TAG_IDEAS_KEY) !== "off"; } catch (e) { return true; }
}

// The words that are said (tags left out), each with where it starts and
// whether a tag already sits right before it.
function spokenWords(text) {
  const out = [];
  const re = /\[[^\]\n]*\]|\S+/g;
  let m;
  let tagBefore = false;
  while ((m = re.exec(text))) {
    if (/^\[[A-Za-z][A-Za-z' \-]{0,38}\]$/.test(m[0])) { tagBefore = true; continue; }
    out.push({ word: m[0], start: m.index, end: m.index + m[0].length, tagged: tagBefore });
    tagBefore = false;
  }
  out.endsWithTag = /\]\s*$/.test(text);
  return out;
}

function clearTagIdeas() {
  const st = tagIdeasState;
  clearTimeout(st.timer);
  st.ideas = [];
  st.asked = "";
  st.answered = "";
  st.again = false;
  st.paused = false;
  st.aiDown = false;
  renderTagIdeas({ now: true });
}

// Where an idea goes, or null when it no longer applies: the words up to
// and including the one it goes before must still be the same, and that
// word mustn't already have a tag in front of it (you put one in). One
// meant for the end only fits while nothing's been added.
function tagIdeaPlace(idea) {
  const input = $("messageInput");
  if (!input) return null;
  const now = spokenWords(input.value);
  const then = idea.words || [];
  const upto = Math.min(idea.at + 1, then.length);
  for (let i = 0; i < upto; i++) {
    if (!now[i] || now[i].word !== then[i]) return null;
  }
  if (idea.at < then.length) {
    if (idea.at >= now.length || now[idea.at].tagged) return null;
    return { offset: now[idea.at].start, end: false };
  }
  if (now.length !== then.length || !now.length || now.endsWithTag) return null;
  return { offset: now[now.length - 1].end, end: true };
}

function putTagIdea(idea) {
  const input = $("messageInput");
  const place = tagIdeaPlace(idea);
  if (!input || !place) return false;
  const v = input.value;
  input.value = place.end
    ? v.slice(0, place.offset) + ` [${idea.tag}]` + v.slice(place.offset)
    : v.slice(0, place.offset) + `[${idea.tag}] ` + v.slice(place.offset);
  return true;
}

// Where a stretch of the message box's text is drawn, in the box's own
// coordinates (the message box is the positioning parent).
var tagMeasureCtx = null;
function textWidthIn(input, str) {
  if (!tagMeasureCtx) tagMeasureCtx = document.createElement("canvas").getContext("2d");
  const cs = getComputedStyle(input);
  tagMeasureCtx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
  tagMeasureCtx.letterSpacing = cs.letterSpacing === "normal" ? "0px" : cs.letterSpacing;
  return tagMeasureCtx.measureText(str).width;
}
// CHANGED (1.5.0): the box wraps onto several lines now, so a copy of it
// (laid out the same, out of sight) says where each word is drawn: x across
// the composer, y down from the top of the box's text. A word scrolled out
// of the box is "left" (above) or "right" (below).
var tagMirror = null;
var MIRROR_PROPS = ["fontFamily", "fontSize", "fontWeight", "fontStyle", "letterSpacing", "lineHeight",
  "textTransform", "wordSpacing", "textIndent", "tabSize", "paddingTop", "paddingRight", "paddingBottom",
  "paddingLeft", "whiteSpace", "overflowWrap", "wordBreak"];
function textBoxIn(input, start, end, width) {   // width: measure as if this wide
  if (!tagMirror) {
    tagMirror = document.createElement("div");
    tagMirror.setAttribute("aria-hidden", "true");
    tagMirror.style.cssText = "position:absolute;left:-9999px;top:0;visibility:hidden;overflow:hidden;"
      + "border:0;box-sizing:border-box;";
    document.body.appendChild(tagMirror);
  }
  const cs = getComputedStyle(input);
  MIRROR_PROPS.forEach((p) => { tagMirror.style[p] = cs[p]; });
  if (input.tagName === "TEXTAREA") {
    tagMirror.style.whiteSpace = "pre-wrap";
    tagMirror.style.overflowWrap = "break-word";
  } else {
    tagMirror.style.whiteSpace = "pre";
  }
  tagMirror.style.width = `${width || input.clientWidth}px`;
  const v = input.value;
  const mark = document.createElement("span");
  mark.textContent = v.slice(start, end) || "\u200b";
  tagMirror.replaceChildren(document.createTextNode(v.slice(0, start)), mark, document.createTextNode(v.slice(end) || " "));
  const padTop = parseFloat(cs.paddingTop || 0);
  const padBottom = parseFloat(cs.paddingBottom || 0);
  const left = input.offsetLeft + input.clientLeft;
  const x = left + mark.offsetLeft - input.scrollLeft;
  const w = Math.max(6, mark.offsetWidth);
  const h = mark.offsetHeight || parseFloat(cs.lineHeight) || 22;
  const y = mark.offsetTop - input.scrollTop;   // from the top of the box's padding
  let side = "";
  if (input.tagName === "TEXTAREA") {
    if (y + h <= padTop + 2) side = "left";
    else if (y >= input.clientHeight - padBottom - 2) side = "right";
  } else {
    const right = left + input.clientWidth;
    side = x + w <= left + 2 ? "left" : x >= right - 2 ? "right" : "";
  }
  return { x, w, y, h, visible: !side, side, left, rawX: x + input.scrollLeft, rawY: mark.offsetTop };
}

function fadeOut(el) {
  if (!el) return;
  el.classList.add("is-leaving");
  setTimeout(() => el.remove(), 170);
}

// Pills and marks are kept between updates, so one that still fits stays
// put (gliding if its word moved) instead of blinking. Ideas for words
// scrolled out of view are counted on a small arrow at that edge, which
// scrolls to them.
function renderTagIdeas({ now = false } = {}) {
  const float = $("tagIdeas");
  const pills = $("tagIdeasChips");
  const marks = $("tagMarks");
  const input = $("messageInput");
  if (!float || !pills || !marks || !input) return;
  // CHANGED (1.5.0): with the rich box, the ideas are ghost tags in the
  // text itself (richRenderGhosts), not pills over the words.
  if (typeof richActive === "function" && richActive()) {
    tagIdeasState.ideas = tagIdeasState.ideas.filter((idea) => tagIdeaPlace(idea));
    float.classList.add("is-hidden");
    marks.classList.add("is-hidden");
    const composer = input.closest(".composer");
    if (composer) composer.classList.remove("has-tag-ideas");
    richRenderGhosts();
    return;
  }
  const st = tagIdeasState;
  st.ideas = st.ideas.filter((idea) => tagIdeaPlace(idea));
  const composer = input.closest(".composer");
  const words = spokenWords(input.value);
  const wanted = new Map();
  const offscreen = { left: [], right: [] };
  st.ideas.forEach((idea) => {
    const atEnd = idea.at >= (idea.words || []).length;
    const word = atEnd ? null : words[idea.at];
    const box = word
      ? textBoxIn(input, word.start, word.end)
      : textBoxIn(input, input.value.length, input.value.length);
    if (box.visible) wanted.set(idea.key, { idea, word, box });
    else offscreen[box.side].push({ idea, box });
  });
  ["left", "right"].forEach((side) => {
    if (offscreen[side].length) wanted.set(`edge-${side}`, { edge: side, list: offscreen[side] });
  });

  // Gone: fade out.
  st.nodes.forEach((node, key) => {
    if (wanted.has(key)) return;
    fadeOut(node.pill);
    fadeOut(node.mark);
    st.nodes.delete(key);
  });

  if (wanted.size) {
    clearTimeout(st.hideTimer);
    st.hideTimer = null;
    float.classList.remove("is-hidden");
    marks.classList.remove("is-hidden");
    if (composer) composer.classList.add("has-tag-ideas");
  }
  // The marks line up with the text by its distance from the bottom, which
  // doesn't change while the box grows to make room for the ideas.
  if (composer) {
    marks.style.top = "auto";
    marks.style.bottom = `${composer.clientHeight - input.offsetTop - input.offsetHeight}px`;
    marks.style.height = `${input.offsetHeight}px`;
  }

  const placed = [];
  const edges = {};
  wanted.forEach((want, key) => {
    let node = st.nodes.get(key);
    if (want.edge) {
      if (!node) {
        const pill = document.createElement("button");
        pill.type = "button";
        pill.className = `tag-pill tag-pill--edge is-${want.edge}`;
        node = { pill, mark: null, list: want.list };
        pill.addEventListener("click", () => {
          // Scroll the box so the nearest hidden word is in view.
          const target = node.list.slice().sort((a, b) =>
            want.edge === "left" ? b.box.rawX - a.box.rawX : a.box.rawX - b.box.rawX)[0];
          if (!target) return;
          const cs = getComputedStyle(input);
          if (input.tagName === "TEXTAREA") {   // CHANGED (1.5.0): up or down
            const near = node.list.slice().sort((a, b) =>
              want.edge === "left" ? b.box.rawY - a.box.rawY : a.box.rawY - b.box.rawY)[0];
            input.scrollTop = want.edge === "left"
              ? Math.max(0, near.box.rawY - parseFloat(cs.paddingTop || 0) - 4)
              : near.box.rawY + near.box.h - input.clientHeight + parseFloat(cs.paddingBottom || 0) + 4;
            renderTagIdeas();
            return;
          }
          const pad = parseFloat(cs.paddingLeft || 0) + 24;
          input.scrollLeft = want.edge === "left"
            ? Math.max(0, target.box.rawX - (input.offsetLeft + pad))
            : Math.max(0, target.box.rawX + target.box.w - (input.offsetLeft + input.clientWidth) + pad);
          renderTagIdeas();
        });
        pills.append(pill);
        st.nodes.set(key, node);
      }
      node.list = want.list;
      const n = want.list.length;
      const tall = input.tagName === "TEXTAREA";   // CHANGED (1.5.0)
      node.pill.textContent = want.edge === "left" ? `${tall ? "↑" : "‹"} ${n}` : `${n} ${tall ? "↓" : "›"}`;
      node.pill.title = `${n} idea${n === 1 ? "" : "s"} for words scrolled out of view. Click to see.`;
      edges[want.edge] = node.pill;
      return;
    }
    const { idea, word, box } = want;
    if (!node) {
      const pill = document.createElement("button");
      pill.type = "button";
      pill.className = "tag-pill";
      pill.textContent = idea.tag;
      node = { pill, mark: null, idea };
      pill.addEventListener("click", () => applyTagIdeas([node.idea]));
      const hot = (on) => { if (node.mark) node.mark.classList.toggle("is-hot", on); };
      pill.addEventListener("pointerenter", () => hot(true));
      pill.addEventListener("pointerleave", () => hot(false));
      pill.addEventListener("focus", () => hot(true));
      pill.addEventListener("blur", () => hot(false));
      pills.append(pill);
      if (word) {
        node.mark = document.createElement("span");
        node.mark.className = "tag-mark";
        marks.append(node.mark);
      }
      st.nodes.set(key, node);
    }
    node.idea = idea;
    node.pill.title = word ? `Put [${idea.tag}] before “${word.word}”` : `Put [${idea.tag}] at the end`;
    if (node.mark) {
      node.mark.style.left = `${box.x - 3}px`;
      node.mark.style.width = `${box.w + 6}px`;
      // CHANGED (1.5.0): on the word's own line.
      node.mark.style.top = `${input.clientTop + box.y - 1}px`;
      node.mark.style.height = `${box.h + 2}px`;
    }
    placed.push({ pill: node.pill, center: box.x + (word ? box.w / 2 : 0) });
  });

  // Each pill sits centred over its word, without overlapping the one
  // before; the edge arrows hold the ends.
  const limit = pills.clientWidth || float.clientWidth;
  let edge = 0;
  let cap = limit;
  if (edges.left) { edges.left.style.left = "0px"; edge = edges.left.offsetWidth + 4; }
  if (edges.right) { cap = limit - edges.right.offsetWidth - 4; edges.right.style.left = `${Math.max(0, cap + 4)}px`; }
  placed.sort((a, b) => a.center - b.center).forEach(({ pill, center }) => {
    const w = pill.offsetWidth;
    let left = Math.round(center - w / 2);
    left = Math.max(left, edge, 0);
    left = Math.min(left, Math.max(0, cap - w));
    pill.style.left = `${left}px`;
    pill.style.setProperty("--point", `${Math.round(Math.min(Math.max(center - left, 8), w - 8))}px`);
    edge = left + w + 4;
  });
  const all = $("tagIdeasAll");
  if (all) all.classList.toggle("is-hidden", st.ideas.length < 2);

  if (!wanted.size) {
    // Held open a moment, so the box doesn't jump while new ideas are on
    // their way.
    const close = () => {
      st.hideTimer = null;
      if (st.nodes.size) return;
      float.classList.add("is-hidden");
      marks.classList.add("is-hidden");
      if (composer) composer.classList.remove("has-tag-ideas");
    };
    if (now || !input.value.trim()) close();
    else if (!st.hideTimer) st.hideTimer = setTimeout(close, st.inFlight ? 1600 : 900);
  }
}

function applyTagIdeas(list) {
  const input = $("messageInput");
  if (!input) return;
  // Last first, so putting one in doesn't move where the others go.
  const sorted = list.slice().sort((a, b) => b.at - a.at);
  let any = false;
  sorted.forEach((idea) => { if (putTagIdea(idea)) { any = true; noteTagOffers([idea.tag]); } });   // CHANGED (1.5.0): offered
  tagIdeasState.ideas = tagIdeasState.ideas.filter((i) => !list.includes(i));
  if (any) {
    if (typeof cancelAutoSend === "function") cancelAutoSend();
    if (typeof setTypedByHand === "function") setTypedByHand(true);
    input.focus();
    try { input.setSelectionRange(input.value.length, input.value.length); } catch (e) { /* fine */ }
  }
  renderTagIdeas({ now: !tagIdeasState.ideas.length });
}

function tagIdeaKey(idea) {
  return `${idea.tag}@${idea.at}:${(idea.words || [])[idea.at] || "end"}`;
}

function withWords(list, words) {
  return list.map((idea) => {
    const full = { tag: idea.tag, at: idea.at, words };
    full.key = tagIdeaKey(full);
    return full;
  });
}


async function askTagIdeas() {
  const input = $("messageInput");
  const st = tagIdeasState;
  if (!input || !tagIdeasOn() || st.paused) return;
  const wrap = $("voiceTagWrap");
  if (!wrap || wrap.classList.contains("is-hidden")) return;   // not an ElevenLabs voice
  const words = spokenWords(input.value).map((w) => w.word);
  const key = words.join(" ");
  if (words.length < 3 || key === st.asked) return;
  if (st.inFlight) { st.again = true; return; }   // asked again when this answer is in
  st.inFlight = true;
  st.asked = key;
  st.lastAskAt = Date.now();
  wrap.classList.add("is-thinking");
  try {
    const res = await fetch("/api/voice-tags/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: input.value, profile_id: currentProfileId || null, session_id: sessionId, light: true }),   // CHANGED (1.5.0): a shorter ask, often
    });
    const data = await res.json();
    if (!st.paused && input.value.trim()) {
      if (res.ok) {
        st.aiDown = false;
        st.answered = key;
        // The AI's view replaces the last one and Frivo's quick guesses;
        // an idea that's the same keeps its pill.
        st.ideas = withWords((data.ideas || []).slice(0, 4), words);
        renderTagIdeas();
      } else {
        st.aiDown = true;   // the quick ideas stay up
      }
    }
  } catch (err) {
    st.aiDown = true;
  } finally {
    st.inFlight = false;
    wrap.classList.remove("is-thinking");
    if (st.again) {
      st.again = false;
      askTagIdeas();
    }
  }
}

// Anything that changes the message box calls this: typing, dictation,
// the picker, a click in the dictation history.
function messageBoxChanged() {
  const input = $("messageInput");
  const st = tagIdeasState;
  if (!input) return;
  if (!input.value.trim()) { clearTagIdeas(); return; }
  const wrap = $("voiceTagWrap");
  if (!tagIdeasOn() || autoTagsOn() || !wrap || wrap.classList.contains("is-hidden")) return;   // Auto tags: no need
  renderTagIdeas();   // moves the ideas along, and drops any whose word changed
  clearTimeout(st.timer);
  // CHANGED (1.5.0): asked when a sentence ends, or after a short pause,
  // so the AI sees whole thoughts rather than half a sentence (one
  // question at a time; anything typed meanwhile is asked about as soon
  // as the answer is in).
  const sentenceEnd = /[.!?]["')\]]*\s*$/.test(input.value);
  st.timer = setTimeout(askTagIdeas, sentenceEnd ? 120 : 800);
}

var AUTO_TAGS_KEY = "frivo_auto_tags";
function autoTagsOn() {
  try { return localStorage.getItem(AUTO_TAGS_KEY) === "on"; } catch (e) { return false; }
}
function showAutoTagsState() {
  const on = autoTagsOn();
  const split = $("tagSplit");
  const label = $("tagSplitLabel");
  const main = $("voiceTagSuggestQuick");
  if (split) split.classList.toggle("is-auto", on);
  if (label) label.textContent = on ? "Auto tags on" : "Suggest tags";   // CHANGED (1.7.0)
  if (main) main.title = on
    ? "Auto tags is on: the AI tags every message as it's spoken. Click for the options."
    : "The AI adds voice tags that fit what you've typed. Your words stay the same.";
}

(function wireTagIdeas() {
  const input = $("messageInput");
  const auto = $("autoTagsToggle");
  if (auto) {
    auto.checked = autoTagsOn();
    showAutoTagsState();
    auto.addEventListener("change", () => {
      try { localStorage.setItem(AUTO_TAGS_KEY, auto.checked ? "on" : "off"); } catch (e) { /* not kept */ }
      showAutoTagsState();
      if (auto.checked) clearTagIdeas(); else messageBoxChanged();
    });
  }
  const toggle = $("tagIdeasToggle");
  if (toggle) {
    toggle.checked = tagIdeasOn();
    toggle.addEventListener("change", () => {
      try { localStorage.setItem(TAG_IDEAS_KEY, toggle.checked ? "on" : "off"); } catch (e) { /* not kept */ }
      if (!toggle.checked) clearTagIdeas();
      else messageBoxChanged();
    });
  }
  const all = $("tagIdeasAll");
  if (all) all.addEventListener("click", () => applyTagIdeas(tagIdeasState.ideas));
  const close = $("tagIdeasClose");
  if (close) close.addEventListener("click", () => {
    tagIdeasState.paused = true;   // none for this message
    tagIdeasState.ideas = [];
    renderTagIdeas({ now: true });
  });
  if (!input) return;
  // The box scrolls sideways as a long message grows, so the ideas follow.
  ["scroll", "keyup", "click", "select"].forEach((type) => input.addEventListener(type, () => {
    if (tagIdeasState.nodes.size) renderTagIdeas();
  }));
  window.addEventListener("resize", () => { if (tagIdeasState.nodes.size) renderTagIdeas(); });
  // NEW (1.5.0): and when the box grows or shrinks a line.
  if (typeof ResizeObserver === "function") {
    new ResizeObserver(() => { if (tagIdeasState.nodes.size) renderTagIdeas(); }).observe(input);
  }
  input.addEventListener("input", messageBoxChanged);
})();

// ---------------------------------------------------------------------------
// NEW (1.5.0): the anchor (Settings > Voices): what the voice is being
// matched to, with Hear it and Make a new one. Shown only when Hold the
// accent is Anchor.
// ---------------------------------------------------------------------------

function showAnchorRows() {
  const mode = $("holdAccentRadios") ? getRadioValue($("holdAccentRadios"), "anchor") : "anchor";
  ["voiceAccentRow", "anchorRow"].forEach((id) => { const el = $(id); if (el) el.classList.toggle("is-hidden", mode !== "anchor"); });
}

var anchorAudio = null;
async function refreshAnchorStatus() {
  const status = $("anchorStatus");
  const hear = $("anchorHearBtn");
  if (!status) return;
  const voiceId = typeof activeVoiceId === "function" ? activeVoiceId() : "";
  if (!voiceId || voiceEngine({ voice_id: voiceId }) !== "elevenlabs") {
    status.textContent = "For ElevenLabs voices. The profile selected now has a free voice.";
    if (hear) hear.disabled = true;
    return;
  }
  try {
    const res = await fetch(`/api/voice-anchor?voice_id=${encodeURIComponent(voiceId)}&language=${encodeURIComponent(typeof currentLanguage !== "undefined" ? currentLanguage : "English")}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Couldn't check.");
    const name = typeof activeVoiceName === "function" ? activeVoiceName() : "this voice";
    if (!data.anchor) {
      status.textContent = `None yet for ${name}. It's made the first time ${name} speaks an expressive line (about 40 credits, once).`;
      if (hear) hear.disabled = true;
    } else {
      const accent = $("voiceAccentSelect");
      const accentName = accent && accent.options[accent.selectedIndex] && data.anchor.accent !== "auto"
        ? ` in a ${accent.options[accent.selectedIndex].textContent} accent` : "";
      status.textContent = `${name} said one plain sentence${accentName}; every expressive line is matched to it. If it came out wrong, make a new one.`;
      if (hear) { hear.disabled = !data.anchor.audio_url; hear.dataset.url = data.anchor.audio_url || ""; }
    }
  } catch (err) {
    status.textContent = err.message;
    if (hear) hear.disabled = true;
  }
}

(function wireAnchor() {
  const hear = $("anchorHearBtn");
  const remake = $("anchorRemakeBtn");
  const accent = $("voiceAccentSelect");
  if (hear) hear.addEventListener("click", () => {
    if (!hear.dataset.url) return;
    if (anchorAudio) { anchorAudio.pause(); anchorAudio = null; }
    anchorAudio = new Audio(hear.dataset.url);
    anchorAudio.play().catch(() => {});
  });
  if (remake) remake.addEventListener("click", async () => {
    const voiceId = typeof activeVoiceId === "function" ? activeVoiceId() : "";
    if (!voiceId) return;
    remake.disabled = true;
    const status = $("anchorStatus");
    if (status) status.textContent = "Making a new one…";
    try {
      // Save the accent first, so the new anchor is made in it.
      if (typeof saveAllSettings === "function") await saveAllSettings({ quiet: true });
      const res = await fetch("/api/voice-anchor", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ voice_id: voiceId, language: typeof currentLanguage !== "undefined" ? currentLanguage : "English" }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Couldn't make it.");
      await refreshAnchorStatus();
      if (hear && hear.dataset.url) hear.click();   // hear the new one straight away
    } catch (err) {
      if (status) status.textContent = err.message;
    } finally {
      remake.disabled = false;
    }
  });
  if (accent) accent.addEventListener("change", () => {
    // A new accent means a new anchor; the old one is only right for the old accent.
    const status = $("anchorStatus");
    if (status) status.textContent = "Accent changed: press Make a new one to hear the voice in it (the next expressive line makes one anyway).";
  });
  const name = $("voiceTriggerName");
  if (name && typeof MutationObserver === "function") {
    new MutationObserver(() => { if (settingsPanel && !settingsPanel.classList.contains("is-hidden")) refreshAnchorStatus(); })
      .observe(name, { childList: true, characterData: true, subtree: true });
  }
})();

// ---------------------------------------------------------------------------
// NEW (1.5.0): Tag words (Settings > Voices). One list for every profile
// with Shape words for tags on: a word or phrase, and the tag it becomes
// (or "AI picks"). Saved as it's changed.
// ---------------------------------------------------------------------------

var tagWordsState = null;
var TAG_WORD_DEFAULTS = ["lol", "haha", "lmao", "lmfao", "rofl", "hehe", "heh", "teehee", "omg", "ugh", "smh", "pfft"]
  .map((word) => ({ word, tag: "" }));
var TAG_SUGGESTIONS = ["laughs", "laughs hard", "chuckles", "giggles", "nervous laugh", "scoffs", "sighs", "groans",
  "gasps", "whispers", "excited", "sarcastic", "sad", "pause", "clears throat"];

// CHANGED (1.5.0): two sections, so "AI picks" isn't said twelve times:
// the words the AI picks a tag for, on one line; and the words with their
// own tag, one per row, the tag shown the way it looks in a message.
function renderTagWords() {
  const list = $("tagWordsList");
  const note = $("tagWordsNote");
  if (!list || !Array.isArray(tagWordsState)) return;
  list.replaceChildren();
  const removeEntry = (entry) => {
    tagWordsState = tagWordsState.filter((x) => x !== entry);
    renderTagWords();
    saveTagWords(`Removed "${entry.word}". It's read out as typed now.`);
  };
  const removeBtn = (entry) => {
    const x = document.createElement("button");
    x.type = "button";
    x.className = "tag-word-remove";
    x.title = `Remove "${entry.word}": it'll be read out as typed`;
    x.setAttribute("aria-label", `Remove ${entry.word}`);
    x.textContent = "×";
    x.addEventListener("click", () => removeEntry(entry));
    return x;
  };
  const picks = tagWordsState.filter((e) => !e.tag);
  const fixed = tagWordsState.filter((e) => e.tag);

  if (picks.length) {
    const sec = document.createElement("div");
    sec.className = "tag-words-section";
    const head = document.createElement("span");
    head.className = "tag-words-head";
    head.textContent = "The AI picks the tag from how it's meant";
    const line = document.createElement("div");
    line.className = "tag-words-line";
    picks.forEach((entry) => {
      const w = document.createElement("span");
      w.className = "tag-words-pick";
      const t = document.createElement("span");
      t.textContent = entry.word;
      w.append(t, removeBtn(entry));
      line.append(w);
    });
    sec.append(head, line);
    list.append(sec);
  }
  if (fixed.length) {
    const sec = document.createElement("div");
    sec.className = "tag-words-section";
    const head = document.createElement("span");
    head.className = "tag-words-head";
    head.textContent = "Always the same tag";
    sec.append(head);
    fixed.forEach((entry) => {
      const row = document.createElement("div");
      row.className = "tag-words-row";
      const w = document.createElement("span");
      w.className = "tag-words-word";
      w.textContent = entry.word;
      const arrow = document.createElement("span");
      arrow.className = "tag-words-arrow";
      arrow.setAttribute("aria-hidden", "true");
      arrow.textContent = "→";
      const tag = document.createElement("span");
      tag.className = "voice-tag";   // the same mark as in a message
      tag.dataset.tag = entry.tag;
      const gap = document.createElement("span");
      row.append(w, arrow, tag, gap, removeBtn(entry));
      sec.append(row);
    });
    list.append(sec);
  }
  if (!tagWordsState.length) {
    const empty = document.createElement("p");
    empty.className = "tag-words-empty";
    empty.textContent = "Nothing typed becomes a tag. Add a word below, or put back the defaults.";
    list.append(empty);
  }
  if (note && !note.dataset.flash) note.textContent = "";
}

async function saveTagWords(message) {
  const note = $("tagWordsNote");
  try {
    if (typeof saveAllSettings === "function") await saveAllSettings({ quiet: true });
    if (note && message) {
      note.dataset.flash = "1";
      note.textContent = message;
      setTimeout(() => { delete note.dataset.flash; renderTagWords(); }, 1800);
    }
  } catch (err) {
    if (note) note.textContent = "Couldn't save: " + err.message;
  }
}

(function wireTagWords() {
  const form = $("tagWordsForm");
  const wordIn = $("tagWordsWord");
  const tagIn = $("tagWordsTag");
  const reset = $("tagWordsReset");
  const options = $("tagWordsTagList");
  if (options) {
    TAG_SUGGESTIONS.forEach((t) => { const o = document.createElement("option"); o.value = t; options.append(o); });
  }
  if (form && wordIn && tagIn) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const word = wordIn.value.replace(/\s+/g, " ").trim().toLowerCase();
      const tag = tagIn.value.replace(/[\[\]]/g, "").replace(/\s+/g, " ").trim().toLowerCase();
      const note = $("tagWordsNote");
      if (!word) { wordIn.focus(); return; }
      if (tag && !/^[a-z][a-z' \-]{0,37}$/.test(tag)) {
        if (note) note.textContent = "A tag is a word or two of letters, like laughs or nervous laugh.";
        tagIn.focus();
        return;
      }
      if (!Array.isArray(tagWordsState)) tagWordsState = TAG_WORD_DEFAULTS.slice();
      const existing = tagWordsState.findIndex((x) => x.word === word);
      if (existing >= 0) tagWordsState[existing] = { word, tag };
      else tagWordsState = tagWordsState.concat([{ word, tag }]);
      wordIn.value = "";
      tagIn.value = "";
      renderTagWords();
      saveTagWords(existing >= 0 ? `Updated "${word}".` : `Added "${word}".`);
      wordIn.focus();
    });
    // Enter in the tag box adds, too; in the word box it moves to the tag.
    wordIn.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && wordIn.value.trim()) { e.preventDefault(); tagIn.focus(); }
    });
  }
  if (reset) reset.addEventListener("click", () => {
    tagWordsState = TAG_WORD_DEFAULTS.map((x) => ({ ...x }));
    renderTagWords();
    saveTagWords("Defaults put back.");
  });
})();


// ---------------------------------------------------------------------------
// NEW (1.5.0): better tags, on the page.
//
//   * Tag amount (Settings > Voices, and each profile).
//   * Your tag taste: the tags Suggest and the live ideas offered are
//     remembered until you send. Sent = kept, deleted (or Undo) = removed,
//     any other tag you sent = added. Frivo counts these and the AI leans
//     towards what you keep. Settings shows it, with a way to forget it.
//   * Retake, on a spoken reply: say it again the same, without tags, or
//     with different tags. The words stay; the new take replaces the old.
// ---------------------------------------------------------------------------
var tagAmounts = [
  { id: "subtle", name: "Subtle", description: "A tag only where it really counts. Often none." },
  { id: "normal", name: "Normal", description: "A tag or two where the feeling clearly calls for one." },
  { id: "dramatic", name: "Dramatic", description: "Plenty of tags and bold choices: a performance." },
];

function tagAmountNote(id) {
  const a = tagAmounts.find((x) => x.id === id);
  return a ? a.description : "";
}

function tagsIn(text) {
  const out = [];
  const re = /\[([A-Za-z][A-Za-z' \-]{0,38})\]/g;
  let m;
  while ((m = re.exec(String(text || "")))) out.push(m[1].toLowerCase().replace(/\s+/g, " ").trim());
  return out;
}

var tagOffers = new Set();

function noteTagOffers(tags) {
  (tags || []).forEach((t) => tagOffers.add(String(t).toLowerCase()));
}

function postTagFeedback(body) {
  if (!["kept", "removed", "added"].some((k) => body[k] && body[k].length)) return;
  fetch("/api/voice-tags/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(() => { tagTasteStale = true; }).catch(() => { /* taste is a nicety */ });
}

function dropTagOffers(tags, removed) {
  (tags || []).forEach((t) => tagOffers.delete(String(t).toLowerCase()));
  if (removed) postTagFeedback({ removed: tags });
}

// Called by send(), with the message as it goes.
function reportTagTaste(message) {
  const sent = Array.from(new Set(tagsIn(message)));
  const offered = Array.from(tagOffers);
  tagOffers = new Set();
  const wrap = $("voiceTagWrap");
  if (!wrap || wrap.classList.contains("is-hidden")) return;   // not an ElevenLabs voice
  postTagFeedback({
    kept: sent.filter((t) => offered.includes(t)),
    removed: offered.filter((t) => !sent.includes(t)),
    added: sent.filter((t) => !offered.includes(t)),
  });
}

var tagTasteStale = true;

async function loadTagTaste() {
  const list = $("tagTasteList");
  const note = $("tagTasteNote");
  if (!list) return;
  let data;
  try {
    const res = await fetch("/api/voice-tags/taste");
    data = await res.json();
    if (!res.ok) return;
  } catch (err) {
    return;
  }
  tagTasteStale = false;
  const liked = data.liked || [];
  const avoided = data.avoided || [];
  list.replaceChildren();
  const chip = (tag, kind) => {
    const el = document.createElement("span");
    el.className = `taste-chip is-${kind}`;
    el.textContent = tag;
    el.title = kind === "liked" ? "You keep or add this one: the AI leans towards it."
      : "You usually remove this one: the AI avoids it" + ((data.never || []).includes(tag) ? ", and Frivo takes it out." : ".");
    return el;
  };
  liked.forEach((t) => list.append(chip(t, "liked")));
  avoided.forEach((t) => list.append(chip(t, "avoided")));
  list.classList.toggle("is-hidden", !liked.length && !avoided.length);
  const reset = $("tagTasteReset");
  if (reset) reset.classList.toggle("is-hidden", !data.counted);
  if (note) {
    note.textContent = liked.length || avoided.length
      ? "Learned from the tags you keep and remove. The AI leans towards the green ones and away from the red."
      : data.counted
        ? "Still learning: keep or delete a few more suggested tags."
        : "Frivo learns which tags you like from the ones you keep and remove after Suggest.";
  }
}

(function wireTagTaste() {
  const reset = $("tagTasteReset");
  if (reset) {
    reset.addEventListener("click", async () => {
      try {
        await fetch("/api/voice-tags/taste", { method: "DELETE" });
        setStatus("Forgot your tag taste.");
      } catch (err) { /* shown as unchanged */ }
      loadTagTaste();
    });
  }
  // Fresh whenever Settings opens.
  document.addEventListener("click", (e) => {
    if (tagTasteStale && e.target.closest && e.target.closest("#settingsToggle, [data-settings-section], [data-settings-page]")) loadTagTaste();
  });
})();

// The Retake button and its menu.
var openRetakeMenu = null;

function closeRetakeMenu() {
  if (!openRetakeMenu) return;
  openRetakeMenu.classList.remove("is-open");
  const btn = openRetakeMenu.querySelector(".turn-save");
  if (btn) btn.setAttribute("aria-expanded", "false");
  openRetakeMenu = null;
}

document.addEventListener("click", (e) => {
  if (openRetakeMenu && !openRetakeMenu.contains(e.target)) closeRetakeMenu();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && openRetakeMenu) closeRetakeMenu();
});

function makeRetakeButton(getTurn) {
  const wrap = document.createElement("span");
  wrap.className = "retake";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "turn-save retake-btn";
  btn.title = "Say it again: the same, without tags, or with different tags";
  btn.setAttribute("aria-haspopup", "menu");
  btn.setAttribute("aria-expanded", "false");
  const label = document.createElement("span");
  label.textContent = "Retake";
  btn.append(iconNode("i-refresh", "icon-12"), label);
  const menu = document.createElement("span");
  menu.className = "retake-menu";
  menu.setAttribute("role", "menu");
  const { opts, text } = getTurn();
  const hasTags = tagsIn(opts.voiced || text).length > 0;
  [
    ["same", "Say it again", "The same words and tags, a new take."],
    ["plain", "Without tags", hasTags ? "Just the words. Counts as not liking these tags." : "It has no tags already."],
    ["fresh", "Different tags", "The AI picks other tags for the same words."],   // not counted against the old ones
  ].forEach(([mode, name, sub]) => {
    const item = document.createElement("button");
    item.type = "button";
    item.setAttribute("role", "menuitem");
    item.className = "retake-item";
    item.dataset.mode = mode;
    if (mode === "plain" && !hasTags) item.disabled = true;
    const n = document.createElement("span");
    n.className = "retake-name";
    n.textContent = name;
    const s = document.createElement("span");
    s.className = "retake-sub";
    s.textContent = sub;
    item.append(n, s);
    item.addEventListener("click", (e) => {
      e.stopPropagation();
      closeRetakeMenu();
      retakeTurn(getTurn(), mode, btn);
    });
    menu.append(item);
  });
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (btn.disabled) return;
    if (openRetakeMenu === wrap) { closeRetakeMenu(); return; }
    closeRetakeMenu();
    wrap.classList.add("is-open");
    btn.setAttribute("aria-expanded", "true");
    openRetakeMenu = wrap;
    const first = menu.querySelector(".retake-item:not(:disabled)");
    if (first) first.focus({ preventScroll: true });
  });
  wrap.append(btn, menu);
  return wrap;
}

async function retakeTurn({ turn, who, text, opts, at }, mode, btn) {
  ensureAudioContext();   // inside the click, so the browser lets it play
  btn.disabled = true;
  btn.classList.add("is-busy");
  turn.classList.add("is-retaking");
  setStatus(mode === "fresh" ? "Finding different tags…" : "Saying it again…");
  setLamp("busy");
  beginReplyTyping();
  requestVrchatUnmute();
  let data;
  try {
    const res = await fetch("/api/retake", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        voiced: opts.voiced || text,
        reply: text,
        language: opts.language || currentLanguage,
        profile_id: opts.profileId || null,
        session_id: sessionId,
        mode,
      }),
    });
    data = await res.json();
    if (!res.ok) throw new Error(data.error || "Couldn't say it again.");
  } catch (err) {
    endReplyTyping();
    setStatus(err.message, true);
    setLamp("ready");
    btn.disabled = false;
    btn.classList.remove("is-busy");
    turn.classList.remove("is-retaking");
    return;
  }
  if (data.removed_tags && data.removed_tags.length) postTagFeedback({ removed: data.removed_tags });
  const pages = Array.isArray(data.chatbox_pages) ? data.chatbox_pages : [];
  const pager = data.audio_url && pages.length > 1 && oscEnabled() && typeof makeChatboxPager === "function"
    ? makeChatboxPager(pages.length) : null;
  const follower = data.audio_url && pages.length > 1
    ? makeChatboxFollower(pages, pager ? (i) => pager.show(i) : null) : null;
  const kept = {};
  Object.keys(opts).forEach((k) => {
    if (typeof opts[k] !== "function" && !(opts[k] instanceof Node) && k !== "restoring") kept[k] = opts[k];
  });
  const voiced = data.voiced && data.voiced !== data.reply ? data.voiced : undefined;
  addTurn(who, data.reply, {
    ...kept,
    at,
    replaceTurn: turn,
    audioUrl: data.audio_url,
    wordTimes: data.word_times,
    voiced,
    credits: data.credits,
    spoke: true,
    voiceHow: data.voice_how || "",
    totalSeconds: data.total_seconds,
    textSeconds: data.text_seconds,
    audioSeconds: data.audio_seconds,
    autoTagged: false,
    tagShaped: false,
    retaken: mode,
    footer: pager ? pager.el : null,
    saveData: data.audio_url ? {
      ...(opts.saveData || {}),
      saved_done: false,
      audio_url: data.audio_url,
      text: data.reply,
      voiced: data.voiced || data.reply,
      voice_how: data.voice_how || "",
      word_times: data.word_times,
      chatbox_pages: data.chatbox_pages,
    } : null,
    onAudioStart: () => {
      if (!oscEnabled()) endReplyTyping();
      else if (!follower) sendToChatbox(data.reply, { speaking: true });
    },
    onPlayback: follower ? (playing, offset, dur) => follower.update(playing, offset, dur) : null,
  });
  addCredits(data.credits || 0);
  loadCredits({ force: true });
  setLamp("ready");
  setStatus(data.voice_notice || ({ same: "Said again.", plain: "Said again, without tags.",
    fresh: voiced ? "Said again, with different tags." : "Said again. The AI found no other tags that fit." }[mode]),
  Boolean(data.voice_notice));
}


// ---------------------------------------------------------------------------
// NEW (1.5.0): the message box grows, [ for tags, and checking Auto tags.
//
//   * The box grows upwards with the message (up to a limit, then it
//     scrolls), so every word and every tag idea is in view. Browsers that
//     can't size a box to its text get the same from here.
//   * Typing [ opens a short tag list at the cursor: what matches what you
//     type after it, the tags you use most first. Enter or Tab puts it in,
//     the arrows choose, Esc leaves a plain bracket. ElevenLabs voices only;
//     "Type [ for tags" in the ✦ menu turns it off.
//   * "Check auto tags first" (✦ menu): with Auto tags on and a Clean up or
//     Word for word profile, Enter shows your message with the AI's tags.
//     Click a tag to swap or remove it; Enter (or Say it) sends it as shown,
//     Without tags sends it plain, Edit puts it in the box, Esc goes back.
//     Auto-send never stops to ask.
// ---------------------------------------------------------------------------
var BRACKET_KEY = "frivo_tag_bracket";
var TAG_CHECK_KEY = "frivo_tag_check";

(function growingBox() {
  const input = $("messageInput");
  if (!input || input.tagName !== "TEXTAREA") return;
  const native = typeof CSS !== "undefined" && CSS.supports && CSS.supports("field-sizing", "content");
  const composer = input.closest(".composer");
  // Past one line, the box takes the whole width and the buttons move under
  // it. Whether it's past one line is judged at the one-line width, so the
  // box doesn't flip back and forth as it widens.
  let narrow = 0;
  const tall = () => {
    if (!composer) return;
    // CHANGED (1.5.0): the rich box is the one you see.
    const shown = composer.classList.contains("has-rich") && $("messageRich") ? $("messageRich") : input;
    if (!composer.classList.contains("is-tall")) narrow = shown.clientWidth || narrow;
    let want = false;
    if (input.value.includes("\n")) want = true;
    else if (input.value && narrow) {
      const end = textBoxIn(input, input.value.length, input.value.length, narrow);
      const lineH = parseFloat(getComputedStyle(input).lineHeight) || 22;
      want = end.rawY > lineH * 0.6;
    }
    if (composer.classList.contains("is-tall") !== want) composer.classList.toggle("is-tall", want);
  };
  const fit = () => {
    tall();
    if (native) return;
    input.style.height = "auto";
    const max = parseFloat(getComputedStyle(input).maxHeight) || 240;
    input.style.height = `${Math.min(input.scrollHeight, max)}px`;
  };
  // Every way the text changes (typing, dictation, Suggest, sending) goes
  // through .value or an input event.
  const desc = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value");
  if (desc && desc.set) {
    Object.defineProperty(input, "value", {
      configurable: true,
      get() { return desc.get.call(this); },
      set(v) { desc.set.call(this, v); fit(); },
    });
  }
  input.addEventListener("input", fit);
  window.addEventListener("resize", fit);
  fit();
})();

function elevenVoiceNow() {
  const wrap = $("voiceTagWrap");
  return Boolean(wrap && !wrap.classList.contains("is-hidden"));
}

function bracketOn() {
  try { return localStorage.getItem(BRACKET_KEY) !== "off"; } catch (e) { return true; }
}

function tagCheckOn() {
  try { return localStorage.getItem(TAG_CHECK_KEY) === "on"; } catch (e) { return false; }
}

// Where the composer's own popups go: just above a point in the text.
function composerPoint(input, offset) {
  // CHANGED (1.5.0): the rich box says where its text is drawn.
  if (typeof richActive === "function" && richActive()) {
    const composer = input.closest(".composer");
    const p = richPointAt(offset);
    const r = document.createRange();
    let rect = null;
    try { r.setStart(p.node, p.offset); r.collapse(true); rect = r.getClientRects()[0] || null; } catch (e) { rect = null; }
    if (!rect) rect = rich.el.getBoundingClientRect();
    const c = composer.getBoundingClientRect();
    return { x: rect.left - c.left, bottom: c.bottom - rect.top + 6, visible: true };
  }
  const box = textBoxIn(input, offset, Math.min(offset + 1, input.value.length) || offset);
  const composer = input.closest(".composer");
  const top = input.offsetTop + input.clientTop + box.y;
  return { x: box.x, bottom: composer ? composer.clientHeight - top + 6 : 0, visible: box.visible };
}

// ---- [ for tags ----
var bracketState = { open: false, start: -1, items: [], pick: 0, dismissed: -1, likes: [] };

function bracketQuery(input) {
  if (input.selectionStart !== input.selectionEnd) return null;
  const caret = input.selectionStart;
  const m = input.value.slice(0, caret).match(/\[([A-Za-z' \-]{0,24})$/);
  if (!m) return null;
  return { start: caret - m[0].length, caret, q: m[1].toLowerCase() };
}

function bracketChoices(q) {
  const yours = typeof yourTags === "function" ? yourTags() : [];
  const favourites = Array.from(new Set([...(bracketState.likes || []), ...yours]));
  const known = [];
  (audioTagGroups || []).forEach((g) => g.tags.forEach((t) => known.push({ tag: t, kind: g.name })));
  const all = new Map();
  favourites.forEach((t) => all.set(t, { tag: t, kind: yours.includes(t) ? "Yours" : "You use it", fav: true }));
  known.forEach((k) => { if (!all.has(k.tag)) all.set(k.tag, { tag: k.tag, kind: k.kind, fav: false }); });
  const list = Array.from(all.values());
  if (!q) return list.filter((c) => c.fav).concat(list.filter((c) => !c.fav)).slice(0, 7);
  const starts = list.filter((c) => c.tag.startsWith(q));
  const inside = list.filter((c) => !c.tag.startsWith(q) && c.tag.includes(q));
  const ranked = [...starts.filter((c) => c.fav), ...starts.filter((c) => !c.fav), ...inside].slice(0, 6);
  // Whatever you've typed can be a tag of its own, too.
  // (only when nothing starts with it, so "lau" doesn't offer [lau]).
  if (q.trim().length > 1 && !starts.length && !ranked.some((c) => c.tag === q.trim())) {
    ranked.push({ tag: q.trim(), kind: "As typed", fav: false });
  }
  return ranked;
}

function closeBracket() {
  const pop = $("tagBracket");
  bracketState.open = false;
  if (pop) pop.classList.add("is-hidden");
}

function renderBracket() {
  const input = $("messageInput");
  const pop = $("tagBracket");
  if (!input || !pop) return;
  const focused = document.activeElement === input || (typeof rich === "object" && rich.el && document.activeElement === rich.el);   // CHANGED (1.5.0)
  const query = bracketOn() && elevenVoiceNow() && focused ? bracketQuery(input) : null;
  if (!query || query.start === bracketState.dismissed) { closeBracket(); return; }
  const items = bracketChoices(query.q);
  if (!items.length) { closeBracket(); return; }
  if (!bracketState.open || bracketState.start !== query.start) bracketState.pick = 0;
  bracketState.open = true;
  bracketState.start = query.start;
  bracketState.items = items;
  bracketState.pick = Math.min(bracketState.pick, items.length - 1);
  pop.replaceChildren();
  const head = document.createElement("div");
  head.className = "tag-bracket-head";
  head.textContent = query.q ? `Tags for “${query.q}”` : "Voice tags";
  pop.append(head);
  items.forEach((item, i) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "tag-bracket-item" + (i === bracketState.pick ? " is-picked" : "");
    row.setAttribute("role", "option");
    row.setAttribute("aria-selected", i === bracketState.pick ? "true" : "false");
    const name = document.createElement("span");
    name.className = "tag-bracket-name";
    const at = query.q ? item.tag.indexOf(query.q) : -1;
    if (at >= 0) {
      const hit = document.createElement("b");
      hit.textContent = item.tag.slice(at, at + query.q.length);
      name.append(item.tag.slice(0, at), hit, item.tag.slice(at + query.q.length));
    } else {
      name.textContent = item.tag;
    }
    const kind = document.createElement("span");
    kind.className = "tag-bracket-kind";
    kind.textContent = item.kind;
    row.append(name, kind);
    if (item.fav) row.classList.add("is-fav");
    row.addEventListener("mousedown", (e) => e.preventDefault());   // keep the cursor in the box
    row.addEventListener("click", () => putBracketTag(item.tag));
    pop.append(row);
  });
  const foot = document.createElement("div");
  foot.className = "tag-bracket-foot";
  foot.innerHTML = "<span><kbd>↵</kbd> put it in</span><span><kbd>↑↓</kbd> choose</span><span><kbd>Esc</kbd> just a bracket</span>";
  pop.append(foot);
  pop.classList.remove("is-hidden");
  const point = composerPoint(input, query.start);
  const composer = input.closest(".composer");
  const width = pop.offsetWidth || 280;
  const maxLeft = (composer ? composer.clientWidth : 600) - width - 8;
  pop.style.left = `${Math.max(8, Math.min(point.x - 14, maxLeft))}px`;
  pop.style.bottom = `${point.bottom}px`;
}

function putBracketTag(tag) {
  const input = $("messageInput");
  const query = input ? bracketQuery(input) : null;
  if (!input || !query) { closeBracket(); return; }
  const v = input.value;
  let after = v.slice(query.caret);
  if (after.startsWith("]")) after = after.slice(1);
  const insert = `[${tag}]` + (after.startsWith(" ") || !after ? "" : " ");
  input.value = v.slice(0, query.start) + insert + (after ? after : " ");
  const caret = query.start + insert.length + (after ? 0 : 1);
  try { input.setSelectionRange(caret, caret); } catch (e) { /* fine */ }
  closeBracket();
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.focus();
}

(function wireBracket() {
  const input = $("messageInput");
  const composer = input ? input.closest(".composer") : null;
  const toggle = $("tagBracketToggle");
  if (toggle) {
    toggle.checked = bracketOn();
    toggle.addEventListener("change", () => {
      try { localStorage.setItem(BRACKET_KEY, toggle.checked ? "on" : "off"); } catch (e) { /* not kept */ }
      if (!toggle.checked) closeBracket();
    });
  }
  if (!input || !composer) return;
  input.addEventListener("input", () => {
    const q = bracketQuery(input);
    if (!q || q.start !== bracketState.dismissed) bracketState.dismissed = q ? bracketState.dismissed : -1;
    renderBracket();
  });
  input.addEventListener("click", renderBracket);
  input.addEventListener("blur", () => setTimeout(() => {
    if (document.activeElement !== input && !(rich.el && document.activeElement === rich.el)) closeBracket();   // CHANGED (1.5.0)
  }, 120));
  // Before the box's own Enter (send), so Enter picks a tag while the list is open.
  composer.addEventListener("keydown", (e) => {
    if (!bracketState.open || e.target !== input) return;
    const n = bracketState.items.length;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      bracketState.pick = (bracketState.pick + (e.key === "ArrowDown" ? 1 : n - 1)) % n;
      renderBracket();
    } else if ((e.key === "Enter" && !e.shiftKey && !e.isComposing) || e.key === "Tab") {
      putBracketTag(bracketState.items[bracketState.pick].tag);
    } else if (e.key === "Escape") {
      bracketState.dismissed = bracketState.start;
      closeBracket();
    } else {
      return;
    }
    e.preventDefault();
    e.stopImmediatePropagation();
  }, true);
  // The tags you use most, from your taste.
  fetch("/api/voice-tags/taste").then((r) => r.json()).then((d) => { bracketState.likes = d.liked || []; }).catch(() => {});
})();

// ---- Check auto tags first ----
var tagCheck = { open: false, original: "", text: "", offered: [], busy: false, menu: -1 };

function activeVoiceStyle() {
  const profile = (typeof allProfiles !== "undefined" ? allProfiles : []).find((p) => p.id === currentProfileId);
  if (profile) return { style: profile.response_style || "echo", shaping: profile.tag_shaping === true };
  return {
    style: typeof responseStyleRadios !== "undefined" ? getRadioValue(responseStyleRadios, "echo") : "echo",
    shaping: $("tagShapingToggle") ? $("tagShapingToggle").checked : false,
  };
}

function shouldCheckTags() {
  if (!tagCheckOn() || !(typeof autoTagsOn === "function" && autoTagsOn())) return false;
  if (!speakEnabled() || !elevenVoiceNow()) return false;
  const v = activeVoiceStyle();
  // A Reply profile's tags are in its answer (Retake is for those), and
  // Shape words for tags does its own tagging.
  return v.style !== "reply" && !v.shaping;
}

function closeTagCheck() {
  const card = $("tagReview");
  tagCheck.open = false;
  tagCheck.menu = -1;
  if (card) card.classList.add("is-hidden");
  const composer = card ? card.closest(".composer") : null;
  if (composer) composer.classList.remove("is-checking");
}

async function startTagCheck(message) {
  const card = $("tagReview");
  if (!card || tagCheck.busy) return;
  tagCheck.busy = true;
  tagCheck.open = true;
  tagCheck.original = message;
  tagCheck.text = "";
  card.closest(".composer").classList.add("is-checking");
  card.replaceChildren();
  const wait = document.createElement("div");
  wait.className = "tag-review-wait";
  wait.textContent = "Finding tags…";
  card.append(wait);
  card.classList.remove("is-hidden");
  setStatus("Finding tags for your message…");
  let data = null;
  try {
    const res = await fetch("/api/voice-tags/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: message, profile_id: currentProfileId || null, session_id: sessionId }),
    });
    data = await res.json();
    if (!res.ok) throw new Error(data.error || "Couldn't find tags.");
  } catch (err) {
    tagCheck.busy = false;
    closeTagCheck();
    setStatus(`${err.message} Sent without checking.`, true);
    send({ reviewed: false, auto: true });
    return;
  }
  tagCheck.busy = false;
  if (!tagCheck.open) return;   // Esc while it was looking
  if (messageInput.value.trim() !== message) { closeTagCheck(); return; }   // you kept typing
  if (!data.added) {
    closeTagCheck();
    setStatus("No tags fit this one. Sent as it is.");
    send({ reviewed: true });
    return;
  }
  tagCheck.text = data.text;
  tagCheck.offered = tagsIn(data.text).filter((t) => !tagsIn(message).includes(t));
  renderTagCheck();
  setStatus("Check the tags, then press Enter to say it.");
}

function tagSwaps(tag) {
  const group = (audioTagGroups || []).find((g) => g.tags.includes(tag)) || (audioTagGroups || [])[0];
  const pool = [...(bracketState.likes || []), ...(group ? group.tags : [])];
  return Array.from(new Set(pool)).filter((t) => t !== tag).slice(0, 5);
}

function renderTagCheck() {
  const card = $("tagReview");
  if (!card) return;
  const n = tagsIn(tagCheck.text).length;
  const active = (typeof allProfiles !== "undefined" ? allProfiles : []).find((p) => p.id === currentProfileId);
  const speaker = active ? active.name : "the voice";
  card.replaceChildren();
  const head = document.createElement("div");
  head.className = "tag-review-head";
  head.textContent = n ? `Auto tags added ${n}. Check them before ${speaker} says it.` : "No tags left. Say it plain?";
  const body = document.createElement("p");
  body.className = "tag-review-text";
  const re = /\[([A-Za-z][A-Za-z' \-]{0,38})\]/g;
  let last = 0;
  let m;
  let index = 0;
  while ((m = re.exec(tagCheck.text))) {
    if (m.index > last) body.append(tagCheck.text.slice(last, m.index));
    const i = index;
    const tag = m[1].toLowerCase();
    const wrap = document.createElement("span");
    wrap.className = "tag-review-tagwrap";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "tag-review-tag" + (tagCheck.menu === i ? " is-open" : "");
    btn.textContent = tag;
    btn.title = "Swap or remove this tag";
    btn.setAttribute("aria-haspopup", "menu");
    btn.setAttribute("aria-expanded", tagCheck.menu === i ? "true" : "false");
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      tagCheck.menu = tagCheck.menu === i ? -1 : i;
      renderTagCheck();
    });
    wrap.append(btn);
    if (tagCheck.menu === i) {
      const menu = document.createElement("span");
      menu.className = "tag-review-menu";
      menu.setAttribute("role", "menu");
      const label = document.createElement("span");
      label.className = "tag-review-menu-label";
      label.textContent = "Swap for";
      menu.append(label);
      tagSwaps(tag).forEach((t) => {
        const opt = document.createElement("button");
        opt.type = "button";
        opt.setAttribute("role", "menuitem");
        opt.textContent = t;
        opt.addEventListener("click", (e) => { e.stopPropagation(); replaceCheckTag(i, t); });
        menu.append(opt);
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "is-remove";
      remove.setAttribute("role", "menuitem");
      remove.textContent = "Remove this tag";
      remove.addEventListener("click", (e) => { e.stopPropagation(); replaceCheckTag(i, null); });
      menu.append(remove);
      wrap.append(menu);
    }
    body.append(wrap);
    last = m.index + m[0].length;
    index += 1;
  }
  if (last < tagCheck.text.length) body.append(tagCheck.text.slice(last));
  const foot = document.createElement("div");
  foot.className = "tag-review-foot";
  const always = document.createElement("label");
  always.className = "tag-review-always";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = tagCheckOn();
  box.addEventListener("change", () => {
    try { localStorage.setItem(TAG_CHECK_KEY, box.checked ? "on" : "off"); } catch (e) { /* not kept */ }
    const t = $("tagReviewToggle");
    if (t) t.checked = box.checked;
  });
  always.append(box, " Always check first");
  const edit = document.createElement("button");
  edit.type = "button";
  edit.className = "link-btn";
  edit.textContent = "Edit";
  edit.title = "Put it in the box with these tags, to change it yourself";
  edit.addEventListener("click", () => {
    noteTagOffers(tagCheck.offered);
    messageInput.value = tagCheck.text;
    closeTagCheck();
    tagCheck.skipNext = tagCheck.text;
    messageInput.dispatchEvent(new Event("input", { bubbles: true }));
    messageInput.focus();
  });
  const plain = document.createElement("button");
  plain.type = "button";
  plain.className = "btn-ghost btn-sm tag-review-plain";
  plain.textContent = "Without tags";
  plain.addEventListener("click", () => finishTagCheck(false));
  const say = document.createElement("button");
  say.type = "button";
  say.className = "btn btn-sm tag-review-say";
  say.innerHTML = "Say it <kbd>↵</kbd>";
  say.addEventListener("click", () => finishTagCheck(true));
  foot.append(always, edit, plain, say);
  card.append(head, body, foot);
}

function replaceCheckTag(index, tag) {
  let i = -1;
  tagCheck.text = tagCheck.text.replace(/\[([A-Za-z][A-Za-z' \-]{0,38})\]\s?/g, (whole, t) => {
    i += 1;
    if (i !== index) return whole;
    return tag ? `[${tag}]` + (whole.endsWith(" ") ? " " : "") : "";
  }).replace(/\s{2,}/g, " ").trim();
  tagCheck.menu = -1;
  renderTagCheck();
}

function finishTagCheck(withTags) {
  if (!tagCheck.open || !tagCheck.text) return;
  const text = withTags ? tagCheck.text : tagCheck.original.replace(/\[[^\]\n]*\]\s?/g, "").trim() || tagCheck.original;
  noteTagOffers(tagCheck.offered);   // your taste: kept, swapped out or removed
  closeTagCheck();
  messageInput.value = text;
  send({ reviewed: true });
}

(function wireTagCheck() {
  const toggle = $("tagReviewToggle");
  if (toggle) {
    toggle.checked = tagCheckOn();
    toggle.addEventListener("change", () => {
      try { localStorage.setItem(TAG_CHECK_KEY, toggle.checked ? "on" : "off"); } catch (e) { /* not kept */ }
    });
  }
  const input = $("messageInput");
  const composer = input ? input.closest(".composer") : null;
  if (!input || !composer) return;
  // On the page, not just the box: clicking a tag in the card moves the focus.
  document.addEventListener("keydown", (e) => {
    // CHANGED (1.5.0): keys in the rich box come through the plain one.
    if (typeof rich === "object" && rich.el && e.target === rich.el) return;
    const where = document.activeElement;
    const ours = !where || where === document.body || where === input || (where.closest && where.closest("#tagReview"))
      || (typeof rich === "object" && where === rich.el);
    if (tagCheck.open && !ours) return;
    if (!tagCheck.open && e.target !== input) return;
    if (!tagCheck.open) {
      // A message you put in the box from the check goes as it is.
      if (e.target === input && e.key === "Enter" && !e.shiftKey && !e.isComposing
          && tagCheck.skipNext && input.value.trim() === tagCheck.skipNext.trim()) {
        tagCheck.skipNext = "";
        e.preventDefault();
        e.stopImmediatePropagation();
        send({ reviewed: true });
      }
      return;
    }
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      e.stopImmediatePropagation();
      if (!tagCheck.busy) finishTagCheck(true);
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopImmediatePropagation();
      if (tagCheck.menu >= 0) { tagCheck.menu = -1; renderTagCheck(); } else closeTagCheck();
    }
  }, true);
  // Changing the message means the check was for something else.
  input.addEventListener("input", () => { if (tagCheck.open && !tagCheck.busy) closeTagCheck(); });
  document.addEventListener("click", (e) => {
    if (tagCheck.open && tagCheck.menu >= 0 && !e.target.closest(".tag-review-tagwrap")) {
      tagCheck.menu = -1;
      renderTagCheck();
    }
  });
})();


// ---------------------------------------------------------------------------
// NEW (1.5.0): the models on the Ollama PC (Settings > AI providers).
//
//   * The drive: free space where Ollama keeps its models (from Evora, when
//     it's on the same PC), with what the models take.
//   * Installed: size, size class, which tier uses it, loaded or not, and
//     whether it fits the graphics card. "Use as" puts it in Fast, Balanced
//     or Best (and saves); Remove asks first, and says if a tier uses it.
//   * Download any model by name: Check looks up its size first. Suggestions
//     come with sizes, and say if they fit the card or the drive.
//   * Downloads run on the Ollama PC and show their progress here; Stop
//     ends one. They carry on if you close Settings.
// ---------------------------------------------------------------------------
var omState = { data: null, suggestions: null, card: null, pollTimer: null, confirming: "", lookup: null };

function fmtGB(bytes) {
  if (!bytes && bytes !== 0) return "";
  const gb = bytes / 1024 ** 3;
  if (gb >= 100) return `${Math.round(gb)} GB`;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`;
}

function omFitText(fit, card) {
  const withEvora = card && card.evora_mb > 0;
  return {
    fits: withEvora ? "Fits with Evora" : "Fits the card",
    tight: "Fits only without Evora",
    big: "Too big for the card (slower)",
  }[fit] || "";
}

function omBadge(text, kind) {
  const b = document.createElement("span");
  b.className = `om-badge is-${kind}`;
  b.textContent = text;
  return b;
}

function omFreeBytes() {
  const d = omState.data && omState.data.drive;
  return d && d.ok ? d.free_bytes : null;
}

async function omLoad() {
  let data;
  try {
    const res = await fetch("/api/ollama/models");
    data = await res.json();
  } catch (err) {
    data = { reachable: false, error: "Frivo couldn't ask the Ollama PC.", pulls: {} };
  }
  omState.data = data;
  if (data.card) omState.card = data.card;
  omRender();
  omPollIfPulling();
}

function omPollIfPulling() {
  clearTimeout(omState.pollTimer);
  const pulls = (omState.data && omState.data.pulls) || {};
  if (Object.values(pulls).some((p) => p.state === "pulling")) {
    omState.pollTimer = setTimeout(async () => {
      try {
        const res = await fetch("/api/ollama/pull");
        const d = await res.json();
        const before = Object.entries((omState.data && omState.data.pulls) || {}).filter(([, p]) => p.state === "pulling").map(([n]) => n);
        omState.data.pulls = d.pulls || {};
        const finished = before.some((n) => !omState.data.pulls[n] || omState.data.pulls[n].state !== "pulling");
        if (finished) { omLoad(); omLoadSuggestions(); if (typeof refreshAiPop === "function") refreshAiPop(); return; }
        omRenderPulls();
        omRenderSuggestions();
      } catch (err) { /* try again */ }
      omPollIfPulling();
    }, 1000);
  }
}

function omRender() {
  omCardUses();   // NEW (1.6.0)
  omRenderDrive();
  omRenderInstalled();
  omRenderSuggestions();
}

function omRenderDrive() {
  const box = $("omDrive");
  const data = omState.data;
  if (!box) return;
  box.replaceChildren();
  if (!data || !data.reachable) {
    const p = document.createElement("span");
    p.className = "om-muted is-error";
    p.textContent = (data && data.error) || "Ollama isn't reachable.";
    box.append(p);
    return;
  }
  const d = data.drive || {};
  const line = document.createElement("div");
  line.className = "om-drive-line";
  const name = document.createElement("span");
  name.className = "om-drive-name";
  if (d.ok) {
    name.textContent = `Drive ${d.drive || ""}`.trim();
    const free = document.createElement("span");
    free.className = "om-drive-free";
    free.textContent = `${fmtGB(d.free_bytes)} free of ${fmtGB(d.total_bytes)}`;
    const models = document.createElement("span");
    models.className = "om-muted";
    models.textContent = `Models use ${fmtGB(data.used_bytes)}`;
    line.append(name, free, models);
    const bar = document.createElement("div");
    bar.className = "om-bar";
    bar.setAttribute("role", "img");
    bar.setAttribute("aria-label", `${fmtGB(d.free_bytes)} free of ${fmtGB(d.total_bytes)}; models use ${fmtGB(data.used_bytes)}`);
    const other = Math.max(0, d.used_bytes - data.used_bytes);
    const seg = (cls, bytes) => {
      const s = document.createElement("span");
      s.className = `om-bar-seg ${cls}`;
      s.style.width = `${Math.max(0, Math.min(100, (bytes / d.total_bytes) * 100))}%`;
      return s;
    };
    bar.append(seg("is-models", data.used_bytes), seg("is-other", other));
    box.append(line, bar);
    if (d.free_bytes < 10 * 1024 ** 3) {
      const warn = document.createElement("span");
      warn.className = "om-muted is-warn";
      warn.textContent = "Under 10 GB left. Remove a model you don't use before downloading another.";
      box.append(warn);
    }
    if (!d.found) {
      const note = document.createElement("span");
      note.className = "om-muted";
      note.textContent = "Evora couldn't find Ollama's models folder, so this is the drive Evora is on.";
      box.append(note);
    }
  } else {
    name.textContent = `Models use ${fmtGB(data.used_bytes)}`;
    const why = document.createElement("span");
    why.className = "om-muted";
    why.textContent = d.reason || "The drive's free space is unknown.";
    line.append(name, why);
    box.append(line);
  }
}

function omRenderPulls() {
  const list = $("omInstalled");
  if (!list) return;
  list.querySelectorAll(".om-row.is-pull").forEach((r) => r.remove());
  const pulls = (omState.data && omState.data.pulls) || {};
  Object.entries(pulls).forEach(([name, p]) => {
    if (p.state === "done") return;
    const row = document.createElement("div");
    row.className = "om-row is-pull" + (p.state === "error" ? " is-error" : "");
    const main = document.createElement("div");
    main.className = "om-row-main";
    const title = document.createElement("span");
    title.className = "om-name";
    title.textContent = name;
    const meta = document.createElement("span");
    meta.className = "om-meta";
    const total = p.total || p.expected || 0;
    const pct = total ? Math.min(100, Math.round((p.completed / total) * 100)) : 0;
    if (p.state === "pulling") {
      meta.textContent = total ? `Downloading · ${fmtGB(p.completed)} of ${fmtGB(total)} · ${pct}%` : (p.status || "Starting…");
    } else if (p.state === "stopped") {
      meta.textContent = "Stopped. Downloading it again carries on where it left off.";
    } else {
      meta.textContent = p.error || "The download failed.";
    }
    main.append(title, meta);
    if (p.state === "pulling") {
      const bar = document.createElement("div");
      bar.className = "om-progress";
      const fill = document.createElement("span");
      fill.style.width = `${pct}%`;
      bar.append(fill);
      main.append(bar);
    }
    const actions = document.createElement("div");
    actions.className = "om-actions";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn-ghost btn-sm";
    if (p.state === "pulling") {
      btn.textContent = "Stop";
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        await fetch("/api/ollama/pull", { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model: name }) });
        setTimeout(omLoad, 600);
      });
    } else {
      btn.textContent = "Try again";
      btn.addEventListener("click", () => omPull(name));
    }
    actions.append(btn);
    row.append(main, actions);
    list.prepend(row);
  });
}

function omRenderInstalled() {
  const list = $("omInstalled");
  const data = omState.data;
  if (!list) return;
  list.replaceChildren();
  if (!data || !data.reachable) return;
  if (!data.installed.length) {
    const empty = document.createElement("p");
    empty.className = "om-muted om-empty";
    empty.textContent = "No models on the Ollama PC yet. Pick one from the suggestions below.";
    list.append(empty);
  }
  const tierName = { fast: "Fast", balanced: "Balanced", best: "Best" };
  data.installed.forEach((m) => {
    const row = document.createElement("div");
    row.className = "om-row";
    const main = document.createElement("div");
    main.className = "om-row-main";
    const top = document.createElement("div");
    top.className = "om-row-top";
    const title = document.createElement("span");
    title.className = "om-name";
    title.textContent = m.name;
    top.append(title);
    m.tiers.forEach((t) => top.append(omBadge(tierName[t], "tier")));
    if (m.loaded) top.append(omBadge("Loaded", "loaded"));
    const meta = document.createElement("span");
    meta.className = "om-meta";
    meta.textContent = [fmtGB(m.size), m.params, m.quant].filter(Boolean).join(" · ");
    if (m.fit) {
      const fit = omBadge(omFitText(m.fit, data.card), m.fit);
      meta.append(" ", fit);
    }
    main.append(top, meta);

    const actions = document.createElement("div");
    actions.className = "om-actions";
    if (omState.confirming === m.name) {
      const ask = document.createElement("span");
      ask.className = "om-confirm";
      ask.textContent = m.tiers.length
        ? `${m.tiers.map((t) => tierName[t]).join(" and ")} use${m.tiers.length === 1 ? "s" : ""} it. Remove ${fmtGB(m.size)}?`
        : `Remove ${fmtGB(m.size)}?`;
      const yes = document.createElement("button");
      yes.type = "button";
      yes.className = "btn btn-sm om-danger";
      yes.textContent = "Remove";
      yes.addEventListener("click", () => omRemove(m.name, yes));
      const no = document.createElement("button");
      no.type = "button";
      no.className = "btn-ghost btn-sm";
      no.textContent = "Keep";
      no.addEventListener("click", () => { omState.confirming = ""; omRenderInstalled(); omRenderPulls(); });
      actions.append(ask, no, yes);
    } else {
      const use = document.createElement("select");
      use.className = "om-use";
      use.setAttribute("aria-label", `Use ${m.name} as`);
      [["", "Use as…"], ["fast", "Fast"], ["balanced", "Balanced"], ["best", "Best"]].forEach(([v, label]) => {
        const o = document.createElement("option");
        o.value = v;
        o.textContent = v && m.tiers.includes(v) ? `${label} ✓` : label;
        use.append(o);
      });
      use.addEventListener("change", () => {
        const t = use.value;
        use.value = "";
        if (!t) return;
        omUseAs(m.name, t);
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "btn-ghost btn-sm";
      remove.textContent = "Remove";
      remove.addEventListener("click", () => { omState.confirming = m.name; omRenderInstalled(); omRenderPulls(); });
      actions.append(use, remove);
    }
    row.append(main, actions);
    list.append(row);
  });
  omRenderPulls();
}

function omUseAs(name, tier) {
  const ids = { fast: "ollamaModel", balanced: "ollamaModelBalanced", best: "ollamaModelBest" };
  const input = $(ids[tier]);
  if (!input) return;
  input.value = name;
  input.dispatchEvent(new Event("change", { bubbles: true }));   // Settings saves itself
  setStatus(`${name} is now the ${tier === "best" ? "Best" : tier === "balanced" ? "Balanced" : "Fast"} model.`);
  setTimeout(() => { omLoad(); if (typeof refreshAiPop === "function") refreshAiPop(); }, 900);
}

async function omRemove(name, btn) {
  btn.disabled = true;
  try {
    const res = await fetch("/api/ollama/models", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: name }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Couldn't remove it.");
    omState.confirming = "";
    omState.data = data;
    omRender();
    setStatus(`Removed ${name} from the Ollama PC.`);
    omLoadSuggestions();
  } catch (err) {
    btn.disabled = false;
    setStatus(err.message, true);
  }
}

async function omPull(name) {
  try {
    const res = await fetch("/api/ollama/pull", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: name }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Couldn't start the download.");
    if (omState.data) omState.data.pulls = data.pulls || {};
    omRenderPulls();
    omRenderSuggestions();
    omPollIfPulling();
    setStatus(`Downloading ${name} on the Ollama PC. You can close Settings; it carries on.`);
  } catch (err) {
    setStatus(err.message, true);
  }
}

function omDownloadButton(item) {
  const pulls = (omState.data && omState.data.pulls) || {};
  const pull = pulls[item.name];
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn btn-sm";
  const free = omFreeBytes();
  if (item.installed) {
    btn.className = "btn-ghost btn-sm";
    btn.textContent = "Installed";
    btn.disabled = true;
  } else if (pull && pull.state === "pulling") {
    const total = pull.total || pull.expected || 0;
    btn.className = "btn-ghost btn-sm";
    btn.textContent = total ? `${Math.round((pull.completed / total) * 100)}%` : "Starting…";
    btn.disabled = true;
  } else if (free != null && item.size && item.size > free - 1024 ** 3) {
    btn.className = "btn-ghost btn-sm";
    btn.textContent = "No space";
    btn.title = `Needs ${fmtGB(item.size)}; the drive has ${fmtGB(free)} free.`;
    btn.disabled = true;
  } else {
    btn.textContent = "Download";
    btn.addEventListener("click", () => { btn.disabled = true; omPull(item.name); });
  }
  return btn;
}

async function omLoadSuggestions() {
  try {
    const res = await fetch("/api/ollama/suggestions");
    const data = await res.json();
    omState.suggestions = data.suggestions || [];
    if (data.card) omState.card = data.card;
  } catch (err) {
    omState.suggestions = [];
  }
  omRenderSuggestions();
}

function omRenderSuggestions() {
  const box = $("omSuggest");
  if (!box || !omState.suggestions) return;
  const note = $("omCardNote");
  const card = omState.card;
  if (note) {
    note.textContent = card
      ? `Graphics card: ${(card.total_mb / 1024).toFixed(0)} GB${card.evora_mb ? `, Evora uses ${(card.evora_mb / 1024).toFixed(1)} GB` : ""}`
      : "";
  }
  box.replaceChildren();
  if (!omState.suggestions.length) {
    box.append(Object.assign(document.createElement("span"), { className: "om-muted", textContent: "Couldn't reach Ollama's library for suggestions." }));
    return;
  }
  const groups = [];
  omState.suggestions.forEach((s) => {
    let g = groups.find((x) => x.name === s.group);
    if (!g) { g = { name: s.group, items: [] }; groups.push(g); }
    g.items.push(s);
  });
  groups.forEach((g) => {
    const head = document.createElement("div");
    head.className = "om-group";
    head.textContent = g.name;
    box.append(head);
    g.items.forEach((s) => {
      const row = document.createElement("div");
      row.className = "om-row is-suggest";
      const main = document.createElement("div");
      main.className = "om-row-main";
      const title = document.createElement("span");
      title.className = "om-name";
      title.textContent = s.name;
      const meta = document.createElement("span");
      meta.className = "om-meta";
      meta.textContent = [s.size ? fmtGB(s.size) : "", s.note].filter(Boolean).join(" · ");
      if (s.fit) meta.append(" ", omBadge(omFitText(s.fit, card), s.fit));
      main.append(title, meta);
      const actions = document.createElement("div");
      actions.className = "om-actions";
      actions.append(omDownloadButton(s));
      row.append(main, actions);
      box.append(row);
    });
  });
}

async function omCheck(name) {
  const out = $("omLookup");
  if (!out) return;
  out.classList.remove("is-hidden");
  out.replaceChildren(Object.assign(document.createElement("span"), { className: "om-muted", textContent: `Looking up ${name}…` }));
  let data;
  try {
    const res = await fetch(`/api/ollama/suggestions?lookup=${encodeURIComponent(name)}`);
    data = await res.json();
    if (!res.ok) throw new Error(data.error || "Couldn't look it up.");
  } catch (err) {
    out.replaceChildren(Object.assign(document.createElement("span"), { className: "om-muted is-error", textContent: err.message }));
    return;
  }
  const l = data.lookup;
  out.replaceChildren();
  if (!l) {
    out.append(Object.assign(document.createElement("span"), { className: "om-muted is-error", textContent: "That isn't a model name Frivo can use." }));
    return;
  }
  const row = document.createElement("div");
  row.className = "om-row is-suggest";
  const main = document.createElement("div");
  main.className = "om-row-main";
  main.append(Object.assign(document.createElement("span"), { className: "om-name", textContent: l.name }));
  const meta = document.createElement("span");
  meta.className = "om-meta";
  if (!l.found) {
    meta.classList.add("is-error");
    meta.textContent = "Ollama's library doesn't have that. Check the spelling, and include the owner (like huihui_ai/…) for community models.";
  } else {
    meta.textContent = l.size ? fmtGB(l.size) : "Size unknown (not in Ollama's library)";
    if (l.fit) meta.append(" ", omBadge(omFitText(l.fit, data.card), l.fit));
  }
  main.append(meta);
  row.append(main);
  if (l.found) {
    const actions = document.createElement("div");
    actions.className = "om-actions";
    actions.append(omDownloadButton(l));
    row.append(actions);
  }
  out.append(row);
}

(function wireOllamaModels() {
  const card = $("ollamaModels");
  if (!card) return;
  const refresh = $("omRefresh");
  if (refresh) refresh.addEventListener("click", () => { omLoad(); omLoadSuggestions(); });
  const form = $("omGet");
  const input = $("omGetInput");
  if (form && input) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const name = input.value.trim();
      if (name) omCheck(name);
    });
  }
  // Asked when the card comes into view, not on every page load.
  let asked = false;
  const ask = () => {
    if (asked) { omLoad(); return; }
    asked = true;
    omLoad();
    omLoadSuggestions();
  };
  if (typeof IntersectionObserver === "function") {
    new IntersectionObserver((entries) => { if (entries.some((x) => x.isIntersecting)) ask(); }).observe(card);
  } else {
    ask();
  }
})();


// ---------------------------------------------------------------------------
// NEW (1.5.0): the message box with real tag chips.
//
// What you type goes into a rich box (#messageRich) where every [tag] is a
// chip: one Backspace removes it, the cursor can't land inside it, a click
// swaps or removes it, and it can be dragged to another word (it lifts,
// follows your finger smoothly, and a magnifier shows where it will land,
// like moving the cursor on iOS).
//
// The plain box (#messageInput) is still the message as far as the rest of
// Frivo is concerned: the rich box writes into it as you type, and anything
// that sets it (dictation, Suggest, sending) is drawn into the rich box.
// Keys the rest of Frivo listens for (Enter, Tab, Esc, the arrows) are
// passed on to it.
//
// Also here:
//   * Ghost tags: the AI's tag ideas appear faintly in the text, right where
//     they'd go. Tab takes the next one, a click takes that one, Esc hides
//     them. (They replace the pills over the words.)
//   * Instant tags: with a Clean up or Word for word profile and an
//     ElevenLabs voice, "lol", "haha", "ugh"... (your Tag words) and 😂 become
//     their tag as soon as you finish the word. Backspace straight after
//     puts the word back. "Turn lol into tags" in the ✦ menu turns it off.
// ---------------------------------------------------------------------------
var SHORTCUTS_KEY = "frivo_tag_shortcuts";
var TAG_WORD_GUESS = {
  lol: "laughs", haha: "laughs", lmao: "laughs hard", lmfao: "laughs hard", rofl: "laughs hard",
  hehe: "giggles", teehee: "giggles", heh: "chuckles", lel: "chuckles", omg: "gasps",
  ugh: "sighs", smh: "sighs", pfft: "scoffs",
};
var EMOJI_TAGS = [["😂🤣😆😹", "laughs"], ["😭", "sobs"], ["😮‍💨😔😩", "sighs"], ["😱😲", "gasps"], ["😏", "chuckles"]];
var rich = { el: null, input: null, rendering: false, syncing: false, composing: false,
             lastConv: null, keep: new Set(), drag: null, ghostKey: "", menu: null };

function richActive() {
  return Boolean(rich.el && rich.el.isConnected && !rich.el.hidden);
}

function shortcutsOn() {
  try { return localStorage.getItem(SHORTCUTS_KEY) !== "off"; } catch (e) { return true; }
}

function richMakeChip(tag, ghost) {
  const c = document.createElement("span");
  c.className = "rich-chip" + (ghost ? " is-ghost" : "");
  c.contentEditable = "false";
  c.dataset.tag = String(tag).toLowerCase();
  c.textContent = String(tag).toLowerCase();
  if (ghost) c.title = `Tab or click to add [${tag}]`;
  else c.title = "Drag to move · click to swap or remove";
  return c;
}

// The rich box as segments of the message: text, chips, line breaks.
// Ghosts take no room in the message.
function richSegments() {
  const segs = [];
  let pos = 0;
  const walk = (node) => {
    node.childNodes.forEach((n) => {
      if (n.nodeType === 3) {
        segs.push({ n, kind: "text", start: pos, len: n.data.length });
        pos += n.data.length;
      } else if (n.nodeType === 1) {
        if (n.classList.contains("rich-chip")) {
          if (n.classList.contains("is-ghost")) segs.push({ n, kind: "ghost", start: pos, len: 0 });
          else { const len = n.dataset.tag.length + 2; segs.push({ n, kind: "chip", start: pos, len }); pos += len; }
        } else if (n.tagName === "BR") {
          // Every new line here is typed as "\n"; a <br> is only the
          // browser's placeholder at the end, so it takes no room.
          segs.push({ n, kind: "br", start: pos, len: 0 });
        } else {
          // A block the browser made (Enter in some cases): a new line.
          if (pos > 0 && (n.tagName === "DIV" || n.tagName === "P")) { segs.push({ n, kind: "nl", start: pos, len: 1 }); pos += 1; }
          walk(n);
        }
      }
    });
  };
  walk(rich.el);
  segs.total = pos;
  return segs;
}

function richSerialize() {
  let s = "";
  richSegments().forEach((seg) => {
    if (seg.kind === "text") s += seg.n.data.replace(/ /g, " ");
    else if (seg.kind === "chip") s += `[${seg.n.dataset.tag}]`;
    else if (seg.kind === "nl") s += "\n";
  });
  return s;
}

function richOffsetOf(container, offset) {
  const segs = richSegments();
  if (container.nodeType === 3) {
    const seg = segs.find((s) => s.n === container);
    return seg ? seg.start + Math.min(offset, seg.len) : segs.total;
  }
  const child = container.childNodes[offset];
  if (!child) {
    // After the last child of `container`: the end of whatever it holds.
    let end = null;
    segs.forEach((s) => { if (container.contains(s.n)) end = s.start + s.len; });
    return end === null ? (container === rich.el ? segs.total : 0) : end;
  }
  const seg = segs.find((s) => s.n === child || child.contains(s.n));
  return seg ? seg.start : segs.total;
}

function richPointAt(offset) {
  const segs = richSegments();
  for (const s of segs) {
    if (s.kind === "text" && offset >= s.start && offset <= s.start + s.len) return { node: s.n, offset: offset - s.start };
    if ((s.kind === "chip" || s.kind === "ghost" || s.kind === "br") && offset <= s.start) {
      const parent = s.n.parentNode;
      return { node: parent, offset: Array.prototype.indexOf.call(parent.childNodes, s.n) };
    }
  }
  return { node: rich.el, offset: rich.el.childNodes.length };
}

function richCaretOffset() {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount || !rich.el.contains(sel.anchorNode)) return null;
  const a = richOffsetOf(sel.anchorNode, sel.anchorOffset);
  const f = richOffsetOf(sel.focusNode, sel.focusOffset);
  return { start: Math.min(a, f), end: Math.max(a, f) };
}

function richSetCaret(start, end = start) {
  const sel = window.getSelection();
  if (!sel) return;
  const a = richPointAt(start);
  const b = end === start ? a : richPointAt(end);
  const range = document.createRange();
  try {
    range.setStart(a.node, a.offset);
    range.setEnd(b.node, b.offset);
    sel.removeAllRanges();
    sel.addRange(range);
  } catch (e) { /* the box changed under us */ }
}

// The rich box, drawn from the message. Keeps the cursor where it was.
function richRender(value, caret) {
  if (!rich.el) return;
  rich.rendering = true;
  const focused = document.activeElement === rich.el;
  const keep = caret != null ? caret : (focused ? richCaretOffset() : null);
  const frag = document.createDocumentFragment();
  const re = /\[([A-Za-z][A-Za-z' \-]{0,38})\]/g;
  let last = 0;
  let m;
  while ((m = re.exec(value))) {
    if (m.index > last) frag.append(document.createTextNode(value.slice(last, m.index)));
    frag.append(richMakeChip(m[1]));
    last = m.index + m[0].length;
  }
  if (last < value.length) frag.append(document.createTextNode(value.slice(last)));
  if (value.endsWith("\n")) {   // so a new last line shows
    const pad = document.createElement("br");
    pad.dataset.pad = "1";
    frag.append(pad);
  }
  rich.el.replaceChildren(frag);
  rich.ghostKey = "";
  richRenderGhosts();
  if (focused && keep) richSetCaret(typeof keep === "number" ? keep : keep.start, typeof keep === "number" ? keep : keep.end);
  rich.el.classList.toggle("is-empty", !value);
  rich.rendering = false;
}

// Writes the rich box's message into the plain box, and tells everyone.
function richPush(inputType) {
  const value = richSerialize();
  const caret = richCaretOffset();
  rich.syncing = true;
  rich.nativeSet.call(rich.input, value);
  if (caret) rich.nativeSelect.call(rich.input, caret.start, caret.end);
  rich.syncing = false;
  rich.el.classList.toggle("is-empty", !value);
  rich.input.dispatchEvent(new Event("input", { bubbles: true }));
  return { value, caret };
}

function richSyncSelection() {
  if (!richActive() || document.activeElement !== rich.el || rich.rendering) return;
  const caret = richCaretOffset();
  if (caret) rich.nativeSelect.call(rich.input, caret.start, caret.end);
}

// ---- instant tags ----
function wordTag(word) {
  const raw = String(word || "");
  for (const [chars, tag] of EMOJI_TAGS) {
    if ([...chars].some((c) => raw.includes(c)) && !/[A-Za-z]/.test(raw)) return tag;
  }
  const w = raw.toLowerCase().replace(/^[^\w]+|[^\w]+$/g, "").replace(/\s+/g, " ");
  if (!w) return null;
  const list = Array.isArray(tagWordsState) ? tagWordsState : Object.keys(TAG_WORD_GUESS).map((x) => ({ word: x, tag: "" }));
  for (const entry of list) {
    const base = String(entry.word || "").toLowerCase();
    if (!base) continue;
    let hit = w === base;
    if (!hit && /^([a-z]{2})\1+$/.test(base)) {            // haha, hehe: any number of repeats
      const unit = base.slice(0, 2);
      hit = new RegExp(`^a?(?:${unit}){2,}${unit[0]}?$`).test(w);
    }
    if (!hit && base === "lol") hit = /^lo+l(?:ol)*$/.test(w);
    if (!hit && base === "omg") hit = /^omg+$/.test(w);
    if (!hit && base === "ugh") hit = /^ug+h+$/.test(w);
    if (hit) {
      if (entry.tag) return entry.tag;
      const guess = TAG_WORD_GUESS[base];
      if (guess === "laughs" && /^[A-Z]{3,}$/.test(raw.replace(/[^A-Za-z]/g, ""))) return "laughs hard";
      return guess || null;
    }
  }
  return null;
}

function richShortcut(typed) {
  if (!shortcutsOn() || !elevenVoiceNow() || activeVoiceStyle().style === "reply") return;
  if (bracketState.open) return;
  const value = rich.input.value;
  const caret = richCaretOffset();
  if (!caret || caret.start !== caret.end) return;
  const before = value.slice(0, caret.start - typed.length);
  // The last word, or the last two ("im dead").
  let word = "";
  let tag = null;
  for (const re of [/(^|\s)([^\s\[\]]+ [^\s\[\]]+)$/, /(^|\s)([^\s\[\]]+)$/]) {
    const m = before.match(re);
    if (m && (tag = wordTag(m[2]))) { word = m[2]; break; }
  }
  if (!tag) return;
  const start = before.length - word.length;
  if (rich.keep.has(`${start}:${word}`)) return;
  const next = value.slice(0, start) + `[${tag}]` + value.slice(before.length);
  const shift = `[${tag}]`.length - word.length;
  rich.syncing = true;
  rich.nativeSet.call(rich.input, next);
  rich.syncing = false;
  richRender(next, caret.start + shift);
  richPush();
  rich.lastConv = { start, word, tag, caret: caret.start + shift, typed };
  if (typeof noteTagOffers === "function") { /* your own: counts as added */ }
}

function richUndoShortcut() {
  const c = rich.lastConv;
  rich.lastConv = null;
  if (!c) return false;
  const value = rich.input.value;
  const caret = richCaretOffset();
  const chip = `[${c.tag}]`;
  if (!caret || caret.start !== c.caret || value.slice(c.start, c.start + chip.length) !== chip) return false;
  const next = value.slice(0, c.start) + c.word + value.slice(c.start + chip.length);
  rich.keep.add(`${c.start}:${c.word}`);
  rich.syncing = true;
  rich.nativeSet.call(rich.input, next);
  rich.syncing = false;
  richRender(next, c.caret - chip.length + c.word.length);
  richPush();
  return true;
}

// ---- ghost tags (the AI's ideas, in place) ----
function richRenderGhosts() {
  if (!richActive() || rich.composing) return;
  const st = typeof tagIdeasState === "object" ? tagIdeasState : null;
  const ideas = st && !st.paused && tagIdeasOn() && !autoTagsOn() && elevenVoiceNow()
    ? st.ideas.filter((i) => tagIdeaPlace(i)) : [];
  const key = ideas.map((i) => `${i.key}`).join("|");
  const present = rich.el.querySelectorAll(".rich-chip.is-ghost").length;
  if (key === rich.ghostKey && present === ideas.length) return;
  rich.ghostKey = key;
  const caret = document.activeElement === rich.el ? richCaretOffset() : null;
  const wasRendering = rich.rendering;
  rich.rendering = true;
  rich.el.querySelectorAll(".rich-chip.is-ghost").forEach((g) => g.remove());
  rich.el.normalize();
  ideas.slice().sort((a, b) => tagIdeaPlace(b).offset - tagIdeaPlace(a).offset).forEach((idea) => {
    const place = tagIdeaPlace(idea);
    const ghost = richMakeChip(idea.tag, true);
    ghost._idea = idea;
    ghost.addEventListener("mousedown", (e) => e.preventDefault());
    ghost.addEventListener("click", (e) => { e.preventDefault(); applyTagIdeas([idea]); });
    const point = richPointAt(place.offset);
    if (point.node.nodeType === 3) {
      const after = point.node.splitText(point.offset);
      after.parentNode.insertBefore(ghost, after);
      if (place.end) ghost.before(document.createTextNode(" "));
    } else {
      point.node.insertBefore(ghost, point.node.childNodes[point.offset] || null);
    }
  });
  if (caret) richSetCaret(caret.start, caret.end);
  rich.rendering = wasRendering;
}

function richTakeGhost() {
  const ghosts = Array.from(rich.el.querySelectorAll(".rich-chip.is-ghost"));
  if (!ghosts.length) return false;
  const caret = richCaretOffset();
  const segs = richSegments();
  const at = (g) => (segs.find((s) => s.n === g) || { start: 0 }).start;
  const after = caret ? ghosts.filter((g) => at(g) >= caret.start) : ghosts;
  const pick = (after.length ? after : ghosts).sort((a, b) => at(a) - at(b))[0];
  applyTagIdeas([pick._idea]);
  return true;
}

// ---- a chip's menu: swap or remove ----
function richCloseMenu() {
  if (rich.menu) { rich.menu.remove(); rich.menu = null; }
}

// CHANGED (1.7.0): a box at the top to type any tag of your own, with
// matching tags listed as you type (the ones you use, Frivo's, yours);
// otherwise suggestions that fit the one you clicked. Arrows choose, Enter
// takes it, Esc closes.
function richOpenMenu(chip) {
  richCloseMenu();
  const composer = rich.el.closest(".composer");
  const current = chip.dataset.tag || "";
  const menu = document.createElement("div");
  menu.className = "rich-chip-menu";
  menu.setAttribute("role", "dialog");
  menu.setAttribute("aria-label", `Change [${current}]`);

  const replaceWith = (tag) => {
    const segs = richSegments();
    const seg = segs.find((s) => s.n === chip);
    if (!seg) return;
    const value = rich.input.value;
    let next = value.slice(0, seg.start) + (tag ? `[${tag}]` : "") + value.slice(seg.start + seg.len);
    if (!tag) next = next.replace(/ {2,}/g, " ").replace(/^ /, "");
    rich.syncing = true;
    rich.nativeSet.call(rich.input, next);
    rich.syncing = false;
    richRender(next, seg.start + (tag ? tag.length + 2 : 0));
    richPush();
    richCloseMenu();
    rich.el.focus();
  };

  const form = document.createElement("form");
  form.className = "rich-chip-menu-form";
  form.setAttribute("autocomplete", "off");
  const input = document.createElement("input");
  input.type = "text";
  input.maxLength = 38;
  input.placeholder = "Type any tag…";
  input.setAttribute("aria-label", "Type a tag");
  input.spellcheck = false;
  form.append(input);
  const label = document.createElement("span");
  label.className = "rich-chip-menu-label";
  const list = document.createElement("div");
  list.className = "rich-chip-menu-list";
  list.setAttribute("role", "listbox");
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "is-remove";
  remove.textContent = "Remove this tag";
  remove.addEventListener("mousedown", (e) => e.preventDefault());
  remove.addEventListener("click", () => replaceWith(null));
  menu.append(form, label, list, remove);

  const VALID = /^[A-Za-z][A-Za-z' \-]{0,37}$/;
  const everyTag = () => Array.from(new Set([
    ...((typeof bracketState === "object" && bracketState.likes) || []),
    ...(typeof yourTags === "function" ? yourTags() : []),
    ...(audioTagGroups || []).flatMap((g) => g.tags || []),
  ]));
  let items = [];
  let active = 0;
  const paint = () => {
    list.querySelectorAll("button").forEach((b, i) => b.classList.toggle("is-active", i === active));
  };
  const fill = () => {
    const q = input.value.trim().toLowerCase().replace(/^\[|\]$/g, "");
    if (q) {
      const matches = everyTag().filter((t) => t !== current && t.toLowerCase().includes(q))
        .sort((a, b) => (a.toLowerCase().startsWith(q) ? 0 : 1) - (b.toLowerCase().startsWith(q) ? 0 : 1));
      items = matches.slice(0, 6).map((t) => ({ tag: t }));
      if (VALID.test(q) && !matches.some((t) => t.toLowerCase() === q)) items.push({ tag: q, custom: true });
      label.textContent = !items.length ? "Letters, spaces, ' and - only"
        : items.every((i) => i.custom) ? "Your own tag" : "Matches";
    } else {
      items = (typeof tagSwaps === "function" ? tagSwaps(current) : []).map((t) => ({ tag: t }));
      label.textContent = "Swap for";
    }
    active = 0;
    list.replaceChildren(...items.map((item, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "option");
      if (item.custom) {
        b.classList.add("is-custom");
        b.innerHTML = `Use <span class="rich-chip-menu-tag"></span>`;
        b.querySelector("span").textContent = `[${item.tag}]`;
      } else {
        b.textContent = item.tag;
      }
      b.addEventListener("mousedown", (e) => e.preventDefault());
      b.addEventListener("mouseenter", () => { active = i; paint(); });
      b.addEventListener("click", () => take(item));
      return b;
    }));
    paint();
  };
  const take = (item) => {
    if (!item) return;
    if (item.custom && typeof rememberYourTag === "function") rememberYourTag(item.tag);
    replaceWith(item.tag);
  };
  input.addEventListener("input", fill);
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(items.length - 1, active + 1); paint(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); paint(); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); richCloseMenu(); rich.el.focus(); }
  });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value.trim().replace(/^\[|\]$/g, "");
    if (items[active]) take(items[active]);
    else if (VALID.test(q)) take({ tag: q, custom: true });
  });
  fill();

  composer.append(menu);
  const c = chip.getBoundingClientRect();
  const box = composer.getBoundingClientRect();
  const width = menu.offsetWidth || 220;
  menu.style.left = `${Math.max(8, Math.min(c.left - box.left, box.width - width - 8))}px`;
  menu.style.bottom = `${box.bottom - c.top + 6}px`;
  rich.menu = menu;
  // Typing goes straight into the box; the message keeps its place.
  setTimeout(() => input.focus(), 0);
}

// ---- dragging a chip: lift, follow, magnify, settle ----
function richDropTargets(chip) {
  // Every place a tag can go: before each word, and the end. Measured once,
  // as nothing moves while you drag.
  const out = [];
  const segs = richSegments();
  const chipSeg = segs.find((s) => s.n === chip);
  const value = rich.input.value;
  const re = /\S+/g;
  const box = rich.el.getBoundingClientRect();
  const rectAt = (offset) => {
    const p = richPointAt(offset);
    const r = document.createRange();
    try { r.setStart(p.node, p.offset); r.collapse(true); } catch (e) { return null; }
    let rect = r.getClientRects()[0];
    if (!rect) {
      const probe = document.createElement("span");
      probe.textContent = "​";
      r.insertNode(probe);
      rect = probe.getBoundingClientRect();
      probe.remove();
      rich.el.normalize();
    }
    return rect;
  };
  let m;
  const starts = [];
  while ((m = re.exec(value))) {
    const token = m[0];
    if (/^\[[A-Za-z][A-Za-z' \-]{0,38}\]$/.test(token)) continue;
    starts.push(m.index);
  }
  starts.push(value.length);
  starts.forEach((offset) => {
    if (chipSeg && (offset === chipSeg.start || offset === chipSeg.start + chipSeg.len + 1)) return;   // where it is now
    const rect = rectAt(offset);
    if (!rect || (!rect.width && !rect.height && !rect.top)) return;
    out.push({ offset, x: rect.left, y: rect.top, h: rect.height || 20, inBox: rect.top >= box.top - 4 && rect.bottom <= box.bottom + 4 });
  });
  return out;
}

// CHANGED (1.5.0): while you drag, the text where the tag would land is
// gently magnified: a soft-edged circle, no outline, that blends into the
// words around it and glides smoothly from place to place.
var DROP_SIZE = 58;
var dropMapUrl = null;

function dropRefractionMap() {
  // A displacement map that pulls the middle of the drop outward (it
  // magnifies there) and leaves the rim alone: what a lens does.
  if (dropMapUrl) return dropMapUrl;
  const n = DROP_SIZE * 2;
  const canvas = document.createElement("canvas");
  canvas.width = n;
  canvas.height = n;
  const ctx = canvas.getContext("2d");
  const img = ctx.createImageData(n, n);
  const c = (n - 1) / 2;
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      const nx = (x - c) / c;
      const ny = (y - c) / c;
      const r2 = nx * nx + ny * ny;
      const f = r2 < 1 ? (1 - r2) * (1 - r2) : 0;   // strongest in the middle, nothing at the edge: no seam
      const i = (y * n + x) * 4;
      img.data[i] = Math.round(255 * (0.5 - 0.5 * nx * f));
      img.data[i + 1] = Math.round(255 * (0.5 - 0.5 * ny * f));
      img.data[i + 2] = 128;
      img.data[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  dropMapUrl = canvas.toDataURL();
  return dropMapUrl;
}

function ensureDropFilter() {
  if (document.getElementById("frivoDropFilter")) return;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("width", "0");
  svg.setAttribute("height", "0");
  svg.setAttribute("aria-hidden", "true");
  svg.style.position = "absolute";
  const filter = document.createElementNS(ns, "filter");
  filter.id = "frivoDropFilter";
  filter.setAttribute("x", "0");
  filter.setAttribute("y", "0");
  filter.setAttribute("width", String(DROP_SIZE));
  filter.setAttribute("height", String(DROP_SIZE));
  filter.setAttribute("filterUnits", "userSpaceOnUse");
  filter.setAttribute("color-interpolation-filters", "sRGB");
  const image = document.createElementNS(ns, "feImage");
  image.setAttribute("href", dropRefractionMap());
  image.setAttribute("x", "0");
  image.setAttribute("y", "0");
  image.setAttribute("width", String(DROP_SIZE));
  image.setAttribute("height", String(DROP_SIZE));
  image.setAttribute("preserveAspectRatio", "none");
  image.setAttribute("result", "map");
  const displace = document.createElementNS(ns, "feDisplacementMap");
  displace.setAttribute("in", "SourceGraphic");
  displace.setAttribute("in2", "map");
  displace.setAttribute("scale", String(Math.round(DROP_SIZE * 0.24)));   // about 1.3× in the middle
  displace.setAttribute("xChannelSelector", "R");
  displace.setAttribute("yChannelSelector", "G");
  filter.append(image, displace);
  svg.append(filter);
  document.body.append(svg);
}

function richStartDrag(chip, e) {
  richCloseMenu();
  rich.el.querySelectorAll(".rich-chip.is-ghost").forEach((g) => g.remove());
  const rect = chip.getBoundingClientRect();
  const targets = richDropTargets(chip);
  const floating = chip.cloneNode(true);
  floating.className = "rich-chip is-floating";
  floating.style.left = `${rect.left}px`;
  floating.style.top = `${rect.top}px`;
  document.body.append(floating);
  chip.classList.add("is-lifted");
  // The drop: a circle holding a copy of the text, enlarged about its
  // middle and bent by the filter. A caret in the copy marks the spot.
  const drop = document.createElement("div");
  drop.className = "rich-drop";
  const glass = document.createElement("div");
  glass.className = "rich-drop-glass";
  const lens = rich.el.cloneNode(true);
  lens.removeAttribute("id");
  lens.removeAttribute("contenteditable");
  lens.className = "rich-lens";
  lens.style.width = `${rich.el.clientWidth}px`;
  const lensCaret = document.createElement("span");
  lensCaret.className = "rich-lens-caret";
  glass.append(lens, lensCaret);
  drop.append(glass);
  document.body.append(drop);
  rich.el.classList.add("is-dragging");
  const d = {
    chip, floating, drop, glass, lens, lensCaret, targets,
    grabX: e.clientX - rect.left, grabY: e.clientY - rect.top,
    px: e.clientX, py: e.clientY, x: rect.left, y: rect.top, vx: 0,
    target: null, raf: 0, fx: null, fy: null, dvx: 0, dvy: 0, h: 20, shown: false,
  };
  rich.drag = d;
  const frame = () => {
    if (rich.drag !== d) return;
    // The chip follows with a little lag, like something with weight.
    const tx = d.px - d.grabX;
    const ty = d.py - d.grabY - 46;   // held above the pointer, so the drop shows
    const nx = d.x + (tx - d.x) * 0.32;
    const ny = d.y + (ty - d.y) * 0.32;
    d.vx = d.vx * 0.7 + (nx - d.x) * 0.3;
    d.x = nx;
    d.y = ny;
    const tilt = Math.max(-6, Math.min(6, d.vx * 0.6));
    floating.style.transform = `translate3d(${d.x - rect.left}px, ${d.y - rect.top}px, 0) scale(1.1) rotate(${tilt}deg)`;
    // The nearest place it could go.
    let best = null;
    let bestD = Infinity;
    d.targets.forEach((t) => {
      const dx = d.px - t.x;
      const dy = (d.py - (t.y + t.h / 2)) * 2.2;   // lines matter more than columns
      const dist = dx * dx + dy * dy;
      if (dist < bestD) { bestD = dist; best = t; }
    });
    d.target = best;
    if (best) {
      // The drop glides there, and stretches the way it's moving.
      const gx = best.x;
      const gy = best.y + best.h / 2;
      if (d.fx === null) { d.fx = gx; d.fy = gy; }
      const ox = d.fx;
      const oy = d.fy;
      d.fx += (gx - d.fx) * 0.24;
      d.fy += (gy - d.fy) * 0.24;
      d.dvx = d.dvx * 0.6 + (d.fx - ox) * 0.4;
      d.dvy = d.dvy * 0.6 + (d.fy - oy) * 0.4;
      d.h += (best.h - d.h) * 0.3;
      const half = DROP_SIZE / 2;
      d.drop.style.transform = `translate3d(${(d.fx - half).toFixed(1)}px, ${(d.fy - half).toFixed(1)}px, 0)`;
      // The copy of the text lines up with the real text under the drop,
      // enlarged about the drop's middle.
      const box = rich.el.getBoundingClientRect();
      const lx = box.left - (d.fx - half);
      const ly = box.top - (d.fy - half) - rich.el.scrollTop;
      const ix = d.fx - box.left;
      const iy = d.fy - box.top + rich.el.scrollTop;
      lens.style.left = `${lx.toFixed(1)}px`;
      lens.style.top = `${ly.toFixed(1)}px`;
      lens.style.transformOrigin = `${ix.toFixed(1)}px ${iy.toFixed(1)}px`;
      lensCaret.style.height = `${(d.h * 1.25).toFixed(1)}px`;
      lensCaret.style.top = `${(half - d.h * 0.625).toFixed(1)}px`;
      if (!d.shown) { d.shown = true; d.drop.classList.add("is-on"); }
    }
    d.raf = requestAnimationFrame(frame);
  };
  d.raf = requestAnimationFrame(frame);
}

function richEndDrag(cancel) {
  const d = rich.drag;
  if (!d) return;
  rich.drag = null;
  cancelAnimationFrame(d.raf);
  rich.el.classList.remove("is-dragging");
  // The drop shrinks away as the tag falls into place.
  d.drop.classList.remove("is-on");
  d.drop.classList.add("is-leaving");
  setTimeout(() => d.drop.remove(), 240);
  richFinishDrop(d, cancel);
}

function richFinishDrop(d, cancel) {
  const settle = (el) => {
    // The floating chip glides into its new place, then the real one shows.
    const to = el ? el.getBoundingClientRect() : null;
    const base = { left: parseFloat(d.floating.style.left), top: parseFloat(d.floating.style.top) };
    d.floating.classList.add("is-settling");
    if (to) d.floating.style.transform = `translate3d(${to.left - base.left}px, ${to.top - base.top}px, 0) scale(1)`;
    if (el) el.classList.add("is-arriving");
    setTimeout(() => {
      d.floating.remove();
      if (el) {
        el.classList.remove("is-arriving", "is-lifted");
        el.classList.add("is-landed");
        setTimeout(() => el.classList.remove("is-landed"), 260);
      }
    }, 230);
  };
  const value = rich.input.value;
  if (cancel || !d.target) {
    richRender(value);
    const back = richSegments().find((s) => s.kind === "chip" && s.n.dataset.tag === d.chip.dataset.tag);
    settle(back ? back.n : null);
    return;
  }
  // Read where the chip was before the box is redrawn.
  const segs = richSegments();
  const seg = segs.find((s) => s.n === d.chip);
  if (!seg) { richRender(value); d.floating.remove(); return; }
  const token = `[${d.chip.dataset.tag}]`;
  // Out of its old place, with the space after it.
  let from = seg.start;
  let len = seg.len;
  if (value[from + len] === " ") len += 1;
  else if (from > 0 && value[from - 1] === " ") { from -= 1; len += 1; }
  let to = d.target.offset;
  const without = value.slice(0, from) + value.slice(from + len);
  if (to > from) to -= len;
  const atEnd = to >= without.length;
  const insert = atEnd ? (without && !without.endsWith(" ") ? " " : "") + token : token + " ";
  const next = without.slice(0, to) + insert + without.slice(to);
  const chipAt = atEnd ? to + insert.length - token.length : to;
  rich.syncing = true;
  rich.nativeSet.call(rich.input, next);
  rich.syncing = false;
  richRender(next);
  richPush();
  const landed = richSegments().find((s) => s.kind === "chip" && s.start === chipAt);
  if (landed) landed.n.classList.add("is-lifted");
  settle(landed ? landed.n : null);
}

(function wireRichBox() {
  const input = $("messageInput");
  const box = $("messageRich");
  if (!input || !box || input.tagName !== "TEXTAREA") return;
  rich.el = box;
  rich.input = input;
  const proto = HTMLTextAreaElement.prototype;
  const own = Object.getOwnPropertyDescriptor(input, "value");
  const base = own || Object.getOwnPropertyDescriptor(proto, "value");
  rich.nativeSet = (v) => base.set.call(input, v);
  rich.nativeSet = function (v) { base.set.call(input, v); };
  rich.nativeSelect = proto.setSelectionRange;
  const composer = input.closest(".composer");
  if (composer) composer.classList.add("has-rich");
  box.dataset.placeholder = input.getAttribute("placeholder") || "";

  // Anything that sets the plain box is drawn here.
  Object.defineProperty(input, "value", {
    configurable: true,
    get() { return base.get.call(this); },
    set(v) {
      base.set.call(this, v);
      if (!rich.syncing) richRender(String(v), document.activeElement === box ? String(v).length : null);
    },
  });
  input.setSelectionRange = function (start, end, dir) {
    rich.nativeSelect.call(this, start, end, dir);
    if (document.activeElement === box) richSetCaret(start, end);
  };
  input.select = function () {   // "select all" means in the box you see
    const n = rich.input.value.length;
    rich.nativeSelect.call(this, 0, n);
    if (document.activeElement !== box) box.focus({ preventScroll: true });
    richSetCaret(0, n);
  };
  input.focus = function () {
    box.focus({ preventScroll: true });
    const s = rich.input.selectionStart;
    richSetCaret(Number.isInteger(s) ? s : rich.input.value.length);
  };
  // A test or the browser setting the plain box directly.
  input.addEventListener("input", () => { if (!rich.syncing && richSerialize() !== input.value) richRender(input.value); });
  input.addEventListener("focus", () => input.focus());
  // Text selected in the plain box (by a script) is selected here too.
  const mirrorSelection = () => {
    if (rich.syncing || rich.rendering) return;
    const now = document.activeElement === box ? richCaretOffset() : null;
    if (now && now.start === input.selectionStart && now.end === input.selectionEnd) return;   // already so
    if (document.activeElement !== box) box.focus({ preventScroll: true });
    richSetCaret(input.selectionStart, input.selectionEnd);
  };
  input.addEventListener("select", mirrorSelection);
  input.addEventListener("selectionchange", mirrorSelection);

  box.addEventListener("compositionstart", () => { rich.composing = true; });
  box.addEventListener("compositionend", () => { rich.composing = false; richPush(); });
  box.addEventListener("beforeinput", (e) => {
    // Pasted or dropped text comes in plain.
    if (e.inputType === "insertFromPaste" || e.inputType === "insertFromDrop") return;
    if (e.inputType === "insertParagraph" || e.inputType === "insertLineBreak") {
      e.preventDefault();
      document.execCommand("insertText", false, "\n");
    }
  });
  box.addEventListener("paste", (e) => {
    e.preventDefault();
    const text = (e.clipboardData && e.clipboardData.getData("text/plain")) || "";
    document.execCommand("insertText", false, text);
  });
  box.addEventListener("drop", (e) => e.preventDefault());
  box.addEventListener("input", (e) => {
    if (rich.rendering || rich.composing) return;
    const typed = e.data || "";
    if (e.inputType !== "insertText" || !/^[\s.,!?;:]$/.test(typed)) rich.lastConv = null;
    // The browser wrapped something (a pasted block, a new line): tidy it.
    const messy = box.querySelector("div, p, span:not(.rich-chip), font, b, i");
    const { value, caret } = richPush();
    // A tag typed in full ("[laughs]"), or pasted: a chip.
    const typedTag = Array.from(box.childNodes).some((n) => n.nodeType === 3 && /\[[A-Za-z][A-Za-z' \-]{0,38}\]/.test(n.data));
    if (messy || typedTag) richRender(value, caret ? caret.start : value.length);
    if (e.inputType === "insertText" && /^[\s.,!?;:]$/.test(typed)) richShortcut(typed);
  });
  // The keys the rest of Frivo listens for on the plain box.
  box.addEventListener("keydown", (e) => {
    if (rich.drag) {
      if (e.key === "Escape") { e.preventDefault(); richEndDrag(true); }
      return;
    }
    if (e.key === "Backspace" && rich.lastConv && !e.shiftKey) {
      if (richUndoShortcut()) { e.preventDefault(); return; }
    }
    if (e.key !== "Backspace") rich.lastConv = e.key.length === 1 ? rich.lastConv : null;
    if (e.key === "Escape" && rich.menu) { e.preventDefault(); richCloseMenu(); return; }
    if (e.key === "Tab" && !e.shiftKey && !bracketState.open) {
      if (richTakeGhost()) { e.preventDefault(); return; }
    }
    if (e.key === "Escape" && !bracketState.open && box.querySelector(".rich-chip.is-ghost")) {
      e.preventDefault();
      if (typeof tagIdeasState === "object") { tagIdeasState.paused = true; tagIdeasState.ideas = []; }
      richRenderGhosts();
      return;
    }
    if (!["Enter", "Tab", "Escape", "ArrowUp", "ArrowDown"].includes(e.key)) return;
    richSyncSelection();
    const copy = new KeyboardEvent("keydown", {
      key: e.key, code: e.code, shiftKey: e.shiftKey, ctrlKey: e.ctrlKey, altKey: e.altKey, metaKey: e.metaKey,
      isComposing: e.isComposing, bubbles: true, cancelable: true,
    });
    input.dispatchEvent(copy);
    if (copy.defaultPrevented) e.preventDefault();
    else if (e.key === "Enter" && !e.isComposing) {
      e.preventDefault();
      document.execCommand("insertText", false, "\n");
    }
  });
  ["click", "keyup"].forEach((type) => box.addEventListener(type, () => {
    richSyncSelection();
    input.dispatchEvent(new Event(type, { bubbles: false }));
  }));
  box.addEventListener("blur", () => input.dispatchEvent(new Event("blur")));
  document.addEventListener("selectionchange", richSyncSelection);
  box.addEventListener("scroll", () => input.dispatchEvent(new Event("scroll")));

  // Chips: click for the menu, drag to move.
  box.addEventListener("pointerdown", (e) => {
    const chip = e.target.closest && e.target.closest(".rich-chip:not(.is-ghost)");
    if (!chip || e.button !== 0) return;
    e.preventDefault();
    const sx = e.clientX;
    const sy = e.clientY;
    let started = false;
    const move = (ev) => {
      if (!started && Math.hypot(ev.clientX - sx, ev.clientY - sy) > 4) {
        started = true;
        richStartDrag(chip, ev);
      }
      if (started && rich.drag) { rich.drag.px = ev.clientX; rich.drag.py = ev.clientY; }
    };
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", cancel);
      if (started) richEndDrag(false);
      else richOpenMenu(chip);
    };
    const cancel = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", cancel);
      if (started) richEndDrag(true);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", cancel);
  });
  document.addEventListener("pointerdown", (e) => {
    if (rich.menu && !rich.menu.contains(e.target) && !(e.target.closest && e.target.closest(".rich-chip"))) richCloseMenu();
  });

  // The ✦ menu switch.
  const toggle = $("tagShortcutsToggle");
  if (toggle) {
    toggle.checked = shortcutsOn();
    toggle.addEventListener("change", () => {
      try { localStorage.setItem(SHORTCUTS_KEY, toggle.checked ? "on" : "off"); } catch (e) { /* not kept */ }
    });
  }
  richRender(input.value);
})();


// ---------------------------------------------------------------------------
// NEW (1.5.0): the ElevenLabs key, actually tried. The Accounts row says
// Connected only when ElevenLabs answers; otherwise what's wrong (a wrong
// key, or one not allowed to read your voices). The key page shows the
// details: how many voices, how many your own, and the plan.
// ---------------------------------------------------------------------------
var elevenCheckAt = 0;

async function checkElevenKey(force) {
  if (!force && Date.now() - elevenCheckAt < 20000) return;
  elevenCheckAt = Date.now();
  const text = $("elevenStatusText");
  const lamp = $("elevenStatus");
  const box = $("elevenKeyCheck");
  let d;
  try {
    const res = await fetch("/api/elevenlabs/check");
    d = await res.json();
  } catch (e) {
    return;
  }
  const words = {
    ok: "Connected",
    partial: "Connected",
    no_voices: "Can't read voices",
    invalid: "Key not accepted",
    unreachable: "Can't reach ElevenLabs",
    missing: "Not set",
  }[d.state] || "Saved";
  if (text) text.textContent = words;
  if (lamp) {
    lamp.classList.toggle("is-lit", d.state === "ok" || d.state === "partial");
    lamp.classList.toggle("is-warn", !["ok", "partial", "missing"].includes(d.state));
  }
  if (!box) return;
  box.replaceChildren();
  box.classList.toggle("is-hidden", d.state === "missing");
  box.classList.toggle("is-bad", !["ok", "partial"].includes(d.state));
  const line = (t, cls) => {
    const p = document.createElement("p");
    p.className = "key-check-line" + (cls ? ` ${cls}` : "");
    p.textContent = t;
    box.append(p);
  };
  if (d.voices != null) {
    line(`✓ ${d.voices} voices, ${d.own_voices} of them yours (clones and ones you added from the Voice Library).`, "is-ok");
  }
  if (d.account && d.account.limit) {
    line(`✓ ${d.account.tier ? d.account.tier[0].toUpperCase() + d.account.tier.slice(1) + " plan, " : ""}${(d.account.limit - d.account.used).toLocaleString()} of ${d.account.limit.toLocaleString()} credits left.`, "is-ok");
  }
  (d.problems || []).forEach((p) => line(`✗ ${p.message}`, "is-bad"));
  const again = document.createElement("button");
  again.type = "button";
  again.className = "link-btn";
  again.textContent = "Check again";
  again.addEventListener("click", async () => {
    await checkElevenKey(true);
    if (typeof loadVoices === "function") loadVoices();
  });
  box.append(again);
}


// ---------------------------------------------------------------------------
// NEW (1.5.0): back up and restore (Settings > Updates & backup).
// The server zips what it keeps; the page adds what this browser keeps
// (favourite voices, your tags, recent voices, the switches), and puts it
// back on restore.
// ---------------------------------------------------------------------------
(function initBackup() {
  const makeRow = $("backupMakeRow");
  const fileInput = $("backupFile");
  const result = $("backupResult");
  if (!makeRow || !fileInput || !result) return;
  const PREFIXES = ["voice_console_", "frivo_"];
  const SKIP = new Set(["voice_console_session", "frivo_transcript_v1", "voice_console_mic_device_id",
    "voice_console_listen_device"]);
  // Lists that are merged with what's here rather than replaced.
  const LIST_KEYS = new Set(["voice_console_voice_favorites", "frivo_your_tags", "voice_console_voice_recents",
    "voice_console_language_recents"]);

  function browserData() {
    const out = {};
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && PREFIXES.some((p) => k.startsWith(p)) && !SKIP.has(k)) out[k] = localStorage.getItem(k);
      }
    } catch (_) { /* storage blocked: the server part still backs up */ }
    return out;
  }

  function mergeList(here, incoming) {
    let a, b;
    try { a = JSON.parse(here || "[]"); b = JSON.parse(incoming || "[]"); } catch (_) { return incoming; }
    if (!Array.isArray(a) || !Array.isArray(b)) return incoming;
    const seen = new Set(a.map((x) => JSON.stringify(x)));
    return JSON.stringify(a.concat(b.filter((x) => !seen.has(JSON.stringify(x)))));
  }

  function putBrowserData(data) {
    let n = 0;
    try {
      Object.entries(data || {}).forEach(([k, v]) => {
        if (!PREFIXES.some((p) => k.startsWith(p)) || SKIP.has(k) || typeof v !== "string") return;
        const here = localStorage.getItem(k);
        localStorage.setItem(k, LIST_KEYS.has(k) && here ? mergeList(here, v) : v);
        n++;
      });
    } catch (_) { /* storage blocked */ }
    return n;
  }

  function show(html, isError) {
    result.innerHTML = html;
    result.classList.toggle("is-error", !!isError);
    result.classList.remove("is-hidden");
  }
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  makeRow.addEventListener("click", async () => {
    makeRow.classList.add("is-busy");
    $("backupMakeValue").textContent = "Making…";
    try {
      const res = await fetch("/api/backup", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ include_keys: $("backupKeysToggle").checked,
          include_voices: $("backupVoicesToggle").checked, browser: browserData() }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || `Frivo said ${res.status}`);
      const blob = await res.blob();
      const name = (/filename="?([^";]+)"?/.exec(res.headers.get("Content-Disposition") || "") || [])[1]
        || "Frivo backup.zip";
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 4000);
      $("backupMakeValue").textContent = blob.size < 1048576 ? `${Math.max(1, Math.round(blob.size / 1024))} KB`
        : `${(blob.size / 1048576).toFixed(blob.size > 10485760 ? 0 : 1)} MB`;
      result.classList.add("is-hidden");
    } catch (err) {
      $("backupMakeValue").textContent = "";
      show(`Couldn't make the backup: ${esc(err.message || err)}`, true);
    } finally {
      makeRow.classList.remove("is-busy");
    }
  });

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files && fileInput.files[0];
    fileInput.value = "";
    if (!file) return;
    const row = $("backupRestoreRow");
    row.classList.add("is-busy");
    $("backupRestoreValue").textContent = "Restoring…";
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch("/api/backup/restore", { method: "POST", body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Frivo said ${res.status}`);
      const browserCount = putBrowserData(data.browser);
      const parts = [];
      if (data.profiles) parts.push(plural(data.profiles, "profile", "profiles"));
      if (data.saved) parts.push(plural(data.saved, "saved reply", "saved replies"));
      if (data.settings) parts.push(plural(data.settings, "setting", "settings"));
      if (data.keys) parts.push(plural(data.keys, "API key", "API keys"));
      if (data.voices) parts.push(plural(data.voices, "added voice", "added voices"));
      if (data.anchors) parts.push(plural(data.anchors, "accent anchor", "accent anchors"));
      if (data.taste) parts.push("your tag taste");
      if (browserCount) parts.push("favourite voices, your tags and this browser's choices");
      $("backupRestoreValue").textContent = "Done";
      if (!parts.length) {
        show("Nothing new to add: everything in that file is already here.");
        return;
      }
      show(`Restored ${esc(file.name)}:<ul>${parts.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>Reloading to show it…`);
      setTimeout(() => location.reload(), 2200);
    } catch (err) {
      $("backupRestoreValue").textContent = "";
      show(`Couldn't restore that: ${esc(err.message || err)}`, true);
    } finally {
      row.classList.remove("is-busy");
    }
  });
})();


// ---------------------------------------------------------------------------
// NEW (1.5.0): the free voice library ("Browse free voices" in the voice list)
// Every Piper voice from the library on Hugging Face: play its sample,
// download it with one click. Frivo fetches the samples and the files, so
// only the PC Frivo runs on needs to reach Hugging Face. A download becomes
// one of your added voices, the same as "Add a voice".
// ---------------------------------------------------------------------------
(function initVoiceLibrary() {
  const pop = $("voiceLibPop");
  const openBtn = $("voiceLibBtn");
  if (!pop || !openBtn) return;
  const list = $("voiceLibList");
  const search = $("voiceLibSearch");
  const langSel = $("voiceLibLang");
  const qualSel = $("voiceLibQuality");
  const LANG_KEY = "frivo_voicelib_lang";
  const QUAL_KEY = "frivo_voicelib_quality";
  const QUALITY_LABEL = { x_low: "x-low", low: "low", medium: "medium", high: "high" };
  let voices = [];
  let disk = {};
  let jobs = {};
  let loaded = false;
  let pollTimer = null;
  let audio = null;
  let playingKey = "";
  let loadingKey = "";
  const licences = {};
  const notes = {};   // key -> a message to show on that row

  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const mb = (n) => (n >= 1073741824 ? `${(n / 1073741824).toFixed(1)} GB` : `${Math.max(1, Math.round(n / 1048576))} MB`);
  const store = {
    get(k) { try { return localStorage.getItem(k) || ""; } catch (_) { return ""; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) { /* fine */ } },
  };

  function open() {
    pop.classList.remove("is-hidden");
    search.value = "";
    if (!loaded) load(); else render();
    setTimeout(() => search.focus(), 30);
  }
  function close() {
    pop.classList.add("is-hidden");
    stop();
  }

  async function load(refresh) {
    list.innerHTML = '<p class="vlib-empty">Loading the voice library…</p>';
    try {
      const res = await fetch("/api/voices/library" + (refresh ? "?refresh=1" : ""));
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Frivo said ${res.status}`);
      voices = data.voices || [];
      disk = data.disk || {};
      loaded = true;
      if (data.problem) notes._all = data.problem;
      fillLanguages();
      await pollJobs();
      render();
    } catch (err) {
      list.innerHTML = `<p class="vlib-empty is-error">${esc(err.message || err)}</p>`;
    }
  }

  function fillLanguages() {
    const counts = new Map();
    voices.forEach((v) => counts.set(v.language, (counts.get(v.language) || 0) + 1));
    const langs = [...counts.keys()].sort((a, b) => a.localeCompare(b));
    // The language Frivo speaks now is the starting point, then the last one picked.
    const current = (typeof currentLanguage === "string" && currentLanguage) || "";
    const guess = voices.find((v) => current && v.language.toLowerCase() === current.toLowerCase());   // currentLanguage is a name ("English")
    const saved = store.get(LANG_KEY);
    const pick = saved && (saved === "*" || counts.has(saved)) ? saved : (guess ? guess.language : "English");
    langSel.innerHTML = `<option value="*">All languages (${voices.length})</option>`
      + langs.map((l) => `<option value="${esc(l)}">${esc(l)} (${counts.get(l)})</option>`).join("");
    langSel.value = counts.has(pick) || pick === "*" ? pick : "*";
    qualSel.value = store.get(QUAL_KEY) || "";
  }

  function filtered() {
    const q = search.value.trim().toLowerCase();
    const lang = langSel.value;
    const qual = qualSel.value;
    return voices.filter((v) => {
      if (q) {
        const hay = `${v.name} ${v.language} ${v.language_native} ${v.country} ${v.key}`.toLowerCase();
        if (!q.split(/\s+/).every((w) => hay.includes(w))) return false;
      } else if (lang !== "*" && v.language !== lang) return false;
      if (qual && v.quality !== qual) return false;
      return true;
    });
  }

  function renderDrive() {
    const el = $("voiceLibDrive");
    if (!disk || !disk.total) { el.innerHTML = ""; return; }
    const used = disk.total - disk.free;
    const pct = Math.min(100, (used / disk.total) * 100);
    const mine = Math.min(pct, (disk.voices_bytes / disk.total) * 100);
    el.innerHTML = `Downloads go to drive ${esc(disk.drive)} with your other added voices: <strong>${mb(disk.free)} free</strong>`
      + ` of ${mb(disk.total)}${disk.voices_bytes ? `, added voices use ${mb(disk.voices_bytes)}` : ""}.`
      + `<div class="om-bar" aria-hidden="true"><span class="om-bar-seg is-models" style="width:${mine}%"></span>`
      + `<span class="om-bar-seg is-other" style="width:${Math.max(0, pct - mine)}%"></span></div>`;
  }

  function rowHtml(v) {
    const job = jobs[v.key];
    const busy = job && (job.state === "downloading" || job.state === "adding");
    const playing = playingKey === v.key;
    const icon = loadingKey === v.key ? "i-refresh" : playing ? "i-stop" : "i-play";
    const badges = [`<span class="om-badge${v.quality === "high" ? " is-tight" : ""}" title="${v.quality === "high" ? "Clearest; about twice the CPU of medium" : "Quality"}">${esc(QUALITY_LABEL[v.quality] || v.quality)}</span>`];
    if (v.speakers > 1) badges.push(`<span class="om-badge" title="Frivo uses the first speaker; the sample is that speaker">${v.speakers} speakers</span>`);
    if (v.included) badges.push('<span class="om-badge is-fits">Included</span>');
    else if (v.voice_id) badges.push('<span class="om-badge is-fits">Added</span>');
    const where = [v.language, v.country].filter(Boolean).join(" · ");
    let meta = `${esc(where)} · ${mb(v.size)}`;
    let metaClass = "vlib-meta";
    if (notes[v.key]) { meta = esc(notes[v.key].text); if (notes[v.key].error) metaClass += " is-error"; }
    let action;
    if (busy) {
      const pct = job.total ? Math.min(100, Math.round((job.done / job.total) * 100)) : 0;
      const adding = job.state === "adding";
      action = `<div class="vlib-progress${adding ? " is-busy" : ""}" title="${adding ? "Converting and trying it out" : "Downloading"}"><span style="width:${pct}%"></span></div>`
        + `<span class="vlib-pct">${adding ? "…" : `${pct}%`}</span>`
        + (adding ? "" : `<button class="btn-ghost btn-sm" type="button" data-vlib-cancel="${esc(v.key)}">Cancel</button>`);
    } else if (v.voice_id) {
      action = `<button class="btn btn-sm" type="button" data-vlib-use="${esc(v.voice_id)}">Use</button>`;
    } else {
      action = `<button class="btn-ghost btn-sm" type="button" data-vlib-get="${esc(v.key)}" title="Download ${mb(v.size)}">`
        + '<svg class="icon-14" aria-hidden="true"><use href="#i-download"/></svg>Download</button>';
    }
    const lic = licences[v.key];
    return `<div class="vlib-row${playing ? " is-playing" : ""}" data-vlib-key="${esc(v.key)}">`
      + `<button class="vlib-play${loadingKey === v.key ? " is-loading" : ""}" type="button" data-vlib-play="${esc(v.key)}" aria-label="${playing ? "Stop" : "Play"} ${esc(v.name)}"><svg><use href="#${icon}"/></svg></button>`
      + `<div class="vlib-main"><div class="vlib-top"><span class="vlib-name">${esc(v.name)}</span>${badges.join("")}</div>`
      + `<span class="${metaClass}">${meta}</span>`
      + (lic ? `<span class="vlib-licence">Licence: ${esc(lic)}</span>` : "")
      + `</div><div class="vlib-actions">${action}</div></div>`;
  }

  function render() {
    if (!loaded) return;
    renderDrive();
    const shown = filtered();
    $("voiceLibCount").textContent = `${shown.length} of ${voices.length} voices`;
    if (notes._all) {
      list.innerHTML = `<p class="vlib-empty is-error">${esc(notes._all)}</p>`;
      return;
    }
    if (!shown.length) {
      list.innerHTML = '<p class="vlib-empty">No voices match that.</p>';
      return;
    }
    const keepScroll = list.scrollTop;
    let html = "";
    let group = "";
    shown.forEach((v) => {
      const g = [v.language, v.country].filter(Boolean).join(" · ");
      if (g !== group) { group = g; html += `<div class="vlib-group">${esc(g)}</div>`; }
      html += rowHtml(v);
    });
    list.innerHTML = html;
    list.scrollTop = keepScroll;
  }

  function stop() {
    if (audio) { audio.pause(); audio = null; }
    playingKey = "";
    loadingKey = "";
  }

  function play(key) {
    const was = playingKey === key || loadingKey === key;
    stop();
    if (typeof stopVoicePreview === "function") stopVoicePreview();
    if (was) { render(); return; }
    const a = new Audio(`/api/voices/library/sample/${encodeURIComponent(key)}`);
    a.volume = Math.min(1, typeof masterVolume === "number" ? masterVolume : 1);
    audio = a;
    loadingKey = key;
    render();
    a.addEventListener("playing", () => {
      if (audio !== a) return;
      loadingKey = "";
      playingKey = key;
      render();
    });
    a.addEventListener("ended", () => { if (audio === a) { stop(); render(); } });
    a.addEventListener("error", async () => {
      if (audio !== a) return;
      stop();
      let text = "Couldn't play its sample.";
      try {
        const r = await fetch(a.src);
        const d = await r.json();
        if (d.error) text = d.error;
      } catch (_) { /* keep the plain message */ }
      notes[key] = { text, error: true };
      render();
    });
    a.play().catch(() => { /* the error event says why */ });
    if (!(key in licences)) {
      licences[key] = "";
      fetch(`/api/voices/library/card/${encodeURIComponent(key)}`).then((r) => r.json()).then((d) => {
        if (d && d.license) { licences[key] = d.license; render(); }
      }).catch(() => {});
    }
  }

  async function pollJobs() {
    try {
      const res = await fetch("/api/voices/library/install");
      const data = await res.json();
      const before = jobs;
      jobs = data.jobs || {};
      let finished = false;
      Object.entries(jobs).forEach(([key, job]) => {
        const v = voices.find((x) => x.key === key);
        const was = before[key];
        const fresh = !was || was.state === "downloading" || was.state === "adding";
        if (job.state === "done" && v) {
          if (!v.voice_id) finished = true;
          v.voice_id = job.voice_id;
          if (fresh) notes[key] = { text: `Added as ${job.name}. It's in the voice list under "added by you".` };
        } else if (job.state === "error" && fresh) {
          notes[key] = { text: job.error || "The download failed.", error: true };
        } else if (job.state === "cancelled" && fresh) {
          delete notes[key];
        }
      });
      if (finished && typeof loadVoices === "function") loadVoices();
      const active = Object.values(jobs).some((j) => j.state === "downloading" || j.state === "adding");
      clearTimeout(pollTimer);
      if (active) pollTimer = setTimeout(async () => { await pollJobs(); render(); }, 700);
    } catch (_) { /* tried again on the next action */ }
  }

  async function download(key) {
    delete notes[key];
    try {
      const res = await fetch("/api/voices/library/install", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Frivo said ${res.status}`);
    } catch (err) {
      notes[key] = { text: err.message || String(err), error: true };
    }
    await pollJobs();
    render();
  }

  list.addEventListener("click", async (e) => {
    const t = e.target.closest("button");
    if (!t) return;
    if (t.dataset.vlibPlay) play(t.dataset.vlibPlay);
    else if (t.dataset.vlibGet) download(t.dataset.vlibGet);
    else if (t.dataset.vlibCancel) {
      await fetch(`/api/voices/library/install/${encodeURIComponent(t.dataset.vlibCancel)}`, { method: "DELETE" }).catch(() => {});
      await pollJobs();
      render();
    } else if (t.dataset.vlibUse) {
      const v = typeof voiceById === "function" ? voiceById(t.dataset.vlibUse) : null;
      if (!v) {
        if (typeof loadVoices === "function") await loadVoices();
      }
      const voice = typeof voiceById === "function" ? voiceById(t.dataset.vlibUse) : null;
      if (voice && typeof chooseVoice === "function") {
        close();
        chooseVoice(voice);
      }
    }
  });

  openBtn.addEventListener("click", open);
  $("voiceLibCloseBtn").addEventListener("click", close);
  pop.addEventListener("click", (e) => { if (e.target === pop) close(); });
  pop.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); openBtn.focus(); }
  });
  let typing = null;
  search.addEventListener("input", () => { clearTimeout(typing); typing = setTimeout(render, 120); });
  langSel.addEventListener("change", () => { store.set(LANG_KEY, langSel.value); list.scrollTop = 0; render(); });
  qualSel.addEventListener("change", () => { store.set(QUAL_KEY, qualSel.value); list.scrollTop = 0; render(); });
})();


// ---------------------------------------------------------------------------
// NEW (1.6.0): the built-in AI (Settings > Providers > Built-in AI).
// One button: downloads the engine and the model, checks them, and switches
// Chat replies to Built-in. Then Test, the idle timer, and Remove.
// ---------------------------------------------------------------------------
(function initBuiltinAI() {
  const card = $("builtinCard");
  if (!card) return;
  const modelsEl = $("builtinModels");
  const getBtn = $("builtinGetBtn");
  const cancelBtn = $("builtinCancelBtn");
  const testBtn = $("builtinTestBtn");
  const statusEl = $("builtinStatus");
  const progress = $("builtinProgress");
  let info = null;
  let chosen = "small";
  let poll = null;
  let lastJobState = "";
  let pickedHere = false;   // a model picked on this page wins over what the server last said
  const gb = (n) => `${(n / 1e9).toFixed(1)} GB`;
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function say(text, kind) {
    statusEl.textContent = text || "";
    statusEl.classList.toggle("is-error", kind === "error");
    statusEl.classList.toggle("is-ok", kind === "ok");
  }

  function renderModels() {
    modelsEl.innerHTML = (info.models || []).map((m) => {
      const fits = info.memory_gb ? info.memory_gb >= m.memory_gb + 2 : true;
      const badge = m.downloaded ? '<span class="om-badge is-fits">Downloaded</span>'
        : fits ? "" : `<span class="om-badge is-tight" title="The PC Frivo runs on has ${info.memory_gb} GB of memory">Tight on memory</span>`;
      return `<label class="bai-model${m.id === chosen ? " is-checked" : ""}">`
        + `<input type="radio" name="builtin_ai_model" value="${esc(m.id)}"${m.id === chosen ? " checked" : ""}>`
        + `<span class="bai-model-top"><span class="bai-model-name">${esc(m.name)}</span>${badge}</span>`
        + `<span class="bai-model-sub">${esc(m.model)} · ${gb(m.size)} download · about ${m.memory_gb} GB of memory</span>`
        + `<span class="bai-model-note">${esc(m.note)}</span>`
        + (m.downloaded ? `<button type="button" class="bai-model-remove" data-remove="${esc(m.id)}">Remove</button>` : "")
        + "</label>";
    }).join("");
  }

  function render() {
    if (!info) return;
    const value = $("builtinValue");
    const model = (info.models || []).find((m) => m.id === chosen) || {};
    const ready = info.engine && model.downloaded;
    const active = (info.models || []).find((m) => m.id === info.active_model) || {};
    const job = info.job || {};
    const busy = ["checking", "engine", "model"].includes(job.state);
    renderModels();
    $("builtinModelNote").textContent = info.memory_gb
      ? `The PC Frivo runs on has ${info.memory_gb} GB of memory. The AI uses ${info.threads} of its processor threads while it writes.`
      : "";
    value.textContent = !info.supported ? "Not available" : info.in_use && ready ? "In use"
      : ready ? "Downloaded" : busy ? "Downloading" : "Not downloaded";
    progress.classList.toggle("is-hidden", !busy);
    cancelBtn.classList.toggle("is-hidden", !busy);
    testBtn.classList.toggle("is-hidden", !ready || busy);
    if ($("builtinAgainBtn")) $("builtinAgainBtn").classList.toggle("is-hidden", !ready || busy);   // NEW (1.7.0)
    getBtn.classList.toggle("is-hidden", busy || (ready && info.in_use));
    getBtn.textContent = ready ? "Use the built-in AI" : `Download and use (${gb(model.size || 0)})`;
    getBtn.disabled = !info.supported;
    $("builtinRemoveRow").classList.toggle("is-hidden", !info.engine && !(info.models || []).some((m) => m.downloaded));
    $("builtinFolder").textContent = info.folder ? `Kept in ${info.folder}` : "";
    if (busy) {
      const pct = job.total ? Math.min(100, Math.round((job.done / job.total) * 100)) : 0;
      $("builtinProgressText").textContent = job.state === "engine" ? "Downloading the engine…"
        : job.state === "model" ? `Downloading ${model.model || "the model"}…` : "Getting ready…";
      $("builtinProgressPct").textContent = job.total ? `${gb(job.done)} of ${gb(job.total)} · ${pct}%` : "";
      $("builtinProgressBar").style.width = `${pct}%`;
    }
    if (!info.supported) say(info.problem, "error");
    else if (job.state === "error" && lastJobState !== "shown-error") say(job.error, "error");
    else if (!busy && ready && info.in_use && !statusEl.textContent) {
      say(info.running ? `${model.model} is running.` : `${model.model} starts with the next reply (a few seconds).`, "ok");
    } else if (!busy && !ready && info.in_use && active.downloaded && !statusEl.textContent) {
      say(`Replies use ${active.model} until ${model.model} is downloaded.`);
    }
  }

  async function refresh() {
    try {
      const res = await fetch("/api/builtin-ai");
      info = await res.json();
      if (!poll && !pickedHere && info.model) chosen = info.model;
      const job = info.job || {};
      const busy = ["checking", "engine", "model"].includes(job.state);
      if (lastJobState && ["checking", "engine", "model"].includes(lastJobState) && job.state === "done") {
        say(`Ready. Chat replies now use the built-in AI (${(info.models.find((m) => m.id === chosen) || {}).model}).`, "ok");
        if (typeof loadSettings === "function") loadSettings();   // the provider changed on the server
      } else if (lastJobState && ["checking", "engine", "model"].includes(lastJobState) && job.state === "cancelled") {
        say("Cancelled. Nothing was kept.");
      }
      render();
      if (job.state === "error") lastJobState = "shown-error"; else lastJobState = job.state || "";
      clearTimeout(poll);
      poll = busy ? setTimeout(refresh, 800) : null;
    } catch (_) { /* tried again when the card is shown */ }
  }

  modelsEl.addEventListener("change", (e) => {
    if (e.target.name !== "builtin_ai_model") return;
    chosen = e.target.value;
    pickedHere = true;
    say("");
    render();
    // Saved like any setting, so a downloaded model is used straight away.
    fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ builtin_ai_model: chosen }) }).catch(() => {});
  });
  modelsEl.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-remove]");
    if (!btn) return;
    e.preventDefault();
    if (btn.dataset.armed !== "1") {
      btn.dataset.armed = "1";
      btn.textContent = "Remove? Click again";
      setTimeout(() => { btn.dataset.armed = ""; btn.textContent = "Remove"; }, 3000);
      return;
    }
    // CHANGED (1.7.0): says when something couldn't be deleted.
    const res = await fetch(`/api/builtin-ai/${encodeURIComponent(btn.dataset.remove)}`, { method: "DELETE" }).catch(() => null);
    const data = res ? await res.json().catch(() => ({})) : {};
    if (res && res.ok) say("Removed."); else say(data.error || "Couldn't remove it.", "error");
    if (typeof loadSettings === "function") loadSettings();
    refresh();
  });
  async function startDownload(again) {
    say("");
    getBtn.disabled = true;
    try {
      const res = await fetch("/api/builtin-ai/download", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: chosen, use: true, again }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Frivo said ${res.status}`);
      if (data.ready) {
        say("Chat replies now use the built-in AI.", "ok");
        if (typeof loadSettings === "function") loadSettings();
      }
      lastJobState = "checking";
    } catch (err) {
      say(err.message || String(err), "error");
    } finally {
      getBtn.disabled = false;
    }
    refresh();
  }
  getBtn.addEventListener("click", () => startDownload(false));
  // NEW (1.7.0): replaces the engine and the model, for when it won't start.
  const againBtn = $("builtinAgainBtn");
  if (againBtn) againBtn.addEventListener("click", () => startDownload(true));
  cancelBtn.addEventListener("click", () => fetch("/api/builtin-ai/cancel", { method: "POST" }).then(refresh));
  testBtn.addEventListener("click", async () => {
    testBtn.disabled = true;
    say("Starting it and asking for a line…");
    try {
      const res = await fetch("/api/builtin-ai/test", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Frivo said ${res.status}`);
      say(`"${data.text}" in ${data.seconds} s` + (data.start_seconds > 1 ? ` (${data.start_seconds} s of that was starting up)` : "") + ".", "ok");
    } catch (err) {
      say(err.message || String(err), "error");
    } finally {
      testBtn.disabled = false;
      refresh();
    }
  });
  $("builtinRemoveBtn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    if (btn.dataset.armed !== "1") {
      btn.dataset.armed = "1";
      btn.textContent = "Remove everything?";
      setTimeout(() => { btn.dataset.armed = ""; btn.textContent = "Remove"; }, 3000);
      return;
    }
    btn.dataset.armed = "";
    btn.textContent = "Remove";
    const res = await fetch("/api/builtin-ai", { method: "DELETE" }).catch(() => null);
    const data = res ? await res.json().catch(() => ({})) : {};
    if (res && res.ok) say("Removed. Clean up in English still works without AI.");
    else say(data.error || "Couldn't remove it.", "error");
    if (typeof loadSettings === "function") loadSettings();
    refresh();
  });

  // Fetched when Providers is opened, and once at the start.
  document.addEventListener("click", (e) => {
    // CHANGED (1.6.0): only the Providers button in the list on the left.
    // (Matching the whole section re-drew the card on every click inside it,
    // which undid Remove's "click again" and put the model choice back.)
    if (e.target.closest && e.target.closest('.settings-nav-btn[data-settings-section="providers"]')) {
      setTimeout(refresh, 50);
      // So the Ollama card can say what your own models use.
      if (typeof omLoad === "function" && !(omState && omState.data)) setTimeout(omLoad, 80);
    }
  });
  refresh();
})();


// NEW (1.6.0): the Ollama card under Chat replies says what *your* three
// models use, once Ollama has said how big they are. (Until then, or if
// Ollama can't be reached, it gives the usual range.)
function omCardUses() {
  const line = document.querySelector('#chatProviderRadios .radio-pill[data-id="ollama"] .radio-card-uses');
  const data = omState.data;
  if (!line || !data || !data.reachable) return;
  const installed = data.installed || [];
  const sizeOf = (name) => {
    name = (name || "").trim();
    if (!name) return null;
    const full = name.includes(":") ? name : `${name}:latest`;
    const m = installed.find((x) => x.name === name || x.name === full);
    return m ? m.size : null;
  };
  const tiers = [["Fast", ollamaModel], ["Balanced", ollamaModelBalanced], ["Best", ollamaModelBest]]
    .map(([label, el]) => [label, sizeOf(el && el.value)])
    .filter(([, size]) => size);
  if (!tiers.length) return;
  // Loaded, a model takes about its file size plus room for the conversation.
  const gb = (bytes) => (bytes * 1.1 / 1e9 + 0.4).toFixed(1);
  const parts = tiers.map(([label, size]) => `${gb(size)} GB (${label})`);
  const lead = line.querySelector(".radio-card-lead");
  line.textContent = "";
  if (lead) line.append(lead, " ");
  line.append(`About ${parts.join(", ")} of graphics memory with your models; only one is loaded at a time. Free.`);
}


// ---------------------------------------------------------------------------
// NEW (1.7.0): Settings > Storage: where the big files are kept, and a
// folder picker for the PC Frivo runs on.
// ---------------------------------------------------------------------------
(function initStorage() {
  const list = $("storageList");
  if (!list) return;
  const pop = $("folderPop");
  const statusEl = $("storageStatus");
  let info = null;
  let poll = null;
  let picking = null;      // the kind a folder is being picked for
  let browsePath = "";
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const size = (n) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${Math.round(n / 1e6)} MB` : n > 0 ? "under 1 MB" : "empty");
  const say = (text, kind) => {
    statusEl.textContent = text || "";
    statusEl.classList.toggle("is-error", kind === "error");
    statusEl.classList.toggle("is-ok", kind === "ok");
  };

  function render() {
    if (!info) return;
    const job = info.job || {};
    const moving = job.state === "moving";
    list.innerHTML = info.kinds.map((k) => {
      const free = k.drive && k.drive.free != null ? ` · ${size(k.drive.free)} free on ${esc(k.drive.name)}` : "";
      return `<div class="st-row" data-kind="${esc(k.id)}">`
        + `<div class="st-main"><span class="st-name">${esc(k.name)}</span>`
        + `<span class="st-what">${esc(k.what)}</span>`
        + `<span class="st-folder">${esc(k.folder)}</span>`
        + `<span class="st-meta">Using ${size(k.size)}${free}${k.is_default ? " · Frivo's own folder" : ""}</span>`
        + (k.problem ? `<span class="st-problem">${esc(k.problem)}</span>` : "")
        + `</div><div class="st-actions">`
        + `<button type="button" class="btn-ghost btn-sm" data-change="${esc(k.id)}"${moving ? " disabled" : ""}>Change…</button>`
        + (k.is_default ? "" : `<button type="button" class="link-btn" data-default="${esc(k.id)}"${moving ? " disabled" : ""}>Back to Frivo's folder</button>`)
        + `</div></div>`;
    }).join("");
    const jobEl = $("storageJob");
    jobEl.classList.toggle("is-hidden", !moving);
    if (moving) {
      const pct = job.total ? Math.min(100, Math.round((job.done / job.total) * 100)) : 0;
      const kind = info.kinds.find((k) => k.id === job.kind) || {};
      $("storageJobText").textContent = `Moving ${kind.name || "files"} to ${job.folder}…`;
      $("storageJobPct").textContent = job.total ? `${size(job.done)} of ${size(job.total)} · ${pct}%` : "";
      $("storageJobBar").style.width = `${pct}%`;
    }
  }

  let lastState = "";
  async function refresh() {
    try {
      const res = await fetch("/api/storage");
      info = await res.json();
      const job = info.job || {};
      if (lastState === "moving" && job.state === "done") say(job.message, "ok");
      if (lastState === "moving" && job.state === "error") say(job.message, "error");
      lastState = job.state;
      render();
      clearTimeout(poll);
      poll = job.state === "moving" ? setTimeout(refresh, 700) : null;
    } catch (_) { /* tried again when Storage is opened */ }
  }

  async function change(kind, body) {
    say("");
    const res = await fetch("/api/storage", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ kind }, body)) }).catch(() => null);
    const data = res ? await res.json().catch(() => ({})) : {};
    if (res && res.status === 409 && data.exists) return data;   // the picker asks what to do
    if (!res || !res.ok) { say(data.error || "Couldn't change it.", "error"); return null; }
    if (data.unchanged) say("That's where it already is.");
    else lastState = "moving";
    refresh();
    return data;
  }

  // ---- the folder picker ----
  async function browse(path) {
    const note = $("folderNote");
    note.classList.remove("is-error");
    note.textContent = "";
    const res = await fetch(`/api/storage/browse?path=${encodeURIComponent(path || "")}`).catch(() => null);
    const data = res ? await res.json().catch(() => ({})) : {};
    if (!res || !res.ok) { note.textContent = data.error || "Couldn't look there."; note.classList.add("is-error"); return; }
    browsePath = data.path || "";
    $("folderPath").value = browsePath;
    $("folderUpBtn").disabled = !data.parent && !(data.drives || []).length;
    $("folderUpBtn").dataset.parent = data.parent || "";
    $("folderDrives").innerHTML = (data.drives || []).map((d) => `<button type="button" class="st-drive" data-path="${esc(d)}">${esc(d)}</button>`).join("");
    const folders = data.folders || [];
    $("folderList").innerHTML = !browsePath ? '<p class="st-empty">Pick a drive.</p>'
      : folders.length ? folders.map((f) => `<button type="button" class="st-folder-btn" data-name="${esc(f)}">${esc(f)}</button>`).join("")
      : '<p class="st-empty">No folders in here. Make one below, or use this one.</p>';
    $("folderChooseBtn").disabled = !browsePath || data.writable === false;
    const kind = info && info.kinds.find((k) => k.id === picking);
    const sub = kind ? kind.sub : "";
    note.textContent = !browsePath ? "" : data.writable === false ? "Frivo can't write here."
      : `Frivo will use ${browsePath.replace(/[\\/]$/, "")}${browsePath.includes("/") && !browsePath.includes("\\") ? "/" : "\\"}${sub}`
        + (data.free != null ? ` · ${size(data.free)} free` : "");
  }

  function openPicker(kindId) {
    picking = kindId;
    const kind = info.kinds.find((k) => k.id === kindId);
    $("folderTitle").textContent = `Where to keep: ${kind.name}`;
    $("folderSub").textContent = `Pick a folder on the PC Frivo runs on. Frivo makes a "${kind.sub}" folder inside it and moves what's there now (${size(kind.size)}).`;
    pop.classList.remove("is-hidden");
    browse(kind.is_default ? "" : kind.parent);
  }
  const closePicker = () => { pop.classList.add("is-hidden"); picking = null; };

  list.addEventListener("click", async (e) => {
    const c = e.target.closest("[data-change]");
    if (c) { openPicker(c.dataset.change); return; }
    const d = e.target.closest("[data-default]");
    if (d) {
      if (d.dataset.armed !== "1") {
        d.dataset.armed = "1";
        d.textContent = "Move back? Click again";
        setTimeout(() => { d.dataset.armed = ""; d.textContent = "Back to Frivo's folder"; }, 3000);
        return;
      }
      const data = await change(d.dataset.default, { default: true, mode: "move" });
      if (data && data.exists) say(`${data.error}`, "error");
    }
  });
  $("folderList").addEventListener("click", (e) => {
    const b = e.target.closest("[data-name]");
    if (!b) return;
    const sep = browsePath.includes("\\") || /^[A-Za-z]:/.test(browsePath) ? "\\" : "/";
    browse(browsePath.replace(/[\\/]+$/, "") + sep + b.dataset.name);
  });
  $("folderDrives").addEventListener("click", (e) => {
    const b = e.target.closest("[data-path]");
    if (b) browse(b.dataset.path);
  });
  $("folderUpBtn").addEventListener("click", (e) => browse(e.currentTarget.dataset.parent || ""));
  $("folderGoBtn").addEventListener("click", () => browse($("folderPath").value.trim()));
  $("folderPath").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); browse($("folderPath").value.trim()); } });
  $("folderNewBtn").addEventListener("click", async () => {
    const name = $("folderNewName").value.trim();
    if (!name || !browsePath) return;
    const res = await fetch("/api/storage/mkdir", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: browsePath, name }) }).catch(() => null);
    const data = res ? await res.json().catch(() => ({})) : {};
    if (!res || !res.ok) { $("folderNote").textContent = data.error || "Couldn't make it."; $("folderNote").classList.add("is-error"); return; }
    $("folderNewName").value = "";
    browse(data.path);
  });
  $("folderChooseBtn").addEventListener("click", async () => {
    const kind = picking;
    const btn = $("folderChooseBtn");
    btn.disabled = true;
    let data = await change(kind, { folder: browsePath, mode: "move" });
    if (data && data.exists) {
      // Frivo's files from before are already there (an earlier install, say).
      if (window.confirm(`${data.error}\n\nOK: use the files that are there. (What's in the current folder stays where it is.)\nCancel: pick another folder.`)) {
        data = await change(kind, { folder: browsePath, mode: "use" });
      } else {
        btn.disabled = false;
        return;
      }
    }
    btn.disabled = false;
    if (data) closePicker();
  });
  $("folderCloseBtn").addEventListener("click", closePicker);
  pop.addEventListener("click", (e) => { if (e.target === pop) closePicker(); });
  pop.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closePicker(); } });

  document.addEventListener("click", (e) => {
    if (e.target.closest && e.target.closest('.settings-nav-btn[data-settings-section="storage"]')) setTimeout(refresh, 50);
  });
  refresh();
})();


// ============================================================
// NEW (1.8.0): the Frivo app (desktop\ in the repo)
// ============================================================
// Inside the app, the page has window.frivoApp (desktop\src\preload.js) and
// Settings gets an App section for the app's own settings. In a browser on
// Windows, Settings › Updates offers the app instead.
(function initDesktopApp() {
  const api = window.frivoApp;
  const offer = $("appOffer");

  if (!api) {
    if (!offer) return;
    const DISMISS_KEY = "frivo_app_offer_dismissed";
    const windows = /Windows/i.test(navigator.userAgent) && !/Windows Phone/i.test(navigator.userAgent);
    let dismissed = false;
    try { dismissed = localStorage.getItem(DISMISS_KEY) === "1"; } catch { /* private window */ }
    if (!windows || dismissed) return;
    offer.classList.remove("is-hidden");
    $("appOfferClose").addEventListener("click", () => {
      offer.classList.add("is-hidden");
      try { localStorage.setItem(DISMISS_KEY, "1"); } catch { /* not remembered */ }
    });
    // The releases page Frivo updates from, so a fork links to its own app.
    fetch("/api/updates").then((r) => r.json()).then((d) => {
      if (d && d.releases_page) $("appOfferLink").href = `${d.releases_page}?q=app-v&expanded=true`;
    }).catch(() => {});
    return;
  }

  document.documentElement.classList.add("in-frivo-app");
  if (offer) offer.remove();
  $("appNavBtn").classList.remove("is-hidden");

  const closeSelect = $("appCloseSelect");
  const loginToggle = $("appLoginToggle");
  let current = null;

  function updateLabel(u) {
    switch (u && u.state) {
      case "checking": return "Checking…";
      case "downloading": return `Downloading ${u.version}… ${u.percent || 0}%`;
      case "ready": return `Restart to update to ${u.version}`;
      case "current": return "Up to date";
      case "error": return u.error || "Couldn't check";
      default: return "";
    }
  }

  function render(s) {
    if (!s) return;
    current = s;
    const local = s.mode === "local";
    $("appWhereValue").textContent = local ? "This PC" : (s.host || "—");
    $("appWhereSub").textContent = local
      ? "Frivo's server runs in the background here, and this window is Frivo."
      : "Frivo runs on another PC; this window connects to it like a phone does.";

    const lan = local && s.local && s.local.lanUrl;
    $("appLanRow").classList.toggle("is-hidden", !lan);
    if (lan) $("appLanValue").textContent = s.local.lanUrl;
    $("appRunRow").classList.toggle("is-hidden", !local);

    $("appLoginRow").classList.toggle("is-hidden", !s.startAtLoginAvailable);
    loginToggle.checked = Boolean(s.startAtLogin);
    $("appLoginSub").textContent = local
      ? "Starts Frivo when you sign in, with the app in the tray. The same setting as Frivo's launcher."
      : "Opens the app in the tray when you sign in.";

    closeSelect.value = s.closeAction === "quit" ? "quit" : "tray";
    closeSelect.options[1].textContent = local ? "Stop Frivo and quit" : "Quit";
    $("appCloseSub").textContent = s.closeAction === "quit"
      ? (local ? "Closing the window stops Frivo on this PC." : "Closing the window quits the app.")
      : "Frivo keeps running. Right-click the tray icon to quit.";

    $("appVersionValue").textContent = s.version || "—";
    $("appUpdateValue").textContent = updateLabel(s.update);

    const note = $("appOutdatedNote");
    const outdated = local && s.local && s.local.outdated;
    note.classList.toggle("is-hidden", !outdated);
    if (outdated) {
      note.textContent = `Frivo ${s.local.version} runs fine in the app, but update it to ${s.local.minimum} or newer (Updates, above) so its launcher stays in the background.`;
    }
  }

  const refresh = () => api.getState().then(render).catch(() => {});

  $("appChangeBtn").addEventListener("click", () => api.changeConnection());
  $("appLanCopy").addEventListener("click", async () => {
    if (!current || !current.local || !current.local.lanUrl) return;
    await api.copy(current.local.lanUrl);
    const btn = $("appLanCopy");
    btn.textContent = "Copied";
    setTimeout(() => { btn.textContent = "Copy"; }, 1500);
  });
  $("appStopBtn").addEventListener("click", () => {
    if (window.confirm("Stop Frivo on this PC? Phones and other devices are disconnected until it's started again.")) api.stopFrivo();
  });
  loginToggle.addEventListener("change", () => api.setStartAtLogin(loginToggle.checked).then(render));
  closeSelect.addEventListener("change", () => api.setCloseAction(closeSelect.value).then(render));
  $("appUpdateRow").addEventListener("click", () => {
    if (current && current.update && current.update.state === "ready") { api.installUpdate(); return; }
    $("appUpdateValue").textContent = "Checking…";
    api.checkForUpdate().then(render).catch(() => {});
  });

  // ---- NEW: shortcuts (global hotkeys) ----
  const HOTKEY_ROWS = {
    dictate: { value: "appHotkeyDictate", sub: "appHotkeyDictateSub", note: "Works anywhere, even with a game in front." },
    send: { value: "appHotkeySend", sub: "appHotkeySendSub", note: "Speaks what's in the message box." },
  };
  let capturing = null;

  const showKeys = (accel) => accel
    ? accel.replace(/CommandOrControl|Control/g, "Ctrl").replace(/Super/g, "Win").split("+").join(" + ")
    : "Off";

  function renderHotkeys(s) {
    if (!s || !s.hotkeys) return;
    for (const [action, row] of Object.entries(HOTKEY_ROWS)) {
      if (capturing && capturing.action === action) continue;
      $(row.value).textContent = showKeys(s.hotkeys[action]);
      const err = s.hotkeyErrors && s.hotkeyErrors[action];
      $(row.sub).textContent = err || row.note;
      $(row.sub).classList.toggle("srow-sub--error", Boolean(err));
    }
  }

  const KEY_NAMES = {
    Space: "Space", Enter: "Enter", Tab: "Tab", Backspace: "Backspace", Insert: "Insert", Delete: "Delete",
    Home: "Home", End: "End", PageUp: "PageUp", PageDown: "PageDown",
    ArrowUp: "Up", ArrowDown: "Down", ArrowLeft: "Left", ArrowRight: "Right",
    Minus: "-", Equal: "=", BracketLeft: "[", BracketRight: "]", Semicolon: ";", Quote: "'",
    Comma: ",", Period: ".", Slash: "/", Backslash: "\\", Backquote: "`",
  };

  // CHANGED: letters and digits as the keyboard layout names them (what
  // Windows matches a shortcut on), so AZERTY and QWERTZ get the key they
  // pressed.
  const RESERVED = new Set(["C", "V", "X", "A", "Z", "Y"].map((k) => `CommandOrControl+${k}`)
    .concat(["Alt+F4", "Alt+Tab", "CommandOrControl+Alt+Delete"]));
  function acceleratorFor(e) {
    let key = null;
    const typed = e.key && e.key.length === 1 ? e.key.toUpperCase() : "";
    if (/^[A-Z0-9]$/.test(typed)) key = typed;
    else if (/^Key[A-Z]$/.test(e.code)) key = e.code.slice(3);   // Alt+letter can type a symbol
    else if (/^Digit\d$/.test(e.code)) key = e.code.slice(5);
    else if (/^F([1-9]|1\d|2[0-4])$/.test(e.code)) key = e.code;
    else if (KEY_NAMES[e.code]) key = KEY_NAMES[e.code];
    if (!key || key === "Delete") return null;
    const mods = [];
    if (e.ctrlKey) mods.push("CommandOrControl");
    if (e.altKey) mods.push("Alt");
    if (e.shiftKey) mods.push("Shift");
    if (e.metaKey) mods.push("Super");
    // Ctrl, Alt or Win with it, or an F key: Shift and a letter alone would
    // stop that capital being typed anywhere.
    if (!/^F\d+$/.test(key) && !mods.some((m) => m !== "Shift")) return null;
    const accel = [...mods, key].join("+");
    return RESERVED.has(accel) ? null : accel;
  }

  function stopCapture() {
    if (!capturing) return;
    document.removeEventListener("keydown", capturing.listener, true);
    window.removeEventListener("blur", stopCapture);
    capturing.button.textContent = "Change";
    capturing = null;
    if (api.pauseHotkeys) api.pauseHotkeys(false).catch(() => {});
    if (current) renderHotkeys(current);
  }

  function startCapture(action, button) {
    stopCapture();
    const row = HOTKEY_ROWS[action];
    $(row.value).textContent = "Press keys…";
    $(row.sub).textContent = row.note;
    $(row.sub).classList.remove("srow-sub--error");
    button.textContent = "Cancel";
    const listener = (e) => {
      // Settings closed or another section opened: stop waiting, and let
      // the key do what it normally does.
      if (!$("appSection").offsetParent) { stopCapture(); return; }
      if (["Control", "Alt", "Shift", "Meta"].includes(e.key)) return;   // still holding modifiers
      e.preventDefault();
      e.stopPropagation();
      if (e.key === "Escape") { stopCapture(); return; }
      let accel;
      if ((e.key === "Backspace" || e.key === "Delete") && !e.ctrlKey && !e.altKey && !e.shiftKey && !e.metaKey) accel = "";
      else accel = acceleratorFor(e);
      if (accel === null) {
        $(row.sub).textContent = "Use Ctrl, Alt or Win with a key, or an F key. Ctrl+C, V, X, A, Z and Y are left alone.";
        $(row.sub).classList.add("srow-sub--error");
        return;
      }
      stopCapture();
      api.setHotkey(action, accel).then(render).catch((err) => {
        $(row.sub).textContent = String((err && err.message) || err).replace(/^Error invoking remote method '[^']+': (Error: )?/, "");
        $(row.sub).classList.add("srow-sub--error");
      });
    };
    capturing = { action, button, listener };
    document.addEventListener("keydown", listener, true);
    window.addEventListener("blur", stopCapture);
    // The shortcuts already set would act before this page saw the keys.
    if (api.pauseHotkeys) api.pauseHotkeys(true).catch(() => {});
  }

  document.querySelectorAll("#appHotkeys [data-hotkey]").forEach((button) => {
    button.addEventListener("click", () => {
      if (capturing && capturing.button === button) { stopCapture(); return; }
      startCapture(button.dataset.hotkey, button);
    });
  });

  // A hotkey pressed anywhere presses Frivo's own button, so it does exactly
  // what clicking it would.
  if (api.onHotkey) {
    api.onHotkey((action) => {
      const btn = $(action === "send" ? "sendBtn" : "dictateBtn");
      if (btn && !btn.disabled) btn.click();
    });
  }

  const baseRender = render;
  render = (s) => { baseRender(s); renderHotkeys(s); };

  api.onState(render);
  refresh();
})();


// ============================================================
// NEW (1.8.0): Settings › Other devices
// ============================================================
// This PC's network address with a QR code for phones, the pairing code the
// Frivo app asks for, and Frivo's certificate for trusting it on a phone.
(function initOtherDevices() {
  const section = $("devicesSection");
  if (!section) return;
  let loaded = false;

  function showQr(url) {
    $("devQr").src = `/api/qr.png?scale=6&text=${encodeURIComponent(url)}`;
    document.querySelectorAll("#devUrls .dev-url").forEach((b) => b.classList.toggle("is-on", b.dataset.url === url));
  }

  async function load() {
    let d;
    try {
      const res = await fetch("/api/devices");
      d = await res.json();
    } catch {
      return;
    }
    loaded = true;
    const urls = d.network_urls || [];
    const host = $("devUrls");
    host.innerHTML = "";
    urls.forEach((url) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "dev-url";
      b.dataset.url = url;
      b.textContent = url;
      b.title = "Show this address as the QR code";
      b.addEventListener("click", () => showQr(url));
      host.appendChild(b);
    });
    $("devQrRow").classList.toggle("is-hidden", !urls.length);
    if (urls.length) showQr(urls[0]);
    $("devCode").textContent = d.pairing_code || "—";
    const note = $("devNote");
    if (!urls.length) {
      note.textContent = "This PC isn't on a network right now, so other devices can't reach Frivo.";
    } else if (!d.https) {
      note.textContent = "Frivo isn't using HTTPS here, so there's no certificate or pairing code. Run setup again (Repair) to make one.";
    } else {
      note.textContent = "If a phone can't connect, allow network access in Frivo's launcher on this PC (Settings › Open port 5000).";
    }
    note.classList.remove("is-hidden");
    $("devCodeRow").classList.toggle("is-hidden", !d.pairing_code);
    $("devTrust").classList.toggle("is-hidden", !d.certificate);
  }

  // Loaded the first time the section is opened.
  new MutationObserver(() => {
    if (!loaded && !section.classList.contains("is-hidden") && section.offsetParent !== null) load();
  }).observe(section, { attributes: true, attributeFilter: ["class", "style", "hidden"] });
  document.querySelectorAll('[data-settings-section="devices"]').forEach((b) => b.addEventListener("click", () => { if (!loaded) load(); }));
})();
