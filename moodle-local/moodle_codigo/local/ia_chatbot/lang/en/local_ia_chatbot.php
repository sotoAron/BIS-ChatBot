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
$string['widget_title']         = 'Academic Assistant';
$string['widget_placeholder']   = 'Ask me anything about your courses…';
$string['widget_send']          = 'Send';
$string['widget_close']         = 'Close chat';
$string['widget_open']          = 'Open Academic Assistant';
$string['widget_thinking']      = 'Thinking…';
$string['widget_error_generic'] = 'An error occurred. Please try again.';
$string['widget_error_401']     = 'Your session has expired. Please refresh the page.';
$string['widget_error_429']     = 'Too many requests. Please wait a moment before trying again.';
$string['widget_error_connect'] = 'Cannot connect to the AI assistant. Please check your connection.';

// ── Web service descriptions ──────────────────────────────────────────────────
$string['ws_get_user_context']  = 'Get current user context (courses, name, role) — Read-Only.';
$string['ws_refresh_token']     = 'Issue a fresh JWT for the current session — Read-Only.';

// ── Capabilities ──────────────────────────────────────────────────────────────
$string['ia_chatbot:use']       = 'Use the IA Academic Chatbot';
$string['ia_chatbot:manage']    = 'Manage IA Chatbot plugin settings';
