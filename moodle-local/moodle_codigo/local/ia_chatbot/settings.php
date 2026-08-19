<?php
// This file is part of Moodle - https://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

/**
 * Plugin administration settings page for local_ia_chatbot.
 *
 * SECURITY NOTE: The JWT secret field here is a fallback for local/dev environments.
 * In production, always prefer the IA_CHATBOT_JWT_SECRET environment variable or
 * the $CFG->ia_chatbot_jwt_secret property in config.php.
 *
 * @package   local_ia_chatbot
 * @copyright 2026 BIS Faculty
 * @license   https://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

defined('MOODLE_INTERNAL') || die();

if ($hassiteconfig) {

    // ── Página de ajustes del plugin ──────────────────────────────────────────
    $settings = new admin_settingpage(
        'local_ia_chatbot',
        get_string('pluginname', 'local_ia_chatbot')
    );

    // Añadir la página al árbol de administración.
    $ADMIN->add('localplugins', $settings);

    // ── Encabezado informativo ────────────────────────────────────────────────
    $settings->add(new admin_setting_heading(
        'local_ia_chatbot/settings_heading',
        get_string('settings_heading', 'local_ia_chatbot'),
        get_string('settings_desc', 'local_ia_chatbot')
    ));

    // ─────────────────────────────────────────────────────────────────────────
    // Ajuste 1: URL del backend FastAPI
    // ─────────────────────────────────────────────────────────────────────────
    $settings->add(new admin_setting_configtext(
        'local_ia_chatbot/backend_url',
        get_string('backend_url', 'local_ia_chatbot'),
        get_string('backend_url_desc', 'local_ia_chatbot'),
        'http://localhost:8000',   // Valor por defecto.
        PARAM_URL
    ));

    // ─────────────────────────────────────────────────────────────────────────
    // Ajuste 2: Tiempo de expiración del JWT (segundos)
    // ─────────────────────────────────────────────────────────────────────────
    $settings->add(new admin_setting_configtext(
        'local_ia_chatbot/token_expiry',
        get_string('token_expiry', 'local_ia_chatbot'),
        get_string('token_expiry_desc', 'local_ia_chatbot'),
        '900',                     // Por defecto: 15 minutos.
        PARAM_INT
    ));

    // ─────────────────────────────────────────────────────────────────────────
    // Ajuste 3: Secreto JWT (fallback — NO usar en producción)
    // ─────────────────────────────────────────────────────────────────────────
    // Este campo usa admin_setting_configpasswordunmask para que el valor
    // quede enmascarado en la UI pero sea recuperable por código PHP.
    $settings->add(new admin_setting_configpasswordunmask(
        'local_ia_chatbot/jwt_secret',
        get_string('jwt_secret', 'local_ia_chatbot'),
        get_string('jwt_secret_desc', 'local_ia_chatbot'),
        ''    // Valor por defecto vacío — obliga a configurar env var en producción.
    ));
}
