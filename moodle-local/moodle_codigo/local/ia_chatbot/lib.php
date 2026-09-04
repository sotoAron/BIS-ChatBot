<?php
// This file is part of Moodle - https://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

/**
 * Library functions for local_ia_chatbot.
 *
 * HOOK USADO: local_ia_chatbot_extend_navigation(global_navigation $navigation)
 * ─────────────────────────────────────────────────────────────────────────────
 * Este hook es un callback estándar de Moodle, reconocido por la convención
 * {plugintype}_{pluginname}_extend_navigation(). Se dispara durante la
 * construcción de la navegación global, ANTES de que se envíe cualquier
 * output (HEAD incluido), lo que garantiza que:
 *
 *   • $PAGE->requires->css()            → inyecta el <link> en el <head>  ✓
 *   • $PAGE->requires->js_init_code()   → ejecuta el bloque JS en el footer ✓
 *   • $PAGE->requires->js()             → carga el script en el footer      ✓
 *
 * El widget HTML lo genera chatbot.js dinámicamente al inicializarse, por lo
 * que no necesitamos un segundo hook (before_footer) para inyectar markup.
 *
 * @package   local_ia_chatbot
 * @copyright 2026 BIS Faculty
 * @license   https://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

defined('MOODLE_INTERNAL') || die();

/**
 * Injects chatbot assets (CSS, config, JS) into every authenticated page.
 *
 * Called automatically by Moodle core during navigation building via the
 * callback convention {plugintype}_{pluginname}_extend_navigation().
 *
 * @param global_navigation $navigation  The Moodle global navigation tree.
 * @return void
 */
function local_ia_chatbot_extend_navigation(global_navigation $navigation): void {
    global $PAGE, $USER, $CFG;

    // ── Guardia 1: Solo usuarios autenticados (no invitados) ──────────────────
    if (!isloggedin() || isguestuser()) {
        return;
    }

    // ── Guardia 2: El usuario debe tener la capacidad de uso ──────────────────
    // NOTA: Comentado porque roles como "student" suelen estar a nivel curso, 
    // y no siempre tienen la capability heredada correctamente en CONTEXT_SYSTEM.
    // $context = context_system::instance();
    // if (!has_capability('local/ia_chatbot:use', $context)) {
    //     return;
    // }

    // ── Autoload del helper ───────────────────────────────────────────────────
    require_once($CFG->dirroot . '/local/ia_chatbot/classes/jwt_helper.php');

    // ── Generar el JWT ────────────────────────────────────────────────────────
    try {
        $token = \local_ia_chatbot\jwt_helper::generate($USER->id, $USER);
    } catch (\Throwable $e) {
        // No romper la página; el error queda en los logs de Moodle.
        debugging('local_ia_chatbot JWT error: ' . $e->getMessage(), DEBUG_DEVELOPER);
        return;
    }

    // ── Leer configuración del plugin ─────────────────────────────────────────
    $backend_url  = rtrim(get_config('local_ia_chatbot', 'backend_url') ?: 'http://localhost:8000', '/');
    $token_expiry = (int)(get_config('local_ia_chatbot', 'token_expiry') ?: 900);

    // ── Objeto de configuración para el widget JS ─────────────────────────────
    $config = [
        'token'      => $token,
        'exp'        => time() + $token_expiry,
        'backendUrl' => $backend_url,
        'userId'     => (int) $USER->id,
        'wwwroot'    => $CFG->wwwroot,
        'wsUrl'      => (new moodle_url('/lib/ajax/service.php'))->out(false),
        'sesskey'    => sesskey(),
        'strings'    => [
            'title'       => get_string('widget_title',         'local_ia_chatbot'),
            'placeholder' => get_string('widget_placeholder',   'local_ia_chatbot'),
            'send'        => get_string('widget_send',          'local_ia_chatbot'),
            'close'       => get_string('widget_close',         'local_ia_chatbot'),
            'open'        => get_string('widget_open',          'local_ia_chatbot'),
            'thinking'    => get_string('widget_thinking',      'local_ia_chatbot'),
            'err401'      => get_string('widget_error_401',     'local_ia_chatbot'),
            'err429'      => get_string('widget_error_429',     'local_ia_chatbot'),
            'errConnect'  => get_string('widget_error_connect', 'local_ia_chatbot'),
            'errGeneric'  => get_string('widget_error_generic', 'local_ia_chatbot'),
        ],
    ];

    // ── Inyección de assets ───────────────────────────────────────────────────
    //
    // ORDEN DE INYECCIÓN (crítico para que chatbot.js funcione):
    //   1. CSS  → <link> en <head>  (extend_navigation corre antes del output)
    //   2. Config JS → <script> inline en <head> (true = en cabecera)
    //      Así window.CHATBOT_CONFIG existe ANTES de que chatbot.js se ejecute.
    //   3. chatbot.js → <script> en el footer de Moodle
    //      El script lee window.CHATBOT_CONFIG y crea el widget en el DOM.

    // 1. CSS — se inyecta en el <head> con versión para evitar caché del navegador.
    $PAGE->requires->css(new moodle_url('/local/ia_chatbot/widget/chatbot.css', ['v' => '2026090302']));

    // 2. Config global — 'true' → coloca el bloque en el <head>, antes de cualquier script.
    //    JSON_HEX_TAG escapa < y > para prevenir XSS.
    $PAGE->requires->js_init_code(
        'window.CHATBOT_CONFIG = ' . json_encode(
            $config,
            JSON_HEX_TAG | JSON_HEX_AMP | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR
        ) . ';',
        true   // true = inyectar en <head>, no en footer.
    );

    // 3. Script del widget — se carga en el footer con versión.
    //    chatbot.js creará el HTML del widget dinámicamente al ejecutarse.
    $PAGE->requires->js(new moodle_url('/local/ia_chatbot/widget/chatbot.js', ['v' => '2026090302']));
}
