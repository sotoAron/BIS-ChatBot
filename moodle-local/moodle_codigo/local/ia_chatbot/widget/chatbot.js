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

  const POLL_INTERVAL_MS   = 100;   // Intervalo entre intentos de sondeo.
  const POLL_MAX_ATTEMPTS  = 30;    // 30 × 100 ms = 3 segundos de espera máxima.
  const DEFAULT_BACKEND_URL = "https://undertake-luckless-endearing.ngrok-free.dev";

  /**
   * Intenta leer la configuración global. Si existe y es válida, arranca el widget.
   * Soporta window.CHATBOT_CONFIG (inyectado por lib.php) y window.IA_CHATBOT_CONFIG con fallback.
   *
   * @param {number} attempt  Número del intento actual (empieza en 0).
   */
  function tryBoot(attempt) {
    const rawCfg = window.CHATBOT_CONFIG || window.IA_CHATBOT_CONFIG;

    if (rawCfg && rawCfg.token) {
      // Resolver la URL del backend con fallback solicitado
      const backendUrl = (rawCfg.backendUrl || rawCfg.backend_url || DEFAULT_BACKEND_URL).replace(/\/+$/, '');
      const cfg = {
        ...rawCfg,
        backendUrl: backendUrl,
        backend_url: backendUrl,
      };

      // Config disponible — arrancar el widget.
      boot(cfg);
      return;
    }

    if (attempt >= POLL_MAX_ATTEMPTS) {
      // Se agotaron los intentos.
      console.warn(
        '[ia_chatbot] window.CHATBOT_CONFIG o window.IA_CHATBOT_CONFIG no encontrada tras ' +
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
        <!-- Ícono Robot Académico SVG Líneas / Bordes (Outline) -->
        <span class="ia-chatbot-toggle__icon ia-chatbot-toggle__icon--robot" aria-hidden="true">
          <svg class="icon-bot" width="30" height="30" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <!-- Birrete superior (bordes) -->
            <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="#FFFFFF" stroke-width="1.6" stroke-linejoin="round"/>
            <path d="M6 9.5V13.5C6 13.5 8.5 15.5 12 15.5C15.5 15.5 18 13.5 18 13.5V9.5" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round"/>
            <path d="M22 7V13.5" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round"/>
            <circle cx="22" cy="13.5" r="0.8" fill="#FFFFFF"/>
            <!-- Cara del bot (solo contorno/bordes) -->
            <rect x="5.5" y="11" width="13" height="10" rx="3" stroke="#FFFFFF" stroke-width="1.6"/>
            <!-- Orejas/antenas (bordes) -->
            <rect x="3.5" y="13.5" width="2" height="5" rx="1" stroke="#FFFFFF" stroke-width="1.4"/>
            <rect x="18.5" y="13.5" width="2" height="5" rx="1" stroke="#FFFFFF" stroke-width="1.4"/>
            <!-- Ojos y boca (puntos y línea blanca) -->
            <circle cx="9.5" cy="15.5" r="1.2" fill="#FFFFFF"/>
            <circle cx="14.5" cy="15.5" r="1.2" fill="#FFFFFF"/>
            <line x1="10" y1="18.5" x2="14" y2="18.5" stroke="#FFFFFF" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
        </span>
        <!-- Ícono X para minimizar (Abierto) -->
        <span class="ia-chatbot-toggle__icon ia-chatbot-toggle__icon--close" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="white" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round">
            <line x1="5" y1="5" x2="19" y2="19"/>
            <line x1="19" y1="5" x2="5" y2="19"/>
          </svg>
        </span>
        <span class="ia-chatbot-toggle__badge" id="ia-chatbot-badge" aria-live="polite"></span>
      </button>

      <div id="ia-chatbot-panel"
           class="ia-chatbot-panel"
           role="dialog"
           aria-modal="false"
           aria-labelledby="ia-chatbot-title"
           hidden>

        <header class="ia-chatbot-panel__header">
          <h2 id="ia-chatbot-title" class="ia-chatbot-panel__title">
            <svg class="icon-bot" width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" style="flex-shrink:0;">
              <path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="#FFFFFF" stroke-width="1.6" stroke-linejoin="round"/>
              <path d="M6 9.5V13.5C6 13.5 8.5 15.5 12 15.5C15.5 15.5 18 13.5 18 13.5V9.5" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round"/>
              <path d="M22 7V13.5" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round"/>
              <rect x="5.5" y="11" width="13" height="10" rx="3" stroke="#FFFFFF" stroke-width="1.6"/>
              <rect x="3.5" y="13.5" width="2" height="5" rx="1" stroke="#FFFFFF" stroke-width="1.4"/>
              <rect x="18.5" y="13.5" width="2" height="5" rx="1" stroke="#FFFFFF" stroke-width="1.4"/>
              <circle cx="9.5" cy="15.5" r="1.2" fill="#FFFFFF"/>
              <circle cx="14.5" cy="15.5" r="1.2" fill="#FFFFFF"/>
              <line x1="10" y1="18.5" x2="14" y2="18.5" stroke="#FFFFFF" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
            <span>${escHtml(s.title || 'Asistente Académico')}</span>
          </h2>
          <button id="ia-chatbot-close"
                  class="ia-chatbot-panel__close"
                  title="Minimizar chat"
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
  // 3. PERSISTENCIA DE SESIÓN (SESSIONSTORAGE)
  // ═══════════════════════════════════════════════════════════════════════════

  const HISTORY_KEY = 'ia_chatbot_history_' + cfg.userId;

  function saveHistory() {
    try {
      sessionStorage.setItem(HISTORY_KEY, els.messages.innerHTML);
    } catch (e) {
      console.warn('[ia_chatbot] No se pudo guardar el historial en sessionStorage', e);
    }
  }

  function loadHistory() {
    try {
      const historyHtml = sessionStorage.getItem(HISTORY_KEY);
      if (historyHtml) {
        els.messages.innerHTML = historyHtml;
        scrollToBottom();
      }
    } catch (e) {
      console.warn('[ia_chatbot] No se pudo cargar el historial de sessionStorage', e);
    }
  }

  loadHistory();

  // Limpiar historial al cerrar sesión en Moodle
  document.addEventListener('click', function (e) {
    const link = e.target.closest('a');
    if (link && link.href && link.href.indexOf('logout.php') !== -1) {
      try {
        sessionStorage.removeItem(HISTORY_KEY);
      } catch (err) {}
    }
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // 4. CONTROL DEL PANEL (abrir / cerrar)
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
    if (els.input.scrollHeight > 110) {
      els.input.style.height = '110px';
      els.input.style.overflowY = 'auto';
    } else {
      els.input.style.height = els.input.scrollHeight + 'px';
      els.input.style.overflowY = 'hidden';
    }
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
    if (text) {
      const parts = text.split('\n');
      for (let i = 0; i < parts.length; i++) {
        if (parts[i].length > 0) {
          div.appendChild(document.createTextNode(parts[i]));
        }
        if (i < parts.length - 1) {
          div.appendChild(document.createElement('br'));
        }
      }
    }
    els.messages.appendChild(div);
    scrollToBottom();
    // Guardamos si no es un mensaje bot en streaming (esos se guardan en finalizeStreaming)
    if (role !== 'bot' || text !== '') {
        saveHistory();
    }
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
    if (state.abortController) {
      state.abortController.abort();
      state.abortController = null;
    }
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

    const controller = new AbortController();
    state.abortController = controller;

    let botMsgNode = null;

    try {
      const endpoint = `${cfg.backendUrl}/api/chat/stream`;
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${state.token}`,
          'ngrok-skip-browser-warning': 'true',
        },
        body: JSON.stringify({
          question: question,
          user_id: cfg.userId,
          año_academico: "2026",
          carrera: "",
        }),
        signal: controller.signal,
      });

      typingDots.remove();

      if (response.status === 401 && !retried) {
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

      if (!response.ok) {
        if (response.status === 429) {
          appendMessage('error', cfg.strings.err429);
        } else if (response.status === 401) {
          appendMessage('error', cfg.strings.err401);
        } else {
          appendMessage('error', cfg.strings.errGeneric);
        }
        setStreaming(false);
        return;
      }

      botMsgNode = appendMessage('bot', '');
      state.currentBotMsg = botMsgNode;

      state.cursorNode = document.createElement('span');
      state.cursorNode.className = 'ia-chatbot-cursor';
      state.cursorNode.setAttribute('aria-hidden', 'true');
      botMsgNode.appendChild(state.cursorNode);
      clearStatus();

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); // Mantener fragmento incompleto

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith('data:')) continue;

          const rawData = trimmed.slice(5).trim();
          if (rawData === '[DONE]') {
            finalizeStreaming(botMsgNode);
            return;
          }

          let data;
          try {
            data = JSON.parse(rawData);
          } catch {
            data = { chunk: rawData };
          }

          if (!state.panelOpen) {
            openPanel();
          }

          if (data.chunk) {
            const parts = data.chunk.split('\n');
            for (let i = 0; i < parts.length; i++) {
              if (parts[i].length > 0) {
                botMsgNode.insertBefore(document.createTextNode(parts[i]), state.cursorNode);
              }
              if (i < parts.length - 1) {
                botMsgNode.insertBefore(document.createElement('br'), state.cursorNode);
              }
            }
            scrollToBottom();
          }

          if (data.done) {
            finalizeStreaming(botMsgNode);
            return;
          }
        }
      }

      finalizeStreaming(botMsgNode);

    } catch (err) {
      if (err.name === 'AbortError') return;
      typingDots.remove();
      console.error('[ia_chatbot] Error streaming:', err);
      if (!navigator.onLine) {
        appendMessage('error', cfg.strings.errConnect);
      } else {
        appendMessage('error', cfg.strings.errGeneric);
      }
      setStreaming(false);
    }
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
    saveHistory(); // Guardar el mensaje final del bot
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



