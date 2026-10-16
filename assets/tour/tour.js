// Spike: tutorial interactivo con driver.js sobre una app Flet (Flutter web).
//
// Flutter dibuja en un canvas, así que no hay elementos DOM para resaltar.
// Al activar la capa de accesibilidad de Flutter web se generan nodos
// <flt-semantics aria-label="..."> posicionados sobre cada control; los
// controles marcados con ft.Semantics(label="tour:...") en app.py sirven de
// anclas para driver.js.
//
// Lanzar: añadir ?tour=1 a la URL, o ejecutar infohubTour.start() en consola.
(function () {
  "use strict";

  const STEPS = [
    {
      anchor: "tour:config",
      title: "Configuración",
      description: "Desde aquí configuras la carpeta vigilada, la conexión con InfoHub y Ollama.",
    },
    {
      anchor: "tour:op-scan",
      title: "Escanear archivos",
      description: "Previsualiza el contenido de tus carpetas sin subir nada a InfoHub.",
    },
  ];

  function anchorSelector(label) {
    // Flutter fusiona la etiqueta con el texto/tooltip del control hijo
    // separándolos con saltos de línea, antes o después según el control
    // ("Configuración\ntour:config"). `~=` busca la palabra en cualquier posición.
    return `flt-semantics[aria-label~="${label}"]`;
  }

  function enableSemantics() {
    const placeholder = document.querySelector("flt-semantics-placeholder");
    if (placeholder) {
      placeholder.click();
      return true;
    }
    return false;
  }

  function waitFor(predicate, timeoutMs) {
    return new Promise((resolve, reject) => {
      const start = Date.now();
      (function poll() {
        const value = predicate();
        if (value) return resolve(value);
        if (Date.now() - start > timeoutMs) return reject(new Error("timeout"));
        setTimeout(poll, 150);
      })();
    });
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function isInView(rect) {
    return rect.top >= 0 && rect.bottom <= window.innerHeight;
  }

  // driver.js hace scrollIntoView sobre el nodo de semántica, pero eso solo
  // desplaza la capa DOM: Flutter no mueve el canvas y el resaltado queda
  // desfasado. Se hace scroll en Flutter con eventos de rueda sobre el canvas
  // hasta que el ancla esté visible; así driver.js ya no necesita desplazar.
  async function scrollFlutterTo(selector) {
    const host = document.querySelector("flutter-view") || document.querySelector("flt-glass-pane");
    for (let i = 0; i < 10; i++) {
      const el = document.querySelector(selector);
      if (!el || !host) return;
      const rect = el.getBoundingClientRect();
      if (isInView(rect)) return;
      const deltaY = rect.top - window.innerHeight / 3;
      host.dispatchEvent(new WheelEvent("wheel", {
        deltaY,
        clientX: window.innerWidth / 2,
        clientY: window.innerHeight / 2,
        bubbles: true,
        cancelable: true,
      }));
      await sleep(250);
    }
  }

  async function start() {
    enableSemantics();
    try {
      await waitFor(() => document.querySelector(anchorSelector(STEPS[0].anchor)), 10000);
    } catch (e) {
      console.warn("[tour] no se encontraron anclas de semántica", e);
      return;
    }

    const selectors = STEPS.map((s) => anchorSelector(s.anchor));

    async function goTo(index) {
      await scrollFlutterTo(selectors[index]);
      tour.moveTo(index);
    }

    const tour = window.driver.js.driver({
      showProgress: true,
      nextBtnText: "Siguiente",
      prevBtnText: "Anterior",
      doneBtnText: "Finalizar",
      progressText: "{{current}} de {{total}}",
      steps: STEPS.map((s, i) => ({
        // Selector (no nodo): driver.js lo resuelve al mostrar cada paso,
        // y Flutter recrea los nodos de semántica al redibujar.
        element: selectors[i],
        popover: { title: s.title, description: s.description },
      })),
      onNextClick: () => {
        const next = tour.getActiveIndex() + 1;
        if (next >= STEPS.length) tour.destroy();
        else goTo(next);
      },
      onPrevClick: () => goTo(tour.getActiveIndex() - 1),
    });
    window.infohubTour.instance = tour;

    // Flutter reubica los nodos de semántica después del resize, cuando
    // driver.js ya ha recalculado; se vuelve a recalcular con retardo.
    let resizeTimer;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if (tour.isActive()) tour.refresh();
      }, 400);
    });

    await scrollFlutterTo(selectors[0]);
    tour.drive();
  }

  window.infohubTour = { start, enableSemantics, anchorSelector };

  if (new URLSearchParams(location.search).get("tour") === "1") {
    waitFor(() => document.querySelector("flt-semantics-placeholder, flt-glass-pane, flutter-view"), 30000)
      .then(() => setTimeout(start, 1500))
      .catch(() => console.warn("[tour] Flutter no cargó a tiempo"));
  }
})();
