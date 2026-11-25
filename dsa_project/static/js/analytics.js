// Draws the three analytics charts. The numbers come from the read-only JSON endpoints.
(function () {
  var root = document.getElementById("analytics-root");
  if (!root) { return; }

  function status(canvasId, text) {
    var note = root.querySelector('.chart-status[data-for="' + canvasId + '"]');
    if (note) { note.textContent = text; }
  }

  function load(url, canvasId, draw) {
    if (typeof Chart === "undefined") {
      status(canvasId, "The chart library could not be loaded. Check your internet connection and reload the page.");
      return;
    }
    fetch(url, { headers: { "Accept": "application/json" }, credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) { throw new Error("HTTP " + response.status); }
        return response.json();
      })
      .then(function (data) {
        if (!data.length) { status(canvasId, "No data for this chart yet."); return; }
        status(canvasId, "");
        draw(document.getElementById(canvasId), data);
      })
      .catch(function () { status(canvasId, "This chart could not be loaded. Reload the page to try again."); });
  }

  var percentAxis = { min: 0, max: 100, title: { display: true, text: "Percent" } };
  var common = { responsive: true, maintainAspectRatio: false };

  load(root.dataset.trendUrl, "trend-chart", function (canvas, rows) {
    new Chart(canvas, {
      type: "line",
      data: {
        labels: rows.map(function (r) { return r.date; }),
        datasets: [
          { label: "Accuracy so far (%)", data: rows.map(function (r) { return r.cumulative_accuracy; }),
            borderColor: "#2563eb", backgroundColor: "#2563eb", tension: 0.2 },
          { label: "Accuracy that day (%)", data: rows.map(function (r) { return r.daily_accuracy; }),
            borderColor: "#94a3b8", backgroundColor: "#94a3b8", borderDash: [5, 4], tension: 0.2 }
        ]
      },
      options: Object.assign({}, common, { scales: { y: percentAxis } })
    });
  });

  load(root.dataset.topicsUrl, "topics-chart", function (canvas, rows) {
    new Chart(canvas, {
      type: "bar",
      data: {
        labels: rows.map(function (r) { return r.topic; }),
        datasets: [
          { label: "Accuracy (%)", data: rows.map(function (r) { return r.accuracy; }), backgroundColor: "#93c5fd" },
          { label: "Mastery (0-100)", data: rows.map(function (r) { return r.mastery; }), backgroundColor: "#172554" }
        ]
      },
      options: Object.assign({}, common, { scales: { y: percentAxis } })
    });
  });

  load(root.dataset.difficultyUrl, "difficulty-chart", function (canvas, rows) {
    new Chart(canvas, {
      type: "bar",
      data: {
        labels: rows.map(function (r) { return r.difficulty + " (" + r.attempts + " tries)"; }),
        datasets: [{ label: "Accuracy (%)", data: rows.map(function (r) { return r.accuracy; }),
                     backgroundColor: ["#15803d", "#b45309", "#b91c1c"] }]
      },
      options: Object.assign({}, common, { scales: { y: percentAxis }, plugins: { legend: { display: false } } })
    });
  });
})();
