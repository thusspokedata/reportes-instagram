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
    // El alto lo fija el .chart-box (no el ancho): evita que el gráfico se
    // aplaste en pantallas angostas.
    maintainAspectRatio: false,
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

  // --- Demografía de audiencia ---
  var demo = data.demographics;
  if (demo) {
    var demoColors = [
      "#3b5bdb", "#15aabf", "#7048e8", "#2f9e44", "#e8590c",
      "#c2255c", "#1098ad", "#5c940d", "#9c36b5", "#0c8599",
    ];

    function labels(arr) {
      return arr.map(function (x) { return x.label; });
    }
    function values(arr) {
      return arr.map(function (x) { return x.value; });
    }

    var genderCanvas = document.getElementById("chart-demo-gender");
    if (genderCanvas && demo.gender && demo.gender.length) {
      new Chart(genderCanvas, {
        type: "doughnut",
        data: {
          labels: labels(demo.gender),
          datasets: [{ data: values(demo.gender), backgroundColor: demoColors }],
        },
        // maintainAspectRatio:false: el alto lo fija el .chart-box. El doughnut
        // se dibuja como círculo centrado del lado menor, así no desborda.
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { position: "bottom" } },
        },
      });
    }

    [
      ["chart-demo-age", demo.age, "#3b5bdb"],
      ["chart-demo-country", demo.country, "#2f9e44"],
      ["chart-demo-city", demo.city, "#7048e8"],
    ].forEach(function (cfg) {
      var canvas = document.getElementById(cfg[0]);
      var arr = cfg[1];
      if (canvas && arr && arr.length) {
        new Chart(canvas, {
          type: "bar",
          data: {
            labels: labels(arr),
            datasets: [{ data: values(arr), backgroundColor: cfg[2] }],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: { y: { beginAtZero: true } },
            plugins: { legend: { display: false } },
          },
        });
      }
    });
  }

  // --- Evolución (serie temporal de snapshots diarios) ---
  var evo = data.evolution;
  if (evo && evo.enough) {
    var followersCanvas = document.getElementById("chart-evolution-followers");
    if (followersCanvas) {
      new Chart(followersCanvas, {
        type: "line",
        data: {
          labels: evo.labels,
          datasets: [
            {
              label: "Seguidores",
              data: evo.followers,
              borderColor: "#3b5bdb",
              backgroundColor: "#3b5bdb",
              tension: 0.2,
              // Un día sin dato (null) corta la línea; no se rellena con 0.
              spanGaps: false,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          // Seguidores no arranca en 0: forzar 0 aplastaría la tendencia.
          scales: { y: { beginAtZero: false } },
          plugins: { legend: { position: "bottom" } },
        },
      });
    }

    var pviewsCanvas = document.getElementById("chart-evolution-profile-views");
    if (pviewsCanvas && evo.profile_views) {
      new Chart(pviewsCanvas, {
        type: "line",
        data: {
          labels: evo.labels,
          datasets: [
            {
              label: "Visitas al perfil",
              data: evo.profile_views,
              borderColor: "#e8590c",
              backgroundColor: "#e8590c",
              tension: 0.2,
              // Los días sin dato (null) cortan la línea; no se rellena con 0.
              spanGaps: false,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          // Conteo diario chico: anclar en 0 es honesto (a diferencia de
          // seguidores, donde el eje desde 0 aplastaría la tendencia).
          scales: { y: { beginAtZero: true } },
          plugins: { legend: { position: "bottom" } },
        },
      });
    }

    var reachEvoCanvas = document.getElementById("chart-evolution-reach");
    if (reachEvoCanvas) {
      var evoDatasets = [
        { label: "Reach", data: evo.reach, backgroundColor: "#7048e8" },
      ];
      // Vistas: sólo si Meta las devolvió (evo.views != null).
      if (evo.views) {
        evoDatasets.push({
          label: "Vistas",
          data: evo.views,
          backgroundColor: "#2f9e44",
        });
      }
      new Chart(reachEvoCanvas, {
        type: "bar",
        data: { labels: evo.labels, datasets: evoDatasets },
        options: baseOptions,
      });
    }
  }
})();
