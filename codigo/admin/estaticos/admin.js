/* Módulo de administración — lo mínimo que no puede hacer el HTML solo.
   Tres cosas: abrir y cerrar paneles, copiar al portapapeles, y mostrar el
   selector de entorno solo cuando el rol elegido lo necesita.
   Sin librerías: el módulo tiene que funcionar con la máquina desconectada. */

(function () {
  "use strict";

  /* --- paneles: los botones con data-panel abren el suyo y cierran los demás */
  document.addEventListener("click", function (ev) {
    var abre = ev.target.closest("[data-panel]");
    if (abre) {
      var destino = document.getElementById(abre.dataset.panel);
      if (!destino) return;
      var abierto = !destino.hidden;
      document.querySelectorAll(".panel, .panel-fila").forEach(function (p) {
        p.hidden = true;
      });
      destino.hidden = abierto;
      if (!destino.hidden) {
        var primero = destino.querySelector("input, select");
        if (primero) primero.focus();
      }
      return;
    }

    var cierra = ev.target.closest(".cierra");
    if (cierra) {
      var panel = cierra.closest(".panel, .panel-fila");
      if (panel) panel.hidden = true;
    }
  });

  /* --- copiar al portapapeles, con confirmación visible en el propio botón */
  document.addEventListener("click", function (ev) {
    var boton = ev.target.closest(".copiar");
    if (!boton) return;
    var origen = document.getElementById(boton.dataset.copia);
    if (!origen) return;

    var texto = origen.textContent.trim();
    var avisa = function (ok) {
      var antes = boton.textContent;
      boton.textContent = ok ? "Copiado" : "No se pudo";
      setTimeout(function () { boton.textContent = antes; }, 1600);
    };

    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(texto).then(function () { avisa(true); },
                                                function () { avisa(false); });
    } else {
      /* http://127.0.0.1 no siempre cuenta como contexto seguro según el
         navegador, así que queda el camino viejo como respaldo. */
      var caja = document.createElement("textarea");
      caja.value = texto;
      caja.style.position = "fixed";
      caja.style.opacity = "0";
      document.body.appendChild(caja);
      caja.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(caja);
      avisa(ok);
    }
  });

  /* --- el entorno solo se pide para estudiantes, que son los que lo necesitan */
  var rol = document.getElementById("rol-nuevo");
  var campoEntorno = document.getElementById("entorno-nuevo");
  if (rol && campoEntorno) {
    var ajusta = function () {
      var esEstudiante = rol.value === "student";
      campoEntorno.hidden = !esEstudiante;
      var select = campoEntorno.querySelector("select");
      if (select) {
        select.required = esEstudiante;
        if (!esEstudiante) select.value = "";
      }
    };
    rol.addEventListener("change", ajusta);
    ajusta();
  }
})();

/* --- espera visible en lo que tarda ---------------------------------------
   Reindexar un corpus y restaurar una base tardan minutos. Sin esto la página
   se queda quieta y el silencio se lee como que se colgó, que es justo cuando
   alguien vuelve a pulsar. El botón dice que está trabajando y no admite un
   segundo clic; si el botón declara data-espera, además se echa un velo. */
(function () {
  "use strict";

  document.addEventListener("submit", function (ev) {
    var formulario = ev.target;
    var boton = formulario.querySelector("[data-lento]");
    if (!boton || boton.classList.contains("trabajando")) return;

    /* La validación del navegador manda: si el formulario no es válido -el SI
       sin escribir, un campo vacío- no se ha enviado nada que esperar. */
    if (typeof formulario.checkValidity === "function" && !formulario.checkValidity()) {
      return;
    }

    boton.classList.add("trabajando");
    boton.dataset.textoPrevio = boton.textContent;
    boton.textContent = "Trabajando…";
    /* disabled quitaría el botón del envío; readonly no existe en button, así
       que se bloquea el clic por CSS y se marca el formulario como en curso. */
    boton.style.pointerEvents = "none";

    var espera = boton.dataset.espera;
    if (espera) {
      var velo = document.createElement("div");
      velo.className = "velo";
      var caja = document.createElement("div");
      caja.textContent = espera;
      velo.appendChild(caja);
      document.body.appendChild(velo);
    }
  });
})();
