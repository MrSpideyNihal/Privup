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

/* ---------- rule set selector ---------- */

async function loadTagSets() {
  const holder = $("tagset");
  let sets;
  try {
    sets = (await (await fetch("/api/tags")).json()).tag_sets;
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
        [...holder.children].forEach((other) =>
          other.setAttribute("aria-checked", String(other === button))
        );
      });
      return button;
    })
  );
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
  const shape = DECISION[data.decision] || DECISION.warning;

  document.documentElement.style.setProperty("--accent", shape.tone);
  $("verdict-kicker").textContent = shape.kicker;
  $("verdict-line").textContent =
    data.metadata && data.metadata.empty_document
      ? "No readable policy text was found. This is not an all-clear."
      : shape.line;

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
        `<span class="tile-label"><i class="dot"></i>${name}</span><strong></strong>`;
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
  severity.textContent = finding.severity;
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
    note.textContent = "Nothing anywhere in this document covers this. The finding is the absence.";
    evidence.append(note);
  } else {
    if (finding.clause.heading) {
      const where = document.createElement("p");
      where.className = "clause-where";
      where.textContent = `Under "${finding.clause.heading}"`;
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

  const source = data.driver === "url" ? data.origin : "pasted text";
  $("meta").textContent = `${data.clauses_analyzed} clauses read · ${data.rule_set} · ${source}`;
}

function render(data) {
  renderVerdict(data);
  renderMismatch(data);
  renderTiles(data);
  renderFindings(data);
  $("result").hidden = false;
  $("result").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* ---------- submit ---------- */

async function analyze(event) {
  event.preventDefault();

  const target = $("target").value.trim();
  if (!target) {
    setStatus("Paste a policy, or a link to one.", "error");
    return;
  }

  const button = $("analyze");
  button.disabled = true;
  button.textContent = "Reading";
  $("result").hidden = true;
  setStatus("Reading the document on this machine.");

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target, tags: currentTags }),
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

loadTagSets();
