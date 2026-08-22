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
const voiceFilters = $("voiceFilters");
const voiceFavFilter = $("voiceFavFilter");
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
const whisperStartCommand = $("whisperStartCommand");

const oscEnabledToggle = $("oscEnabledToggle");
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
const profilePersonalityPresetSelect = $("profilePersonalityPresetSelect");
const profileSystemPromptInput = $("profileSystemPrompt");
const profileModalSave = $("profileModalSave");
const profileModalCancel = $("profileModalCancel");

// ---------- Status + lamp ----------

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  // The line is a fixed single row that can't wrap, so a long message is
  // ellipsised — the full text stays available on hover rather than being
  // allowed to reflow the page.
  statusEl.title = text || "";
  statusEl.classList.toggle("is-error", isError);
}

function setLamp(state) {
  readyLamp.classList.toggle("is-lit", state === "ready");
  readyLamp.classList.toggle("is-busy", state === "busy");
}

function addCredits(n) {
  sessionCredits += n;
  sessionCreditsEl.textContent = `${sessionCredits.toLocaleString()} credits this session`;
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

async function loadLocalStatus() {
  if (!serviceStatus) return;
  try {
    const res = await fetch("/api/local-status");
    const data = await res.json();

    if (!res.ok || data.none_selected) {
      serviceStatus.classList.add("is-hidden");
      return;
    }

    serviceStatus.classList.remove("is-hidden");
    const down = data.services.filter((s) => !s.ok);

    if (!down.length) {
      canStartWhisper = false;
      const names = data.services.map((s) => s.name).join(" + ");
      serviceStatus.className = "service-status is-ok";
      serviceStatus.textContent = names;
      serviceStatus.title =
        data.services
          .map((s) => `${s.name} (${s.url}) — ${s.message}`)
          .join("\n") + "\n\nClick to re-check.";
      return;
    }

    serviceStatus.className = "service-status is-down";
    const whisperDown = down.some((s) => s.id === "whisper");
    canStartWhisper = Boolean(data.can_start_whisper) && whisperDown;
    serviceStatus.textContent =
      down.length === 1 ? `${down[0].name} offline` : `${down.length} services offline`;
    if (canStartWhisper) serviceStatus.textContent += " — click to start";
    serviceStatus.title =
      down
        .map(
          (s) =>
            `${s.name} at ${s.url} is not reachable.\n` +
            `${s.message}\n` +
            `Used for: ${s.used_for.join(", ")}.` +
            // FrivOSC has nothing to fall back to — if it is down, VRChat
            // just gets nothing. Only the providers with an OpenAI path
            // behind them get the warning about paying for it.
            (s.fallback === false
              ? ""
              : " Falling back to OpenAI, which costs credits.")
        )
        .join("\n\n") + "\n\nClick to re-check.";
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

let canStartWhisper = false;

if (serviceStatus) {
  serviceStatus.addEventListener("click", async () => {
    if (!canStartWhisper) {
      serviceStatus.textContent = "Checking…";
      serviceStatus.className = "service-status";
      loadLocalStatus();
      return;
    }

    serviceStatus.textContent = "Starting…";
    serviceStatus.className = "service-status";
    try {
      const res = await fetch("/api/start-whisper", { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        serviceStatus.className = "service-status is-down";
        serviceStatus.textContent = "Start failed";
        serviceStatus.title = data.error || "The start command failed.";
        return;
      }
    } catch (err) {
      serviceStatus.className = "service-status is-down";
      serviceStatus.textContent = "Start failed";
      serviceStatus.title = err.message;
      return;
    }

    // Loading a model takes a while, so poll rather than reporting a
    // result the moment the command returns — the command succeeding only
    // means the task was triggered, not that the service is up.
    serviceStatus.textContent = "Starting… loading model";
    for (let i = 0; i < 40; i += 1) {
      await new Promise((r) => setTimeout(r, 2000));
      const res = await fetch("/api/local-status");
      const data = await res.json();
      const whisper = (data.services || []).find((s) => s.id === "whisper");
      if (whisper && whisper.ok) break;
    }
    loadLocalStatus();
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
    }
  });

  if (ollamaUrl) ollamaUrl.value = settings.ollama_url || "";
  if (ollamaModel) ollamaModel.value = settings.ollama_model || "";
  if (ollamaTranslationModel) {
    ollamaTranslationModel.value = settings.ollama_translation_model || "";
  }
  if (whisperUrl) whisperUrl.value = settings.whisper_url || "";
  if (allowFallbackToggle) allowFallbackToggle.checked = Boolean(settings.allow_openai_fallback);
  if (whisperStartCommand) whisperStartCommand.value = settings.whisper_start_command || "";

  syncProviderVisibility();

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
  lengthValue.textContent = `${words} words`;
  lengthEcho.textContent = words;
  creditEcho.textContent = chars.toLocaleString();
  secondsEcho.textContent = seconds;
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

function attachBubbleAudio(wrap, url, onStart) {
  wrap.classList.add("has-audio", "is-loading");
  wrap.setAttribute("role", "button");
  wrap.setAttribute("tabindex", "0");
  wrap.setAttribute("aria-label", "Loading audio");

  let started = false;
  function fireStart() {
    if (started) return;
    started = true;
    if (typeof onStart === "function") onStart();
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
    if (state.isPlaying) state.rafId = requestAnimationFrame(tick);
  }

  function setPlayingUI(isPlaying) {
    wrap.classList.toggle("is-playing", isPlaying);
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
  }

  function pause() {
    if (!state.isPlaying) return;
    state.offset = currentTime();
    stopSource();
    state.isPlaying = false;
    setPlayingUI(false);
    if (state.rafId) cancelAnimationFrame(state.rafId);
    updateUI();
  }
  wrap._pause = pause;

  function toggle() {
    // Set by the fallback path when Web Audio couldn't decode the clip.
    if (typeof wrap._toggle === "function") return wrap._toggle();
    if (!state.buffer) return;
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

  fetch(url)
    .then((r) => r.arrayBuffer())
    .then((buf) => ensureAudioContext().decodeAudioData(buf))
    .then((decoded) => {
      state.buffer = decoded;
      state.clipGain = computeClipGain(decoded.getChannelData(0));
      wrap.classList.remove("is-loading");
      setPlayingUI(false);
      updateUI();
      play(); // autoplay once decoded, matching the previous behavior
    })
    .catch(() => {
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
      // Clicking the bubble drives the fallback element too, so the
      // interaction is the same whichever path a clip took.
      wrap._toggle = () => (audio.paused ? audio.play() : audio.pause());
      wrap.appendChild(audio);
    });
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


function addTurn(who, text, opts = {}) {
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
    const spent = opts.spoke === false ? "not spoken" : `${opts.charCount} credits`;
    cost.textContent = `${opts.wordCount} words${target} · ${spent}`;
    meta.appendChild(cost);
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
      time.title =
        opts.spoke === false
          ? `ChatGPT: ${opts.textSeconds.toFixed(1)}s · not spoken`
          : `ChatGPT: ${opts.textSeconds.toFixed(1)}s · ElevenLabs: ${opts.audioSeconds.toFixed(1)}s`;
    }
    meta.appendChild(time);
  }

  const body = document.createElement("div");
  body.className = "bubble";
  const textEl = document.createElement("span");
  textEl.className = "bubble-text";
  textEl.textContent = text;
  body.appendChild(textEl);

  // Wall-clock time, floated into the last line of the bubble the way every
  // messaging app does it. Floated rather than absolutely positioned so it
  // reserves its own space and can never sit on top of the final word.
  const stamp = document.createElement("span");
  stamp.className = "bubble-stamp";
  stamp.textContent = new Date().toLocaleTimeString([], {
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
    attachBubbleAudio(body, opts.audioUrl, opts.onAudioStart);
  }

  if (opts.condensed) {
    const flag = document.createElement("span");
    flag.className = "turn-flag";
    flag.textContent = "Ran long — rewritten to length";
    stack.appendChild(flag);
  } else if (opts.repaired) {
    const flag = document.createElement("span");
    flag.className = "turn-flag";
    flag.textContent = "Trimmed to last full sentence";
    stack.appendChild(flag);
  }

  // Under the bubble, in the margin — present when you look for it, out of
  // the way when you're reading.
  if (meta.childNodes.length) stack.appendChild(meta);

  removeTypingBubble();
  logBody.appendChild(turn);
  logEl.scrollTop = logEl.scrollHeight;
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
  logEl.scrollTop = logEl.scrollHeight;
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
}

function addProfileDivider(label) {
  // Nothing to divide yet.
  if (logBody.querySelector(".empty")) return;

  // Switching back and forth without saying anything shouldn't leave a
  // stack of markers, so an unused one is replaced rather than added to.
  const last = logBody.lastElementChild;
  if (last && last.classList.contains("turn-divider")) last.remove();

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
  systemPromptInput.value = data.system_prompt || "";
  openaiStatus.classList.toggle("is-lit", data.openai_key_set);
  elevenStatus.classList.toggle("is-lit", data.elevenlabs_key_set);

  // The default voice is no longer a control in this panel — it's whatever
  // the Voice row shows while no profile is selected — so it's held in a
  // variable and written back untouched when Settings is saved.
  defaultVoiceId = data.voice_id || "";
  defaultVoiceName = data.voice_name || "";
  renderVoiceTrigger();

  if (oscEnabledToggle) oscEnabledToggle.checked = Boolean(data.osc_enabled);
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
      data.response_style || "flair",
      handleSettingsResponseStyleChange
    );
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
  settingsPanel.classList.toggle("is-hidden", !open);
  settingsToggle.classList.toggle("is-active", open);
  // Always reopens at the top level. Coming back to whichever sub-page you
  // were on last time is the kind of state that feels broken rather than
  // helpful — you asked for Settings, not for the page you left.
  if (!open && typeof closeSettingsPage === "function") closeSettingsPage();
  if (open && typeof refreshSettingsSummaries === "function") refreshSettingsSummaries();
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
  if (settingsPanel.classList.contains("is-hidden")) return;
  // One level at a time: a sub-page closes back to the list, and only the
  // list closes Settings itself.
  if (typeof settingsPageIsOpen === "function" && settingsPageIsOpen()) {
    closeSettingsPage();
    return;
  }
  setSettingsOpen(false);
});

saveSettingsBtn.addEventListener("click", async () => {
  const body = {
    // Written back as-is. The picker owns this value now; sending it
    // unchanged keeps /api/settings from clearing it.
    voice_id: defaultVoiceId,
    voice_name: defaultVoiceName,
    model: getModelValue(textModelList, textModelCustom, recommendedTextModel),
    translation_model: getModelValue(translationModelList, translationModelCustom, recommendedTranslationModel),
    system_prompt: systemPromptInput.value,
    response_style: getRadioValue(responseStyleRadios, "flair"),
    personality_preset: personalityPresetSelect.value,
    max_words: parseInt(lengthSlider.value, 10),
    speaking_speed: speakingSpeedSlider ? parseInt(speakingSpeedSlider.value, 10) / 100 : 1,
    temperature: temperatureSlider ? parseInt(temperatureSlider.value, 10) / 100 : 0.7,
    max_tokens: readMaxTokensSetting(),
    language: currentLanguage,
    chat_provider: getRadioValue(chatProviderRadios, "openai"),
    translation_provider: getRadioValue(translationProviderRadios, "openai"),
    transcription_provider: getRadioValue(transcriptionProviderRadios, "openai"),
    ollama_url: ollamaUrl ? ollamaUrl.value.trim() : "",
    ollama_model: ollamaModel ? ollamaModel.value.trim() : "",
    ollama_translation_model: ollamaTranslationModel
      ? ollamaTranslationModel.value.trim()
      : "",
    whisper_url: whisperUrl ? whisperUrl.value.trim() : "",
    whisper_start_command: whisperStartCommand ? whisperStartCommand.value.trim() : "",
    allow_openai_fallback: allowFallbackToggle ? allowFallbackToggle.checked : false,
    osc_enabled: oscEnabledToggle ? oscEnabledToggle.checked : false,
  };
  if (openaiKeyInput.value.trim()) body.openai_api_key = openaiKeyInput.value.trim();
  if (elevenKeyInput.value.trim()) body.elevenlabs_api_key = elevenKeyInput.value.trim();

  const res = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (res.ok) {
    openaiKeyInput.value = "";
    elevenKeyInput.value = "";
    setStatus("Settings saved.");
    await loadSettings();
    // Providers may have just changed, so the indicator is stale.
    loadLocalStatus();
    // A key may have just been pasted in, which is the difference between
    // an empty picker and a full one — and between a balance and no
    // balance to show.
    await loadVoices();
    loadCredits({ force: true });
    refreshPromptIfOpen();
    setSettingsOpen(false);
  } else {
    setStatus("Settings didn't save. Try again.", true);
  }
});


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
    creditsPanel.classList.toggle("is-hidden", !opening);
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
}

// ---------- FrivOSC status ----------
// Frivo speaks no OSC of its own. FrivOSC runs on the VRChat PC and reports
// in; all this does is show whether it is there, and keep the composer
// switch honest about whether a message would actually arrive.

const FRIVOSC_POLL_MS = 5000;
let frivoscTimer = null;

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
    oscConfigured = frivoscConnected && oscEnabled_setting;
    setSummary("frivoscStatusValue", describeFrivosc(data));
    syncOscSwitch();
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
  pollFrivoscStatus();
  frivoscTimer = setInterval(pollFrivoscStatus, FRIVOSC_POLL_MS);
}

if (oscEnabledToggle) {
  oscEnabledToggle.addEventListener("change", () => {
    // Reflected immediately so the composer switch does not look stale
    // between here and the next poll; the server is the authority and the
    // poll will correct this if saving failed.
    oscEnabled_setting = oscEnabledToggle.checked;
    oscConfigured = oscEnabled_setting && frivoscConnected;
    syncOscSwitch();
  });
}

function sendToChatbox(text, { speaking = false } = {}) {
  if (!text) return;
  if (!oscConfigured) {
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
    .catch((err) => setStatus(`VRChat chatbox: ${err.message}`, true));
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

const voiceFacets = { fav: false, language: "", gender: "", category: "" };
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
function voiceLanguageLabel(v) {
  const langs = v.languages || [];
  if (!langs.length) return "";
  const first = langs[0].name;
  return langs.length > 1 ? `${first} +${langs.length - 1}` : first;
}

function renderVoiceTrigger() {
  const id = activeVoiceId();
  const v = voiceById(id);

  // Falls back to the stored name so the row still reads correctly before
  // the list has loaded, or when there's no ElevenLabs key to load it with.
  if (v) {
    voiceTriggerName.textContent = voiceShortName(v);
    // The full name still lives in the tooltip, so nothing is lost by
    // showing the short one on the row.
    voiceTrigger.title = v.name;
    // Same two facts as the list rows, for the same reason.
    voiceTriggerTags.textContent = [voiceLanguageLabel(v), v.gender]
      .filter(Boolean)
      .join(" · ");
  } else if (activeVoiceName()) {
    voiceTriggerName.textContent = activeVoiceName();
    voiceTriggerTags.textContent = allVoices.length ? "not in your library" : "";
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

function anyFacetActive() {
  return Boolean(
    voiceFacets.fav || voiceFacets.language || voiceFacets.gender || voiceFacets.category
  );
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

function renderVoiceFilters() {
  const favCount = voiceFavorites().filter((id) => voiceById(id)).length;
  voiceFavFilter.classList.toggle("is-on", voiceFacets.fav);
  voiceFavFilter.disabled = !favCount;
  voiceFavFilter.title = favCount
    ? `${favCount} starred`
    : "Star a voice to use this";

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

  voiceFilterClear.classList.toggle("is-hidden", !anyFacetActive());
}

function onFacetChange() {
  renderVoiceFilters();
  renderVoiceList();
}

voiceFavFilter.addEventListener("click", () => {
  voiceFacets.fav = !voiceFacets.fav;
  onFacetChange();
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
  voiceFacets.fav = false;
  voiceFacets.language = "";
  voiceFacets.gender = "";
  voiceFacets.category = "";
  onFacetChange();
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

function voiceGroupNode(label) {
  const el = document.createElement("div");
  el.className = "voice-group";
  el.textContent = label;
  return el;
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

function voiceRowNode(v) {
  const isCurrent = v.voice_id === activeVoiceId();

  const row = document.createElement("div");
  row.className = "voice-row";
  row.setAttribute("role", "option");
  row.setAttribute("aria-selected", String(isCurrent));
  row.classList.toggle("is-current", isCurrent);

  const mark = document.createElement("span");
  mark.className = "voice-mark";
  mark.style.setProperty("--voice-color", voiceColor(v.voice_id));
  mark.appendChild(iconNode("i-wave", "icon-18"));

  // Three fixed columns — name, language, gender — so the values line up
  // down the list and can be compared by scanning rather than read one row
  // at a time. Everything else about a voice is behind the row menu.
  const pick = document.createElement("button");
  pick.type = "button";
  pick.className = "voice-pick";

  const name = document.createElement("span");
  name.className = "voice-name";
  name.textContent = voiceShortName(v);

  const lang = document.createElement("span");
  lang.className = "voice-lang";
  const langLabel = voiceLanguageLabel(v);
  if (langLabel) {
    // A language worked out from the accent rather than stated by the voice
    // is marked, so a wrong guess is explicable instead of baffling.
    if (v.language_source === "accent") lang.classList.add("is-guess");
    lang.textContent = langLabel;
  } else {
    // Kept in the DOM even when empty so the gender column stays aligned
    // with the rows above and below it.
    lang.classList.add("is-blank");
  }

  const gender = document.createElement("span");
  gender.className = "voice-gender";
  gender.textContent = v.gender || "";

  pick.append(name, lang, gender);
  pick.addEventListener("click", () => chooseVoice(v));

  row.append(mark, pick);

  if (v.preview_url) {
    const play = document.createElement("button");
    play.type = "button";
    play.className = "voice-preview";
    const playing = voicePreviewId === v.voice_id;
    play.classList.toggle("is-playing", playing);
    play.appendChild(iconNode(playing ? "i-stop" : "i-play", "icon-16"));
    play.title = "Hear a sample — costs nothing";
    play.setAttribute("aria-label", playing ? "Stop sample" : "Play sample");
    play.addEventListener("click", (e) => {
      e.stopPropagation();
      playVoicePreview(v);
    });
    row.appendChild(play);
  }

  // Keep the action menu on the voice in use too. It used to be replaced by
  // a non-interactive checkmark, which meant the selected voice could not be
  // added to or removed from Favorites.
  const menuBtn = document.createElement("button");
  menuBtn.type = "button";
  menuBtn.className = "voice-menu-btn";
  menuBtn.classList.toggle("is-current", isCurrent);
  menuBtn.title = isCurrent ? "Selected voice options" : "More";
  menuBtn.setAttribute("aria-label", `More options for ${v.name}${isCurrent ? " (selected)" : ""}`);
  menuBtn.appendChild(iconNode(isCurrent ? "i-check" : "i-dots", isCurrent ? "icon-16" : "icon-18"));
  menuBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    openVoiceMenu(menuBtn, v);
  });
  row.appendChild(menuBtn);

  return row;
}


let voiceMenuEl = null;

function closeVoiceMenu() {
  if (voiceMenuEl) {
    voiceMenuEl.remove();
    voiceMenuEl = null;
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

  item(isFav ? "Remove from favorites" : "Add to favorites", null, () => {
    toggleFavorite(v.voice_id);
    renderVoiceFilters();
    renderVoiceList();
  });
  item("Voice details", "i-spark", () => showVoiceTip(anchor, v));
  if (v.category) {
    item(`Hide all ${categoryLabel(v.category)} voices`, "i-close", () => {
      toggleHiddenCategory(v.category);
      renderVoiceFilters();
      renderVoiceList();
    });
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
  const query = voiceQuery.trim().toLowerCase();

  // While searching, what you typed outranks the sort: a name starting with
  // the query is almost always the one being looked for, even if the sort
  // would bury it. The chosen order still applies within each bucket.
  if (query) {
    const ordered = sortVoicesFlat(matches);
    const starts = ordered.filter((v) => v.name.toLowerCase().startsWith(query));
    const startIds = new Set(starts.map((v) => v.voice_id));
    const rest = ordered.filter((v) => !startIds.has(v.voice_id));
    return [["", [...starts, ...rest]]];
  }

  if (voiceSortMode === "language") {
    const groups = new Map();
    matches.forEach((v) => {
      const label = (v.languages || [])[0]?.name || "No language listed";
      if (!groups.has(label)) groups.set(label, []);
      groups.get(label).push(v);
    });
    return [...groups.entries()]
      .sort((a, b) => {
        // The catch-all goes last however it happens to sort.
        if (a[0] === "No language listed") return 1;
        if (b[0] === "No language listed") return -1;
        return a[0].localeCompare(b[0]);
      })
      .map(([label, list]) => [label, list.sort(byVoiceName)]);
  }

  if (voiceSortMode === "recent") {
    // Voices ElevenLabs gives no date for can't be placed in the order, so
    // they go after everything that can, alphabetically among themselves —
    // rather than being silently treated as the oldest.
    const dated = matches.filter((v) => v.created_at);
    const undated = matches.filter((v) => !v.created_at).sort(byVoiceName);
    dated.sort((a, b) => b.created_at - a.created_at);
    return undated.length
      ? [["Newest first", dated], ["No date from ElevenLabs", undated]]
      : [["", dated]];
  }

  if (voiceSortMode === "name") {
    return [["", [...matches].sort(byVoiceName)]];
  }

  if (voiceSortMode === "category") {
    const groups = new Map();
    matches.forEach((v) => {
      const label = categoryLabel(v.category);
      if (!groups.has(label)) groups.set(label, []);
      groups.get(label).push(v);
    });
    return [...groups.entries()]
      .sort((a, b) => {
        // "Default" is ElevenLabs' own stock set and the one most people
        // are looking for, so it leads regardless of how it sorts.
        if (a[0] === "Default") return -1;
        if (b[0] === "Default") return 1;
        if (a[0] === "Uncategorised") return 1;
        if (b[0] === "Uncategorised") return -1;
        return a[0].localeCompare(b[0]);
      })
      .map(([label, list]) => [label, list.sort(byVoiceName)]);
  }

  // "favorites" — starred first, then what you've used lately, then the
  // rest. The default, because it puts the handful of voices you actually
  // switch between at the top of a list of dozens.
  const favs = new Set(voiceFavorites());
  const recents = voiceRecents();
  const fav = matches.filter((v) => favs.has(v.voice_id)).sort(byVoiceName);
  const used = matches
    .filter((v) => !favs.has(v.voice_id) && recents.includes(v.voice_id))
    .sort((a, b) => recents.indexOf(a.voice_id) - recents.indexOf(b.voice_id));
  const pinned = new Set([...fav, ...used].map((v) => v.voice_id));
  const rest = matches.filter((v) => !pinned.has(v.voice_id)).sort(byVoiceName);
  return [
    ["Favorites", fav],
    ["Recently used", used],
    [fav.length || used.length ? "All voices" : "", rest],
  ];
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
  voiceList.innerHTML = "";
  voiceRows = [];
  voiceActiveIndex = -1;

  if (!allVoices.length) {
    const note = document.createElement("p");
    note.className = "voice-none";
    note.textContent = "No voices loaded. Check your ElevenLabs key in Settings, then Reload.";
    voiceList.appendChild(note);
    voiceFoot.textContent = "";
    return;
  }

  const matches = matchingVoices();
  if (!matches.length) {
    const note = document.createElement("p");
    note.className = "voice-none";
    note.textContent = "Nothing matches that.";
    voiceList.appendChild(note);
    voiceFoot.textContent = `0 of ${allVoices.length}`;
    return;
  }

  const sections = voiceSections(matches);

  sections.forEach(([label, list]) => {
    if (!list.length) return;
    if (label) voiceList.appendChild(voiceGroupNode(label));
    list.forEach((v) => {
      const row = voiceRowNode(v);
      voiceList.appendChild(row);
      voiceRows.push({ row, voice: v });
    });
  });

  voiceFoot.textContent =
    matches.length === allVoices.length
      ? `${allVoices.length} voices`
      : `${matches.length} of ${allVoices.length} voices`;
  showHiddenCategoryNote();
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
  note.textContent = `${hidden.map(categoryLabel).join(", ")} hidden — show`;
  note.title = "Bring these categories back into the list";
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
    setStatus(`Couldn't play that preview: ${err.message}`, true);
    renderVoiceList();
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
  voiceTrigger.setAttribute("aria-expanded", "true");
  // Every visit starts from a clean slate rather than resuming last time's
  // search, which is almost never what you want on reopening.
  voiceQuery = "";
  voiceSearch.value = "";
  voiceFacets.fav = false;
  voiceFacets.language = "";
  voiceFacets.gender = "";
  voiceFacets.category = "";
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
      ? `Speaks as ${profile.voice_name}. Change it from the Voice row while this profile is selected.`
      : "Set its voice from the Voice row while this profile is selected.";
  } else {
    const current = voiceById(activeVoiceId());
    const name = current ? current.name : activeVoiceName();
    profileVoiceNote.textContent = name
      ? `Starts on the voice you have selected now (${name}), and can be changed any time from the Voice row.`
      : "Pick a voice from the Voice row first — a profile needs one.";
  }
  buildRadioGroup(
    profileResponseStyleRadios,
    responseStyles,
    "responseStyleProfile",
    profile ? (profile.response_style || "flair") : getRadioValue(responseStyleRadios, "flair"),
    null
  );
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
}

function closeModal() {
  overlay.classList.add("is-hidden");
}

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
    setStatus("Pick a voice in the Voice row first — a profile needs one.", true);
    return;
  }

  const body = {
    name,
    voice_id: voiceId,
    voice_name: voiceName,
    system_prompt: systemPrompt,
    response_style: getRadioValue(profileResponseStyleRadios, "flair"),
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
  const styleLabels = { echo: "Exact echo", flair: "With personality", reply: "Reply" };
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


const MIC_STORAGE_KEY = "voice_console_mic_device_id";

function fillMicrophones(devices, selectedId) {
  const mics = devices.filter((d) => d.kind === "audioinput");
  micSelect.innerHTML = "";
  if (!mics.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No microphones found";
    micSelect.appendChild(opt);
    return;
  }
  mics.forEach((mic, i) => {
    const opt = document.createElement("option");
    opt.value = mic.deviceId;
    opt.textContent = mic.label || `Microphone ${i + 1}`;
    if (mic.deviceId === selectedId) opt.selected = true;
    micSelect.appendChild(opt);
  });
}

async function loadMicrophones() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
    micSelect.innerHTML = '<option value="">Not supported in this browser</option>';
    return;
  }
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    fillMicrophones(devices, localStorage.getItem(MIC_STORAGE_KEY) || "");
    const hasLabels = devices.some((d) => d.kind === "audioinput" && d.label);
    micNote.textContent = hasLabels
      ? "Used when you click the dictation mic button."
      : "Click Reload once to grant microphone access and see device names.";
  } catch (err) {
    console.error("enumerateDevices failed:", err);
  }
}

micSelect.addEventListener("change", () => {
  localStorage.setItem(MIC_STORAGE_KEY, micSelect.value);
});

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

function scheduleAutoSend() {
  if (!autoSendToggle || !autoSendToggle.checked) return;
  cancelAutoSend();
  autoSendTimer = setTimeout(() => {
    autoSendTimer = null;
    // Re-checked at fire time, not just when scheduled: you may have
    // started speaking again, cleared the box, or switched the option off
    // during the grace period.
    if (!autoSendToggle.checked) return;
    if (!messageInput.value.trim()) return;
    if (sendBtn.disabled) return;
    send();
  }, AUTO_SEND_DELAY_MS);
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

function setDictateUI(active) {
  dictateBtn.classList.toggle("is-recording", active);
  dictateBtn.setAttribute("aria-label", active ? "Stop dictation" : "Dictate");
}

async function startDictation() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
    setStatus("Dictation isn't supported in this browser.", true);
    return;
  }

  const deviceId = localStorage.getItem(MIC_STORAGE_KEY) || "";
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: deviceId ? { deviceId: { exact: deviceId } } : true,
    });
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
  setStatus("Listening… click the mic again to stop.");
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
    const existing = messageInput.value.trim();
    messageInput.value = existing ? `${existing} ${text}` : text;
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
  return [liveCommitted, liveInterim].filter(Boolean).join(" ").trim();
}

function resetLiveDictation() {
  liveCommitted = "";
  liveInterim = "";

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
  messageInput.value = liveDisplayText();
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
  liveStopping = false;

  recognition.addEventListener("result", (event) => {
    syncLiveFromInput();

    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i];
      const chunk = result[0].transcript;
      if (result.isFinal) {
        const trimmed = chunk.trim();
        if (trimmed) liveCommitted = [liveCommitted, trimmed].filter(Boolean).join(" ");
      } else {
        interim += chunk;
      }
    }
    liveInterim = interim.trim();
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
  // How often to re-transcribe while speech continues.
  INTERIM_MS: 1000,
  // Don't bother sending anything shorter than this; it produces noise.
  MIN_CLIP_MS: 400,
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

  const deviceId = localStorage.getItem(MIC_STORAGE_KEY) || "";
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: deviceId ? { deviceId: { exact: deviceId } } : true,
    });
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
    analyser,
    data: new Uint8Array(analyser.fftSize),
    recorder: null,
    chunks: [],
    mimeType: pickRecorderMimeType() || "audio/webm",
    speaking: false,
    silenceSince: 0,
    startedAt: 0,
    lastInterimAt: 0,
    inflight: false,
    timer: null,
  };

  liveCommitted = messageInput.value.trim();
  liveInterim = "";
  liveStopping = false;
  isDictating = true;
  setDictateUI(true);
  setStatus("Listening — text appears as you speak.");

  liveLocal.timer = setInterval(pollLocalLevel, 50);
}

function currentRms() {
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
  recorder.addEventListener("stop", () => finishUtterance(chunks, recorder.speechMs || 0));

  // Small timeslice so there's always recent audio available to send
  // without waiting for the recorder to stop.
  recorder.start(250);
  s.recorder = recorder;
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
    if (isDictating && liveLocal === s && s.speaking) {
      liveInterim = text;
      renderLiveText();
    }
  } catch (err) {
    console.error("interim transcription failed:", err);
  } finally {
    s.inflight = false;
  }
}

async function finishUtterance(chunks, speechMs) {
  const s = liveLocal;
  if (!s) return;

  const tooShort = speechMs < LIVE_LOCAL.MIN_CLIP_MS;

  if (!chunks.length || tooShort) {
    liveInterim = "";
    renderLiveText();
    return;
  }

  const blob = new Blob(chunks, { type: s.mimeType });
  try {
    const text = await transcribeBlob(blob, s.mimeType);
    if (text) {
      // The final pass sees the whole utterance, so it supersedes whatever
      // the interim passes guessed.
      liveCommitted = [liveCommitted, text].filter(Boolean).join(" ");
    }
  } catch (err) {
    setStatus(`Transcription failed: ${err.message}`, true);
  } finally {
    liveInterim = "";
    renderLiveText();
    scheduleAutoSend();
  }
}

function pollLocalLevel() {
  const s = liveLocal;
  if (!s || !isDictating) return;

  const level = currentRms();
  const now = Date.now();

  if (level > LIVE_LOCAL.SPEECH_THRESHOLD) {
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
  if (now - s.silenceSince > LIVE_LOCAL.SILENCE_MS) {
    // Speech ran from the start of the utterance to the moment it went
    // quiet — not to now, which is SILENCE_MS later.
    s.speaking = false;
    if (s.recorder && s.recorder.state !== "inactive") {
      s.recorder.speechMs = s.silenceSince - s.startedAt;
      s.recorder.stop();
    }
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

dictateBtn.addEventListener("click", () => {
  if (isDictating) {
    if (activeDictationMode === "live") stopLiveDictation();
    else if (activeDictationMode === "live_local") stopLocalLiveDictation();
    else stopDictation();
    return;
  }

  activeDictationMode = currentDictationMode();
  if (activeDictationMode === "live") startLiveDictation();
  else if (activeDictationMode === "live_local") startLocalLiveDictation();
  else startDictation();
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
}

// How many distinct voices the panel has separated so far. Counted from
// what's on screen rather than tracked in a variable, so a merge or a Clear
// corrects it without anything extra having to remember to.
const listenPeopleCount = $("listenPeopleCount");
function updateSpeakerCount() {
  if (!listenPeopleCount || !listenLog) return;
  const ids = new Set();
  listenLog.querySelectorAll(".listen-entry[data-speaker-id]").forEach((el) => {
    ids.add(el.dataset.speakerId);
  });
  const n = ids.size;
  listenPeopleCount.textContent = `${n} ${n === 1 ? "person" : "people"}`;
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

const SPEAKER_NAMES_KEY = "voice_console_speaker_names";

function speakerNames() {
  try {
    return JSON.parse(localStorage.getItem(SPEAKER_NAMES_KEY) || "{}");
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
  localStorage.setItem(SPEAKER_NAMES_KEY, JSON.stringify(names));

  // Applies backwards through the transcript, so naming someone halfway
  // through a conversation relabels what they already said.
  const label = speakerLabel(id);
  listenLog.querySelectorAll(`.listen-speaker[data-speaker="${id}"]`).forEach((el) => {
    el.textContent = label;
  });
  listenLog.querySelectorAll(`.listen-avatar[data-speaker="${id}"]`).forEach((el) => {
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
  entry.title = "Click to put this message in your reply box";

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
  entry.addEventListener("click", (event) => {
    if (event.target.closest(".listen-speaker")) return;
    const spoken = text.textContent.trim();
    if (!spoken || spoken === "…") return;
    messageInput.value = spoken;
    messageInput.focus();
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
  const sameAsPrevious = previous && previous.dataset.speakerId === String(id);
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

  if (namesChanged) localStorage.setItem(SPEAKER_NAMES_KEY, JSON.stringify(names));

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
      node.speaker.addEventListener("click", () => renameSpeaker(id));
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

async function sendListenSegment(chunks, mimeType, ref, interim = false) {
  const blob = new Blob(chunks, { type: mimeType });
  const ext = mimeType.includes("mp4") ? "mp4" : mimeType.includes("ogg") ? "ogg" : "webm";

  const form = new FormData();
  form.append("audio", blob, `listen.${ext}`);
  form.append("target_language", listenTargetLanguage());
  if (interim) form.append("interim", "1");

  try {
    const res = await fetch("/api/listen", { method: "POST", body: form });
    const data = await res.json();

    // The node may have been finalised by the real result while this
    // interim pass was still in flight. Late partial text must never
    // overwrite a finished sentence.
    if (interim && ref.node && ref.node.done) return;

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

    fillListenEntry(ensureListenNode(ref), data, interim);
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
  const ref = { node: null };
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

  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const source = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);

  listening = {
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
  listening.timer = setInterval(listenPoll, LISTEN.POLL_MS);

  listenStartBtn.textContent = "Stop listening";
  setListenLamp(true);
  listenStartBtn.classList.add("is-live");
  // Only overwrite the warning above when there was nothing to warn about.
  if (!savedDevice || deviceId === savedDevice) {
    setListenStatus(`Listening → ${listenTargetLanguage()}`);
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

  if (!s) return;
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
  listenStartBtn.addEventListener("click", () => {
    if (listening) stopListening();
    else startListening();
  });
}

// Docking is remembered, because it's a workspace preference rather than a
// per-session choice — if you like the chat window pinned, you like it
// pinned every time.
const listenDockBtn = $("listenDockBtn");
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
    try {
      const res = await fetch("/api/listen-speakers", { method: "DELETE" });
      const data = await res.json();
      if (res.ok) {
        // The saved names refer to voice IDs that no longer exist, so
        // keeping them would attach old names to new people.
        localStorage.removeItem(SPEAKER_NAMES_KEY);
        setListenStatus(`Forgot ${data.cleared} voice profile(s).`);
      } else {
        setListenStatus(data.error || "Couldn't reset voices.");
      }
    } catch (err) {
      setListenStatus(`Reset failed: ${err.message}`);
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

async function send() {
  const message = messageInput.value.trim();
  if (!message) return;

  // Browser audio must be initialized during a direct user gesture.
  if (speakEnabled()) ensureAudioContext();

  messageInput.value = "";
  cancelAutoSend();
  // Start a fresh dictation utterance after sending.
  resetLiveDictation();
  addTurn("You", message);
  showTypingBubble();
  setStatus("Generating…");
  setLamp("busy");
  sendBtn.disabled = true;

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

    addTurn(speaker, data.reply, {
      audioUrl: data.audio_url,
      wordCount: data.word_count,
      charCount: data.char_count,
      targetWords: data.target_words,
      language: data.language,
      english: data.english,
      condensed: data.condensed,
      repaired: data.repaired,
      spoke: data.spoke,
      totalSeconds: data.total_seconds,
      textSeconds: data.text_seconds,
      audioSeconds: data.audio_seconds,
      // Send the spoken reply to OSC when audio playback begins. Checking the
      // current toggle here honors changes made while the reply was generated.
      onAudioStart: () => {
        if (oscEnabled()) sendToChatbox(data.reply, { speaking: true });
      },
    });

    if (!data.audio_url && oscEnabled()) sendToChatbox(data.reply, { speaking: false });

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
  } finally {
    sendBtn.disabled = false;
    messageInput.focus();
  }
}

sendBtn.addEventListener("click", send);
messageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") send();
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
  const wideEnoughForColumn = window.matchMedia("(min-width: 1280px)").matches;
  const listenOpen = savedOpen === null ? wideEnoughForColumn : savedOpen === "1";
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
  if (settingsRoot) settingsRoot.classList.remove("is-hidden");
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
    elevenStatusText.textContent = data.elevenlabs_key_set ? "Connected" : "Not set";
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
  languageTriggerName.textContent = match ? languageLabel(match) : currentLanguage;
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
