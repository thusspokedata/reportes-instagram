// Lee los datos calculados en el backend (inyectados como JSON seguro) e
// inicializa los gráficos de Chart.js. Las métricas NULL se pasan como `null`:
// Chart.js NO las dibuja como 0 (quedan como hueco / "sin dato").
(function () {
  "use strict";

  var el = document.getElementById("dashboard-data");
  if (!el || typeof Chart === "undefined") return;

  var data;
  try {
    data = JSON.parse(el.textContent);
  } catch (e) {
    return;
  }

  var baseOptions = {
    responsive: true,
    scales: { y: { beginAtZero: true } },
    plugins: { legend: { position: "bottom" } },
  };

  var engagement = data.engagement || [];
  var labels = engagement.map(function (p) {
    return p.label;
  });

  var engCanvas = document.getElementById("chart-engagement");
  if (engCanvas && engagement.length) {
    new Chart(engCanvas, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Likes",
            data: engagement.map(function (p) { return p.likes; }),
            backgroundColor: "#3b5bdb",
          },
          {
            label: "Comentarios",
            data: engagement.map(function (p) { return p.comments; }),
            backgroundColor: "#15aabf",
          },
        ],
      },
      options: baseOptions,
    });
  }

  var reachCanvas = document.getElementById("chart-reach");
  if (reachCanvas && engagement.length) {
    new Chart(reachCanvas, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Reach",
            data: engagement.map(function (p) { return p.reach; }),
            backgroundColor: "#7048e8",
          },
        ],
      },
      options: baseOptions,
    });
  }

  var byType = data.reach_by_type || [];
  var typeCanvas = document.getElementById("chart-reach-type");
  if (typeCanvas && byType.length) {
    new Chart(typeCanvas, {
      type: "bar",
      data: {
        labels: byType.map(function (t) { return t.type + " (n=" + t.n + ")"; }),
        datasets: [
          {
            label: "Reach mediano",
            data: byType.map(function (t) { return t.median_reach; }),
            backgroundColor: "#2f9e44",
          },
        ],
      },
      options: baseOptions,
    });
  }
})();
