/*
  script.js - everything that happens after the page has loaded: keep
  the budget slider's live number in sync, collect the form into a
  player profile, send it to POST /api/recommend, and render whatever
  comes back - a loading state, an error, a "nothing suits you" note,
  or up to three racket cards.

  No framework, no build step. Every DOM element below is built with
  document.createElement() and .textContent rather than innerHTML with
  a template string - deliberately, not out of habit: pick.why and
  pick.tradeoff are text written by an AI model, not something this
  codebase fully controls. .textContent always inserts its argument as
  plain text, never as HTML, so even if a response somehow contained
  something that looked like a <script> tag, it would render on the
  page as the literal characters "<script>", not execute. innerHTML
  would not give us that guarantee for free.
*/

// Grabbing every element we'll touch once, up front, rather than
// re-querying the DOM every time a function runs.
const form = document.getElementById("profile-form");
const budgetInput = document.getElementById("budget");
const budgetValueOutput = document.getElementById("budget-value");
const submitButton = document.getElementById("submit-button");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

// ---------------------------------------------------------------------------
// Rand formatting
// ---------------------------------------------------------------------------

/**
 * Turns a plain number like 4000 into "R4,000".
 *
 * Deliberately hand-rolled instead of using the browser's built-in
 * Intl.NumberFormat("en-ZA", {style: "currency", ...}) - that API is
 * real and works, but exactly how it formats ZAR (comma vs space as
 * the thousands separator, "R" vs "ZAR" as the symbol) can differ
 * between browsers depending on their bundled locale data. Writing the
 * grouping ourselves means this looks identical everywhere, which
 * matters more here than saving a few lines.
 */
function formatRand(amount) {
  const digits = String(Math.round(amount));
  let withCommas = "";

  for (let i = 0; i < digits.length; i++) {
    // How many digits are left AFTER this one, counting this one.
    // e.g. for "4000", at i=0 (the "4") there are 4 digits left
    // including itself - that's the position we use to decide whether
    // a comma belongs right after it.
    const digitsRemaining = digits.length - i;
    withCommas += digits[i];

    const isNotTheLastDigit = digitsRemaining > 1;
    const isEveryThirdPosition = (digitsRemaining - 1) % 3 === 0;
    if (isNotTheLastDigit && isEveryThirdPosition) {
      withCommas += ",";
    }
  }

  return `R${withCommas}`;
}

// ---------------------------------------------------------------------------
// Budget slider
// ---------------------------------------------------------------------------

function updateBudgetDisplay() {
  budgetValueOutput.textContent = formatRand(budgetInput.value);
}

// "input" fires continuously while dragging, not just on release - the
// number updates live as you move the slider.
budgetInput.addEventListener("input", updateBudgetDisplay);
updateBudgetDisplay(); // set the correct starting text on page load

// ---------------------------------------------------------------------------
// Status area: loading / error messages. Only one of these is ever
// shown at a time, and clearStatus() is what removes whichever is
// currently there before the next state starts.
// ---------------------------------------------------------------------------

function clearStatus() {
  statusEl.textContent = "";
  statusEl.className = "status";
}

function showLoading() {
  statusEl.textContent = "Thinking about your game...";
  statusEl.className = "status status--loading";
}

function showError(message) {
  statusEl.textContent = message;
  statusEl.className = "status status--error";
}

// ---------------------------------------------------------------------------
// Results area
// ---------------------------------------------------------------------------

function clearResults() {
  resultsEl.textContent = "";
}

/**
 * Builds one racket card as real DOM nodes - see the file header for
 * why this doesn't use innerHTML anywhere.
 */
function buildCard(pick) {
  const card = document.createElement("article");
  card.className = "racket-card";

  const header = document.createElement("div");
  header.className = "racket-card__header";

  const name = document.createElement("h3");
  name.className = "racket-card__name";
  name.textContent = pick.name;

  const price = document.createElement("span");
  price.className = "racket-card__price";
  price.textContent = formatRand(pick.price_zar);

  header.append(name, price);

  const meta = document.createElement("p");
  meta.className = "racket-card__meta";
  const shapeText = pick.shape ? pick.shape : "shape not confirmed";
  meta.textContent = `${pick.brand} · ${shapeText}`;

  const why = document.createElement("p");
  why.className = "racket-card__why";
  why.textContent = pick.why;

  const tradeoff = document.createElement("p");
  tradeoff.className = "racket-card__tradeoff";
  const tradeoffLabel = document.createElement("span");
  tradeoffLabel.className = "racket-card__tradeoff-label";
  tradeoffLabel.textContent = "Trade-off: ";
  tradeoff.append(tradeoffLabel, document.createTextNode(pick.tradeoff));

  card.append(header, meta, why, tradeoff);

  // Only add a store link if the URL genuinely looks like a web
  // address. pick.url comes from our own catalogue data, not from the
  // AI, so this isn't really guarding against an attack today - but an
  // <a href> is one of the few places a stray "javascript:" string
  // would actually do something if it ever got this far, so checking
  // costs nothing and closes that door for good.
  if (pick.url && (pick.url.startsWith("http://") || pick.url.startsWith("https://"))) {
    const link = document.createElement("a");
    link.className = "racket-card__link";
    link.href = pick.url;
    link.target = "_blank";
    // rel="noopener noreferrer": without this, a page opened via
    // target="_blank" can use window.opener to reach back into THIS
    // tab - a real, if obscure, way a linked-to site could redirect
    // your original tab somewhere unexpected.
    link.rel = "noopener noreferrer";
    link.textContent = "View at store →";
    card.append(link);
  }

  return card;
}

/**
 * Renders whatever the API gave us: a note (if present), then between
 * zero and three cards. Handles all three shapes explicitly - full
 * results, partial results, and no results - rather than assuming
 * there will always be exactly three, which the backend deliberately
 * never guarantees (see PRODUCT.md: "never pad with poor matches").
 */
function renderResults(data) {
  const picks = data.picks || [];

  if (data.note) {
    const note = document.createElement("p");
    note.className = "results-note";
    note.textContent = data.note;
    resultsEl.append(note);
  }

  if (picks.length === 0) {
    if (!data.note) {
      // Belt and braces - both places that can produce an empty picks
      // list on the backend already attach a note explaining why, so
      // this should be unreachable in practice. Still handled, so the
      // page never just goes silent if that ever changes.
      const fallback = document.createElement("p");
      fallback.className = "results-note";
      fallback.textContent = "No rackets matched this profile. Try a different budget or preferences.";
      resultsEl.append(fallback);
    }
    return;
  }

  if (picks.length < 3) {
    const count = document.createElement("p");
    count.className = "results-count";
    const plural = picks.length === 1 ? "match" : "matches";
    count.textContent = `Showing ${picks.length} genuine ${plural} - not padded to three.`;
    resultsEl.append(count);
  }

  picks.forEach((pick) => resultsEl.append(buildCard(pick)));
}

// ---------------------------------------------------------------------------
// Form submission
// ---------------------------------------------------------------------------

function collectProfile() {
  const formData = new FormData(form);
  return {
    level: formData.get("level"),
    side: formData.get("side"),
    style: formData.get("style"),
    // FormData reads every field as a string, including the range
    // input's value - Number() converts "4000" to the actual number
    // 4000 the way app.py's validator expects.
    budget_max: Number(formData.get("budget_max")),
    // A checkbox's FormData entry only exists at all when it's ticked
    // - there's no separate "false" value to read. form.elements looks
    // up the actual <input> and asks it directly instead.
    arm_issues: form.elements["arm-issues"].checked,
    frequency: formData.get("frequency"),
  };
}

async function handleSubmit(event) {
  event.preventDefault();

  clearStatus();
  clearResults();
  showLoading();
  submitButton.disabled = true;

  try {
    const response = await fetch("/api/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectProfile()),
    });

    // .catch(() => null): if the response body isn't valid JSON for
    // some reason, treat it the same as "no data" rather than letting
    // that exception escape and skip the error handling below.
    const data = await response.json().catch(() => null);

    if (!response.ok) {
      const message = data && data.error ? data.error : `Request failed (status ${response.status}).`;
      showError(message);
      return;
    }

    if (!data) {
      showError("Received an unexpected response from the server.");
      return;
    }

    clearStatus();
    renderResults(data);
  } catch (networkError) {
    // fetch() only throws for network-level failures - server
    // unreachable, no connection, request blocked - never for a normal
    // HTTP error response, which is handled by the !response.ok branch
    // above instead.
    showError("Could not reach the server. Check your connection and try again.");
  } finally {
    submitButton.disabled = false;
  }
}

form.addEventListener("submit", handleSubmit);
