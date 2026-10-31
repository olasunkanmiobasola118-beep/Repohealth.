"use strict";

/*
  RepoHealth report display (preview).

  Draws the findings returned by /api/scan. Every piece of text that came from
  the server is inserted with textContent, never innerHTML, because repository
  content is untrusted. Scores, charts and JSON export come in the next stage.
*/

(function () {
  const CATEGORY_NAMES = {
    documentation: "Documentation",
    contribution: "Contribution readiness",
    testing: "Testing and CI",
    dependencies: "Dependencies",
    security: "Security hygiene",
  };
  const STATUS_LABELS = {
    passed: "Passed",
    failed: "Failed",
    not_assessed: "Not assessed",
  };
  const STATUS_ORDER = { failed: 0, not_assessed: 1, passed: 2 };
  const SEVERITY_LABELS = { high: "High", medium: "Medium", low: "Low" };
  const SEVERITY_ORDER = { high: 0, medium: 1, low: 2 };
  const KIND_LABELS = { objective: "Objective check", heuristic: "Heuristic" };
  const MAX_EVIDENCE_SHOWN = 10;

  const section = document.getElementById("results");
  const statusCard = document.getElementById("status");
  const heading = document.getElementById("results-heading");
  const description = document.getElementById("results-description");
  const meta = document.getElementById("results-meta");
  const link = document.getElementById("results-link");
  const summary = document.getElementById("results-summary");
  const warnings = document.getElementById("results-warnings");
  const findingsBox = document.getElementById("results-findings");
  const scannedAt = document.getElementById("results-time");

  // ----- Small helpers -----

  // True only if `key` is one of the map's own keys (so "constructor" never matches).
  function known(map, key) {
    return (
      typeof key === "string" && Object.prototype.hasOwnProperty.call(map, key)
    );
  }

  // Create an element; `text` is inserted as plain text.
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = String(text);
    }
    return node;
  }

  function formatNumber(value) {
    return typeof value === "number" && Number.isFinite(value)
      ? value.toLocaleString()
      : "unknown";
  }

  function formatDate(value, withTime) {
    const date = typeof value === "string" ? new Date(value) : null;
    if (!date || Number.isNaN(date.getTime())) {
      return "unknown";
    }
    if (withTime) {
      return date.toLocaleString();
    }
    return date.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }

  function statusOf(finding) {
    return known(STATUS_LABELS, finding.status)
      ? finding.status
      : "not_assessed";
  }

  function compareFindings(a, b) {
    const byStatus = STATUS_ORDER[statusOf(a)] - STATUS_ORDER[statusOf(b)];
    if (byStatus !== 0) {
      return byStatus;
    }
    const severityA = known(SEVERITY_ORDER, a.severity)
      ? SEVERITY_ORDER[a.severity]
      : 3;
    const severityB = known(SEVERITY_ORDER, b.severity)
      ? SEVERITY_ORDER[b.severity]
      : 3;
    return severityA - severityB;
  }

  function tally(findings) {
    const counts = { passed: 0, failed: 0, not_assessed: 0 };
    findings.forEach(function (finding) {
      counts[statusOf(finding)] += 1;
    });
    return counts;
  }

  // ----- Drawing -----

  function renderFinding(finding) {
    const status = statusOf(finding);
    const card = el("article", "rh-finding-card");

    const badges = el("div", "d-flex flex-wrap align-items-center gap-2");
    badges.appendChild(
      el("span", "badge rh-status rh-status-" + status, STATUS_LABELS[status]),
    );
    if (status === "failed" && known(SEVERITY_LABELS, finding.severity)) {
      badges.appendChild(
        el(
          "span",
          "badge rh-sev rh-sev-" + finding.severity,
          SEVERITY_LABELS[finding.severity] + " severity",
        ),
      );
    }
    if (known(KIND_LABELS, finding.kind)) {
      badges.appendChild(
        el("span", "badge rh-kind", KIND_LABELS[finding.kind]),
      );
    }
    if (typeof finding.confidence === "string") {
      badges.appendChild(
        el("span", "badge rh-kind", "Confidence: " + finding.confidence),
      );
    }
    card.appendChild(badges);

    const title = typeof finding.title === "string" ? finding.title : "Check";
    card.appendChild(el("h4", "h6 mt-2 mb-1", title));

    if (typeof finding.detail === "string" && finding.detail) {
      card.appendChild(el("p", "mb-2", finding.detail));
    }

    const evidence = Array.isArray(finding.evidence)
      ? finding.evidence.filter(function (item) {
          return typeof item === "string";
        })
      : [];
    if (evidence.length > 0) {
      const list = el("ul", "list-unstyled rh-evidence mb-2");
      evidence.slice(0, MAX_EVIDENCE_SHOWN).forEach(function (item) {
        const row = el("li");
        row.appendChild(el("code", null, item));
        list.appendChild(row);
      });
      card.appendChild(list);
    }

    if (typeof finding.remediation === "string" && finding.remediation) {
      const fix = el("p", "small text-secondary mb-0 rh-remediation");
      fix.appendChild(el("strong", null, "How to fix: "));
      fix.appendChild(document.createTextNode(finding.remediation));
      card.appendChild(fix);
    }

    return card;
  }

  function renderGroup(name, items) {
    const group = el("section", "rh-category-group");
    const counts = tally(items);

    const heading = el("div", "rh-category-heading");
    const title = el("div");
    title.appendChild(el("h3", null, name));
    title.appendChild(
      el(
        "p",
        null,
        counts.failed +
          " need attention · " +
          counts.not_assessed +
          " not assessed",
      ),
    );
    heading.appendChild(title);
    heading.appendChild(
      el("span", "rh-category-count", items.length + " checks"),
    );
    group.appendChild(heading);

    const sorted = items.slice().sort(compareFindings);
    const attention = sorted.filter(function (f) {
      return statusOf(f) !== "passed";
    });
    const passed = sorted.filter(function (f) {
      return statusOf(f) === "passed";
    });

    attention.forEach(function (finding) {
      group.appendChild(renderFinding(finding));
    });

    if (passed.length > 0) {
      const details = el("details", "rh-passed-details");
      details.appendChild(
        el(
          "summary",
          null,
          "Show " +
            passed.length +
            " passed check" +
            (passed.length === 1 ? "" : "s"),
        ),
      );
      passed.forEach(function (finding) {
        details.appendChild(renderFinding(finding));
      });
      group.appendChild(details);
    }

    return group;
  }

  function groupByCategory(findings) {
    const groups = new Map();
    findings.forEach(function (finding) {
      const key =
        typeof finding.category === "string" ? finding.category : "other";
      if (!groups.has(key)) {
        groups.set(key, []);
      }
      groups.get(key).push(finding);
    });

    const order = Object.keys(CATEGORY_NAMES);
    return Array.from(groups.entries()).sort(function (a, b) {
      const indexA = order.indexOf(a[0]);
      const indexB = order.indexOf(b[0]);
      return (
        (indexA === -1 ? order.length : indexA) -
        (indexB === -1 ? order.length : indexB)
      );
    });
  }

  function renderSummary(counts) {
    summary.replaceChildren();
    [
      ["passed", "Passed"],
      ["failed", "Failed"],
      ["not_assessed", "Not assessed"],
    ].forEach(function (pair) {
      const column = el("div", "col-4");
      const tile = el("div", "rh-summary-card h-100");
      const label = el("div", "rh-summary-top");
      label.appendChild(el("span", null, pair[1]));
      label.appendChild(
        el("span", "rh-summary-indicator rh-summary-indicator-" + pair[0]),
      );
      tile.appendChild(label);
      tile.appendChild(el("div", "rh-summary-number", counts[pair[0]]));
      column.appendChild(tile);
      summary.appendChild(column);
    });
  }

  function renderWarnings(items) {
    warnings.replaceChildren();
    const texts = items.filter(function (item) {
      return typeof item === "string";
    });
    if (texts.length === 0) {
      return;
    }
    const box = el("div", "alert alert-warning");
    box.setAttribute("role", "note");
    box.appendChild(el("strong", null, "Things to know about this scan"));
    const list = el("ul", "mb-0 mt-2");
    texts.forEach(function (text) {
      list.appendChild(el("li", null, text));
    });
    box.appendChild(list);
    warnings.appendChild(box);
  }

  function renderOverview(repo) {
    heading.textContent =
      typeof repo.full_name === "string" ? repo.full_name : "Scan results";
    description.textContent =
      typeof repo.description === "string" && repo.description
        ? repo.description
        : "This repository has no description.";

    const parts = [
      formatNumber(repo.stars) + " stars",
      formatNumber(repo.forks) + " forks",
      formatNumber(repo.open_issues_and_prs) + " open issues and pull requests",
      typeof repo.language === "string" ? repo.language : "language unknown",
      "License: " +
        (typeof repo.license === "string" ? repo.license : "none detected"),
      "Last push: " + formatDate(repo.pushed_at, false),
    ];
    if (repo.archived === true) {
      parts.push("Archived");
    }
    meta.textContent = parts.join(" · ");

    // Only link to GitHub, whatever the server sent.
    if (
      typeof repo.html_url === "string" &&
      repo.html_url.startsWith("https://github.com/")
    ) {
      link.href = repo.html_url;
      link.hidden = false;
    } else {
      link.hidden = true;
    }
  }

  // ----- Public functions (used by app.js) -----

  function clearReport() {
    section.hidden = true;
    statusCard.hidden = false;
    summary.replaceChildren();
    warnings.replaceChildren();
    findingsBox.replaceChildren();
    link.hidden = true;
  }

  function renderReport(data) {
    clearReport();

    const payload = data && typeof data === "object" ? data : {};
    const repo =
      payload.repository && typeof payload.repository === "object"
        ? payload.repository
        : {};
    const findings = (
      Array.isArray(payload.findings) ? payload.findings : []
    ).filter(function (item) {
      return item && typeof item === "object";
    });

    renderOverview(repo);
    renderSummary(tally(findings));
    renderWarnings(Array.isArray(payload.warnings) ? payload.warnings : []);

    if (findings.length === 0) {
      findingsBox.appendChild(
        el(
          "p",
          "text-secondary",
          "No findings were returned for this repository.",
        ),
      );
    } else {
      groupByCategory(findings).forEach(function (entry) {
        const name = known(CATEGORY_NAMES, entry[0])
          ? CATEGORY_NAMES[entry[0]]
          : entry[0];
        findingsBox.appendChild(renderGroup(name, entry[1]));
      });
    }

    scannedAt.textContent =
      "Scanned at " + formatDate(payload.scanned_at, true);

    statusCard.hidden = true;
    section.hidden = false;
    heading.focus();
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    if (window.gsap && !reduceMotion) {
      window.gsap.fromTo(
        ["#results-summary > *", ".rh-category-group"],
        { y: 9, autoAlpha: 0 },
        {
          y: 0,
          autoAlpha: 1,
          duration: 0.38,
          stagger: 0.045,
          ease: "power2.out",
          clearProps: "transform,opacity,visibility",
        },
      );
    }
    section.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "start",
    });
  }

  window.renderReport = renderReport;
  window.clearReport = clearReport;
})();
