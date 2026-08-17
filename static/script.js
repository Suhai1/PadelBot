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
// Previous rackets - optional, up to window.MAX_PREVIOUS_RACKETS slots,
// none of which exist in the markup until "+ Add a racket" is clicked.
//
// Consistent with the rest of this file: no slot state lives in a
// parallel JS object. Everything script.js needs to know about a slot
// - which racket was picked, the rating, the notes - is read straight
// back off the DOM at submit time. That's the same instinct behind
// budgetInput.value driving the whole budget flow: the DOM elements
// ARE the state, so there is nothing that can drift out of sync with
// what the player actually sees on screen.
// ---------------------------------------------------------------------------

const previousRacketSlotsContainer = document.getElementById("previous-racket-slots");
const addPreviousRacketButton = document.getElementById("add-previous-racket");
let nextSlotId = 0; // ever-incrementing, only used to keep radio group names unique - never reused, even after a slot is removed

function syncAddButtonVisibility() {
  const slotCount = previousRacketSlotsContainer.querySelectorAll(".previous-racket-slot").length;
  addPreviousRacketButton.disabled = slotCount >= window.MAX_PREVIOUS_RACKETS;
}

/**
 * Renumbers the visible "Racket 1" / "Racket 2" titles to match
 * current position, not creation order - otherwise removing the
 * first of two slots would leave a lone slot confusingly labelled
 * "Racket 2".
 */
function retitleSlots() {
  const slots = previousRacketSlotsContainer.querySelectorAll(".previous-racket-slot");
  slots.forEach((slot, index) => {
    slot.querySelector(".previous-racket-slot__title").textContent = `Racket ${index + 1}`;
  });
}

/**
 * The "which racket?" search widget. Filters window.RACKET_SEARCH_INDEX
 * (embedded in the page by app.py's index() route, from the real
 * catalogue) as the player types, entirely client-side - 521 rackets
 * is small enough that there's no need for this to hit the network.
 *
 * The selected racket's name lives in a hidden input inside the
 * returned element (class "previous-racket-slot__selected-name"),
 * queryable later without this function needing to hand back any kind
 * of accessor object.
 */
function buildRacketSearch() {
  const wrapper = document.createElement("div");
  wrapper.className = "racket-search";

  const selectedNameInput = document.createElement("input");
  selectedNameInput.type = "hidden";
  selectedNameInput.className = "previous-racket-slot__selected-name";

  const input = document.createElement("input");
  input.type = "text";
  input.className = "racket-search__input";
  input.placeholder = "Start typing a brand or racket name...";
  input.autocomplete = "off";

  const results = document.createElement("ul");
  results.className = "racket-search__results";

  function showSearchField() {
    const selectedRow = wrapper.querySelector(".racket-search__selected");
    if (selectedRow) selectedRow.remove();
    input.style.display = "";
    results.style.display = "";
    input.focus();
  }

  function showSelected(racket) {
    input.style.display = "none";
    results.textContent = "";
    results.style.display = "none";

    const selectedRow = document.createElement("div");
    selectedRow.className = "racket-search__selected";

    const label = document.createElement("span");
    label.textContent = `${racket.brand} - ${racket.name}`;

    const clearButton = document.createElement("button");
    clearButton.type = "button";
    clearButton.className = "racket-search__clear";
    clearButton.textContent = "Change";
    clearButton.addEventListener("click", () => {
      selectedNameInput.value = "";
      input.value = "";
      showSearchField();
    });

    selectedRow.append(label, clearButton);
    wrapper.append(selectedRow);
  }

  function selectRacket(racket) {
    selectedNameInput.value = racket.name;
    showSelected(racket);
  }

  function renderResults(query) {
    results.textContent = "";
    const trimmed = query.trim();
    if (!trimmed) return;

    const lowerQuery = trimmed.toLowerCase();
    const matches = window.RACKET_SEARCH_INDEX.filter((racket) =>
      `${racket.brand} ${racket.name}`.toLowerCase().includes(lowerQuery)
    ).slice(0, 8);

    if (matches.length === 0) {
      const empty = document.createElement("li");
      empty.className = "racket-search__result";
      empty.textContent = "No match in our catalogue - fine to skip this one.";
      results.append(empty);
      return;
    }

    matches.forEach((racket) => {
      const item = document.createElement("li");
      item.className = "racket-search__result";
      item.tabIndex = 0;

      const nameSpan = document.createElement("span");
      nameSpan.textContent = `${racket.brand} - ${racket.name} `;
      const priceSpan = document.createElement("span");
      priceSpan.className = "racket-search__result-price";
      priceSpan.textContent = formatRand(racket.price_zar);
      item.append(nameSpan, priceSpan);

      item.addEventListener("click", () => selectRacket(racket));
      item.addEventListener("keydown", (event) => {
        if (event.key === "Enter") selectRacket(racket);
      });

      results.append(item);
    });
  }

  input.addEventListener("input", () => renderResults(input.value));

  wrapper.append(selectedNameInput, input, results);
  return wrapper;
}

/**
 * A row of toggle-style buttons backed by real radio inputs (see the
 * CSS - the inputs are visually hidden, not display:none, so this
 * stays keyboard- and screen-reader-navigable). groupName must be
 * unique across the whole page, or two slots' radio groups would
 * fight over the same selection.
 */
function buildRatingGroup(groupName) {
  const group = document.createElement("div");
  group.className = "rating-group";

  // "fine" is the neutral default the moment a slot exists, not
  // something that waits for a racket to be picked first - simpler
  // than coordinating between two separate widgets, and there's
  // always a sensible value to read back even if the player never
  // touches this control.
  const defaultRating = window.RATING_OPTIONS.includes("fine") ? "fine" : window.RATING_OPTIONS[0];

  window.RATING_OPTIONS.forEach((rating) => {
    const inputId = `${groupName}-${rating}`;

    const input = document.createElement("input");
    input.type = "radio";
    input.name = groupName;
    input.id = inputId;
    input.value = rating;
    if (rating === defaultRating) {
      input.checked = true;
    }

    const label = document.createElement("label");
    label.htmlFor = inputId;
    label.textContent = rating.charAt(0).toUpperCase() + rating.slice(1);

    group.append(input, label);
  });

  return group;
}

function buildPreviousRacketSlot() {
  nextSlotId += 1;

  const slot = document.createElement("div");
  slot.className = "previous-racket-slot";

  const header = document.createElement("div");
  header.className = "previous-racket-slot__header";

  const title = document.createElement("span");
  title.className = "previous-racket-slot__title"; // text set by retitleSlots() once this is in the DOM

  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.className = "previous-racket-slot__remove";
  removeButton.textContent = "Remove";
  removeButton.addEventListener("click", () => {
    slot.remove();
    retitleSlots();
    syncAddButtonVisibility();
  });

  header.append(title, removeButton);

  const searchField = document.createElement("div");
  searchField.className = "field";
  const searchLabel = document.createElement("label");
  searchLabel.textContent = "Which racket?";
  searchField.append(searchLabel, buildRacketSearch());

  const ratingField = document.createElement("div");
  ratingField.className = "field";
  const ratingLabel = document.createElement("label");
  ratingLabel.textContent = "How did you feel about it?";
  ratingField.append(ratingLabel, buildRatingGroup(`previous-racket-rating-${nextSlotId}`));

  const notesField = document.createElement("div");
  notesField.className = "field";
  const notesLabel = document.createElement("label");
  notesLabel.textContent = "What did you like or not like about it? (optional)";

  const notesMaxLength = 500; // must match app.py's MAX_NOTES_LENGTH
  const notes = document.createElement("textarea");
  notes.className = "previous-racket-slot__notes";
  notes.maxLength = notesMaxLength;

  const notesCount = document.createElement("p");
  notesCount.className = "previous-racket-slot__notes-count";
  notesCount.textContent = `0/${notesMaxLength}`;
  notes.addEventListener("input", () => {
    notesCount.textContent = `${notes.value.length}/${notesMaxLength}`;
  });

  notesField.append(notesLabel, notes, notesCount);

  slot.append(header, searchField, ratingField, notesField);
  return slot;
}

addPreviousRacketButton.addEventListener("click", () => {
  previousRacketSlotsContainer.append(buildPreviousRacketSlot());
  retitleSlots();
  syncAddButtonVisibility();
});

/**
 * Reads previous-racket data straight off the DOM. A slot with no
 * racket selected is skipped entirely, not sent as a half-empty entry
 * - the search widget always has a rating default, so "no racket
 * chosen" is the only way a slot can be genuinely incomplete.
 */
function collectPreviousRackets() {
  const slots = previousRacketSlotsContainer.querySelectorAll(".previous-racket-slot");
  const previousRackets = [];

  slots.forEach((slot) => {
    const name = slot.querySelector(".previous-racket-slot__selected-name").value;
    if (!name) return;

    const checkedRating = slot.querySelector(".rating-group input[type='radio']:checked");
    const notes = slot.querySelector(".previous-racket-slot__notes").value.trim();

    const entry = { name: name, rating: checkedRating ? checkedRating.value : window.RATING_OPTIONS[0] };
    if (notes) {
      entry.notes = notes;
    }
    previousRackets.push(entry);
  });

  return previousRackets;
}

// ---------------------------------------------------------------------------
// Form submission
// ---------------------------------------------------------------------------

function collectProfile() {
  const formData = new FormData(form);
  const profile = {
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

  const previousRackets = collectPreviousRackets();
  if (previousRackets.length > 0) {
    profile.previous_rackets = previousRackets;
  }

  return profile;
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
