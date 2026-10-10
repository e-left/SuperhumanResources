"use strict";

const $ = (id) => document.getElementById(id);
const form = $("context-form");
let context = null;
let candidate = null; // the candidate this context was prepared for, if any
let sample = false;
let busy = false;
let timer = null;
const REQUEST_TIMEOUT = 180_000; // Clone (60s) + Gemini (90s), with response overhead.

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function sourceTags(files) {
  const tags = el("div", "source-tags");
  for (const file of files) tags.append(el("span", "", file));
  return tags;
}

function validateContext(value, sessionId) {
  const strings = (items) =>
    Array.isArray(items) && items.every((item) => typeof item === "string");
  const sourced = (item) => item && strings(item.source_files);
  if (
    !value ||
    value.session_id !== sessionId ||
    typeof value.summary !== "string" ||
    typeof value.role !== "string" ||
    !(value.repo_url === null || typeof value.repo_url === "string") ||
    !strings(value.included_files) ||
    !strings(value.omitted_files) ||
    !Array.isArray(value.technologies) ||
    !value.technologies.every(
      (t) =>
        sourced(t) && typeof t.name === "string" && typeof t.usage === "string",
    ) ||
    !Array.isArray(value.project_areas) ||
    !value.project_areas.every(
      (a) =>
        sourced(a) &&
        typeof a.name === "string" &&
        typeof a.description === "string" &&
        strings(a.optimization_topics),
    ) ||
    !Array.isArray(value.questions) ||
    value.questions.length !== 3 ||
    !value.questions.every(
      (q) =>
        sourced(q) &&
        ["question", "answer", "context"].every(
          (key) => typeof q[key] === "string",
        ),
    )
  ) {
    throw new Error(
      "The server returned incomplete context. Please generate a new analysis.",
    );
  }
  return value;
}

async function request(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error(
        `The server returned an unreadable response (${response.status}). Check the server and try again.`,
      );
    }
    if (!response.ok) {
      const detail =
        typeof data.detail === "string"
          ? data.detail
          : `Request failed (${response.status}). Check the repository URL and try again.`;
      throw new Error(detail);
    }
    return data;
  } catch (error) {
    if (error.name === "AbortError")
      throw new Error(
        "The request timed out. Analysis may still finish on the server; check server logs before trying again.",
      );
    if (error instanceof TypeError)
      throw new Error(
        "Could not reach the server. Check your connection and try again.",
      );
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function setAgent(state, title, description, status) {
  $("agent-panel").className = `panel agent-panel ${state}`;
  $("agent-title").textContent = title;
  $("agent-description").textContent = description;
  $("agent-state").replaceChildren(
    el("span", "status-dot"),
    document.createTextNode(
      state === "running"
        ? "Agent working"
        : state === "complete"
          ? "Context ready"
          : state === "failed"
            ? "Needs attention"
            : "Ready when you are",
    ),
  );
  $("agent-status-text").textContent = status;
}

function setBusy(value) {
  busy = value;
  for (const field of form.elements) field.disabled = value;
  $("preview-button").disabled = value;
  $("example-button").disabled = value;
  $("agent-panel").setAttribute("aria-busy", String(value));
  $("analyze-button").querySelector("span").textContent = value
    ? "Preparing interview…"
    : "Prepare interview";
  clearInterval(timer);
  $("elapsed").textContent = "";
  if (value) {
    const started = Date.now();
    timer = setInterval(() => {
      $("elapsed").textContent =
        `${Math.floor((Date.now() - started) / 1000)}s`;
    }, 1000);
  }
}

function showError(error) {
  $("form-error").textContent = error.message;
  $("form-error").hidden = false;
  setAgent(
    "failed",
    "Let’s reconnect.",
    "We couldn’t complete this request. Your repository settings are still here.",
    "Analysis unsuccessful. Review the message beside the form.",
  );
}

function selectTab(name, focus = false) {
  for (const tab of document.querySelectorAll('[role="tab"]')) {
    const selected = tab.dataset.tab === name;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    $(`view-${tab.dataset.tab}`).hidden = !selected;
    if (selected && focus) tab.focus();
  }
}

function render(data, isSample = false) {
  context = data;
  sample = isSample;
  $("empty-output").hidden = true;
  $("results").hidden = false;
  $("results").classList.remove("animate-in");
  requestAnimationFrame(() => $("results").classList.add("animate-in"));
  $("output-actions").hidden = false;
  $("copy-button").hidden = isSample;
  $("output-badge").textContent = isSample ? "SAMPLE PREVIEW" : "CONTEXT READY";
  $("output-subtitle").textContent = isSample
    ? "Illustrative FlatPal context. This preview does not run the agent or create a session."
    : "Source-grounded context, saved and ready for your agents.";
  $("result-repository").textContent =
    (data.repo_url
      ? data.repo_url.replace("https://github.com/", "")
      : "Local repository") + (data.subdir ? ` / ${data.subdir}` : "");
  $("result-role").textContent = data.role;
  $("result-summary").textContent = data.summary;
  $("stat-files").textContent = String(data.included_files.length).padStart(
    2,
    "0",
  );
  $("stat-tech").textContent = String(data.technologies.length).padStart(
    2,
    "0",
  );
  $("technology-list").replaceChildren(
    ...data.technologies.map((tech) => {
      const card = el("article", "technology-card");
      card.append(
        el("h4", "", tech.name),
        el("p", "", tech.usage),
        sourceTags(tech.source_files),
      );
      return card;
    }),
  );
  $("area-list").replaceChildren(
    ...data.project_areas.map((area) => {
      const card = el("article", "area-card");
      const topics = el("ul", "topic-list");
      topics.append(
        ...area.optimization_topics.map((topic) => el("li", "", topic)),
      );
      card.append(
        el("h4", "", area.name),
        el("p", "", area.description),
        topics,
        sourceTags(area.source_files),
      );
      return card;
    }),
  );
  $("question-list").replaceChildren(
    ...data.questions.map((question, index) => {
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
        if (label === "Codebase context")
          content.append(sourceTags(question.source_files));
        details.append(el("summary", "", label), content);
        card.append(details);
      }
      return card;
    }),
  );
  $("included-list").replaceChildren(
    ...data.included_files.map((file) => el("li", "", file)),
  );
  $("omitted-list").replaceChildren(
    ...(data.omitted_files.length
      ? data.omitted_files.map((file) => el("li", "", file))
      : [el("li", "", "No budget omissions were reported.")]),
  );
  $("interview-link").hidden = isSample;
  if (!isSample)
    $("interview-link").href =
      `/?session=${encodeURIComponent(data.session_id)}`;
  $("handoff-note").replaceChildren();
  $("copy-link-button").hidden = isSample || !candidate;
  $("candidates-link").hidden = isSample || !candidate;
  if (isSample)
    $("handoff-note").textContent =
      "Prepare an interview from a public repository to create a candidate link.";
  else if (candidate) {
    document.querySelector("#handoff h3").textContent =
      `${candidate.first_name} ${candidate.last_name}’s interview is ready.`;
    $("handoff-note").append(
      document.createTextNode("Their personal link: "),
      el("code", "", interviewUrl(data.session_id)),
    );
  } else
    $("handoff-note").append(
      document.createTextNode("Before starting, add the candidate profile to "),
      el("code", "", `data/${data.session_id}/candidate.md`),
      document.createTextNode("."),
    );
  selectTab("context");
  setAgent(
    "complete",
    isSample ? "A glimpse of the signal." : "Your code. Understood.",
    isSample
      ? "Explore the kind of context your agents can share. Generate an analysis for actual repository results."
      : `${data.technologies.length} technologies. ${data.project_areas.length} project areas. Three questions grounded in your code.`,
    isSample
      ? "Sample preview · no agent run or session created."
      : `Analysis saved · ${data.included_files.length} source files included.`,
  );
}

function interviewUrl(sessionId) {
  return `${location.origin}/?session=${encodeURIComponent(sessionId)}`;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Poll until the candidate's profile and questions are written.
async function waitUntilPrepared(sessionId) {
  for (;;) {
    const detail = await request(
      `/api/candidates/${encodeURIComponent(sessionId)}`,
    );
    const { status, stage, error } = detail.summary;
    if (status === "failed")
      throw new Error(error || "The interview could not be prepared.");
    if (status !== "preparing") return detail;
    if (stage) $("agent-status-text").textContent = `${stage}…`;
    await sleep(2000);
  }
}

function remember(key, value) {
  const url = new URL(location.href);
  url.searchParams.delete("context");
  url.searchParams.delete("sample");
  // A pre-fill from the Applicant's list has done its job once a session exists.
  for (const name of ["first_name", "last_name", "github"])
    url.searchParams.delete(name);
  url.searchParams.set(key, value);
  history.replaceState(null, "", url);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  $("form-error").hidden = true;
  const repo_url = $("repo-url").value.trim();
  const role = $("role").value.trim();
  const subdir = $("subdir").value.trim();
  const firstName = $("first-name").value.trim();
  const lastName = $("last-name").value.trim();
  const githubProfile = $("github-profile").value.trim();
  const cvFile = $("cv-file").files[0];
  for (const [field, value, message] of [
    ["first-name", firstName, "Enter the candidate’s first name."],
    ["last-name", lastName, "Enter the candidate’s last name."],
  ]) {
    if (!value) {
      $(field).setCustomValidity(message);
      $(field).reportValidity();
      return;
    }
  }
  if (
    !/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/?$/.test(
      repo_url,
    )
  ) {
    $("repo-url").setCustomValidity(
      "Enter a public GitHub repository URL, such as https://github.com/team/repository.",
    );
    $("repo-url").reportValidity();
    return;
  }
  if (!role) {
    $("role").setCustomValidity("Enter the role you are hiring for.");
    $("role").reportValidity();
    return;
  }
  // Read the form before disabling it: disabled fields are left out of FormData.
  const body = new FormData();
  body.set("first_name", firstName);
  body.set("last_name", lastName);
  body.set("role", role);
  body.set("looking_for", $("looking-for").value.trim());
  body.set("repo_url", repo_url);
  body.set("subdir", subdir);
  body.set("github_profile", githubProfile);
  if (cvFile) body.set("cv_file", cvFile);
  setBusy(true);
  context = null;
  candidate = null;
  $("results").hidden = true;
  $("output-actions").hidden = true;
  $("empty-output").hidden = false;
  $("output-badge").textContent = "AGENT WORKING";
  $("output-subtitle").textContent =
    "Building a new foundation from your candidate and your repository.";
  setAgent(
    "running",
    "Finding your signal.",
    "Reading the candidate’s profile and your source files, then writing questions for them. This can take a minute or two.",
    "Interview requested · waiting for the agents.",
  );
  try {
    const created = await request("/api/candidates", { method: "POST", body });
    if (
      !created ||
      typeof created.session_id !== "string" ||
      !/^[a-f0-9]{32}$/.test(created.session_id)
    )
      throw new Error("The server did not return a valid candidate session.");
    // Remember the session before waiting, so a refresh can pick it up again.
    remember("context", created.session_id);
    const detail = await waitUntilPrepared(created.session_id);
    candidate = detail.record;
    const data = validateContext(detail.context, created.session_id);
    render(data);
    $("output-title").tabIndex = -1;
    $("output-title").focus({ preventScroll: true });
    $("output-section").scrollIntoView({
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
      block: "start",
    });
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
});

for (const field of [
  $("repo-url"),
  $("role"),
  $("first-name"),
  $("last-name"),
  $("github-profile"),
])
  field.addEventListener("input", () => field.setCustomValidity(""));
$("cv-file").addEventListener("change", () =>
  $("github-profile").setCustomValidity(""),
);

$("copy-link-button").addEventListener("click", async () => {
  if (!context || sample) return;
  const link = interviewUrl(context.session_id);
  try {
    await navigator.clipboard.writeText(link);
    $("copy-link-button").replaceChildren(
      icon("check"),
      document.createTextNode("Link copied"),
    );
    setTimeout(
      () =>
        $("copy-link-button").replaceChildren(
          icon("copy"),
          document.createTextNode("Copy interview link"),
        ),
      2000,
    );
  } catch {
    $("form-error").textContent = `Clipboard unavailable. Link: ${link}`;
    $("form-error").hidden = false;
  }
});
$("example-button").addEventListener("click", () => {
  $("repo-url").value = "https://github.com/e-left/SuperhumanResources";
  $("subdir").value = "demo-proj";
  $("role").value = "Backend Engineer";
  $("repo-url").setCustomValidity("");
  $("role").setCustomValidity("");
  $("form-error").hidden = true;
  $("repo-url").focus();
});

const sampleContext = {
  session_id: "sample",
  repo_url: "https://github.com/e-left/SuperhumanResources",
  subdir: "demo-proj",
  role: "Backend Engineer",
  summary:
    "FlatPal brings a shared household into one place: expenses, chores, shopping, and the conversations around them. A TypeScript API and relational data model connect a web client and a mobile experience.",
  included_files: [
    "api/package.json",
    "api/prisma/schema.prisma",
    "package.json",
    "mobile/package.json",
  ],
  omitted_files: [],
  technologies: [
    {
      name: "TypeScript",
      usage: "A shared language across the API and client applications.",
      source_files: ["api/package.json", "package.json"],
    },
    {
      name: "Prisma",
      usage: "Relational models for households and shared responsibilities.",
      source_files: ["api/prisma/schema.prisma"],
    },
    {
      name: "React Native",
      usage: "Mobile access to the household workspace.",
      source_files: ["mobile/package.json"],
    },
  ],
  project_areas: [
    {
      name: "Shared household data",
      description:
        "Connected members, expenses, and household resources need clear ownership and consistent updates.",
      optimization_topics: [
        "Prevent duplicate writes with idempotent operations",
        "Enforce household access at the API boundary",
      ],
      source_files: ["api/prisma/schema.prisma"],
    },
    {
      name: "API and client coordination",
      description:
        "Web and mobile clients share a backend while working with different connectivity and interaction patterns.",
      optimization_topics: [
        "Keep client and API contracts compatible",
        "Handle failed requests without losing user changes",
      ],
      source_files: ["api/package.json", "mobile/package.json"],
    },
  ],
  questions: [
    {
      question:
        "How would you design an expense-sharing feature so retries cannot create duplicate charges or records?",
      answer:
        "Define an idempotency key for each logical operation, enforce uniqueness in storage, and commit the expense and its allocations atomically. Return the prior result for safe retries and test concurrent submissions.",
      context:
        "Illustrative question inspired by a shared household application and its relational data model.",
      source_files: ["api/prisma/schema.prisma"],
    },
    {
      question:
        "How would you make sure a member can only read and change data belonging to their household?",
      answer:
        "Authenticate the caller and check household membership for each operation at the API boundary. Scope reads and writes to an authorized household and test cross-household access attempts.",
      context:
        "Illustrative access-control discussion for an API serving multiple households.",
      source_files: ["api/prisma/schema.prisma", "api/package.json"],
    },
    {
      question:
        "How would you evolve an API used by both web and mobile clients without breaking older app versions?",
      answer:
        "Prefer additive changes, preserve existing field meanings, and use contract tests. Observe client versions before removing old behavior, and roll out incompatible changes through an explicit versioning plan.",
      context:
        "Illustrative compatibility discussion for a backend shared by independently released clients.",
      source_files: ["api/package.json", "mobile/package.json"],
    },
  ],
};

$("preview-button").addEventListener("click", () => {
  $("form-error").hidden = true;
  render(sampleContext, true);
  remember("sample", "1");
  $("output-section").scrollIntoView({
    behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "instant"
      : "smooth",
  });
});

for (const tab of document.querySelectorAll('[role="tab"]')) {
  tab.addEventListener("click", () => selectTab(tab.dataset.tab));
  tab.addEventListener("keydown", (event) => {
    const tabs = [...document.querySelectorAll('[role="tab"]')];
    const current = tabs.indexOf(tab);
    let next;
    if (event.key === "ArrowRight") next = (current + 1) % tabs.length;
    if (event.key === "ArrowLeft")
      next = (current - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    if (next !== undefined) {
      event.preventDefault();
      selectTab(tabs[next].dataset.tab, true);
    }
  });
}

$("copy-button").addEventListener("click", async () => {
  if (!context || sample) return;
  try {
    await navigator.clipboard.writeText(context.session_id);
    $("copy-button").replaceChildren(
      icon("check"),
      document.createTextNode("Session copied"),
    );
    setTimeout(
      () =>
        $("copy-button").replaceChildren(
          icon("copy"),
          document.createTextNode("Copy session"),
        ),
      2000,
    );
  } catch {
    $("form-error").textContent =
      `Clipboard unavailable. Session ID: ${context.session_id}`;
    $("form-error").hidden = false;
  }
});

$("download-button").addEventListener("click", () => {
  if (!context) return;
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(context, null, 2) + "\n"], {
      type: "application/json",
    }),
  );
  const link = el("a");
  link.href = url;
  link.download = sample
    ? "sample-context.json"
    : `context-${context.session_id}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

async function restore() {
  const params = new URLSearchParams(location.search);
  const sessionId = params.get("context");
  if (params.get("sample") === "1") {
    render(sampleContext, true);
    return;
  }
  if (!sessionId) {
    // Arriving from the Applicant's list: fill in who the interview is for.
    // Nothing is submitted, and every field stays editable.
    const prefill = [
      ["first_name", "first-name"],
      ["last_name", "last-name"],
      ["github", "github-profile"],
    ].filter(([name]) => params.get(name));
    for (const [name, field] of prefill)
      $(field).value = params.get(name).slice(0, 200);
    if (prefill.length) $("repo-url").focus();
    return;
  }
  if (!/^[a-f0-9]{32}$/.test(sessionId)) {
    showError(
      new Error(
        "This context link contains an invalid session ID. Generate a new analysis.",
      ),
    );
    return;
  }
  setBusy(true);
  setAgent(
    "running",
    "Reconnecting your context.",
    "Loading the saved analysis for this session.",
    "Retrieving saved codebase context.",
  );
  try {
    let data;
    try {
      // A candidate session: wait if it is still being prepared.
      const detail = await waitUntilPrepared(sessionId);
      candidate = detail.record;
      $("first-name").value = candidate.first_name;
      $("last-name").value = candidate.last_name;
      $("github-profile").value = candidate.github_url || "";
      $("looking-for").value = candidate.looking_for || "";
      data = validateContext(detail.context, sessionId);
    } catch (error) {
      if (candidate) throw error;
      // Not a candidate: a context created with the analysis route alone.
      data = validateContext(
        await request(`/sessions/${encodeURIComponent(sessionId)}/context`),
        sessionId,
      );
    }
    $("repo-url").value = data.repo_url || "";
    $("role").value = data.role;
    $("subdir").value = data.subdir || "";
    render(data);
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
}
restore();
