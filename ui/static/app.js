/*
 *  ╔════════════════════════════════════════════════════════════╗
 *  ║                                                            ║
 *  ║                     PRIVACY-URL-FINDER                     ║
 *  ║                                                            ║
 *  ║                         by Nihal Rodge                     ║
 *  ║                                                            ║
 *  ║  GitHub: github.com/MrSpideyNihal/privacy-url-finder       ║
 *  ║                                                            ║
 *  ╚════════════════════════════════════════════════════════════╝
 */
/*
 * This code integrates privacy-url-finder for company search and link resolution
 */
/* PrivUp local UI.
 *
 * Presentation only. Every judgement shown here was made by core/main.py;
 * this file decides nothing about a policy, it only renders the Verdict.
 */

"use strict";

const $ = (id) => document.getElementById(id);

const TONES = {
  critical: "#E1573A",
  high: "#D2691E",
  medium: "#C2761C",
  low: "#7A7F88",
  info: "#9A9EA6",
};

const DECISION = {
  allow: { tone: "var(--allow)", kicker: "Allow", line: "Nothing here matched a red flag." },
  warning: { tone: "var(--warning)", kicker: "Warning", line: "Read these before you agree." },
  deny: { tone: "var(--deny)", kicker: "Deny", line: "Do not agree to this without reading it in full." },
};

const SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"];

let currentTags = "generic";

/* UI text for the current verdict, in its language. Sent by the server with
 * every verdict, so this page holds no translations of its own. */
let messages = {};

function t(key, fallback, values = {}) {
  const template = messages[key] || fallback;
  return template.replace(/\{(\w+)\}/g, (whole, name) =>
    name in values ? String(values[name]) : whole
  );
}

/* ---------- sliding segmented pill indicator ---------- */

function updateSegmented(container) {
  if (!container) return;
  let indicator = container.querySelector(".segmented-indicator");
  if (!indicator) {
    indicator = document.createElement("span");
    indicator.className = "segmented-indicator";
    indicator.setAttribute("aria-hidden", "true");
    container.prepend(indicator);
  }

  const activeBtn = container.querySelector('[aria-checked="true"], [aria-selected="true"]');
  if (activeBtn) {
    const left = activeBtn.offsetLeft;
    const width = activeBtn.offsetWidth;
    indicator.style.transform = `translateX(${left}px)`;
    indicator.style.width = `${width}px`;
  }
}

window.addEventListener("resize", () => {
  document.querySelectorAll(".segmented").forEach(updateSegmented);
});

/* ---------- rule set selector ---------- */

async function loadTagSets() {
  const holder = $("tagset");
  let sets;
  try {
    const data = await (await fetch("/api/tags")).json();
    sets = data.tag_sets;
    loadLanguages(data.languages || []);
  } catch {
    holder.textContent = "Could not load rule sets.";
    return;
  }

  holder.replaceChildren(
    ...sets.map((set, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.role = "radio";
      button.textContent = set.name.replace(/_/g, " ");
      button.title = `${set.description} (${set.rules} rules)`;
      button.setAttribute("aria-checked", String(index === 0));
      if (index === 0) currentTags = set.name;

      button.addEventListener("click", () => {
        currentTags = set.name;
        [...holder.children].filter((c) => c.tagName === "BUTTON").forEach((other) =>
          other.setAttribute("aria-checked", String(other === button))
        );
        updateSegmented(holder);
      });
      return button;
    })
  );

  updateSegmented(holder);
  requestAnimationFrame(() => updateSegmented(holder));
}

function loadLanguages(languages) {
  const select = $("lang");
  select.replaceChildren(
    ...languages.map((lang) => {
      const option = document.createElement("option");
      option.value = lang.code;
      option.textContent = lang.native_name === lang.name
        ? lang.name
        : `${lang.native_name} (${lang.name})`;
      return option;
    })
  );
  select.value = "en";
  select.hidden = languages.length < 2;
}

/* ---------- rendering ---------- */

function setStatus(message, kind) {
  const status = $("status");
  if (!message) {
    status.hidden = true;
    return;
  }
  status.textContent = message;
  status.dataset.kind = kind || "info";
  status.hidden = false;
}

function renderVerdict(data) {
  const decision = DECISION[data.decision] ? data.decision : "warning";
  const shape = DECISION[decision];

  document.documentElement.style.setProperty("--accent", shape.tone);
  $("verdict-kicker").textContent = t(`decision.${decision}`, shape.kicker);
  $("verdict-line").textContent =
    data.metadata && data.metadata.empty_document
      ? t("unreadable.empty_document", "No readable policy text was found. This is not an all-clear.")
      : t(`decision.${decision}.line`, shape.line);

  const score = Number(data.risk_score) || 0;
  $("risk-score").textContent = String(Math.round(score));

  // 2 * pi * r, r = 34.
  const circumference = 213.6;
  $("gauge-value").style.strokeDashoffset = String(
    circumference - (circumference * Math.min(score, 100)) / 100
  );
}

function renderMismatch(data) {
  const notice = data.metadata && data.metadata.relevance && data.metadata.relevance.notice;
  const element = $("mismatch");
  element.hidden = !notice;
  if (notice) element.textContent = notice;

  // Policy quotes are never translated, so say so, and say when nobody who
  // speaks the language has checked the translation yet.
  const translation = data.metadata && data.metadata.translation;
  const note = $("translation-note");
  note.hidden = !translation;
  if (translation) {
    const lines = [t("ui.original_language", "")];
    if (!translation.reviewed) lines.push(t("ui.unreviewed", ""));
    note.textContent = lines.filter(Boolean).join(" ");
  }
}

function renderTiles(data) {
  const counts = (data.metadata && data.metadata.severity_counts) || {};
  const present = SEVERITY_ORDER.filter((name) => counts[name]);

  $("tiles").replaceChildren(
    ...present.map((name) => {
      const tile = document.createElement("div");
      tile.className = "tile";
      tile.style.setProperty("--tone", TONES[name]);
      tile.innerHTML =
        `<span class="tile-label"><i class="dot"></i></span><strong></strong>`;
      tile.querySelector(".tile-label").append(t(`severity.${name}`, name));
      tile.querySelector("strong").textContent = String(counts[name]);
      return tile;
    })
  );
}

/* Highlight the matched phrase inside the quoted clause without ever
 * building HTML from policy text. */
function quoteClause(text, matched) {
  const paragraph = document.createElement("p");
  paragraph.className = "clause";

  const at = matched ? text.toLowerCase().indexOf(matched.toLowerCase()) : -1;
  if (at < 0) {
    paragraph.textContent = text;
    return paragraph;
  }

  const mark = document.createElement("mark");
  mark.textContent = text.slice(at, at + matched.length);
  paragraph.append(
    document.createTextNode(text.slice(0, at)),
    mark,
    document.createTextNode(text.slice(at + matched.length))
  );
  return paragraph;
}

function renderFinding(finding) {
  const item = document.createElement("li");
  const details = document.createElement("details");
  details.className = "finding";
  details.style.setProperty("--tone", TONES[finding.severity] || TONES.info);

  const summary = document.createElement("summary");
  const severity = document.createElement("span");
  severity.className = "severity";
  severity.textContent = t(`severity.${finding.severity}`, finding.severity);
  const reason = document.createElement("span");
  reason.className = "reason";
  reason.textContent = finding.reason;
  const chevron = document.createElement("i");
  chevron.className = "chevron";
  summary.append(severity, reason, chevron);

  const evidence = document.createElement("div");
  evidence.className = "evidence";

  const isAbsence = finding.clause.index < 0;
  if (isAbsence) {
    const note = document.createElement("p");
    note.className = "absence";
    note.textContent = t(
      "ui.absence",
      "Nothing anywhere in this document covers this. The finding is the absence."
    );
    evidence.append(note);
  } else {
    if (finding.clause.heading) {
      const where = document.createElement("p");
      where.className = "clause-where";
      where.textContent = t("ui.under_heading", 'Under "{heading}"', {
        heading: finding.clause.heading,
      });
      evidence.append(where);
    }
    evidence.append(quoteClause(finding.clause.text, finding.matched_text));
  }

  const citation = document.createElement("p");
  citation.className = "citation";
  citation.textContent = finding.reference
    ? `${finding.reference} · ${finding.rule_id}`
    : finding.rule_id;
  evidence.append(citation);

  details.append(summary, evidence);
  item.append(details);
  return item;
}

function renderFindings(data) {
  const findings = data.findings || [];
  $("findings").replaceChildren(...findings.map(renderFinding));
  $("empty").hidden = findings.length > 0;
  $("findings-title").textContent = findings.length
    ? `What it found (${findings.length})`
    : "What it found";

  const source = data.driver === "url" || data.driver === "company" ? data.origin : "pasted text";
  $("meta").textContent = `${data.clauses_analyzed} clauses read · ${data.rule_set} · ${source}`;
}

function render(data) {
  messages = data.messages || {};
  renderVerdict(data);
  renderMismatch(data);
  renderTiles(data);
  renderFindings(data);
  $("result").hidden = false;
  $("result").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* ---------- input mode switcher ---------- */

let currentMode = "company";

function initInputModes() {
  const modesHolder = $("input-modes");
  if (!modesHolder) return;

  const tabs = modesHolder.querySelectorAll(".mode-tab");
  const sectionCompany = $("section-company");
  const sectionText = $("section-text");
  const hint = $("input-hint");

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const mode = tab.dataset.mode;
      currentMode = mode;
      tabs.forEach((t) => {
        const isSel = String(t === tab);
        t.setAttribute("aria-selected", isSel);
        t.setAttribute("aria-checked", isSel);
      });
      updateSegmented(modesHolder);

      if (mode === "company") {
        sectionCompany.hidden = false;
        sectionText.hidden = true;
        hint.textContent = "Finds and verifies the official privacy policy using Privacy URL Finder.";
        const comp = $("company-target");
        if (comp) comp.focus();
      } else {
        sectionCompany.hidden = true;
        sectionText.hidden = false;
        hint.textContent = "A link is fetched and followed; pasted text is read directly on this machine.";
        const tgt = $("target");
        if (tgt) tgt.focus();
      }
    });
  });

  updateSegmented(modesHolder);
  requestAnimationFrame(() => updateSegmented(modesHolder));

  const compInput = $("company-target");
  if (compInput) {
    compInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") analyze(event);
    });
  }
}

/* ---------- submit ---------- */

async function analyze(event) {
  event.preventDefault();

  let target = "";
  let driver = null;

  if (currentMode === "company") {
    target = ($("company-target") ? $("company-target").value : "").trim();
    if (!target) {
      setStatus("Enter a company, app name, or Android package.", "error");
      return;
    }
    driver = "company";
  } else {
    target = ($("target") ? $("target").value : "").trim();
    if (!target) {
      setStatus("Paste a policy, or a link to one.", "error");
      return;
    }
  }

  const button = $("analyze");
  button.disabled = true;
  button.textContent = currentMode === "company" ? "Searching" : "Reading";
  $("result").hidden = true;
  setStatus(
    currentMode === "company"
      ? `Discovering and verifying privacy policy for "${target}"...`
      : "Reading the document on this machine."
  );

  try {
    const payload = { target, tags: currentTags, lang: $("lang").value || "en" };
    if (driver) payload.driver = driver;

    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();

    if (!response.ok) {
      setStatus(data.error || "That did not work.", "error");
      return;
    }
    setStatus(null);
    render(data);
  } catch {
    setStatus("Could not reach the local PrivUp server. Is it still running?", "error");
  } finally {
    button.disabled = false;
    button.textContent = "Analyze";
  }
}

$("composer").addEventListener("submit", analyze);

// Ctrl/Cmd+Enter submits from inside the textarea.
$("target").addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") analyze(event);
});

initInputModes();
loadTagSets();
