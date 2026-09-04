<?php
// This file is part of Moodle - https://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

/**
 * Language strings for local_ia_chatbot (English).
 *
 * @package   local_ia_chatbot
 * @copyright 2026 BIS Faculty
 * @license   https://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

defined('MOODLE_INTERNAL') || die();

// ── Plugin identity ──────────────────────────────────────────────────────────
$string['pluginname']           = 'IA Chatbot — Academic Assistant';

// ── Settings page ────────────────────────────────────────────────────────────
$string['settings_heading']     = 'IA Chatbot Settings';
$string['settings_desc']        = 'Configure the connection to the FastAPI backend and token security. '
                                . 'For production, prefer environment variables over storing secrets here.';

$string['backend_url']          = 'FastAPI Backend URL';
$string['backend_url_desc']     = 'Full URL of the FastAPI backend, including protocol and port. '
                                . 'Example: <code>http://localhost:8000</code>';

$string['token_expiry']         = 'JWT Token Expiry (seconds)';
$string['token_expiry_desc']    = 'How long (in seconds) the issued JWT remains valid. Default: 900 (15 minutes).';

$string['jwt_secret']           = 'JWT Secret (fallback)';
$string['jwt_secret_desc']      = 'Signing secret used when the <code>IA_CHATBOT_JWT_SECRET</code> environment variable '
                                . 'is not set. <strong>Leave empty in production and set the env variable instead.</strong>';

// ── Widget UI strings ─────────────────────────────────────────────────────────
$string['widget_title']         = 'Asistente Académico';
$string['widget_placeholder']   = 'Escribe tu consulta aquí…';
$string['widget_send']          = 'Enviar';
$string['widget_close']         = 'Minimizar chat';
$string['widget_open']          = 'Abrir Asistente Académico';
$string['widget_thinking']      = 'Pensando…';
$string['widget_error_generic'] = 'Ocurrió un error. Por favor, intenta nuevamente.';
$string['widget_error_401']     = 'Tu sesión ha expirado. Por favor, recarga la página.';
$string['widget_error_429']     = 'Demasiadas solicitudes. Por favor, espera un momento.';
$string['widget_error_connect'] = 'No se pudo conectar con el asistente. Verifica tu conexión.';

// ── Web service descriptions ──────────────────────────────────────────────────
$string['ws_get_user_context']  = 'Get current user context (courses, name, role) — Read-Only.';
$string['ws_refresh_token']     = 'Issue a fresh JWT for the current session — Read-Only.';

// ── Capabilities ──────────────────────────────────────────────────────────────
$string['ia_chatbot:use']       = 'Use the IA Academic Chatbot';
$string['ia_chatbot:manage']    = 'Manage IA Chatbot plugin settings';
