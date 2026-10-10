"use strict";

const $ = (id) => document.getElementById(id);
const REFRESH_MS = 5000;
const ADVANCE_MIN = 60;

const STATUS = {
  preparing: "Preparing",
  failed: "Failed",
  invited: "Invited",
  in_progress: "In interview",
  interviewed: "Evaluating",
  advance: "Advance",
  reject: "Reject",
};
const ENDINGS = {
  completed: "ran to the end",
  time_limit: "cut short by the time limit",
  disconnected: "connection dropped",
  stopped: "stopped early",
};

// session id -> { open, tab, detail, signature }
const state = new Map();
let hashHandled = false; // the row named in the URL hash is opened once

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

// All text is set through textContent: it comes from an LLM, a CV and a candidate.
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const clock = (seconds) =>
  `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
const day = (iso) =>
  new Date(iso).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
const interviewUrl = (summary) => `${location.origin}${summary.interview_url}`;

async function getJson(url) {
  const response = await fetch(url);
  const data = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      (data && typeof data.detail === "string" && data.detail) ||
        `Request failed (${response.status}).`,
    );
  return data;
}

function pill(status) {
  const node = el("span", `pill ${status}`);
  node.append(el("span", "status-dot"), STATUS[status] || status);
  return node;
}

function list(title, items) {
  const card = el("div", "eval-card");
  card.append(el("h4", "", title));
  if (items.length) {
    const ul = el("ul");
    ul.append(...items.map((item) => el("li", "", item)));
    card.append(ul);
  } else card.append(el("p", "", "None."));
  return card;
}

// Run (or re-run) the evaluation for one candidate, then redraw the list.
async function evaluate(sessionId, button, message) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "Evaluating…";
  try {
    const response = await fetch(
      `/sessions/${encodeURIComponent(sessionId)}/evaluate`,
      { method: "POST" },
    );
    const data = await response.json().catch(() => null);
    if (!response.ok)
      throw new Error(
        (data && typeof data.detail === "string" && data.detail) ||
          `Evaluation failed (${response.status}).`,
      );
    // Force this row to refetch even if its status and score did not change.
    const entry = state.get(sessionId);
    if (entry) entry.signature = null;
    $("candidate-list").dataset.signature = "";
    await refresh();
  } catch (error) {
    message.textContent = `The evaluation did not complete: ${error.message}`;
    message.className = "note bad";
    button.disabled = false;
    button.textContent = label;
  }
}

function evaluateButton(sessionId, label, message, confirmText) {
  const button = el("button", "button secondary compact", label);
  button.type = "button";
  button.addEventListener("click", () => {
    if (confirmText && !confirm(confirmText)) return;
    evaluate(sessionId, button, message);
  });
  return button;
}

// --- tab views ---------------------------------------------------------------

function transcriptView(detail) {
  const view = el("div");
  const transcript = detail.transcript;
  if (!transcript) {
    view.append(
      el(
        "p",
        "note",
        detail.summary.status === "invited"
          ? "No interview yet. Send the candidate their link."
          : "The transcript appears here once the interview starts.",
      ),
    );
    return view;
  }
  if (transcript.ended_reason && transcript.ended_reason !== "completed")
    view.append(
      el(
        "p",
        "note warn",
        `This interview did not finish normally: ${ENDINGS[transcript.ended_reason] || transcript.ended_reason}.`,
      ),
    );
  for (const turn of transcript.turns) {
    const row = el("div", "turn");
    const who = el(
      "div",
      `turn-who ${turn.speaker}`,
      turn.speaker === "agent" ? "Interviewer" : detail.record.first_name,
    );
    const tags = [
      turn.question_id ? turn.question_id.toUpperCase() : null,
      turn.followup ? "follow-up" : null,
      turn.second_chance
        ? turn.hint
          ? "second chance, hint"
          : "second chance"
        : null,
      turn.interrupted ? "interrupted" : null,
    ].filter(Boolean);
    if (tags.length) who.append(el("small", "", tags.join(" · ")));
    const text = el("div", "", turn.text);
    if (turn.interrupted)
      text.append(
        el(
          "span",
          "turn-heard",
          turn.heard ? `Heard only: “${turn.heard}”` : "Not heard.",
        ),
      );
    row.append(el("time", "", clock(turn.t)), who, text);
    view.append(row);
  }
  return view;
}

function evaluationView(detail) {
  const view = el("div");
  const report = detail.report;
  if (!report) {
    const finished = detail.summary.status === "interviewed";
    const message = el(
      "p",
      "note",
      finished
        ? "The evaluation is being written. It normally appears here within a minute."
        : "The evaluation appears here after the interview.",
    );
    view.append(message);
    // The evaluation starts by itself; this is for when that run failed.
    if (finished)
      view.append(evaluateButton(detail.record.session_id, "Evaluate now", message));
    return view;
  }
  const advance = report.decision === "advance";
  const panel = el("div", "decision-panel");
  const left = el("div");
  left.append(
    pill(report.decision),
    el(
      "h3",
      "",
      advance ? "Advance to the next round" : "Not moving forward",
    ),
    el("p", "", report.summary),
  );
  const score = el("div", "decision-score");
  score.append(
    el("strong", "", String(report.overall_score)),
    el("span", "", `out of 100 · bar ${ADVANCE_MIN}`),
  );
  panel.append(left, score);
  view.append(panel);

  if (!report.interview_complete)
    view.append(
      el(
        "p",
        "note bad",
        "Incomplete interview: questions without an answer score 0.",
      ),
    );
  if (report.needs_human_review)
    view.append(
      el(
        "p",
        "note warn",
        `Check before relying on this: ${report.review_reasons.join(" ")}`,
      ),
    );

  const columns = el("div", "eval-columns");
  if (advance)
    columns.append(
      list("Strengths", report.strengths),
      list("Cover in the next interviews", report.next_interview_focus),
    );
  else
    columns.append(
      list("Reasons", report.rejection_reasons),
      list("Strengths noted", report.strengths),
    );
  view.append(columns);

  const how = el("div", "eval-card");
  how.append(
    el("h4", "", "How the score came about"),
    el("p", "", report.reasoning),
  );
  how.style.marginBottom = "22px";
  view.append(how);

  view.append(el("h3", "view-title", "Question by question"));
  report.per_question.forEach((q, index) => {
    const card = el("article", "question-card");
    const title = el("div", "question-title");
    title.append(
      el("span", "question-number", `0${index + 1}`),
      el("h3", "", q.question),
      el("span", "question-score", `${q.score} / 100`),
    );
    card.append(title);
    const tags = el("div", "question-tags");
    if (q.status !== "answered") {
      const missing = el("span", "pill failed");
      missing.append(el("span", "status-dot"), "Not answered");
      tags.append(missing);
    }
    for (const [on, label] of [
      [q.followup_asked, "Follow-up asked"],
      [q.second_chance_given, q.hint_given ? "Second chance with hint" : "Second chance"],
      [q.score_before_cap != null, `Capped from ${q.score_before_cap}`],
    ])
      if (on) tags.append(el("span", "pill", label));
    if (tags.children.length) card.append(tags);
    card.append(el("p", "question-reasoning", q.reasoning));
    for (const [label, items, quote] of [
      ["Covered", q.covered_points, false],
      ["Missed", q.missed_points, false],
      ["In the candidate’s words", q.evidence, true],
    ]) {
      if (!items.length) continue;
      const details = el("details");
      const content = el("div", "question-detail");
      for (const item of items)
        content.append(
          el("p", quote ? "quote" : "", quote ? `“${item}”` : `• ${item}`),
        );
      details.append(el("summary", "", `${label} (${items.length})`), content);
      card.append(details);
    }
    view.append(card);
  });

  const extra = el("div", "eval-columns");
  extra.style.marginTop = "22px";
  extra.append(
    list("Red flags", report.red_flags),
    list("Profile claims contradicted", report.profile_alignment.contradicted),
  );
  view.append(extra);
  const full = el("a", "button secondary compact", "Open full report");
  full.href = `/internal/report?session=${encodeURIComponent(report.session_id)}`;
  full.target = "_blank";
  full.rel = "noopener";
  const message = el("p", "note");
  message.style.marginTop = "12px";
  const actions = el("div", "candidate-actions");
  actions.style.padding = "0";
  actions.append(
    full,
    evaluateButton(
      report.session_id,
      "Evaluate again",
      message,
      "Run the evaluation again? This replaces the current report.",
    ),
  );
  view.append(actions, message);
  return view;
}

function questionsView(detail) {
  const view = el("div");
  if (!detail.questions) {
    view.append(el("p", "note", "The questions are still being written."));
    return view;
  }
  view.append(
    el(
      "p",
      "view-description",
      "Written for this candidate. Reference answers stay out of the voice interview.",
    ),
  );
  const cards = el("div");
  view.append(cards);
  detail.questions.forEach((question, index) => {
    const card = el("article", "question-card");
    const title = el("div", "question-title");
    title.append(
      el("span", "question-number", `0${index + 1}`),
      el("h3", "", question.question),
    );
    card.append(title);
    const sections = [
      ["Reference answer", question.answer],
      ["Codebase context", question.context],
    ];
    if (question.followup)
      sections.push([
        "Follow-up",
        `${question.followup.question}\n\nReference answer: ${question.followup.answer}`,
      ]);
    for (const [label, text] of sections) {
      const details = el("details");
      const content = el("div", "question-detail");
      content.append(el("p", "", text));
      details.append(el("summary", "", label), content);
      card.append(details);
    }
    cards.append(card);
  });
  return view;
}

function profileView(detail) {
  const view = el("div");
  const record = detail.record;
  const facts = el("p", "note");
  facts.append(`Role: ${record.role}. `);
  if (record.github_url) {
    const link = el("a", "", record.github_url.replace("https://", ""));
    link.href = record.github_url;
    link.target = "_blank";
    link.rel = "noopener";
    link.style.color = "var(--accent)";
    facts.append("GitHub: ", link, ". ");
  }
  if (record.cv_filename) facts.append("CV uploaded. ");
  facts.append(
    `Repository: ${record.repo_url.replace("https://github.com/", "")}${record.subdir ? ` / ${record.subdir}` : ""}.`,
  );
  view.append(facts);
  if (record.looking_for)
    view.append(el("p", "note", `Looking for: ${record.looking_for}`));
  for (const warning of record.warnings)
    view.append(el("p", "note warn", warning));
  view.append(
    detail.profile
      ? el("pre", "profile-text", detail.profile)
      : el("p", "note", "The profile is still being written."),
  );
  return view;
}

const TABS = [
  ["transcript", "Transcript", transcriptView],
  ["evaluation", "Evaluation", evaluationView],
  ["questions", "Interview questions", questionsView],
  ["profile", "Profile", profileView],
];

// --- rows ----------------------------------------------------------------------

function renderBody(summary, body) {
  const entry = state.get(summary.session_id);
  const detail = entry.detail;
  body.replaceChildren();
  if (!detail) {
    const loading = el("div", "result-view");
    loading.append(el("p", "note", entry.error || "Loading…"));
    body.append(loading);
    return;
  }
  const actions = el("div", "candidate-actions");
  if (summary.status === "failed") {
    actions.append(
      el("p", "note bad", `Preparation failed: ${summary.error || "unknown error"}.`),
    );
  } else if (summary.status === "preparing") {
    actions.append(el("p", "note", `${summary.stage || "Preparing"}…`));
  } else {
    actions.append(el("code", "", interviewUrl(summary)));
    const copy = el("button", "button secondary compact");
    copy.type = "button";
    copy.append(icon("copy"), "Copy interview link");
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(interviewUrl(summary));
        copy.replaceChildren(icon("check"), "Link copied");
        setTimeout(() => copy.replaceChildren(icon("copy"), "Copy interview link"), 2000);
      } catch {
        prompt("Copy the interview link:", interviewUrl(summary));
      }
    });
    actions.append(copy);
  }
  const tabs = el("div", "result-tabs");
  tabs.setAttribute("role", "tablist");
  const view = el("div", "result-view");
  const show = (name) => {
    entry.tab = name;
    for (const button of tabs.children)
      button.setAttribute("aria-selected", String(button.dataset.tab === name));
    view.replaceChildren(TABS.find(([key]) => key === name)[2](detail));
  };
  for (const [key, label] of TABS) {
    const button = el("button", "", label);
    button.type = "button";
    button.dataset.tab = key;
    button.setAttribute("role", "tab");
    button.addEventListener("click", () => show(key));
    tabs.append(button);
  }
  body.append(actions, tabs, view);
  // Default to the most useful tab for where the candidate is.
  const fallback = detail.transcript ? "transcript" : detail.questions ? "questions" : "profile";
  show(entry.tab || fallback);
}

async function loadDetail(summary, body) {
  const entry = state.get(summary.session_id);
  try {
    entry.detail = await getJson(
      `/api/candidates/${encodeURIComponent(summary.session_id)}`,
    );
    entry.error = null;
  } catch (error) {
    entry.error = error.message;
  }
  if (entry.open) renderBody(summary, body);
}

// What makes a row worth redrawing or its detail worth refetching.
const signature = (s) =>
  [s.status, s.stage, s.overall_score, s.duration_s, s.error].join("|");

function renderRow(summary) {
  const entry = state.get(summary.session_id) || { open: false, tab: null, detail: null };
  state.set(summary.session_id, entry);
  const changed = entry.signature !== signature(summary);
  entry.signature = signature(summary);

  const item = el("article", "candidate");
  item.dataset.id = summary.session_id;
  const row = el("button", "candidate-row");
  row.type = "button";
  row.setAttribute("aria-expanded", String(entry.open));
  const name = el("div", "candidate-name", `${summary.first_name} ${summary.last_name}`);
  name.append(el("small", "", summary.role));
  const when = el("div", "candidate-when");
  if (summary.interviewed_at) {
    when.textContent = day(summary.interviewed_at);
    when.append(
      el("small", "", summary.duration_s != null ? `${clock(summary.duration_s)} interview` : "Interview"),
    );
  } else {
    when.textContent = day(summary.created_at);
    when.append(el("small", "", "Added"));
  }
  const score = el("div", "candidate-score");
  if (summary.overall_score != null) {
    score.textContent = String(summary.overall_score);
    score.append(el("small", "", " / 100"));
  } else {
    score.classList.add("none");
    score.textContent = "No score yet";
  }
  row.append(
    el(
      "span",
      "candidate-avatar",
      `${summary.first_name[0] || ""}${summary.last_name[0] || ""}`.toUpperCase(),
    ),
    name,
    when,
    pill(summary.status),
    score,
    icon("chevron"),
  );
  const body = el("div", "candidate-body");
  body.hidden = !entry.open;
  row.addEventListener("click", () => {
    entry.open = !entry.open;
    row.setAttribute("aria-expanded", String(entry.open));
    body.hidden = !entry.open;
    if (entry.open) {
      renderBody(summary, body);
      loadDetail(summary, body);
    }
  });
  item.append(row, body);
  if (entry.open) {
    renderBody(summary, body);
    // Refetch when something changed, or while the interview is still running.
    if (changed || summary.status === "in_progress") loadDetail(summary, body);
  }
  return item;
}

async function refresh() {
  let summaries;
  try {
    summaries = await getJson("/api/candidates");
    $("list-error").hidden = true;
  } catch (error) {
    $("list-error").textContent = `Could not load candidates: ${error.message}`;
    $("list-error").hidden = false;
    return;
  }
  const count = (...statuses) =>
    summaries.filter((s) => statuses.includes(s.status)).length;
  $("count-badge").textContent = `${summaries.length} TOTAL`;
  $("stat-invited").textContent = String(count("invited", "preparing")).padStart(2, "0");
  $("stat-interviewed").textContent = String(
    count("in_progress", "interviewed", "advance", "reject"),
  ).padStart(2, "0");
  $("stat-advancing").textContent = String(count("advance")).padStart(2, "0");
  $("candidate-stats").hidden = summaries.length === 0;
  $("empty-list").hidden = summaries.length > 0;
  $("candidate-list").hidden = summaries.length === 0;

  // Leave the list alone unless something changed, so open rows and scroll position stay put.
  // A link from the Applicant's list names one candidate: open that row.
  const wanted = decodeURIComponent(location.hash.slice(1));
  const openWanted = wanted && !hashHandled && summaries.some((s) => s.session_id === wanted);
  if (openWanted)
    state.set(wanted, { ...(state.get(wanted) || { tab: null, detail: null }), open: true });

  const list = $("candidate-list");
  const next = summaries.map((s) => `${s.session_id}:${signature(s)}`).join(",");
  const running = summaries.some((s) => s.status === "in_progress" && state.get(s.session_id)?.open);
  if (list.dataset.signature === next && !running) return;
  list.dataset.signature = next;
  const scroll = window.scrollY;
  list.replaceChildren(...summaries.map(renderRow));
  window.scrollTo(0, scroll);
  if (openWanted) {
    hashHandled = true;
    list.querySelector(`[data-id="${CSS.escape(wanted)}"]`)?.scrollIntoView({ block: "start" });
  }
}

refresh();
setInterval(refresh, REFRESH_MS);
