// Recorrido guiado del panel con driver.js sobre una app Flet (Flutter web).
//
// Flutter dibuja en un canvas, así que no hay elementos DOM para resaltar.
// Al activar la capa de accesibilidad de Flutter web se generan nodos
// <flt-semantics aria-label="..."> posicionados sobre cada control; los
// controles marcados con ft.Semantics(label="tour:...") en app.py sirven de
// anclas para driver.js.
//
// Se abre solo la primera vez (marca en localStorage de este navegador), con
// el botón «?» del panel, con ?tour=1 en la URL o con infohubTour.start().
(function () {
  "use strict";

  // Subir la versión cuando cambien los pasos: el recorrido se vuelve a mostrar.
  const STORAGE_KEY = "infohub-fm-tour-v1";

  // Sin `anchor`, el paso es un mensaje centrado. Con `optional`, el paso se
  // omite si el control no está en pantalla (el botón de inicio depende de PORTAL_URL).
  const STEPS_ES = [
    {
      title: "Bienvenido a InfoHub File Manager",
      description:
        "Sincroniza una carpeta de tu equipo con InfoHub. Cada subcarpeta es un workspace: " +
        "lo que pongas ahí se sube, se actualiza o se borra en InfoHub. Te muestro el panel.",
    },
    {
      anchor: "tour:status",
      title: "Estado",
      description: "Aquí ves si el sistema está listo o si hay una operación en curso.",
    },
    {
      anchor: "tour:stats",
      title: "Resumen",
      description:
        "Workspaces y archivos que hay en tus carpetas, cuántos se subieron en la última " +
        "operación y cuántos quedaron pendientes.",
    },
    {
      anchor: "tour:config",
      title: "Configuración",
      description:
        "Carpeta raíz, conexión con InfoHub, workspaces protegidos y Ollama para describir " +
        "imágenes. La primera vez, empieza por aquí.",
    },
    {
      anchor: "tour:op-scan",
      title: "Escanear archivos",
      description:
        "Revisa tus carpetas sin subir nada. Sirve para confirmar qué workspaces y archivos ve la herramienta.",
    },
    {
      anchor: "tour:op-simulate",
      title: "Simular limpieza",
      description:
        "Muestra, por workspace, qué borraría y qué subiría la carga completa, sin cambiar nada " +
        "en InfoHub. Úsalo antes de cada carga completa.",
    },
    {
      anchor: "tour:op-full",
      title: "Carga completa y limpieza",
      description:
        "Sube los archivos nuevos, actualiza los modificados y borra de InfoHub lo que eliminaste " +
        "en tu equipo. Pide confirmación antes de empezar.",
    },
    {
      anchor: "tour:op-images",
      title: "Descripciones de imágenes",
      description:
        "Genera con IA un texto para cada imagen, para encontrarla preguntando en InfoHub. " +
        "A InfoHub solo se sube ese texto.",
    },
    {
      anchor: "tour:logs",
      title: "Registro de operaciones",
      description: "Cada operación deja aquí su resultado y sus errores.",
    },
    {
      anchor: "tour:home",
      optional: true,
      title: "Volver a InfoHub",
      description: "Regresa al portal de InfoHub.",
    },
    {
      anchor: "tour:help",
      title: "Repetir el recorrido",
      description: "Desde este botón puedes ver el recorrido otra vez cuando quieras.",
    },
  ];

  const STEPS_EN = [
    {
      title: "Welcome to InfoHub File Manager",
      description:
        "Syncs a folder on your computer with InfoHub. Each subfolder is a workspace: " +
        "whatever you put there is uploaded, updated or deleted in InfoHub. Let me show you the panel.",
    },
    {
      anchor: "tour:status",
      title: "Status",
      description: "Shows whether the system is ready or an operation is running.",
    },
    {
      anchor: "tour:stats",
      title: "Summary",
      description:
        "Workspaces and files in your folders, how many were uploaded in the last " +
        "operation and how many are still pending.",
    },
    {
      anchor: "tour:config",
      title: "Settings",
      description:
        "Root folder, InfoHub connection, protected workspaces and Ollama to describe " +
        "images. The first time, start here.",
    },
    {
      anchor: "tour:op-scan",
      title: "Scan files",
      description:
        "Checks your folders without uploading anything. Use it to confirm which workspaces and files the tool sees.",
    },
    {
      anchor: "tour:op-simulate",
      title: "Simulate cleanup",
      description:
        "Shows, per workspace, what the full upload would delete and upload, without changing anything " +
        "in InfoHub. Use it before every full upload.",
    },
    {
      anchor: "tour:op-full",
      title: "Full upload and cleanup",
      description:
        "Uploads new files, updates the modified ones and deletes from InfoHub what you removed " +
        "on your computer. It asks for confirmation before starting.",
    },
    {
      anchor: "tour:op-images",
      title: "Image descriptions",
      description:
        "Generates a text for each image with AI, so you can find it by asking InfoHub. " +
        "Only that text is uploaded to InfoHub.",
    },
    {
      anchor: "tour:logs",
      title: "Operations log",
      description: "Each operation leaves its result and its errors here.",
    },
    {
      anchor: "tour:home",
      optional: true,
      title: "Back to InfoHub",
      description: "Returns to the InfoHub portal.",
    },
    {
      anchor: "tour:help",
      title: "Repeat the tour",
      description: "Use this button to see the tour again whenever you want.",
    },
  ];

  // Idioma: el que guarda app.py en shared_preferences (localStorage de
  // Flutter web, claves con prefijo «flutter.» y valor en JSON): primero la
  // elección del usuario, después el de la instancia, si no español.
  function readPref(key) {
    try {
      const raw = localStorage.getItem("flutter." + key);
      if (raw == null) return null;
      try { return JSON.parse(raw); } catch (e) { return raw; }
    } catch (e) {
      return null;
    }
  }

  function language() {
    for (const key of ["infohubFm.language", "infohubFm.instanceLanguage"]) {
      const lang = readPref(key);
      if (lang === "es" || lang === "en") return lang;
    }
    return "es";
  }

  const BUTTONS = {
    es: { next: "Siguiente", prev: "Anterior", done: "Finalizar", progress: "{{current}} de {{total}}" },
    en: { next: "Next", prev: "Previous", done: "Done", progress: "{{current}} of {{total}}" },
  };
  const STEPS_BY_LANG = { es: STEPS_ES, en: STEPS_EN };

  // Ancla que debe existir para dar el panel por cargado.
  const READY_ANCHOR = "tour:config";

  function anchorSelector(label) {
    // Flutter fusiona la etiqueta con el texto/tooltip del control hijo
    // separándolos con saltos de línea, antes o después según el control
    // ("Configuración\ntour:config"). `~=` busca la palabra en cualquier posición.
    return `flt-semantics[aria-label~="${label}"]`;
  }

  function wasSeen() {
    try {
      return localStorage.getItem(STORAGE_KEY) === "1";
    } catch (e) {
      return false;
    }
  }

  function markSeen() {
    try {
      localStorage.setItem(STORAGE_KEY, "1");
    } catch (e) {
      // Sin almacenamiento (ventana privada, bloqueado): se volverá a mostrar.
    }
  }

  function enableSemantics() {
    const placeholder = document.querySelector("flt-semantics-placeholder");
    if (placeholder) {
      placeholder.click();
      return true;
    }
    return false;
  }

  // El panel está listo cuando sus anclas existen y no hay un diálogo abierto
  // (login, configuración, confirmación): Flutter oculta las anclas de debajo.
  function panelReady() {
    return (
      document.querySelector(anchorSelector(READY_ANCHOR)) &&
      !document.querySelector('flt-semantics[role="dialog"], flt-semantics[role="alertdialog"]')
    );
  }

  function waitFor(predicate, timeoutMs) {
    return new Promise((resolve, reject) => {
      const start = Date.now();
      (function poll() {
        const value = predicate();
        if (value) return resolve(value);
        if (timeoutMs && Date.now() - start > timeoutMs) return reject(new Error("timeout"));
        setTimeout(poll, 300);
      })();
    });
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // Donde empieza el área con scroll (barra superior, barra de estado y margen
  // del contenido, ~120 px). Un ancla más arriba está recortada por Flutter y
  // su nodo de semántica también, con el borde superior justo en ese límite.
  const HEADER_HEIGHT = 130;

  function isInView(rect) {
    return rect.top >= HEADER_HEIGHT && rect.bottom <= window.innerHeight;
  }

  // driver.js hace scrollIntoView sobre el nodo de semántica, pero eso solo
  // desplaza la capa DOM: Flutter no mueve el canvas y el resaltado queda
  // desfasado. Se hace scroll en Flutter con eventos de rueda sobre el canvas
  // hasta que el ancla esté visible; así driver.js ya no necesita desplazar.
  async function scrollFlutterTo(selector) {
    if (!selector) return;
    const host = document.querySelector("flutter-view") || document.querySelector("flt-glass-pane");
    let lastTop = null;
    for (let i = 0; i < 10; i++) {
      const el = document.querySelector(selector);
      if (!el || !host) return;
      const rect = el.getBoundingClientRect();
      // Si no se movió, está fuera del área con scroll (cabecera) o ya en el tope.
      if (isInView(rect) || rect.top === lastTop) return;
      lastTop = rect.top;
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

  let tour = null;

  async function start() {
    if (tour && tour.isActive()) return;
    enableSemantics();
    try {
      await waitFor(panelReady, 10000);
    } catch (e) {
      console.warn("[tour] el panel no está disponible", e);
      return;
    }

    const lang = language();
    const buttons = BUTTONS[lang];
    const steps = STEPS_BY_LANG[lang].filter((s) => !s.optional || document.querySelector(anchorSelector(s.anchor)));
    const selectors = steps.map((s) => (s.anchor ? anchorSelector(s.anchor) : null));

    async function goTo(index) {
      await scrollFlutterTo(selectors[index]);
      tour.moveTo(index);
    }

    tour = window.driver.js.driver({
      showProgress: true,
      popoverClass: "infohub-tour",
      overlayColor: "#14152E",
      overlayOpacity: 0.55,
      stagePadding: 6,
      stageRadius: 8,
      nextBtnText: buttons.next,
      prevBtnText: buttons.prev,
      doneBtnText: buttons.done,
      progressText: buttons.progress,
      steps: steps.map((s, i) => ({
        // Selector (no nodo): driver.js lo resuelve al mostrar cada paso,
        // y Flutter recrea los nodos de semántica al redibujar.
        element: selectors[i] || undefined,
        popover: { title: s.title, description: s.description },
      })),
      onNextClick: () => {
        const next = tour.getActiveIndex() + 1;
        if (next >= steps.length) tour.destroy();
        else goTo(next);
      },
      onPrevClick: () => goTo(tour.getActiveIndex() - 1),
      // Al terminar o al cerrarlo antes: no se vuelve a abrir solo.
      onDestroyed: markSeen,
    });
    window.infohubTour.instance = tour;

    await scrollFlutterTo(selectors[0]);
    tour.drive();
  }

  // Flutter reubica los nodos de semántica después del resize, cuando
  // driver.js ya ha recalculado; se vuelve a recalcular con retardo.
  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (tour && tour.isActive()) tour.refresh();
    }, 400);
  });

  // El botón «?» de app.py no tiene acción en Python: el clic sobre su nodo
  // de semántica abre el recorrido.
  document.addEventListener(
    "click",
    (e) => {
      if (e.target instanceof Element && e.target.closest(anchorSelector("tour:help"))) start();
    },
    true
  );

  window.infohubTour = { start, enableSemantics, anchorSelector, STORAGE_KEY };

  const forced = new URLSearchParams(location.search).get("tour") === "1";
  waitFor(() => document.querySelector("flt-semantics-placeholder, flt-glass-pane, flutter-view"), 30000)
    .then(async () => {
      await sleep(1500);
      // La semántica queda activa siempre, para que el botón «?» tenga su nodo.
      enableSemantics();
      if (!forced && wasSeen()) return;
      // Sin límite de tiempo: la primera vez espera a que se cierre el login.
      await waitFor(panelReady);
      await sleep(800);
      start();
    })
    .catch(() => console.warn("[tour] Flutter no cargó a tiempo"));
})();
