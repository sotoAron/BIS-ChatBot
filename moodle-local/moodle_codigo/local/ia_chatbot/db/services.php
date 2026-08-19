<?php
// This file is part of Moodle - https://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

/**
 * Web service definitions for local_ia_chatbot.
 *
 * SEGURIDAD: Todas las funciones declaradas aquí son estrictamente
 * de solo lectura (captype = 'read'). El plugin NUNCA escribe en la
 * base de datos de Moodle a través de estos servicios.
 *
 * @package   local_ia_chatbot
 * @copyright 2026 BIS Faculty
 * @license   https://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

defined('MOODLE_INTERNAL') || die();

// Registro de funciones externas del plugin.
$functions = [
    'local_ia_chatbot_get_user_context' => [
        'classname'     => 'local_ia_chatbot_external',
        'methodname'    => 'get_user_context',
        'classpath'     => 'local/ia_chatbot/externallib.php',
        'description'   => 'Returns the current user\'s enrolled courses, full name, and role. Read-Only.',
        'type'          => 'read',           // ← Estrictamente de solo lectura.
        'ajax'          => true,             // Disponible vía AJAX desde JS.
        'loginrequired' => true,             // Requiere sesión autenticada.
        'capabilities'  => 'local/ia_chatbot:use',
    ],

    'local_ia_chatbot_refresh_token' => [
        'classname'     => 'local_ia_chatbot_external',
        'methodname'    => 'refresh_token',
        'classpath'     => 'local/ia_chatbot/externallib.php',
        'description'   => 'Issues a fresh JWT for the current authenticated session. Read-Only.',
        'type'          => 'read',
        'ajax'          => true,
        'loginrequired' => true,
        'capabilities'  => 'local/ia_chatbot:use',
    ],
];

// Servicio web agrupado (opcional, facilita la gestión desde la UI de Moodle).
$services = [
    'IA Chatbot Service' => [
        'functions'       => [
            'local_ia_chatbot_get_user_context',
            'local_ia_chatbot_refresh_token',
        ],
        'restrictedusers' => 0,   // No restringido a usuarios específicos.
        'enabled'         => 1,
        'shortname'       => 'ia_chatbot_service',
        'downloadfiles'   => 0,
        'uploadfiles'     => 0,
    ],
];
