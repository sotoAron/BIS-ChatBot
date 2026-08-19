/**
 * IA Chatbot Widget — Frontend Logic (Vanilla JS / ES2020)
 *
 * Responsabilidades:
 *  1. Inicialización: leer window.CHATBOT_CONFIG inyectado por lib.php.
 *  2. UI: abrir/cerrar panel, auto-resize del textarea, scroll automático.
 *  3. Streaming SSE: conectar al backend FastAPI, renderizar tokens en tiempo real.
 *  4. Seguridad de token: detectar expiración (401), solicitar renovación vía
 *     Moodle Web Service, reintentar la petición con el nuevo JWT.
 *  5. Rate limit: mostrar mensaje amigable en respuesta 429.
 *  6. Manejo de errores: desconexión, timeout, errores genéricos.
 *
 * NOTA: Vanilla JS puro — sin dependencias externas ni módulos ES.
 * Compatible con navegadores modernos (Chrome 80+, Firefox 75+, Safari 14+).
 *
 * @package   local_ia_chatbot
 * @copyright 2026 BIS Faculty
 * @license   https://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

(function () {
  'use strict';

  // ═══════════════════════════════════════════════════════════════════════════
  // 1. BOOTSTRAP — esperar window.CHATBOT_CONFIG antes de inicializar
  //
  // PROBLEMA: $PAGE->requires->js() y js_init_code() van ambos al footer de
  // Moodle. El orden interno del requirements manager no garantiza que el
  // bloque <script>window.CHATBOT_CONFIG=…</script> aparezca ANTES del tag
  // <script src="chatbot.js">. Si el script se carga primero, cfg es undefined.
  //
  // SOLUCIÓN — estrategia en tres capas:
  //   A. Si DOMContentLoaded aún no disparó: escuchar el evento y probar ahí.
  //   B. Si el DOM ya cargó pero cfg no existe: sondeo corto (100 ms × 30).
  //   C. Si cfg existe en este mismo ciclo de ejecución: arrancar de inmediato.
  //
  // Esto cubre TODOS los escenarios de carga de Moodle (normal, Boost, AJAX).
  // ═══════════════════════════════════════════════════════════════════════════

  const POLL_INTERVAL_MS = 100;   // Intervalo entre intentos de sondeo.
  const POLL_MAX_ATTEMPTS = 30;   // 30 × 100 ms = 3 segundos de espera máxima.

  /**
   * Intenta leer window.CHATBOT_CONFIG. Si existe y es válido, arranca el widget.
   * Si no, programa un reintento después de POLL_INTERVAL_MS.
   *
   * @param {number} attempt  Número del intento actual (empieza en 0).
   */
  function tryBoot(attempt) {
    const cfg = window.CHATBOT_CONFIG;

    if (cfg && cfg.token && cfg.backendUrl) {
      // Config disponible — arrancar el widget.
      boot(cfg);
      return;
    }

    if (attempt >= POLL_MAX_ATTEMPTS) {
      // Se agotaron los intentos.
      console.warn(
        '[ia_chatbot] window.CHATBOT_CONFIG no encontrada tras ' +
        (POLL_MAX_ATTEMPTS * POLL_INTERVAL_MS / 1000) + 's de espera. Widget deshabilitado.'
      );
      return;
    }

    // Programar el siguiente intento.
    setTimeout(function () { tryBoot(attempt + 1); }, POLL_INTERVAL_MS);
  }

  /**
   * Punto de entrada: esperar al DOM antes de sondear la config.
   */
  if (document.readyState === 'loading') {
    // El HTML todavía se está parseando — esperar a DOMContentLoaded.
    document.addEventListener('DOMContentLoaded', function () { tryBoot(0); });
  } else {
    // El DOM ya está listo (script cargado de forma diferida o en el footer).
    tryBoot(0);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // FUNCIÓN PRINCIPAL: boot(cfg)
  // Se ejecuta UNA SOLA VEZ, cuando window.CHATBOT_CONFIG está confirmado.
  // Todo el estado y la lógica del widget vive dentro de esta función.
  // ═══════════════════════════════════════════════════════════════════════════

  /**
   * Inicializa el widget completo: DOM, eventos, SSE y gestión de tokens.
   *
   * @param {object} cfg  El objeto window.CHATBOT_CONFIG validado.
   */
  function boot(cfg) {

  // Estado interno del widget
  const state = {
    /** JWT actual (mutable — puede renovarse) */
    token:        cfg.token,
    /** Timestamp UNIX de expiración del token actual */
    tokenExp:     cfg.exp,
    /** EventSource activo (conexión SSE) */
    eventSource:  null,
    /** ¿El panel está abierto? */
    panelOpen:    false,
    /** ¿Estamos esperando respuesta? */
    isStreaming:  false,
    /** Nodo DOM del mensaje bot actual (streaming en curso) */
    currentBotMsg: null,
    /** Nodo cursor de streaming */
    cursorNode:    null,
    /** ID del timer de expiración */
    expTimer:      null,
  };



  // ═══════════════════════════════════════════════════════════════════════════
  // 2. CREACIÓN DINÁMICA DEL WIDGET EN EL DOM
  //
  // Como usamos extend_navigation (que no devuelve HTML), el widget se crea
  // íntegramente aquí en JS. Se invoca antes de buscar los elementos por ID.
  // ═══════════════════════════════════════════════════════════════════════════

  /**
   * Crea e inyecta en el <body> el markup completo del widget flotante.
   * Idempotente: si el wrapper ya existe (p.ej. carga parcial Ajax), no duplica.
   */
  function createWidgetDOM() {
    if (document.getElementById('ia-chatbot-wrapper')) return; // ya existe

    const s = cfg.strings;

    const wrapper = document.createElement('div');
    wrapper.id = 'ia-chatbot-wrapper';
    wrapper.setAttribute('role', 'complementary');
    wrapper.setAttribute('aria-label', s.title);

    wrapper.innerHTML = `
      <button id="ia-chatbot-toggle"
              class="ia-chatbot-toggle"
              aria-expanded="false"
              aria-controls="ia-chatbot-panel"
              title="${escHtml(s.open)}">
        <span class="ia-chatbot-toggle__icon" aria-hidden="true">&#x1F4AC;</span>
        <span class="ia-chatbot-toggle__badge" id="ia-chatbot-badge" aria-live="polite"></span>
      </button>

      <div id="ia-chatbot-panel"
           class="ia-chatbot-panel"
           role="dialog"
           aria-modal="false"
           aria-labelledby="ia-chatbot-title"
           hidden>

        <header class="ia-chatbot-panel__header">
          <h2 id="ia-chatbot-title" class="ia-chatbot-panel__title">${escHtml(s.title)}</h2>
          <button id="ia-chatbot-close"
                  class="ia-chatbot-panel__close"
                  aria-label="${escHtml(s.close)}">&times;</button>
        </header>

        <div id="ia-chatbot-messages"
             class="ia-chatbot-panel__messages"
             role="log"
             aria-live="polite"
             aria-relevant="additions"></div>

        <div id="ia-chatbot-status"
             class="ia-chatbot-panel__status"
             aria-live="assertive"
             aria-atomic="true"></div>

        <form id="ia-chatbot-form" class="ia-chatbot-panel__form" autocomplete="off">
          <label for="ia-chatbot-input" class="sr-only">${escHtml(s.placeholder)}</label>
          <textarea id="ia-chatbot-input"
                    class="ia-chatbot-panel__input"
                    rows="1"
                    placeholder="${escHtml(s.placeholder)}"
                    maxlength="1000"
                    required></textarea>
          <button type="submit"
                  id="ia-chatbot-send"
                  class="ia-chatbot-panel__send">${escHtml(s.send)}</button>
        </form>
      </div>`;

    document.body.appendChild(wrapper);
  }

  /**
   * Escapa caracteres HTML especiales para evitar XSS al construir el DOM
   * con innerHTML. Sólo aplica a los strings que vienen del servidor PHP.
   *
   * @param {string} str
   * @returns {string}
   */
  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Crear el widget antes de intentar buscar sus nodos.
  createWidgetDOM();

  // ═══════════════════════════════════════════════════════════════════════════
  // 3. REFERENCIAS A ELEMENTOS DEL DOM
  // ═══════════════════════════════════════════════════════════════════════════


  const $ = (id) => document.getElementById(id);

  const els = {
    wrapper:  $('ia-chatbot-wrapper'),
    toggle:   $('ia-chatbot-toggle'),
    panel:    $('ia-chatbot-panel'),
    messages: $('ia-chatbot-messages'),
    status:   $('ia-chatbot-status'),
    form:     $('ia-chatbot-form'),
    input:    $('ia-chatbot-input'),
    send:     $('ia-chatbot-send'),
    close:    $('ia-chatbot-close'),
    badge:    $('ia-chatbot-badge'),
  };

  // Verificar que el DOM está completo
  if (!els.toggle || !els.panel || !els.form) {
    console.error('[ia_chatbot] Elementos DOM del widget no encontrados.');
    return;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // 3. CONTROL DEL PANEL (abrir / cerrar)
  // ═══════════════════════════════════════════════════════════════════════════

  function openPanel() {
    state.panelOpen = true;
    els.panel.removeAttribute('hidden');
    // Forzar reflow para que la transición CSS funcione.
    els.panel.getBoundingClientRect();
    els.panel.classList.add('is-open');
    els.toggle.setAttribute('aria-expanded', 'true');
    els.input.focus();
  }

  function closePanel() {
    state.panelOpen = false;
    els.panel.classList.remove('is-open');
    els.toggle.setAttribute('aria-expanded', 'false');
    // Ocultar del DOM después de la transición CSS (300ms)
    setTimeout(() => {
      if (!state.panelOpen) els.panel.setAttribute('hidden', '');
    }, 320);
    els.toggle.focus();
    abortSSE();
  }

  els.toggle.addEventListener('click', () => {
    state.panelOpen ? closePanel() : openPanel();
  });

  els.close.addEventListener('click', closePanel);

  // Cerrar con Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && state.panelOpen) closePanel();
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // 4. AUTO-RESIZE DEL TEXTAREA
  // ═══════════════════════════════════════════════════════════════════════════

  els.input.addEventListener('input', () => {
    els.input.style.height = 'auto';
    els.input.style.height = Math.min(els.input.scrollHeight, 110) + 'px';
  });

  // Enviar con Enter (Shift+Enter = salto de línea)
  els.input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!state.isStreaming) els.form.requestSubmit();
    }
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // 5. GESTIÓN DE MENSAJES EN EL DOM
  // ═══════════════════════════════════════════════════════════════════════════

  /**
   * Añade una burbuja de mensaje al panel.
   *
   * @param {'user'|'bot'|'error'} role
   * @param {string} text   Texto inicial (puede estar vacío para streaming).
   * @returns {HTMLElement}  El nodo creado.
   */
  function appendMessage(role, text = '') {
    const div = document.createElement('div');
    div.className = `ia-chatbot-message ia-chatbot-message--${role}`;
    div.setAttribute('role', role === 'user' ? 'listitem' : 'listitem');
    if (text) div.textContent = text;
    els.messages.appendChild(div);
    scrollToBottom();
    return div;
  }

  function scrollToBottom() {
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  /**
   * Muestra el indicador de typing (tres puntos animados).
   * @returns {HTMLElement}  Nodo del indicador (para eliminarlo después).
   */
  function showTypingIndicator() {
    const div = document.createElement('div');
    div.className = 'ia-chatbot-typing ia-chatbot-message--bot';
    div.setAttribute('aria-label', cfg.strings.thinking);
    div.innerHTML = `
      <span class="ia-chatbot-typing__dot"></span>
      <span class="ia-chatbot-typing__dot"></span>
      <span class="ia-chatbot-typing__dot"></span>`;
    els.messages.appendChild(div);
    scrollToBottom();
    return div;
  }

  function setStatus(text) {
    els.status.textContent = text;
  }

  function clearStatus() {
    els.status.textContent = '';
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // 6. CONTROL DE ESTADO DE LA UI
  // ═══════════════════════════════════════════════════════════════════════════

  function setStreaming(active) {
    state.isStreaming = active;
    els.send.disabled = active;
    els.input.disabled = active;
    if (!active) {
      els.input.disabled = false;
      clearStatus();
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // 7. GESTIÓN DE TOKEN JWT (expiración y renovación)
  // ═══════════════════════════════════════════════════════════════════════════

  /**
   * Solicita un nuevo JWT al Web Service de Moodle (refresh_token).
   * Llama a la función external API de Moodle via AJAX nativo.
   *
   * @returns {Promise<string>}  Resuelve con el nuevo token JWT.
   * @throws {Error}  Si la renovación falla.
   */
  async function refreshToken() {
    const url = cfg.wsUrl; // URL pre-construida por PHP (moodle_url), soporta subdirectorios.
    const body = JSON.stringify([{
      index:      0,
      methodname: 'local_ia_chatbot_refresh_token',
      args:       {},
    }]);

    const res = await fetch(url, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      credentials: 'same-origin',
    });

    if (!res.ok) throw new Error(`Token refresh HTTP ${res.status}`);

    const data = await res.json();
    if (data[0]?.error) throw new Error(data[0].exception?.message || 'refresh_token failed');

    const { token, exp } = data[0].data;
    state.token    = token;
    state.tokenExp = exp;
    scheduleTokenRefresh();
    return token;
  }

  /**
   * Programa una renovación automática del token 60 segundos antes de expirar.
   */
  function scheduleTokenRefresh() {
    clearTimeout(state.expTimer);
    const msUntilExpiry = (state.tokenExp * 1000) - Date.now();
    const refreshIn     = Math.max(msUntilExpiry - 60_000, 0);

    state.expTimer = setTimeout(async () => {
      try {
        await refreshToken();
        console.debug('[ia_chatbot] Token renovado automáticamente.');
      } catch (err) {
        console.warn('[ia_chatbot] Fallo en renovación automática:', err.message);
      }
    }, refreshIn);
  }

  // Programar la primera renovación al iniciar.
  scheduleTokenRefresh();

  // ═══════════════════════════════════════════════════════════════════════════
  // 8. CONEXIÓN SSE AL BACKEND FASTAPI
  // ═══════════════════════════════════════════════════════════════════════════

  /**
   * Cancela la conexión SSE activa si existe.
   */
  function abortSSE() {
    if (state.eventSource) {
      state.eventSource.close();
      state.eventSource = null;
    }
    // Eliminar cursor de streaming si quedó
    if (state.cursorNode) {
      state.cursorNode.remove();
      state.cursorNode = null;
    }
  }

  /**
   * Inicia una nueva conversación SSE con el backend FastAPI.
   * El JWT se envía como query param 'token' en el handshake inicial,
   * ya que EventSource nativo no soporta headers custom.
   *
   * @param {string} question   Pregunta del usuario.
   * @param {boolean} retried   Si ya reintentamos tras renovar el token.
   */
  async function startSSE(question, retried = false) {
    abortSSE();
    setStreaming(true);
    setStatus(cfg.strings.thinking);

    const typingDots = showTypingIndicator();

    const endpoint = new URL(`${cfg.backendUrl}/api/chat/stream`);
    endpoint.searchParams.set('token',    state.token);
    endpoint.searchParams.set('question', question);
    endpoint.searchParams.set('user_id',  String(cfg.userId));

    let botMsgNode = null;

    const es = new EventSource(endpoint.toString());
    state.eventSource = es;

    // ── Primer evento 'open' ──────────────────────────────────────────────────
    es.addEventListener('open', () => {
      typingDots.remove();
      botMsgNode          = appendMessage('bot', '');
      state.currentBotMsg = botMsgNode;

      // Añadir cursor de streaming
      state.cursorNode = document.createElement('span');
      state.cursorNode.className = 'ia-chatbot-cursor';
      state.cursorNode.setAttribute('aria-hidden', 'true');
      botMsgNode.appendChild(state.cursorNode);
      clearStatus();
    });

    // ── Evento 'message' — token a token ─────────────────────────────────────
    es.addEventListener('message', (ev) => {
      if (!botMsgNode) return;

      let data;
      try {
        data = JSON.parse(ev.data);
      } catch {
        data = { chunk: ev.data };
      }

      if (data.chunk) {
        // Insertar texto antes del cursor
        const textNode = document.createTextNode(data.chunk);
        botMsgNode.insertBefore(textNode, state.cursorNode);
        scrollToBottom();
      }

      if (data.done) {
        finalizeStreaming(botMsgNode);
      }
    });

    // ── Evento 'done' explícito (server-sent) ─────────────────────────────────
    es.addEventListener('done', () => {
      finalizeStreaming(botMsgNode);
    });

    // ── Errores SSE ───────────────────────────────────────────────────────────
    es.addEventListener('error', async (ev) => {
      es.close();
      typingDots.remove();

      // Leer el status del error si el servidor lo envió
      const httpStatus = ev.status || (ev.target && ev.target.status);

      if (httpStatus === 401 && !retried) {
        // Token expirado → renovar y reintentar UNA sola vez
        setStatus('Renovando sesión…');
        try {
          await refreshToken();
          startSSE(question, /* retried= */ true);
        } catch {
          appendMessage('error', cfg.strings.err401);
          setStreaming(false);
        }
        return;
      }

      if (httpStatus === 429) {
        appendMessage('error', cfg.strings.err429);
      } else if (httpStatus === 401) {
        appendMessage('error', cfg.strings.err401);
      } else if (httpStatus === 0 || !navigator.onLine) {
        appendMessage('error', cfg.strings.errConnect);
      } else {
        appendMessage('error', cfg.strings.errGeneric);
      }

      setStreaming(false);
    });
  }

  /**
   * Finaliza el streaming: quita el cursor y libera el estado.
   * @param {HTMLElement} node  Nodo del mensaje bot.
   */
  function finalizeStreaming(node) {
    abortSSE();
    if (node && state.cursorNode && node.contains(state.cursorNode)) {
      state.cursorNode.remove();
    }
    state.cursorNode    = null;
    state.currentBotMsg = null;
    setStreaming(false);
    // Devolver foco al input
    els.input.focus();
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // 9. ENVÍO DEL FORMULARIO
  // ═══════════════════════════════════════════════════════════════════════════

  els.form.addEventListener('submit', (e) => {
    e.preventDefault();

    const question = els.input.value.trim();
    if (!question || state.isStreaming) return;

    // Mostrar mensaje del usuario
    appendMessage('user', question);

    // Resetear textarea
    els.input.value = '';
    els.input.style.height = 'auto';

    // Iniciar streaming
    startSSE(question);
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // 10. LIMPIAR TIMERS AL SALIR DE LA PÁGINA
  // ═══════════════════════════════════════════════════════════════════════════


  window.addEventListener('beforeunload', () => {
    abortSSE();
    clearTimeout(state.expTimer);
  });

  console.debug('[ia_chatbot] Widget inicializado. Backend:', cfg.backendUrl);

  } // ── fin de boot(cfg) ─────────────────────────────────────────────────────

})();

