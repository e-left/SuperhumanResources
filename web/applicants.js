"use strict";

// Adds an "Interview" column to the applicants table: prepare an interview for
// an applicant, or see how far the one they already have has got.
const STATUS = {
  preparing: "Preparing",
  failed: "Failed",
  invited: "Invited",
  in_progress: "In interview",
  interviewed: "Evaluating",
  advance: "Advance",
  reject: "Reject",
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const key = (first, last) => `${first} ${last}`.trim().toLowerCase();

async function candidatesByName() {
  const found = new Map();
  try {
    const response = await fetch("/api/candidates");
    if (!response.ok) return found;
    // The list is newest first: keep the first one seen for each name.
    for (const candidate of await response.json()) {
      const name = key(candidate.first_name, candidate.last_name);
      if (!found.has(name)) found.set(name, candidate);
    }
  } catch {
    // Without the API every row simply offers "Prepare interview".
  }
  return found;
}

function interviewCell(row, candidates) {
  const cells = row.querySelectorAll("td");
  const first = cells[0].textContent.trim();
  const last = cells[1].textContent.trim();
  const cell = el("td", "applicant-interview");
  const candidate = candidates.get(key(first, last));
  if (candidate) {
    const pill = el("span", `pill ${candidate.status}`);
    pill.append(el("span", "status-dot"), STATUS[candidate.status] || candidate.status);
    const view = el("a", "applicant-action", "View");
    view.href = `/candidates#${encodeURIComponent(candidate.session_id)}`;
    cell.append(pill, view);
    return cell;
  }
  const params = new URLSearchParams({ first_name: first, last_name: last });
  // Only a real profile link is passed on; the demo handles are placeholders.
  const github = row.querySelector('a[href^="https://github.com/"]');
  if (github) params.set("github", github.href);
  const prepare = el("a", "applicant-action", "Prepare interview →");
  prepare.href = `/?${params}`;
  cell.append(prepare);
  return cell;
}

async function addInterviewColumn() {
  const table = document.querySelector(".applicants-table");
  if (!table) return;
  const candidates = await candidatesByName();
  const heading = el("th", "", "Interview");
  heading.scope = "col";
  table.querySelector("thead tr").append(heading);
  for (const row of table.querySelectorAll("tbody tr"))
    row.append(interviewCell(row, candidates));
}

addInterviewColumn();
