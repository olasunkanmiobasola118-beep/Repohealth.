"use strict";

/*
  RepoHealth front-end logic.
  Part B: validate the repository URL and show empty, loading, and error states.
*/

// Matches https://github.com/owner/repo, with an optional ".git" and optional trailing "/".
// Group 1 = owner, group 2 = repository name.
const REPO_URL_PATTERN =
  /^https:\/\/(?:www\.)?github\.com\/([A-Za-z0-9][A-Za-z0-9-]{0,38})\/([A-Za-z0-9._-]{1,100}?)(?:\.git)?\/?$/;

const SCAN_TIMEOUT_MS = 30000; // give up after 30 seconds

// ----- Grab the page elements we need -----
const form = document.getElementById("scan-form");
const input = document.getElementById("repo-url");
const feedback = document.getElementById("repo-url-feedback");
const scanButton = document.getElementById("scan-button");
const loadingRepo = document.getElementById("loading-repo");
const errorMessage = document.getElementById("error-message");

const panels = {
  empty: document.getElementById("state-empty"),
  loading: document.getElementById("state-loading"),
  error: document.getElementById("state-error"),
};

// First-load motion is presentational and never delays interaction.
if (
  window.gsap &&
  !window.matchMedia("(prefers-reduced-motion: reduce)").matches
) {
  const intro = window.gsap.timeline({ defaults: { ease: "power3.out" } });
  intro.from(".rh-hero-copy > *", {
    y: 14,
    autoAlpha: 0,
    duration: 0.55,
    stagger: 0.055,
    clearProps: "all",
  });
  intro.from(
    ".rh-hero-aside",
    { y: 12, autoAlpha: 0, duration: 0.6, clearProps: "all" },
    "-=0.38",
  );
}

// ----- Small helper functions -----

// Show one panel and hide the others.
function showState(name) {
  Object.keys(panels).forEach(function (key) {
    panels[key].hidden = key !== name;
  });
}

function showInputError(message) {
  input.classList.add("is-invalid");
  input.setAttribute("aria-invalid", "true");
  feedback.textContent = message;
  feedback.hidden = false;
}

function clearInputError() {
  input.classList.remove("is-invalid");
  input.removeAttribute("aria-invalid");
  feedback.textContent = "";
  feedback.hidden = true;
}

function setBusy(isBusy) {
  scanButton.disabled = isBusy;
  scanButton.setAttribute("aria-busy", String(isBusy));
}

// Check the text the user typed. Returns {ok: true, owner, repo}
// or {ok: false, message}.
function parseRepoUrl(rawValue) {
  const value = rawValue.trim();

  if (value === "") {
    return { ok: false, message: "Enter a GitHub repository URL." };
  }

  const match = REPO_URL_PATTERN.exec(value);
  if (!match) {
    return {
      ok: false,
      message:
        "That doesn't look like a repository URL. Use the form https://github.com/owner/repository",
    };
  }

  const owner = match[1];
  const repo = match[2];

  if (repo === "." || repo === "..") {
    return { ok: false, message: "That repository name is not valid." };
  }

  return { ok: true, owner: owner, repo: repo };
}

// ----- Talk to the server -----

async function scanRepository(owner, repo) {
  const controller = new AbortController();
  const timer = setTimeout(function () {
    controller.abort();
  }, SCAN_TIMEOUT_MS);

  try {
    const response = await fetch("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        repo_url: "https://github.com/" + owner + "/" + repo,
      }),
      signal: controller.signal,
    });

    // The reply might not be JSON (for example, a 404 page), so be careful.
    let data = null;
    try {
      data = await response.json();
    } catch (parseError) {
      data = null;
    }

    if (!response.ok) {
      if (data && data.error && data.error.message) {
        throw new Error(data.error.message);
      }
      if (response.status === 404 || response.status === 405) {
        throw new Error("The scan service is not available yet.");
      }
      throw new Error(
        "The server returned an error (" + response.status + ").",
      );
    }

    return data;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error(
        "The scan took too long and was cancelled. Please try again.",
      );
    }
    if (error instanceof TypeError) {
      throw new Error(
        "Could not reach the server. Check your connection and try again.",
      );
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

// ----- Handle the form -----

form.addEventListener("submit", async function (event) {
  event.preventDefault(); // stop the page from reloading
  clearInputError();

  const result = parseRepoUrl(input.value);
  if (!result.ok) {
    showInputError(result.message);
    input.focus();
    return;
  }

  // textContent (not innerHTML) so user text is never treated as HTML.
  loadingRepo.textContent = result.owner + "/" + result.repo;
  window.clearReport();
  showState("loading");
  setBusy(true);

  try {
    const data = await scanRepository(result.owner, result.repo);
    // Stage 5 will draw the real report from `data` here.
    window.renderReport(data);
    showState("none");
  } catch (error) {
    errorMessage.textContent = error.message;
    showState("error");
  } finally {
    setBusy(false);
  }
});

// Clear the red error as soon as the user starts fixing the text.
input.addEventListener("input", clearInputError);
